"""database.ai_sessions_db — AI chat session, message, report, and secretary audit storage.

Public API
----------
ai_ensure_schema()                          — create/migrate AI tables
ai_backfill_sessions_from_messages()        — create stubs for orphan messages
ai_upsert_session(sid, title, study_uid)    — insert or update session row
ai_fetch_sessions_by_study(study_uid)       — [(sid, title)] for study
ai_set_last_session_for_study(uid, sid)     — persist last-opened session per study
ai_get_last_session_for_study(uid)          — get last-opened session for study
ai_update_session_title(sid, title)         — update title for session
ai_set_server_sid(sid, server_sid)          — store server-assigned SID
ai_get_server_sid(sid)                      — retrieve server SID
ai_fetch_sid_pairs()                        — (sid, title, server_sid) for all sessions
ai_append_message(sid, who, html, ...)      — append message, return msg_id
ai_update_message(msg_id, new_html)         — update message HTML
ai_fetch_messages_full(sid)                 — [(id, who, html, origin)] for session
ai_fetch_messages(sid)                      — [(who, html)] for session
ai_reassign_session(old_sid, new_sid, ...)  — merge session into new SID
ai_fetch_all_sessions()                     — [(sid, title)] all sessions
ai_is_pinned(sid)                           — bool
ai_set_pinned(sid, pinned)                  — set pin state
ai_toggle_pinned(sid)                       — toggle, returns new state
ai_fetch_pinned_sids(study_uid)             — list of pinned sids
ai_set_pinned_bulk(study_uid, sids)         — bulk pin/unpin
ai_delete_session_and_messages(sid)         — hard delete session + messages
ai_set_last_session(sid)                    — write to global ai_meta
ai_get_last_session()                       — read from global ai_meta
ai_insert_report(sid, msg_id, raw_en, ...) — persist report payload
ai_fetch_reports_for_session(sid, ...)      — report rows for session
ai_fetch_reports_map_for_session(sid, ...)  — {msg_id: raw_en} map
ai_fetch_reports_for_study(study_uid, ...)  — report rows for entire study
ai_log_secretary_action_start(...)          — insert audit row, return id
ai_log_secretary_action_end(...)            — update audit row
ai_fetch_secretary_actions(sid, limit)      — list of action dicts

Split from database/core.py (v2.2.9.0).
"""

import json
import logging
import sqlite3

