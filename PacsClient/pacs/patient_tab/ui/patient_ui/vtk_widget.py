import time
import logging
import os

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from PacsClient.pacs.patient_tab.interactor_styles import AbstractInteractorStyle
from PacsClient.pacs.patient_tab.viewers.viewer_2d import ImageViewer2D, CustomCombineImageViewers
from PacsClient.pacs.patient_tab.ui.widgets import ViewportSpinner
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor, QPainter, QPixmap, QColor
import gc  # For manual garbage collection
from PacsClient.pacs.patient_tab.utils import read_segment_nifti
import vtkmodules.all as vtk
from PySide6.QtWidgets import QApplication
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing

logger = logging.getLogger(__name__)

# =====================================================
# ANTI-FLICKERING CONSTANTS
# =====================================================
_RENDER_THROTTLE_MS = 16  # ~60fps max render rate
_SPINNER_HIDE_DELAY_MS = 50  # Delay before hiding spinner to allow final render
_SYNC_MOVE_THROTTLE_MS = 16  # min interval between sync mouse move processing (~60fps)


def grow_vtk_inplace(old_input, new_vtk_image_data):
    # Old/new dimensions
    ox, oy, oz = old_input.GetDimensions()
    nx, ny, nz = new_vtk_image_data.GetDimensions()

    # If nothing was added, just mark as Modified
    if (nx <= ox and ny <= oy and nz <= oz):
        old_input.Modified()
        return False

    # 2) XY must remain unchanged; otherwise avoid memory corruption
    if (ox, oy) != (nx, ny):
        # If XY changed, reject for now to avoid crashes/heavy memory use
        # (A safer path can be implemented if needed)
        return False

    # 3) Update spacing/origin only when changed
    if old_input.GetSpacing() != new_vtk_image_data.GetSpacing():
        old_input.SetSpacing(new_vtk_image_data.GetSpacing())
    if old_input.GetOrigin() != new_vtk_image_data.GetOrigin():
        old_input.SetOrigin(new_vtk_image_data.GetOrigin())

    # 4) New dimensions/extent
    old_input.SetDimensions(nx, ny, nz)
    old_input.SetExtent(0, nx - 1, 0, ny - 1, 0, nz - 1)

    # 5) Lowest-cost scalar update: use SetScalars instead of DeepCopy (pointer swap)
    new_scalars = new_vtk_image_data.GetPointData().GetScalars()
    old_input.GetPointData().SetScalars(new_scalars)

    # 7) Mark as modified; no immediate Render/Update
    old_input.GetPointData().Modified()
    old_input.Modified()

    # self.image_reslice.Modified()
    # self.image_reslice.Update()      # intentionally removed
    # self.UpdateDisplayExtent()       # intentionally removed
    # self.update_corners_actors()     # intentionally removed (caller can trigger after throttle)
    # self.Render()                    # intentionally removed

    ################################################################
    # # 3) Change signal
    # old_vtk.GetPointData().Modified()
    # old_vtk.Modified()
    return True


