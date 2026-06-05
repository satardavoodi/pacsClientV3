"""Priority & coordination: critical series, viewed series, preemption"""
# Auto-generated from main_widget.py — Phase 2 split



import logging
import time

from PySide6.QtCore import Signal, Qt, QTimer

from ...core.enums import DownloadPriority, DownloadStatus
from ...core.models import DownloadTask, DownloadState
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class _DMPriorityMixin:
    """Priority & coordination: critical series, viewed series, preemption"""

    def _find_object_request_context(self, series_uid: str):
        """Return ``(study_uid, series_info)`` for a FAST object request."""
        uid = str(series_uid or "").strip()
        if not uid:
            return None
        for study_uid, task in dict(getattr(self, '_tasks', {}) or {}).items():
            for series_info in getattr(task, 'series_list', []) or []:
                if str(getattr(series_info, 'series_uid', '') or '') == uid:
                    return str(study_uid), series_info
        return None

    def _object_file_path_for(self, study_uid: str, series_number: str, slice_index: int):
        """Map a zero-based viewer slice index to the current local DICOM path."""
        try:
            instance_no = max(1, int(slice_index) + 1)
        except Exception:
            instance_no = 1
        return (
            self.base_output_dir
            / str(study_uid)
            / str(series_number)
            / f"Instance_{instance_no:04d}.dcm"
        )

    def has_object(self, series_uid: str, slice_index: int) -> bool:
        """ObjectCache hook: true when the requested slice file is local."""
        ctx = self._find_object_request_context(series_uid)
        if ctx is None:
            return False
        study_uid, series_info = ctx
        path = self._object_file_path_for(
            study_uid,
            str(getattr(series_info, 'series_number', '') or ''),
            int(slice_index),
        )
        try:
            return bool(path.exists())
        except Exception:
            return False

    def request_object(self, priority: int, series_uid: str, slice_index: int) -> bool:
        """ObjectCache hook: promote the owning series when a stack target is missing.

        The current socket protocol downloads by series/batch, not arbitrary SOP
        object.  This method therefore turns P0/P1 stack object requests into the
        strongest safe intent available today: mark the owning series CRITICAL
        and trigger the existing series retry/start path, with debounce so drag
        events cannot flood the Download Manager.
        """
        ctx = self._find_object_request_context(series_uid)
        if ctx is None:
            return False

        study_uid, series_info = ctx
        series_number = str(getattr(series_info, 'series_number', '') or '')
        if not series_number:
            return False
        if self.has_object(series_uid, slice_index):
            return True

        try:
            pri = int(priority)
        except Exception:
            pri = 4
        # P0 can refresh intent a little sooner; P1+ requests collapse harder.
        min_interval_s = 0.25 if pri <= 0 else 0.75
        now = time.monotonic()
        last_map = getattr(self, '_fast_object_request_last_s', None)
        if last_map is None:
            last_map = {}
            self._fast_object_request_last_s = last_map
        key = (str(study_uid), series_number)
        last_t = float(last_map.get(key, 0.0) or 0.0)
        if now - last_t < min_interval_s:
            return False
        last_map[key] = now

        try:
            self.intent_coordinator.request_critical_series(study_uid, series_number)
        except Exception as exc:
            logger.debug(
                "[FAST-OBJECT] critical-series intent failed study=%s series=%s slice=%s: %s",
                study_uid[:40],
                series_number,
                slice_index,
                exc,
            )
            return False

        try:
            state = self.state_store.get(study_uid)
            current_series = str(getattr(state, 'current_series_number', '') or '') if state else ''
            is_active = bool(getattr(state, 'is_active', False)) if state else False
            if (not is_active or current_series != series_number) and hasattr(self, '_on_series_retry'):
                self._on_series_retry(study_uid, series_number, str(series_uid or ''))
        except Exception as exc:
            logger.debug(
                "[FAST-OBJECT] series retry hint failed study=%s series=%s slice=%s: %s",
                study_uid[:40],
                series_number,
                slice_index,
                exc,
            )

        logger.debug(
            "[FAST-OBJECT] requested study=%s series=%s slice=%s priority=%s",
            study_uid[:40],
            series_number,
            slice_index,
            pri,
        )
        return True

    def start_priority_download_immediately(
        self,
        study_data: Dict,
        server_info: Dict = None,
        priority: str = "Critical",
        clicked_series_number: str = None
    ) -> bool:
        """
        START A HIGH-PRIORITY DOWNLOAD IMMEDIATELY (for double-click patient opening)

        This method:
        1. Pauses all active downloads
        2. Adds/updates the study in queue with high priority
        3. Starts the download immediately

        Args:
            study_data: Dict with patient/study info (study_uid, patient_name, patient_id, series, etc.)
            server_info: Server connection info (optional)
            priority: Priority level ("Critical" or "High")
            clicked_series_number: Series number that was clicked (for priority ordering)

        Returns:
            True if download started successfully
        """
        import time
        start_time = time.time()

        try:
            study_uid = study_data.get('study_uid')
            patient_name = study_data.get('patient_name', 'Unknown')

            logger.info(f"⚡ [PRIORITY-DOWNLOAD] Starting priority download: {patient_name[:25]} (priority={priority})")

            # ========== STEP 1: CREATE TASK FOR VALIDATION ==========
            # Map priority string to enum
            priority_map = {
                "Critical": DownloadPriority.CRITICAL,
                "High": DownloadPriority.HIGH,
                "Normal": DownloadPriority.NORMAL,
                "Low": DownloadPriority.LOW
            }
            priority_enum = priority_map.get(priority, DownloadPriority.CRITICAL)

            # Convert series data to SeriesInfo objects
            series_list = study_data.get('series', [])
            series_info_list = []
            for s in series_list:
                from ...core.models import SeriesInfo
                series_info = SeriesInfo(
                    series_uid=s.get('series_uid', ''),
                    series_number=s.get('series_number', ''),
                    series_description=s.get('series_description', ''),
                    modality=s.get('modality', ''),
                    image_count=s.get('image_count', 0)
                )
                series_info_list.append(series_info)

            # Create task for validation
            task = DownloadTask(
                study_uid=study_uid,
                patient_id=study_data.get('patient_id', ''),
                patient_name=patient_name,
                study_date=study_data.get('study_date', ''),
                study_time=study_data.get('study_time', study_data.get('time', '')),
                description=study_data.get('study_description', ''),
                modality=study_data.get('modality', ''),
                series_list=series_info_list,
                priority=priority_enum,  # Set the priority on the task
                output_dir=(self.base_output_dir / study_uid) if study_uid else None,
                # Complete patient information for database insertion
                patient_age=study_data.get('patient_age', study_data.get('age', '')),
                patient_sex=study_data.get('patient_sex', study_data.get('sex', '')),
                patient_birth_date=study_data.get('patient_birth_date', study_data.get('birth_date', '')),
                body_part=study_data.get('body_part', study_data.get('body_part_examined', '')),
                institution_name=study_data.get('institution_name', '')
            )

            # ========== STEP 2: VALIDATE WITH RULE ENGINE (R17) ==========
            # Enhanced R17 checks BOTH StateStore AND Database for completed downloads
            logger.info(f"🔍 [VALIDATION] Validating download with rule engine...")
            can_add = self.rule_engine.can_add_download(task)

            if not can_add.allowed:
                # R17 rejected - study already exists or completed
                metadata = can_add.metadata or {}

                # ── RESUME PATH: incomplete download in StateStore ──
                if metadata.get('should_resume'):
                    logger.info(
                        f"🔄 [VALIDATION] Incomplete download detected — resuming: {can_add.reason}"
                    )
                    # Fall through to STEP 3+ so the download is re-triggered.
                    # The existing state will be reset to PENDING in STEP 4.

                elif metadata.get('should_load_local'):
                    # Study is completed in database - signal caller to load from local files
                    logger.info(f"✅ [VALIDATION] {can_add.reason} - Viewer will load from local files")
                    return False  # Don't proceed with download
                else:
                    # Other rejection reason - suppress if already completed (expected)
                    if "already exists" not in can_add.reason.lower() or "completed" not in can_add.reason.lower():
                        logger.warning(f"⚠️ [VALIDATION] Cannot add download: {can_add.reason}")
                    else:
                        logger.debug(f"🔍 [VALIDATION] Download already complete: {study_uid[:40]}...")
                    return False  # Don't proceed with download

            # ========== STEP 3: PAUSE ALL ACTIVE DOWNLOADS ==========
            logger.info(f"⏸️ [PRIORITY-DOWNLOAD] Pausing all active downloads...")
            self._pause_all_active_downloads()

            # ========== STEP 4: ADD/UPDATE IN QUEUE ==========
            # Check if study already exists in state (after R17 passed)
            existing_state = self.state_store.get(study_uid)

            if existing_state:
                # Update existing - set priority and reset status
                logger.info(f"🔄 [PRIORITY-DOWNLOAD] Existing study - updating priority to {priority}")
                self.state_store.update(
                    study_uid,
                    priority=priority_enum,
                    status=DownloadStatus.PENDING,
                    # Reset per-series state so the downloader re-evaluates all
                    # series from scratch (files on disk are still checked via R20)
                    completed_series=[],
                    skipped_series=[],
                    failed_series=[],
                    downloaded_count=0,
                    progress_percent=0.0,
                )
                # Ensure the latest task is available for the worker
                self._tasks[study_uid] = task
                logger.info(f"💾 [DATABASE] Updated study {study_uid[:40]}... priority to {priority}, status to PENDING")
            else:
                # Create new download state
                logger.info(f"➕ [PRIORITY-DOWNLOAD] Creating new download task")

                # Store task and create state
                self._tasks[study_uid] = task
                
                # Store additional task information for display
                if not hasattr(self, '_additional_task_info'):
                    self._additional_task_info = {}
                self._additional_task_info[study_uid] = {
                    'patient_age': study_data.get('patient_age', study_data.get('age', '')),
                    'patient_sex': study_data.get('patient_sex', study_data.get('sex', '')),
                    'patient_birth_date': study_data.get('patient_birth_date', study_data.get('birth_date', '')),
                    'study_time': study_data.get('study_time', study_data.get('time', '')),
                    'body_part': study_data.get('body_part', study_data.get('body_part_examined', '')),
                    'modality': study_data.get('modality', '')
                }
                logger.info(f"💾 [ADDITIONAL-INFO] Stored additional info: {self._additional_task_info[study_uid]}")
                
                self.state_store.create(task)
                logger.info(f"💾 [DATABASE] Created new study {study_uid[:40]}... with priority {priority}")

            # ========== STEP 4b: SET VIEWED SERIES IF SPECIFIED ==========
            # If a specific series was clicked (not just patient double-click),
            # mark that series as viewed so it downloads first.
            if clicked_series_number:
                self.set_viewed_series(study_uid, str(clicked_series_number))

            # ========== STEP 5: REFRESH UI ==========
            logger.info(f"🔄 [UI] Refreshing UI after priority download setup...")
            # Rebuild is coalesced — observers from state_store.create + set_viewed_series
            # already queued coalesced rebuilds; this merges with those (no-op if one pending).
            self.refresh_table_order()
            QTimer.singleShot(0, lambda: self._select_study_row(study_uid))

            # ========== STEP 6: START DOWNLOAD IMMEDIATELY ==========
            logger.info(f"🚀 [PRIORITY-DOWNLOAD] Starting download worker...")
            started = self._start_download_worker(study_uid)

            elapsed = (time.time() - start_time) * 1000
            if started:
                logger.info(f"✅ [PRIORITY-DOWNLOAD] Priority download started in {elapsed:.0f}ms for {study_uid[:40]}...")
            else:
                # Pool is at capacity — the old worker will stop shortly (cancel flag set).
                # Schedule a retry poll so the new study starts the moment a slot opens
                # instead of waiting for _start_next_pending to be triggered by worker completion.
                logger.info(
                    f"⏳ [PRIORITY-DOWNLOAD] Pool at capacity — scheduling deferred start retry "
                    f"for {study_uid[:40]}..."
                )
                self.intent_coordinator.schedule_priority_start_retry(study_uid)

            return started

        except Exception as e:
            logger.error(f"❌ [PRIORITY-DOWNLOAD] Error in start_priority_download_immediately: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def _schedule_priority_start_retry(
        self,
        study_uid: str,
        max_retries: int = 60,
        interval_ms: int = 500,
        _attempt: int = 0,
    ) -> None:
        """
        Poll for a free worker-pool slot and start the priority download worker
        as soon as one becomes available.

        Called only when ``start_priority_download_immediately`` could not start
        the worker immediately because the pool was at capacity (the old worker
        is still winding down its current batch after receiving the cancel flag).

        Each attempt is scheduled with ``QTimer.singleShot`` so the Qt event
        loop is never blocked.
        """
        self.intent_coordinator.schedule_priority_start_retry(
            study_uid,
            max_retries=max_retries,
            interval_ms=interval_ms,
            _attempt=_attempt,
        )

    def set_viewed_series(self, study_uid: str, series_number: str) -> None:
        """
        Mark a specific series as the one being actively viewed.

        Priority rules:
        - The viewed series becomes CRITICAL (highest download priority).
        - All other series of the same patient remain HIGH.
        - The SeriesDownloader will reorder remaining series so the
          viewed one downloads first (if not already complete).

        Called from home_ui._handle_priority_download_from_thumbnail()
        when the user clicks a series thumbnail in the viewer.

        Args:
            study_uid: Study Instance UID
            series_number: The series number now being viewed
        """
        try:
            state = self.state_store.get(study_uid)
            if not state:
                logger.warning(f"⚠️ [VIEWED-SERIES] No state for {study_uid[:40]} – ignoring")
                return

            old_viewed = state.viewed_series_number
            if old_viewed == str(series_number):
                logger.debug(f"[VIEWED-SERIES] Series {series_number} already marked as viewed")
                return

            # Delegate to coordinator for atomic intent application.
            self.intent_coordinator.request_critical_series(study_uid, str(series_number))

            logger.info(
                f"⚡ [VIEWED-SERIES] Study {study_uid[:40]}… series {series_number} → CRITICAL "
                f"(was viewing: {old_viewed or 'none'})"
            )
            # NOTE: Do NOT call _refresh_table_order() here (Phase 1A).
            # request_critical_series() above updates state → UIObserver fires
            # refresh_table_order() (deferred + coalesced) which handles the rebuild.
            # Adding a direct sync call here caused ~400-540ms main-thread stall per drag-drop.

        except Exception as e:
            logger.error(f"❌ [VIEWED-SERIES] Error setting viewed series: {e}")

    def request_critical_series_download(
        self,
        study_uid: str,
        series_number: str,
        series_uid: str = None,
    ) -> None:
        """Single entry-point for viewer-driven critical-series requests.

        This is the preferred public API for FAST/ADV viewer interactions.
        It atomically applies CRITICAL intent and starts series retry.

        Preempt-on-drag (DM-H3): with MAX_CONCURRENT_STUDIES=1, if a *different*
        study currently holds the single download slot, gracefully preempt it
        (auto-pause-for-resume) so the dragged series' study can take the slot and
        load now — otherwise the CRITICAL series just waits out the priority-handoff
        retry chain behind the slot-holder. Do NOT preempt when this study is
        already the active worker or the slot is idle (avoid needless churn).
        """
        try:
            try:
                active_workers = list(self.worker_pool.get_all_workers() or [])
            except Exception:
                active_workers = []
            other_holds_slot = any(
                str((w[0] if isinstance(w, (list, tuple)) else w) or '').strip()
                not in ('', str(study_uid or '').strip())
                for w in active_workers
            )
            if other_holds_slot:
                logger.info(
                    "🚀 [VIEWED-SERIES] A different study holds the download slot — "
                    "preempting so dragged series of %s can load", str(study_uid)[:40]
                )
                self._pause_all_active_downloads()

            self.intent_coordinator.request_critical_series(study_uid, str(series_number))
            self._on_series_retry(study_uid, series_number, series_uid)
        except Exception as e:
            logger.error(f"❌ [VIEWED-SERIES] Error requesting critical series download: {e}")

    def clear_viewed_series(self, study_uid: str) -> None:
        """
        Clear the viewed-series flag (e.g. when the tab is closed or
        the series download completes).  The study priority drops back
        to HIGH unless no patient tab is open, in which case NORMAL.

        Args:
            study_uid: Study Instance UID
        """
        try:
            state = self.state_store.get(study_uid)
            if not state:
                return

            if state.viewed_series_number is None:
                return  # Nothing to clear

            cleared = self.intent_coordinator.clear_series_intent(study_uid)
            if cleared:
                logger.info(
                    f"🔽 [VIEWED-SERIES] Cleared viewed series for {study_uid[:40]}… → HIGH"
                )

        except Exception as e:
            logger.error(f"❌ [VIEWED-SERIES] Error clearing viewed series: {e}")

    def _pause_downloads_for_preemption(self, study_uids: List[str]) -> None:
        """
        Pause a targeted set of active downloads without blocking the UI thread.

        Used for HIGH/NORMAL priority promotions where only lower-priority active
        downloads should be interrupted.
        """
        try:
            for paused_uid in dict.fromkeys(study_uids or []):
                state = self.state_store.get(paused_uid)
                if not state or state.status not in [DownloadStatus.DOWNLOADING, DownloadStatus.VALIDATING]:
                    continue

                worker = self.worker_pool.get_worker(paused_uid)
                if worker:
                    worker.request_cancel()
                    logger.info(f"⏸️ [PREEMPT] Cancel requested for worker: {paused_uid[:40]}...")

                self.state_store.update(
                    paused_uid,
                    status=DownloadStatus.PAUSED,
                    is_auto_paused=True,
                )
                logger.info(
                    f"💾 [PREEMPT] State updated to PAUSED (auto_paused=True) for {paused_uid[:40]}..."
                )

        except Exception as e:
            logger.error(f"❌ [PREEMPT] Error pausing targeted downloads: {e}")

    def _negotiate_priority_change(self, study_uid: str, new_priority: DownloadPriority) -> None:
        """
        Apply queue negotiation after a priority change.

        A priority change must not remain cosmetic: if a viewer/user raises
        priority and a lower-priority download is active, the scheduler should
        non-blockingly preempt the lower-priority work and give the promoted study
        a fair chance to run next.
        """
        self.intent_coordinator.negotiate_priority_change(study_uid, new_priority)

    def _pause_all_active_downloads(self) -> None:
        """
        Pause all active downloads to make room for priority download.
        
        R2: Critical pauses ALL other downloads.
        
        This method:
        1. Requests cancellation on all active workers (sets cancel flag)
        2. Stops all workers via worker pool
        3. Updates all downloading states to PAUSED with is_auto_paused=True
        
        The cancellation will propagate: Worker → Executor → SeriesDownloader → SocketClient
        Each component checks the cancel flag and stops gracefully.
        """
        try:
            # Ground truth for active work is the worker pool, not only state status.
            # In some flows the state can temporarily lag (e.g., still PENDING) while
            # a subprocess worker is actively downloading; relying only on status then
            # misses cancellation and CRITICAL preemption appears to be ignored.
            active_workers = self.worker_pool.get_all_workers()
            active_worker_uids = [uid for uid, _ in active_workers]

            # Keep state-based view for logging and state normalization.
            downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
            validating = self.state_store.get_by_status(DownloadStatus.VALIDATING)
            state_active_uids = {s.study_uid for s in (downloading + validating)}

            # Union: any worker actually running OR any state marked active.
            to_pause_uids = list(dict.fromkeys(active_worker_uids + list(state_active_uids)))

            if not to_pause_uids:
                logger.info("⏸️ [PAUSE-ALL] No active downloads/workers to pause")
                return

            logger.info(
                f"⏸️ [PAUSE-ALL] Pausing downloads: workers={len(active_worker_uids)}, "
                f"state_active={len(state_active_uids)}, total_unique={len(to_pause_uids)}"
            )

            # Request cancel by active workers first (fast path).
            for study_uid, worker in active_workers:
                try:
                    if worker:
                        worker.request_cancel()
                        logger.info(f"⏸️ [PAUSE-ALL] Cancel requested for active worker: {study_uid[:40]}...")
                except Exception as e:
                    logger.warning(f"⚠️ [PAUSE-ALL] Failed requesting cancel for {study_uid[:40]}...: {e}")

            # Normalize state to auto-paused so queue rules can resume later.
            for study_uid in to_pause_uids:
                state = self.state_store.get(study_uid)
                if not state:
                    continue
                if state.status in [DownloadStatus.COMPLETED, DownloadStatus.CANCELLED]:
                    continue

                if state.status != DownloadStatus.PAUSED or not state.is_auto_paused:
                    self.state_store.update(
                        study_uid,
                        status=DownloadStatus.PAUSED,
                        is_auto_paused=True
                    )
                    logger.info(
                        f"💾 [DATABASE] State updated to PAUSED (auto_paused=True) for {study_uid[:40]}..."
                    )

            # Also signal all workers to cancel (non-blocking — workers clean
            # themselves up via their ``finished`` signal).  Do NOT call
            # stop_all() here — it blocks the main thread for up to 5s per
            # worker, which freezes the UI.
            logger.info("🛑 [PAUSE-ALL] Requesting non-blocking cancel on worker pool...")
            self.worker_pool.cancel_all_non_blocking()
            logger.info("✅ [PAUSE-ALL] Cancel requested (workers will stop asynchronously)")

        except Exception as e:
            logger.error(f"❌ [PAUSE-ALL] Error pausing downloads: {e}")
            import traceback
            logger.error(traceback.format_exc())
