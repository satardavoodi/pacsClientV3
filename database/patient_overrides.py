"""database.patient_overrides — local, display-only Patient-ID correction alias.

WHY THIS EXISTS
---------------
A reception operator can send a study under a wrong ``PatientID`` (e.g. a typo
``52659`` for the correct ``52658``). The right-click ▸ "Edit patient / study
info…" action corrects the DICOM files + the local ``dicom.db`` — but the
AI-PACS server has **no endpoint** to write demographics (verified 2026-07-18;
``dicom_demographics_edit.server_push_supported()`` is ``False``). The server
therefore keeps returning the original ID, and because the patient list is
rebuilt from the server on every search, the corrected value visually snaps back.

THE MODEL — a LOCAL ALIAS, never a server push
----------------------------------------------
The reception / RIS server is the **system of record** for patient identity;
``PatientID`` == the ``receptionID`` and is the immutable cross-service join key
(reception REST, PACS HTTP, PACS socket). This module does NOT try to change
that. It records a purely local alias ``original_server_id -> corrected_id`` and
lets the patient-list ID column *paint* the corrected value while the row's true
identity (``.text()`` / DisplayRole) stays the **server's original ID**. Every
server-directed read (assignment ``reception_id``, reception payload, report
status, open) therefore keeps using the original key and keeps working. A
permanent, everywhere fix must still be made at reception.

ISOLATION / SAFETY
------------------
Mirrors :mod:`database.identity_db`: a single new, **self-initializing**
(idempotent ``CREATE TABLE IF NOT EXISTS``) table that touches no existing table
or module. The consumption (:func:`resolve_display_patient_id`) is on the Qt
paint path, so it is backed by an in-memory cache and **never** hits disk after
the first load and **never** raises.

Flag ``AIPACS_PATIENT_ID_OVERRIDES`` (default **OFF**; ``=1`` to enable) gates the
DISPLAY only. Recording an alias is always allowed (it writes only to this new,
otherwise-unread table, so it changes no existing behaviour); enabling the flag
later immediately surfaces every alias already recorded.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_ENV_FLAG = "AIPACS_PATIENT_ID_OVERRIDES"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS patient_id_overrides (
    original_patient_id    TEXT PRIMARY KEY,
    corrected_patient_id   TEXT NOT NULL,
    corrected_patient_name TEXT,
    source                 TEXT,
    updated_at             INTEGER
)
"""

_schema_ready = False
_lock = threading.RLock()

# Paint-path cache: original_patient_id -> corrected_patient_id. Loaded lazily
# once, then kept coherent by set_/clear_. `None` means "not loaded yet".
_id_cache: Optional[Dict[str, str]] = None
_name_cache: Dict[str, str] = {}


def patient_overrides_enabled() -> bool:
    """Whether the corrected Patient ID is shown in the UI (display gate).

    Default OFF until live-verified on a source build. ``os.getenv`` is an
    in-memory dict lookup (no disk), so this is safe to call on the paint path.
    """
    return os.getenv(_ENV_FLAG, "0") == "1"


def _db_conn():
    """Return the app's pooled DB connection context manager (lazy import)."""
    from database._pool import get_db_connection

    return get_db_connection()


def patient_overrides_ensure_schema() -> None:
    """Create the ``patient_id_overrides`` table if missing (idempotent)."""
    global _schema_ready
    if _schema_ready:
        return
    with _db_conn() as conn:
        conn.execute(_CREATE_SQL)
        conn.commit()
    _schema_ready = True


def _norm(value) -> str:
    return str(value or "").strip()


def _load_cache_locked() -> Dict[str, str]:
    """Populate the in-memory caches from the DB (once). Never raises."""
    global _id_cache
    try:
        patient_overrides_ensure_schema()
        ids: Dict[str, str] = {}
        names: Dict[str, str] = {}
        with _db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT original_patient_id, corrected_patient_id, "
                "corrected_patient_name FROM patient_id_overrides"
            )
            for orig, corrected, name in cur.fetchall():
                o, c = _norm(orig), _norm(corrected)
                if o and c and o != c:
                    ids[o] = c
                    if _norm(name):
                        names[o] = _norm(name)
        _id_cache = ids
        _name_cache.clear()
        _name_cache.update(names)
    except Exception as exc:  # pragma: no cover - display must never break
        logger.debug("patient-override cache load skipped: %s", exc)
        _id_cache = {}
    return _id_cache


def _ensure_cache() -> Dict[str, str]:
    global _id_cache
    if _id_cache is None:
        with _lock:
            if _id_cache is None:
                return _load_cache_locked()
    return _id_cache


