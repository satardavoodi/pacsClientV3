"""Worker lifecycle: start, progress, complete, error, auto-management, health"""
# Auto-generated from main_widget.py — Phase 2 split



import logging

from PySide6.QtCore import Signal, Qt, QTimer

from ...core.enums import DownloadPriority, DownloadStatus
from ...core.models import DownloadTask, DownloadState
from ...workers.download_process_worker import DownloadProcessWorker as DownloadWorker
from PacsClient.utils.diagnostic_logging import now_ms
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class _DMWorkersMixin:
    """Worker lifecycle: start, progress, complete, error, auto-management, health"""

    def _on_pool_slot_freed(self, study_uid: str) -> None:
        """Called by WorkerPool._remove_worker when a pool slot is freed.

        This fires from the QThread that emitted ``finished``, so we must
        defer to the main thread via ``QTimer.singleShot(0)``.  This gives
        the coordinator an **immediate** event-driven signal that the pool
        has capacity — no more relying solely on the 200 ms retry poller.
        """
        QTimer.singleShot(0, self._start_next_pending)

    def _reconstruct_task_from_database(self, study_uid: str) -> Optional[DownloadTask]:
        """
        Reconstruct a DownloadTask from server when it's not in memory.
        
        This happens when:
        - App is restarted and user wants to retry a download
        - Task was removed from memory but state persists in database
        
        Args:
            study_uid: Study UID to reconstruct
            
        Returns:
            DownloadTask if successful, None otherwise
        """
        try:
            logger.info(f"🔄 [TASK-RECONSTRUCT] Reconstructing task for {study_uid[:40]}...")
            
            # Get state from state_store for patient info
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"🔄 [TASK-RECONSTRUCT] ❌ No state found for {study_uid[:40]}...")
                return None
            
            logger.info(f"🔄 [TASK-RECONSTRUCT] Found state for {state.patient_name}")

            # Fetch metadata from server (most reliable source)
            try:
                logger.info(f"🔄 [TASK-RECONSTRUCT] Fetching metadata from server via gRPC...")
                metadata = self.grpc_client.fetch_study_metadata_sync(study_uid)

                if not metadata or not metadata.series_list:
                    logger.error(f"🔄 [TASK-RECONSTRUCT] ❌ No metadata or series returned from server")
                    return None

                logger.info(f"🔄 [TASK-RECONSTRUCT] ✅ Fetched metadata with {len(metadata.series_list)} series from server")

            except Exception as e:
                logger.error(f"🔄 [TASK-RECONSTRUCT] ❌ Failed to fetch metadata from server: {e}")
                import traceback
                logger.error(f"🔄 [TASK-RECONSTRUCT] Traceback:\n{traceback.format_exc()}")
                return None
            
            patient_info = getattr(metadata, 'patient_info', None)

            def _first_truthy_attr(obj, *names):
                if obj is None:
                    return None
                for name in names:
                    value = getattr(obj, name, None)
                    if value:
                        return value
                return None

            patient_id = getattr(state, 'patient_id', None) or _first_truthy_attr(patient_info, 'patient_id', 'id')
            patient_name = getattr(state, 'patient_name', None) or _first_truthy_attr(
                patient_info, 'patient_name', 'name', 'full_name'
            )

            # Build study data dict from metadata and state
            # Get modality from first series (study-level modality may not exist)
            study_modality = metadata.series_list[0].modality if metadata.series_list else ''
            study_data = {
                'study_uid': study_uid,
                'patient_id': patient_id or '',
                'patient_name': patient_name or '',
                'study_date': metadata.study_date or '',
                'study_time': metadata.study_time or '',
                'modality': study_modality,
                'study_description': metadata.study_description or '',
                'patient_age': _first_truthy_attr(patient_info, 'age') or '',
                'patient_sex': _first_truthy_attr(patient_info, 'sex') or '',
                'patient_birth_date': _first_truthy_attr(patient_info, 'birth_date') or '',
                'body_part': '',
                'series': []
            }
            
            # Convert SeriesInfo objects to dicts for _create_task_from_dict
            for series in metadata.series_list:
                series_dict = {
                    'series_number': series.series_number,
                    'series_uid': series.series_uid,
                    'series_description': series.series_description,
                    'modality': series.modality,
                    'image_count': series.image_count
                }
                study_data['series'].append(series_dict)
            
            logger.info(f"🔄 [TASK-RECONSTRUCT] Prepared study data with {len(study_data['series'])} series")
            
            # Create task from dict (same method used in add_downloads)
            task = self._create_task_from_dict(study_data)
            
            logger.info(f"🔄 [TASK-RECONSTRUCT] ✅ Task reconstructed successfully")
            logger.info(f"🔄 [TASK-RECONSTRUCT] Patient: {task.patient_name}")
            logger.info(f"🔄 [TASK-RECONSTRUCT] Series: {len(task.series_list)}")
            logger.info(f"🔄 [TASK-RECONSTRUCT] Total images: {task.total_image_count}")
            
            return task
            
        except Exception as e:
            logger.error(f"🔄 [TASK-RECONSTRUCT] ❌ Failed to reconstruct task: {e}")
            import traceback
            logger.error(f"🔄 [TASK-RECONSTRUCT] Traceback:\n{traceback.format_exc()}")
            return None

    def _start_download_worker(self, study_uid: str) -> bool:
        """
        Start a download worker for given study

        Args:
            study_uid: Study UID to download

        Returns:
            True if started, False otherwise
        """
        t_download_start_marker = now_ms()
        logger.info(
            "download-impact-window marker=download_start_before_worker_start ts_ms=%.3f study=%s",
            t_download_start_marker,
            study_uid[:40],
            extra={"component": "download", "study_uid": study_uid, "stage": "download_start_impact"},
        )
        logger.info(f"🚀 [WORKER-START] Starting worker for {study_uid[:40]}...")

        try:
            # Check if can add worker
            logger.info(f"🚀 [WORKER-START] Checking worker pool capacity...")
            can_add = self.worker_pool.can_add_worker()
            active_count = self.worker_pool.get_active_count()
            logger.info(f"🚀 [WORKER-START] Can add: {can_add}, Active: {active_count}")

            if not can_add:
                logger.warning(f"🚀 [WORKER-START] ⚠️ Cannot start - pool at capacity ({active_count})")
                return False

            # Get state
            logger.info(f"🚀 [WORKER-START] Getting state from state store...")
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"🚀 [WORKER-START] ❌ State not found for {study_uid[:40]}...")
                return False

            logger.info(f"🚀 [WORKER-START] State found: {state.patient_name}, Status: {state.status.value}")

            # Get the original task from storage (or reconstruct from database)
            logger.info(f"🚀 [WORKER-START] Getting original DownloadTask from storage...")
            task = self._tasks.get(study_uid)

            if not task:
                logger.warning(f"🚀 [WORKER-START] ⚠️ Task not in memory, attempting to reconstruct from database...")
                logger.warning(f"🚀 [WORKER-START] Available tasks in memory: {list(self._tasks.keys())}")
                
                # Try to reconstruct task from database
                task = self._reconstruct_task_from_database(study_uid)
                
                if task:
                    logger.info(f"🚀 [WORKER-START] ✅ Task reconstructed from database with {len(task.series_list)} series")
                    # Store it for future use
                    self._tasks[study_uid] = task
                else:
                    logger.error(f"🚀 [WORKER-START] ❌ Failed to reconstruct task from database")
                    logger.error(f"🚀 [WORKER-START] Cannot start download without task information")
                    return False

            logger.info(f"🚀 [WORKER-START] Found task with {len(task.series_list)} series")

            # Create worker — DownloadProcessWorker runs the download in a
            # separate Python process (own GIL) so the viewer is never starved.
            logger.info(f"🚀 [WORKER-START] Creating DownloadProcessWorker instance...")
            worker = DownloadWorker(task, self.executor)
            logger.info(f"🚀 [WORKER-START] Worker created: {type(worker).__name__}")

            # Connect signals
            logger.info(f"🚀 [WORKER-START] Connecting worker signals...")
            worker.progress.connect(self._on_worker_progress)
            worker.completed.connect(self._on_worker_completed)
            worker.error.connect(self._on_worker_error)
            logger.info(f"🚀 [WORKER-START] Signals connected successfully")

            # Add to pool
            logger.info(f"🚀 [WORKER-START] Adding worker to pool...")
            logger.info(f"🚀 [WORKER-START] Worker type: {type(worker)}, Worker isRunning: {worker.isRunning()}")
            logger.info(f"🚀 [WORKER-START] Pool type: {type(self.worker_pool)}, Pool capacity: {self.worker_pool.can_add_worker()}")

            try:
                add_result = self.worker_pool.add_worker(worker, study_uid)
                logger.info(f"🚀 [WORKER-START] add_worker returned: {add_result}")
            except Exception as e:
                logger.error(f"🚀 [WORKER-START] ❌ EXCEPTION in add_worker:")
                logger.error(f"🚀 [WORKER-START] Exception type: {type(e).__name__}")
                logger.error(f"🚀 [WORKER-START] Exception message: {str(e)}")
                import traceback
                logger.error(f"🚀 [WORKER-START] Traceback:\n{traceback.format_exc()}")
                raise

            if add_result:
                logger.info(f"🚀 [WORKER-START] Worker added to pool successfully")

                # Start worker
                logger.info(f"🚀 [WORKER-START] Starting worker thread...")
                worker.start()
                logger.info(f"🚀 [WORKER-START] Worker thread started")
                logger.info(
                    "download-impact-window marker=download_start_after_worker_start delta_ms=%.2f",
                    now_ms() - t_download_start_marker,
                    extra={"component": "download", "study_uid": study_uid, "stage": "download_start_impact"},
                )

                for _delay in (250, 1500, 5000):
                    QTimer.singleShot(
                        _delay,
                        lambda d=_delay: logger.info(
                            "download-impact-window marker=viewer_post_start_probe delay_ms=%d elapsed_ms=%.2f active_workers=%d",
                            d,
                            now_ms() - t_download_start_marker,
                            self.worker_pool.get_active_count(),
                            extra={"component": "viewer", "study_uid": study_uid, "stage": "download_start_impact"},
                        ),
                    )

                # TASK 1 FIX: Wire global download counter
                # Blocks ZetaBoost warmup/background lanes during ANY download
                try:
                    from modules.zeta_boost.engine import ZetaBoostEngine
                    ZetaBoostEngine.notify_global_download_start()
                    logger.info(f"✅ [ZETABOOST-TASK1] Global download counter INCREMENTED")
                except Exception as e:
                    logger.warning(f"⚠️ [ZETABOOST-TASK1] Failed to notify download start: {e}")

                # Log database update for download start
                updated_state = self.state_store.get(study_uid)
                if updated_state:
                    logger.info(f"💾 [DATABASE] Study {study_uid[:40]}... started download, status: {updated_state.status.value}")

                logger.info(f"🚀 [WORKER-START] ✅ 🚀 Worker fully started for {study_uid[:40]}...")
                return True
            else:
                logger.error(f"🚀 [WORKER-START] ❌ Failed to add worker to pool")
                return False

        except Exception as e:
            logger.error(f"🚀 [WORKER-START] ❌ EXCEPTION in _start_download_worker")
            logger.error(f"🚀 [WORKER-START] Error type: {type(e).__name__}")
            logger.error(f"🚀 [WORKER-START] Error message: {str(e)}")
            import traceback
            logger.error(f"🚀 [WORKER-START] Traceback:\n{traceback.format_exc()}")
            return False

    def _on_worker_progress(
        self,
        study_uid: str,
        event_type: str,
        series_number: str,
        progress: float,
        downloaded: int,
        total: int
    ) -> None:
        """Handle worker progress signal - THROTTLED to prevent event loop flooding"""
        try:
            # Log series changes but not every progress update to avoid spam
            if event_type == 'instance_downloaded':
                # Compute overall progress across all images
                overall_downloaded, overall_total, overall_percent = self._calculate_overall_progress(
                    study_uid,
                    series_number,
                    downloaded,
                    total
                )

                # NOTE: studyProgressUpdated is now batched in _pending_progress
                # and emitted by _apply_throttled_progress every 100ms —
                # not here, to avoid flooding the main-thread event queue.

                # Resolve series info from task
                task = self._tasks.get(study_uid)
                series_info = None
                if task:
                    for s in task.series_list:
                        if str(s.series_number) == str(series_number):
                            series_info = s
                            break

                series_uid = series_info.series_uid if series_info else series_number
                series_desc = series_info.series_description if series_info else ''

                # Emit series started when series number changes
                last_series = self._last_series_number_by_study.get(study_uid)
                if series_number and series_number != last_series:
                    self._last_series_number_by_study[study_uid] = series_number
                    logger.info(f"📊 [PROGRESS] Series {series_number} started: {series_desc}")
                    self.log_message(f"📊 [{study_uid[:10]}...] Series {series_number} started: {series_desc}")
                    self.seriesDownloadStarted.emit(study_uid, series_uid, series_desc)

                # NOTE: seriesProgressUpdated is batched below in _pending_progress
                # and emitted by _apply_throttled_progress every 100ms.

                # Emit series completed once
                if total > 0 and downloaded >= total:
                    completed_set = self._completed_series_emitted.setdefault(study_uid, set())
                    if series_uid not in completed_set:
                        completed_set.add(series_uid)
                        logger.info(f"✅ [PROGRESS] Series {series_number} completed")
                        self.log_message(f"✅ [{study_uid[:10]}...] Series {series_number} completed")
                        self.seriesDownloadCompleted.emit(study_uid, series_uid)

                        # Update completed_series in main-process state (series_downloader
                        # lives in a subprocess and cannot reach our state store directly).
                        _cs_state = self.state_store.get(study_uid)
                        if _cs_state and not _cs_state.is_terminal:
                            _updated_cs = list(set(_cs_state.completed_series or []) | {series_uid})
                            self.state_store.update(study_uid, completed_series=_updated_cs)

                        # If the completed series was the viewed (CRITICAL) series,
                        # clear the flag so priority drops back to HIGH.
                        state = self.state_store.get(study_uid)
                        if state and state.viewed_series_number == str(series_number):
                            self.clear_viewed_series(study_uid)

                # CRITICAL FIX: Batch progress updates instead of immediate
                # This reduces state store calls from 1000+ to ~10 per download
                # Store in pending dict and apply on throttle timer
                if study_uid not in self._pending_progress:
                    self._pending_progress[study_uid] = {}

                self._pending_progress[study_uid]['current_series_number'] = series_number
                self._pending_progress[study_uid]['current_series_downloaded'] = downloaded
                self._pending_progress[study_uid]['current_series_total'] = total
                self._pending_progress[study_uid]['current_series_progress'] = progress
                self._pending_progress[study_uid]['progress_percent'] = overall_percent
                self._pending_progress[study_uid]['downloaded_count'] = overall_downloaded
                self._pending_progress[study_uid]['total_count'] = overall_total
                # Store latest signal args so _apply_throttled_progress emits them
                # at 100ms intervals instead of per-image (primary lag fix).
                self._pending_progress[study_uid]['_study_progress_args'] = (
                    study_uid, overall_downloaded, overall_total, overall_percent
                )
                self._pending_progress[study_uid]['_series_progress_args'] = (
                    study_uid, series_uid, downloaded, total
                )

                # Start throttle timer if not already running
                if not self._progress_throttle_timer.isActive():
                    self._progress_throttle_timer.start()

                # Per-image at DEBUG level only — avoids GIL + string-fmt cost on main thread
                logger.debug(f"📊 [PROGRESS] {study_uid[:40]}... - {overall_percent:.1f}% "
                             f"({overall_downloaded}/{overall_total} images), Series: {series_number} ({downloaded}/{total})")
                
                # Log to UI log area periodically (not every image to avoid spam)
                if overall_downloaded % 100 == 0 or overall_percent == 100:  # Log every 100 images or when complete
                    self.log_message(f"📊 [{study_uid[:10]}...] Progress: {overall_percent:.1f}% ({overall_downloaded}/{overall_total} images)")
            else:
                # Other event types - also throttle
                if study_uid not in self._pending_progress:
                    self._pending_progress[study_uid] = {}

                pending = self._pending_progress[study_uid]
                pending['progress_percent'] = progress
                pending['downloaded_count'] = downloaded
                pending['total_count'] = total

                if not self._progress_throttle_timer.isActive():
                    self._progress_throttle_timer.start()

                logger.info(f"📊 [PROGRESS] {event_type} event for {study_uid[:40]}... - {progress:.1f}% ({downloaded}/{total})")

        except Exception as e:
            logger.error(f"❌ Error in progress handler: {e}", exc_info=True)

    def _apply_throttled_progress(self) -> None:
        """
        Apply all pending progress updates to state store (runs every 100ms)
        
        This method batches multiple progress updates from worker threads
        into single state_store calls, reducing event loop pressure.
        
        CRITICAL FIX for freezing:
        - Without throttling: 1000 state updates per download → freezes event loop
        - With throttling: ~10 state updates per download → smooth UI
        
        Performance improvement: 100x reduction in state store calls
        """
        try:
            # Adapt throttle interval to system load. During protected drag
            # (user actively stack-scrolling with mouse drag), bump the DM
            # progress fan-out from 100ms -> 750ms so main-thread slots
            # aren't firing 10x/second while the user is interacting.
            # This was the #1 cause of event_p50 == 106-150ms during
            # drag+download overlap in log 92.
            #
            # v2.3.6 game-changer #4: during protected drag, ALSO skip
            # the apply pass entirely. Each tick chains ~4-5 main-thread
            # slots (state_store.update + studyProgressUpdated +
            # seriesProgressUpdated + on_series_progress + per-viewer
            # progressive handlers), which totals 30-100ms of main-thread
            # work on slow PCs. Pending updates accumulate in
            # self._pending_progress and are flushed on the first tick
            # after the drag releases the protected latch.
            try:
                from modules.viewer.fast import ui_throttle as _ui_throttle
                protected = _ui_throttle.is_protected_drag_active()
                if protected:
                    target_interval = 1500
                elif _ui_throttle.is_heavy_download_active():
                    target_interval = 200
                else:
                    target_interval = 100
                if self._progress_throttle_timer.interval() != target_interval:
                    self._progress_throttle_timer.setInterval(target_interval)
                if protected:
                    # Keep the timer alive so it re-fires after the drag
                    # ends, but don't do the expensive apply work now.
                    if self._pending_progress and not self._progress_throttle_timer.isActive():
                        self._progress_throttle_timer.start()
                    return
            except Exception:
                pass

            if not self._pending_progress:
                # No pending updates, stop timer
                self._progress_throttle_timer.stop()
                return
            
            # Apply all pending updates in this batch
            # Dict comprehension ensures we process all updates atomically
            updates_to_apply = dict(self._pending_progress)
            self._pending_progress.clear()  # Clear before processing in case new updates arrive
            
            for study_uid, updates in updates_to_apply.items():
                try:
                    if updates:  # Only update if there are changes
                        # Pop signal-only keys so they are not forwarded to state_store.
                        study_progress_args = updates.pop('_study_progress_args', None)
                        series_progress_args = updates.pop('_series_progress_args', None)

                        # Persist state (remaining keys after pop)
                        if updates:
                            self.state_store.update(study_uid, **updates)

                        # Emit throttled UI signals — at most once per 100ms per study
                        # instead of once per downloaded image (100x–1000x reduction).
                        if study_progress_args:
                            self.studyProgressUpdated.emit(*study_progress_args)
                        if series_progress_args:
                            self.seriesProgressUpdated.emit(*series_progress_args)

                except Exception as e:
                    logger.error(f"❌ Error applying throttled update for {study_uid}: {e}")
            
            # Timer will continue running until _pending_progress is empty
            # This ensures all updates are processed even if they arrive frequently
            
        except Exception as e:
            logger.error(f"❌ Error in throttle timer: {e}", exc_info=True)
            self._progress_throttle_timer.stop()

    def _on_worker_completed(self, study_uid: str, success: bool) -> None:
        """Handle worker completion signal"""
        # TASK 1 FIX: Wire global download counter (stop side)
        try:
            from modules.zeta_boost.engine import ZetaBoostEngine
            ZetaBoostEngine.notify_global_download_stop()
            logger.info(f"✅ [ZETABOOST-TASK1] Global download counter DECREMENTED")
        except Exception as e:
            logger.warning(f"⚠️ [ZETABOOST-TASK1] Failed to notify download stop: {e}")
        
        try:
            logger.info(f"✅ [COMPLETION] Worker completed: {study_uid[:40]}... (success={success})")

            if success:
                logger.info(f"✅ [COMPLETION] Download completed successfully: {study_uid[:40]}...")
                logger.info("   Emitting download_completed signal...")
                self.download_completed.emit(study_uid)
                logger.info("   Signal emitted")

                # Update state to COMPLETED — force 100 % so progress bar matches badge.
                # completed_series is populated from subprocess state; replicate it here
                # from the task so the series breakdown shows all series as done.
                task_for_completion = self._tasks.get(study_uid)
                total_for_completion = (
                    task_for_completion.total_image_count if task_for_completion else 0
                ) or (self.state_store.get(study_uid).total_count if self.state_store.get(study_uid) else 0)
                all_series_uids = [
                    s.series_uid for s in task_for_completion.series_list
                ] if task_for_completion else []
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.COMPLETED,
                    progress_percent=100.0,
                    downloaded_count=total_for_completion,
                    total_count=total_for_completion,
                    completed_series=all_series_uids,
                    is_auto_paused=False,
                    viewed_series_number=None  # Clear viewed series on completion
                )
                logger.info(f"💾 [DATABASE] Updated study {study_uid[:40]}... to COMPLETED status (100 %, {total_for_completion} images)")
                
                # CRITICAL FIX: Clean up task state to prevent memory accumulation in high-frequency loops
                # (1000+ cycles with no cleanup = 1000+ dict entries accumulating)
                self._cleanup_task_state(study_uid)
                
                # Log completion to UI
                state = self.state_store.get(study_uid)
                patient_name = getattr(state, 'patient_name', 'Unknown') if state else 'Unknown'
                self.log_message(f"✅ [{study_uid[:10]}...] Download completed successfully for {patient_name}")
            else:
                # Check if this is a preemption (series-interrupt): the coordinator
                # sets state to PENDING before this signal arrives.  Do NOT count
                # preemptions against auto-retry — just let the pipeline re-queue.
                state = self.state_store.get(study_uid)
                if state and (
                    state.status == DownloadStatus.PENDING
                    or (state.status == DownloadStatus.PAUSED and state.is_auto_paused)
                ):
                    logger.info(
                        f"⏸️ [COMPLETION] Ignoring failure for preempted study "
                        f"{study_uid[:40]}... status={state.status.value} — will be re-queued automatically"
                    )
                    self._refresh_table_order()
                    self._check_auto_resume()
                    QTimer.singleShot(0, self._start_next_pending)
                    return

                logger.warning(f"❌ [COMPLETION] Download failed: {study_uid[:40]}...")
                # Log failure to UI
                patient_name = getattr(state, 'patient_name', 'Unknown') if state else 'Unknown'
                self.log_message(f"❌ [{study_uid[:10]}...] Download failed for {patient_name}")

            # Refresh table to show updated status
            logger.info("   Refreshing table order...")
            self._refresh_table_order()
            logger.info("   Table refreshed")

            # Check for auto-paused downloads that should auto-resume (Rule R5)
            logger.info("   Checking auto-resume...")
            self._check_auto_resume()
            logger.info("   Auto-resume checked")

            # Check for failed downloads that should auto-retry (Rule R28)
            # This ensures the pipeline doesn't get stuck on transient failures
            logger.info("   Checking auto-retry...")
            self._check_auto_retry()
            logger.info("   Auto-retry checked")

            # IMPORTANT: Defer starting next download to allow worker to be removed from pool first
            # The worker.finished signal removes the worker from the pool, but it happens after
            # the completed signal is processed. Using QTimer.singleShot(0, ...) defers execution
            # to the next event loop iteration when the worker has been removed.
            logger.info("   Scheduling next pending check (deferred)...")
            QTimer.singleShot(0, self._start_next_pending)
            logger.info("   Next pending scheduled")

            # Log database update for completion
            state = self.state_store.get(study_uid)
            if state:
                logger.info(f"💾 [DATABASE] Study {study_uid[:40]}... status: {state.status.value}, completed: {success}")

        except Exception as e:
            logger.error(f"❌ Error in _on_worker_completed: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _cleanup_task_state(self, study_uid: str) -> None:
        """
        CRITICAL: Clean up task state to prevent memory accumulation in high-frequency loops.
        
        Over 1000+ repeated cycles (select → download → view → send), state dictionaries
        would accumulate indefinitely without cleanup. This method removes cached data
        after a download completes to maintain stable memory footprint.
        
        ⚠️  IMPORTANT: Do NOT delete self._tasks[study_uid] - it's needed for retry operations!
        Keep the original task so users can retry the download after it completes.
        
        Args:
            study_uid: Study UID to clean up
        """
        try:
            # Clean up speed label widget reference
            if study_uid in self._speed_label_widgets:
                del self._speed_label_widgets[study_uid]
                logger.debug(f"   Cleared speed label widget for {study_uid[:40]}...")
            
            # Clean up speed tracking data
            if hasattr(self, '_last_speed_check_per_study') and study_uid in self._last_speed_check_per_study:
                del self._last_speed_check_per_study[study_uid]
            if hasattr(self, '_last_progress_per_study') and study_uid in self._last_progress_per_study:
                del self._last_progress_per_study[study_uid]
            
            # Continue with existing cleanup...
            # ✅ CRITICAL FIX: KEEP self._tasks for retry operations!
            # After a download completes, users may click "Retry" to re-download the same study.
            # If we delete the task, the retry operation fails silently because the task data is lost.
            # The task dictionary is the SOURCE OF TRUTH for download configuration.
            # It has no memory bloat - its size is proportional to series count, not loop iterations.
            # The actual memory bloat comes from intermediate caches below, which we DO clean up.
            
            # Remove from additional task info cache
            if study_uid in self._additional_task_info:
                del self._additional_task_info[study_uid]
                logger.debug(f"🗑️ Cleaned up _additional_task_info for {study_uid[:40]}...")
            
            # Remove from series image count cache
            if study_uid in self._series_image_count_cache:
                del self._series_image_count_cache[study_uid]
                logger.debug(f"🗑️ Cleaned up _series_image_count_cache for {study_uid[:40]}...")
            
            # Remove pending progress tracking
            if study_uid in self._pending_progress:
                del self._pending_progress[study_uid]
                logger.debug(f"🗑️ Cleaned up _pending_progress for {study_uid[:40]}...")
            
            # Remove completed series tracking (no longer needed after download)
            if study_uid in self._completed_series_emitted:
                del self._completed_series_emitted[study_uid]
                logger.debug(f"🗑️ Cleaned up _completed_series_emitted for {study_uid[:40]}...")
            
            # Remove last series number tracking
            if study_uid in self._last_series_number_by_study:
                del self._last_series_number_by_study[study_uid]
                logger.debug(f"🗑️ Cleaned up _last_series_number_by_study for {study_uid[:40]}...")
            
            logger.info(f"✅ Task state cleanup complete for {study_uid[:40]}... (preserved task for retry, cleaned intermediate caches)")
            
        except Exception as e:
            logger.warning(f"⚠️ Error during task state cleanup: {e}")

    def _on_worker_error(self, study_uid: str, error_message: str) -> None:
        """
        Handle worker error signal

        This ensures the pipeline doesn't get stuck on errors:
        1. Emit the failure signal
        2. Check for auto-resume (in case preempted downloads exist)
        3. Check for auto-retry (in case this download should retry)
        4. Start the next pending download
        """
        current_state = self.state_store.get(study_uid)
        _error_l = str(error_message or "").lower()
        _has_preemption_marker = (
            "preemption" in _error_l
            or "higher priority download" in _error_l
        )
        _is_user_cancel = "cancelled by user" in _error_l
        _is_classic_preemption = bool(
            current_state
            and current_state.status == DownloadStatus.PAUSED
            and current_state.is_auto_paused
        )
        _is_series_interrupt_preemption = bool(
            current_state
            and current_state.status in (
                DownloadStatus.PENDING,
                DownloadStatus.VALIDATING,
                DownloadStatus.DOWNLOADING,
            )
            and _has_preemption_marker
        )
        # Classic preemption: state was already flipped to PAUSED+is_auto_paused by the
        # coordinator/executor before the worker finished — no message marker needed.
        _is_expected_preemption = bool(
            (_has_preemption_marker or _is_classic_preemption) and not _is_user_cancel
        )
        if _is_expected_preemption:
            logger.info(
                f"Expected preemption worker completion for {study_uid[:40]}... "
                f"(classic={_is_classic_preemption}, series_interrupt={_is_series_interrupt_preemption}, "
                f"state={getattr(current_state, 'status', None)})"
            )
            self._check_auto_resume()
            QTimer.singleShot(0, self._start_next_pending)
            return
        logger.error(f"❌ [ERROR] Worker error: {study_uid[:40] if study_uid else 'None'}... - {error_message}")

        # Update state to FAILED before emitting signal
        self.state_store.update(
            study_uid,
            status=DownloadStatus.FAILED,
            error_message=error_message,
            is_auto_paused=False
        )
        logger.info(f"💾 [DATABASE] Updated study {study_uid[:40] if study_uid else 'None'}... to FAILED status due to error")

        # Log error to UI
        state = self.state_store.get(study_uid)
        patient_name = getattr(state, 'patient_name', 'Unknown') if state else 'Unknown'
        self.log_message(f"❌ [{study_uid[:10]}...] Download failed for {patient_name}: {error_message}")

        self.download_failed.emit(study_uid, error_message)

        # Check for auto-paused downloads that should auto-resume
        logger.info("   Checking auto-resume after error...")
        self._check_auto_resume()

        # Check for failed downloads that should auto-retry
        # This is critical for forward progress - don't get stuck!
        logger.info("   Checking auto-retry after error...")
        self._check_auto_retry()

        # Defer starting next pending to allow worker cleanup
        QTimer.singleShot(0, self._start_next_pending)

        # Log database update for error
        state = self.state_store.get(study_uid)
        if state:
            logger.info(f"💾 [DATABASE] Study {study_uid[:40] if study_uid else 'None'}... status: {state.status.value}, error: {error_message}")

    def _check_auto_resume(self) -> None:
        """
        Check for auto-paused downloads that should auto-resume (Rule R5)
        
        Auto-paused downloads (paused due to higher priority preemption) should
        automatically resume when the higher priority download completes.
        """
        try:
            # Do NOT auto-resume while a CRITICAL intent is still active.
            # This prevents HIGH/NORMAL downloads from bouncing back during
            # per-series CRITICAL preemption (viewer drag/drop or click).
            all_states = self.state_store.get_all()
            critical_active = any(
                (
                    s.status in [DownloadStatus.PENDING, DownloadStatus.VALIDATING, DownloadStatus.DOWNLOADING]
                    and (
                        s.priority == DownloadPriority.CRITICAL
                        or bool(getattr(s, 'viewed_series_number', None))
                    )
                )
                for s in all_states
            )
            if critical_active:
                logger.info("⏳ Auto-resume deferred: CRITICAL download/intent still active")
                return

            # Get all paused downloads
            paused = self.state_store.get_by_status(DownloadStatus.PAUSED)
            
            auto_paused_count = 0
            for state in paused:
                # Check if this was auto-paused (not manually paused by user)
                if state.is_auto_paused:
                    auto_paused_count += 1
                    logger.info(f"🔄 Auto-resuming {state.patient_name} (was auto-paused)")
                    
                    # Reset to PENDING for the queue processing
                    self.state_store.update(
                        state.study_uid,
                        status=DownloadStatus.PENDING,
                        is_auto_paused=False
                    )
            
            if auto_paused_count > 0:
                logger.info(f"✅ Auto-resumed {auto_paused_count} downloads that were preempted")
                
        except Exception as e:
            logger.error(f"❌ Error in auto-resume check: {e}")

    def _check_auto_retry(self) -> None:
        """
        Check for failed downloads that should auto-retry (Rule R28)
        
        Failed downloads with retry_count < MAX_RETRIES should automatically
        be re-queued for another attempt. This ensures forward progress.
        
        The system must not get stuck - failed downloads should retry until:
        1. They succeed (reach COMPLETED)
        2. They exceed MAX_RETRIES (then stay FAILED for manual intervention)
        """
        from ...core.constants import MAX_RETRIES
        
        try:
            # Get all failed downloads
            failed = self.state_store.get_by_status(DownloadStatus.FAILED)
            
            auto_retry_count = 0
            for state in failed:
                # Check if retry count allows another attempt
                if state.retry_count < MAX_RETRIES:
                    auto_retry_count += 1
                    logger.info(
                        f"🔄 Auto-retrying {state.patient_name} "
                        f"(retry {state.retry_count + 1}/{MAX_RETRIES})"
                    )
                    
                    # Increment retry count and move to PENDING for re-queue
                    self.state_store.update(
                        state.study_uid,
                        status=DownloadStatus.PENDING,
                        retry_count=state.retry_count + 1,
                        error_message=None  # Clear error for fresh attempt
                    )
                else:
                    logger.warning(
                        f"⚠️ {state.patient_name} exceeded max retries ({MAX_RETRIES}), "
                        f"requires manual intervention"
                    )
            
            if auto_retry_count > 0:
                logger.info(f"✅ Auto-queued {auto_retry_count} failed downloads for retry")
                
        except Exception as e:
            logger.error(f"❌ Error in auto-retry check: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _pipeline_health_check(self) -> None:
        """
        Periodic pipeline health check - ensures downloads never get stuck
        
        This is a BACKUP mechanism that runs every 5 seconds to ensure:
        1. If there are PENDING downloads and no active workers, start one
        2. If there are auto-paused downloads and no critical running, resume them
        3. If there are failed downloads that can retry, auto-retry them
        
        This guarantees forward progress even if something goes wrong with
        the normal completion/error handlers.
        """
        try:
            # Check current state
            active_count = self.worker_pool.get_active_count()
            pending = self.state_store.get_by_status(DownloadStatus.PENDING)
            downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
            paused = self.state_store.get_by_status(DownloadStatus.PAUSED)
            failed = self.state_store.get_by_status(DownloadStatus.FAILED)
            
            # Check if critical is running
            critical_running = [d for d in downloading if d.priority == DownloadPriority.CRITICAL]
            
            # Only log if there's something to check
            if pending or paused or failed:
                logger.debug(
                    f"🏥 Health check: active={active_count}, pending={len(pending)}, "
                    f"paused={len(paused)}, failed={len(failed)}"
                )
            
            # STUCK STATE 1: Pending downloads exist but no workers running
            if pending and active_count == 0 and not critical_running:
                logger.warning(
                    f"⚠️ Health check: {len(pending)} pending downloads but no workers! "
                    "Starting next pending..."
                )
                self._start_next_pending()
                return
            
            # STUCK STATE 2: Auto-paused downloads exist but no critical running
            auto_paused = [p for p in paused if p.is_auto_paused]
            if auto_paused and not critical_running and active_count == 0:
                logger.warning(
                    f"⚠️ Health check: {len(auto_paused)} auto-paused downloads but no critical running! "
                    "Triggering auto-resume..."
                )
                self._check_auto_resume()
                QTimer.singleShot(100, self._start_next_pending)
                return
            
            # STUCK STATE 3: Failed downloads that can retry but no workers running
            from ...core.constants import MAX_RETRIES
            retryable = [f for f in failed if f.retry_count < MAX_RETRIES]
            if retryable and active_count == 0:
                logger.warning(
                    f"⚠️ Health check: {len(retryable)} retryable failed downloads! "
                    "Triggering auto-retry..."
                )
                self._check_auto_retry()
                QTimer.singleShot(100, self._start_next_pending)
                return
                
        except Exception as e:
            logger.error(f"❌ Error in pipeline health check: {e}")

    def _start_next_pending(self) -> None:
        """
        Start next pending download using rule engine (Rules R4, R7, R15)
        
        Priority order: CRITICAL > HIGH > NORMAL > LOW
        Within same priority: LIFO (newest first)
        
        R2: Does NOT start lower priority downloads while Critical is running
        """
        try:
            # Check if worker pool has capacity
            can_add = self.worker_pool.can_add_worker()
            logger.info(f"📥 [START-NEXT] Worker pool can_add_worker: {can_add}")
            
            if not can_add:
                logger.info("📥 [START-NEXT] Worker pool at capacity, waiting...")
                return
            
            # R2: Check if a CRITICAL download is currently running
            # If so, don't start any other downloads (they should wait)
            downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
            critical_running = [d for d in downloading if d.priority == DownloadPriority.CRITICAL]
            
            if critical_running:
                logger.info(f"📥 [START-NEXT] Critical download running ({critical_running[0].patient_name[:20]}), not starting others")
                return
            
            # Use rule engine to get next download by priority (R4, R7, R15)
            logger.info("📥 [START-NEXT] Getting next download from rule engine...")
            next_download = self.rule_engine.get_next_download()
            logger.info(f"📥 [START-NEXT] Rule engine returned: {next_download}")
            
            if next_download:
                logger.info(f"📥 [START-NEXT] Starting next download: {next_download.patient_name} ({next_download.priority.name})")
                self._start_download_worker(next_download.study_uid)
            else:
                # List all states to see what's there
                all_states = self.state_store.get_all()
                pending_states = [s for s in all_states if s.status == DownloadStatus.PENDING]
                logger.info(f"📥 [START-NEXT] No pending downloads. Total states: {len(all_states)}, Pending: {len(pending_states)}")
                for s in all_states:
                    logger.info(f"   - {s.patient_name[:20]}: {s.status.value} ({s.priority.name})")
                
        except Exception as e:
            logger.error(f"❌ Error in start_next_pending: {e}")
            import traceback
            logger.error(traceback.format_exc())
