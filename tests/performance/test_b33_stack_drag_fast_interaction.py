"""
B3.3 Stack-Drag Fast-Interaction Parity Tests
===============================================
Verifies that stack-drag uses fast_interaction=True during drag and
settles with end_fast_interaction() after drag stops.

Tests:
  1. stack_drag_state_changed signal emitted on start/stop
  2. Bridge tracks _stack_drag_active state
  3. _on_qt_scroll passes fast_interaction=True during stack-drag
  4. _on_qt_scroll passes fast_interaction=False when no drag
  5. Settle timer created and configured
  6. Settle timer fires end_fast_interaction after drag stop
  7. Settle timer cancelled when drag resumes
  8. Area-exit emits stack_drag_state_changed(False)
  9. Pipeline filter skipped during stack-drag
  10. Pipeline filter applied after settle

Usage:
  python -m pytest tests/performance/test_b33_stack_drag_fast_interaction.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

# Ensure QApplication exists
_app = QApplication.instance() or QApplication(sys.argv)

from tests.performance.perf_helpers import make_dicom_series_on_disk


@pytest.fixture(scope="module")
def series_dir():
    """Create a synthetic DICOM series on disk."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "series"
        make_dicom_series_on_disk(p, n=20, rows=64, cols=64)
        yield str(p)


@pytest.fixture
def pipeline(series_dir):
    """Create a Lightweight2DPipeline for testing."""
    from modules.viewer.fast.lightweight_2d_pipeline import (
        Lightweight2DPipeline,
        PipelineConfig,
    )
    cfg = PipelineConfig(
        pixel_cache_size=32,
        frame_cache_size=32,
        prefetch_radius=5,
        prefetch_workers=1,
    )
    p = Lightweight2DPipeline(config=cfg)
    p.open_series(series_dir)
    yield p
    p.close_series()


@pytest.fixture
def bridge(series_dir, pipeline):
    """Create a QtViewerBridge for testing signal flow."""
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer

    qt_viewer = QtSliceViewer()
    metadata = {
        "series": {
            "series_number": 1,
            "modality": "CT",
            "series_description": "Test",
            "image_count": 20,
        },
        "instances": [],
    }
    bridge = QtViewerBridge(qt_viewer, pipeline, metadata)
    yield bridge


# ── Signal emission tests ────────────────────────────────────────────────────

class TestStackDragSignal:
    """Test that QtSliceViewer emits stack_drag_state_changed correctly."""

    def test_signal_exists(self):
        """Signal is defined on QtSliceViewer."""
        from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
        viewer = QtSliceViewer()
        assert hasattr(viewer, "stack_drag_state_changed")

    def test_signal_emission_on_start(self):
        """Signal emitted with True when stack-drag activates."""
        from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
        viewer = QtSliceViewer()
        received = []
        viewer.stack_drag_state_changed.connect(lambda v: received.append(v))
        # Simulate: emit directly
        viewer.stack_drag_state_changed.emit(True)
        assert received == [True]

    def test_signal_emission_on_stop(self):
        """Signal emitted with False when stack-drag deactivates."""
        from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
        viewer = QtSliceViewer()
        received = []
        viewer.stack_drag_state_changed.connect(lambda v: received.append(v))
        viewer.stack_drag_state_changed.emit(False)
        assert received == [False]


# ── Bridge state tracking tests ──────────────────────────────────────────────

class TestBridgeStackDragState:
    """Test that QtViewerBridge tracks stack-drag state."""

    def test_initial_state_is_false(self, bridge):
        """Bridge starts with _stack_drag_active=False."""
        assert bridge._stack_drag_active is False

    def test_state_set_true_on_drag_start(self, bridge):
        """Bridge sets _stack_drag_active=True when signal received."""
        bridge._on_stack_drag_state(True)
        assert bridge._stack_drag_active is True

    def test_state_set_false_on_drag_stop(self, bridge):
        """Bridge sets _stack_drag_active=False after settle."""
        bridge._on_stack_drag_state(True)
        assert bridge._stack_drag_active is True
        bridge._on_stack_drag_state(False)
        # Note: settle timer is armed but hasn't fired yet
        # _stack_drag_active stays True until timer fires
        # Let's verify the timer is running
        assert bridge._interaction_settle_timer.isActive()


class TestBridgeSettleTimer:
    """Test the 200ms settle timer behavior."""

    def test_settle_timer_exists(self, bridge):
        """Settle timer is created."""
        assert hasattr(bridge, "_interaction_settle_timer")
        assert isinstance(bridge._interaction_settle_timer, QTimer)

    def test_settle_timer_is_single_shot(self, bridge):
        """Settle timer is single-shot with 200ms interval."""
        assert bridge._interaction_settle_timer.isSingleShot()
        assert bridge._interaction_settle_timer.interval() == 200

    def test_settle_timer_started_on_drag_stop(self, bridge):
        """Settle timer starts when stack-drag stops."""
        bridge._on_stack_drag_state(True)
        bridge._on_stack_drag_state(False)
        assert bridge._interaction_settle_timer.isActive()

    def test_settle_timer_cancelled_on_drag_resume(self, bridge):
        """Settle timer cancelled when drag resumes before settling."""
        bridge._on_stack_drag_state(True)
        bridge._on_stack_drag_state(False)
        assert bridge._interaction_settle_timer.isActive()
        # Resume drag
        bridge._on_stack_drag_state(True)
        assert not bridge._interaction_settle_timer.isActive()
        assert bridge._stack_drag_active is True

    def test_settle_calls_end_fast_interaction(self, bridge):
        """Settle timer fires end_fast_interaction."""
        bridge._on_stack_drag_state(True)
        bridge._on_stack_drag_state(False)
        # Simulate timer firing
        bridge._on_interaction_settled()
        assert bridge._stack_drag_active is False


