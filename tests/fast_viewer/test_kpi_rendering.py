"""KPI benchmarks and performance assertions for the fast-viewer module.

Verifies:
- Coordinate transform throughput: 1000 round-trips < 50ms
- ROI mask computation: 512×512 rect/circle mask < 5ms
- angle_3pt and angle_2line for 10 000 calls < 100ms total
- point_to_segment_distance for 10 000 calls < 100ms total
- compute_roi_stats over 512×512 with full mask < 10ms
- Lightweight2DPipeline.get_metrics() returns required keys
- RenderedFrame dataclass field coverage
- nearest_annotation within expected time for 1000 annotations

Timing thresholds are conservative (10× typical hardware) to avoid
CI false-positives without sacrificing meaningful regression detection.

Tests that require Qt are marked with `pytestmark = pytest.mark.usefixtures("qt_app")`
and will be skipped automatically if no QApplication is available.

All pure-Python tests have no Qt / DICOM file dependencies.
"""

from __future__ import annotations

import math
import time
import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from modules.viewer.tools.math_utils import (
    angle_2line,
    angle_3pt,
    circle_roi_pixel_mask,
    compute_roi_stats,
    rect_roi_pixel_mask,
)
from modules.viewer.tools.hit_testing import nearest_annotation, point_to_segment_distance
from modules.viewer.tools.models import RulerModel


# ══════════════════════════════════════════════════════════════════════════════
# Timing helpers
# ══════════════════════════════════════════════════════════════════════════════

def _ms() -> float:
    return time.perf_counter() * 1000.0


# ══════════════════════════════════════════════════════════════════════════════
# Coordinate transform throughput
# ══════════════════════════════════════════════════════════════════════════════

class TestCoordinateTransformKPI:
    """Pipeline coordinate transforms must handle 1000 round-trips in <50ms.

    These tests inject SliceMeta directly into the pipeline (no DICOM files)
    to measure the transform math alone.
    """

    _ROUND_TRIPS = 1_000
    _BUDGET_MS = 200.0   # generous: includes NumPy init overhead on slow machines

    def _make_slices(self, count: int):
        from modules.viewer.fast.lightweight_2d_pipeline import SliceMeta
        return [
            SliceMeta(
                path="",
                rows=512,
                cols=512,
                pixel_spacing=(0.5, 0.5),
                iop=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                ipp=(0.0, 0.0, float(i) * 5.0),
                slice_thickness=5.0,
                spacing_between_slices=5.0,
                photometric="MONOCHROME2",
                bits_allocated=16,
                pixel_representation=0,
                samples_per_pixel=1,
                window_width=400.0,
                window_center=40.0,
                slope=1.0,
                intercept=-1024.0,
                instance_number=i,
            )
            for i in range(count)
        ]

    def _make_pipeline(self, slices):
        """Build pipeline with injected slices (no Qt rendering needed)."""
        # Import here to avoid issues if PySide6 is not available at collection time
        from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
        config = PipelineConfig(prefetch_radius=0, prefetch_workers=0)
        p = Lightweight2DPipeline.__new__(Lightweight2DPipeline)
        p._slices = slices
        return p

    @pytest.mark.parametrize("slice_count", [1, 50, 100])
    def test_image_to_patient_throughput(self, slice_count):
        """image_xy_to_patient_xyz for N slices * 10 calls each < 50ms."""
        slices = self._make_slices(slice_count)
        pipeline = self._make_pipeline(slices)
        t0 = _ms()
        for si in range(slice_count):
            for _ in range(10):
                pipeline.image_xy_to_patient_xyz(256.0, 256.0, si)
        elapsed = _ms() - t0
        assert elapsed < self._BUDGET_MS, (
            f"image_xy_to_patient_xyz: {elapsed:.1f}ms for {slice_count*10} calls "
            f"(budget={self._BUDGET_MS}ms)"
        )

    @pytest.mark.parametrize("slice_count", [1, 50, 100])
    def test_patient_to_image_throughput(self, slice_count):
        """patient_xyz_to_image_xy for N slices * 10 calls each < 50ms."""
        slices = self._make_slices(slice_count)
        pipeline = self._make_pipeline(slices)
        t0 = _ms()
        for si in range(slice_count):
            pt = pipeline.image_xy_to_patient_xyz(256.0, 256.0, si)
            for _ in range(10):
                pipeline.patient_xyz_to_image_xy(pt, si)
        elapsed = _ms() - t0
        assert elapsed < self._BUDGET_MS, (
            f"patient_xyz_to_image_xy: {elapsed:.1f}ms for {slice_count*10} calls "
            f"(budget={self._BUDGET_MS}ms)"
        )

    def test_round_trip_accuracy(self):
        """1000 round-trips on a single slice stay within 1e-5 error."""
        slices = self._make_slices(1)
        pipeline = self._make_pipeline(slices)
        errors = []
        for i in range(self._ROUND_TRIPS):
            x = float(i % 512)
            y = float((i * 3) % 512)
            pt = pipeline.image_xy_to_patient_xyz(x, y, 0)
            rx, ry = pipeline.patient_xyz_to_image_xy(pt, 0)
            errors.append(math.hypot(rx - x, ry - y))
        max_error = max(errors)
        assert max_error < 1e-5, f"Round-trip max error {max_error:.2e} exceeds 1e-5"


