"""
Scroll hot-path mixin for VTKWidget.
set_slice, wheelEvent, adaptive throttle, GC suppression, timing probes.
"""
from __future__ import annotations
import gc
import logging
import os
import sys
import time
import threading
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from modules.viewer.fast.stale_frame_guard import should_render_ready_slice
from modules.viewer.viewer_backend_config import BACKEND_PYDICOM, BACKEND_PYDICOM_QT
from modules.viewer.fast import ui_throttle as _ui_throttle
from modules.viewer.fast._decode_guard import (
    h13_check_overlap_before_render,
    h13_get_decode_age_ms,
    _H13_RENDER_GATE,
)
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _throttle_background_threads,
    _nt_suspend_download_subprocesses,
    _nt_resume_download_subprocesses,
    _RENDER_THROTTLE_MS,
)

logger = logging.getLogger(__name__)


class _VWScrollMixin:
    """Scroll hot-path: wheelEvent, set_slice, adaptive throttle, GC suppression."""

    def _get_interactive_slice_count(self) -> int:
        """Return the slice count user navigation may actually reach.

        In progressive mode, ``get_count_of_slices()`` intentionally exposes
        the total expected slice count so the slider range stays stable.
        Wheel/drag navigation must instead clamp to the loaded slice count,
        otherwise the Qt fast path can request unloaded indices and appear
        visually frozen on the first available frames.
        """
        try:
            if bool(getattr(self, '_progressive_mode', False)):
                available = int(getattr(self, '_available_slice_count', 0) or 0)
                if available > 0:
                    return available
        except Exception:
            pass
        try:
            return int(self.get_count_of_slices())
        except Exception:
            return 0

    def _reenable_gc(self):
        """Re-enable garbage collection after scroll burst ends.

        v2.2.9.3 / H5b: Outer guard -- this is a direct QTimer.timeout slot.
        Any unhandled exception propagates through the Qt event loop and causes
        the fatal 'Qt has caught an exception' crash.
        """
        try:
            self._reenable_gc_impl()
        except Exception as exc:
            logger.error(
                "[GC_REENABLE] unhandled exception viewer=%s: %s",
                getattr(self, "id_vtk_widget", "?"), exc, exc_info=True,
            )

    def _reenable_gc_impl(self):
        """Re-enable GC after scroll burst. See _reenable_gc wrapper."""

        if self._gc_suppressed:
            self._gc_suppressed = False
            # Keep thresholds at (700,50,50) ├تظéشظإ gen-1 only runs every 50th
            # gen-0 collection, making expensive pauses extremely rare.
            gc.enable()
            self.isolation_guard.exit_scroll()
            try:
                vc = getattr(self.patient_widget, 'viewer_controller', None)
                mgr = getattr(vc, '_warmup_subprocess_mgr', None) if vc else None
                if mgr is not None:
                    if hasattr(mgr, 'resume_process'):
                        mgr.resume_process()
                    if hasattr(mgr, 'set_scroll_pause'):
                        mgr.set_scroll_pause(False)
            except Exception:
                pass
            _nt_resume_download_subprocesses()
            _throttle_background_threads(False)
            self._restore_reslice_quality()
        try:
            tm = getattr(self.patient_widget, "thumbnail_manager", None)
            if tm is not None and hasattr(tm, "set_scroll_active"):
                tm.set_scroll_active(False)
        except Exception:
            pass
        # v2.3.8 R15: Release the Advanced protected-interaction latch.
        # Runs unconditionally (outside the _gc_suppressed guard) because
        # stack-drag bursts start the GC re-enable timer without flipping
        # _gc_suppressed. 250ms tail grace mirrors FAST's record_protected_drag.
        try:
            _ui_throttle.record_advanced_protected_interaction(
                False, grace_ms=250.0, source="gc_reenable",
            )
        except Exception:
            pass

    def _restore_reslice_quality(self) -> None:
        # v2.2.5.5: NN degradation is now disabled for ALL backends (see
        # wheelEvent comment).  Nothing to restore; skip the reslice
        # Modified() + Render() that would needlessly dirty the pipeline.
        return

    def _on_qt_scroll_stop(self):
        """Called 200ms after the last Qt bridge wheelEvent.

        Re-renders the current frame with OpenCV filter applied and updates
        annotations. This is the scroll-stop counterpart for the Qt fast-path
        (the VTK path uses _reenable_gc instead).  v2.3.3-perf.
        """
        try:
            if self.image_viewer is not None and hasattr(self.image_viewer, 'end_fast_interaction'):
                self.image_viewer.end_fast_interaction()
        except Exception as exc:
            logger.warning("[QT_SCROLL_STOP] end_fast_interaction failed: %s", exc)

    def _should_log_timing(self, duration_ms: float, stage: str) -> bool:
        """Rate-limit very high-frequency timing logs while keeping slow spikes.

        Always logs slow events and samples normal events every N calls.
        v2.2.3.3.1: Uses cached env-var values (set in __init__) to avoid
        per-frame os.getenv calls (~3-5ms each on Windows).
        """
        self._timing_log_counter += 1

        if duration_ms >= self._timing_min_ms:
            return True
        if stage in ("set_slice_total", "scroll_event_total") and (self._timing_log_counter % self._timing_sample_every == 0):
            return True
        return False

    @staticmethod
    def _percentile(sorted_values, pct: float) -> float:
        if not sorted_values:
            return 0.0
        if pct <= 0:
            return float(sorted_values[0])
        if pct >= 100:
            return float(sorted_values[-1])
        idx = int(round((len(sorted_values) - 1) * (pct / 100.0)))
        idx = max(0, min(len(sorted_values) - 1, idx))
        return float(sorted_values[idx])

    def _is_global_download_active_for_probe(self) -> bool:
        try:
            viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
            if viewer_controller is not None and hasattr(viewer_controller, "_global_downloads_active"):
                return bool(viewer_controller._global_downloads_active())
        except Exception:
            pass

        try:
            from modules.zeta_boost.engine import ZetaBoostEngine
            return int(getattr(ZetaBoostEngine, '_global_active_download_count', 0) or 0) > 0
        except Exception:
            return False

    def _record_scroll_lag_probe(self, total_ms: float, queue_delay_ms: float, slice_apply_ms: float):
        """Record a scroll timing sample.

        Probes BOTH Mode A (no download) and Mode B (download active).
        When the download state changes mid-window the samples are flushed
        so Mode A and Mode B metrics are never mixed in the same report.
        Log tag: ``viewer-scroll-probe mode=mode_a|mode_b``
        """
        if not self._lag_probe_enabled:
            return

        now = time.time() * 1000.0
        is_dl_active = self._is_global_download_active_for_probe()

        # Flush window cleanly when download state changes (avoid mixing modes).
        if is_dl_active != self._lag_probe_last_dl_active:
            self._lag_probe_samples.clear()
            self._lag_probe_window_start_ms = 0.0
            self._lag_probe_last_dl_active = is_dl_active

        if self._lag_probe_window_start_ms <= 0.0:
            self._lag_probe_window_start_ms = now

        self._lag_probe_samples.append((float(total_ms), float(max(0.0, queue_delay_ms)), float(slice_apply_ms)))

        elapsed_ms = now - self._lag_probe_window_start_ms
        if elapsed_ms < (self._lag_probe_window_sec * 1000.0):
            return

        if len(self._lag_probe_samples) < self._lag_probe_min_samples:
            self._lag_probe_window_start_ms = now
            self._lag_probe_samples.clear()
            return

        totals = sorted(v[0] for v in self._lag_probe_samples)
        queues = sorted(v[1] for v in self._lag_probe_samples)
        applies = sorted(v[2] for v in self._lag_probe_samples)
        mode_tag = "mode_b" if is_dl_active else "mode_a"

        logger.info(
            (
                "viewer-scroll-probe mode=%s window_sec=%.1f samples=%d "
                "set_slice_p50_ms=%.2f set_slice_p95_ms=%.2f set_slice_max_ms=%.2f "
                "queue_p95_ms=%.2f slice_apply_p95_ms=%.2f"
            ),
            mode_tag,
            (elapsed_ms / 1000.0),
            len(totals),
            self._percentile(totals, 50),
            self._percentile(totals, 95),
            self._percentile(totals, 100),
            self._percentile(queues, 95),
            self._percentile(applies, 95),
            extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "scroll_probe"},
        )

        _p95_total = self._percentile(totals, 95)
        _mode_b_target_ms = 60.0
        if mode_tag == "mode_b" and _p95_total > _mode_b_target_ms:
            logger.warning(
                "REGRESSION ALERT: Mode B set_slice_p95=%.1fms exceeds target %.0fms (samples=%d, max=%.1fms, guard_violations=%d)",
                _p95_total,
                _mode_b_target_ms,
                len(totals),
                self._percentile(totals, 100),
                getattr(self.isolation_guard, 'violation_count', 0),
                extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "regression_alert"},
            )

        self._lag_probe_window_start_ms = now
        self._lag_probe_samples.clear()

    def _estimate_interaction_velocity(self, target_slice: int, t_now_ms: float) -> float:
        prev_slice = self._last_interaction_sample_slice
        prev_ms = float(self._last_interaction_sample_ms or 0.0)
        self._last_interaction_sample_slice = int(target_slice)
        self._last_interaction_sample_ms = float(t_now_ms)
        if prev_slice is None or prev_ms <= 0.0:
            return 0.0
        dt_ms = max(1.0, float(t_now_ms) - float(prev_ms))
        delta = abs(int(target_slice) - int(prev_slice))
        return float(delta) * 1000.0 / dt_ms

    def _notify_interaction_if_due(self, reason: str, t_now_ms: float) -> None:
        try:
            if float(t_now_ms) - float(self._last_interaction_notify_ms) > 250.0:
                self._last_interaction_notify_ms = float(t_now_ms)
                viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
                if viewer_controller is not None and hasattr(viewer_controller, "notify_viewer_interaction"):
                    viewer_controller.notify_viewer_interaction(reason=reason)
        except Exception:
            pass

    def _is_heavy_series_interaction(self) -> bool:
        try:
            return int(self.get_count_of_slices()) >= int(self._heavy_series_slice_threshold)
        except Exception:
            return False

    def _effective_fast_render_min_interval_ms(self) -> float:
        if self._is_heavy_series_interaction():
            return float(max(self._fast_render_min_interval_ms, self._heavy_fast_render_min_interval_ms))
        return float(self._fast_render_min_interval_ms)

    def _effective_fast_skip_velocity_sps(self) -> float:
        if self._is_heavy_series_interaction():
            return float(min(self._fast_render_skip_velocity_sps, self._heavy_fast_skip_velocity_sps))
        return float(self._fast_render_skip_velocity_sps)

    def _effective_fast_max_skip_chain(self) -> int:
        if self._is_heavy_series_interaction():
            return int(max(self._fast_render_max_skip_chain, self._heavy_fast_max_skip_chain))
        return int(self._fast_render_max_skip_chain)

    def _quantize_interactive_target(self, target_slice: int, direction: int, velocity_sps: float, max_slice: int) -> int:
        if not self._is_heavy_series_interaction():
            return int(target_slice)
        stride = 1
        velocity = float(max(0.0, velocity_sps))
        if velocity >= float(self._heavy_quantize_velocity_sps) * 2.0:
            stride = int(self._heavy_quantize_stride_very_high)
        elif velocity >= float(self._heavy_quantize_velocity_sps):
            stride = int(self._heavy_quantize_stride_high)
        if stride <= 1:
            return int(target_slice)

        target = int(target_slice)
        if int(direction) > 0:
            snapped = (target // stride) * stride
        elif int(direction) < 0:
            snapped = ((target + stride - 1) // stride) * stride
        else:
            snapped = int(round(float(target) / float(stride))) * stride

        return max(0, min(int(max_slice - 1), int(snapped)))

    def _should_defer_fast_slice_render(self, velocity_sps: float, now_ms_value: float) -> bool:
        # v2.2.5.1: Never re-defer when the coalesce timer callback is
        # executing.  The timer already waited the minimum interval;
        # deferring again would double the latency and cause scroll freeze.
        if bool(getattr(self, "_coalesce_flush_in_progress", False)):
            return False
        if not bool(getattr(self, "_in_fast_slice_interaction", False)):
            return False
        skip_velocity = float(self._effective_fast_skip_velocity_sps())
        max_skip_chain = int(self._effective_fast_max_skip_chain())
        min_interval_ms = float(self._effective_fast_render_min_interval_ms())
        if float(velocity_sps) < skip_velocity:
            return False
        if int(self._fast_render_skip_chain) >= max_skip_chain:
            return False
        since_last_render = float(now_ms_value) - float(self._last_fast_render_ms or 0.0)
        return float(since_last_render) < min_interval_ms

    def _call_image_viewer_set_slice(self, slice_index: int, fast_interaction: bool) -> None:
        if self.image_viewer is None:
            return
        try:
            self.image_viewer.set_slice(int(slice_index), fast_interaction=bool(fast_interaction))
        except TypeError:
            self.image_viewer.set_slice(int(slice_index))
        except Exception:
            logger.warning(
                "[H13-S5] _call_image_viewer_set_slice exception slice=%s viewer=%s backend=%s",
                slice_index,
                getattr(self, 'id_vtk_widget', '?'),
                getattr(self, '_active_backend', '?'),
                exc_info=True,
            )

    def queue_interactive_slice_target(
        self,
        slice_index: int,
        source: str = "wheel",
        direction: int = 0,
        velocity_sps: float = None,
    ) -> None:
        if self.image_viewer is None:
            return
        max_slice = self._get_interactive_slice_count()
        if max_slice <= 0:
            return

        target = max(0, min(int(slice_index), int(max_slice - 1)))
        t_now = now_ms()
        self._last_scroll_event_ms = t_now

        if velocity_sps is None:
            velocity = self._estimate_interaction_velocity(target, t_now)
        else:
            try:
                velocity = max(0.0, float(velocity_sps))
            except Exception:
                velocity = 0.0
        velocity = min(float(self._interaction_velocity_cap_sps), float(velocity))
        target = self._quantize_interactive_target(
            target_slice=int(target),
            direction=int(direction),
            velocity_sps=float(velocity),
            max_slice=int(max_slice),
        )

        self._pending_wheel_slice = int(target)
        self._pending_scroll_source = str(source or "wheel")
        self._pending_scroll_direction = int(direction)
        self._pending_scroll_velocity_sps = float(velocity)

        if self.slider is not None:
            try:
                self.slider.blockSignals(True)
                self.slider.setValue(int(target))
            finally:
                self.slider.blockSignals(False)

        reason = "wheel_scroll" if str(source) == "wheel" else "stack_drag"
        self._notify_interaction_if_due(reason=reason, t_now_ms=t_now)
        if str(source) != "wheel":
            self._stack_event_count += 1
            if self._stack_event_count <= 3 or self._stack_event_count % 20 == 0:
                logger.info(
                    "viewer-scroll stage=stack_route viewer=%s target_slice=%d direction=%d velocity_sps=%.2f event=%d",
                    str(getattr(self, "id_vtk_widget", None)),
                    int(target),
                    int(direction),
                    float(velocity),
                    int(self._stack_event_count),
                    extra={
                        "component": "viewer",
                        "function": "VTKWidget.queue_interactive_slice_target",
                        "stage": "stack_route",
                    },
                )

        _since_last = float(t_now) - float(self._last_render_end_ms)
        if not self._wheel_coalesce_timer.isActive():
            if _since_last >= float(self._adaptive_frame_gap_ms):
                self._flush_pending_wheel_slice()
            else:
                _remaining = max(1, int(float(self._adaptive_frame_gap_ms) - _since_last))
                self._wheel_coalesce_timer.setInterval(_remaining)
                self._wheel_coalesce_timer.start()
        elif _since_last >= float(self._adaptive_frame_gap_ms):
            self._wheel_coalesce_timer.stop()
            self._flush_pending_wheel_slice()

    def _flush_pending_wheel_slice(self):
        """Render the latest coalesced scroll position (throttle callback).

        v2.2.9.3 / H5c: Outer guard -- this is a direct QTimer.timeout slot.
        The tail code (adaptive gap, timer restart, post-scroll scheduling)
        was previously outside the try/except around set_slice.
        """
        try:
            self._flush_pending_wheel_slice_impl()
        except Exception as exc:
            logger.error(
                "[SCROLL_COALESCE] unhandled exception in flush viewer=%s: %s",
                getattr(self, "id_vtk_widget", "?"), exc, exc_info=True,
            )

    def _flush_pending_wheel_slice_impl(self):
        """Flush impl. See _flush_pending_wheel_slice wrapper."""
        # [H10-1] Mismatch detection — scroll flush
        try:
            _vsn = str(getattr(getattr(self, 'image_viewer', None), 'metadata', {}).get('series', {}).get('series_number', '?'))
            _pw = getattr(self, 'patient_widget', None)
            _dm = getattr(_pw, '_h10_dm_active_series', '?') if _pw else '?'
            logger.debug(
                "[H10-1] fn=_flush_pending_wheel_slice viewer_series=%s dm_active=%s progressive=%s backend=%s",
                _vsn, _dm, getattr(self, '_progressive_mode', '?'), getattr(self, '_active_backend', '?'),
            )
        except Exception:
            pass

        idx = self._pending_wheel_slice
        self._pending_wheel_slice = None
        source = str(self._pending_scroll_source or "wheel")
        direction = int(self._pending_scroll_direction or 0)
        velocity_sps = float(self._pending_scroll_velocity_sps or 0.0)
        self._pending_scroll_source = None
        self._pending_scroll_direction = 0
        self._pending_scroll_velocity_sps = 0.0
        if idx is not None:
            # v2.2.3.2.7: Reset scroll timestamp to "now" to break stale-drain
            # re-arm loop (see commit 8fb6629 for full explanation).
            _t_start = now_ms()
            self._last_scroll_event_ms = _t_start
            logger.debug(f"[SCROLL_COALESCE] flush slice={idx}")
            # v2.2.3.4.0: Flag wheel-scroll context so set_slice() skips
            # non-essential overhead (camera save/restore, style.update_slice).
            self._in_wheel_scroll = source == "wheel"
            self._in_stack_scroll = source == "stack_drag"
            # v2.3.8 R15: Advanced viewer joins the unified protected-
            # interaction latch. Per-frame call acts as begin + keepalive.
            # 2500ms grace covers the 2000ms GC re-enable timer + margin.
            # R3/R5 extend automatically via is_protected_drag_active().
            try:
                _ui_throttle.record_advanced_protected_interaction(
                    True, grace_ms=2500.0, source=source,
                )
            except Exception:
                pass
            # v2.2.5.1: Mark coalesce flush active so _should_defer_fast_slice_render
            # never re-defers the render.  The timer already waited min_interval.
            self._coalesce_flush_in_progress = True
            self._in_fast_slice_interaction = bool(self._in_wheel_scroll or self._in_stack_scroll)
            self._active_interaction_direction = int(direction)
            self._active_interaction_velocity_sps = float(velocity_sps)
            try:
                self.set_slice(idx)
                self._last_flushed_target = int(idx)
            except Exception as _flush_exc:
                logger.error(
                    "[SCROLL_COALESCE] flush set_slice failed viewer=%s idx=%s: %s",
                    getattr(self, 'id_vtk_widget', '?'), idx, _flush_exc,
                )
            finally:
                self._coalesce_flush_in_progress = False
                self._in_wheel_scroll = False
                self._in_stack_scroll = False
                self._in_fast_slice_interaction = False
                self._active_interaction_direction = 0
                self._active_interaction_velocity_sps = 0.0
            _t_end = now_ms()
            self._last_render_end_ms = _t_end
            # Adaptive gap: 25% of frame time, clamped [4ms, 50ms].
            # Gives Qt event loop breathing room proportional to render cost.
            _frame_ms = max(1.0, _t_end - _t_start)
            if bool(getattr(self, "_last_set_slice_deferred_render", False)):
                # Keep throttle conservative after deferred frames so we don't
                # immediately flood the UI loop with 4ms reflushes.
                _effective_min_interval = float(self._effective_fast_render_min_interval_ms())
                self._adaptive_frame_gap_ms = max(
                    float(self._adaptive_frame_gap_ms),
                    min(50.0, max(8.0, float(_effective_min_interval) * 0.70)),
                )
            else:
                self._adaptive_frame_gap_ms = max(4.0, min(50.0, _frame_ms * 0.25))
            # v2.2.3.3.2: Schedule GC re-enable 2000ms after last render.
            # Restarts on every render so GC stays suppressed during the
            # burst.  2000ms ensures GC never fires mid-session (all observed
            # scroll gaps are <2s).  Previous 500ms timer caused a 660-700ms
            # periodic lag (500ms wait + ~150ms GC collection).
            self._gc_reenable_timer.start()
        # Re-arm if more scroll events queued during the render block
        if self._pending_wheel_slice is not None:
            self._wheel_coalesce_timer.setInterval(max(1, int(self._adaptive_frame_gap_ms)))
            self._wheel_coalesce_timer.start()
        else:
            # v2.2.5.4: Scroll settled — schedule a one-shot sync render.
            # During fast-scroll, certain code paths skip VTK Render() (stale
            # drain, lazy cache miss, _should_defer) and skip widget visibility
            # updates (update_slice skipped when _fast_scroll=True).  After the
            # last flush, force a full render at the final position to guarantee
            # the displayed image matches the slider and annotation widgets
            # are shown/hidden for the correct slice.
            QTimer.singleShot(0, self._post_scroll_sync_render)

    def _post_scroll_sync_render(self):
        """Force image + annotation sync after scroll settles."""
        try:
            if self.image_viewer is None:
                return
            # Use the slider value as canonical position (it was updated
            # in every code path, even those that skipped VTK render).
            target = None
            if self.slider is not None:
                try:
                    target = int(self.slider.value())
                except Exception:
                    pass
            if target is None:
                try:
                    target = int(self.image_viewer.last_index_slice_saved)
                except Exception:
                    return

            # Force a full render at the final position (non-fast path).
            current_vtk = None
            try:
                current_vtk = int(self.image_viewer.GetSlice())
            except Exception:
                pass

            if current_vtk is None or current_vtk != target:
                # VTK is out of sync — force SetSlice + Render
                self._call_image_viewer_set_slice(target, fast_interaction=False)

            # Update annotation widget visibility for the current slice.
            try:
                style = self.interactor.GetInteractorStyle()
                if hasattr(style, 'update_slice'):
                    style.update_slice()
            except Exception:
                pass
        except Exception:
            pass

    def set_slice(self, slice_index):
        if self.image_viewer is None:
            return
        # [H10-2] Viewer state snapshot on scroll (throttled)
        _h10_ss_cnt = getattr(self, '_h10_set_slice_count', 0) + 1
        self._h10_set_slice_count = _h10_ss_cnt
        if _h10_ss_cnt <= 5 or _h10_ss_cnt % 20 == 0:
            try:
                _vsn = str(getattr(getattr(self, 'image_viewer', None), 'metadata', {}).get('series', {}).get('series_number', '?'))
                _pw = getattr(self, 'patient_widget', None)
                _dm = getattr(_pw, '_h10_dm_active_series', '?') if _pw else '?'
                logger.info(
                    "[H10-2] fn=set_slice idx=%s total=%s viewer_series=%s dm_active=%s "
                    "progressive=%s backend=%s gen=%s n=%d",
                    slice_index, self.get_count_of_slices(),
                    _vsn, _dm,
                    getattr(self, '_progressive_mode', '?'),
                    getattr(self, '_active_backend', '?'),
                    getattr(self, '_series_generation_id', '?'),
                    _h10_ss_cnt,
                )
            except Exception:
                pass

        if self._progressive_mode and not self._is_slice_available(slice_index):
            if self.slider is not None:
                try:
                    self.slider.blockSignals(True)
                    self.slider.setValue(slice_index)
                    self.slider.blockSignals(False)
                except Exception:
                    pass
            self.image_viewer.last_index_slice_saved = int(slice_index)
            _wheel = bool(getattr(self, "_in_wheel_scroll", False))
            if not _wheel or (self._download_overlay_label is None or not self._download_overlay_label.isVisible()):
                self._show_download_overlay()
            return

        if self._progressive_mode and self._download_overlay_label is not None:
            if self._download_overlay_label.isVisible():
                self._hide_download_overlay()

        # ظ¤ظ¤ Qt bridge fast path: delegate entirely, skip VTK pipeline ظ¤ظ¤
        if self._qt_bridge_active:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(  # CP4 [FAST-DIAG]
                    "[FAST-DIAG] set_slice Qt bridge entry idx=%s backend=%s",
                    slice_index, getattr(self, '_active_backend', 'N/A'),
                )
            try:
                _wheel = bool(getattr(self, "_in_wheel_scroll", False))
                _stack_drag = bool(getattr(self, "_in_stack_scroll", False))
                _fast = bool(_wheel or _stack_drag)
                # B4.1: distinguish precision wheel from fast stack-drag
                _itype = 'drag' if _stack_drag else ('wheel' if _wheel else '')
                self.image_viewer.set_slice(slice_index, fast_interaction=_fast, interaction_type=_itype)
                self.image_viewer.last_index_slice_saved = int(slice_index)
                # Update slider
                if self.slider is not None:
                    self.slider.blockSignals(True)
                    self.slider.setValue(slice_index)
                    self.slider.blockSignals(False)
                # Lock sync (throttled during fast scroll)
                if self._on_slice_changed_cb is not None:
                    _t_now = now_ms()
                    if not _fast or (_t_now - self._last_lock_sync_ms >= 100.0):
                        self._last_lock_sync_ms = _t_now
                        try:
                            self._on_slice_changed_cb(self)
                        except Exception:
                            pass
                # Reference lines
                try:
                    _pw = getattr(self, 'patient_widget', None)
                    if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                        _pw._schedule_reference_line_update()
                except Exception:
                    pass
            except Exception as e:
                logger.warning("Qt set_slice failed idx=%s: %s", slice_index, e)
            return

        t_set_slice = now_ms()
        self._last_set_slice_deferred_render = False
        queue_delay_ms = -1.0
        if self._last_scroll_event_ms is not None:
            queue_delay_ms = max(0.0, t_set_slice - self._last_scroll_event_ms)
            if self._should_log_timing(queue_delay_ms, "event_queue_delay"):
                logger.info(
                    "viewer-scroll stage=event_queue_delay_ms duration_ms=%.2f",
                    queue_delay_ms,
                    extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "event_queue_delay"},
                )
        _wheel = bool(getattr(self, "_in_wheel_scroll", False))
        _stack_drag = bool(getattr(self, "_in_stack_scroll", False))
        _fast_scroll = bool(_wheel or _stack_drag)
        _active_velocity_sps = float(getattr(self, "_active_interaction_velocity_sps", 0.0) or 0.0)

        # v2.2.5.2: Clear flushed-target on non-scroll set_slice so it doesn't
        # pollute the next wheel session with a stale logical position.
        if not _fast_scroll:
            self._last_flushed_target = None

        # v2.2.3.2.1: Stale-event fast-drain guard.
        # -----------------------------------------
        # If this scroll event has been waiting in the Qt event queue longer than
        # _STALE_SCROLL_MS (500ms) the main thread was briefly blocked and we now
        # have a large backlog of backed-up events.  Processing each one with a
        # full VTK render (~50ms) would freeze the viewer for many seconds.
        # Instead: skip the render for stale events, just slide the UI position
        # tracker forward.  The _pending_wheel_slice + coalesce timer guarantees
        # the FINAL (freshest) position is always rendered after the backlog drains.
        _STALE_SCROLL_MS = 500.0
        if _fast_scroll and queue_delay_ms > _STALE_SCROLL_MS:
            try:
                if self.slider is not None:
                    self.slider.blockSignals(True)
                    self.slider.setValue(slice_index)
                    self.slider.blockSignals(False)
            except Exception:
                pass
            # Store the position so the coalesce timer renders it once
            self._pending_wheel_slice = slice_index
            self._pending_scroll_source = "wheel" if _wheel else "stack_drag" if _stack_drag else "direct"
            self._pending_scroll_direction = int(getattr(self, "_active_interaction_direction", 0) or 0)
            self._pending_scroll_velocity_sps = float(getattr(self, "_active_interaction_velocity_sps", 0.0) or 0.0)
            try:
                if not self._wheel_coalesce_timer.isActive():
                    self._wheel_coalesce_timer.start()
            except Exception:
                pass
            self.image_viewer.last_index_slice_saved = slice_index
            self._last_set_slice_deferred_render = True
            # Log only 1st, 10th, 50th, 100th... stale skip to avoid log spam
            self._stale_scroll_skip_count += 1
            _cnt = self._stale_scroll_skip_count
            if _cnt == 1 or _cnt % 10 == 0:
                logger.info(
                    "viewer-scroll stage=stale_scroll_skip_ms duration_ms=%.2f slice=%d skip_count=%d",
                    queue_delay_ms, slice_index, _cnt,
                    extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "stale_scroll_skip"},
                )
            return

        # Reset drain counter when a non-stale render runs (log how many were skipped)
        if self._stale_scroll_skip_count > 0:
            logger.info(
                "viewer-scroll stage=stale_drain_complete skipped=%d queue_delay_ms=%.2f slice=%d",
                self._stale_scroll_skip_count, queue_delay_ms, slice_index,
                extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "stale_drain_complete"},
            )
            self._stale_scroll_skip_count = 0

        # ├ت┼ôظخ CRITICAL: Save current camera zoom before slice change
        # v2.2.3.4.0: Skip during wheel scroll ├تظéشظإ the wheel event is consumed
        # (event.accept) so VTK's built-in zoom is blocked.  Camera save/
        # restore costs ~3-5ms per frame (VTK ├تظبظآ Python round-trips + comparison).
        # The _protected_parallel_scale remains valid from the last non-scroll
        # set_slice or explicit user zoom, so skipping here is safe.
        saved_scale = None
        if not _fast_scroll:
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    saved_scale = camera.GetParallelScale()
                    # Update protected scale only if not already set or if changed by user zoom
                    if self._protected_parallel_scale is None or abs(saved_scale - self._protected_parallel_scale) > 0.01:
                        self._protected_parallel_scale = saved_scale
                    logger.debug(f"[set_slice] Protected scale={self._protected_parallel_scale}")
            except Exception:
                logger.warning("[H13-S5] Camera scale save failed in set_slice", exc_info=True)
        
        # PyDicom lazy race guard:
        # mark the requested/current slice before decode is queued so a fast
        # decode callback cannot be dropped as stale for this same request.
        _is_lazy_active = bool(self._active_backend == BACKEND_PYDICOM and self._lazy_loader is not None)
        if _is_lazy_active:
            try:
                self._lazy_requested_generation = self._series_generation_id
                self._lazy_requested_slice = int(slice_index)
            except Exception:
                pass
            try:
                if hasattr(self._lazy_loader, "set_scroll_hint"):
                    self._lazy_loader.set_scroll_hint(
                        int(slice_index),
                        direction=int(getattr(self, "_active_interaction_direction", 0) or 0),
                        velocity_sps=float(getattr(self, "_active_interaction_velocity_sps", 0.0) or 0.0),
                        source=("wheel" if _wheel else "stack_drag" if _stack_drag else "direct"),
                    )
            except Exception:
                pass
        t_slice_apply = now_ms()
        lazy_cache_hit = False
        lazy_render_immediate = True
        if _is_lazy_active:
            # Request decode first. On cache miss, always defer render to the
            # lazy callback so the displayed slice arrives already decoded and
            # filtered instead of flashing an intermediate/unprepared state.
            lazy_cache_hit = bool(self._ensure_lazy_slice_loaded(slice_index, mark_current=False))
            lazy_render_immediate = bool(lazy_cache_hit)
        if lazy_render_immediate and self._should_defer_fast_slice_render(
            velocity_sps=float(_active_velocity_sps),
            now_ms_value=now_ms(),
        ):
            lazy_render_immediate = False
            self._last_set_slice_deferred_render = True
        if lazy_render_immediate:
            # H13-P1: Check for write/render overlap before entering render chain.
            h13_check_overlap_before_render(int(slice_index), "set_slice_scroll")
            # H13-P3: Log decode-to-render age.
            _h13_age = h13_get_decode_age_ms(int(slice_index))
            if _h13_age >= 0.0 and _h13_age < 5.0:
                logger.info("[H13-AGE] tight decode-to-render age=%.2fms slice=%d caller=scroll", _h13_age, int(slice_index))
            # H13-T4: Render-chain gate — acquire _load_lock around full render chain.
            _h13_gate_held = False
            if _H13_RENDER_GATE and self._lazy_loader is not None and hasattr(self._lazy_loader, "_load_lock"):
                self._lazy_loader._load_lock.acquire()
                _h13_gate_held = True
            try:
                if _is_lazy_active and self._lazy_loader is not None:
                    try:
                        if hasattr(self._lazy_loader, "mark_vtk_modified"):
                            self._lazy_loader.mark_vtk_modified()
                        # mark_vtk_modified() above called vtk_image_data.Modified() on the lazy source.
                        # For pydicom_2d the viewer is wired directly to that source (bypassing
                        # image_reslice), so VTK's trivial producer detects the MTime change on
                        # Render() and re-reads the numpy-backed scalars. No reslice call needed.
                    except Exception:
                        logger.warning("[H13-S5] mark_vtk_modified failed in set_slice", exc_info=True)
                self._call_image_viewer_set_slice(slice_index, fast_interaction=_fast_scroll)
            finally:
                if _h13_gate_held:
                    self._lazy_loader._load_lock.release()
            if _fast_scroll:
                self._last_fast_render_ms = now_ms()
                self._fast_render_skip_chain = 0
        else:
            self.image_viewer.last_index_slice_saved = int(slice_index)
            if _fast_scroll:
                _effective_max_skip_chain = int(self._effective_fast_max_skip_chain())
                self._fast_render_skip_chain = min(
                    int(_effective_max_skip_chain),
                    int(self._fast_render_skip_chain) + 1,
                )
                self._pending_wheel_slice = int(slice_index)
                self._pending_scroll_source = "wheel" if _wheel else "stack_drag" if _stack_drag else "direct"
                self._pending_scroll_direction = int(getattr(self, "_active_interaction_direction", 0) or 0)
                self._pending_scroll_velocity_sps = float(_active_velocity_sps)
                try:
                    if not self._wheel_coalesce_timer.isActive():
                        since_last = max(0.0, now_ms() - float(self._last_fast_render_ms or 0.0))
                        _effective_min_interval = float(self._effective_fast_render_min_interval_ms())
                        remaining = max(1, int(float(_effective_min_interval) - float(since_last)))
                        self._wheel_coalesce_timer.setInterval(remaining)
                        self._wheel_coalesce_timer.start()
                except Exception:
                    pass
        if not _fast_scroll:
            self._fast_render_skip_chain = 0
        if not _is_lazy_active:
            self._ensure_lazy_slice_loaded(slice_index)
        if _is_lazy_active and lazy_cache_hit:
            self._mark_lazy_first_frame_if_needed()
        if lazy_render_immediate:
            wl_ms = float(getattr(self.image_viewer, "last_wl_convert_ms", 0.0) or 0.0)
            if wl_ms > 0.0:
                self._lazy_metrics["wl_convert_ms_total"] += wl_ms
                self._lazy_metrics["wl_convert_count"] += 1
        self._log_lazy_metrics_if_due()
        slice_apply_ms = max(0.0, now_ms() - t_slice_apply)
        if self._should_log_timing(slice_apply_ms, "slice_apply"):
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget.set_slice",
                stage="slice_apply",
                start_ms=t_slice_apply,
            )
        self.image_viewer.last_index_slice_saved = slice_index
        
        # ├ت┼ôظخ CRITICAL: Force restore camera zoom after slice change
        # Phase 1 fix (v2.2.3.1.6): compare against _protected_parallel_scale
        # (the user's last explicitly set zoom), not against saved_scale which
        # was captured at the top of this call and may already include VTK
        # floating-point drift.  Tolerance widened from 0.001 ├تظبظآ 0.05 so minor
        # per-frame FP jitter in SetSlice() no longer fires a second Render()
        # on every scroll (was measured as 60├تظéشظ£80ms extra per scroll in Mode B).
        # v2.2.3.4.0: Skip during wheel scroll (same rationale as camera save).
        if not _fast_scroll:
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if saved_scale is not None and camera:
                    current_scale = camera.GetParallelScale()
                    _ref_scale = (
                        self._protected_parallel_scale
                        if self._protected_parallel_scale is not None
                        else saved_scale
                    )
                    # Only re-render if zoom deviated meaningfully from user's intended scale
                    if abs(current_scale - _ref_scale) > 0.05:
                        logger.warning(f"[set_slice] Zoom change detected! scale={current_scale:.4f} ├تظبظآ reverting to {_ref_scale:.4f}")
                        camera.SetParallelScale(_ref_scale)
                        self._protected_parallel_scale = _ref_scale
                        t_render = now_ms()
                        self.image_viewer.Render()
                        render_ms = max(0.0, now_ms() - t_render)
                        if self._should_log_timing(render_ms, "render_complete"):
                            log_stage_timing(
                                logger,
                                component="viewer",
                                function="VTKWidget.set_slice",
                                stage="render_complete",
                                start_ms=t_render,
                            )
            except Exception:
                logger.warning("[H13-S5] Camera zoom restore failed in set_slice", exc_info=True)

        # Notify interactor style if it's a ruler style
        # v2.2.3.4.0: Skip during wheel scroll ├تظéشظإ ruler tools are not
        # meaningfully updated during rapid scrolling and the VTK call +
        # Python wrapper costs ~1ms per frame.
        if not _fast_scroll:
            try:
                style = self.interactor.GetInteractorStyle()
                if hasattr(style, 'update_slice'):
                    style.update_slice()

            except Exception as e:
                logger.debug(f"Error updating on slice change: {e}")

        self._update_overlay_extent()

        # Lock Sync callback ├تظéشظإ fires on EVERY slice change regardless of source
        # v2.2.3.4.0: Throttle to once per 100ms during wheel scroll.
        # _do_lock_sync() computes world-space coordinates and syncs ALL target
        # viewers (including their Render).  At 10-15fps scroll rate, calling
        # on every frame wastes 5-20ms/frame on work that is immediately
        # superseded.  100ms spacing keeps target viewers visually tracked
        # without saturating the event loop.
        if self._on_slice_changed_cb is not None:
            try:
                _t_now = now_ms()
                if not _fast_scroll or (_t_now - self._last_lock_sync_ms >= 100.0):
                    self._last_lock_sync_ms = _t_now
                    self._on_slice_changed_cb(self)
            except Exception:
                pass

        # Notify ImageSliceBooster only in Fast backend mode.
        # Advanced backend does not consume this cache and would only add
        # background I/O contention during scroll.
        try:
            if self._active_backend in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT):
                _t_now = now_ms()
                if _t_now - self._last_booster_notify_ms >= 200.0:
                    self._last_booster_notify_ms = _t_now
                    _vc = getattr(getattr(self, 'patient_widget', None), 'viewer_controller', None)
                    if _vc is not None:
                        _booster = getattr(_vc, '_image_slice_booster', None)
                        if _booster is not None and _booster.is_active:
                            _sn = _booster.active_series
                            if _sn is not None:
                                _viewer_sn = ''
                                try:
                                    _viewer_sn = str(
                                        getattr(self.image_viewer, 'metadata', {})
                                        .get('series', {})
                                        .get('series_number', '')
                                    )
                                except Exception:
                                    _viewer_sn = ''
                                if _viewer_sn and str(_viewer_sn) == str(_sn):
                                    _booster.on_slice_changed(_sn, slice_index)
        except Exception:
            pass

        # v2.2.3.3.7: Throttled reference line update on wheel scroll.
        # Leading-edge fires geometry-only (repaint=False, ~1ms) for instant
        # actor positioning.  Trailing-edge (50ms) paints ONE target viewer
        # (round-robin) to cap event-loop blocking at ~20ms per tick.
        # Scroll-end tick repaints ALL targets for full visual correctness.
        try:
            _pw = getattr(self, 'patient_widget', None)
            if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                _pw._schedule_reference_line_update()
        except Exception:
            pass

        set_slice_total_ms = max(0.0, now_ms() - t_set_slice)
        if self._should_log_timing(set_slice_total_ms, "set_slice_total"):
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget.set_slice",
                stage="set_slice_total",
                start_ms=t_set_slice,
                queue_delay_ms=f"{queue_delay_ms:.2f}",
            )
        self._record_scroll_lag_probe(set_slice_total_ms, queue_delay_ms, slice_apply_ms)

    def set_slider(self, slider):
        self.slider = slider
        # Only set slider in style if style exists, is not a method, and image_viewer is initialized
        if (hasattr(self, 'style') and 
            self.style is not None and 
            not callable(self.style) and
            hasattr(self.style, 'set_slider_from_ui')):
            self.style.set_slider_from_ui(self.slider)

    def _dump_scroll_state(self, source: str = "unknown"):
        """Dump full scroll-relevant state for diagnostics."""
        try:
            spinner_vis = False
            try:
                sp = getattr(self, 'viewport_spinner', None)
                if sp and sp.spinner:
                    spinner_vis = sp.spinner.isVisible()
            except Exception:
                pass
            logger.info(
                "[SCROLL-STATE] source=%s viewer=%s image_viewer=%s slider=%s "
                "backend=%s lazy_loader=%s progressive=%s total_expected=%d "
                "available=%d spinner_visible=%s updatesEnabled=%s "
                "count_of_slices=%d",
                source,
                getattr(self, 'id_vtk_widget', None),
                'present' if self.image_viewer else 'None',
                'present' if getattr(self, 'slider', None) else 'None',
                getattr(self, '_active_backend', None),
                'present' if getattr(self, '_lazy_loader', None) else 'None',
                getattr(self, '_progressive_mode', False),
                getattr(self, '_total_expected_slices', 0),
                getattr(self, '_available_slice_count', 0),
                spinner_vis,
                self.updatesEnabled(),
                self.get_count_of_slices() if hasattr(self, 'get_count_of_slices') else -1,
            )
        except Exception as e:
            logger.warning("[SCROLL-STATE] dump failed: %s", e)

    def wheelEvent(self, event):
        """
        Handle mouse wheel scrolling for slice navigation within current series.
        CRITICAL: Prevents VTK zoom by consuming the event and NOT calling super().wheelEvent()
        """
                # ── FAST mode (Qt bridge) fast-path ──────────────────────────────
        # When the Qt 2D backend is active, skip the entire VTK scroll
        # machinery (GC suppression, coalesce timer, adaptive step,
        # pending-wheel tracking).  Directly compute ±1 step, render via
        # the bridge, and update the slider.  This guarantees scroll works
        # regardless of VTK interactor / event-delivery edge cases.
        if (getattr(self, '_active_backend', None) == BACKEND_PYDICOM_QT  # CP3 fail-fast guard
                and not self._qt_bridge_active):
            logger.critical(
                "[FAST-CRITICAL] wheelEvent dead-scroll: backend=PYDICOM_QT but _qt_bridge_active=False viewer_id=%s",
                id(self),
            )
        if self._qt_bridge_active and self.image_viewer is not None and self.slider is not None:
            delta = event.angleDelta().y()
            if delta == 0:
                event.accept()
                return
            max_s = self._get_interactive_slice_count()
            if max_s <= 1:
                event.accept()
                return
            step = -1 if delta > 0 else 1
            current = self.image_viewer.GetSlice()
            new_idx = max(0, min(current + step, max_s - 1))
            if new_idx != current:
                try:
                    # B4.1: wheel event — precision browsing, no surrogates
                    self.image_viewer.set_slice(new_idx, fast_interaction=True, interaction_type='wheel')
                    self.image_viewer.last_index_slice_saved = int(new_idx)
                except Exception as _e:
                    logger.warning("Qt fast-scroll set_slice failed: %s", _e)
                # Update slider without triggering valueChanged
                self.slider.blockSignals(True)
                self.slider.setValue(new_idx)
                self.slider.blockSignals(False)
                # Lock Sync callback (throttled)
                if self._on_slice_changed_cb is not None:
                    try:
                        self._on_slice_changed_cb(self)
                    except Exception:
                        pass
                # Reference lines
                try:
                    _pw = getattr(self, 'patient_widget', None)
                    if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                        _pw._schedule_reference_line_update()
                except Exception:
                    pass
            # B4.4: settle timer unification
            # Do NOT arm a second VTK-side 200ms timer here.
            # QtViewerBridge._interaction_settle_timer is the single source of
            # truth for "scroll/drag settled" and already calls
            # end_fast_interaction() after 200ms of inactivity.
            event.accept()
            return

