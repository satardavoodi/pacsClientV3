"""Impatient-user stacking + drag-drop driven through the CODE-BASE, no mouse.

Why (2026-06-14): computer-use synthetic mouse wheel/drag does NOT reach the FAST
viewer (a live scroll logged `total_events=0`), so the impatient-user "aggressive
scroll" and "drag a series into a viewport" flows can't be tested via the OS mouse.
The viewer exposes no-mouse entry points that the wheel/drop handlers call
internally — this test drives THOSE directly:

  Stacking  : pipeline.set_slice_index(i)  /  bridge.set_slice(i)
              + the slider-drag session  bridge.begin_slider_drag() ->
              handle_slider_drag_target(i) -> end_slider_drag()
  Drag-drop : series replacement in the viewport (the effect of
              qt_fast_container.switch_series / dropEvent) via
              pipeline.close_series() + open_series(other)

Verifies the impatient-user acceptance criteria: aggressive stacking is bounded
and crash-free, and a drop replaces the viewport CLEANLY (new slice range, index
reset, no residue of the previous series).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AIPACS_NO_TAKEOVER", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from tests.code.performance.perf_helpers import make_dicom_series_on_disk  # noqa: E402
from modules.viewer.fast.lightweight_2d_pipeline import (  # noqa: E402
    Lightweight2DPipeline,
    PipelineConfig,
)
from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge  # noqa: E402
from modules.viewer.fast.qt_slice_viewer import QtSliceViewer  # noqa: E402


def _series(tmp, name, n, rows=64, cols=64):
    p = Path(tmp) / name
    make_dicom_series_on_disk(p, n=n, rows=rows, cols=cols)
    return str(p)


def _pipeline():
    return Lightweight2DPipeline(config=PipelineConfig(
        pixel_cache_size=32, frame_cache_size=32, prefetch_radius=2, prefetch_workers=1))


def _bridge(pipeline, n):
    md = {"series": {"series_number": 1, "modality": "CT", "image_count": n}, "instances": []}
    return QtViewerBridge(QtSliceViewer(), pipeline, md)


def test_aggressive_stacking_via_pipeline_no_mouse():
    """Rapid forward+backward slice stepping (pipeline level) tracks exactly."""
    with tempfile.TemporaryDirectory() as td:
        p = _pipeline()
        p.open_series(_series(td, "A", 24))
        try:
            assert p.slice_count == 24 and p.is_open
            order = list(range(24)) + list(range(23, -1, -1)) + [0, 23, 5, 18, 0]
            for i in order:
                assert p.set_slice_index(i) in (True, False)  # never raises
                assert p.current_index == i, f"slice did not follow to {i}"
        finally:
            p.close_series()


def test_stacking_out_of_bounds_is_clamped_no_mouse():
    """Impatient over-scroll past the ends is clamped, never crashes/blanks."""
    with tempfile.TemporaryDirectory() as td:
        p = _pipeline()
        p.open_series(_series(td, "A", 16))
        try:
            p.set_slice_index(-50)
            assert p.current_index == 0
            p.set_slice_index(9999)
            assert p.current_index == 15
        finally:
            p.close_series()


def test_stacking_via_bridge_set_slice_no_mouse():
    """The bridge.set_slice path (what the wheel handler calls) never raises."""
    with tempfile.TemporaryDirectory() as td:
        p = _pipeline()
        p.open_series(_series(td, "A", 20))
        try:
            b = _bridge(p, 20)
            for i in list(range(0, 20, 2)) + list(range(19, -1, -3)):
                b.set_slice(i)  # must not raise
            # out-of-range through the bridge is also safe
            b.set_slice(-3)
            b.set_slice(999)
        finally:
            p.close_series()


def test_stacking_via_slider_drag_session_no_mouse():
    """The bridge's no-mouse drag API: begin -> handle_target* -> end."""
    with tempfile.TemporaryDirectory() as td:
        p = _pipeline()
        p.open_series(_series(td, "A", 30))
        try:
            b = _bridge(p, 30)
            b.set_slice(0)
            b.begin_slider_drag()
            for i in [0, 6, 12, 18, 24, 29, 18, 6, 0, 29]:  # aggressive back-and-forth
                b.handle_slider_drag_target(i)
            b.end_slider_drag()
            # drag session must clean up (no stuck protected-drag state)
            assert getattr(b, "_stack_drag_active", False) in (False, 0)
        finally:
            p.close_series()


def test_dragdrop_replaces_viewport_cleanly_no_mouse():
    """Dropping series B over A replaces the viewport: new range, index reset,
    no residue of A. Then re-dropping A restores A's range."""
    with tempfile.TemporaryDirectory() as td:
        a = _series(td, "A", 20, 64, 64)
        bs = _series(td, "B", 12, 48, 48)
        p = _pipeline()
        p.open_series(a)
        try:
            p.set_slice_index(15)
            assert p.current_index == 15 and p.slice_count == 20

            # ── "drop" series B into the same viewport (code-base equivalent of
            #     a drag-drop: qt_fast_container.switch_series / dropEvent) ──
            p.close_series()
            p.open_series(bs)
            assert p.slice_count == 12, "viewport must reflect dropped B (12), not A (20)"
            assert p.current_index == 0, "slice index must reset on replacement (no A residue)"
            p.set_slice_index(11)
            assert p.current_index == 11            # B's last slice
            p.set_slice_index(15)
            assert p.current_index == 11, "must clamp to B's range; A's slice 15 is gone"

            # ── re-drop A: viewport switches back cleanly ──
            p.close_series()
            p.open_series(a)
            assert p.slice_count == 20 and p.current_index == 0
        finally:
            p.close_series()


def test_repeated_same_series_drop_is_idempotent_no_mouse():
    """Dropping the SAME series again (impatient repeat) stays consistent."""
    with tempfile.TemporaryDirectory() as td:
        a = _series(td, "A", 18)
        p = _pipeline()
        p.open_series(a)
        try:
            p.set_slice_index(9)
            for _ in range(3):  # re-drop the same series repeatedly
                p.close_series()
                p.open_series(a)
                assert p.slice_count == 18
                assert p.current_index == 0
        finally:
            p.close_series()
