# Database Module Split — v2.2.9.0

**Date:** 2026-04-04  
**Status:** Complete  
**Test result:** 7/7 DB scenarios pass · 24/24 smoke imports pass

---

## Why

`database/core.py` had grown to **3 481 lines** containing six logically
independent domains mixed together.  This made it hard to:

- find functions (no sector grouping)
- understand impact of a change (unrelated concerns in the same file)
- onboard new contributors quickly

---

## What changed

`database/core.py` is now a **126-line backward-compatible re-export shim**.
All code lives in six new domain files.  No caller was modified.

### Domain files created

| File | Lines | Responsibility |
|------|------:|----------------|
| `database/_pool.py` | ~250 | Connection pool, `get_db_connection()`, `log_stage_timing()` |
| `database/dicom_db.py` | ~550 | DICOM hierarchy schema + CRUD (patient/study/series/instance) |
| `database/token_usage_db.py` | ~375 | AI token & transcript usage accounting |
| `database/ai_sessions_db.py` | ~480 | AI chat sessions, messages, reports, secretary audit log |
| `database/ai_reception_db.py` | ~170 | AI reception report queue |
| `database/download_progress_db.py` | ~220 | Download progress tracking |

---

## Backward compatibility guarantee

Three layers ensure zero-impact for all existing callers:

1. **`database/core.py`** re-exports every public symbol from the six domain
   files via explicit `from database.<module> import ...` statements.

2. **`database/__init__.py`** uses `__getattr__` to proxy any attribute access
   to `database.core`, so `from database import X` continues to work.

3. **`PacsClient/utils/database.py`** uses the same `__getattr__` pattern to
   proxy to `database.core`, so the legacy shim path also continues to work.

**None of the 40+ caller files were modified.**

---

## Import patterns (all still valid)

```python
# Direct domain import (preferred for new code)
from database._pool import get_db_connection
from database.dicom_db import init_database, insert_patient

# Legacy shim path — still 100% functional
from database.core import get_db_connection, init_database
from database import get_db_connection
from PacsClient.utils.database import get_db_connection
```

---

## Standards for future additions

When adding a new database function, choose the correct domain file:

| Kind of function | File |
|-----------------|------|
| Connection / pool / timing helpers | `_pool.py` |
| Patient, study, series, instance CRUD | `dicom_db.py` |
| AI token or transcript usage | `token_usage_db.py` |
| AI chat sessions, messages, reports, secretary log | `ai_sessions_db.py` |
| AI reception report queue | `ai_reception_db.py` |
| Download progress / status | `download_progress_db.py` |

Rules:
- **Always** import `get_db_connection` from `database._pool` (never from `database.core` inside domain files — that would be circular).
- **Always** add the new symbol to the re-export list in `database/core.py`.
- **Never** add a `PRAGMA read_uncommitted` — it leaks via the pool.
- **Always** call `conn.commit()` before the `with get_db_connection()` block exits for any DML.

---

## Test coverage

| Suite | Command | Result |
|-------|---------|--------|
| Database scenarios (D1–D7) | `python tests/database/run_db_test.py` | 7/7 ✅ |
| Smoke imports (26 modules) | `python -m pytest tests/smoke/ -v` | 24/24 ✅ |
