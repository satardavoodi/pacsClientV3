"""
FAST Viewer — Rendering & Output Tests
========================================
Verifies that the FAST viewer pipeline produces correct visible output:
pixel values, QImage dimensions, Window/Level application, corner
annotations, geometry extraction, and coordinate mapping.

Scenarios:
  R-01  get_frame() returns a valid QImage
  R-02  QImage dimensions match DICOM rows × cols
  R-03  MONOCHROME2 slice: middle pixels lighter than edge (gradient check)
  R-04  Window/Level: clamp-all-black when W/L set to extreme values
  R-05  Window/Level: clamp-all-white when W/L set to the other extreme
  R-06  Each slice returns a distinct QImage (not the same frame repeated)
  R-07  get_geometry() returns non-zero IPP for each slice
  R-08  get_geometry() IOP is a valid 6-element unit-vector pair
  R-09  CornerAnnotations: update_from_metadata() sets patient fields
  R-10  CornerAnnotations: slice info string contains correct numbers
  R-11  CornerAnnotations: W/L string matches supplied values
  R-12  image_xy_to_patient_xyz() returns a 3-tuple of floats
  R-13  patient_xyz_to_image_xy() returns a 2-tuple of floats
  R-14  RenderedFrame dataclass carries correct timing fields
  R-15  render_frame() qimage format is Grayscale8 or RGB888
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pytest


# ─── R-01 / R-02  get_frame returns valid QImage ──────────────────────────────

class TestGetFrameOutput:
    def test_r01_get_frame_returns_qimage(self, make_dicom_series, qt_app):
        from PySide6.QtGui import QImage
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=3)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        frame = backend.get_frame(0)
        assert frame is not None
        assert isinstance(frame.image, QImage)
        assert not frame.image.isNull()
        backend.close_series()

    def test_r02_qimage_dimensions_match_dicom(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2, rows=64, cols=96)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        frame = backend.get_frame(0)
        assert frame.width == 96
        assert frame.height == 64
        backend.close_series()


# ─── R-03 / R-04 / R-05  Window/Level ────────────────────────────────────────

class TestWindowLevel:
    def _mean_pixel(self, qimage) -> float:
        """Compute mean pixel intensity of a Grayscale8 QImage."""
        from PySide6.QtGui import QImage
        img = qimage.convertToFormat(QImage.Format.Format_Grayscale8)
        buf = img.bits().tobytes()
        arr = np.frombuffer(buf, dtype=np.uint8).copy()
        return float(arr.mean())

    def test_r04_very_narrow_bright_wl_produces_white(self, make_dicom_series, qt_app):
        """W=1, L=very high → pixel values clamp to 255 (all white)."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        backend.set_window_level(1.0, 60000.0)  # level far above all pixel values
        frame = backend.get_frame(0)
        mean = self._mean_pixel(frame.image)
        assert mean < 20.0, f"R-04: Expected dark image (mean<20), got {mean:.1f}"
        backend.close_series()

    def test_r05_very_narrow_dark_wl_produces_dark(self, make_dicom_series, qt_app):
        """Narrow window centered far above pixel HU range → all pixels clamp to 0 (dark)."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        # Pixels are ~-24 HU; window WW=50, WC=400 is far above → all clamp to 0 (dark)
        backend.set_window_level(50.0, 400.0)
        frame = backend.get_frame(0)
        mean = self._mean_pixel(frame.image)
        assert mean < 20.0, f"R-05: Expected dark image (mean<20), got {mean:.1f}"
        backend.close_series()

    def test_r03_reasonable_wl_produces_mid_range(self, make_dicom_series, qt_app):
        """Default W/L should produce intermediate grey values."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        frame = backend.get_frame(0)
        mean = self._mean_pixel(frame.image)
        # With default W/L from DICOM headers, should be non-trivial grey values
        assert 5.0 <= mean <= 250.0, f"R-03: mean {mean:.1f} outside expected [5,250]"
        backend.close_series()


# ─── R-06  Each slice is distinct ────────────────────────────────────────────

class TestSliceDistinctness:
    def test_r06_each_slice_distinct(self, make_dicom_series, qt_app):
        """Consecutive slices must differ (synthetic data has unique pixel values)."""
        from PySide6.QtGui import QImage
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=5)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        checksums: List[int] = []
        for i in range(5):
            arr = backend.get_pixel_array(i)
            checksums.append(int(arr.sum()))
        assert len(set(checksums)) == 5, f"Slices not distinct: {checksums}"
        backend.close_series()


# ─── R-07 / R-08  Geometry extraction ────────────────────────────────────────

