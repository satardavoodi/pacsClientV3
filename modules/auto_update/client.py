"""Client-side update check / plan / download (PURE stdlib + aipacs_runtime).

No Qt in this module — the Qt layer (``service``/``ui``) drives it from worker
threads via plain callbacks.  Network I/O is urllib (matching the existing
updater code in ``aipacs_runtime``); every downloaded artifact is verified by
SHA-256 before it is accepted.  ``type: "file"`` update sources resolve to
plain filesystem paths, which keeps the whole flow testable offline.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit

import aipacs_runtime
from aipacs_runtime import (
    CORE_COMPONENT_ID,
    compare_release_versions,
    current_app_version,
    load_update_sources,
    resolve_update_artifact_source,
    summarize_available_updates,
    updates_cache_root,
)

from . import manifest as manifest_mod

logger = logging.getLogger(__name__)

_DOWNLOAD_CHUNK = 256 * 1024
_DOWNLOAD_RETRIES = 3
_DOWNLOAD_TIMEOUT_S = 60

# Prefer the full installer when the delta would fetch more than this fraction
# of the (known) installer size — at that point the delta has no advantage.
_INSTALLER_FALLBACK_RATIO = 0.60

# progress callback: (files_done, files_total, bytes_done, bytes_total, label)
DownloadProgressCb = Callable[[int, int, int, int, str], None]
CancelCheck = Callable[[], bool]


class UpdateCheckError(RuntimeError):
    """No source could be reached / no usable feed."""


# ── source failover ────────────────────────────────────────────────────────

def iter_source_locations() -> list[dict[str, Any]]:
    """Configured sources, active one first, blanks skipped (mirror failover)."""
    payload = load_update_sources()
    sources = [s for s in (payload.get("sources") or []) if isinstance(s, dict)]
    active_id = str(payload.get("active_source_id") or "")
    ordered = sorted(
        sources,
        key=lambda s: 0 if str(s.get("id") or "") == active_id else 1,
    )
    return [s for s in ordered if str(s.get("location") or "").strip()]


def check_for_core_update() -> dict[str, Any] | None:
    """Try every configured source in order; return the first usable summary.

    Returns ``None`` when no source is configured or the core is up to date.
    Raises :class:`UpdateCheckError` only when sources are configured but ALL
    of them failed (so a manual check can show a real error while the silent
    startup check just logs).
    """
    sources = iter_source_locations()
    if not sources:
        logger.info("auto-update: no update source configured — check skipped")
        return None

    errors: list[str] = []
    for source in sources:
        location = str(source.get("location") or "").strip()
        try:
            summary = summarize_available_updates(location)
        except Exception as exc:  # noqa: BLE001 — per-source failover
            errors.append(f"{source.get('id')}: {exc}")
            logger.warning("auto-update: source %r failed: %s", source.get("id"), exc)
            continue
        core = dict(summary.get("core") or {})
        summary["source_config"] = source
        if core.get("status") == "update_available":
            logger.info(
                "auto-update: update available %s -> %s (source=%s)",
                core.get("current_version"),
                core.get("available_version"),
                source.get("id"),
            )
            return summary
        logger.info(
            "auto-update: up to date (current=%s, feed=%s, source=%s)",
            core.get("current_version"),
            core.get("available_version"),
            source.get("id"),
        )
        return None

    raise UpdateCheckError("; ".join(errors) or "no usable update source")


# ── fetch helpers (http(s) OR local path) ──────────────────────────────────

def _encode_url(url: str) -> str:
    """Percent-encode the URL path (spaces in installer names, etc.).

    urllib does NOT encode for us — an unencoded space in
    ``core/ai-pacs installer v3.5.4.exe`` is rejected by real web servers.
    ``%`` stays safe so an already-encoded URL is never double-encoded.
    """
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme, parts.netloc, quote(parts.path, safe="/%:@"), parts.query, parts.fragment)
    )


def _fetch_bytes(resolved_source: str, *, timeout: int = 30) -> bytes:
    if resolved_source.startswith(("http://", "https://")):
        with urllib.request.urlopen(_encode_url(resolved_source), timeout=timeout) as response:
            return response.read()
    return Path(resolved_source).read_bytes()


def _fetch_to_file(
    resolved_source: str,
    target: Path,
    *,
    progress: Callable[[int], None] | None = None,
    cancel_check: CancelCheck | None = None,
) -> None:
    """Chunked download (or local copy) → ``target`` via a ``.part`` temp."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        if resolved_source.startswith(("http://", "https://")):
            request = urllib.request.Request(
                _encode_url(resolved_source), headers={"User-Agent": "AIPacs-Updater"}
            )
            with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT_S) as response:
                with open(tmp, "wb") as handle:
                    while True:
                        if cancel_check is not None and cancel_check():
                            raise InterruptedError("update download cancelled")
                        block = response.read(_DOWNLOAD_CHUNK)
                        if not block:
                            break
                        handle.write(block)
                        if progress is not None:
                            progress(len(block))
        else:
            source_path = Path(resolved_source)
            size = source_path.stat().st_size
            shutil.copyfile(source_path, tmp)
            if progress is not None:
                progress(size)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ── manifest fetch + plan ──────────────────────────────────────────────────

