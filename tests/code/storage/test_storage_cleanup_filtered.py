"""Filtered patient-cleanup strategies + DB-commit persistence (2026-07-04).

Guards the "Cleanup Strategy is not working" bug class in the Viewer Configuration
Patient Data Cleanup dialog:

  * the filtered strategies used to query patients.created_at / patients.patient_uid,
    columns that do not exist -> every "keep last N days / older than N / oldest N"
    threw a SQL error (Preview showed 0, Execute failed);
  * disk folders are keyed by study_uid, not patient, so deletes removed no files;
  * the _cleanup_*_db helpers never committed, so "Clear ALL" left DB rows behind
    (get_db_connection rolls back on scope exit).

Everything runs against an isolated temp sqlite DB + temp SOURCE_PATH/THUMBNAIL_PATH;
the live dicom.db is never touched. The temp connection context commits on exit so it
faithfully reproduces the production connection contract (explicit commit required).
"""
from __future__ import annotations

import contextlib
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from modules.storage import local_storage_cleanup_manager as lscm


@contextlib.contextmanager
def _temp_db_ctx(db_path):
    # NOTE: deliberately does NOT auto-commit — the code under test must commit
    # itself, exactly like the production pooled connection (which rolls back).
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _setup(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE patients (patient_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                               patient_id TEXT, patient_name TEXT);
        CREATE TABLE studies  (study_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                               study_uid TEXT, patient_fk INTEGER, study_date TEXT,
                               study_time TEXT, study_path TEXT);
        CREATE TABLE series   (series_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                               study_fk INTEGER, thumbnail_path TEXT, main_thumbnail INTEGER);
        CREATE TABLE instances (instance_pk INTEGER PRIMARY KEY AUTOINCREMENT, series_fk INTEGER);
        CREATE TABLE download_progress (progress_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                                        study_uid TEXT, created_at TEXT);
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(lscm, "get_db_connection", lambda: _temp_db_ctx(db))
    src = tmp_path / "patients"
    src.mkdir()
    monkeypatch.setattr(lscm, "SOURCE_PATH", src)
    thumb = tmp_path / "thumbs"
    thumb.mkdir()
    monkeypatch.setattr(lscm, "THUMBNAIL_PATH", thumb)
    # Neutralize the in-memory thumbnail store (no real Qt store in the sandbox).
    monkeypatch.setattr(lscm.LocalStorageCleanupManager, "_clear_thumbnail_store",
                        lambda self, warnings=None: None)
    return db, src, thumb


def _yyyymmdd(days_ago: int) -> str:
    return time.strftime("%Y%m%d", time.localtime(time.time() - days_ago * 86400))


def _add_patient(db, src, patient_id, study_uid, days_ago, with_files=True):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO patients(patient_id, patient_name) VALUES(?, ?)",
                  (patient_id, patient_id))
        pk = c.execute("SELECT patient_pk FROM patients WHERE patient_id=?",
                       (patient_id,)).fetchone()[0]
        study_date = _yyyymmdd(days_ago) if days_ago is not None else None
        c.execute(
            "INSERT INTO studies(study_uid, patient_fk, study_date, study_time) VALUES(?,?,?,?)",
            (study_uid, pk, study_date, "120000"),
        )
        study_pk = c.execute("SELECT study_pk FROM studies WHERE study_uid=?",
                             (study_uid,)).fetchone()[0]
        c.execute("INSERT INTO series(study_fk, main_thumbnail) VALUES(?, 1)", (study_pk,))
        series_pk = c.execute("SELECT series_pk FROM series WHERE study_fk=?",
                              (study_pk,)).fetchone()[0]
        c.execute("INSERT INTO instances(series_fk) VALUES(?)", (series_pk,))
        c.execute("INSERT INTO download_progress(study_uid, created_at) VALUES(?,?)",
                  (study_uid, ""))
    if with_files:
        folder = src / study_uid
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "a.dcm").write_bytes(b"x")