from database._pool import get_db_connection, get_connection_database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def ai_ensure_schema():
    """
    Ensure AI chat tables exist and include study scoping + timestamps.

    Tables:
      - ai_sessions(sid PK, title, server_sid, study_uid, pinned, created_at, updated_at)
      - ai_messages(id PK, sid, who, html, created_at, origin)
      - ai_reports(id PK, sid, msg_id, study_uid, kind, label, raw_en, created_at)
      - ai_last_session(study_uid PK, sid)
      - ai_meta(k PK, v)
    """
    conn = get_connection_database()
    cur = conn.cursor()

    # sessions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_sessions(
            sid TEXT PRIMARY KEY,
            title TEXT,
            server_sid TEXT,
            study_uid TEXT
        )
    """)
    try:
        cur.execute("SELECT study_uid FROM ai_sessions LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE ai_sessions ADD COLUMN study_uid TEXT")

    try:
        cur.execute("SELECT pinned FROM ai_sessions LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE ai_sessions ADD COLUMN pinned INTEGER DEFAULT 0")
        cur.execute("UPDATE ai_sessions SET pinned = 0 WHERE pinned IS NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_sessions_pinned ON ai_sessions(pinned)")

    try:
        cur.execute("SELECT created_at FROM ai_sessions LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE ai_sessions ADD COLUMN created_at INTEGER")
        cur.execute("UPDATE ai_sessions SET created_at = strftime('%s','now') WHERE created_at IS NULL")

    try:
        cur.execute("SELECT updated_at FROM ai_sessions LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE ai_sessions ADD COLUMN updated_at INTEGER")
        cur.execute("UPDATE ai_sessions SET updated_at = created_at WHERE updated_at IS NULL")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_sessions_study ON ai_sessions(study_uid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_sessions_updated ON ai_sessions(updated_at)")

    # messages
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sid TEXT,
            who TEXT,
            html TEXT,
            ts INTEGER,
            origin TEXT
        )
    """)
    try:
        cur.execute("SELECT created_at FROM ai_messages LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE ai_messages ADD COLUMN created_at INTEGER")
        cur.execute("UPDATE ai_messages SET created_at = COALESCE(ts, strftime('%s','now')) WHERE created_at IS NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_messages_sid ON ai_messages(sid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_messages_created ON ai_messages(created_at)")

    # reports
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sid TEXT NOT NULL,
            msg_id INTEGER,
            study_uid TEXT,
            kind TEXT DEFAULT 'report',
            label TEXT,
            raw_en TEXT NOT NULL,
            created_at INTEGER
        )
    """)
    try:
        cur.execute("SELECT created_at FROM ai_reports LIMIT 1")
    except Exception:
        try:
            cur.execute("ALTER TABLE ai_reports ADD COLUMN created_at INTEGER")
            cur.execute("UPDATE ai_reports SET created_at = strftime('%s','now') WHERE created_at IS NULL")
        except Exception:
            pass

    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_reports_sid ON ai_reports(sid, created_at, id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_reports_msg_id ON ai_reports(msg_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_reports_study ON ai_reports(study_uid, created_at, id)")

    # last-session per study
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_last_session(
            study_uid TEXT PRIMARY KEY,
            sid TEXT
        )
    """)

    # global meta
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_meta(
            k TEXT PRIMARY KEY,
            v TEXT
        )
    """)

    # Reception reports table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_reception_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            study_uid TEXT,
            html_content TEXT NOT NULL,
            session_id TEXT,
            msg_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            read_at INTEGER,
            sender_info TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_reception_reports_patient ON ai_reception_reports(patient_id, status, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_reception_reports_study ON ai_reception_reports(study_uid, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_reception_reports_status ON ai_reception_reports(status, created_at)")

    # Secretary action audit log
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_secretary_actions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL,
            sid TEXT,
            source_tab TEXT,
            command_text TEXT,
            stt_route_requested TEXT,
            stt_route_used TEXT,
            intent TEXT,
            entities_json TEXT,
            action_json TEXT,
            confirmation_required INTEGER DEFAULT 0,
            confirmed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'started',
            error_code TEXT,
            error_text TEXT,
            result_count INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_secretary_actions_sid ON ai_secretary_actions(sid, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_secretary_actions_status ON ai_secretary_actions(status, created_at DESC)")

    conn.commit()


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def ai_backfill_sessions_from_messages():
    """
    If a message references a sid that has no ai_sessions row,
    create a minimal stub so it appears in the session list.
    """
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO ai_sessions(sid)
        SELECT DISTINCT m.sid
        FROM ai_messages AS m
        LEFT JOIN ai_sessions AS s ON s.sid = m.sid
        WHERE s.sid IS NULL
    """)
    conn.commit()


def ai_upsert_session(sid: str, title: str | None = None, study_uid: str | None = None):
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ai_sessions(sid, title, study_uid)
        VALUES(?, ?, ?)
        ON CONFLICT(sid) DO UPDATE SET
            title = COALESCE(?, ai_sessions.title),
            study_uid = COALESCE(?, ai_sessions.study_uid)
    """, (sid, title, study_uid, title, study_uid))
    conn.commit()


def ai_fetch_sessions_by_study(study_uid: str) -> list[tuple[str, str]]:
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("""
        SELECT sid, COALESCE(title,'New Chat')
        FROM ai_sessions
        WHERE study_uid = ?
        ORDER BY COALESCE(pinned, 0) DESC, COALESCE(updated_at, created_at, rowid) DESC
    """, (study_uid,))
    return cur.fetchall()


def ai_set_last_session_for_study(study_uid: str, sid: str):
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ai_last_session(study_uid, sid)
        VALUES(?, ?)
        ON CONFLICT(study_uid) DO UPDATE SET sid=excluded.sid
    """, (study_uid, sid))
    conn.commit()


def ai_get_last_session_for_study(study_uid: str) -> str | None:
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT sid FROM ai_last_session WHERE study_uid = ?", (study_uid,))
    row = cur.fetchone()
    return row[0] if row else None


def ai_update_session_title(sid: str, title: str):
    with get_db_connection() as conn:
        conn.execute("UPDATE ai_sessions SET title=? WHERE sid=?", (title, sid))
        conn.commit()


def ai_set_server_sid(sid: str, server_sid: str | None):
    with get_db_connection() as conn:
        conn.execute("UPDATE ai_sessions SET server_sid=? WHERE sid=?", (server_sid, sid))
        conn.commit()


