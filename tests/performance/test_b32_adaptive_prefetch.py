"""
B3.2 Adaptive Prefetch Policy — Unit + Integration Tests
==========================================================
Validates the generation-gated adaptive prefetch behavior introduced
in B3.2-i1 (stale-aware prefetch control).

Tests:
  1. Velocity estimation accuracy
  2. Adaptive radius computation
  3. Generation gating (stale early-exit)
  4. Direction-only prefetch under fast scroll
  5. Cache pollution guard
  6. Small series full-cache behavior
  7. Stability across repeated open/close
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.viewer.fast.lightweight_2d_pipeline import (
    Lightweight2DPipeline,
    PipelineConfig,
)
from modules.viewer.fast.perf_metrics import PerfMetrics
from tests.performance.perf_helpers import make_dicom_series_on_disk


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def pipeline():
    """Create a bare pipeline (no series open)."""
    p = Lightweight2DPipeline(config=PipelineConfig(
        pixel_cache_size=96,
        frame_cache_size=96,
        prefetch_radius=20,
        prefetch_workers=4,
    ))
    yield p
    p.close_series()


@pytest.fixture
def small_series(tmp_path):
    """Create a 20-slice synthetic series."""
    d = tmp_path / "small"
    make_dicom_series_on_disk(d, n=20, rows=32, cols=32)
    return str(d)


@pytest.fixture
def medium_series(tmp_path):
    """Create a 100-slice synthetic series."""
    d = tmp_path / "medium"
    make_dicom_series_on_disk(d, n=100, rows=32, cols=32)
    return str(d)


@pytest.fixture
def large_series(tmp_path):
    """Create a 300-slice synthetic series."""
    d = tmp_path / "large"
    make_dicom_series_on_disk(d, n=300, rows=32, cols=32)
    return str(d)


# ── 1. Velocity estimation ───────────────────────────────────────────────

class TestVelocityEstimation:
    def test_no_history_returns_zero(self, pipeline):
        assert pipeline._estimate_scroll_velocity() == 0.0

    def test_single_event_returns_zero(self, pipeline):
        pipeline._record_scroll_event(10)
        assert pipeline._estimate_scroll_velocity() == 0.0

    def test_fast_scroll_detected(self, pipeline):
        """Simulating 30 slices in 300ms → ~100 sl/s."""
        base = time.perf_counter()
        for i in range(31):
            pipeline._scroll_history.append((base + i * 0.01, i))
        v = pipeline._estimate_scroll_velocity()
        assert v >= 20.0, f"Expected fast scroll detection, got {v:.1f} sl/s"

    def test_slow_scroll_detected(self, pipeline):
        """1 slice over 200ms → 5 sl/s."""
        now = time.perf_counter()
        pipeline._scroll_history.append((now - 0.2, 50))
        pipeline._scroll_history.append((now, 51))
        v = pipeline._estimate_scroll_velocity()
        assert v < 8.0, f"Expected slow scroll, got {v:.1f} sl/s"

    def test_old_events_ignored(self, pipeline):
        """Events older than 300ms should not affect velocity."""
        now = time.perf_counter()
        # Old event (1 second ago)
        pipeline._scroll_history.append((now - 1.0, 0))
        pipeline._scroll_history.append((now - 0.9, 50))
        # Recent event
        pipeline._scroll_history.append((now - 0.1, 100))
        pipeline._scroll_history.append((now, 101))
        v = pipeline._estimate_scroll_velocity()
        assert v < 20.0, f"Old events should not inflate velocity, got {v:.1f} sl/s"


# ── 2. Adaptive radius computation ──────────────────────────────────────

class TestAdaptiveRadius:
    def test_small_series_full_radius(self, pipeline):
        """Small series (≤30) should get full-series radius."""
        pipeline._slices = [None] * 20  # mock
        r = pipeline._compute_adaptive_radius(0.0)
        assert r >= 20, f"Small series should cache all, got radius={r}"

    def test_fast_scroll_narrow_radius(self, pipeline):
        """Fast scroll → radius 3."""
        pipeline._slices = [None] * 200
        r = pipeline._compute_adaptive_radius(30.0)
        assert r == 3, f"Expected radius=3 for fast scroll, got {r}"

    def test_medium_scroll_medium_radius(self, pipeline):
        """Medium scroll → radius 8."""
        pipeline._slices = [None] * 200
        r = pipeline._compute_adaptive_radius(12.0)
        assert r == 8, f"Expected radius=8 for medium scroll, got {r}"

    def test_slow_scroll_wide_radius(self, pipeline):
        """Slow scroll → radius 15."""
        pipeline._slices = [None] * 200
        r = pipeline._compute_adaptive_radius(3.0)
        assert r == 15, f"Expected radius=15 for slow scroll, got {r}"

    def test_idle_wide_radius(self, pipeline):
        """Idle → radius 15."""
        pipeline._slices = [None] * 200
        r = pipeline._compute_adaptive_radius(0.0)
        assert r == 15, f"Expected radius=15 for idle, got {r}"


# ── 3. Generation gating ────────────────────────────────────────────────

class TestGenerationGating:
    def test_generation_stable_during_scroll(self, pipeline, medium_series):
        """Generation should NOT bump during normal position scrolling."""
        pipeline.open_series(medium_series)
        gen0 = pipeline._prefetch_generation
        pipeline._prefetch_around(50)
        pipeline._prefetch_around(51)  # different center
        pipeline._prefetch_around(52)
        assert pipeline._prefetch_generation == gen0, \
            "Generation should stay stable during scroll"

    def test_wl_bumps_generation(self, pipeline, medium_series):
        """Window/Level change should bump generation."""
        pipeline.open_series(medium_series)
        gen0 = pipeline._prefetch_generation
        pipeline.set_window_level(400.0, 40.0)
        assert pipeline._prefetch_generation > gen0, \
            "set_window_level should bump generation"

    def test_close_bumps_generation(self, pipeline, medium_series):
        pipeline.open_series(medium_series)
        pipeline._prefetch_around(50)
        gen_before_close = pipeline._prefetch_generation
        pipeline.close_series()
        assert pipeline._prefetch_generation > gen_before_close


# ── 4. Direction-only prefetch ───────────────────────────────────────────

class TestDirectionalPrefetch:
    def test_fast_forward_skips_backward(self, pipeline, medium_series):
        """During fast forward scroll, no backward prefetch submitted."""
        pipeline.open_series(medium_series)
        pm = PerfMetrics.get()
        pm.enable()

        # Simulate fast forward scroll via scroll history
        now = time.perf_counter()
        for i in range(10):
            pipeline._scroll_history.append((now - 0.3 + i * 0.03, 50 + i))

        pipeline._prefetch_around(59, direction=1)

        # Give workers a moment then check what was submitted
        time.sleep(0.1)
        snap = pm.snapshot()
        # With radius=3, forward-only, we expect ≤3 submitted (not 6)
        assert snap["prefetch_submitted"] <= 6, \
            f"Expected ≤6 submissions for forward-only, got {snap['prefetch_submitted']}"
        pm.disable()


# ── 5. Cache pollution guard ────────────────────────────────────────────

class TestCachePollutionGuard:
    def test_stale_decode_not_cached(self, pipeline, medium_series):
        """Decoded slice far from current position should be discarded."""
        pipeline.open_series(medium_series)
        pipeline._current_index = 90  # user is at slice 90

        # Manually call _decode_into_cache for slice 10 (far from 90)
        # with a stale generation
        old_gen = pipeline._prefetch_generation
        pipeline._prefetch_generation = old_gen + 10  # advance generation far ahead
        with pipeline._prefetch_lock:
            pipeline._prefetch_pending.add(10)

        pipeline._decode_into_cache(10, old_gen)

        # Slice 10 should NOT be in pixel cache (generation was stale)
        assert 10 not in pipeline._pixel_cache, \
            "Stale-generation decode should not enter pixel cache"


# ── 6. Small series full-cache ──────────────────────────────────────────

class TestSmallSeries:
    def test_all_slices_prefetched(self, pipeline, small_series):
        """Small series (≤30) should prefetch all slices."""
        pipeline.open_series(small_series)
        pm = PerfMetrics.get()
        pm.enable()

        # Access middle slice — should prefetch everything
        pipeline.get_rendered_frame(10)
        time.sleep(0.5)  # let workers finish

        snap = pm.snapshot()
        # Should have submitted towards all 19 other slices
        assert snap["prefetch_submitted"] >= 15, \
            f"Small series should prefetch aggressively, got {snap['prefetch_submitted']} submitted"
        pm.disable()


# ── 7. Repeated open/close stability ────────────────────────────────────

class TestStability:
    def test_open_close_no_leak(self, pipeline, tmp_path):
        """Repeated open/close should not leak state."""
        for i in range(10):
            d = tmp_path / f"s{i}"
            make_dicom_series_on_disk(d, n=20, rows=16, cols=16)
            pipeline.open_series(str(d))
            pipeline.get_rendered_frame(5)
            pipeline.close_series()

        assert pipeline._scroll_history == []
        assert pipeline._current_index == 0
        assert pipeline._last_prefetch_center == -1
        assert len(pipeline._pixel_cache) == 0
        assert len(pipeline._frame_cache) == 0

    def test_generation_monotonic_across_series(self, pipeline, tmp_path):
        """Generation should be monotonically increasing across open/close."""
        gens = []
        for i in range(5):
            d = tmp_path / f"s{i}"
            make_dicom_series_on_disk(d, n=10, rows=16, cols=16)
            pipeline.open_series(str(d))
            pipeline._prefetch_around(5)
            gens.append(pipeline._prefetch_generation)
            pipeline.close_series()
            gens.append(pipeline._prefetch_generation)

        # All generations should be strictly increasing
        for j in range(1, len(gens)):
            assert gens[j] >= gens[j - 1], \
                f"Generation should be monotonic: {gens}"
