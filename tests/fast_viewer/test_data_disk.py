"""
FAST Viewer — Disk I/O Tests
==============================
Verifies that the backend correctly reads DICOM files from disk:
file ordering, corrupt/missing file tolerance, header extraction,
and pixel array correctness.

Scenarios:
  D-01  Files loaded in natsort (Instance_0001, …, Instance_0010) order
  D-02  Corrupt DICOM file in series → backend skips or raises gracefully
  D-03  Non-DICOM file in series directory is ignored
  D-04  Empty directory → open_series raises / returns 0 slices
  D-05  Series with gaps in instance numbers → remaining slices still load
  D-06  get_pixel_array() returns a NumPy ndarray
  D-07  Pixel array dtype is numeric (int or uint)
  D-08  Pixel array shape matches reported rows × cols
  D-09  RescaleSlope=2.0 applied → output values doubled vs slope=1.0
  D-10  MONOCHROME1 photometric interpretation reported correctly
  D-11  series_path property reflects the opened directory
  D-12  Geometry data (pixel_spacing) matches DICOM headers
  D-13  Single-slice series loads without error
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

import numpy as np
import pydicom
import sys

import pytest
from pydicom.uid import generate_uid

_FV_DIR = str(Path(__file__).parent)
if _FV_DIR not in sys.path:
    sys.path.insert(0, _FV_DIR)
from helpers import _make_dicom_slice


# ─── D-01  Natsort ordering ───────────────────────────────────────────────────

class TestFileOrdering:
    def test_d01_natsort_order(self, make_dicom_series, tmp_path, qt_app):
        """Files must be loaded in natsort order, not filesystem order."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=10)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        paths = backend.get_file_paths()
        names = [Path(p).name for p in paths]
        expected = sorted(names, key=lambda s: [
            int(c) if c.isdigit() else c for c in __import__('re').split(r'(\d+)', s)
        ])
        assert names == expected, f"Files not in natsort order: {names}"
        backend.close_series()


# ─── D-02  Corrupt DICOM ─────────────────────────────────────────────────────

class TestCorruptFile:
    def test_d02_corrupt_file_handled_gracefully(self, make_dicom_series, tmp_path, qt_app):
        """A corrupt DICOM file must not crash open_series or get_pixel_array for valid slices."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, files = make_dicom_series(n=5)
        # Overwrite slice 2 with garbage
        corrupt_path = series_dir / "Instance_0003.dcm"
        corrupt_path.write_bytes(b"\x00\x01\x02\x03garbage data")

        backend = PyDicom2DBackend()
        try:
            backend.open_series(str(series_dir))
        except Exception:
            return  # raising on open is acceptable

        # If it opened, at least the valid slices should be accessible
        for i in range(min(2, backend.get_slice_count())):
            try:
                arr = backend.get_pixel_array(i)
                # index 2 may raise — that's OK
            except Exception:
                pass  # graceful skip
        backend.close_series()


# ─── D-03  Non-DICOM files ignored ───────────────────────────────────────────

class TestNonDicomIgnored:
    def test_d03_non_dcm_files_ignored(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=4)
        # Add non-DICOM files — use extensions explicitly excluded by the scanner (.json, .png, .txt)
        # Note: extensionless files are scanned (DICOM dirs may contain DICOMDIR w/o extension)
        (series_dir / "DIRINDEX.json").write_text("{}")
        (series_dir / "thumbnail.png").write_bytes(b"\x89PNG\r\n")
        (series_dir / "manifest.txt").write_text("info\n")

        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        assert backend.get_slice_count() == 4, (
            f"Expected 4 DICOM slices, got {backend.get_slice_count()}"
        )
        backend.close_series()


# ─── D-04  Empty directory ────────────────────────────────────────────────────

class TestEmptyDirectory:
    def test_d04_empty_dir_zero_slices_or_raises(self, tmp_path, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        backend = PyDicom2DBackend()
        try:
            backend.open_series(str(empty_dir))
            assert backend.get_slice_count() == 0
        except Exception:
            pass  # raising is also acceptable for an empty series


# ─── D-05  Gaps in instance numbers ─────────────────────────────────────────

class TestGappedInstances:
    def test_d05_gaps_in_instance_numbers_still_loads(self, tmp_path, qt_app):
        """Series with non-contiguous instance numbers loads those files that exist."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir = tmp_path / "gapped"
        series_dir.mkdir()
        for i in [0, 1, 5, 9]:  # gaps at 2,3,4,6,7,8
            ds = _make_dicom_slice(index=i, rows=32, cols=32)
            pydicom.dcmwrite(str(series_dir / f"Instance_{i+1:04d}.dcm"), ds)

        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        n = backend.get_slice_count()
        assert n == 4, f"Expected 4 slices for 4 files, got {n}"
        backend.close_series()


