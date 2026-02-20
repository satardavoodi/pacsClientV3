import os
import sqlite3
import threading
import contextlib
import json
from typing import Optional
import hashlib
# from typing import Optional, Dict, Any

# Thread-local storage for database connections (for per-thread reuse)
_local = threading.local()

# Global lock for database operations
_db_lock = threading.Lock()

# Connection pool - reusable connections for high-frequency loops 
# CRITICAL FIX: Actually use the pool to prevent connection accumulation
_connection_pool = {}  # thread_id -> sqlite3.Connection
_pool_lock = threading.Lock()
_max_pool_size = 5  # Max connections per thread


@contextlib.contextmanager
def get_db_connection():
    """Context manager for database connections with automatic cleanup and pooling."""
    conn = None
    try:
        # Get connection from pool or create new one
        conn = _get_pooled_connection()
        yield conn
    except Exception as e:
        print(f"⚠️ Database error in transaction: {e}")
        if conn:
            try:
                conn.rollback()  # Rollback on error for data integrity
            except:
                pass
        raise
    finally:
        if conn:
            try:
                # Return connection to pool instead of closing (for reuse)
                _return_to_pool(conn)
            except Exception as e:
                print(f"⚠️ Error returning connection to pool: {e}")


def _get_pooled_connection():
    """Get a reusable connection from pool or create new one."""
    thread_id = threading.current_thread().ident
    
    with _pool_lock:
        if thread_id in _connection_pool:
            conns = _connection_pool[thread_id]
            if conns:
                conn = conns.pop()
                # Validate connection is still open
                try:
                    conn.execute("SELECT 1")
                    return conn
                except sqlite3.OperationalError:
                    # Connection is dead, create new one
                    pass
        
        # Create new connection if pool is empty or invalid
        return get_connection_database()


def _return_to_pool(conn):
    """Return connection to pool for reuse (or close if pool is full)."""
    thread_id = threading.current_thread().ident
    
    with _pool_lock:
        if thread_id not in _connection_pool:
            _connection_pool[thread_id] = []
        
        conns = _connection_pool[thread_id]
        if len(conns) < _max_pool_size:
            # Add back to pool for reuse
            try:
                conn.rollback()  # Ensure clean state
                conns.append(conn)
            except:
                # If rollback fails, close the connection
                try:
                    conn.close()
                except:
                    pass
        else:
            # Pool is full, close this connection
            try:
                conn.close()
            except:
                pass


def get_connection_database():
    """Return a SQLite connection **with foreign‑key constraints enabled**."""
    import time
    import random
    
    db = 'dicom.db'
    max_retries = 15  # Increased retries for better reliability
    
    for attempt in range(max_retries):
        try:
            # Use longer timeout and better connection parameters
            # CRITICAL: Using DEFERRED isolation level ensures data integrity for medical data
            conn = sqlite3.connect(
                db, 
                timeout=300.0,  # Increased timeout to 300 seconds
                check_same_thread=False,  # Allow multi-threading with proper locking
                isolation_level="DEFERRED"  # FIXED: Use DEFERRED transactions (safe default)
            )
            conn.execute("PRAGMA foreign_keys = ON;")  # Enforce referential integrity
            conn.execute("PRAGMA journal_mode = WAL;")  # Enable WAL mode for better concurrency
            conn.execute("PRAGMA synchronous = NORMAL;")  # Balanced safety/performance
            conn.execute("PRAGMA busy_timeout = 120000;")  # 120 second busy timeout
            conn.execute("PRAGMA temp_store = MEMORY;")  # Use memory for temp tables
            conn.execute("PRAGMA cache_size = -10000;")  # FIXED: 10MB cache (negative = KB)
            conn.execute("PRAGMA mmap_size = 104857600;")  # FIXED: 100MB mmap (was 512MB)
            conn.execute("PRAGMA wal_autocheckpoint = 500;")  # Checkpoint every 500 pages
            conn.execute("PRAGMA locking_mode = NORMAL;")  # Normal locking mode
            # REMOVED: PRAGMA read_uncommitted = 1 (CRITICAL: This was allowing dirty reads on medical data!)
            return conn
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                # Wait with exponential backoff and jitter
                wait_time = (2 ** attempt) + random.uniform(0, 3)
                print(f"⚠️ Database locked, retrying in {wait_time:.1f}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                print(f"❌ Database connection failed after {max_retries} attempts: {e}")
                raise
            
    
    raise sqlite3.OperationalError("Failed to connect to database after all retries")


def cleanup_connection_pools():
    """Close all pooled connections (for app shutdown or testing)."""
    global _connection_pool
    with _pool_lock:
        for thread_id, conns in _connection_pool.items():
            for conn in conns:
                try:
                    conn.close()
                except:
                    pass
        _connection_pool.clear()
        print("✅ All pooled database connections closed")



def init_database():
    """Create (if required) the four DICOM hierarchy tables."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                patient_pk     INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id     TEXT UNIQUE,
                patient_name   TEXT,
                birth_date     TEXT DEFAULT NULL,
                sex            TEXT DEFAULT NULL,
                age            TEXT DEFAULT NULL,
                patient_weight TEXT DEFAULT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS studies (
                study_pk           INTEGER PRIMARY KEY AUTOINCREMENT,
                study_uid          TEXT UNIQUE,
                patient_fk         INTEGER NOT NULL,
                study_date         TEXT DEFAULT NULL,
                study_time         TEXT DEFAULT NULL,
                study_description  TEXT DEFAULT NULL,
                institution_name   TEXT DEFAULT NULL,
                modality         TEXT DEFAULT NULL,
                body_part        TEXT DEFAULT NULL,
                number_of_series   INTEGER DEFAULT 0,
                number_of_instances INTEGER DEFAULT 0,
                study_path      TEXT DEFAULT NULL,
                attachments_uploaded TEXT DEFAULT NULL,
                FOREIGN KEY(patient_fk) REFERENCES patients(patient_pk) ON DELETE CASCADE
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS series (
                series_pk        INTEGER PRIMARY KEY AUTOINCREMENT,
                series_uid       TEXT UNIQUE,
                series_name      TEXT,
                study_fk         INTEGER NOT NULL,
                series_number    INTEGER DEFAULT NULL,
                series_thk       TEXT DEFAULT NULL,
                series_description TEXT DEFAULT NULL,
                orientation      TEXT DEFAULT NULL,
                modality         TEXT DEFAULT NULL,
                image_count      INTEGER DEFAULT 0,
                protocol_name    TEXT DEFAULT NULL,
                body_part_examined TEXT DEFAULT NULL,
                manufacturer     TEXT DEFAULT NULL,
                institution_name TEXT DEFAULT NULL,
                main_thumbnail   BOOLEAN DEFAULT 0,
                thumbnail_path   TEXT DEFAULT NULL,
                series_path      TEXT DEFAULT NULL,
                FOREIGN KEY(study_fk) REFERENCES studies(study_pk) ON DELETE CASCADE
            )
            """
        )

        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_token_usage (
                center_name TEXT NOT NULL,
                model_name  TEXT NOT NULL,
                total_tokens INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (center_name, model_name)
            )
        """)


        # Per-API (hashed) token usage table (API key itself is never stored).
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

        # Per-API transcript usage table (unit: seconds; API key itself is never stored).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS api_transcript_usage (
                api_hash       TEXT NOT NULL,
                api_mask       TEXT NOT NULL,
                center_name    TEXT DEFAULT NULL,
                model_name     TEXT NOT NULL,
                total_seconds  INTEGER DEFAULT 0,
                last_used_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (api_hash, model_name)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_api_transcript_usage_last_used ON api_transcript_usage(last_used_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_api_transcript_usage_mask ON api_transcript_usage(api_mask)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS instances (
                instance_pk     INTEGER PRIMARY KEY AUTOINCREMENT,
                sop_uid         TEXT UNIQUE,
                series_fk       INTEGER NOT NULL,
                instance_path   TEXT,
                instance_number INTEGER DEFAULT NULL,
                rows            INTEGER DEFAULT NULL,
                columns         INTEGER DEFAULT NULL,
                window_width    REAL DEFAULT 127.5,
                window_center   REAL DEFAULT 255,
                is_rgb          BOOLEAN DEFAULT 0,
                group_id        INTEGER,
                image_position_patient  TEXT DEFAULT NULL,
                image_orientation_patient  TEXT DEFAULT NULL,
                pixel_spacing  TEXT DEFAULT NULL,
                direction  TEXT DEFAULT NULL,
                FOREIGN KEY(series_fk) REFERENCES series(series_pk) ON DELETE CASCADE
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS download_progress (
                progress_pk     INTEGER PRIMARY KEY AUTOINCREMENT,
                study_uid       TEXT UNIQUE NOT NULL,
                downloaded_count INTEGER DEFAULT 0,
                total_instances INTEGER DEFAULT 0,
                progress_percent REAL DEFAULT 0.0,
                current_batch   INTEGER DEFAULT 0,
                total_batches   INTEGER DEFAULT 0,
                status          TEXT DEFAULT 'in_progress',
                last_update     TEXT DEFAULT NULL,
                created_at      TEXT DEFAULT NULL,
                completed_at    TEXT DEFAULT NULL
            )
            """
        )

        # Tools settings table for customizing reference line and measurement tools
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tools_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                settings_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Educational courses tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                course_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                course_name TEXT NOT NULL,
                course_description TEXT,
                author_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                outline TEXT,
                thumbnail_path TEXT,
                tags TEXT DEFAULT '[]',
                modality TEXT DEFAULT '',
                body_regions TEXT DEFAULT '[]',
                level TEXT DEFAULT 'Intermediate',
                is_my_course INTEGER DEFAULT 1,
                is_downloaded INTEGER DEFAULT 0,
                resource_type TEXT DEFAULT 'Course',
                content_origin TEXT DEFAULT 'local',
                validation_status TEXT DEFAULT 'ok',
                needs_attention INTEGER DEFAULT 0,
                import_source_path TEXT DEFAULT '',
                import_manifest_path TEXT DEFAULT ''
            )
        """)

        # Case of the Day (My Course) tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS case_of_day_entries (
                case_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                saved_by TEXT NOT NULL,
                modality TEXT NOT NULL,
                body_part TEXT NOT NULL,
                diagnosis TEXT NOT NULL,
                anatomical_classification TEXT DEFAULT '',
                protocol_details TEXT DEFAULT '',
                description TEXT DEFAULT '',
                differential_diagnosis TEXT DEFAULT '',
                dicom_folder_path TEXT NOT NULL,
                original_source_path TEXT DEFAULT '',
                source_type TEXT DEFAULT 'manual',
                patient_id TEXT DEFAULT '',
                study_uid TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS case_of_day_body_parts (
                body_part TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Migrate existing courses table if needed
        try:
            cur.execute("PRAGMA table_info(courses)")
            columns = [col[1] for col in cur.fetchall()]
            
            if 'tags' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN tags TEXT DEFAULT '[]'")
            if 'modality' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN modality TEXT DEFAULT ''")
            if 'body_regions' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN body_regions TEXT DEFAULT '[]'")
            if 'level' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN level TEXT DEFAULT 'Intermediate'")
            if 'is_my_course' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN is_my_course INTEGER DEFAULT 1")
            if 'is_downloaded' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN is_downloaded INTEGER DEFAULT 0")
            if 'resource_type' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN resource_type TEXT DEFAULT 'Course'")
            if 'content_origin' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN content_origin TEXT DEFAULT 'local'")
            if 'validation_status' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN validation_status TEXT DEFAULT 'ok'")
            if 'needs_attention' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN needs_attention INTEGER DEFAULT 0")
            if 'import_source_path' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN import_source_path TEXT DEFAULT ''")
            if 'import_manifest_path' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN import_manifest_path TEXT DEFAULT ''")
        except Exception as e:
            print(f"Migration warning: {e}")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS slides (
                slide_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                course_fk INTEGER NOT NULL,
                slide_order INTEGER NOT NULL,
                slide_title TEXT,
                slide_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(course_fk) REFERENCES courses(course_pk) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS slide_content (
                content_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                slide_fk INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                content_order INTEGER NOT NULL,
                content_data TEXT NOT NULL,
                layout_position TEXT,
                FOREIGN KEY(slide_fk) REFERENCES slides(slide_pk) ON DELETE CASCADE
            )
        """)

        conn.commit()
        
        # Ensure report status schema exists
        ensure_report_status_schema()

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


