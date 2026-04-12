"""database.token_usage_db — AI token and transcript usage accounting.

Public API
----------
load_token_usage()                          — {center: {model: tokens}}
save_token_usage(center, model, tokens)     — upsert row
add_token_usage_delta(center, model, delta) — atomic increment
add_api_token_usage_delta(key, ...)         — increment by API key (stored as hash)
load_api_token_usage()                      — {api_mask: {model: tokens}}
load_api_token_usage_for_key(key)           — {model: tokens} for one key
add_transcript_usage_delta(...)             — increment transcript (seconds)
add_api_transcript_usage_delta(...)         — increment transcript by API key
load_api_transcript_usage_for_key(key)      — {model: minutes} for one key
get_api_usage_rows(limit)                   — flat rows for debug/export
get_api_usage_rows_for_key(key, limit)      — rows for single key
get_api_usage_summary_html(key)             — HTML for Welcome UI

Internal helpers: _mask_api_key, _hash_api_key, _hash_and_mask_api_key,
                  _ensure_token_usage_tables, _ensure_transcript_usage_tables

Split from database/core.py (v2.2.9.0).
"""

import hashlib
import logging
import sqlite3
from typing import Optional

from database._pool import get_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal key helpers
# ---------------------------------------------------------------------------

def _mask_api_key(api_key: str) -> str:
    """Return safe UI representation; never store full API key."""
    k = (api_key or "").strip()
    if not k:
        return "<empty>"
    if len(k) <= 10:
        return k[:2] + "…" + k[-2:]
    return k[:4] + "…" + k[-4:]


def _hash_api_key(api_key: str) -> str:
    """Stable SHA256 hash of API key (no plaintext storage)."""
    k = (api_key or "").strip()
    if not k:
        return ""
    return hashlib.sha256(k.encode("utf-8", errors="ignore")).hexdigest()


def _hash_and_mask_api_key(api_key: str) -> tuple[str, str]:
    """Return (api_hash, api_mask) using existing helpers."""
    return _hash_api_key(api_key), _mask_api_key(api_key)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _ensure_token_usage_tables(conn: sqlite3.Connection) -> None:
    """Ensure token-usage tables exist (safe for old DBs)."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_token_usage (
            center_name TEXT NOT NULL,
            model_name  TEXT NOT NULL,
            total_tokens INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (center_name, model_name)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_token_usage (
            api_hash     TEXT NOT NULL,
            api_mask     TEXT NOT NULL,
            center_name  TEXT DEFAULT NULL,
            model_name   TEXT NOT NULL,
            total_tokens INTEGER DEFAULT 0,
            last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (api_hash, model_name)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_token_usage_last_used ON api_token_usage(last_used_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_token_usage_mask ON api_token_usage(api_mask)")


def _ensure_transcript_usage_tables(conn: sqlite3.Connection) -> None:
    """Ensure transcript-usage tables exist.

    Transcript usage is tracked in **seconds** and also redundantly in **minutes**
    (for easy reporting). Older DBs may only have total_seconds; we migrate safely.
    """
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_transcript_usage (
            center_name    TEXT NOT NULL,
            model_name     TEXT NOT NULL,
            total_seconds  INTEGER DEFAULT 0,
            total_minutes  REAL DEFAULT 0,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (center_name, model_name)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_transcript_usage (
            api_hash       TEXT NOT NULL,
            api_mask       TEXT NOT NULL,
            center_name    TEXT DEFAULT NULL,
            model_name     TEXT NOT NULL,
            total_seconds  INTEGER DEFAULT 0,
            total_minutes  REAL DEFAULT 0,
            last_used_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (api_hash, model_name)
        )
        """
    )

    def _ensure_col(table: str, col: str, ddl: str) -> None:
        try:
            cur.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in cur.fetchall()]
            if col not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        except Exception:
            return

    _ensure_col("user_transcript_usage", "total_minutes", "total_minutes REAL DEFAULT 0")
    _ensure_col("api_transcript_usage", "total_minutes", "total_minutes REAL DEFAULT 0")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_transcript_usage_last_used ON api_transcript_usage(last_used_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_transcript_usage_mask ON api_transcript_usage(api_mask)")


# ---------------------------------------------------------------------------
# Center/model token usage (user-level)
# ---------------------------------------------------------------------------

def load_token_usage() -> dict:
    """Load token usage from DB: {center: {model: tokens}}"""
    usage = {}
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT center_name, model_name, total_tokens FROM user_token_usage")
        for center, model, tokens in cur.fetchall():
            if center not in usage:
                usage[center] = {}
            usage[center][model] = tokens
    return usage


def save_token_usage(center: str, model: str, tokens: int):
    """Save or update token count for a center+model."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_token_usage (center_name, model_name, total_tokens)
            VALUES (?, ?, ?)
            ON CONFLICT(center_name, model_name) DO UPDATE SET
                total_tokens = excluded.total_tokens,
                updated_at = CURRENT_TIMESTAMP
        """, (center, model, tokens))
        conn.commit()


