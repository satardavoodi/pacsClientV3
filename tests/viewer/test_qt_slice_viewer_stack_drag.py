from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from modules.viewer.fast.qt_slice_viewer import QtSliceViewer


_app = QApplication.instance() or QApplication(sys.argv)


class TestQtSliceViewerStackDrag:
    def test_zoom_to_fit_respects_anisotropic_pixel_spacing(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)

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

    def test_stack_profile_distinguishes_20_100_250_slice_stacks(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")

        viewer.set_total_slices_hint(20)
        t20, c20 = viewer._get_stack_drag_profile()

        viewer.set_total_slices_hint(100)
        t100, c100 = viewer._get_stack_drag_profile()

        viewer.set_total_slices_hint(250)
        t250, c250 = viewer._get_stack_drag_profile()

        assert t20 > t100 > t250
        # n=20 and n=100 both use cap=1 (n<150); n=250 uses cap=2 (n>=150)
        assert c20 <= c100 < c250

    def test_medium_large_stack_caps_per_event_burst_more_tightly(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(100)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert threshold > 1.0
        # n=100 < 150 -> max_per_event=1 (deliberate; only n>=150 allows cap=2)
        assert max_steps == 1

    def test_136_slice_stack_uses_two_step_cap(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(136)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert threshold > 1.0
        # n=136 < 150 -> max_per_event=1 (velocity gain provides smooth acceleration)
        assert max_steps == 1

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
        # n=240 >= 150 -> max_per_event=2 (hard burst cap keeps drag feeling controlled)
        assert max_steps == 2

    def test_large_stack_fast_drag_velocity_gain_applies(self):
        """At high velocity on a large stack, the gain amplifies the move and
        the hard burst cap (max_per_event=2 for n>=150) keeps it from exceeding 2."""
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(200)
        threshold, _ = viewer._get_stack_drag_profile()

        # n=200 (150<=n<250): gain_max=2.0, max_per_event=2.
        # threshold * 4.0 with gain at high speed gives steps >> 2 -> cap fires -> emit=2.
        assert viewer._consume_stack_drag_delta(threshold * 4.0, speed_px_per_sec=threshold * 90.0) == 2
        assert viewer._stacked_accum == 0.0

    def test_very_fast_drag_hits_max_per_event_cap(self):
        """Even at maximum velocity the hard burst cap (max_per_event=2 for n<250)
        prevents more than 2 slices per event, keeping drag smooth and controlled."""
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(220)
        threshold, _ = viewer._get_stack_drag_profile()

        # n=220 (150<=n<250): max_per_event=2; no skip lane regardless of speed.
        assert viewer._consume_stack_drag_delta(threshold * 4.0, speed_px_per_sec=threshold * 130.0) == 2
        assert viewer._stacked_accum == 0.0


    def test_large_stack_slow_drag_keeps_single_slice_precision(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(200)
        threshold, _ = viewer._get_stack_drag_profile()

        viewer._stacked_first_step_pending = True

        assert viewer._consume_stack_drag_delta(threshold * 0.7, speed_px_per_sec=threshold * 5.0) == 1

    def test_medium_stack_does_not_exceed_single_step_cap(self):
        """n=80 is below the n>=150 threshold for cap=2, so max_per_event stays 1
        regardless of drag velocity."""
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(80)
        threshold, max_steps = viewer._get_stack_drag_profile()

        # n=80 < 150 -> cap=1; high velocity still capped at 1.
        assert max_steps == 1
        assert viewer._consume_stack_drag_delta(threshold * 4.0, speed_px_per_sec=threshold * 90.0) == 1
        assert viewer._stacked_accum == 0.0

    def test_small_stack_full_drag_remains_deliberate(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(20)

        threshold, max_steps = viewer._get_stack_drag_profile()
        estimated_full_drag_steps = int(512.0 / float(threshold))

        assert max_steps == 1
        assert estimated_full_drag_steps <= 32

    def test_stack_profile_uses_full_viewer_height(self):
        viewer = QtSliceViewer()
        viewer.set_stack_drag_policy("adaptive")

        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))
        viewer.set_total_slices_hint(60)

        viewer.resize(256, 256)
        tall_threshold, _ = viewer._get_stack_drag_profile()

        viewer.resize(128, 128)
        short_threshold, _ = viewer._get_stack_drag_profile()

        assert tall_threshold > short_threshold

    def test_stack_profile_is_independent_of_image_zoomed_height(self):
        viewer = QtSliceViewer()
        viewer.resize(256, 256)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))
        viewer.set_total_slices_hint(60)

        viewer.set_zoom(0.5)
        threshold_small_zoom, _ = viewer._get_stack_drag_profile()

        viewer.set_zoom(3.0)
        threshold_large_zoom, _ = viewer._get_stack_drag_profile()

        assert threshold_small_zoom == threshold_large_zoom

    def test_stack_drag_stays_active_inside_layout_even_outside_image(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))

        emitted: list[int] = []
        viewer.stack_drag_target_requested.connect(lambda target: emitted.append(target))
        viewer.set_current_slice_index(20)

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
            QPointF(480, 340),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseMoveEvent(move)

        assert viewer._stacked_dragging is True
        assert emitted

    def test_consume_stack_drag_delta_uses_threshold(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(20)
        threshold, max_steps = viewer._get_stack_drag_profile()

        assert max_steps == 1
        assert viewer._consume_stack_drag_delta(threshold - 0.5, speed_px_per_sec=0.0) == 0
        assert viewer._consume_stack_drag_delta(1.0, speed_px_per_sec=0.0) == 1
        # remainder should be preserved, not discarded
        assert viewer._stacked_accum > 0.0

    def test_consume_stack_drag_delta_caps_large_event(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        threshold, max_steps = viewer._get_stack_drag_profile()

        assert viewer._consume_stack_drag_delta(threshold * (max_steps + 5), speed_px_per_sec=0.0) == max_steps
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

        # n=136 < 150 -> max_per_event=1; first-step fires at 65% of px_per_slice.
        assert max_steps == 1
        assert viewer._consume_stack_drag_delta(threshold * 0.7, speed_px_per_sec=threshold * 5.0) == 1
        assert viewer._stacked_first_step_pending is False
        assert viewer._stacked_accum == 0.0

    def test_after_first_drag_step_regular_threshold_is_restored(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(136)
        threshold, _ = viewer._get_stack_drag_profile()

        viewer._stacked_first_step_pending = True
        assert viewer._consume_stack_drag_delta(threshold * 0.7, speed_px_per_sec=threshold * 5.0) == 1

        assert viewer._consume_stack_drag_delta(threshold * 0.7, speed_px_per_sec=threshold * 5.0) == 0
        assert viewer._stacked_accum > 0.0

    def test_reversal_clears_pending_drag_backlog_immediately(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        threshold, _ = viewer._get_stack_drag_profile()

        viewer._stacked_accum = threshold * 0.9

        assert viewer._consume_stack_drag_delta(-threshold * 1.1, speed_px_per_sec=threshold * 5.0) == -1
        assert viewer._stacked_accum < 0.0

    def test_slice_count_growth_does_not_reinterpret_active_drag_session(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(80)
        threshold, _ = viewer._get_stack_drag_profile()
        viewer._stacked_dragging = True
        viewer._begin_stack_drag_session()
        viewer._stacked_accum = threshold * 0.8
        session_threshold, session_max_steps, _ = viewer._get_active_stack_drag_profile()

        viewer.set_total_slices_hint(120)

        new_threshold, _ = viewer._get_stack_drag_profile()

        assert viewer._stacked_accum == threshold * 0.8
        assert session_threshold != new_threshold
        assert viewer._get_active_stack_drag_profile()[:2] == (session_threshold, session_max_steps)

    def test_new_drag_session_uses_latest_hint_after_previous_drag_stops(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(80)

        viewer._begin_stack_drag_session()
        first_threshold, first_max_steps, _ = viewer._get_active_stack_drag_profile()

        viewer.set_total_slices_hint(120)
        viewer._end_stack_drag_session()
        viewer._begin_stack_drag_session()
        second_threshold, second_max_steps, _ = viewer._get_active_stack_drag_profile()

        assert (first_threshold, first_max_steps) != (second_threshold, second_max_steps)
        assert (second_threshold, second_max_steps) == viewer._get_active_stack_drag_profile()[:2]

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

        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))

        emitted: list[int] = []
        stopped: list[bool] = []
        viewer.stack_drag_target_requested.connect(lambda target: emitted.append(target))
        viewer.stack_drag_state_changed.connect(lambda active: stopped.append(active))
        viewer.set_current_slice_index(20)

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
        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))
        threshold, max_steps = viewer._get_stack_drag_profile()

        emitted: list[int] = []
        viewer.stack_drag_target_requested.connect(lambda target: emitted.append(target))

        viewer.set_current_slice_index(20)

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
        assert emitted[0] > 20

    def test_adaptive_stack_drag_uses_bounded_incremental_targets(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))
        threshold, _max_steps = viewer._get_stack_drag_profile()

        emitted: list[int] = []
        viewer.stack_drag_target_requested.connect(lambda target: emitted.append(target))
        viewer.set_current_slice_index(50)

        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(256, 256),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mousePressEvent(press)

        first_move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(256, 256 + int(round(threshold * 2.2))),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseMoveEvent(first_move)

        same_target_move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(256, 256 + int(round(threshold * 2.35))),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseMoveEvent(same_target_move)

        assert emitted == [51]

    def test_adaptive_stack_drag_caps_large_followup_move_to_profile_limit(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))
        threshold, max_steps = viewer._get_stack_drag_profile()

        emitted: list[int] = []
        viewer.stack_drag_target_requested.connect(lambda target: emitted.append(target))
        viewer.set_current_slice_index(50)

        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(256, 256),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mousePressEvent(press)

        first_move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(256, 256 + int(round(threshold * 0.8))),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseMoveEvent(first_move)

        laggy_followup_move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(256, 256 + int(round(threshold * (max_steps + 6.0)))),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseMoveEvent(laggy_followup_move)

        assert emitted == [51, 51 + max_steps]

    def test_absolute_stack_drag_clamps_target_to_valid_range(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        viewer.set_image(QImage(128, 128, QImage.Format.Format_Grayscale8))
        threshold, _max_steps = viewer._get_stack_drag_profile()

        emitted: list[int] = []
        viewer.stack_drag_target_requested.connect(lambda target: emitted.append(target))
        viewer.set_current_slice_index(118)

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
            QPointF(256, 256 + int(round(threshold * 4.0))),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        viewer.mouseMoveEvent(move)

        assert emitted[-1] == 119

    def test_clearcanvas_policy_emits_single_step_per_nonzero_move(self, monkeypatch):
        monkeypatch.setenv("AIPACS_STACK_DRAG_POLICY", "clearcanvas")

        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_total_slices_hint(500)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert threshold == 1.0
        assert max_steps == 1
        assert viewer._consume_stack_drag_delta(0.25, speed_px_per_sec=0.0) == 1
        assert viewer._consume_stack_drag_delta(-0.25, speed_px_per_sec=0.0) == -1
        assert viewer._consume_stack_drag_delta(0.0, speed_px_per_sec=0.0) == 0

    def test_unknown_stack_drag_policy_falls_back_to_adaptive(self, monkeypatch):
        monkeypatch.setenv("AIPACS_STACK_DRAG_POLICY", "mystery-soup")

        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_total_slices_hint(120)

        threshold, max_steps = viewer._get_stack_drag_profile()

        assert threshold > 1.0
        # Verifies the policy falls back to adaptive (not ClearCanvas) - cap value varies by n.
        assert max_steps >= 1

    def test_full_viewport_drag_traverses_all_slices_design_invariant(self):
        """Full viewport drag at gain=1.0 must traverse all n slices.

        Design invariant: px_per_slice = viewer_h / n, so (viewer_h / px_per_slice) == n.
        This guarantees a deliberate top-to-bottom drag always covers the full stack,
        regardless of series size or viewer dimensions.
        """
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")

        for n in (20, 60, 100, 136, 200, 264, 500):
            viewer.set_total_slices_hint(n)
            threshold, _ = viewer._get_stack_drag_profile()  # returns px_per_slice
            estimated_full_drag_steps = int(512.0 / float(threshold))
            # At gain=1.0, full viewport drag should cover all n slices.
            assert estimated_full_drag_steps >= n - 1, (
                f"n={n}: full drag covers only {estimated_full_drag_steps} slices (expected >= {n - 1})"
            )

        # Larger n -> smaller px_per_slice (more responsive threshold).
        viewer.set_total_slices_hint(100)
        t100, _ = viewer._get_stack_drag_profile()
        viewer.set_total_slices_hint(264)
        t264, _ = viewer._get_stack_drag_profile()
        assert t264 < t100