def _ensure_transcript_usage_tables(conn: sqlite3.Connection) -> None:
    """Ensure transcript-usage tables exist.

    Transcript usage is tracked in **seconds** and also redundantly in **minutes**
    (for easy reporting). Older DBs may only have total_seconds; we migrate safely.
    """
    cur = conn.cursor()

    # --- create tables (new schema includes total_minutes) ---
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

    # --- lightweight migration for older DBs (add missing columns) ---
    def _ensure_col(table: str, col: str, ddl: str) -> None:
        try:
            cur.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in cur.fetchall()]
            if col not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        except Exception:
            # never break app startup for migration issues
            return

    _ensure_col("user_transcript_usage", "total_minutes", "total_minutes REAL DEFAULT 0")
    _ensure_col("api_transcript_usage", "total_minutes", "total_minutes REAL DEFAULT 0")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_transcript_usage_last_used ON api_transcript_usage(last_used_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_transcript_usage_mask ON api_transcript_usage(api_mask)")


def add_transcript_usage_delta(center_name: str, model_name: str, seconds_delta: int) -> None:
    """Increment transcript usage for a center+model.

    Stores:
      - total_seconds (INTEGER)
      - total_minutes (REAL, derived from seconds)
    """
    if not center_name:
        center_name = "<unknown>"
    model_name = (model_name or "").strip()

    # Canonical transcript model name (merge old name into new name)
    if model_name == "irannobattranscript model":
        model_name = "irannobat transcriptmodel"
    if model_name == "":
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
        except sqlite3.OperationalError:
            # fallback for very old DBs without total_minutes
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
def _hash_and_mask_api_key(api_key: str) -> tuple[str, str]:
    """Return (api_hash, api_mask) using existing helpers."""
    return _hash_api_key(api_key), _mask_api_key(api_key)

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
            "api": r[0],
            "center": r[1],
            "model": r[2],
            "tokens": int(r[3] or 0),
            "last_used_at": r[4],
        }
        for r in rows
    ]

def add_api_transcript_usage_delta(api_key: str, center_name: str, model_name: str, seconds_delta: int) -> None:
    api_key = (api_key or "").strip()
    if not api_key:
        return

    # ✅ نام مدل دقیق طبق خواسته شما
    model_name = "irannobat transcriptmodel"

    try:
        sec_f = float(seconds_delta or 0)
    except Exception:
        return
    sec = int(round(sec_f))
    if sec <= 0:
        return

    mins = float(sec) / 60.0
    api_hash, api_mask = _hash_and_mask_api_key(api_key)  # ✅ now exists
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

def load_api_transcript_usage_for_key(api_key: str) -> dict:
    """{model: minutes} for a single api_key (by hash)."""
    api_key = (api_key or "").strip()
    if not api_key:
        return {}

    api_hash, _ = _hash_and_mask_api_key(api_key)  # ✅ now exists
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
                # ✅ canonical
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
            # old DB: only total_seconds
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
            "api": r[0],
            "center": r[1],
            "model": r[2],
            "tokens": int(r[3] or 0),
            "last_used_at": r[4],
        }
        for r in rows
    ]
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

    # transcript usage is returned as {model: minutes}
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
        # اگر خیلی کم بود، ثانیه نشان بده تا صفر دیده نشود
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

    # ✅ همیشه اگر tr_models چیزی داشت، نمایش بده (حتی اگر خیلی کم باشد)
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


def insert_patient(patient_id: str, name: str, birth_date: str = None, sex: str = None, age: str = None,
                   patient_weight: str = None) -> int:
    """Insert a patient and return its primary key (PK).

    Uses ``INSERT OR IGNORE`` to prevent duplicates based on ``patient_id``.
    If the record already exists, the existing PK is returned.
    """
    conn = get_connection_database()
    cur = conn.cursor()
    #
    cur.execute(
        """
        INSERT OR IGNORE INTO patients
            (patient_id, patient_name, birth_date, sex, age, patient_weight)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (patient_id, name, birth_date, sex, age, patient_weight),
    )
    conn.commit()

    # Retrieve PK (either new or existing)
    cur.execute("SELECT patient_pk FROM patients WHERE patient_id = ?", (patient_id,))
    return cur.fetchone()[0]


def insert_study(study_uid: str, patient_fk: int, study_date: str = None, study_time: str = None,
                 study_description: str = None, institution_name: str = None, modality: str = None,
                  body_part: str = None, number_of_series: int = 0,
                 number_of_instances: int = 0, study_path: str = None) -> int:

    """Insert a study row and return its PK. Updates study_path if study already exists."""
    conn = get_connection_database()
    cur = conn.cursor()

    try:
        # Try to insert the study
        cur.execute(
            """
            INSERT INTO studies
                (study_uid, patient_fk, study_date, study_time, study_description,
                 institution_name, modality, body_part, number_of_series, number_of_instances, study_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                study_uid,
                patient_fk,
                study_date,
                study_time,
                study_description,
                institution_name,
                modality,
                body_part,
                number_of_series,
                number_of_instances,
                study_path,
            ),
        )
        # If insert succeeded, get the new study_pk
        study_pk = cur.lastrowid
    except sqlite3.IntegrityError:
        # If we get a unique constraint error, update the existing record
        cur.execute(
            """
            UPDATE studies
            SET patient_fk = ?, study_date = ?, study_time = ?, study_description = ?,
                institution_name = ?, modality = ?, body_part = ?,
                number_of_series = ?, number_of_instances = ?,
                study_path = COALESCE(?, study_path)
            WHERE study_uid = ?
            """,
            (
                patient_fk, study_date, study_time, study_description,
                institution_name, modality, body_part,
                number_of_series, number_of_instances,
                study_path, study_uid
            )
        )
        # Get the study_pk of the existing record
        cur.execute("SELECT study_pk FROM studies WHERE study_uid = ?", (study_uid,))
        study_pk = cur.fetchone()[0]

    conn.commit()
    return study_pk


