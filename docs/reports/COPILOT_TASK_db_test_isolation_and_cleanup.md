# Copilot Agent Task — Fix DB Test Isolation & Clean Up Leaked Test Pollution

> **Paste this whole file into the VS Code Copilot agent.** It is self-contained.
> Project: **AI-PACS** — a Python / PySide6 medical imaging (PACS / DICOM) workstation.
> Repo root: `E:\ai-pacs\ai-pacs codes\ai-pacs beta version\`

---

## 0. Your role and working style

You are an autonomous engineering agent working on a clinical imaging product.
Work **conservatively**. Stability and avoiding regressions outweigh speed.

- Understand before editing. Read every file named below **before** changing anything.
- Make **minimal, isolated, reversible** edits. Do not refactor unrelated code.
- Do **not** modify the database schema, the viewer, networking/sockets, the
  connection-pool internals, or any production code path. The only source file you
  may edit is the **test file** named in Task 1. Everything else is read-only review
  plus running a script that already exists.
- If anything is ambiguous or you find a second defect, **stop and report it** rather
  than guessing.
- Produce the detailed report described in Section 7 when finished.

---

## 1. Background — root cause (already diagnosed; verify, don't re-debug)

`tests/database/test_database.py` is supposed to run against an **isolated temporary
database**. It does not. It has been writing into the **live clinical database**
`user_data/database/dicom.db` on every run.

Why the isolation fails:

1. `tests/database/test_database.py` → `_setup_temp_db()` sets
   `database.core._DB_PATH = temp_db`.
2. **Nothing in the codebase reads `database.core._DB_PATH`.** It is a dead attribute.
3. `database/core.py` is only a **re-export shim** (it re-exports symbols from
   `database/_pool.py`, `database/dicom_db.py`, etc.).
4. The real connection factory is `database/_pool.py` →
   `_create_sqlite_connection()`. It resolves the path with, **inside the function
   body**, `from PacsClient.utils.data_paths import DATABASE_FILE` and then
   `db = str(DATABASE_FILE)`.
5. `DATABASE_FILE` is a module-level `Path` defined in
   `PacsClient/utils/data_paths.py` (`DATABASE_FILE = DATABASE_DIR / "dicom.db"`).
6. The connection pool itself lives in `database/_pool.py` as the module dict
   `_connection_pool` (keyed by `thread_id`) guarded by `_pool_lock`. The test's
   `db_core._pool = []` / `db_core._pool_lock = threading.Lock()` reset targets
   attributes that the pool logic never uses — another no-op.
7. The test also has **no `DROP TABLE` cleanup**; teardown only `rmtree`s the unused
   temp directory.

Net effect: every `init_database()`, every CRUD insert, and every `CREATE TABLE` in
the test executed against production `dicom.db`.

**Key technical fact that makes the fix work:** because
`_create_sqlite_connection()` does `from PacsClient.utils.data_paths import DATABASE_FILE`
**inside the function** (not at module top level), patching the module attribute
`PacsClient.utils.data_paths.DATABASE_FILE` at runtime **is** picked up by every
subsequent connection. Confirm this by reading `database/_pool.py` before editing.

---

## 2. Evidence of damage (state captured 2026-05-24)

Roughly **43 test runs** leaked into `user_data/database/dicom.db`:

| Leaked artifact | Count | Identifying signature |
|---|---|---|
| Orphan tables | 87 | `_commit_test_*` (43), `_nocommit_test_*` (43), `_test_rollback` (1) |
| Synthetic patients | 946 | `patient_id` LIKE `PID-%` / `THREAD-%` / `SRCH-%` |
| Synthetic studies | 86 | children of the synthetic patients |
| Synthetic series | 43 | children of the synthetic studies |
| Synthetic instances | 43 | children of the synthetic series |

Real clinical data underneath: ~363 patients, ~374 studies, ~3,411 series,
~120,136 instances. Real patients use **numeric** `patient_id` values
(e.g. `40740`, name `ZAMANI^AZAM`) and never match the test prefixes.
Every synthetic patient is confirmed by **two** signals — the id prefix **and** a
fixed test `patient_name` (`TestPatient^DB`, `SearchTest^Patient`, or
`Thread%Patient%`).

---

## 3. TASK 1 — Fix the test harness (the only source-code edit)

**File to edit:** `tests/database/test_database.py` — and **only** this file.

Replace the two functions `_setup_temp_db()` and `_teardown_temp_db()` (and the
two module globals above them, if needed) with the implementation below. Add the
small helper `_clear_connection_pool()`. Do **not** change any of the seven
`scenario_*` functions, `main()`, `test_database_kpis()`, or what they assert —
only the isolation mechanism changes.

```python
def _setup_temp_db():
    """Redirect the database to an isolated temp file for testing.

    The real DB path is resolved INSIDE
    database._pool._create_sqlite_connection() from
    PacsClient.utils.data_paths.DATABASE_FILE, so that module attribute is what
    we patch. (The old code patched database.core._DB_PATH, which nothing reads.)
    """
    global _TEMP_DIR, _ORIGINAL_DB
    _TEMP_DIR = tempfile.mkdtemp(prefix="db_test_")
    temp_db = os.path.join(_TEMP_DIR, "test_dicom.db")

    import PacsClient.utils.data_paths as data_paths
    import database._pool as db_pool

    # Redirect the path the connection factory actually uses.
    _ORIGINAL_DB = data_paths.DATABASE_FILE
    data_paths.DATABASE_FILE = Path(temp_db)

    # Drop any pooled connections that may still point at the real DB.
    _clear_connection_pool(db_pool)

    # Fail LOUDLY if isolation did not take effect — never silently fall back
    # to the production database.
    from database.core import get_db_connection
    with get_db_connection() as conn:
        actual = conn.execute("PRAGMA database_list").fetchall()[0][2]
    if os.path.abspath(actual or "") != os.path.abspath(temp_db):
        raise RuntimeError(
            f"Test DB isolation FAILED — connected to {actual!r}, expected "
            f"{temp_db!r}. Aborting to avoid polluting the production database."
        )
    return temp_db


