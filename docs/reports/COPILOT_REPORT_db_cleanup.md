# COPILOT_REPORT_db_cleanup.md
**Date:** 2026-05-24  
**Branch:** matab-conservative  
**Task source:** `COPILOT_TASK_db_test_isolation_and_cleanup.md`

---

## Summary

All four tasks were completed successfully.

| # | Task | Status |
|---|------|--------|
| 1 | Fix `tests/database/test_database.py` isolation | ✅ Complete |
| 2 | Remove leaked test data from production DB | ✅ Complete |
| 3 | Read-only pipeline investigation of other tests | ✅ Complete |
| 4 | Write this report | ✅ Complete |

**Section 7 expected final behaviour is fully met:**
- `tests/database/test_database.py` now connects to a temp directory DB and never touches `user_data/database/dicom.db`.
- Production DB is clean: `test_tables=0`, `test_patients=0`, `quick_check=ok`, `fk_check=clean`.
- No other production test actively writes to the production DB.

---

## Task 1 — Test isolation fix

### Problem (root cause)

`_setup_temp_db()` patched **dead attributes** that the pool logic never reads:

```python
# OLD — non-working patches
database.core._DB_PATH = temp_db         # attribute does not exist / nothing reads it
db_core._pool = {}                        # attribute does not exist in _pool.py
db_core._pool_lock = threading.Lock()    # attribute does not exist in _pool.py
```

The actual connection factory is `database/_pool.py :: _create_sqlite_connection()`.  
It resolves the path via an **in-function import**:

```python
def _create_sqlite_connection():
    from PacsClient.utils.data_paths import DATABASE_FILE   # ← reads at call time
    ...
```

Because Python re-executes the `from ... import` each call and resolves the current
module-level attribute, patching `data_paths.DATABASE_FILE` redirects every subsequent
connection to the temp DB.

### Name-matching audit (all exact, no guessing required)

| Name patched | Where it lives | Confirmed match |
|---|---|---|
| `data_paths.DATABASE_FILE` | `PacsClient/utils/data_paths.py` line ~18 | ✅ |
| `db_pool._connection_pool` | `database/_pool.py` line ~32 (`_connection_pool: dict = {}`) | ✅ |
| `db_pool._pool_lock` | `database/_pool.py` line ~33 (`_pool_lock = threading.Lock()`) | ✅ |
| in-function `from … import DATABASE_FILE` | `database/_pool.py` `_create_sqlite_connection()` line ~241 | ✅ |

### Diff summary — `tests/database/test_database.py`

Three functions were replaced; everything else in the file is untouched.

**New `_clear_connection_pool(db_pool)`**
```python
def _clear_connection_pool(db_pool):
    try:
        with db_pool._pool_lock:
            for conns in list(db_pool._connection_pool.values()):
                for c in conns:
                    try: c.close()
                    except Exception: pass
            db_pool._connection_pool.clear()
    except Exception:
        pass
```
> *Note: `cleanup_connection_pools()` already exists in `database._pool` and does the
> same work. The spec asked for an explicit helper so it was written inline; in a future
> refactor it could delegate to the public function.*

**New `_setup_temp_db()`**
- Creates `tempfile.mkdtemp(prefix="db_test_")`.
- Saves `_ORIGINAL_DB = data_paths.DATABASE_FILE`.
- Sets `data_paths.DATABASE_FILE = Path(temp_db)`.
- Calls `_clear_connection_pool()` to flush any pooled production connections.
- **Loud-fail guard:** opens a connection via `get_db_connection()` and asserts
  `PRAGMA database_list` returns the expected temp path; raises `RuntimeError` if not.

**New `_teardown_temp_db()`**
- Calls `_clear_connection_pool()` again (drains connections to the temp DB).
- Restores `data_paths.DATABASE_FILE = _ORIGINAL_DB`.
- `shutil.rmtree()` deletes the temp directory.

---

## Task 2 — Production DB cleanup

### Before counts (recorded at session start)

| Metric | Count |
|--------|-------|
| Orphan test tables | 87 |
| Synthetic test patients | 946 |
| `patients` total | 1 309 |
| `studies` total | 460 |
| `series` total | 3 454 |
| `instances` total | 120 179 |

Root cause: ~43 test runs against the production DB over the life of the old broken
isolation code. Each run created tables (`_commit_test_*`, `_nocommit_test_*`,
`_test_rollback`) and rows (patients with `PID-`, `THREAD-`, `SRCH-` id prefixes and
test patient-name values).

### Cleanup execution

Tool: `tools/maintenance/cleanup_test_pollution.py` (pre-existing, unmodified)

1. **Dry-run** confirmed plan:
   - 87 tables to drop
   - 946 patients / 86 studies / 43 series / 43 instances to delete
2. **Backup** taken before writes:  
   `backups/dicom_pre-cleanup_2026-05-24_192543.db` — 74.5 MB (SQLite online backup)
3. **`--apply` run** completed cleanly. DB was NOT locked.
4. Post-apply `PRAGMA quick_check = ok`, `PRAGMA foreign_key_check` = clean.