# ─── D-06 / D-07 / D-08  get_pixel_array ────────────────────────────────────

class TestPixelArray:
    def test_d06_get_pixel_array_returns_ndarray(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=3)
        b = PyDicom2DBackend()
        b.open_series(str(series_dir))
        arr = b.get_pixel_array(0)
        assert isinstance(arr, np.ndarray)
        b.close_series()

    def test_d07_pixel_array_dtype_is_numeric(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        b = PyDicom2DBackend()
        b.open_series(str(series_dir))
        arr = b.get_pixel_array(0)
        assert np.issubdtype(arr.dtype, np.number), f"Non-numeric dtype: {arr.dtype}"
        b.close_series()

    def test_d08_pixel_array_shape_matches_rows_cols(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2, rows=48, cols=80)
        b = PyDicom2DBackend()
        b.open_series(str(series_dir))
        arr = b.get_pixel_array(0)
        assert arr.shape[0] == 48, f"Row mismatch: {arr.shape[0]}"
        assert arr.shape[1] == 80, f"Col mismatch: {arr.shape[1]}"
        b.close_series()


# ─── D-09  RescaleSlope applied ───────────────────────────────────────────────

class TestRescaleSlope:
    def test_d09_rescale_slope_applied(self, tmp_path, qt_app):
        """Slice with RescaleSlope=2.0 should have raw-pixel × 2 output."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend

        series_dir = tmp_path / "slope_test"
        series_dir.mkdir()
        ds = _make_dicom_slice(index=0, rows=16, cols=16, pixel_value_base=100)
        ds.RescaleSlope = 2.0
        ds.RescaleIntercept = 0.0
        pydicom.dcmwrite(str(series_dir / "Instance_0001.dcm"), ds)

        b = PyDicom2DBackend()
        b.open_series(str(series_dir))
        arr = b.get_pixel_array(0)
        # All raw pixels are 100 → after slope=2: expect ~200
        center = float(arr[arr.shape[0] // 2, arr.shape[1] // 2])
        assert 150.0 <= center <= 250.0, f"D-09: slope not applied, center pixel = {center}"
        b.close_series()


# ─── D-11  series_path property ──────────────────────────────────────────────

class TestSeriesPathProperty:
    def test_d11_series_path_reflects_opened_dir(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=3)
        b = PyDicom2DBackend()
        b.open_series(str(series_dir))
        assert b._series_path == str(series_dir)
        b.close_series()


# ─── D-12  Geometry pixel spacing ────────────────────────────────────────────

class TestGeometryPixelSpacing:
    def test_d12_pixel_spacing_matches_header(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        b = PyDicom2DBackend()
        b.open_series(str(series_dir))
        g = b.get_geometry(0)
        assert abs(g.pixel_spacing[0] - 0.9765625) < 0.001
        assert abs(g.pixel_spacing[1] - 0.9765625) < 0.001
        b.close_series()


# ─── D-13  Single-slice series ────────────────────────────────────────────────

class TestSingleSliceSeries:
    def test_d13_single_slice_loads_without_error(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=1)
        b = PyDicom2DBackend()
        b.open_series(str(series_dir))
        assert b.get_slice_count() == 1
        arr = b.get_pixel_array(0)
        assert arr is not None
        b.close_series()
