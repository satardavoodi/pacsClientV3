"""B3.4 — Unified Interaction-Aware Policy tests.

Verifies the production-log-driven fix:
- Wheel scroll ALWAYS passes fast_interaction=True (was False before B3.4)
- Stack-drag also passes fast_interaction=True (unchanged from B3.3)
- B4.1 passes interaction_type='wheel' or 'drag' through the bridge
- Unified settle timer (200ms) fires end_fast_interaction() after last event
- B3.7 prefetch caps fast_interaction radius to 3 and skips frame prefetch
"""

from __future__ import annotations

import time
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Bridge tests — fast_interaction propagation
# ---------------------------------------------------------------------------

class _FakeTimer:
    """Minimal QTimer stand-in for bridge tests."""

    def __init__(self):
        self._active = False
        self._callback = None
        self.start_count = 0
        self.stop_count = 0

    def setSingleShot(self, v):
        pass

    def setInterval(self, ms):
        pass

    def timeout(self):
        return self

    def connect(self, cb):
        self._callback = cb

    def start(self):
        self._active = True
        self.start_count += 1

    def stop(self):
        self._active = False
        self.stop_count += 1

    def isActive(self):
        return self._active

    def fire(self):
        if self._callback:
            self._callback()


def _build_bridge_stub(slice_count: int = 100):
    """Build a minimal bridge-like stub with B3.4 methods bound."""
    bridge = SimpleNamespace()

    # State
    bridge._current_slice = 0
    bridge._slice_count = slice_count
    bridge._stack_drag_active = False
    bridge._last_stack_scroll_ms = 0.0
    bridge._last_stack_sync_ms = 0.0
    bridge._last_stack_reference_ms = 0.0
    bridge._last_stack_target_slice = None
    bridge._suppress_render = True  # skip rendering

    # Timer
    bridge._interaction_settle_timer = _FakeTimer()
    bridge.qt_viewer = SimpleNamespace(set_total_slices_hint=lambda _count: None)
    bridge._drag_start_notifications = []
    bridge.pipeline = SimpleNamespace(
        set_interaction_slice_count_hint=lambda _count: None,
        notify_drag_started=lambda idx: bridge._drag_start_notifications.append(idx),
    )

    # Track calls
    bridge._set_slice_calls = []
    bridge._end_fast_calls = 0

    def _set_slice(idx, fast_interaction=False, *, interaction_type=''):
        bridge._current_slice = idx
        bridge._set_slice_calls.append((idx, fast_interaction, interaction_type))

    bridge.set_slice = _set_slice
    bridge.last_index_slice_saved = 0
    bridge.vtk_widget = None  # skip slider update

    def _end_fast():
        bridge._end_fast_calls += 1

    bridge.end_fast_interaction = _end_fast
    bridge._interaction_settle_timer.connect(_end_fast)

    # Import and bind the real methods from the module
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
    bridge._on_qt_scroll = types.MethodType(QtViewerBridge._on_qt_scroll, bridge)
    bridge._on_stack_drag_state = types.MethodType(QtViewerBridge._on_stack_drag_state, bridge)
    bridge._on_interaction_settled = types.MethodType(QtViewerBridge._on_interaction_settled, bridge)
    bridge._get_interaction_slice_count_hint = types.MethodType(QtViewerBridge._get_interaction_slice_count_hint, bridge)
    bridge._sync_interaction_slice_count_hint = types.MethodType(QtViewerBridge._sync_interaction_slice_count_hint, bridge)

    return bridge


