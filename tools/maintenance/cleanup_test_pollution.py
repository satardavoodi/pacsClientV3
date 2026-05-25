"""
cleanup_test_pollution.py — one-time maintenance: remove leaked test data from dicom.db
========================================================================================

WHY THIS EXISTS
---------------
`tests/database/test_database.py` was meant to run against an isolated temp database,
but its `_setup_temp_db()` patched `database.core._DB_PATH` — an attribute that nothing
in the codebase reads. The real DB path is resolved from
`PacsClient.utils.data_paths.DATABASE_FILE`. As a result, every run of that test wrote
into the LIVE clinical database `user_data/database/dicom.db`.

Evidence found 2026-05-24 (≈43 test runs leaked in):
  - 87 orphan schema tables  : _commit_test_* (43), _nocommit_test_* (43), _test_rollback
  - 946 synthetic patients   : patient_id LIKE 'PID-%' / 'THREAD-%' / 'SRCH-%'
  - 86 synthetic studies + 43 synthetic series + 43 synthetic instances (children of those)

Every targeted row is confirmed synthetic by TWO independent signals (id prefix AND the
fixed test patient_name). Real clinical patients use numeric ids (e.g. 40740) and were
verified to never match these prefixes.

WHAT IT DOES
------------
  1. Makes a consistent backup of dicom.db  (SQLite online-backup API).
  2. Drops the 87 orphan _commit_test_* / _nocommit_test_* / _test_rollback tables.
  3. Deletes the synthetic patients and their cascaded studies/series/instances,
     in child→parent order (so it is correct regardless of the FK pragma).
  4. Verifies row counts before/after and runs PRAGMA quick_check.
  5. Checkpoints the WAL. Optional --vacuum to compact the file.

SAFETY
------
  - DRY-RUN BY DEFAULT. Nothing is written unless you pass --apply.
  - Always takes a timestamped backup before any write.
  - The patient delete is double-guarded (id prefix AND test name).
  - Refuses to run if the DB is locked — close the AI-PACS app first.

USAGE
-----
    # from the project root, with the AI-PACS app CLOSED:
    python tools/maintenance/cleanup_test_pollution.py            # dry run (shows plan)
    python tools/maintenance/cleanup_test_pollution.py --apply     # perform cleanup
    python tools/maintenance/cleanup_test_pollution.py --apply --vacuum   # + compact file
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sqlite3
import sys
from pathlib import Path

# ── Locate the database (this file lives at tools/maintenance/) ──────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _PROJECT_ROOT / "user_data" / "database" / "dicom.db"
_BACKUP_DIR = _PROJECT_ROOT / "backups"

# Synthetic-patient signatures left by tests/database/test_database.py
_TEST_ID_PREFIXES = ("PID-", "THREAD-", "SRCH-")
_TEST_NAMES = ("TestPatient^DB", "SearchTest^Patient")  # + LIKE 'Thread%Patient%'

# WHERE clause that selects ONLY confirmed synthetic patients (double-guarded).
_TEST_PATIENT_WHERE = (
    "( (patient_id LIKE 'PID-%' OR patient_id LIKE 'THREAD-%' OR patient_id LIKE 'SRCH-%') "
    "  AND (patient_name IN ('TestPatient^DB','SearchTest^Patient') "
    "       OR patient_name LIKE 'Thread%Patient%') )"
)


def _hr(title: str) -> None:
    print("\n" + "=" * 78 + f"\n  {title}\n" + "=" * 78)


def _test_table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND ("
        "  name LIKE '\\_commit\\_test\\_%' ESCAPE '\\' "
        "  OR name LIKE '\\_nocommit\\_test\\_%' ESCAPE '\\' "
        "  OR name='_test_rollback') ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _counts(conn: sqlite3.Connection) -> dict:
    test_pids = (
        "SELECT patient_pk FROM patients WHERE " + _TEST_PATIENT_WHERE
    )
    q = {
        "test_tables": "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND ("
                       "name LIKE '\\_commit\\_test\\_%' ESCAPE '\\' "
                       "OR name LIKE '\\_nocommit\\_test\\_%' ESCAPE '\\' "
                       "OR name='_test_rollback')",
        "patients_total": "SELECT COUNT(*) FROM patients",
        "test_patients": f"SELECT COUNT(*) FROM ({test_pids})",
        "test_studies": f"SELECT COUNT(*) FROM studies WHERE patient_fk IN ({test_pids})",
        "test_series": f"SELECT COUNT(*) FROM series WHERE study_fk IN "
                       f"(SELECT study_pk FROM studies WHERE patient_fk IN ({test_pids}))",
        "test_instances": f"SELECT COUNT(*) FROM instances WHERE series_fk IN "
                          f"(SELECT series_pk FROM series WHERE study_fk IN "
                          f"(SELECT study_pk FROM studies WHERE patient_fk IN ({test_pids})))",
    }
    return {k: conn.execute(v).fetchone()[0] for k, v in q.items()}


def _make_backup() -> Path:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = _BACKUP_DIR / f"dicom_pre-cleanup_{stamp}.db"
    src = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)          # online-backup API → consistent even in WAL mode
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove leaked test data from dicom.db")
    ap.add_argument("--apply", action="store_true",
                    help="actually perform the cleanup (default is dry-run)")
    ap.add_argument("--vacuum", action="store_true",
                    help="after cleanup, VACUUM to compact the file (needs exclusive lock)")
    args = ap.parse_args()

    _hr("AI-PACS — test-pollution cleanup")
    print(f"  Database : {_DB_PATH}")
    print(f"  Mode     : {'APPLY (will write)' if args.apply else 'DRY RUN (no changes)'}")

    if not _DB_PATH.exists():
        print(f"\n  ERROR: database not found at {_DB_PATH}")
        return 2

    # Read-only inspection first.
    try:
        ro = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    except sqlite3.Error as e:
        print(f"\n  ERROR opening database: {e}")
        return 2
    before = _counts(ro)
    tbls = _test_table_names(ro)
    ro.close()

    _hr("Will remove")
    print(f"  Orphan test tables ........ {before['test_tables']:>6}")
    print(f"  Synthetic patients ........ {before['test_patients']:>6}  "
          f"(of {before['patients_total']} total)")
    print(f"  Synthetic studies ......... {before['test_studies']:>6}")
    print(f"  Synthetic series .......... {before['test_series']:>6}")
    print(f"  Synthetic instances ....... {before['test_instances']:>6}")

    if not args.apply:
        print("\n  Dry run only — re-run with --apply to perform the cleanup above.")
        print("  (A timestamped backup is taken automatically before any write.)")
        return 0

    if (before["test_tables"] == 0 and before["test_patients"] == 0):
        print("\n  Nothing to clean — database is already free of test pollution.")
        return 0

    # ── Backup ───────────────────────────────────────────────────────────────
    _hr("Backup")
    backup = _make_backup()
    print(f"  Saved consistent backup → {backup}  ({backup.stat().st_size/1_048_576:.1f} MB)")

    # ── Apply ────────────────────────────────────────────────────────────────
    _hr("Applying cleanup")
    conn = sqlite3.connect(str(_DB_PATH), timeout=10.0)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("BEGIN IMMEDIATE")

        for name in tbls:
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        print(f"  Dropped {len(tbls)} orphan test tables.")

        sub = "SELECT patient_pk FROM patients WHERE " + _TEST_PATIENT_WHERE
        di = conn.execute(
            f"DELETE FROM instances WHERE series_fk IN (SELECT series_pk FROM series "
            f"WHERE study_fk IN (SELECT study_pk FROM studies WHERE patient_fk IN ({sub})))"
        ).rowcount
        ds = conn.execute(
            f"DELETE FROM series WHERE study_fk IN "
            f"(SELECT study_pk FROM studies WHERE patient_fk IN ({sub}))"
        ).rowcount
        dst = conn.execute(
            f"DELETE FROM studies WHERE patient_fk IN ({sub})"
        ).rowcount
        dp = conn.execute(
            "DELETE FROM patients WHERE " + _TEST_PATIENT_WHERE
        ).rowcount
        print(f"  Deleted instances={di}  series={ds}  studies={dst}  patients={dp}")

        conn.commit()
    except sqlite3.OperationalError as e:
        conn.rollback()
        print(f"\n  ABORTED — {e}")
        print("  The database is locked. Close the AI-PACS app and re-run.")
        print(f"  No changes were made. Backup is at: {backup}")
        return 3
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        print(f"\n  ABORTED — unexpected error: {e}\n  No changes committed.")
        return 3

    # ── Verify ───────────────────────────────────────────────────────────────
    _hr("Verifying")
    qc = conn.execute("PRAGMA quick_check").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    after = _counts(conn)
    print(f"  quick_check ............... {qc}")
    print(f"  foreign_key_check ......... {'clean' if not fk else f'{len(fk)} VIOLATIONS'}")
    print(f"  Remaining test tables ..... {after['test_tables']}")
    print(f"  Remaining test patients ... {after['test_patients']}")
    print(f"  Patients now .............. {after['patients_total']}")

    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass

    if args.vacuum:
        _hr("VACUUM (compacting file)")
        try:
            conn.isolation_level = None
            conn.execute("VACUUM")
            print("  VACUUM complete.")
        except sqlite3.Error as e:
            print(f"  VACUUM skipped — {e} (needs an exclusive lock; app must be closed)")
    conn.close()

    ok = (qc == "ok" and not fk
          and after["test_tables"] == 0 and after["test_patients"] == 0)
    _hr("DONE" if ok else "DONE — WITH WARNINGS")
    print(f"  Backup retained at: {backup}")
    print("  Restore if needed by copying the backup over user_data/database/dicom.db")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