def migrate_fix_null_study_paths() -> dict:
    """
    Migration function to fix studies with NULL study_path by checking disk.
    
    When studies are imported from Socket/PACS, they may have study_path=NULL in the database.
    This function:
    1. Finds all studies with study_path IS NULL
    2. Checks if files exist on disk at SOURCE_PATH/{study_uid}
    3. Updates database with correct study_path if files exist
    
    Returns:
        dict: {'updated': count, 'checked': count, 'not_found': count}
    """
    from PacsClient.utils.config import SOURCE_PATH
    from pathlib import Path
    import logging
    
    logger = logging.getLogger(__name__)
    # Silent migration - only reports summary at end
    logger.debug("=" * 80)
    logger.debug("🔧 [MIGRATION] Starting study_path NULL fix migration...")
    logger.debug("=" * 80)
    
    try:
        conn = get_connection_database()
        cur = conn.cursor()
        
        # Find all studies with NULL study_path
        cur.execute("""
            SELECT s.study_pk, s.study_uid, s.patient_fk, p.patient_name
            FROM studies s
            LEFT JOIN patients p ON s.patient_fk = p.patient_pk
            WHERE s.study_path IS NULL
            ORDER BY s.study_pk
        """)
        
        null_studies = cur.fetchall()
        logger.debug(f"📋 Found {len(null_studies)} studies with NULL study_path")
        
        if not null_studies:
            logger.debug("✅ No studies with NULL study_path found")
            return {'updated': 0, 'checked': 0, 'not_found': 0}
        
        updated = 0
        not_found = 0
        
        for study_pk, study_uid, patient_fk, patient_name in null_studies:
            try:
                # Check if study files exist on disk
                if study_uid:
                    potential_path = Path(SOURCE_PATH) / study_uid
                    if potential_path.exists():
                        # Update study_path in database
                        cur.execute("""
                            UPDATE studies
                            SET study_path = ?
                            WHERE study_pk = ?
                        """, (str(potential_path), study_pk))
                        
                        logger.debug(f"✅ Updated: {patient_name} ({study_uid[:40]}...)")
                        logger.debug(f"   Path: {potential_path}")
                        updated += 1
                    else:
                        # Silently count missing studies - they may be archived or deleted
                        logger.debug(f"❌ Not found: {patient_name} ({study_uid[:40]}...)")
                        logger.debug(f"   Expected path: {potential_path}")
                        not_found += 1
                else:
                    logger.debug(f"❌ No study_uid for study_pk={study_pk}")
                    not_found += 1
                    
            except Exception as e:
                logger.error(f"❌ Error processing study_pk={study_pk}: {e}")
                not_found += 1
        
        # Commit all changes
        conn.commit()
        
        # Only show summary if there were changes or issues
        if updated > 0 or not_found > 0:
            logger.info("-" * 80)
            logger.info(f"📊 Migration Summary:")
            if updated > 0:
                logger.info(f"   ✅ Updated: {updated}")
            if not_found > 0:
                logger.info(f"   ⚠️  Not found on disk: {not_found}")
            logger.info(f"   📋 Total checked: {len(null_studies)}")
            logger.info("=" * 80)
        
        return {
            'updated': updated,
            'checked': len(null_studies),
            'not_found': not_found
        }
        
    except Exception as e:
        logger.error(f"❌ Migration error: {e}")
        import traceback
        traceback.print_exc()
        return {'updated': 0, 'checked': 0, 'not_found': 0, 'error': str(e)}


def insert_series(series_uid: str, study_fk: int, series_name: str = None, series_number: str = None,
                  series_thk: str = None, series_description: str = None, orientation: str = None,
                  modality: str = None, image_count: int = 0, protocol_name: str = None,
                  body_part_examined: str = None, manufacturer: str = None, institution_name: str = None,
                  main_thumbnail: bool = False, thumbnail_path: str = None, series_path: str = None) -> int:
    """Insert a series row and return its PK. Updates series_path if series already exists."""
    conn = get_connection_database()
    cur = conn.cursor()

    # First, try to insert the series
    try:
        cur.execute(
            """
            INSERT INTO series
                (series_uid, series_name, study_fk, series_number,
                 series_thk, series_description, orientation, modality, image_count,
                 protocol_name, body_part_examined, manufacturer, institution_name,
                 main_thumbnail, thumbnail_path, series_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                series_uid,
                series_name,
                study_fk,
                series_number,
                series_thk,
                series_description,
                orientation,
                modality,
                image_count,
                protocol_name,
                body_part_examined,
                manufacturer,
                institution_name,
                int(main_thumbnail),
                thumbnail_path,
                series_path,
            ),
        )
        # If insert succeeded, get the new series_pk
        series_pk = cur.lastrowid
    except sqlite3.IntegrityError:
        # If we get a unique constraint error, update the existing record
        cur.execute(
            """
            UPDATE series
            SET study_fk = ?, series_name = ?, series_number = ?, series_thk = ?,
                series_description = ?, orientation = ?, modality = ?, image_count = ?,
                protocol_name = ?, body_part_examined = ?, manufacturer = ?,
                institution_name = ?, main_thumbnail = ?, thumbnail_path = ?,
                series_path = COALESCE(?, series_path)
            WHERE series_uid = ?
            """,
            (
                study_fk, series_name, series_number, series_thk,
                series_description, orientation, modality, image_count,
                protocol_name, body_part_examined, manufacturer,
                institution_name, int(main_thumbnail), thumbnail_path,
                series_path, series_uid
            )
        )
        # Get the series_pk of the existing record
        cur.execute("SELECT series_pk FROM series WHERE series_uid = ?", (series_uid,))
        series_pk = cur.fetchone()[0]

    conn.commit()
    return series_pk


def insert_instances_batch(instances: list) -> int:
    """
    Insert multiple instances in a single transaction (MUCH faster than individual inserts)
    
    ✅ PHASE 3: Batch insert optimization - 50-100x faster than individual inserts
    
    Args:
        instances: List of dicts with keys: sop_uid, series_fk, instance_path, 
                   instance_number, rows, columns
                   
    Returns:
        Number of instances inserted
    """
    if not instances:
        return 0
    
    conn = get_connection_database()
    cur = conn.cursor()
    
    try:
        # Batch insert using executemany
        insert_data = []
        for inst in instances:
            insert_data.append((
                inst.get('sop_uid'),
                inst.get('series_fk'),
                inst.get('instance_path'),
                inst.get('instance_number'),
                inst.get('rows'),
                inst.get('columns'),
                inst.get('window_width'),       # None if not provided (viewer will auto-calculate)
                inst.get('window_center'),      # None if not provided (viewer will auto-calculate)
                inst.get('is_rgb', False),
                inst.get('group_id', 0),
                inst.get('image_position_patient'),
                inst.get('image_orientation_patient'),
                inst.get('pixel_spacing'),
                inst.get('direction')
            ))
        
        cur.executemany(
            """
            INSERT OR REPLACE INTO instances
                (sop_uid, series_fk, instance_path, instance_number, rows, columns,
                 window_width, window_center, is_rgb, group_id, 
                 image_position_patient, image_orientation_patient, pixel_spacing, direction)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_data
        )
        
        conn.commit()
        inserted_count = len(insert_data)
        # logger.info(f"✅ Batch inserted {inserted_count} instances")
        return inserted_count
        
    except Exception as e:
        conn.rollback()
        import logging
        logging.getLogger(__name__).error(f"❌ Batch insert failed: {e}")
        raise