class TestWheelFastInteraction:
    """Wheel scroll must ALWAYS propagate fast_interaction=True."""

    def test_wheel_scroll_sets_fast_interaction_true(self):
        """Core B3.4 fix: wheel scroll passes fast_interaction=True."""
        bridge = _build_bridge_stub(100)
        bridge._on_qt_scroll(1)  # simulate wheel delta=1 (forward)

        assert len(bridge._set_slice_calls) == 1
        idx, fast, interaction_type = bridge._set_slice_calls[0]
        assert idx == 1
        assert fast is True, "Wheel scroll must pass fast_interaction=True"
        assert interaction_type == 'wheel'

    def test_wheel_scroll_backward_sets_fast_interaction_true(self):
        bridge = _build_bridge_stub(100)
        bridge._current_slice = 50
        bridge._on_qt_scroll(-1)  # backward

        idx, fast, interaction_type = bridge._set_slice_calls[0]
        assert idx == 49
        assert fast is True
        assert interaction_type == 'wheel'

    def test_wheel_scroll_at_boundary_is_noop(self):
        bridge = _build_bridge_stub(100)
        bridge._current_slice = 0
        bridge._on_qt_scroll(-1)  # at start, backward

        assert len(bridge._set_slice_calls) == 0

    def test_wheel_multiple_scrolls_all_fast(self):
        """Multiple consecutive wheel events all pass fast_interaction=True."""
        bridge = _build_bridge_stub(100)
        for i in range(10):
            bridge._on_qt_scroll(1)

        assert len(bridge._set_slice_calls) == 10
        for idx, fast, interaction_type in bridge._set_slice_calls:
            assert fast is True, f"Scroll to {idx} must be fast_interaction=True"
            assert interaction_type == 'wheel'


class TestStackDragFastInteraction:
    """Stack-drag scroll must also propagate fast_interaction=True."""

    def test_stack_drag_scroll_sets_fast_interaction_true(self):
        bridge = _build_bridge_stub(100)
        bridge._on_stack_drag_state(True)
        bridge._on_qt_scroll(5)  # large delta typical of stack-drag

        idx, fast, interaction_type = bridge._set_slice_calls[0]
        assert fast is True
        assert interaction_type == 'drag'

    def test_stack_drag_does_not_restart_settle_timer(self):
        """During active drag, wheel settle timer should NOT restart."""
        bridge = _build_bridge_stub(100)
        bridge._on_stack_drag_state(True)

        # Timer should have been stopped on drag start
        assert bridge._interaction_settle_timer.stop_count == 1

        # Scroll while dragging
        bridge._on_qt_scroll(3)

        # Timer should NOT have been started (drag owns the lifecycle)
        assert bridge._interaction_settle_timer.start_count == 0

    def test_stack_drag_start_notifies_pipeline_for_warmup(self):
        bridge = _build_bridge_stub(100)
        bridge._current_slice = 37

        bridge._on_stack_drag_state(True)

        assert bridge._drag_start_notifications == [37]


class TestUnifiedSettleTimer:
    """The 200ms settle timer fires end_fast_interaction for both modes."""

    def test_wheel_scroll_restarts_settle_timer(self):
        bridge = _build_bridge_stub(100)
        bridge._on_qt_scroll(1)

        # Timer should have been stopped then started
        assert bridge._interaction_settle_timer.stop_count == 1
        assert bridge._interaction_settle_timer.start_count == 1

    def test_consecutive_wheel_scrolls_restart_timer(self):
        bridge = _build_bridge_stub(100)
        for _ in range(5):
            bridge._on_qt_scroll(1)

        # Timer restarted on each event
        assert bridge._interaction_settle_timer.start_count == 5

    def test_drag_stop_starts_settle_timer(self):
        bridge = _build_bridge_stub(100)
        bridge._on_stack_drag_state(True)
        bridge._on_stack_drag_state(False)  # drag stop

        # Timer started on drag stop
        assert bridge._interaction_settle_timer.start_count == 1

    def test_drag_start_stops_settle_timer(self):
        """If timer is running (from wheel), drag start cancels it."""
        bridge = _build_bridge_stub(100)
        bridge._on_qt_scroll(1)  # starts timer
        assert bridge._interaction_settle_timer.isActive()

        bridge._on_stack_drag_state(True)
        # Timer should be stopped
        assert bridge._interaction_settle_timer.stop_count == 2  # once from scroll, once from drag

    def test_settle_fires_end_fast_interaction(self):
        bridge = _build_bridge_stub(100)
        bridge._on_qt_scroll(1)

        # Simulate timer firing
        bridge._on_interaction_settled()

        assert bridge._end_fast_calls == 1
        assert bridge._stack_drag_active is False

    def test_settle_clears_stack_drag_flag(self):
        bridge = _build_bridge_stub(100)
        bridge._stack_drag_active = True
        bridge._on_interaction_settled()
        assert bridge._stack_drag_active is False


