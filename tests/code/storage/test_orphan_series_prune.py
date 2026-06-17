"""Guards for the orphan-series self-heal (2026-06-17).

An ORPHAN series has DB instance rows but no files on disk, AND lives in a study
that is otherwise PARTIALLY present (other series still have files) — the POKORA
562346 series-3 case (a re-split/re-download left the old series row dangling).

The dangerous false positive this MUST avoid: a whole study that was downloaded
then cache-EVICTED (every series file-less) — those rows are a legitimate
re-downloadable record and must never be pruned. The guard distinguishes them by
requiring at least one OTHER series in the study to still have files.

prune_orphan_series_for_study / find_orphan_series accept a source_root override,
so these tests need no config patching for the disk side; the DB side uses the
documented temp-DB isolation (patch DATABASE_FILE + clear the pool).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _setup(tmp_path, monkeypatch):
    data_paths = importlib.import_module("PacsClient.utils.data_paths")
    pool = importlib.import_module("database._pool")
    dicom_db = importlib.import_module("database.dicom_db")
    monkeypatch.setattr(data_paths, "DATABASE_FILE", str(tmp_path / "dicom.db"), raising=False)
    with pool._pool_lock:
        pool._connection_pool.clear()
    dicom_db.init_database()
    return dicom_db


def _series_with_rows(dicom_db, study_fk, number, uid, n, folder, with_files):
    spk = dicom_db.insert_series(uid, study_fk, series_number=str(number),
                                 series_path=str(folder))
    if with_files:
        folder.mkdir(parents=True, exist_ok=True)
    insts = [{"sop_uid": f"{uid}.{i}", "series_fk": spk,
              "instance_path": str(folder / f"Instance_{i:04d}.dcm"),
              "instance_number": i, "rows": 1, "columns": 1} for i in range(1, n + 1)]
    if with_files:
        for inst in insts:
            Path(inst["instance_path"]).write_bytes(b"x")
    dicom_db.insert_instances_batch(insts)
    return spk


def test_orphan_in_partial_study_is_pruned(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    src = tmp_path / "dicom"; src.mkdir()
    ppk = db.insert_patient("P1", "N1")
    sx = db.insert_study("STUDY.X", ppk)
    _series_with_rows(db, sx, 1, "X.1", 3, src / "STUDY.X" / "1", with_files=True)   # present
    s2 = _series_with_rows(db, sx, 2, "X.2", 4, src / "STUDY.X" / "2", with_files=False)  # orphan

    pruned = db.prune_orphan_series_for_study("STUDY.X", source_root=str(src))
    assert pruned == [("2", 4)]                       # only the file-less series
    assert db.find_series_pk("X.2") is None           # series row gone
    assert db.find_series_pk("X.1") is not None        # sibling kept


def test_evicted_whole_study_not_pruned(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    src = tmp_path / "dicom"; src.mkdir()
    ppk = db.insert_patient("P2", "N2")
    sy = db.insert_study("STUDY.Y", ppk)
    _series_with_rows(db, sy, 1, "Y.1", 5, src / "STUDY.Y" / "1", with_files=False)
    _series_with_rows(db, sy, 2, "Y.2", 6, src / "STUDY.Y" / "2", with_files=False)

    # whole study file-less => cache-evicted, NOT orphans => never pruned
    assert db.prune_orphan_series_for_study("STUDY.Y", source_root=str(src)) == []
    assert db.find_series_pk("Y.1") is not None
    assert db.find_series_pk("Y.2") is not None


def test_pending_zero_row_series_kept(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    src = tmp_path / "dicom"; src.mkdir()
    ppk = db.insert_patient("P3", "N3")
    sz = db.insert_study("STUDY.Z", ppk)
    _series_with_rows(db, sz, 1, "Z.1", 3, src / "STUDY.Z" / "1", with_files=True)
    db.insert_series("Z.2", sz, series_number="2", series_path=str(src / "STUDY.Z" / "2"))  # 0 rows = pending

    pruned = db.prune_orphan_series_for_study("STUDY.Z", source_root=str(src))
    assert pruned == []                       # pending series (no rows) untouched
    assert db.find_series_pk("Z.2") is not None


def test_offline_store_prunes_nothing(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    src = tmp_path / "dicom"; src.mkdir()
    ppk = db.insert_patient("P4", "N4")
    sx = db.insert_study("STUDY.W", ppk)
    _series_with_rows(db, sx, 1, "W.1", 3, src / "STUDY.W" / "1", with_files=True)
    _series_with_rows(db, sx, 2, "W.2", 4, src / "STUDY.W" / "2", with_files=False)
    # unreachable store root => never prune (transient offline drive safety)
    assert db.prune_orphan_series_for_study("STUDY.W", source_root=str(tmp_path / "nope")) == []
    assert db.find_series_pk("W.2") is not None


def test_flag_off_is_noop(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    src = tmp_path / "dicom"; src.mkdir()
    ppk = db.insert_patient("P5", "N5")
    sx = db.insert_study("STUDY.V", ppk)
    _series_with_rows(db, sx, 1, "V.1", 3, src / "STUDY.V" / "1", with_files=True)
    _series_with_rows(db, sx, 2, "V.2", 4, src / "STUDY.V" / "2", with_files=False)
    monkeypatch.setenv("AIPACS_PRUNE_ORPHAN_SERIES", "0")
    assert db.prune_orphan_series_for_study("STUDY.V", source_root=str(src)) == []
    assert db.find_series_pk("V.2") is not None


def test_find_orphan_series_partial_only(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    src = tmp_path / "dicom"; src.mkdir()
    p = db.insert_patient("P6", "N6")
    # partial study (one orphan) + evicted study (no orphans reported)
    sp = db.insert_study("STUDY.P", p)
    _series_with_rows(db, sp, 1, "P.1", 3, src / "STUDY.P" / "1", with_files=True)
    _series_with_rows(db, sp, 2, "P.2", 4, src / "STUDY.P" / "2", with_files=False)
    se = db.insert_study("STUDY.E", p)
    _series_with_rows(db, se, 1, "E.1", 3, src / "STUDY.E" / "1", with_files=False)

    found = db.find_orphan_series(source_root=str(src))
    keys = {(o["study_uid"], str(o["series_number"])) for o in found}
    assert ("STUDY.P", "2") in keys           # partial-study orphan reported
    assert all(o["study_uid"] != "STUDY.E" for o in found)   # evicted study excluded


def test_source_wiring_present():
    db = (_REPO_ROOT / "database" / "dicom_db.py").read_text(encoding="utf-8", errors="ignore")
    assert "def prune_orphan_series_for_study" in db
    assert "def find_orphan_series" in db
    assert "AIPACS_PRUNE_ORPHAN_SERIES" in db
    assert "ORPHAN_SERIES_PRUNED" in db
    assert "study_has_files" in db            # the cache-evicted guard
    open_src = (_REPO_ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py").read_text(encoding="utf-8", errors="ignore")
    assert "prune_orphan_series_for_study" in open_src   # hooked at study open
