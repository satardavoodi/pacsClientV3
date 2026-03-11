# Database Architecture

> **Version:** v2.2.3.4.0 | **Updated:** 2026-03-10

## Overview

AIPacs uses SQLite as its local persistence layer. The database stores the full DICOM hierarchy (Patient→Study→Series→Instance), download state, filming metadata, reception reports, and AI session data.

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

### Connection Lifecycle
```python
# CORRECT: always use context manager
with get_db_connection() as conn:
    cursor = conn.execute("SELECT ...")
    rows = cursor.fetchall()
# Connection automatically returned to pool

# INCORRECT: manual connection management
conn = get_db_connection()
# ... if exception here, connection leaks
conn.close()
```

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

Enable via `DIAGNOSTIC_LOGGING_ENABLED` environment variable.

## Migration Strategy

- Schema migrations live in `database/migrations/`
- `manager.py` provides migration helpers
- Migrations run on startup if schema version is outdated
- All migrations are forward-only (no rollback support)

## Database Files

| File | Purpose |
|------|---------|
| `database/core.py` | Connection pool, schema DDL, low-level operations |
| `database/manager.py` | Query helpers, CRUD wrappers, migration support |
| `PacsClient/utils/database.py` | Legacy shim (imports from `database/core.py`) |
| `PacsClient/utils/db_manager.py` | Backward-compatible import proxy |

## Stability Rules

1. **Always use `with get_db_connection()` context manager** — never hold connections manually
2. **Never hold a connection across async boundaries** — acquire per-operation
3. **Pool cleanup on shutdown** — call `cleanup_connection_pools()` in closeEvent
4. **WAL mode is mandatory** — do not switch to DELETE or TRUNCATE journal modes
5. **DEFERRED transactions** — do not use IMMEDIATE or EXCLUSIVE unless absolutely necessary