# v2.2.9.3-diag: first 5 wheel events logged at INFO to confirm entry
        t_event_receive = now_ms()
        self._last_scroll_event_ms = t_event_receive
        # v2.2.3.3.2: Suppress GC during scroll burst.
        # Save original thresholds only once ├تظéشظإ if we already have saved
        # values (from a previous burst where _reenable_gc kept elevated
        # thresholds), don't overwrite with the elevated (700,50,50).
        if not self._gc_suppressed:
            if self._gc_saved_thresholds is None:
                self._gc_saved_thresholds = gc.get_threshold()
            gc.set_threshold(700, 50, 50)  # 5╪ثظ¤ less frequent gen-1/gen-2
            if gc.isenabled():
                gc.disable()
            self._gc_suppressed = True
            self.isolation_guard.enter_scroll()
            try:
                vc = getattr(self.patient_widget, 'viewer_controller', None)
                mgr = getattr(vc, '_warmup_subprocess_mgr', None) if vc else None
                if mgr is not None:
                    if hasattr(mgr, 'set_scroll_pause'):
                        mgr.set_scroll_pause(True)
                    if hasattr(mgr, 'suspend_process'):
                        mgr.suspend_process()
            except Exception:
                pass
            _throttle_background_threads(True)
            # v2.2.5.5: Skip NN interpolation degradation for ALL backends.
            # When the reslice has a non-identity direction-matrix transform
            # (convert_itk2vtk Y-flip), switching to NearestNeighbor +
            # Modified() causes VTK's UpdateDisplayExtent to compute a wrong
            # output extent, collapsing the slice range (e.g. (0,24) → (14,14))
            # and replacing vtk_image_data with a 1-slice image.  This caused
            # the "scrollbar moves but image freezes" bug after stack drag.
            _skip_nn_degrade = True
            if not _skip_nn_degrade:
                try:
                    reslice = getattr(getattr(self, 'image_viewer', None), 'image_reslice', None)
                    if reslice is not None:
                        reslice.SetInterpolationModeToNearestNeighbor()
                        reslice.Modified()
                except Exception:
                    pass
                try:
                    if self.image_viewer is not None:
                        actor = self.image_viewer.GetImageActor()
                        if actor is not None:
                            actor.InterpolateOff()
                            prop = actor.GetProperty()
                            if prop is not None:
                                prop.SetInterpolationType(0)
                except Exception:
                    pass
            _nt_suspend_download_subprocesses()
        # v2.2.3.3.9: Tighten throttle from 500ms├تظبظآ250ms so the busy flag
        # stays True continuously during scroll (with 350ms release delay,
        # 500ms left a 150ms gap where warmup workers could start).
        try:
            if t_event_receive - self._last_interaction_notify_ms > 250.0:
                self._last_interaction_notify_ms = t_event_receive
                viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
                if viewer_controller is not None and hasattr(viewer_controller, "notify_viewer_interaction"):
                    viewer_controller.notify_viewer_interaction(reason="wheel_scroll")
                tm = getattr(self.patient_widget, "thumbnail_manager", None)
                if tm is not None and hasattr(tm, "set_scroll_active"):
                    tm.set_scroll_active(True)
        except Exception:
            pass
        logger.debug(f"[WHEEL] Called - image_viewer={'present' if self.image_viewer else 'None'}, slider={'present' if getattr(self, 'slider', None) else 'None'}")
        
        try:
            # Check if image_viewer exists with valid slider
            if self.image_viewer is None or self.slider is None:
                # No image or slider - consume event to prevent VTK zoom
                logger.info(
                    "[WHEEL] BLOCKED — image_viewer=%s slider=%s viewer=%s",
                    "present" if self.image_viewer else "None",
                    "present" if self.slider else "None",
                    getattr(self, "id_vtk_widget", None),
                )
                event.accept()
                return
            
            delta = event.angleDelta().y()
            max_slice = self._get_interactive_slice_count()
            
            logger.debug(f"[WHEEL] delta={delta}, max_slice={max_slice}")
            
            # Nothing to scroll through - still consume to prevent VTK zoom
            if max_slice <= 1:
                logger.info(
                    "[WHEEL] BLOCKED — max_slice=%d viewer=%s backend=%s",
                    max_slice, getattr(self, "id_vtk_widget", None),
                    getattr(self, "_active_backend", None),
                )
                event.accept()
                return
            
            # Wheel policy: ALWAYS move one slice per notch (no skipping).
            # Stack-drag has its own adaptive acceleration path.
            if delta > 0:
                step = -1
            elif delta < 0:
                step = 1
            else:
                step = 0
            
            # Calculate next slice index
            current_slice = self.image_viewer.GetSlice()
            if self._active_backend == BACKEND_PYDICOM and self._lazy_requested_slice is not None:
                try:
                    current_slice = int(self._lazy_requested_slice)
                except Exception:
                    pass
            elif self._pending_wheel_slice is not None:
                # v2.2.5.1: For VTK (and all) backends, use the pending
                # (requested-but-not-yet-rendered) slice as logical position.
                try:
                    current_slice = int(self._pending_wheel_slice)
                except Exception:
                    pass
            elif self._last_flushed_target is not None:
                # v2.2.5.2: After flush completes, _pending is cleared but
                # GetSlice() may still return the stale pre-flush value.
                # Use the last successfully flushed target as logical position
                # to keep the wheel advancing.
                try:
                    current_slice = int(self._last_flushed_target)
                except Exception:
                    pass
            next_slice = current_slice + step
            
            # Clamp to valid range [0, N-1]
            next_slice = max(0, min(next_slice, max_slice - 1))
            
            logger.debug(f"[WHEEL] current={current_slice}, next={next_slice}, step={step}")
            self._wheel_event_count += 1
            if (
                self._wheel_event_count <= 3 or self._wheel_event_count % 20 == 0
            ):
                _vtk_raw = -1
                try:
                    _vtk_raw = int(self.image_viewer.GetSlice()) if self.image_viewer else -1
                except Exception:
                    pass
                _pos_src = "getslice"
                if self._active_backend == BACKEND_PYDICOM and self._lazy_requested_slice is not None:
                    _pos_src = "lazy"
                elif self._pending_wheel_slice is not None:
                    _pos_src = "pending"
                elif self._last_flushed_target is not None:
                    _pos_src = "flushed"
                logger.info(
                    "viewer-scroll stage=backend_route backend=%s viewer=%s current_slice=%d target_slice=%d delta=%d event=%d vtk_raw=%d pos_src=%s",
                    str(self._active_backend),
                    str(getattr(self, "id_vtk_widget", None)),
                    int(current_slice),
                    int(next_slice),
                    int(delta),
                    int(self._wheel_event_count),
                    int(_vtk_raw),
                    str(_pos_src),
                    extra={
                        "component": "viewer",
                        "function": "VTKWidget.wheelEvent",
                        "stage": "backend_route",
                    },
                )
            
            # v2.2.3.2.8: Adaptive THROTTLE replaces debounce.
            # Debounce restarted the 16ms timer on every event, adding 16ms
            # latency to EVERY frame.  Throttle renders immediately when
            # enough time has passed since the last render (leading-edge),
            # otherwise starts a timer for the remaining gap.  The adaptive
            # gap (25% of last frame time) auto-tunes to hardware speed.
            direction = 1 if step > 0 else -1 if step < 0 else 0
            self.queue_interactive_slice_target(
                slice_index=next_slice,
                source="wheel",
                direction=direction,
            )

            # v2.2.3.2.8: Skip per-event ruler/border/camera checks.
            # set_slice() already handles ruler update (style.update_slice),
            # camera zoom protection, and overlay sync during the actual render.
            # Running them per-wheel-event operates on stale state and wastes
            # 3-8ms per event ╪ثظ¤ 3-5 queued events = 9-40ms per frame cycle.

            # ├ت┼ôظخ CRITICAL: CONSUME the event - DO NOT let parent handle it
            event.accept()
            
        except Exception as e:
            logger.warning(f"[WHEEL] Exception (consuming to prevent zoom): {e}")
            event.accept()

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for Curved MPR and other tools"""
        try:
            # Check if image_viewer exists
            if self.image_viewer is None:
                super().keyPressEvent(event)
                return
            
            key = event.key()
            modifiers = event.modifiers()
            
            # Curved MPR shortcuts (when mode is active)
            if hasattr(self.image_viewer, 'curved_mpr_mode') and self.image_viewer.curved_mpr_mode:
                # G key: Generate curved MPR
                if key == Qt.Key_G and modifiers == Qt.NoModifier:
                    logger.debug("[SHORTCUT] 'G' pressed - Generating Curved MPR...")
                    point_count = self.image_viewer.curved_mpr_module.get_point_count()
                    if point_count >= 2:
                        self.image_viewer.generate_and_show_curved_mpr()
                        logger.debug(f"├ت┼ôظ£ Curved MPR generated with {point_count} points")
                    else:
                        logger.debug(f"├ت┌ّ┬ب├»┬╕┌ê Need at least 2 points (have {point_count})")
                    event.accept()
                    return
                
                # C key: Clear all points
                elif key == Qt.Key_C and modifiers == Qt.NoModifier:
                    logger.debug("[SHORTCUT] 'C' pressed - Clearing points...")
                    self.image_viewer.curved_mpr_module.reset()
                    self.image_viewer._clear_curved_mpr_visuals()
                    logger.debug("├ت┼ôظ£ All points cleared")
                    event.accept()
                    return
                
                # ESC key: Exit curved MPR mode
                elif key == Qt.Key_Escape:
                    logger.debug("[SHORTCUT] 'ESC' pressed - Exiting Curved MPR mode...")
                    self.image_viewer.enable_curved_mpr_mode(False)
                    logger.debug("├ت┼ôظ£ Curved MPR mode deactivated")
                    event.accept()
                    return
        
        except Exception as e:
            logger.error(f"Error in keyPressEvent: {e}")
        
        # Pass to parent if not handled
        super().keyPressEvent(event)
