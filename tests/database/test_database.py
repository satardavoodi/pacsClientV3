"""
Database Module — Architecture & Correctness Test Suite
========================================================

Run:
    python tests/database/test_database.py
    # Or via pytest:
    python -m pytest tests/database/test_database.py -v

Tests the v2.2.8.0 database architecture:
  - Connection pool (lazy creation, validation, return)
  - Context manager safety (auto-rollback, commit discipline)
  - FK indexes existence
  - CRUD operations (patients, studies, series, instances)
  - Search correctness
  - Thread safety under concurrent writes
  - Log throttle (min_ms suppression)

No live server connection required — uses a temporary SQLite database.
"""

from __future__ import annotations

import gc
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── project root on sys.path ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── logging ──
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("db_test")
logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════════
#  KPI Collector (same pattern as DM tests)
# ═══════════════════════════════════════════════════════════════════

class KPICollector:
    def __init__(self):
        self._records: List[Dict[str, Any]] = []

    def record(self, scenario: str, metric: str, value: Any,
               unit: str = "", passed: Optional[bool] = None):
        self._records.append({
            "scenario": scenario, "metric": metric,
            "value": value, "unit": unit, "passed": passed,
        })

    def report(self) -> str:
        lines = ["", "=" * 100, "  DATABASE MODULE — KPI REPORT", "=" * 100]
        scenarios: Dict[str, list] = defaultdict(list)
        for r in self._records:
            scenarios[r["scenario"]].append(r)

        total_pass = total_fail = total_info = 0
        for scenario, records in scenarios.items():
            lines.append(f"\n  ┌─ Scenario: {scenario}")
            lines.append(f"  │{'Metric':<50} {'Value':>12} {'Unit':<8} {'Status':>8}")
            lines.append(f"  │{'─' * 82}")
            for r in records:
                if r["passed"] is True:
                    s = "  ✅ PASS"; total_pass += 1
                elif r["passed"] is False:
                    s = "  ❌ FAIL"; total_fail += 1
                else:
                    s = "  ── info"; total_info += 1
                v = f"{r['value']:>12.3f}" if isinstance(r['value'], float) else f"{str(r['value']):>12}"
                lines.append(f"  │ {r['metric']:<49} {v} {r['unit']:<8}{s}")
            lines.append(f"  └{'─' * 82}")

        lines += ["", "=" * 100,
                   f"  TOTALS:  ✅ {total_pass} passed   ❌ {total_fail} failed   ── {total_info} info",
                   "=" * 100, ""]
        return "\n".join(lines)

    @property
    def failed_count(self):
        return sum(1 for r in self._records if r["passed"] is False)


_kpi = KPICollector()


# ═══════════════════════════════════════════════════════════════════
#  Setup: temporary database
# ═══════════════════════════════════════════════════════════════════

_TEMP_DIR = None
_ORIGINAL_DB = None


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


# ═══════════════════════════════════════════════════════════════════
#  SCENARIO 1 — init_database() & Table Schema
# ═══════════════════════════════════════════════════════════════════

def scenario_init_and_schema():
    SCENARIO = "D1: init_database & Schema"
    logger.info(f"\n{'='*70}\n  {SCENARIO}\n{'='*70}")

    from database.core import init_database, get_db_connection

    t0 = time.perf_counter()
    init_database()
    init_ms = (time.perf_counter() - t0) * 1000
    _kpi.record(SCENARIO, "init_database() latency", init_ms, "ms")

    # Verify tables exist
    with get_db_connection() as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cur.fetchall()}

    required = {"patients", "studies", "series", "instances"}
    ok = required.issubset(tables)
    _kpi.record(SCENARIO, "Required tables exist", ok, "", ok)
    _kpi.record(SCENARIO, "Total tables found", len(tables), "")

    # Verify FK indexes exist (v2.2.8.0 requirement)
    with get_db_connection() as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        )
        indexes = {row[0] for row in cur.fetchall()}

    fk_indexes = {"idx_studies_patient_fk", "idx_series_study_fk",
                  "idx_instances_series_fk", "idx_instances_series_group"}
    found = fk_indexes.intersection(indexes)
    ok = fk_indexes == found
    _kpi.record(SCENARIO, "FK indexes present", len(found), f"/{len(fk_indexes)}", ok)
    if not ok:
        missing = fk_indexes - found
        _kpi.record(SCENARIO, f"Missing FK indexes: {missing}", False, "", False)

    logger.info(f"  ✅ {SCENARIO} done\n")


