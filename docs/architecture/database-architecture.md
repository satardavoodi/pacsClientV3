# Database Architecture

> **Version:** v2.2.8.1 | **Updated:** 2026-04-02  
> **Previous:** v2.2.3.4.0 (2026-03-10)

## Overview

AIPacs uses SQLite as its local persistence layer.  The database stores the
full DICOM hierarchy (Patient → Study → Series → Instance), download state,
filming metadata, reception reports, and AI session data.

## Schema: DICOM Hierarchy

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────────┐
│ Patients │────▶│ Studies  │────▶│ Series   │────▶│ Instances    │
│          │ 1:N │          │ 1:N │          │ 1:N │              │
│ pk (PK)  │     │ pk (PK)  │     │ pk (PK)  │     │ pk (PK)      │
│ patient_id│     │ study_uid│     │ series_uid│    │ sop_inst_uid │
│ name     │     │ patient_pk│    │ study_pk │     │ series_pk    │
│ ...      │     │ ...      │     │ ...      │     │ instance_path│
└──────────┘     └──────────┘     └──────────┘     │ geometry     │
                                                    │ window/level │
                                                    └──────────────┘
```

### Indexes (v2.2.8.0)

Foreign-key indexes were added to eliminate full-table scans on the most
frequent query patterns:

```sql
CREATE INDEX IF NOT EXISTS idx_studies_patient_fk  ON studies   (patient_fk);
CREATE INDEX IF NOT EXISTS idx_series_study_fk     ON series    (study_fk);
CREATE INDEX IF NOT EXISTS idx_instances_series_fk ON instances (series_fk);
CREATE INDEX IF NOT EXISTS idx_instances_series_group
    ON instances (series_fk, group_id);
```

These are created in `init_database()` alongside the table DDL.  Do NOT remove
them — they are critical for sub-3ms lookup of patient → study → series →
instance chains.

### Additional Tables
- **Download state**: tracks download progress, status, timestamps per study/series
- **Filming metadata**: print job records and DICOM print settings
- **Reception reports**: study reception and report status
- **AI sessions**: EchoMind and advanced imaging session data

## Connection Strategy

### WAL Mode (Write-Ahead Logging)
```python
conn.execute("PRAGMA journal_mode=WAL")
```
- Allows concurrent reads during writes
- Critical for DICOM workstation: viewer reads while downloads write
- No reader blocking during downloads

### Connection Pool
```
Thread A ──▶ Pool ──▶ Connection 1 (reused)
Thread B ──▶ Pool ──▶ Connection 2 (reused)
Thread C ──▶ Pool ──▶ Connection 3 (new if pool empty)
```

**Pool Rules:**
- Thread-local pool (per-thread isolation)
- Max 5 connections per thread
- 30-second timeout on connection acquisition
- DEFERRED isolation level (non-blocking transactions)
- Connection reuse validation: `SELECT 1` before handing out pooled connections

### Connection Lifecycle (v2.2.8.0 — ENFORCED)

```python
# CORRECT: always use context manager — connection returned to pool on exit
with get_db_connection() as conn:
    cursor = conn.execute("SELECT ...")
    rows = cursor.fetchall()
    # For writes: conn.commit() INSIDE the with block
    conn.commit()