def add_token_usage_delta(center: str, model: str, tokens_delta: int) -> None:
    """Atomic increment for center+model token usage."""
    if not center or not model:
        return
    try:
        delta = int(tokens_delta or 0)
    except Exception:
        return
    if delta <= 0:
        return

    with get_db_connection() as conn:
        _ensure_token_usage_tables(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_token_usage (center_name, model_name, total_tokens)
            VALUES (?, ?, ?)
            ON CONFLICT(center_name, model_name) DO UPDATE SET
                total_tokens = user_token_usage.total_tokens + excluded.total_tokens,
                updated_at = CURRENT_TIMESTAMP
            """,
            (center, model, delta),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Per-API-key token usage
# ---------------------------------------------------------------------------

def add_api_token_usage_delta(
    api_key: str,
    center_name: Optional[str],
    model_name: str,
    tokens_delta: int,
) -> None:
    """Atomic increment for API-key+model usage (stored as hash+mask).

    Schema key: (api_hash, model_name)
    """
    api_hash = _hash_api_key(api_key)
    if not api_hash or not model_name:
        return
    try:
        delta = int(tokens_delta or 0)
    except Exception:
        return
    if delta <= 0:
        return

    api_mask = _mask_api_key(api_key)
    with get_db_connection() as conn:
        _ensure_token_usage_tables(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO api_token_usage (api_hash, api_mask, center_name, model_name, total_tokens)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(api_hash, model_name) DO UPDATE SET
                total_tokens = api_token_usage.total_tokens + excluded.total_tokens,
                api_mask = excluded.api_mask,
                center_name = COALESCE(excluded.center_name, api_token_usage.center_name),
                last_used_at = CURRENT_TIMESTAMP
            """,
            (api_hash, api_mask, center_name, model_name, delta),
        )
        conn.commit()


def load_api_token_usage() -> dict:
    """Load per-API usage from DB: {api_mask: {model: tokens}}"""
    usage: dict = {}
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT api_mask, model_name, total_tokens FROM api_token_usage ORDER BY api_mask, model_name"
        )
        for api_mask, model, tokens in cur.fetchall():
            usage.setdefault(api_mask, {})[model] = int(tokens or 0)
    return usage


def load_api_token_usage_for_key(api_key: str) -> dict:
    """{model: tokens} for a single api_key (by hash)."""
    api_hash = _hash_api_key(api_key)
    if not api_hash:
        return {}
    out: dict = {}
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT model_name, total_tokens FROM api_token_usage WHERE api_hash=? ORDER BY model_name",
            (api_hash,),
        )
        for model, tokens in cur.fetchall():
            out[model] = int(tokens or 0)
    return out


