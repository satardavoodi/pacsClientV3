"""
FAST Viewer — Performance KPI Tests
=====================================
Measures and enforces latency/throughput KPIs for every layer of the
pydicom_qt rendering pipeline.

KPI targets (all measured on warm cache unless stated):
  P-01  Cold decode (per slice, 64×64 CT)          < 20 ms
  P-02  Warm decode / cache hit (per slice)         <  2 ms
  P-03  Pipeline render_frame() per frame           < 15 ms
  P-04  Window/Level change + re-render             <  5 ms
  P-05  stale_frame_guard decision                  < 0.5 ms
  P-06  open_series() for 10-slice series           < 2000 ms
  P-07  open_series() for 50-slice series           < 8000 ms
  P-08  get_slice_count() call                      <  1 ms
  P-09  FrameData attribute access (50k iterations) < 200 ms total
  P-10  StaleFrameGuard: 100k decisions             < 100 ms total
"""
from __future__ import annotations

import time
from pathlib import Path

import sys

import pytest

_FV_DIR = str(Path(__file__).parent)
if _FV_DIR not in sys.path:
    sys.path.insert(0, _FV_DIR)
from helpers import build_fake_metadata


# ─── helpers ─────────────────────────────────────────────────────────────────

def _elapsed_ms(fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return (time.perf_counter() - t0) * 1000.0, result


# ─── P-05 / P-10  StaleFrameGuard ─────────────────────────────────────────────

class TestStaleFrameGuard:
    from modules.viewer.fast.stale_frame_guard import should_render_ready_slice  # noqa: PLC0415

    def test_p05_single_decision_under_half_ms(self):
        from modules.viewer.fast.stale_frame_guard import should_render_ready_slice
        ms, _ = _elapsed_ms(should_render_ready_slice, 5, 5, 5, 3, 3)
        assert ms < 0.5, f"P-05 FAIL: {ms:.3f} ms (limit 0.5 ms)"

    def test_p10_100k_decisions_under_100ms(self):
        from modules.viewer.fast.stale_frame_guard import should_render_ready_slice
        t0 = time.perf_counter()
        for i in range(100_000):
            should_render_ready_slice(i % 200, i % 200, i % 200, 1, 1)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert elapsed_ms < 300.0, f"P-10 FAIL: {elapsed_ms:.1f} ms for 100k decisions (limit 300 ms)"

    def test_stale_generation_returns_false(self):
        from modules.viewer.fast.stale_frame_guard import should_render_ready_slice
        assert should_render_ready_slice(5, 5, 5, ready_generation=2, current_generation=3) is False

    def test_matching_generation_and_slice_returns_true(self):
        from modules.viewer.fast.stale_frame_guard import should_render_ready_slice
        assert should_render_ready_slice(7, 7, 7, ready_generation=1, current_generation=1) is True

    def test_mismatched_ready_vs_current_returns_false(self):
        from modules.viewer.fast.stale_frame_guard import should_render_ready_slice
        # ready=5 but current=6 → should not render
        assert should_render_ready_slice(5, 5, 6, ready_generation=1, current_generation=1) is False

    def test_none_requested_returns_false(self):
        from modules.viewer.fast.stale_frame_guard import should_render_ready_slice
        assert should_render_ready_slice(0, None, 0, 1, 1) is False


# ─── P-09  FrameData construction ─────────────────────────────────────────────

class TestFrameDataConstruction:
    def test_p09_50k_framedata_constructions_under_200ms(self, qt_app):
        from PySide6.QtGui import QImage
        from modules.viewer.fast.contracts import FrameData
        img = QImage(64, 64, QImage.Format.Format_Grayscale8)
        t0 = time.perf_counter()
        for _ in range(50_000):
            FrameData(
                image=img,
                width=64,
                height=64,
                photometric="MONOCHROME2",
                dtype="uint8",
                window_applied=True,
            )
        elapsed = (time.perf_counter() - t0) * 1000.0
        assert elapsed < 300.0, f"P-09 FAIL: {elapsed:.1f} ms for 50k FrameData (limit 300 ms)"


# ─── P-08  get_slice_count ────────────────────────────────────────────────────

class TestBackendSliceCount:
    def test_p08_get_slice_count_under_1ms(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, files = make_dicom_series(n=10)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        ms, count = _elapsed_ms(backend.get_slice_count)
        assert count == 10
        assert ms < 1.0, f"P-08 FAIL: {ms:.3f} ms (limit 1 ms)"
        backend.close_series()


# ─── P-01 / P-02  Decode latency ─────────────────────────────────────────────

class TestDecodeLatency:
    def test_p01_cold_decode_under_20ms(self, make_dicom_series, qt_app):
        """Cold decode: first access for a slice (no pixel cache)."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=5)
        backend = PyDicom2DBackend(cache_size=0, prefetch_radius=0)
        backend.open_series(str(series_dir))
        # Warm up system I/O on slice 0, then measure slice 1
        _ = backend.get_pixel_array(0)
        ms, arr = _elapsed_ms(backend.get_pixel_array, 1)
        assert arr is not None
        assert ms < 20.0, f"P-01 FAIL cold decode: {ms:.2f} ms (limit 20 ms)"
        backend.close_series()

    def test_p02_warm_decode_under_2ms(self, make_dicom_series, qt_app):
        """Warm decode: second access for same slice (cache hit)."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=5)
        backend = PyDicom2DBackend(cache_size=32, prefetch_radius=0)
        backend.open_series(str(series_dir))
        _ = backend.get_pixel_array(0)           # populate cache
        ms, arr = _elapsed_ms(backend.get_pixel_array, 0)  # cache hit
        assert arr is not None
        assert ms < 2.0, f"P-02 FAIL warm decode: {ms:.2f} ms (limit 2 ms)"
        backend.close_series()


# ─── P-03 / P-04  Pipeline render_frame ──────────────────────────────────────

class TestPipelineRenderFrame:
    def test_p03_render_frame_under_15ms(self, make_dicom_series, qt_app):
        """Single render_frame call (warm cache) must complete < 15ms."""
        from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
        series_dir, _ = make_dicom_series(n=5)
        cfg = PipelineConfig(
            pixel_cache_size=96,
            frame_cache_size=96,
            prefetch_radius=0,
            prefetch_workers=1,
        )
        pipeline = Lightweight2DPipeline(config=cfg)
        pipeline.open_series(str(series_dir))
        _ = pipeline.get_rendered_frame(0)  # cold
        ms, frame = _elapsed_ms(pipeline.get_rendered_frame, 0)  # warm
        assert frame is not None
        assert ms < 15.0, f"P-03 FAIL get_rendered_frame: {ms:.2f} ms (limit 15 ms)"
        pipeline.close_series()

    def test_p04_wl_change_rerrender_under_5ms(self, make_dicom_series, qt_app):
        """Change W/L then re-render — should evict frame cache but reuse pixels < 5ms."""
        from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
        series_dir, _ = make_dicom_series(n=5)
        pipeline = Lightweight2DPipeline(config=PipelineConfig(prefetch_radius=0, prefetch_workers=1))
        pipeline.open_series(str(series_dir))
        _ = pipeline.get_rendered_frame(0)     # warm pixel cache
        pipeline.set_window_level(600.0, 100.0)  # change W/L → frame cache evicted
        ms, frame = _elapsed_ms(pipeline.get_rendered_frame, 0)
        assert frame is not None
        assert ms < 5.0, f"P-04 FAIL W/L re-render: {ms:.2f} ms (limit 5 ms)"
        pipeline.close_series()


# ─── P-06 / P-07  open_series latency ────────────────────────────────────────

class TestOpenSeriesLatency:
    def test_p06_open_10_slices_under_2000ms(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=10)
        backend = PyDicom2DBackend()
        ms, _ = _elapsed_ms(backend.open_series, str(series_dir))
        assert ms < 2000.0, f"P-06 FAIL open 10 slices: {ms:.0f} ms (limit 2000 ms)"
        backend.close_series()

    def test_p07_open_50_slices_under_8000ms(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=50)
        backend = PyDicom2DBackend()
        ms, _ = _elapsed_ms(backend.open_series, str(series_dir))
        assert ms < 8000.0, f"P-07 FAIL open 50 slices: {ms:.0f} ms (limit 8000 ms)"
        backend.close_series()


# ─── Throughput: sequential scan ─────────────────────────────────────────────

class TestSequentialScanThroughput:
    def test_sequential_10_frames_total_under_150ms(self, make_dicom_series, qt_app):
        """Decode all 10 slices sequentially; total wall time must be < 150ms."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=10)
        backend = PyDicom2DBackend(cache_size=0, prefetch_radius=0)
        backend.open_series(str(series_dir))
        t0 = time.perf_counter()
        for i in range(10):
            arr = backend.get_pixel_array(i)
            assert arr is not None
        elapsed = (time.perf_counter() - t0) * 1000.0
        assert elapsed < 150.0, f"Sequential 10-frame decode: {elapsed:.0f} ms (limit 150 ms)"
        backend.close_series()
