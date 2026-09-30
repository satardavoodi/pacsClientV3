"""Stage a minimal VMTK geometry bundle built against the custom Slicer SDK."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

PIN = "d8f45c1b8c276e1aaf5e19a7ae16320b5df6b03b"


def prepare(install, source, output):
    if output.exists():
        raise FileExistsError("Use a fresh bundle destination")
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != PIN:
        raise ValueError("Unexpected VMTK source revision")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip():
        raise ValueError("VMTK source must be clean")
    inputs = {"LICENSE": source / "LICENSE"}
    for kit in ("Common", "ComputationalGeometry"):
        inputs[f"bin/vtkvmtk{kit}.dll"] = install / f"bin/vtkvmtk{kit}.dll"
        inputs[f"python/vmtk/vtkvmtk{kit}Python.pyd"] = install / f"lib/python3.12/site-packages/vmtk/vtkvmtk{kit}Python.pyd"
    for path in inputs.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    for name, path in inputs.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    (output / "python/vmtk/__init__.py").write_text('"""Minimal VMTK geometry bindings; see bundled LICENSE."""\n', encoding="utf-8")
    files = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(output.rglob("*")) if p.is_file()}
    manifest = {"schema": 1, "source": "https://github.com/vmtk/vmtk", "revision": PIN,
                "python": "3.12", "vtk": "9.5.2", "platform": "win-amd64",
                "tetgen": False, "files": files}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.install, args.source, args.output), indent=2))