def get_api_usage_rows_for_key(api_key: str, limit: int = 50) -> list[dict]:
    """Rows for a single api_key (by hash) from api_token_usage."""
    api_hash = _hash_api_key(api_key)
    if not api_hash:
        return []

    limit = max(1, min(int(limit or 50), 5000))
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT api_mask, COALESCE(center_name,''), model_name, total_tokens, last_used_at
            FROM api_token_usage
            WHERE api_hash = ?
            ORDER BY datetime(last_used_at) DESC, total_tokens DESC
            LIMIT ?
            """,
            (api_hash, limit),
        )
        rows = cur.fetchall()

    return [
        {
            "api": r[0], "center": r[1], "model": r[2],
            "tokens": int(r[3] or 0), "last_used_at": r[4],
        }
        for r in rows
    ]


def get_api_usage_rows(limit: int = 500) -> list[dict]:
    """Flat rows for UI/debug/export."""
    limit = max(1, min(int(limit or 500), 5000))
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT api_mask, COALESCE(center_name,''), model_name, total_tokens, last_used_at
            FROM api_token_usage
            ORDER BY datetime(last_used_at) DESC, total_tokens DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [
        {
            "api": r[0], "center": r[1], "model": r[2],
            "tokens": int(r[3] or 0), "last_used_at": r[4],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Per-API-key transcript usage
# ---------------------------------------------------------------------------

def add_transcript_usage_delta(center_name: str, model_name: str, seconds_delta: int) -> None:
    """Increment transcript usage for a center+model.

    Stores:
      - total_seconds (INTEGER)
      - total_minutes (REAL, derived from seconds)
    """
    if not center_name:
        center_name = "<unknown>"
    model_name = (model_name or "").strip()

    # Canonical transcript model name
    if model_name in ("irannobattranscript model", ""):
        model_name = "irannobat transcriptmodel"

    try:
        sec_f = float(seconds_delta or 0)
    except Exception:
        sec_f = 0.0
    sec = int(round(sec_f))
    if sec <= 0:
        return
    mins = float(sec) / 60.0

    with get_db_connection() as conn:
        _ensure_transcript_usage_tables(conn)
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO user_transcript_usage(center_name, model_name, total_seconds, total_minutes, updated_at)
                VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(center_name, model_name) DO UPDATE SET
                    total_seconds = COALESCE(total_seconds, 0) + ?,
                    total_minutes = COALESCE(total_minutes, 0) + ?,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (center_name, model_name, sec, mins, sec, mins),
            )
            conn.commit()
        except sqlite3.OperationalError:
            cur.execute(
                """
                INSERT INTO user_transcript_usage(center_name, model_name, total_seconds, updated_at)
                VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(center_name, model_name) DO UPDATE SET
                    total_seconds = COALESCE(total_seconds, 0) + ?,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (center_name, model_name, sec, sec),
            )
            conn.commit()


