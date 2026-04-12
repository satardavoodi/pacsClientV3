"""Download queue: add/update/remove rows, progress bars, badges"""
# Auto-generated from main_widget.py — Phase 2 split



import logging

from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QLabel, QSplitter, QFrame, QHeaderView, QAbstractItemView, QGroupBox, QScrollArea, QProgressBar, QComboBox, QTextEdit

from ...core.enums import DownloadPriority, DownloadStatus
from ...core.models import DownloadTask, DownloadState
from ..components.status_badge import StatusBadge
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class _DMQueueMixin:
    """Download queue: add/update/remove rows, progress bars, badges"""

    def add_downloads(self, studies: List[Dict], start_immediately: bool = False) -> None:
        """
        Add downloads to queue

        Args:
            studies: List of study dicts
            start_immediately: Start downloads immediately
        """
        logger.info("=" * 100)
        logger.info(f"📥 add_downloads() called with {len(studies)} studies")
        logger.info(f"Start immediately: {start_immediately}")
        logger.info("=" * 100)

        added_studies = []
        skipped_studies = []

        for i, study_data in enumerate(studies):
            patient_name = study_data.get('patient_name', 'Unknown')
            patient_id = study_data.get('patient_id', 'Unknown')
            study_uid = study_data.get('study_uid', 'No UID')
            series_count = len(study_data.get('series', []))
            
            logger.info("-" * 100)
            logger.info(f"📥 [DOWNLOAD-{i+1}/{len(studies)}] Adding new download")
            logger.info(f"   🧍 Patient Name: {patient_name}")
            logger.info(f"   🆔 Patient ID: {patient_id}")
            logger.info(f"   📄 Study UID: {study_uid[:60]}...")
            logger.info(f"   📁 Series Count: {series_count}")
            logger.info(f"   📅 Study Date: {study_data.get('study_date', 'Unknown')}")
            logger.info(f"   🏥 Modality: {study_data.get('modality', 'Unknown')}")
            logger.info(f"   📝 Description: {study_data.get('study_description', 'Unknown')}")
            try:
                # Create download task
                task = self._create_task_from_dict(study_data)

                # Check for duplicates
                existing = self.state_store.get(task.study_uid)
                if existing:
                    reason = f"Download already exists (Status: {existing.status.value})"
                    logger.warning(f"⚠️ {reason}: {task.study_uid[:40]}...")
                    skipped_studies.append((task.study_uid, task.patient_name, reason))
                    continue

                # Validate
                can_add = self.rule_engine.can_add_download(task)
                if not can_add.allowed:
                    reason = can_add.reason or "Validation failed"
                    logger.warning(f"⚠️ Cannot add: {reason}")
                    skipped_studies.append((task.study_uid, task.patient_name, reason))
                    continue

                # Store the task for later use (worker creation)
                self._tasks[task.study_uid] = task

                # Add to state store (observers auto-notify)
                state = self.state_store.create(task)
                added_studies.append(task.study_uid)

                logger.info(f"   ✅ Successfully added to queue")
                logger.info(f"   💾 Saved to database with status: {state.status.value}")
                logger.info(f"   ⭐ Priority: {state.priority.display_name}")
                logger.info(f"   📊 Total Images: {task.total_image_count}")

            except Exception as e:
                logger.error(f"   ❌ Error adding download: {e}")
                skipped_studies.append((study_uid, patient_name, str(e)))
                import traceback
                traceback.print_exc()

        logger.info("-" * 100)
        logger.info(f"✅ BATCH SUMMARY: Added {len(added_studies)} studies to download queue")
        for idx, uid in enumerate(added_studies, 1):
            task = self._tasks.get(uid)
            if task:
                logger.info(f"   {idx}. {task.patient_name} ({uid[:40]}...)")
        if skipped_studies:
            logger.info("-" * 100)
            logger.info(f"⚠️ SKIPPED SUMMARY: {len(skipped_studies)} studies were not added")
            for idx, (uid, name, reason) in enumerate(skipped_studies, 1):
                logger.info(f"   {idx}. {name} ({uid[:40]}...) - {reason}")
        logger.info("=" * 100)

        # FIX: Fetch reception data for ALL added studies with delays
        # ReceptionDataService only supports one request at a time (cancels previous ones)
        # So we need to space out the requests with delays
        logger.info("=" * 100)
        logger.info(f"📡 [RECEPTION-FETCH-ALL] Fetching reception data for {len(added_studies)} added studies...")
        logger.info(f"   ⏱️ Using staggered delays to prevent request cancellation")
        logger.info("=" * 100)
        for idx, study_uid in enumerate(added_studies, 1):
            task = self._tasks.get(study_uid)
            if task and task.patient_id:
                # Calculate delay: 0ms for first, 200ms for second, 400ms for third, etc.
                delay_ms = (idx - 1) * 200
                logger.info(f"   📡 [{idx}/{len(added_studies)}] Scheduling fetch for: {task.patient_name} (delay: {delay_ms}ms)")
                
                # Use QTimer.singleShot to delay each request
                # Create a proper function to handle cache check and fetch
                def delayed_fetch(patient_id, study_uid, patient_name):
                    logger.info(f"   🚀 Checking cache for: {patient_name} (Patient ID: {patient_id})")
                    if patient_id not in self._reception_cache:
                        logger.info(f"   📡 Not in cache, fetching from server...")
                        self._load_reception_data(patient_id, study_uid)
                    else:
                        logger.info(f"   ✅ Already in cache, skipping fetch")
                
                QTimer.singleShot(
                    delay_ms,
                    lambda pid=task.patient_id, suid=study_uid, name=task.patient_name: delayed_fetch(pid, suid, name)
                )
            else:
                logger.warning(f"   ⚠️ [{idx}/{len(added_studies)}] No patient_id for {study_uid[:40]}..., skipping")
        logger.info("=" * 100)

        # Start downloads if requested
        if start_immediately and added_studies:
            logger.info(f"▶ Auto-starting {len(added_studies)} downloads")
            for study_uid in added_studies:
                if self.worker_pool.can_add_worker():
                    logger.info(f"🚀 Starting download worker for {study_uid[:40]}...")
                    self._start_download_worker(study_uid)
                    # Log to UI
                    task = self._tasks.get(study_uid)
                    if task:
                        self.log_message(f"🚀 Started download: {task.patient_name} (Study: {study_uid[:10]}...)")
                else:
                    logger.info(f"⏳ Worker pool full, {study_uid[:40]}... will start when slot available")
                    break

        # Auto-select the most recently added study to sync details panel
        if added_studies:
            last_added_uid = added_studies[-1]
            self._selected_study_uid = last_added_uid
            logger.info(f"🔍 Auto-selecting study {last_added_uid[:40]}... in details panel")
            QTimer.singleShot(0, lambda: self._select_study_row(last_added_uid))

        self._update_status_label()

        # Log all studies after adding new ones
        logger.info(f"📊 [ADDED_DOWNLOADS] After adding {len(studies)} studies:")
        logger.info(f"📊 [ADDED_DOWNLOADS] Total studies in queue: {len(self._tasks)}")
        for idx, (study_uid, task) in enumerate(self._tasks.items()):
            state = self.state_store.get(study_uid)
            status = getattr(state, 'status', 'Unknown') if state else 'Unknown'
            logger.info(f"📊 [ADDED_DOWNLOADS] Study {idx+1}: {task.patient_name} (UID: {study_uid[:20]}...) - Status: {status}")

    def _create_task_from_dict(self, data: Dict) -> DownloadTask:
        """Create DownloadTask from dict - extracts and converts series information"""
        from ...core.models import SeriesInfo
        
        # Extract series list from study data
        study_uid = data.get('study_uid', '')
        series_dicts = data.get('series', [])
        
        # Debug logging
        logger.info(f"📋 Creating task for {data.get('patient_name', 'Unknown')}")
        logger.info(f"   Study UID: {data.get('study_uid', '')[:40]}...")
        logger.info(f"   Series in data: {len(series_dicts)} series")
        
        # Convert series dicts to SeriesInfo objects
        series_list = []
        for series_dict in series_dicts:
            try:
                series_info = SeriesInfo(
                    series_uid=series_dict.get('series_uid', ''),
                    series_number=str(series_dict.get('series_number', '')),
                    series_description=series_dict.get('series_description', ''),
                    modality=series_dict.get('modality', ''),
                    image_count=int(series_dict.get('image_count', 0)),
                    protocol_name=series_dict.get('protocol_name'),
                    body_part_examined=series_dict.get('body_part_examined'),
                    manufacturer=series_dict.get('manufacturer'),
                    institution_name=series_dict.get('institution_name'),
                    thumbnail_data=series_dict.get('thumbnail_data'),
                    thumbnail_path=series_dict.get('thumbnail_path')
                )
                series_list.append(series_info)
                logger.debug(f"   ✅ Converted series: {series_info.series_description} ({series_info.image_count} images)")
            except Exception as e:
                logger.error(f"   ❌ Error converting series: {e}")
                continue
        
        # Order series by numeric series_number when possible to keep download order consistent
        if series_list:
            def _series_sort_key(item):
                raw = str(item.series_number) if item.series_number is not None else ""
                if raw.isdigit():
                    return (0, int(raw), raw)
                return (1, raw)

            series_list = sorted(series_list, key=_series_sort_key)

        # If no series after conversion, log warning
        if not series_list:
            logger.warning(f"⚠️ No valid series for {data.get('patient_name', 'Unknown')} - validation will fail!")
            logger.warning(f"   Available keys in data: {list(data.keys())}")
            if series_dicts:
                logger.warning(f"   Raw series data (first): {series_dicts[0] if series_dicts else 'None'}")
        else:
            logger.info(f"   ✅ Converted {len(series_list)} series successfully")
        
        # Extract comprehensive patient information
        patient_age = data.get('patient_age', data.get('age', ''))
        patient_sex = data.get('patient_sex', data.get('sex', ''))
        patient_birth_date = data.get('patient_birth_date', data.get('birth_date', ''))
        study_time = data.get('study_time', data.get('time', ''))
        body_part = data.get('body_part', data.get('body_part_examined', ''))
        modality = data.get('modality', '')
        
        logger.info(f"📋 [PATIENT-INFO] Extracted comprehensive patient data:")
        logger.info(f"📋 [PATIENT-INFO]   Patient ID: {data.get('patient_id', '')}")
        logger.info(f"📋 [PATIENT-INFO]   Patient Name: {data.get('patient_name', '')}")
        logger.info(f"📋 [PATIENT-INFO]   Patient Age: {patient_age}")
        logger.info(f"📋 [PATIENT-INFO]   Patient Sex: {patient_sex}")
        logger.info(f"📋 [PATIENT-INFO]   Patient Birth Date: {patient_birth_date}")
        logger.info(f"📋 [PATIENT-INFO]   Study Date: {data.get('study_date', '')}")
        logger.info(f"📋 [PATIENT-INFO]   Study Time: {study_time}")
        logger.info(f"📋 [PATIENT-INFO]   Body Part: {body_part}")
        logger.info(f"📋 [PATIENT-INFO]   Description: {data.get('study_description', '')}")
        logger.info(f"📋 [PATIENT-INFO]   Modality: {modality}")

        # Create DownloadTask with all patient information
        task = DownloadTask(
            study_uid=study_uid,
            patient_id=data.get('patient_id', ''),
            patient_name=data.get('patient_name', ''),
            study_date=data.get('study_date', ''),
            modality=modality,
            description=data.get('study_description', ''),
            series_list=series_list,
            output_dir=(self.base_output_dir / study_uid) if study_uid else None,
            # Complete patient information
            patient_age=patient_age,
            patient_sex=patient_sex,
            patient_birth_date=patient_birth_date,
            study_time=study_time,
            body_part=body_part
        )
        
        # Store the additional information in the _tasks dictionary alongside the task
        # This avoids frozen dataclass issues while keeping the information accessible
        try:
            # Store in a separate dictionary to avoid frozen dataclass issues
            if not hasattr(self, '_additional_task_info'):
                self._additional_task_info = {}
            self._additional_task_info[study_uid] = {
                'patient_age': patient_age,
                'patient_sex': patient_sex,
                'patient_birth_date': patient_birth_date,
                'study_time': study_time,
                'body_part': body_part,
                'modality': modality  # Add modality to additional info too
            }
        except Exception as e:
            logger.warning(f"⚠️ [PATIENT-INFO] Could not store additional info for {study_uid[:40]}...: {e}")
        
        return task

    def add_download_row(self, study_uid: str, state: DownloadState) -> None:
        """Add download row to table (called by UIObserver) - triggers full refresh"""
        logger.debug(f"📥 add_download_row called for {study_uid[:40]}...")
        # Instead of adding individual rows, refresh the entire table with priority grouping
        QTimer.singleShot(0, self._refresh_table_order)

    def update_progress_bar(self, study_uid: str, progress: float) -> None:
        """Update progress (called by UIObserver)"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_update_progress_bar(study_uid, progress))

    def _get_series_image_count_map(self, study_uid: str) -> Dict[str, int]:
        """Get cached map of series_number -> image_count for a study."""
        if study_uid in self._series_image_count_cache:
            return self._series_image_count_cache[study_uid]

        task = self._tasks.get(study_uid)
        if not task:
            return {}

        series_map = {}
        for series in task.series_list:
            image_count = int(series.image_count or 0)
            if series.series_number:
                series_map[str(series.series_number)] = image_count
            if series.series_uid:
                series_map[str(series.series_uid)] = image_count
        self._series_image_count_cache[study_uid] = series_map
        return series_map

    def _calculate_overall_progress(
        self,
        study_uid: str,
        series_number: str,
        series_done: int,
        series_total: int
    ) -> tuple[int, int, float]:
        """
        Calculate overall progress across all images.

        Uses completed/skipped series plus current series progress.
        Returns (overall_downloaded, overall_total, overall_percent).
        """
        task = self._tasks.get(study_uid)
        total_images = task.total_image_count if task else 0

        state = self.state_store.get(study_uid)
        completed_series = set()
        if state:
            completed_series.update(state.completed_series or [])
            completed_series.update(state.skipped_series or [])

        series_map = self._get_series_image_count_map(study_uid)
        if total_images <= 0 and series_map:
            total_images = sum(series_map.values())
        if total_images <= 0 and series_total > 0:
            total_images = series_total

        completed_images = 0
        if series_map and completed_series:
            completed_images = sum(
                series_map.get(str(series_id), 0) for series_id in completed_series
            )

        # Avoid double-counting if current series already completed
        current_done = 0 if str(series_number) in completed_series else series_done

        overall_downloaded = completed_images + current_done
        overall_total = max(total_images, 0)
        overall_percent = (overall_downloaded / overall_total * 100) if overall_total > 0 else 0.0
        if overall_percent < 0:
            overall_percent = 0.0
        elif overall_percent > 100:
            overall_percent = 100.0

        return overall_downloaded, overall_total, overall_percent

    def _do_update_progress_bar(self, study_uid: str, progress: float) -> None:
        """Actually update progress bar (runs in main thread)"""
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return
            
            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping progress update")
                return
            
            state = self.state_store.get(study_uid)
            if not state:
                logger.warning(f"No state found for {study_uid}")
                return

            row = self.download_rows.get(study_uid)
            task = self._tasks.get(study_uid)

            display_total = state.total_count or (task.total_image_count if task else 0)
            display_downloaded = state.downloaded_count
            display_percent = state.progress_percent
            if display_percent <= 0 and display_total > 0 and display_downloaded > 0:
                display_percent = (display_downloaded / display_total) * 100
            if display_percent < 0:
                display_percent = 0.0
            elif display_percent > 100:
                display_percent = 100.0
            
            # Update table progress bar
            try:
                if row is not None:
                    progress_widget = self.download_table.cellWidget(row, 3)
                    if progress_widget and isinstance(progress_widget, QProgressBar):
                        progress_widget.setValue(int(display_percent))
                        progress_widget.setFormat(
                            f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
                        )
                    else:
                        self.download_table.setItem(
                            row,
                            3,
                            QTableWidgetItem(f"{display_percent:.1f}%")
                        )
            except Exception as e:
                logger.error(f"Error updating table progress: {e}")
            
            # Update details panel if this is the selected download (INLINE - NO nested QTimer)
            try:
                if study_uid == self._selected_study_uid:
                    self.progress_bar.setValue(int(display_percent))
                    self.progress_bar.setFormat(
                        f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
                    )
                    self.progress_label.setText(
                        f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
                    )
            except Exception as e:
                logger.error(f"Error updating details panel progress: {e}")
        
        except Exception as e:
            logger.error(f"❌ Error in progress bar update: {e}", exc_info=True)

    def update_status_badge(self, study_uid: str, status: DownloadStatus) -> None:
        """Update status (called by UIObserver)"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_update_status_badge(study_uid, status))

    def _do_update_status_badge(self, study_uid: str, status: DownloadStatus) -> None:
        """Actually update status (runs in main thread)"""
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return
            
            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping status update")
                return
            
            if study_uid not in self.download_rows:
                logger.warning(f"study_uid {study_uid} not in download_rows during status update")
                return
            
            row = self.download_rows[study_uid]
            
            # Update status in table
            status_widget = self.download_table.cellWidget(row, 0)
            if isinstance(status_widget, StatusBadge):
                status_widget.update_status(status)
            else:
                self.download_table.setItem(row, 0, QTableWidgetItem(status.value))
            
            # INLINE: Update action buttons (NO nested QTimer call)
            try:
                action_buttons = self.download_table.cellWidget(row, 6)  # Column 6 for Actions
                if action_buttons:
                    state = self.state_store.get(study_uid)
                    if state and hasattr(action_buttons, 'update_state'):
                        action_buttons.update_state(state)
            except Exception as e:
                logger.error(f"Error updating action buttons: {e}")
            
            # INLINE: Update details panel (NO nested QTimer call)
            try:
                if study_uid == self._selected_study_uid:
                    state = self.state_store.get(study_uid)
                    if state:
                        task = self._tasks.get(study_uid)
                        self.patient_name_label.setText(state.patient_name or 'N/A')
                        self.patient_id_label.setText(task.patient_id if task else 'N/A')
            except Exception as e:
                logger.error(f"Error updating details panel: {e}")
        
        except Exception as e:
            logger.error(f"❌ Error in status badge update: {e}", exc_info=True)

    def update_priority_badge(self, study_uid: str, priority: DownloadPriority) -> None:
        """Update priority (called by UIObserver) - triggers full refresh"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_update_priority_badge(study_uid, priority))

    def _do_update_priority_badge(self, study_uid: str, priority: DownloadPriority) -> None:
        """Actually update priority badge (runs in main thread)"""
        try:
            logger.debug(f"📊 update_priority_badge for {study_uid[:40]}... → {priority.display_name}")
            
            # INLINE: Refresh table order immediately (NO nested QTimer)
            try:
                if hasattr(self, '_refresh_table_order_inline'):
                    self._refresh_table_order_inline()
                else:
                    self._refresh_table_order()
            except Exception as e:
                logger.error(f"Error refreshing table order: {e}")
            
            # INLINE: Update details panel (NO nested QTimer)
            try:
                if study_uid == self._selected_study_uid:
                    if hasattr(self, 'priority_combo'):
                        self.priority_combo.blockSignals(True)
                        self.priority_combo.setCurrentText(priority.display_name)
                        self.priority_combo.blockSignals(False)
            except Exception as e:
                logger.error(f"Error updating priority combo: {e}")
        
        except Exception as e:
            logger.error(f"❌ Error in priority badge update: {e}", exc_info=True)

    def update_current_series(self, study_uid: str) -> None:
        """Update current series (called by UIObserver)"""
        state = self.state_store.get(study_uid)
        task = self._tasks.get(study_uid)
        if not state or not task:
            return

        if study_uid == self._selected_study_uid:
            # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._update_series_breakdown_from_task(task, state))

    def update_action_buttons(self, study_uid: str, status: DownloadStatus) -> None:
        """Update action buttons based on status"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_update_action_buttons(study_uid, status))

    def _do_update_action_buttons(self, study_uid: str, status: DownloadStatus) -> None:
        """Actually update action buttons (runs in main thread)"""
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return
            
            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping action buttons update")
                return
            
            if study_uid not in self.download_rows:
                return
            
            row = self.download_rows[study_uid]
            action_buttons = self.download_table.cellWidget(row, 6)  # Column 6 for Actions
            
            if action_buttons:
                # Get updated state
                state = self.state_store.get(study_uid)
                if state:
                    if hasattr(action_buttons, 'update_state'):
                        action_buttons.update_state(state)
        
        except Exception as e:
            logger.error(f"❌ Error in action buttons update: {e}", exc_info=True)

    def remove_download_row(self, study_uid: str) -> None:
        """Remove download row (called by UIObserver) - triggers full refresh"""
        logger.debug(f"🗑️ remove_download_row for {study_uid[:40]}...")
        
        # Clean up speed label widget reference
        if study_uid in self._speed_label_widgets:
            del self._speed_label_widgets[study_uid]
        
        # Refresh entire table to maintain priority grouping
        QTimer.singleShot(0, self._refresh_table_order)
        
        # Clear details if this was the selected download
        if study_uid == self._selected_study_uid:
            self._selected_study_uid = None
            self._clear_details_panel()

    def refresh_table_order(self) -> None:
        """Public method to refresh table order - delegates to _refresh_table_order"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._refresh_table_order)

    def _rebuild_row_index(self) -> None:
        """Rebuild row index after row removal"""
        new_index = {}
        for row in range(self.download_table.rowCount()):
            # Find study_uid for this row
            for study_uid, row_idx in self.download_rows.items():
                if row_idx == row:
                    new_index[study_uid] = row
                    break
        
        self.download_rows = new_index

    def _get_study_uid_for_row(self, row: int) -> Optional[str]:
        """Get study_uid for a given table row using item data first."""
        if row is None or row < 0:
            return None

        try:
            item = self.download_table.item(row, 1)
            if item:
                uid = item.data(Qt.UserRole)
                if uid:
                    return uid
        except Exception:
            pass

        for uid, row_idx in self.download_rows.items():
            if row_idx == row:
                return uid
        return None

    def _find_row_for_study_uid(self, study_uid: str) -> Optional[int]:
        """Find table row index for a study_uid."""
        if not study_uid:
            return None

        try:
            for row in range(self.download_table.rowCount()):
                item = self.download_table.item(row, 1)
                if item and item.data(Qt.UserRole) == study_uid:
                    return row
        except Exception:
            pass

        return self.download_rows.get(study_uid)

    def _update_status_label(self) -> None:
        """Update status label with statistics"""
        stats = self.state_store.get_statistics()
        
        text = (
            f"Total: {stats['total']} | "
            f"Active: {stats['active']} | "
            f"Downloading: {stats['downloading']}"
        )
        
        if self.status_summary:
            self.status_summary.setText(text)
