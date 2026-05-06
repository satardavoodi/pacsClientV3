"""Button/control handlers: play, pause, clear, start, cancel, retry, reset, priority"""
# Auto-generated from main_widget.py — Phase 2 split



import logging

from ...core.enums import DownloadPriority, DownloadStatus

logger = logging.getLogger(__name__)

class _DMControlsMixin:
    """Button/control handlers: play, pause, clear, start, cancel, retry, reset, priority"""

    def _on_play(self) -> None:
        """
        Global Play/Resume - Resume paused downloads or restart cancelled ones
        
        Behavior:
        - Resumes PAUSED downloads (keeps their current progress)
        - Restarts CANCELLED downloads (resets progress to 0%)
        - Does NOT restart completed or failed downloads
        
        Note: Use Retry button to restart a specific download from the beginning
        Note: Use Reset All button to restart all downloads from the beginning
        """
        logger.info("=" * 80)
        logger.info("🔵 [BUTTON CLICK] Play/Resume button clicked")
        logger.info("▶ PLAY PRESSED - Resuming paused & restarting cancelled downloads")
        logger.info("=" * 80)
        
        try:
            # Step 1: Check worker pool state
            logger.info(f"[PLAY-1] Checking worker pool state...")
            active_workers = self.worker_pool.get_active_count()
            logger.info(f"[PLAY-1] Active workers BEFORE play: {active_workers}")
            
            # Step 2: Get all downloads
            logger.info(f"[PLAY-2] Getting all downloads from state store...")
            all_downloads = self.state_store.get_all_downloads()
            logger.info(f"[PLAY-2] Total downloads in state store: {len(all_downloads)}")
            
            # Log status breakdown
            status_breakdown = {}
            for state in all_downloads:
                status_key = state.status.value if hasattr(state.status, 'value') else str(state.status)
                status_breakdown[status_key] = status_breakdown.get(status_key, 0) + 1
            logger.info(f"[PLAY-2] Status breakdown: {status_breakdown}")
            
            # Step 3: Filter paused and cancelled downloads
            logger.info(f"[PLAY-3] Filtering paused and cancelled downloads...")
            paused_downloads = [
                state for state in all_downloads
                if state.status == DownloadStatus.PAUSED
            ]
            cancelled_downloads = [
                state for state in all_downloads
                if state.status == DownloadStatus.CANCELLED
            ]
            logger.info(f"[PLAY-3] Paused downloads to resume: {len(paused_downloads)}")
            logger.info(f"[PLAY-3] Cancelled downloads to restart: {len(cancelled_downloads)}")
            
            to_process = paused_downloads + cancelled_downloads
            
            if not to_process:
                logger.info("✅ [PLAY-3] No downloads to resume or restart")
                self.log_message("ℹ️ No paused or cancelled downloads")
                self._update_status_label()
                logger.info("=" * 80)
                return
            
            # Step 4: Process paused downloads (WITHOUT resetting progress)
            logger.info(f"[PLAY-4] Processing {len(paused_downloads)} paused downloads (resume)...")
            for i, state in enumerate(paused_downloads):
                logger.info(f"[PLAY-4.{i}] {state.patient_name or 'Unknown'} - Status: PAUSED")
                try:
                    # IMPORTANT: Only set status to PENDING, do NOT reset progress
                    logger.info(f"[PLAY-4.{i}] 📤 Resuming download (keeping current progress)")
                    self.state_store.update(
                        state.study_uid,
                        status=DownloadStatus.PENDING,
                        is_auto_paused=False
                    )
                except Exception as e:
                    logger.error(f"[PLAY-4.{i}] ❌ Error resuming download: {e}")
            
            # Step 4b: Process cancelled downloads (WITH reset - restart from beginning)
            logger.info(f"[PLAY-4b] Processing {len(cancelled_downloads)} cancelled downloads (restart)...")
            for i, state in enumerate(cancelled_downloads):
                logger.info(f"[PLAY-4b.{i}] {state.patient_name or 'Unknown'} - Status: CANCELLED")
                try:
                    # IMPORTANT: Reset cancelled downloads to start from beginning
                    logger.info(f"[PLAY-4b.{i}] 🔄 Restarting cancelled download from 0%")
                    self.state_store.reset(state.study_uid)
                except Exception as e:
                    logger.error(f"[PLAY-4b.{i}] ❌ Error restarting download: {e}")
            
            # Step 5: Start workers up to pool capacity
            logger.info(f"[PLAY-5] Starting workers up to pool capacity...")
            max_workers = self.worker_pool.max_workers
            logger.info(f"[PLAY-5] Pool capacity: {max_workers}, Downloads to process: {len(to_process)}")
            
            success_count = 0
            error_count = 0
            started_count = 0
            
            # Only try to start as many workers as pool capacity allows
            for i, state in enumerate(to_process):
                # Check if pool still has capacity
                if not self.worker_pool.can_add_worker():
                    logger.info(f"[PLAY-5] Pool at capacity, remaining {len(to_process) - i} downloads will auto-start when slots free up")
                    break
                
                try:
                    logger.info(f"[PLAY-5.{i}] Starting worker for {state.study_uid[:40]}...")
                    started = self._start_download_worker(state.study_uid)
                    
                    if started:
                        logger.info(f"[PLAY-5.{i}] ✅ Worker started successfully")
                        success_count += 1
                        started_count += 1
                    else:
                        logger.warning(f"[PLAY-5.{i}] ⚠��� Worker did not start")
                        error_count += 1
                
                except Exception as e:
                    logger.error(f"[PLAY-5.{i}] ❌ ERROR: {e}")
                    import traceback
                    logger.error(f"[PLAY-5.{i}] Traceback:\n{traceback.format_exc()}")
                    error_count += 1
            
            # Step 6: Summary
            logger.info(f"[PLAY-6] Processing complete:")
            logger.info(f"[PLAY-6]   ✅ Workers started: {started_count}")
            logger.info(f"[PLAY-6]   ⏳ Queued (will auto-start): {len(to_process) - started_count - error_count}")
            logger.info(f"[PLAY-6]   ❌ Errors: {error_count}")
            logger.info(f"[PLAY-6]   📊 Total downloads: {len(to_process)} ({len(paused_downloads)} paused, {len(cancelled_downloads)} cancelled)")
            
            # Step 7: Check final worker pool state
            active_workers_after = self.worker_pool.get_active_count()
            logger.info(f"[PLAY-7] Active workers AFTER play: {active_workers_after}")
            logger.info(f"[PLAY-7] Worker change: +{active_workers_after - active_workers}")
            
            # Step 8: Update UI
            logger.info(f"[PLAY-8] Updating status label...")
            self._update_status_label()

            # Step 9: Refresh table to show updated statuses
            logger.info(f"[PLAY-9] Refreshing table order...")
            self.refresh_table_order()

            logger.info("=" * 80)
            logger.info("▶ PLAY COMPLETED")
            logger.info("🟢 [BUTTON SUCCESS] Play/Resume operation completed successfully")
            logger.info("=" * 80)
        
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ CRITICAL ERROR IN _on_play()")
            logger.error(f"🔴 [BUTTON FAILURE] Play/Resume operation failed")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            logger.error("=" * 80)
            raise  # Re-raise to ensure crash is visible

    def _on_pause(self) -> None:
        """
        Global Pause - Freeze ALL downloads immediately (non-blocking).

        Behavior:
        - Requests cancellation on all active workers (sets cancel flags only — non-blocking)
        - Marks all non-terminal downloads as PAUSED in the state store
        - Workers self-clean via their ``finished`` signal; UI does NOT wait for them

        CRITICAL: Must NOT call stop_all() here — it blocks the main thread up to
        5 s/worker and freezes the entire application.
        """
        logger.info("⏸ PAUSE PRESSED - Starting global pause (non-blocking)")

        try:
            # Step 1: Request cancellation on all workers — returns immediately
            cancelled = self.worker_pool.cancel_all_non_blocking()
            logger.info(f"[PAUSE] Cancel requested for {cancelled} worker(s) (non-blocking)")

            # Step 2: Normalize all non-terminal states to PAUSED
            all_downloads = self.state_store.get_all_downloads()
            paused_count = 0
            for state in all_downloads:
                if not state.is_terminal:
                    try:
                        self.state_store.update(
                            state.study_uid,
                            status=DownloadStatus.PAUSED,
                            is_auto_paused=False
                        )
                        paused_count += 1
                    except Exception as e:
                        logger.error(f"[PAUSE] Error pausing {state.study_uid[:40]}...: {e}")

            logger.info(f"[PAUSE] Paused {paused_count}/{len(all_downloads)} downloads")

            # Step 3: Update UI
            self._update_status_label()
            self.refresh_table_order()

            logger.info("⏸ PAUSE COMPLETED")

        except Exception as e:
            logger.error(f"❌ CRITICAL ERROR IN _on_pause(): {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    def _on_clear(self) -> None:
        """Clear completed downloads"""
        logger.info("🔵 [BUTTON CLICK] Clear Completed button clicked")
        try:
            cleared = self.state_store.clear_completed()
            logger.info(f"🧹 Cleared {cleared} completed downloads")
            self._update_status_label()
            logger.info(f"🟢 [BUTTON SUCCESS] Clear Completed operation successful - {cleared} items cleared")
        except Exception as e:
            logger.error(f"🔴 [BUTTON FAILURE] Clear Completed operation failed: {e}")
            raise

    def _on_refresh(self):
        """Refresh download status from database"""
        logger.info("� [BUTTON CLICK] Refresh button clicked")
        try:
            logger.info("🔄 Refreshing download status...")
            self._update_status_label()
            logger.info("🟢 [BUTTON SUCCESS] Refresh operation completed successfully")
        except Exception as e:
            logger.error(f"🔴 [BUTTON FAILURE] Refresh operation failed: {e}")
            raise

    def _on_start_selected(self):
        """Start/Resume selected download (PAUSED, FAILED, CANCELLED)."""
        logger.info("🔵 [BUTTON CLICK] Start Selected button clicked")
        if self._selected_study_uid:
            logger.info(f"Starting download for selected study: {self._selected_study_uid[:40]}...")
            
            # Get the current state to check if it's paused/cancelled/failed
            state = self.state_store.get(self._selected_study_uid)
            if state:
                logger.info(f"📊 Current state: {state.status.value}, changing to PENDING")
                
                # Resume PAUSED/FAILED downloads OR restart CANCELLED downloads
                if state.status == DownloadStatus.PAUSED:
                    # Update the state to PENDING and start the download
                    logger.info(f"📤 Resuming paused download (keeping current progress)")
                    self.state_store.update(
                        self._selected_study_uid,
                        status=DownloadStatus.PENDING,
                        error_message=None,
                        is_auto_paused=False
                    )
                    
                    logger.info(f"💾 Database update: {self._selected_study_uid[:40]}... status changed to PENDING")
                    
                    # Start the download worker
                    logger.info(f"🚀 Starting download worker for selected study: {self._selected_study_uid[:40]}...")
                    started = self._start_download_worker(self._selected_study_uid)
                    
                    if started:
                        logger.info(f"✅ Download worker started successfully for {self._selected_study_uid[:40]}...")
                    else:
                        logger.warning(f"⚠️ Failed to start download worker for {self._selected_study_uid[:40]}...")
                    
                    # Refresh the table to reflect the status change
                    logger.info(f"🔄 Refreshing table after resume selected for {self._selected_study_uid[:40]}...")
                    self.refresh_table_order()
                    
                    # Update button states after status change
                    updated_state = self.state_store.get(self._selected_study_uid)
                    if updated_state:
                        logger.info(f"🔄 Updating button states for resumed study {self._selected_study_uid[:40]}...")
                        self._update_button_states(updated_state)
                        
                elif state.status == DownloadStatus.FAILED:
                    # Retry failed download from pending state
                    logger.info(f"🔄 Resuming failed download")
                    self.state_store.update(
                        self._selected_study_uid,
                        status=DownloadStatus.PENDING,
                        error_message=None,
                        is_auto_paused=False
                    )
                    logger.info(f"💾 Database update: {self._selected_study_uid[:40]}... status changed to PENDING")

                    # Start the download worker
                    logger.info(f"🚀 Starting download worker for resumed-failed study: {self._selected_study_uid[:40]}...")
                    started = self._start_download_worker(self._selected_study_uid)

                    if started:
                        logger.info(f"✅ Download worker started successfully for {self._selected_study_uid[:40]}...")
                    else:
                        logger.warning(f"⚠️ Failed to start download worker for {self._selected_study_uid[:40]}...")

                    # Refresh the table to reflect the status change
                    logger.info(f"🔄 Refreshing table after failed->pending resume for {self._selected_study_uid[:40]}...")
                    self.refresh_table_order()

                    # Update button states after status change
                    updated_state = self.state_store.get(self._selected_study_uid)
                    if updated_state:
                        logger.info(f"🔄 Updating button states for resumed-failed study {self._selected_study_uid[:40]}...")
                        self._update_button_states(updated_state)

                elif state.status == DownloadStatus.CANCELLED:
                    # Restart cancelled download from beginning
                    logger.info(f"🔄 Restarting cancelled download from 0%")
                    self.state_store.reset(self._selected_study_uid)
                    logger.info(f"💾 Database update: {self._selected_study_uid[:40]}... status reset to PENDING")
                    
                    # Start the download worker
                    logger.info(f"🚀 Starting download worker for restarted study: {self._selected_study_uid[:40]}...")
                    started = self._start_download_worker(self._selected_study_uid)
                    
                    if started:
                        logger.info(f"✅ Download worker started successfully for {self._selected_study_uid[:40]}...")
                    else:
                        logger.warning(f"⚠️ Failed to start download worker for {self._selected_study_uid[:40]}...")
                    
                    # Refresh the table to reflect the status change
                    logger.info(f"🔄 Refreshing table after restart selected for {self._selected_study_uid[:40]}...")
                    self.refresh_table_order()
                    
                    # Update button states after status change
                    updated_state = self.state_store.get(self._selected_study_uid)
                    if updated_state:
                        logger.info(f"🔄 Updating button states for restarted study {self._selected_study_uid[:40]}...")
                        self._update_button_states(updated_state)
                        
                else:
                    # Not paused or cancelled - cannot resume/restart with this button
                    logger.warning(f"⚠️ Cannot resume: download status is {state.status.value}, not PAUSED/FAILED/CANCELLED")
                    self.log_message(
                        f"ℹ️ Can only Start for PAUSED/FAILED or restart CANCELLED downloads. "
                        f"Use Retry to restart from beginning."
                    )
            else:
                logger.warning(f"⚠️ No state found for study {self._selected_study_uid[:40]}...")
            
            logger.info("🟢 [BUTTON SUCCESS] Start Selected operation completed")
        else:
            logger.warning("⚠️ [BUTTON WARNING] Start Selected clicked but no study selected")

    def _on_pause_selected(self):
        """Pause selected download"""
        logger.info("🔵 [BUTTON CLICK] Pause Selected button clicked")
        if self._selected_study_uid:
            logger.info(f"Pausing download for selected study: {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self._on_per_patient_pause(self._selected_study_uid)
            
            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after pause selected for {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self.refresh_table_order()
            
            logger.info("🟢 [BUTTON SUCCESS] Pause Selected operation completed")
        else:
            logger.warning("⚠️ [BUTTON WARNING] Pause Selected clicked but no study selected")

    def _on_cancel_selected(self):
        """Cancel selected download"""
        logger.info("🔵 [BUTTON CLICK] Cancel Selected button clicked")
        if self._selected_study_uid:
            logger.info(f"Canceling download for selected study: {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self._on_per_patient_cancel(self._selected_study_uid)
            
            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after cancel selected for {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self.refresh_table_order()
            
            logger.info("🟢 [BUTTON SUCCESS] Cancel Selected operation completed")
        else:
            logger.warning("⚠️ [BUTTON WARNING] Cancel Selected clicked but no study selected")

    def _on_retry_selected(self):
        """Retry selected download"""
        logger.info("🔵 [BUTTON CLICK] Retry Selected button clicked")
        if self._selected_study_uid:
            logger.info(f"Retrying download for selected study: {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self._on_per_patient_retry(self._selected_study_uid)
            
            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after retry selected for {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self.refresh_table_order()
            
            logger.info("🟢 [BUTTON SUCCESS] Retry Selected operation completed")
        else:
            logger.warning("⚠️ [BUTTON WARNING] Retry Selected clicked but no study selected")

    def _on_reset_all(self):
        """
        Reset All Downloads button - Reset all downloads and restart from beginning
        
        This resets ALL downloads regardless of their current state:
        - PENDING → PENDING (clear progress)
        - DOWNLOADING → PENDING (abort current, reset from start)
        - COMPLETED → PENDING (download again) ⭐ FORCED via state_store.reset()
        - FAILED → PENDING (clear error, retry)
        - CANCELLED → PENDING (restore to queue) ⭐ FORCED via state_store.reset()
        - PAUSED → PENDING (unpause and reset)
        
        For each download:
        1. Reset status to PENDING (FORCED even from terminal states)
        2. Clear all progress (downloaded, current series, etc.)
        3. Clear errors
        4. Reset series tracking
        5. Clear timers
        """
        logger.info("=" * 100)
        logger.info("🟡 [BUTTON CLICK] Reset All button clicked")
        logger.info("🔄 RESET PRESSED - Resetting ALL downloads to start from beginning")
        logger.info("=" * 100)
        
        try:
            # Get all downloads currently in the system
            all_studies = list(self.state_store._states.keys())
            
            if not all_studies:
                logger.warning("⚠️ No downloads to reset")
                self.log_message("ℹ️ No downloads to reset")
                return
            
            logger.info(f"📊 Resetting {len(all_studies)} downloads...")
            
            reset_count = 0
            for study_uid in all_studies:
                try:
                    task = self._tasks.get(study_uid)
                    if not task:
                        logger.warning(f"⚠️ No task found for {study_uid[:40] if study_uid else 'None'}...")
                        continue
                    
                    logger.info(f"🔄 Resetting {task.patient_name} ({study_uid[:40]}...)")
                    
                    # Use FORCE RESET method (bypasses terminal state check)
                    # This is necessary because COMPLETED and CANCELLED are terminal states
                    self.state_store.reset(study_uid)
                    
                    # Clear series image count cache for this study
                    if study_uid in self._series_image_count_cache:
                        del self._series_image_count_cache[study_uid]
                    
                    # Clear pending progress for this study
                    if study_uid in self._pending_progress:
                        del self._pending_progress[study_uid]
                    
                    logger.info(
                        f"✅ Reset {task.patient_name}: Status=PENDING, "
                        f"Progress=0%, Priority=NORMAL, Error=None"
                    )
                    reset_count += 1
                    
                except Exception as e:
                    logger.error(f"❌ Failed to reset {study_uid[:40]}...: {e}", exc_info=True)
            
            logger.info("-" * 100)
            logger.info(f"✅ Reset complete: {reset_count}/{len(all_studies)} downloads reset")
            logger.info("=" * 100)
            
            # Log to UI
            self.log_message(f"✅ Reset {reset_count} downloads - all ready to restart")
            
            # Refresh entire table
            self.refresh_table_order()
            
            # Update status label
            self._update_status_label()
            
            # Clear details panel since all downloads were affected
            self._clear_details_panel()
            self._selected_study_uid = None
            
            logger.info("🟢 [BUTTON SUCCESS] Reset All operation completed")
            
        except Exception as e:
            logger.error(f"🔴 [BUTTON FAILURE] Reset All failed: {e}", exc_info=True)
            self.log_message(f"❌ Reset failed: {e}")
            raise

    def _on_priority_changed(self, new_priority: str):
        """Handle priority change from combo box"""
        # G7 — observability for the historical "ghost combo signal"
        # bug: when called during a `_refresh_table_order` rebuild, this
        # is a programmatic write (not user-initiated). Post-G8.1 the
        # only programmatic writers wrap the call in `blockSignals`, so
        # `during_rebuild=True` here is a regression signal.
        try:
            during_rebuild = bool(getattr(self, "_refresh_table_order_in_progress", False))
            current_uid = getattr(self, "_selected_study_uid", None) or ""
            # WARNING level: component=download default threshold is
            # WARNING in diagnostic_logging — INFO would be dropped.
            logger.warning(
                "[DM_PRIORITY_TRANSITION] event=combo_changed new=%s "
                "study=%s during_rebuild=%s",
                new_priority,
                current_uid[:40],
                during_rebuild,
                extra={"component": "download"},
            )
        except Exception:
            pass

        logger.info(f"📊 [CONTROL CHANGE] Priority dropdown changed to: {new_priority}")
        study_uid = self._selected_study_uid  # Cache to avoid race condition
        if study_uid:
            try:
                logger.info(f"Changing priority for study: {study_uid[:40]}...")
                # Map priority name to DownloadPriority enum
                priority_map = {
                    "Critical": DownloadPriority.CRITICAL,
                    "High": DownloadPriority.HIGH,
                    "Normal": DownloadPriority.NORMAL,
                    "Low": DownloadPriority.LOW
                }
                priority = priority_map.get(new_priority, DownloadPriority.NORMAL)

                can_change = self.rule_engine.can_change_priority(study_uid, priority)
                if not can_change.allowed:
                    logger.warning(
                        f"⚠️ Priority change rejected for {study_uid[:40]}...: {can_change.reason}"
                    )
                    state = self.state_store.get(study_uid)
                    if state:
                        self.priority_combo.blockSignals(True)
                        self.priority_combo.setCurrentText(state.priority.display_name)
                        self.priority_combo.blockSignals(False)
                    return

                # Update state
                self.state_store.update(study_uid, priority=priority)
                self.intent_coordinator.negotiate_priority_change(study_uid, priority)
                self.refresh_table_order()
                
                # Update button states after priority change
                state = self.state_store.get(study_uid)
                if state:
                    self._update_button_states(state)
                
                logger.info(f"📊 Priority changed for {study_uid[:40]}... → {new_priority}")
                logger.info(f"🟢 [CONTROL SUCCESS] Priority change completed successfully")
            except Exception as e:
                logger.error(f"🔴 [CONTROL FAILURE] Priority change failed for {study_uid[:40]}...: {e}")
                raise
        else:
            logger.debug("[CONTROL] Priority changed with no active study selection; ignoring")