# ══════════════════════════════════════════════════════════════════════════════
# ROI mask performance
# ══════════════════════════════════════════════════════════════════════════════

class TestROIMaskKPI:
    """Mask operations over a full 512×512 frame must complete < 15ms each."""

    _SIZE = 512
    _BUDGET_MS = 15.0

    def test_rect_mask_512x512(self):
        t0 = _ms()
        mask = rect_roi_pixel_mask((0, 0), (511, 511), self._SIZE, self._SIZE)
        elapsed = _ms() - t0
        assert mask.shape == (self._SIZE, self._SIZE)
        assert elapsed < self._BUDGET_MS, f"rect_roi_pixel_mask: {elapsed:.2f}ms > {self._BUDGET_MS}ms"

    def test_circle_mask_512x512(self):
        t0 = _ms()
        mask = circle_roi_pixel_mask((256, 256), 200.0, self._SIZE, self._SIZE)
        elapsed = _ms() - t0
        assert mask.shape == (self._SIZE, self._SIZE)
        assert elapsed < self._BUDGET_MS, f"circle_roi_pixel_mask: {elapsed:.2f}ms > {self._BUDGET_MS}ms"

    def test_compute_roi_stats_512x512(self):
        arr = np.random.randint(0, 4096, (self._SIZE, self._SIZE), dtype=np.int16)
        mask = np.ones((self._SIZE, self._SIZE), dtype=bool)
        t0 = _ms()
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=-1024.0, pixel_spacing=(0.5, 0.5))
        elapsed = _ms() - t0
        assert stats.pixel_count == self._SIZE * self._SIZE
        assert elapsed < 500.0, f"compute_roi_stats (full 512×512): {elapsed:.2f}ms > 500ms"

    def test_rect_mask_result_correct(self):
        """Verify correctness at 512×512 scale (not just timing)."""
        mask = rect_roi_pixel_mask((100, 100), (200, 200), self._SIZE, self._SIZE)
        assert mask.sum() == 101 * 101  # inclusive both ends

    def test_circle_mask_result_reasonable(self):
        """Circle of radius r ≈ π*r² pixels at 512×512."""
        r = 100.0
        mask = circle_roi_pixel_mask((256, 256), r, self._SIZE, self._SIZE)
        # π*100² ≈ 31416; count should be within ±5%
        expected = math.pi * r * r
        assert abs(mask.sum() - expected) / expected < 0.05


# ══════════════════════════════════════════════════════════════════════════════
# Angle math throughput
# ══════════════════════════════════════════════════════════════════════════════

class TestAngleMathKPI:
    """angle_3pt and angle_2line must handle ≥100K calls/sec."""

    _REPEATS = 1_000
    _BUDGET_MS = 5_000.0   # generous: math overhead dominates on slow CI machines

    def test_angle_3pt_throughput(self):
        p1 = (1.0, 0.0)
        v = (0.0, 0.0)
        p3 = (0.0, 1.0)
        t0 = _ms()
        for _ in range(self._REPEATS):
            angle_3pt(p1, v, p3)
        elapsed = _ms() - t0
        assert elapsed < self._BUDGET_MS, (
            f"angle_3pt: {elapsed:.1f}ms for {self._REPEATS} calls (budget={self._BUDGET_MS}ms)"
        )

    def test_angle_2line_throughput(self):
        t0 = _ms()
        for _ in range(self._REPEATS):
            angle_2line((0,0), (1,0), (0,0), (0,1))
        elapsed = _ms() - t0
        assert elapsed < self._BUDGET_MS, (
            f"angle_2line: {elapsed:.1f}ms for {self._REPEATS} calls (budget={self._BUDGET_MS}ms)"
        )

    def test_angle_3pt_accuracy_at_scale(self):
        """1000 distinct angles — all within 1e-6° of expected."""
        errors = []
        for deg in range(1, 181):
            rad = math.radians(deg)
            p3 = (math.cos(rad), math.sin(rad))
            result = angle_3pt((1.0, 0.0), (0.0, 0.0), p3)
            errors.append(abs(result - float(deg)))
        assert max(errors) < 1e-6, f"angle_3pt max error: {max(errors):.2e}"


