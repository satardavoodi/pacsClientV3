"""
Attachment Pending-Sync Manifest
=================================
Tracks which locally-saved attachment files have not yet been uploaded to the server.

Layout
------
ATTACHMENT_PATH / <study_uid> / .pending_sync.json

  {
    "version": 1,
    "pending": {
      "REC_20260506_123456.wav": {
        "saved_at": "2026-05-06T12:00:00",
        "last_attempt": null,
        "attempts": 0
      }
    }
  }

All public functions are thread-safe (use an in-process file lock).
Writes are atomic (tmp-file + rename).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MANIFEST_FILENAME = ".pending_sync.json"
_MANIFEST_VERSION = 1

# Per-study in-process lock to avoid concurrent manifest writes
_study_locks: Dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()


def _get_study_lock(study_uid: str) -> threading.Lock:
    with _locks_meta:
        if study_uid not in _study_locks:
            _study_locks[study_uid] = threading.Lock()
        return _study_locks[study_uid]


def _manifest_path(study_uid: str) -> Path:
    from PacsClient.utils.config import ATTACHMENT_PATH
    return ATTACHMENT_PATH / study_uid / _MANIFEST_FILENAME


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": _MANIFEST_VERSION, "pending": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("pending"), dict):
            data["pending"] = {}
        return data
    except Exception as e:
        logger.warning(f"[PENDING_SYNC] Could not read manifest {path}: {e} — resetting")
        return {"version": _MANIFEST_VERSION, "pending": {}}


def _save_manifest(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to tmp file then rename
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".psync_tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
    except Exception as e:
        logger.warning(f"[PENDING_SYNC] Could not save manifest {path}: {e}")


# ─────────────────────────────────────────
# Public API
# ─────────────────────────────────────────

def mark_pending(study_uid: str, filename: str) -> None:
    """
    Register *filename* as a locally-saved attachment that has not been
    uploaded to the server yet.  Idempotent — calling it multiple times for
    the same file only resets the 'saved_at' timestamp on the first call.
    """
    if not study_uid or not filename:
        return
    lock = _get_study_lock(study_uid)
    with lock:
        path = _manifest_path(study_uid)
        data = _load_manifest(path)
        if filename not in data["pending"]:
            data["pending"][filename] = {
                "saved_at": datetime.now().isoformat(),
                "last_attempt": None,
                "attempts": 0,
            }
            _save_manifest(path, data)
            logger.debug(f"[PENDING_SYNC] marked pending: study={study_uid} file={filename}")


def mark_synced(study_uid: str, filename: str) -> None:
    """
    Remove *filename* from the pending manifest (upload succeeded).
    Idempotent — safe to call even if the file was not in the manifest.
    """
    if not study_uid or not filename:
        return
    lock = _get_study_lock(study_uid)
    with lock:
        path = _manifest_path(study_uid)
        data = _load_manifest(path)
        if filename in data["pending"]:
            del data["pending"][filename]
            _save_manifest(path, data)
            logger.debug(f"[PENDING_SYNC] marked synced: study={study_uid} file={filename}")


def record_attempt(study_uid: str, filename: str) -> None:
    """
    Increment the attempt counter and update last_attempt timestamp for
    *filename*.  Called when an upload attempt is made (even if it fails).
    """
    if not study_uid or not filename:
        return
    lock = _get_study_lock(study_uid)
    with lock:
        path = _manifest_path(study_uid)
        data = _load_manifest(path)
        entry = data["pending"].get(filename)
        if entry is not None:
            entry["attempts"] = entry.get("attempts", 0) + 1
            entry["last_attempt"] = datetime.now().isoformat()
            _save_manifest(path, data)


def get_pending_files(study_uid: str) -> List[str]:
    """
    Return the list of filenames that are pending upload for *study_uid*.
    Returns [] if there are no pending files or the manifest does not exist.
    """
    if not study_uid:
        return []
    path = _manifest_path(study_uid)
    if not path.exists():
        return []
    lock = _get_study_lock(study_uid)
    with lock:
        data = _load_manifest(path)
        return list(data["pending"].keys())


def is_pending(study_uid: str, filename: str) -> bool:
    """Return True if *filename* is registered as pending for *study_uid*."""
    return filename in get_pending_files(study_uid)


def has_pending(study_uid: str) -> bool:
    """Return True if there is at least one pending file for *study_uid*."""
    return bool(get_pending_files(study_uid))


def get_pending_info(study_uid: str) -> Dict[str, dict]:
    """
    Return the full pending dict for *study_uid*:
      { filename: {saved_at, last_attempt, attempts}, ... }
    Returns {} if none.
    """
    if not study_uid:
        return {}
    path = _manifest_path(study_uid)
    if not path.exists():
        return {}
    lock = _get_study_lock(study_uid)
    with lock:
        data = _load_manifest(path)
        return dict(data.get("pending", {}))


def clear_all_pending(study_uid: str) -> None:
    """Remove all pending entries for *study_uid* (e.g. after bulk upload)."""
    if not study_uid:
        return
    lock = _get_study_lock(study_uid)
    with lock:
        path = _manifest_path(study_uid)
        if path.exists():
            data = _load_manifest(path)
            data["pending"] = {}
            _save_manifest(path, data)