def ai_get_server_sid(sid: str) -> str | None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT server_sid FROM ai_sessions WHERE sid=?", (sid,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def ai_fetch_sid_pairs() -> list[tuple[str, str | None, str | None]]:
    """(sid, title, server_sid) for all ai_sessions."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT sid, COALESCE(title,'New Chat'), server_sid FROM ai_sessions")
        return cur.fetchall()


def ai_fetch_all_sessions() -> list[tuple[str, str | None]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT sid, COALESCE(title,'New Chat')
            FROM ai_sessions
            ORDER BY COALESCE(pinned, 0) DESC, COALESCE(updated_at, created_at, rowid) DESC
        """)
        return cur.fetchall()


def ai_delete_session_and_messages(sid: str):
    """Hard-delete a session + all its messages/reports and cleanup last_session pointers."""
    if not sid:
        return
    with get_db_connection() as conn:
        cur = conn.cursor()

        cur.execute("DELETE FROM ai_last_session WHERE sid=?", (sid,))

        try:
            cur.execute("SELECT v FROM ai_meta WHERE k='last_session'")
            row = cur.fetchone()
            if row and (row[0] == sid):
                cur.execute("DELETE FROM ai_meta WHERE k='last_session'")
        except Exception:
            pass

        try:
            cur.execute("DELETE FROM ai_reports WHERE sid=?", (sid,))
        except Exception:
            pass
        cur.execute("DELETE FROM ai_messages WHERE sid=?", (sid,))
        cur.execute("DELETE FROM ai_sessions WHERE sid=?", (sid,))
        conn.commit()