def invalidate_cache() -> None:
    """Force the next resolve to reload from disk (tests / DB path swap)."""
    global _id_cache
    with _lock:
        _id_cache = None
        _name_cache.clear()
        # Allow a re-created (temp) DB to be re-provisioned.
        global _schema_ready
        _schema_ready = False


def resolve_display_patient_id(original_patient_id) -> Optional[str]:
    """Return the corrected ID to DISPLAY for a server ID, or ``None``.

    ``None`` when the feature is off, when there is no alias, or on any error —
    so the caller falls back to the original (server) value. Paint-safe: no disk
    after the first load, never raises.
    """
    if not patient_overrides_enabled():
        return None
    try:
        key = _norm(original_patient_id)
        if not key:
            return None
        corrected = _ensure_cache().get(key)
        if corrected and corrected != key:
            return corrected
    except Exception:  # pragma: no cover - paint path
        return None
    return None


def resolve_display_patient_name(original_patient_id) -> Optional[str]:
    """Return the corrected patient NAME for a server ID, or ``None``.

    Same gating/safety as :func:`resolve_display_patient_id`. Only returns a
    value when a name was captured with the alias.
    """
    if not patient_overrides_enabled():
        return None
    try:
        key = _norm(original_patient_id)
        if not key:
            return None
        _ensure_cache()
        name = _name_cache.get(key)
        return name or None
    except Exception:  # pragma: no cover - paint path
        return None


def set_patient_id_override(
    original_patient_id,
    corrected_patient_id,
    corrected_patient_name: Optional[str] = None,
    source: str = "demographic_edit",
) -> bool:
    """Record (or update) a local alias ``original -> corrected``.

    A no-op when the two IDs are equal or either is blank. Writes only to this
    new isolated table, so it is safe to call regardless of the display flag.
    Keeps the in-memory cache coherent. Returns ``True`` on a write.
    """
    orig = _norm(original_patient_id)
    corrected = _norm(corrected_patient_id)
    if not orig or not corrected or orig == corrected:
        return False
    name = _norm(corrected_patient_name)
    try:
        patient_overrides_ensure_schema()
        with _db_conn() as conn:
            conn.execute(
                """
                INSERT INTO patient_id_overrides
                    (original_patient_id, corrected_patient_id,
                     corrected_patient_name, source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(original_patient_id) DO UPDATE SET
                    corrected_patient_id   = excluded.corrected_patient_id,
                    corrected_patient_name = excluded.corrected_patient_name,
                    source                 = excluded.source,
                    updated_at             = excluded.updated_at
                """,
                (orig, corrected, name or None, source, int(time.time())),
            )
            conn.commit()
    except Exception:
        logger.exception("[PATIENT-OVERRIDE] failed to record %s -> %s", orig, corrected)
        return False
    with _lock:
        if _id_cache is not None:
            _id_cache[orig] = corrected
            if name:
                _name_cache[orig] = name
            else:
                _name_cache.pop(orig, None)
    logger.info("[PATIENT-OVERRIDE] alias recorded server_id=%s -> display_id=%s", orig, corrected)
    return True


def get_patient_id_override(original_patient_id) -> Optional[dict]:
    """Return the full alias row for a server ID as a dict, or ``None``."""
    orig = _norm(original_patient_id)
    if not orig:
        return None
    try:
        patient_overrides_ensure_schema()
        with _db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT original_patient_id, corrected_patient_id, "
                "corrected_patient_name, source, updated_at "
                "FROM patient_id_overrides WHERE original_patient_id = ?",
                (orig,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "original_patient_id": row[0],
                "corrected_patient_id": row[1],
                "corrected_patient_name": row[2],
                "source": row[3],
                "updated_at": row[4],
            }
    except Exception:  # pragma: no cover
        return None


def all_patient_id_overrides() -> Dict[str, str]:
    """Return a copy of the ``original -> corrected`` alias map (all rows)."""
    return dict(_ensure_cache())


def clear_patient_id_override(original_patient_id) -> bool:
    """Delete a recorded alias. Returns ``True`` if a row was removed."""
    orig = _norm(original_patient_id)
    if not orig:
        return False
    removed = False
    try:
        patient_overrides_ensure_schema()
        with _db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM patient_id_overrides WHERE original_patient_id = ?",
                (orig,),
            )
            conn.commit()
            removed = cur.rowcount > 0
    except Exception:
        logger.exception("[PATIENT-OVERRIDE] failed to clear %s", orig)
        return False
    with _lock:
        if _id_cache is not None:
            _id_cache.pop(orig, None)
        _name_cache.pop(orig, None)
    return removed