# ---------------------------------------------------------------------------
# Pipeline prefetch tests — interaction-aware radius + frame skip
# ---------------------------------------------------------------------------

class _FakePipeline:
    """Minimal pipeline stub for prefetch tests."""

    def __init__(self, slice_count=100, radius=3):
        self._slices = list(range(slice_count))
        self._interaction_slice_count_hint = 0
        self._pixel_cache = {}
        self._prefetch_pending = set()
        self._prefetch_lock = __import__("threading").Lock()
        self._fast_interaction = False
        self._last_prefetch_center = -1
        self._series_path = "stub-series"
        self._active_prefetch_targets = set()
        self._prefetch_request_epoch = 0

        # Config
        self._config = SimpleNamespace(prefetch_radius=radius)

        # Scroll tracking
        self._scroll_events = []
        self._prefetch_generation = 0

        # Track submissions
        self._submitted_prefetch = []
        self._submitted_frame_prefetch = []

    def _record_scroll_event(self, center):
        self._scroll_events.append((time.perf_counter(), center))

    def _estimate_scroll_velocity(self):
        return 50.0  # Simulate medium-fast scroll

    def _compute_adaptive_radius(self, velocity):
        return 3  # Default

    def _submit_prefetch(self, idx, gen, *, request_epoch=0):
        self._submitted_prefetch.append(idx)

    def _submit_frame_prefetch(self, idx):
        self._submitted_frame_prefetch.append(idx)


def _build_pipeline_stub(**kwargs):
    """Build pipeline stub with real _prefetch_around bound."""
    p = _FakePipeline(**kwargs)

    from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline
    p._effective_policy_slice_count = types.MethodType(
        Lightweight2DPipeline._effective_policy_slice_count,
        p,
    )
    p._prefetch_around = types.MethodType(Lightweight2DPipeline._prefetch_around, p)
    return p