def insert_instance(sop_uid: str, series_fk: int, instance_path: str, instance_number: int = None, rows: int = None,
                    columns: int = None, window_width: float = None, window_center: float = None,
                    is_rgb: bool = False, group_id=0, image_position_patient=None,
                    image_orientation_patient=None, pixel_spacing=None, direction=None) -> int:

    """Insert an instance row and return its PK. Updates metadata if instance already exists.
    
    Lists (image_position_patient, image_orientation_patient, pixel_spacing, direction) 
    are stored as JSON strings for proper serialization.
    """
    conn = get_connection_database()
    cur = conn.cursor()
    
    # Helper function to serialize lists to JSON
    def serialize_value(value):
        """Convert list/tuple to JSON string, keep None as None, convert other values to string."""
        if value is None:
            return None
        elif isinstance(value, (list, tuple)):
            # Convert to JSON string for proper storage
            return json.dumps(value)
        else:
            # For other types (like numpy arrays), convert to list first
            try:
                return json.dumps(list(value))
            except (TypeError, ValueError):
                # If conversion fails, return as string
                return str(value)
    
    # Serialize all list-based parameters
    image_position_json = serialize_value(image_position_patient)
    image_orientation_json = serialize_value(image_orientation_patient)
    pixel_spacing_json = serialize_value(pixel_spacing)
    direction_json = serialize_value(direction)
    
    try:
        # Try to insert the instance
        cur.execute(
            """
            INSERT INTO instances
                (sop_uid, series_fk, instance_path, instance_number, rows, columns,
                 window_width, window_center, is_rgb, group_id, image_position_patient,
                  image_orientation_patient, pixel_spacing, direction)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sop_uid,
                series_fk,
                instance_path,
                instance_number,
                rows,
                columns,
                window_width,
                window_center,
                int(is_rgb),
                int(group_id),
                image_position_json,
                image_orientation_json,
                pixel_spacing_json,
                direction_json
            ),
        )
        # If insert succeeded, get the new instance_pk
        instance_pk = cur.lastrowid
    except sqlite3.IntegrityError:
        # If we get a unique constraint error, update the existing record
        cur.execute(
            """
            UPDATE instances
            SET series_fk = ?, instance_path = ?, instance_number = ?,
                rows = COALESCE(?, rows), columns = COALESCE(?, columns),
                window_width = ?, window_center = ?, is_rgb = ?, group_id = ?,
                image_position_patient = COALESCE(?, image_position_patient),
                image_orientation_patient = COALESCE(?, image_orientation_patient),
                pixel_spacing = COALESCE(?, pixel_spacing),
                direction = COALESCE(?, direction)
            WHERE sop_uid = ?
            """,
            (
                series_fk, instance_path, instance_number,
                rows, columns,
                window_width, window_center, int(is_rgb), int(group_id),
                image_position_json, image_orientation_json,
                pixel_spacing_json, direction_json,
                sop_uid
            )
        )
        # Get the instance_pk of the existing record
        cur.execute("SELECT instance_pk FROM instances WHERE sop_uid = ?", (sop_uid,))
        instance_pk = cur.fetchone()[0]

    conn.commit()
    return instance_pk

# -----------------------------------------------------------------------------
# Helper functions for JSON serialization/deserialization
# -----------------------------------------------------------------------------

# =============================
# AI Chat storage: schema + CRUD
# =============================
def ai_ensure_schema():
    """
    Ensure AI chat tables exist and include study scoping + timestamps.

    Tables:
      - ai_sessions(sid PK, title, server_sid, study_uid, pinned, created_at, updated_at)
      - ai_messages(id PK, sid, who, html, created_at, origin)
      - ai_reports(id PK, sid, msg_id, study_uid, kind, label, raw_en, created_at)
      - ai_last_session(study_uid PK, sid)   # last opened per study
      - ai_meta(k PK, v)                      # global key/value (e.g. last_session)
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
    # add study_uid if missing
    try:
        cur.execute("SELECT study_uid FROM ai_sessions LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE ai_sessions ADD COLUMN study_uid TEXT")

    # add pinned flag (0/1)
    try:
        cur.execute("SELECT pinned FROM ai_sessions LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE ai_sessions ADD COLUMN pinned INTEGER DEFAULT 0")
        cur.execute("UPDATE ai_sessions SET pinned = 0 WHERE pinned IS NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_sessions_pinned ON ai_sessions(pinned)")

    # add created_at
    try:
        cur.execute("SELECT created_at FROM ai_sessions LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE ai_sessions ADD COLUMN created_at INTEGER")
        cur.execute("UPDATE ai_sessions SET created_at = strftime('%s','now') WHERE created_at IS NULL")

    # add updated_at
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
            ts INTEGER,      -- برای سازگاری نسخه‌های قدیمی
            origin TEXT
        )
    """)
    # add created_at
    try:
        cur.execute("SELECT created_at FROM ai_messages LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE ai_messages ADD COLUMN created_at INTEGER")
        # migrate ts -> created_at اگر ts موجود است
        cur.execute("UPDATE ai_messages SET created_at = COALESCE(ts, strftime('%s','now')) WHERE created_at IS NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_messages_sid ON ai_messages(sid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_messages_created ON ai_messages(created_at)")

    # reports (raw EN JSON for persistence of collections/corrections/persian)
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
    # add created_at if missing (older dev DBs)
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

    # global meta (e.g. last_session)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_meta(
            k TEXT PRIMARY KEY,
            v TEXT
        )
    """)

    # Reception reports table (for AI-generated reports sent to reception)
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



def ensure_report_status_schema():
    """
    Ensure report status fields exist in studies table.
    Adds reportStatus and reportStatusHistory columns if they don't exist.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    conn = get_connection_database()
    cur = conn.cursor()
    
    # Add reportStatus column if missing
    try:
        cur.execute("SELECT reportStatus FROM studies LIMIT 1")
    except:
        cur.execute("ALTER TABLE studies ADD COLUMN reportStatus TEXT DEFAULT 'pending'")
        # Update existing studies to have 'pending' status
        cur.execute("UPDATE studies SET reportStatus = 'pending' WHERE reportStatus IS NULL")
        logger.info("✅ Added reportStatus column to studies table")
    
    # Add reportStatusHistory column if missing (stored as JSON text)
    try:
        cur.execute("SELECT reportStatusHistory FROM studies LIMIT 1")
    except:
        cur.execute("ALTER TABLE studies ADD COLUMN reportStatusHistory TEXT DEFAULT '[]'")
        # Initialize empty history for existing studies
        cur.execute("UPDATE studies SET reportStatusHistory = '[]' WHERE reportStatusHistory IS NULL")
        logger.info("✅ Added reportStatusHistory column to studies table")
    
    # Add updatedAt column if missing (for tracking when status was last updated)
    try:
        cur.execute("SELECT reportStatusUpdatedAt FROM studies LIMIT 1")
    except:
        cur.execute("ALTER TABLE studies ADD COLUMN reportStatusUpdatedAt TEXT DEFAULT NULL")
        logger.info("✅ Added reportStatusUpdatedAt column to studies table")
    
    # Create indexes for better query performance
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_studies_reportStatus ON studies(reportStatus)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_studies_reportStatus_date ON studies(reportStatus, study_date)")
        logger.info("✅ Created indexes for report status")
    except Exception as e:
        logger.warning(f"⚠️ Could not create indexes: {e}")
    
    conn.commit()


# در بخش AI Chat storage: schema + CRUD (کنار بقیه توابع)
def ai_backfill_sessions_from_messages():
    """
    اگر پیامی با sid ای وجود داشته باشد که در ai_sessions ثبت نشده،
    یک ردیف مینیمال برایش می‌سازیم تا در لیست سشن‌ها ظاهر شود.
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


def ai_set_server_sid(sid: str, server_sid: str | None):
    with get_db_connection() as conn:
        conn.execute("UPDATE ai_sessions SET server_sid=? WHERE sid=?", (server_sid, sid))


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


def ai_append_message(sid: str, who: str, html: str, ts: int | None = None, origin: str | None = None) -> int:
    import time
    created = int(time.time()) if ts is None else int(ts)
    with get_db_connection() as conn:
        ai_upsert_session(sid)  # ensure session exists
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ai_messages(sid, who, html, created_at, origin) VALUES(?,?,?,?,?)",
            (sid, who, html, created, origin)
        )
        msg_id = int(cur.lastrowid)
        conn.execute("UPDATE ai_sessions SET updated_at=? WHERE sid=?", (int(time.time()), sid))
        conn.commit()
        return msg_id


def ai_update_message(msg_id: int, new_html: str):
    with get_db_connection() as conn:
        conn.execute("UPDATE ai_messages SET html=? WHERE id=?", (new_html, msg_id))


def ai_fetch_messages_full(sid: str) -> list[tuple[int, str, str, str | None]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, who, html, origin FROM ai_messages WHERE sid=? ORDER BY created_at ASC, id ASC",
            (sid,)
        )
        rows = cur.fetchall()
        return [(int(r[0]), r[1], r[2], r[3]) for r in rows]

