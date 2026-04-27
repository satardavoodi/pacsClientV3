"""database._pool — connection-pool infrastructure for AIPacs SQLite.

Public API
----------
get_db_connection()       — context manager for transactional use
get_connection_database() — returns a _PooledConnection proxy (legacy)
cleanup_connection_pools()— close all pooled connections (shutdown / tests)
now_ms()                  — millisecond timestamp (delegates to diagnostic_logging)
log_stage_timing(...)     — timing logger (delegates to diagnostic_logging)

Internal symbols (_*) are private to this module.

Split from database/core.py (v2.2.8.0 → v2.2.9.0).
"""

import contextlib
import logging
import os
import sqlite3
import sys
import threading
from typing import Optional

# ── Lazy import to break circular chain ───────────────────────────────────────
#  database._pool -> PacsClient.utils.diagnostic_logging
#                 -> PacsClient.utils.__init__
#                 -> PacsClient.utils.database (shim) -> database.core -> database._pool
_diag = None


def _get_diag():
    global _diag
    if _diag is None:
        from PacsClient.utils import diagnostic_logging as _dl
        _diag = _dl
    return _diag


def now_ms():
    return _get_diag().now_ms()


def log_stage_timing(*args, **kwargs):
    return _get_diag().log_stage_timing(*args, **kwargs)


# ── Module-level pool state ───────────────────────────────────────────────────
_local = threading.local()
_db_lock = threading.Lock()
_connection_pool: dict = {}          # thread_id -> list[sqlite3.Connection]
_pool_lock = threading.Lock()
_max_pool_size = 5
logger = logging.getLogger(__name__)


def _db_timing_min_ms() -> float:
    try:
        return max(0.0, float(os.getenv("AIPACS_DB_TIMING_MIN_MS", "1.0") or "1.0"))
    except Exception:
        return 1.0


def _classify_db_caller() -> dict:
    """Classify the external caller at the shared DB boundary."""
    try:
        frame = sys._getframe(2)
    except Exception:
        frame = None

    module = ""
    function = ""
    for _ in range(14):
        if frame is None:
            break
        module = str(frame.f_globals.get("__name__", "") or "")
        function = str(frame.f_code.co_name or "")
        if module and module != __name__ and module != "contextlib" and not module.startswith("logging"):
            break
        frame = frame.f_back

    mod_l = module.lower()
    fn_l = function.lower().lstrip("_")
    caller_area = "other"
    viewer_mode = "Shared"
    query_type = "mixed"

    if fn_l.startswith(("get_", "find_", "fetch_", "load_", "select_", "check_")) or "select" in fn_l:
        query_type = "read"
    elif (
        fn_l.startswith(("insert_", "update_", "delete_", "complete_", "clear_", "save_", "bulk_insert", "bulk_update"))
        or "insert" in fn_l
        or "update" in fn_l
    ):
        query_type = "write"
    elif fn_l.startswith(("init_", "ensure_", "migrate_")):
        query_type = "write"

    if "download_manager" in mod_l or "download_progress" in mod_l:
        caller_area = "shared_download"
    elif mod_l.startswith("database") or "pacsclient.utils.database" in mod_l:
        caller_area = "shared_db_helper"
    elif "modules.viewer.fast" in mod_l or "pydicom_qt" in mod_l or "lightweight_2d" in mod_l:
        caller_area = "fast_interaction" if any(token in fn_l for token in ("scroll", "slice", "drag")) else "fast_load_setup"
        viewer_mode = "FAST"
    elif "modules.viewer.advanced" in mod_l:
        caller_area = "advanced_interaction" if any(token in fn_l for token in ("scroll", "slice", "window_level")) else "advanced_load_setup"
        viewer_mode = "Advanced"
    elif "patient_tab" in mod_l or "image_io" in mod_l:
        caller_area = "viewer_load_setup"
        viewer_mode = "Viewer"

    return {
        "caller_area": caller_area,
        "viewer_mode": viewer_mode,
        "caller_module": module,
        "caller_function": function,
        "query_type": query_type,
        "thread_role": "main" if threading.current_thread() is threading.main_thread() else "worker",
    }


# ── Public context manager ────────────────────────────────────────────────────