### After counts (verified by independent query)

| Metric | Count |
|--------|-------|
| Test tables | **0** |
| Test patients | **0** |
| `patients` total | **363** |
| `studies` total | **374** |
| `quick_check` | **ok** |
| `foreign_key_check` | **clean** |

**Decision on `--vacuum`:** Not applied. The task spec marked it optional, and
`VACUUM` on a 74 MB database takes several seconds and re-numbers all row-IDs.
The file size freed by the dropped rows is modest and the production DB is healthy.
The decision was logged here to satisfy the spec requirement.

---

## Task 3 — Pipeline investigation (read-only)

### `tests/conftest.py`

Only adds the project root to `sys.path`. No DB import, no module init. **Safe.**

### `tests/viewer/conftest.py`, `tests/fast_viewer/conftest.py`, `tests/fast/conftest.py`, `tests/diagnostics/conftest.py`

Viewer/fast/diagnostics conftest files add CLI flags (`--capture-golden`) or no-ops.
None import or initialize any DB module. **Safe.**

### `tests/printing/test_printing_series_repository.py`

Isolation mechanism: pytest `tmp_path` fixture + `monkeypatch.setattr(repo, "_resolve_db_path", lambda: db_path)`.

The printing `SeriesRepository` resolves its DB path through its own private method `_resolve_db_path()`.  
The tests intercept that method directly, pointing it at a fresh `tmp_path / "dicom.db"`.  
**This does NOT go through `database._pool._create_sqlite_connection()`** — the repo opens
its own raw `sqlite3.connect()`. As a result:
- The central pool is never involved.
- `PacsClient.utils.data_paths.DATABASE_FILE` is never read.
- Each test gets a completely fresh, isolated SQLite file.

**Risk: none. Isolation is correct.**

### `tests/offline_cloud_server/test_offline_cloud_server.py`

Isolation mechanism: `_temp_offline_cloud_env()` context manager patches
`offline_cloud_impl.DATABASE_FILE = local_db` and restores it in `finally`.

Key observations:
- `offline_cloud_impl` imports `DATABASE_FILE` at module level from `data_paths`,
  creating its own local reference (`offline_cloud_impl.DATABASE_FILE`).
- The patch rebinds that module-level name, so any code **inside `offline_cloud_impl`**
  that reads `DATABASE_FILE` directly (e.g., `sqlite3.connect(DATABASE_FILE)`) sees the
  temp path.
- If `offline_cloud_impl` calls `get_db_connection()` from `database._pool`, the patch
  would NOT redirect those connections, because `_pool._create_sqlite_connection()` reads
  from `PacsClient.utils.data_paths.DATABASE_FILE`, not from `offline_cloud_impl`'s copy.

**Current risk assessment:** Low — the offline cloud module is a self-contained
integration layer that appears to open its own raw connections using its own module-level
paths. However, if the module ever gains a call to the central pool, isolation would
silently break in the same way `test_database.py` did. A future hardening step would
be to also patch `PacsClient.utils.data_paths.DATABASE_FILE` in `_temp_offline_cloud_env()`.

### `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`

The `dicom.db` / `get_db_connection` text appears only inside string literals (log-line
fixtures). No actual DB access. **Safe.**

### `tools/diagnostics/` scripts

Several diagnostic scripts (`_diag_series_db2.py`, `_diag_series_pipeline.py`,
`_run_diag_34621.py`) do open the production DB directly — this is expected and correct
for diagnostic tooling; they are not part of the test suite and do not run under pytest.

---

## Verification queries

### Pre-fix (baseline)
```
test_tables=87, test_patients=946, patients_total=1309, studies_total=460
```

### Post-cleanup (final confirmed state)
```
POST-CLEANUP: test_tables=0, test_patients=0, patients_total=363, studies_total=374
quick_check=ok, fk_check=clean
```

---

## pytest output

```
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-9.0.3, pluggy-1.6.0
rootdir: E:\ai-pacs\ai-pacs codes\ai-pacs beta version
configfile: pyproject.toml
collected 1 item

tests/database/test_database.py::test_database_kpis PASSED               [100%]

============================== 1 passed in 0.88s
==============================
```

The test function `test_database_kpis` contains 23 internal KPI assertions; all pass.  
The test used a temp DB (`C:\Users\...\db_test_...\test_dicom.db`). Production DB unchanged.

---

## Risks and remaining notes

| Item | Severity | Note |
|------|----------|------|
| `offline_cloud_server` partial isolation | Low | Patches module-level copy only; central pool not affected today but could be in future |
| `cleanup_connection_pools()` not reused | Cosmetic | Existing public function in `database._pool` does the same work as `_clear_connection_pool()`; spec requested the helper explicitly |
| `--vacuum` not applied | None | Intentional; noted above |
| Diagnostic scripts read production DB | Expected | Not part of test suite; behaviour is correct |

---

## Deviations from spec

**None.** Every attribute name (`_connection_pool`, `_pool_lock`, `DATABASE_FILE`,
in-function import pattern) matched exactly what was documented in the task spec.
No guessing, no trial-and-error, no fallback patching required.