def add_api_transcript_usage_delta(api_key: str, center_name: str, model_name: str, seconds_delta: int) -> None:
    api_key = (api_key or "").strip()
    if not api_key:
        return

    model_name = "irannobat transcriptmodel"

    try:
        sec_f = float(seconds_delta or 0)
    except Exception:
        return
    sec = int(round(sec_f))
    if sec <= 0:
        return

    mins = float(sec) / 60.0
    api_hash, api_mask = _hash_and_mask_api_key(api_key)
    if not api_hash:
        return

    with get_db_connection() as conn:
        _ensure_transcript_usage_tables(conn)
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO api_transcript_usage(api_hash, api_mask, center_name, model_name, total_seconds, total_minutes, last_used_at)
                VALUES(?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(api_hash, model_name) DO UPDATE SET
                    api_mask = excluded.api_mask,
                    center_name = excluded.center_name,
                    total_seconds = COALESCE(total_seconds, 0) + ?,
                    total_minutes = COALESCE(total_minutes, 0) + ?,
                    last_used_at = CURRENT_TIMESTAMP
                """,
                (api_hash, api_mask, center_name, model_name, sec, mins, sec, mins),
            )
            conn.commit()
        except sqlite3.OperationalError:
            cur.execute(
                """
                INSERT INTO api_transcript_usage(api_hash, api_mask, center_name, model_name, total_seconds, last_used_at)
                VALUES(?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(api_hash, model_name) DO UPDATE SET
                    api_mask = excluded.api_mask,
                    center_name = excluded.center_name,
                    total_seconds = COALESCE(total_seconds, 0) + ?,
                    last_used_at = CURRENT_TIMESTAMP
                """,
                (api_hash, api_mask, center_name, model_name, sec, sec),
            )
            conn.commit()


def load_api_transcript_usage_for_key(api_key: str) -> dict:
    """{model: minutes} for a single api_key (by hash)."""
    api_key = (api_key or "").strip()
    if not api_key:
        return {}

    api_hash, _ = _hash_and_mask_api_key(api_key)
    if not api_hash:
        return {}

    out: dict = {}
    with get_db_connection() as conn:
        _ensure_transcript_usage_tables(conn)
        cur = conn.cursor()

        try:
            cur.execute(
                """
                SELECT model_name, total_minutes, total_seconds
                FROM api_transcript_usage
                WHERE api_hash = ?
                """,
                (api_hash,),
            )
            for model, mins, secs in (cur.fetchall() or []):
                model = "irannobat transcriptmodel"

                try:
                    mins_f = float(mins or 0.0)
                except Exception:
                    mins_f = 0.0

                if mins_f <= 0.0:
                    try:
                        secs_i = int(secs or 0)
                    except Exception:
                        secs_i = 0
                    if secs_i > 0:
                        mins_f = float(secs_i) / 60.0

                out[model] = float(out.get(model, 0.0) or 0.0) + mins_f

        except sqlite3.OperationalError:
            cur.execute(
                """
                SELECT total_seconds
                FROM api_transcript_usage
                WHERE api_hash = ? AND model_name IN ('irannobat transcriptmodel','irannobattranscript model')
                """,
                (api_hash,),
            )
            total_sec = 0
            for (secs,) in (cur.fetchall() or []):
                try:
                    total_sec += int(secs or 0)
                except Exception:
                    pass
            if total_sec > 0:
                out["irannobat transcriptmodel"] = float(total_sec) / 60.0

    return out


# ---------------------------------------------------------------------------
# Summary HTML
# ---------------------------------------------------------------------------

def get_api_usage_summary_html(api_key: str) -> str:
    """
    Human-readable HTML summary for Welcome UI.

    - Tokens: show per-model tokens.
    - Transcript: show per-model minutes (and seconds when very small).
    """
    api_key = (api_key or "").strip()
    if not api_key:
        return "<i>No API key.</i>"

    models = load_api_token_usage_for_key(api_key)
    total_tokens = sum(int(v or 0) for v in models.values())

    tr_models = load_api_transcript_usage_for_key(api_key) or {}
    tr_vals = []
    for _, v in tr_models.items():
        try:
            tr_vals.append(float(v or 0.0))
        except Exception:
            tr_vals.append(0.0)
    total_tr_minutes = sum(x for x in tr_vals if x > 0)

    rows = get_api_usage_rows_for_key(api_key, limit=1)
    last_used = rows[0]["last_used_at"] if rows else None

    def _fmt_minutes_or_seconds(m: float) -> str:
        if m <= 0:
            return "0"
        if m < 0.1:
            sec = int(round(m * 60.0))
            sec = max(sec, 1)
            return f"{sec} sec"
        return f"{m:.1f} min"

    html = "<div style='line-height:1.5'>"
    html += f"<b>Total tokens:</b> {total_tokens:,}<br>"

    if models:
        html += "<b>Models (tokens):</b><br><ul style='margin:4px 0 4px 18px'>"
        for k, v in sorted(models.items(), key=lambda x: (x[0] or "")):
            html += f"<li>{k}: {int(v or 0):,}</li>"
        html += "</ul>"

    if tr_models:
        html += f"<b>Total transcript:</b> {_fmt_minutes_or_seconds(float(total_tr_minutes))}<br>"
        html += "<b>Models (transcript):</b><br><ul style='margin:4px 0 4px 18px'>"
        for k, v in sorted(tr_models.items(), key=lambda x: (x[0] or "")):
            try:
                mv = float(v or 0.0)
            except Exception:
                mv = 0.0
            if mv > 0:
                html += f"<li>{k}: {_fmt_minutes_or_seconds(mv)}</li>"
        html += "</ul>"

    if last_used:
        html += f"<b>Last used:</b> {last_used}<br>"

    html += "</div>"
    return html
