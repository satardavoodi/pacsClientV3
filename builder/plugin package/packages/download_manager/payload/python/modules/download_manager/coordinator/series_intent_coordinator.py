"""Series-intent coordination for Download Manager.

This module centralizes intent-driven priority decisions (viewer/open-tab actions)
so callers do not independently mutate queue state.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace
from typing import Callable, Dict, Optional

from ..core.enums import DownloadPriority, DownloadStatus, PreemptionAction

logger = logging.getLogger(__name__)

# F3.5.1 — env-gated verbose tracing. When 0 (default), only begin / recover /
# exhaust / started tags are emitted. When 1, every tick / defer is emitted as well.
_INTENT_TRACE_ENABLED = os.environ.get("AIPACS_INTENT_PRIORITY_TRACE", "0") == "1"
_INTENT_VERBOSE_TAGS = {"tick", "defer"}


def _intent_handoff_v2_enabled() -> bool:
    """Return True if the F3.5.2 wall-clock retry path is enabled.

    Defaults to False per ``INTENT_HANDOFF_V2_DEFAULT``. Override with
    ``AIPACS_INTENT_HANDOFF_V2=1`` (or 0) to flip per-process. Read at every
    chain start so tests can flip it without re-importing the module.
    """
    val = os.environ.get("AIPACS_INTENT_HANDOFF_V2")
    if val is None:
        try:
            from ..core.constants import INTENT_HANDOFF_V2_DEFAULT
            return bool(INTENT_HANDOFF_V2_DEFAULT)
        except Exception:
            return False
    return val.strip() == "1"


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
        # One active priority-start retry chain per study. Without this guard,
        # repeated viewed-series / CRITICAL requests can spawn overlapping
        # QTimer retry ladders for the same study, creating a control-plane
        # storm while the worker pool is still occupied.
        self._priority_retry_tokens: Dict[str, int] = {}
        self._priority_retry_seq = 0
        # F3.5.1 — wall-clock timestamp (time.monotonic seconds) of the moment
        # the retry chain began for each study. Drives elapsed_ms in
        # [INTENT_PRIORITY] log emissions and is the source of
        # overlap_priority_handoff_latency_ms in the KPI harness.
        self._priority_retry_started_ms: Dict[str, float] = {}

    def _defer(self, delay_ms: int, callback: Callable[[], None]) -> None:
        if self._defer_call is not None:
            self._defer_call(delay_ms, callback)
            return

        from PySide6.QtCore import QTimer

        QTimer.singleShot(delay_ms, callback)

    def _begin_priority_retry(self, study_uid: str) -> Optional[int]:
        existing = self._priority_retry_tokens.get(study_uid)
        if existing is not None:
            logger.debug(
                "[INTENT] Priority retry already active for %s (token=%s)",
                study_uid,
                existing,
            )
            return None

        self._priority_retry_seq += 1
        token = self._priority_retry_seq
        self._priority_retry_tokens[study_uid] = token
        # F3.5.1 — record begin timestamp BEFORE first emit so elapsed_ms is 0.
        self._priority_retry_started_ms[study_uid] = time.monotonic()
        return token

    def _clear_priority_retry(self, study_uid: str, token: Optional[int] = None) -> None:
        active = self._priority_retry_tokens.get(study_uid)
        if active is None:
            return
        if token is not None and active != token:
            return
        self._priority_retry_tokens.pop(study_uid, None)
        self._priority_retry_started_ms.pop(study_uid, None)

    def _emit_intent_priority(
        self,
        *,
        tag: str,
        study_uid: str,
        attempt: int = 0,
        max_attempts: int = 0,
        recovery: bool = False,
        pool_busy: bool = False,
        branch: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Emit a structured `[INTENT_PRIORITY]` log line for KPI harness parsing.

        Format (stable; round-tripped by tests/performance/test_priority_handoff_kpi_parser.py):
            [INTENT_PRIORITY] tag=<TAG> study=<UID40> series=<SN> attempt=<N>/<M>
              recovery=<BOOL> pool_busy=<BOOL> pool_capacity=<U>/<T> state=<S>
              auto_paused=<BOOL> elapsed_ms=<INT> token=<INT> [branch=<B>] [reason=<R>]

        F3.5.2 — `reason` field is appended to ``exhaust`` emissions of the V2
        wall-clock path (``pool_busy``, ``reclaimed``, ``state_lost``,
        ``timeout``). Legacy emissions never set it. Verbose tags (tick /
        defer) are suppressed unless AIPACS_INTENT_PRIORITY_TRACE=1.
        """
        if tag in _INTENT_VERBOSE_TAGS and not _INTENT_TRACE_ENABLED:
            return
        try:
            state = self.state_store.get(study_uid)
        except Exception:
            state = None
        started_ms = self._priority_retry_started_ms.get(study_uid)
        if started_ms is None:
            elapsed_ms = 0
        else:
            elapsed_ms = int((time.monotonic() - started_ms) * 1000)
        try:
            active = len(getattr(self.worker_pool, "active_workers", {}) or {})
            cap = int(getattr(self.worker_pool, "max_workers", 0))
        except Exception:
            active = 0
            cap = 0
        pool_capacity = f"{active}/{cap}"
        if state is not None:
            status_attr = getattr(state, "status", None)
            status = getattr(status_attr, "value", str(status_attr)) if status_attr is not None else "missing"
            auto = bool(getattr(state, "is_auto_paused", False))
            series = getattr(state, "viewed_series_number", None) or ""
        else:
            status = "missing"
            auto = False
            series = ""
        token = self._priority_retry_tokens.get(study_uid, 0)
        uid_short = (study_uid[:40] if study_uid else "") or ""
        parts = [
            f"[INTENT_PRIORITY] tag={tag}",
            f"study={uid_short}",
            f"series={series}",
            f"attempt={attempt}/{max_attempts}",
            f"recovery={recovery}",
            f"pool_busy={pool_busy}",
            f"pool_capacity={pool_capacity}",
            f"state={status}",
            f"auto_paused={auto}",
            f"elapsed_ms={elapsed_ms}",
            f"token={token}",
        ]
        if branch is not None:
            parts.append(f"branch={branch}")
        if reason is not None:
            parts.append(f"reason={reason}")
        logger.info(" ".join(parts), extra={"component": "download"})

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
        _token: Optional[int] = None,
    ) -> None:
        # F3.5.2 — fork to V2 wall-clock retry on chain entry when enabled.
        # Only fork on the *first* call (when the caller hasn't supplied a
        # token); continuation ticks of an in-flight legacy chain stay on
        # the legacy path even if the env flips mid-chain.
        if _token is None and _intent_handoff_v2_enabled():
            self._schedule_priority_start_retry_v2(study_uid)
            return
        if _token is None:
            _token = self._begin_priority_retry(study_uid)
            if _token is None:
                return
            # F3.5.1 — emit chain-begin marker (only on first entry).
            self._emit_intent_priority(
                tag="begin",
                study_uid=study_uid,
                attempt=0,
                max_attempts=max_retries,
                recovery=_recovery,
            )
        elif self._priority_retry_tokens.get(study_uid) != _token:
            logger.debug(
                "[INTENT] Ignoring stale retry callback for %s (token=%s active=%s)",
                study_uid,
                _token,
                self._priority_retry_tokens.get(study_uid),
            )
            return
        else:
            # Continued tick (token reused). Verbose-only.
            self._emit_intent_priority(
                tag="tick",
                study_uid=study_uid,
                attempt=_attempt,
                max_attempts=max_retries,
                recovery=_recovery,
            )

        if _attempt >= max_retries:
            state = self.state_store.get(study_uid)
            if state and state.status not in (DownloadStatus.PENDING, DownloadStatus.PAUSED):
                logger.info(
                    "[INTENT] Priority retry chain ended for %s (state=%s)",
                    study_uid,
                    state.status,
                )
                self._clear_priority_retry(study_uid, _token)
                return

            # v2.2.9.2 — schedule one deferred recovery round instead of giving up.
            # Covers the case where a dying worker takes >18 s to release its pool slot
            # (e.g. stuck in socket I/O).  Recovery round: 3 retries × 3 s after 5 s delay.
            if not _recovery:
                logger.info(
                    "[INTENT] Priority start retry entering recovery for %s after %s attempts",
                    study_uid,
                    max_retries,
                )
                # F3.5.1 — primary chain expired; entering recovery round.
                self._emit_intent_priority(
                    tag="recover",
                    study_uid=study_uid,
                    attempt=_attempt,
                    max_attempts=max_retries,
                    recovery=False,
                    branch="primary",
                )
                self._defer(
                    5000,
                    lambda _token=_token: self.schedule_priority_start_retry(
                        study_uid,
                        max_retries=3,
                        interval_ms=3000,
                        _attempt=0,
                        _recovery=True,
                        _token=_token,
                    ),
                )
            else:
                state_error_l = str(getattr(state, "error_message", "") or "").lower() if state else ""
                expected_preemption_window = bool(
                    state
                    and (
                        state.is_auto_paused
                        or "preemption" in state_error_l
                        or "higher priority" in state_error_l
                    )
                )
                if expected_preemption_window:
                    logger.info(
                        "[INTENT] Priority retry chain ended in expected preemption window for %s",
                        study_uid,
                    )
                else:
                    logger.warning(
                        "[INTENT] Priority start retry exhausted for %s after recovery attempts=%s",
                        study_uid,
                        max_retries,
                    )
                # F3.5.1 — recovery chain expired (always emit; branch=recovery).
                self._emit_intent_priority(
                    tag="exhaust",
                    study_uid=study_uid,
                    attempt=_attempt,
                    max_attempts=max_retries,
                    recovery=True,
                    branch="recovery",
                )
                self._clear_priority_retry(study_uid, _token)
            return

        state = self.state_store.get(study_uid)
        if not state:
            self._clear_priority_retry(study_uid, _token)
            return
        if state.status not in (DownloadStatus.PENDING, DownloadStatus.PAUSED):
            self._clear_priority_retry(study_uid, _token)
            return

        if self.worker_pool.can_add_worker():
            if state.status == DownloadStatus.PAUSED:
                self.state_store.update(study_uid, status=DownloadStatus.PENDING)

            started = self._start_download_worker(study_uid)
            if not started:
                # Slot reportedly free but start failed — likely reclamation race.
                self._emit_intent_priority(
                    tag="defer",
                    study_uid=study_uid,
                    attempt=_attempt,
                    max_attempts=max_retries,
                    recovery=_recovery,
                    pool_busy=False,
                )
                self._defer(
                    interval_ms,
                    lambda _token=_token: self.schedule_priority_start_retry(
                        study_uid,
                        max_retries,
                        interval_ms,
                        _attempt + 1,
                        _recovery,
                        _token,
                    ),
                )
            else:
                # F3.5.1 — success: record total handoff latency.
                self._emit_intent_priority(
                    tag="started",
                    study_uid=study_uid,
                    attempt=_attempt,
                    max_attempts=max_retries,
                    recovery=_recovery,
                )
                self._clear_priority_retry(study_uid, _token)
            return

        # Pool busy — defer and try again.
        self._emit_intent_priority(
            tag="defer",
            study_uid=study_uid,
            attempt=_attempt,
            max_attempts=max_retries,
            recovery=_recovery,
            pool_busy=True,
        )
        self._defer(
            interval_ms,
            lambda _token=_token: self.schedule_priority_start_retry(
                study_uid,
                max_retries,
                interval_ms,
                _attempt + 1,
                _recovery,
                _token,
            ),
        )

    # ────────────────────────────────────────────────────────────────────
    # F3.5.2 — V2 wall-clock priority-handoff retry
    # ────────────────────────────────────────────────────────────────────
    # Replaces the legacy 90-attempt × 200 ms primary chain followed by a
    # 5 s deferred 3-attempt × 3 s recovery chain with a single wall-clock
    # budget (default 60 s, INTENT_HANDOFF_HARD_TIMEOUT_MS). Ticks at
    # INTENT_HANDOFF_V2_INTERVAL_MS (default 250 ms). Detects the
    # reclamation-race condition where ``can_add_worker()`` reports True
    # but ``_start_download_worker`` returns False, and reports it via
    # ``reason=reclaimed`` on the eventual exhaust emission.
    #
    # Default-off via INTENT_HANDOFF_V2_DEFAULT (False). Enable per-process
    # with AIPACS_INTENT_HANDOFF_V2=1. Will flip to default-on in F3.5.4
    # after cross-PC baseline confirms the regression budget.
    def _schedule_priority_start_retry_v2(self, study_uid: str) -> None:
        token = self._begin_priority_retry(study_uid)
        if token is None:
            # Another retry chain (legacy or V2) is already active for this
            # study — defer to it.
            return
        # Read constants lazily so tests can monkeypatch them.
        try:
            from ..core.constants import (
                INTENT_HANDOFF_HARD_TIMEOUT_MS,
                INTENT_HANDOFF_V2_INTERVAL_MS,
            )
        except Exception:
            INTENT_HANDOFF_HARD_TIMEOUT_MS = 60000
            INTENT_HANDOFF_V2_INTERVAL_MS = 250

        self._emit_intent_priority(
            tag="begin",
            study_uid=study_uid,
            attempt=0,
            max_attempts=int(INTENT_HANDOFF_HARD_TIMEOUT_MS),
            recovery=False,
            branch="v2",
        )
        self._priority_retry_v2_tick(
            study_uid,
            token=token,
            attempt=0,
            hard_timeout_ms=int(INTENT_HANDOFF_HARD_TIMEOUT_MS),
            interval_ms=int(INTENT_HANDOFF_V2_INTERVAL_MS),
            last_branch=None,
        )

    def _priority_retry_v2_tick(
        self,
        study_uid: str,
        *,
        token: int,
        attempt: int,
        hard_timeout_ms: int,
        interval_ms: int,
        last_branch: Optional[str],
    ) -> None:
        if self._priority_retry_tokens.get(study_uid) != token:
            # Stale tick from a chain that was cancelled or replaced.
            return

        # Wall-clock deadline check (F3.5.2 core fix — no attempt count).
        started_ms = self._priority_retry_started_ms.get(study_uid)
        if started_ms is None:
            # Chain was cleared between defer and tick — exit silently.
            return
        elapsed_ms = (time.monotonic() - started_ms) * 1000.0
        if elapsed_ms >= hard_timeout_ms:
            reason = last_branch or "timeout"
            state = self.state_store.get(study_uid)
            state_error_l = str(getattr(state, "error_message", "") or "").lower() if state else ""
            expected_preemption_window = bool(
                state
                and (
                    getattr(state, "is_auto_paused", False)
                    or "preemption" in state_error_l
                    or "higher priority" in state_error_l
                )
            )
            if expected_preemption_window:
                logger.info(
                    "[INTENT] Priority retry V2 ended in expected preemption window for %s",
                    study_uid,
                )
            else:
                logger.warning(
                    "[INTENT] Priority retry V2 wall-clock budget exhausted for %s "
                    "(elapsed_ms=%d reason=%s)",
                    study_uid,
                    int(elapsed_ms),
                    reason,
                )
            self._emit_intent_priority(
                tag="exhaust",
                study_uid=study_uid,
                attempt=attempt,
                max_attempts=hard_timeout_ms,
                recovery=False,
                branch="v2",
                reason=reason,
            )
            self._clear_priority_retry(study_uid, token)
            return

        # State sanity check — exit if no longer schedulable.
        state = self.state_store.get(study_uid)
        if state is None:
            self._emit_intent_priority(
                tag="exhaust",
                study_uid=study_uid,
                attempt=attempt,
                max_attempts=hard_timeout_ms,
                recovery=False,
                branch="v2",
                reason="state_lost",
            )
            self._clear_priority_retry(study_uid, token)
            return
        if state.status not in (DownloadStatus.PENDING, DownloadStatus.PAUSED):
            # Worker started by another path or download terminal — done.
            self._clear_priority_retry(study_uid, token)
            return

        # Try start. Reclamation race: can_add says True but start fails.
        next_branch = last_branch
        try:
            can_add = self.worker_pool.can_add_worker()
        except Exception:
            can_add = False
        if can_add:
            # Flip PAUSED→PENDING via CAS so we never race a writer.
            if state.status == DownloadStatus.PAUSED:
                self.state_store.update_if_status(
                    study_uid,
                    DownloadStatus.PAUSED,
                    DownloadStatus.PENDING,
                    is_auto_paused=False,
                    error_message=None,
                )
            try:
                started = self._start_download_worker(study_uid)
            except Exception as exc:
                logger.warning(
                    "[INTENT] V2 start_download_worker raised for %s: %s",
                    study_uid,
                    exc,
                )
                started = False
            if started:
                self._emit_intent_priority(
                    tag="started",
                    study_uid=study_uid,
                    attempt=attempt,
                    max_attempts=hard_timeout_ms,
                    recovery=False,
                    branch="v2",
                )
                self._clear_priority_retry(study_uid, token)
                return
            # Reclamation race detected — slot reportedly free but start
            # failed. Could be the dying worker still releasing its slot,
            # or the rule engine deferred the start. Tag and continue
            # ticking; defer fall-through path will also nudge the
            # central scheduler.
            self._emit_intent_priority(
                tag="defer",
                study_uid=study_uid,
                attempt=attempt,
                max_attempts=hard_timeout_ms,
                recovery=False,
                pool_busy=False,
                branch="v2",
                reason="reclaimed",
            )
            next_branch = "reclaimed"
            # Nudge the scheduler in case _start_next_pending picks a
            # different study (e.g. R2 critical-running guard).
            try:
                self._defer(0, self._start_next_pending)
            except Exception:
                pass
        else:
            self._emit_intent_priority(
                tag="defer",
                study_uid=study_uid,
                attempt=attempt,
                max_attempts=hard_timeout_ms,
                recovery=False,
                pool_busy=True,
                branch="v2",
            )
            next_branch = "pool_busy"

        # Re-arm next tick.
        self._defer(
            interval_ms,
            lambda: self._priority_retry_v2_tick(
                study_uid,
                token=token,
                attempt=attempt + 1,
                hard_timeout_ms=hard_timeout_ms,
                interval_ms=interval_ms,
                last_branch=next_branch,
            ),
        )