def ai_set_last_session(sid: str):
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO ai_meta(k, v) VALUES('last_session', ?)
            ON CONFLICT(k) DO UPDATE SET v=excluded.v
        """, (sid,))
        conn.commit()


def ai_get_last_session() -> str | None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT v FROM ai_meta WHERE k='last_session'")
        row = cur.fetchone()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# Pin management
# ---------------------------------------------------------------------------

def ai_is_pinned(sid: str) -> bool:
    if not sid:
        return False
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(pinned, 0) FROM ai_sessions WHERE sid=?", (sid,))
        row = cur.fetchone()
        return bool(row and int(row[0]) == 1)


def ai_set_pinned(sid: str, pinned: bool):
    if not sid:
        return
    with get_db_connection() as conn:
        conn.execute("UPDATE ai_sessions SET pinned=? WHERE sid=?", (1 if pinned else 0, sid))
        conn.commit()


def ai_toggle_pinned(sid: str) -> bool:
    """Toggle pin state; returns the new state."""
    new_state = not ai_is_pinned(sid)
    ai_set_pinned(sid, new_state)
    return new_state


def ai_fetch_pinned_sids(study_uid: str | None = None) -> list[str]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        if study_uid:
            cur.execute("""
                SELECT sid FROM ai_sessions
                WHERE study_uid = ? AND COALESCE(pinned,0)=1
                ORDER BY COALESCE(updated_at, created_at, rowid) DESC
            """, (study_uid,))
        else:
            cur.execute("""
                SELECT sid FROM ai_sessions
                WHERE COALESCE(pinned,0)=1
                ORDER BY COALESCE(updated_at, created_at, rowid) DESC
            """)
        return [r[0] for r in (cur.fetchall() or []) if r and r[0]]


def ai_set_pinned_bulk(study_uid: str | None, pinned_sids: list[str]):
    pinned_sids = [str(x) for x in (pinned_sids or []) if str(x).strip()]
    with get_db_connection() as conn:
        cur = conn.cursor()

        if study_uid:
            cur.execute("UPDATE ai_sessions SET pinned=0 WHERE study_uid=?", (study_uid,))
            if pinned_sids:
                ph = ",".join(["?"] * len(pinned_sids))
                cur.execute(
                    f"UPDATE ai_sessions SET pinned=1 WHERE study_uid=? AND sid IN ({ph})",
                    (study_uid, *pinned_sids),
                )
        else:
            cur.execute("UPDATE ai_sessions SET pinned=0")
            if pinned_sids:
                ph = ",".join(["?"] * len(pinned_sids))
                cur.execute(
                    f"UPDATE ai_sessions SET pinned=1 WHERE sid IN ({ph})",
                    (*pinned_sids,),
                )
        conn.commit()


# ---------------------------------------------------------------------------
# Message CRUD
# ---------------------------------------------------------------------------

def ai_append_message(sid: str, who: str, html: str, ts: int | None = None,
                      origin: str | None = None) -> int:
    import time
    created = int(time.time()) if ts is None else int(ts)
    with get_db_connection() as conn:
        ai_upsert_session(sid)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ai_messages(sid, who, html, created_at, origin) VALUES(?,?,?,?,?)",
            (sid, who, html, created, origin),
        )
        msg_id = int(cur.lastrowid)
        conn.execute("UPDATE ai_sessions SET updated_at=? WHERE sid=?", (int(time.time()), sid))
        conn.commit()
        return msg_id


def ai_update_message(msg_id: int, new_html: str):
    with get_db_connection() as conn:
        conn.execute("UPDATE ai_messages SET html=? WHERE id=?", (new_html, msg_id))
        conn.commit()


def ai_fetch_messages_full(sid: str) -> list[tuple[int, str, str, str | None]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, who, html, origin FROM ai_messages WHERE sid=? ORDER BY created_at ASC, id ASC",
            (sid,),
        )
        rows = cur.fetchall()
        return [(int(r[0]), r[1], r[2], r[3]) for r in rows]


def ai_fetch_messages(sid: str) -> list[tuple[str, str]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT who, html FROM ai_messages WHERE sid=? ORDER BY created_at ASC, id ASC",
            (sid,),
        )
        return cur.fetchall()


def ai_reassign_session(old_sid: str, new_sid: str, new_title: str | None = None):
    if not old_sid or old_sid == new_sid:
        return
    with get_db_connection() as conn:
        ai_upsert_session(new_sid, new_title)
        conn.execute("UPDATE ai_messages SET sid=? WHERE sid=?", (new_sid, old_sid))
        try:
            conn.execute("UPDATE ai_reports SET sid=? WHERE sid=?", (new_sid, old_sid))
        except Exception:
            pass
        conn.execute("DELETE FROM ai_sessions WHERE sid=?", (old_sid,))
        conn.commit()


# ---------------------------------------------------------------------------
# Report CRUD
# ---------------------------------------------------------------------------

def ai_insert_report(
    sid: str,
    msg_id: int | None,
    raw_en: str,
    *,
    study_uid: str | None = None,
    label: str | None = None,
    kind: str = "report",
    ts: int | None = None,
) -> int | None:
    """
    Persist a report payload (raw EN JSON-like string) for a session.

    Dedup rule: If msg_id is provided, keep at most one row per msg_id (replace).
    """
    import time
    if not sid or not (raw_en or "").strip():
        return None

    created = int(time.time()) if ts is None else int(ts)
    raw_en = (raw_en or "").strip()

    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            ai_upsert_session(sid, None, study_uid)
        except Exception:
            try:
                ai_upsert_session(sid)
            except Exception:
                pass

        if msg_id is not None:
            try:
                cur.execute("DELETE FROM ai_reports WHERE msg_id=?", (int(msg_id),))
            except Exception:
                pass

        cur.execute(
            """
            INSERT INTO ai_reports(sid, msg_id, study_uid, kind, label, raw_en, created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (sid, int(msg_id) if msg_id is not None else None, study_uid, kind, label, raw_en, created),
        )
        rid = int(cur.lastrowid)
        try:
            conn.execute("UPDATE ai_sessions SET updated_at=? WHERE sid=?", (int(time.time()), sid))
        except Exception:
            pass
        conn.commit()
        return rid