class TestPrefetchInteractionAware:
    """B3.4: Prefetch adapts to interaction mode."""

    def test_idle_prefetch_uses_full_radius(self):
        """When not in fast_interaction, full adaptive radius is used."""
        p = _build_pipeline_stub(slice_count=100, radius=5)
        p._fast_interaction = False
        p._prefetch_around(50, direction=0)

        # Should submit prefetch for radius 3 (computed by _compute_adaptive_radius)
        assert len(p._submitted_prefetch) == 6  # 3 forward + 3 backward

    def test_fast_interaction_caps_radius_to_3(self):
        """During fast_interaction, B3.7 caps radius to 3."""
        p = _build_pipeline_stub(slice_count=100, radius=5)
        p._fast_interaction = True
        p._prefetch_around(50, direction=0)

        # Should submit 3 forward + 3 backward = 6
        assert len(p._submitted_prefetch) == 6
        assert set(p._submitted_prefetch) == {47, 48, 49, 51, 52, 53}

    def test_small_stack_protected_drag_uses_tiny_directional_p1_lane(self):
        """Protected drag admits two ahead and one behind, not broad warmup."""
        p = _build_pipeline_stub(slice_count=18, radius=5)
        p._fast_interaction = True
        p._fast_interaction_mode = 'drag'
        p._protected_drag_active = True
        p._estimate_scroll_velocity = lambda: 25.0
        p._prefetch_around(9, direction=1)

        assert p._submitted_prefetch == [10, 11, 8]

    def test_fast_interaction_skips_frame_prefetch(self):
        """During fast_interaction, frame prefetch is skipped for cached slices."""
        p = _build_pipeline_stub(slice_count=100, radius=5)
        p._fast_interaction = True
        # Pre-populate cache so frame prefetch path is reached
        p._pixel_cache = {51: b"data", 49: b"data"}
        p._prefetch_around(50, direction=0)

        # Frame prefetch should be skipped during fast interaction
        assert len(p._submitted_frame_prefetch) == 0

    def test_idle_allows_frame_prefetch(self):
        """When idle (not fast_interaction), frame prefetch is allowed."""
        p = _build_pipeline_stub(slice_count=100, radius=5)
        p._fast_interaction = False
        # Pre-populate cache
        p._pixel_cache = {51: b"data", 49: b"data", 52: b"data", 48: b"data", 53: b"data", 47: b"data"}
        p._prefetch_around(50, direction=0)

        # All 6 already cached → all should get frame prefetch
        assert len(p._submitted_frame_prefetch) == 6

    def test_fast_interaction_mixed_cache_only_decodes_uncached(self):
        """During fast interaction, only uncached radius-3 slices are decoded."""
        p = _build_pipeline_stub(slice_count=100, radius=5)
        p._fast_interaction = True
        p._pixel_cache = {51: b"data"}  # forward cached, backward not

        p._prefetch_around(50, direction=0)

        # Forward (51) is cached → frame prefetch skipped during interaction
        # Backward (49) is not cached → pixel decode submitted
        assert set(p._submitted_prefetch) == {47, 48, 49, 52, 53}
        assert len(p._submitted_frame_prefetch) == 0

    def test_fast_interaction_fully_cached_neighborhood_skips_submit_path(self):
        """Fully hot drag neighborhoods should avoid redundant prefetch submissions."""
        p = _build_pipeline_stub(slice_count=100, radius=5)
        p._fast_interaction = True
        p._pixel_cache = {
            47: b"data", 48: b"data", 49: b"data",
            51: b"data", 52: b"data", 53: b"data",
        }

        p._prefetch_around(50, direction=0)

        assert p._submitted_prefetch == []
        assert p._submitted_frame_prefetch == []
        assert p._active_prefetch_targets == set()
        assert p._prefetch_request_epoch == 0

    def test_fast_interaction_epoch_tracks_only_uncached_targets(self):
        """Epoch bookkeeping should ignore cached neighbors and track decode work only."""
        p = _build_pipeline_stub(slice_count=100, radius=5)
        p._fast_interaction = True
        p._pixel_cache = {51: b"data"}

        p._prefetch_around(50, direction=1)

        assert set(p._submitted_prefetch) == {52, 53}
        assert p._active_prefetch_targets == {52, 53}
        assert p._prefetch_request_epoch == 1


class TestPrefetchDedup:
    """Center dedup still works with interaction-awareness."""

    def test_same_center_deduped(self):
        p = _build_pipeline_stub(slice_count=100)
        p._fast_interaction = True
        p._prefetch_around(50, direction=0)
        p._prefetch_around(50, direction=0)  # same center

        # Second call should be deduped
        assert len(p._submitted_prefetch) == 6  # only from first call


