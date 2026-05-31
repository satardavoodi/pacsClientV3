"""database.identity_db — storage for external identities linked to the AI-PACS user.

Part of the additive Identity module (Phase 0/1). Creates and owns a single new
table, ``external_identities``. It is **self-initializing** (idempotent
``CREATE TABLE IF NOT EXISTS`` on first use) and **isolated** — it does not modify
any existing table or any existing database module.

Refresh tokens are NOT stored here; they live in the OS keychain via
:mod:`modules.Identity.secure_store`. This table holds only non-secret identity
metadata + the link to the current AI-PACS user.

Import-safety / testability: the connection accessor is imported lazily inside
:func:`_db_conn` so importing this module never pulls the full DB stack, and unit
tests can monkeypatch :func:`_db_conn` to point at a temp SQLite database.

When ready, wire :func:`identity_ensure_schema` into ``database.dicom_db.init_database``
and re-export the public functions from ``database.core`` (deferred to keep blast
radius zero until verified).
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

_schema_ready = False

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS external_identities (
    id            INTEGER PRIMARY KEY,
    aipacs_user   TEXT NOT NULL,
    provider      TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    handle        TEXT,
    display_name  TEXT,
    avatar_url    TEXT,
    avatar_cache  TEXT,
    capabilities  TEXT,
    is_active_for TEXT,
    extra         TEXT,
    linked_at     INTEGER,
    last_used_at  INTEGER,
    UNIQUE(aipacs_user, provider, subject_id)
)
"""


def _db_conn():
    """Return the app's pooled DB connection context manager (lazy import)."""
    from database._pool import get_db_connection

    return get_db_connection()


def identity_ensure_schema() -> None:
    """Create the ``external_identities`` table if missing (idempotent)."""
    global _schema_ready
    if _schema_ready:
        return
    with _db_conn() as conn:
        conn.execute(_CREATE_SQL)
        conn.commit()
    _schema_ready = True


def _row_to_dict(cur, row) -> dict:
    columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))


def upsert_identity(identity) -> int:
    """Insert or update a linked identity. Returns its row id."""
    identity_ensure_schema()
    now = int(time.time())
    caps = json.dumps(list(getattr(identity, "capabilities", []) or []))
    extra = json.dumps(dict(getattr(identity, "extra", {}) or {}))
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, linked_at FROM external_identities "
            "WHERE aipacs_user = ? AND provider = ? AND subject_id = ?",
            (identity.aipacs_user, identity.provider, identity.subject_id),
        )
        existing = cur.fetchone()
        if existing:
            row_id = existing[0]
            cur.execute(
                """
                UPDATE external_identities SET
                    handle = ?, display_name = ?, avatar_url = ?, avatar_cache = ?,
                    capabilities = ?, extra = ?, last_used_at = ?
                WHERE id = ?
                """,
                (
                    identity.handle, identity.display_name, identity.avatar_url,
                    identity.avatar_cache, caps, extra, now, row_id,
                ),
            )
            conn.commit()
            return int(row_id)

        cur.execute(
            """
            INSERT INTO external_identities
                (aipacs_user, provider, subject_id, handle, display_name, avatar_url,
                 avatar_cache, capabilities, is_active_for, extra, linked_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.aipacs_user, identity.provider, identity.subject_id,
                identity.handle, identity.display_name, identity.avatar_url,
                identity.avatar_cache, caps, json.dumps([]), extra, now, now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_identity(aipacs_user: str, provider: str, subject_id: str):
    """Return one linked :class:`ExternalIdentity` or ``None``."""
    from modules.Identity.models import ExternalIdentity

    identity_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM external_identities "
            "WHERE aipacs_user = ? AND provider = ? AND subject_id = ?",
            (aipacs_user, provider, subject_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return ExternalIdentity.from_row(_row_to_dict(cur, row))


def list_identities(aipacs_user: str) -> list:
    """Return all linked identities for an AI-PACS user (newest first)."""
    from modules.Identity.models import ExternalIdentity

    identity_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM external_identities WHERE aipacs_user = ? "
            "ORDER BY linked_at DESC",
            (aipacs_user,),
        )
        rows = cur.fetchall()
        if not rows:
            return []
        return [ExternalIdentity.from_row(_row_to_dict(cur, r)) for r in rows]


def delete_identity(aipacs_user: str, provider: str, subject_id: str) -> bool:
    identity_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM external_identities "
            "WHERE aipacs_user = ? AND provider = ? AND subject_id = ?",
            (aipacs_user, provider, subject_id),
        )
        conn.commit()
        return cur.rowcount > 0