def fetch_core_manifest(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Download + verify the delta manifest referenced by the feed, or None."""
    core = dict(summary.get("core") or {})
    delta = core.get("delta")
    if not isinstance(delta, dict):
        return None
    manifest_path = str(delta.get("manifest_path") or "").strip()
    if not manifest_path:
        return None
    context = dict(summary.get("source") or {})
    resolved = resolve_update_artifact_source(manifest_path, context=context)
    payload = _fetch_bytes(resolved)
    manifest = manifest_mod.load_manifest_bytes(
        payload, expected_sha256=str(delta.get("manifest_sha256") or "")
    )
    feed_version = str(core.get("available_version") or "")
    if feed_version and str(manifest.get("version")) != feed_version:
        raise ValueError(
            f"manifest version {manifest.get('version')!r} does not match "
            f"feed version {feed_version!r}"
        )
    return manifest


def local_index_cache_path() -> Path:
    return updates_cache_root() / "local_index.json"


def install_root_path() -> Path:
    return aipacs_runtime.install_root()


def build_update_plan(
    manifest: dict[str, Any],
    *,
    install_root: str | Path | None = None,
    cache_path: str | Path | None = None,
    progress_cb: manifest_mod.ProgressCb | None = None,
) -> dict[str, Any]:
    root = Path(install_root) if install_root is not None else install_root_path()
    cache = cache_path if cache_path is not None else local_index_cache_path()
    local_hashes = manifest_mod.scan_local_tree(
        root, manifest, cache_path=cache, progress_cb=progress_cb
    )
    plan = manifest_mod.diff_manifest_against_local(manifest, local_hashes)
    plan["version"] = str(manifest.get("version") or "")
    plan["install_root"] = str(root)
    plan["stored_bytes"] = sum(
        int(entry.get("stored_size") or entry.get("size") or 0)
        for entry in plan["changed"]
    )
    return plan


def installer_fallback_recommended(plan: dict[str, Any], summary: dict[str, Any]) -> bool:
    """Prefer the full installer when the delta carries no real advantage."""
    if os.getenv("AIPACS_UPDATE_INSTALLER_FALLBACK", "1") == "0":
        return False
    core = dict(summary.get("core") or {})
    installer_size = int(core.get("size") or 0)
    if installer_size <= 0 or not str(core.get("artifact_path") or "").strip():
        return False
    return int(plan.get("stored_bytes") or 0) >= installer_size * _INSTALLER_FALLBACK_RATIO


# ── delta download → staging ───────────────────────────────────────────────

def staging_root_for(version: str) -> Path:
    return updates_cache_root() / "staging" / str(version)


def download_plan_files(
    plan: dict[str, Any],
    summary: dict[str, Any],
    *,
    staging_root: str | Path | None = None,
    progress_cb: DownloadProgressCb | None = None,
    cancel_check: CancelCheck | None = None,
) -> Path:
    """Fetch every changed file into a staging mirror of the install layout.

    Already-staged files with the right hash are skipped (resume).  Every file
    is hash-verified after gunzip; a mismatch aborts the whole download with
    the install tree untouched.
    """
    core = dict(summary.get("core") or {})
    delta = dict(core.get("delta") or {})
    context = dict(summary.get("source") or {})
    files_base = str(delta.get("files_base") or "files/").strip()
    if files_base and not files_base.endswith("/"):
        files_base += "/"

    version = str(plan.get("version") or "")
    staging = Path(staging_root) if staging_root is not None else staging_root_for(version)
    staging.mkdir(parents=True, exist_ok=True)

    changed = list(plan.get("changed") or [])
    total_files = len(changed)
    total_bytes = int(plan.get("stored_bytes") or 0)
    done_bytes = 0

    for index, entry in enumerate(changed):
        if cancel_check is not None and cancel_check():
            raise InterruptedError("update download cancelled")
        rel = manifest_mod.normalize_manifest_path(str(entry.get("path") or ""))
        if not manifest_mod.is_safe_manifest_path(rel):
            raise ValueError(f"unsafe path in update plan: {rel!r}")
        sha = str(entry.get("sha256") or "")
        target = staging / rel

        # resume: already staged + verified → skip
        if target.is_file() and manifest_mod.sha256_file(target) == sha:
            done_bytes += int(entry.get("stored_size") or entry.get("size") or 0)
            if progress_cb is not None:
                progress_cb(index + 1, total_files, done_bytes, total_bytes, rel)
            continue

        blob_rel = files_base + manifest_mod.store_relpath(sha)
        resolved = resolve_update_artifact_source(blob_rel, context=context)

        last_error: Exception | None = None
        for attempt in range(1, _DOWNLOAD_RETRIES + 1):
            bytes_before = done_bytes
            try:
                with tempfile.TemporaryDirectory(dir=str(staging)) as tmp_dir:
                    blob_tmp = Path(tmp_dir) / "blob.gz"

                    def _tick(n: int) -> None:
                        nonlocal done_bytes
                        done_bytes += n
                        if progress_cb is not None:
                            progress_cb(index, total_files, done_bytes, total_bytes, rel)

                    _fetch_to_file(
                        resolved, blob_tmp, progress=_tick, cancel_check=cancel_check
                    )
                    manifest_mod.extract_store_blob(blob_tmp, target, sha)
                last_error = None
                break
            except InterruptedError:
                raise
            except Exception as exc:  # noqa: BLE001 — retried, then surfaced
                last_error = exc
                done_bytes = bytes_before
                logger.warning(
                    "auto-update: download attempt %d/%d failed for %s: %s",
                    attempt, _DOWNLOAD_RETRIES, rel, exc,
                )
                time.sleep(min(2.0 * attempt, 5.0))
        if last_error is not None:
            raise UpdateCheckError(f"failed to download {rel}: {last_error}") from last_error

        if progress_cb is not None:
            progress_cb(index + 1, total_files, done_bytes, total_bytes, rel)

    # persist the plan next to the staged files for the applier
    plan_snapshot = {
        "version": version,
        "from_version": current_app_version(),
        "generated_at_utc": plan.get("generated_at_utc") or "",
        "files": [
            manifest_mod.normalize_manifest_path(str(entry.get("path") or ""))
            for entry in changed
        ],
    }
    (staging / "staged_plan.json").write_text(
        json.dumps(plan_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return staging


__all__ = [
    "CORE_COMPONENT_ID",
    "UpdateCheckError",
    "check_for_core_update",
    "iter_source_locations",
    "fetch_core_manifest",
    "build_update_plan",
    "installer_fallback_recommended",
    "download_plan_files",
    "staging_root_for",
    "local_index_cache_path",
    "install_root_path",
    "compare_release_versions",
]