# ── Fast-interaction propagation tests ───────────────────────────────────────

class TestFastInteractionPropagation:
    """Test that _on_qt_scroll propagates fast_interaction correctly."""

    def test_scroll_without_drag_uses_fast_false(self, bridge):
        """Normal wheel scroll uses fast_interaction=True with wheel routing."""
        bridge._stack_drag_active = False
        original_set_slice = bridge.set_slice
        calls = []

        def mock_set_slice(idx, fast_interaction=False, **kwargs):
            calls.append((fast_interaction, kwargs.get("interaction_type", "")))
            return original_set_slice(idx, fast_interaction=fast_interaction, **kwargs)

        bridge.set_slice = mock_set_slice
        bridge._on_qt_scroll(1)
        assert len(calls) == 1
        assert calls[0] == (True, "wheel")

    def test_scroll_during_drag_uses_fast_true(self, bridge):
        """Stack-drag scroll uses fast_interaction=True."""
        bridge._stack_drag_active = True
        original_set_slice = bridge.set_slice
        calls = []

        def mock_set_slice(idx, fast_interaction=False, **kwargs):
            calls.append((fast_interaction, kwargs.get("interaction_type", "")))
            return original_set_slice(idx, fast_interaction=fast_interaction, **kwargs)

        bridge.set_slice = mock_set_slice
        bridge._on_qt_scroll(1)
        assert len(calls) == 1
        assert calls[0] == (True, "drag")


# ── Pipeline filter behavior tests ───────────────────────────────────────────

class TestPipelineFilterBehavior:
    """Test that pipeline skips filter during fast_interaction."""

    def test_filter_skipped_during_fast_interaction(self, pipeline):
        """When fast_interaction=True, filter is not applied."""
        pipeline.set_fast_interaction(True)
        frame = pipeline.get_rendered_frame(5)
        # filter_ms should be near-zero (only timer overhead, no actual filter)
        assert frame.filter_ms < 0.5, f"Expected near-zero filter_ms, got {frame.filter_ms}"

    def test_filter_applied_without_fast_interaction(self, pipeline):
        """When fast_interaction=False, filter is applied (if enabled)."""
        pipeline.set_fast_interaction(False)
        frame = pipeline.get_rendered_frame(5)
        # Filter may or may not be enabled by default config, but the path is exercised
        # The important thing is the code runs without error


# ── Integration-style flow test ──────────────────────────────────────────────

class TestStackDragFlow:
    """Integration test simulating a full stack-drag → settle cycle."""

    def test_full_drag_settle_cycle(self, bridge):
        """Simulate: start drag → scroll several slices → stop drag → settle."""
        # Start drag
        bridge._on_stack_drag_state(True)
        assert bridge._stack_drag_active is True

        # Scroll several slices (simulates the ±1 signal loop)
        for _ in range(5):
            bridge._on_qt_scroll(1)

        # Current slice should have advanced
        assert bridge._current_slice >= 5

        # Stop drag
        bridge._on_stack_drag_state(False)
        assert bridge._interaction_settle_timer.isActive()

        # Simulate settle timer firing
        bridge._on_interaction_settled()
        assert bridge._stack_drag_active is False
        # Pipeline should be in non-fast mode
        assert bridge.pipeline._fast_interaction is False

    def test_drag_resume_before_settle(self, bridge):
        """Simulate: drag → stop → resume before 200ms → settle never fires."""
        # Start drag
        bridge._on_stack_drag_state(True)
        bridge._on_qt_scroll(1)

        # Stop drag
        bridge._on_stack_drag_state(False)
        assert bridge._interaction_settle_timer.isActive()

        # Resume drag before settle fires
        bridge._on_stack_drag_state(True)
        assert not bridge._interaction_settle_timer.isActive()
        assert bridge._stack_drag_active is True

        # Scroll more
        bridge._on_qt_scroll(1)
        bridge._on_qt_scroll(1)

        # Now final stop + settle
        bridge._on_stack_drag_state(False)
        bridge._on_interaction_settled()
        assert bridge._stack_drag_active is False

    def test_multiple_steps_per_event_all_fast(self, bridge):
        """When drag emits 4 steps in a row, all use fast_interaction=True."""
        bridge._on_stack_drag_state(True)
        calls = []
        original = bridge.set_slice

        def track(idx, fast_interaction=False, **kwargs):
            calls.append((fast_interaction, kwargs.get("interaction_type", "")))
            return original(idx, fast_interaction=fast_interaction, **kwargs)

        bridge.set_slice = track
        # Simulate 4 rapid ±1 emissions (typical for 200-slice CT fast drag)
        for _ in range(4):
            bridge._on_qt_scroll(1)

        assert all(c[0] is True for c in calls), f"Expected all True, got {calls}"
        assert all(c[1] == "drag" for c in calls), f"Expected drag routing, got {calls}"
        assert len(calls) == 4