# INCORRECT: bare connection — leaks on exception, relies on GC __del__
conn = get_connection_database()
cursor = conn.execute(...)    # if this throws, connection is never returned
conn.close()
```

As of v2.2.8.0, **all functions in `database/manager.py`** have been converted
from bare `get_connection_database()` to `with get_db_connection() as conn:`.
The `get_connection_database()` function still exists for backward
compatibility but should not be used in new code.

## Commit Safety (v2.2.8.0)

The `get_db_connection()` context manager **does NOT auto-commit**.  The
`_return_to_pool()` method calls `conn.rollback()` to clear any implicit
transaction state before reuse.

**This means: if you do DML (INSERT/UPDATE/DELETE) inside a `with` block and
forget `conn.commit()`, your write is silently lost.**

The following 11 functions had missing `conn.commit()` calls that were fixed
in v2.2.8.0:

| Function | Fix |
|----------|-----|
| `upsert_download()` | Added commit after INSERT/UPDATE |
| `update_download_progress()` | Added commit after UPDATE |
| `update_download_status()` | Added commit after UPDATE |
| `add_attachment_record()` | Added commit after INSERT |
| `update_attachment_record()` | Added commit after UPDATE |
| `update_filming_job_*()` | Added commit per function |
| `ai_save_reception_report()` | Added commit after INSERT |
| `ai_update_reception_report()` | Added commit after UPDATE |
| `ai_delete_reception_report()` | Added commit after DELETE |
| `add_transcript_usage_delta()` | Added commit in total_minutes path |
| `add_api_transcript_usage_delta()` | Added commit in total_minutes path |

## Key Operations

| Operation | Function | Typical Timing |
|-----------|----------|----------------|
| Find patient | `find_patient_pk(patient_id)` | 1-3ms |
| Find study | `find_study_pk_with_study_uid(study_uid)` | 1-3ms |
| Insert instance | `insert_instance(...)` | 2-5ms |
| Full series query | `get_series_instances(series_pk)` | 5-15ms |
| Download state update | `update_download_progress(...)` | 2-5ms |

## Diagnostic Logging

Database operations are instrumented with per-stage timing:
```
Component: db
Stages: pool_lock_wait, reuse_validate, create_connection, transaction_scope
```

### Log Throttling (v2.2.8.0)

`log_stage_timing()` accepts an optional `min_ms` parameter.  Pool operations
(`pool_lock_wait`, `reuse_validate`, `create_connection`, `transaction_scope`)
pass `min_ms=5.0` so that sub-5ms stages are suppressed.  This reduces DB log
volume by ~90% during normal operation while preserving visibility for slow
operations.

To see all pool timing (including sub-5ms), set `min_ms=0` in the
`log_stage_timing()` calls in `database/core.py`.

Enable diagnostic logging via `DIAGNOSTIC_LOGGING_ENABLED` environment
variable.

## Database Initialization Ownership

`init_database()` is called **once** from `MainWindowWidget.__init__()` in
`PacsClient/pacs/workstation_ui/mainwindow_ui.py`.  It was previously also
called from `ControlPanelInterface.__init__()` — the duplicate was removed
in v2.2.8.0 to prevent double-initialization.

Do NOT add `init_database()` calls to other UI constructors.

## Migration Strategy

- Schema migrations live in `database/migrations/`
- `manager.py` provides migration helpers
- Migrations run on startup if schema version is outdated
- All migrations are forward-only (no rollback support)

## Database Files

| File | Lines | Purpose |
|------|-------|---------|
| `database/__init__.py` | — | Package marker |
| `database/core.py` | ~3300 | Connection pool, schema DDL, all low-level CRUD, find/insert/upsert/search |
| `database/manager.py` | ~950 | Higher-level query helpers, CRUD wrappers, migration support |
| `PacsClient/utils/database.py` | — | Legacy shim (imports from `database/core.py`) |
| `PacsClient/utils/db_manager.py` | — | Backward-compatible import proxy |

### manager.py Query Pattern (v2.2.8.0)

All query functions now use `cur.description` to build result dicts instead of
hardcoded key lists.  This prevents column drift when the schema is extended:

```python
# CORRECT (v2.2.8.0): schema-driven keys
with database.get_db_connection() as conn:
    cur = conn.execute("SELECT * FROM series WHERE pk = ?", (pk,))
    row = cur.fetchone()
    if row:
        keys = [desc[0] for desc in cur.description]
        return dict(zip(keys, row))

# INCORRECT (pre-v2.2.8.0): hardcoded keys that drift from schema
keys = ["pk", "study_fk", "series_uid", ...]  # manually maintained list
```

## Stability Rules

1. **Always use `with get_db_connection()` context manager** — never hold
   connections manually.  All of `manager.py` was converted in v2.2.8.0.
2. **Always call `conn.commit()` inside the `with` block** for writes — the
   pool calls `rollback()` on return, so uncommitted writes are lost.
3. **Never hold a connection across async boundaries** — acquire per-operation.
4. **Pool cleanup on shutdown** — call `cleanup_connection_pools()` in
   closeEvent.
5. **WAL mode is mandatory** — do not switch to DELETE or TRUNCATE journal
   modes.
6. **DEFERRED transactions** — do not use IMMEDIATE or EXCLUSIVE unless
   absolutely necessary.
7. **Do not use `PRAGMA read_uncommitted`** — it leaks via the connection pool
   and affects subsequent callers.  This was removed from
   `get_incomplete_downloads()` in v2.2.8.0.
8. **Use parameter binding** (`?` placeholders) for all user-supplied values —
   never use f-strings or `.format()` in SQL.

## Rules for Future Development

### MUST follow

- **All new DB read/write functions** must use `with get_db_connection() as
  conn:` — not `get_connection_database()`.
- **All DML** (INSERT/UPDATE/DELETE) must call `conn.commit()` inside the
  `with` block before the block exits.
- **All SQL parameters** must use `?` binding — never f-string interpolation.
- **New indexes** for new FK columns or frequent WHERE clauses must be added
  in `init_database()` alongside the table DDL.
- **Result dict construction** must use `cur.description` — not hardcoded key
  lists.

### SHOULD follow

- Keep `core.py` under 4000 lines.  If it grows, extract domain-specific
  groups (e.g., AI reception, filming, attachment) into their own modules.
- Prefer single-statement transactions over multi-statement when possible.
- Add `min_ms=5.0` to new `log_stage_timing()` calls for pool operations.

### MUST NOT do

- Do not add `init_database()` calls anywhere except `MainWindowWidget`.
- Do not use `PRAGMA read_uncommitted` — it leaks across pooled connections.
- Do not remove the FK indexes from `init_database()`.
- Do not rely on `__del__` for connection cleanup — always use `with`.
- Do not use banner-style logging (`"=" * 80`) in DB functions — use single
  `logger.debug()` lines.