def ai_fetch_messages(sid: str) -> list[tuple[str, str]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT who, html FROM ai_messages WHERE sid=? ORDER BY created_at ASC, id ASC", (sid,))
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


def ai_fetch_all_sessions() -> list[tuple[str, str | None]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT sid, COALESCE(title,'New Chat')
            FROM ai_sessions
            ORDER BY COALESCE(pinned, 0) DESC, COALESCE(updated_at, created_at, rowid) DESC
        """)
        return cur.fetchall()

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
            # unpin all in this study
            cur.execute("UPDATE ai_sessions SET pinned=0 WHERE study_uid=?", (study_uid,))
            if pinned_sids:
                ph = ",".join(["?"] * len(pinned_sids))
                # pin only those in this study
                cur.execute(
                    f"UPDATE ai_sessions SET pinned=1 WHERE study_uid=? AND sid IN ({ph})",
                    (study_uid, *pinned_sids)
                )
        else:
            # global: unpin all
            cur.execute("UPDATE ai_sessions SET pinned=0")
            if pinned_sids:
                ph = ",".join(["?"] * len(pinned_sids))
                cur.execute(
                    f"UPDATE ai_sessions SET pinned=1 WHERE sid IN ({ph})",
                    (*pinned_sids,)
                )


def ai_delete_session_and_messages(sid: str):
    """Hard-delete a session + all its messages/reports and cleanup last_session pointers."""
    if not sid:
        return
    with get_db_connection() as conn:
        cur = conn.cursor()

        # cleanup per-study last-session pointers
        cur.execute("DELETE FROM ai_last_session WHERE sid=?", (sid,))

        # cleanup global last_session meta
        try:
            cur.execute("SELECT v FROM ai_meta WHERE k='last_session'")
            row = cur.fetchone()
            if row and (row[0] == sid):
                cur.execute("DELETE FROM ai_meta WHERE k='last_session'")
        except Exception:
            pass

        # delete reports + messages first, then session
        try:
            cur.execute("DELETE FROM ai_reports WHERE sid=?", (sid,))
        except Exception:
            pass
        cur.execute("DELETE FROM ai_messages WHERE sid=?", (sid,))
        cur.execute("DELETE FROM ai_sessions WHERE sid=?", (sid,))


def ai_set_last_session(sid: str):
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO ai_meta(k, v) VALUES('last_session', ?)
            ON CONFLICT(k) DO UPDATE SET v=excluded.v
        """, (sid,))

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

    Why:
      - Collections/corrections must NOT depend on UI bubbles.
      - Persian/Edit on old report bubbles requires access to the raw EN JSON.

    Dedup rule:
      - If msg_id is provided, we keep at most one row per msg_id (replace).
    """
    import time
    if not sid or not (raw_en or "").strip():
        return None

    created = int(time.time()) if ts is None else int(ts)
    raw_en = (raw_en or "").strip()

    with get_db_connection() as conn:
        cur = conn.cursor()

        # ensure session exists and study_uid is set if provided
        try:
            ai_upsert_session(sid, None, study_uid)
        except Exception:
            try:
                ai_upsert_session(sid)
            except Exception:
                pass

        # replace-by-msg_id (best effort)
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


def ai_fetch_reports_for_session(sid: str, *, kind: str = "report") -> list[tuple[int, int | None, str | None, str, int | None]]:
    """
    Returns rows:
      (report_id, msg_id, label, raw_en, created_at)
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
            # if kind column doesn't exist for some reason
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


def ai_fetch_reports_for_study(study_uid: str, *, kind: str = "report") -> list[tuple[int, str, int | None, str | None, str, int | None]]:
    """
    Fetch reports across all sessions of a study.
    Returns rows:
      (report_id, sid, msg_id, label, raw_en, created_at)
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


def ai_get_last_session() -> str | None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT v FROM ai_meta WHERE k='last_session'")
        row = cur.fetchone()
        return row[0] if row else None


# -----------------------------------------------------------------------------
# AI Secretary audit log
# -----------------------------------------------------------------------------
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
                int(time.time()),
                sid,
                source_tab,
                command_text,
                stt_route_requested,
                stt_route_used,
                intent,
                _to_json(entities_json),
                _to_json(action_json),
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
                1 if confirmed else 0,
                status,
                error_code,
                error_text,
                int(result_count or 0),
                int(latency_ms or 0),
                int(action_id),
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


# -----------------------------------------------------------------------------
# AI Reception Reports (for sending AI reports to Reception panel)
# -----------------------------------------------------------------------------

def ai_save_reception_report(
    patient_id: str,
    html_content: str,
    study_uid: str | None = None,
    session_id: str | None = None,
    msg_id: int | None = None,
    sender_info: str | None = None
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
    import logging
    
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("AI_SAVE_RECEPTION_REPORT - START")
    logger.info("=" * 80)
    logger.info(f"→ Patient ID: {patient_id}")
    logger.info(f"→ Study UID: {study_uid}")
    logger.info(f"→ Session ID: {session_id}")
    logger.info(f"→ Message ID: {msg_id}")
    logger.info(f"→ Sender Info: {sender_info}")
    logger.info(f"→ Content length: {len(html_content) if html_content else 0} chars")
    logger.info(f"→ Content preview: {(html_content[:200] + '...' if len(html_content) > 200 else html_content) if html_content else 'None'}")

    with get_db_connection() as conn:
        cur = conn.cursor()
        created_at = int(time.time())

        logger.info(f"→ About to execute INSERT query at timestamp: {created_at}")
        
        cur.execute("""
            INSERT INTO ai_reception_reports
            (patient_id, study_uid, html_content, session_id, msg_id, status, created_at, sender_info)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (patient_id, study_uid, html_content, session_id, msg_id, created_at, sender_info))

        conn.commit()
        report_id = cur.lastrowid
        
        logger.info(f"→ INSERT successful, report_id: {report_id}")
        logger.info("=" * 80)
        logger.info("AI_SAVE_RECEPTION_REPORT - COMPLETED SUCCESSFULLY")
        logger.info(f"  • Report ID: {report_id}")
        logger.info(f"  • Patient ID: {patient_id}")
        logger.info(f"  • Status: pending")
        logger.info(f"  • Created at: {created_at}")
        logger.info("=" * 80)

        return report_id


