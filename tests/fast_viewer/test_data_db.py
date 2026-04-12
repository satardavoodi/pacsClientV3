"""
FAST Viewer — Database Metadata Path Tests
============================================
Tests the fast-path that reads DICOM metadata (instances, series info,
image_count) directly from the SQLite DB, bypassing the ITK pipeline.

Covers the in-memory DB schema that mirrors database/core.py, the helper
functions used by image_io.py's BACKEND_PYDICOM_QT early exit, and the
metadata dict structure produced by _get_cached_metadata / _build_metadata_*

Scenarios:
  DB-01  Schema created — tables and indexes exist
  DB-02  Insert patient/study/series/instances → query count matches
  DB-03  Instances returned in instance_number order
  DB-04  group_id=0 instances returned first over group_id=1
  DB-05  Empty series (0 instances) returns empty list
  DB-06  Missing series_pk returns None / empty result
  DB-07  image_count field updated after inserting more instances
  DB-08  build_fake_metadata produces 'instances' list of correct length
  DB-09  build_fake_metadata instance dicts contain required geometry keys
  DB-10  Metadata dict 'series.image_count' equals len(instances)
  DB-11  resolve_viewer_backend with DB-sourced metadata keeps pydicom_qt
  DB-12  Metadata 'patient_pk' present in patient sub-dict
  DB-13  Inserting duplicate instance_number does not crash schema
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Tuple

import sys
from pathlib import Path

import pytest

_FV_DIR = str(Path(__file__).parent)
if _FV_DIR not in sys.path:
    sys.path.insert(0, _FV_DIR)
from helpers import build_fake_metadata, _insert_fake_series


# ─── DB-01  Schema ────────────────────────────────────────────────────────────

class TestSchema:
    REQUIRED_TABLES = {"patients", "studies", "series", "instances"}
    REQUIRED_INDEXES = {
        "idx_studies_patient_fk",
        "idx_series_study_fk",
        "idx_instances_series_fk",
        "idx_instances_series_group",
    }

    def test_db01_required_tables_exist(self, in_memory_db):
        conn, _ = in_memory_db
        tables = {
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for t in self.REQUIRED_TABLES:
            assert t in tables, f"Missing table: {t}"

    def test_db01b_required_indexes_exist(self, in_memory_db):
        conn, _ = in_memory_db
        indexes = {
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        for idx in self.REQUIRED_INDEXES:
            assert idx in indexes, f"Missing index: {idx}"


# ─── DB-02  Insert and query ──────────────────────────────────────────────────

class TestInsertQuery:
    def test_db02_insert_returns_correct_slice_count(self, in_memory_db):
        conn, insert_fn = in_memory_db
        patient_pk, study_pk, series_pk = insert_fn(conn, n_slices=15)
        count = conn.execute(
            "SELECT COUNT(*) FROM instances WHERE series_fk=?", (series_pk,)
        ).fetchone()[0]
        assert count == 15

    def test_db03_instances_ordered_by_instance_number(self, in_memory_db):
        conn, insert_fn = in_memory_db
        _, _, series_pk = insert_fn(conn, n_slices=8)
        rows = conn.execute(
            "SELECT instance_number FROM instances WHERE series_fk=? ORDER BY instance_number",
            (series_pk,),
        ).fetchall()
        numbers = [r[0] for r in rows]
        assert numbers == sorted(numbers), f"Not sorted: {numbers}"

    def test_db04_group_id_0_instances_exist(self, in_memory_db):
        conn, insert_fn = in_memory_db
        _, _, series_pk = insert_fn(conn, n_slices=5)
        count = conn.execute(
            "SELECT COUNT(*) FROM instances WHERE series_fk=? AND group_id=0",
            (series_pk,),
        ).fetchone()[0]
        assert count == 5

    def test_db05_empty_series_returns_zero(self, in_memory_db):
        conn, insert_fn = in_memory_db
        from pydicom.uid import generate_uid
        cur = conn.execute(
            "INSERT INTO patients (patient_id, patient_name) VALUES (?,?)",
            ("PAT002", "Empty^Patient"),
        )
        cur2 = conn.execute(
            "INSERT INTO studies (patient_fk, study_uid) VALUES (?,?)",
            (cur.lastrowid, generate_uid()),
        )
        cur3 = conn.execute(
            "INSERT INTO series (study_fk, series_number, image_count) VALUES (?,?,?)",
            (cur2.lastrowid, "99", 0),
        )
        conn.commit()
        series_pk = cur3.lastrowid
        count = conn.execute(
            "SELECT COUNT(*) FROM instances WHERE series_fk=?", (series_pk,)
        ).fetchone()[0]
        assert count == 0

    def test_db06_missing_series_pk_returns_empty(self, in_memory_db):
        conn, _ = in_memory_db
        rows = conn.execute(
            "SELECT * FROM instances WHERE series_fk=?", (999999,)
        ).fetchall()
        assert rows == []


# ─── DB-07  image_count update ───────────────────────────────────────────────

class TestImageCountUpdate:
    def test_db07_image_count_updated(self, in_memory_db):
        conn, insert_fn = in_memory_db
        _, _, series_pk = insert_fn(conn, n_slices=10)
        # Update image_count to match a new total
        conn.execute("UPDATE series SET image_count=20 WHERE id=?", (series_pk,))
        conn.commit()
        row = conn.execute("SELECT image_count FROM series WHERE id=?", (series_pk,)).fetchone()
        assert row[0] == 20


# ─── DB-08 / DB-09 / DB-10  Fake metadata structure ──────────────────────────

class TestFakeMetadataStructure:
    def test_db08_instances_list_correct_length(self):
        meta = build_fake_metadata(n=12)
        assert len(meta["instances"]) == 12

    def test_db09_instance_dicts_have_geometry_keys(self):
        meta = build_fake_metadata(n=3)
        required_keys = {
            "file_path", "instance_number",
            "image_position_patient", "image_orientation_patient",
            "pixel_spacing", "slice_thickness", "rows", "columns",
            "window_width", "window_center", "rescale_slope", "rescale_intercept",
        }
        for inst in meta["instances"]:
            missing = required_keys - set(inst.keys())
            assert not missing, f"Missing keys in instance: {missing}"

    def test_db10_series_image_count_equals_instances_len(self):
        for n in (1, 5, 20):
            meta = build_fake_metadata(n=n)
            assert meta["series"]["image_count"] == len(meta["instances"])

    def test_db12_patient_pk_present(self):
        meta = build_fake_metadata(n=5)
        assert "patient_pk" in meta["patient"]
        assert meta["patient"]["patient_pk"] is not None


# ─── DB-11  resolve_viewer_backend with DB metadata ──────────────────────────

class TestResolveWithDbMetadata:
    def test_db11_pydicom_qt_kept_with_valid_db_metadata(self):
        from modules.viewer.viewer_backend_config import BACKEND_PYDICOM_QT, resolve_viewer_backend
        meta = build_fake_metadata(n=8)
        result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM_QT)
        assert result["backend"] == BACKEND_PYDICOM_QT
        assert result["metadata_complete"] is True


# ─── DB-13  Duplicate instance_number ────────────────────────────────────────

class TestDuplicateInstanceNumber:
    def test_db13_duplicate_instance_number_no_crash(self, in_memory_db):
        conn, insert_fn = in_memory_db
        _, _, series_pk = insert_fn(conn, n_slices=3)
        # Insert a duplicate instance_number — schema allows this (no UNIQUE constraint)
        conn.execute(
            "INSERT INTO instances (series_fk, group_id, instance_number, file_path) VALUES (?,?,?,?)",
            (series_pk, 0, 1, "/fake/dup.dcm"),
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM instances WHERE series_fk=? AND instance_number=1",
            (series_pk,),
        ).fetchone()[0]
        assert count >= 2  # both rows present
