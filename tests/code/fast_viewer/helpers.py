"""
Shared helper functions for the fast_viewer test suite.

Import from test files using:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from helpers import build_fake_metadata, _make_dicom_slice, _insert_fake_series

These are pure Python utilities — no pytest fixtures.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

try:
    import numpy as np
except ModuleNotFoundError:
    np = None

try:
    import pydicom
    import pydicom.uid
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
except ModuleNotFoundError:
    pydicom = None
    Dataset = object
    FileDataset = object
    ExplicitVRLittleEndian = "1.2.840.10008.1.2.1"

    def generate_uid() -> str:
        return f"2.25.{uuid.uuid4().int}"

# ─── ensure project root on path ─────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ─── synthetic DICOM factory ─────────────────────────────────────────────────

def _make_dicom_slice(
    index: int,
    rows: int = 64,
    cols: int = 64,
    pixel_value_base: int = 1000,
    modality: str = "CT",
    series_uid: Optional[str] = None,
    study_uid: Optional[str] = None,
    window_width: float = 400.0,
    window_center: float = 40.0,
    z_pos: float = 0.0,
) -> Dataset:
    """Build a minimal valid in-memory DICOM Dataset for one slice."""
    if np is None or pydicom is None:
        pytest.skip("numpy and pydicom are required to synthesize DICOM pixel data")

    series_uid = series_uid or generate_uid()
    study_uid = study_uid or generate_uid()

    ds = FileDataset(None, {}, preamble=b"\x00" * 128)
    ds.file_meta = Dataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"  # CT
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    # Patient
    ds.PatientName = "Test^Patient"
    ds.PatientID = "PAT001"
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "M"

    # Study
    ds.StudyInstanceUID = study_uid
    ds.StudyDate = "20260408"
    ds.StudyTime = "120000"
    ds.AccessionNumber = "ACC001"
    ds.InstitutionName = "Test Hospital"

    # Series
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = 1
    ds.Modality = modality
    ds.SeriesDescription = "Test Series"

    # Image geometry
    ds.SOPInstanceUID = generate_uid()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.InstanceNumber = index + 1
    ds.ImagePositionPatient = [0.0, 0.0, float(z_pos + index * 3.0)]
    ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    ds.PixelSpacing = [0.9765625, 0.9765625]
    ds.SliceThickness = 3.0
    ds.SpacingBetweenSlices = 3.0
    ds.Rows = rows
    ds.Columns = cols
    ds.PixelRepresentation = 0
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.RescaleSlope = 1.0
    ds.RescaleIntercept = -1024.0
    ds.WindowWidth = window_width
    ds.WindowCenter = window_center

    # Pixel data: gradient ramp so each slice is unique
    pixel_array = np.full((rows, cols), pixel_value_base + index * 10, dtype=np.uint16)
    pixel_array[rows // 4 : rows * 3 // 4, cols // 4 : cols * 3 // 4] = pixel_value_base + index * 20
    ds.PixelData = pixel_array.tobytes()
    ds.is_implicit_VR = False
    ds.is_little_endian = True
    return ds


# ─── fake metadata dict ───────────────────────────────────────────────────────

def build_fake_metadata(
    n: int = 10,
    rows: int = 64,
    cols: int = 64,
    series_number: str = "1",
    series_path: Optional[str] = None,
) -> Dict:
    """Return a metadata dict matching the structure expected by the fast viewer."""
    instances = []
    for i in range(n):
        instances.append({
            "file_path": f"/fake/study/series_{series_number}/Instance_{i+1:04d}.dcm",
            "instance_number": i + 1,
            "image_position_patient": [0.0, 0.0, float(i * 3.0)],
            "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            "pixel_spacing": [0.9765625, 0.9765625],
            "slice_thickness": 3.0,
            "spacing_between_slices": 3.0,
            "rows": rows,
            "columns": cols,
            "window_width": 400.0,
            "window_center": 40.0,
            "rescale_slope": 1.0,
            "rescale_intercept": -1024.0,
        })
    return {
        "patient": {
            "patient_name": "Test^Patient",
            "patient_id": "PAT001",
            "patient_age": "46Y",
            "patient_sex": "M",
            "patient_pk": 1,
        },
        "study": {
            "study_date": "20260408",
            "institution_name": "Test Hospital",
            "study_pk": 10,
        },
        "series": {
            "series_number": series_number,
            "series_description": "Test Series",
            "modality": "CT",
            "image_count": n,
            "series_path": series_path or f"/fake/study/series_{series_number}",
        },
        "instances": instances,
    }


# ─── in-memory SQLite schema helpers ─────────────────────────────────────────

def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the AIPacs DB schema in an existing connection."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT,
            patient_name TEXT,
            patient_birth_date TEXT,
            patient_sex TEXT
        );
        CREATE TABLE IF NOT EXISTS studies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_fk INTEGER REFERENCES patients(id),
            study_uid TEXT,
            study_date TEXT,
            accession_number TEXT,
            institution_name TEXT
        );
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_fk INTEGER REFERENCES studies(id),
            series_number TEXT,
            series_uid TEXT,
            modality TEXT,
            series_description TEXT,
            image_count INTEGER DEFAULT 0,
            series_path TEXT
        );
        CREATE TABLE IF NOT EXISTS instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_fk INTEGER REFERENCES series(id),
            group_id INTEGER DEFAULT 0,
            instance_number INTEGER,
            file_path TEXT,
            rows INTEGER,
            columns INTEGER,
            window_width REAL,
            window_center REAL,
            slice_thickness REAL,
            spacing_between_slices REAL,
            rescale_slope REAL DEFAULT 1.0,
            rescale_intercept REAL DEFAULT 0.0,
            image_position_patient TEXT,
            image_orientation_patient TEXT,
            pixel_spacing TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_studies_patient_fk ON studies(patient_fk);
        CREATE INDEX IF NOT EXISTS idx_series_study_fk   ON series(study_fk);
        CREATE INDEX IF NOT EXISTS idx_instances_series_fk ON instances(series_fk);
        CREATE INDEX IF NOT EXISTS idx_instances_series_group ON instances(series_fk, group_id);
    """)
    conn.commit()


