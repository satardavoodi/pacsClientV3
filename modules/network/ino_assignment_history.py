# -*- coding: utf-8 -*-
"""Internal-center assignment — SEPARATE local history log.

A tiny, isolated append-only JSONL log of internal (INO) assignment actions,
kept **completely separate** from the consultation records
(`database.consultation_db`) so the two workflows never share storage. One line
per action (assigned / reassigned / unassigned / failed).

Stored per-center under the active profile's data root so two centers keep
independent history. Pure stdlib + a soft dependency on the data-paths helper
(with a safe fallback). Never raises into the caller.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from .ino_assignment_models import AssignmentRecord

logger = logging.getLogger("ino_assignment")

_LOCK = threading.Lock()
_HISTORY_FILENAME = "history.jsonl"
_SUBDIR = "ino_assignment"


def _base_dir() -> str:
    """Per-center data dir for the internal-assignment history (with fallbacks)."""
    # 1) Preferred: the active profile's clinical data root (per-center).
    try:
        from PacsClient.utils import data_paths as _dp

        root = getattr(_dp, "CLINICAL_DATA_ROOT", None) or getattr(_dp, "USER_DATA_ROOT", None)
        if root:
            return os.path.join(str(root), _SUBDIR)
    except Exception:
        pass
    # 2) OS-appropriate fallback.
    if os.name == "nt":
        base = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "AIPacs")
    else:
        base = os.path.join(os.path.expanduser("~"), ".aipacs")
    return os.path.join(base, "user_data", _SUBDIR)


def _history_path() -> str:
    d = _base_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, _HISTORY_FILENAME)


def record(entry: AssignmentRecord) -> bool:
    """Append one assignment action to the history log. Best-effort."""
    try:
        line = json.dumps(entry.to_dict(), ensure_ascii=False)
    except Exception:
        return False
    path = _history_path()
    try:
        with _LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        logger.info(
            "[ino-assignment] history: %s reception=%s type=%s assignee=%s ok=%s",
            entry.action, entry.reception_id, entry.assign_type, entry.assignee_name, entry.server_ok,
        )
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[ino-assignment] could not write history: %s", exc)
        return False


def read_all(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return history entries (most recent last). Best-effort; [] on any error."""
    path = _history_path()
    rows: List[Dict[str, Any]] = []
    try:
        if not os.path.exists(path):
            return []
        with _LOCK:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rows.append(json.loads(raw))
                    except Exception:
                        continue
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[ino-assignment] could not read history: %s", exc)
        return []
    if limit and limit > 0:
        return rows[-limit:]
    return rows


def read_for_reception(reception_id, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    rid = str(reception_id)
    rows = [r for r in read_all() if str(r.get("reception_id")) == rid]
    if limit and limit > 0:
        return rows[-limit:]
    return rows


def current_assignee(reception_id) -> Optional[str]:
    """The SERVER-CONFIRMED current assignee NAME for a reception, or None.

    Walks the reception's history in order and honours only entries the server
    confirmed (``server_ok`` truthy): the last ``assigned``/``reassigned`` wins,
    an ``unassigned`` clears it, ``failed`` entries are ignored. A CANCELLED
    status also clears it. This is the persistent, server-derived source the
    Assign-column red indicator reads — a row is never shown red from a
    local-only click, only after the server accepted the assignment.
    """
    from .ino_assignment_models import STATUS_CANCELLED, resolve_assignment_status

    rows = read_for_reception(reception_id)
    if resolve_assignment_status(rows) == STATUS_CANCELLED:
        return None
    name: Optional[str] = None
    for r in rows:
        if not r.get("server_ok"):
            continue
        action = str(r.get("action") or "").strip().lower()
        if action in ("assigned", "reassigned"):
            name = str(r.get("assignee_name") or "").strip() or None
        elif action == "unassigned":
            name = None
    return name


def current_assignment_details(reception_id) -> Optional[Dict[str, Any]]:
    """Everything the assignment-details UI needs, from the REAL record.

    Returns the latest server-confirmed assign/reassign row enriched with the
    resolved lifecycle ``assignment_status`` (active / completed / deactivated /
    cancelled), or None when the reception was never assigned. A cancelled
    assignment still returns the last assignee for context.
    """
    from .ino_assignment_models import resolve_assignment_status

    rows = read_for_reception(reception_id)
    if not rows:
        return None
    base: Optional[Dict[str, Any]] = None
    for r in rows:
        if not r.get("server_ok"):
            continue
        if str(r.get("action") or "").strip().lower() in ("assigned", "reassigned"):
            base = r
    if base is None:
        return None
    out = dict(base)
    out["assignment_status"] = resolve_assignment_status(rows)
    return out
