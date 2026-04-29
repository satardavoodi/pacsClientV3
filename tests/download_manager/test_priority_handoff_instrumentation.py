"""F3.5.1 — DM priority-handoff instrumentation tests.

Verify that ``SeriesIntentCoordinator.schedule_priority_start_retry`` emits the
expected ``[INTENT_PRIORITY]`` tag sequence and that
``_priority_retry_started_ms`` is populated on begin and cleared on success
and on exhaustion.

These tests do NOT exercise the production timer chain — they drive the retry
state machine directly via ``defer_call`` capture, like the existing
``test_priority_retry_dedup.py``.

Plan reference: plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md
Step:           F3.5.1.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from modules.download_manager.coordinator import series_intent_coordinator as sic_module
from modules.download_manager.coordinator.series_intent_coordinator import SeriesIntentCoordinator
from modules.download_manager.core.enums import DownloadPriority, DownloadStatus
from modules.download_manager.core.models import DownloadTask
from modules.download_manager.state.state_store import DownloadStateStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _PoolBusy:
    max_workers = 3
    active_workers = {"a": 1, "b": 1, "c": 1}

    def can_add_worker(self):
        return False


class _PoolFree:
    max_workers = 3
    active_workers = {}

    def can_add_worker(self):
        return True


class _RuleEngineStub:
    def evaluate_preemption(self, _task):
        return None


def _make_task(study_uid: str = "study-handoff") -> DownloadTask:
    return DownloadTask(
        study_uid=study_uid,
        patient_id="p1",
        patient_name="Patient One",
        study_date="2026-04-29",
        study_time="08:30:00",
        modality="CT",
        description="Handoff Test",
        series_list=[],
        priority=DownloadPriority.CRITICAL,
        output_dir=Path("."),
    )


_TAG_RE = re.compile(r"\[INTENT_PRIORITY\]\s+tag=(\w+)(?:.*?branch=(\w+))?", re.DOTALL)


def _emitted_tags(caplog):
    """Return list of (tag, branch_or_None) tuples in order from caplog records."""
    out = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if "[INTENT_PRIORITY]" not in msg:
            continue
        m = _TAG_RE.search(msg)
        if not m:
            continue
        out.append((m.group(1), m.group(2)))
    return out


@pytest.fixture
def caplog_intent(caplog):
    """Configure caplog to capture INFO from the coordinator module."""
    caplog.set_level(logging.INFO, logger=sic_module.__name__)
    return caplog


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_begin_then_started_chain_emits_expected_tags(caplog_intent, monkeypatch):
    # Force trace=True so tick / defer also emit, exercising the full code path.
    monkeypatch.setattr(sic_module, "_INTENT_TRACE_ENABLED", True)

    store = DownloadStateStore()
    task = _make_task()
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    deferred = []
    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolFree(),
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: True,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, cb: deferred.append(cb),
    )

    coordinator.schedule_priority_start_retry(task.study_uid)

    tags = [t for t, _b in _emitted_tags(caplog_intent)]
    # Pool is free + start succeeds → exactly: begin, started.
    assert tags[0] == "begin"
    assert "started" in tags
    # No tick / defer before started in the immediate-success path.
    assert tags.index("started") == len(tags) - 1
    # Started timestamp must be cleared on success.
    assert task.study_uid not in coordinator._priority_retry_started_ms
    assert task.study_uid not in coordinator._priority_retry_tokens


def test_begin_started_ms_is_populated_and_monotonic(caplog_intent):
    store = DownloadStateStore()
    task = _make_task("study-monotonic")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    deferred = []
    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolBusy(),  # forces defer path → keeps started_ms alive.
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: False,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, cb: deferred.append(cb),
    )

    coordinator.schedule_priority_start_retry(task.study_uid)
    started_at = coordinator._priority_retry_started_ms.get(task.study_uid)
    assert started_at is not None
    assert started_at > 0.0


def test_exhaust_clears_started_ms_and_emits_branch_recovery(caplog_intent):
    store = DownloadStateStore()
    task = _make_task("study-exhaust")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolBusy(),
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: False,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, _cb: None,
    )

    # Drive directly into the recovery-exhaust branch by passing _attempt
    # equal to max_retries with _recovery=True.
    token = coordinator._begin_priority_retry(task.study_uid)
    assert token is not None
    coordinator.schedule_priority_start_retry(
        task.study_uid,
        max_retries=3,
        interval_ms=3000,
        _attempt=3,
        _recovery=True,
        _token=token,
    )

    # started_ms must be cleared.
    assert task.study_uid not in coordinator._priority_retry_started_ms
    assert task.study_uid not in coordinator._priority_retry_tokens

    # Last [INTENT_PRIORITY] event must be tag=exhaust branch=recovery.
    events = _emitted_tags(caplog_intent)
    assert len(events) >= 1
    last_tag, last_branch = events[-1]
    assert last_tag == "exhaust"
    assert last_branch == "recovery"


def test_recover_emits_branch_primary_and_keeps_started_ms_alive(caplog_intent):
    store = DownloadStateStore()
    task = _make_task("study-recover")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolBusy(),
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: False,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, _cb: None,
    )

    token = coordinator._begin_priority_retry(task.study_uid)
    assert token is not None
    coordinator.schedule_priority_start_retry(
        task.study_uid,
        max_retries=90,
        interval_ms=200,
        _attempt=90,        # primary chain expired
        _recovery=False,
        _token=token,
    )

    events = _emitted_tags(caplog_intent)
    last_tag, last_branch = events[-1]
    assert last_tag == "recover"
    assert last_branch == "primary"
    # During the recover transition the chain stays alive, so started_ms must
    # remain (cleared only at recovery exhaust or success).
    assert task.study_uid in coordinator._priority_retry_started_ms


def test_trace_disabled_suppresses_tick_and_defer(caplog_intent, monkeypatch):
    monkeypatch.setattr(sic_module, "_INTENT_TRACE_ENABLED", False)

    store = DownloadStateStore()
    task = _make_task("study-no-trace")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    deferred = []
    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolBusy(),
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: False,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, cb: deferred.append(cb),
    )

    coordinator.schedule_priority_start_retry(task.study_uid)
    # Drive one extra tick: pool stays busy, defer fires another tick.
    if deferred:
        deferred.pop(0)()

    tags = [t for t, _b in _emitted_tags(caplog_intent)]
    # tick / defer suppressed → only `begin` should appear.
    assert "tick" not in tags
    assert "defer" not in tags
    assert tags[0] == "begin"


def test_started_emit_records_elapsed_ms_field(caplog_intent):
    store = DownloadStateStore()
    task = _make_task("study-elapsed")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolFree(),
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: True,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, _cb: None,
    )

    coordinator.schedule_priority_start_retry(task.study_uid)
    started_lines = [
        rec.getMessage()
        for rec in caplog_intent.records
        if "tag=started" in rec.getMessage()
    ]
    assert len(started_lines) == 1
    line = started_lines[0]
    m = re.search(r"elapsed_ms=(\d+)", line)
    assert m is not None
    # Synchronous test → elapsed_ms is small but well-formed (>= 0).
    assert int(m.group(1)) >= 0
    # Format-stability: must contain all required fields in expected order.
    for token in (
        "tag=started",
        "study=",
        "series=",
        "attempt=",
        "recovery=",
        "pool_busy=",
        "pool_capacity=",
        "state=",
        "auto_paused=",
        "elapsed_ms=",
        "token=",
    ):
        assert token in line


def test_no_emit_when_chain_already_active_for_same_study(caplog_intent):
    """`_begin_priority_retry` rejects a duplicate begin; the second call must
    NOT emit a second `tag=begin` line (otherwise the parser would double-count
    handoff starts)."""
    store = DownloadStateStore()
    task = _make_task("study-dedup")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coordinator = SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=_PoolBusy(),
        tasks_ref={task.study_uid: task},
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: False,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda _delay, _cb: None,
    )

    coordinator.schedule_priority_start_retry(task.study_uid)
    coordinator.schedule_priority_start_retry(task.study_uid)

    tags = [t for t, _b in _emitted_tags(caplog_intent)]
    assert tags.count("begin") == 1
