# -*- coding: utf-8 -*-
"""Assignment DETAILS — the one display-ready view of who a patient is assigned to.

WHY (2026-07-14)
----------------
The UI could say *that* a patient was assigned but not *to whom*: every consumer
(the Assign column, the internal-assignment panel) read
``ino_assignment_history`` — the LOCAL action log — so for a reception assigned on
ANOTHER workstation (50210) there was simply no record to show, and the details
card stayed hidden.

This module merges the two sources into ONE dict every consumer renders:

* the **SERVER snapshot** (``ino_assignment_server_state``, refreshed by the
  patient-list refresh) — authoritative for assignee, assigner, timestamp, type;
* the **LOCAL log** (``ino_assignment_history``) — the only source of the comment
  and of the ``completed`` / ``deactivated`` lifecycle states, which have no INO
  endpoint.

``assigned_by`` comes back from the server as a raw user **id**; :func:`resolve_user_name`
turns it into a name using the eligible-user list (cached), so the card can read
"Assigned by: Dr Reza Ahmadi" instead of an opaque hex id.

Never raises. Stdlib + the isolated INO service only.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("ino_assignment")

# id -> display name. Populated lazily from the eligible-user list; a miss is
# cached as "" so we never re-query the server for an id it does not know.
_NAME_CACHE: Dict[str, str] = {}
_NAME_LOCK = threading.Lock()
_USERS_LOADED = False


def _load_user_directory() -> None:
    """Fetch the eligible-user list ONCE and index it by id (best-effort)."""
    global _USERS_LOADED
    if _USERS_LOADED:
        return
    _USERS_LOADED = True   # set first: a failure must not cause a retry storm
    try:
        from modules.network.ino_assignment import get_internal_assignment_service

        res = get_internal_assignment_service().list_users("all") or {}
        if not res.get("ok"):
            return
        with _NAME_LOCK:
            for u in res.get("users") or []:
                uid = str(getattr(u, "id", "") or "").strip()
                name = str(getattr(u, "full_name", "") or "").strip()
                if uid and name:
                    _NAME_CACHE.setdefault(uid, name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[ino-details] user directory unavailable: %s", exc)


def resolve_user_name(user_id: str) -> str:
    """Display name for a user id ("" when unknown). Blocking on first call."""
    uid = str(user_id or "").strip()
    if not uid:
        return ""
    with _NAME_LOCK:
        hit = _NAME_CACHE.get(uid)
    if hit is not None:
        return hit
    _load_user_directory()
    with _NAME_LOCK:
        return _NAME_CACHE.get(uid, "")


def cached_user_name(user_id: str) -> str:
    """Cache-ONLY lookup — never triggers a REST call. Used on the paint path."""
    uid = str(user_id or "").strip()
    if not uid:
        return ""
    with _NAME_LOCK:
        return _NAME_CACHE.get(uid, "")


def prime_user_name(user_id: str, name: str) -> None:
    """Remember an id→name pair we already know (e.g. from an assign we just did)."""
    uid, nm = str(user_id or "").strip(), str(name or "").strip()
    if uid and nm:
        with _NAME_LOCK:
            _NAME_CACHE[uid] = nm


def reset_user_directory() -> None:
    """Drop the cached directory (center switch / logout / tests)."""
    global _USERS_LOADED
    with _NAME_LOCK:
        _NAME_CACHE.clear()
    _USERS_LOADED = False


def _fmt_ts(raw: str) -> str:
    """'2026-07-14T11:10:14.770000' → '2026-07-14 11:10:14'."""
    s = str(raw or "").strip()
    if not s:
        return ""
    return s[:19].replace("T", " ")


def get_assignment_details(
    reception_id,
    *,
    report_status: str = "",
    resolve_names: bool = True,
) -> Optional[Dict[str, Any]]:
    """The merged, display-ready assignment for one reception (or None).

    ``report_status`` (optional) lets the caller get the SAME effective lifecycle
    status the Assign column shows — an active assignment whose report is finished
    is *completed*, not *active*.

    Returns None only when the INO feature is off. When no assignment exists the
    dict is returned with ``assigned=False`` and an empty status, so callers can
    render "Not assigned" without a second lookup.
    """
    try:
        from modules.network.ino_assignment import is_enabled
        if not is_enabled():
            return None
        from modules.network import ino_assignment_history as _hist
        from modules.network import ino_assignment_models as _m
        from modules.network import ino_assignment_server_state as _srv
    except Exception:
        return None

    rid = str(reception_id or "").strip()
    if not rid:
        return None

    snap = {}
    try:
        snap = _srv.get_state(rid) or {}
    except Exception:
        snap = {}
    local = {}
    try:
        local = _hist.current_assignment_details(rid) or {}
    except Exception:
        local = {}

    server_assigned = bool(snap.get("assigned")) if snap else None
    merged = _m.merge_assignment_status(
        server_assigned,
        str(snap.get("assignee_name") or ""),
        str(local.get("assignment_status") or ""),
        str(local.get("assignee_name") or ""),
    )
    status = _m.effective_assign_status(merged["status"], report_status)

    # SERVER wins for identity/time; LOCAL is the only source of the comment.
    assignee_name = str(snap.get("assignee_name") or local.get("assignee_name") or "")
    assignee_id = str(snap.get("assignee_id") or local.get("assignee_id") or "")
    assigned_by_id = str(snap.get("assigned_by") or local.get("assigned_by") or "")
    assigned_at = _fmt_ts(snap.get("assigned_at") or local.get("timestamp") or "")

    # ``resolve_names=False`` (the paint path) must never block on a REST call — it
    # reads the already-primed cache. The refresh worker primes it off-thread.
    assigned_by_name = ""
    if assigned_by_id:
        assigned_by_name = (resolve_user_name(assigned_by_id) if resolve_names
                            else cached_user_name(assigned_by_id))

    return {
        "reception_id": rid,
        "assigned": bool(merged["status"]) and status not in ("", _m.STATUS_CANCELLED),
        "status": status,
        "status_label": _m.status_label(status) if status else "Not assigned",
        "status_color": _m.status_color(status),
        "assignee_name": assignee_name,
        "assignee_id": assignee_id,
        "assign_type": str(snap.get("assign_type") or local.get("assign_type") or ""),
        "assignee_source": str(snap.get("assignee_source") or local.get("assignee_source") or ""),
        "assigned_by_id": assigned_by_id,
        "assigned_by_name": assigned_by_name,
        "assigned_at": assigned_at,
        "comment": str(local.get("comment") or ""),      # local-only (no server field)
        "mine": bool(snap.get("mine")),
        "from_server": bool(snap),
    }


def format_tooltip(details: Optional[Dict[str, Any]]) -> str:
    """The Assign-column tooltip: WHO, by whom, when, status, comment."""
    if not details or not details.get("status"):
        return "Not assigned\n(Right-click to manage)"
    d = details
    lines = [f"Status: {d.get('status_label') or '—'}"]
    if d.get("assignee_name"):
        who = d["assignee_name"]
        if d.get("mine"):
            who += "  (you)"
        lines.append(f"Assigned to: {who}")
    if d.get("assign_type"):
        lines.append(f"Role: {d['assign_type']}")
    if d.get("assigned_by_name") or d.get("assigned_by_id"):
        lines.append(f"Assigned by: {d.get('assigned_by_name') or d['assigned_by_id']}")
    if d.get("assigned_at"):
        lines.append(f"Assigned at: {d['assigned_at']}")
    if d.get("comment"):
        lines.append(f"Comment: {d['comment']}")
    lines.append("(Right-click to manage)")
    return "\n".join(lines)
