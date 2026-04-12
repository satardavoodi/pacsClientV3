"""
Rendering mixin for VTKWidget.
schedule_render, do_render, freeze_render_window.
"""
from __future__ import annotations
import logging
import time
from PySide6.QtCore import QTimer
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _RENDER_THROTTLE_MS,
    _SPINNER_HIDE_DELAY_MS,
)

logger = logging.getLogger(__name__)


class _VWRenderMixin:
    """Render throttling: schedule, flush, freeze for batch updates."""

    def _schedule_render(self, delay_ms=None):
        """
        ANTI-FLICKERING: Throttled render scheduling
        Prevents multiple renders within the same frame
        """
        # Qt bridge mode: no VTK rendering needed
        if self._qt_bridge_active:
            return

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
            
            logger.debug("[RENDER] ├تظô┬╢ Starting batched render")
            
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
                self.slider.setMaximum(max(0, self.get_count_of_slices() - 1))
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
                    logger.warning(f"[RENDER] ├ت┌ّ┬ب INCOMPLETE - Image has zero dimensions: {dims}")
                else:
                    logger.debug(f"[RENDER] ├ت┼ôظ£ Complete - dims: {dims[0]}x{dims[1]}x{dims[2]}")
            
        except Exception as e:
            logger.error(f"[RENDER] ├ت┼ôظ¤ FAILED - Error: {e}")
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

    def _freeze_render_window(self, duration_ms=200):
        if self.image_viewer is None or self._qt_bridge_active:
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
