"""Content identity for local build inputs, excluding generated and clinical state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


class BuildAuthorityError(ValueError):
    """Raised when a release backend is started outside an approved snapshot."""


def is_source_input(name: str) -> bool:
    path = Path(name)
    parts = tuple(part.lower() for part in path.parts)
    if path.is_absolute() or ".." in parts or ":" in name:
        return False
    if any(p in {"__pycache__", ".git", ".venv", ".venv_build", "user data", "user_data",
                 "logs", ".pytest_cache", "node_modules"} for p in parts):
        return False
    normalized = name.replace("\\", "/").lower()
    if path.name.lower().startswith(".env") or normalized == "builder/spec/appa_version_info.txt":
        return False
    if normalized.startswith(("builder/output/", "builder nuitka/output/", "crash-diagnostics/",
                              "generated-files/", "modules/cd_burner/lightviewer_dist/")):
        return normalized.startswith("generated-files/css/")
    if normalized.startswith("builder/plugin package/packages/"):
        # Keep the checked-in mirror boundary; runtime binaries are materialized
        # from the verified external asset inventory, never an old payload.
        return path.suffix.lower() in {".py", ".json", ".yaml", ".yml", ".md", ".txt"}
    if path.suffix.lower() in {".pyc", ".pyo", ".log", ".dcm", ".db", ".sqlite", ".sqlite3",
                               ".bak", ".pem", ".key", ".zip", ".rar", ".7z"}:
        return False
    return True


def input_paths(root: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                             "--exclude-standard"], capture_output=True, check=True)
    names = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    return [name for name in names if is_source_input(name) and (root / name).is_file()]


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_fingerprint(root: Path) -> str:
    entries = [(name, file_hash(root / name)) for name in input_paths(root)
               if name != "build_source_manifest.json"
               and not name.startswith("builder/plugin package/packages/")]
    return hashlib.sha256(json.dumps(entries, ensure_ascii=True).encode("utf-8")).hexdigest()


def validate_build_authority(root: Path, version: str, *, internal: bool = False) -> dict:
    """Validate the immutable provenance contract for a build-capable backend.

    Official builds must come from the canonical coordinator's receipt-backed
    snapshot. Internal diagnostics must come from its explicitly prepared,
    non-promotable snapshot. This prevents direct backend invocation in a
    mutable developer checkout from silently creating release-looking output.
    """
    manifest_path = root / "build_source_manifest.json"
    if not manifest_path.is_file():
        raise BuildAuthorityError(
            "Build authority manifest is missing. Start at BUILD.md and use "
            "tools/build/build_local_candidate.py; do not run a release backend "
            "directly from the developer checkout."
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildAuthorityError("Build authority manifest is unreadable or invalid") from exc

    if manifest.get("version") != version:
        raise BuildAuthorityError("Build authority version does not match the source version")
    if manifest.get("source_sha256") != source_fingerprint(root):
        raise BuildAuthorityError("Build snapshot source changed after provenance was recorded")
    if not manifest.get("developer_run_accepted"):
        raise BuildAuthorityError("Build snapshot has no recorded Developer Run acceptance")
    if manifest.get("production_accepted"):
        raise BuildAuthorityError("Build input manifest must not pre-claim production acceptance")

    if internal:
        if manifest.get("github_freshness_verified") or manifest.get("source_published"):
            raise BuildAuthorityError(
                "--internal-build is only valid for an explicitly non-promotable internal snapshot"
            )
        return manifest

    sync = manifest.get("release_sync")
    if not manifest.get("github_freshness_verified") or not manifest.get("source_published"):
        raise BuildAuthorityError("Official builds require verified Git publication freshness")
    if not isinstance(sync, dict):
        raise BuildAuthorityError("Official build snapshot has no Git synchronization receipt")
    if sync.get("version") != version:
        raise BuildAuthorityError("Git synchronization receipt version does not match the build")
    if sync.get("commit") != manifest.get("source_head"):
        raise BuildAuthorityError("Git synchronization receipt does not identify this source commit")
    return manifest
