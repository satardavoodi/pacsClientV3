"""
Pipeline managers, startup, local series discovery, progressive display.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""

import asyncio
import contextlib
import logging
import logging as _logging
import threading
import time
import traceback
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from PacsClient.pacs.patient_tab.utils import check_and_get_thumbnails, get_quickly_series_info, load_images, load_images_from_server, save_image_as_png
from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
from PacsClient.utils import CallerTypes

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))
logger = logging.getLogger(__name__)


class _PWPipelineMixin:
    """Pipeline managers, startup, local series discovery, progressive display."""

    def _create_init_overlay(self):
        """Show the branded empty-layout loader without any text."""
        try:
            if getattr(self, '_init_overlay', None) is not None:
                return self._init_overlay

            from PacsClient.components.loading_overlay import AiPacsLoadingOverlay

            anchor = getattr(self, 'center_widget', None) or self
            self._init_overlay = AiPacsLoadingOverlay.show_overlay(
                anchor,
                title="",
                status="",
                subtitle="",
                minimal=True,
                pass_through=True,
            )
            return self._init_overlay
        except Exception:
            logger.exception("Failed to create init overlay")
            self._init_overlay = None
            return None

    def _update_overlay_size(self):
        """Update overlay size to match widget size - ensure it covers everything"""
        if hasattr(self, '_init_overlay') and self._init_overlay and self._init_overlay.isVisible():
            # Try widget size first
            widget_size = self.size()
            if widget_size.width() > 0 and widget_size.height() > 0:
                self._init_overlay.setGeometry(0, 0, widget_size.width(), widget_size.height())
                self._init_overlay.raise_()
                return
            
            # Try parent size
            parent = self.parent()
            if parent:
                parent_size = parent.size()
                if parent_size.width() > 0 and parent_size.height() > 0:
                    self._init_overlay.setGeometry(0, 0, parent_size.width(), parent_size.height())
                    self._init_overlay.raise_()
                    return
            
            # Fallback: use very large size to ensure coverage
            self._init_overlay.setGeometry(0, 0, 10000, 10000)
            self._init_overlay.raise_()

    def _start_pipeline(self):
        """Deferred pipeline start - called after window is painted"""
        print("🚀 _start_pipeline called")

        # ✅ PREVENT CONCURRENT EXECUTION
        if self._pipeline_running:
            print("⚠️ Pipeline already running, skipping...")
            return

        try:
            self._pipeline_running = True
            print("✅ Pipeline flag set to True")
            
            # ✅ FLICKER FIX: Disable UI updates during entire initialization
            self.setUpdatesEnabled(False)

            # ✅ Use QTimer to schedule pipeline in the main thread
            QTimer.singleShot(0, lambda: self._run_pipeline_safely())

        except Exception as e:
            print(f"❌ _start_pipeline error: {e}")
            import traceback
            traceback.print_exc()
            self._pipeline_running = False
            self.setUpdatesEnabled(True)  # Re-enable on error
            self._hide_init_overlay()

    def _run_pipeline_safely(self):
        """Run pipeline safely, handling async context properly"""
        try:
            # ✅ RUN PIPELINE SYNCHRONOUSLY - AVOID ASYNC LOCK CONFLICTS
            # Pipeline is already synchronous at its core, so no need for async wrapper
            print("🔄 Running pipeline_manager synchronously...")
            try:
                self.pipeline_manager(
                    self._deferred_caller,
                    self._deferred_size
                )
                print("✅ Pipeline completed successfully")
            except Exception as e:
                print(f"❌ Pipeline error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                self._pipeline_running = False
                self._is_initializing = False  # ✅ FLICKER FIX: Mark initialization complete
                # ✅ FLICKER FIX: Re-enable UI updates after pipeline completes
                self.setUpdatesEnabled(True)
                self.update()  # Single repaint
                self._settle_empty_layout_idle_state()
                # Manual-only layout policy: keep locally available series in the
                # thumbnail lane until the user explicitly places them in a viewer.
                print("✅ Pipeline flag reset to False")
                
                # ✅ Register buttons with safeguard after UI is ready
                QTimer.singleShot(100, self._register_buttons_with_safeguard)

        except Exception as e:
            print(f"❌ _run_pipeline_safely error: {e}")
            import traceback
            traceback.print_exc()
            self._pipeline_running = False
            self._is_initializing = False
            self.setUpdatesEnabled(True)  # Re-enable on error
            self._hide_init_overlay()

    def _register_buttons_with_safeguard(self):
        """
        Register all interactive buttons with the button safeguard.
        This prevents multiple simultaneous button clicks that could cause hangs.
        """
        try:
            buttons_to_register = []
            
            # Sidebar buttons
            if hasattr(self, 'btn_series'):
                buttons_to_register.append(self.btn_series)
            if hasattr(self, 'btn_reception'):
                buttons_to_register.append(self.btn_reception)
            if hasattr(self, 'btn_ai_chat'):
                buttons_to_register.append(self.btn_ai_chat)
            if hasattr(self, 'btn_ai_module'):
                buttons_to_register.append(self.btn_ai_module)
            if hasattr(self, 'btn_advanced_tools'):
                buttons_to_register.append(self.btn_advanced_tools)
            
            # Advanced Analysis buttons
            if hasattr(self, 'btn_advanced_mpr'):
                buttons_to_register.append(self.btn_advanced_mpr)
            if hasattr(self, 'btn_stitching'):
                buttons_to_register.append(self.btn_stitching)
            
            # Reception panel buttons
            if hasattr(self, 'btn_open_folder_attachments'):
                buttons_to_register.append(self.btn_open_folder_attachments)
            
            # Register all buttons
            self.button_safeguard.register_buttons(buttons_to_register)
            
            # Also auto-discover any other buttons we might have missed
            self.button_safeguard.auto_discover_buttons()
            
            logger.info(f"[PatientWidget] Registered {len(buttons_to_register)} buttons with safeguard")
            
        except Exception as e:
            logger.error(f"[PatientWidget] Error registering buttons with safeguard: {e}")
            import traceback
            traceback.print_exc()

    def _ensure_initial_series_visible(self):
        """Legacy watchdog — neutered.  First-series display is now signal-driven.

        Kept as a no-op stub so any stale references don't raise AttributeError.
        """
        return

    def _settle_empty_layout_idle_state(self):
        """Clear startup loading chrome when layouts are intentionally empty.

        Under the manual-only layout policy, the patient can open with viewers
        created but no series placed yet. At that point the global init overlay
        and per-viewport loading GIFs should be removed immediately so the user
        sees a clean drop-ready layout instead of a fake loading state.
        """
        try:
            if bool(getattr(self, '_first_series_displayed', False)):
                return
            self._hide_init_overlay()
            if hasattr(self, '_hide_viewer_loading_all'):
                self._hide_viewer_loading_all()
            try:
                self.loading_complete.emit()
            except Exception:
                pass
        except Exception:
            logger.exception("Failed to settle empty-layout idle state")

    def _check_and_load_local_first_series(self):
        """Discover local series without auto-inserting them into viewers.

        A patient can open with cached local series already present on disk, but
        Block A/thumbnails must not automatically push those series into Block B
        layouts.  This method therefore only validates local availability and
        maintains retry bookkeeping while the viewer shell is being created.
        """
        try:
            # Already displayed — nothing to do
            if self._first_series_displayed:
                setattr(self, '_local_first_series_retry_count', 0)
                return

            # Widget deleted guard
            try:
                _ = self.isVisible()
            except RuntimeError:
                return

            from pathlib import Path
            study_path = Path(self.import_folder_path) if self.import_folder_path else None
            if not study_path or not study_path.exists():
                return

            local_series = self._discover_local_series_candidates()

            viewer_controller = getattr(self, 'viewer_controller', None)
            viewer_nodes = list(getattr(viewer_controller, 'lst_nodes_viewer', []) or [])
            if not viewer_nodes:
                retry_count = int(getattr(self, '_local_first_series_retry_count', 0) or 0)
                if retry_count < 10:
                    setattr(self, '_local_first_series_retry_count', retry_count + 1)
                    logger.info(
                        "[LOCAL_CHECK] deferring first local series replay: viewers_not_ready retry=%s",
                        retry_count + 1,
                    )
                    QTimer.singleShot(150, self._check_and_load_local_first_series)
                return
            setattr(self, '_local_first_series_retry_count', 0)

            # [H7-P3] Local series discovery
            try:
                import os as _h7_os
                _h7_study_uid = getattr(self, 'study_uid', 'unknown')
                _h7_dm_active = False
                try:
                    from modules.zeta_boost import ZetaBoostEngine
                    _h7_dm_active = int(getattr(ZetaBoostEngine, '_global_active_download_count', 0) or 0) > 0
                except Exception:
                    pass
                _h7_candidates = []
                for _c in (local_series or []):
                    _c_path = _c.get("path")
                    _c_count = 0
                    if _c_path:
                        try:
                            _c_count = sum(1 for f in _h7_os.scandir(str(_c_path)) if f.name.lower().endswith('.dcm'))
                        except Exception:
                            pass
                    _h7_candidates.append(f"{_c.get('series_number')}:{_c_count}")
                logger.info(
                    "[H7-P3] study=%s first_series_displayed=%s candidates=[%s] dm_active=%s",
                    _h7_study_uid, self._first_series_displayed,
                    ",".join(_h7_candidates) if _h7_candidates else "none",
                    _h7_dm_active,
                )
            except Exception:
                pass

            if not local_series:
                # No local data yet — download will fire series_downloaded later
                return

            first_series = str(local_series[0]["series_number"])
            print(
                f"📂 [LOCAL_CHECK] Found local series {first_series} — manual placement required; "
                f"auto-display disabled"
            )
        except Exception as e:
            print(f"⚠️ [LOCAL_CHECK] Error: {e}")

    @staticmethod
    def _has_direct_dicom_files(path: Path) -> bool:
        try:
            if not path or not path.exists() or not path.is_dir():
                return False
            for pattern in ("*.dcm", "*.DCM", "*.dicom", "*.DICOM"):
                if next(path.glob(pattern), None):
                    return True
        except Exception:
            return False
        return False

    @classmethod
    def _child_dicom_dirs(cls, path: Path) -> list[Path]:
        try:
            if not path or not path.exists() or not path.is_dir():
                return []
            return [
                child for child in path.iterdir()
                if child.is_dir() and cls._has_direct_dicom_files(child)
            ]
        except Exception:
            return []

    def _discover_local_series_candidates(self) -> list[dict]:
        """Discover locally available series for cached imports.

        Supports:
        - flat study folders where the selected import folder contains DICOM files directly
        - study folders with series subdirectories, including non-numeric names
        """
        study_path = Path(self.import_folder_path) if self.import_folder_path else None
        if not study_path or not study_path.exists() or not study_path.is_dir():
            return []

        candidate_paths = []
        if self._has_direct_dicom_files(study_path):
            candidate_paths.append(study_path)
        candidate_paths.extend(self._child_dicom_dirs(study_path))

        series_candidates = []
        seen_paths = set()
        for path in candidate_paths:
            key = str(path).lower()
            if key in seen_paths:
                continue
            seen_paths.add(key)

            info = get_quickly_series_info(path)
            if not info:
                continue

            series_number = str(info.get("series_number", "")).strip()
            if not series_number:
                continue

            if series_number.isdigit():
                sort_key = (0, int(series_number), path.name.lower())
            else:
                sort_key = (1, series_number.lower(), path.name.lower())

            series_candidates.append(
                {
                    "series_number": series_number,
                    "path": path,
                    "sort_key": sort_key,
                }
            )

        series_candidates.sort(key=lambda item: item["sort_key"])
        return series_candidates

    def _hide_init_overlay(self):
        overlay = getattr(self, '_init_overlay', None)
        if overlay is None:
            return
        try:
            from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
            AiPacsLoadingOverlay.hide_overlay(overlay, fade_ms=0, delay_ms=0)
        except Exception:
            logger.exception("Failed to hide init overlay")
            try:
                overlay.hide()
                overlay.deleteLater()
            except Exception:
                pass
        finally:
            self._init_overlay = None

    def pipeline_manager(self, caller, size_init_viewers=(1, 1)):
        _t0 = time.perf_counter()
        size_init_viewers = self._get_default_layout_from_config()
        count_exist_thumbnails = self.show_exist_thumbnails()
        print(f"[PROFILE] pipeline_manager: show_exist_thumbnails={count_exist_thumbnails} in {(time.perf_counter() - _t0)*1000:.1f}ms (study={self.study_uid})")
        print(f"🔍 [PIPELINE] count_exist_thumbnails = {count_exist_thumbnails}")

        try:
            # Check if we have a running event loop
            loop = asyncio.get_running_loop()
            has_running_loop = loop and loop.is_running()
            print(f"🔍 [PIPELINE] has_running_loop = {has_running_loop}")
            # Store the event loop reference for cleanup
            self._event_loop = loop
        except RuntimeError:
            has_running_loop = False
            print("⚠️ No running event loop detected")

        # ✅ CRITICAL: CREATE VIEWERS FIRST (before loading any series)
        # This ensures the UI is ready with loading indicators
        print(f"🔨 [PIPELINE] Creating viewers upfront with layout {size_init_viewers}...")
        try:
            self.apply_multi_viewer(size_init_viewers, modify_by_user=False)
            self._show_viewer_loading_all()
            print(f"✅ [PIPELINE] Viewers created successfully")
            print(f"[PROFILE] pipeline_manager: viewers created in {(time.perf_counter() - _t0)*1000:.1f}ms (study={self.study_uid})")
        except Exception as e:
            print(f"❌ [PIPELINE] Error creating viewers: {e}")
            import traceback
            traceback.print_exc()

        if not has_running_loop:
            print("⚠️ Pipeline manager called without running event loop - using fallback")
            # Fallback: schedule thumbnails to load but don't create tasks
            if count_exist_thumbnails > 0:
                print(f"✅ Found {count_exist_thumbnails} existing thumbnails")
                # Try to load first series synchronously
                try:
                    self._load_first_series_sync(size_init_viewers)
                except Exception as e:
                    print(f"⚠️ Could not load first series: {e}")
            return

        if getattr(self, '_progressive_display_enabled', False):
            print(f"🔍 [PIPELINE] Progressive mode — layout ready, first series via signal")
            # Layout is ready.  First series display will be triggered by:
            # - series_downloaded signal  (for active downloads)
            # - _check_and_load_local_first_series  (for already-downloaded data,
            #   scheduled in _run_pipeline_safely after a short defer)
            return
        elif count_exist_thumbnails > 0:
            print(f"🔍 [PIPELINE] Layout ready with {count_exist_thumbnails} thumbnails — first series via signal")
            # Defer first series display to signal-driven path
            return

        # if getattr(self, "selected_widget", None) and getattr(self.selected_widget, "viewport_spinner", None):
        #     self.selected_widget.viewport_spinner.show_loading("Loading...")  # Commented out to avoid showing loading message to user

        if caller == CallerTypes.IMPORT:
            task = asyncio.create_task(
                self.pipeline_manager_import(thumb_index=count_exist_thumbnails, size_init_viewers=size_init_viewers))
            self._background_tasks.add(task)
            def cleanup_task(t):
                try:
                    self._background_tasks.discard(t)
                except:
                    pass  # Ignore errors during cleanup
            task.add_done_callback(lambda t: QTimer.singleShot(0, lambda: cleanup_task(t)))
        elif caller == CallerTypes.SERVER:
            task = asyncio.create_task(
                self.pipeline_manager_server(thumb_index=count_exist_thumbnails, size_init_viewers=size_init_viewers))
            self._background_tasks.add(task)
            def cleanup_task(t):
                try:
                    self._background_tasks.discard(t)
                except:
                    pass  # Ignore errors during cleanup
            task.add_done_callback(lambda t: QTimer.singleShot(0, lambda: cleanup_task(t)))

    def _load_first_series_sync(self, size_init_viewers=(1, 1)):
        """
        Synchronously load the first available series
        بارگذاری همزمان اولین سری موجود

        This is a fallback for when there's no running event loop.
        """
        # Delegate to viewer controller
        self.viewer_controller._load_first_series_sync(size_init_viewers)

    def _load_first_series_sync(self, size_init_viewers):
        """Load first series synchronously when no event loop is available"""
        try:
            from PacsClient.pacs.patient_tab.utils import load_images
            
            print("📂 [SYNC_LOAD] Loading first series synchronously...") # لاگ اضافه شده
            
            first_series_loaded = False
            for vtk_image_data, metadata, patient_info in load_images(
                    self.import_folder_path,
                    patient_pk=self.metadata_fixed.get('patient_pk', None),
                    study_pk=self.metadata_fixed.get('study_pk', None),
                    ordering_by_instances_number=self.ordering_by_instances_number
            ):
                # ✅ FLICKER FIX: Only process events if not in initialization batch
                if self.updatesEnabled():
                    QApplication.processEvents()
                
                self.check_and_add_meta_fixed(patient_info)
                
                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                
                self.add_new_data_to_lst_thumbnails_data(new_data)
                
                if not first_series_loaded:
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    print(f"✅ [SYNC_LOAD] Determined optimal layout: {optimal_layout}") # لاگ اضافه شده
                    
                    # ✅ FLICKER FIX: Only process events if not in initialization batch
                    if self.updatesEnabled():
                        QApplication.processEvents()
                    # Use synchronous viewer creation
                    self._apply_multi_viewer_sync(optimal_layout) # این تابع ویوورها را تنظیم می کند
                    if self.updatesEnabled():
                        QApplication.processEvents()
                    
                    first_series_loaded = True
                    self._hide_loading_spinner()
                    
                    series_no = metadata['series']['series_number']
                    if (not self._first_series_displayed) or self._any_viewer_empty():
                        self._display_first_series_in_all_viewers(str(series_no))
                    self.thumbnail_manager.set_series_ready(str(series_no))
                    
                    if file_path and not self.logo_patient:
                        self.logo_patient = file_path
                        self.update_tab_manager()
                    
                    print(f"✅ [SYNC_LOAD] First series loaded: {series_no}. Breaking loop.") # لاگ اضافه شده
                    break  # فقط اولین سری را بارگذاری کن
                    
        except Exception as e:
            print(f"❌ [SYNC_LOAD] Error loading first series sync: {e}") # لاگ اضافه شده
            import traceback
            traceback.print_exc()

    def _apply_multi_viewer_sync(self, numbers):
        """Delegate to viewer controller"""
        self.viewer_controller._apply_multi_viewer_sync(numbers)

    async def lazy_load_first_series_progressive(self, size_init_viewers):
        """Wait for first series to download, then load it - OR load immediately if already exists"""
        print(f"🔍 [PROGRESSIVE] Starting lazy_load_first_series_progressive")

        try:
            # Yield control immediately to allow other tasks to start
            await asyncio.sleep(0)

            # Check if widget is still valid (allow hidden tabs to load)
            try:
                _ = self.isVisible()
            except RuntimeError:
                return  # Widget was deleted

            # Perform the lazy load directly without locks to avoid deadlocks
            await self._do_lazy_load_first_series(size_init_viewers)

        except asyncio.CancelledError:
            print(f"⚠️ [PROGRESSIVE] Task cancelled")
            raise
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error in lazy load: {e}")
        except Exception as e:
            self.logger.error(f"Error in lazy_load_first_series_progressive: {e}", exc_info=True)

    async def _locked_lazy_load(self, size_init_viewers):
        """Run the first-series lazy load without locks to avoid deadlocks."""
        # Check widget validity before doing heavy work
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return  # Widget was deleted

            await self._do_lazy_load_first_series(size_init_viewers)

    async def _do_lazy_load_first_series(self, size_init_viewers):
        from pathlib import Path
        study_path = Path(self.import_folder_path)

        # Check if widget is still valid (allow hidden tabs to load)
        try:
            _ = self.isVisible()
        except RuntimeError:
            return  # Widget was deleted

        # Check if widget is still valid (allow hidden tabs to load)
        try:
            _ = self.isVisible()
        except RuntimeError:
            return  # Widget was deleted

        # Determine series source: existing or download
        first_series_folder = None
        first_series_number = None
        local_series = self._discover_local_series_candidates()
        if local_series:
            first_series_number = str(local_series[0]["series_number"])
            first_series_folder = Path(local_series[0]["path"])
        else:
            # Async wait for download with timeout
            first_series_number = await self._wait_for_series_download(timeout=60)
            if first_series_number:
                first_series_folder = study_path / str(first_series_number)

        if not (first_series_folder and first_series_folder.exists()):
            return

        # Check if widget is still valid (allow hidden tabs to load)
        try:
            _ = self.isVisible()
        except RuntimeError:
            return  # Widget was deleted

        try:
            if first_series_number is None:
                return
            series_num = str(first_series_number)

            result = load_single_series_by_number(
                study_path=self.import_folder_path,
                series_number=series_num,
                patient_pk=self.metadata_fixed.get('patient_pk'),
                study_pk=self.metadata_fixed.get('study_pk'),
                ordering_by_instances_number=self.ordering_by_instances_number,
            )
            if not result:
                return

            result_list = list(result)
            if not result_list:
                return

            last_item = result_list[-1]
            vtk_image_data, metadata, (patient_pk, study_pk) = last_item

            self.check_and_add_meta_fixed((patient_pk, study_pk))
            optimal_layout = self.get_optimal_layout_for_series(metadata)

            if not self.lst_nodes_viewer:
                await self.create_progressive_viewers(optimal_layout)

            thumbnail_path = metadata['series'].get('thumbnail_path', '')
            self.add_new_data_to_lst_thumbnails_data({
                'vtk_image_data': vtk_image_data,
                'metadata': metadata,
                'file_path': thumbnail_path
            })

            if thumbnail_path and not self.logo_patient:
                self.logo_patient = thumbnail_path
                self.update_tab_manager()

            self._distribute_series_to_viewers()

            if (not self._first_series_displayed) or self._any_viewer_empty():
                self._display_first_series_in_all_viewers(str(series_num))

        except Exception as e:
            self._handle_loading_error(e, first_series_folder.name)

    def load_series_immediately(self, series_number: str, series_dir: str):
        """
        Load a series immediately after download and display it automatically.

        Args:
            series_number: Can be either a simple series number (e.g., "1", "2")
                          or a Series Instance UID (e.g., "1.3.12.2.1107...")
            series_dir: Directory containing the series DICOM files
        """
        # Delegate to viewer controller
        self.viewer_controller.load_series_immediately(series_number, series_dir)

    def _trigger_priority_display(self, series_key):
        """Delegate to viewer controller"""
        self.viewer_controller._trigger_priority_display(series_key)

    def show_priority_status(self, message):
        """Show special status for priority download"""
        # Implement status display
        pass

    def hide_priority_status(self):
        """Hide priority status"""
        # Implement status hide
        pass

    async def _wait_for_series_download(self, timeout: float) -> int | None:
        """Wait for first series download signal with timeout"""
        series_number = None
        download_event = asyncio.Event()

        def handle_download(series_str: str):
            nonlocal series_number
            with contextlib.suppress(ValueError):
                series_number = int(series_str)
            if not download_event.is_set():
                download_event.set()

        try:
            self.series_downloaded.connect(handle_download, Qt.QueuedConnection)
            await asyncio.wait_for(download_event.wait(), timeout=timeout)
            return series_number
        except asyncio.TimeoutError:
            return None
        finally:
            # ✅ FIX: Also suppress RuntimeError when signal source is deleted
            with contextlib.suppress(TypeError, RuntimeError):
                self.series_downloaded.disconnect(handle_download)

    def _handle_loading_error(self, error: Exception, series_name: str):
        """Centralized error handling for series loading"""
        import traceback
        traceback.print_exc()
        
        # Fallback UI cleanup
        if self.lst_nodes_viewer and hasattr(self.lst_nodes_viewer[0], 'vtk_widget'):
            spinner = getattr(self.lst_nodes_viewer[0].vtk_widget, 'viewport_spinner', None)
            if spinner:
                spinner.hide_loading()
        self._hide_init_overlay()
        try:
            self.loading_complete.emit()
        except Exception:
            pass

    def _distribute_series_to_viewers(self):
        # Check if lst_thumbnails_data exists and initialize if not
        if not hasattr(self, 'lst_thumbnails_data'):
            self.lst_thumbnails_data = []

        self.logger.info(f"Distributing {len(self.lst_thumbnails_data)} series to {len(self.lst_nodes_viewer)} viewers")
        """
        Distribute available series to all viewers for non-MG modalities
        This ensures all viewers get populated with images
        """
        try:
            print(f"🔀 [DISTRIBUTE] Distributing series to {len(self.lst_nodes_viewer)} viewers")

            if not self.lst_nodes_viewer:
                print("⚠️ [DISTRIBUTE] No viewers available")
                return

            if not self.lst_thumbnails_data:
                print("⚠️ [DISTRIBUTE] No thumbnail data available")
                return
                
            # For each viewer, assign a series if available
            for viewer_idx, node_viewer in enumerate(self.lst_nodes_viewer):
                # Skip if viewer is already populated
                if (hasattr(node_viewer.vtk_widget, 'last_series_show') and 
                    node_viewer.vtk_widget.last_series_show is not None):
                    print(f"   ⏭️ Viewer {viewer_idx} already has series {node_viewer.vtk_widget.last_series_show}")
                    continue
                    
                # Find a series to assign to this viewer
                series_to_assign = None
                series_index = None
                
                # Try to find a series that hasn't been displayed yet
                for i, thumb_data in enumerate(self.lst_thumbnails_data):
                    series_num = thumb_data['metadata']['series']['series_number']
                    series_displayed = False
                    
                    # Check if this series is already displayed in any viewer
                    for other_viewer in self.lst_nodes_viewer:
                        if (hasattr(other_viewer.vtk_widget, 'last_series_show') and
                            other_viewer.vtk_widget.last_series_show == series_num):
                            series_displayed = True
                            break
                            
                    if not series_displayed:
                        series_to_assign = thumb_data
                        series_index = i
                        break
                        
                if series_to_assign is None and self.lst_thumbnails_data:
                    # All series are displayed, use the first one for this viewer
                    series_to_assign = self.lst_thumbnails_data[0]
                    series_index = 0
                    
                if series_to_assign:
                    print(f"   🎯 Assigning series {series_to_assign['metadata']['series']['series_number']} to viewer {viewer_idx}")
                    
                    # Display the series in this viewer
                    flag_switch = node_viewer.switch_series(
                        series_to_assign['vtk_image_data'],
                        series_to_assign['metadata'],
                        series_index,
                        metadata_fixed=self.metadata_fixed
                    )
                    
                    # ✅ اطمینان از اینکه selected_widget برای Eagle Eye تنظیم شده
                    if viewer_idx == 0:  # First viewer becomes main
                        self.set_viewer_to_main_viewer(node_viewer)
                    
                    # Reset slider after switching series
                    if flag_switch and hasattr(node_viewer, 'vtk_widget') and hasattr(node_viewer, 'slider'):
                        self.reset_slider(node_viewer.vtk_widget, node_viewer.slider)
                        
                    # Update corners if image_viewer exists
                    if node_viewer.vtk_widget.image_viewer is not None:
                        node_viewer.vtk_widget.image_viewer.update_corners_actors()
                        
                    # Hide loading spinner
                    if hasattr(node_viewer.vtk_widget, 'viewport_spinner'):
                        node_viewer.vtk_widget.viewport_spinner.hide_loading()
                        
                    # Update UI
                    node_viewer.vtk_widget.show()
                    node_viewer.vtk_widget.update()
                    node_viewer.widget.show()
                    node_viewer.widget.update()
                    
                    if node_viewer.vtk_widget.image_viewer:
                        node_viewer.vtk_widget.image_viewer.Render()
                        node_viewer.vtk_widget.render_window.Render()
                        node_viewer.vtk_widget.GetRenderWindow().Render()
                        
                    print(f"   ✅ Viewer {viewer_idx} populated successfully")
                    
        except Exception as e:
            print(f"❌ [DISTRIBUTE] Error distributing series to viewers: {e}")
            import traceback
            traceback.print_exc()

    def _distribute_series_to_viewers(self):
        """Delegate to viewer controller"""
        self.viewer_controller._distribute_series_to_viewers()

    async def create_progressive_viewers(self, layout):
        """Create viewers for progressive display mode"""
        try:
            self.logger.info(f"Creating {layout[0]}x{layout[1]} viewer layout")

            # Check if widget is still valid (allow hidden tabs to load)
            try:
                _ = self.isVisible()
            except RuntimeError:
                return  # Widget was deleted

            # Route first progressive layouts through the same canonical viewer
            # controller path used by later user layout changes. This keeps the
            # initial layout's drag-drop/switch wiring identical across all
            # layouts, including 2x1.
            self.viewer_controller.apply_multi_viewer(layout, modify_by_user=False)

            # Give UI a chance to update
            await asyncio.sleep(0)

            # Check if widget is still valid after update
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            self.logger.info(f"Successfully created {layout[0]}x{layout[1]} viewer layout")

        except asyncio.CancelledError:
            self.logger.debug("Viewer creation cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error creating viewers: {e}", exc_info=True)

    async def lazy_load_first_series(self, size_init_viewers):
        """Load first series and create appropriate viewers for ANY modality"""
        print(f"🔍 [LAZY_LOAD] Starting lazy_load_first_series with layout {size_init_viewers}")
        try:
            from PacsClient.pacs.patient_tab.utils import load_images

            first_series_loaded = False
            first_modality = None

            for vtk_image_data, metadata, patient_info in load_images(
                    self.import_folder_path,
                    patient_pk=self.metadata_fixed.get('patient_pk', None),
                    study_pk=self.metadata_fixed.get('study_pk', None),
                    ordering_by_instances_number=self.ordering_by_instances_number
            ):
                # Check if widget is still valid before continuing
                try:
                    _ = self.isVisible()
                except RuntimeError:
                    return  # Widget was deleted
                
                # ✅ FLICKER FIX: Only process events if not in initialization batch
                if self.updatesEnabled():
                    QApplication.processEvents()

                self.check_and_add_meta_fixed(patient_info)

                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                self.add_new_data_to_lst_thumbnails_data(new_data)

                if not first_series_loaded:
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    first_modality = metadata.get('series', {}).get('modality', 'N/A')

                    # ✅ FLICKER FIX: Only process events if not in initialization batch
                    if self.updatesEnabled():
                        QApplication.processEvents()

                    # ✅ ساخت viewer مناسب برای هر مودالیتی
                    if not self.lst_nodes_viewer:
                        self.init_matrix_viewers(optimal_layout)
                    if self.updatesEnabled():
                        QApplication.processEvents()


                    self._distribute_series_to_viewers()

                    first_series_loaded = True
                    self._hide_loading_spinner()

                    series_no = metadata['series']['series_number']
                    if (not self._first_series_displayed) or self._any_viewer_empty():
                        self._display_first_series_in_all_viewers(str(series_no))
                    self.thumbnail_manager.set_series_ready(str(series_no))

                    if file_path and not self.logo_patient:
                        self.logo_patient = file_path
                        self.update_tab_manager()

                    print(f"✅ [LAZY_LOAD] First series loaded: {series_no}")
                    break  # فقط اولین سری را بارگذاری کن

        except Exception as e:
            print(f"❌ [LAZY_LOAD] Error: {e}")
            import traceback
            traceback.print_exc()

    async def pipeline_manager_server(self, thumb_index, size_init_viewers):
        # TIMING: Start timing the pipeline
        import time
        _pipeline_start = time.time()

        running_pipeline_server = True
        # check_exist_study = True
        pull_request = 0.1
        load_viewer = True
        lst_series_downloaded = []
        _series_count = 0

        while running_pipeline_server:
            _iter_start = time.time()

            results, lst_series_downloaded, finish_downloading = await asyncio.to_thread(
                lambda: list(load_images_from_server(
                    folder_path=self.import_folder_path,
                    patient_pk=self.metadata_fixed.get('patient_pk', None),
                    study_pk=self.metadata_fixed.get('study_pk', None),
                    study_uid=self.study_uid,
                    number_of_instances_on_db=self.metadata_fixed.get('number_of_instances', None),
                    lst_series_downloaded=lst_series_downloaded,
                    ordering_by_instances_number=self.ordering_by_instances_number
                )))

            _load_time = time.time() - _iter_start

            # print('result:', results, '\n')
            # print('finish_downloading:', finish_downloading)

            for vtk_image_data, metadata, patient_info in results:  # for each series created. from folder read.
                _series_start = time.time()
                _series_count += 1

                self.check_and_add_meta_fixed(patient_info)

                file_path = save_image_as_png(
                    vtk_image_data=vtk_image_data, metadata=metadata,
                    metadata_fixed=self.metadata_fixed,
                    file=metadata['series']['series_path']
                )

                _thumbnail_time = time.time() - _series_start

                self.check_logo_patient(file_path)

                thumb_index = self.add_thumbnail_to_thumbnail_layout(
                    thumb_index=thumb_index, file_path_thumbnail=file_path,
                    key_thumbnail=metadata['series']['series_number'], metadata=metadata)

                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                self.add_new_data_to_lst_thumbnails_data(new_data)

                if load_viewer:
                    _viewer_start = time.time()
                    # تعیین layout بهینه بر اساس modality
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    print(
                        f"[LAYOUT] Detected modality: {metadata.get('series', {}).get('modality', 'N/A')}, using layout: {optimal_layout}")
                    if not self.lst_nodes_viewer:
                        self.init_matrix_viewers(optimal_layout)
                    load_viewer = False
                    _viewer_time = time.time() - _viewer_start
                    self._hide_loading_spinner()
                    if (not self._first_series_displayed) or self._any_viewer_empty():
                        self._display_first_series_in_all_viewers(str(metadata['series']['series_number']))

                if self.selected_widget:
                    same = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                    if (not same) and (
                            metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series'][
                        'series_number']):
                        optimal_layout = self.get_optimal_layout_for_series(metadata)
                        print(f"[LAYOUT] Re-initializing with optimal layout: {optimal_layout}")
                        self.init_matrix_viewers(optimal_layout)

                _total_series_time = time.time() - _series_start

                await asyncio.sleep(0)  # فرصت به UI
                # print('metadata:', metadata)

            if finish_downloading:
                # running_pipeline_server = False
                # print('EXITTTTTTTTTTTTTTT')
                self._hide_loading_spinner()

                _total_time = time.time() - _pipeline_start
                print(f"\n{'=' * 60}")
                print(
                    f"[TIMING] Average per series: {_total_time / _series_count:.3f}s" if _series_count > 0 else "N/A")
                print(f"{'=' * 60}\n")
                return

            print('waiting...')
            # Check if widget is still valid before continuing
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted
            await asyncio.sleep(pull_request)

    async def pipeline_manager_import(self, thumb_index, size_init_viewers):
        """
            Manage pipeline base on caller
            caller: server, import, local(db)
        """
        # TIMING: Start timing the pipeline
        import time
        _pipeline_start = time.time()

        loop = asyncio.get_running_loop()
        # Store the event loop reference for cleanup
        self._event_loop = loop
        q = asyncio.Queue(maxsize=4)  # backpressure تا UI نفس بکشد
        _series_count = 0

        def producer():
            try:
                for item in load_images(
                        self.import_folder_path,
                        patient_pk=self.metadata_fixed.get('patient_pk', None),
                        study_pk=self.metadata_fixed.get('study_pk', None),
                        ordering_by_instances_number=self.ordering_by_instances_number
                ):
                    # انتقال ایمن به حلقۀ asyncio
                    asyncio.run_coroutine_threadsafe(q.put(item), loop)
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("__ERROR__", e))
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=producer, daemon=True).start()

        load_viewer = True
        while True:
            item = await q.get()
            if item is None:  # تمام شد
                break
            if isinstance(item, tuple) and item and item[0] == "__ERROR__":
                print("load_images error:", item[1])
                continue

            _series_start = time.time()
            _series_count += 1

            vtk_image_data, metadata, patient_info = item
            self.check_and_add_meta_fixed(patient_info)

            # ذخیره‌ی PNG در نخ (I/O دیسک سنگین است)
            _thumb_start = time.time()
            file_path = await asyncio.to_thread(
                save_image_as_png,
                vtk_image_data, metadata, self.metadata_fixed,
                metadata['series']['series_path']
            )
            _thumb_time = time.time() - _thumb_start

            self.check_logo_patient(file_path)

            thumb_index = self.add_thumbnail_to_thumbnail_layout(
                thumb_index=thumb_index, file_path_thumbnail=file_path,
                key_thumbnail=metadata['series']['series_number'],
                metadata=metadata)
            # print('metadata:', metadata)

            new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
            self.add_new_data_to_lst_thumbnails_data(new_data)

            if load_viewer:
                _viewer_start = time.time()
                # تعیین layout بهینه بر اساس modality
                optimal_layout = self.get_optimal_layout_for_series(metadata)
                modality = metadata.get('series', {}).get('modality', 'N/A')
                print(f"[LAYOUT] Detected modality: {modality}, using layout: {optimal_layout}")
                if not self.lst_nodes_viewer:
                    self.init_matrix_viewers(optimal_layout)
                load_viewer = False
                _viewer_time = time.time() - _viewer_start
                self._hide_loading_spinner()
                if (not self._first_series_displayed) or self._any_viewer_empty():
                    self._display_first_series_in_all_viewers(str(metadata['series']['series_number']))


            if self.selected_widget:
                same = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                if (not same) and (
                        metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series'][
                    'series_number']):
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    print(f"[LAYOUT] Re-initializing with optimal layout: {optimal_layout}")
                    self.init_matrix_viewers(optimal_layout)

            _total_series_time = time.time() - _series_start

            # Check if widget is still valid before continuing
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted
            await asyncio.sleep(0)  # فرصت به UI

        self._hide_loading_spinner()

        _total_time = time.time() - _pipeline_start
        print(f"\n{'=' * 60}")
        print(f"{'=' * 60}\n")

    async def pipeline_manager_import_full_series(self, thumb_index, size_init_viewers):
        """
            Manage pipeline base on caller
            caller: server, import, local(db)
        """
        # TIMING: Start timing the pipeline
        import time
        _pipeline_start = time.time()

        loop = asyncio.get_running_loop()
        # Store the event loop reference for cleanup
        self._event_loop = loop
        q = asyncio.Queue(maxsize=4)  # backpressure تا UI نفس بکشد
        _series_count = 0

        def producer():
            try:
                for item in load_images(
                        self.import_folder_path,
                        patient_pk=self.metadata_fixed.get('patient_pk', None),
                        study_pk=self.metadata_fixed.get('study_pk', None),
                        ordering_by_instances_number=self.ordering_by_instances_number
                ):
                    # انتقال ایمن به حلقۀ asyncio
                    asyncio.run_coroutine_threadsafe(q.put(item), loop)
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("__ERROR__", e))
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=producer, daemon=True).start()

        load_viewer = True
        while True:
            item = await q.get()
            if item is None:  # تمام شد
                break
            if isinstance(item, tuple) and item and item[0] == "__ERROR__":
                print("load_images error:", item[1])
                continue

            _series_start = time.time()
            _series_count += 1

            vtk_image_data, metadata, patient_info = item
            self.check_and_add_meta_fixed(patient_info)

            # ذخیره‌ی PNG در نخ (I/O دیسک سنگین است)
            _thumb_start = time.time()
            file_path = await asyncio.to_thread(
                save_image_as_png,
                vtk_image_data, metadata, self.metadata_fixed,
                metadata['series']['series_path']
            )
            _thumb_time = time.time() - _thumb_start

            self.check_logo_patient(file_path)

            thumb_index = self.add_thumbnail_to_thumbnail_layout(
                thumb_index=thumb_index, file_path_thumbnail=file_path,
                key_thumbnail=metadata['series']['series_number'],
                metadata=metadata)
            # print('metadata:', metadata)

            new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
            self.add_new_data_to_lst_thumbnails_data(new_data)

            if load_viewer:
                _viewer_start = time.time()
                self.init_matrix_viewers(size_init_viewers)
                load_viewer = False
                _viewer_time = time.time() - _viewer_start
                self._hide_loading_spinner()

            if self.selected_widget:
                same = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                if (not same) and (
                        metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series'][
                    'series_number']):
                    self.init_matrix_viewers(size_init_viewers)

            _total_series_time = time.time() - _series_start

            # Check if widget is still valid before continuing
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted
            await asyncio.sleep(0)

        self._hide_loading_spinner()

        _total_time = time.time() - _pipeline_start
        print(f"\n{'=' * 60}")
        print(f"{'=' * 60}\n")

    def _load_first_series_sync_fallback(self, size_init_viewers):
        """Synchronous fallback for when async is not available"""
        try:
            from pathlib import Path
            study_path = Path(self.import_folder_path)
            
            # Find first existing series
            existing_series = sorted(
                int(d.name) for d in study_path.iterdir()
                if d.is_dir() and d.name.isdigit() and (
                    next(d.glob("*.dcm"), None) or next(d.glob("*.DCM"), None)
                )
            )
            
            if existing_series:
                series_number = existing_series[0]
                print(f"📥 [SYNC_FALLBACK] Loading series {series_number}...")
                success = self._load_single_series_on_demand(series_number)
                
                if success:
                    print(f"✅ [SYNC_FALLBACK] Series {series_number} loaded")
                    # Create viewers
                    self.init_matrix_viewers(size_init_viewers)
                    # Display first series if available
                    if self.lst_thumbnails_data:
                        self._distribute_series_to_viewers()
            else:
                print("⚠️ [SYNC_FALLBACK] No series found")
                
        except Exception as e:
            print(f"❌ [SYNC_FALLBACK] Error: {e}")
            import traceback
            traceback.print_exc()

    async def enable_progressive_display(self):
        """
        Enable progressive display mode - show series as they are downloaded
        فعال‌سازی حالت نمایش تدریجی - نمایش سری‌ها به محض دانلود
        """
        try:
            # Yield immediately to prevent blocking
            await asyncio.sleep(0)

            self._progressive_display_enabled = True

            # Set up folder path if not set
            # تنظیم مسیر پوشه اگر تنظیم نشده است
            if not self.import_folder_path or self.import_folder_path is None:
                from PacsClient.pacs.patient_tab.utils import get_study_source_path
                self.import_folder_path, _ = get_study_source_path(self.study_uid)

            # ✅ FIX: Don't call show_exist_thumbnails here - already called in pipeline_manager
            # ✅ FIX: Don't cleanup viewers here - already done in pipeline_manager
            # ✅ FIX: Don't create viewers here - already created in pipeline_manager
            # Just get the count for size calculation
            thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid)
            count_exist_thumbnails = len(thumbnails) if thumbnails else 0
            print(f"📊 [enable_progressive_display] Found {count_exist_thumbnails} thumbnails (already shown)")

            # Verify we have viewers (should already exist from pipeline_manager)
            default_layout = self._get_default_layout_from_config()
            if not self.lst_nodes_viewer:
                print("⚠️ No viewers found, creating them...")
                self.init_matrix_viewers(default_layout)
                self._show_viewer_loading_all()
            else:
                print(f"✅ Using existing {len(self.lst_nodes_viewer)} viewers")

            if self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                first_viewer = self.lst_nodes_viewer[0]
                if not self.selected_widget and hasattr(first_viewer, 'vtk_widget'):
                    self.selected_widget = first_viewer.vtk_widget
                    self.slider = first_viewer.slider

                # Load first series (either from disk or wait for download)
                if count_exist_thumbnails > 0:
                    try:
                        # Use await instead of creating a separate task
                        await self.lazy_load_first_series_progressive(size_init_viewers=default_layout)
                    except asyncio.CancelledError:
                        self.logger.debug("Progressive load cancelled")
                    except Exception as e:
                        self.logger.error(f"Error in progressive load: {e}", exc_info=True)

        except asyncio.CancelledError:
            self.logger.debug("Enable progressive display cancelled")
            raise
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error in enable_progressive_display: {e}")
        except Exception as e:
            self.logger.error(f"Error enabling progressive display: {e}", exc_info=True)

    def refresh_after_download(self, study_uid_downloaded: str = None):
        """Refresh UI after download completion"""
        try:
            if study_uid_downloaded and self.study_uid != study_uid_downloaded:
                return
            if not getattr(self, '_progressive_display_enabled', False):
                return

            # Reset thumbnails flag to allow refresh
            self._thumbnails_shown = False

            # Refresh thumbnails
            self.show_exist_thumbnails()
        except Exception:
            pass
        finally:
            if getattr(self, '_suppress_thumb_scroll_reset', False):
                self._suppress_thumb_scroll_reset = False

    def load_first_series_only(self, folder_path, series_number):
        """
        Load only the first series when it's downloaded
        بارگذاری فقط اولین سری وقتی دانلود شد

        This method is called by home_ui when the first series download completes.

        Args:
            folder_path: Path to the study folder
            series_number: The series number that was downloaded
        """
        # Delegate to viewer controller
        self.viewer_controller.load_first_series_only(folder_path, series_number)