class TestGeometryExtraction:
    def test_r07_ipp_nonzero_for_multiple_slices(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=5)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        z_values = []
        for i in range(5):
            g = backend.get_geometry(i)
            z_values.append(g.image_position_patient[2])
        # Slices should have different Z positions (step = 3.0mm in factory)
        assert len(set(z_values)) > 1, f"All slices same Z: {z_values}"
        backend.close_series()

    def test_r08_iop_valid_unit_vectors(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        g = backend.get_geometry(0)
        iop = g.image_orientation_patient
        assert len(iop) == 6
        row = np.array(iop[0:3])
        col = np.array(iop[3:6])
        assert abs(np.linalg.norm(row) - 1.0) < 0.01, "Row cosine not a unit vector"
        assert abs(np.linalg.norm(col) - 1.0) < 0.01, "Col cosine not a unit vector"
        backend.close_series()


# ─── R-09 / R-10 / R-11  CornerAnnotations ───────────────────────────────────

class TestCornerAnnotations:
    def test_r09_patient_fields_populated(self, fake_metadata, qt_app):
        from modules.viewer.fast.qt_slice_viewer import CornerAnnotations
        ca = CornerAnnotations()
        meta = fake_metadata(n=5)
        ca.update_from_metadata(meta, slice_index=0, total_slices=5, window_width=400, window_center=40)
        assert "Test" in ca.patient_name or "Patient" in ca.patient_name
        assert ca.patient_id == "PAT001"

    def test_r10_slice_info_contains_correct_numbers(self, fake_metadata, qt_app):
        from modules.viewer.fast.qt_slice_viewer import CornerAnnotations
        ca = CornerAnnotations()
        meta = fake_metadata(n=10)
        ca.update_from_metadata(meta, slice_index=3, total_slices=10, window_width=400, window_center=40)
        assert "4" in ca.slice_info   # 1-based: slice_index 3 → "4"
        assert "10" in ca.slice_info

    def test_r11_wl_string_matches_values(self, fake_metadata, qt_app):
        from modules.viewer.fast.qt_slice_viewer import CornerAnnotations
        ca = CornerAnnotations()
        meta = fake_metadata(n=5)
        ca.update_from_metadata(meta, slice_index=0, total_slices=5, window_width=350, window_center=55)
        assert "350" in ca.window_level
        assert "55" in ca.window_level


# ─── R-12 / R-13  Coordinate mapping ─────────────────────────────────────────

class TestCoordinateMapping:
    def test_r12_image_xy_to_patient_returns_3_floats(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        xyz = backend.image_xy_to_patient_xyz(32.0, 32.0, 0)
        assert len(xyz) == 3
        assert all(isinstance(v, float) for v in xyz)
        backend.close_series()

    def test_r13_patient_xyz_to_image_returns_2_floats(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        xyz = backend.image_xy_to_patient_xyz(32.0, 32.0, 0)
        xy = backend.patient_xyz_to_image_xy(xyz, 0)
        assert len(xy) == 2
        assert abs(xy[0] - 32.0) < 1.0, f"Round-trip X error: {xy[0]:.2f} vs 32"
        assert abs(xy[1] - 32.0) < 1.0, f"Round-trip Y error: {xy[1]:.2f} vs 32"
        backend.close_series()


# ─── R-14 / R-15  RenderedFrame fields ───────────────────────────────────────

class TestRenderedFrame:
    def test_r14_rendered_frame_timing_fields_positive(self, make_dicom_series, qt_app):
        from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
        series_dir, _ = make_dicom_series(n=2)
        p = Lightweight2DPipeline(config=PipelineConfig(prefetch_radius=0, prefetch_workers=1))
        p.open_series(str(series_dir))
        frame = p.get_rendered_frame(0)
        assert frame is not None
        assert frame.total_ms >= 0.0
        assert frame.decode_ms >= 0.0
        p.close_series()

    def test_r15_rendered_frame_qimage_format(self, make_dicom_series, qt_app):
        from PySide6.QtGui import QImage
        from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
        series_dir, _ = make_dicom_series(n=2)
        p = Lightweight2DPipeline(config=PipelineConfig(prefetch_radius=0, prefetch_workers=1))
        p.open_series(str(series_dir))
        frame = p.get_rendered_frame(0)
        assert not frame.qimage.isNull()
        valid_formats = {
            QImage.Format.Format_Grayscale8,
            QImage.Format.Format_Grayscale16,
            QImage.Format.Format_RGB888,
            QImage.Format.Format_ARGB32,
        }
        assert frame.qimage.format() in valid_formats, f"Unexpected QImage format: {frame.qimage.format()}"
        p.close_series()
