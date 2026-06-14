"""Storage cleanup consistency: validator, repair, in-memory cache invalidation,
and partial-failure warnings (2026-06-14).

Guards the real user-visible bug class: DICOM files cleared but the DB still
"knows" the study (stale green/downloaded badge), thumbnails left dangling, and
in-memory thumbnail bytes surviving a disk clear. Uses an isolated temp sqlite DB
+ temp SOURCE_PATH/THUMBNAIL_PATH (never touches the live dicom.db).
"""
from __future__ import annotations

import contextlib
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from modules.storage import local_storage_cleanup_manager as lscm


@contextlib.contextmanager
def _temp_db_ctx(db_path):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _setup(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE studies (study_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                              study_uid TEXT, patient_fk INTEGER, number_of_series INTEGER);
        CREATE TABLE series  (series_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                              study_fk INTEGER, thumbnail_path TEXT, main_thumbnail INTEGER);
        CREATE TABLE instances (instance_pk INTEGER PRIMARY KEY AUTOINCREMENT, series_fk INTEGER);
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
    return db, src, thumb


def test_validator_detects_db_study_missing_files_and_repair_removes_it(tmp_path, monkeypatch):
    db, src, thumb = _setup(tmp_path, monkeypatch)
    missing_thumb = str(thumb / "missing.png")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO studies(study_uid, number_of_series) VALUES('1.2.3.gone', 2)")
        c.execute("INSERT INTO series(study_fk, thumbnail_path, main_thumbnail) VALUES(1, ?, 1)", (missing_thumb,))
        c.execute("INSERT INTO instances(series_fk) VALUES(1)")

    mgr = lscm.LocalStorageCleanupManager()
    rep = mgr.validate_storage_consistency()
    # DB knows a study whose files are gone -> would still show green/downloaded
    assert "1.2.3.gone" in rep["db_studies_missing_files"]
    assert missing_thumb in rep["thumbnails_missing_source"]

    summary = mgr.repair_storage_consistency(rep)
    assert summary["removed_db_studies"] >= 1
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM studies WHERE study_uid='1.2.3.gone'").fetchone()[0] == 0
        # series + instances of the gone study are removed too (explicit, cascade-agnostic)
        assert c.execute("SELECT COUNT(*) FROM series WHERE study_fk=1").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM instances WHERE series_fk=1").fetchone()[0] == 0

    # Re-validate: clean now
    rep2 = mgr.validate_storage_consistency()
    assert rep2["counts"]["db_studies_missing_files"] == 0


def test_validator_detects_orphan_disk_study(tmp_path, monkeypatch):
    db, src, thumb = _setup(tmp_path, monkeypatch)
    (src / "1.2.3.orphan").mkdir()
    (src / "1.2.3.orphan" / "a.dcm").write_bytes(b"x")
    mgr = lscm.LocalStorageCleanupManager()
    rep = mgr.validate_storage_consistency()
    assert "1.2.3.orphan" in rep["orphan_disk_studies"]
    # Conservative repair must NOT delete orphan disk studies (could be a fresh import)
    summary = mgr.repair_storage_consistency(rep)
    assert (src / "1.2.3.orphan" / "a.dcm").exists()
    assert summary["removed_db_studies"] == 0


def test_present_study_not_flagged(tmp_path, monkeypatch):
    db, src, thumb = _setup(tmp_path, monkeypatch)
    (src / "1.2.3.present").mkdir()
    (src / "1.2.3.present" / "a.dcm").write_bytes(b"x")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO studies(study_uid, number_of_series) VALUES('1.2.3.present', 1)")
    mgr = lscm.LocalStorageCleanupManager()
    rep = mgr.validate_storage_consistency()
    assert "1.2.3.present" not in rep["db_studies_missing_files"]
    assert "1.2.3.present" not in rep["orphan_disk_studies"]


def test_cache_clear_clears_in_memory_thumbnail_store(tmp_path, monkeypatch):
    cleared = []
    import modules.storage.thumbnail_store as ts

    class _FakeStore:
        def clear(self):
            cleared.append(True)

    monkeypatch.setattr(ts.ThumbnailStore, "instance", staticmethod(lambda: _FakeStore()))
    db, src, thumb = _setup(tmp_path, monkeypatch)
    (thumb / "1.2.3" ).mkdir()
    (thumb / "1.2.3" / "1.png").write_bytes(b"x")

    mgr = lscm.LocalStorageCleanupManager()
    mgr.cache_paths = [thumb]  # avoid touching the real zeta cache dir
    res = mgr.cleanup_cache_folder()
    assert cleared, "cleanup_cache_folder must clear the in-memory ThumbnailStore"
    assert res.success and not res.warnings


def test_partial_failure_sets_warning_and_success_false(tmp_path, monkeypatch):
    db, src, thumb = _setup(tmp_path, monkeypatch)
    mgr = lscm.LocalStorageCleanupManager()
    mgr.cache_paths = [thumb]
    # Simulate DB cleanup failing AFTER files were deleted.
    monkeypatch.setattr(mgr, "_cleanup_cache_db", lambda: (_ for _ in ()).throw(RuntimeError("db locked")))
    res = mgr.cleanup_cache_folder()
    assert res.success is False
    assert any("db" in w.lower() for w in res.warnings), res.warnings
    assert "WARNING" in res.message
