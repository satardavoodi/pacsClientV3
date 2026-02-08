import time
import logging

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from PacsClient.pacs.patient_tab.interactor_styles import AbstractInteractorStyle
from PacsClient.pacs.patient_tab.viewers.viewer_2d import ImageViewer2D, CustomCombineImageViewers
from PacsClient.pacs.patient_tab.ui.widgets import ViewportSpinner
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor, QPainter, QPixmap, QColor
import gc  # برای garbage collection دستی
from PacsClient.pacs.patient_tab.utils import read_segment_nifti
import vtkmodules.all as vtk
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# =====================================================
# ANTI-FLICKERING CONSTANTS
# =====================================================
_RENDER_THROTTLE_MS = 16  # ~60fps max render rate
_SPINNER_HIDE_DELAY_MS = 50  # Delay before hiding spinner to allow final render
_SYNC_MOVE_THROTTLE_MS = 16  # min interval between sync mouse move processing (~60fps)


def grow_vtk_inplace(old_input, new_vtk_image_data):
    # ابعاد قدیم/جدید
    ox, oy, oz = old_input.GetDimensions()
    nx, ny, nz = new_vtk_image_data.GetDimensions()

    # اگر چیزی اضافه نشده، فقط Modified بده
    if (nx <= ox and ny <= oy and nz <= oz):
        old_input.Modified()
        return False

    # 2) XY باید ثابت باشد؛ در غیر این صورت، از تخریب حافظه جلوگیری کن
    if (ox, oy) != (nx, ny):
        # اگر XY تغییر کرده، برای جلوگیری از کراش/مصرف سنگین، فعلاً رد کن
        # (در صورت نیاز می‌توان مسیر ایمن دیگری پیاده کرد)
        return False

    # 3) فقط در صورت تغییر، spacing/origin را به‌روز کن
    if old_input.GetSpacing() != new_vtk_image_data.GetSpacing():
        old_input.SetSpacing(new_vtk_image_data.GetSpacing())
    if old_input.GetOrigin() != new_vtk_image_data.GetOrigin():
        old_input.SetOrigin(new_vtk_image_data.GetOrigin())

    # 4) ابعاد/extent جدید
    old_input.SetDimensions(nx, ny, nz)
    old_input.SetExtent(0, nx - 1, 0, ny - 1, 0, nz - 1)

    # 5) کم‌هزینه‌ترین آپدیت اسکالرها: به‌جای DeepCopy، SetScalars (تعویض اشاره‌گر)
    new_scalars = new_vtk_image_data.GetPointData().GetScalars()
    old_input.GetPointData().SetScalars(new_scalars)

    # 7) علامت‌زدن تغییر؛ بدون Render/Update فوری
    old_input.GetPointData().Modified()
    old_input.Modified()

    # self.image_reslice.Modified()
    # self.image_reslice.Update()      # عمداً حذف شد
    # self.UpdateDisplayExtent()       # عمداً حذف شد
    # self.update_corners_actors()     # عمداً حذف شد (caller می‌تواند بعد از throttle صدا بزند)
    # self.Render()                    # عمداً حذف شد

    ################################################################
    # # 3) سیگنالِ تغییر
    # old_vtk.GetPointData().Modified()
    # old_vtk.Modified()
    return True