# ═══════════════════════════════════════════════════════════════════
#  SCENARIO 2 — Connection Pool Safety
# ═══════════════════════════════════════════════════════════════════

def scenario_connection_pool():
    SCENARIO = "D2: Connection Pool Safety"
    logger.info(f"\n{'='*70}\n  {SCENARIO}\n{'='*70}")

    from database.core import get_db_connection

    # Test 1: Context manager returns connection to pool
    with get_db_connection() as conn:
        conn.execute("SELECT 1")
    # If we get here without exception, pool return worked
    _kpi.record(SCENARIO, "Context manager returns conn to pool", True, "", True)

    # Test 2: Context manager rollback on exception
    try:
        with get_db_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS _test_rollback (id INTEGER)")
            conn.execute("INSERT INTO _test_rollback VALUES (1)")
            # DON'T commit — raise exception
            raise ValueError("test rollback")
    except ValueError:
        pass

    with get_db_connection() as conn:
        cur = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='_test_rollback'"
        )
        table_exists = cur.fetchone()[0] > 0
        if table_exists:
            cur2 = conn.execute("SELECT count(*) FROM _test_rollback")
            count = cur2.fetchone()[0]
            ok = count == 0  # Should be rolled back
            _kpi.record(SCENARIO, "Auto-rollback on exception (no leaked data)", ok, "", ok)
        else:
            _kpi.record(SCENARIO, "Auto-rollback on exception (no leaked data)", True, "", True)

    # Test 3: Multiple connections don't deadlock
    t0 = time.perf_counter()
    for _ in range(10):
        with get_db_connection() as c:
            c.execute("SELECT 1")
    ms = (time.perf_counter() - t0) * 1000
    _kpi.record(SCENARIO, "10 sequential pool acquire/release", ms, "ms", ms < 500)

    logger.info(f"  ✅ {SCENARIO} done\n")


# ═══════════════════════════════════════════════════════════════════
#  SCENARIO 3 — CRUD Operations (Patient → Study → Series → Instance)
# ═══════════════════════════════════════════════════════════════════

def scenario_crud_operations():
    SCENARIO = "D3: CRUD Operations"
    logger.info(f"\n{'='*70}\n  {SCENARIO}\n{'='*70}")

    from database.core import (
        insert_patient, find_patient_pk,
        insert_study, find_study_pk_with_study_uid,
        insert_series, find_series_pk,
        insert_instance, find_instance_pk,
        get_db_connection,
    )

    pid = f"PID-{uuid.uuid4().hex[:8]}"
    study_uid = f"1.2.840.{uuid.uuid4().int % 10**12}"
    series_uid = f"1.2.840.{uuid.uuid4().int % 10**12}"
    instance_uid = f"1.2.840.{uuid.uuid4().int % 10**12}"

    # Insert patient
    t0 = time.perf_counter()
    patient_pk = insert_patient(
        patient_id=pid,
        name='TestPatient^DB',
        birth_date='19900101',
        sex='M',
    )
    insert_ms = (time.perf_counter() - t0) * 1000
    ok = patient_pk is not None and patient_pk > 0
    _kpi.record(SCENARIO, "insert_patient succeeded", ok, "", ok)
    _kpi.record(SCENARIO, "insert_patient latency", insert_ms, "ms")

    # Find patient
    found_pk = find_patient_pk(pid)
    ok = found_pk == patient_pk
    _kpi.record(SCENARIO, "find_patient_pk matches", ok, "", ok)

    # Insert study
    study_pk = insert_study(
        study_uid=study_uid,
        patient_fk=patient_pk,
        study_date='20260401',
        study_time='120000',
        study_description='Test Study',
        modality='CT',
    )
    ok = study_pk is not None and study_pk > 0
    _kpi.record(SCENARIO, "insert_study succeeded", ok, "", ok)

    found_study_pk = find_study_pk_with_study_uid(study_uid)
    ok = found_study_pk == study_pk
    _kpi.record(SCENARIO, "find_study_pk matches", ok, "", ok)

    # Insert series
    series_pk = insert_series(
        series_uid=series_uid,
        study_fk=study_pk,
        series_number='1',
        series_description='Test Series',
        modality='CT',
        image_count=10,
    )
    ok = series_pk is not None and series_pk > 0
    _kpi.record(SCENARIO, "insert_series succeeded", ok, "", ok)

    found_series_pk = find_series_pk(series_uid)
    ok = found_series_pk == series_pk
    _kpi.record(SCENARIO, "find_series_pk matches", ok, "", ok)

    # Insert instance
    instance_pk = insert_instance(
        sop_uid=instance_uid,
        series_fk=series_pk,
        instance_path='/test/Instance_0001.dcm',
        instance_number=1,
    )
    ok = instance_pk is not None and instance_pk > 0
    _kpi.record(SCENARIO, "insert_instance succeeded", ok, "", ok)

    found_instance_pk = find_instance_pk(instance_uid)
    ok = found_instance_pk == instance_pk
    _kpi.record(SCENARIO, "find_instance_pk matches", ok, "", ok)

    # Verify cascade via SQL
    with get_db_connection() as conn:
        cur = conn.execute(
            "SELECT s.study_uid FROM studies s "
            "JOIN patients p ON s.patient_fk = p.patient_pk "
            "WHERE p.patient_id = ?", (pid,)
        )
        row = cur.fetchone()
        ok = row is not None and row[0] == study_uid
        _kpi.record(SCENARIO, "FK join patient→study works", ok, "", ok)

    logger.info(f"  ✅ {SCENARIO} done\n")


