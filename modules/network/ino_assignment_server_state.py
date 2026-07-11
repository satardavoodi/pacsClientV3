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
    try:
        p = _path()
        tmp = p + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, p)  # atomic
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[ino-assignment] could not write server state: %s", exc)
        return False


def set_state(reception_id, *, assigned: bool, assignee_name: str = "") -> bool:
    """Record the server's answer for one reception. Best-effort, never raises."""
    rid = str(reception_id or "").strip()
    if not rid:
        return False
    try:
        with _LOCK:
            data = _load()
            data[rid] = {
                "assigned": bool(assigned),
                "assignee_name": str(assignee_name or "").strip(),
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
        entry = _load().get(rid)
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
