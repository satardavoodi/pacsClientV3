"""database.consultation_db — state tracking for cloud consultations (Phase 4).

Three additive, self-initializing tables, isolated from the rest of the schema:

* ``consultations``      — one row per consultation (status, version, assignee,
                            remote folder id, study uids, timestamps).
* ``consultation_files`` — per-file transfer state, the key to **resumable** sync
                            (a file marked ``done`` with a matching sha256 is skipped
                            on a retry).
* ``consultation_events``— append-only audit trail.

Import-safety/testability mirrors ``database.identity_db``: the connection accessor
is imported lazily inside :func:`_db_conn`, so unit tests monkeypatch it to a temp
SQLite database and never touch the live ``dicom.db``.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

_schema_ready = False

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS consultations (
    id              INTEGER PRIMARY KEY,
    consultation_id TEXT NOT NULL UNIQUE,
    direction       TEXT NOT NULL DEFAULT 'outgoing',   -- outgoing | incoming
    status          TEXT NOT NULL DEFAULT 'pending',
    provider        TEXT NOT NULL DEFAULT 'google_drive',
    remote_folder_id TEXT,
    local_path      TEXT,
    owner_identity_id INTEGER,
    from_handle     TEXT,
    assignee_email  TEXT,
    assigned_by     TEXT,
    assigned_at     TEXT,
    case_title      TEXT,
    clinical_question TEXT,
    priority        TEXT,
    package_version INTEGER NOT NULL DEFAULT 1,
    manifest_sha256 TEXT,
    study_uids      TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    due_at          TEXT,
    last_synced_at  TEXT
);
CREATE TABLE IF NOT EXISTS consultation_files (
    id              INTEGER PRIMARY KEY,
    consultation_id TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    remote_file_id  TEXT,
    sha256          TEXT,
    bytes_total     INTEGER,
    bytes_done      INTEGER,
    state           TEXT,                                -- pending | done | failed
    updated_at      INTEGER,
    UNIQUE(consultation_id, rel_path)
);
CREATE TABLE IF NOT EXISTS consultation_events (
    id              INTEGER PRIMARY KEY,
    consultation_id TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    actor_handle    TEXT,
    actor_subject   TEXT,
    details         TEXT,
    created_at      INTEGER
);
"""

_CONSULTATION_COLUMNS = {
    "direction", "status", "provider", "remote_folder_id", "local_path",
    "owner_identity_id", "from_handle", "assignee_email", "assigned_by",
    "assigned_at", "case_title", "clinical_question", "priority",
    "package_version", "manifest_sha256", "study_uids", "created_at",
    "updated_at", "due_at", "last_synced_at",
}
_FILE_COLUMNS = {"remote_file_id", "sha256", "bytes_total", "bytes_done", "state"}


def _db_conn():
    from database._pool import get_db_connection

    return get_db_connection()


def consultation_ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _db_conn() as conn:
        conn.executescript(_CREATE_SQL)
        conn.commit()
    _schema_ready = True


