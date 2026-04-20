"""Download coordination: start, complete, fail, resume, progress dialog"""
# Auto-generated from home_ui.py — Phase 3 split

import asyncio
import logging as _logging
import os
import traceback

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))

from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, save_image_as_png
from PacsClient.utils import get_all_patients, search_patients_local, find_patient_pk, find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.db_manager import get_study_by_study_uid
from modules.network.zeta_adapter import get_zeta_download_manager_widget, get_zeta_executor, get_zeta_worker_pool, start_zeta_download, create_download_task_from_study
from pathlib import Path

class _HPDownloadMixin:
    """Download coordination: start, complete, fail, resume, progress dialog"""

    def _on_download_requested(self, selected_studies, set_current_tab=True):
        """Handle download request from patient table - NOW USES ZETA DOWNLOAD MANAGER"""
        print('[Zeta Download] Download button clicked!')
        try:
            # Check if server is selected
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                QMessageBox.warning(self, "Server Not Selected",
                                    "Please select a PACS server first.")
                return
            if server.get("server_type") == "offline_cloud":
                QMessageBox.information(
                    self,
                    "Offline Cloud Server",
                    "The selected server is an Offline Cloud Server. Work directly against the shared folder package here, and use Offline Sync manually when handing data between the folder and a live AI PACS server.",
                )
                return
            
            print(f"[Zeta Download] Server selected - {server}")
            
            # Get or create Zeta Download Manager
            zeta_manager = self._get_or_create_download_manager_tab()
            
            if not zeta_manager:
                QMessageBox.critical(self, "Error", "Failed to create Zeta Download Manager")
                return
            
            # Switch to tab if requested
            if set_current_tab:
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.widget(i) is zeta_manager:
                        self.tab_widget.setCurrentIndex(i)
                        break
            
            # Enhance studies with series information before adding
            for study in selected_studies:
                if 'series' not in study or not study.get('series'):
                    try:
                        study_uid = study.get('study_uid')
                        patient_id = study.get('patient_id')
                        if study_uid:
                            print(f"[Old Download] Fetching series info for {study.get('patient_name')}...")
                            study_info = self._get_or_fetch_series_info(study_uid, patient_id)
                            if study_info:
                                study['series'] = study_info.get('series', [])
                                study['series_count'] = study_info.get('count_of_series', len(study.get('series', [])))
                                if study.get('series'):
                                    study['images_count'] = sum(s.get('image_count', 0) for s in study['series'])
                                print(f"[Old Download] ✅ Fetched {len(study.get('series', []))} series")
                    except Exception as e:
                        print(f"⚠️ [Old Download] Could not fetch series info: {e}")
            
            print(f"[Old Download] Adding {len(selected_studies)} studies to manager")
            
            # Add downloads to Zeta
            zeta_manager.add_downloads(selected_studies, start_immediately=True)
            # Throttle all ZetaBoost warmup workers globally while any download runs.
            try:
                from modules.zeta_boost.engine import set_global_download_active
                set_global_download_active(True)
                print("[GlobalDL] set_global_download_active=True")
            except Exception:
                pass

        except Exception as e:
            print(f"❌ Error in _on_download_requested: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error in download request: {str(e)}")

    def _normalize_study_uids(self, studies):
        return sorted({
            str(study.get("study_uid") or "").strip()
            for study in (studies or [])
            if str(study.get("study_uid") or "").strip()
        })

    def _get_or_create_download_manager_tab(self, activate_tab: bool = False):
        """Get existing Download Manager tab or create new one (delegates to service).

        The service handles creation, but completion signals need to be
        connected to *this* widget's handler the first time.
        """
        dm = self.download_service.get_or_create_dm_tab(activate=activate_tab)
        if dm is not None:
            # Ensure completion signals are connected (idempotent check)
            try:
                if not getattr(dm, '_home_signals_connected', False):
                    dm.download_completed.connect(self._on_study_download_completed)
                    dm.download_failed.connect(self._on_study_download_failed)
                    dm._home_signals_connected = True
            except Exception:
                pass
        return dm

    def _connect_download_manager_to_widget(self, download_manager, widget, study_uid: str):
        """Connect DM progress signals to a patient widget (delegates to service)."""
        self.download_service.connect_dm_to_widget(download_manager, widget, study_uid)

    def _on_study_download_completed(self, study_uid: str):
        """Update patient list when a study download completes.

        v2.2.3.1.7 Phase 3A: The heavy DB-save work (study info retrieval +
        DB write + study_path update) is now offloaded to an executor thread
        via ``_save_study_to_db_async``.  Only the fast, UI-critical operations
        stay on the main thread: pipeline signal, table status update, auto-open.
        This eliminates the ~80–200ms main-thread block that showed up as a Mode B
        queue spike in the B4 log metric.
        """
        try:
            from PacsClient.pacs.patient_tab.utils.utils import check_study_complete

            print(f"\n{'='*70}")
            print(f"📥 [DOWNLOAD_COMPLETE] Study download completed: {study_uid}")
            print(f"{'='*70}")

            # 1. Determine status (fast DB/file check — stays on main thread).
            result = check_study_complete(study_uid)
            print(f"[CHECK_STATUS] check_study_complete returned: {result}")

            if isinstance(result, dict):
                if result.get('is_complete', False):
                    status = 'complete'
                    print(f"[STATUS] ✓ Study completely downloaded: "
                          f"{result.get('series_downloaded', 0)}/{result.get('series_expected', 0)} series")
                elif result.get('series_downloaded', 0) > 0:
                    status = 'partial'
                    print(f"[STATUS] ⚠️ Partial: "
                          f"{result.get('series_downloaded')}/{result.get('series_expected')} series")
                else:
                    status = 'not_downloaded'
                    print(f"[STATUS] ✗ No downloaded series")
            elif isinstance(result, bool):
                status = 'complete' if result else 'not_downloaded'
                print(f"[STATUS] Result is bool: {status}")
            else:
                status = 'not_downloaded'
                print(f"[STATUS] Unknown result type: {type(result)}")

            # 2. Fire pipeline signal immediately (unlocks ZetaBoost warmup).
            #    Must run on the main/UI thread.
            if status == 'complete':
                try:
                    widget = self._find_widget_by_study_uid(study_uid)
                    if widget and hasattr(widget, 'viewer_controller'):
                        widget.viewer_controller.on_study_download_completed(study_uid)
                        print(f"[PIPELINE] ✅ Signaled viewer controller: study download complete")
                except Exception as pipe_err:
                    print(f"[PIPELINE] ⚠️ Failed to signal viewer controller: {pipe_err}")

            # 3. Quick UI updates (main thread only).
            if hasattr(self, 'patient_table_widget'):
                self.patient_table_widget.update_study_download_status(study_uid, status)
                print(f"[UI_UPDATE] Updated patient table for {study_uid}: {status}")

            if status == 'complete' and hasattr(self, '_auto_open_after_download'):
                if self._auto_open_after_download:
                    print(f"[AUTO_OPEN] Opening study {study_uid}...")
                    self._auto_open_downloaded_study(study_uid)

            print(f"{'='*70}\n")

            # 4. Global download flag (fast — stays on main thread).
            self._refresh_global_download_flag()

            # 5. Offload heavy DB-save work to background executor.
            #    Avoids blocking the UI/VTK thread with file-I/O and DB writes.
            if status in ('complete', 'partial'):
                try:
                    asyncio.ensure_future(self._save_study_to_db_async(study_uid, status))
                except Exception as sched_err:
                    print(f"[SAVE_TO_DB] ⚠️ Could not schedule async DB save: {sched_err}")

        except Exception as e:
            print(f"❌ [FATAL] Error: {e}")
            import traceback
            traceback.print_exc()

    async def _save_study_to_db_async(self, study_uid: str, status: str):
        """Background executor task for DB-heavy post-download work.

        Called from ``_on_study_download_completed`` after all UI-critical work
        is done.  Runs the time-consuming DB reads/writes off the main thread so
        the VTK render loop and ZetaBoost warmup are not blocked.

        After the executor completes, ``_refresh_local_tab_after_download`` is
        called back on the Qt/asyncio event loop to refresh the patient list UI.
        """
        try:
            from PacsClient.utils.config import SOURCE_PATH
            from PacsClient.utils.db_manager import find_study_pk_with_study_uid, update_study_missing_fields

            loop = asyncio.get_event_loop()

            def _bg_work():
                results = {}

                # ── Retrieve and persist study info ──
                try:
                    print(f"[SAVE_TO_DB] Retrieving study info for {study_uid}...")
                    study_info = self._get_study_info_for_completed_download(study_uid)
                    if study_info:
                        print(f"[SAVE_TO_DB] Got study info: "
                              f"patient={study_info.get('patient_name')}, "
                              f"series_count={len(study_info.get('series', []))}")
                        saved = self.save_complete_study_info(study_uid, study_info=study_info)
                        results['saved'] = saved
                        print(f"[SAVE_TO_DB] {'✅ Saved' if saved else '❌ Failed to save'} study to database")
                    else:
                        print(f"[SAVE_TO_DB] ❌ Could not retrieve study info")
                        results['saved'] = False
                except Exception as e:
                    print(f"[SAVE_TO_DB] ❌ Error: {e}")
                    import traceback
                    traceback.print_exc()
                    results['saved'] = False

                # ── Ensure study_path is populated for local search visibility ──
                try:
                    study_pk = find_study_pk_with_study_uid(study_uid)
                    if study_pk:
                        study_path = str(SOURCE_PATH / study_uid)
                        update_study_missing_fields(study_pk, study_path=study_path)
                        print(f"[LOCAL_SYNC] Updated study_path: {study_path}")
                    else:
                        print(f"[LOCAL_SYNC] ❌ Study not found in database after download")
                except Exception as update_error:
                    print(f"[LOCAL_SYNC] ❌ Failed to update study_path: {update_error}")

                return results

            results = await loop.run_in_executor(None, _bg_work)

            # ── Refresh patient list UI back on the event-loop thread ──
            if results.get('saved'):
                self._refresh_local_tab_after_download()

        except Exception as e:
            print(f"[SAVE_TO_DB_ASYNC] ❌ Error: {e}")
            import traceback
            traceback.print_exc()

    def _refresh_global_download_flag(self):
        """Update the ZetaBoost global download flag (delegates to service)."""
        self.download_service.refresh_global_download_flag()

    def _get_study_info_for_completed_download(self, study_uid: str) -> dict:
        """Get study info for a completed download from local files or database"""
        try:
            print(f"\n[GET_INFO] Retrieving study info for {study_uid}...")
            
            # First try to get from database
            print(f"[GET_INFO] Querying database...")
            study_info = get_study_by_study_uid(study_uid)
            if study_info:
                print(f"[GET_INFO] ✓ Found study in database")
                print(f"[GET_INFO] Study info keys: {study_info.keys()}")
                
                # Get patient info from the study
                from PacsClient.utils.db_manager import get_patient_by_patient_pk
                patient_pk = study_info.get('patient_fk')
                patient_info = None
                
                if patient_pk:
                    patient_info = get_patient_by_patient_pk(patient_pk)
                    if patient_info:
                        print(f"[GET_INFO] ✓ Found patient: {patient_info.get('patient_name')} ({patient_info.get('patient_id')})")
                        # Add patient info to study_info
                        study_info['patient_id'] = patient_info.get('patient_id')
                        study_info['patient_name'] = patient_info.get('patient_name')
                    else:
                        print(f"[GET_INFO] ❌ Patient not found for pk={patient_pk}")
                else:
                    print(f"[GET_INFO] ❌ No patient_fk in study_info")
                
                # Get series from database
                from PacsClient.utils.db_manager import get_series_by_study_pk
                series_list = get_series_by_study_pk(study_info['study_pk'])
                if series_list:
                    print(f"[GET_INFO] ✓ Found {len(series_list)} series in database")
                    study_info['series'] = series_list
                    study_info['count_of_series'] = len(series_list)
                    
                    # Make sure patient_id and patient_name are set
                    if study_info.get('patient_id') and study_info.get('patient_name'):
                        print(f"[GET_INFO] ✅ Complete study info ready: {study_info.get('patient_name')} ({len(series_list)} series)")
                        return study_info
                    else:
                        print(f"[GET_INFO] ⚠️ Missing patient info, trying local files...")
                else:
                    print(f"[GET_INFO] ⚠️ No series in database, trying local files...")
            else:
                print(f"[GET_INFO] ⚠️ Not in database, trying local files...")
            
            # If not in database or missing patient info, try to get from local files
            study_path = SOURCE_PATH / study_uid
            print(f"[GET_INFO] Checking local path: {study_path}")
            if study_path.exists():
                print(f"[GET_INFO] 📂 Found study path, analyzing files...")
                # Build study info from local files
                from PacsClient.pacs.patient_tab.utils import get_all_series_thumbnail_from_study_folder
                series_data = get_all_series_thumbnail_from_study_folder(str(study_path))
                if series_data and 'series' in series_data:
                    series_count = len(series_data['series'])
                    print(f"[GET_INFO] ✓ Found {series_count} series in local files")
                    # Get basic study info from first series
                    first_series = series_data['series'][0] if series_data['series'] else {}
                    study_info = {
                        'study_uid': study_uid,
                        'patient_id': first_series.get('patient_id', 'Unknown'),
                        'patient_name': first_series.get('patient_name', 'Unknown'),
                        'study_date': first_series.get('study_date', ''),
                        'study_time': first_series.get('study_time', ''),  # Add study_time
                        'study_description': first_series.get('study_description', ''),
                        'series': series_data['series'],
                        'count_of_series': series_count
                    }
                    print(f"[GET_INFO] ✅ Built study info from files: {study_info['patient_name']} ({series_count} series)")
                    return study_info
                else:
                    print(f"[GET_INFO] ❌ No series data in local files")
            else:
                print(f"[GET_INFO] ❌ Study path does not exist: {study_path}")
            
            return None
        except Exception as e:
            print(f"[GET_INFO] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _refresh_local_tab_after_download(self):
        """Refresh local patient list if currently on Local tab"""
        try:
            # Check if we're on the Local tab
            current_tab = self.data_access_panel_widget.tab_selected_name
            print(f"[REFRESH_LOCAL] Current tab: {current_tab}")
            if current_tab and current_tab.lower() == 'local':
                print(f"[REFRESH_LOCAL] 🔄 Refreshing local patient list...")
                # Trigger a search to refresh the list
                asyncio.create_task(self.search_patients_from_local_async())
            else:
                print(f"[REFRESH_LOCAL] Not on Local tab, skipping refresh")
        except Exception as e:
            print(f"[REFRESH_LOCAL] ❌ Error: {e}")

    def _on_study_download_failed(self, study_uid: str, error_message: str):
        """Handle study download failure"""
        try:
            print(f"❌ Study download failed: {study_uid}")
            print(f"   Error: {error_message}")
            
            # Update patient table widget to show error status
            if hasattr(self, 'patient_table_widget'):
                self.patient_table_widget.update_study_download_status(study_uid, 'error')
                print(f"✓ Updated patient table for {study_uid}: error")
            
            # Re-evaluate global warmup throttle flag.
            self._refresh_global_download_flag()
                    
        except Exception as e:
            print(f"Error handling download failure: {e}")

    def _on_resumable_download_clicked(self):
        """Handle resumable download manager button click - Uses Zeta Download Manager"""
        try:
            # Import Zeta download manager widget (replaces resumable_download_widget)
            from modules.download_manager.ui.main_widget import DownloadManagerWidget as ResumableDownloadManagerWidget
            from PacsClient.utils.config import SOURCE_PATH

            # Check if resumable download manager tab already exists
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, ResumableDownloadManagerWidget):
                    # Tab already exists, just switch to it
                    self.tab_widget.setCurrentIndex(i)
                    print("[Zeta Download] Switched to existing Resumable Downloads tab")
                    return

            # Create new Zeta download manager tab
            print("[Zeta Download] Creating new Resumable Downloads tab")
            resumable_download_manager = ResumableDownloadManagerWidget(base_output_dir=Path(SOURCE_PATH))
            self.tab_widget.addTab(resumable_download_manager, "🚀 Zeta Downloads")

            # Switch to the new tab
            self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)

            print("[OK] Resumable Download Manager opened")

        except Exception as e:
            print(f"[ERROR] Error opening resumable download manager: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error opening resumable download manager: {str(e)}")

    def download_study(self, row):
        """Download study from the selected row using Zeta Download Manager"""
        try:
            patient_data = self.patient_table_widget.get_patient_data_by_row(row)
            if not patient_data:
                raise Exception("Patient data not found")

            patient_id = patient_data['patient_id']
            patient_name = patient_data['patient_name']
            study_uid = patient_data['study_uid']

            # Use Zeta download adapter
            from modules.network.zeta_adapter import start_zeta_download, create_download_task_from_study

            # Get service instance
            service = get_resumable_dicom_service()

            # Check if download is already active
            if service.is_download_active(study_uid):
                QMessageBox.information(self, "Download Active",
                                        f"Download is already in progress for:\nPatient: {patient_name} ({patient_id})")
                return

            # Check download status
            output_dir = os.path.join(os.getcwd(), "downloads", study_uid)
            status = service.get_download_status(study_uid, output_dir)

            if status['status'] == 'completed':
                QMessageBox.information(self, "Download Complete",
                                        f"Study is already downloaded for:\nPatient: {patient_name} ({patient_id})")
                return

            # Show download options dialog
            self.show_download_options_dialog(patient_data, service)

        except Exception as e:
            print(f"Error in download_study: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error downloading study: {str(e)}")

    def show_download_options_dialog(self, patient_data, service):
        """Show download options dialog"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QSpinBox, \
            QComboBox, QFileDialog, QMessageBox
        from PySide6.QtCore import Qt

        dialog = QDialog(self)
        dialog.setWindowTitle("Download Options")
        dialog.setModal(True)
        dialog.resize(500, 400)

        layout = QVBoxLayout(dialog)

        # Study info
        info_group = QLabel(f"<b>Study Information:</b><br>"
                            f"Patient: {patient_data['patient_name']} ({patient_data['patient_id']})<br>"
                            f"Study UID: {patient_data['study_uid']}<br>"
                            f"Modality: {patient_data.get('modality', 'N/A')}<br>"
                            f"Date: {patient_data.get('study_date', 'N/A')}")
        info_group.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 10px; border-radius: 5px; }")
        layout.addWidget(info_group)

        # Output directory
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Output Directory:"))
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setText(os.path.join(os.getcwd(), "downloads", patient_data['study_uid']))
        dir_layout.addWidget(self.output_dir_input)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(lambda: self.browse_output_directory())
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)

        # Batch size
        batch_layout = QHBoxLayout()
        batch_layout.addWidget(QLabel("Batch Size:"))
        self.batch_size_input = QSpinBox()
        self.batch_size_input.setRange(1, 100)
        self.batch_size_input.setValue(10)
        batch_layout.addWidget(self.batch_size_input)
        batch_layout.addStretch()
        layout.addLayout(batch_layout)

        # Compression
        comp_layout = QHBoxLayout()
        comp_layout.addWidget(QLabel("Compression:"))
        self.compression_combo = QComboBox()
        self.compression_combo.addItems(["gzip", "none"])
        comp_layout.addWidget(self.compression_combo)
        comp_layout.addStretch()
        layout.addLayout(comp_layout)

        # Resume option
        self.resume_checkbox = QCheckBox("Resume from previous download")
        self.resume_checkbox.setChecked(True)
        layout.addWidget(self.resume_checkbox)

        # Buttons
        button_layout = QHBoxLayout()

        start_btn = QPushButton("Start Download")
        start_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; }")
        start_btn.clicked.connect(lambda: self.start_resumable_download(patient_data, service, dialog))

        resume_btn = QPushButton("Resume Only")
        resume_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; padding: 8px; }")
        resume_btn.clicked.connect(lambda: self.resume_download_only(patient_data, service, dialog))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)

        button_layout.addWidget(start_btn)
        button_layout.addWidget(resume_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        dialog.exec()

    def browse_output_directory(self):
        """Browse for output directory"""
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir_input.setText(directory)

    def start_resumable_download(self, patient_data, service, dialog):
        """Start resumable download"""
        try:
            study_uid = patient_data['study_uid']
            output_dir = self.output_dir_input.text()
            batch_size = self.batch_size_input.value()
            compression = self.compression_combo.currentText()
            resume = self.resume_checkbox.isChecked()

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Start download
            if service.start_download(study_uid, output_dir, batch_size, compression, resume):
                QMessageBox.information(self, "Download Started",
                                        f"Download started successfully for:\nPatient: {patient_data['patient_name']}")
                dialog.accept()

                # Show download progress dialog
                self.show_download_progress_dialog(patient_data, service)
            else:
                QMessageBox.warning(self, "Download Failed", "Failed to start download")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error starting download: {str(e)}")

    def resume_download_only(self, patient_data, service, dialog):
        """Resume download only"""
        try:
            study_uid = patient_data['study_uid']
            output_dir = self.output_dir_input.text()

            # Resume download
            if service.resume_download(study_uid, output_dir):
                QMessageBox.information(self, "Download Resumed",
                                        f"Download resumed successfully for:\nPatient: {patient_data['patient_name']}")
                dialog.accept()

                # Show download progress dialog
                self.show_download_progress_dialog(patient_data, service)
            else:
                QMessageBox.warning(self, "Resume Failed", "Failed to resume download")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error resuming download: {str(e)}")

    def show_download_progress_dialog(self, patient_data, service):
        """Show Zeta download progress widget"""
        # Use Zeta download manager widget
        widget = get_zeta_download_manager_widget()
        widget.show()
        return
        
        # Legacy code kept for reference:
        # from PacsClient.components.resumable_download_widget import DownloadProgressWidget

        # Create progress widget
        progress_widget = DownloadProgressWidget(
            patient_data['study_uid'],
            self.output_dir_input.text()
        )

        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Download Progress - {patient_data['patient_name']}")
        dialog.setModal(False)
        dialog.resize(600, 500)

        layout = QVBoxLayout(dialog)
        layout.addWidget(progress_widget)

        # Connect signals
        progress_widget.downloadCompleted.connect(
            lambda success, message: self.on_download_completed(success, message, dialog))
        progress_widget.downloadError.connect(lambda error: self.on_download_error(error, dialog))

        dialog.show()

    def on_download_completed(self, success, message, dialog):
        """Handle download completion"""
        if success:
            QMessageBox.information(self, "Download Complete", f"[OK] {message}")
        else:
            QMessageBox.warning(self, "Download Failed", f"[ERROR] {message}")
        dialog.close()

    def on_download_error(self, error, dialog):
        """Handle download error"""
        QMessageBox.critical(self, "Download Error", f"[ERROR] {error}")
        dialog.close()
