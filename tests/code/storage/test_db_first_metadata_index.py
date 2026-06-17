"""Guards for the DB-first metadata architecture (P0 + P1, 2026-06-16).

Plan: docs/plans/performance/DB_FIRST_METADATA_ARCHITECTURE_PLAN_2026-06-16.md

P0 (write-side, safe): series.metadata_index_status / indexed_instance_count /
expected_instance_count / last_indexed_at (additive migration); the downloader
stamps them at completion (Indexed only when every local file got a DB row) and
also persists SliceThickness / SpacingBetweenSlices.

P1 (read-side, opt-in): load_single_series_by_number gains a gate —
AIPACS_VIEWER_DB_METADATA=verify builds DB + disk maps and logs a golden
geometry/order compare while DISPLAYING the disk map (observe-only); =auto trusts
the DB map only when geometry-complete, else disk; "0" (default) and "1" are
unchanged. Geometry/slice order are NEVER recomputed differently — the DB path
runs the same normalizer, and the comparator proves equality before trust.

Source-wiring tests run anywhere. Functional tests import image_io / dicom_db
(PySide6 / a temp DB) — run on Windows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _read(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")


# ── source wiring (runs anywhere; protects the build path) ───────────────────
def test_source_wiring_present():
    db = _read("database/dicom_db.py")
    assert "metadata_index_status" in db
    assert "def mark_series_indexed" in db
    assert "def get_series_metadata_index" in db
    assert "ALTER TABLE series ADD COLUMN metadata_index_status" in db

    sd = _read("modules/download_manager/download/series_downloader.py")
    assert "mark_series_indexed" in sd
    assert "'slice_thickness': slice_thickness_val" in sd
    assert "'spacing_between_slices': spacing_between_val" in sd

    io = _read("PacsClient/pacs/patient_tab/utils/image_io.py")
    assert "def _compare_geometry_signature" in io
    assert "[DB_METADATA_VERIFY]" in io
    assert "[DB_METADATA_GATE]" in io
    assert "def _dedupe_instances_by_sop" in io
    assert "[DICOM_DEDUP]" in io

    vc = _read("PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py")
    assert '"verify", "auto"' in vc  # gate widened beyond "1"


# ── geometry-signature comparator (P1 safety proof) — Windows ────────────────
def test_geometry_signature_equal_and_unequal():
    from PacsClient.pacs.patient_tab.utils.image_io import _compare_geometry_signature

    a = {"instances": [
        {"image_position_patient": [0.0, 0.0, 1.0], "image_orientation_patient": [1, 0, 0, 0, 1, 0]},
        {"image_position_patient": [0.0, 0.0, 2.0], "image_orientation_patient": [1, 0, 0, 0, 1, 0]},
    ]}
    # same geometry, IPP stored as JSON strings (storage-format robustness)
    b = {"instances": [
        {"image_position_patient": "[0.0, 0.0, 1.0]", "image_orientation_patient": "[1, 0, 0, 0, 1, 0]"},
        {"image_position_patient": "[0.0, 0.0, 2.0]", "image_orientation_patient": "[1, 0, 0, 0, 1, 0]"},
    ]}
    assert _compare_geometry_signature(a, b) is True

    # different order → different signature
    c = {"instances": list(reversed(a["instances"]))}
    assert _compare_geometry_signature(a, c) is False

    # different count → not equal
    d = {"instances": a["instances"][:1]}
    assert _compare_geometry_signature(a, d) is False


def test_dedupe_instances_by_sop():
    # The POKORA 802-vs-401 fix: duplicate-SOP files (multi-source import) collapse
    # to unique SOPs; empty-SOP rows are kept; a clean series is a no-op.
    from PacsClient.pacs.patient_tab.utils.image_io import _dedupe_instances_by_sop

    insts = [
        {"sop_uid": "A", "instance_path": "a1.dcm"},
        {"sop_uid": "B", "instance_path": "b1.dcm"},
        {"sop_uid": "A", "instance_path": "a2.dcm"},  # same SOP, 2nd filename
        {"sop_uid": "B", "instance_path": "b2.dcm"},
    ]
    out = _dedupe_instances_by_sop(insts, "3")
    assert [i["sop_uid"] for i in out] == ["A", "B"]

    # empty SOP UID → cannot prove duplicate → kept
    empties = [{"sop_uid": "", "instance_path": "x"}, {"sop_uid": "", "instance_path": "y"}]
    assert len(_dedupe_instances_by_sop(empties, "3")) == 2

    # clean series → unchanged
    clean = [{"sop_uid": "S1"}, {"sop_uid": "S2"}, {"sop_uid": "S3"}]
    assert len(_dedupe_instances_by_sop(clean, "3")) == 3


# ── mark/get round-trip (Indexed only when complete) — Windows, temp DB ──────
def test_mark_series_indexed_roundtrip(tmp_path, monkeypatch):
    import importlib
    data_paths = importlib.import_module("PacsClient.utils.data_paths")
    pool = importlib.import_module("database._pool")
    dicom_db = importlib.import_module("database.dicom_db")

    temp_db = tmp_path / "dicom_test.db"
    monkeypatch.setattr(data_paths, "DATABASE_FILE", str(temp_db), raising=False)
    with pool._pool_lock:
        pool._connection_pool.clear()
    try:
        dicom_db.init_database()
        # minimal patient/study/series so a series_pk exists
        ppk = dicom_db.insert_patient("TESTPID", "TEST^NAME")
        spk_study = dicom_db.insert_study("1.2.3.studyuid", ppk)
        series_pk = dicom_db.insert_series("1.2.3.seriesuid", spk_study, series_number="1")

        # partial index → NotIndexed
        dicom_db.mark_series_indexed(series_pk, indexed_count=3, expected_count=5)
        st = dicom_db.get_series_metadata_index(series_pk)
        assert st["status"] == "NotIndexed" and st["indexed"] == 3 and st["expected"] == 5

        # complete index → Indexed
        dicom_db.mark_series_indexed(series_pk, indexed_count=5, expected_count=5)
        st = dicom_db.get_series_metadata_index(series_pk)
        assert st["status"] == "Indexed" and st["indexed"] == 5
        assert st["last_indexed_at"]
    finally:
        with pool._pool_lock:
            pool._connection_pool.clear()


def test_migration_idempotent(tmp_path, monkeypatch):
    import importlib
    data_paths = importlib.import_module("PacsClient.utils.data_paths")
    pool = importlib.import_module("database._pool")
    dicom_db = importlib.import_module("database.dicom_db")

    temp_db = tmp_path / "dicom_test2.db"
    monkeypatch.setattr(data_paths, "DATABASE_FILE", str(temp_db), raising=False)
    with pool._pool_lock:
        pool._connection_pool.clear()
    try:
        dicom_db.init_database()
        dicom_db.init_database()  # second run must not raise (guarded ALTER)
        import sqlite3
        con = sqlite3.connect(str(temp_db))
        cols = [r[1] for r in con.execute("PRAGMA table_info(series)").fetchall()]
        con.close()
        for c in ("metadata_index_status", "indexed_instance_count",
                  "expected_instance_count", "last_indexed_at"):
            assert c in cols
    finally:
        with pool._pool_lock:
            pool._connection_pool.clear()