@contextlib.contextmanager
def get_db_connection():
    """Context manager for database connections with automatic cleanup and pooling."""
    conn = None
    t_txn = now_ms()
    caller_info = _classify_db_caller()
    try:
        conn = _get_pooled_connection()
        yield conn
    except Exception as e:
        print(f"⚠️ Database error in transaction: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn:
            try:
                _return_to_pool(conn)
            except Exception as e:
                print(f"⚠️ Error returning connection to pool: {e}")
        log_stage_timing(
            logger,
            component="db",
            function="database.get_db_connection",
            stage="transaction_scope",
            start_ms=t_txn,
            min_ms=_db_timing_min_ms(),
            **caller_info,
        )


# ── Internal pool helpers ─────────────────────────────────────────────────────

def _get_pooled_connection() -> sqlite3.Connection:
    """Get a reusable connection from pool or create new one."""
    thread_id = threading.current_thread().ident

    t_lock = now_ms()
    _pool_lock.acquire()
    log_stage_timing(
        logger,
        component="db",
        function="database._get_pooled_connection",
        stage="pool_lock_wait",
        start_ms=t_lock,
        query_type="mixed",
        min_ms=5.0,
    )
    try:
        if thread_id in _connection_pool:
            conns = _connection_pool[thread_id]
            if conns:
                t_validate = now_ms()
                conn = conns.pop()
                try:
                    conn.execute("SELECT 1")
                    log_stage_timing(
                        logger,
                        component="db",
                        function="database._get_pooled_connection",
                        stage="reuse_validate",
                        start_ms=t_validate,
                        query_type="mixed",
                        min_ms=5.0,
                    )
                    return conn
                except sqlite3.OperationalError:
                    pass  # dead connection — fall through to create new one

        t_create = now_ms()
        conn = _create_sqlite_connection()
        log_stage_timing(
            logger,
            component="db",
            function="database._get_pooled_connection",
            stage="create_connection",
            start_ms=t_create,
            query_type="mixed",
            min_ms=5.0,
        )
        return conn
    finally:
        _pool_lock.release()


def _return_to_pool(conn: sqlite3.Connection) -> None:
    """Return connection to pool for reuse (or close if pool is full)."""
    thread_id = threading.current_thread().ident
    with _pool_lock:
        if thread_id not in _connection_pool:
            _connection_pool[thread_id] = []
        conns = _connection_pool[thread_id]
        if len(conns) < _max_pool_size:
            try:
                conn.rollback()
                conns.append(conn)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
        else:
            try:
                conn.close()
            except Exception:
                pass


def _create_sqlite_connection() -> sqlite3.Connection:
    """Create a brand-new raw sqlite3.Connection with standard PRAGMAs.

    Internal use only.  Pool machinery and get_connection_database() both call
    this so the pool never stores _PooledConnection proxies.
    """
    import random
    import time
    from PacsClient.utils.data_paths import DATABASE_FILE

    db = str(DATABASE_FILE)
    max_retries = 15

    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(
                db,
                timeout=300.0,
                check_same_thread=False,
                isolation_level="DEFERRED",
            )
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 120000;")
            conn.execute("PRAGMA temp_store = MEMORY;")
            conn.execute("PRAGMA cache_size = -10000;")
            conn.execute("PRAGMA mmap_size = 104857600;")
            conn.execute("PRAGMA wal_autocheckpoint = 2000;")
            conn.execute("PRAGMA locking_mode = NORMAL;")
            return conn
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 3)
                print(f"⚠️ Database locked, retrying in {wait_time:.1f}s... "
                      f"(attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                print(f"❌ Database connection failed after {max_retries} attempts: {e}")
                raise

    raise sqlite3.OperationalError("Failed to connect to database after all retries")


# ── _PooledConnection proxy ───────────────────────────────────────────────────

class _PooledConnection:
    """Thin proxy around sqlite3.Connection that auto-returns to the pool.

    Every get_connection_database() call returns one of these.  When the
    caller never calls close() the connection is silently returned to the
    pool (or closed cleanly) in __del__, preventing ResourceWarning floods.
    """

    __slots__ = ("_conn", "_closed")

    def __init__(self, conn: sqlite3.Connection):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_closed", False)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_conn"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_conn"), name, value)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if not object.__getattribute__(self, "_closed"):
            object.__setattr__(self, "_closed", True)
            _return_to_pool(object.__getattribute__(self, "_conn"))

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __iter__(self):
        return iter(object.__getattribute__(self, "_conn"))


# ── Public legacy helper ──────────────────────────────────────────────────────

def get_connection_database() -> _PooledConnection:
    """Return a _PooledConnection proxy with foreign-key constraints enabled.

    Prefer get_db_connection() context manager for new code.
    """
    return _PooledConnection(_get_pooled_connection())


def cleanup_connection_pools() -> None:
    """Close all pooled connections (for app shutdown or testing)."""
    global _connection_pool
    with _pool_lock:
        for _tid, conns in _connection_pool.items():
            for conn in conns:
                try:
                    conn.close()
                except Exception:
                    pass
        _connection_pool.clear()
        logger.info("All pooled database connections closed")