class VTKWidget(QVTKRenderWindowInteractor):
    def __init__(self, parent=None, height_viewer=480):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.last_series_show = None
        self.id_vtk_widget = None
        self.current_style: AbstractInteractorStyle = None
        self.image_viewer = None
        self.height_viewer = height_viewer
        self.apply_default_filter = True
        
        # =====================================================
        # ANTI-FLICKERING: Render throttling state
        # =====================================================
        self._render_pending = False
        self._last_render_time = 0
        self._render_timer = None

        self.render_window = self.GetRenderWindow()
        self.interactor = self.render_window.GetInteractor()
        
        # =====================================================
        # ANTI-FLICKERING: Enable double buffering on render window
        # =====================================================
        self.render_window.SetDoubleBuffer(True)
        self.render_window.SetSwapBuffers(True)
        
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
        try:
            # Check if image_viewer exists before rendering
            if self.image_viewer is None:
                return
            
            # Update last render time
            self._last_render_time = time.time() * 1000
            
            # Batch all updates together before single render
            self.image_viewer.image_reslice.Update()
            self.image_viewer.UpdateDisplayExtent()
            self.image_viewer.update_corners_actors()
            
            # Update slider without triggering signals
            if hasattr(self, 'slider') and self.slider is not None:
                self.slider.blockSignals(True)
                self.slider.setMaximum(self.image_viewer.get_count_of_slices())
                self.slider.blockSignals(False)
            
            # Single render call at the end
            self.image_viewer.Render()

        finally:
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
        """افزایش نرم تعداد اسلایس‌های سری فعلی، بدون ریست/سوییچ."""
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
            #     # فقط حداکثر اسلایدر را آپدیت کن؛ مقدار فعلی دست‌نخورده بماند
            #     max_slice = self.get_count_of_slices() - 1
            #     cur = self.slider.value()
            #     self.slider.setMaximum(max_slice)
            #
            #     # اگر کاربر روی آخرین اسلایس بود و اسلایس جدید اضافه شد، می‌توانی تصمیم بگیری خودکار یک قدم جلوتر برود یا نه
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
            
        interactorstyle: AbstractInteractorStyle = style(self.image_viewer)

        # load widgets on new interactor style
        interactorstyle = self.set_widgets_on_new_interactorstyle(interactorstyle)

        # replace new interactor style
        self.interactor.SetInteractorStyle(interactorstyle)
        interactorstyle.signal_emitter.interactionOccurred.connect(self.change_container_border)

        self.current_style = interactorstyle
        self.image_viewer.Render()

    def restore_default_interactorstyle(self):
        if self.image_viewer is None:
            return
            
        default_interactorstyle = self.style

        # load widgets on new interactor style
        default_interactorstyle = self.set_widgets_on_new_interactorstyle(default_interactorstyle)

        self.interactor.SetInteractorStyle(default_interactorstyle)
        self.current_style = default_interactorstyle
        self.current_style.reset_events()  # reset events to default events
        self.image_viewer.Render()

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
        # Show spinner (non-blocking)
        self.viewport_spinner.show_loading("Loading...")

        try:
            # =====================================================
            # ANTI-FLICKERING: Disable updates during heavy operation
            # =====================================================
            self.setUpdatesEnabled(False)
            
            self.image_viewer = ImageViewer2D(self.render_window, self.interactor, self.height_viewer, vtk_image_data,
                                              metadata, metadata_fixed, self.apply_default_filter, vtk_widget=self)
            
            self.style = AbstractInteractorStyle(self.image_viewer)
            self.current_style = self.style
            self.interactor.SetInteractorStyle(self.style)
            self.style.signal_emitter.interactionOccurred.connect(self.change_container_border)

            self.last_series_show = series_index
            self.id_vtk_widget = id_vtk_widget
            self.save_status_camera(self.image_viewer)

        finally:
            # Re-enable updates
            self.setUpdatesEnabled(True)
            # Hide spinner with small delay to allow final render
            QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)

    def reset_image(self, vtk_image_data, metadata):  # reload image
        # Show reset spinner
        self.viewport_spinner.show_reset("Applying reset...")

        try:
            # delete and set image
            self.image_viewer.reset_image_viewer(vtk_image_data, metadata)

            # select mid-slice for show with default window level
            mid_slice = self.get_count_of_slices() // 2  # Use middle slice like toolbar reset
            # mid_slice = mid_slice - self.image_viewer.skip_slices
            # mid_slice = 0

            self.slider.setValue(mid_slice)
            self.image_viewer.apply_default_window_level(mid_slice)

            # Reset camera to default state (like toolbar reset)
            camera = self.image_viewer.renderer.GetActiveCamera()

            # Set default view up if initial_view_up_camera exists, otherwise use default
            if hasattr(self, 'initial_view_up_camera') and self.initial_view_up_camera:
                camera.SetViewUp(self.initial_view_up_camera)
            else:
                # Default view up for medical images
                camera.SetViewUp(0, -1, 0)

            # Reset camera and apply zoom to fit
            self.image_viewer.renderer.ResetCamera()
            self.image_viewer.renderer.ResetCameraClippingRange()
            self.image_viewer.zoom_to_fit()

            self.image_viewer.Render()

        finally:
            # Hide spinner after reset is complete
            QTimer.singleShot(300, self.viewport_spinner.hide_loading)

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

        # فراخوانی cleanup برای آزاد کردن همه چیز

        # del self.style
        # self.style = None

        # del self.current_style
        # self.current_style = None

        # فراخوانی garbage collection برای کمک به آزادسازی حافظه
        gc.collect()

    def switch_series_backup(self, vtk_image_data, metadata, series_index, vtk_image_data_2=None, metadata_2=None,
                      metadata_fixed=None):
        """
        ANTI-FLICKERING: Series switch without processEvents
        """
        # Check this series has showed
        if self.last_series_show == series_index:
            return False

        # Show loading spinner (non-blocking)
        self.viewport_spinner.show_loading("Switching series...")
        
        # =====================================================
        # ANTI-FLICKERING: Disable updates during switch
        # =====================================================
        self.setUpdatesEnabled(False)

        self.cleanup_image_viewer()

        if (vtk_image_data_2 is not None) and (metadata_2 is not None):
            self.image_viewer = CustomCombineImageViewers(
                self.render_window, self.interactor, self.height_viewer, vtk_image_data1=vtk_image_data,
                metadata1=metadata,
                vtk_image_data2=vtk_image_data_2, metadata2=metadata_2, metadata_fixed=metadata_fixed,
                apply_default_filter=self.apply_default_filter, vtk_widget=self)

        else:
            self.image_viewer = ImageViewer2D(self.render_window, self.interactor, self.height_viewer, vtk_image_data,
                                              metadata, metadata_fixed, self.apply_default_filter, vtk_widget=self)

        self.image_viewer.apply_default_window_level(self.image_viewer.GetSlice())
        # add new renderer
        new_renderer = self.image_viewer.GetRenderer()
        self.render_window.AddRenderer(new_renderer)

        # set interactor style again
        self.style = AbstractInteractorStyle(self.image_viewer)
        self.interactor.SetInteractorStyle(self.style)
        # self.style.interactionOccurred.connect(self.change_container_border)
        self.style.signal_emitter.interactionOccurred.connect(self.change_container_border)

        self.image_viewer.UpdateDisplayExtent()
        # Single render call (not both viewer and window)
        self.render_window.Render()

        self.last_series_show = series_index
        self.save_status_camera(self.image_viewer)
        
        # =====================================================
        # ANTI-FLICKERING: Re-enable updates and hide spinner
        # =====================================================
        self.setUpdatesEnabled(True)
        QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)
        return True

    def switch_series(self, vtk_image_data, metadata, series_index, vtk_image_data_2=None, metadata_2=None,
                      metadata_fixed=None):
        """
        ANTI-FLICKERING: Optimized series switch without flickering
        Removed all processEvents() calls and excessive print statements
        """
        # Check this series has showed
        if self.last_series_show == series_index:
            return False

        # Show loading spinner (non-blocking - no processEvents!)
        self.viewport_spinner.show_loading("Switching series...")
        
        # =====================================================
        # ANTI-FLICKERING: Disable widget updates during switch
        # =====================================================
        self.setUpdatesEnabled(False)
        
        try:
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
                            self.image_viewer.reset_image_viewer(vtk_image_data, metadata)
                            self.image_viewer.apply_default_window_level(self.image_viewer.GetSlice())
                            
                            self.last_series_show = series_index
                            self.save_status_camera(self.image_viewer)
                            
                            # Re-enable updates and hide spinner
                            self.setUpdatesEnabled(True)
                            QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)
                            return True
                            
                except Exception as e:
                    self.cleanup_image_viewer()

            # Create new viewer (first time or fallback)
            if (vtk_image_data_2 is not None) and (metadata_2 is not None):
                self.image_viewer = CustomCombineImageViewers(
                    self.render_window, self.interactor, self.height_viewer, vtk_image_data1=vtk_image_data,
                    metadata1=metadata,
                    vtk_image_data2=vtk_image_data_2, metadata2=metadata_2, metadata_fixed=metadata_fixed,
                    apply_default_filter=self.apply_default_filter, vtk_widget=self)
            else:
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

            # Single batched render at the end
            self.image_viewer.UpdateDisplayExtent()
            self.render_window.Render()

            self.last_series_show = series_index
            self.save_status_camera(self.image_viewer)
            
        finally:
            # =====================================================
            # ANTI-FLICKERING: Re-enable updates in finally block
            # =====================================================
            self.setUpdatesEnabled(True)
            
        # Hide spinner with delay to allow render to complete
        QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)
        return True

    def get_count_of_slices(self):
        if self.image_viewer is None:
            return 0
        return self.image_viewer.get_count_of_slices()

    def set_slice(self, slice_index):
        if self.image_viewer is None:
            return
        self.image_viewer.set_slice(slice_index)
        self.image_viewer.last_index_slice_saved = slice_index

        # Notify interactor style if it's a ruler style
        try:
            style = self.interactor.GetInteractorStyle()
            if hasattr(style, 'update_slice'):
                style.update_slice()

        except Exception as e:
            print(f"Error updating on slice change: {e}")

        self._update_overlay_extent()

        # Lock Sync callback — fires on EVERY slice change regardless of source
        if self._on_slice_changed_cb is not None:
            try:
                self._on_slice_changed_cb(self)
            except Exception:
                pass

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
        try:
            # Check if image_viewer exists
            if self.image_viewer is None:
                super().wheelEvent(event)
                return
                
            delta = event.angleDelta().y()
            max_slice = self.get_count_of_slices()
            
            # Smooth and proportional scrolling based on stack size
            if max_slice <= 1:
                return  # Nothing to scroll
            
            # Calculate adaptive step based on number of slices
            N = max_slice
            
            if N < 50:
                # Small stacks: show all slices, step = 1
                step = 1
            elif N < 300:
                # Medium stacks: interpolate between 1 and higher steps
                # Linear interpolation: step = 1 + (N - 50) / 250 * 4
                # This gives step ≈ 1-5 as N goes from 50 to 300
                step = max(1, int(1 + (N - 50) / 250 * 4))
            else:
                # Large stacks: dynamically skip slices
                # Target: show approximately 300 "visible" slices
                step = max(1, int(N / 300))
            
            # Invert direction for natural scrolling
            # step = 1 if delta > 0 else -1 if delta < 0 else 0  # determine increase/decrease slice
            if delta > 0:
                step = -step
            elif delta < 0:
                step = step
            else:
                step = 0
            
            next_slice = self.image_viewer.GetSlice() + self.image_viewer.skip_slices + step
            
            # Clamp to valid range [0, N-1]
            next_slice = max(0, min(next_slice, max_slice - 1))
            
            # print('max slice:', max_slice, 'next slice:', next_slice, 'step:', step)
            self.slider.setValue(next_slice)
            
            # Additional check for ruler style
            try:
                style = self.interactor.GetInteractorStyle()
                if hasattr(style, 'update_slice'):
                    style.update_slice()

            except Exception as e:
                print(f"Error updating ruler on wheel event: {e}")

            # Update container border
            self.change_container_border()

        except:
            super().wheelEvent(event)

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
            # dropped from thumbnails series
            # change series with drag and drop - ASYNC for smooth UI
            self.change_container_border()
            
            # Use QTimer to defer the call and avoid blocking during drop
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.method_change_series_on_viewer(
                series_index=int(data), 
                flag_change_selected_widget=False,
                vtk_widget=self, 
                slider=self.slider
            ))
            
        except Exception as e:
            # dropped segmentation out of app
            if event.mimeData().hasUrls():
                data = event.mimeData().urls()[0].toLocalFile()
                print(f'dropped file url: {data}\n')
                vtk_segmentation_img = read_segment_nifti(data)
                self.overlay(vtk_segmentation_img, color=(0.0, 1.0, 0.0), opacity=0.35, is_label=True)
                print('add segmentation successful.')

    def overlay(self, vtk_image_data: vtk.vtkImageData, color=(1.0, 0.0, 0.0), opacity=0.4, is_label=True):
        """
        یک تصویر را به عنوان اوورلی روی image_viewer فعلی می‌اندازد.
        - vtk_image_data: vtk.vtkImageData
        - color: (r,g,b) در بازه [0..1]
        - opacity: شفافیت اوورلی (برای پیکسل‌های غیر صفر)
        - is_label: اگر True باشد نداشتن مقدار (0) شفاف می‌شود و غیرصفرها رنگ می‌گیرند.
        """
        if not hasattr(self, "image_viewer") or self.image_viewer is None:
            return

        self.clear_overlay()
        self._overlay = {}

        # 1) ریسلایس اوورلی مطابق ریسلایس تصویر پایه
        ov_reslice = vtk.vtkImageReslice()
        ov_reslice.SetInputData(vtk_image_data)

        # # همان ماتریس محورهای ریسلایس تصویر اصلی
        # axes = self.image_viewer.image_reslice.GetResliceAxes()
        # if axes is not None:
        #     ov_reslice.SetResliceAxes(axes)

        # اطلاعات هندسی را از تصویر فعلی بگیر (origin/spacing/extent)
        # ov_reslice.SetInformationInput(self.image_viewer.vtk_image_data)
        # ov_reslice.SetOutputOrigin(self.image_viewer.vtk_image_data.GetOrigin())

        # # اینترپولیشن: برای ماسک nearest، برای تصویر معمولی linear
        # if is_label:
        #     ov_reslice.SetInterpolationModeToNearestNeighbor()
        # else:
        #     ov_reslice.SetInterpolationModeToLinear()

        # ov_reslice.SetInterpolationModeToNearestNeighbor()
        # ov_reslice.SetInterpolationModeToLinear()

        ov_reslice.Update()
        self._overlay["reslice"] = ov_reslice

        # 2) نگاشت رنگ/آلفا
        #   الف) برای ماسک برچسبی: LUT با 0 شفاف، بقیه رنگ/opacity
        #   ب) برای تصویر معمولی: WL/WW دلخواه می‌توان گذاشت؛ فعلاً LUT ساده
        rng = ov_reslice.GetOutput().GetScalarRange()
        lut = vtk.vtkLookupTable()
        # تعداد جدول را معقول تعیین می‌کنیم

        table_size = max(256, int(rng[1] - rng[0] + 1))
        lut.SetNumberOfTableValues(table_size)
        lut.Build()

        if is_label:
            # index۰ شفاف کامل
            lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)
            # بقیه اندیس‌ها با رنگ/اپسیتی
            for i in range(1, table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))
        else:
            # همه مقادیر با یک شفافیت ملایم؛ اگر خواستی می‌تونی WL/WW مجزا بگذاری
            for i in range(table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))

        map_colors = vtk.vtkImageMapToColors()
        map_colors.SetLookupTable(lut)
        map_colors.SetInputConnection(ov_reslice.GetOutputPort())
        map_colors.Update()
        self._overlay["map"] = map_colors

        # 3) اکتور تصویر اوورلی
        actor = vtk.vtkImageActor()
        actor.GetMapper().SetInputConnection(map_colors.GetOutputPort())
        actor.SetPickable(False)
        self.image_viewer.GetRenderer().AddActor(actor)
        self._overlay["actor"] = actor

        # 4) همگام کردن Extent با اسلایس فعلی و اورینتیشن
        self._update_overlay_extent()

        # 5) رندر
        self._schedule_render(1)

    def clear_overlay(self):
        """حذف اوورلی از رندرر و آزادسازی مرجع‌ها"""
        if hasattr(self, "_overlay") and self._overlay:
            try:
                actor = self._overlay.get("actor")
                if actor:
                    self.image_viewer.GetRenderer().RemoveActor(actor)
            except Exception:
                pass
        self._overlay = {}

    def _update_overlay_extent(self):
        """DisplayExtent اوورلی را با توجه به اسلایس و اورینتیشن فعلی تنظیم می‌کند."""
        if not hasattr(self, "_overlay") or not self._overlay:
            return
        actor = self._overlay.get("actor")
        ov_img = self._overlay.get("reslice").GetOutput()
        base_img = self.image_viewer.vtk_image_data
        if not actor or not ov_img or not base_img:
            return

        # از ویوِر اصلی ابعاد و اسلایس فعلی را بگیر
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