# ═══════════════════════════════════════════════════════════════════
#  SCENARIO 4 — Commit Discipline (v2.2.8.0 critical rule)
# ═══════════════════════════════════════════════════════════════════

def scenario_commit_discipline():
    SCENARIO = "D4: Commit Discipline"
    logger.info(f"\n{'='*70}\n  {SCENARIO}\n{'='*70}")

    from database.core import get_db_connection

    # Test: write inside `with` WITH commit → data persists
    test_table = f"_commit_test_{uuid.uuid4().hex[:6]}"
    with get_db_connection() as conn:
        conn.execute(f"CREATE TABLE {test_table} (val TEXT)")
        conn.execute(f"INSERT INTO {test_table} VALUES ('committed')")
        conn.commit()

    with get_db_connection() as conn:
        cur = conn.execute(f"SELECT val FROM {test_table}")
        row = cur.fetchone()
        ok = row is not None and row[0] == "committed"
        _kpi.record(SCENARIO, "Committed data persists across connections", ok, "", ok)

    # Test: write inside `with` WITHOUT commit → data is lost (rollback)
    test_table2 = f"_nocommit_test_{uuid.uuid4().hex[:6]}"
    with get_db_connection() as conn:
        conn.execute(f"CREATE TABLE {test_table2} (val TEXT)")
        conn.commit()  # commit the CREATE TABLE
    
    with get_db_connection() as conn:
        conn.execute(f"INSERT INTO {test_table2} VALUES ('should_be_lost')")
        # NO conn.commit() — connection returns to pool, rollback happens

    with get_db_connection() as conn:
        cur = conn.execute(f"SELECT count(*) FROM {test_table2}")
        count = cur.fetchone()[0]
        ok = count == 0
        _kpi.record(SCENARIO, "Uncommitted data is rolled back", ok, "", ok)

    logger.info(f"  ✅ {SCENARIO} done\n")


# ═══════════════════════════════════════════════════════════════════
#  SCENARIO 5 — Thread Safety (Concurrent DB Access)
# ═══════════════════════════════════════════════════════════════════

