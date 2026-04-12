"""Per-patient/series retry: non-blocking pause, resume, cancel, retry"""
# Auto-generated from main_widget.py — Phase 2 split



import logging
import threading

from PySide6.QtCore import Signal, Qt, QTimer

from ...core.enums import DownloadPriority, DownloadStatus
from dataclasses import replace
from pathlib import Path

logger = logging.getLogger(__name__)

class _DMRetryMixin:
    """Per-patient/series retry: non-blocking pause, resume, cancel, retry"""

    def _on_per_patient_pause(self, study_uid: str) -> None:
        """
        Per-patient Pause - Pause specific download

        Args:
            study_uid: Study UID to pause
        """
        logger.info(f"⏸️ Per-patient PAUSE clicked for {study_uid[:40]}...")

        try:
            # Check current state before pausing
            state = self.state_store.get(study_uid)
            if state:
                logger.info(f"📊 Current state before pause: {state.status.value}, Priority: {state.priority.display_name}")

            # Only pause if the download is currently active
            if state and state.status in [DownloadStatus.PENDING, DownloadStatus.VALIDATING, DownloadStatus.DOWNLOADING]:
                # Update state to PAUSED first to prevent race conditions
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.PAUSED,
                    is_auto_paused=False
                )
                logger.info(f"💾 Database update: {study_uid[:40]}... status changed to PAUSED")
                logger.info(f"✅ State updated to PAUSED for {study_uid[:40]}...")

                # Then stop the worker for this specific study
                logger.info(f"🛑 Stopping worker for study: {study_uid[:40]}...")
                worker_stopped = self.worker_pool.stop_worker(study_uid)

                if worker_stopped:
                    logger.info(f"✅ Worker stopped for {study_uid[:40]}...")
                else:
                    logger.info(f"ℹ️ No active worker found for {study_uid[:40]}... (may not be running)")
            else:
                logger.info(f"ℹ️ Study {study_uid[:40]}... is not in active state, cannot pause (current: {state.status.value if state else 'Unknown'})")

            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after pause for {study_uid[:40]}...")
            self._refresh_table_order()

            # Update button states after status change
            updated_state = self.state_store.get(study_uid)
            if updated_state and self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating button states for paused study {study_uid[:40]}...")
                self._update_button_states(updated_state)

            # Update the details panel to reflect the new status
            if self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating details panel for paused study {study_uid[:40]}...")
                QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))

            # Start next pending if available
            logger.info(f"🔄 Checking for next pending download after pause...")
            self._start_next_pending()
            logger.info(f"🟢 [OPERATION SUCCESS] Per-patient pause completed for {study_uid[:40]}...")

        except Exception as e:
            logger.error(f"❌ Error in per-patient pause: {e}")
            logger.error(f"🔴 [OPERATION FAILURE] Per-patient pause failed for {study_uid[:40]}...: {e}")
            import traceback
            traceback.print_exc()

    def _on_per_patient_resume(self, study_uid: str) -> None:
        """
        Per-patient Resume - Resume specific download

        Args:
            study_uid: Study UID to resume
        """
        logger.info(f"▶ Per-patient RESUME clicked for {study_uid[:40] if study_uid else 'None'}...")

        try:
            # Check state
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"❌ State not found for {study_uid[:40] if study_uid else 'None'}...")
                return

            logger.info(f"📊 Current state before resume: {state.status.value}, Priority: {state.priority.display_name}")

            # Update state to PENDING (only if currently paused or failed)
            if state.status in [DownloadStatus.PAUSED, DownloadStatus.FAILED, DownloadStatus.CANCELLED]:
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.PENDING,
                    error_message=None,
                    is_auto_paused=False
                )

                logger.info(f"💾 Database update: {study_uid[:40] if study_uid else 'None'}... status changed to PENDING")

                # Start the download worker
                logger.info(f"🚀 Starting download worker for resumed study: {study_uid[:40] if study_uid else 'None'}...")
                self._start_download_worker(study_uid)
            elif state.status == DownloadStatus.COMPLETED:
                # For COMPLETED (terminal state), use force reset
                logger.info(f"💾 Force resetting COMPLETED download: {study_uid[:40] if study_uid else 'None'}...")
                self.state_store.reset(study_uid)
                logger.info(f"💾 Database update: {study_uid[:40] if study_uid else 'None'}... status reset to PENDING")

                # Start the download worker
                logger.info(f"🚀 Starting download worker for reset study: {study_uid[:40] if study_uid else 'None'}...")
                self._start_download_worker(study_uid)
            else:
                logger.info(f"ℹ️ Study {study_uid[:40] if study_uid else 'None'}... is not in a resumable state: {state.status.value}")

            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after resume for {study_uid[:40] if study_uid else 'None'}...")
            self._refresh_table_order()

            # Update button states after status change
            updated_state = self.state_store.get(study_uid)
            if updated_state and self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating button states for resumed study {study_uid[:40] if study_uid else 'None'}...")
                self._update_button_states(updated_state)

            # Update the details panel to reflect the new status
            if self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating details panel for resumed study {study_uid[:40] if study_uid else 'None'}...")
                QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))

            logger.info(f"✅ Resume initiated for {study_uid[:40] if study_uid else 'None'}...")
            logger.info(f"🟢 [OPERATION SUCCESS] Per-patient resume completed for {study_uid[:40] if study_uid else 'None'}...")

        except Exception as e:
            logger.error(f"❌ Error in per-patient resume: {e}")
            logger.error(f"🔴 [OPERATION FAILURE] Per-patient resume failed for {study_uid[:40] if study_uid else 'None'}...: {e}")
            import traceback
            traceback.print_exc()

    def _on_per_patient_cancel(self, study_uid: str) -> None:
        """
        Per-patient Cancel - Cancel specific download

        Args:
            study_uid: Study UID to cancel
        """
        logger.info(f"❌ Per-patient CANCEL clicked for {study_uid[:40] if study_uid else 'None'}...")

        try:
            # Check current state before cancelling
            state = self.state_store.get(study_uid)
            if state:
                logger.info(f"📊 Current state before cancel: {state.status.value}, Priority: {state.priority.display_name}")

            # Stop the worker
            logger.info(f"🛑 Stopping worker for study: {study_uid[:40] if study_uid else 'None'}...")
            self.worker_pool.stop_worker(study_uid)

            # Update state to CANCELLED
            state = self.state_store.get(study_uid)
            if state:
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.CANCELLED
                )
                logger.info(f"💾 Database update: {study_uid[:40] if study_uid else 'None'}... status changed to CANCELLED")
                logger.info(f"✅ Download cancelled for {study_uid[:40] if study_uid else 'None'}...")
            else:
                logger.warning(f"⚠️ State not found for {study_uid[:40] if study_uid else 'None'}... during cancel")

            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after cancel for {study_uid[:40] if study_uid else 'None'}...")
            self._refresh_table_order()

            # Update button states after status change
            updated_state = self.state_store.get(study_uid)
            if updated_state and self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating button states for cancelled study {study_uid[:40] if study_uid else 'None'}...")
                self._update_button_states(updated_state)

            # Update details panel if this study is selected
            if self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating details panel after cancel {study_uid[:40] if study_uid else 'None'}...")
                QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))

            # Start next pending
            logger.info(f"🔄 Checking for next pending download after cancel...")
            self._start_next_pending()
            logger.info(f"🟢 [OPERATION SUCCESS] Per-patient cancel completed for {study_uid[:40] if study_uid else 'None'}...")

        except Exception as e:
            logger.error(f"❌ Error in per-patient cancel: {e}")
            logger.error(f"🔴 [OPERATION FAILURE] Per-patient cancel failed for {study_uid[:40] if study_uid else 'None'}...: {e}")
            import traceback
            traceback.print_exc()

    def _on_series_retry(self, study_uid: str, series_number: str = None, series_uid: str = None) -> None:
        """
        Per-series Retry - Retry download for a specific series only.

        Heavy I/O (file deletion, gRPC metadata fetch) is offloaded to a
        background thread so the Qt event loop is never blocked.

        Args:
            study_uid: Study UID
            series_number: Series number to retry
            series_uid: Series UID to retry (optional)
        """
        logger.info(f"🔄🔄 [SERIES RETRY] Series-specific retry requested")
        logger.info(f"   Study UID: {study_uid[:40] if study_uid else 'None'}")
        logger.info(f"   Series Number: {series_number}")
        logger.info(f"   Series UID: {series_uid[:40] if series_uid else 'None'}")

        try:
            # ──────────────────────────────────────────────────────────
            # FAST PATH — runs on the main Qt thread (no blocking I/O)
            # ──────────────────────────────────────────────────────────

            # Check state
            state = self.state_store.get(study_uid)
            if not state:
                logger.warning(f"⚠️ [SERIES RETRY] State not found in store for study {study_uid[:40]}")
                logger.info(f"ℹ️ [SERIES RETRY] Attempting to auto-create state from database...")

                try:
                    from PacsClient.utils.db_manager import get_study_info_with_series
                    db_info = get_study_info_with_series(study_uid)

                    if db_info:
                        logger.info(f"✅ [SERIES RETRY] Found study in database, creating state...")
                        task = self._create_task_from_dict(db_info)
                        state = self.state_store.create(task)
                        self._tasks[study_uid] = task
                        logger.info(f"✅ [SERIES RETRY] Auto-created state for study {study_uid[:40]}")
                    else:
                        logger.warning(f"⚠️ [SERIES RETRY] Study not found in database — scheduling background cleanup")
                        # Offload file deletion to background thread
                        def _bg_cleanup():
                            try:
                                from PacsClient.utils.config import SOURCE_PATH
                                from pathlib import Path
                                import shutil
                                series_path = Path(SOURCE_PATH) / study_uid / str(series_number)
                                if series_path.exists():
                                    logger.info(f"🗑️ [SERIES RETRY-BG] Deleting {series_path}")
                                    shutil.rmtree(series_path)
                                    logger.info(f"✅ [SERIES RETRY-BG] Deleted")
                            except Exception as e:
                                logger.error(f"❌ [SERIES RETRY-BG] Error: {e}")
                        threading.Thread(target=_bg_cleanup, daemon=True, name="series-retry-cleanup").start()
                        return

                except Exception as e:
                    logger.error(f"❌ [SERIES RETRY] Error auto-creating state: {e}")
                    return

                if not state:
                    return

            logger.info(f"📊 [SERIES RETRY] Current study state: {state.status.value}")

            # Get or fast-resolve task (from memory only — no gRPC here)
            task = self._tasks.get(study_uid)

            target_uid = str(series_uid) if series_uid else None
            target_num = str(series_number) if series_number is not None else None

            if task and task.series_list:
                # Resolve missing series_uid/series_number from the task list
                if not target_uid or not target_num:
                    for series_info in task.series_list:
                        if target_uid and str(series_info.series_uid) == target_uid:
                            target_num = str(series_info.series_number)
                            break
                        if target_num is not None and str(series_info.series_number) == target_num:
                            target_uid = str(series_info.series_uid)
                            break

                target_idx = None
                for idx, series_info in enumerate(task.series_list):
                    if target_uid and str(series_info.series_uid) == target_uid:
                        target_idx = idx
                        break
                    if target_num is not None and str(series_info.series_number) == target_num:
                        target_idx = idx
                        break

                if target_idx is not None and target_idx > 0:
                    series_list = list(task.series_list)
                    series_list.insert(0, series_list.pop(target_idx))
                    task = replace(task, series_list=series_list)
                    self._tasks[study_uid] = task
                    logger.info(f"✅ [SERIES RETRY] Promoted series {target_num or series_number} to front")

            # Remove series from completed/failed/skipped lists
            series_removed = False
            if target_num:
                if target_num in (state.completed_series or []):
                    state.completed_series.remove(target_num)
                    series_removed = True
                if target_num in (state.failed_series or []):
                    state.failed_series.remove(target_num)
                    series_removed = True
                if target_num in (state.skipped_series or []):
                    state.skipped_series.remove(target_num)
                    series_removed = True
            if target_uid:
                if target_uid in (state.completed_series or []):
                    state.completed_series.remove(target_uid)
                    series_removed = True
                if target_uid in (state.failed_series or []):
                    state.failed_series.remove(target_uid)
                    series_removed = True
                if target_uid in (state.skipped_series or []):
                    state.skipped_series.remove(target_uid)
                    series_removed = True

            if not series_removed:
                _active_count = self.worker_pool.get_active_count()
                if _active_count > 0 and state.status == DownloadStatus.DOWNLOADING:
                    current_num = str(state.current_series_number) if state.current_series_number is not None else None
                    current_uid = str(state.current_series) if state.current_series is not None else None

                    target_is_current = False
                    if target_num and current_num and str(target_num) == str(current_num):
                        target_is_current = True
                    if target_uid and current_uid and str(target_uid) == str(current_uid):
                        target_is_current = True

                    if target_is_current:
                        logger.info(
                            f"⏳ [SERIES RETRY] Target series {target_num or series_number} is already "
                            f"the active downloading series (pool={_active_count}). Skipping retry."
                        )
                        return

                    logger.info(
                        f"⚡ [SERIES RETRY] Critical request for series {target_num or series_number} "
                        f"while series {current_num or current_uid or 'unknown'} is active. "
                        f"Preempting current study worker for immediate reprioritization."
                    )

            # Non-blocking preemption of active downloads
            if self.worker_pool.get_active_count() > 0:
                logger.info(f"⏸️ [SERIES RETRY] Preempting active downloads (non-blocking)")
                self._pause_all_active_downloads()

            # Promote priority to CRITICAL and latch viewed series via coordinator.
            if target_num:
                self.intent_coordinator.request_critical_series(study_uid, str(target_num))
            else:
                self.intent_coordinator.request_study_priority(study_uid, DownloadPriority.CRITICAL)

            # Force state to PENDING (bypass terminal state protection)
            if state.status == DownloadStatus.COMPLETED:
                old_status = state.status
                state.status = DownloadStatus.PENDING
                state.error_message = None
                self.state_store._notify_observers('updated', study_uid, state, 'status', old_status, DownloadStatus.PENDING)
            elif state.status in [DownloadStatus.FAILED, DownloadStatus.PAUSED, DownloadStatus.CANCELLED]:
                old_status = state.status
                state.status = DownloadStatus.PENDING
                state.error_message = None
                state.is_auto_paused = False
                self.state_store._notify_observers('updated', study_uid, state, 'status', old_status, DownloadStatus.PENDING)
            if state.status != DownloadStatus.PENDING:
                self.state_store.update(study_uid, status=DownloadStatus.PENDING, error_message=None)

            # Final consolidated table refresh after ALL state changes
            # (priority→CRITICAL, others→PAUSED, this→PENDING) are applied.
            QTimer.singleShot(50, self._refresh_table_order)

            # ──────────────────────────────────────────────────────────
            # SLOW PATH — offloaded to a background thread
            # File I/O + gRPC task reconstruction, then marshal back
            # to the main thread to start the download worker.
            # ──────────────────────────────────────────────────────────
            _series_key = target_num or series_number
            _has_task = task is not None

            def _bg_series_retry():
                """Background thread: file I/O + task reconstruction."""
                _task = task
                try:
                    from PacsClient.utils.config import SOURCE_PATH
                    from pathlib import Path
                    import shutil
                    import os

                    # --- Reconstruct task from gRPC if not in memory ---
                    if not _task:
                        logger.info(f"🔄 [SERIES RETRY-BG] Reconstructing task via gRPC...")
                        _task = self._reconstruct_task_from_database(study_uid)
                        if _task:
                            self._tasks[study_uid] = _task
                        else:
                            logger.error(f"❌ [SERIES RETRY-BG] Task reconstruction failed")

                    # --- File cleanup ---
                    series_path = Path(SOURCE_PATH) / study_uid / str(_series_key)
                    if series_path.exists():
                        existing_dcm = [f for f in os.listdir(series_path) if f.endswith('.dcm')]
                        existing_count = len(existing_dcm)

                        expected_count = 0
                        if _task and _task.series_list:
                            for si in _task.series_list:
                                if str(si.series_number) == str(_series_key):
                                    expected_count = si.image_count
                                    break

                        if expected_count > 0 and existing_count < expected_count:
                            logger.info(
                                f"ℹ️ [SERIES RETRY-BG] Keeping {existing_count}/{expected_count} files "
                                f"for series {_series_key} (incremental resume)"
                            )
                        else:
                            logger.info(f"🗑️ [SERIES RETRY-BG] Deleting series {_series_key} ({existing_count} files)")
                            shutil.rmtree(series_path)
                            logger.info(f"✅ [SERIES RETRY-BG] Deleted")
                    else:
                        logger.info(f"ℹ️ [SERIES RETRY-BG] No files at {series_path}")

                except Exception as e:
                    logger.error(f"❌ [SERIES RETRY-BG] Error: {e}")
                    import traceback
                    traceback.print_exc()

                # --- Marshal back to the main Qt thread ---
                def _main_thread_continue():
                    try:
                        logger.info(f"🚀 [SERIES RETRY] Starting download worker for series {_series_key}")
                        started = self._start_download_worker(study_uid)
                        if not started:
                            QTimer.singleShot(150, self._start_next_pending)

                        self._refresh_table_order()
                        updated_state = self.state_store.get(study_uid)
                        if updated_state and self._selected_study_uid == study_uid:
                            self._update_button_states(updated_state)
                        if self._selected_study_uid == study_uid:
                            QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))
                        logger.info(f"✅✅ [SERIES RETRY] Completed for series {_series_key}")
                    except Exception as e:
                        logger.error(f"❌ [SERIES RETRY] Error in main-thread continuation: {e}")

                QTimer.singleShot(0, _main_thread_continue)

            threading.Thread(target=_bg_series_retry, daemon=True, name="series-retry-io").start()
            logger.info(f"🔄 [SERIES RETRY] Background I/O thread started for series {_series_key}")

            # Immediate UI feedback
            self._refresh_table_order()

        except Exception as e:
            logger.error(f"❌ [SERIES RETRY] Error in series retry: {e}")
            import traceback
            traceback.print_exc()

    def _on_per_patient_retry(self, study_uid: str) -> None:
        """
        Per-patient Retry - Retry failed download (entire study).

        Heavy I/O (file deletion, gRPC metadata fetch) is offloaded to a
        background thread so the Qt event loop is never blocked.

        Args:
            study_uid: Study UID to retry
        """
        logger.info(f"🔄 Per-patient RETRY clicked for {study_uid[:40] if study_uid else 'None'}...")

        try:
            # ──────────────────────────────────────────────────────────
            # FAST PATH — runs on the main Qt thread (no blocking I/O)
            # ──────────────────────────────────────────────────────────
            state = self.state_store.get(study_uid)
            if not state:
                logger.warning(f"⚠️ State not found for {study_uid[:40] if study_uid else 'None'}...")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    None,
                    "Download State Not Found",
                    f"Study not found in download queue.\n\n"
                    f"Please:\n"
                    f"1. Add the study to downloads first\n"
                    f"2. Then retry the download"
                )
                return

            logger.info(f"📊 Current state before retry: {state.status.value}, Retry count: {state.retry_count}")

            # Reset state to PENDING immediately (fast, no I/O)
            if state.status == DownloadStatus.COMPLETED:
                logger.info(f"💾 Force resetting COMPLETED download for retry: {study_uid[:40] if study_uid else 'None'}...")
                self.state_store.reset(study_uid)
            else:
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.PENDING,
                    error_message=None,
                    is_auto_paused=False
                )

            # Quick access: task from memory (may be None)
            task_in_memory = self._tasks.get(study_uid)

            # ──────────────────────────────────────────────────────────
            # SLOW PATH — offloaded to background thread
            # File deletion + gRPC task reconstruction, then marshal
            # back to main thread to start the download worker.
            # ──────────────────────────────────────────────────────────
            def _bg_patient_retry():
                """Background thread: file I/O + task reconstruction."""
                _task = task_in_memory
                try:
                    from PacsClient.utils.config import SOURCE_PATH
                    from pathlib import Path
                    import shutil
                    import os

                    study_path = Path(SOURCE_PATH) / study_uid

                    # Reconstruct task from gRPC if not in memory
                    if not _task:
                        logger.info(f"🔄 [RETRY-BG] Reconstructing task via gRPC for {study_uid[:40]}...")
                        _task = self._reconstruct_task_from_database(study_uid)
                        if _task:
                            self._tasks[study_uid] = _task

                    # File cleanup: delete "complete" series, keep incomplete for resume
                    if study_path.exists() and _task and _task.series_list:
                        for si in _task.series_list:
                            series_path = study_path / str(si.series_number)
                            if not series_path.exists():
                                continue
                            existing_dcm = [f for f in os.listdir(series_path) if f.endswith('.dcm')]
                            existing_count = len(existing_dcm)
                            expected_count = si.image_count

                            if expected_count > 0 and existing_count < expected_count:
                                logger.info(
                                    f"ℹ️ [RETRY-BG] Keeping {existing_count}/{expected_count} files "
                                    f"for series {si.series_number} (incremental resume)"
                                )
                            else:
                                logger.info(
                                    f"🗑️ [RETRY-BG] Deleting {existing_count} files for series "
                                    f"{si.series_number} (complete/unknown — force re-download)"
                                )
                                shutil.rmtree(series_path)
                    elif study_path.exists():
                        logger.info(f"🗑️ [RETRY-BG] No task info — deleting entire study dir")
                        shutil.rmtree(study_path)

                except Exception as e:
                    logger.error(f"❌ [RETRY-BG] Error during file cleanup: {e}")
                    import traceback
                    traceback.print_exc()

                # Marshal back to main Qt thread
                def _main_thread_continue():
                    try:
                        logger.info(f"🚀 Starting download worker for retry: {study_uid[:40] if study_uid else 'None'}...")
                        self._start_download_worker(study_uid)

                        self._refresh_table_order()
                        updated_state = self.state_store.get(study_uid)
                        if updated_state and self._selected_study_uid == study_uid:
                            self._update_button_states(updated_state)
                        if self._selected_study_uid == study_uid:
                            QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))
                        logger.info(f"✅ [RETRY] Download worker started for {study_uid[:40] if study_uid else 'None'}...")
                    except Exception as e:
                        logger.error(f"❌ [RETRY] Error in main-thread continuation: {e}")

                QTimer.singleShot(0, _main_thread_continue)

            threading.Thread(target=_bg_patient_retry, daemon=True, name="patient-retry-io").start()
            logger.info(f"🔄 [RETRY] Background I/O thread started for {study_uid[:40] if study_uid else 'None'}...")

            # Immediate UI feedback
            self._refresh_table_order()

        except Exception as e:
            logger.error(f"❌ Error in per-patient retry: {e}")
            logger.error(f"🔴 [OPERATION FAILURE] Per-patient retry failed for {study_uid[:40] if study_uid else 'None'}...: {e}")
            import traceback
            traceback.print_exc()
