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
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger("ino_assignment")

#: Server fields that can carry the assignee identity, in the order we trust them.
_MY_ID_FIELDS = ("id", "_id", "user_id", "personnel_id", "ris_user_id", "username")

#: How long a fetched snapshot is trusted before we re-read it from the server.
#: A search, the Refresh button and the auto-refresh all ask for the same rows;
#: without this they each re-fetch the entire visible list. The Refresh button
#: passes ``force=True`` and always re-reads, so the user can never be stuck with a
#: stale row. ``AIPACS_ASSIGN_SNAPSHOT_TTL_S=0`` disables the skip entirely.
DEFAULT_SNAPSHOT_TTL_S = 45.0


def snapshot_ttl_s() -> float:
    try:
        return max(0.0, float(os.environ.get("AIPACS_ASSIGN_SNAPSHOT_TTL_S", "")
                              or DEFAULT_SNAPSHOT_TTL_S))
    except Exception:
        return DEFAULT_SNAPSHOT_TTL_S


def _snapshot_is_fresh(state_mod, reception_id: str, ttl: float) -> bool:
    try:
        snap = state_mod.get_state(reception_id) or {}
        ts = float(snap.get("ts") or 0.0)
        return ts > 0.0 and (time.time() - ts) < ttl
    except Exception:
        return False


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
    force: bool = False,
) -> Dict[str, Any]:
    """Re-read the SERVER assignment for each reception and persist the answer.

    Blocking — call from a worker thread. Fetches run in PARALLEL over a pooled
    keep-alive session. ``on_row(rid, parsed)`` fires per success (on a WORKER
    thread; the caller marshals to the GUI). Returns a summary:
    ``{"ok": bool, "checked": n, "updated": n, "failed": n, "rows": {rid: parsed}}``.

    ``force=True`` re-reads every reception even if its snapshot is still fresh —
    what the Refresh button does. Otherwise recently-fetched receptions are skipped
    (see :data:`DEFAULT_SNAPSHOT_TTL_S`) so a search does not re-fetch a list the
    refresh just read.

    A per-reception failure is recorded as ``failed`` and the stored snapshot is
    left ALONE — an unreachable server must never wipe a known assignment.
    """
    from modules.network import ino_assignment_server_state as _state
    from modules.network.http_session import parallel_workers

    ids = [str(r).strip() for r in (reception_ids or []) if str(r or "").strip()]
    # De-dup while preserving order (a patient can occupy one row only).
    seen: set = set()
    ids = [r for r in ids if not (r in seen or seen.add(r))]

    # SKIP WHAT IS ALREADY FRESH. A search and the Refresh button (and the auto
    # refresh) each ask for the same receptions; without this they re-fetch the
    # whole list every time. `force=True` (the Refresh button) always re-reads.
    if not force:
        ttl = snapshot_ttl_s()
        if ttl > 0:
            fresh = {r for r in ids if _snapshot_is_fresh(_state, r, ttl)}
            if fresh:
                logger.debug("[ino-refresh] %d/%d receptions still fresh — skipped",
                             len(fresh), len(ids))
            ids = [r for r in ids if r not in fresh]
    if not ids:
        return {"ok": True, "checked": 0, "updated": 0, "failed": 0, "rows": {},
                "skipped_fresh": True}

    identities = current_user_identities()
    rows: Dict[str, Any] = {}
    updated = failed = 0
    lock = threading.Lock()

    def _one(rid: str) -> None:
        nonlocal updated, failed
        if should_stop and should_stop():
            return
        parsed = fetch_assignment(rid)
        if parsed is None:
            with lock:
                failed += 1
            return
        parsed["mine"] = assignment_is_mine(parsed["assignee_id"], identities)
        with lock:
            rows[rid] = parsed
            updated += 1
        try:
            _state.set_state(
                rid,
                assigned=bool(parsed["assigned"]),
                assignee_name=parsed["assignee_name"],
                assignee_id=parsed["assignee_id"],
                mine=bool(parsed["mine"]),
                assign_type=parsed["assign_type"],
                assignee_source=parsed["assignee_source"],
                assigned_by=parsed["last_assigned_by"],
                assigned_at=parsed["last_assigned_at"],
            )
        except Exception:
            pass
        if on_row:
            try:
                on_row(rid, parsed)
            except Exception:  # pragma: no cover
                logger.exception("[ino-refresh] on_row callback failed for %s", rid)

    # FAN OUT. This loop used to be strictly sequential on ONE thread — 24 receptions
    # x ~68 ms = ~1.6 s before a single row could update. Each call is an independent,
    # idempotent GET, so they parallelise cleanly; with the pooled keep-alive session
    # the same 24 take ~230 ms (measured, 7x). `AIPACS_RECEPTION_WORKERS=1` restores
    # the sequential behaviour.
    workers = min(parallel_workers(), max(1, len(ids)))
    if workers <= 1:
        for rid in ids:
            _one(rid)
    else:
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="INOAssignFetch") as pool:
            list(pool.map(_one, ids))

    # Resolve the "assigned by" user ids to NAMES here, on the WORKER thread, so the
    # patient list can render "Assigned by: Dr Reza Ahmadi" from a warm cache instead
    # of blocking the GUI on a REST call while it paints.
    try:
        from modules.network import ino_assignment_details as _details

        for parsed in rows.values():
            if parsed.get("assignee_id") and parsed.get("assignee_name"):
                _details.prime_user_name(parsed["assignee_id"], parsed["assignee_name"])
        for parsed in rows.values():
            if parsed.get("last_assigned_by"):
                _details.resolve_user_name(parsed["last_assigned_by"])
    except Exception:  # pragma: no cover - never break the refresh
        pass

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
