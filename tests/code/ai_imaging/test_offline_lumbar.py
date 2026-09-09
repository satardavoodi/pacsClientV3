"""Behavioral guards for the local bundle boundary; no patient data or AI downloads."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import numpy as np
import pytest

from modules.ai_imaging.offline_lumbar.bundle import BundleError, validate_bundle
from modules.ai_imaging.offline_lumbar import service


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "bundle"
    names = [
        "python/python.exe", "python/python312._pth", "app/offline_lumbar/worker.py",
        "app/offline_lumbar/bundle.py", "app/offline_lumbar/service.py", "requirements-resolved.txt",
        "licenses/MODEL-NOTICE.txt",
        "weights/Dataset756_mri_vertebrae_1076subj/trainer/fold_0/checkpoint_final.pth",
        "weights/Dataset756_mri_vertebrae_1076subj/trainer/plans.json",
        "weights/Dataset756_mri_vertebrae_1076subj/trainer/dataset.json",
    ]
    files = []
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = b"synthetic test fixture"
        path.write_bytes(data)
        files.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"format_version": 1, "bundle_id": "vertebrae-mr-cpu-2.14.0",
                "task": "vertebrae_mr", "engine_version": "2.14.0", "python_version": "3.12.10",
                "platform": "win_amd64", "device": "cpu", "network_required": False, "files": files}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


def test_valid_inventory_and_same_size_corruption(bundle):
    assert validate_bundle(bundle)["task"] == "vertebrae_mr"
    path = bundle / "python/python.exe"
    path.write_bytes(b"x" * path.stat().st_size)
    with pytest.raises(BundleError, match="hash"):
        validate_bundle(bundle)


def test_bootstrap_defers_model_hashing_but_full_worker_validation_rejects_corruption(bundle):
    weight = next((bundle / "weights").rglob("*.pth"))
    weight.write_bytes(b"x" * weight.stat().st_size)
    assert validate_bundle(bundle, bootstrap_only=True)["task"] == "vertebrae_mr"
    with pytest.raises(BundleError, match="hash"):
        validate_bundle(bundle)
    (bundle / "app/offline_lumbar/worker.py").write_bytes(b"corrupt")
    with pytest.raises(BundleError):
        validate_bundle(bundle, bootstrap_only=True)


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/escape", "python/../escape",
                                      "python\\escape", "python//escape"])
def test_manifest_rejects_unsafe_paths(bundle, path):
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["files"][0]["path"] = path
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(BundleError):
        validate_bundle(bundle)


@pytest.mark.parametrize("key,value", [("network_required", True), ("task", "total"),
                                        ("device", "gpu"), ("format_version", True)])
def test_unsupported_bundle_is_not_silently_substituted(bundle, key, value):
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest[key] = value
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(BundleError):
        validate_bundle(bundle)


def test_weights_missing_even_if_manifest_is_rewritten(bundle):
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["files"] = [f for f in manifest["files"] if not f["path"].endswith(".pth")]
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(BundleError, match="weights"):
        validate_bundle(bundle)


def test_network_guard_blocks_dns_in_own_process():
    worker = Path(service.__file__).with_name("worker.py")
    code = ("import runpy,socket;runpy.run_path(" + repr(str(worker)) + ");"
            "socket.getaddrinfo('example.com',443)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Network access is disabled" in result.stderr


def test_cancel_stops_owned_process_and_removes_raw_input(bundle, tmp_path, monkeypatch):
    cancel = threading.Event()
    cancel.set()
    stopped = []

    class Process:
        pid = 321
        def poll(self):
            return None if not stopped else 1
        def wait(self, timeout):
            return 1
        def terminate(self):
            stopped.append("terminated")

    monkeypatch.setattr(service.subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(service.subprocess, "run", lambda cmd, **kw: stopped.append(cmd))
    with pytest.raises(service.AnalysisCancelled):
        service.run_snapshot(bundle, tmp_path / "jobs", np.ones((4, 5, 6)), np.eye(4), cancel=cancel)
    assert stopped
    assert not list((tmp_path / "jobs").rglob("input.npy"))


def test_missing_bundle_never_starts_a_downloader(tmp_path, monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail("No process may start for a missing bundle")
    monkeypatch.setattr(service.subprocess, "Popen", forbidden)
    with pytest.raises(BundleError):
        service.run_snapshot(tmp_path / "absent", tmp_path / "jobs", np.zeros((4, 4, 4)), np.eye(4))
    assert not (tmp_path / "jobs").exists()


def test_process_start_failure_removes_raw_input(bundle, tmp_path, monkeypatch):
    def cannot_start(*args, **kwargs):
        raise OSError("Synthetic executable failure")
    monkeypatch.setattr(service.subprocess, "Popen", cannot_start)
    with pytest.raises(OSError, match="Synthetic"):
        service.run_snapshot(bundle, tmp_path / "jobs", np.ones((4, 5, 6)), np.eye(4))
    assert not list((tmp_path / "jobs").rglob("input.npy"))
