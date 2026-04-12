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

import logging

from database._pool import get_db_connection

logger = logging.getLogger(__name__)


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

        cur.execute("""
            UPDATE ai_reception_reports
            SET status = ?, updated_at = ?
            WHERE id = ?
        """, (status, int(time.time()), report_id))

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
