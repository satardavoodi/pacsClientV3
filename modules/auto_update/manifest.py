"""File-level update manifest + content-addressed store (PURE stdlib).

This is the shared authority used by BOTH the build tool
(``tools/build/generate_update_manifest.py``) and the client
(``modules.auto_update.client``).  Keep it importable with zero Qt / zero
third-party dependencies so it stays unit-testable offscreen and usable from
build scripts.

Manifest paths are relative to the INSTALL ROOT (``stage/core`` maps 1:1 to
``{app}``): ``AIPacs.exe`` at the top plus the ``engine/`` subtree.  The path
guard below is a HARD clinical-safety rule: the applier may only ever write
paths accepted by :func:`is_safe_manifest_path` — nothing under ``User Data``,
nothing absolute, nothing escaping the install root.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

MANIFEST_FORMAT_VERSION = 1
DEFAULT_COMPRESSION = "gzip"
STORE_DIRNAME = "files"
_CHUNK = 1024 * 1024

ProgressCb = Callable[[int, int, str], None]  # (done_units, total_units, label)


# ── hashing ────────────────────────────────────────────────────────────────

def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ── path safety (HARD RULE — see design doc §5) ────────────────────────────

def normalize_manifest_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


# The installed {app} payload roots: AIPacs.exe (top-level file) + these
# directories. `stage/core` currently ships engine\ (frozen app) and Qss\
# (theme stylesheets, synced by build_release.sync_theme_qss). ``User Data``
# is deliberately NOT here and must never be added.
_ALLOWED_TOP_DIRS = frozenset({"engine", "qss"})


def is_safe_manifest_path(path: str) -> bool:
    """True only for paths the applier is allowed to write.

    Allowed: a bare top-level FILE name (e.g. ``AIPacs.exe``) or anything under
    an allow-listed payload root (``engine/``, ``Qss/``).  Rejected: absolute
    paths, drive letters, ``..`` components, empty components, and anything
    under any other top-level directory — which by construction excludes
    ``User Data`` and every center-state tree.
    """
    rel = normalize_manifest_path(path)
    if not rel:
        return False
    if ":" in rel:  # drive letter or ADS
        return False
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if len(parts) == 1:
        return True  # top-level file (AIPacs.exe)
    return parts[0].casefold() in _ALLOWED_TOP_DIRS


# ── manifest build / validate ──────────────────────────────────────────────

def build_manifest(
    tree_root: str | Path,
    version: str,
    *,
    app_name: str = "AIPacs",
    compression: str = DEFAULT_COMPRESSION,
    progress_cb: ProgressCb | None = None,
) -> dict[str, Any]:
    """Walk ``tree_root`` (== the installed {app} layout) and hash every file."""
    root = Path(tree_root)
    if not root.is_dir():
        raise FileNotFoundError(str(root))

    all_files = sorted(
        p for p in root.rglob("*") if p.is_file()
    )
    entries: list[dict[str, Any]] = []
    total = len(all_files)
    total_size = 0
    for index, file_path in enumerate(all_files):
        rel = normalize_manifest_path(str(file_path.relative_to(root)))
        if not is_safe_manifest_path(rel):
            raise ValueError(f"Unsafe path in payload tree: {rel!r}")
        size = file_path.stat().st_size
        entries.append(
            {
                "path": rel,
                "size": size,
                "sha256": sha256_file(file_path),
            }
        )
        total_size += size
        if progress_cb is not None:
            progress_cb(index + 1, total, rel)

    return {
        "format_version": MANIFEST_FORMAT_VERSION,
        "app_name": app_name,
        "version": str(version),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "layout": "install_root",
        "compression": compression,
        "file_count": len(entries),
        "total_size": total_size,
        "files": entries,
    }


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return a list of problems; empty list == valid."""
    problems: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest is not an object"]
    if int(manifest.get("format_version") or 0) > MANIFEST_FORMAT_VERSION:
        problems.append("manifest format_version is newer than this client")
    if not str(manifest.get("version") or "").strip():
        problems.append("manifest has no version")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        problems.append("manifest has no files")
        return problems
    for entry in files:
        if not isinstance(entry, dict):
            problems.append("file entry is not an object")
            continue
        rel = normalize_manifest_path(str(entry.get("path") or ""))
        if not is_safe_manifest_path(rel):
            problems.append(f"unsafe path: {entry.get('path')!r}")
        sha = str(entry.get("sha256") or "")
        if len(sha) != 64:
            problems.append(f"bad sha256 for {rel!r}")
    return problems


# ── local hash index (avoid re-hashing 1.4 GB on every check) ──────────────

def scan_local_tree(
    install_root: str | Path,
    manifest: dict[str, Any],
    *,
    cache_path: str | Path | None = None,
    progress_cb: ProgressCb | None = None,
) -> dict[str, str]:
    """Return {manifest_path: local_sha256_or_""} for every manifest entry.

    Missing local files map to ``""``.  A (size, mtime_ns) cache avoids
    re-hashing unchanged files across checks.
    """
    root = Path(install_root)
    cache: dict[str, Any] = {}
    if cache_path is not None:
        try:
            cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            if not isinstance(cache, dict):
                cache = {}
        except Exception:
            cache = {}

    result: dict[str, str] = {}
    files = list(manifest.get("files") or [])
    total = len(files)
    dirty = False
    for index, entry in enumerate(files):
        rel = normalize_manifest_path(str(entry.get("path") or ""))
        local = root / rel
        if not local.is_file():
            result[rel] = ""
            continue
        try:
            stat = local.stat()
        except OSError:
            result[rel] = ""
            continue
        cached = cache.get(rel)
        if (
            isinstance(cached, dict)
            and int(cached.get("size", -1)) == stat.st_size
            and int(cached.get("mtime_ns", -1)) == stat.st_mtime_ns
            and len(str(cached.get("sha256") or "")) == 64
        ):
            result[rel] = str(cached["sha256"])
        else:
            sha = sha256_file(local)
            result[rel] = sha
            cache[rel] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha}
            dirty = True
        if progress_cb is not None:
            progress_cb(index + 1, total, rel)

    if cache_path is not None and dirty:
        try:
            path = Path(cache_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache), encoding="utf-8")
        except Exception:
            pass  # cache is an optimization only — never fail the check on it
    return result