def _insert_fake_series(conn: sqlite3.Connection, n_slices: int = 10) -> Tuple[int, int, int]:
    """Insert one patient/study/series/instances. Returns (patient_pk, study_pk, series_pk)."""
    cur = conn.execute(
        "INSERT INTO patients (patient_id, patient_name) VALUES (?,?)",
        ("PAT001", "Test^Patient"),
    )
    patient_pk = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO studies (patient_fk, study_uid, study_date) VALUES (?,?,?)",
        (patient_pk, generate_uid(), "20260408"),
    )
    study_pk = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO series (study_fk, series_number, modality, image_count, series_path) VALUES (?,?,?,?,?)",
        (study_pk, "1", "CT", n_slices, "/fake/study/series_1"),
    )
    series_pk = cur.lastrowid
    for i in range(n_slices):
        conn.execute(
            """INSERT INTO instances
               (series_fk, group_id, instance_number, file_path, rows, columns,
                window_width, window_center, slice_thickness, spacing_between_slices,
                rescale_slope, rescale_intercept,
                image_position_patient, image_orientation_patient, pixel_spacing)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                series_pk, 0, i + 1,
                f"/fake/study/series_1/Instance_{i+1:04d}.dcm",
                64, 64,
                400.0, 40.0, 3.0, 3.0,
                1.0, -1024.0,
                f"[0.0, 0.0, {float(i * 3.0)}]",
                "[1.0, 0.0, 0.0, 0.0, 1.0, 0.0]",
                "[0.9765625, 0.9765625]",
            ),
        )
    conn.commit()
    return patient_pk, study_pk, series_pk
