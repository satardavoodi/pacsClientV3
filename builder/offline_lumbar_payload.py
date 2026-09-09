"""Attach the complete offline model bundle to the existing Advanced MPR package."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

from modules.ai_imaging.offline_lumbar.bundle import validate_bundle

REPO = Path(__file__).resolve().parents[1]


def bundle_source():
    configured = os.environ.get("AIPACS_OFFLINE_LUMBAR_BUNDLE_SOURCE")
    return Path(configured).resolve() if configured else REPO / "generated-files/offline-lumbar/bundle"


def stage_offline_lumbar(payload: Path, source: Path | None = None):
    source = Path(source) if source is not None else bundle_source()
    manifest = validate_bundle(source)
    destination = Path(payload) / "offline_lumbar"
    if destination.resolve() == source.resolve():
        raise ValueError("Bundle staging must not overwrite its source")
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # The model environment is immutable; application adapter code follows this checkout.
    adapter = REPO / "modules/ai_imaging/offline_lumbar"
    shutil.copytree(adapter, destination / "app/offline_lumbar", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    records = {item["path"]: item for item in manifest["files"]}
    for path in (destination / "app").rglob("*.py"):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        name = path.relative_to(destination).as_posix()
        records[name] = {"path": name, "size": path.stat().st_size, "sha256": digest}
    manifest["files"] = [records[key] for key in sorted(records)]
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    validate_bundle(destination)
    return destination
