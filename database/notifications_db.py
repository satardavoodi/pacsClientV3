"""database.notifications_db — in-app notification queue (Phase 5).

One additive, self-initializing table (mirrors the ``ai_reception_db`` queue pattern:
status unread → read → archived). Lazy ``_db_conn`` for import-safety + temp-DB tests.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_schema_ready = False

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL,
    title           TEXT,
    body            TEXT,
    consultation_id TEXT,
    status          TEXT NOT NULL DEFAULT 'unread',   -- unread | read | archived
    created_at      INTEGER
);
"""


def _db_conn():
    from database._pool import get_db_connection

    return get_db_connection()


def notifications_ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _db_conn() as conn:
        conn.executescript(_CREATE_SQL)
        conn.commit()
    _schema_ready = True


def _row_to_dict(cur, row) -> dict:
    return dict(zip([d[0] for d in cur.description], row))


def add_notification(kind: str, *, title: str = "", body: str = "", consultation_id: str = "") -> int:
    notifications_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO notifications (kind, title, body, consultation_id, status, created_at) "
            "VALUES (?, ?, ?, ?, 'unread', ?)",
            (kind, title, body, consultation_id, int(time.time())),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_notifications(status: str | None = None, limit: int | None = None) -> list[dict]:
    notifications_ensure_schema()
    q = "SELECT * FROM notifications WHERE 1=1"
    params: list = []
    if status:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY id DESC"
    if limit:
        q += " LIMIT ?"
        params.append(int(limit))
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(q, params)
        return [_row_to_dict(cur, r) for r in cur.fetchall()]


def set_status(notification_id: int, status: str) -> bool:
    notifications_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE notifications SET status = ? WHERE id = ?", (status, notification_id))
        conn.commit()
        return cur.rowcount > 0


def count(status: str | None = "unread") -> int:
    notifications_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        if status:
            cur.execute("SELECT COUNT(*) FROM notifications WHERE status = ?", (status,))
        else:
            cur.execute("SELECT COUNT(*) FROM notifications")
        row = cur.fetchone()
        return int(row[0]) if row else 0


def delete(notification_id: int) -> bool:
    notifications_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
        conn.commit()
        return cur.rowcount > 0
