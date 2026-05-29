"""F3.5.2 — DM priority-handoff V2 wall-clock retry tests.

Verify the V2 path replaces the legacy 90×200 ms primary + 3×3000 ms recovery
chains with a single wall-clock budget, and that reclamation-race detection
emits ``reason=reclaimed``.

These tests drive the retry state machine directly via ``defer_call``
capture, like ``test_priority_handoff_instrumentation.py``. They never rely
on real Qt timers.

Plan reference: plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md
Step:           F3.5.2.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from modules.download_manager.coordinator import series_intent_coordinator as sic_module
from modules.download_manager.coordinator.series_intent_coordinator import (
    SeriesIntentCoordinator,
    _intent_handoff_v2_enabled,
)
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


def _make_task(study_uid: str = "study-v2") -> DownloadTask:
    return DownloadTask(
        study_uid=study_uid,
        patient_id="p1",
        patient_name="Patient One",
        study_date="2026-04-29",
        study_time="08:30:00",
        modality="CT",
        description="Handoff V2 Test",
        series_list=[],
        priority=DownloadPriority.CRITICAL,
        output_dir=Path("."),
    )


_TAG_RE = re.compile(
    r"\[INTENT_PRIORITY\]\s+tag=(?P<tag>\w+).*?(?:branch=(?P<branch>\w+))?"
    r"(?:\s+reason=(?P<reason>\w+))?\s*$"
)


def _emitted(caplog):
    """Return list of (tag, branch, reason) tuples in order."""
    out = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if "[INTENT_PRIORITY]" not in msg:
            continue
        # Parse fields manually for robustness.
        d = {}
        for tok in msg.split():
            if "=" in tok:
                k, _, v = tok.partition("=")
                d[k] = v
        out.append((d.get("tag"), d.get("branch"), d.get("reason")))
    return out


@pytest.fixture
def caplog_intent(caplog):
    caplog.set_level(logging.INFO, logger=sic_module.__name__)
    return caplog


@pytest.fixture
def v2_enabled(monkeypatch):
    monkeypatch.setenv("AIPACS_INTENT_HANDOFF_V2", "1")
    assert _intent_handoff_v2_enabled() is True
    yield


@pytest.fixture
def v2_disabled(monkeypatch):
    monkeypatch.setenv("AIPACS_INTENT_HANDOFF_V2", "0")
    assert _intent_handoff_v2_enabled() is False
    yield


def _make_coord(store, pool, tasks, *, started=False, defer_log=None):
    """Create a coordinator wired for direct-tick driving.

    `started` controls what `_start_download_worker` returns. `defer_log`
    captures (delay, callback) tuples without firing them.
    """
    if defer_log is None:
        defer_log = []
    return SeriesIntentCoordinator(
        state_store=store,
        rule_engine=_RuleEngineStub(),
        worker_pool=pool,
        tasks_ref=tasks,
        pause_downloads_for_preemption=lambda _uids: None,
        start_download_worker=lambda _uid: started,
        start_next_pending=lambda: None,
        refresh_table_order=lambda: None,
        check_auto_resume=lambda: None,
        defer_call=lambda d, cb: defer_log.append((d, cb)),
    ), defer_log


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_v2_env_default_off():
    """When env is unset, V2 must default to off (default-off ship gate)."""
    import os as _os
    saved = _os.environ.pop("AIPACS_INTENT_HANDOFF_V2", None)
    try:
        assert _intent_handoff_v2_enabled() is False
    finally:
        if saved is not None:
            _os.environ["AIPACS_INTENT_HANDOFF_V2"] = saved


def test_v2_off_uses_legacy_chain(v2_disabled, caplog_intent):
    """With env=0, schedule_priority_start_retry must use the legacy 90+3 chain.

    Detect by checking that no `branch=v2` ever appears.
    """
    store = DownloadStateStore()
    task = _make_task("study-legacy-mode")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, _defer = _make_coord(store, _PoolBusy(), {task.study_uid: task}, started=False)
    coord.schedule_priority_start_retry(task.study_uid)

    events = _emitted(caplog_intent)
    branches = [b for _t, b, _r in events if b]
    assert "v2" not in branches, f"Legacy chain leaked V2 branch tag: {events}"


def test_v2_immediate_start_emits_branch_v2(v2_enabled, caplog_intent):
    """Pool free + start succeeds → begin(branch=v2), started(branch=v2)."""
    store = DownloadStateStore()
    task = _make_task("study-v2-success")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, _defer = _make_coord(store, _PoolFree(), {task.study_uid: task}, started=True)
    coord.schedule_priority_start_retry(task.study_uid)

    events = _emitted(caplog_intent)
    tags = [t for t, _b, _r in events]
    branches = [b for _t, b, _r in events if b]
    assert tags[0] == "begin"
    assert tags[-1] == "started"
    assert all(b == "v2" for b in branches)
    # Cleared on success.
    assert task.study_uid not in coord._priority_retry_started_ms
    assert task.study_uid not in coord._priority_retry_tokens


def test_v2_pool_busy_defers_and_continues(v2_enabled, caplog_intent, monkeypatch):
    """Pool busy on every tick → defer(branch=v2,pool_busy=True), no exhaust until budget hit."""
    # Force trace=True so defer emissions are visible.
    monkeypatch.setattr(sic_module, "_INTENT_TRACE_ENABLED", True)

    store = DownloadStateStore()
    task = _make_task("study-v2-busy")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, defers = _make_coord(store, _PoolBusy(), {task.study_uid: task}, started=False)
    coord.schedule_priority_start_retry(task.study_uid)

    # Drive 3 ticks — must keep deferring, never exhaust (budget = 60 s,
    # ticks at 250 ms wall-clock → many iterations before exhaust).
    for _ in range(3):
        assert defers, "Expected V2 to schedule next tick"
        _delay, cb = defers.pop()
        cb()

    events = _emitted(caplog_intent)
    tags = [t for t, _b, _r in events]
    assert "begin" in tags
    assert "defer" in tags
    assert "exhaust" not in tags  # not yet — wall-clock budget not hit
    # Started_ms still alive (chain in flight).
    assert task.study_uid in coord._priority_retry_started_ms


def test_v2_reclamation_race_emits_reason_reclaimed(v2_enabled, caplog_intent, monkeypatch):
    """can_add_worker=True but start_download_worker=False → defer(reason=reclaimed)."""
    monkeypatch.setattr(sic_module, "_INTENT_TRACE_ENABLED", True)

    store = DownloadStateStore()
    task = _make_task("study-v2-reclaim")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, defers = _make_coord(store, _PoolFree(), {task.study_uid: task}, started=False)
    coord.schedule_priority_start_retry(task.study_uid)

    events = _emitted(caplog_intent)
    # Must contain a defer with reason=reclaimed, branch=v2.
    reclaim_events = [(t, b, r) for t, b, r in events if r == "reclaimed"]
    assert reclaim_events, f"Expected reason=reclaimed defer; got {events}"
    tag, branch, reason = reclaim_events[0]
    assert tag == "defer"
    assert branch == "v2"
    # And we must be re-armed (next tick scheduled).
    assert defers, "V2 reclamation race must continue ticking"


def test_v2_wall_clock_exhaust_emits_reason(v2_enabled, caplog_intent, monkeypatch):
    """Force wall-clock budget exhaustion by setting started_ms far in the past."""
    import time as _time

    store = DownloadStateStore()
    task = _make_task("study-v2-budget")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, defers = _make_coord(store, _PoolBusy(), {task.study_uid: task}, started=False)
    coord.schedule_priority_start_retry(task.study_uid)

    # Rewind started_ms to make the next tick exceed the 60 s budget.
    coord._priority_retry_started_ms[task.study_uid] = _time.monotonic() - 120.0

    # Pop the next-tick callback and fire it.
    assert defers, "Expected V2 to schedule next tick"
    _d, cb = defers.pop()
    cb()

    events = _emitted(caplog_intent)
    exhaust = [(t, b, r) for t, b, r in events if t == "exhaust"]
    assert exhaust, f"Expected exhaust emission; got {events}"
    tag, branch, reason = exhaust[-1]
    assert branch == "v2"
    # reason should be one of the propagated values: pool_busy, reclaimed, or timeout.
    assert reason in ("pool_busy", "reclaimed", "timeout"), f"got reason={reason!r}"
    # State cleaned up on exhaust.
    assert task.study_uid not in coord._priority_retry_started_ms
    assert task.study_uid not in coord._priority_retry_tokens


def test_v2_state_lost_emits_reason_state_lost(v2_enabled, caplog_intent):
    """If state vanishes mid-chain, exhaust with reason=state_lost."""
    store = DownloadStateStore()
    task = _make_task("study-v2-state-lost")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, defers = _make_coord(store, _PoolBusy(), {task.study_uid: task}, started=False)
    coord.schedule_priority_start_retry(task.study_uid)

    # Pop the next-tick callback before we delete the state.
    assert defers
    _d, cb = defers.pop()

    # Erase state to simulate state_lost path.
    store._states.pop(task.study_uid, None)

    cb()

    events = _emitted(caplog_intent)
    exhaust = [(t, b, r) for t, b, r in events if t == "exhaust"]
    assert exhaust, f"Expected exhaust emission; got {events}"
    _t, branch, reason = exhaust[-1]
    assert branch == "v2"
    assert reason == "state_lost"


def test_v2_paused_status_is_cas_promoted(v2_enabled, caplog_intent):
    """If state is PAUSED + can_add_worker → CAS promote to PENDING + start."""
    store = DownloadStateStore()
    task = _make_task("study-v2-paused")
    store.create(task)
    # Start as DOWNLOADING then transition through PAUSED (legal path).
    store.update(task.study_uid, status=DownloadStatus.DOWNLOADING)
    store.update(task.study_uid, status=DownloadStatus.PAUSED, is_auto_paused=True)

    coord, _defer = _make_coord(store, _PoolFree(), {task.study_uid: task}, started=True)
    coord.schedule_priority_start_retry(task.study_uid)

    events = _emitted(caplog_intent)
    tags = [t for t, _b, _r in events]
    assert "started" in tags, f"PAUSED→PENDING CAS path should reach started: {events}"
    # The state should have been flipped to a non-PAUSED status by CAS.
    refreshed = store.get(task.study_uid)
    assert refreshed.status != DownloadStatus.PAUSED
    assert refreshed.is_auto_paused is False


def test_update_if_status_cas_helper():
    """state_store.update_if_status correctly applies/rejects based on expected."""
    store = DownloadStateStore()
    task = _make_task("study-cas")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    # Wrong expected → no change.
    ok = store.update_if_status(
        task.study_uid, DownloadStatus.PAUSED, DownloadStatus.DOWNLOADING
    )
    assert ok is False
    assert store.get(task.study_uid).status == DownloadStatus.PENDING

    # Correct expected → applied.
    ok = store.update_if_status(
        task.study_uid, DownloadStatus.PENDING, DownloadStatus.DOWNLOADING
    )
    assert ok is True
    assert store.get(task.study_uid).status == DownloadStatus.DOWNLOADING

    # Unknown study_uid → False.
    ok = store.update_if_status("does-not-exist", DownloadStatus.PENDING, DownloadStatus.DOWNLOADING)
    assert ok is False
