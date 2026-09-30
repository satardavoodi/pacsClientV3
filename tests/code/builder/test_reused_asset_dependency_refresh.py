"""A fresh cache can retain verified large inputs and refresh build dependencies."""

import json
import sys

import pytest

from tools.build import prepare_distribution_assets as assets


@pytest.mark.parametrize("wheel_failure", [False, True])
def test_reused_cache_refreshes_only_build_wheels_without_mutating_donor(monkeypatch, tmp_path, wheel_failure):
    from builder import lumen_vmtk_payload, slicer_runtime_payload

    donor = tmp_path / "donor"
    donor.mkdir()
    required = ("build-environment.lock", "build-wheels-hashed.lock",
                "inno-setup/ISCC.exe", "downloads/python-3.13.5-amd64.exe",
                "offline_lumbar/manifest.json", "offline_lumbar/python/python.exe",
                "model-environment.lock", "model-wheels-hashed.lock")
    before = {}
    for name in required:
        path = donor / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old-pinned-input")
        before[name] = path.read_bytes()
    (donor / "manifest.json").write_text(json.dumps({
        "format_version": 1, "platform": "win_amd64", "model_weights_included": True,
        "wheels_cached": True, "offline_wheel_resolution_verified": True,
        "files": [{"path": name, "size": len(before[name]),
                   "sha256": assets.digest(donor / name)} for name in required],
    }), encoding="utf-8")
    before["manifest.json"] = (donor / "manifest.json").read_bytes()
    root = tmp_path / "new-assets"
    calls = []

    def snapshot(_source, destination):
        destination.mkdir()
        (destination / "AIPacsAdvancedViewer.exe").write_bytes(b"current-native")
        (destination / "aipacs-native-build.json").write_text("{}", encoding="utf-8")

    def lumen(destination):
        target = destination / "lumen_vmtk"
        target.mkdir()
        (target / "manifest.json").write_text("{}", encoding="utf-8")

    def wheels(python, requirements, destination, log, *, model=False):
        assert not model, "Reused model wheels must not be rebuilt"
        assert requirements.read_text(encoding="utf-8") == "pywin32==311\nexample==2\n"
        if wheel_failure:
            raise RuntimeError("offline dependency resolution failed")
        destination.mkdir()
        (destination / "pywin32-311-cp313-cp313-win_amd64.whl").write_bytes(b"native-wheel")
        (destination.parent / "build-wheels-hashed.lock").write_text(
            "pywin32==311 --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
        calls.append(str(python))

    monkeypatch.setattr(assets, "snapshot_runtime", snapshot)
    monkeypatch.setattr(assets, "cache_wheels", wheels)
    monkeypatch.setattr(assets.subprocess, "check_output", lambda *_a, **_k: "pywin32==311\nexample==2\n")
    monkeypatch.setattr("aipacs_runtime.advanced_mpr_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(slicer_runtime_payload, "verify_native_build_provenance", lambda *_: None)
    monkeypatch.setattr(lumen_vmtk_payload, "stage_lumen_vmtk", lumen)
    monkeypatch.setattr(sys, "argv", ["prepare_distribution_assets", "--root", str(root),
                                     "--reuse-non-slicer-assets", str(donor), "--download-wheels"])

    if wheel_failure:
        with pytest.raises(RuntimeError, match="offline dependency resolution failed"):
            assets.main()
        assert not (root / "manifest.json").exists()
    else:
        assert assets.main() == 0
        assert len(calls) == 1
        assert (root / "model-environment.lock").read_bytes() == before["model-environment.lock"]
        assert (root / "build-environment.lock").read_text(encoding="utf-8") == "pywin32==311\nexample==2\n"
        assert assets.verify(root)["wheels_cached"] is True
    assert all((donor / name).read_bytes() == data for name, data in before.items())


def test_completed_reused_cache_cannot_be_refreshed_in_place(monkeypatch, tmp_path):
    root = tmp_path / "completed"
    root.mkdir()
    (root / "manifest.json").write_bytes(b"immutable receipt")
    monkeypatch.setattr(sys, "argv", ["prepare_distribution_assets", "--root", str(root),
                                     "--reuse-non-slicer-assets", str(tmp_path / "donor"),
                                     "--download-wheels"])
    with pytest.raises(RuntimeError, match="Completed cache exists"):
        assets.main()
    assert (root / "manifest.json").read_bytes() == b"immutable receipt"
