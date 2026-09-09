"""Portable bundle integrity contract shared by preparation, packaging, and inference."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

MODEL_DIRECTORY = "Dataset756_mri_vertebrae_1076subj"
BUNDLE_ID = "vertebrae-mr-cpu-2.14.0"


class BundleError(RuntimeError):
    """The offline payload is absent, incomplete, unsupported, or corrupt."""


def validate_bundle(root: Path, *, verify_hashes: bool = True, bootstrap_only: bool = False) -> dict:
    """Validate all metadata; optionally read only interpreter/adapter bootstrap files.

    The standalone worker always performs full validation before importing the
    model. Bootstrap mode avoids thousands of GIL-releasing filesystem calls in
    Slicer's PythonQt interpreter while still checking what launches that worker.
    """
    root = Path(root).resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BundleError("Offline lumbar bundle is missing or unreadable; reinstall Advanced Analysis") from exc
    expected = {"format_version": 1, "bundle_id": BUNDLE_ID, "task": "vertebrae_mr",
                "engine_version": "2.14.0", "python_version": "3.12.10",
                "platform": "win_amd64", "device": "cpu", "network_required": False}
    if not isinstance(manifest, dict) or any(
        type(manifest.get(k)) is not type(v) or manifest.get(k) != v for k, v in expected.items()
    ):
        raise BundleError("Unsupported offline lumbar bundle")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > 100000:
        raise BundleError("Invalid bundle file inventory")
    paths = set()
    for item in files:
        if not isinstance(item, dict):
            raise BundleError("Invalid bundle file record")
        name, size, digest = item.get("path"), item.get("size"), item.get("sha256")
        if not isinstance(name, str):
            raise BundleError("Invalid bundle path")
        relative = PurePosixPath(name)
        if (relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name
                or not name or name.casefold() in paths or relative.as_posix() != name):
            raise BundleError("Unsafe or duplicate bundle path")
        if type(size) is not int or size < 0 or not isinstance(digest, str) or len(digest) != 64:
            raise BundleError("Invalid bundle integrity metadata")
        paths.add(name.casefold())
        if bootstrap_only and not (name.startswith("app/") or
                                   (name.startswith("python/") and len(relative.parts) == 2)):
            continue
        path = root / name
        if not path.resolve().is_relative_to(root) or not path.is_file() or path.stat().st_size != size:
            raise BundleError("Offline lumbar bundle file is missing or changed")
        if verify_hashes:
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != digest:
                raise BundleError("Offline lumbar bundle hash mismatch")
    required = {"python/python.exe", "python/python312._pth", "app/offline_lumbar/worker.py",
                "app/offline_lumbar/bundle.py", "app/offline_lumbar/service.py",
                "requirements-resolved.txt", "licenses/model-notice.txt"}
    if not required.issubset(paths):
        raise BundleError("Offline lumbar executable, adapter, or notices are incomplete")
    model_files = [name for name in paths if name.startswith("weights/" + MODEL_DIRECTORY.lower() + "/")]
    for suffix in ("/fold_0/checkpoint_final.pth", "/plans.json", "/dataset.json"):
        if not any(name.endswith(suffix) for name in model_files):
            raise BundleError("Offline lumbar model weights or metadata are incomplete")
    return manifest
