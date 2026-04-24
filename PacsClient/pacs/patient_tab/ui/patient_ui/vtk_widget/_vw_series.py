"""
Series management mixin for VTKWidget.
switch_series, start_process_series, reset_image, cleanup_image_viewer.
"""
from __future__ import annotations
import gc
import logging
import os
import time
import threading
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from modules.viewer.advanced.viewer_2d import ImageViewer2D, CustomCombineImageViewers
from modules.viewer.interactor_styles import AbstractInteractorStyle
from modules.viewer.viewer_backend_config import (
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    BACKEND_VTK,
    resolve_viewer_backend,
    load_viewer_backend,
)
from modules.viewer.fast.lazy_volume_registry import (
    acquire_loader,
    release_loader,
)
from modules.viewer.gpu_boost import resolve_gpu_boost_plan
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _create_qt_viewer_bridge,
    _SPINNER_HIDE_DELAY_MS,
)
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class _VWSeriesMixin:
    """Series lifecycle: start_process_series, switch_series, reset, cleanup."""

    _QT_STARTUP_REFIT_DELAYS_MS = (0, 50, 120, 220)

    def _queue_qt_startup_refit(self, bridge) -> None:
        """Re-fit a freshly created Qt viewer on the next event-loop tick.

        The initial zoom-to-fit in ``_start_qt_viewer`` can run before the
        target viewport has fully settled into its final layout geometry.
        When that happens, the last series dropped into a layout may appear
        under-zoomed until a later UI event triggers another presentation sync.

        Queue a short guarded refit burst for fresh Qt starts only.
        In-place Qt refreshes continue to use the controller-managed refit path.

        ``QTimer.singleShot(0)`` fixed the original under-fit case, but the
        Block B regression in ``log 83`` shows there are still switch paths
        where the first follow-up runs before the layout has fully stabilized.
        A tiny bounded retry window keeps the first visible image authoritative
        while making the startup refit resilient to one or two late layout
        passes.
        """

        # v2.3.7: reset the refit-dedupe signature so the first delayed refit
        # in this burst always runs (host may have reflowed since the initial
        # zoom_to_fit in _start_qt_viewer). Subsequent delays with identical
        # host geometry will dedupe in _sync_qt_viewer_presentation.
        try:
            self._last_refit_signature = None
        except Exception:
            pass

        def _apply(delay_ms: int) -> None:
            try:
                if not bool(getattr(self, '_qt_bridge_active', False)):
                    return
                if getattr(self, 'image_viewer', None) is not bridge:
                    return
                qt_viewer = getattr(self, '_qt_viewer_widget', None)
                if qt_viewer is not None:
                    try:
                        qt_viewer.setGeometry(self.rect())
                    except Exception:
                        pass
                self._sync_qt_viewer_presentation(refit_view=True)
                if qt_viewer is not None:
                    try:
                        qt_viewer.repaint()
                    except Exception:
                        pass
                logger.info(
                    "[QT_PRESENTATION] startup_refit delay_ms=%d host=%dx%d",
                    int(delay_ms),
                    int(max(0, self.width())),
                    int(max(0, self.height())),
                )
            except Exception as exc:
                logger.debug("[QT_PRESENTATION] deferred startup refit failed: %s", exc)

        for delay_ms in self._QT_STARTUP_REFIT_DELAYS_MS:
            try:
                QTimer.singleShot(int(delay_ms), lambda d=delay_ms: _apply(int(d)))
            except Exception:
                _apply(int(delay_ms))

    def _sync_qt_viewer_presentation(self, *, refit_view: bool = False) -> None:
        """Keep the FAST Qt child viewer aligned with the host widget.

        Drag-drop and layout churn can resize/reflow the parent viewer without
        necessarily going through a clean same-series recreation path. In FAST
        mode the Qt child widget is an overlay, so stale child geometry or stale
        fit state shows up as an image that occupies only a fraction of the
        target layout.

        This helper centralizes the safe presentation sync steps:
        - resize the Qt child to the current host rect
        - keep the child and slider stacked correctly
        - optionally re-apply zoom-to-fit and refresh the protected scale
        """
        qt_viewer = getattr(self, '_qt_viewer_widget', None)
        if qt_viewer is None:
            return
        try:
            qt_viewer.setGeometry(self.rect())
            qt_viewer.raise_()
            qt_viewer.updateGeometry()
            qt_viewer.update()
            if self.slider is not None:
                self.slider.raise_()
        except Exception:
            pass

        if not refit_view:
            return

        # v2.3.7: dedupe redundant zoom_to_fit within a refit burst. Log 96
        # showed 4 identical zoom_to_fit scale=324.64 calls during startup
        # (host=425x554 on all 4). `_last_refit_signature` is cleared at the
        # start of `_queue_qt_startup_refit` so the first real refit runs;
        # subsequent refits on an unchanged host skip the expensive call.
        try:
            host_size = (int(self.width()), int(self.height()))
        except Exception:
            host_size = None

        if host_size is not None:
            last_sig = getattr(self, '_last_refit_signature', None)
            if last_sig is not None and last_sig == host_size:
                logger.debug(
                    "[QT_PRESENTATION] zoom_to_fit skipped (dedupe) host=%dx%d",
                    host_size[0], host_size[1],
                )
                return

        try:
            new_scale = self.image_viewer.zoom_to_fit()
            if new_scale:
                self._protected_parallel_scale = float(new_scale)
                if host_size is not None:
                    self._last_refit_signature = host_size
                # Log components for zoom diagnosis (host geometry + bridge state)
                try:
                    qv = getattr(self.image_viewer, 'qt_viewer', None)
                    img_w = getattr(qv, '_image_width', '?') if qv else '?'
                    img_h = getattr(qv, '_image_height', '?') if qv else '?'
                    sx = getattr(qv, '_display_scale_x', '?') if qv else '?'
                    sy = getattr(qv, '_display_scale_y', '?') if qv else '?'
                    zoom = getattr(qv, '_zoom', '?') if qv else '?'
                    logger.info(
                        "[QT_PRESENTATION] zoom_to_fit scale=%.2f"
                        " host=%dx%d img=%sx%s scale_xy=(%.3f,%.3f) zoom=%.4f",
                        float(new_scale), host_size[0], host_size[1] if host_size else 0,
                        img_w, img_h,
                        float(sx) if isinstance(sx, float) else 0.0,
                        float(sy) if isinstance(sy, float) else 0.0,
                        float(zoom) if isinstance(zoom, float) else 0.0,
                    )
                except Exception:
                    logger.info("[QT_PRESENTATION] zoom_to_fit scale=%.2f", float(new_scale))
        except Exception as exc:
            logger.debug("[QT_PRESENTATION] zoom_to_fit failed: %s", exc)

    def _refresh_qt_series_inplace(self, vtk_image_data, metadata, series_index) -> bool:
        """Refresh an already-visible Qt series without resetting to the midpoint.

        This is used when the same series is rebound with a different slice count
        (for example partial-download -> fuller on-disk series). Recreating the
        Qt bridge would re-center at the middle slice, which feels like a forward
        or backward jump during active stack drag.
        """
        bridge = getattr(self, 'image_viewer', None)
        if not (self._qt_bridge_active and bridge is not None and hasattr(bridge, 'reset_image_viewer')):
            return False

        try:
            current_slice = int(bridge.GetSlice())
        except Exception:
            current_slice = 0

        try:
            bridge.reset_image_viewer(vtk_image_data, metadata, preserve_slice=current_slice)
            target_slice = max(0, min(current_slice, max(0, self.get_count_of_slices() - 1)))
            if self.slider is not None:
                try:
                    self.slider.blockSignals(True)
                    self.slider.setValue(target_slice)
                finally:
                    self.slider.blockSignals(False)
            bridge.apply_default_window_level(target_slice)
            bridge.set_slice(target_slice)
            self.last_series_show = series_index
            self._sync_progressive_available_after_switch()
            self._sync_qt_viewer_presentation(refit_view=False)
            self._qt_switch_refit_applied = False
            self.save_status_camera(bridge)
            logger.info(
                "[SERIES SWITCH] COMPLETE (Qt refresh) - preserved slice=%d/%d",
                target_slice,
                self.get_count_of_slices(),
            )
            return True
        except Exception as exc:
            logger.warning("[SERIES SWITCH] Qt in-place refresh failed: %s", exc)
            return False

    def _get_loaded_slice_count_for_progressive_sync(self) -> int:
        """Return the currently loaded slice count without progressive-total overrides."""
        image_viewer = getattr(self, 'image_viewer', None)
        if image_viewer is not None:
            for attr_name in ('_slice_count', 'slice_count'):
                try:
                    raw_count = int(getattr(image_viewer, attr_name, 0) or 0)
                except Exception:
                    raw_count = 0
                if raw_count > 0:
                    return raw_count

            try:
                raw_count = int(image_viewer.get_count_of_slices())
            except Exception:
                raw_count = 0
            if raw_count > 0:
                return raw_count

            try:
                vtk_image_data = getattr(image_viewer, 'vtk_image_data', None)
                dims = vtk_image_data.GetDimensions() if vtk_image_data is not None else None
                raw_count = int(dims[2]) if dims and len(dims) > 2 else 0
            except Exception:
                raw_count = 0
            if raw_count > 0:
                return raw_count

        try:
            raw_count = int(getattr(self._lazy_loader, 'slice_count', 0) or 0)
        except Exception:
            raw_count = 0
        if raw_count > 0:
            return raw_count

        return 0

    def _sync_progressive_available_after_switch(self) -> None:
        """Seed progressive availability from slices already loaded on disk."""
        if not bool(getattr(self, '_progressive_mode', False)):
            return
        try:
            available = int(self._get_loaded_slice_count_for_progressive_sync())
        except Exception:
            available = 0
        if available <= 0:
            return
        try:
            self.update_available_slice_count(available)
        except Exception as exc:
            logger.debug(
                "[SERIES SWITCH] progressive availability sync failed viewer=%s available=%s: %s",
                getattr(self, 'id_vtk_widget', '?'),
                available,
                exc,
            )

    def _h7_p6_log(self, path_label: str) -> None:
        """[H7-P6] Viewer state snapshot after switch_series completes."""
        try:
            _meta = (
                getattr(self, 'metadata', None)
                or getattr(self, '_bound_backend_metadata', None)
                or {}
            )
            _sn = getattr(self, 'series_number', None) or _meta.get('series', {}).get('series_number', None)
            _instances = _meta.get('instances', [])
            _series_info = _meta.get('series', {})
            _server_count = _series_info.get('image_count', '?')
            # disk file count
            _disk_count = '?'
            _study_path = getattr(getattr(self, 'parent_widget', None), 'import_folder_path', None)
            if _study_path and _sn:
                _sp = os.path.join(str(_study_path), str(_sn))
                if os.path.isdir(_sp):
                    _disk_count = sum(1 for e in os.scandir(_sp) if e.is_file() and e.name.endswith('.dcm'))
            logger.info(
                "[H7-P6] path=%s series=%s server_image_count=%s "
                "disk_file_count=%s metadata_instance_count=%s "
                "viewer_slice_count=%s available_slice_count=%s "
                "active_backend=%s progressive_mode=%s slider_max=%s",
                path_label, _sn, _server_count, _disk_count,
                len(_instances),
                self.get_count_of_slices(),
                getattr(self, '_available_slice_count', '?'),
                getattr(self, '_active_backend', '?'),
                getattr(self, '_progressive_mode', '?'),
                self.slider.maximum() if hasattr(self, 'slider') and self.slider else '?',
            )
        except Exception as _e:
            logger.debug("[H7-P6] logging failed: %s", _e)

    def start_process_combine_series(
            self, vtk_image_data1, metadata1, vtk_image_data2, metadata2,
            series_index, id_vtk_widget, metadata_fixed):
        self._bind_backend_from_metadata(
            metadata1,
            force_vtk=True,
            source="start_process_combine_series",
        )

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
        self._bind_backend_from_metadata(metadata, source="start_process_series")
        if self._lazy_loader is not None:
            self._ensure_lazy_slice_loaded(0, mark_current=False)
        
        logger.info(f"[SERIES INIT] ├تظô┬╢ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[SERIES INIT]   Viewer ID: {id_vtk_widget}, Index: {series_index}")
        logger.info(f"[SERIES INIT]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Show spinner immediately (non-blocking)
        self.viewport_spinner.show_loading("Loading...")

        try:
            # =====================================================
            # ANTI-FLICKERING: Disable updates during heavy operation
            # =====================================================
            self.setUpdatesEnabled(False)

            # ظ¤ظ¤ Qt Backend Path (VTK-free 2D) ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤
            if self._active_backend == BACKEND_PYDICOM_QT:
                self._start_qt_viewer(metadata, metadata_fixed)
                self._sync_progressive_available_after_switch()
                self.last_series_show = series_index
                self.id_vtk_widget = id_vtk_widget
                logger.info("[SERIES INIT] COMPLETE (Qt backend) - slices=%d", self.get_count_of_slices())
            else:
                # ظ¤ظ¤ VTK Backend Path (original) ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤
                self._qt_bridge_active = False
                self._hide_qt_viewer()

                self.image_viewer = ImageViewer2D(self.render_window, self.interactor, self.height_viewer, vtk_image_data,
                                                  metadata, metadata_fixed, self.apply_default_filter, vtk_widget=self)
                
                logger.debug(f"[SERIES INIT]   ImageViewer2D created successfully")

                self.style = AbstractInteractorStyle(self.image_viewer)
                self.current_style = self.style
                self.interactor.SetInteractorStyle(self.style)
                self.style.signal_emitter.interactionOccurred.connect(self.change_container_border)

                self.last_series_show = series_index
                self.id_vtk_widget = id_vtk_widget
                # Capture zoom_to_fit scale set by ImageViewer2D.__init__ so the
                # scroll restore logic in set_slice has a valid reference from the start.
                # Without this _protected_parallel_scale stays None and the first
                # non-fast-scroll set_slice may lock in a wrong (VTK-chosen) scale,
                # causing the image to appear not zoom-to-fitted on download start.
                try:
                    _init_scale = getattr(self.image_viewer, 'base_zoom_scale', None)
                    if _init_scale:
                        self._protected_parallel_scale = float(_init_scale)
                    else:
                        _cam = self.image_viewer.renderer.GetActiveCamera()
                        if _cam:
                            self._protected_parallel_scale = float(_cam.GetParallelScale())
                except Exception:
                    pass
                self.save_status_camera(self.image_viewer)
                if self._lazy_loader is not None:
                    try:
                        current_idx = int(self.image_viewer.GetSlice())
                    except Exception:
                        current_idx = 0
                    self._ensure_lazy_slice_loaded(current_idx, mark_current=True)
                    self._mark_lazy_first_frame_if_needed()
                    self._log_lazy_metrics_if_due(force=True)
                
                # Log final camera state
                if self.image_viewer and self.image_viewer.renderer:
                    camera = self.image_viewer.renderer.GetActiveCamera()
                    if camera:
                        parallel_scale = camera.GetParallelScale()
                        logger.info(f"[SERIES INIT] COMPLETE - Final parallel scale: {parallel_scale:.2f}")
                    logger.info(f"[SERIES INIT] ├ت┼ôظ£ COMPLETE - Final parallel scale: {parallel_scale:.2f}")

        except Exception as e:
            logger.error(f"[SERIES INIT] ├ت┼ôظ¤ FAILED - Error: {e}")
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
        self._dump_scroll_state("start_process_series")

    def _start_qt_viewer(self, metadata, metadata_fixed):
        """Create and show the Qt-based 2D viewer (VTK-free path)."""
        try:
            if self.image_viewer is not None or self._qt_bridge_active or self._qt_viewer_widget is not None:
                logger.info("qt-viewer replacing existing viewer before restart")
                self.cleanup_image_viewer(preserve_bound_backend=True)

            bridge, qt_viewer = _create_qt_viewer_bridge(self, metadata, metadata_fixed)
            self.image_viewer = bridge
            self._qt_viewer_widget = qt_viewer
            self._qt_bridge_active = True
            self._active_backend = BACKEND_PYDICOM_QT
            self._update_backend_badge()

            # Initialize a functional bridge style for toolbar integration
            from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_interactor import _QtBridgeStyle
            self.current_style = _QtBridgeStyle(vtk_widget=self)

            # Replay any tool style that was requested while image_viewer was None
            _pending = getattr(self, '_pending_tool_style_cls', None)
            if _pending is not None:
                self._pending_tool_style_cls = None
                self.set_new_interactorstyle(_pending)

            # ── Hide the VTK native render window surface ──────────────
            # QVTKRenderWindowInteractor.__init__ embeds a native OpenGL
            # window via SetWindowInfo(winId).  That OS-level surface always
            # paints on top of any Qt child widget.  Three steps:
            #   1. Clear WA_PaintOnScreen so Qt restores compositing.
            #   2. Tell VTK to render off-screen (no GPU present → no
            #      drawing).
            #   3. Shrink + hide the render window as a safety fallback.
            from PySide6.QtCore import Qt as _Qt
            self.setAttribute(_Qt.WidgetAttribute.WA_PaintOnScreen, False)
            try:
                rw = getattr(self, 'render_window', None) or getattr(self, '_RenderWindow', None)
                if rw is not None:
                    if hasattr(rw, 'SetOffScreenRendering'):
                        rw.SetOffScreenRendering(True)
                    rw.SetSize(0, 0)
                    if hasattr(rw, 'SetShowWindow'):
                        rw.SetShowWindow(False)
            except Exception as _e:
                logger.warning("could not hide VTK render window: %s", _e)

            # Show Qt viewer over the VTK render window
            try:
                qt_viewer.setGeometry(self.rect())
                qt_viewer.updateGeometry()
            except Exception:
                pass
            qt_viewer.show()
            try:
                qt_viewer.raise_()
                qt_viewer.update()
            except Exception:
                pass
            if self.slider is not None:
                try:
                    self.slider.raise_()
                except Exception:
                    pass
            self._sync_qt_viewer_presentation(refit_view=False)

            # Render the first slice
            mid_slice = bridge.get_count_of_slices() // 2
            bridge.SetSlice(mid_slice)
            bridge.apply_default_window_level(mid_slice)
            bridge.set_slice(mid_slice)
            self._sync_qt_viewer_presentation(refit_view=True)
            try:
                qt_viewer.repaint()
            except Exception:
                pass
            self._qt_switch_refit_applied = True
            self._queue_qt_startup_refit(bridge)

            logger.info(
                "qt-viewer started slices=%d mid=%d",
                bridge.get_count_of_slices(), mid_slice,
            )
        except Exception as e:
            logger.error("Qt viewer creation failed, falling back to VTK: %s", e)
            import traceback
            logger.error(traceback.format_exc())
            self._qt_bridge_active = False
            self._active_backend = BACKEND_VTK
            self._update_backend_badge()
            raise

    def _hide_qt_viewer(self):
        """Hide and cleanup the Qt viewer widget if it exists."""
        if self._qt_viewer_widget is not None:
            try:
                _scroll_timer = getattr(self._qt_viewer_widget, '_scroll_stop_timer', None)
                if _scroll_timer is not None:
                    _scroll_timer.stop()
            except Exception:
                pass
            try:
                self._qt_viewer_widget.hide()
            except Exception:
                pass
            try:
                self._qt_viewer_widget.deleteLater()
            except Exception:
                pass
            self._qt_viewer_widget = None
        # Restore VTK render window and WA_PaintOnScreen for VTK path
        try:
            from PySide6.QtCore import Qt as _Qt
            self.setAttribute(_Qt.WidgetAttribute.WA_PaintOnScreen, True)
            rw = getattr(self, 'render_window', None) or getattr(self, '_RenderWindow', None)
            if rw is not None:
                if hasattr(rw, 'SetOffScreenRendering'):
                    rw.SetOffScreenRendering(False)
                w, h = self.width(), self.height()
                rw.SetSize(w, h)
                if hasattr(rw, 'SetShowWindow'):
                    rw.SetShowWindow(True)
        except Exception:
            pass

    def reset_image(self, vtk_image_data, metadata):  # reload image
        # ظ¤ظ¤ Qt backend: re-open pipeline on same series ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤
        if self._qt_bridge_active and self.image_viewer is not None:
            try:
                self.viewport_spinner.show_reset("Applying reset...")
                self.image_viewer.reset_image_viewer(
                    vtk_image_data,
                    metadata,
                    reset_presentation=True,
                )
                mid_slice = self.get_count_of_slices() // 2
                if self.slider is not None:
                    self.slider.setValue(mid_slice)
                self.image_viewer.apply_default_window_level(mid_slice)
                self.image_viewer.set_slice(mid_slice)
                self._sync_qt_viewer_presentation(refit_view=True)
                logger.info("[IMAGE RESET] COMPLETE (Qt backend) - mid=%d", mid_slice)
            except Exception as e:
                logger.error("[IMAGE RESET] Qt path failed: %s", e)
            finally:
                QTimer.singleShot(300, self.viewport_spinner.hide_loading)
            return

        # Extract series info for logging
        series_number = metadata.get('series', {}).get('series_number', 'N/A') if metadata else 'N/A'
        series_desc = metadata.get('series', {}).get('series_description', 'Unknown') if metadata else 'Unknown'
        modality = metadata.get('series', {}).get('modality', 'Unknown') if metadata else 'Unknown'
        dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
        self._bind_backend_from_metadata(metadata, source="reset_image")
        if self._lazy_loader is not None:
            self._ensure_lazy_slice_loaded(0, mark_current=False)
        
        logger.info(f"[IMAGE RESET] ├تظô┬╢ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[IMAGE RESET]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Show reset spinner
        self.viewport_spinner.show_reset("Applying reset...")

        try:
            # ├ت┼ôظخ Save current camera scale before reset
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
            if self._lazy_loader is not None:
                self._ensure_lazy_slice_loaded(mid_slice, mark_current=True)
            
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
            
            # ├ت┼ôظخ Always use zoom_to_fit to ensure image fills the viewer properly
            new_scale = self.image_viewer.zoom_to_fit()
            if new_scale:
                self._protected_parallel_scale = new_scale
                logger.info(f"[IMAGE RESET]   Applied zoom_to_fit scale: {new_scale:.2f}")
            else:
                logger.warning(f"[IMAGE RESET]   zoom_to_fit returned None/False")

            self.image_viewer.Render()
            if self._lazy_loader is not None:
                self._mark_lazy_first_frame_if_needed()
                self._log_lazy_metrics_if_due(force=True)
            logger.info(f"[IMAGE RESET] ├ت┼ôظ£ COMPLETE")

        except Exception as e:
            logger.error(f"[IMAGE RESET] ├ت┼ôظ¤ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        finally:
            # Hide spinner after reset is complete
            QTimer.singleShot(300, self.viewport_spinner.hide_loading)

        # Ensure spinner is properly positioned during reset
        if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
            self.viewport_spinner.spinner.center_in_parent()

    def cleanup_image_viewer(self, preserve_bound_backend=False):
        self._dbg_fast_state("cleanup_image_viewer")  # CP7 [FAST-DIAG]
        _preserved_backend = str(getattr(self, '_active_backend', BACKEND_VTK) or BACKEND_VTK)
        # Hide and release Qt viewer resources if active
        if self._qt_bridge_active:
            self._hide_qt_viewer()
            self._qt_bridge_active = False

        # Check if image_viewer exists before cleanup (for progressive download dummy viewers)
        if self.image_viewer is not None:
            # v2.2.9.3: Remove old renderer from render_window BEFORE cleanup.
            # Without this, orphaned renderers accumulate and may reference
            # stale VTK pipeline data from closed lazy loaders.
            try:
                old_renderer = self.image_viewer.GetRenderer()
                if old_renderer is not None and self.render_window is not None:
                    self.render_window.RemoveRenderer(old_renderer)
            except Exception:
                pass
            self.image_viewer.cleanup()
            del self.image_viewer
            self.image_viewer = None
        if not preserve_bound_backend:
            self._release_bound_lazy_loader()
            self._bound_backend_metadata = None
            self._series_generation_id += 1
            self._lazy_requested_generation = self._series_generation_id
            self._lazy_requested_slice = None
            self._active_backend = BACKEND_VTK
        else:
            self._active_backend = _preserved_backend
        self._update_backend_badge()

        # Run garbage collection to help free memory
        gc.collect()

    def switch_series(self, vtk_image_data, metadata, series_index, vtk_image_data_2=None, metadata_2=None,
                      metadata_fixed=None, progressive_total: int = 0):
        """
        HIGHLY OPTIMIZED: Series switch with minimal flickering
        - Shows loading spinner immediately with smart messaging
        - Reuses existing viewers when possible (FAST PATH)
        - Batches all VTK operations
        - No processEvents() calls to avoid blocking
        
        Performance gains:
        - Single viewer reuse: ~90% faster than recreation
        - Smart spinner messaging based on series size
        - Batched rendering operations
        """
        # ── v2.2.9.3: Validate vtk_image_data scalar buffer ──────────
        # If the lazy loader that created this vtk_image_data was closed,
        # the underlying mmap may have been unmapped.  Accessing the VTK
        # scalar array in that state causes a segfault.  Catch it early.
        #
        # CRITICAL EXCEPTION — PYDICOM_QT stubs (v2.3.1 fast path):
        # load_single_series_by_number creates a dimensioned vtkImageData stub
        # with NO scalar data by design.  The Qt pipeline renders directly from
        # DICOM files; it never uses VTK scalars.  Checking scalars on such a
        # stub always returns None → the guard trips and returns False, which
        # means switch_series never calls _start_qt_viewer, _qt_bridge_active
        # stays False, and wheelEvent falls through to VTK (nothing to show).
        # This is the "scrollbar moves but image stays frozen" regression.
        # Fix: read viewer_backend from the metadata annotation set by
        # _annotate_backend_metadata() in image_io.py and skip the scalar check
        # for PYDICOM_QT.  The check is still applied to all other backends.
        if vtk_image_data is not None:
            _is_qt_stub = False
            try:
                _is_qt_stub = (
                    str((metadata or {}).get('series', {}).get('viewer_backend', ''))
                    == BACKEND_PYDICOM_QT
                )
            except Exception:
                pass
            if not _is_qt_stub:
                try:
                    _scalars = vtk_image_data.GetPointData().GetScalars()
                    if _scalars is None or _scalars.GetNumberOfTuples() == 0:
                        logger.error(
                            "[SERIES SWITCH] vtk_image_data has no scalar data — "
                            "possibly from a closed lazy loader.  Aborting switch."
                        )
                        return False
                except Exception as _e:
                    logger.error(
                        "[SERIES SWITCH] vtk_image_data scalar validation failed: %s  "
                        "Aborting switch.", _e
                    )
                    return False
        # Extract series info for logging
        series_number = metadata.get('series', {}).get('series_number', 'N/A') if metadata else 'N/A'
        series_desc = metadata.get('series', {}).get('series_description', 'Unknown') if metadata else 'Unknown'
        modality = metadata.get('series', {}).get('modality', 'Unknown') if metadata else 'Unknown'
        dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
        is_combined = (vtk_image_data_2 is not None) and (metadata_2 is not None)
        if is_combined:
            self._bind_backend_from_metadata(metadata, force_vtk=True, source="switch_series_combined")
        else:
            self._bind_backend_from_metadata(metadata, source="switch_series")
            if self._lazy_loader is not None:
                # Always prefetch first slice on series switch. Using the previous
                # series current-slice index can enqueue irrelevant frames and
                # inflate dropped stale deliveries on the new series.
                self._ensure_lazy_slice_loaded(0, mark_current=False)
        
        logger.info(f"[SERIES SWITCH] ├تظô┬╢ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[SERIES SWITCH]   Index: {series_index}, Combined: {is_combined}")
        logger.info(f"[SERIES SWITCH]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        self._dbg_fast_state("switch_series_post_bind")  # CP1 [FAST-STATE]
        
        # Check this series has showed
        if self.last_series_show == series_index:
            # v2.2.5.3: Don't skip if incoming data has different dimensions
            # (e.g., preview → full data refresh).  The viewer's internal
            # slice range is stale and needs SetInputData via reset_image_viewer.
            _skip_switch = True
            try:
                if vtk_image_data is not None and self.image_viewer is not None:
                    _new_dims = vtk_image_data.GetDimensions()
                    _old_dims = self.image_viewer.vtk_image_data.GetDimensions()
                    if tuple(_new_dims) != tuple(_old_dims):
                        _skip_switch = False
                        logger.info(f"[SERIES SWITCH] Same series but dims changed: {_old_dims} -> {_new_dims}, allowing refresh")
            except Exception:
                pass
            if _skip_switch:
                logger.info(f"[SERIES SWITCH] ├ت┌ê┬ص SKIP - Already showing series {series_index}")
                return False

        self._camera_restore_generation = getattr(self, '_camera_restore_generation', 0) + 1

        if self._progressive_mode:
            self.exit_progressive_mode()

        if int(progressive_total) > 0:
            self.enter_progressive_mode(int(progressive_total), str(series_number))

        # Discard any pending scroll state from the previous series.
        # Without this, _last_scroll_event_ms stays at the old-series scroll time,
        # making event_queue_delay_ms show 14-17 s on the new series (false alarm).
        # Also prevents a stale _pending_wheel_slice from jumping to the wrong slice
        # the moment the new series finishes loading.
        try:
            self._wheel_coalesce_timer.stop()
            self._gc_reenable_timer.stop()
            self._pending_wheel_slice = None
            self._last_flushed_target = None
            self._last_scroll_event_ms = None
            self._stale_scroll_skip_count = 0
            self._last_render_end_ms = 0.0
            self._adaptive_frame_gap_ms = 4.0
            self._last_booster_notify_ms = 0.0
            if self._gc_suppressed:
                self._gc_suppressed = False
                if self._gc_saved_thresholds is not None:
                    try:
                        gc.set_threshold(*self._gc_saved_thresholds)
                    except Exception:
                        pass
                    self._gc_saved_thresholds = None
                gc.enable()
        except Exception:
            pass

        # ظ¤ظ¤ Qt backend fast path for series switch ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤
        logger.debug(  # CP1b [FAST-DIAG]
            "[FAST-DIAG] switch_series_qt_check backend=%s is_combined=%s qt_bridge_active=%s",
            getattr(self, '_active_backend', 'N/A'), is_combined, getattr(self, '_qt_bridge_active', False),
        )
        self._dbg_fast_state("switch_series_pre_qt_branch")  # CP1b [FAST-STATE]
        if self._active_backend == BACKEND_PYDICOM_QT and not is_combined:
            self.viewport_spinner.show_loading("Switching series...")
            try:
                _same_series_refresh = False
                try:
                    _current_meta = getattr(getattr(self, 'image_viewer', None), 'metadata', {}) or {}
                    _current_sn = str(_current_meta.get('series', {}).get('series_number', ''))
                    _incoming_sn = str((metadata or {}).get('series', {}).get('series_number', ''))
                    _same_series_refresh = bool(self._qt_bridge_active and _current_sn and _current_sn == _incoming_sn)
                except Exception:
                    _same_series_refresh = False

                if _same_series_refresh and self._refresh_qt_series_inplace(vtk_image_data, metadata, series_index):
                    pass
                else:
                    self._start_qt_viewer(metadata, metadata_fixed)
                self._sync_progressive_available_after_switch()
                self.last_series_show = series_index
                self.save_status_camera(self.image_viewer)
                logger.info(
                    "[SERIES SWITCH] COMPLETE (Qt backend) - slices=%d",
                    self.get_count_of_slices(),
                )
                self._h7_p6_log("Qt")
            except Exception as e:
                logger.error("[SERIES SWITCH] Qt path failed: %s", e)
                import traceback
                logger.error(traceback.format_exc())
                raise
            finally:
                QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)
            return True

        # ── VTK path: ensure Qt bridge is deactivated ──────────────────
        # When switching from a Qt backend series to a VTK backend series on
        # the same viewer, _qt_bridge_active may still be True from the
        # previous _start_qt_viewer call.  Clean up the Qt viewer so the fast
        # path below does not mistakenly call reset_image_viewer on the
        # QtViewerBridge instead of an ImageViewer2D.
        if self._qt_bridge_active:
            self.cleanup_image_viewer(preserve_bound_backend=True)

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

        # ┘ï┌║┌ء┬ش SHOW SPINNER WITH SMART MESSAGE BASED ON SERIES SIZE
        spinner_message = self._get_smart_spinner_message(vtk_image_data, metadata)
        self.viewport_spinner.show_loading(spinner_message)
        # Force-paint the spinner overlay BEFORE disabling widget updates.
        # Without this, setUpdatesEnabled(False) blocks the spinner from
        # being painted and the user briefly sees the old image.
        try:
            self.viewport_spinner.spinner.repaint()
        except Exception:
            pass
        
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
                        self.cleanup_image_viewer(preserve_bound_backend=True)
                    else:
                        # Same viewer type - just reset the image data (FAST!)
                        if is_combined_new:
                            # Combined viewer - recreate
                            self.cleanup_image_viewer(preserve_bound_backend=True)
                        else:
                            # Single viewer - use fast reset
                            # ├ت┌ّ╪î FAST PATH: Just update image data without full viewer recreation
                            logger.debug(f"[SERIES SWITCH]   Using FAST PATH (viewer reuse)")
                            # [H11] Probe 4: pre-fast-path state capture
                            _h11_pre_viewer_id = id(self.image_viewer)
                            _h11_pre_loader_id = id(self._lazy_loader) if self._lazy_loader is not None else None
                            _h11_pre_viewer_sn = None
                            try:
                                if hasattr(self.image_viewer, 'metadata') and isinstance(self.image_viewer.metadata, dict):
                                    _h11_pre_viewer_sn = self.image_viewer.metadata.get('series', {}).get('series_number')
                            except Exception:
                                pass
                            _h11_pre_slice = None
                            try:
                                _h11_pre_slice = int(self.image_viewer.GetSlice())
                            except Exception:
                                pass
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
                            
                            # ├ت┼ôظخ CRITICAL: Update _protected_parallel_scale to match the 
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
                            self._sync_progressive_available_after_switch()
                            self.save_status_camera(self.image_viewer)
                            
                            # Log final camera state
                            try:
                                camera = self.image_viewer.renderer.GetActiveCamera()
                                final_scale = camera.GetParallelScale() if camera else 0
                                logger.info(f"[SERIES SWITCH] COMPLETE (FAST) - Final scale: {final_scale:.2f}")
                            except:
                                logger.info(f"[SERIES SWITCH] ├ت┼ôظ£ COMPLETE (FAST)")

                            try:
                                self.image_viewer.Render()
                                logger.debug("[SERIES SWITCH]   VTK reslice pipeline pre-warmed (FAST)")
                            except Exception:
                                pass
                            self._camera_restore_generation = getattr(self, '_camera_restore_generation', 0) + 1
                            self._log_slice_range(source="switch_series_fast")
                            self._h7_p6_log("FAST")
                            
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
                            if self._lazy_loader is not None:
                                try:
                                    current_idx = int(self.image_viewer.GetSlice())
                                except Exception:
                                    current_idx = 0
                                self._ensure_lazy_slice_loaded(current_idx, mark_current=True)
                                self._mark_lazy_first_frame_if_needed()
                                self._log_lazy_metrics_if_due(force=True)
                            self._dump_scroll_state("switch_series_fast")
                            # [H11] Probe 4: fast-path completion
                            try:
                                _h11_post_viewer_id = id(self.image_viewer)
                                _h11_post_loader_id = id(self._lazy_loader) if self._lazy_loader is not None else None
                                _h11_post_viewer_sn = None
                                try:
                                    if hasattr(self.image_viewer, 'metadata') and isinstance(self.image_viewer.metadata, dict):
                                        _h11_post_viewer_sn = self.image_viewer.metadata.get('series', {}).get('series_number')
                                except Exception:
                                    pass
                                _h11_post_slice = None
                                try:
                                    _h11_post_slice = int(self.image_viewer.GetSlice())
                                except Exception:
                                    pass
                                _h11_meta_sn = metadata.get('series', {}).get('series_number') if isinstance(metadata, dict) else None
                                logger.info(
                                    "[H11] FAST_PATH_COMPLETE viewer=%s "
                                    "viewer_reused=%s loader_reused=%s "
                                    "meta_sn_changed=%s slice_inherited=%s "
                                    "pre_viewer_sn=%s post_viewer_sn=%s meta_sn=%s "
                                    "pre_slice=%s post_slice=%s "
                                    "pre_loader_id=%s post_loader_id=%s "
                                    "gen=%s req_slice=%s progressive=%s",
                                    str(getattr(self, 'id_vtk_widget', '?')),
                                    _h11_pre_viewer_id == _h11_post_viewer_id,
                                    _h11_pre_loader_id == _h11_post_loader_id if _h11_pre_loader_id is not None else 'N/A',
                                    _h11_pre_viewer_sn != _h11_meta_sn,
                                    _h11_post_slice is not None and _h11_post_slice == _h11_pre_slice and _h11_pre_slice != 0,
                                    _h11_pre_viewer_sn, _h11_post_viewer_sn, _h11_meta_sn,
                                    _h11_pre_slice, _h11_post_slice,
                                    _h11_pre_loader_id, _h11_post_loader_id,
                                    int(self._series_generation_id),
                                    self._lazy_requested_slice,
                                    bool(getattr(self, '_progressive_mode', False)),
                                )
                            except Exception as _h11_e:
                                logger.debug("[H11] fast-path probe error: %s", _h11_e)
                            return True
                            
                except Exception as e:
                    logger.warning(f"[SERIES SWITCH] Fast path failed, falling back to recreation: {e}")
                    import traceback
                    traceback.print_exc()
                    self.cleanup_image_viewer(preserve_bound_backend=True)

            # Create new viewer (first time or fallback)
            # ├ت┌ّ╪î BATCHED CREATION: All operations grouped together
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

            # ├ت┌ّ╪î SINGLE BATCHED RENDER at the end (not multiple renders)
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

            self._camera_restore_generation = getattr(self, '_camera_restore_generation', 0) + 1

            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    zoom_fit_scale = camera.GetParallelScale()
                    self._protected_parallel_scale = zoom_fit_scale
                    logger.info(f"[SERIES SWITCH]   Updated protected scale (SLOW): {zoom_fit_scale:.2f}")
            except Exception:
                logger.warning("[SERIES SWITCH]   Failed to update protected scale (SLOW)")

            self.last_series_show = series_index
            self._sync_progressive_available_after_switch()
            self.save_status_camera(self.image_viewer)

            # Log final camera state
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                final_scale = camera.GetParallelScale() if camera else 0
                logger.info(f"[SERIES SWITCH] ├ت┼ôظ£ COMPLETE (SLOW) - Final scale: {final_scale:.2f}")
            except:
                logger.info(f"[SERIES SWITCH] ├ت┼ôظ£ COMPLETE (SLOW)")
            self._log_slice_range(source="switch_series_slow")
            self._h7_p6_log("SLOW")
            
        except Exception as e:
            logger.error(f"[SERIES SWITCH] ├ت┼ôظ¤ FAILED - Error: {e}")
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
        if self._lazy_loader is not None and self.image_viewer is not None:
            try:
                current_idx = int(self.image_viewer.GetSlice())
            except Exception:
                current_idx = 0
            self._ensure_lazy_slice_loaded(current_idx, mark_current=True)
            self._mark_lazy_first_frame_if_needed()
            self._log_lazy_metrics_if_due(force=True)

        self._dump_scroll_state("switch_series_slow")
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
                    return f"┘ï┌║ظ£┘╣ Loading large series... ({num_slices} images)"
                elif num_slices > 100:
                    return f"┘ï┌║ظ£┬╖ Switching series... ({num_slices} images)"
                elif num_slices > 50:
                    return " Switching series..."
                else:
                    return "Switching series..."
        except:
            pass
        
        return "Switching series..."

    def get_count_of_slices(self):
        if self._progressive_mode and self._total_expected_slices > 0:
            return self._total_expected_slices
        # Qt bridge: direct slice count from pipeline
        if self._qt_bridge_active and self.image_viewer is not None:
            try:
                return int(self.image_viewer.get_count_of_slices())
            except Exception:
                return 0
        if self._active_backend == BACKEND_PYDICOM:
            try:
                backend_count = int(getattr(self._lazy_loader, "slice_count", 0) or 0)
            except Exception:
                backend_count = 0
            if backend_count <= 0:
                for meta in (self._bound_backend_metadata, getattr(self.image_viewer, "metadata", None)):
                    if not isinstance(meta, dict):
                        continue
                    try:
                        backend_count = int(len(meta.get("instances", []) or []))
                    except Exception:
                        backend_count = 0
                    if backend_count > 0:
                        break
            if backend_count > 0:
                return backend_count
        if self.image_viewer is None:
            return 0
        try:
            return int(self.image_viewer.get_count_of_slices())
        except Exception:
            return 0

    def _dbg_fast_state(self, tag: str) -> None:
        """[FAST-DIAG] One-line FAST-viewer state snapshot. Zero behavior change."""
        try:
            _iv = getattr(self, 'image_viewer', None)
            _slice: object = None
            _count: object = None
            try:
                _slice = int(_iv.GetSlice()) if _iv else None
            except Exception:
                pass
            try:
                _count = self.get_count_of_slices()
            except Exception:
                pass
            logger.debug(
                "[FAST-STATE] %s backend=%s qt_bridge_active=%s current_slice=%s slice_count=%s viewer_id=%s",
                tag,
                getattr(self, '_active_backend', 'N/A'),
                getattr(self, '_qt_bridge_active', 'N/A'),
                _slice,
                _count,
                id(_iv) if _iv else 'None',
            )
        except Exception:
            pass