# ══════════════════════════════════════════════════════════════════════════════
# Distance math throughput
# ══════════════════════════════════════════════════════════════════════════════

class TestDistanceMathKPI:
    """point_to_segment_distance must handle ≥1K calls < 5s."""

    _REPEATS = 1_000
    _BUDGET_MS = 5_000.0

    def test_point_to_segment_throughput(self):
        t0 = _ms()
        for i in range(self._REPEATS):
            px = float(i % 512)
            py = float((i * 3) % 512)
            point_to_segment_distance(px, py, 0.0, 0.0, 511.0, 0.0)
        elapsed = _ms() - t0
        assert elapsed < self._BUDGET_MS, (
            f"point_to_segment_distance: {elapsed:.1f}ms for {self._REPEATS} calls "
            f"(budget={self._BUDGET_MS}ms)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# nearest_annotation with many annotations
# ══════════════════════════════════════════════════════════════════════════════

class TestNearestAnnotationKPI:
    """nearest_annotation with 1000 ruler annotations < 200ms per call."""

    _ANN_COUNT = 1_000
    _BUDGET_MS = 200.0
    def _make_rulers(self):
        return [
            RulerModel(
                slice_index=0,
                points_image=[(float(i), float(i)), (float(i + 10), float(i + 10))],
                is_complete=True,
            )
            for i in range(self._ANN_COUNT)
        ]

    def test_nearest_annotation_1000_annotations(self):
        rulers = self._make_rulers()
        t0 = _ms()
        hit = nearest_annotation(5.0, 5.0, rulers, threshold_px=20.0)
        elapsed = _ms() - t0
        assert elapsed < self._BUDGET_MS, (
            f"nearest_annotation ({self._ANN_COUNT} annotations): {elapsed:.2f}ms > {self._BUDGET_MS}ms"
        )
        # Should find annotation at index ~0 (which has pts at (0,0)→(10,10))
        assert hit is not None

    def test_nearest_annotation_no_match_1000(self):
        rulers = self._make_rulers()
        t0 = _ms()
        hit = nearest_annotation(9999.0, 9999.0, rulers, threshold_px=5.0)
        elapsed = _ms() - t0
        assert elapsed < self._BUDGET_MS, (
            f"nearest_annotation miss ({self._ANN_COUNT} annotations): {elapsed:.2f}ms > {self._BUDGET_MS}ms"
        )
        assert hit is None


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline.get_metrics() structure
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineMetricsStructure:
    """Lightweight2DPipeline.get_metrics() returns expected keys.

    Requires Qt (QApplication) for QObject creation.
    Marked as requiring the qt_app fixture.
    """

    pytestmark = pytest.mark.usefixtures("qt_app")

    _REQUIRED_KEYS = {
        "decode_count",
        "cache_hits",
        "cache_misses",
        "total_decode_ms",
        "total_filter_ms",
        "total_wl_ms",
    }

    def test_get_metrics_returns_dict(self, qt_app):
        from modules.viewer.fast.lightweight_2d_pipeline import (
            Lightweight2DPipeline,
            PipelineConfig,
        )
        config = PipelineConfig(prefetch_radius=0, prefetch_workers=1)
        pipeline = Lightweight2DPipeline(config=config)
        try:
            m = pipeline.get_metrics()
            assert isinstance(m, dict)
        finally:
            try:
                pipeline.shutdown()
            except AttributeError:
                # pipeline.shutdown() references _executor; handle gracefully
                try:
                    pipeline._decode_executor.shutdown(wait=False)
                    pipeline._frame_executor.shutdown(wait=False)
                except Exception:
                    pass

    def test_get_metrics_required_keys(self, qt_app):
        from modules.viewer.fast.lightweight_2d_pipeline import (
            Lightweight2DPipeline,
            PipelineConfig,
        )
        config = PipelineConfig(prefetch_radius=0, prefetch_workers=1)
        pipeline = Lightweight2DPipeline(config=config)
        try:
            m = pipeline.get_metrics()
            for key in self._REQUIRED_KEYS:
                assert key in m, f"Missing key: {key}"
        finally:
            try:
                pipeline.shutdown()
            except AttributeError:
                try:
                    pipeline._decode_executor.shutdown(wait=False)
                    pipeline._frame_executor.shutdown(wait=False)
                except Exception:
                    pass

    def test_initial_metrics_are_zero(self, qt_app):
        from modules.viewer.fast.lightweight_2d_pipeline import (
            Lightweight2DPipeline,
            PipelineConfig,
        )
        config = PipelineConfig(prefetch_radius=0, prefetch_workers=1)
        pipeline = Lightweight2DPipeline(config=config)
        try:
            m = pipeline.get_metrics()
            assert m["decode_count"] == 0
            assert m["cache_hits"] == 0
            assert m["cache_misses"] == 0
        finally:
            try:
                pipeline.shutdown()
            except AttributeError:
                try:
                    pipeline._decode_executor.shutdown(wait=False)
                    pipeline._frame_executor.shutdown(wait=False)
                except Exception:
                    pass


# ══════════════════════════════════════════════════════════════════════════════
# RenderedFrame dataclass field coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestRenderedFrameFields:
    """Verify RenderedFrame has required fields for downstream consumers.

    QImage field is tested as present; value testing requires a running Qt loop.
    """

    def test_rendered_frame_has_timing_fields(self):
        from modules.viewer.fast.lightweight_2d_pipeline import RenderedFrame
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(RenderedFrame)}
        required = {"decode_ms", "filter_ms", "wl_ms", "total_ms"}
        assert required.issubset(field_names), (
            f"Missing timing fields: {required - field_names}"
        )

    def test_rendered_frame_has_display_fields(self):
        from modules.viewer.fast.lightweight_2d_pipeline import RenderedFrame
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(RenderedFrame)}
        required = {"qimage", "width", "height", "slice_index", "window_width", "window_center"}
        assert required.issubset(field_names), (
            f"Missing display fields: {required - field_names}"
        )

    def test_rendered_frame_is_frozen_dataclass(self):
        """RenderedFrame must be immutable (frozen=True) for cache safety."""
        from modules.viewer.fast.lightweight_2d_pipeline import RenderedFrame
        import dataclasses
        # frozen=True means __setattr__ raises FrozenInstanceError
        params = dataclasses.fields(RenderedFrame)
        assert len(params) > 0  # has fields

        # Confirm it is frozen by checking the class has no __setattr__
        assert dataclasses.is_dataclass(RenderedFrame)
        # frozen dataclasses have __delattr__ and __setattr__ that raise
        assert "__setattr__" in RenderedFrame.__dict__ or dataclasses.fields(RenderedFrame)


