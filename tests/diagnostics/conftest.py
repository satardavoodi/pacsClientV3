"""
tests/diagnostics/conftest.py
==============================
Shared pytest fixtures for the FAST viewer diagnostic test suite.

Provides:
  - qt_app          : headless QApplication singleton (session scope)
  - diag_run_dir    : tmp_path-based directory for one diagnostic run's artifacts
  - event_log       : an EventLog scoped to one test
  - report_writer   : a ReportWriter scoped to one test
  - fake_metadata_ct: pre-built large-CT metadata dict (400 slices)
  - fake_metadata_mr: pre-built small-MR metadata dict (25 slices)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict

import pytest

# ─── add project root to sys.path ────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ─── headless Qt ─────────────────────────────────────────────────────────────
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app():
    """Return a headless QApplication (created once per session)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(["pytest-diag", "-platform", "offscreen"])
    return app


# ─── per-test artifact directory ─────────────────────────────────────────────

@pytest.fixture()
def diag_run_dir(tmp_path) -> Path:
    """Return a fresh per-test directory for diagnostic artifact output."""
    run_dir = tmp_path / "diag_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


# ─── EventLog fixture ─────────────────────────────────────────────────────────

@pytest.fixture()
def event_log(diag_run_dir):
    """Return an EventLog writing to diag_run_dir."""
    from tests.diagnostics.event_log import EventLog
    log = EventLog(output_dir=diag_run_dir)
    yield log
    log.close()


# ─── ReportWriter fixture ────────────────────────────────────────────────────

@pytest.fixture()
def report_writer(diag_run_dir):
    """Return a ReportWriter writing to diag_run_dir."""
    from tests.diagnostics.report_writer import ReportWriter
    writer = ReportWriter(output_dir=diag_run_dir)
    yield writer
    writer.close()


# ─── KpiCollector fixture ────────────────────────────────────────────────────

@pytest.fixture()
def kpi_collector():
    """Return a fresh KpiCollector for one test."""
    from tests.diagnostics.kpi_collector import KpiCollector
    return KpiCollector()


# ─── Synthetic metadata factories ────────────────────────────────────────────

def _build_fake_metadata(
    n: int,
    modality: str,
    series_number: str = "1",
    rows: int = 64,
    cols: int = 64,
    series_path: str | None = None,
) -> Dict:
    """Return a minimal metadata dict with *n* synthetic instance entries."""
    instances = []
    for i in range(n):
        instances.append({
            "file_path": f"/fake/series_{series_number}/Instance_{i+1:04d}.dcm",
            "instance_number": i + 1,
            "image_position_patient": [0.0, 0.0, float(i * 3.0)],
            "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            "pixel_spacing": [0.9765625, 0.9765625],
            "slice_thickness": 3.0,
            "spacing_between_slices": 3.0,
            "rows": rows,
            "columns": cols,
            "window_width": 400.0 if modality == "CT" else 300.0,
            "window_center": 40.0 if modality == "CT" else 200.0,
            "rescale_slope": 1.0,
            "rescale_intercept": -1024.0 if modality == "CT" else 0.0,
        })
    return {
        "patient": {
            "patient_name": f"Test^{modality}",
            "patient_id": "PAT001",
            "patient_age": "50Y",
            "patient_sex": "M",
            "patient_pk": 1,
        },
        "study": {
            "study_date": "20260410",
            "institution_name": "Test Hospital",
            "study_pk": 10,
            "study_uid": "1.2.3.4.5",
        },
        "series": {
            "series_number": series_number,
            "series_description": f"{modality} Series {series_number}",
            "modality": modality,
            "image_count": n,
            "series_path": series_path or f"/fake/series_{series_number}",
            "viewer_backend": "pydicom_qt",
            "thumbnail_path": "",
        },
        "instances": instances,
    }


@pytest.fixture()
def fake_metadata_ct() -> Dict:
    """Large CT — 400 slices (primary crash scenario)."""
    return _build_fake_metadata(400, "CT", series_number="1")


@pytest.fixture()
def fake_metadata_mr() -> Dict:
    """Small MRI — 25 slices (baseline)."""
    return _build_fake_metadata(25, "MR", series_number="2")


@pytest.fixture()
def fake_metadata_ct_medium() -> Dict:
    """Medium CT — 120 slices."""
    return _build_fake_metadata(120, "CT", series_number="3")


# ─── DICOM file factory ──────────────────────────────────────────────────────

@pytest.fixture()
def make_dicom_series(tmp_path):
    """Factory: write N synthetic DICOM files and return (dir, metadata)."""
    import struct
    import numpy as np
    try:
        import pydicom
        from pydicom.dataset import Dataset, FileDataset
        from pydicom.uid import ExplicitVRLittleEndian, generate_uid
        _pydicom_ok = True
    except ImportError:
        _pydicom_ok = False

    def _factory(
        n: int = 10,
        modality: str = "CT",
        rows: int = 64,
        cols: int = 64,
        series_number: str = "1",
    ):
        if not _pydicom_ok:
            pytest.skip("pydicom not available")
        series_uid = generate_uid()
        study_uid = generate_uid()
        series_dir = tmp_path / "study" / series_number
        series_dir.mkdir(parents=True, exist_ok=True)

        for i in range(n):
            ds = FileDataset(None, {}, preamble=b"\x00" * 128)
            ds.file_meta = Dataset()
            ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
            ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds.PatientName = f"Test^{modality}"
            ds.PatientID = "PAT001"
            ds.StudyInstanceUID = study_uid
            ds.StudyDate = "20260410"
            ds.SeriesInstanceUID = series_uid
            ds.SeriesNumber = int(series_number)
            ds.Modality = modality
            ds.SOPInstanceUID = generate_uid()
            ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
            ds.InstanceNumber = i + 1
            ds.ImagePositionPatient = [0.0, 0.0, float(i * 3.0)]
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
            ds.WindowWidth = 400.0
            ds.WindowCenter = 40.0
            pixel_array = np.full((rows, cols), 1000 + i * 10, dtype=np.uint16)
            ds.PixelData = pixel_array.tobytes()
            ds.is_implicit_VR = False
            ds.is_little_endian = True
            out_path = series_dir / f"Instance_{i+1:04d}.dcm"
            pydicom.dcmwrite(str(out_path), ds)

        metadata = _build_fake_metadata(n, modality, series_number, rows, cols, str(series_dir))
        # Update file paths to real paths
        for idx, inst in enumerate(metadata["instances"]):
            inst["file_path"] = str(series_dir / f"Instance_{idx+1:04d}.dcm")

        return series_dir, metadata

    return _factory
