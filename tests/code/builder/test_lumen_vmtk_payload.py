"""The two workspaces ship with the same verified native geometry bundle."""
import hashlib
import json
from pathlib import Path

import pytest
from builder.lumen_vmtk_payload import PIN, verify_bundle, stage_lumen_vmtk


def bundle(root):
    files = ["LICENSE", "python/vmtk/__init__.py"]
    for kit in ("Common", "ComputationalGeometry"):
        files.extend([f"bin/vtkvmtk{kit}.dll", f"python/vmtk/vtkvmtk{kit}Python.pyd"])
    hashes = {}
    for name in files:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic native bundle fixture")
        hashes[name] = hashlib.sha256(file.read_bytes()).hexdigest()
    metadata = {"schema": 1, "revision": PIN, "python": "3.12", "vtk": "9.5.2",
                "platform": "win-amd64", "tetgen": False, "files": hashes}
    (root / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
    return root


def test_stage_preserves_bundle_and_license(tmp_path):
    source = bundle(tmp_path / "source")
    target = stage_lumen_vmtk(tmp_path / "payload", source)
    assert verify_bundle(target) == verify_bundle(source)
    assert (target / "LICENSE").read_bytes() == (source / "LICENSE").read_bytes()


def test_wrong_abi_and_damaged_bundle_fail_closed(tmp_path):
    source = bundle(tmp_path / "source")
    metadata = verify_bundle(source)
    metadata["vtk"] = "9.6.1"
    (source / "manifest.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="incompatible"):
        verify_bundle(source)
    metadata["vtk"] = "9.5.2"
    (source / "manifest.json").write_text(json.dumps(metadata))
    (source / "bin/vtkvmtkCommon.dll").write_bytes(b"damaged")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_bundle(source)


def test_staging_uses_snapshot_asset_override_and_excludes_bytecode(tmp_path, monkeypatch):
    source = bundle(tmp_path / "assets/lumen_vmtk")
    cache = source / "python/vmtk/__pycache__"
    cache.mkdir()
    (cache / "test.pyc").write_bytes(b"local cache")
    monkeypatch.setenv("AIPACS_LUMEN_VMTK_BUNDLE_SOURCE", str(source))
    target = stage_lumen_vmtk(tmp_path / "payload")
    assert verify_bundle(target) == verify_bundle(source)
    assert not (target / "python/vmtk/__pycache__").exists()
    with pytest.raises(ValueError, match="separate"):
        stage_lumen_vmtk(source.parent)


def test_both_packagers_stage_shared_engine():
    root = Path(__file__).resolve().parents[3]
    for path in ("builder/build_release.py", "builder/materialize_plugin_packages.py"):
        source = (root / path).read_text(encoding="utf-8")
        assert "stage_lumen_vmtk(package_dir / MODULE_PACKAGE_PAYLOAD_DIRNAME)" in source
    definition = json.loads((root / "builder/plugin package/definitions/advanced_mpr/plugin_package.json").read_text())
    assert "modules/mpr/advanced_3d_slicer" in definition["source_paths"]
    assert {"patient.vascular_analysis", "patient.virtual_bronchoscopy"} <= set(definition["integration_points"])