def test_older_than_days_deletes_only_old_and_removes_folders(tmp_path, monkeypatch):
    db, src, thumb = _setup(tmp_path, monkeypatch)
    _add_patient(db, src, "OLD", "1.2.old", days_ago=200)
    _add_patient(db, src, "NEW", "1.2.new", days_ago=5)
    mgr = lscm.LocalStorageCleanupManager()

    assert mgr.count_patients_to_delete("older_than_days", 90) == 1

    res = mgr.cleanup_patients_folder_filtered("older_than_days", 90)
    assert res.success and res.folders_touched == 1 and res.files_deleted == 1
    # Old patient + folder gone; recent one untouched.
    assert not (src / "1.2.old").exists()
    assert (src / "1.2.new" / "a.dcm").exists()
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM patients WHERE patient_id='OLD'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM patients WHERE patient_id='NEW'").fetchone()[0] == 1
        # cascade-agnostic child rows for the old study removed
        assert c.execute("SELECT COUNT(*) FROM studies WHERE study_uid='1.2.old'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM download_progress WHERE study_uid='1.2.old'").fetchone()[0] == 0


def test_keep_recent_days_matches_older_than(tmp_path, monkeypatch):
    db, src, thumb = _setup(tmp_path, monkeypatch)
    _add_patient(db, src, "OLD", "1.2.old", days_ago=60)
    _add_patient(db, src, "NEW", "1.2.new", days_ago=3)
    mgr = lscm.LocalStorageCleanupManager()
    # keep only last 30 days -> deletes the 60-day-old patient
    assert mgr.count_patients_to_delete("keep_recent_days", 30) == 1
    res = mgr.cleanup_patients_folder_filtered("keep_recent_days", 30)
    assert res.success and res.db_rows_affected > 0
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 1


def test_delete_oldest_count(tmp_path, monkeypatch):
    db, src, thumb = _setup(tmp_path, monkeypatch)
    _add_patient(db, src, "P1", "1.2.a", days_ago=300)
    _add_patient(db, src, "P2", "1.2.b", days_ago=200)
    _add_patient(db, src, "P3", "1.2.c", days_ago=10)
    mgr = lscm.LocalStorageCleanupManager()
    assert mgr.count_patients_to_delete("delete_oldest_count", 2) == 2
    res = mgr.cleanup_patients_folder_filtered("delete_oldest_count", 2)
    assert res.success and res.folders_touched == 2
    with sqlite3.connect(db) as c:
        remaining = [r[0] for r in c.execute("SELECT patient_id FROM patients").fetchall()]
    assert remaining == ["P3"]  # only the newest survives


def test_undatable_patient_is_kept_by_date_strategies(tmp_path, monkeypatch):
    db, src, thumb = _setup(tmp_path, monkeypatch)
    # No study_date and no download timestamp -> undatable -> must be KEPT (never
    # delete data whose age is unknown).
    _add_patient(db, src, "UNKNOWN", "1.2.unk", days_ago=None)
    mgr = lscm.LocalStorageCleanupManager()
    assert mgr.count_patients_to_delete("older_than_days", 1) == 0
    res = mgr.cleanup_patients_folder_filtered("older_than_days", 1)
    assert res.folders_touched == 0
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 1


def test_no_match_returns_clean_result(tmp_path, monkeypatch):
    db, src, thumb = _setup(tmp_path, monkeypatch)
    _add_patient(db, src, "NEW", "1.2.new", days_ago=1)
    mgr = lscm.LocalStorageCleanupManager()
    res = mgr.cleanup_patients_folder_filtered("older_than_days", 90)
    assert res.success and res.folders_touched == 0 and res.db_rows_affected == 0


def test_clear_all_patients_db_is_committed(tmp_path, monkeypatch):
    """Bug C: _cleanup_patients_db must commit or the pooled connection rolls the
    DELETE back. The temp ctx here does NOT auto-commit, so a missing commit would
    leave the rows behind."""
    db, src, thumb = _setup(tmp_path, monkeypatch)
    _add_patient(db, src, "A", "1.2.a", days_ago=5)
    _add_patient(db, src, "B", "1.2.b", days_ago=5)
    mgr = lscm.LocalStorageCleanupManager()
    rows = mgr._cleanup_patients_db()
    assert rows > 0
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM download_progress").fetchone()[0] == 0