def _clear_connection_pool(db_pool):
    """Close and drop every pooled sqlite connection in database._pool."""
    try:
        with db_pool._pool_lock:
            for conns in list(db_pool._connection_pool.values()):
                for c in conns:
                    try:
                        c.close()
                    except Exception:
                        pass
            db_pool._connection_pool.clear()
    except Exception:
        pass


def _teardown_temp_db():
    """Restore the production DB path and clean up the temp database."""
    global _TEMP_DIR, _ORIGINAL_DB

    import PacsClient.utils.data_paths as data_paths
    import database._pool as db_pool

    _clear_connection_pool(db_pool)

    if _ORIGINAL_DB is not None:
        data_paths.DATABASE_FILE = _ORIGINAL_DB

    if _TEMP_DIR and os.path.exists(_TEMP_DIR):
        shutil.rmtree(_TEMP_DIR, ignore_errors=True)
```

Notes:
- `Path`, `os`, `shutil`, `tempfile`, `threading` are already imported at the top
  of the file — confirm before relying on them; add nothing unnecessary.
- Keep the module globals `_TEMP_DIR = None` and `_ORIGINAL_DB = None`.
- Before editing, **read** `database/_pool.py`, `database/core.py`, and
  `PacsClient/utils/data_paths.py` to confirm the names `_connection_pool`,
  `_pool_lock`, `DATABASE_FILE`, and the in-function import still match. If any
  name differs in the current code, adapt and **note it in the report** — do not
  blindly paste.

---

## 4. TASK 2 — Run the cleanup of the leaked data

A cleanup script **already exists** in the repo (created during the diagnosis):

`tools/maintenance/cleanup_test_pollution.py`

It is **dry-run by default**, takes a consistent backup before any write, drops the
87 orphan tables, deletes the 946 synthetic patients in child→parent order
(instances → series → studies → patients), then verifies with `PRAGMA quick_check`
and `PRAGMA foreign_key_check`.

Steps:

1. **Read the whole script** and confirm it is correct and safe. Specifically check:
   - It only targets tables matching `_commit_test_%`, `_nocommit_test_%`,
     `_test_rollback`.
   - The patient delete is **double-guarded** — it requires the id prefix
     (`PID-`/`THREAD-`/`SRCH-`) **AND** a test `patient_name`. It must **never**
     delete by `study_description` (`"CT Abdomen"` is also a legitimate real
     description).
   - It backs up `user_data/database/dicom.db` before writing.
   - It uses `BEGIN IMMEDIATE` and rolls back cleanly if the DB is locked.
2. Run the **dry run** first and capture the output:
   `python tools/maintenance/cleanup_test_pollution.py`
   Expected plan: 87 tables, 946 patients, 86 studies, 43 series, 43 instances.
3. **Ensure the AI-PACS application is fully closed** (the DB must not be locked).
4. Run the real cleanup and capture the output:
   `python tools/maintenance/cleanup_test_pollution.py --apply`
   - If the script reports the database is locked, **stop**, leave everything as-is,
     and report that the app must be closed and the command re-run. The script makes
     no changes in that case.
5. Do **not** pass `--vacuum` unless you have explicitly confirmed the app is closed;
   `VACUUM` is optional and not required. Note this decision in the report.
6. Confirm the script kept its automatic timestamped backup under `backups/`.

Do not hand-write your own `DELETE`/`DROP` SQL against the live DB. Use the script.

---

## 5. TASK 3 — Review related pipeline connections (read-only investigation)

Without changing code, investigate and report on the surrounding database pipeline:

1. **Other tests with the same flaw.** Search the whole `tests/` tree for any test
   that opens or initialises the database. For each, confirm whether it isolates
   correctly (uses `tmp_path`, a temp dir, or now patches
   `data_paths.DATABASE_FILE`) or whether it can also write to production
   `dicom.db`. Pay attention to anything referencing `_DB_PATH`, `DATABASE_FILE`,
   `init_database`, `get_db_connection`, or `dicom.db`. Known files to check at
   minimum: `tests/database/test_database.py`,
   `tests/printing/test_printing_series_repository.py`,
   `tests/offline_cloud_server/test_offline_cloud_server.py`,
   `tests/utils/test_structured_logging.py`. Report findings; do **not** fix other
   tests in this task unless one is actively dangerous — if so, stop and report.
2. **conftest.py / pytest config.** Check for any `conftest.py` or pytest settings
   that import database modules early (which could bind paths before a test patches
   them). Report what you find.
3. **Path resolution.** Confirm `PacsClient/utils/data_paths.py` is the single
   source of truth for the DB path, and that `database/_pool.py` is the only place
   that opens raw sqlite connections to it. Report any other code that opens
   `dicom.db` directly (e.g. files under `tools/diagnostics/` — note them, they are
   diagnostics, not a concern, but list them).
4. **Pool ownership.** Confirm the connection pool is `database._pool._connection_pool`
   and that `cleanup_connection_pools()` exists and does the same closing the test
   helper now does — note whether the test could reuse it instead.

---

## 6. Constraints & regression-prevention checklist

Honour every item:

- **Only one source file may be modified:** `tests/database/test_database.py`.
  Task 2 runs an existing script; Task 3 is read-only.
- Do **not** modify the database schema, migrations, the connection pool, the
  viewer, sockets/networking, or any clinical workflow code.
- Do **not** "fix" the denormalised counters (`number_of_series`,
  `number_of_instances`, `image_count`). Their drift is expected for on-demand
  DICOM downloads and is out of scope.
- Do **not** drop the two redundant indexes (`idx_studies_reportStatus`,
  `idx_instances_series_fk`). Out of scope for this task.
- Do **not** delete, move, or overwrite anything under `backups/`.
- Do **not** touch `sqlite_sequence` — its AUTOINCREMENT high-water marks must be
  left intact so primary keys are never reused.
- The cleanup must remove **only** confirmed-synthetic rows. If the script's
  dry-run reports counts that differ materially from 87 / 946 / 86 / 43 / 43,
  **stop and report** instead of running `--apply`.
- Preserve the behaviour and assertions of all seven `scenario_*` test functions.
  The fix changes *where* the test runs, never *what* it checks.
- A fresh backup of `dicom.db` must exist before any write (the script does this —
  verify it).
- If a write step fails or the DB is locked, leave the database unchanged and
  report it; never retry destructively.

---

## 7. Expected final behavior

When you are done:

1. Running `tests/database/test_database.py` (directly **and** via
   `pytest`) executes entirely against a temp database. It creates **zero** new
   tables and **zero** new rows in `user_data/database/dicom.db`.
2. If isolation ever fails again, the test **raises `RuntimeError` immediately**
   at setup instead of silently writing to production.
3. All seven scenarios still pass (same KPI pass/fail outcome as before the change).
4. `user_data/database/dicom.db` contains **0** tables matching `_commit_test_%`,
   `_nocommit_test_%`, or `_test_rollback`, and **0** patients with
   `patient_id` LIKE `PID-%` / `THREAD-%` / `SRCH-%`.
5. ~363 real patients, ~374 real studies remain, untouched.
6. `PRAGMA quick_check` returns `ok` and `PRAGMA foreign_key_check` returns no rows.

---

## 8. Verification steps you must perform

1. **Before** the test fix and cleanup, record baseline counts (use Python +
   sqlite3, read-only, app closed). Run this and save the output:
   ```sql
   SELECT
     (SELECT COUNT(*) FROM sqlite_master WHERE type='table'
        AND (name LIKE '\_commit\_test\_%' ESCAPE '\'
             OR name LIKE '\_nocommit\_test\_%' ESCAPE '\'
             OR name='_test_rollback'))                       AS test_tables,
     (SELECT COUNT(*) FROM patients
        WHERE patient_id LIKE 'PID-%' OR patient_id LIKE 'THREAD-%'
              OR patient_id LIKE 'SRCH-%')                     AS test_patients,
     (SELECT COUNT(*) FROM patients)                           AS patients_total;
   ```
2. Apply the Task 1 fix.
3. Run the test isolation check: run `python tests/database/test_database.py`,
   then **re-run the query from step 1**. `test_tables` and `test_patients` must be
   **unchanged from the post-cleanup baseline** (i.e. the test created nothing in
   the real DB). Also run `python -m pytest tests/database/test_database.py -v`.
4. Run Task 2 (dry-run, then `--apply` with the app closed).
5. After cleanup, run the query again: `test_tables` = 0, `test_patients` = 0,
   `patients_total` ≈ 363. Run `PRAGMA quick_check` and `PRAGMA foreign_key_check`.
6. Confirm the timestamped backup exists under `backups/`.

---

## 9. Required final report

After completing everything, produce a detailed report (`COPILOT_REPORT_db_cleanup.md`
in the repo root) containing:

1. **Summary** — what was done, and whether the expected final behavior (Section 7)
   is fully met.
2. **Task 1 — test fix:** the exact diff of `tests/database/test_database.py`, and
   confirmation that the names you patched (`DATABASE_FILE`, `_connection_pool`,
   `_pool_lock`, the in-function import) matched the current source — note any
   deviation you had to adapt to.
3. **Task 2 — cleanup:** the dry-run output, the `--apply` output, the backup file
   path and size, and the before/after counts. State explicitly whether the DB was
   locked at any point.
4. **Task 3 — pipeline review:** for every test/file that touches the database,
   whether it is properly isolated or at risk, and any other place that opens
   `dicom.db` directly. List `conftest.py` findings.
5. **Verification:** the output of every query/command in Section 8, with the
   before/after numbers side by side.
6. **Test results:** full pytest output for `tests/database/test_database.py`.
7. **Risks & remaining issues:** anything you could not verify, any other test you
   believe is still unsafe, and any follow-up you recommend (do not act on it).
8. **Deviations:** anything you did differently from this prompt and why.

Be honest and precise. If something did not work or could not be verified, say so
explicitly rather than implying success.
```
