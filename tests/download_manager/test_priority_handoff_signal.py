"""F3.5.3 — Priority-handoff failure UX guardrail tests.

Verify that ``SeriesIntentCoordinator`` invokes registered failure callbacks
exactly once per exhaust event, with the correct ``reason`` for each of the
4 V2 exhaust paths plus the legacy recovery exhaust, and that the public
register/unregister API is idempotent and isolation-safe.

These tests drive the retry state machine directly via ``defer_call``
capture, like ``test_priority_handoff_v2.py``. They never rely on real Qt
timers and never instantiate the DM widget (Qt-free).

Plan reference: plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md
Step:           F3.5.3.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from modules.download_manager.coordinator import series_intent_coordinator as sic_module
from modules.download_manager.coordinator.series_intent_coordinator import (
    SeriesIntentCoordinator,
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


def _make_task(study_uid: str) -> DownloadTask:
    return DownloadTask(
        study_uid=study_uid,
        patient_id="p1",
        patient_name="Patient One",
        study_date="2026-04-29",
        study_time="08:30:00",
        modality="CT",
        description="Handoff F3.5.3 Test",
        series_list=[],
        priority=DownloadPriority.CRITICAL,
        output_dir=Path("."),
    )


def _make_coord(store, pool, tasks, *, started=False, defer_log=None):
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


@pytest.fixture
def v2_enabled(monkeypatch):
    monkeypatch.setenv("AIPACS_INTENT_HANDOFF_V2", "1")
    yield


@pytest.fixture
def v2_disabled(monkeypatch):
    monkeypatch.setenv("AIPACS_INTENT_HANDOFF_V2", "0")
    yield


@pytest.fixture
def caplog_intent(caplog):
    caplog.set_level(logging.INFO, logger=sic_module.__name__)
    return caplog


# ---------------------------------------------------------------------------
# API surface tests
# ---------------------------------------------------------------------------

def test_register_callback_idempotent():
    """Registering the same callback twice must not double-fire."""
    store = DownloadStateStore()
    coord, _ = _make_coord(store, _PoolFree(), {})
    cb_calls = []

    def cb(uid, sn, reason):
        cb_calls.append((uid, sn, reason))

    coord.register_priority_handoff_failed_callback(cb)
    coord.register_priority_handoff_failed_callback(cb)  # duplicate ignored

    coord._emit_priority_handoff_failed("study-x", "timeout")

    assert len(cb_calls) == 1
    assert cb_calls[0] == ("study-x", "", "timeout")


def test_unregister_callback_no_op_when_missing():
    """Unregistering a callback that was never registered must not raise."""
    store = DownloadStateStore()
    coord, _ = _make_coord(store, _PoolFree(), {})
    coord.unregister_priority_handoff_failed_callback(lambda *_: None)  # no-op


def test_callback_isolation_one_raises_others_still_fire():
    """A buggy callback must not block sibling callbacks."""
    store = DownloadStateStore()
    coord, _ = _make_coord(store, _PoolFree(), {})
    calls = []

    def bad(_uid, _sn, _reason):
        raise RuntimeError("boom")

    def good(uid, sn, reason):
        calls.append((uid, sn, reason))

    coord.register_priority_handoff_failed_callback(bad)
    coord.register_priority_handoff_failed_callback(good)
    coord._emit_priority_handoff_failed("study-y", "pool_busy")

    assert calls == [("study-y", "", "pool_busy")]


def test_callback_passes_viewed_series_number():
    """Callback receives series_number from state.viewed_series_number."""
    store = DownloadStateStore()
    task = _make_task("study-z")
    store.create(task)
    store.update(task.study_uid, viewed_series_number="42")
    coord, _ = _make_coord(store, _PoolFree(), {task.study_uid: task})

    received = []
    coord.register_priority_handoff_failed_callback(
        lambda uid, sn, r: received.append((uid, sn, r))
    )
    coord._emit_priority_handoff_failed(task.study_uid, "reclaimed")

    assert received == [(task.study_uid, "42", "reclaimed")]


# ---------------------------------------------------------------------------
# Exhaust path: V2 timeout (each of 4 reasons reach _emit_priority_handoff_failed)
# ---------------------------------------------------------------------------

def _drive_v2_to_timeout(coord, study_uid, *, monkeypatch):
    """Simulate the wall-clock budget being exceeded on the next tick."""
    # Force time.monotonic to jump past the hard timeout window.
    started = coord._priority_retry_started_ms.get(study_uid)
    assert started is not None
    monkeypatch.setattr(
        sic_module.time,
        "monotonic",
        lambda _started=started: _started + 1_000_000.0,  # +1Ms
    )


@pytest.mark.parametrize(
    "pool_state, last_branch, expected_reason",
    [
        ("busy", None, "timeout"),           # last_branch never set → reason=timeout
        ("busy", "pool_busy", "pool_busy"),  # last_branch=pool_busy carried over
        ("free_fail", "reclaimed", "reclaimed"),  # reclamation race recorded last_branch
    ],
)
def test_v2_exhaust_callback_fires_with_reason(
    v2_enabled, monkeypatch, pool_state, last_branch, expected_reason
):
    """V2 wall-clock exhaust must fire callback with the carried reason."""
    store = DownloadStateStore()
    task = _make_task(f"study-v2-exhaust-{expected_reason}")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    pool = _PoolBusy() if pool_state == "busy" else _PoolFree()
    started = False  # always fail to start (free_fail case = reclamation race)
    coord, _defer = _make_coord(store, pool, {task.study_uid: task}, started=started)

    received = []
    coord.register_priority_handoff_failed_callback(
        lambda uid, sn, r: received.append((uid, sn, r))
    )

    # Begin chain (records started_ms via _begin_priority_retry).
    token = coord._begin_priority_retry(task.study_uid)
    assert token is not None
    # Force the wall-clock check to fire on the very next tick by jumping
    # monotonic forward past the hard timeout.
    _drive_v2_to_timeout(coord, task.study_uid, monkeypatch=monkeypatch)

    # Drive the tick directly with the parametrized last_branch so we
    # exercise the reason carry-over deterministically.
    coord._priority_retry_v2_tick(
        task.study_uid,
        token=token,
        attempt=1,
        hard_timeout_ms=60000,
        interval_ms=250,
        last_branch=last_branch,
    )

    assert len(received) == 1
    rx_uid, _rx_sn, rx_reason = received[0]
    assert rx_uid == task.study_uid
    assert rx_reason == expected_reason


def test_v2_exhaust_state_lost_fires_callback(v2_enabled, monkeypatch):
    """When state vanishes mid-tick, exhaust(reason=state_lost) fires callback."""
    store = DownloadStateStore()
    task = _make_task("study-v2-state-lost")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, _defer = _make_coord(store, _PoolBusy(), {task.study_uid: task}, started=False)

    received = []
    coord.register_priority_handoff_failed_callback(
        lambda uid, sn, r: received.append((uid, sn, r))
    )

    token = coord._begin_priority_retry(task.study_uid)
    assert token is not None
    # Now delete the state to trigger the state_lost branch on the tick.
    store.remove(task.study_uid)
    coord._priority_retry_v2_tick(
        task.study_uid,
        token=token,
        attempt=1,
        hard_timeout_ms=60000,
        interval_ms=250,
        last_branch=None,
    )

    assert len(received) == 1
    assert received[0][2] == "state_lost"


def test_v2_exhaust_skipped_in_expected_preemption_window(v2_enabled, monkeypatch):
    """Auto-paused study at exhaust must NOT fire UX callback (false-positive guard)."""
    store = DownloadStateStore()
    task = _make_task("study-v2-autopaused")
    store.create(task)
    store.update(
        task.study_uid,
        status=DownloadStatus.PAUSED,
        is_auto_paused=True,
        error_message="Paused due to higher priority download",
    )

    coord, _defer = _make_coord(store, _PoolBusy(), {task.study_uid: task}, started=False)

    received = []
    coord.register_priority_handoff_failed_callback(
        lambda uid, sn, r: received.append((uid, sn, r))
    )

    token = coord._begin_priority_retry(task.study_uid)
    assert token is not None
    _drive_v2_to_timeout(coord, task.study_uid, monkeypatch=monkeypatch)
    coord._priority_retry_v2_tick(
        task.study_uid,
        token=token,
        attempt=1,
        hard_timeout_ms=60000,
        interval_ms=250,
        last_branch="pool_busy",
    )

    # Callback must NOT have fired.
    assert received == []


# ---------------------------------------------------------------------------
# Exhaust path: legacy recovery
# ---------------------------------------------------------------------------

def test_legacy_recovery_exhaust_fires_callback(v2_disabled, caplog_intent):
    """Legacy chain recovery exhaust → callback(reason='recovery_exhausted')."""
    store = DownloadStateStore()
    task = _make_task("study-legacy-exhaust")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, _defer = _make_coord(store, _PoolBusy(), {task.study_uid: task}, started=False)

    received = []
    coord.register_priority_handoff_failed_callback(
        lambda uid, sn, r: received.append((uid, sn, r))
    )

    # Drive directly to the recovery-exhausted code path.
    coord.schedule_priority_start_retry(
        task.study_uid,
        max_retries=3,
        interval_ms=3000,
        _attempt=3,  # at-or-past max
        _recovery=True,
        _token=coord._begin_priority_retry(task.study_uid),
    )

    assert len(received) == 1
    assert received[0][0] == task.study_uid
    assert received[0][2] == "recovery_exhausted"


def test_legacy_recovery_exhaust_skipped_in_expected_preemption(v2_disabled):
    """Legacy recovery exhaust on auto-paused study must NOT fire UX callback."""
    store = DownloadStateStore()
    task = _make_task("study-legacy-autopaused")
    store.create(task)
    store.update(
        task.study_uid,
        status=DownloadStatus.PAUSED,
        is_auto_paused=True,
        error_message="Paused due to preemption",
    )

    coord, _defer = _make_coord(store, _PoolBusy(), {task.study_uid: task}, started=False)

    received = []
    coord.register_priority_handoff_failed_callback(
        lambda uid, sn, r: received.append((uid, sn, r))
    )

    coord.schedule_priority_start_retry(
        task.study_uid,
        max_retries=3,
        interval_ms=3000,
        _attempt=3,
        _recovery=True,
        _token=coord._begin_priority_retry(task.study_uid),
    )

    assert received == []


# ---------------------------------------------------------------------------
# Exhaust path: success / non-exhaust paths must NOT fire callback
# ---------------------------------------------------------------------------

def test_success_path_does_not_fire_callback(v2_enabled):
    """Successful immediate start → no callback fires."""
    store = DownloadStateStore()
    task = _make_task("study-v2-ok")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, _defer = _make_coord(store, _PoolFree(), {task.study_uid: task}, started=True)

    received = []
    coord.register_priority_handoff_failed_callback(
        lambda uid, sn, r: received.append((uid, sn, r))
    )

    coord._schedule_priority_start_retry_v2(task.study_uid)
    assert received == []


# ---------------------------------------------------------------------------
# Manual retry forces V2 path even when env=0 (DM widget contract)
# ---------------------------------------------------------------------------

def test_manual_retry_forces_v2_path_when_env_off(v2_disabled, caplog_intent):
    """Direct call to _schedule_priority_start_retry_v2 must run V2 regardless of env.

    This is the contract the DM widget's `retry_stalled_priority` relies on
    so that a user click guarantees V2 wall-clock semantics even when the
    default-off ship gate is in effect.
    """
    store = DownloadStateStore()
    task = _make_task("study-manual-retry")
    store.create(task)
    store.update(task.study_uid, status=DownloadStatus.PENDING)

    coord, _defer = _make_coord(store, _PoolFree(), {task.study_uid: task}, started=True)
    coord._schedule_priority_start_retry_v2(task.study_uid)

    branches = []
    for rec in caplog_intent.records:
        msg = rec.getMessage()
        if "[INTENT_PRIORITY]" not in msg:
            continue
        for tok in msg.split():
            if tok.startswith("branch="):
                branches.append(tok.split("=", 1)[1])
    assert branches and all(b == "v2" for b in branches), (
        f"manual retry must use V2 branch tag, got branches={branches}"
    )
