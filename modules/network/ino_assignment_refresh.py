# -*- coding: utf-8 -*-
"""Internal-assignment REFRESH — pull the server's assignment for listed patients.

WHY (2026-07-14, patient 50210)
-------------------------------
The Assign column and the red name in the Report column were painted **only** from
the LOCAL action log (``ino_assignment_history`` → ``history.jsonl``), which is
written by whichever workstation performed the assign. Nothing in the app ever
asked the server who a patient is assigned to — ``InternalAssignmentService.
current_assignment()`` existed but had **zero callers**. So an assignment created
on another PC could never appear here, no matter how often you refreshed. (The
server had it all along: ``GET /api/patients/50210/assign`` returned the
radiologist correctly.)

This module is the missing read path. The Main-Page "Refresh Status" button (and
the patient search) call it for the visible receptions; the answer is stored in
``ino_assignment_server_state`` so the columns can be painted from **server truth**
and survive a restart.

IDENTITY — match by ID, never by display name
---------------------------------------------
:func:`assignment_is_mine` compares the server's ``assignee_id`` against the
logged-in user's ``id`` / ``personnel_id`` / ``ris_user_id`` / ``username`` (the
fields the socket Login response binds — ASSIGN_CLIENT_GUIDE_FA §5.1). Display
names collide and get transliterated; ids do not.

Pure-ish: stdlib + the isolated INO service. Never raises; never touches the
consultation / Drive workflow. Runs on a worker thread — callers must marshal any
UI update back to the GUI thread.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger("ino_assignment")

#: Server fields that can carry the assignee identity, in the order we trust them.
_MY_ID_FIELDS = ("id", "_id", "user_id", "personnel_id", "ris_user_id", "username")


def current_user_identities() -> List[str]:
    """Every id the logged-in user can legitimately be assigned under.

    The server may store a PACS user ``_id``, a RIS ``Personnel._id`` or a RIS
    ``AdminUser._id`` depending on ``assignee_source`` — so we compare against all
    of them rather than assuming one.
    """
    out: List[str] = []
    try:
        from modules.network.socket_token_manager import get_socket_token_manager

        user = get_socket_token_manager().get_user() or {}
        for key in _MY_ID_FIELDS:
            val = str(user.get(key) or "").strip()
            if val and val not in out:
                out.append(val)
    except Exception:
        pass
    return out


def assignment_is_mine(assignee_id: str, identities: Optional[Iterable[str]] = None) -> bool:
    """True when ``assignee_id`` identifies the LOGGED-IN user. ID match only."""
    aid = str(assignee_id or "").strip()
    if not aid:
        return False
    ids = list(identities) if identities is not None else current_user_identities()
    return any(aid == str(i).strip() for i in ids if str(i).strip())


def parse_assignment(assignment: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the server's ``assignment`` object (PURE).

    Server shape (ASSIGN_CLIENT_GUIDE_FA §3.3)::

        {"radiologist": {"id","name","source"},
         "typist":      {"id","name","source"},
         "study_uid": "...", "last_assigned_at": "...", "last_assigned_by": "..."}

    An EMPTY id means "not assigned" — the server clears the id on unassign, so an
    empty string must never be treated as an assignment.
    """
    a = assignment if isinstance(assignment, dict) else {}
    rad = a.get("radiologist") if isinstance(a.get("radiologist"), dict) else {}
    typ = a.get("typist") if isinstance(a.get("typist"), dict) else {}

    rad_id = str(rad.get("id") or "").strip()
    typ_id = str(typ.get("id") or "").strip()
    # The radiologist is the reporting assignment (what the Report column shows).
    primary_id = rad_id or typ_id
    primary = rad if rad_id else (typ if typ_id else {})

    return {
        "assigned": bool(primary_id),
        "assign_type": "radiologist" if rad_id else ("typist" if typ_id else ""),
        "assignee_id": primary_id,
        "assignee_name": str(primary.get("name") or "").strip(),
        "assignee_source": str(primary.get("source") or "").strip(),
        "radiologist_id": rad_id,
        "radiologist_name": str(rad.get("name") or "").strip(),
        "typist_id": typ_id,
        "typist_name": str(typ.get("name") or "").strip(),
        "last_assigned_at": str(a.get("last_assigned_at") or ""),
        "last_assigned_by": str(a.get("last_assigned_by") or ""),
    }


def fetch_assignment(reception_id) -> Optional[Dict[str, Any]]:
    """``GET /api/patients/{rid}/assign`` for ONE reception (blocking).

    Returns the parsed assignment (with ``mine``), or None when the call failed —
    a failure is NOT "unassigned", and must never be persisted as one.
    """
    try:
        from modules.network.ino_assignment import get_internal_assignment_service

        res = get_internal_assignment_service().current_assignment(reception_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[ino-refresh] assignment fetch raised for %s: %s", reception_id, exc)
        return None

    if not isinstance(res, dict) or not res.get("ok"):
        # disabled / auth / permission / network — do NOT downgrade to "unassigned"
        return None

    parsed = parse_assignment(res.get("assignment") or {})
    parsed["mine"] = assignment_is_mine(parsed["assignee_id"])
    parsed["reception_id"] = str(reception_id)
    return parsed


def refresh_assignments(
    reception_ids: Iterable[Any],
    *,
    on_row: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Re-read the SERVER assignment for each reception and persist the answer.

    Blocking — call from a worker thread. ``on_row(rid, parsed)`` fires per success
    (on the WORKER thread; the caller marshals to the GUI). Returns a summary:
    ``{"ok": bool, "checked": n, "updated": n, "failed": n, "rows": {rid: parsed}}``.

    A per-reception failure is recorded as ``failed`` and the stored snapshot is
    left ALONE — an unreachable server must never wipe a known assignment.
    """
    from modules.network import ino_assignment_server_state as _state

    ids = [str(r).strip() for r in (reception_ids or []) if str(r or "").strip()]
    # De-dup while preserving order (a patient can occupy one row only).
    seen: set = set()
    ids = [r for r in ids if not (r in seen or seen.add(r))]

    identities = current_user_identities()
    rows: Dict[str, Any] = {}
    updated = failed = 0

    for rid in ids:
        if should_stop and should_stop():
            break
        parsed = fetch_assignment(rid)
        if parsed is None:
            failed += 1
            continue
        parsed["mine"] = assignment_is_mine(parsed["assignee_id"], identities)
        rows[rid] = parsed
        updated += 1
        try:
            _state.set_state(
                rid,
                assigned=bool(parsed["assigned"]),
                assignee_name=parsed["assignee_name"],
            )
        except Exception:
            pass
        if on_row:
            try:
                on_row(rid, parsed)
            except Exception:  # pragma: no cover
                logger.exception("[ino-refresh] on_row callback failed for %s", rid)

    logger.info(
        "[ino-refresh] assignments checked=%d updated=%d failed=%d",
        len(ids), updated, failed,
    )
    return {
        "ok": failed == 0 and bool(ids),
        "checked": len(ids),
        "updated": updated,
        "failed": failed,
        "rows": rows,
    }
