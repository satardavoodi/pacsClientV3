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


def _load() -> Dict[str, Any]:
    try:
        p = _path()
        if not os.path.exists(p):
            return {}
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
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
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


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
    try:
        with _LOCK:
            data = _load()
            data[rid] = {
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
            return _save(data)
    except Exception:
        return False


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
        return entry if isinstance(entry, dict) else None
    except Exception:
        return None


def clear() -> bool:
    """Drop the whole snapshot (e.g. on logout / center switch)."""
    try:
        with _LOCK:
            return _save({})
    except Exception:
        return False
