"""Series-intent coordination for Download Manager.

This module centralizes intent-driven priority decisions (viewer/open-tab actions)
so callers do not independently mutate queue state.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Callable, Dict, Optional

from ..core.enums import DownloadPriority, DownloadStatus, PreemptionAction

logger = logging.getLogger(__name__)


class SeriesIntentCoordinator:
    """Coordinate viewer/patient intent with scheduler state transitions."""

    def __init__(
        self,
        *,
        state_store,
        rule_engine,
        worker_pool,
        tasks_ref: Dict,
        pause_downloads_for_preemption: Callable[[list], None],
        start_download_worker: Callable[[str], bool],
        start_next_pending: Callable[[], None],
        refresh_table_order: Callable[[], None],
        check_auto_resume: Callable[[], None],
        defer_call: Optional[Callable[[int, Callable[[], None]], None]] = None,
        queue_recheck_ms: int = 50,
    ):
        self.state_store = state_store
        self.rule_engine = rule_engine
        self.worker_pool = worker_pool
        self._tasks = tasks_ref

        self._pause_downloads_for_preemption = pause_downloads_for_preemption
        self._start_download_worker = start_download_worker
        self._start_next_pending = start_next_pending
        self._refresh_table_order = refresh_table_order
        self._check_auto_resume = check_auto_resume
        self._defer_call = defer_call
        self._queue_recheck_ms = queue_recheck_ms

    def _defer(self, delay_ms: int, callback: Callable[[], None]) -> None:
        if self._defer_call is not None:
            self._defer_call(delay_ms, callback)
            return

        from PySide6.QtCore import QTimer

        QTimer.singleShot(delay_ms, callback)

    def request_study_priority(self, study_uid: str, priority: DownloadPriority) -> bool:
        state = self.state_store.get(study_uid)
        if not state:
            return False

        self.state_store.update(study_uid, priority=priority)
        self.negotiate_priority_change(study_uid, priority)
        return True

    def request_critical_series(self, study_uid: str, series_number: str) -> bool:
        state = self.state_store.get(study_uid)
        if not state:
            logger.warning("[INTENT] Study state not found for critical series request: %s", study_uid)
            return False

        updates = {"viewed_series_number": str(series_number)}
        if state.priority != DownloadPriority.CRITICAL:
            updates["priority"] = DownloadPriority.CRITICAL

        self.state_store.update(study_uid, **updates)

        task = self._tasks.get(study_uid)
        if task and task.priority != DownloadPriority.CRITICAL:
            self._tasks[study_uid] = replace(task, priority=DownloadPriority.CRITICAL)

        # If the study is currently DOWNLOADING a different series than the one
        # requested, cancel the worker so it restarts with the viewed series
        # first.  Without this, the user must wait for the entire current series
        # to finish before the viewed series begins downloading.
        current_series = getattr(state, 'current_series_number', None)
        if (
            state.status == DownloadStatus.DOWNLOADING
            and current_series
            and str(current_series) != str(series_number)
        ):
            logger.info(
                "[INTENT] Series interrupt: study=%s downloading series %s "
                "but viewer requested series %s — cancelling worker",
                study_uid[:40], current_series, series_number,
            )
            self._pause_downloads_for_preemption([study_uid])
            # Override PAUSED→PENDING so _start_next_pending picks it up
            self.state_store.update(
                study_uid,
                status=DownloadStatus.PENDING,
                is_auto_paused=False,
                error_message=None,
            )

        self.negotiate_priority_change(study_uid, DownloadPriority.CRITICAL)
        self._refresh_table_order()
        return True

    def clear_series_intent(self, study_uid: str) -> bool:
        state = self.state_store.get(study_uid)
        if not state or state.viewed_series_number is None:
            return False

        self.state_store.update(
            study_uid,
            viewed_series_number=None,
            priority=DownloadPriority.HIGH,
        )

        self._refresh_table_order()
        self._check_auto_resume()

        self._defer(100, self._start_next_pending)
        return True

    def negotiate_priority_change(self, study_uid: str, new_priority: DownloadPriority) -> None:
        state = self.state_store.get(study_uid)
        if not state:
            return

        task = self._tasks.get(study_uid)
        preemption_result = None
        if task:
            try:
                task = replace(task, priority=new_priority)
                self._tasks[study_uid] = task
                preemption_result = self.rule_engine.evaluate_preemption(task)
            except Exception as exc:
                logger.warning("[INTENT] Preemption evaluation failed for %s: %s", study_uid, exc)

        if preemption_result:
            if preemption_result.action == PreemptionAction.PAUSE_ALL:
                others_to_pause = [
                    uid for uid in preemption_result.affected_downloads if uid != study_uid
                ]
                if others_to_pause:
                    self._pause_downloads_for_preemption(others_to_pause)
            elif preemption_result.action == PreemptionAction.PREEMPT_LOWER and preemption_result.affected_downloads:
                self._pause_downloads_for_preemption(preemption_result.affected_downloads)

        refreshed = self.state_store.get(study_uid)
        if refreshed and refreshed.status == DownloadStatus.PAUSED and refreshed.is_auto_paused:
            self.state_store.update(
                study_uid,
                status=DownloadStatus.PENDING,
                is_auto_paused=False,
                error_message=None,
            )

        should_schedule = False
        refreshed = self.state_store.get(study_uid)
        if refreshed and refreshed.status == DownloadStatus.PENDING:
            should_schedule = True
        if preemption_result and preemption_result.affected_downloads:
            should_schedule = True

        if should_schedule:
            # Try immediate start if a worker slot is available — avoids
            # the 50ms deferred delay for the common case where preemption
            # just freed a slot.
            started_immediately = False
            try:
                if self.worker_pool.can_add_worker():
                    refreshed = self.state_store.get(study_uid)
                    if refreshed and refreshed.status == DownloadStatus.PENDING:
                        started_immediately = self._start_download_worker(study_uid)
            except Exception:
                pass

            if not started_immediately:
                self._defer(self._queue_recheck_ms, self._start_next_pending)
                # Backup: if pool is still occupied when _start_next_pending fires,
                # the retry poller will keep trying until a slot opens.
                self.schedule_priority_start_retry(study_uid)

    def schedule_priority_start_retry(
        self,
        study_uid: str,
        max_retries: int = 90,
        interval_ms: int = 200,
        _attempt: int = 0,
        _recovery: bool = False,
    ) -> None:
        if _attempt >= max_retries:
            logger.warning(
                "[INTENT] Priority start retry exhausted for %s after %s attempts",
                study_uid,
                max_retries,
            )
            # v2.2.9.2 — schedule one deferred recovery round instead of giving up.
            # Covers the case where a dying worker takes >18 s to release its pool slot
            # (e.g. stuck in socket I/O).  Recovery round: 3 retries × 3 s after 5 s delay.
            if not _recovery:
                self._defer(
                    5000,
                    lambda: self.schedule_priority_start_retry(
                        study_uid,
                        max_retries=3,
                        interval_ms=3000,
                        _attempt=0,
                        _recovery=True,
                    ),
                )
            return

        state = self.state_store.get(study_uid)
        if not state:
            return
        if state.status not in (DownloadStatus.PENDING, DownloadStatus.PAUSED):
            return

        if self.worker_pool.can_add_worker():
            if state.status == DownloadStatus.PAUSED:
                self.state_store.update(study_uid, status=DownloadStatus.PENDING)

            started = self._start_download_worker(study_uid)
            if not started:
                self._defer(
                    interval_ms,
                    lambda: self.schedule_priority_start_retry(
                        study_uid,
                        max_retries,
                        interval_ms,
                        _attempt + 1,
                        _recovery,
                    ),
                )
            return

        self._defer(
            interval_ms,
            lambda: self.schedule_priority_start_retry(
                study_uid,
                max_retries,
                interval_ms,
                _attempt + 1,
                _recovery,
            ),
        )
