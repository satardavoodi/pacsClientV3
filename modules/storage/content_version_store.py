"""Local cache of the per-study server *contentVersion* that was LAST SYNCED.

Background
----------
The PACS server keeps a monotonic ``contentVersion`` counter on each study and
``$inc``s it on **any** content change (new series, replaced images, …). The
server returns it on ``GetStudyThumbnails`` (see ``STUDY_STORAGE_AND_VERSIONING``).
This gives the client the cheapest possible, authoritative staleness signal:

    server.content_version > local_synced_version  ==>  the study changed; re-sync

This module persists, per ``study_uid``, the contentVersion at which the local
copy was **last confirmed complete**. The resync reads it to decide whether it
can skip the (relatively expensive) DB query + disk manifest scan entirely:

    server_cv == local_synced  ==>  unchanged since we were last complete -> SKIP

Semantics (important)
---------------------
``set_synced_version`` must be called **only when the study is actually complete
on disk** at that server version — never merely when a download was *enqueued*.
Recording a version we have not finished downloading would make the next resync
skip the disk check and pin an incomplete study as "current". The resync honours
this: it stamps the version on the *up-to-date* branch (nothing missing), and on
the *enqueue* branch it leaves the stamp alone so a later resync re-confirms.

Safety
------
Best-effort and fail-open: any error (missing file, bad JSON, unwritable dir)
degrades to "unknown" (``None``), which makes the caller fall back to the
disk-aware manifest check — i.e. never *less* safe than before this store
existed. Reads are served from an in-memory cache; writes are atomic
(``*.part`` -> ``os.replace``).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
# study_uid -> last-synced contentVersion (int). ``None`` => not yet loaded.
_CACHE: Optional[Dict[str, int]] = None
_STORE_FILENAME = "content_versions.json"


def _store_path() -> Path:
    """Resolve the JSON store path under USER_DATA_ROOT.

    Kept as a function (not a module constant) so tests can monkeypatch it and so
    a USER_DATA_ROOT import failure degrades to a cwd-relative file instead of
    raising at import time.
    """
    try:
        from PacsClient.utils.data_paths import USER_DATA_ROOT
        return Path(USER_DATA_ROOT) / _STORE_FILENAME
    except Exception:
        return Path(_STORE_FILENAME)


def _load() -> Dict[str, int]:
    """Load (once) the persisted map into the in-memory cache."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    data: Dict[str, int] = {}
    try:
        p = _store_path()
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    try:
                        data[str(k)] = int(v)
                    except (TypeError, ValueError):
                        continue
    except Exception as e:  # corrupt / unreadable -> start empty (fail-open)
        logger.debug("content_version_store load failed: %s", e)
        data = {}
    _CACHE = data
    return _CACHE


def _persist(cache: Dict[str, int]) -> None:
    """Atomically write the cache to disk (best-effort)."""
    try:
        p = _store_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        tmp.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        logger.debug("content_version_store persist failed: %s", e)


def get_synced_version(study_uid: str) -> Optional[int]:
    """Return the last-synced contentVersion for ``study_uid`` (or ``None``)."""
    if not study_uid:
        return None
    with _LOCK:
        return _load().get(str(study_uid))


def set_synced_version(study_uid: str, version) -> None:
    """Record that the local copy of ``study_uid`` is complete at ``version``.

    No-op when ``version`` is ``None`` / not an int, or unchanged. Callers MUST
    only invoke this once the study is confirmed complete on disk at this server
    version (see module docstring).
    """
    if not study_uid or version is None:
        return
    try:
        v = int(version)
    except (TypeError, ValueError):
        return
    with _LOCK:
        cache = _load()
        if cache.get(str(study_uid)) == v:
            return
        cache[str(study_uid)] = v
        # In-memory value is now set; persistence is best-effort and must never
        # raise to the caller (fail-open). _persist swallows its own errors, but
        # guard here too as defence-in-depth.
        try:
            _persist(cache)
        except Exception as e:
            logger.debug("content_version_store persist failed (set): %s", e)


def clear(study_uid: Optional[str] = None) -> None:
    """Forget the synced version for a study (so the next open re-syncs).

    ``study_uid=None`` clears every entry. Call this when local data for a study
    is deleted/cleared so contentVersion can't pin a now-empty study as current.
    """
    with _LOCK:
        cache = _load()
        if study_uid is None:
            if not cache:
                return
            cache.clear()
        else:
            if str(study_uid) not in cache:
                return
            cache.pop(str(study_uid), None)
        try:
            _persist(cache)
        except Exception as e:
            logger.debug("content_version_store persist failed (clear): %s", e)


def _reset_cache_for_tests() -> None:
    """Drop the in-memory cache so the next call re-reads ``_store_path()``."""
    global _CACHE
    with _LOCK:
        _CACHE = None