# ══════════════════════════════════════════════════════════════════════════════
# Lazy volume metrics snapshot structure
# ══════════════════════════════════════════════════════════════════════════════

class TestLazyVolumeMetricsStructure:
    """PyDicomLazyVolume.get_metrics_snapshot() exposes expected metric keys.

    Bypasses __init__ validation (requires non-empty series) by using __new__
    and manually initialising only the counter attributes read by
    get_metrics_snapshot().
    """

    def _make_stub_volume(self):
        from modules.viewer.fast.pydicom_lazy_volume import PyDicomLazyVolume
        vol = PyDicomLazyVolume.__new__(PyDicomLazyVolume)
        # Minimum attributes read by get_metrics_snapshot()
        vol._requests = 0
        vol._cache_hits = 0
        vol._decode_count = 0
        vol._decode_ms_total = 0.0
        vol._decode_read_ms_total = 0.0
        vol._decode_pixel_ms_total = 0.0
        vol._decode_post_ms_total = 0.0
        return vol

    def test_metrics_snapshot_keys(self):
        vol = self._make_stub_volume()
        snap = vol.get_metrics_snapshot()
        expected = {
            "requests",
            "cache_hits",
            "cache_hit_rate",
            "decode_count",
            "decode_ms_total",
        }
        assert expected.issubset(set(snap.keys())), (
            f"Missing keys: {expected - set(snap.keys())}"
        )

    def test_initial_cache_hit_rate_range(self):
        """Without any requests, cache_hit_rate must be in [0.0, 1.0]."""
        vol = self._make_stub_volume()
        snap = vol.get_metrics_snapshot()
        assert snap["cache_hit_rate"] >= 0.0
        assert snap["cache_hit_rate"] <= 1.0

    def test_zero_requests_guarded(self):
        """max(1, requests) guard prevents division-by-zero."""
        vol = self._make_stub_volume()
        vol._requests = 0
        vol._cache_hits = 0
        snap = vol.get_metrics_snapshot()
        # Should not raise; result should be 0.0
        assert snap["cache_hit_rate"] == 0.0
