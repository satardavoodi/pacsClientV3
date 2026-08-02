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
