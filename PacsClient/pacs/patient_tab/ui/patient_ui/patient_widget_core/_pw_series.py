"""
Series loading, display, search, and download progress.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""

import asyncio
import logging as _logging
import re
import time
import traceback
from pathlib import Path
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QSlider
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
import logging
logger = logging.getLogger(__name__)

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))


class _PWSeriesMixin:
    """Series loading, display, search, and download progress."""

    def change_series_on_viewer(self, series_index, flag_change_selected_widget=True,
                                vtk_widget: VTKWidget = None, slider: QSlider = None,
                                allow_paired: bool = True):
        """
        Switch series with robust handling for layout changes and missing data
        Uses caching to avoid redundant lookups

        ✅ Always ensures viewers exist before attempting to display series
        """
        # Mark this series as "viewed" — it is being loaded into a viewport
        # (drag-drop or click both route through here). Session-scoped, in-memory;
        # see ThumbnailManager.mark_series_viewed. Isolated so a failure here can
        # never block the series switch itself.
        try:
            _tm = getattr(self, 'thumbnail_manager', None)
            if _tm is not None and hasattr(_tm, 'mark_series_viewed'):
                _tm.mark_series_viewed(series_index)
        except Exception:
            pass

        # ✅ OPTIMIZATION: موقع drag & drop، اولویت interactive را افزایش دهید
        try:
            if hasattr(self, 'viewer_controller') and hasattr(self.viewer_controller, 'zeta_boost'):
                # Signal ZetaBoost: این یک user-interactive action است
                self.viewer_controller._set_zeta_external_interactive_busy(
                    True, 
                    reason="user_drag_drop_active"
                )
                
                # استفاده از timer برای release کردن بعد از عملیات
                def release_interactive():
                    try:
                        if hasattr(self, 'viewer_controller'):
                            self.viewer_controller._set_zeta_external_interactive_busy(
                                False,
                                reason="drag_drop_complete"
                            )
                    except Exception:
                        pass
                
                QTimer.singleShot(1500, release_interactive)  # Release بعد از 1.5 ثانیه
        except Exception as e:
            print(f"⚠️ [INTERACTIVE_BOOST] error: {e}")
        
        # Delegate to viewer controller
        self.viewer_controller.change_series_on_viewer(series_index, flag_change_selected_widget, vtk_widget, slider,
                                   allow_paired)

    def _get_correct_study_path(self) -> str:
        """Get the correct study path, ensuring it's not pointing to a series subfolder"""
        from pathlib import Path
        
        if not self.import_folder_path:
            return None
            
        path = Path(self.import_folder_path)
        
        if self._has_direct_dicom_files(path):
            sibling_series_dirs = self._child_dicom_dirs(path.parent) if path.parent.exists() else []
            if path.name.isdigit() or len(sibling_series_dirs) > 1:
                return str(path.parent)
            return str(path)

        # If current path has numeric subfolders that are series, we're at study level
        # If current path is numeric and exists inside another folder, go up
        if path.name.isdigit() and path.parent.exists():
            parent = path.parent
            if len(self._child_dicom_dirs(parent)) > 1:
                return str(parent)
        
        return str(path)

    def _perform_series_switch(self, vtk_widget, metadata, vtk_image_data, series_idx, slider):
        """Perform the actual series switch with widget transfer"""
        try:
            series_number = metadata['series']['series_number']

            # Defensive validation for stale/invalid image payloads
            if not vtk_image_data:
                print(f"⚠️ [SWITCH RECOVERY] vtk_image_data missing for series {series_number}, attempting recovery")
                try:
                    study_path = self._get_correct_study_path()
                    if str(series_number).isdigit() and hasattr(self, 'viewer_controller'):
                        recovered = self.viewer_controller._load_single_series_on_demand(
                            int(series_number),
                            study_path,
                            target_vtk_widget=vtk_widget,
                            allow_paired=True,
                            expected_token=None,
                        )
                        if recovered:
                            vtk_image_data = self._find_series_fast(str(series_number))
                except Exception as recovery_error:
                    print(f"⚠️ [SWITCH RECOVERY] failed while attempting recovery: {recovery_error}")
                if not vtk_image_data:
                    print("❌ [SWITCH ABORT] vtk_image_data remains invalid after recovery")
                    return

            dims = vtk_image_data.GetDimensions()
            if dims[0] <= 0 or dims[1] <= 0 or dims[2] <= 0:
                print(f"⚠️ [SWITCH RECOVERY] Invalid dimensions {dims} for series {series_number}, attempting recovery")
                return

            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []

            # Check for combined viewer (if series has paired data)
            vtk_widget_data_2 = None
            metadata_2 = None

            # Look for paired series (same series name, different data)
            series_name = metadata['series']['series_name']
            for data in self.lst_thumbnails_data:
                if (data['metadata']['series']['series_name'] == series_name and
                    data['metadata']['series']['series_number'] != series_number):
                    vtk_widget_data_2 = data['vtk_image_data']
                    metadata_2 = data['metadata']
                    break
            
            # Perform switch
            if hasattr(vtk_widget, 'switch_series'):
                flag_switch = vtk_widget.switch_series(
                    vtk_image_data, 
                    metadata, 
                    series_idx,
                    vtk_widget_data_2,
                    metadata_2, 
                    self.metadata_fixed
                )
                
                if flag_switch:
                    self.reset_slider(vtk_widget, slider)
                    self.toolbar_manager.turn_off_all_tools()
                    
                    # Update corners if method exists
                    if vtk_widget.image_viewer:
                        vtk_widget.image_viewer.update_corners_actors()
                        
                    print(f"   ✅ Switch completed for series {series_number}")
                else:
                    print(f"   ⚠️ switch_series returned False")
            else:
                print(f"   ❌ vtk_widget does not have switch_series method")
                
        except Exception as e:
            print(f"❌ Error in _perform_series_switch: {e}")
            raise

    def _find_series_fast(self, series_number: str):
        """
        Fast path for series lookup - checks cache first
        Optimized for repeated access
        """
        series_number = str(series_number)
        
        # Super fast path: check cache
        if series_number in self.viewer_controller._series_cache:
            return self.viewer_controller._series_cache[series_number][0]  # Return vtk_data only

        # Medium path: check name cache
        if series_number in self.viewer_controller._series_name_cache:
            # Search and populate cache
            for data in self.lst_thumbnails_data:
                sn = str(data['metadata']['series']['series_number'])
                if sn == series_number:
                    self.viewer_controller._series_cache[series_number] = (
                        data['vtk_image_data'],
                        data['metadata'],
                        self.lst_thumbnails_data.index(data)
                    )
                    return data['vtk_image_data']
        
        # Slow path: search list
        for i, data in enumerate(self.lst_thumbnails_data):
            if str(data['metadata']['series']['series_number']) == series_number:
                # Cache for future
                self.viewer_controller._series_cache[series_number] = (
                    data['vtk_image_data'],
                    data['metadata'],
                    i
                )
                return data['vtk_image_data']
        
        return None

    def _invalidate_series_cache(self):
        """Invalidate caches when data structure changes"""
        self.viewer_controller._series_cache.clear()
        self.viewer_controller._series_name_cache.clear()

    def _trigger_download_if_needed(self, series_number: str):
        """Delegate to viewer controller"""
        self.viewer_controller._trigger_download_if_needed(series_number)

    def _show_loading_spinner(self, message="Loading..."):
        """Delegate to viewer controller"""
        self.viewer_controller._show_loading_spinner(message)

    def _hide_loading_spinner(self):
        """Delegate to viewer controller"""
        self.viewer_controller._hide_loading_spinner()

    def _load_single_series_on_demand(self, series_number: int, study_path: str = None) -> bool:
        """
        Load a single series with correct path resolution
        """
        # Delegate to viewer controller
        return self.viewer_controller._load_single_series_on_demand(series_number, study_path)

    def update_download_progress(self, current: int, total: int, percent: int):
        """
        Update download progress for this patient's study.
        
        This is called by the Download Manager to provide real-time progress updates.
        
        Args:
            current: Number of images downloaded so far
            total: Total number of images in the study
            percent: Progress percentage (0-100)
        """
        try:
            safe_current = max(current or 0, 0)
            safe_total = max(total or 0, 0)
            safe_percent = max(min(percent or 0, 100), 0)

            # Store progress info for display
            self._download_progress = {
                'current': safe_current,
                'total': safe_total,
                'percent': safe_percent
            }
            
            # Update toolbar if available
            if hasattr(self, 'toolbar') and self.toolbar:
                if hasattr(self.toolbar, 'update_download_progress'):
                    self.toolbar.update_download_progress(safe_current, safe_total, safe_percent)
            
            # Log major milestones
            if safe_percent % 25 == 0 or safe_percent == 100:
                self.logger.debug(f"Download progress: {safe_current}/{safe_total} ({safe_percent}%)")
                
        except Exception as e:
            self.logger.debug(f"Error updating download progress: {e}")

    def load_series_on_demand(self, series_number: str):
        """
        Load a series on demand with simple queue-based coordination
        Avoids async lock conflicts by using non-blocking async calls
        """
        # Delegate to viewer controller
        self.viewer_controller.load_series_on_demand(series_number)

    async def load_multiple_series_parallel(self, series_numbers: list, max_concurrent=8):
        """
        Load multiple series in parallel with a concurrency limit.
        This is much faster than loading series one by one.
        
        Args:
            series_numbers: List of series numbers to load
            max_concurrent: Maximum number of series to load simultaneously (default: 3)
        """
        print(f"\n🚀 [PARALLEL LOAD] Starting batch loading of {len(series_numbers)} series (max {max_concurrent} concurrent)...")
        
        from concurrent.futures import ThreadPoolExecutor
        import time
        
        _batch_start = time.time()
        loaded_count = 0
        failed_count = 0
        
        # Filter out already loaded series
        series_to_load = []
        for sn in series_numbers:
            series_key = f"series_{sn}"
            if series_key not in self.lst_series_name:
                series_to_load.append(sn)
            else:
                print(f"   ⏭️  Series {sn} already loaded, skipping")
        
        if not series_to_load:
            print("   ℹ️  No series need to be loaded")
            return
        
        print(f"   📋 Loading {len(series_to_load)} series: {series_to_load}")
        
        progress_dialog = None  # Set to None since we're not showing the dialog
        
        # Create a thread pool for concurrent loading
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # Submit all tasks
            futures = {}
            for series_number in series_to_load:
                future = executor.submit(self._load_single_series_on_demand, int(series_number))
                futures[future] = series_number
            
            # Wait for all tasks to complete and track progress
            from concurrent.futures import as_completed
            for i, future in enumerate(as_completed(futures), 1):
                series_number = futures[future]
                try:
                    success = future.result()
                    if success:
                        loaded_count += 1
                        print(f"   ✅ [{i}/{len(series_to_load)}] Series {series_number} loaded")
                    else:
                        failed_count += 1
                        print(f"   ❌ [{i}/{len(series_to_load)}] Series {series_number} failed")
                except Exception as e:
                    failed_count += 1
                    print(f"   ❌ [{i}/{len(series_to_load)}] Series {series_number} exception: {e}")
                
                # Update progress dialog
                if progress_dialog:
                    try:
                        progress_dialog.setValue(i)
                        progress_dialog.setLabelText(
                            f"Loading series {i}/{len(series_to_load)}\n"
                            f"✅ Loaded: {loaded_count} | ❌ Failed: {failed_count}"
                        )
                        QApplication.processEvents()
                        if progress_dialog.wasCanceled():
                            print("   ⚠️ User cancelled parallel loading")
                            break
                    except Exception:
                        pass
        
        # Close progress dialog
        if progress_dialog:
            try:
                progress_dialog.close()
            except Exception:
                pass
        
        _batch_elapsed = time.time() - _batch_start
        print(f"\n✅ [PARALLEL LOAD] Batch complete in {_batch_elapsed:.2f}s: {loaded_count} loaded, {failed_count} failed")
        print(f"   ⚡ Average: {_batch_elapsed/len(series_to_load):.2f}s per series")
        
        # Refresh thumbnails if needed
        if loaded_count > 0:
            try:
                QTimer.singleShot(100, self.update_thumbnails_after_batch_load)
            except Exception:
                pass

    def update_thumbnails_after_batch_load(self):
        """
        Refresh thumbnails display after batch loading is complete
        """
        try:
            print(f"   🔄 Refreshing thumbnails display...")
            # Force thumbnail panel to update
            if hasattr(self, 'show_thumbnails'):
                self.show_thumbnails()
        except Exception as e:
            print(f"   ⚠️  Error refreshing thumbnails: {e}")

    def _load_series_in_thread(self, series_number: str):
        """
        Load series in a background thread (for cases where event loop is not available)
        """
        try:
            from concurrent.futures import ThreadPoolExecutor

            def load_task():
                return self._load_single_series_on_demand(int(series_number))

            # Use thread pool to load series
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(load_task)

        except Exception:
            pass

    async def _async_load_and_display_series(self, series_number: str):
        """
        Async method to load and display a series without blocking UI.
        Uses asyncio lock to prevent race conditions with contextvars.
        After loading, it immediately displays the series in the first viewer.

        Args:
            series_number: Can be either a simple series number (e.g., "1", "2")
                          or a Series Instance UID (e.g., "1.3.12.2.1107...")
        """
        try:
            # Yield control first
            await asyncio.sleep(0)

            # Validate widget state
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            # ✅ FIX: Handle both series numbers and Series Instance UIDs
            # Try to convert to integer (simple series number)
            try:
                series_int = int(series_number)
            except ValueError:
                # Not a simple number - might be a Series Instance UID
                # Try to find the series in loaded data by UID
                self.logger.warning(f"Series identifier '{series_number}' is not a simple number - searching by UID")

                # Search for series by UID in loaded thumbnails
                for idx, thumb_data in enumerate(self.lst_thumbnails_data):
                    series_uid = thumb_data.get('metadata', {}).get('series', {}).get('series_uid', '')
                    if series_uid == series_number:
                        # Found it - use the index as series number
                        series_int = idx + 1  # Series numbers are 1-based
                        self.logger.info(f"Found series UID {series_number} at index {series_int}")
                        break
                else:
                    # Not found in loaded data - series may not be downloaded yet
                    self.logger.warning(f"Series UID {series_number} not found in loaded thumbnails - may need download")
                    return

            # Yield before heavy operation
            await asyncio.sleep(0)

            # Use asyncio.to_thread to properly handle contextvars and prevent RuntimeError
            try:
                success = await asyncio.to_thread(
                    self._load_single_series_on_demand,
                    series_int
                )
            except AttributeError:
                # Fallback for Python < 3.9 - yield before and after
                await asyncio.sleep(0)
            except AttributeError:
                # Fallback for Python < 3.9
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None,
                    self._load_single_series_on_demand,
                    series_int
                )

            if success:
                self.logger.info(f"Series {series_number} loaded successfully")
                # Mark as ready in UI
                QTimer.singleShot(0, lambda: self._display_series_after_load(series_number))
            else:
                self.logger.warning(f"Failed to load series {series_number}")

        except asyncio.CancelledError:
            self.logger.debug(f"Load cancelled for series {series_number}")
            raise
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error loading series {series_number}: {e}")
        except Exception as e:
            self.logger.error(f"Error loading series {series_number}: {e}", exc_info=True)

    def _display_series_after_load(self, series_number: str):
        """
        Mark series ready; for the first downloaded series, display it in all viewers
        and hide loading.
        """
        try:
            # Validate widget state
            if not self.isVisible():
                return

            if (not self._first_series_displayed) or self._any_viewer_empty():
                if self._display_first_series_in_all_viewers(series_number):
                    self._mark_first_series_displayed()
                    return
            
            # Mark as ready in thumbnail manager
            if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                self.thumbnail_manager.set_series_ready(str(series_number))
                self.thumbnail_manager.apply_border_states_new()
                self.logger.debug(f"Series {series_number} marked as ready")
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error in _display_series_after_load: {e}")
        except Exception as e:
            self.logger.error(f"Error in _display_series_after_load: {e}", exc_info=True)
            traceback.print_exc()

    def _any_viewer_empty(self) -> bool:
        """Delegate to viewer controller"""
        return self.viewer_controller._any_viewer_empty()

    def _auto_open_first_series_for_eagle_eye(self):
        """Ensure first series is visible when Eagle Eye is opened."""
        try:
            if self._first_series_displayed and not self._any_viewer_empty():
                return
            self._eagle_eye_autoload_attempts = 0
            self._eagle_eye_autoload_inflight = True
            self._try_auto_open_first_series_for_eagle_eye()
        except Exception as e:
            print(f"⚠️ [EAGLE EYE] Failed to auto-open first series: {e}")

    def _try_auto_open_first_series_for_eagle_eye(self):
        """Retry helper to wait for thumbnails/viewers before opening first series."""
        try:
            if not getattr(self, '_eagle_eye_autoload_inflight', False):
                return

            if self._first_series_displayed and not self._any_viewer_empty():
                self._eagle_eye_autoload_inflight = False
                return

            has_viewers = bool(getattr(self, 'lst_nodes_viewer', None))
            has_thumbs = bool(getattr(self, 'lst_thumbnails_data', None))

            if has_viewers and has_thumbs:
                if self._display_first_series_in_viewer():
                    self._eagle_eye_autoload_inflight = False
                    return

            self._eagle_eye_autoload_attempts += 1
            if self._eagle_eye_autoload_attempts >= 8:
                self._eagle_eye_autoload_inflight = False
                return

            QTimer.singleShot(50, self._try_auto_open_first_series_for_eagle_eye)
        except Exception as e:
            self._eagle_eye_autoload_inflight = False
            print(f"⚠️ [EAGLE EYE] Auto-open retry failed: {e}")

    async def _do_load_series(self, series_number: str):
        """Internal method to actually load the series"""
        try:
            # Use asyncio.to_thread instead of run_in_executor to better handle contextvars
            # asyncio.to_thread copies contextvars correctly and prevents RuntimeError
            try:
                success = await asyncio.to_thread(
                    self._load_single_series_on_demand,
                    int(series_number)
                )
            except AttributeError:
                # Fallback for Python < 3.9
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None,
                    self._load_single_series_on_demand,
                    int(series_number)
                )
            
            if success:
                print(f"   ✅ Series {series_number} loaded successfully!")

            if success:
                print(f"   ✅ Series {series_number} loaded successfully!")

                print(f"   ℹ️ Series {series_number} ready - user can click thumbnail to display")

            else:
                print(f"   ❌ Failed to load series {series_number}")

        except Exception as e:
            print(f"❌ [ASYNC LOAD ERROR] Failed to load series {series_number}: {e}")
            import traceback
            traceback.print_exc()

    async def _load_and_display_series_async(self, series_number, flag_change_selected_widget, vtk_widget, slider):
        """
        بارگذاری و نمایش سری به صورت asynchronous برای جلوگیری از blocking UI
        """
        import time
        _start = time.time()

        try:
            # بارگذاری در background thread
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)

            # Run loading in background
            loop = asyncio.get_event_loop()
            try:
                loaded = await loop.run_in_executor(
                    executor,
                    self._load_single_series_on_demand,
                    series_number
                )
            finally:
                # One-shot pool: release its worker thread as soon as the await
                # completes so it cannot accumulate one live thread per series load.
                executor.shutdown(wait=False)

            if not loaded:
                print(f"[ASYNC LOAD ERROR] Failed to load series {series_number}")
                self._hide_loading_spinner()
                return

            # پیدا کردن داده‌های لود شده
            vtk_image_data = None
            metadata = None
            for i in range(len(self.lst_thumbnails_data)):
                if int(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == int(series_number):
                    vtk_image_data = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata = self.lst_thumbnails_data[i]['metadata']
                    break

            if metadata is None:
                self._hide_loading_spinner()
                return

            # Mark as ready
            self.thumbnail_manager.set_series_ready(str(series_number))

            # Hide spinner
            self._hide_loading_spinner()

            # حالا نمایش بده - بقیه کد change_series_on_viewer را اینجا اجرا کن
            self._display_loaded_series(
                series_number, vtk_image_data, metadata,
                flag_change_selected_widget, vtk_widget, slider
            )

        except Exception as e:
            print(f"[ASYNC LOAD ERROR] {e}")
            import traceback
            traceback.print_exc()
            self._hide_loading_spinner()

    def _display_loaded_series(self, series_number, vtk_image_data, metadata,
                               flag_change_selected_widget, vtk_widget, slider):
        """
        Display series that has been loaded - optimized with caching
        This function handles only the visualization part
        """
        try:
            # Check if we have a selected_widget set
            if flag_change_selected_widget and self.selected_widget is None:
                print(f"⚠️ [DISPLAY] selected_widget is None, trying to set from lst_nodes_viewer")
                if hasattr(self, 'lst_nodes_viewer') and self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                    self.selected_widget = self.lst_nodes_viewer[0].vtk_widget
                    self.slider = self.lst_nodes_viewer[0].slider
                    print(f"   ✅ Set selected_widget from first viewer")
                else:
                    print(f"   ❌ No viewers available!")
                    return

            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []

            # Find paired series data efficiently using cache
            vtk_widget_data_2 = None
            metadata_2 = None
            series_idx = None
            
            # Use cached name if available
            series_name = metadata.get('series', {}).get('series_name')
            
            for i in range(len(self.lst_thumbnails_data)):
                data_series_number = self.lst_thumbnails_data[i]['metadata']['series']['series_number']
                if str(data_series_number) == str(series_number):
                    series_idx = i
                # Check if same series name but different data
                if (self.lst_thumbnails_data[i]['metadata']['series'].get('series_name') == series_name and
                    data_series_number != series_number and 
                    id(self.lst_thumbnails_data[i]['vtk_image_data']) != id(vtk_image_data)):
                    vtk_widget_data_2 = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata_2 = self.lst_thumbnails_data[i]['metadata']
                    break

            if series_idx is None:
                print(f"❌ [DISPLAY] Could not resolve series index for series_number={series_number}")
                return

            if flag_change_selected_widget:  # change on first viewer
                flag_switch = self.selected_widget.switch_series(vtk_image_data, metadata, series_idx,
                                                                 vtk_widget_data_2,
                                                                 metadata_2, self.metadata_fixed)
                vtk_widget = self.selected_widget
                slider = self.slider

            else:  # change on selected viewer
                flag_switch = vtk_widget.switch_series(vtk_image_data, metadata, series_idx, vtk_widget_data_2,
                                                       metadata_2, self.metadata_fixed)

            if flag_switch is True:
                self.reset_slider(vtk_widget, slider)
                self.toolbar_manager.turn_off_all_tools()
                vtk_widget.resizeEvent(None)
                # Check if image_viewer exists before updating
                if vtk_widget.image_viewer is not None:
                    vtk_widget.image_viewer.update_corners_actors()
                
                # Notify priority manager that this series is now in the viewer
                # This promotes the series to CRITICAL priority
                if PRIORITY_MANAGER_AVAILABLE and self.study_uid:
                    try:
                        series_uid = metadata.get('series', {}).get('series_uid', '')
                        # Determine layout position (0 for primary viewer)
                        layout_position = 0
                        if vtk_widget and self.lst_nodes_viewer:
                            for i, node in enumerate(self.lst_nodes_viewer):
                                if hasattr(node, 'vtk_widget') and node.vtk_widget == vtk_widget:
                                    layout_position = i
                                    break
                        
                        # Legacy priority manager removed - Zeta handles priority internally
                        # priority_manager = get_download_priority_manager()
                        # priority_manager.on_series_loaded_in_viewer(...)
                        logger.debug(f"Series {series_number} loaded in viewer (layout: {layout_position})")
                    except Exception as pm_error:
                        logger.debug(f"Could not notify priority manager: {pm_error}")

        except Exception as e:
            print(f'❌ [DISPLAY] Error on display loaded series: {e}')
            import traceback
            traceback.print_exc()
            return False

    def _show_viewer_loading_all(self):
        """Delegate to viewer controller"""
        self.viewer_controller._show_viewer_loading_all()

    def _hide_viewer_loading_all(self):
        """Delegate to viewer controller"""
        self.viewer_controller._hide_viewer_loading_all()

    def _display_first_series_in_viewer(self):
        """Delegate to viewer controller"""
        return self.viewer_controller._display_first_series_in_viewer()

    def _mark_first_series_displayed(self):
        """Delegate to viewer controller"""
        self.viewer_controller._mark_first_series_displayed()

    def _display_first_series_in_all_viewers(self, series_number: str) -> bool:
        """Delegate to viewer controller"""
        return self.viewer_controller._display_first_series_in_all_viewers(series_number)

    def on_download_completion(self, study_uid: str, success: bool, is_cancelled: bool = False):
        """
        ✅ GRACEFUL HANDLING: Called when download completes, fails, or is cancelled
        
        Args:
            study_uid: Study UID that was downloading
            success: Whether download succeeded
            is_cancelled: Whether download was cancelled by user
        """
        print(f"\n{'='*60}")
        print(f"📥 [Download Completion] study={study_uid}")
        print(f"   success={success}, cancelled={is_cancelled}")
        
        try:
            # Handle cancellation gracefully
            if is_cancelled:
                print(f"⏸️ Download was cancelled - updating UI gracefully")
                
                # Show subtle message (not popup)
                if hasattr(self, 'status_label'):
                    self.status_label.setText(f"Download cancelled for study {study_uid[:20]}...")
                    self.status_label.setStyleSheet("color: #FFA500;")  # Orange
                
                # Still refresh UI if some data was downloaded
                try:
                    self.refresh_after_download(study_uid)
                except Exception as e:
                    print(f"⚠️ Error refreshing after cancellation: {e}")
                
                # Log cancellation without alarming user
                self.logger.info(f"Download cancelled: {study_uid}")
                return
            
            # Handle normal completion/failure
            if success:
                print(f"✅ Download completed successfully")
                try:
                    self.refresh_after_download(study_uid)
                except Exception as e:
                    print(f"⚠️ Error refreshing after download: {e}")
            else:
                print(f"❌ Download failed")
                # Show error message to user
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Download Failed",
                    f"Failed to download study. Check your connection and try again."
                )
                
        except Exception as e:
            print(f"❌ Error in download completion handler: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"{'='*60}\n")

    def _on_retry_series_download(self, series_number: str, study_uid: str, series_uid: str = None):
        """
        Handle retry download request from the retry button on a series thumbnail.
        
        Args:
            series_number: Series number (string)
            study_uid: Study UID 
            series_uid: Series UID (optional)
        """
        try:
            print(f"🔄🔄 [PatientWidget] ========== RETRY DOWNLOAD TRIGGERED ==========")
            print(f"   Series Number: {series_number}")
            print(f"   Study UID: {study_uid}")
            print(f"   Series UID: {series_uid}")
            print(f"🔄🔄 [PatientWidget] ====================================================")
            
            # Avoid scroll-to-top on thumbnail refresh for retry downloads
            self._suppress_thumb_scroll_reset = True

            # Get the download manager widget from home_ui
            try:
                from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
                
                home_widget = get_home_widget()
                print(f"🔍 [PatientWidget] home_widget found: {home_widget is not None}")
                
                if home_widget and hasattr(home_widget, '_get_or_create_download_manager_tab'):
                    print(f"🔍 [PatientWidget] home_widget has _get_or_create_download_manager_tab method")
                    # Get the download manager (don't activate the tab)
                    download_manager = home_widget._get_or_create_download_manager_tab(activate_tab=False)
                    print(f"🔍 [PatientWidget] download_manager obtained: {download_manager is not None}")
                    
                    if download_manager:
                        print(f"✅ [PatientWidget] Found download manager, triggering SERIES-SPECIFIC retry")

                        # Preferred single API: apply CRITICAL intent + start retry.
                        if hasattr(download_manager, 'request_critical_series_download'):
                            print(
                                f"🚀 [PatientWidget] Calling request_critical_series_download "
                                f"with series_number={series_number}, series_uid={series_uid}"
                            )
                            download_manager.request_critical_series_download(study_uid, series_number, series_uid)
                            print(f"✅✅ [PatientWidget] Critical series request initiated for series {series_number}")
                        # Backward-compatible fallback for older manager versions
                        elif hasattr(download_manager, '_on_series_retry'):
                            print(f"🚀 [PatientWidget] Fallback _on_series_retry with series_number={series_number}, series_uid={series_uid}")
                            try:
                                if hasattr(download_manager, 'set_viewed_series'):
                                    download_manager.set_viewed_series(study_uid, str(series_number))
                            except Exception as _e:
                                print(f"⚠️ [PatientWidget] set_viewed_series fallback failed: {_e}")
                            download_manager._on_series_retry(study_uid, series_number, series_uid)
                            print(f"✅✅ [PatientWidget] Fallback series retry initiated for series {series_number}")
                        else:
                            print(f"⚠️ [PatientWidget] Download manager doesn't have _on_series_retry method")
                            print(f"⚠️ [PatientWidget] Falling back to full study retry")
                            if hasattr(download_manager, '_on_per_patient_retry'):
                                download_manager._on_per_patient_retry(study_uid)
                                print(f"✅ [PatientWidget] Full study retry initiated")
                            else:
                                from PySide6.QtWidgets import QMessageBox
                                QMessageBox.warning(
                                    self, 
                                    "Retry Download",
                                    "Download retry method not found.\n"
                                    "Please use the Download Manager tab to retry downloads."
                                )
                    else:
                        print(f"⚠️ [PatientWidget] Could not get download manager widget")
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.information(
                            self,
                            "Download Manager",
                            "Download manager is not available.\n"
                            "Please open the Download Manager tab to retry downloads."
                        )
                else:
                    print(f"⚠️ [PatientWidget] Could not get home_widget or _get_or_create_download_manager_tab method")
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        "Retry Download",
                        "Download manager is not available.\n"
                        "Please open the Download Manager tab to retry downloads."
                    )
                    
            except Exception as e:
                print(f"⚠️ [PatientWidget] Error accessing download manager: {e}")
                import traceback
                traceback.print_exc()
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, 
                    "Download Manager",
                    f"Error accessing download manager: {str(e)}\n"
                    "Please use the Download Manager tab to retry downloads."
                )
        
        except Exception as e:
            print(f"❌ Error in _on_retry_series_download: {e}")
            import traceback
            traceback.print_exc()

