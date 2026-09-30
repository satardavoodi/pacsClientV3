"""Verified shared VMTK payload for both Advanced Analysis workflows."""
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PIN = "d8f45c1b8c276e1aaf5e19a7ae16320b5df6b03b"


def verify_bundle(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema"), manifest.get("revision"), manifest.get("python"),
            manifest.get("vtk"), manifest.get("platform"), manifest.get("tetgen")) != (
            1, PIN, "3.12", "9.5.2", "win-amd64", False):
        raise ValueError("VMTK bundle identity is incompatible")
    required = {"LICENSE", "python/vmtk/__init__.py"}
    for kit in ("Common", "ComputationalGeometry"):
        required.update({f"bin/vtkvmtk{kit}.dll", f"python/vmtk/vtkvmtk{kit}Python.pyd"})
    if set(manifest["files"]) != required:
        raise ValueError("VMTK bundle inventory is incomplete or unexpected")
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("VMTK bundle file is missing")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("VMTK bundle hash mismatch")
    return manifest


def stage_lumen_vmtk(payload, source=None):
    source = Path(source or os.environ.get("AIPACS_LUMEN_VMTK_BUNDLE_SOURCE")
                  or ROOT / "generated-files/lumen-vmtk/bundle").resolve()
    verify_bundle(source)
    target = (Path(payload) / "lumen_vmtk").resolve()
    if target == source or target.is_relative_to(source):
        raise ValueError("VMTK staging destination must be separate from its source")
    shutil.copytree(source, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    verify_bundle(target)
    return target
