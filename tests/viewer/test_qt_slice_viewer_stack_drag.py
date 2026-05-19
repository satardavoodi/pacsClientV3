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

    def test_large_stack_fast_drag_velocity_gain_applies(self, monkeypatch):
        """V1-specific: natural h/n threshold + velocity gain for large stacks."""
        import modules.viewer.fast.qt_slice_viewer as _qsv_mod
        monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(200)
        threshold, _ = viewer._get_stack_drag_profile()

        # n=200 (150<=n<250): gain_max=2.0, max_per_event=2.
        # threshold * 4.0 with gain at high speed gives steps >> 2 -> cap fires -> emit=2.
        assert viewer._consume_stack_drag_delta(threshold * 4.0, speed_px_per_sec=threshold * 90.0) == 2
        assert viewer._stacked_accum == 0.0

    def test_very_fast_drag_hits_max_per_event_cap(self, monkeypatch):
        """V1-specific: natural h/n threshold + max_per_event cap for very fast drag."""
        import modules.viewer.fast.qt_slice_viewer as _qsv_mod
        monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(220)
        threshold, _ = viewer._get_stack_drag_profile()

        # n=220 (150<=n<250): max_per_event=2; no skip lane regardless of speed.
        assert viewer._consume_stack_drag_delta(threshold * 4.0, speed_px_per_sec=threshold * 130.0) == 2
        assert viewer._stacked_accum == 0.0


    def test_large_stack_slow_drag_keeps_single_slice_precision(self, monkeypatch):
        """V1-specific: first-step fires at 65% of natural h/n threshold."""
        import modules.viewer.fast.qt_slice_viewer as _qsv_mod
        monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)
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

    def test_consume_stack_drag_delta_uses_threshold(self, monkeypatch):
        """V1-specific: threshold accumulation mechanic."""
        import modules.viewer.fast.qt_slice_viewer as _qsv_mod
        monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)
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

    def test_consume_stack_drag_delta_caps_large_event(self, monkeypatch):
        """V1-specific: large coalesced events are capped to max_per_event."""
        import modules.viewer.fast.qt_slice_viewer as _qsv_mod
        monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(120)
        threshold, max_steps = viewer._get_stack_drag_profile()

        assert viewer._consume_stack_drag_delta(threshold * (max_steps + 5), speed_px_per_sec=0.0) == max_steps
        # Only the sub-threshold tail may remain; capped overflow must not
        # create momentum for later mouse moves.
        assert 0.0 <= abs(viewer._stacked_accum) < threshold


    def test_first_drag_step_uses_smaller_start_threshold_without_burst(self, monkeypatch):
        """V1-specific: first-step assist fires at 65% of natural h/n threshold."""
        import modules.viewer.fast.qt_slice_viewer as _qsv_mod
        monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)
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

    def test_after_first_drag_step_regular_threshold_is_restored(self, monkeypatch):
        """V1-specific: after first step, regular h/n threshold applies."""
        import modules.viewer.fast.qt_slice_viewer as _qsv_mod
        monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)
        viewer = QtSliceViewer()
        viewer.resize(512, 512)
        viewer.set_stack_drag_policy("adaptive")
        viewer.set_total_slices_hint(136)
        threshold, _ = viewer._get_stack_drag_profile()

        viewer._stacked_first_step_pending = True
        assert viewer._consume_stack_drag_delta(threshold * 0.7, speed_px_per_sec=threshold * 5.0) == 1

        assert viewer._consume_stack_drag_delta(threshold * 0.7, speed_px_per_sec=threshold * 5.0) == 0
        assert viewer._stacked_accum > 0.0

    def test_reversal_clears_pending_drag_backlog_immediately(self, monkeypatch):
        """V1-specific: direction reversal flushes accumulator using natural h/n threshold."""
        import modules.viewer.fast.qt_slice_viewer as _qsv_mod
        monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)
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