class TestDirectionReversal:
    """F3.2 — Direction-flip mid-drag must invalidate old-direction queue."""

    def test_direction_reversal_bumps_request_epoch_and_replaces_targets(self):
        """When user reverses scroll direction, _active_prefetch_targets is
        replaced and _prefetch_request_epoch is bumped so F3.1's pre-queue gate
        rejects any in-flight stale tasks."""
        p = _build_pipeline_stub(slice_count=100, radius=3)
        p._fast_interaction = True
        # Force unidirectional scroll path (velocity >= 8.0 + direction != 0)
        p._estimate_scroll_velocity = lambda: 25.0

        # Forward scroll: prefetches center+1..center+3
        p._prefetch_around(50, direction=1)
        epoch_after_first = p._prefetch_request_epoch
        targets_after_first = set(p._active_prefetch_targets)
        assert epoch_after_first == 1
        assert targets_after_first == {51, 52, 53}
        assert p._last_prefetch_direction == 1

        # Reverse direction at a new center: must bump epoch + replace targets
        p._prefetch_around(48, direction=-1)
        assert p._prefetch_request_epoch == epoch_after_first + 1
        assert set(p._active_prefetch_targets) == {45, 46, 47}
        assert p._last_prefetch_direction == -1

    def test_same_direction_continues_without_extra_epoch_bump(self):
        """Continuing in the same direction should NOT force an epoch bump
        beyond the natural target-set-change bumps."""
        p = _build_pipeline_stub(slice_count=100, radius=3)
        p._fast_interaction = True
        p._estimate_scroll_velocity = lambda: 25.0

        p._prefetch_around(50, direction=1)
        epoch_a = p._prefetch_request_epoch  # 1
        # Step forward one slice — same direction. New targets {52,53,54},
        # different from {51,52,53}, so the natural targets-changed branch
        # bumps the epoch — but only ONCE, not the direction-flip extra bump.
        p._prefetch_around(51, direction=1)
        epoch_b = p._prefetch_request_epoch  # 2
        assert epoch_b - epoch_a == 1
        assert p._last_prefetch_direction == 1

    def test_direction_reversal_with_zero_direction_does_not_count(self):
        """Calls with direction=0 (idle/centering prefetch) must not flip the
        tracked direction nor force an epoch bump on a subsequent directional
        call that matches the *previous* non-zero direction."""
        p = _build_pipeline_stub(slice_count=100, radius=3)
        p._fast_interaction = True
        p._estimate_scroll_velocity = lambda: 25.0

        p._prefetch_around(50, direction=1)
        assert p._last_prefetch_direction == 1
        p._prefetch_around(60, direction=0)  # non-tracking call
        assert p._last_prefetch_direction == 1, "direction=0 must NOT overwrite"
        epoch_before = p._prefetch_request_epoch
        # New directional call still matching last_dir=1 → no flip-bump beyond
        # the natural target-set change.
        p._prefetch_around(70, direction=1)
        # natural change: targets {71,72,73} vs whatever was last set → 1 bump
        assert p._prefetch_request_epoch == epoch_before + 1

    def test_close_series_resets_last_direction(self):
        """close_series must reset _last_prefetch_direction so a new series
        cannot accidentally trigger a flip against a stale recorded direction."""
        from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline

        # Use the real Lightweight2DPipeline.close_series via a SimpleNamespace
        # bound stub. close_series touches a lot of attributes; mirror them.
        import threading as _t
        p = SimpleNamespace(
            _pixel_cache={},
            _frame_cache={},
            _prefetch_lock=_t.Lock(),
            _prefetch_pending=set(),
            _frame_prefetch_pending=set(),
            _prefetch_generation=3,
            _prefetch_request_epoch=7,
            _active_prefetch_targets={1, 2, 3},
            _slices=[1, 2, 3],
            _current_index=2,
            _window=400.0,
            _level=40.0,
            _series_path="x",
            _series_uid="u",
            _is_open=True,
            _interaction_slice_count_hint=10,
            _drag_start_boost_until=0.0,
            _last_drag_prefetch_submit_ts=0.0,
            _protected_drag_active=False,
            _drag_target_generation=0,
            _drag_session_started_at=0.0,
            _drag_prefetch_submitted=0,
            _drag_background_decode_count=0,
            _stack_drag_p01_slices=(),
            _first_render_logged=True,
            _filter_first_slices=set(),
            _scroll_history=[(0.0, 1)],
            _last_prefetch_center=42,
            _last_prefetch_direction=1,
            _prefetch_prepared_index=5,
        )
        Lightweight2DPipeline.close_series(p)
        assert p._last_prefetch_direction == 0
        assert p._last_prefetch_center == -1


