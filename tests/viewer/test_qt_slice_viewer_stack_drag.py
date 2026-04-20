from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from modules.viewer.fast.qt_slice_viewer import QtSliceViewer


_app = QApplication.instance() or QApplication(sys.argv)


class TestQtSliceViewerStackDrag:
    def test_zoom_to_fit_respects_anisotropic_pixel_spacing(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        from PySide6.QtGui import QImage

        viewer.set_image(QImage(256, 256, QImage.Format.Format_Grayscale8))
        isotropic_zoom = viewer.zoom_to_fit()

        viewer.set_pixel_spacing((3.5, 1.0))
        anisotropic_zoom = viewer.zoom_to_fit()

        assert anisotropic_zoom < isotropic_zoom
        assert viewer._display_scale_y == 3.5
        assert viewer._display_scale_x == 1.0

    def test_default_policy_is_slice_adaptive(self, monkeypatch):
        monkeypatch.delenv("AIPACS_STACK_DRAG_POLICY", raising=False)

        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_total_slices_hint(200)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert viewer._stack_drag_policy == viewer.STACK_DRAG_POLICY_ADAPTIVE
        assert threshold > 1.0
        assert max_steps >= 2

    def test_default_left_drag_uses_scroll_suppression_window(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_total_slices_hint(120)
        from PySide6.QtGui import QImage

        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))

        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(256, 256),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mousePressEvent(press)

        assert viewer._in_wheel_scroll is True

        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(256, 256),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseReleaseEvent(release)

        assert viewer._scroll_stop_timer.isActive()
        assert viewer._in_wheel_scroll is True

        viewer._on_scroll_stopped()

        assert viewer._in_wheel_scroll is False

    def test_stack_profile_gets_more_sensitive_for_larger_stacks(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")

        viewer.set_total_slices_hint(20)
        small_threshold, small_cap = viewer._get_stack_drag_profile()

        viewer.set_total_slices_hint(500)
        large_threshold, large_cap = viewer._get_stack_drag_profile()

        assert large_threshold < small_threshold
        assert large_cap >= small_cap

    def test_stack_profile_distinguishes_20_100_200_slice_stacks(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")

        viewer.set_total_slices_hint(20)
        t20, c20 = viewer._get_stack_drag_profile()

        viewer.set_total_slices_hint(100)
        t100, c100 = viewer._get_stack_drag_profile()

        viewer.set_total_slices_hint(200)
        t200, c200 = viewer._get_stack_drag_profile()

        assert t20 > t100 > t200
        assert c20 < c100 < c200

    def test_medium_large_stack_caps_per_event_burst_more_tightly(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(100)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert threshold > 1.0
        assert max_steps == 2

    def test_136_slice_stack_uses_two_step_cap(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(136)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert threshold > 1.0
        assert max_steps == 2

    def test_large_stack_full_drag_covers_meaningful_span(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)

        threshold, _ = viewer._get_stack_drag_profile()
        estimated_full_drag_steps = int(512.0 / float(threshold))

        assert estimated_full_drag_steps >= 40

    def test_very_large_stack_caps_per_event_burst_for_smoother_drag(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(240)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert threshold > 1.0
        assert max_steps == 3

    def test_small_stack_full_drag_remains_deliberate(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(20)

        threshold, max_steps = viewer._get_stack_drag_profile()
        estimated_full_drag_steps = int(512.0 / float(threshold))

        assert max_steps == 1
        assert estimated_full_drag_steps <= 32

    def test_stack_profile_uses_visible_height(self):
        viewer = QtSliceViewer()
        viewer.set_stack_drag_policy("adaptive")
        from PySide6.QtGui import QImage

        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))
        viewer.set_zoom(2.0)
        viewer.set_total_slices_hint(60)

        viewer.resize(256, 256)
        tall_threshold, _ = viewer._get_stack_drag_profile()

        viewer.resize(128, 128)
        short_threshold, _ = viewer._get_stack_drag_profile()

        assert tall_threshold > short_threshold

    def test_consume_stack_drag_delta_uses_threshold(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(20)
        threshold, max_steps = viewer._get_stack_drag_profile()

        assert max_steps == 1
        assert viewer._consume_stack_drag_delta(threshold - 0.5) == 0
        assert viewer._consume_stack_drag_delta(1.0) == 1
        # remainder should be preserved, not discarded
        assert viewer._stacked_accum > 0.0

    def test_consume_stack_drag_delta_caps_large_event(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        threshold, max_steps = viewer._get_stack_drag_profile()

        assert viewer._consume_stack_drag_delta(threshold * (max_steps + 5)) == max_steps
        # Only the sub-threshold tail may remain; capped overflow must not
        # create momentum for later mouse moves.
        assert 0.0 <= abs(viewer._stacked_accum) < threshold

    def test_first_drag_step_uses_smaller_start_threshold_without_burst(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(136)
        threshold, max_steps = viewer._get_stack_drag_profile()

        viewer._stacked_first_step_pending = True

        assert max_steps == 2
        assert viewer._consume_stack_drag_delta(threshold * 0.7) == 1
        assert viewer._stacked_first_step_pending is False
        assert viewer._stacked_accum == 0.0

    def test_after_first_drag_step_regular_threshold_is_restored(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(136)
        threshold, _ = viewer._get_stack_drag_profile()

        viewer._stacked_first_step_pending = True
        assert viewer._consume_stack_drag_delta(threshold * 0.7) == 1

        assert viewer._consume_stack_drag_delta(threshold * 0.7) == 0
        assert viewer._stacked_accum > 0.0

    def test_reversal_clears_pending_drag_backlog_immediately(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        threshold, _ = viewer._get_stack_drag_profile()

        viewer._stacked_accum = threshold * 0.9

        assert viewer._consume_stack_drag_delta(-threshold * 1.1) == -1
        assert viewer._stacked_accum < 0.0

    def test_slice_count_growth_preserves_partial_drag_progress(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(80)
        threshold, _ = viewer._get_stack_drag_profile()
        viewer._stacked_dragging = True
        viewer._stacked_accum = threshold * 0.8

        viewer.set_total_slices_hint(120)

        new_threshold, _ = viewer._get_stack_drag_profile()

        assert 0.0 < viewer._stacked_accum < new_threshold

    def test_slice_count_shrink_clears_pending_drag_accum(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        threshold, _ = viewer._get_stack_drag_profile()
        viewer._stacked_dragging = True
        viewer._stacked_accum = threshold * 0.8

        viewer.set_total_slices_hint(80)

        assert viewer._stacked_accum == 0.0

    def test_stack_drag_allows_small_leave_from_image_edge(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        from PySide6.QtGui import QImage

        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))

        emitted: list[int] = []
        stopped: list[bool] = []
        viewer.slice_scroll_requested.connect(lambda delta: emitted.append(delta))
        viewer.stack_drag_state_changed.connect(lambda active: stopped.append(active))

        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(256, 256),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mousePressEvent(press)

        move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(256, 325),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseMoveEvent(move)

        assert viewer._stacked_dragging is True
        assert emitted
        assert stopped == [True]

    def test_default_left_drag_starts_with_single_bounded_step(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        from PySide6.QtGui import QImage
        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))
        threshold, max_steps = viewer._get_stack_drag_profile()

        emitted: list[int] = []
        viewer.slice_scroll_requested.connect(lambda delta: emitted.append(delta))

        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(256, 256),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mousePressEvent(press)

        move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(256, 256 + int(round(threshold * (max_steps + 5)))),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseMoveEvent(move)

        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(256, 256 + int(round(threshold * (max_steps + 5)))),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseReleaseEvent(release)

        assert len(emitted) == 1
        assert emitted == [1]

    def test_clearcanvas_policy_emits_single_step_per_nonzero_move(self, monkeypatch):
        monkeypatch.setenv("AIPACS_STACK_DRAG_POLICY", "clearcanvas")

        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_total_slices_hint(500)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert threshold == 1.0
        assert max_steps == 1
        assert viewer._consume_stack_drag_delta(0.25) == 1
        assert viewer._consume_stack_drag_delta(-0.25) == -1
        assert viewer._consume_stack_drag_delta(0.0) == 0

    def test_unknown_stack_drag_policy_falls_back_to_adaptive(self, monkeypatch):
        monkeypatch.setenv("AIPACS_STACK_DRAG_POLICY", "mystery-soup")

        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_total_slices_hint(120)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert threshold > 1.0
        assert max_steps > 1