def ai_get_reception_reports(
    patient_id: str | None = None,
    study_uid: str | None = None,
    status: str | None = None,
    limit: int | None = None
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
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("AI_GET_RECEPTION_REPORTS - START")
    logger.info("=" * 80)
    logger.info(f"→ Patient ID: {patient_id}")
    logger.info(f"→ Study UID: {study_uid}")
    logger.info(f"→ Status: {status}")
    logger.info(f"→ Limit: {limit}")

    with get_db_connection() as conn:
        cur = conn.cursor()

        query = "SELECT * FROM ai_reception_reports WHERE 1=1"
        params = []

        if patient_id:
            query += " AND patient_id = ?"
            params.append(patient_id)
            logger.info(f"  • Added patient_id filter: {patient_id}")

        if study_uid:
            query += " AND study_uid = ?"
            params.append(study_uid)
            logger.info(f"  • Added study_uid filter: {study_uid}")

        if status:
            query += " AND status = ?"
            params.append(status)
            logger.info(f"  • Added status filter: {status}")

        query += " ORDER BY created_at DESC"
        logger.info(f"  • Query: {query}")

        if limit:
            query += f" LIMIT {int(limit)}"
            logger.info(f"  • Added limit: {limit}")

        logger.info(f"→ Executing query with params: {params}")
        cur.execute(query, params)
        rows = cur.fetchall()

        logger.info(f"→ Query returned {len(rows)} rows")

        if not rows:
            logger.info("→ No reports found in database")
            logger.info("=" * 80)
            logger.info("AI_GET_RECEPTION_REPORTS - COMPLETED (NO RESULTS)")
            logger.info("=" * 80)
            return []

        # Convert to dictionaries
        columns = [desc[0] for desc in cur.description]
        result = [dict(zip(columns, row)) for row in rows]
        
        logger.info(f"→ Converted {len(result)} rows to dictionaries")
        logger.info(f"→ Sample report IDs: {[r.get('id') for r in result[:3]]}")  # Show first 3 report IDs
        logger.info("=" * 80)
        logger.info("AI_GET_RECEPTION_REPORTS - COMPLETED SUCCESSFULLY")
        logger.info(f"  • Total reports returned: {len(result)}")
        logger.info(f"  • Columns: {columns}")
        logger.info("=" * 80)

        return result


def ai_mark_reception_report_read(report_id: int):
    """
    Mark a reception report as read.

    Args:
        report_id: Report ID to mark as read
    """
    import time
    import logging
    
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("AI_MARK_RECEPTION_REPORT_READ - START")
    logger.info("=" * 80)
    logger.info(f"→ Report ID: {report_id}")
    logger.info(f"→ Current timestamp: {int(time.time())}")

    with get_db_connection() as conn:
        cur = conn.cursor()
        read_at = int(time.time())

        logger.info(f"→ About to execute UPDATE query for report_id: {report_id}")
        
        cur.execute("""
            UPDATE ai_reception_reports
            SET status = 'read', read_at = ?
            WHERE id = ?
        """, (read_at, report_id))

        conn.commit()
        rows_affected = cur.rowcount
        
        logger.info(f"→ UPDATE successful, rows affected: {rows_affected}")
        logger.info("=" * 80)
        logger.info("AI_MARK_RECEPTION_REPORT_READ - COMPLETED")
        logger.info(f"  • Report ID: {report_id}")
        logger.info(f"  • Rows affected: {rows_affected}")
        logger.info(f"  • New status: read")
        logger.info(f"  • Read at: {read_at}")
        logger.info("=" * 80)


def ai_update_reception_report_status(report_id: int, status: str):
    """
    Update reception report status.

    Args:
        report_id: Report ID
        status: New status ('pending', 'read', 'archived')

    Returns:
        bool: True if successful
    """
    import time
    import logging
    
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("AI_UPDATE_RECEPTION_REPORT_STATUS - START")
    logger.info("=" * 80)
    logger.info(f"→ Report ID: {report_id}")
    logger.info(f"→ New Status: {status}")
    logger.info(f"→ Current timestamp: {int(time.time())}")

    with get_db_connection() as conn:
        cur = conn.cursor()

        logger.info(f"→ About to execute UPDATE query for report_id: {report_id}, new status: {status}")
        
        cur.execute("""
            UPDATE ai_reception_reports
            SET status = ?, updated_at = ?
            WHERE id = ?
        """, (status, int(time.time()), report_id))

        conn.commit()
        rows_affected = cur.rowcount
        
        logger.info(f"→ UPDATE successful, rows affected: {rows_affected}")
        logger.info("=" * 80)
        logger.info("AI_UPDATE_RECEPTION_REPORT_STATUS - COMPLETED")
        logger.info(f"  • Report ID: {report_id}")
        logger.info(f"  • New Status: {status}")
        logger.info(f"  • Rows affected: {rows_affected}")
        logger.info(f"  • Success: {rows_affected > 0}")
        logger.info("=" * 80)
        
        return cur.rowcount > 0


def ai_delete_reception_report(report_id: int):
    """
    Delete a reception report.

    Args:
        report_id: Report ID to delete

    Returns:
        bool: True if successful
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("AI_DELETE_RECEPTION_REPORT - START")
    logger.info("=" * 80)
    logger.info(f"→ Report ID: {report_id}")

    with get_db_connection() as conn:
        cur = conn.cursor()

        logger.info(f"→ About to execute DELETE query for report_id: {report_id}")
        
        cur.execute("DELETE FROM ai_reception_reports WHERE id = ?", (report_id,))
        conn.commit()
        rows_affected = cur.rowcount
        
        logger.info(f"→ DELETE successful, rows affected: {rows_affected}")
        logger.info("=" * 80)
        logger.info("AI_DELETE_RECEPTION_REPORT - COMPLETED")
        logger.info(f"  • Report ID: {report_id}")
        logger.info(f"  • Rows affected: {rows_affected}")
        logger.info(f"  • Success: {rows_affected > 0}")
        logger.info("=" * 80)
        
        return cur.rowcount > 0


def ai_get_pending_reception_reports_count(patient_id: str | None = None) -> int:
    """
    Get count of pending reception reports.

    Args:
        patient_id: Filter by patient ID (optional)

    Returns:
        Number of pending reports
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("AI_GET_PENDING_RECEPTION_REPORTS_COUNT - START")
    logger.info("=" * 80)
    logger.info(f"→ Patient ID: {patient_id}")

    with get_db_connection() as conn:
        cur = conn.cursor()

        if patient_id:
            logger.info(f"→ About to execute COUNT query for patient_id: {patient_id}")
            cur.execute("""
                SELECT COUNT(*) FROM ai_reception_reports
                WHERE patient_id = ? AND status = 'pending'
            """, (patient_id,))
        else:
            logger.info(f"→ About to execute COUNT query for all patients")
            cur.execute("""
                SELECT COUNT(*) FROM ai_reception_reports
                WHERE status = 'pending'
            """)

        row = cur.fetchone()
        count = row[0] if row else 0
        
        logger.info(f"→ COUNT query returned: {count}")
        logger.info("=" * 80)
        logger.info("AI_GET_PENDING_RECEPTION_REPORTS_COUNT - COMPLETED")
        logger.info(f"  • Patient ID: {patient_id}")
        logger.info(f"  • Pending reports count: {count}")
        logger.info("=" * 80)
        
        return count



def deserialize_instance_metadata(instance_row: dict) -> dict:
    """
    Deserialize JSON fields in an instance row.

    Args:
        instance_row: Dictionary containing instance data from database
        
    Returns:
        Dictionary with JSON fields deserialized to Python objects
    """
    if not instance_row:
        return instance_row
    
    # Fields that are stored as JSON
    json_fields = ['image_position_patient', 'image_orientation_patient', 'pixel_spacing', 'direction']
    
    for field in json_fields:
        if field in instance_row and instance_row[field] is not None:
            try:
                # Try to parse as JSON
                if isinstance(instance_row[field], str):
                    instance_row[field] = json.loads(instance_row[field])
            except (json.JSONDecodeError, ValueError):
                # If parsing fails, keep as-is
                pass
    
    return instance_row

# -----------------------------------------------------------------------------
# Utility queries
# -----------------------------------------------------------------------------


def get_all_patients() -> list:
    """Return *all* patients as list of dictionaries."""
    conn = get_connection_database()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT
            p.*,
            s.*
        FROM patients p
        LEFT JOIN studies s ON p.patient_pk = s.patient_fk
        ORDER BY p.patient_name, s.study_date DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_patients_local(search_data: dict) -> list:
    """
    Search patients in local database with filters.
    
    Args:
        search_data: Dictionary containing search criteria:
            - patient_id: Patient ID (partial match)
            - patient_name: Patient Name (partial match)
            - patient_sex: Patient Sex (M/F/O)
            - study_id: Study ID (partial match)
            - date_from: Start date in YYYYMMDD format
            - date_to: End date in YYYYMMDD format
            - study_description: Study Description (partial match)
            - series_description: Series Description (partial match)
            - modality: Comma-separated modalities (e.g., "CT,MR")
    
    Returns:
        List of patient dictionaries matching the criteria
    """
    print(f"\n[DB_SEARCH] 🔍 search_patients_local called with:\n{search_data}")
    conn = get_connection_database()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Check total patients in database first
    cur.execute("SELECT COUNT(*) as count FROM patients")
    total_count = cur.fetchone()[0]
    print(f"[DB_SEARCH] Total patients in database: {total_count}")
    
    # Check total studies in database
    cur.execute("SELECT COUNT(*) as count FROM studies")
    total_studies = cur.fetchone()[0]
    print(f"[DB_SEARCH] Total studies in database: {total_studies}")
    
    # Check if any studies have study_path set
    cur.execute("SELECT COUNT(*) as count FROM studies WHERE study_path IS NOT NULL AND study_path != ''")
    studies_with_path = cur.fetchone()[0]
    print(f"[DB_SEARCH] Studies with study_path: {studies_with_path}")
    
    # List first few studies
    cur.execute("SELECT patient_fk, study_uid, study_path, study_date FROM studies LIMIT 5")
    studies = cur.fetchall()
    print(f"[DB_SEARCH] Sample studies (first 5):")
    for s in studies:
        print(f"[DB_SEARCH]   - patient_fk={s[0]}, study_uid={s[1]}, study_path={s[2]}, study_date={s[3]}")
    
    # Check if any series_description filter is needed
    has_series_filter = bool(search_data.get('series_description'))
    
    # Build the SQL query dynamically based on provided filters
    if has_series_filter:
        # If we need to filter by series, we must join the series table
        query = """
            SELECT DISTINCT
                p.*,
                s.*
            FROM patients p
            LEFT JOIN studies s ON p.patient_pk = s.patient_fk
            LEFT JOIN series sr ON s.study_pk = sr.study_fk
            WHERE 1=1
        """
    else:
        # Simple query without series join
        query = """
            SELECT
                p.*,
                s.*
            FROM patients p
            LEFT JOIN studies s ON p.patient_pk = s.patient_fk
            WHERE 1=1
        """
    
    params = []
    
    # Patient ID filter (partial match, case-insensitive)
    if search_data.get('patient_id'):
        query += " AND LOWER(p.patient_id) LIKE LOWER(?)"
        params.append(f"%{search_data['patient_id']}%")
    
    # Patient Name filter (partial match, case-insensitive)
    if search_data.get('patient_name'):
        query += " AND LOWER(p.patient_name) LIKE LOWER(?)"
        params.append(f"%{search_data['patient_name']}%")
    
    # Patient Sex filter (exact match, case-insensitive)
    if search_data.get('patient_sex'):
        query += " AND LOWER(p.patient_sex) = LOWER(?)"
        params.append(search_data['patient_sex'])
    
    # Study ID filter (partial match, case-insensitive)
    if search_data.get('study_id'):
        query += " AND LOWER(s.study_id) LIKE LOWER(?)"
        params.append(f"%{search_data['study_id']}%")
    
    # Date range filter - only apply if dates are explicitly provided (not None)
    if search_data.get('date_from') and search_data['date_from'] is not None:
        query += " AND s.study_date >= ?"
        params.append(search_data['date_from'])
    
    if search_data.get('date_to') and search_data['date_to'] is not None:
        query += " AND s.study_date <= ?"
        params.append(search_data['date_to'])
    
    # Study Description filter (partial match, case-insensitive)
    if search_data.get('study_description'):
        query += " AND LOWER(s.study_description) LIKE LOWER(?)"
        params.append(f"%{search_data['study_description']}%")
    
    # Series Description filter (partial match, case-insensitive)
    if has_series_filter:
        query += " AND LOWER(sr.series_description) LIKE LOWER(?)"
        params.append(f"%{search_data['series_description']}%")
    
    # Modality filter (supports multiple modalities)
    if search_data.get('modality'):
        modalities = search_data['modality'].split(',')
        modalities = [m.strip() for m in modalities if m.strip()]
        if modalities:
            placeholders = ','.join(['?' for _ in modalities])
            query += f" AND s.modality IN ({placeholders})"
            params.extend(modalities)
    
    # Order by patient name and study date
    query += " ORDER BY p.patient_name, s.study_date DESC"
    
    print(f"[DB_SEARCH] ✅ Built query with {len(params)} parameters")
    print(f"[DB_SEARCH] Query: {query}")
    print(f"[DB_SEARCH] Params: {params}")
    
    try:
        cur.execute(query, params)
        rows = cur.fetchall()
        result = [dict(r) for r in rows]
        print(f"[DB_SEARCH] ✅ Query returned {len(rows)} rows")
        if result:
            for i, r in enumerate(result[:3]):
                patient_name = r.get('patient_name')
                study_uid = r.get('study_uid')
                study_date = r.get('study_date')
                print(f"[DB_SEARCH]   Row {i}: patient_name={patient_name}, study_uid={study_uid}, study_date={study_date}")
        print(f"[DB_SEARCH] ✅ Returning {len(result)} results\n")
        return result
    except Exception as e:
        print(f"[DB_SEARCH] ❌ Query execution failed: {e}")
        raise
    finally:
        conn.close()


def get_patient_by_id(patient_id: str) -> dict:
    """Return patient row as dict or ``None`` if not found."""
    conn = get_connection_database()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None



def find_patient_pk(patient_id: str) -> int:
    """Find patient primary key by patient_id. Returns None if not found."""
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT patient_pk FROM patients WHERE patient_id = ?", (patient_id,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else None


def find_study_pk(patient_fk: int) -> int:
    """Find study primary key by patient_fk. Returns None if not found."""
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT study_pk FROM studies WHERE patient_fk = ?", (patient_fk,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else None


def find_study_pk_with_study_uid(study_uid: str) -> int:
    """Find study primary key by study_uid. Returns None if not found."""
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT study_pk FROM studies WHERE study_uid = ?", (study_uid,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else None


def find_series_pk(series_uid: str) -> int:
    """Find series primary key by series_uid. Returns None if not found."""
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT series_pk FROM series WHERE series_uid = ?", (series_uid,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else None


def find_series_pk_by_number(series_number, study_pk) -> int:
    """Find series primary key by series_number and study_pk. Returns None if not found."""
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute(
        "SELECT series_pk FROM series WHERE series_number = ? AND study_fk = ?", 
        (str(series_number), study_pk)
    )
    result = cur.fetchone()
    conn.close()
    return result[0] if result else None


def find_instance_pk(sop_uid: str) -> int:
    """Find instance primary key by sop_uid. Returns None if not found."""
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT instance_pk FROM instances WHERE sop_uid = ?", (sop_uid,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else None


# Download Progress Functions
def insert_download_progress(study_uid: str, downloaded_count: int = 0, total_instances: int = 0,
                           progress_percent: float = 0.0, current_batch: int = 0, total_batches: int = 0,
                           status: str = 'in_progress') -> int:
    """Insert or update download progress for a study."""
    from datetime import datetime
    import time
    import random
    
    now = datetime.now().isoformat()
    
    max_retries = 5  # Increased retries for better reliability
    for attempt in range(max_retries):
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                
                # Use UPSERT (INSERT OR REPLACE) to avoid race conditions
                cur.execute("""
                    INSERT OR REPLACE INTO download_progress 
                    (study_uid, downloaded_count, total_instances, progress_percent, 
                     current_batch, total_batches, status, created_at, last_update)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 
                            COALESCE((SELECT created_at FROM download_progress WHERE study_uid = ?), ?),
                            ?)
                """, (study_uid, downloaded_count, total_instances, progress_percent,
                      current_batch, total_batches, status, study_uid, now, now))
                
                # Get the progress_pk
                cur.execute("SELECT progress_pk FROM download_progress WHERE study_uid = ?", (study_uid,))
                result = cur.fetchone()
                progress_pk = result[0] if result else None
                
                conn.commit()
                return progress_pk
            
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                import time
                import random
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                print(f"⚠️ Database locked in insert_download_progress, retrying in {wait_time:.1f}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                print(f"⚠️ Database error in insert_download_progress after {max_retries} attempts: {e}")
                raise


def get_download_progress(study_uid: str) -> dict:
    """Get download progress for a study."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT downloaded_count, total_instances, progress_percent, 
                       current_batch, total_batches, status, last_update, created_at, completed_at
                FROM download_progress WHERE study_uid = ?
            """, (study_uid,))
            
            result = cur.fetchone()
            
            if result:
                return {
                    'downloaded_count': result[0],
                    'total_instances': result[1],
                    'progress_percent': result[2],
                    'current_batch': result[3],
                    'total_batches': result[4],
                    'status': result[5],
                    'last_update': result[6],
                    'created_at': result[7],
                    'completed_at': result[8]
                }
            return None
        
    except Exception as e:
        print(f"⚠️ Database error in get_download_progress: {e}")
        return None


def complete_download_progress(study_uid: str):
    """Mark download as completed."""
    from datetime import datetime
    now = datetime.now().isoformat()
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE download_progress 
                SET status = ?, completed_at = ?, last_update = ?
                WHERE study_uid = ?
            """, ('Completed', now, now, study_uid))
            
            conn.commit()
            
            # Verify update
            cur.execute("SELECT status FROM download_progress WHERE study_uid = ?", (study_uid,))
            result = cur.fetchone()
            if result:
                print(f"✅ Download marked as '{result[0]}' in database for {study_uid[:40]}...")
                print(f"   This download will be remembered after app restart")
            else:
                print(f"⚠️ No download progress record found for {study_uid}")
        
    except Exception as e:
        print(f"⚠️ Database error in complete_download_progress: {e}")
        import traceback
        print(traceback.format_exc())
        raise


def delete_download_progress(study_uid: str):
    """Delete download progress for a study."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("DELETE FROM download_progress WHERE study_uid = ?", (study_uid,))
            
            conn.commit()
        
    except Exception as e:
        print(f"⚠️ Database error in delete_download_progress: {e}")
        raise


def clear_all_download_progress():
    """
    Clear ALL download progress records from the database.
    Called on application shutdown to ensure clean state on next startup.
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Delete all download progress records
            cur.execute("DELETE FROM download_progress")
            deleted_count = cur.rowcount
            
            conn.commit()
            
            if deleted_count > 0:
                print(f"🧹 Cleared {deleted_count} download progress records from database")
            
            return deleted_count
        
    except Exception as e:
        print(f"⚠️ Database error in clear_all_download_progress: {e}")
        return 0


def get_all_download_progress() -> list:
    """Get all download progress records with study info."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT dp.study_uid, dp.downloaded_count, dp.total_instances, dp.progress_percent,
                       dp.status, dp.last_update, dp.created_at, s.study_description, p.patient_name, p.patient_id
                FROM download_progress dp
                LEFT JOIN studies s ON dp.study_uid = s.study_uid
                LEFT JOIN patients p ON s.patient_fk = p.patient_pk
                ORDER BY dp.last_update DESC
            """)
            
            results = cur.fetchall()
            
            return [
                {
                    'study_uid': row[0],
                    'downloaded_count': row[1],
                    'total_instances': row[2],
                    'progress_percent': row[3],
                    'status': row[4],
                    'last_update': row[5],
                    'created_at': row[6],  # Added created_at for cleanup logic
                    'study_description': row[7],
                    'patient_name': row[8],
                    'patient_id': row[9]
                }
                for row in results
            ]
        
    except Exception as e:
        print(f"⚠️ Database error in get_all_download_progress: {e}")
        return []


def get_incomplete_downloads() -> list:
    """Get all incomplete download progress records with study info."""
    import time
    import random
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                
                # Use READ UNCOMMITTED isolation level for better concurrency
                cur.execute("PRAGMA read_uncommitted = 1")
                
                cur.execute("""
                    SELECT dp.study_uid, dp.downloaded_count, dp.total_instances, dp.progress_percent,
                           dp.status, dp.last_update, dp.current_batch, dp.total_batches,
                           s.study_description, s.study_date, s.modality,
                           p.patient_name, p.patient_id
                    FROM download_progress dp
                    LEFT JOIN studies s ON dp.study_uid = s.study_uid
                    LEFT JOIN patients p ON s.patient_fk = p.patient_pk
                    WHERE dp.status != 'completed' AND dp.total_instances > 0
                    ORDER BY dp.last_update DESC
                """)
                
                results = cur.fetchall()
                
                return [
                    {
                        'study_uid': row[0],
                        'downloaded_count': row[1],
                        'total_instances': row[2],
                        'progress_percent': row[3],
                        'status': row[4],
                        'last_update': row[5],
                        'current_batch': row[6],
                        'total_batches': row[7],
                        'study_description': row[8],
                        'study_date': row[9],
                        'modality': row[10],
                        'patient_name': row[11],
                        'patient_id': row[12]
                    }
                    for row in results
                ]
        
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                print(f"⚠️ Database locked in get_incomplete_downloads, retrying in {wait_time:.1f}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                print(f"⚠️ Database error in get_incomplete_downloads: {e}")
                return []
    
    return []


# =============================
# BULK OPERATIONS FOR PERFORMANCE
# =============================

def find_instances_by_sop_uids(sop_uids: list) -> list:
    """
    Bulk check which instances already exist in database.
    Returns list of dicts with instance info.
    """
    if not sop_uids:
        return []
    
    conn = get_connection_database()
    cur = conn.cursor()
    
    # Create placeholders for IN clause
    placeholders = ','.join(['?' for _ in sop_uids])
    query = f"SELECT instance_pk, sop_uid FROM instances WHERE sop_uid IN ({placeholders})"
    
    cur.execute(query, sop_uids)
    results = cur.fetchall()
    conn.close()
    
    return [{'instance_pk': row[0], 'sop_uid': row[1]} for row in results]


def bulk_insert_instances(instances_data: list):
    """
    Bulk insert multiple instances at once for better performance.
    instances_data: list of dicts with instance information
    
    ✅ FIX: Use INSERT OR IGNORE to skip duplicates instead of raising UNIQUE constraint error
    """
    if not instances_data:
        return
    
    conn = get_connection_database()
    cur = conn.cursor()
    
    # ✅ FIX: Use INSERT OR REPLACE to handle duplicates gracefully
    # This will update existing records instead of failing
    insert_sql = """
        INSERT OR REPLACE INTO instances (
            sop_uid, series_fk, instance_path, instance_number,
            rows, columns, window_width, window_center, is_rgb, group_id,
            image_position_patient, image_orientation_patient, pixel_spacing, direction
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    # Prepare values for executemany
    values = []
    for inst in instances_data:
        instance_path = inst.get('instance_path')
        if instance_path is not None:
            try:
                instance_path = str(instance_path)
            except Exception:
                instance_path = None
        values.append((
            inst['sop_uid'],
            inst['series_fk'],
            instance_path,
            inst['instance_number'],
            inst['rows'],
            inst['columns'],
            inst['window_width'],
            inst['window_center'],
            int(inst['is_rgb']),
            inst['group_id'],
            inst['image_position_patient'],
            inst['image_orientation_patient'],
            inst['pixel_spacing'],
            inst['direction']
        ))
    
    try:
        # Execute bulk insert
        cur.executemany(insert_sql, values)
        conn.commit()
    except Exception as e:
        print(f"⚠️ Warning during bulk_insert_instances: {e}")
        # Try to rollback and continue
        conn.rollback()
    finally:
        conn.close()


def bulk_update_instances(instances_data: list):
    """
    Bulk update multiple instances at once for better performance.
    instances_data: list of dicts with instance information
    """
    if not instances_data:
        return
    
    conn = get_connection_database()
    cur = conn.cursor()
    
    # Prepare bulk update
    update_sql = """
        UPDATE instances
        SET series_fk = ?, instance_path = ?, instance_number = ?,
            rows = COALESCE(?, rows), columns = COALESCE(?, columns),
            window_width = ?, window_center = ?, is_rgb = ?, group_id = ?,
            image_position_patient = COALESCE(?, image_position_patient),
            image_orientation_patient = COALESCE(?, image_orientation_patient),
            pixel_spacing = COALESCE(?, pixel_spacing),
            direction = COALESCE(?, direction)
        WHERE sop_uid = ?
    """
    
    # Prepare values for executemany
    values = []
    for inst in instances_data:
        instance_path = inst.get('instance_path')
        if instance_path is not None:
            try:
                instance_path = str(instance_path)
            except Exception:
                instance_path = None
        values.append((
            inst['series_fk'],
            instance_path,
            inst['instance_number'],
            inst['rows'],
            inst['columns'],
            inst['window_width'],
            inst['window_center'],
            int(inst['is_rgb']),
            inst['group_id'],
            inst['image_position_patient'],
            inst['image_orientation_patient'],
            inst['pixel_spacing'],
            inst['direction'],
            inst['sop_uid']  # WHERE clause
        ))
    
    # Execute bulk update
    cur.executemany(update_sql, values)
    conn.commit()
    conn.close()


# =============================
# STORAGE CLEANUP FUNCTIONS
# =============================

def get_patients_ordered_by_date(limit: int = None, oldest_first: bool = True) -> list:
    """
    Get patients ordered by earliest study date for cleanup selection.
    
    Args:
        limit: Maximum number of patients to return (None for all)
        oldest_first: If True, order by oldest first (default), else newest first
        
    Returns:
        List of dicts with patient info and study count
    """
    order = "ASC" if oldest_first else "DESC"
    limit_clause = f"LIMIT {limit}" if limit else ""
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT 
                    p.patient_pk,
                    p.patient_id,
                    p.patient_name,
                    p.sex,
                    p.age,
                    MIN(s.study_date) as earliest_study,
                    MAX(s.study_date) as latest_study,
                    COUNT(DISTINCT s.study_pk) as study_count
                FROM patients p
                LEFT JOIN studies s ON p.patient_pk = s.patient_fk
                GROUP BY p.patient_pk
                HAVING study_count > 0
                ORDER BY earliest_study {order}
                {limit_clause}
            """)
            
            results = cur.fetchall()
            
            return [
                {
                    'patient_pk': row[0],
                    'patient_id': row[1],
                    'patient_name': row[2],
                    'sex': row[3],
                    'age': row[4],
                    'earliest_study': row[5],
                    'latest_study': row[6],
                    'study_count': row[7]
                }
                for row in results
            ]
    
    except Exception as e:
        print(f"[WARNING] Database error in get_patients_ordered_by_date: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_patient_storage_info(patient_pk: int) -> dict:
    """
    Get comprehensive storage information for a patient including all file references.
    
    Args:
        patient_pk: Patient primary key
        
    Returns:
        Dict with patient_id, patient_name, study_uids, and file path lists
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get patient basic info
            cur.execute("""
                SELECT patient_id, patient_name
                FROM patients
                WHERE patient_pk = ?
            """, (patient_pk,))
            
            patient_row = cur.fetchone()
            if not patient_row:
                return {
                    'patient_id': None,
                    'patient_name': None,
                    'study_uids': [],
                    'study_paths': [],
                    'series_paths': [],
                    'instance_paths': [],
                    'attachment_paths': []
                }
            
            patient_id, patient_name = patient_row
            
            # Get all study UIDs
            cur.execute("""
                SELECT study_uid, study_path, attachments_uploaded
                FROM studies
                WHERE patient_fk = ?
            """, (patient_pk,))
            
            studies = cur.fetchall()
            study_uids = [row[0] for row in studies if row[0]]
            study_paths = [row[1] for row in studies if row[1]]
            
            # Parse attachment paths
            attachment_paths = []
            for row in studies:
                if row[2]:  # attachments_uploaded field
                    paths = [p.strip() for p in row[2].split(',') if p.strip()]
                    attachment_paths.extend(paths)
            
            # Get all series paths
            cur.execute("""
                SELECT DISTINCT se.series_path
                FROM series se
                JOIN studies s ON se.study_fk = s.study_pk
                WHERE s.patient_fk = ?
                AND se.series_path IS NOT NULL
            """, (patient_pk,))
            
            series_paths = [row[0] for row in cur.fetchall()]
            
            # Get all instance paths
            cur.execute("""
                SELECT DISTINCT i.instance_path
                FROM instances i
                JOIN series se ON i.series_fk = se.series_pk
                JOIN studies s ON se.study_fk = s.study_pk
                WHERE s.patient_fk = ?
                AND i.instance_path IS NOT NULL
            """, (patient_pk,))
            
            instance_paths = [row[0] for row in cur.fetchall()]
            
            return {
                'patient_id': patient_id,
                'patient_name': patient_name,
                'study_uids': study_uids,
                'study_paths': study_paths,
                'series_paths': series_paths,
                'instance_paths': instance_paths,
                'attachment_paths': attachment_paths
            }
    
    except Exception as e:
        print(f"[WARNING] Database error in get_patient_storage_info: {e}")
        import traceback
        traceback.print_exc()
        return {
            'patient_id': None,
            'patient_name': None,
            'study_uids': [],
            'study_paths': [],
            'series_paths': [],
            'instance_paths': [],
            'attachment_paths': []
        }


def delete_patient_cascade(patient_pk: int) -> bool:
    """
    Delete patient and all related records from database using CASCADE.
    This will automatically delete:
    - All studies (via CASCADE)
    - All series (via CASCADE from studies)
    - All instances (via CASCADE from series)
    
    Args:
        patient_pk: Patient primary key
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Delete patient (CASCADE handles the rest)
            cur.execute("DELETE FROM patients WHERE patient_pk = ?", (patient_pk,))
            deleted = cur.rowcount
            
            conn.commit()
            
            if deleted > 0:
                print(f"[OK] Deleted patient {patient_pk} from database (CASCADE)")
                return True
            else:
                print(f"[WARNING] Patient {patient_pk} not found in database")
                return False
    
    except Exception as e:
        print(f"[WARNING] Database error in delete_patient_cascade: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_patients_by_date_range(start_date: str = None, end_date: str = None) -> list:
    """
    Get patients with studies within a specific date range.
    
    Args:
        start_date: Start date in YYYYMMDD format (inclusive, None for no start limit)
        end_date: End date in YYYYMMDD format (inclusive, None for no end limit)
        
    Returns:
        List of dicts with patient info
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Build WHERE clause
            where_clauses = []
            params = []
            
            if start_date:
                where_clauses.append("s.study_date >= ?")
                params.append(start_date)
            
            if end_date:
                where_clauses.append("s.study_date <= ?")
                params.append(end_date)
            
            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            
            cur.execute(f"""
                SELECT 
                    p.patient_pk,
                    p.patient_id,
                    p.patient_name,
                    MIN(s.study_date) as earliest_study,
                    MAX(s.study_date) as latest_study,
                    COUNT(DISTINCT s.study_pk) as study_count
                FROM patients p
                JOIN studies s ON p.patient_pk = s.patient_fk
                {where_sql}
                GROUP BY p.patient_pk
                ORDER BY earliest_study DESC
            """, params)
            
            results = cur.fetchall()
            
            return [
                {
                    'patient_pk': row[0],
                    'patient_id': row[1],
                    'patient_name': row[2],
                    'earliest_study': row[3],
                    'latest_study': row[4],
                    'study_count': row[5]
                }
                for row in results
            ]
    
    except Exception as e:
        print(f"[WARNING] Database error in get_patients_by_date_range: {e}")
        import traceback
        traceback.print_exc()
        return []


#
# init_database()
# # quick smoke‑test
#
# p_pk = insert_patient(patient_id="P001", name="Test Name", sex="M")
# s_pk = insert_study(study_uid="1.2.3.4", patient_fk=p_pk, study_date="20250101")
# se_pk = insert_series(series_uid="1.2.3.4.5", study_fk=s_pk, modality="MR")
# i_pk = insert_instance(sop_uid="1.2.3.4.5.6", series_fk=se_pk, instance_path="/path/to/file.dcm")
