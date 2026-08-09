"""database.ai_reception_db — AI reception report queue storage.

Public API
----------
ai_save_reception_report(patient_id, html_content, ...)  — store report
ai_get_reception_reports(patient_id, study_uid, ...)     — query reports
ai_mark_reception_report_read(report_id)                 — set status='read'
ai_update_reception_report_status(report_id, status)     — set any status
ai_delete_reception_report(report_id)                    — delete one report
ai_get_pending_reception_reports_count(patient_id)       — count pending

Split from database/core.py (v2.2.9.0).
"""

import os
import logging

from database._pool import get_db_connection

logger = logging.getLogger(__name__)


_ENV_RECEPTION_DEDUPE = "AIPACS_RECEPTION_DEDUPE"


def _reception_dedupe_enabled() -> bool:
    """Kill switch for the duplicate-report guard (default ON).

    ``AIPACS_RECEPTION_DEDUPE=0`` restores the byte-identical legacy behaviour:
    every call inserts a new row, duplicates included.
    """
    raw = os.environ.get(_ENV_RECEPTION_DEDUPE)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def ai_save_reception_report(
    patient_id: str,
    html_content: str,
    study_uid: str | None = None,
    session_id: str | None = None,
    msg_id: int | None = None,
    sender_info: str | None = None,
) -> int:
    """
    Save an AI-generated report to reception reports table.

    Args:
        patient_id: Patient identifier
        html_content: HTML formatted report content
        study_uid: Study UID (optional)
        session_id: AI chat session ID (optional)
        msg_id: Message ID from ai_messages (optional)
        sender_info: Additional sender information (optional)

    Returns:
        int: Report ID
    """
    import time

    _logger = logging.getLogger(__name__)
    _logger.debug(
        "ai_save_reception_report: patient=%s study=%s session=%s",
        patient_id, study_uid, session_id,
    )

    with get_db_connection() as conn:
        cur = conn.cursor()
        created_at = int(time.time())

        # ── 2026-07-31: do not create a second row for the same report ───────
        # Observed in the field: one report reaching reception TWICE — two rows
        # with the same patient_id, the same study_uid, the same msg_id and a
        # byte-identical html_content, written ~8 minutes apart, both stuck at
        # 'pending'. The user could not tell the first send had worked (the
        # status column could never be updated, and the button stayed live), so
        # they sent again. Reception then holds one report twice, and a
        # radiologist has to work out which to retire.
        #
        # The dedupe window is deliberately narrow: only a row that is still
        # 'pending' counts. Once reception has marked it 'read' the report has
        # been consumed, and a genuine re-send after that is a NEW report and
        # must get its own row.
        #
        # It also repairs the link while it is here: the first send often
        # arrives with session_id/sender_info NULL (80 of 86 rows on the
        # machine where this was found), so a later send that DOES carry them
        # backfills the existing row instead of creating a rival copy.
        if _reception_dedupe_enabled():
            try:
                cur.execute("""
                    SELECT id, session_id, sender_info FROM ai_reception_reports
                    WHERE patient_id = ?
                      AND status = 'pending'
                      AND IFNULL(study_uid, '') = IFNULL(?, '')
                      AND IFNULL(msg_id, -1)   = IFNULL(?, -1)
                      AND html_content = ?
                    ORDER BY id DESC LIMIT 1
                """, (patient_id, study_uid, msg_id, html_content))
                dup = cur.fetchone()
            except Exception as exc:            # never block a clinical save
                _logger.warning("reception dedupe probe failed: %s", exc)
                dup = None

            if dup:
                dup_id, dup_session, dup_sender = dup[0], dup[1], dup[2]
                patch, params = [], []
                if session_id and not dup_session:
                    patch.append("session_id = ?"); params.append(session_id)
                if sender_info and not dup_sender:
                    patch.append("sender_info = ?"); params.append(sender_info)
                if patch:
                    params.append(dup_id)
                    cur.execute(
                        "UPDATE ai_reception_reports SET %s WHERE id = ?" % ", ".join(patch),
                        params,
                    )
                    conn.commit()
                _logger.info(
                    "ai_save_reception_report: reusing pending report id=%s for "
                    "patient=%s (identical content already queued; backfilled=%s)",
                    dup_id, patient_id, bool(patch),
                )
                return int(dup_id)

        cur.execute("""
            INSERT INTO ai_reception_reports
            (patient_id, study_uid, html_content, session_id, msg_id, status, created_at, sender_info)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (patient_id, study_uid, html_content, session_id, msg_id, created_at, sender_info))

        conn.commit()
        report_id = cur.lastrowid
        _logger.debug("ai_save_reception_report: report_id=%s", report_id)
        return report_id


def ai_get_reception_reports(
    patient_id: str | None = None,
    study_uid: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """
    Get reception reports with optional filtering.

    Args:
        patient_id: Filter by patient ID (optional)
        study_uid: Filter by study UID (optional)
        status: Filter by status ('pending', 'read', 'archived') (optional)
        limit: Maximum number of results (optional)

    Returns:
        List of report dictionaries
    """
    _logger = logging.getLogger(__name__)
    _logger.debug(
        "ai_get_reception_reports: patient=%s study=%s status=%s limit=%s",
        patient_id, study_uid, status, limit,
    )

    with get_db_connection() as conn:
        cur = conn.cursor()

        query = "SELECT * FROM ai_reception_reports WHERE 1=1"
        params = []

        if patient_id:
            query += " AND patient_id = ?"
            params.append(patient_id)

        if study_uid:
            query += " AND study_uid = ?"
            params.append(study_uid)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(int(limit))

        cur.execute(query, params)
        rows = cur.fetchall()

        if not rows:
            return []

        columns = [desc[0] for desc in cur.description]
        result = [dict(zip(columns, row)) for row in rows]
        _logger.debug("ai_get_reception_reports: returned %d rows", len(result))
        return result


def ai_mark_reception_report_read(report_id: int):
    """
    Mark a reception report as read.

    Args:
        report_id: Report ID to mark as read
    """
    import time

    _logger = logging.getLogger(__name__)
    _logger.debug("ai_mark_reception_report_read: report_id=%s", report_id)

    with get_db_connection() as conn:
        cur = conn.cursor()
        read_at = int(time.time())

        cur.execute("""
            UPDATE ai_reception_reports
            SET status = 'read', read_at = ?
            WHERE id = ?
        """, (read_at, report_id))

        conn.commit()


def ai_update_reception_report_status(report_id: int, status: str) -> bool:
    """
    Update reception report status.

    Args:
        report_id: Report ID
        status: New status ('pending', 'read', 'archived')

    Returns:
        bool: True if successful
    """
    import time

    _logger = logging.getLogger(__name__)
    _logger.debug(
        "ai_update_reception_report_status: report_id=%s status=%s",
        report_id, status,
    )

    with get_db_connection() as conn:
        cur = conn.cursor()

        # 2026-07-31 -- `ai_reception_reports` has NO `updated_at` column.
        # Its only definition (ai_sessions_db.ai_ensure_schema) is: id,
        # patient_id, study_uid, html_content, session_id, msg_id, status,
        # created_at, read_at, sender_info -- and there is no ALTER TABLE for
        # `updated_at` anywhere in the codebase. Every call therefore raised
        # `OperationalError: no such column: updated_at`, nothing was written,
        # a report could never leave 'pending', and the pending badge never
        # cleared. `read_at` is the timestamp column this table actually has,
        # and `ai_mark_reception_report_read` already maintains it.
        cur.execute("""
            UPDATE ai_reception_reports
            SET status = ?
            WHERE id = ?
        """, (status, report_id))

        conn.commit()
        return cur.rowcount > 0


def ai_delete_reception_report(report_id: int) -> bool:
    """
    Delete a reception report.

    Args:
        report_id: Report ID to delete

    Returns:
        bool: True if successful
    """
    _logger = logging.getLogger(__name__)
    _logger.debug("ai_delete_reception_report: report_id=%s", report_id)

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM ai_reception_reports WHERE id = ?", (report_id,))
        conn.commit()
        return cur.rowcount > 0


def ai_get_pending_reception_reports_count(patient_id: str | None = None) -> int:
    """
    Get count of pending reception reports.

    Args:
        patient_id: Filter by patient ID (optional)

    Returns:
        Number of pending reports
    """
    _logger = logging.getLogger(__name__)
    _logger.debug("ai_get_pending_reception_reports_count: patient=%s", patient_id)

    with get_db_connection() as conn:
        cur = conn.cursor()

        if patient_id:
            cur.execute("""
                SELECT COUNT(*) FROM ai_reception_reports
                WHERE patient_id = ? AND status = 'pending'
            """, (patient_id,))
        else:
            cur.execute("""
                SELECT COUNT(*) FROM ai_reception_reports
                WHERE status = 'pending'
            """)

        row = cur.fetchone()
        count = row[0] if row else 0
        _logger.debug("ai_get_pending_reception_reports_count: count=%d", count)
        return count


# ═══════════════════════════════════════════════════════════════════════════
# Reception SERVICES cache (2026-08-08)
# ═══════════════════════════════════════════════════════════════════════════
#
# The reception panel's "Services (N)" is the only place in AI-PACS that knows what the
# patient was actually BOOKED for, which makes it the strongest single input for
# EchoMind's region gating: DICOM states laterality in only 18% of studies, and a body
# part alone cannot tell "CT chest" from "CT angiography of the chest".
#
# Until now it arrived from the reception API, lived in ReceptionDataTab.current_data,
# and vanished with the widget. This caches the payload verbatim, keyed by patient id,
# so another module can read it later without a second network call — the same
# store-it-when-it-arrives pattern as the server report snapshot above.
#
# Stored as JSON rather than normalised into columns ON PURPOSE: the reception payload
# is not ours, its shape can change without notice, and a schema that guessed at its
# fields would start losing data the first time it did.

_SERVICES_DDL = """
CREATE TABLE IF NOT EXISTS ai_reception_services(
    patient_id    TEXT PRIMARY KEY,
    services_json TEXT NOT NULL,
    study_uid     TEXT,
    updated_at    INTEGER NOT NULL
)
"""


def ai_save_reception_services(patient_id, services, study_uid=None) -> int:
    """Cache the reception service list for a patient. Last write wins.

    Returns how many services were stored; 0 when there was nothing to store.
    """
    import json
    import time

    pid = str(patient_id or "").strip()
    if not pid:
        return 0
    items = [s for s in (services or []) if isinstance(s, dict)]
    if not items:
        return 0
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(_SERVICES_DDL)
        cur.execute(
            """
            INSERT INTO ai_reception_services(patient_id, services_json, study_uid, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                services_json = excluded.services_json,
                study_uid     = excluded.study_uid,
                updated_at    = excluded.updated_at
            """,
            (pid, json.dumps(items, ensure_ascii=False),
             (str(study_uid).strip() if study_uid else None), int(time.time())),
        )
        conn.commit()
    logger.debug("ai_save_reception_services: patient=%s services=%d", pid, len(items))
    return len(items)


def ai_get_reception_services(patient_id) -> list:
    """The cached reception services for a patient; [] when nothing was cached.

    Never raises: a consumer asking "what was this patient booked for?" must be able to
    accept "we do not know" as an answer.
    """
    import json

    pid = str(patient_id or "").strip()
    if not pid:
        return []
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(_SERVICES_DDL)
            row = cur.execute(
                "SELECT services_json FROM ai_reception_services WHERE patient_id = ?",
                (pid,),
            ).fetchone()
    except Exception as exc:
        logger.debug("ai_get_reception_services failed for %s: %s", pid, exc)
        return []
    if not row:
        return []
    try:
        data = json.loads(row[0])
    except Exception:
        return []
    return data if isinstance(data, list) else []


def ai_get_reception_services_updated_at(patient_id):
    """Unix time this patient's services were last cached, or None.

    Lets a caller decide "fresh enough" for itself instead of refetching on every
    dictation — a physician who re-records four times in a minute should cost the
    reception server one request, not four.
    """
    pid = str(patient_id or "").strip()
    if not pid:
        return None
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(_SERVICES_DDL)
            row = cur.execute(
                "SELECT updated_at FROM ai_reception_services WHERE patient_id = ?",
                (pid,),
            ).fetchone()
    except Exception as exc:
        logger.debug("ai_get_reception_services_updated_at failed for %s: %s", pid, exc)
        return None
    return int(row[0]) if row and row[0] is not None else None