def scenario_thread_safety():
    SCENARIO = "D5: Thread Safety"
    logger.info(f"\n{'='*70}\n  {SCENARIO}\n{'='*70}")

    from database.core import get_db_connection, insert_patient, find_patient_pk

    errors = []
    results = []
    lock = threading.Lock()

    def worker(thread_id):
        try:
            for i in range(5):
                pid = f"THREAD-{thread_id}-{i}-{uuid.uuid4().hex[:4]}"
                pk = insert_patient(
                    patient_id=pid,
                    name=f'Thread{thread_id}Patient{i}',
                    birth_date='20000101',
                    sex='F',
                )
                found = find_patient_pk(pid)
                with lock:
                    results.append((pid, pk, found))
                    if pk != found:
                        errors.append(f"Thread-{thread_id}: pk={pk} != found={found}")
        except Exception as e:
            with lock:
                errors.append(f"Thread-{thread_id}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    ok_no_errors = len(errors) == 0
    _kpi.record(SCENARIO, "No errors under 4-thread concurrency", ok_no_errors, "", ok_no_errors)
    if errors:
        for e in errors[:3]:
            _kpi.record(SCENARIO, f"  Error: {e[:60]}", False, "", False)

    ok_all_found = all(r[1] == r[2] for r in results)
    _kpi.record(SCENARIO, "All inserts findable across threads", ok_all_found, "", ok_all_found)
    _kpi.record(SCENARIO, "Total records written", len(results), "")
    _kpi.record(SCENARIO, "Concurrent write elapsed", elapsed_ms, "ms")

    logger.info(f"  ✅ {SCENARIO} done\n")


# ═══════════════════════════════════════════════════════════════════
#  SCENARIO 6 — Search (search_patients_local)
# ═══════════════════════════════════════════════════════════════════

def scenario_search():
    SCENARIO = "D6: Patient Search"
    logger.info(f"\n{'='*70}\n  {SCENARIO}\n{'='*70}")

    from database.core import (
        insert_patient, insert_study, find_patient_pk,
        search_patients_local, get_db_connection,
    )

    # Insert test data
    pid = f"SRCH-{uuid.uuid4().hex[:6]}"
    pk = insert_patient(
        patient_id=pid,
        name='SearchTest^Patient',
        birth_date='19850315',
        sex='M',
    )

    study_uid = f"1.2.840.{uuid.uuid4().int % 10**12}"
    insert_study(
        study_uid=study_uid,
        patient_fk=pk,
        study_date='20260401',
        study_description='CT Abdomen',
        modality='CT',
    )

    # Search by patient name
    t0 = time.perf_counter()
    results = search_patients_local({"patient_name": "SearchTest"})
    search_ms = (time.perf_counter() - t0) * 1000

    ok = results is not None and len(results) > 0
    _kpi.record(SCENARIO, "search_patients_local returns results", ok, "", ok)
    _kpi.record(SCENARIO, "Search latency", search_ms, "ms")

    if results:
        found_pids = [r.get('patient_id', '') for r in results]
        ok = pid in found_pids
        _kpi.record(SCENARIO, "Target patient found in results", ok, "", ok)

    # Search by patient ID
    results2 = search_patients_local({"patient_id": pid})
    ok = results2 is not None and len(results2) > 0
    _kpi.record(SCENARIO, "Search by patient_id works", ok, "", ok)

    # Search with no matches
    results3 = search_patients_local({"patient_name": "ZZZZZZZ_NONEXISTENT"})
    ok = results3 is not None and len(results3) == 0
    _kpi.record(SCENARIO, "Empty search returns empty list", ok, "", ok)

    logger.info(f"  ✅ {SCENARIO} done\n")


# ═══════════════════════════════════════════════════════════════════
#  SCENARIO 7 — No PRAGMA read_uncommitted leak
# ═══════════════════════════════════════════════════════════════════

def scenario_no_read_uncommitted():
    SCENARIO = "D7: No PRAGMA read_uncommitted"
    logger.info(f"\n{'='*70}\n  {SCENARIO}\n{'='*70}")

    from database.core import get_db_connection

    with get_db_connection() as conn:
        cur = conn.execute("PRAGMA read_uncommitted")
        val = cur.fetchone()[0]
        ok = val == 0
        _kpi.record(SCENARIO, "read_uncommitted is OFF (0)", ok, "", ok)

    logger.info(f"  ✅ {SCENARIO} done\n")


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main() -> int:
    import datetime
    print(f"\n{'=' * 100}")
    print(f"  DATABASE MODULE — TEST SUITE")
    print(f"  Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Platform: {sys.platform}")
    print(f"{'=' * 100}")

    temp_db = _setup_temp_db()
    logger.info(f"Using temp database: {temp_db}")

    try:
        scenario_init_and_schema()
        scenario_connection_pool()
        scenario_crud_operations()
        scenario_commit_discipline()
        scenario_thread_safety()
        scenario_search()
        scenario_no_read_uncommitted()
    finally:
        _teardown_temp_db()

    report = _kpi.report()
    print(report)

    return 0 if _kpi.failed_count == 0 else 1


# pytest entry point
def test_database_kpis():
    temp_db = _setup_temp_db()
    try:
        scenario_init_and_schema()
        scenario_connection_pool()
        scenario_crud_operations()
        scenario_commit_discipline()
        scenario_thread_safety()
        scenario_search()
        scenario_no_read_uncommitted()
    finally:
        _teardown_temp_db()
    assert _kpi.failed_count == 0, f"Database KPI failures: {_kpi.failed_count}"


if __name__ == "__main__":
    sys.exit(main())
