# -*- coding: utf-8 -*-
"""Internal-center assignment — last-known SERVER state snapshot.

The Assign column used to be painted purely from the local append-only action log
(``ino_assignment_history``), so an assignment that was added, changed or removed
**on the server by someone else** never appeared until this client performed the
action itself. The Main-Page "Refresh Status" button now re-reads the server
(``GET /api/patients/{id}/assign``) and stores the answer here.

Why a separate snapshot instead of appending to the history log:
- the history is an **action** log (assigned / reassigned / unassigned / failed);
  writing a row on every refresh would pollute it and skew
  ``resolve_assignment_status``;
- this file is a plain last-known-server-state cache, so it can be rewritten
  freely and lets the refreshed Assign icon **survive reopening / reloading the
  list** (which an in-memory cache would not).

IMPORTANT (see ino_assignment_models): only ``active`` and ``cancelled`` are
server-backed. ``completed`` / ``deactivated`` are LOCAL-only lifecycle states
with no INO endpoint — so this snapshot deliberately records only the
server-owned dimension (*is there an assignment right now, and to whom*). The
caller merges it with the local history and must never let it clobber a local
terminal state.

Pure stdlib; per-center (same data root as the history log); never raises.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("ino_assignment")

_LOCK = threading.Lock()
_FILENAME = "server_state.json"
_SUBDIR = "ino_assignment"


def _base_dir() -> str:
    """Per-center data dir (mirrors ino_assignment_history._base_dir)."""
    try:
        from PacsClient.utils import data_paths as _dp

        root = getattr(_dp, "CLINICAL_DATA_ROOT", None) or getattr(_dp, "USER_DATA_ROOT", None)
        if root:
            return os.path.join(str(root), _SUBDIR)
    except Exception:
        pass
    if os.name == "nt":
        base = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "AIPacs")
    else:
        base = os.path.join(os.path.expanduser("~"), ".aipacs")
    return os.path.join(base, "user_data", _SUBDIR)


def _path() -> str:
    d = _base_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, _FILENAME)


# ── OPT-50 (2026-08-03): mtime-guarded read cache ─────────────────────────────
# `get_state` is called PER PATIENT-LIST ROW (three times per row, via
# _assign_icon_state / _apply_report_status_display / get_assignment_details), and
# each call re-opened and re-parsed this whole JSON file. Profiling an 800-row
# render: 2400 _load() calls = 6.7 s, i.e. HALF the cost of building the list, all
# on the GUI thread — the same defect class as the Status column (2026-08-02).
#
# The cache key is the file's (mtime_ns, size), so a changed file is always
# re-read: staleness is impossible short of two writes inside one mtime tick with
# an identical size, and `_save` invalidates explicitly anyway. It also REDUCES
# open handles on this file, which is exactly what `_save`'s os.replace fights
# with on Windows (see its docstring).
#
# Kill switch: AIPACS_INO_STORE_CACHE=0 restores the read-every-time behaviour.
_CACHE_KEY = None
_CACHE_VALUE: Dict[str, Any] = {}


def _store_cache_enabled() -> bool:
    return (os.getenv("AIPACS_INO_STORE_CACHE", "1") or "1").strip() != "0"


def _fsync_enabled() -> bool:
    """Whether ``_save`` forces the snapshot to physical disk. Default: NO.

    2026-08-16 — the ``os.fsync`` here was 9/10ths of the write cost and it was
    being paid once per reception. Measured on the reporting workstation
    (two real-time AV engines, 336,590-byte / 1,279-reception snapshot):

        with fsync (as shipped)   median 118 ms, p90 162 ms
        without fsync             median  13 ms
        json.dumps alone            3.3 ms

    Since ``get_state`` also takes ``_LOCK`` (see its comment), every one of
    those 118 ms blocked the GUI thread, which reads this per patient-list row.
    One refresh batch produced a **10.79 s** frozen UI: 10793 / 118 = 91 writes.

    Dropping the fsync is safe HERE specifically because of what this file is:
    a last-known-server-state **cache that can always be re-fetched** (the
    module docstring: "a plain last-known-server-state cache, so it can be
    rewritten freely"). ``os.replace`` is still atomic on NTFS, so a reader
    always sees a whole document — old or new, never spliced. The only thing
    fsync adds is durability across a POWER LOSS, and the worst case there is
    an unparseable or stale snapshot, which ``_load`` already swallows
    (returns ``{}``) and the next refresh repopulates. No assignment is lost:
    the server is the source of truth, this is a display cache.

    Set ``AIPACS_INO_STATE_FSYNC=1`` to force the flush back on.
    """
    return (os.getenv("AIPACS_INO_STATE_FSYNC", "0") or "0").strip() == "1"


def _invalidate_cache() -> None:
    """Drop the read cache — called after a successful write."""
    global _CACHE_KEY
    _CACHE_KEY = None


def _load() -> Dict[str, Any]:
    global _CACHE_KEY, _CACHE_VALUE
    try:
        p = _path()
        if not os.path.exists(p):
            _CACHE_KEY = None
            return {}
        if not _store_cache_enabled():
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        st = os.stat(p)
        key = (p, st.st_mtime_ns, st.st_size)
        if key == _CACHE_KEY:
            return _CACHE_VALUE
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data = data if isinstance(data, dict) else {}
        _CACHE_VALUE = data
        _CACHE_KEY = key
        return data
    except Exception:
        _CACHE_KEY = None
        return {}


def _save(data: Dict[str, Any]) -> bool:
    """Write the snapshot atomically. CALLER MUST HOLD ``_LOCK``.

    2026-07-31 — this failed ~9 times in one day with
    ``[WinError 5] Access is denied: 'server_state.json.part' ->
    'server_state.json'``, three of them within 280 ms on three different
    threads. Two separate causes, both fixed here:

    1. The temp name was a FIXED ``p + ".part"``. Every writer used the same
       scratch file, so two writers could interleave into one temp and the
       "atomic" replace could commit a half-merged document. The name is now
       unique per call.
    2. On Windows ``os.replace`` fails with ERROR_ACCESS_DENIED when the
       DESTINATION has an open handle that was not opened with
       FILE_SHARE_DELETE — and CPython's ``open()`` does not request it. So a
       reader merely holding ``server_state.json`` open blocked the writer.
       ``get_state`` now takes ``_LOCK`` too (see below), which removes the
       reader/writer overlap; the short retry here covers the remaining
       out-of-process case (antivirus, search indexer, a backup agent).

    The temp file is always removed, so a failed write cannot litter the
    directory with ``.part`` files.
    """
    tmp = ""
    try:
        p = _path()
        tmp = "%s.%d.%d.part" % (p, os.getpid(), threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
            fh.flush()
            if _fsync_enabled():   # 2026-08-16: off by default — see _fsync_enabled
                os.fsync(fh.fileno())
        last: Exception | None = None
        for attempt in range(3):
            try:
                os.replace(tmp, p)  # atomic
                return True
            except PermissionError as exc:   # WinError 5 / 32 — someone holds it
                last = exc
                if attempt < 2:
                    time.sleep(0.05 * (attempt + 1))
        raise last if last is not None else RuntimeError("replace failed")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[ino-assignment] could not write server state: %s", exc)
        return False
    finally:
        # OPT-50: drop the read cache after ANY write attempt. On success the
        # mtime guard would catch it anyway; on FAILURE this is what matters —
        # `set_state` mutates the dict `_load` handed it, so without this a
        # failed save could leave an unwritten change visible to readers.
        _invalidate_cache()
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


# Must match `_entry`'s keyword-only signature. Used to drop unknown keys in
# `set_many` rather than losing a whole batch to one bad row.
_ENTRY_FIELDS = frozenset({
    "assigned", "assignee_name", "assignee_id", "mine",
    "assign_type", "assignee_source", "assigned_by", "assigned_at",
})


def _entry(
    *,
    assigned: bool,
    assignee_name: str = "",
    assignee_id: str = "",
    mine: bool = False,
    assign_type: str = "",
    assignee_source: str = "",
    assigned_by: str = "",
    assigned_at: str = "",
) -> Dict[str, Any]:
    """Build ONE snapshot entry.

    Single source of truth for the record shape — ``set_state`` (one reception)
    and ``set_many`` (a refresh batch) both go through here, so the two paths
    cannot drift apart.
    """
    return {
        "assigned": bool(assigned),
        "assignee_name": str(assignee_name or "").strip(),
        "assignee_id": str(assignee_id or "").strip(),
        "mine": bool(mine),
        # The FULL server record — so the UI can show WHO it is assigned to,
        # WHO assigned it and WHEN, without inferring any of it locally.
        "assign_type": str(assign_type or "").strip(),
        "assignee_source": str(assignee_source or "").strip(),
        "assigned_by": str(assigned_by or "").strip(),     # a user id
        "assigned_at": str(assigned_at or "").strip(),
        "ts": time.time(),
    }


def _merge_and_save(built: Dict[str, Dict[str, Any]]) -> bool:
    """Merge prepared entries into the snapshot under ONE lock, save ONCE.

    The `_load` MUST happen inside the same acquisition as the `_save`: another
    thread (the Assign dialog, the internal panel) can write between them
    otherwise, and this batch would silently roll its change back.

    Entries are built BEFORE the lock is taken so no string work, and no
    `time.time()`, happens while the GUI thread may be waiting on it.
    """
    if not built:
        return False
    try:
        with _LOCK:
            data = _load()
            # `_load` may hand back the SHARED read cache — copy before mutating,
            # or a reader holding that dict sees the change before it is saved
            # (and keeps it if the save fails).
            data = dict(data)
            data.update(built)
            return _save(data)
    except Exception:
        return False


def set_state(
    reception_id,
    *,
    assigned: bool,
    assignee_name: str = "",
    assignee_id: str = "",
    mine: bool = False,
    assign_type: str = "",
    assignee_source: str = "",
    assigned_by: str = "",
    assigned_at: str = "",
) -> bool:
    """Record the server's answer for one reception. Best-effort, never raises.

    ``assignee_id`` / ``mine`` (2026-07-14) exist because the PACS ``/assign``
    radiologist field is set by the RIS report workflow for *most* receptions — it
    is the reporting radiologist, not only an explicit hand-assignment. So "there
    is an assignee" is NOT the same question as "it is assigned to ME", and the UI
    needs the second one (matched by ID, never by display name).
    """
    rid = str(reception_id or "").strip()
    if not rid:
        return False
    entry = _entry(
        assigned=assigned, assignee_name=assignee_name, assignee_id=assignee_id,
        mine=mine, assign_type=assign_type, assignee_source=assignee_source,
        assigned_by=assigned_by, assigned_at=assigned_at,
    )
    return _merge_and_save({rid: entry})


def set_many(entries: Dict[Any, Dict[str, Any]]) -> bool:
    """Record MANY receptions in ONE lock acquisition and ONE file write.

    Why this exists (2026-08-16). ``refresh_assignments`` called ``set_state``
    per reception, and each call rewrites the WHOLE snapshot under ``_LOCK``.
    That is O(all receptions) work for a single reception's update, and
    ``get_state`` — which the patient list calls per row on the GUI thread —
    takes the same lock. One refresh batch on the live workstation produced a
    **10.79 s frozen UI**; the sampler caught the GUI thread parked on
    ``with _LOCK:`` in ``get_state`` in 10 of 12 samples.

    Measured cost of one write on that machine: 118 ms with fsync, 13 ms
    without. So a 91-reception refresh went from ~10.7 s of lock-held time to
    a single ~13 ms write.

    Each value is a plain kwargs mapping matching :func:`set_state` — the entry
    is built by the SAME ``_entry`` helper, so the two paths cannot drift.
    Unknown keys are ignored; a blank reception id is skipped.

    NOTE for callers: persistence now happens once, at the END of a batch. If
    you need a reception readable via ``get_state`` before the batch finishes,
    call ``set_state`` for it — do not assume mid-batch visibility.
    """
    if not entries:
        return True
    built: Dict[str, Any] = {}
    for rid, kwargs in entries.items():
        key = str(rid or "").strip()
        if not key or not isinstance(kwargs, dict):
            continue
        try:
            built[key] = _entry(**kwargs)
        except TypeError:
            # An unexpected key must not lose the whole batch.
            safe = {k: v for k, v in kwargs.items() if k in _ENTRY_FIELDS}
            built[key] = _entry(**safe)
    if not built:
        return False
    return _merge_and_save(built)


def get_state(reception_id) -> Optional[Dict[str, Any]]:
    """Last-known server state for a reception, or None if never fetched."""
    rid = str(reception_id or "").strip()
    if not rid:
        return None
    try:
        # 2026-07-31 — this read used to run OUTSIDE `_LOCK`. `_load` opens the
        # destination file, and on Windows an open read handle makes the
        # writer's `os.replace` fail with ERROR_ACCESS_DENIED, so server
        # assignment state silently failed to persist (the failure is a
        # swallowed warning). The lock protected writer-vs-writer but not
        # writer-vs-READER, which is the case that actually bites here — the
        # worklist calls this per row from background threads while the refresh
        # thread is writing. `_load` itself must stay lock-free: `set_state`
        # already holds `_LOCK` when it calls it, and threading.Lock is not
        # reentrant.
        with _LOCK:
            data = _load()
        entry = data.get(rid)
        # OPT-50: hand back a COPY — `data` may now be the shared read cache,
        # and a caller mutating the returned dict must not poison it.
        return dict(entry) if isinstance(entry, dict) else None
    except Exception:
        return None


def clear() -> bool:
    """Drop the whole snapshot (e.g. on logout / center switch)."""
    try:
        with _LOCK:
            return _save({})
    except Exception:
        return False
