"""
Tab lifecycle, theme, cleanup, tools, filters, priority queue.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""

import copy
import gc
import logging
import logging as _logging
import time
import traceback
import vtk
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
from PacsClient.pacs.patient_tab.utils import NodeViewer
logger = logging.getLogger(__name__)

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))


class _PWLifecycleMixin:
    """Tab lifecycle, theme, cleanup, tools, filters, priority queue."""

    def add_priority_series_for_display(self, series_number, vtk_image_data, metadata):
        """افزودن سری اولویت‌دار به صف نمایش مستقل"""
        try:
            series_key = str(series_number)
            print(f"🎯 [PRIORITY DISPLAY] Adding series {series_key} to priority display queue")
            
            # ذخیره داده‌ها
            self._priority_series_data[series_key] = {
                'vtk_image_data': vtk_image_data,
                'metadata': metadata,
                'added_time': time.time()
            }
            
            # افزودن به صف (اگر قبلاً نبوده)
            if series_key not in self._priority_series_queue:
                self._priority_series_queue.append(series_key)
                print(f"   ✅ Added to queue. Queue length: {len(self._priority_series_queue)}")
            
            # تلاش برای نمایش فوری
            self._try_display_priority_series(series_key)
            
        except Exception as e:
            print(f"❌ Error adding priority series to display queue: {e}")
            import traceback
            traceback.print_exc()

    def _try_display_priority_series(self, series_key):
        """تلاش برای نمایش فوری سری اولویت‌دار"""
        try:
            if series_key not in self._priority_series_data:
                print(f"⚠️ Series {series_key} not in priority data")
                return False

            # بررسی وجود ویوورها
            if not hasattr(self, 'lst_nodes_viewer') or not self.lst_nodes_viewer:
                print(f"⚠️ No viewers available for series {series_key}, will try later")
                return False

            data = self._priority_series_data[series_key]
            vtk_image_data = data['vtk_image_data']
            metadata = data['metadata']

            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []
                print(f"⚠️ lst_thumbnails_data not initialized")
                return False

            # پیدا کردن ایندکس سری در lst_thumbnails_data
            series_idx = -1
            for i in range(len(self.lst_thumbnails_data)):
                if str(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == series_key:
                    series_idx = i
                    break

            if series_idx == -1:
                print(f"⚠️ Series {series_key} not found in thumbnails data")
                return False

            print(f"🎬 [PRIORITY DISPLAY] Attempting immediate display of series {series_key}")

            # استفاده از اولین ویوور
            viewer = self.lst_nodes_viewer[0]

            # If this is the first displayed series (or any viewer is empty), fill all viewers
            if (not self._first_series_displayed) or self._any_viewer_empty():
                print(f"   🔄 Filling all viewers for first series {series_key}")
                if self._display_first_series_in_all_viewers(series_key):
                    self._mark_first_series_displayed()
                    # Set main viewer to first
                    self.set_viewer_to_main_viewer(viewer)
                    # Remove from queue/data
                    if series_key in self._priority_series_queue:
                        self._priority_series_queue.remove(series_key)
                    if series_key in self._priority_series_data:
                        del self._priority_series_data[series_key]
                    print(f"🎉 [PRIORITY DISPLAY] Series {series_key} displayed in all viewers!")
                    return True

            # روش اصلی: استفاده از switch_series
            if hasattr(viewer, 'switch_series'):
                print(f"   🔄 Using switch_series for series {series_key}")
                flag_switch = viewer.switch_series(
                    vtk_image_data,
                    metadata,
                    series_idx,
                    metadata_fixed=self.metadata_fixed
                )

                if flag_switch:
                    print(f"   ✅ switch_series succeeded for series {series_key}")

                    # تنظیم به عنوان ویوور اصلی
                    self.set_viewer_to_main_viewer(viewer)

                    # تنظیم اسلایدر
                    if hasattr(viewer, 'slider') and viewer.slider:
                        self.reset_slider(viewer.vtk_widget, viewer.slider)

                    # حذف از صف و دیکشنری
                    if series_key in self._priority_series_queue:
                        self._priority_series_queue.remove(series_key)
                    if series_key in self._priority_series_data:
                        del self._priority_series_data[series_key]

                    # رندر فوری
                    if hasattr(viewer.vtk_widget, 'GetRenderWindow'):
                        viewer.vtk_widget.GetRenderWindow().Render()

                    print(f"🎉 [PRIORITY DISPLAY] Series {series_key} displayed successfully!")
                    return True
                else:
                    print(f"   ❌ switch_series failed for series {series_key}")
                    return False

            return False

        except Exception as e:
            print(f"❌ Error in priority display attempt: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _process_priority_series_queue(self):
        """پردازش دوره‌ای صف سری‌های اولویت‌دار"""
        try:
            if not self._priority_series_queue or not self.isVisible():
                return

            # کپی از صف برای جلوگیری از تغییر در حین پردازش
            queue_copy = self._priority_series_queue.copy()

            for series_key in queue_copy:
                # بررسی timeout (بیش از 30 ثانیه نمانده باشد)
                if series_key in self._priority_series_data:
                    added_time = self._priority_series_data[series_key]['added_time']
                    if time.time() - added_time > 30:  # 30 ثانیه
                        print(f"⚠️ Removing stale priority series {series_key} from queue")
                        self._priority_series_queue.remove(series_key)
                        del self._priority_series_data[series_key]
                        continue

                # تلاش برای نمایش
                if self._try_display_priority_series(series_key):
                    break  # فقط یک سری در هر چرخه نمایش بده

        except Exception as e:
            print(f"⚠️ Error processing priority queue: {e}")

    def exit_patient_widget(self):
        """تمام resources را با سرعت تمیز کن"""
        try:
            print("🔴 exit_patient_widget: Starting cleanup...")
            
            # Clean up any loading overlays
            try:
                self._hide_eagle_eye_loading_ui()
            except Exception:
                pass
            
            # Ensure home loading overlay is hidden if this widget is closed early
            try:
                from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
                home_widget = get_home_widget()
                if home_widget is not None:
                    home_widget._hide_double_click_loading()

                    # Remove this widget from home widget's cache if it exists
                    if hasattr(home_widget, 'dict_tabs_widget') and self.study_uid:
                        if self.study_uid in home_widget.dict_tabs_widget:
                            del home_widget.dict_tabs_widget[self.study_uid]
                            print(f"✅ Removed study {self.study_uid} from home widget cache")
                        else:
                            print(f"⚠️ Study {self.study_uid} not found in home widget cache")
                    else:
                        print(f"⚠️ Home widget doesn't have dict_tabs_widget or study_uid is None")
                        
                    # Remove this study from the opening studies set to allow reopening
                    if hasattr(home_widget, 'remove_from_opening_studies') and self.study_uid:
                        home_widget.remove_from_opening_studies(self.study_uid)
            except Exception as e:
                print(f"⚠️ Error removing widget from home cache: {e}")
                import traceback
                traceback.print_exc()

            # Cancel all background tasks first to prevent new tasks from being created
            if hasattr(self, '_background_tasks'):
                for task in list(self._background_tasks):
                    try:
                        if not task.done():
                            task.cancel()
                            # Wait briefly for task to finish cancellation
                            try:
                                if hasattr(task, 'exception'):
                                    task.exception()  # Consume any exceptions from cancellation
                            except:
                                pass
                    except:
                        pass
                self._background_tasks.clear()

            # Cancel the series worker task if it exists
            if hasattr(self, '_series_worker_task') and self._series_worker_task:
                try:
                    if not self._series_worker_task.done():
                        self._series_worker_task.cancel()
                except:
                    pass

            # Cancel any active load task
            if hasattr(self, '_active_load_task') and self._active_load_task:
                try:
                    if not self._active_load_task.done():
                        self._active_load_task.cancel()
                except:
                    pass

            # Clean up viewers
            self.cleanup_all_viewers()

            # Force clear all viewer/controller caches on tab close.
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                try:
                    self.viewer_controller.clear_all_caches_for_close()
                except Exception:
                    pass

            # Clean up viewer controller
            if hasattr(self, 'viewer_controller'):
                # Clean up viewer nodes efficiently
                if hasattr(self.viewer_controller, 'lst_nodes_viewer'):
                    for node in list(self.viewer_controller.lst_nodes_viewer):  # Use list() to avoid modification during iteration
                        try:
                            node: NodeViewer
                            vtk_widget: VTKWidget = getattr(node, 'vtk_widget', None)
                            if vtk_widget is not None and hasattr(vtk_widget, 'cleanup_image_viewer'):
                                try:
                                    vtk_widget.cleanup_image_viewer()
                                except:
                                    pass

                            # Safe cleanup: keep attributes but null them out to avoid AttributeError races
                            for attr in ('vtk_widget', 'widget', 'slider'):
                                try:
                                    if hasattr(node, attr):
                                        setattr(node, attr, None)
                                except:
                                    pass
                        except Exception as e:
                            self.logger.debug(f"Error cleaning up viewer node: {e}")

            # Check if lst_thumbnails_data exists before trying to access it
            if hasattr(self, 'lst_thumbnails_data') and self.lst_thumbnails_data:
                # Use slice assignment for faster clearing
                for i in range(len(self.lst_thumbnails_data)):
                    try:
                        item = self.lst_thumbnails_data[i]
                        if not item:
                            continue

                        # Release VTK data
                        if 'vtk_image_data' in item:
                            vtk_data = item['vtk_image_data']
                            if vtk_data and hasattr(vtk_data, 'GetPointData'):
                                try:
                                    vtk_data.GetPointData().SetScalars(None)
                                except:
                                    pass

                        # Clear metadata
                        try:
                            item.clear()
                        except:
                            pass
                    except Exception as e:
                        self.logger.debug(f"Error cleaning item {i}: {e}")

                self.lst_thumbnails_data.clear()

            # Clean up node viewer list
            if hasattr(self, 'lst_nodes_viewer'):
                self.lst_nodes_viewer.clear()

            # Clean up series names
            if hasattr(self, 'lst_series_name'):
                self.lst_series_name.clear()

            # Stop timers efficiently
            for timer_attr in ['_priority_display_timer', '_pipeline_task']:
                if hasattr(self, timer_attr):
                    timer = getattr(self, timer_attr)
                    if timer:
                        try:
                            if hasattr(timer, 'stop'):
                                timer.stop()
                        except:
                            pass

            # Belt-and-suspenders: stop the progressive grow timer on the viewer
            # controller.  clear_all_caches_for_close() already does this, but
            # if it throws early the timer would keep firing into a dead widget.
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                try:
                    if hasattr(self.viewer_controller, '_progressive_grow_timer'):
                        self.viewer_controller._progressive_grow_timer.stop()
                except Exception:
                    pass

            # Force garbage collection for VTK objects
            import gc as garbage_collector
            garbage_collector.collect()

            print("✅ [EXIT] PatientWidget cleaned up successfully")
        except Exception as e:
            self.logger.error(f"Error in exit_patient_widget: {e}")
            import traceback
            traceback.print_exc()

    def closeEvent(self, event):
        """Handle widget close event"""
        try:
            if getattr(self, '_pw_close_handled', False):
                # closeEvent already ran once. It can be re-entered via the
                # tab manager's close path (close_patient_tab calls
                # widget.close()); make it idempotent so the teardown below
                # is not repeated.
                event.accept()
                return
            self._pw_close_handled = True

            try:
                self.on_tab_deactivated()
            except Exception:
                pass

            # Cancel all background tasks before cleanup
            if hasattr(self, '_background_tasks'):
                for task in list(self._background_tasks):
                    try:
                        if not task.done():
                            task.cancel()
                            # Wait briefly for task to finish cancellation
                            try:
                                if hasattr(task, 'exception'):
                                    task.exception()  # Consume any exceptions from cancellation
                            except:
                                pass
                    except:
                        pass
                self._background_tasks.clear()

            # Cancel the series worker task if it exists
            if hasattr(self, '_series_worker_task') and self._series_worker_task:
                try:
                    if not self._series_worker_task.done():
                        self._series_worker_task.cancel()
                except:
                    pass

            # Clean up resources
            self.exit_patient_widget()

            # If we have a tab manager, notify it that this tab is being closed
            if hasattr(self, 'tab_manager') and self.tab_manager:
                try:
                    # Remove this tab from the custom tab manager
                    tab_index = self.tab_manager.find_tab_by_study_uid(self.study_uid)
                    if tab_index is not None and tab_index != -1:
                        print(f"Removing tab at index {tab_index} for study {self.study_uid}")
                        # Call the tab manager's close method to properly remove the tab
                        self.tab_manager.close_patient_tab(tab_index)
                except Exception as e:
                    print(f"Warning: Error interacting with tab manager: {e}")
                    
                    # Fallback: try to remove from tab manager's study_uid mapping directly
                    try:
                        if (hasattr(self.tab_manager, 'study_uid_to_tab') and 
                            self.study_uid in self.tab_manager.study_uid_to_tab):
                            del self.tab_manager.study_uid_to_tab[self.study_uid]
                            print(f"Fallback: Removed study {self.study_uid} from tab manager mapping")
                    except Exception as fallback_e:
                        print(f"Fallback removal also failed: {fallback_e}")

            # Release this widget's reference to the event loop.
            # IMPORTANT: self._event_loop holds the *single* qasync QEventLoop
            # that drives the ENTIRE application (created once in main.py as
            # `loop = QEventLoop(app)` and run via `loop.run_forever()`).
            # Calling .stop() on it terminates the whole application — that is
            # what previously made AI-PACS exit completely when a single
            # patient tab was closed, or when "Sync and Close" finished.
            # Closing one patient tab must only drop this widget's reference;
            # the shared loop must keep running for the rest of the app.
            # Background tasks for this widget were already cancelled above.
            if hasattr(self, '_event_loop') and self._event_loop:
                self._event_loop = None

            # Accept the close event
            event.accept()
        except Exception as e:
            self.logger.error(f"Error in closeEvent: {e}")
            event.accept()

    def _on_advanced_tool_applied(self, tool_name: str, result):
        """
        Handle results produced by advanced tools (volume, surface, mask, etc.)
        """
        print(f"[PatientWidget] Advanced tool applied: {tool_name}")

        widget = self.selected_widget
        viewer = getattr(widget, "image_viewer", None)

        if viewer is None:
            print("[PatientWidget] No active image viewer")
            return

        renderer = getattr(viewer, "renderer", None)

        def render_scene():
            renderer.ResetCamera()
            renderer.GetRenderWindow().Render()

        try:
            # =========================
            # Volume result
            # =========================
            if isinstance(result, vtk.vtkVolume) and renderer:
                renderer.AddVolume(result)
                render_scene()
                return

            # =========================
            # Single surface actor
            # =========================
            if isinstance(result, vtk.vtkActor) and renderer:
                renderer.AddActor(result)
                render_scene()
                return

            # =========================
            # Multiple actors / volumes
            # =========================
            if isinstance(result, dict) and renderer:
                for obj in result.values():
                    if isinstance(obj, vtk.vtkActor):
                        renderer.AddActor(obj)
                    elif isinstance(obj, vtk.vtkVolume):
                        renderer.AddVolume(obj)
                render_scene()
                return

            # =========================
            # Mask / image data
            # =========================
            if isinstance(result, vtk.vtkImageData):
                self.add_mask_to_viewer(viewer, result, tool_name)
                return

            print(f"[PatientWidget] Unsupported result type: {type(result)}")

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Failed to apply advanced tool result ({tool_name})",
                exc_info=True,
            )

    def add_mask_to_viewer(self, viewer, mask: vtk.vtkImageData, tool_name: str):
        """
        Add a binary mask to either a 2D or 3D viewer automatically.

        - 2D viewer  → RGBA overlay using vtkImageActor
        - 3D viewer  → Surface rendering using FlyingEdges / Marching Cubes

        Viewer type is inferred from its capabilities.
        """

        TOOL_COLORS = {
            "lung":    (1.0, 0.0, 0.0),
            "airway":  (0.0, 1.0, 0.0),
            "vessel":  (0.0, 0.0, 1.0),
            "bone":    (1.0, 1.0, 0.0),
            "default": (1.0, 0.0, 1.0),
        }

        def resolve_color(name: str):
            name = name.lower()
            return next(
                (color for key, color in TOOL_COLORS.items() if key in name),
                TOOL_COLORS["default"],
            )

        try:
            color = resolve_color(tool_name)

            # =========================
            # 2D VIEWER (Image Overlay)
            # =========================
            if hasattr(viewer, "GetRenderer") and hasattr(viewer, "GetSlice"):
                lut = vtk.vtkLookupTable()
                lut.SetNumberOfTableValues(2)
                lut.SetRange(0, 1)
                lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)
                lut.SetTableValue(1, *color, 0.3)
                lut.Build()

                mapper = vtk.vtkImageMapToColors()
                mapper.SetInputData(mask)
                mapper.SetLookupTable(lut)
                mapper.SetOutputFormatToRGBA()
                mapper.Update()

                actor = vtk.vtkImageActor()
                actor.GetMapper().SetInputConnection(mapper.GetOutputPort())

                z = viewer.GetSlice()
                dims = mask.GetDimensions()
                actor.SetDisplayExtent(0, dims[0] - 1, 0, dims[1] - 1, z, z)

                renderer = viewer.GetRenderer()
                renderer.AddActor(actor)

                if not hasattr(self.selected_widget, "_mask_actors"):
                    self.selected_widget._mask_actors = []
                self.selected_widget._mask_actors.append(actor)

                viewer.Render()
                return

            # =========================
            # 3D VIEWER (Surface)
            # =========================
            if hasattr(viewer, "renderer"):
                surface = vtk.vtkFlyingEdges3D()
                surface.SetInputData(mask)
                surface.SetValue(0, 0.5)
                surface.Update()

                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(surface.GetOutputPort())

                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor(*color)
                actor.GetProperty().SetOpacity(0.5)

                viewer.renderer.AddActor(actor)
                viewer.renderer.ResetCamera()
                viewer.renderer.GetRenderWindow().Render()
                return

            raise RuntimeError("Viewer type not supported")

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Failed to add mask ({tool_name}) to viewer", exc_info=True
            )

    def _on_app_theme_changed(self, theme: dict) -> None:
        """Handle application theme changes and retint all UI elements."""
        try:
            self._app_theme = theme or self._app_theme_manager.current_theme() if self._app_theme_manager else {}
            _pw_retint_widget_tree(self, self._app_theme)
        except Exception as e:
            logger.warning(f"Error retinting PatientWidget on theme change: {e}")

    def apply_filters_to_all_series_of_modality(self, modality: str, filter_params: dict):
        """
        Apply the same filters to all series of the same modality.
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []

            logger.info(f"[PatientWidget] Starting to apply filters to all {modality} series...")
            logger.info(f"Filter parameters: {filter_params}")

            # Find all series of the same modality
            series_to_update = []
            metadata_to_update = []
            indices_to_update = []

            for i, thumbnail_data in enumerate(self.lst_thumbnails_data):
                series_modality = thumbnail_data['metadata']['series'].get('modality', '').upper()
                if series_modality == modality:
                    series_to_update.append(thumbnail_data['vtk_image_data'])
                    metadata_to_update.append(thumbnail_data['metadata'])
                    indices_to_update.append(i)

            if not series_to_update:
                logger.warning(f"[PatientWidget] No {modality} series found to update")
                return

            logger.info(f"[PatientWidget] Found {len(series_to_update)} {modality} series to update")

            # Apply filters to all series of the same modality
            from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters_to_multiple_series
            logger.info(f"[PatientWidget] About to apply filters to {len(series_to_update)} series")
            updated_series = apply_filters_to_multiple_series(
                series_to_update,
                metadata_to_update,
                filter_params.get("filter_type", "smoothing"),
                filter_params.get("params", {})
            )
            logger.info(f"[PatientWidget] Filters applied successfully to {len(updated_series)} series")

            # Update the stored image data
            for idx, updated_data in zip(indices_to_update, updated_series):
                self.lst_thumbnails_data[idx]['vtk_image_data'] = updated_data
                logger.info(f"[PatientWidget] Updated series at index {idx} with filtered data")

            logger.info(f"[PatientWidget] Successfully updated {len(series_to_update)} {modality} series")

            # If the current viewer is showing a series of this modality, update it
            if (self.selected_widget and
                hasattr(self.selected_widget, 'image_viewer') and
                hasattr(self.selected_widget.image_viewer, 'metadata')):
                current_modality = self.selected_widget.image_viewer.metadata['series'].get('modality', '').upper()
                if current_modality == modality:
                    logger.info(f"[PatientWidget] Current viewer is showing {current_modality} series, updating...")
                    # Refresh the current view
                    # Find the current series index by matching the metadata
                    current_series_number = self.selected_widget.image_viewer.metadata['series'].get('series_number')
                    current_series_idx = -1
                    for i, thumbnail_data in enumerate(self.lst_thumbnails_data):
                        if thumbnail_data['metadata']['series'].get('series_number') == current_series_number:
                            current_series_idx = i
                            break

                    if current_series_idx != -1:
                        logger.info(f"[PatientWidget] Updating current viewer with filtered data for series {current_series_number}")
                        current_vtk_data = self.lst_thumbnails_data[current_series_idx]['vtk_image_data']
                        # Check if the viewer has the display_image method before calling it
                        if hasattr(self.selected_widget.image_viewer, 'display_image'):
                            self.selected_widget.image_viewer.display_image(current_vtk_data,
                                                                          self.lst_thumbnails_data[current_series_idx]['metadata'])
                        else:
                            # Alternative method for viewers that don't have display_image
                            # This might be a VTK widget that needs to be updated differently
                            logger.warning(f"[PatientWidget] Viewer doesn't have display_image method, trying alternative update")
                            # Update the viewer's image data directly if possible
                            if hasattr(self.selected_widget.image_viewer, 'reset_image_viewer'):
                                self.selected_widget.image_viewer.reset_image_viewer(
                                    current_vtk_data,
                                    self.lst_thumbnails_data[current_series_idx]['metadata']
                                )
                            else:
                                # If neither method is available, try to update through the VTK widget
                                logger.warning(f"[PatientWidget] Neither display_image nor reset_image_viewer available, trying direct update")
                                # Update the VTK widget's image data directly
                                if hasattr(self.selected_widget, 'start_process_series'):
                                    # Restart the series processing with the new data
                                    self.selected_widget.start_process_series(
                                        current_vtk_data,
                                        self.lst_thumbnails_data[current_series_idx]['metadata'],
                                        self.lst_thumbnails_data[current_series_idx]['metadata']['series']['series_number'],
                                        self.selected_widget.id_vtk_widget,
                                        self.metadata_fixed
                                    )

                        logger.info(f"[PatientWidget] Updated current viewer with filtered data")
                    else:
                        logger.warning(f"[PatientWidget] Could not find current series index for series number {current_series_number}")

        except Exception as e:
            logger.error(f"[PatientWidget] Error applying filters to all {modality} series: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def handle_tool_applied(self, tool_name: str, result):
        """
        Handle results from advanced tools including filters
        """
        try:
            print(f"[PatientWidget] Tool applied: {tool_name}")

            if tool_name == "filters_applied_to_modality":
                # Handle filter application to all series of a modality
                modality = result.get("modality", "")
                filter_params = result.get("filter_params", {})

                if modality:
                    self.apply_filters_to_all_series_of_modality(modality, filter_params)
            else:
                # Handle other tools (original functionality)
                self._on_advanced_tool_applied(tool_name, result)

        except Exception as e:
            print(f"[PatientWidget] Error handling tool applied: {e}", exc_info=True)

    def set_tab_manager(self, tab_manager):
        self.tab_manager = tab_manager

    def on_tab_activated(self):
        """Called when this patient tab becomes active in the main tab widget."""
        if self._is_active_patient_tab:
            return
        self._is_active_patient_tab = True
        try:
            print(f"✅ [PatientWidget] on_tab_activated study={self.study_uid}")
        except Exception:
            pass
        try:
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                self.viewer_controller.on_tab_activated()
        except Exception:
            pass

    def on_tab_deactivated(self):
        """Called when this patient tab is no longer the active tab."""
        if not self._is_active_patient_tab:
            return
        self._is_active_patient_tab = False
        try:
            print(f"🛑 [PatientWidget] on_tab_deactivated study={self.study_uid}")
        except Exception:
            pass
        try:
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                self.viewer_controller.on_tab_deactivated()
        except Exception:
            pass

