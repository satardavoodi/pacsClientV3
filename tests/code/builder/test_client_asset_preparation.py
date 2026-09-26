"""Client build inputs must not stage Eagle Eye server model assets."""

from __future__ import annotations

import io
import json
import sys

import pytest

from tools.build import prepare_distribution_assets as assets


def test_canonical_coordinator_defaults_to_final_native_slicer_cache():
    from tools.build import build_local_candidate

    assert build_local_candidate.DEFAULT_ASSET_ROOT == assets.DEFAULT_ROOT
    assert assets.DEFAULT_ROOT.name == "distribution-assets-native-3.6.7-vc143-20260923"


def test_historical_slicer_downloader_cannot_replace_canonical_runtime(monkeypatch, tmp_path):
    from tools.slicer import download_slicer_runtime

    runtime = tmp_path / "canonical-runtime"
    runtime.mkdir()
    marker = runtime / "aipacs-native-build.json"
    marker.write_text("current", encoding="utf-8")
    monkeypatch.setattr(download_slicer_runtime, "TARGET_DIR", runtime)
    monkeypatch.setattr(download_slicer_runtime, "_download", lambda *_: (_ for _ in ()).throw(RuntimeError("download attempted")))
    monkeypatch.setattr(sys, "argv", ["download_slicer_runtime", "--force", "--url", "https://example.invalid/old.zip"])

    with pytest.raises(SystemExit):
        download_slicer_runtime.main()
    assert marker.read_text(encoding="utf-8") == "current"


def test_client_asset_preparation_omits_offline_server_model(monkeypatch, tmp_path):
    from builder import build_release, offline_lumbar_payload, slicer_runtime_payload

    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "client-assets"
    compiler = tmp_path / "compiler" / "ISCC.exe"
    compiler.parent.mkdir()
    compiler.write_bytes(b"compiler")

    def fake_snapshot(_source, destination):
        destination.mkdir(parents=True)
        (destination / "AIPacsAdvancedViewer.exe").write_bytes(b"viewer")
        (destination / "aipacs-native-build.json").write_text("{}", encoding="utf-8")

    def forbid_server_model(*_args, **_kwargs):
        raise AssertionError("Client assets must not stage the Eagle Eye model")

    monkeypatch.setattr(assets, "REPO", repo)
    monkeypatch.setattr(assets, "snapshot_runtime", fake_snapshot)
    monkeypatch.setattr("aipacs_runtime.advanced_mpr_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(slicer_runtime_payload, "verify_native_build_provenance", lambda *_: None)
    monkeypatch.setattr(offline_lumbar_payload, "stage_offline_lumbar", forbid_server_model)
    monkeypatch.setattr(build_release, "find_iscc", lambda: compiler)
    monkeypatch.setattr(assets.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(b"python"))
    monkeypatch.setattr(assets.subprocess, "check_output", lambda *_args, **_kwargs: "example==1\n")
    monkeypatch.setattr(sys, "argv", ["prepare_distribution_assets", "--root", str(root), "--profile", "client"])

    assert assets.main() == 0
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_weights_included"] is False
    assert not (root / "offline_lumbar").exists()
    assert not (root / "model-environment.lock").exists()
    assert assets.verify(root, profile="client")
    monkeypatch.setattr(sys, "argv", ["prepare_distribution_assets", "--root", str(root), "--profile", "client", "--check"])
    assert assets.main() == 0


def test_reuse_non_slicer_assets_rejects_tampered_donor(tmp_path):
    donor = tmp_path / "donor"
    donor.mkdir()
    (donor / "build-environment.lock").write_bytes(b"original")
    (donor / "manifest.json").write_text(json.dumps({
        "format_version": 1, "platform": "win_amd64", "model_weights_included": True,
        "files": [{"path": "build-environment.lock", "size": 8,
                   "sha256": assets.digest(donor / "build-environment.lock")}],
    }), encoding="utf-8")
    (donor / "build-environment.lock").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="hash mismatch"):
        assets.reuse_non_slicer_assets(donor, tmp_path / "new")
    assert not (tmp_path / "new" / "build-environment.lock").exists()


def test_reuse_non_slicer_assets_uses_inventory_and_omits_old_runtime(tmp_path):
    donor = tmp_path / "donor"
    donor.mkdir()
    required = ("build-environment.lock", "inno-setup/ISCC.exe",
                "downloads/python-3.13.5-amd64.exe", "offline_lumbar/manifest.json",
                "offline_lumbar/python/python.exe")
    for name in required:
        path = donor / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"pinned")
    (donor / "slicer-runtime").mkdir()
    (donor / "slicer-runtime" / "AIPacsAdvancedViewer.exe").write_bytes(b"old")
    (donor / "untracked.txt").write_bytes(b"not an asset")
    files = []
    for name in (*required, "slicer-runtime/AIPacsAdvancedViewer.exe"):
        path = donor / name
        files.append({"path": name, "size": path.stat().st_size, "sha256": assets.digest(path)})
    (donor / "manifest.json").write_text(json.dumps({
        "format_version": 1, "platform": "win_amd64", "model_weights_included": True,
        "wheels_cached": True, "offline_wheel_resolution_verified": True, "files": files,
    }), encoding="utf-8")

    metadata = assets.reuse_non_slicer_assets(donor, tmp_path / "new")

    assert metadata["wheels_cached"] is True
    assert (tmp_path / "new" / "build-environment.lock").read_bytes() == b"pinned"
    assert not (tmp_path / "new" / "slicer-runtime").exists()
    assert not (tmp_path / "new" / "untracked.txt").exists()
