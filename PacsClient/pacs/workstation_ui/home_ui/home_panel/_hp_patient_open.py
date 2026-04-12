"""Patient double-click: tab open, loading states, close/cleanup"""
# Auto-generated from home_ui.py — Phase 3 split



import asyncio
import logging
import time as _time
import threading
import traceback

_logger = logging.getLogger(__name__)

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

from ..home_widget_utils import is_widget_alive
from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, save_image_as_png
from PacsClient.utils import get_connection_database, get_all_patients, search_patients_local, find_patient_pk, find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.db_manager import get_study_by_study_uid
from modules.network.upload_download_attchments import download_attachments_for_study, download_attachments_for_study_async
from modules.offline_cloud_server.service import export_studies_to_offline_cloud, get_all_offline_cloud_servers, list_offline_cloud_studies, record_offline_cloud_sync_event, sync_offline_cloud_study_preview_to_local, sync_offline_cloud_study_to_local, validate_offline_cloud_package

from .widget import SourceOfPatientLoad

class _HPPatientOpenMixin:
    """Patient double-click: tab open, loading states, close/cleanup"""

    def open_patient_widget(self, patient_id, patient_name, study_uid):
        if self.loading_message:
            self.loading_message.hide()  # Hide loading message
        # Logic to open the patient widget goes here
        patient_widget = _ensure_patient_widget()(patient_id, patient_name, study_uid)
        patient_widget.show()  # Show the patient widget

    def _on_patient_double_clicked(self, patient_id, patient_name, study_uid, report_status='pending'):
        # run the async flow without blocking UI
        import asyncio
        action_id = self._trace_action_start(
            "double_click",
            context={
                'patient_id': str(patient_id),
                'patient_name': str(patient_name),
                'study_uid': str(study_uid),
            }
        )
        asyncio.create_task(
            self._on_patient_double_clicked_async(
                patient_id,
                patient_name,
                study_uid,
                report_status,
                action_id=action_id,
            )
        )

    async def _on_patient_double_clicked_async(self, patient_id, patient_name, study_uid, report_status='pending', action_id=None):
        """
        FAST patient opening - tab opens immediately, background loading for everything else
        """
        from pathlib import Path
        from PySide6.QtCore import Qt
        from PacsClient.pacs.patient_tab.utils.utils import check_study_complete

        _t0_double_click = _time.perf_counter()
        _logger.info("[FAST-UX] double_click_t0 study=%s patient=%s", study_uid, patient_id)

        try:
            # Prevent duplicate open requests for the same study (double-trigger / re-entrancy)
            if study_uid in self._opening_studies:
                print(f"⚠️ Duplicate open prevented for study {study_uid}")
                return

            # If already open, just focus it and exit
            existing_widget = self._find_widget_by_study_uid(study_uid)
            if existing_widget:
                try:
                    if not is_widget_alive(existing_widget):
                        print(f"⚠️ Existing widget for study {study_uid} has been deleted, creating new one")
                        self.dict_tabs_widget.pop(study_uid, None)
                    else:
                        idx = self.tab_widget.indexOf(existing_widget)
                        if idx != -1:
                            if self.custom_tab_manager:
                                self.custom_tab_manager.set_tab_active(idx)
                            else:
                                self.tab_widget.setCurrentIndex(idx)

                            self._trace_action_done(
                                action_id,
                                phase='already_open_tab',
                                extra={'study_uid': str(study_uid)}
                            )

                            self.hide_loading()
                            self._double_click_first_series_loaded = True
                            self._maybe_hide_double_click_loading()
                            self.patient_table_widget.update_visited_status(study_uid, status='opened')
                            return
                except Exception as e:
                    print(f"⚠️ Error switching to existing tab: {e}")
                    # Continue with normal flow if tab switching fails

            self._opening_studies.add(study_uid)

            # Track loading state: keep until first series is displayed
            self._double_click_loading_active = True
            self._double_click_first_series_loaded = False

            # --- STEP 1: Mark as opened immediately (UI feedback) ---
            self.patient_table_widget.update_visited_status(study_uid, status='opened')
            
            # --- STEP 2: Quick check - is study already downloaded? ---
            selected_server = self.data_access_panel_widget.get_server_selected() or {}
            is_offline_cloud = selected_server.get("server_type") == "offline_cloud"
            study_data = get_study_by_study_uid(study_uid=study_uid)
            output_dir = None
            is_local = self.source_of_patient_load in (SourceOfPatientLoad.DB, SourceOfPatientLoad.OFFLINE_CLOUD)

            if study_data:
                output_dir = study_data.get('study_path')

            if not output_dir:
                # Create output directory path
                output_dir = str(SOURCE_PATH / study_uid)

            if is_offline_cloud:
                sync_result = await asyncio.to_thread(
                    sync_offline_cloud_study_to_local,
                    selected_server,
                    study_uid,
                )
                if not sync_result.get("ok"):
                    QMessageBox.warning(
                        self,
                        "Offline Cloud",
                        sync_result.get("error") or "Could not sync the selected study from the offline cloud package.",
                    )
                    self._double_click_first_series_loaded = True
                    self._maybe_hide_double_click_loading()
                    return
                output_dir = sync_result.get("study_path") or output_dir

            # --- STEP 3: Open tab immediately (UI first) ---
            caller = CallerTypes.IMPORT if is_local else CallerTypes.SERVER

            widget = self.add_new_tab_widget(
                patient_id=patient_id,
                patient_name=patient_name,
                folder_path=output_dir,
                caller=caller,
                study_uid=study_uid,
                enable_progressive_mode=True,
                report_status=report_status
            )

            if not widget:
                self._trace_action_done(action_id, phase='open_widget_failed', extra={'study_uid': str(study_uid)})
                self._double_click_first_series_loaded = True
                self._maybe_hide_double_click_loading()
                return

            if is_offline_cloud:
                widget.offline_cloud_server = dict(selected_server)

            self._attach_action_to_widget(widget, action_id)
            
            # Activate tab immediately; loading indicators live inside the viewer
            if self.custom_tab_manager:
                try:
                    tab_index = self.custom_tab_manager.find_tab_by_study_uid(study_uid)
                    if tab_index is not None and tab_index != -1:
                        self.custom_tab_manager.set_tab_active(tab_index)
                        print(f"✅ [TAB] Activated tab at index {tab_index}")
                except Exception as e:
                    print(f"⚠️ [TAB] Error activating tab: {e}")
            else:
                try:
                    self.tab_widget.setCurrentWidget(widget)
                    print("✅ [TAB] Activated tab via setCurrentWidget")
                except Exception as e:
                    print(f"⚠️ [TAB] Error setting current widget: {e}")

            # [H7-P1] Pipeline A timeline: tab created
            _logger.info(
                "[H7-P1] study=%s tab_created=True is_local=%s t_since_open_ms=%.1f",
                study_uid, is_local, (_time.perf_counter() - _t0_double_click) * 1000.0,
            )

            # Ensure lifecycle hook runs for initial open even if currentChanged is not emitted.
            try:
                if hasattr(widget, 'on_tab_activated') and (not getattr(widget, '_is_active_patient_tab', False)):
                    widget.on_tab_activated()
                    print(f"✅ [TAB] Forced on_tab_activated for study {study_uid}")
            except Exception as e:
                print(f"⚠️ [TAB] Failed forced on_tab_activated: {e}")

            # Connect to first-series displayed signal (to hide loading)
            try:
                if hasattr(self, '_double_click_loading_widget') and self._double_click_loading_widget:
                    try:
                        self._double_click_loading_widget.loading_complete.disconnect(self._on_first_series_loaded)
                    except Exception:
                        pass
                self._double_click_loading_widget = widget
                if hasattr(widget, 'loading_complete'):
                    widget.loading_complete.connect(self._on_first_series_loaded)
            except Exception:
                pass

            # --- STEP 3.5: IMMEDIATE PRIORITY DOWNLOAD ---
            # When a patient is double-clicked:
            # 1. ALL active downloads are INSTANTLY paused
            # 2. This patient is added with CRITICAL priority
            # 3. Download starts IMMEDIATELY (no delay)
            # 4. Queue is reorganized in the background AFTER download starts
            #
            # Note: Enhanced R17 (duplicate check) now prevents re-download of completed studies
            # by checking both StateStore AND Database. If study is complete, R17 returns
            # allowed=False and the caller (Download Manager) handles loading from local files.
            if not is_local:
                try:
                    download_manager = self._get_or_create_download_manager_tab(activate_tab=False)
                    if download_manager:
                        # Get server info
                        server = self.data_access_panel_widget.get_server_selected()

                        # Create study info for Download Manager
                        # Try to get series info from server if not in study_data
                        series_list = []
                        series_count = 0
                        images_count = 0

                        if study_data and 'series' in study_data:
                            series_list = study_data.get('series', [])
                            series_count = len(series_list)
                            images_count = sum(s.get('image_count', 0) for s in series_list)
                        else:
                            # Fetch series info from server if not available
                            # v2.2.3.2.7: offload synchronous gRPC call to a background thread
                            # so the main thread event loop stays responsive (1-5s network latency).
                            try:
                                import asyncio as _aio
                                study_info = await _aio.to_thread(self._get_or_fetch_series_info, study_uid, patient_id)
                                if study_info:
                                    series_list = study_info.get('series', [])
                                    series_count = study_info.get('count_of_series', len(series_list))
                                    images_count = sum(s.get('image_count', 0) for s in series_list)
                            except Exception as e:
                                print(f"Warning: Could not fetch series info: {e}")

                        dm_study_data = {
                            'patient_id': patient_id,
                            'patient_name': patient_name,
                            'study_uid': study_uid,
                            'study_date': study_data.get('study_date', 'Unknown') if study_data else 'Unknown',
                            'modality': study_data.get('modality', 'Unknown') if study_data else 'Unknown',
                            'description': study_data.get('study_description', '') if study_data else '',
                            'series_count': series_count,
                            'images_count': images_count,
                            'series': series_list,  # Include series array for Download Manager UI
                            # Add complete patient information
                            'patient_age': study_data.get('age', '') if study_data else '',
                            'patient_sex': study_data.get('sex', '') if study_data else '',
                            'patient_birth_date': study_data.get('birth_date', '') if study_data else '',
                            'study_time': study_data.get('study_time', '') if study_data else '',
                            'body_part': study_data.get('body_part', '') if study_data else '',
                        }

                        # Ensure series UID -> number mapping is available before download signals fire
                        if widget and series_list:
                            try:
                                widget.set_server_series_info(series_list)
                                _logger.info(
                                    "[FAST-THUMB-OVERVIEW] study=%s series_count=%d thumb_stubs_scheduled thumbnail_overview_visible_ms=%.0f",
                                    study_uid, len(series_list),
                                    (_time.perf_counter() - _t0_double_click) * 1000.0,
                                )
                            except Exception:
                                pass

                        # ⚡ IMMEDIATE START - pauses all, starts this one right away
                        # Priority is HIGH (not CRITICAL) for the patient open.
                        # CRITICAL is reserved for the specific series being viewed.
                        # When the viewer loads a series, it will escalate that
                        # series to CRITICAL via set_viewed_series().
                        _logger.info(
                            "[FAST-SERIES-DOWNLOAD-QUEUE] study=%s series_count=%d order=top_to_bottom priority=High",
                            study_uid, len(series_list),
                        )
                        download_manager.start_priority_download_immediately(
                            study_data=dm_study_data,
                            server_info=server,
                            priority="High"  # Double-clicked patient = High priority (all series)
                        )

                        # [H7-P1] Pipeline A timeline: download started, DM not yet wired
                        _logger.info(
                            "[H7-P1] study=%s dm_started=True dm_wired=False t_since_open_ms=%.1f",
                            study_uid, (_time.perf_counter() - _t0_double_click) * 1000.0,
                        )

                        # Connect Download Manager progress signals to this widget
                        # This allows real-time progress tracking for the opened patient
                        self._connect_download_manager_to_widget(download_manager, widget, study_uid)

                        # [H7-P1] Pipeline A timeline: DM wired
                        _logger.info(
                            "[H7-P1] study=%s dm_started=True dm_wired=True t_since_open_ms=%.1f",
                            study_uid, (_time.perf_counter() - _t0_double_click) * 1000.0,
                        )
                except Exception as e:
                    print(f"⚠️ Error adding to Download Manager: {e}")  # Log for debugging

            # --- STEP 3.6: UI-bound async tasks must run on main thread/event loop ---
            try:
                asyncio.create_task(self._load_and_display_series_info_async(patient_id, patient_name, study_uid))
                patient_info = {
                    "PatientID": patient_id,
                    "PatientName": patient_name,
                    "StudyInstanceUID": study_uid,
                }
                asyncio.create_task(self.show_patient_studies(patient_info))
            except Exception as e:
                print(f"⚠️ [UI] Error scheduling UI tasks: {e}")

            # --- STEP 4: Background tasks (non-blocking via threading to avoid async conflicts) ---
            def _background_setup_thread():
                """Run background setup in a separate thread to avoid async conflicts"""
                try:
                    # Download attachments in background (non-blocking)
                    if not is_local:
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(
                                    download_attachments_for_study_async(study_uid)
                                )
                            finally:
                                loop.close()
                        except Exception as e:
                            print(f"⚠️ [THREAD] Error downloading attachments: {e}")

                    # Get series list for on-demand download
                    series_list = []
                    if hasattr(self, 'right_panel_widget') and hasattr(self.right_panel_widget, '_current_series_info'):
                        series_list = self.right_panel_widget._current_series_info

                    if not series_list and not is_local:
                        try:
                            study_info = self.get_series_info_from_server(study_uid, patient_id)
                            if study_info:
                                series_list = study_info.get('series', [])
                        except Exception:
                            pass

                    # Pass series info to widget
                    if widget and series_list:
                        widget.set_server_series_info(series_list)

                    # Download is already started by add_study_downloads(start_immediately=True)
                    # in Step 3.5 above. No need to start again here.
                    # The Download Manager handles progress tracking and priority ordering.

                except Exception as e:
                    print(f"⚠️ [BACKGROUND] Error in background setup: {e}")

            # Start background tasks in a separate thread (no async conflicts)
            threading.Thread(target=_background_setup_thread, daemon=True).start()

            # Hide loading after tab is shown
            self.hide_loading()
            self._hide_double_click_loading()

            # Auto-hide patient widget overlay after 3 seconds as fallback
            QTimer.singleShot(3000, lambda: widget._hide_init_overlay() if hasattr(widget, '_hide_init_overlay') else None)

            # Everything is handled in the fast path above
        except Exception as e:
            print(f"Error in patient double-click handler: {str(e)}")
            self._trace_action_done(action_id, phase='double_click_error', extra={'study_uid': str(study_uid), 'error': str(e)})
            # Hide loading on error
            self.hide_loading()
            self._double_click_first_series_loaded = True
            self._maybe_hide_double_click_loading()
            
            # Hide loading feed on error
            try:
                self._hide_loading_feed()
            except Exception:
                pass
        finally:
            try:
                self._opening_studies.discard(study_uid)
            except Exception:
                pass

    def _hide_double_click_loading(self):
        """Hide the loading screen specifically for double-click events"""
        self._double_click_first_series_loaded = True
        self._maybe_hide_double_click_loading()

    def _on_first_series_loaded(self):
        self._double_click_first_series_loaded = True
        self._maybe_hide_double_click_loading()

    def remove_from_opening_studies(self, study_uid):
        """Remove a study from the opening studies set"""
        try:
            self._opening_studies.discard(study_uid)
            print(f"Removed study {study_uid} from opening studies set")
        except Exception as e:
            print(f"Error removing study from opening studies: {e}")

    def _maybe_hide_double_click_loading(self):
        if not getattr(self, '_double_click_loading_active', False):
            return
        if self._double_click_first_series_loaded:
            self._double_click_loading_active = False
            self.hide_loading()

    def _on_patient_double_clicked__bb(self, patient_id, patient_name, study_uid):
        """Handle patient double-click event from PatientTableWidget - uses Zeta Download Manager"""
        try:
            # First, check if study already exists locally
            output_dir, have_subfolders = get_study_source_path(study_uid)

            if have_subfolders:
                # Study already exists locally - open immediately
                self.add_new_tab_widget(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    folder_path=output_dir,
                    caller=CallerTypes.SERVER,
                    study_uid=study_uid
                )
            else:
                # Study doesn't exist - open tab immediately and queue for download via Zeta
                widget = self.add_new_tab_widget(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    folder_path=None,
                    caller=CallerTypes.SERVER,
                    study_uid=study_uid
                )

                # Ensure patient_id is available in the widget
                if hasattr(widget, 'patient_id'):
                    widget.patient_id = patient_id
                elif hasattr(widget, 'set_patient_info'):
                    widget.set_patient_info(patient_id, patient_name, study_uid)

                # Route through Zeta Download Manager
                server = self.data_access_panel_widget.get_server_selected()
                if server:
                    # Create study dict for Zeta
                    study_dict = {
                        'patient_id': patient_id,
                        'patient_name': patient_name,
                        'study_uid': study_uid
                    }
                    # Get or create Zeta Download Manager
                    zeta_manager = self._get_or_create_download_manager_tab()
                    if zeta_manager:
                        # Fetch series info first
                        study_info = self._get_or_fetch_series_info(study_uid, patient_id)
                        if study_info:
                            study_dict['series'] = study_info.get('series', [])
                            study_dict['series_count'] = study_info.get('count_of_series', len(study_dict.get('series', [])))
                        # Add to Zeta with high priority
                        zeta_manager.add_downloads([study_dict], start_immediately=True)
                    else:
                        print("Failed to create Zeta Download Manager")
                else:
                    print("No server selected")

        except Exception as e:
            print(f"Error in patient double-click handler: {str(e)}")
            import traceback
            traceback.print_exc()

    def close_tab(self, index):
        """Safely close a tab and clean up references"""
        try:
            widget = self.tab_widget.widget(index)
            study_uid = None
            offline_cloud_server = getattr(widget, 'offline_cloud_server', None) if widget else None
            
            # Clean up download tasks if this is a patient widget
            if widget and hasattr(widget, 'study_uid'):
                study_uid = widget.study_uid
                # Cancel any ongoing downloads for this study
                if hasattr(self, '_download_tasks'):
                    for task in list(self._download_tasks):
                        if task and not task.done():
                            task.cancel()
            
            # Remove from dict_tabs_widget
            if hasattr(widget, 'study_uid') and widget.study_uid in self.dict_tabs_widget:
                del self.dict_tabs_widget[widget.study_uid]
            
            # Close the tab
            self.tab_widget.removeTab(index)
            
            # Force cleanup
            if widget:
                widget.deleteLater()

            if offline_cloud_server and study_uid:
                self._autosync_studies_to_offline_cloud(offline_cloud_server, [study_uid], show_errors=False)
                
        except Exception as e:
            print(f"⚠️ Error closing tab: {e}")

    def cleanup(self):
        """Release resources owned by HomePanelWidget.

        Called from MainWindowWidget.closeEvent before the widget is destroyed.
        Shuts down the thread pool and cancels outstanding background tasks.
        """
        # Shutdown thread pool
        if hasattr(self, 'thread_pool') and self.thread_pool is not None:
            self.thread_pool.shutdown(wait=False)
            self.thread_pool = None

        # Cancel outstanding async tasks
        if hasattr(self, '_background_tasks'):
            for task in list(self._background_tasks):
                if not task.done():
                    task.cancel()
            self._background_tasks.clear()

    def _safe_emit_series_downloaded(self, widget_ref_weak, series_number):
        """Safely emit series_downloaded signal, checking if widget exists"""
        try:
            widget = widget_ref_weak()
            if widget and hasattr(widget, 'series_downloaded'):
                # Check if C++ object is still valid
                try:
                    _ = widget.isVisible()
                    widget.series_downloaded.emit(str(series_number))
                except RuntimeError:
                    print(f"⚠️ Widget deleted, cannot emit signal for series {series_number}")
        except Exception as e:
            print(f"⚠️ Error emitting series_downloaded signal: {e}")