class VTKWidget(QVTKRenderWindowInteractor):
    def __init__(self, parent=None, height_viewer=480, patient_widget=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.last_series_show = None
        self.id_vtk_widget = None
        self.current_style: AbstractInteractorStyle = None
        self.image_viewer = None
        self.height_viewer = height_viewer
        self.apply_default_filter = True
        self.patient_widget = patient_widget
        
        # =====================================================
        # ANTI-FLICKERING: Render throttling state
        # =====================================================
        self._render_pending = False
        self._last_render_time = 0
        self._render_timer = None
        
        # =====================================================
        # ZOOM PROTECTION: Track camera zoom to prevent unwanted changes
        # =====================================================
        self._protected_parallel_scale = None
        self._wheel_event_count = 0

        self.render_window = self.GetRenderWindow()
        self.interactor = self.render_window.GetInteractor()
        
        # =====================================================
        # ANTI-FLICKERING: Enable double buffering on render window
        # =====================================================
        self.render_window.SetDoubleBuffer(True)
        self.render_window.SetSwapBuffers(True)
        # v2.2.3.2.5: Disable multisampling — VTK defaults to 8x MSAA.
        # On software OpenGL (WARP / Mesa / SwiftShader) each sample
        # multiplies the per-pixel work.  For 2D medical images
        # displayed through vtkImageActor, multisampling provides zero
        # visual benefit (pixel-exact raster, no polygon edges to AA).
        self.render_window.SetMultiSamples(0)
        
        # Initialize interactor without processEvents (causes flickering)
        self.interactor.Initialize()

        # Initialize viewport spinner
        self.viewport_spinner = ViewportSpinner(self)
        
        # =====================================================
        # ANTI-FLICKERING: Disable widget updates during init
        # =====================================================
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)  # Prevent transparent flicker
        self.setAutoFillBackground(True)
        
        # Set default style for VTKWidget itself (not container)
        self.setStyleSheet("""
            QVTKRenderWindowInteractor {
                background-color: black;
                border: none;
            }
        """)

        # Sync point interaction state
        self._sync_enabled = False
        self._sync_manager = None
        self._sync_viewer_id = None
        self._sync_dragging = False
        self._sync_observer_ids = []
        self._sync_prev_style = None
        self._sync_style = None
        self._target_cursor = None
        self._sync_last_move_time = 0.0  # throttle mouse-move events
        self._on_slice_changed_cb = None  # Lock Sync callback
        self._stale_scroll_skip_count = 0  # counts stale-drain skips for throttled logging
        self._last_scroll_event_ms = None
        self._timing_log_counter = 0
        self._lag_probe_enabled = os.getenv("AIPACS_SCROLL_LAG_PROBE_ENABLED", "1") == "1"
        self._lag_probe_window_sec = max(3.0, float(os.getenv("AIPACS_SCROLL_LAG_PROBE_WINDOW_SEC", "12") or "12"))
        self._lag_probe_min_samples = max(20, int(os.getenv("AIPACS_SCROLL_LAG_PROBE_MIN_SAMPLES", "40") or "40"))
        self._lag_probe_samples = []
        self._lag_probe_window_start_ms = 0.0
        self._lag_probe_last_dl_active: bool = False  # tracks mode transitions for clean window resets

        # v2.2.3.2.8: Adaptive THROTTLE for scroll coalescing.
        # Previous debounce pattern restarted the timer on every wheel event,
        # adding 16ms latency to EVERY frame even during continuous scrolling.
        # New throttle: render IMMEDIATELY on first scroll after idle, then
        # pace subsequent renders with an adaptive gap (25% of last frame time)
        # so the Qt event loop gets breathing room between expensive renders.
        # Result: 0ms latency for first scroll, ~15fps steady-state on sw GL.
        self._pending_wheel_slice = None
        _coalesce_ms = max(0, int(os.getenv("AIPACS_SCROLL_COALESCE_MS", "16") or "16"))
        self._wheel_coalesce_timer = QTimer(self)
        self._wheel_coalesce_timer.setSingleShot(True)
        self._wheel_coalesce_timer.setInterval(_coalesce_ms)
        self._wheel_coalesce_timer.timeout.connect(self._flush_pending_wheel_slice)
        self._last_render_end_ms = 0.0         # timestamp of last set_slice completion
        self._adaptive_frame_gap_ms = 4.0      # auto-adapts: 25% of last frame time
        self._last_interaction_notify_ms = 0.0  # throttle notify_viewer_interaction

        # v2.2.3.2.9: GC suppression during scroll bursts.
        # Python's cyclic garbage collector can pause the main thread for
        # 100-400ms when it runs a gen-1 or gen-2 collection.  During rapid
        # scrolling, these pauses cause visible stutters (e.g. the 338ms gap
        # observed in v2.2.3.2.8 logs).  Fix: disable GC at the start of a
        # scroll burst and re-enable 300ms after the last render, with a
        # soft gen-0 collect to prevent memory buildup.
        self._gc_suppressed = False
        self._gc_reenable_timer = QTimer(self)
        self._gc_reenable_timer.setSingleShot(True)
        self._gc_reenable_timer.setInterval(300)
        self._gc_reenable_timer.timeout.connect(self._reenable_gc)
        self._last_booster_notify_ms = 0.0  # throttle ImageSliceBooster

    def _reenable_gc(self):
        """Re-enable garbage collection after scroll burst ends."""
        if self._gc_suppressed:
            self._gc_suppressed = False
            gc.enable()
            # Soft gen-0 collect only — fast (~0.1ms) but prevents buildup
            gc.collect(0)

    def _should_log_timing(self, duration_ms: float, stage: str) -> bool:
        """Rate-limit very high-frequency timing logs while keeping slow spikes.

        Always logs slow events and samples normal events every N calls.
        """
        min_ms = float(os.getenv("AIPACS_VIEWER_TIMING_MIN_MS", "35") or "35")
        sample_every = int(os.getenv("AIPACS_VIEWER_TIMING_SAMPLE_EVERY", "25") or "25")
        sample_every = max(1, sample_every)
        self._timing_log_counter += 1

        if duration_ms >= min_ms:
            return True
        if stage in ("set_slice_total", "scroll_event_total") and (self._timing_log_counter % sample_every == 0):
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
            from PacsClient.pacs.patient_tab.zeta_boost.engine import ZetaBoostEngine
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

        self._lag_probe_window_start_ms = now
        self._lag_probe_samples.clear()

    def _schedule_render(self, delay_ms=None):
        """
        ANTI-FLICKERING: Throttled render scheduling
        Prevents multiple renders within the same frame
        """
        if delay_ms is None:
            delay_ms = _RENDER_THROTTLE_MS
            
        if self._render_pending:
            return
            
        # Check if we're rendering too fast
        current_time = time.time() * 1000
        time_since_last = current_time - self._last_render_time
        
        if time_since_last < _RENDER_THROTTLE_MS:
            # Too soon - schedule for later
            actual_delay = max(1, int(_RENDER_THROTTLE_MS - time_since_last))
        else:
            actual_delay = max(1, delay_ms)
        
        self._render_pending = True
        
        # Cancel existing timer if any
        if self._render_timer is not None:
            self._render_timer.stop()
            
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._do_render)
        self._render_timer.start(actual_delay)

    def _do_render(self):
        """
        ANTI-FLICKERING: Execute actual render with safety checks
        """
        render_start = now_ms()
        try:
            # Check if image_viewer exists before rendering
            if self.image_viewer is None:
                logger.debug("[RENDER] Skipped - no image_viewer")
                return
            
            logger.debug("[RENDER] ▶ Starting batched render")
            
            # Update last render time
            self._last_render_time = time.time() * 1000
            
            # Batch all updates together before single render
            t_map = now_ms()
            self.image_viewer.image_reslice.Update()
            self.image_viewer.UpdateDisplayExtent()
            self.image_viewer.update_corners_actors()
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget._do_render",
                stage="vtk_data_mapping",
                start_ms=t_map,
            )
            
            # Update slider without triggering signals
            if hasattr(self, 'slider') and self.slider is not None:
                self.slider.blockSignals(True)
                self.slider.setMaximum(self.image_viewer.get_count_of_slices())
                self.slider.blockSignals(False)
            
            # Single render call at the end
            t_render = now_ms()
            self.image_viewer.Render()
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget._do_render",
                stage="render_complete",
                start_ms=t_render,
            )
            
            # Check if image has valid dimensions (detect incomplete renders)
            if hasattr(self.image_viewer, 'vtk_image_data') and self.image_viewer.vtk_image_data:
                dims = self.image_viewer.vtk_image_data.GetDimensions()
                if dims[0] == 0 or dims[1] == 0:
                    logger.warning(f"[RENDER] ⚠ INCOMPLETE - Image has zero dimensions: {dims}")
                else:
                    logger.debug(f"[RENDER] ✓ Complete - dims: {dims[0]}x{dims[1]}x{dims[2]}")
            
        except Exception as e:
            logger.error(f"[RENDER] ✗ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget._do_render",
                stage="frame_total",
                start_ms=render_start,
            )
            self._render_pending = False

    def get_sync_viewer_id(self):
        if self._sync_viewer_id:
            return self._sync_viewer_id
        if self.id_vtk_widget is not None:
            return f"viewer_{self.id_vtk_widget}"
        return f"viewer_{id(self)}"

    def enable_sync_point(self, sync_manager, viewer_id=None):
        if self.image_viewer is None:
            return

        self._sync_manager = sync_manager
        self._sync_viewer_id = viewer_id or self.get_sync_viewer_id()
        self._sync_enabled = True

        if self._sync_prev_style is None:
            self._sync_prev_style = self.interactor.GetInteractorStyle()

        if self._sync_style is None:
            self._sync_style = self._create_sync_interactor_style()

        self.interactor.SetInteractorStyle(self._sync_style)
        self._set_target_cursor(True)

        if self._sync_observer_ids:
            return

        self._sync_observer_ids.append(
            self.interactor.AddObserver('LeftButtonPressEvent', self._on_sync_left_press)
        )
        self._sync_observer_ids.append(
            self.interactor.AddObserver('MouseMoveEvent', self._on_sync_mouse_move)
        )
        self._sync_observer_ids.append(
            self.interactor.AddObserver('LeftButtonReleaseEvent', self._on_sync_left_release)
        )

    def disable_sync_point(self):
        self._sync_enabled = False
        self._sync_dragging = False

        for obs_id in self._sync_observer_ids:
            try:
                self.interactor.RemoveObserver(obs_id)
            except Exception:
                pass
        self._sync_observer_ids = []

        if self.image_viewer is not None:
            self.image_viewer.hide_sync_point()

        self._set_target_cursor(False)

        if self._sync_prev_style is not None:
            try:
                self.interactor.SetInteractorStyle(self._sync_prev_style)
            except Exception:
                pass
            self._sync_prev_style = None

        self._sync_manager = None

    def _set_target_cursor(self, enabled: bool):
        try:
            if not enabled:
                self.unsetCursor()
                return

            if self._target_cursor is None:
                size = 16
                pixmap = QPixmap(size, size)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setBrush(QColor(220, 38, 38))
                painter.setPen(QColor(220, 38, 38))
                radius = 4
                center = size // 2
                painter.drawEllipse(center - radius, center - radius, radius * 2, radius * 2)
                painter.end()
                self._target_cursor = QCursor(pixmap, center, center)

            self.setCursor(self._target_cursor)
        except Exception:
            pass

    def _create_sync_interactor_style(self):
        widget = self

        class SyncPointInteractorStyle(vtk.vtkInteractorStyleUser):
            def OnLeftButtonDown(self):
                widget._on_sync_left_press(self, None)

            def OnMouseMove(self):
                widget._on_sync_mouse_move(self, None)

            def OnLeftButtonUp(self):
                widget._on_sync_left_release(self, None)

        style = SyncPointInteractorStyle()
        try:
            style.SetInteractor(self.interactor)
        except Exception:
            pass
        return style

    def _on_sync_left_press(self, obj, event):
        if not self._sync_enabled or self.image_viewer is None:
            return

        display_x, display_y = self.interactor.GetEventPosition()
        world_pos = self.image_viewer.pick_world_point(display_x, display_y)
        if world_pos is None:
            return

        self._sync_dragging = True
        self._apply_sync_point(world_pos)
        try:
            self.interactor.SetAbortFlag(1)
        except Exception:
            pass

    def _on_sync_mouse_move(self, obj, event):
        if not self._sync_enabled or not self._sync_dragging or self.image_viewer is None:
            return

        # Throttle: skip if too soon since last processing
        now = time.time() * 1000.0
        if (now - self._sync_last_move_time) < _SYNC_MOVE_THROTTLE_MS:
            return
        self._sync_last_move_time = now

        display_x, display_y = self.interactor.GetEventPosition()
        world_pos = self.image_viewer.pick_world_point(display_x, display_y)
        if world_pos is None:
            return

        self._apply_sync_point(world_pos)
        try:
            self.interactor.SetAbortFlag(1)
        except Exception:
            pass

    def _on_sync_left_release(self, obj, event):
        if not self._sync_enabled:
            return
        self._sync_dragging = False
        try:
            self.interactor.SetAbortFlag(1)
        except Exception:
            pass

    def _apply_sync_point(self, world_pos):
        if self.image_viewer is None:
            return

        orient = self.image_viewer.GetSliceOrientation()
        cur_slice = self.image_viewer.GetSlice()
        logger.debug(
            "[SYNC SOURCE] viewer=%s orient=%d slice=%d → world_pos=(%.2f, %.2f, %.2f)",
            self._sync_viewer_id, orient, cur_slice,
            world_pos[0], world_pos[1], world_pos[2],
        )

        self.image_viewer.set_sync_point(world_pos, adjust_slice=False)

        if self._sync_manager is not None:
            self._sync_manager.set_active_point(world_pos)
            self._sync_manager.notify_cursor_moved(self._sync_viewer_id, world_pos)

    def apply_sync_point_from_manager(self, world_pos, adjust_slice=True):
        if self.image_viewer is None:
            return
        self.image_viewer.set_sync_point(world_pos, adjust_slice=adjust_slice)

    def grow_current_series_inplace(self, new_vtk_image_data, new_metadata=None):
        """Soft-increase slice count for the current series without reset/switch."""
        if not hasattr(self, "image_viewer") or self.image_viewer is None:
            return False

        grown = False
        try:
            grown = self.image_viewer.grow_input_image_inplace(new_vtk_image_data, new_metadata)
            if grown:
                self._schedule_render(1)

            # print('after grow')
            # if grown and hasattr(self, "slider"):
            #     # print('after grow and has slider')
            #     # Only update slider maximum; keep current value unchanged
            #     max_slice = self.get_count_of_slices() - 1
            #     cur = self.slider.value()
            #     self.slider.setMaximum(max_slice)
            #
            #     # If the user was on the last slice and a new slice is added, decide whether to auto-advance
            #     if cur > max_slice:
            #         print('CURRRR')
            #         self.slider.setValue(max_slice)

            # self._schedule_render(1)
            # if grown and hasattr(self, "slider"):
            # max_slice = self.get_count_of_slices() - 1
            # print('max_slice:', max_slice)
            # self.slider.setMaximum(999)
            # if self.slider.maximum() != max_slice:
            #     self.slider.setMaximum(max_slice)

        except Exception as e:
            print(f"[WARN] grow_current_series_inplace failed: {e}")
        return grown

    def set_new_interactorstyle(self, style):
        # Check if image_viewer is initialized (for progressive download)
        if self.image_viewer is None:
            print("⚠️ Cannot set interactor style - viewer not yet initialized")
            return

        self._freeze_render_window()
        _saved_camera_state = self._capture_camera_state()
        try:
            if _saved_camera_state is not None and hasattr(self.image_viewer, "lock_camera_state"):
                self.image_viewer.lock_camera_state(_saved_camera_state, duration_ms=350)
        except Exception:
            pass

        interactorstyle: AbstractInteractorStyle = style(self.image_viewer)

        # load widgets on new interactor style
        interactorstyle = self.set_widgets_on_new_interactorstyle(interactorstyle)

        # replace new interactor style
        self.interactor.SetInteractorStyle(interactorstyle)
        interactorstyle.signal_emitter.interactionOccurred.connect(self.change_container_border)

        self.current_style = interactorstyle

        self._restore_camera_state(_saved_camera_state)
        self._schedule_camera_restore(_saved_camera_state)

        self.image_viewer.Render()

    def _capture_camera_state(self):
        try:
            if self.image_viewer is None:
                return None
            camera = self.image_viewer.renderer.GetActiveCamera()
            if not camera:
                return None
            state = {
                'parallel_scale': camera.GetParallelScale(),
                'position': camera.GetPosition(),
                'focal_point': camera.GetFocalPoint(),
                'view_up': camera.GetViewUp(),
                'clipping_range': camera.GetClippingRange(),
            }
            # ✅ Update protected scale when capturing state
            self._protected_parallel_scale = state['parallel_scale']
            logger.debug(f"[_capture_camera_state] Protected scale saved: {self._protected_parallel_scale}")
            return state
        except Exception:
            return None

    def _restore_camera_state(self, state):
        if not state or self.image_viewer is None:
            return
        try:
            camera = self.image_viewer.renderer.GetActiveCamera()
            if camera:
                camera.SetParallelScale(state['parallel_scale'])
                camera.SetPosition(state['position'])
                # ✅ Update protected scale when restoring state
                self._protected_parallel_scale = state['parallel_scale']
                logger.debug(f"[_restore_camera_state] Protected scale restored: {self._protected_parallel_scale}")
                camera.SetFocalPoint(state['focal_point'])
                camera.SetViewUp(state['view_up'])
                camera.SetClippingRange(state['clipping_range'])
                self.image_viewer.renderer.ResetCameraClippingRange()
        except Exception:
            pass

    def _schedule_camera_restore(self, state):
        if not state or self.image_viewer is None:
            return

        def _restore():
            self._restore_camera_state(state)
            try:
                self.image_viewer.Render()
            except Exception:
                pass

        try:
            QTimer.singleShot(0, _restore)
            QTimer.singleShot(50, _restore)
        except Exception:
            pass

    def _freeze_render_window(self, duration_ms=200):
        if self.image_viewer is None:
            return
        try:
            render_window = self.image_viewer.image_render_window
            interactor = self.image_viewer.image_interactor
            self.image_viewer._suppress_render = True
            render_window.SetAbortRender(1)

            try:
                self._prev_interactor_render = interactor.GetEnableRender()
            except Exception:
                self._prev_interactor_render = None

            try:
                if hasattr(interactor, "EnableRenderOff"):
                    interactor.EnableRenderOff()
            except Exception:
                pass

            def _unfreeze():
                try:
                    render_window.SetAbortRender(0)
                    self.image_viewer._suppress_render = False
                    try:
                        if hasattr(interactor, "EnableRenderOn"):
                            interactor.EnableRenderOn()
                    except Exception:
                        pass
                    try:
                        if self._prev_interactor_render is not None:
                            interactor.SetEnableRender(self._prev_interactor_render)
                    except Exception:
                        pass
                    try:
                        self.image_viewer.Render()
                    except Exception:
                        pass
                except Exception:
                    pass

            QTimer.singleShot(duration_ms, _unfreeze)
        except Exception:
            pass

    def restore_default_interactorstyle(self):
        if self.image_viewer is None:
            return

        self._freeze_render_window()
        _saved_camera_state = self._capture_camera_state()
        try:
            if _saved_camera_state is not None and hasattr(self.image_viewer, "lock_camera_state"):
                self.image_viewer.lock_camera_state(_saved_camera_state, duration_ms=350)
        except Exception:
            pass
            
        default_interactorstyle = self.style

        # load widgets on new interactor style
        default_interactorstyle = self.set_widgets_on_new_interactorstyle(default_interactorstyle)

        self.interactor.SetInteractorStyle(default_interactorstyle)
        self.current_style = default_interactorstyle
        self.current_style.reset_events()  # reset events to default events
        self._ensure_interactor_style_enabled()

        self._restore_camera_state(_saved_camera_state)
        self._schedule_camera_restore(_saved_camera_state)
        self.image_viewer.Render()

    def _ensure_interactor_style_enabled(self):
        try:
            if getattr(self, 'current_style', None) is not None and hasattr(self.current_style, 'On'):
                self.current_style.On()
        except Exception:
            pass
        try:
            if hasattr(self, 'interactor') and self.interactor is not None and hasattr(self.interactor, 'Enable'):
                self.interactor.Enable()
        except Exception:
            pass

    def set_widgets_on_new_interactorstyle(self, new_interactorstyle: AbstractInteractorStyle):
        # Check if current_style exists (for progressive download dummy viewers)
        if self.current_style is not None and hasattr(self.current_style, 'widgets_by_slice'):
            for slice_index in self.current_style.widgets_by_slice.keys():
                new_interactorstyle.widgets_by_slice[slice_index] = self.current_style.widgets_by_slice[slice_index]

            # set slider form before interactorstyle
            if hasattr(self.current_style, 'slider'):
                new_interactorstyle.set_slider_from_ui(self.current_style.slider)
            elif hasattr(self, 'slider') and self.slider is not None:
                new_interactorstyle.set_slider_from_ui(self.slider)
        
        return new_interactorstyle

    def start_process_combine_series(
            self, vtk_image_data1, metadata1, vtk_image_data2, metadata2,
            series_index, id_vtk_widget, metadata_fixed):

        self.image_viewer = CustomCombineImageViewers(
            self.render_window, self.interactor, self.height_viewer, vtk_image_data1, metadata1,
            vtk_image_data2, metadata2, metadata_fixed, self.apply_default_filter, vtk_widget=self)

        self.style = AbstractInteractorStyle(self.image_viewer)
        self.current_style = self.style
        self.interactor.SetInteractorStyle(self.style)

        self.style.signal_emitter.interactionOccurred.connect(self.change_container_border)

        # Removed extra render call - CustomCombineImageViewers handles its own rendering
        self.last_series_show = series_index
        self.id_vtk_widget = id_vtk_widget
        self.save_status_camera(self.image_viewer)

    def start_process_series(self, vtk_image_data, metadata, series_index, id_vtk_widget, metadata_fixed):
        """
        ANTI-FLICKERING: Initialize series without processEvents calls
        """
        # Extract series info for logging
        series_number = metadata.get('series', {}).get('series_number', 'N/A') if metadata else 'N/A'
        series_desc = metadata.get('series', {}).get('series_description', 'Unknown') if metadata else 'Unknown'
        modality = metadata.get('series', {}).get('modality', 'Unknown') if metadata else 'Unknown'
        dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
        
        logger.info(f"[SERIES INIT] ▶ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[SERIES INIT]   Viewer ID: {id_vtk_widget}, Index: {series_index}")
        logger.info(f"[SERIES INIT]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Show spinner immediately (non-blocking)
        self.viewport_spinner.show_loading("Loading...")

        try:
            # =====================================================
            # ANTI-FLICKERING: Disable updates during heavy operation
            # =====================================================
            self.setUpdatesEnabled(False)

            self.image_viewer = ImageViewer2D(self.render_window, self.interactor, self.height_viewer, vtk_image_data,
                                              metadata, metadata_fixed, self.apply_default_filter, vtk_widget=self)
            
            logger.debug(f"[SERIES INIT]   ImageViewer2D created successfully")

            self.style = AbstractInteractorStyle(self.image_viewer)
            self.current_style = self.style
            self.interactor.SetInteractorStyle(self.style)
            self.style.signal_emitter.interactionOccurred.connect(self.change_container_border)

            self.last_series_show = series_index
            self.id_vtk_widget = id_vtk_widget
            self.save_status_camera(self.image_viewer)
            
            # Log final camera state
            if self.image_viewer and self.image_viewer.renderer:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    parallel_scale = camera.GetParallelScale()
                    logger.info(f"[SERIES INIT] ✓ COMPLETE - Final parallel scale: {parallel_scale:.2f}")

        except Exception as e:
            logger.error(f"[SERIES INIT] ✗ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        finally:
            # Re-enable updates
            self.setUpdatesEnabled(True)
            # Hide spinner with small delay to allow final render
            QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)

        # Ensure spinner is properly positioned after viewer is created
        if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
            self.viewport_spinner.spinner.center_in_parent()

    def reset_image(self, vtk_image_data, metadata):  # reload image
        # Extract series info for logging
        series_number = metadata.get('series', {}).get('series_number', 'N/A') if metadata else 'N/A'
        series_desc = metadata.get('series', {}).get('series_description', 'Unknown') if metadata else 'Unknown'
        modality = metadata.get('series', {}).get('modality', 'Unknown') if metadata else 'Unknown'
        dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
        
        logger.info(f"[IMAGE RESET] ▶ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[IMAGE RESET]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Show reset spinner
        self.viewport_spinner.show_reset("Applying reset...")

        try:
            # ✅ Save current camera scale before reset
            saved_scale = None
            try:
                if self.image_viewer and self.image_viewer.renderer:
                    camera = self.image_viewer.renderer.GetActiveCamera()
                    if camera:
                        saved_scale = camera.GetParallelScale()
                        logger.info(f"[IMAGE RESET]   Saved current scale: {saved_scale:.2f}")
            except:
                pass
            
            # delete and set image
            self.image_viewer.reset_image_viewer(vtk_image_data, metadata)

            # select mid-slice for show with default window level
            mid_slice = self.get_count_of_slices() // 2  # Use middle slice like toolbar reset
            # mid_slice = mid_slice - self.image_viewer.skip_slices
            # mid_slice = 0

            self.slider.setValue(mid_slice)
            self.image_viewer.apply_default_window_level(mid_slice)
            
            logger.debug(f"[IMAGE RESET]   Reset to slice {mid_slice} / {self.get_count_of_slices()}")

            # Reset camera to default state (like toolbar reset)
            camera = self.image_viewer.renderer.GetActiveCamera()

            # Set default view up if initial_view_up_camera exists, otherwise use default
            if hasattr(self, 'initial_view_up_camera') and self.initial_view_up_camera:
                camera.SetViewUp(self.initial_view_up_camera)
            else:
                # Default view up for medical images
                camera.SetViewUp(0, -1, 0)

            # Reset camera and apply zoom to fit for proper display
            self.image_viewer.renderer.ResetCamera()
            self.image_viewer.renderer.ResetCameraClippingRange()
            
            # ✅ Always use zoom_to_fit to ensure image fills the viewer properly
            new_scale = self.image_viewer.zoom_to_fit()
            if new_scale:
                self._protected_parallel_scale = new_scale
                logger.info(f"[IMAGE RESET]   Applied zoom_to_fit scale: {new_scale:.2f}")
            else:
                logger.warning(f"[IMAGE RESET]   zoom_to_fit returned None/False")

            self.image_viewer.Render()
            logger.info(f"[IMAGE RESET] ✓ COMPLETE")

        except Exception as e:
            logger.error(f"[IMAGE RESET] ✗ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        finally:
            # Hide spinner after reset is complete
            QTimer.singleShot(300, self.viewport_spinner.hide_loading)

        # Ensure spinner is properly positioned during reset
        if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
            self.viewport_spinner.spinner.center_in_parent()

    def cleanup_image_viewer(self):
        # Check if image_viewer exists before cleanup (for progressive download dummy viewers)
        if self.image_viewer is not None:
            self.image_viewer.cleanup()
            del self.image_viewer
            self.image_viewer = None

        # delete old renderers
        # old_renderer = self.image_viewer.GetRenderer()
        # self.render_window.RemoveRenderer(old_renderer)

        # old_renderer = self.image_viewer.GetRenderer()
        # if old_renderer:
        #     self.render_window.RemoveRenderer(old_renderer)

        # Call cleanup to release everything

        # del self.style
        # self.style = None

        # del self.current_style
        # self.current_style = None

        # Run garbage collection to help free memory
        gc.collect()

    # v2.2.3.1.0: Removed switch_series_backup() — dead code, superseded by switch_series().
    # Was ~72 lines with no callers in the codebase.

    def switch_series(self, vtk_image_data, metadata, series_index, vtk_image_data_2=None, metadata_2=None,
                      metadata_fixed=None):
        """
        ⚡ HIGHLY OPTIMIZED: Series switch with minimal flickering
        - Shows loading spinner immediately with smart messaging
        - Reuses existing viewers when possible (FAST PATH)
        - Batches all VTK operations
        - No processEvents() calls to avoid blocking
        
        Performance gains:
        - Single viewer reuse: ~90% faster than recreation
        - Smart spinner messaging based on series size
        - Batched rendering operations
        """
        # Extract series info for logging
        series_number = metadata.get('series', {}).get('series_number', 'N/A') if metadata else 'N/A'
        series_desc = metadata.get('series', {}).get('series_description', 'Unknown') if metadata else 'Unknown'
        modality = metadata.get('series', {}).get('modality', 'Unknown') if metadata else 'Unknown'
        dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
        is_combined = (vtk_image_data_2 is not None) and (metadata_2 is not None)
        
        logger.info(f"[SERIES SWITCH] ▶ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[SERIES SWITCH]   Index: {series_index}, Combined: {is_combined}")
        logger.info(f"[SERIES SWITCH]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Check this series has showed
        if self.last_series_show == series_index:
            logger.info(f"[SERIES SWITCH] ⏭ SKIP - Already showing series {series_index}")
            return False

        # Discard any pending scroll state from the previous series.
        # Without this, _last_scroll_event_ms stays at the old-series scroll time,
        # making event_queue_delay_ms show 14-17 s on the new series (false alarm).
        # Also prevents a stale _pending_wheel_slice from jumping to the wrong slice
        # the moment the new series finishes loading.
        try:
            self._wheel_coalesce_timer.stop()
            self._gc_reenable_timer.stop()
            self._pending_wheel_slice = None
            self._last_scroll_event_ms = None
            self._stale_scroll_skip_count = 0
            self._last_render_end_ms = 0.0
            self._adaptive_frame_gap_ms = 4.0
            self._last_booster_notify_ms = 0.0
            if self._gc_suppressed:
                self._gc_suppressed = False
                gc.enable()
        except Exception:
            pass

        # Save current camera scale before switch
        saved_scale = None
        try:
            if self.image_viewer and self.image_viewer.renderer:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    saved_scale = camera.GetParallelScale()
                    logger.info(f"[SERIES SWITCH]   Saved current scale: {saved_scale:.2f}")
        except:
            pass

        # 🎬 SHOW SPINNER WITH SMART MESSAGE BASED ON SERIES SIZE
        spinner_message = self._get_smart_spinner_message(vtk_image_data, metadata)
        self.viewport_spinner.show_loading(spinner_message)
        
        # =====================================================
        # ANTI-FLICKERING: Block slider signals AND disable widget updates during switch
        # =====================================================
        if hasattr(self, 'slider') and self.slider is not None:
            self.slider.blockSignals(True)
        self.setUpdatesEnabled(False)
        
        try:
            t_switch = now_ms()
            # OPTIMIZATION: Reuse existing viewer instead of recreating it!
            if self.image_viewer is not None:
                # Viewer already exists - just update the image data
                try:
                    # Check if switching between single/combined viewer types
                    is_combined_new = (vtk_image_data_2 is not None) and (metadata_2 is not None)
                    is_combined_current = isinstance(self.image_viewer, CustomCombineImageViewers)
                    
                    # Clear widgets if current_style exists
                    if hasattr(self, 'current_style') and self.current_style is not None:
                        self.current_style.delete_all_widgets()

                    # If viewer type doesn't match, we need to recreate
                    if is_combined_new != is_combined_current:
                        self.cleanup_image_viewer()
                    else:
                        # Same viewer type - just reset the image data (FAST!)
                        if is_combined_new:
                            # Combined viewer - recreate
                            self.cleanup_image_viewer()
                        else:
                            # Single viewer - use fast reset
                            # ⚡ FAST PATH: Just update image data without full viewer recreation
                            logger.debug(f"[SERIES SWITCH]   Using FAST PATH (viewer reuse)")
                            self.image_viewer.reset_image_viewer(vtk_image_data, metadata)
                            self.image_viewer.apply_default_window_level(self.image_viewer.GetSlice())
                            log_stage_timing(
                                logger,
                                component="viewer",
                                function="VTKWidget.switch_series",
                                stage="vtk_data_mapping",
                                start_ms=t_switch,
                                path="fast",
                            )
                            
                            # ✅ CRITICAL: Update _protected_parallel_scale to match the 
                            # zoom_to_fit scale that reset_image_viewer calculated.
                            # Do NOT restore old saved_scale - it was from a different series
                            # with different dimensions and would make the image appear too
                            # small or too large.
                            try:
                                camera = self.image_viewer.renderer.GetActiveCamera()
                                if camera:
                                    current_scale = camera.GetParallelScale()
                                    self._protected_parallel_scale = current_scale
                                    logger.info(f"[SERIES SWITCH]   Updated protected scale to zoom_to_fit result: {current_scale:.2f}")
                            except:
                                logger.warning(f"[SERIES SWITCH]   Failed to update protected scale")
                            
                            self.last_series_show = series_index
                            self.save_status_camera(self.image_viewer)
                            
                            # Log final camera state
                            try:
                                camera = self.image_viewer.renderer.GetActiveCamera()
                                final_scale = camera.GetParallelScale() if camera else 0
                                logger.info(f"[SERIES SWITCH] ✓ COMPLETE (FAST) - Final scale: {final_scale:.2f}")
                            except:
                                logger.info(f"[SERIES SWITCH] ✓ COMPLETE (FAST)")
                            
                            # Re-enable updates and unblock slider signals, then hide spinner
                            self.setUpdatesEnabled(True)
                            if hasattr(self, 'slider') and self.slider is not None:
                                self.slider.blockSignals(False)
                            QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)
                            log_stage_timing(
                                logger,
                                component="viewer",
                                function="VTKWidget.switch_series",
                                stage="series_switch_total",
                                start_ms=t_switch,
                                path="fast",
                            )
                            return True
                            
                except Exception as e:
                    logger.warning(f"[SERIES SWITCH] Fast path failed, falling back to recreation: {e}")
                    import traceback
                    traceback.print_exc()
                    self.cleanup_image_viewer()

            # Create new viewer (first time or fallback)
            # ⚡ BATCHED CREATION: All operations grouped together
            logger.debug(f"[SERIES SWITCH]   Using SLOW PATH (viewer recreation)")
            
            if (vtk_image_data_2 is not None) and (metadata_2 is not None):
                logger.debug(f"[SERIES SWITCH]   Creating CustomCombineImageViewers")
                self.image_viewer = CustomCombineImageViewers(
                    self.render_window, self.interactor, self.height_viewer, vtk_image_data1=vtk_image_data,
                    metadata1=metadata,
                    vtk_image_data2=vtk_image_data_2, metadata2=metadata_2, metadata_fixed=metadata_fixed,
                    apply_default_filter=self.apply_default_filter, vtk_widget=self)
            else:
                logger.debug(f"[SERIES SWITCH]   Creating ImageViewer2D")
                self.image_viewer = ImageViewer2D(self.render_window, self.interactor, self.height_viewer, vtk_image_data,
                                                  metadata, metadata_fixed, self.apply_default_filter, vtk_widget=self)

            self.image_viewer.apply_default_window_level(self.image_viewer.GetSlice())
            
            # Add new renderer
            new_renderer = self.image_viewer.GetRenderer()
            self.render_window.AddRenderer(new_renderer)

            # Set interactor style again
            self.style = AbstractInteractorStyle(self.image_viewer)
            self.interactor.SetInteractorStyle(self.style)
            self.style.signal_emitter.interactionOccurred.connect(self.change_container_border)
            self.current_style = self.style
            self._ensure_interactor_style_enabled()

            # ⚡ SINGLE BATCHED RENDER at the end (not multiple renders)
            logger.debug(f"[SERIES SWITCH]   UpdateDisplayExtent + Render")
            t_map = now_ms()
            self.image_viewer.UpdateDisplayExtent()
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget.switch_series",
                stage="vtk_data_mapping",
                start_ms=t_map,
                path="slow",
            )
            t_render = now_ms()
            self.render_window.Render()
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget.switch_series",
                stage="vtk_render_pipeline",
                start_ms=t_render,
                path="slow",
            )

            self.last_series_show = series_index
            self.save_status_camera(self.image_viewer)

            # Log final camera state
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                final_scale = camera.GetParallelScale() if camera else 0
                logger.info(f"[SERIES SWITCH] ✓ COMPLETE (SLOW) - Final scale: {final_scale:.2f}")
            except:
                logger.info(f"[SERIES SWITCH] ✓ COMPLETE (SLOW)")
            
        except Exception as e:
            logger.error(f"[SERIES SWITCH] ✗ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
            
        finally:
            # =====================================================
            # ANTI-FLICKERING: Re-enable updates AND unblock slider signals in finally block
            # =====================================================
            self.setUpdatesEnabled(True)
            if hasattr(self, 'slider') and self.slider is not None:
                self.slider.blockSignals(False)
            
        # Hide spinner with delay to allow render to complete
        QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)

        # Ensure spinner is properly positioned after viewer is created
        if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
            self.viewport_spinner.spinner.center_in_parent()

        log_stage_timing(
            logger,
            component="viewer",
            function="VTKWidget.switch_series",
            stage="series_switch_total",
            start_ms=t_switch,
            path="slow",
        )

        return True
    
    def _get_smart_spinner_message(self, vtk_image_data, metadata):
        """
        Generate smart spinner message based on series size
        Shows different messages for small/medium/large series
        """
        try:
            # Get number of slices
            if vtk_image_data:
                dims = vtk_image_data.GetDimensions()
                num_slices = dims[2] if len(dims) > 2 else 1
                
                # Get series name from metadata if available
                series_name = ""
                if metadata and isinstance(metadata, dict):
                    series_name = metadata.get('series', {}).get('series_name', '')
                
                # Adaptive messages based on size
                if num_slices > 200:
                    return f"📊 Loading large series... ({num_slices} images)"
                elif num_slices > 100:
                    return f"📷 Switching series... ({num_slices} images)"
                elif num_slices > 50:
                    return " Switching series..."
                else:
                    return "Switching series..."
        except:
            pass
        
        return "Switching series..."

    def get_count_of_slices(self):
        if self.image_viewer is None:
            return 0
        return self.image_viewer.get_count_of_slices()

    def _flush_pending_wheel_slice(self):
        """Render the latest coalesced scroll position (throttle callback).

        v2.2.3.2.8: Adaptive throttle replaces debounce.
        Called either immediately from wheelEvent (leading-edge) or by the
        coalesce timer (paced renders).  Tracks frame timing and auto-adjusts
        the inter-frame gap so the Qt event loop gets breathing room between
        expensive software-GL renders without adding unnecessary latency.
        """
        idx = self._pending_wheel_slice
        self._pending_wheel_slice = None
        if idx is not None:
            # v2.2.3.2.7: Reset scroll timestamp to "now" to break stale-drain
            # re-arm loop (see commit 8fb6629 for full explanation).
            _t_start = now_ms()
            self._last_scroll_event_ms = _t_start
            logger.debug(f"[SCROLL_COALESCE] flush slice={idx}")
            self.set_slice(idx)
            _t_end = now_ms()
            self._last_render_end_ms = _t_end
            # Adaptive gap: 25% of frame time, clamped [4ms, 50ms].
            # Gives Qt event loop breathing room proportional to render cost.
            _frame_ms = max(1.0, _t_end - _t_start)
            self._adaptive_frame_gap_ms = max(4.0, min(50.0, _frame_ms * 0.25))
            # v2.2.3.2.9: Schedule GC re-enable 300ms after last render.
            # Restarts on every render so GC stays suppressed during the burst.
            self._gc_reenable_timer.start()
        # Re-arm if more scroll events queued during the render block
        if self._pending_wheel_slice is not None:
            self._wheel_coalesce_timer.setInterval(max(1, int(self._adaptive_frame_gap_ms)))
            self._wheel_coalesce_timer.start()

    def set_slice(self, slice_index):
        if self.image_viewer is None:
            return
        t_set_slice = now_ms()
        queue_delay_ms = -1.0
        if self._last_scroll_event_ms is not None:
            queue_delay_ms = max(0.0, t_set_slice - self._last_scroll_event_ms)
            if self._should_log_timing(queue_delay_ms, "event_queue_delay"):
                logger.info(
                    "viewer-scroll stage=event_queue_delay_ms duration_ms=%.2f",
                    queue_delay_ms,
                    extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "event_queue_delay"},
                )

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
        if queue_delay_ms > _STALE_SCROLL_MS:
            try:
                if self.slider is not None:
                    self.slider.blockSignals(True)
                    self.slider.setValue(slice_index)
                    self.slider.blockSignals(False)
            except Exception:
                pass
            # Store the position so the coalesce timer renders it once
            self._pending_wheel_slice = slice_index
            try:
                if not self._wheel_coalesce_timer.isActive():
                    self._wheel_coalesce_timer.start()
            except Exception:
                pass
            self.image_viewer.last_index_slice_saved = slice_index
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

        # ✅ CRITICAL: Save current camera zoom before slice change
        saved_scale = None
        try:
            camera = self.image_viewer.renderer.GetActiveCamera()
            if camera:
                saved_scale = camera.GetParallelScale()
                # Update protected scale only if not already set or if changed by user zoom
                if self._protected_parallel_scale is None or abs(saved_scale - self._protected_parallel_scale) > 0.01:
                    self._protected_parallel_scale = saved_scale
                logger.debug(f"[set_slice] Protected scale={self._protected_parallel_scale}")
        except:
            pass
        
        t_slice_apply = now_ms()
        self.image_viewer.set_slice(slice_index)
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
        
        # ✅ CRITICAL: Force restore camera zoom after slice change
        # Phase 1 fix (v2.2.3.1.6): compare against _protected_parallel_scale
        # (the user's last explicitly set zoom), not against saved_scale which
        # was captured at the top of this call and may already include VTK
        # floating-point drift.  Tolerance widened from 0.001 → 0.05 so minor
        # per-frame FP jitter in SetSlice() no longer fires a second Render()
        # on every scroll (was measured as 60–80ms extra per scroll in Mode B).
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
                    logger.warning(f"[set_slice] Zoom change detected! scale={current_scale:.4f} → reverting to {_ref_scale:.4f}")
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
        except:
            pass

        # Notify interactor style if it's a ruler style
        try:
            style = self.interactor.GetInteractorStyle()
            if hasattr(style, 'update_slice'):
                style.update_slice()

        except Exception as e:
            logger.debug(f"Error updating on slice change: {e}")

        self._update_overlay_extent()

        # Lock Sync callback — fires on EVERY slice change regardless of source
        if self._on_slice_changed_cb is not None:
            try:
                self._on_slice_changed_cb(self)
            except Exception:
                pass

        # v2.2.3.1.8: Notify ImageSliceBooster so the prefetch window follows scroll.
        # v2.2.3.2.9: Throttle to once per 200ms instead of every set_slice.
        # Each call re-centers the prefetch window and may start background I/O.
        # During rapid scroll (10-15 renders/sec), calling on every slice wastes
        # CPU scheduling prefetch that will be immediately invalidated by the
        # next scroll.  200ms spacing lets the booster keep up without waste.
        try:
            _t_now = now_ms()
            if _t_now - self._last_booster_notify_ms >= 200.0:
                self._last_booster_notify_ms = _t_now
                _vc = getattr(getattr(self, 'patient_widget', None), 'viewer_controller', None)
                if _vc is not None:
                    _booster = getattr(_vc, '_image_slice_booster', None)
                    if _booster is not None and _booster.is_active:
                        _sn = _booster.active_series
                        if _sn is not None:
                            _booster.on_slice_changed(_sn, slice_index)
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

    def save_status_camera(self, image_viewer):
        camera = image_viewer.renderer.GetActiveCamera()
        self.initial_view_up_camera = camera.GetViewUp()
        # self.initial_position = camera.GetPosition()
        # self.initial_focal_point = camera.GetFocalPoint()
        # self.initial_parallel_scale = camera.GetParallelScale()

    #####################################################################################

    def wheelEvent(self, event):
        """
        Handle mouse wheel scrolling for slice navigation within current series.
        CRITICAL: Prevents VTK zoom by consuming the event and NOT calling super().wheelEvent()
        """
        # ✅ ALWAYS log to confirm this method is being called
        t_event_receive = now_ms()
        self._last_scroll_event_ms = t_event_receive
        # v2.2.3.2.9: Suppress GC during scroll burst to eliminate ~300ms
        # gen-1/gen-2 collection pauses that cause visible stutters.
        if not self._gc_suppressed and gc.isenabled():
            gc.disable()
            self._gc_suppressed = True
        # v2.2.3.2.8: Throttle notify_viewer_interaction to once per 500ms
        # instead of per-wheel-event.  Each call creates a QTimer.singleShot
        # and toggles ZetaBoost pausing — wasteful at 10-15 events/sec.
        try:
            if t_event_receive - self._last_interaction_notify_ms > 500.0:
                self._last_interaction_notify_ms = t_event_receive
                viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
                if viewer_controller is not None and hasattr(viewer_controller, "notify_viewer_interaction"):
                    viewer_controller.notify_viewer_interaction(reason="wheel_scroll")
        except Exception:
            pass
        logger.debug(f"[WHEEL] Called - image_viewer={'present' if self.image_viewer else 'None'}, slider={'present' if self.slider else 'None'}")
        
        try:
            # Check if image_viewer exists with valid slider
            if self.image_viewer is None or self.slider is None:
                # No image or slider - consume event to prevent VTK zoom
                logger.debug("[WHEEL] No image_viewer or slider - consuming event")
                event.accept()
                return
            
            delta = event.angleDelta().y()
            max_slice = self.get_count_of_slices()
            
            logger.debug(f"[WHEEL] delta={delta}, max_slice={max_slice}")
            
            # Nothing to scroll through - still consume to prevent VTK zoom
            if max_slice <= 1:
                logger.debug("[WHEEL] max_slice <= 1 - consuming event")
                event.accept()
                return
            
            # Calculate adaptive step based on number of slices
            N = max_slice
            
            if N < 50:
                step = 1
            elif N < 300:
                # Linear interpolation: step = 1 + (N - 50) / 250 * 4
                step = max(1, int(1 + (N - 50) / 250 * 4))
            else:
                # Large stacks: target ~300 visible slices
                step = max(1, int(N / 300))
            
            # Invert direction for natural scrolling
            if delta > 0:
                step = -step
            elif delta < 0:
                step = step
            else:
                step = 0
            
            # Calculate next slice index
            current_slice = self.image_viewer.GetSlice()
            skip_slices = getattr(self.image_viewer, 'skip_slices', 0)
            next_slice = current_slice + skip_slices + step
            
            # Clamp to valid range [0, N-1]
            next_slice = max(0, min(next_slice, max_slice - 1))
            
            logger.debug(f"[WHEEL] current={current_slice}, next={next_slice}, step={step}")
            
            # v2.2.3.2.8: Adaptive THROTTLE replaces debounce.
            # Debounce restarted the 16ms timer on every event, adding 16ms
            # latency to EVERY frame.  Throttle renders immediately when
            # enough time has passed since the last render (leading-edge),
            # otherwise starts a timer for the remaining gap.  The adaptive
            # gap (25% of last frame time) auto-tunes to hardware speed.
            self._pending_wheel_slice = next_slice
            self.slider.blockSignals(True)
            self.slider.setValue(next_slice)   # update UI position without triggering set_slice
            self.slider.blockSignals(False)

            if not self._wheel_coalesce_timer.isActive():
                _since_last = t_event_receive - self._last_render_end_ms
                if _since_last >= self._adaptive_frame_gap_ms:
                    # Enough time since last render → render immediately (0ms latency)
                    self._flush_pending_wheel_slice()
                else:
                    # Within adaptive gap → schedule for remaining time
                    _remaining = max(1, int(self._adaptive_frame_gap_ms - _since_last))
                    self._wheel_coalesce_timer.setInterval(_remaining)
                    self._wheel_coalesce_timer.start()
            # else: timer already running, will fire and render the latest pending

            # v2.2.3.2.8: Skip per-event ruler/border/camera checks.
            # set_slice() already handles ruler update (style.update_slice),
            # camera zoom protection, and overlay sync during the actual render.
            # Running them per-wheel-event operates on stale state and wastes
            # 3-8ms per event × 3-5 queued events = 9-40ms per frame cycle.

            # ✅ CRITICAL: CONSUME the event - DO NOT let parent handle it
            event.accept()
            
        except Exception as e:
            # ✅ Even on error, CONSUME the event to prevent VTK zoom fallback
            logger.warning(f"[WHEEL] Exception (consuming to prevent zoom): {e}")
            event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

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
                    print("[SHORTCUT] 'G' pressed - Generating Curved MPR...")
                    point_count = self.image_viewer.curved_mpr_module.get_point_count()
                    if point_count >= 2:
                        self.image_viewer.generate_and_show_curved_mpr()
                        print(f"✓ Curved MPR generated with {point_count} points")
                    else:
                        print(f"⚠️ Need at least 2 points (have {point_count})")
                    event.accept()
                    return
                
                # C key: Clear all points
                elif key == Qt.Key_C and modifiers == Qt.NoModifier:
                    print("[SHORTCUT] 'C' pressed - Clearing points...")
                    self.image_viewer.curved_mpr_module.reset()
                    self.image_viewer._clear_curved_mpr_visuals()
                    print("✓ All points cleared")
                    event.accept()
                    return
                
                # ESC key: Exit curved MPR mode
                elif key == Qt.Key_Escape:
                    print("[SHORTCUT] 'ESC' pressed - Exiting Curved MPR mode...")
                    self.image_viewer.enable_curved_mpr_mode(False)
                    print("✓ Curved MPR mode deactivated")
                    event.accept()
                    return
        
        except Exception as e:
            print(f"Error in keyPressEvent: {e}")
        
        # Pass to parent if not handled
        super().keyPressEvent(event)
    
    def dropEvent(self, event):
        data = event.mimeData().text()
        print("Dropped data:", data)
        event.acceptProposedAction()

        try:
            data = int(data)
            # Dropped from thumbnails series
            # Change series with drag and drop - async for smooth UI
            self.change_container_border()
            
            # 🎬 Show loading spinner immediately when series is dropped
            # This provides instant visual feedback to the user
            self.viewport_spinner.show_loading("Switching series...")
            
            # Use QTimer to defer the call and avoid blocking during drop
            # This allows the spinner to display before the expensive series switch
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.method_change_series_on_viewer(
                series_index=int(data), 
                flag_change_selected_widget=False,
                vtk_widget=self, 
                slider=self.slider
            ))
            
        except Exception as e:
            # Dropped segmentation out of app
            if event.mimeData().hasUrls():
                data = event.mimeData().urls()[0].toLocalFile()
                print(f'dropped file url: {data}\n')
                vtk_segmentation_img = read_segment_nifti(data)
                self.overlay(vtk_segmentation_img, color=(0.0, 1.0, 0.0), opacity=0.35, is_label=True)
                print('add segmentation successful.')

    def overlay(self, vtk_image_data: vtk.vtkImageData, color=(1.0, 0.0, 0.0), opacity=0.4, is_label=True):
        """
        Overlays an image on the current image_viewer.
        - vtk_image_data: vtk.vtkImageData
        - color: (r,g,b) in [0..1]
        - opacity: overlay opacity (for non-zero pixels)
        - is_label: if True, zero becomes transparent and non-zero is colored.
        """
        if not hasattr(self, "image_viewer") or self.image_viewer is None:
            return

        self.clear_overlay()
        self._overlay = {}

        # 1) Reslice overlay to match base image
        ov_reslice = vtk.vtkImageReslice()
        ov_reslice.SetInputData(vtk_image_data)

        # # Same reslice axes matrix as the base image
        # axes = self.image_viewer.image_reslice.GetResliceAxes()
        # if axes is not None:
        #     ov_reslice.SetResliceAxes(axes)

        # Get geometry from current image (origin/spacing/extent)
        # ov_reslice.SetInformationInput(self.image_viewer.vtk_image_data)
        # ov_reslice.SetOutputOrigin(self.image_viewer.vtk_image_data.GetOrigin())

        # # Interpolation: nearest for masks, linear for normal images
        # if is_label:
        #     ov_reslice.SetInterpolationModeToNearestNeighbor()
        # else:
        #     ov_reslice.SetInterpolationModeToLinear()

        # ov_reslice.SetInterpolationModeToNearestNeighbor()
        # ov_reslice.SetInterpolationModeToLinear()

        ov_reslice.Update()
        self._overlay["reslice"] = ov_reslice

        # 2) Color/alpha mapping
        #   a) Label mask: LUT with 0 transparent, others colored/opacity
        #   b) Normal image: WL/WW could be applied; using simple LUT for now
        rng = ov_reslice.GetOutput().GetScalarRange()
        lut = vtk.vtkLookupTable()
        # Set a reasonable LUT size

        table_size = max(256, int(rng[1] - rng[0] + 1))
        lut.SetNumberOfTableValues(table_size)
        lut.Build()

        if is_label:
            # Index 0 fully transparent
            lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)
            # Other indices with color/opacity
            for i in range(1, table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))
        else:
            # All values with mild opacity; WL/WW can be customized if needed
            for i in range(table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))

        map_colors = vtk.vtkImageMapToColors()
        map_colors.SetLookupTable(lut)
        map_colors.SetInputConnection(ov_reslice.GetOutputPort())
        map_colors.Update()
        self._overlay["map"] = map_colors

        # 3) Overlay image actor
        actor = vtk.vtkImageActor()
        actor.GetMapper().SetInputConnection(map_colors.GetOutputPort())
        actor.SetPickable(False)
        self.image_viewer.GetRenderer().AddActor(actor)
        self._overlay["actor"] = actor

        # 4) Sync extent with current slice and orientation
        self._update_overlay_extent()

        # 5) Render
        self._schedule_render(1)

    def clear_overlay(self):
        """Remove overlay from renderer and release references."""
        if hasattr(self, "_overlay") and self._overlay:
            try:
                actor = self._overlay.get("actor")
                if actor:
                    self.image_viewer.GetRenderer().RemoveActor(actor)
            except Exception:
                pass
        self._overlay = {}

    def _update_overlay_extent(self):
        """Set overlay DisplayExtent based on current slice and orientation."""
        if not hasattr(self, "_overlay") or not self._overlay:
            return
        actor = self._overlay.get("actor")
        ov_img = self._overlay.get("reslice").GetOutput()
        base_img = self.image_viewer.vtk_image_data
        if not actor or not ov_img or not base_img:
            return

        # Get dimensions and current slice from the main viewer
        slice_idx = self.image_viewer.GetSlice()
        dims = base_img.GetDimensions()
        # slice_idx = dims[2] - (slice_idx + 2)

        extent = (0, dims[0] - 1, 0, dims[1] - 1, slice_idx, slice_idx)
        # extent = (0, dims[0], 0, dims[1], slice_idx, slice_idx)

        actor.SetDisplayExtent(*extent)

    def set_method_change_series_on_drop(self, method_change_series_on_viewer):
        self.method_change_series_on_viewer = method_change_series_on_viewer

    def set_method_change_container_border(self, method_change_container_border):
        self.method_change_container_border = method_change_container_border

    def change_container_border(self):
        self.method_change_container_border(self.id_vtk_widget)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        try:
            # height = self.height()
            self.height_viewer = self.height()
            height = self.height_viewer

            self.image_viewer.update_corners_actors(update_just_zoom=True, window_height=height)
            self.image_viewer.update_corners_actors_pos(height)

            # Update spinner position if it exists
            if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
                self.viewport_spinner.spinner.center_in_parent()
        except:
            pass

    def cleanup_widget(self):
        """Cleanup widget resources including spinner"""
        try:
            if hasattr(self, 'viewport_spinner'):
                self.viewport_spinner.cleanup()
        except Exception as e:
            print(f"Error cleaning up VTKWidget: {e}")