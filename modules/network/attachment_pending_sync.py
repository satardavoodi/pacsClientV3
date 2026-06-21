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
import re
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


# ─────────────────────────────────────────
# Derived sync-status labels
# ─────────────────────────────────────────
# The manifest stores only the *pending* set; these labels are derived from it
# so callers get the attachment lifecycle states the product spec asks for
# (PendingSync / Synced / FailedSync / LocalOnly) without a schema change. Disk
# is always the source of truth for whether the file *exists*; these labels only
# describe its upload/sync state.
STATUS_SYNCED = "Synced"            # not in the pending manifest -> uploaded & confirmed
STATUS_LOCAL_ONLY = "LocalOnly"     # pending, never attempted (saved while offline)
STATUS_PENDING_SYNC = "PendingSync"  # pending, attempted at least once, awaiting confirmation
STATUS_FAILED_SYNC = "FailedSync"   # reserved: a pending file whose attempts exceed the cap


def get_status(study_uid: str, filename: str) -> str:
    """Return the sync-lifecycle status of one locally-saved attachment.

      - not pending          -> ``STATUS_SYNCED``      (already uploaded / not tracked)
      - pending, 0 attempts   -> ``STATUS_LOCAL_ONLY``  (saved, not yet sent)
      - pending, attempts>0   -> ``STATUS_PENDING_SYNC`` (sent, awaiting/​retrying)
    """
    if not study_uid or not filename:
        return STATUS_SYNCED
    entry = get_pending_info(study_uid).get(filename)
    if entry is None:
        return STATUS_SYNCED
    attempts = int(entry.get("attempts", 0) or 0)
    return STATUS_PENDING_SYNC if attempts > 0 else STATUS_LOCAL_ONLY


# ─────────────────────────────────────────
# Local ↔ server attachment de-duplication
# ─────────────────────────────────────────
# The upload server stores each uploaded attachment under a unique id prepended
# to the ORIGINAL client filename, e.g.
#     REC_20260621_145327.wav  ->  0c634fb7_REC_20260621_145327.wav
# When the study is reopened, ``download_attachments_for_study`` fetches that
# server copy; because its name differs from the local original, the plain
# "does this exact filename already exist locally?" check misses and a SECOND
# file is written — so one synced voice shows up twice (two -> four, etc.).
# These pure helpers recognise that "<server_id>_<original>" and "<original>"
# are the SAME logical attachment, so the server copy reconciles against the
# existing local file instead of duplicating it. Disk stays the source of
# truth; nothing is ever deleted — duplicates are only avoided / hidden.
_SERVER_ID_PREFIX_RE = re.compile(r"^[0-9a-fA-F]{8}_")


def attachment_dedup_enabled() -> bool:
    """Master switch for local↔server attachment de-duplication (default ON).
    Set ``AIPACS_ATTACHMENT_DEDUP=0`` to restore the byte-identical legacy
    behaviour (one file per server item, keyed by exact filename only)."""
    val = os.environ.get("AIPACS_ATTACHMENT_DEDUP", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def strip_server_id_prefix(filename: str) -> str:
    """Return *filename* (basename) without a leading server-assigned id prefix.
    The prefix is an 8-char hex token followed by '_' (the server's attachment
    id). Safe and idempotent for names that have no prefix."""
    if not filename:
        return filename or ""
    base = os.path.basename(str(filename))
    return _SERVER_ID_PREFIX_RE.sub("", base, count=1)


def attachment_identity_key(filename: str) -> str:
    """Canonical identity used to decide whether two attachment files are the
    SAME logical attachment regardless of a server id prefix. The original
    client filename already embeds a per-recording timestamp
    (``REC_<date>_<time>``), so it is a reliable per-attachment identity.
    Case-folded for robustness."""
    return strip_server_id_prefix(filename).casefold()


def find_local_duplicate(
    server_name: str,
    local_names,
    *,
    server_size: Optional[int] = None,
    local_sizes: Optional[Dict[str, int]] = None,
) -> Optional[str]:
    """Return the existing local filename that is the SAME attachment as the
    server-returned *server_name*, or ``None`` if the server file is genuinely
    new (and should be downloaded).

    Matching precedence — most reliable signal first:
      1. exact filename match;
      2. identity-key match (server-id-prefix-insensitive original name).
         When BOTH file sizes are known they must be equal — a size conflict
         rejects the match, so a (vanishingly unlikely) same-second name
         collision can never hide a genuinely different file.
    Never raises.
    """
    try:
        if not server_name:
            return None
        names = list(local_names or [])
        sizes = local_sizes or {}
        if server_name in names:
            return server_name
        s_key = attachment_identity_key(server_name)
        for ln in names:
            if attachment_identity_key(ln) != s_key:
                continue
            if (server_size is not None and sizes.get(ln) is not None
                    and int(server_size) != int(sizes[ln])):
                continue  # same name-key but different bytes -> not a duplicate
            return ln
        return None
    except Exception:
        return None


def choose_canonical_attachment_names(filenames) -> set:
    """Given the attachment filenames in a study folder, return the subset to
    DISPLAY — exactly one per logical attachment (identity key). Prefers the
    original (server-id-prefix-free) name; otherwise a stable lexicographic
    pick. Pure and non-destructive: duplicates are only hidden from the list,
    no file is deleted. Returns a set of names to keep."""
    keep: Dict[str, str] = {}
    for name in filenames or []:
        try:
            key = attachment_identity_key(name)
        except Exception:
            keep[name] = name
            continue
        cur = keep.get(key)
        if cur is None:
            keep[key] = name
            continue
        cur_is_original = strip_server_id_prefix(cur) == cur
        new_is_original = strip_server_id_prefix(name) == name
        if new_is_original and not cur_is_original:
            keep[key] = name
        elif new_is_original == cur_is_original and name < cur:
            keep[key] = name
    return set(keep.values())