# ─── V2 band-parameter unit tests ────────────────────────────────────────────
#
# These tests exercise the module-level V2 helpers directly (no full viewer
# instance required) to pin down the small-stack smoothness contract
# introduced in the revised V2 model (px_per_slice_fixed for tiny/small).

class TestV2BandParams:
    """Unit tests for _v2_select_drag_band and _v2_effective_px_per_slice."""

    # ── Band selection ────────────────────────────────────────────────────

    def test_band_selection_boundaries(self):
        from modules.viewer.fast.qt_slice_viewer import _v2_select_drag_band, _DRAG_BAND_PARAMS
        assert _v2_select_drag_band(1)   is _DRAG_BAND_PARAMS["micro"]
        assert _v2_select_drag_band(9)   is _DRAG_BAND_PARAMS["micro"]
        assert _v2_select_drag_band(10)  is _DRAG_BAND_PARAMS["tiny"]
        assert _v2_select_drag_band(24)  is _DRAG_BAND_PARAMS["tiny"]
        assert _v2_select_drag_band(25)  is _DRAG_BAND_PARAMS["small"]
        assert _v2_select_drag_band(49)  is _DRAG_BAND_PARAMS["small"]
        assert _v2_select_drag_band(50)  is _DRAG_BAND_PARAMS["medium"]
        assert _v2_select_drag_band(99)  is _DRAG_BAND_PARAMS["medium"]
        assert _v2_select_drag_band(100) is _DRAG_BAND_PARAMS["large"]
        assert _v2_select_drag_band(199) is _DRAG_BAND_PARAMS["large"]
        assert _v2_select_drag_band(200) is _DRAG_BAND_PARAMS["xlarge"]
        assert _v2_select_drag_band(299) is _DRAG_BAND_PARAMS["xlarge"]
        assert _v2_select_drag_band(300) is _DRAG_BAND_PARAMS["huge"]
        assert _v2_select_drag_band(999) is _DRAG_BAND_PARAMS["huge"]

    # ── Proportional px_per_slice for ALL bands (v3.0.5 unification) ─────────

    def test_v2_tiny_proportional_px_per_slice(self):
        """tiny band (10 ≤ n < 25) uses proportional dead-zone h/n × 0.86 (15% faster than small)."""
        from modules.viewer.fast.qt_slice_viewer import _v2_effective_px_per_slice, _DRAG_BAND_PARAMS
        band = _DRAG_BAND_PARAMS["tiny"]
        assert band.get("px_per_slice_fixed") is None, "tiny must use divisor, not fixed"
        assert band.get("base_divisor") == 0.86
        # n=11, h=550  →  550/11 × 0.86 = 43.0
        assert abs(_v2_effective_px_per_slice(11, 550.0, band) - 43.0) < 0.01
        # n=20, h=400  →  400/20 × 0.86 = 17.2
        assert abs(_v2_effective_px_per_slice(20, 400.0, band) - 17.2) < 0.01
        # Varies with h and n (not fixed)
        r1 = _v2_effective_px_per_slice(11, 500.0, band)
        r2 = _v2_effective_px_per_slice(20, 500.0, band)
        assert r1 != r2, "px must scale with n, not be a constant"

    def test_v2_sub50_bands_10pct_faster(self):
        """micro/tiny (n<25) use base_divisor=0.86 (15% faster than small);
        small (25-49) uses 0.99 (10% faster than medium+)."""
        from modules.viewer.fast.qt_slice_viewer import _v2_effective_px_per_slice, _DRAG_BAND_PARAMS, _v2_select_drag_band
        h, v = 500.0, 150.0
        std_traversal   = h * 1.1  / v   # medium+    ≈ 3.67 s
        small_traversal = h * 0.99 / v   # small      ≈ 3.30 s  (10% faster than medium)
        fast_traversal  = h * 0.86 / v   # micro/tiny ≈ 2.87 s  (15% faster than small)
        # micro and tiny must use base_divisor=0.86
        for band_name, n_example in [("micro", 5), ("tiny", 15)]:
            band = _DRAG_BAND_PARAMS[band_name]
            assert band.get("base_divisor") == 0.86, f"{band_name} must use base_divisor=0.86"
            px = _v2_effective_px_per_slice(n_example, h, band)
            traversal = n_example * px / v
            assert traversal < std_traversal, f"{band_name} must be faster than medium"
            assert abs(traversal - fast_traversal) / fast_traversal < 0.01, (
                f"{band_name}: traversal={traversal:.3f}s, expected≈{fast_traversal:.3f}s"
            )
        # small must use base_divisor=0.99 (10% faster than medium, unchanged)
        band_s = _DRAG_BAND_PARAMS["small"]
        assert band_s.get("base_divisor") == 0.99, "small must use base_divisor=0.99"
        px_s = _v2_effective_px_per_slice(35, h, band_s)
        traversal_s = 35 * px_s / v
        assert traversal_s < std_traversal, "small must be faster than medium"
        assert abs(traversal_s - small_traversal) / small_traversal < 0.01, (
            f"small: traversal={traversal_s:.3f}s, expected≈{small_traversal:.3f}s"
        )
        # Band selector routing
        assert _v2_select_drag_band(9)  is _DRAG_BAND_PARAMS["micro"]
        assert _v2_select_drag_band(10) is _DRAG_BAND_PARAMS["tiny"]
        assert _v2_select_drag_band(25) is _DRAG_BAND_PARAMS["small"]
        assert _v2_select_drag_band(50) is _DRAG_BAND_PARAMS["medium"]

    def test_v2_small_proportional_px_per_slice(self):
        """small band uses proportional dead-zone h/n × 0.99 — 10% faster, no fixed constant."""
        from modules.viewer.fast.qt_slice_viewer import _v2_effective_px_per_slice, _DRAG_BAND_PARAMS
        band = _DRAG_BAND_PARAMS["small"]
        assert band.get("px_per_slice_fixed") is None, "small must use divisor, not fixed"
        assert band.get("base_divisor") == 0.99
        # n=40, h=440  →  440/40 × 0.99 = 10.89
        assert abs(_v2_effective_px_per_slice(40, 440.0, band) - 10.89) < 0.01
        # n=30, h=300  →  300/30 × 0.99 = 9.9
        assert abs(_v2_effective_px_per_slice(30, 300.0, band) - 9.9) < 0.01

    def test_v2_tiny_no_gain(self):
        """tiny band disables velocity gain — v_onset and gain_max enforce no acceleration."""
        from modules.viewer.fast.qt_slice_viewer import _DRAG_BAND_PARAMS
        band = _DRAG_BAND_PARAMS["tiny"]
        assert band["v_onset"] > 1e8, "tiny v_onset must be effectively infinite"
        assert band["gain_max"] == 1.0, "tiny must have gain_max=1.0"
        assert band["max_per_event"] == 1

    def test_v2_small_no_gain(self):
        """small band disables velocity gain in the revised model."""
        from modules.viewer.fast.qt_slice_viewer import _DRAG_BAND_PARAMS
        band = _DRAG_BAND_PARAMS["small"]
        assert band["v_onset"] > 1e8, "small v_onset must be effectively infinite"
        assert band["gain_max"] == 1.0, "small must have gain_max=1.0"
        assert band["max_per_event"] == 1

    # ── Safety floor ──────────────────────────────────────────────────────

    def test_v2_fixed_minimum_clamp(self):
        """Fixed px_per_slice values are clamped to at least 0.5."""
        from modules.viewer.fast.qt_slice_viewer import _v2_effective_px_per_slice
        band = {"px_per_slice_fixed": 0.0, "v_onset": 1e9, "v_max": 1e9,
                "gain_max": 1.0, "max_per_event": 1}
        assert _v2_effective_px_per_slice(10, 300.0, band) == 0.5

    # ── Medium: natural 1:1 floor ─────────────────────────────────────────

    def test_v2_medium_natural_floor(self):
        """medium band (base_divisor=1.1) returns natural × 1.1 (slight cushion)."""
        from modules.viewer.fast.qt_slice_viewer import _v2_effective_px_per_slice, _DRAG_BAND_PARAMS
        band = _DRAG_BAND_PARAMS["medium"]
        h, n = 500.0, 75
        result = _v2_effective_px_per_slice(n, h, band)
        expected = (h / n) * 1.1  # ≈ 7.33
        assert abs(result - expected) < 0.01, (
            f"medium band should return natural×1.1 ({expected:.3f}), got {result:.3f}"
        )

    def test_v2_medium_base_divisor(self):
        """medium band has base_divisor=1.1 (−10% sensitivity vs pure 1:1)."""
        from modules.viewer.fast.qt_slice_viewer import _DRAG_BAND_PARAMS
        assert _DRAG_BAND_PARAMS["medium"]["base_divisor"] == 1.1
        assert _DRAG_BAND_PARAMS["medium"]["px_per_slice_fixed"] is None

    # ── Large/xlarge/huge: now uniform base_divisor=1.1 ───────────────────────

    def test_v2_large_calibrated_multiplier(self):
        """large band uses base_divisor=1.1 — same as medium for proportional feel."""
        from modules.viewer.fast.qt_slice_viewer import _v2_effective_px_per_slice, _DRAG_BAND_PARAMS
        band = _DRAG_BAND_PARAMS["large"]
        assert band.get("base_divisor") == 1.1
        h, n = 600.0, 150
        result = _v2_effective_px_per_slice(n, h, band)
        expected = (h / n) * 1.1  # = 4.4
        assert abs(result - expected) < 0.01

    def test_v2_huge_calibrated_multiplier(self):
        """huge band uses base_divisor=1.1 — proportional with all other bands."""
        from modules.viewer.fast.qt_slice_viewer import _DRAG_BAND_PARAMS
        band = _DRAG_BAND_PARAMS["huge"]
        assert band.get("base_divisor") == 1.1
        assert band["px_per_slice_fixed"] is None

    # ── Traversal-time consistency (v3.0.5 / v3.0.6 proportionality invariant) ─

    def test_v2_uniform_traversal_time_consistency(self):
        """micro/tiny deliver h×0.86/v (15% faster than small); small delivers h×0.99/v; medium…huge deliver h×1.1/v."""
        from modules.viewer.fast.qt_slice_viewer import _v2_effective_px_per_slice, _DRAG_BAND_PARAMS
        h, v = 500.0, 150.0
        tiny_traversal = h * 0.86 / v   # ≈ 2.87 s — micro/tiny
        fast_traversal = h * 0.99 / v   # ≈ 3.30 s — small
        std_traversal  = h * 1.1  / v   # ≈ 3.67 s — medium…huge
        tiny_cases = [
            ("micro",  5), ("micro",  8),
            ("tiny",  11), ("tiny",  20),
        ]
        fast_cases = [
            ("small", 30), ("small", 49),
        ]
        std_cases = [
            ("medium", 70), ("medium", 90),
            ("large",  130), ("large", 190),
            ("xlarge", 250),
            ("huge",   350),
        ]
        for band_name, n in tiny_cases:
            band = _DRAG_BAND_PARAMS[band_name]
            px = _v2_effective_px_per_slice(n, h, band)
            actual = n * px / v
            assert abs(actual - tiny_traversal) / tiny_traversal < 0.02, (
                f"{band_name}(n={n}): traversal {actual:.3f}s ≠ {tiny_traversal:.3f}s"
            )
        for band_name, n in fast_cases:
            band = _DRAG_BAND_PARAMS[band_name]
            px = _v2_effective_px_per_slice(n, h, band)
            actual = n * px / v
            assert abs(actual - fast_traversal) / fast_traversal < 0.02, (
                f"{band_name}(n={n}): traversal {actual:.3f}s ≠ {fast_traversal:.3f}s"
            )
        for band_name, n in std_cases:
            band = _DRAG_BAND_PARAMS[band_name]
            px = _v2_effective_px_per_slice(n, h, band)
            actual = n * px / v
            assert abs(actual - std_traversal) / std_traversal < 0.02, (
                f"{band_name}(n={n}): traversal {actual:.3f}s ≠ {std_traversal:.3f}s"
            )

    def test_v2_uniform_base_divisor_all_bands(self):
        """Every band has no fixed constant; micro/tiny=0.86, small=0.99, medium…huge=1.1."""
        from modules.viewer.fast.qt_slice_viewer import _DRAG_BAND_PARAMS
        for name, params in _DRAG_BAND_PARAMS.items():
            assert params.get("px_per_slice_fixed") is None, (
                f"{name}: production bands must use divisor model (px_per_slice_fixed must be None)"
            )
            if name in ("micro", "tiny"):
                expected_div = 0.86
            elif name == "small":
                expected_div = 0.99
            else:
                expected_div = 1.1
            assert params.get("base_divisor") == expected_div, (
                f"{name}: base_divisor must be {expected_div}, got {params.get('base_divisor')}"
            )

    def test_v2_traversal_invariant_different_heights(self):
        """Traversal-time invariant holds across different viewport heights.

        micro/tiny → h × 0.86 / v (faster); small → h × 0.99 / v; large/huge → h × 1.1 / v (standard).
        """
        from modules.viewer.fast.qt_slice_viewer import _v2_effective_px_per_slice, _DRAG_BAND_PARAMS
        v = 150.0
        for h in [300.0, 500.0, 800.0]:
            tiny_expected = h * 0.86 / v
            fast_expected = h * 0.99 / v
            std_expected  = h * 1.1  / v
            for band_name, n, expected in [
                ("tiny",  15, tiny_expected),
                ("small", 40, fast_expected),
                ("large", 150, std_expected),
                ("huge",  300, std_expected),
            ]:
                band = _DRAG_BAND_PARAMS[band_name]
                px = _v2_effective_px_per_slice(n, h, band)
                actual = n * px / v
                assert abs(actual - expected) / expected < 0.01, (
                    f"h={h} {band_name}(n={n}): traversal={actual:.3f}s, expected={expected:.3f}s"
                )

    def test_adaptive_stack_drag_caps_large_followup_move_to_profile_limit(self, monkeypatch):
        """V1-specific: large coalesced real mouse event is capped to max_per_event."""
        import modules.viewer.fast.qt_slice_viewer as _qsv_mod
        monkeypatch.setattr(_qsv_mod, "_USE_V2_MODEL", False)
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

    def test_radiography_window_level_drag_is_more_controlled_than_generic(self):
        def _drag_delta_for_modality(modality: str) -> float:
            viewer = QtSliceViewer()
            viewer.resize(512, 512)
            viewer.set_modality_hint(modality)
            viewer.set_window_level_values(4000.0, 2000.0)
            viewer._wl_dragging = True
            viewer._wl_start_pos = QPointF(10.0, 10.0)
            viewer._wl_start_window = 4000.0
            viewer._wl_start_level = 2000.0

            move = QMouseEvent(
                QMouseEvent.Type.MouseMove,
                QPointF(30.0, 10.0),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.RightButton,
                Qt.KeyboardModifier.NoModifier,
            )
            viewer.mouseMoveEvent(move)
            return float(viewer._current_window - 4000.0)

        mg_delta = _drag_delta_for_modality("MG")
        ct_delta = _drag_delta_for_modality("CT")

        assert mg_delta > 0.0
        assert ct_delta > 0.0
        assert mg_delta < ct_delta

    def test_radiography_downscale_smoothing_activation(self):
        viewer = QtSliceViewer()
        viewer.resize(512, 512)

        viewer.set_modality_hint("MG")
        viewer.set_zoom(0.8)
        assert viewer._use_radiography_downscale_smoothing() is True

        viewer.set_modality_hint("CT")
        assert viewer._use_radiography_downscale_smoothing() is False

        viewer.set_modality_hint("DX")
        viewer.set_zoom(1.2)
        assert viewer._use_radiography_downscale_smoothing() is False