def _row_to_dict(cur, row) -> dict:
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _clean_consultation_fields(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if k not in _CONSULTATION_COLUMNS:
            continue
        if k == "study_uids" and not isinstance(v, str):
            v = json.dumps(list(v or []))
        out[k] = v
    return out


# ── consultations ───────────────────────────────────────────────────────────
def upsert_consultation(consultation_id: str, **fields) -> int:
    consultation_ensure_schema()
    now = _now_iso()
    clean = _clean_consultation_fields(fields)
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM consultations WHERE consultation_id = ?", (consultation_id,))
        existing = cur.fetchone()
        if existing:
            clean.setdefault("updated_at", now)
            if clean:
                sets = ", ".join(f"{k} = ?" for k in clean)
                cur.execute(
                    f"UPDATE consultations SET {sets} WHERE consultation_id = ?",
                    (*clean.values(), consultation_id),
                )
            conn.commit()
            return int(existing[0])

        clean.setdefault("direction", "outgoing")
        clean.setdefault("status", "pending")
        clean.setdefault("created_at", now)
        clean.setdefault("updated_at", now)
        cols = ["consultation_id", *clean.keys()]
        placeholders = ", ".join(["?"] * len(cols))
        cur.execute(
            f"INSERT INTO consultations ({', '.join(cols)}) VALUES ({placeholders})",
            (consultation_id, *clean.values()),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_consultation_fields(consultation_id: str, **fields) -> bool:
    return bool(upsert_consultation(consultation_id, **fields)) if fields else False


def get_consultation(consultation_id: str) -> dict | None:
    consultation_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM consultations WHERE consultation_id = ?", (consultation_id,))
        row = cur.fetchone()
        if not row:
            return None
        return _decode_consultation(_row_to_dict(cur, row))


def list_consultations(direction: str | None = None, status: str | None = None) -> list[dict]:
    consultation_ensure_schema()
    q = "SELECT * FROM consultations WHERE 1=1"
    params: list = []
    if direction:
        q += " AND direction = ?"
        params.append(direction)
    if status:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY COALESCE(updated_at, created_at) DESC"
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(q, params)
        rows = cur.fetchall()
        return [_decode_consultation(_row_to_dict(cur, r)) for r in rows]


def _decode_consultation(d: dict) -> dict:
    raw = d.get("study_uids")
    if isinstance(raw, str) and raw:
        try:
            d["study_uids"] = json.loads(raw)
        except Exception:
            d["study_uids"] = []
    elif raw is None:
        d["study_uids"] = []
    return d


# ── per-file transfer state (resume) ─────────────────────────────────────────
def set_file_state(consultation_id: str, rel_path: str, **fields) -> None:
    consultation_ensure_schema()
    clean = {k: v for k, v in fields.items() if k in _FILE_COLUMNS}
    now = int(time.time())
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM consultation_files WHERE consultation_id = ? AND rel_path = ?",
            (consultation_id, rel_path),
        )
        existing = cur.fetchone()
        if existing:
            clean["updated_at"] = now
            sets = ", ".join(f"{k} = ?" for k in clean)
            cur.execute(
                f"UPDATE consultation_files SET {sets} WHERE id = ?",
                (*clean.values(), existing[0]),
            )
        else:
            clean["updated_at"] = now
            cols = ["consultation_id", "rel_path", *clean.keys()]
            placeholders = ", ".join(["?"] * len(cols))
            cur.execute(
                f"INSERT INTO consultation_files ({', '.join(cols)}) VALUES ({placeholders})",
                (consultation_id, rel_path, *clean.values()),
            )
        conn.commit()


def get_file_state(consultation_id: str, rel_path: str) -> dict | None:
    consultation_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM consultation_files WHERE consultation_id = ? AND rel_path = ?",
            (consultation_id, rel_path),
        )
        row = cur.fetchone()
        return _row_to_dict(cur, row) if row else None


def list_file_states(consultation_id: str) -> list[dict]:
    consultation_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM consultation_files WHERE consultation_id = ? ORDER BY rel_path",
            (consultation_id,),
        )
        return [_row_to_dict(cur, r) for r in cur.fetchall()]


def clear_file_states(consultation_id: str) -> int:
    consultation_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM consultation_files WHERE consultation_id = ?", (consultation_id,))
        conn.commit()
        return cur.rowcount


# ── audit events ──────────────────────────────────────────────────────────────
def add_event(consultation_id: str, event_type: str, *, details: str = "",
              actor_handle: str = "", actor_subject: str = "") -> int:
    consultation_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO consultation_events "
            "(consultation_id, event_type, actor_handle, actor_subject, details, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (consultation_id, event_type, actor_handle, actor_subject, details, int(time.time())),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_events(consultation_id: str) -> list[dict]:
    consultation_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM consultation_events WHERE consultation_id = ? ORDER BY id",
            (consultation_id,),
        )
        return [_row_to_dict(cur, r) for r in cur.fetchall()]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