# ── diff plan ──────────────────────────────────────────────────────────────

def diff_manifest_against_local(
    manifest: dict[str, Any],
    local_hashes: dict[str, str],
) -> dict[str, Any]:
    """Files whose local hash differs (or that are missing) must be fetched.

    v1 is add/replace only — files present locally but absent from the
    manifest are REPORTED (``extra_local`` is computed by the caller if
    desired) but never deleted (design doc §5.9).
    """
    changed: list[dict[str, Any]] = []
    unchanged = 0
    changed_bytes = 0
    for entry in manifest.get("files") or []:
        rel = normalize_manifest_path(str(entry.get("path") or ""))
        target_sha = str(entry.get("sha256") or "")
        if local_hashes.get(rel, "") == target_sha:
            unchanged += 1
            continue
        changed.append(entry)
        changed_bytes += int(entry.get("size") or 0)
    return {
        "changed": changed,
        "changed_count": len(changed),
        "unchanged_count": unchanged,
        "changed_bytes": changed_bytes,
        "total_count": len(list(manifest.get("files") or [])),
    }


# ── content-addressed store ────────────────────────────────────────────────

def store_relpath(sha256: str) -> str:
    sha = str(sha256).lower()
    if len(sha) != 64:
        raise ValueError(f"bad sha256: {sha256!r}")
    return f"{sha[:2]}/{sha}.gz"


def write_store_blob(source_file: str | Path, store_root: str | Path) -> tuple[str, int, bool]:
    """Compress ``source_file`` into the store. Returns (relpath, stored_size, created).

    Idempotent: an existing blob is never rewritten (content-addressed).
    """
    sha = sha256_file(source_file)
    rel = store_relpath(sha)
    target = Path(store_root) / rel
    if target.is_file() and target.stat().st_size > 0:
        return rel, target.stat().st_size, False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".part")
    os.close(tmp_fd)
    try:
        with open(source_file, "rb") as src, open(tmp_name, "wb") as raw:
            # mtime=0 → deterministic bytes for identical content
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
                shutil.copyfileobj(src, gz, _CHUNK)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass
    return rel, target.stat().st_size, True


def extract_store_blob(
    blob_file: str | Path,
    dest_file: str | Path,
    expected_sha256: str,
) -> None:
    """Gunzip ``blob_file`` to ``dest_file`` atomically, verifying the hash."""
    dest = Path(dest_file)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
    os.close(tmp_fd)
    try:
        digest = hashlib.sha256()
        with gzip.open(blob_file, "rb") as gz, open(tmp_name, "wb") as out:
            while True:
                block = gz.read(_CHUNK)
                if not block:
                    break
                digest.update(block)
                out.write(block)
        if digest.hexdigest() != str(expected_sha256).lower():
            raise ValueError(
                f"hash mismatch extracting blob for {dest.name}: "
                f"expected {expected_sha256}, got {digest.hexdigest()}"
            )
        os.replace(tmp_name, dest)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def populate_store(
    tree_root: str | Path,
    manifest: dict[str, Any],
    store_root: str | Path,
    *,
    progress_cb: ProgressCb | None = None,
) -> dict[str, Any]:
    """Ensure every manifest file's blob exists in the store.

    Adds ``stored_size`` to each manifest entry (used for accurate download
    progress).  Returns {"added": n, "reused": n, "stored_bytes": total}.
    """
    root = Path(tree_root)
    added = reused = 0
    stored_bytes = 0
    files = list(manifest.get("files") or [])
    total = len(files)
    for index, entry in enumerate(files):
        rel = normalize_manifest_path(str(entry.get("path") or ""))
        blob_rel, stored_size, created = write_store_blob(root / rel, store_root)
        entry["stored_size"] = stored_size
        stored_bytes += stored_size
        if created:
            added += 1
        else:
            reused += 1
        if progress_cb is not None:
            progress_cb(index + 1, total, rel)
    manifest["payload_stored_size"] = stored_bytes
    return {"added": added, "reused": reused, "stored_bytes": stored_bytes}


# ── (de)serialization helpers ──────────────────────────────────────────────

def dump_manifest(manifest: dict[str, Any], path: str | Path) -> str:
    """Write the manifest JSON; returns its sha256 (for the feed).

    Written as EXACT BYTES (``write_bytes``), never ``write_text`` — Windows
    newline translation (\n → \r\n) would silently break the feed's
    ``manifest_sha256`` verification on every client (caught by
    test_dump_and_load_roundtrip_with_hash).
    """
    payload = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return sha256_bytes(payload)


def load_manifest_bytes(payload: bytes, *, expected_sha256: str = "") -> dict[str, Any]:
    if expected_sha256:
        actual = sha256_bytes(payload)
        if actual != str(expected_sha256).lower():
            raise ValueError(
                f"manifest hash mismatch: expected {expected_sha256}, got {actual}"
            )
    manifest = json.loads(payload.decode("utf-8"))
    problems = validate_manifest(manifest)
    if problems:
        raise ValueError("invalid manifest: " + "; ".join(problems[:5]))
    return manifest


def iter_unsafe_paths(paths: Iterable[str]) -> list[str]:
    return [p for p in paths if not is_safe_manifest_path(p)]
