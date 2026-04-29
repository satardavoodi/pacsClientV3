"""Table & details panel: selection, details rendering, table ordering, row building"""
# Auto-generated from main_widget.py — Phase 2 split



import logging

from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QLabel, QSplitter, QFrame, QHeaderView, QAbstractItemView, QGroupBox, QScrollArea, QProgressBar, QComboBox, QTextEdit

from ...core.enums import DownloadPriority, DownloadStatus
from ...core.models import DownloadTask, DownloadState
from ..components.priority_group import PriorityGroupHeader
from ..components.status_badge import StatusBadge

logger = logging.getLogger(__name__)

class _DMDetailsMixin:
    """Table & details panel: selection, details rendering, table ordering, row building"""

    def _on_selection_changed(self):
        """Handle table row selection — update details panel"""
        if self._suppressing_selection_signals:
            return

        # ✅ WIDGET VALIDITY: Check if table still exists
        if not self.download_table or not hasattr(self, 'download_table'):
            logger.debug("⚠️ download_table not available")
            return

        try:
            row = self.download_table.currentRow()
            if row < 0:
                self._selected_study_uid = None
                self._clear_details_panel()
                return

            # Skip if this is a priority group header or spacer row
            widget = self.download_table.cellWidget(row, 0)
            if isinstance(widget, (PriorityGroupHeader, QFrame)):
                self._selected_study_uid = None
                self._clear_details_panel()
                return

            # Find study_uid for this row
            study_uid = None
            for uid, r in self.download_rows.items():
                if r == row:
                    study_uid = uid
                    break

            if study_uid:
                self._selected_study_uid = study_uid
                self._update_details_panel(study_uid)
            else:
                self._selected_study_uid = None
                self._clear_details_panel()

        except Exception as e:
            logger.error(f"Error in _on_selection_changed: {e}")

    def _select_study_row(self, study_uid: str, ensure_visible: bool = True) -> None:
        """Select a study row by study_uid and sync details panel."""
        # finally: suppression flag is always reset at method exit
        self._suppressing_selection_signals = True
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return

            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping selection")
                return

            row = self._find_row_for_study_uid(study_uid)
            if row is None:
                logger.warning(f"⚠️ No row found for study_uid: {study_uid[:40]}")
                return

            logger.info(f"🔍 [SELECT] Programmatic selection of study row: {study_uid[:40]}...")
            self.download_table.selectRow(row)

            if ensure_visible:
                item = self.download_table.item(row, 1)
                if item:
                    self.download_table.scrollToItem(item, QAbstractItemView.PositionAtCenter)

            # Always update details panel (don't skip even if same study)
            self._selected_study_uid = study_uid
            
            # Clear all fields first to ensure fresh start
            self._clear_details_panel()
            
            # Clear reception fields to show loading state
            self._reset_reception_fields("Loading...")
            
            # Update details panel with full refresh
            self._update_details_panel(study_uid)
            logger.info(f"✅ [SELECT] Study row programmatic selection completed for: {study_uid[:40]}...")
        except Exception as e:
            logger.error(f"❌ Error selecting study row: {e}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
        finally:
            self._suppressing_selection_signals = False

    def _on_table_cell_clicked(self, row: int, column: int) -> None:
        """Ensure row selection updates even when clicking cell widgets."""
        try:
            if not self.download_table or not hasattr(self, 'download_table'):
                return

            # Force select the row (critical fix!)
            self.download_table.selectRow(row)

            # Now get study_uid from row
            study_uid = None
            for uid, r in self.download_rows.items():
                if r == row:
                    study_uid = uid
                    break

            if study_uid:
                self._selected_study_uid = study_uid
                self._update_details_panel(study_uid)

        except Exception as e:
            logger.error(f"Error handling cell click: {e}")

    def _on_table_item_clicked(self, item: QTableWidgetItem) -> None:
        """Update details panel when clicking a table item."""
        try:
            row = item.row()
            widget = self.download_table.cellWidget(row, 0)
            if isinstance(widget, (PriorityGroupHeader, QFrame)):
                return

            study_uid = self._get_study_uid_for_row(row)

            if study_uid:
                # Log the patient click event specifically with comprehensive details
                state = self.state_store.get(study_uid)
                task = self._tasks.get(study_uid)

                patient_name = getattr(state, 'patient_name', 'Unknown')
                patient_id = getattr(state, 'patient_id', 'Unknown') if state else (getattr(task, 'patient_id', 'Unknown') if task else 'Unknown')
                study_date = getattr(state, 'study_date', 'Unknown') if state else (getattr(task, 'study_date', 'Unknown') if task else 'Unknown')
                modality = getattr(state, 'modality', 'Unknown') if state else (getattr(task, 'modality', 'Unknown') if task else 'Unknown')
                description = getattr(state, 'study_description', 'Unknown') if state else (getattr(task, 'description', 'Unknown') if task else 'Unknown')
                status = getattr(state, 'status', 'Unknown') if state else 'Unknown'
                priority = getattr(getattr(state, 'priority', None), 'display_name', 'Unknown') if state else 'Unknown'

                logger.info(f"👤 [PATIENT_CLICKED] User clicked on patient via item click with comprehensive details:")
                logger.info(f"   Patient Name: {patient_name}")
                logger.info(f"   Patient ID: {patient_id}")
                logger.info(f"   Study UID: {study_uid[:40]}...")
                logger.info(f"   Study Date: {study_date}")
                logger.info(f"   Modality: {modality}")
                logger.info(f"   Description: {description}")
                logger.info(f"   Status: {status}")
                logger.info(f"   Priority: {priority}")

                # Count series if available
                series_count = 0
                if task and hasattr(task, 'series_list'):
                    series_count = len(task.series_list)
                elif state and hasattr(state, 'total_series_count'):
                    series_count = getattr(state, 'total_series_count', 0)
                logger.info(f"   Series Count: {series_count}")

                # Log to the UI log area
                self.log_message(f"👤 Patient clicked (item): {patient_name} (ID: {patient_id})")
                self.log_message(f"   Study UID: {study_uid[:40]}...")
                self.log_message(f"   Modality: {modality}, Status: {status}, Priority: {priority}")
                self.log_message(f"   Series: {series_count}, Study Date: {study_date}")
                self.log_message("-" * 80)

                # Always update details panel on click
                self._selected_study_uid = study_uid

                # Clear reception fields first to show loading state
                self._reset_reception_fields("Loading...")

                self._update_details_panel(study_uid)

                # Log successful panel update
                logger.info(f"🔄 [RIGHT_PANEL_UPDATED] Right panel updated for patient: {patient_name} (Study UID: {study_uid[:40]}...)")

                # Log all available studies to help debug why both patients might not be showing
                all_studies = list(self._tasks.keys())
                logger.info(f"📊 [STUDIES_AVAILABLE] Total studies in queue: {len(all_studies)}")
                for idx, study in enumerate(all_studies):
                    study_state = self.state_store.get(study)
                    study_task = self._tasks.get(study)
                    study_name = getattr(study_state, 'patient_name', 'Unknown') if study_state else 'Unknown'
                    logger.info(f"📊 [STUDIES_AVAILABLE] Study {idx+1}: {study_name} (UID: {study[:20]}...)")
        except Exception as e:
            logger.error(f"❌ Error handling item click: {e}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")

    def _clear_details_panel(self):
        """Clear all details panel information"""
        if self.patient_name_label:
            self.patient_name_label.setText("Name: -")
        if self.patient_id_label:
            self.patient_id_label.setText("ID: -")
        self._reset_reception_fields("-")
        if self.url_label:
            self.url_label.setText("Study UID: -")
        if self.study_date_label:
            self.study_date_label.setText("Study Date: -")
        if self.modality_label:
            self.modality_label.setText("Modality: -")
        if self.study_desc_label:
            self.study_desc_label.setText("Description: -")
        if self.size_label:
            self.size_label.setText("Series: - | Images: -")
        if self.progress_bar:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0.0% (0/0 images)")
        if self.progress_label:
            self.progress_label.setText("0% (0/0 images)")
        if self.speed_label:
            self.speed_label.setText("Speed: 0 KB/s")
        if self.eta_label:
            self.eta_label.setText("ETA: Unknown")
        if self.priority_combo:
            # G8.1 — block signals so the programmatic write does NOT
            # fire `_on_priority_changed`. Without this the unguarded
            # signal corrupted state (Critical -> Normal) AND triggered
            # a recursive `_refresh_table_order`. See
            # docs/plans/performance/DM_TABLE_REBUILD_STORM_2026-04-29.md.
            #
            # Defensive: the Python wrapper may outlive the C++ widget
            # (RuntimeError: Internal C++ object already deleted) when
            # the details panel is being rebuilt or torn down. Truthy
            # `if self.priority_combo` does NOT detect this. Wrap the
            # whole block so a stale combo never blocks selection or
            # crashes the rebuild loop (regression observed 2026-04-30).
            try:
                self.priority_combo.blockSignals(True)
                try:
                    self.priority_combo.setCurrentText("Normal")
                finally:
                    self.priority_combo.blockSignals(False)
            except RuntimeError:
                # C++ object already deleted; nothing to clear.
                self.priority_combo = None
        # Clear additional patient information fields
        if hasattr(self, 'age_label') and self.age_label:
            self.age_label.setText("Age: -")
        if hasattr(self, 'gender_label') and self.gender_label:
            self.gender_label.setText("Gender: -")
        if hasattr(self, 'birth_date_label') and self.birth_date_label:
            self.birth_date_label.setText("Birth Date: -")
        if hasattr(self, 'tel_label') and self.tel_label:
            self.tel_label.setText("Time: -")
        if hasattr(self, 'body_part_label') and self.body_part_label:
            self.body_part_label.setText("Body Part: -")

    def _reset_reception_fields(self, status_text: str = "Loading...") -> None:
        """Reset reception fields while switching selection."""
        if self.patient_identifier_label:
            self.patient_identifier_label.setText(f"Identifier: {status_text}")
        if self.requesting_physician_label:
            self.requesting_physician_label.setText(f"Requesting Physician: {status_text}")
        if self.reception_status_label:
            self.reception_status_label.setText(f"Reception Status: {status_text}")

    def _update_details_panel(self, study_uid: str):
        state = self.state_store.get(study_uid)
        task = self._tasks.get(study_uid)
        additional_info = self._additional_task_info.get(study_uid, {}) if hasattr(self, '_additional_task_info') else {}

        # If no state, synthesise a minimal one from the task so the details
        # panel can still render without a separate task-lookup at every call
        # site.  Only valid DownloadState fields are used here.
        if not state and task:
            from ...core.models import DownloadState
            state = DownloadState(
                study_uid=task.study_uid,
                status=DownloadStatus.PENDING,
                priority=DownloadPriority.NORMAL,
                total_count=task.total_image_count,
                total_series_count=len(task.series_list),
                patient_name=task.patient_name,
                patient_id=task.patient_id,
                modality=task.modality,
                study_date=task.study_date,
                study_description=task.description,
            )

        if not state:
            self._clear_details_panel()
            return

        # ===== LOG COMPREHENSIVE PATIENT INFO =====
        logger.info(f"📋 [DETAILS-PANEL] Updating details for: {state.patient_name} ({study_uid[:40]}...)")
        logger.info(f"   State available: {state is not None}")
        logger.info(f"   Task available: {task is not None}")
        logger.info(f"   Additional info keys: {list(additional_info.keys())}")

        # Update patient info — prefer task for live data, fall back to state
        # (which now carries patient_id, modality, study_date as of the unified model)
        self.patient_name_label.setText(f"Name: {state.patient_name or 'Unknown'}")
        pid = (task.patient_id if task else None) or getattr(state, 'patient_id', None) or '-'
        self.patient_id_label.setText(f"ID: {pid}")
        self._reset_reception_fields("Loading...")
        self.url_label.setText(f"Study UID: {state.study_uid}")
        study_date = (task.study_date if task else None) or getattr(state, 'study_date', None) or '-'
        self.study_date_label.setText(f"Study Date: {study_date}")
        modality = (task.modality if task else None) or getattr(state, 'modality', None) or '-'
        self.modality_label.setText(f"Modality: {modality}")
        self.study_desc_label.setText(f"Description: {state.study_description or '-'}")

        # Update additional patient information from additional_info dict
        if additional_info:
            age = additional_info.get('patient_age', '-')
            sex = additional_info.get('patient_sex', '-')
            birth_date = additional_info.get('patient_birth_date', '-')
            study_time = additional_info.get('study_time', '-')
            body_part = additional_info.get('body_part', '-')
            
            logger.info(f"   Setting additional info - Age: {age}, Sex: {sex}, BirthDate: {birth_date}")
            logger.info(f"   Setting time: {study_time}, Body Part: {body_part}")
            
            if hasattr(self, 'age_label') and self.age_label:
                self.age_label.setText(f"Age: {age}")
            if hasattr(self, 'gender_label') and self.gender_label:
                self.gender_label.setText(f"Gender: {sex}")
            if hasattr(self, 'birth_date_label') and self.birth_date_label:
                self.birth_date_label.setText(f"Birth Date: {birth_date}")
            if hasattr(self, 'tel_label') and self.tel_label:
                self.tel_label.setText(f"Time: {study_time}")
            if hasattr(self, 'body_part_label') and self.body_part_label:
                self.body_part_label.setText(f"Body Part: {body_part}")
        else:
            logger.info(f"   ⚠️ No additional info available for display")

        # Update progress
        display_total = state.total_count or (task.total_image_count if task else 0)
        display_downloaded = state.downloaded_count
        display_percent = state.progress_percent
        if display_percent <= 0 and display_total > 0 and display_downloaded > 0:
            display_percent = (display_downloaded / display_total) * 100

        self.progress_bar.setValue(int(display_percent))
        self.progress_bar.setFormat(
            f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
        )
        self.progress_label.setText(
            f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
        )

        # Update speed and ETA
        speed_mb_per_sec = state.speed_mb_per_sec
        speed_kb_per_sec = speed_mb_per_sec * 1024
        eta_seconds = state.eta_seconds
        
        if speed_mb_per_sec > 0:
            self.speed_label.setText(f"Speed: {speed_kb_per_sec:.1f} KB/s")
        else:
            self.speed_label.setText("Speed: 0 KB/s")
        
        if eta_seconds and eta_seconds > 0:
            # Convert seconds to human readable format
            minutes = int(eta_seconds // 60)
            seconds = int(eta_seconds % 60)
            if minutes > 60:
                hours = minutes // 60
                minutes = minutes % 60
                self.eta_label.setText(f"ETA: {hours}h {minutes}m {seconds}s")
            elif minutes > 0:
                self.eta_label.setText(f"ETA: {minutes}m {seconds}s")
            else:
                self.eta_label.setText(f"ETA: {seconds}s")
        else:
            self.eta_label.setText("ETA: Unknown")

        # Series count — prefer task (has live list), fall back to state field
        # (populated at creation time so it's always correct even when task is None)
        if task:
            series_count = len(task.series_list)
        else:
            series_count = getattr(state, 'total_series_count', 0)
        self.size_label.setText(f"Series: {series_count} | Images: {display_total}")

        # Priority
        self.priority_combo.blockSignals(True)
        self.priority_combo.setCurrentText(state.priority.display_name)
        self.priority_combo.blockSignals(False)

        # Load reception data (avoid re-fetch loops on repeated refreshes)
        if task and task.patient_id:
            patient_id = task.patient_id
            cached_data = self._reception_cache.get(patient_id)
            if patient_id == self._last_reception_patient_id and cached_data:
                logger.info(f"📋 [RECEPTION] Using cached data for patient {patient_id}")
                self._apply_reception_data(cached_data)
            else:
                self._load_reception_data(patient_id, study_uid)

        # Update series breakdown
        if task:
            self._update_series_breakdown_from_task(task, state)

        # Sync button states with current download status
        self._update_button_states(state)

        logger.info(f"✅ [DETAILS-PANEL] Details panel updated successfully")

    def _log_patient_comprehensive_info(self, study_uid: str, state, task):
        """Log comprehensive patient information when a patient is clicked/selected"""
        logger.info(f"📋 [PATIENT_INFO_LOG] Comprehensive patient information for: {study_uid[:40]}...")
        
        # Basic patient information
        patient_name = getattr(state, 'patient_name', 'Unknown')
        patient_id = getattr(state, 'patient_id', 'Unknown') if state else (getattr(task, 'patient_id', 'Unknown') if task else 'Unknown')
        study_date = getattr(state, 'study_date', 'Unknown') if state else (getattr(task, 'study_date', 'Unknown') if task else 'Unknown')
        modality = getattr(state, 'modality', 'Unknown') if state else (getattr(task, 'modality', 'Unknown') if task else 'Unknown')
        description = getattr(state, 'study_description', 'Unknown') if state else (getattr(task, 'description', 'Unknown') if task else 'Unknown')
        status = getattr(state, 'status', 'Unknown') if state else 'Unknown'
        priority = getattr(getattr(state, 'priority', None), 'display_name', 'Unknown') if state else 'Unknown'
        
        logger.info(f"   🧍 Patient Name: {patient_name}")
        logger.info(f"   🔢 Patient ID: {patient_id}")
        logger.info(f"   📄 Study UID: {study_uid[:40]}...")
        logger.info(f"   📅 Study Date: {study_date}")
        logger.info(f"   🏥 Modality: {modality}")
        logger.info(f"   📝 Description: {description}")
        logger.info(f"   📊 Status: {status}")
        logger.info(f"   ⭐ Priority: {priority}")
        
        # Additional information if available
        if task:
            logger.info(f"   📁 Total Image Count: {task.total_image_count if hasattr(task, 'total_image_count') else 'Unknown'}")
            logger.info(f"   📊 Series Count: {len(task.series_list) if hasattr(task, 'series_list') else 'Unknown'}")
            
            # Log series information
            if hasattr(task, 'series_list') and task.series_list:
                logger.info(f"   📋 Series Details:")
                for i, series in enumerate(task.series_list):
                    logger.info(f"      • Series {i+1}: {series.series_number} - {series.series_description} ({series.image_count} images)")
        
        # State-specific information
        if state:
            logger.info(f"   📈 Downloaded Count: {getattr(state, 'downloaded_count', 'Unknown')}")
            logger.info(f"   📊 Total Count: {getattr(state, 'total_count', 'Unknown')}")
            logger.info(f"   📈 Progress Percent: {getattr(state, 'progress_percent', 'Unknown')}%")
            logger.info(f"   📁 Total Series Count: {getattr(state, 'total_series_count', 'Unknown')}")
            logger.info(f"   📦 Current Series: {getattr(state, 'current_series', 'Unknown')}")
            logger.info(f"   #️⃣  Current Series Number: {getattr(state, 'current_series_number', 'Unknown')}")
            logger.info(f"   📥 Current Series Downloaded: {getattr(state, 'current_series_downloaded', 'Unknown')}")
            logger.info(f"   📤 Current Series Total: {getattr(state, 'current_series_total', 'Unknown')}")
            logger.info(f"   📊 Current Series Progress: {getattr(state, 'current_series_progress', 'Unknown')}%")
            logger.info(f"   ✅ Completed Series: {getattr(state, 'completed_series', 'Unknown')}")
            logger.info(f"   ❌ Failed Series: {getattr(state, 'failed_series', 'Unknown')}")
            logger.info(f"   ⏭️  Skipped Series: {getattr(state, 'skipped_series', 'Unknown')}")
            logger.info(f"   🔄 Retry Count: {getattr(state, 'retry_count', 'Unknown')}")
            logger.info(f"   ❗ Error Message: {getattr(state, 'error_message', 'Unknown')}")
            logger.info(f"   ⏸️  Is Auto-Paused: {getattr(state, 'is_auto_paused', 'Unknown')}")
        
        logger.info(f"📋 [PATIENT_INFO_LOG] End of comprehensive patient information")

    def _update_button_states(self, state):
        """Update button states based on current download status"""
        # Guard: buttons may not exist yet (e.g. called before _setup_ui finishes)
        if not self.start_btn or not self.pause_btn or not self.cancel_btn or not self.retry_btn:
            return

        if not state:
            # Disable all buttons if no state
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(False)
            return

        status = state.status
        logger.debug(f"[BUTTONS] Updating button states for status: {status.value}")

        if status in [DownloadStatus.PENDING, DownloadStatus.VALIDATING, DownloadStatus.DOWNLOADING]:
            # Download is active - enable pause and cancel
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setEnabled(False)
        elif status == DownloadStatus.PAUSED:
            # Download is paused - enable start and cancel
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setEnabled(False)
        elif status == DownloadStatus.COMPLETED:
            # Download is completed - only retry makes sense
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(True)
        elif status == DownloadStatus.FAILED:
            # Download failed - start (resume) and retry both work
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setEnabled(True)
        elif status == DownloadStatus.CANCELLED:
            # Download cancelled - can restart or retry
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(True)
        else:
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(False)

    def _update_series_breakdown_from_task(self, task: DownloadTask, state: DownloadState):
        """Update series breakdown tree from task and state"""
        # Check if series_layout still exists before accessing it
        if not hasattr(self, 'series_layout') or not self.series_layout:
            logger.warning("📋 [SERIES-BREAKDOWN] series_layout not available, skipping update")
            return
            
        # Clear existing series widgets
        while self.series_layout.count():
            item = self.series_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not task or not task.series_list:
            empty_label = QLabel("No series information available")
            empty_label.setStyleSheet("color: #64748b; font-size: 11px; padding: 8px;")
            self.series_layout.addWidget(empty_label)
        else:
            # If the whole study is done every series must be done too, even if
            # the main-process state.completed_series list is incomplete (it is
            # populated from the subprocess which cannot write our state store).
            study_fully_complete = state.status == DownloadStatus.COMPLETED

            for series_info in task.series_list:
                is_completed = (
                    study_fully_complete
                    or series_info.series_uid in state.completed_series
                    or series_info.series_uid in state.skipped_series
                )
                is_failed = (not study_fully_complete) and series_info.series_uid in state.failed_series
                is_current = (
                    state.current_series == series_info.series_uid or
                    state.current_series_number == series_info.series_number
                )

                total_images = series_info.image_count
                if is_completed:
                    downloaded_images = total_images
                    series_progress = 100.0
                    status_text = "Completed"
                    status_color = "#10b981"
                elif is_failed:
                    downloaded_images = 0
                    series_progress = 0.0
                    status_text = "Failed"
                    status_color = "#ef4444"
                elif is_current and state.current_series_total > 0:
                    downloaded_images = min(state.current_series_downloaded, state.current_series_total)
                    total_images = state.current_series_total
                    if state.current_series_progress > 0:
                        series_progress = state.current_series_progress
                    else:
                        series_progress = (downloaded_images / total_images * 100) if total_images > 0 else 0.0
                    status_text = "Downloading"
                    status_color = "#06b6d4"
                else:
                    downloaded_images = 0
                    series_progress = 0.0
                    status_text = "Pending"
                    status_color = "#94a3b8"

                remaining_images = max(0, total_images - downloaded_images)

                series_frame = QFrame()
                series_frame.setStyleSheet(f"""
                    QFrame {{
                        background: #111827;
                        border: 1px solid {'#06b6d4' if is_current else '#374151'};
                        border-radius: 6px;
                        padding: 6px;
                    }}
                """)

                frame_layout = QVBoxLayout(series_frame)
                frame_layout.setContentsMargins(8, 6, 8, 6)
                frame_layout.setSpacing(6)

                header_layout = QHBoxLayout()
                series_title = QLabel(
                    f"{series_info.series_number} • {series_info.series_description or 'Series'}"
                )
                series_title.setStyleSheet("color: #e2e8f0; font-size: 11px; font-weight: 600;")

                status_label = QLabel(status_text)
                status_label.setStyleSheet(
                    f"color: {status_color}; font-size: 10px; font-weight: 700;"
                )

                header_layout.addWidget(series_title)
                header_layout.addStretch()
                header_layout.addWidget(status_label)

                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(int(series_progress))
                progress_bar.setTextVisible(True)
                progress_bar.setFormat(
                    f"{series_progress:.1f}% ({downloaded_images}/{total_images} images)"
                )
                progress_bar.setStyleSheet("""
                    QProgressBar {
                        border: 1px solid #374151;
                        border-radius: 4px;
                        background: #0f172a;
                        height: 18px;
                        color: #e2e8f0;
                        font-size: 10px;
                        font-weight: 600;
                    }
                    QProgressBar::chunk {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #06b6d4, stop:1 #0891b2);
                        border-radius: 3px;
                    }
                """)

                counts_label = QLabel(
                    f"Downloaded: {downloaded_images} | Remaining: {remaining_images}"
                )
                counts_label.setStyleSheet("color: #94a3b8; font-size: 10px;")

                frame_layout.addLayout(header_layout)
                frame_layout.addWidget(progress_bar)
                frame_layout.addWidget(counts_label)

                # Check if series_layout still exists before adding widget
                if hasattr(self, 'series_layout') and self.series_layout:
                    self.series_layout.addWidget(series_frame)
                else:
                    logger.warning("📋 [SERIES-BREAKDOWN] series_layout deleted during update, stopping update")
                    break

        # Add stretch only if series_layout still exists
        if hasattr(self, 'series_layout') and self.series_layout:
            self.series_layout.addStretch()

    def _refresh_table_order(self):
        """Refresh table with priority grouping - shows all 4 priority groups.

        G7/G8 — re-entrancy guard + ``[DM_REBUILD]`` instrumentation. The
        guard short-circuits any recursive entry triggered by Qt signals
        fired mid-rebuild (the historical root cause was an unguarded
        ``priority_combo.setCurrentText`` in ``_clear_details_panel``;
        the guard provides defense-in-depth even if a future caller
        re-introduces a similar signal).
        """
        import time as _dm_rebuild_time

        # G8.2 — re-entrancy guard. Without this, an unguarded combo
        # signal mid-rebuild would call us recursively, doubling the
        # widget churn and corrupting state.
        if getattr(self, "_refresh_table_order_in_progress", False):
            try:
                # WARNING level: component=download default threshold is
                # WARNING in diagnostic_logging — INFO would be dropped.
                logger.warning(
                    "[DM_REBUILD] event=reenter_skip depth=%d caller=%s",
                    int(getattr(self, "_dm_rebuild_depth", 0)),
                    self._dm_rebuild_caller_frame(),
                    extra={"component": "download"},
                )
            except Exception:
                pass
            return

        self._refresh_table_order_in_progress = True
        depth = int(getattr(self, "_dm_rebuild_depth", 0)) + 1
        self._dm_rebuild_depth = depth
        rebuild_t0 = _dm_rebuild_time.perf_counter()

        try:
            # WARNING level: see comment in reenter_skip branch.
            logger.warning(
                "[DM_REBUILD] event=enter depth=%d caller=%s",
                depth,
                self._dm_rebuild_caller_frame(),
                extra={"component": "download"},
            )
        except Exception:
            pass

        # finally: suppression flag is always reset at method exit
        self._suppressing_selection_signals = True
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return

            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping refresh")
                return

            logger.debug("🔄 [TABLE-REFRESH] Refreshing table order with priority groups...")

            # Get all downloads grouped by priority
            all_downloads = self.state_store.get_all_downloads()
            logger.debug("🔄 [TABLE-REFRESH] Total downloads in state: %d", len(all_downloads))

            # Group by priority
            priority_groups = {
                "Critical": [],
                "High": [],
                "Normal": [],
                "Low": []
            }

            for state in all_downloads:
                priority_name = state.priority.display_name
                priority_groups[priority_name].append(state)

            # Clear table
            self.download_table.setRowCount(0)
            self.download_rows.clear()
            self._priority_group_widgets.clear()
            self._priority_group_rows.clear()
            self._speed_label_widgets.clear()  # Clear speed label widget references

            row_count = 0
            # Add priority groups to table
            for priority_name in ["Critical", "High", "Normal", "Low"]:
                group_items = priority_groups[priority_name]

                # Skip empty groups if configured (but we show them by default)
                if not group_items and not self._show_empty_groups:
                    continue

                # Add priority group header
                self._add_priority_group_header(priority_name, len(group_items))

                # Add items in this group
                for state in group_items:
                    self._add_download_row_to_table(state)
                    row_count += 1

                # Add spacer after group
                self._add_priority_group_spacer()

            # Restore selection after rebuild (keeps details panel in sync)
            if self._selected_study_uid:
                self._select_study_row(self._selected_study_uid, ensure_visible=False)

            logger.debug("✅ [TABLE-REFRESH] Table order refreshed successfully (%d rows)", row_count)

        except Exception as e:
            logger.error(f"❌ [TABLE-REFRESH] Error refreshing table order: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            self._suppressing_selection_signals = False
            duration_ms = (_dm_rebuild_time.perf_counter() - rebuild_t0) * 1000.0
            try:
                # WARNING level: see comment in reenter_skip branch.
                logger.warning(
                    "[DM_REBUILD] event=exit depth=%d duration_ms=%.3f rows=%d",
                    depth,
                    duration_ms,
                    int(locals().get("row_count", 0)),
                    extra={"component": "download"},
                )
            except Exception:
                pass
            self._dm_rebuild_depth = depth - 1
            self._refresh_table_order_in_progress = False

    @staticmethod
    def _dm_rebuild_caller_frame() -> str:
        """Return the immediate caller's `<file>:<func>` for `[DM_REBUILD]`."""
        try:
            import inspect

            stack = inspect.stack()
            # 0 = this helper, 1 = _refresh_table_order, 2 = real caller
            if len(stack) >= 3:
                frame = stack[2]
                fn = frame.function
                fname = frame.filename.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
                return f"{fname}:{fn}"
        except Exception:
            pass
        return "unknown"

    def _add_priority_group_header(self, priority_name: str, count: int):
        """Add priority group header to table"""
        # ✅ WIDGET VALIDITY: Check if table still exists before accessing
        if not self.download_table or not hasattr(self, 'download_table'):
            logger.debug("⚠️ download_table not available (widget may be deleted)")
            return
        
        # Additional check: verify widget is not deleted
        try:
            _ = self.download_table.rowCount()  # Try to access a property
        except RuntimeError:
            logger.debug("⚠️ download_table deleted, skipping header add")
            return
        
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)
        
        # Map priority name to enum
        priority_map = {
            "Critical": DownloadPriority.CRITICAL,
            "High": DownloadPriority.HIGH,
            "Normal": DownloadPriority.NORMAL,
            "Low": DownloadPriority.LOW
        }
        priority = priority_map.get(priority_name, DownloadPriority.NORMAL)
        
        # Create header widget
        header_widget = PriorityGroupHeader(priority, count)
        header_widget.collapsed_changed.connect(self._on_group_collapsed)
        
        # Store reference
        self._priority_group_widgets[priority_name] = header_widget
        self._priority_group_rows[priority_name] = row
        
        # Add to table (span all columns)
        self.download_table.setCellWidget(row, 0, header_widget)
        self.download_table.setSpan(row, 0, 1, 7)
        
        # Set row height
        self.download_table.setRowHeight(row, 60)

    def _add_priority_group_spacer(self):
        """Add visual spacer after priority group"""
        # ✅ WIDGET VALIDITY: Check if table still exists before accessing
        if not self.download_table or not hasattr(self, 'download_table'):
            logger.debug("⚠️ download_table not available (widget may be deleted)")
            return
        
        # Additional check: verify widget is not deleted
        try:
            _ = self.download_table.rowCount()  # Try to access a property
        except RuntimeError:
            logger.debug("⚠️ download_table deleted, skipping spacer add")
            return
        
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)
        
        spacer = QFrame()
        spacer.setFixedHeight(4)
        spacer.setStyleSheet("background: transparent;")
        
        self.download_table.setCellWidget(row, 0, spacer)
        self.download_table.setSpan(row, 0, 1, 7)
        self.download_table.setRowHeight(row, 4)

    def _on_group_collapsed(self, priority_name: str, is_collapsed: bool):
        """Handle priority group collapse/expand"""
        if is_collapsed:
            self._collapsed_groups.add(priority_name)
        else:
            self._collapsed_groups.discard(priority_name)
        
        # Refresh table to show/hide items
        self._refresh_table_order()

    def _add_download_row_to_table(self, state: DownloadState):
        """Add a download row to the table"""
        # ✅ WIDGET VALIDITY: Check if table still exists before accessing
        if not self.download_table or not hasattr(self, 'download_table'):
            logger.debug("⚠️ download_table not available (widget may be deleted)")
            return

        # Additional check: verify widget is not deleted
        try:
            _ = self.download_table.rowCount()  # Try to access a property
        except RuntimeError:
            logger.debug("⚠️ download_table deleted, skipping row add")
            return

        # Skip if group is collapsed
        priority_name = state.priority.display_name
        if priority_name in self._collapsed_groups:
            logger.info(f"⏭️ [ROW-ADD] Skipping row for {state.patient_name} - group {priority_name} is collapsed")
            return

        from ..components.download_row import DownloadRowWidget
        from ..components.action_buttons import ActionButtons

        row = self.download_table.rowCount()
        self.download_table.insertRow(row)

        logger.info(f"📥 [ROW-ADD] Adding row {row} for {state.patient_name} ({state.study_uid[:40]}...)")

        task = self._tasks.get(state.study_uid)

        # Store row index
        self.download_rows[state.study_uid] = row
        logger.info(f"📥 [ROW-ADD] Stored in download_rows: {state.study_uid[:40]}... → row {row}")

        # Populate row
        status_badge = StatusBadge(state.status)
        status_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.download_table.setCellWidget(row, 0, status_badge)
        patient_item = QTableWidgetItem(state.patient_name or '')
        patient_item.setData(Qt.UserRole, state.study_uid)
        self.download_table.setItem(row, 1, patient_item)
        self.download_table.setItem(row, 2, QTableWidgetItem(task.modality if task else ''))

        progress_widget = QProgressBar()
        progress_widget.setRange(0, 100)
        progress_widget.setValue(int(state.progress_percent))
        progress_widget.setTextVisible(True)
        progress_widget.setAlignment(Qt.AlignCenter)
        progress_widget.setFormat(
            f"{state.progress_percent:.1f}% ({state.downloaded_count}/{state.total_count} images)"
        )
        progress_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        progress_widget.setStyleSheet("""
            QProgressBar {
                border: 1px solid #374151;
                border-radius: 4px;
                background: #111827;
                height: 22px;
                color: #e2e8f0;
                font-weight: 600;
                font-size: 12px;
                text-align: center;
                padding: 0px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #06b6d4, stop:1 #0891b2);
                border-radius: 3px;
            }
        """)
        self.download_table.setCellWidget(row, 3, progress_widget)
        
        # Speed - use QLabel widget so we can update it dynamically
        speed_label = QLabel("0 KB/s")
        speed_label.setAlignment(Qt.AlignCenter)
        speed_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 11px;
                font-family: 'Consolas', monospace;
                background: transparent;
            }
        """)
        self.download_table.setCellWidget(row, 4, speed_label)
        
        # Store speed label reference for later updates
        self._speed_label_widgets[state.study_uid] = speed_label

        # Priority column — colored label so each tier is visually distinct
        priority_label = QLabel(state.priority.display_name)
        priority_label.setAlignment(Qt.AlignCenter)
        priority_label.setStyleSheet(f"""
            QLabel {{
                color: {state.priority.color_hex};
                font-weight: 700;
                font-size: 11px;
                background: transparent;
                padding: 2px 4px;
            }}
        """)
        priority_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.download_table.setCellWidget(row, 5, priority_label)
        logger.info(f"📥 [ROW-ADD] Populated all cells for row {row}")

        # Add action buttons
        action_buttons = ActionButtons(state)
        action_buttons.pause_clicked.connect(self._on_per_patient_pause)
        action_buttons.resume_clicked.connect(self._on_per_patient_resume)
        action_buttons.cancel_clicked.connect(self._on_per_patient_cancel)
        action_buttons.retry_clicked.connect(self._on_per_patient_retry)

        action_container = QWidget()
        action_layout = QHBoxLayout(action_container)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setAlignment(Qt.AlignCenter)
        action_layout.addWidget(action_buttons)
        self.download_table.setCellWidget(row, 6, action_container)

        self.download_table.setRowHeight(row, 52)

        logger.info(f"✅ [ROW-ADD] Row {row} fully added for {state.patient_name}")
        
        # Log database information for this row
        logger.info(f"💾 [DATABASE] Row added for study {state.study_uid[:40]}... with status {state.status.value}, priority {state.priority.display_name}")