def ai_fetch_reports_for_session(
    sid: str, *, kind: str = "report"
) -> list[tuple[int, int | None, str | None, str, int | None]]:
    """
    Returns rows: (report_id, msg_id, label, raw_en, created_at)
    """
    if not sid:
        return []
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, msg_id, label, raw_en, created_at
                FROM ai_reports
                WHERE sid=? AND COALESCE(kind,'report')=?
                ORDER BY COALESCE(created_at, 0) ASC, id ASC
                """,
                (sid, kind),
            )
        except Exception:
            cur.execute(
                """
                SELECT id, msg_id, label, raw_en, created_at
                FROM ai_reports
                WHERE sid=?
                ORDER BY COALESCE(created_at, 0) ASC, id ASC
                """,
                (sid,),
            )
        rows = cur.fetchall() or []
        out: list[tuple[int, int | None, str | None, str, int | None]] = []
        for r in rows:
            rid = int(r[0])
            mid = None
            try:
                mid = int(r[1]) if r[1] is not None else None
            except Exception:
                mid = None
            label = r[2] if isinstance(r[2], str) else None
            raw = r[3] if isinstance(r[3], str) else ("" if r[3] is None else str(r[3]))
            cat = None
            try:
                cat = int(r[4]) if r[4] is not None else None
            except Exception:
                cat = None
            out.append((rid, mid, label, raw, cat))
        return out


def ai_fetch_reports_map_for_session(sid: str, *, kind: str = "report") -> dict[int, str]:
    """
    Returns {msg_id: raw_en} for fast attachment of report JSON to loaded bubbles.
    """
    mp: dict[int, str] = {}
    for _, msg_id, _, raw_en, _ in (ai_fetch_reports_for_session(sid, kind=kind) or []):
        if msg_id is None:
            continue
        if not (raw_en or "").strip():
            continue
        mp[int(msg_id)] = raw_en
    return mp


def ai_fetch_reports_for_study(
    study_uid: str, *, kind: str = "report"
) -> list[tuple[int, str, int | None, str | None, str, int | None]]:
    """
    Fetch reports across all sessions of a study.
    Returns rows: (report_id, sid, msg_id, label, raw_en, created_at)
    """
    if not study_uid:
        return []
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, sid, msg_id, label, raw_en, created_at
                FROM ai_reports
                WHERE study_uid=? AND COALESCE(kind,'report')=?
                ORDER BY COALESCE(created_at, 0) ASC, id ASC
                """,
                (study_uid, kind),
            )
        except Exception:
            cur.execute(
                """
                SELECT id, sid, msg_id, label, raw_en, created_at
                FROM ai_reports
                WHERE study_uid=?
                ORDER BY COALESCE(created_at, 0) ASC, id ASC
                """,
                (study_uid,),
            )
        rows = cur.fetchall() or []
        out = []
        for r in rows:
            rid = int(r[0])
            sid = r[1]
            mid = None
            try:
                mid = int(r[2]) if r[2] is not None else None
            except Exception:
                mid = None
            label = r[3] if isinstance(r[3], str) else None
            raw = r[4] if isinstance(r[4], str) else ("" if r[4] is None else str(r[4]))
            cat = None
            try:
                cat = int(r[5]) if r[5] is not None else None
            except Exception:
                cat = None
            out.append((rid, sid, mid, label, raw, cat))
        return out


# ---------------------------------------------------------------------------
# Secretary audit log
# ---------------------------------------------------------------------------

def ai_log_secretary_action_start(
    *,
    sid: str | None,
    source_tab: str,
    command_text: str,
    stt_route_requested: str,
    stt_route_used: str,
    intent: str,
    entities_json: dict | str | None,
    action_json: dict | str | None,
    confirmation_required: bool,
) -> int:
    import time

    def _to_json(value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ai_secretary_actions(
                created_at, sid, source_tab, command_text,
                stt_route_requested, stt_route_used, intent,
                entities_json, action_json,
                confirmation_required, confirmed, status
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'started')
            """,
            (
                int(time.time()), sid, source_tab, command_text,
                stt_route_requested, stt_route_used, intent,
                _to_json(entities_json), _to_json(action_json),
                1 if confirmation_required else 0,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def ai_log_secretary_action_end(
    *,
    action_id: int,
    confirmed: bool,
    status: str,
    error_code: str | None,
    error_text: str | None,
    result_count: int,
    latency_ms: int,
) -> None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE ai_secretary_actions
            SET confirmed=?,
                status=?,
                error_code=?,
                error_text=?,
                result_count=?,
                latency_ms=?
            WHERE id=?
            """,
            (
                1 if confirmed else 0, status, error_code, error_text,
                int(result_count or 0), int(latency_ms or 0), int(action_id),
            ),
        )
        conn.commit()


def ai_fetch_secretary_actions(sid: str | None, limit: int = 100) -> list[dict]:
    lim = max(1, min(int(limit or 100), 2000))
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if sid:
            cur.execute(
                """
                SELECT * FROM ai_secretary_actions
                WHERE sid=?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (sid, lim),
            )
        else:
            cur.execute(
                """
                SELECT * FROM ai_secretary_actions
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (lim,),
            )
        rows = cur.fetchall() or []
        return [dict(r) for r in rows]