class TestDragStartWarmup:
    """Drag startup assist should warm cache without changing steady-state policy."""

    def test_notify_drag_started_arms_short_boost_and_prefetches_center(self):
        from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline

        calls = []
        pipe = SimpleNamespace(
            _slices=list(range(120)),
            _current_index=22,
            _drag_start_boost_until=0.0,
            _last_prefetch_center=99,
            _clamp=lambda idx: max(0, min(int(idx), 119)),
            _prefetch_around=lambda idx, direction=0: calls.append((idx, direction)),
        )

        before = time.perf_counter()
        Lightweight2DPipeline.notify_drag_started(pipe)

        assert pipe._drag_start_boost_until > before
        assert pipe._last_prefetch_center == -1
        assert calls == [(22, 0)]

    def test_drag_start_boost_uses_widened_surrogate_window(self, monkeypatch):
        from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline

        pipe = SimpleNamespace(
            _slices=list(range(120)),
            _interaction_slice_count_hint=120,
            _fast_interaction=True,
            _fast_interaction_mode='drag',
            _drag_start_boost_until=time.perf_counter() + 1.0,
            _series_number='201',
            _estimate_scroll_velocity=lambda: 0.0,
        )
        pipe._effective_policy_slice_count = types.MethodType(
            Lightweight2DPipeline._effective_policy_slice_count,
            pipe,
        )

        monkeypatch.setattr(
            'modules.viewer.fast.lightweight_2d_pipeline.is_viewed_series_complete',
            lambda _series_number: False,
        )
        monkeypatch.setattr(
            'modules.viewer.fast.lightweight_2d_pipeline.is_heavy_download_active',
            lambda: False,
        )

        boosted = Lightweight2DPipeline._get_drag_surrogate_max_distance(pipe)
        assert boosted == 20

        pipe._drag_start_boost_until = time.perf_counter() - 1.0
        normal = Lightweight2DPipeline._get_drag_surrogate_max_distance(pipe)
        assert normal == 10


# ---------------------------------------------------------------------------
# Integration scenario: wheel then settle
# ---------------------------------------------------------------------------

class TestWheelSettleIntegration:
    """End-to-end: wheel scroll → fast mode → settle → quality re-render."""

    def test_wheel_scroll_then_settle_sequence(self):
        bridge = _build_bridge_stub(100)

        # Simulate rapid wheel scroll
        for _ in range(5):
            bridge._on_qt_scroll(1)

        # All scrolls should be fast
        assert all(fast for _, fast, _ in bridge._set_slice_calls)
        assert all(interaction_type == 'wheel' for _, _, interaction_type in bridge._set_slice_calls)
        assert bridge._current_slice == 5

        # Simulate timer fire (200ms settle)
        bridge._on_interaction_settled()

        # end_fast_interaction should have been called
        assert bridge._end_fast_calls == 1

    def test_drag_then_wheel_then_settle(self):
        """Mixed interaction: drag → wheel → settle fires once."""
        bridge = _build_bridge_stub(100)

        # Stack drag
        bridge._on_stack_drag_state(True)
        bridge._on_qt_scroll(10)  # big jump
        bridge._on_stack_drag_state(False)

        # Quick wheel afterwards
        bridge._on_qt_scroll(1)
        bridge._on_qt_scroll(1)

        # All should be fast
        assert all(fast for _, fast, _ in bridge._set_slice_calls)
        assert [interaction_type for _, _, interaction_type in bridge._set_slice_calls] == ['drag', 'wheel', 'wheel']

        # Settle
        bridge._on_interaction_settled()
        assert bridge._end_fast_calls == 1
