"""
FAST-UX performance budget: all thumbnail state operations must complete within
CPU-only time budgets used in the pipeline latency spec.

The [FAST-UX] and [FAST-THUMB-STATE] logs emitted in production confirm wall-clock
timing; this suite enforces the per-call contracts in CI.
"""
import time
import pytest

from modules.viewer.fast import ui_throttle


def test_noncritical_open_network_deferred_under_heavy_download(monkeypatch):
    monkeypatch.setattr(ui_throttle, "is_heavy_download_active", lambda grace_ms=750.0: True)
    assert ui_throttle.should_defer_noncritical_open_network(first_series_visible=False)


def test_noncritical_open_network_not_deferred_after_first_series(monkeypatch):
    monkeypatch.setattr(ui_throttle, "is_heavy_download_active", lambda grace_ms=750.0: True)
    assert not ui_throttle.should_defer_noncritical_open_network(first_series_visible=True)


def test_noncritical_open_network_not_deferred_without_heavy_download(monkeypatch):
    monkeypatch.setattr(ui_throttle, "is_heavy_download_active", lambda grace_ms=750.0: False)
    assert not ui_throttle.should_defer_noncritical_open_network(first_series_visible=False)


def test_noncritical_open_network_uses_current_download_state(monkeypatch):
    states = iter([True, False])
    monkeypatch.setattr(ui_throttle, "is_heavy_download_active", lambda grace_ms=750.0: next(states))
    assert ui_throttle.should_defer_noncritical_open_network(first_series_visible=False)
    assert not ui_throttle.should_defer_noncritical_open_network(first_series_visible=False)

_SINGLE_CALL_BUDGET_MS = 5.0     # < 5 ms per state call
_100_UPDATES_BUDGET_MS = 200.0   # < 200 ms for 100 progress updates
_100_REGISTER_BUDGET_MS = 50.0   # < 50 ms for 100 thumbnail registrations
_FULL_LIFECYCLE_BUDGET_MS = 15.0 # < 15 ms for full pending→downloading→complete


def test_start_series_download_under_budget(tm):
    tm.register_series(1)
    t0 = time.perf_counter()
    tm.start_series_download(1)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < _SINGLE_CALL_BUDGET_MS, (
        f"start_series_download took {elapsed_ms:.2f} ms (budget {_SINGLE_CALL_BUDGET_MS} ms)"
    )


def test_update_series_progress_under_budget(tm):
    tm.register_series(1)
    tm.start_series_download(1)
    t0 = time.perf_counter()
    tm.update_series_progress(1, 50.0)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < _SINGLE_CALL_BUDGET_MS, (
        f"update_series_progress took {elapsed_ms:.2f} ms (budget {_SINGLE_CALL_BUDGET_MS} ms)"
    )


def test_complete_series_download_under_budget(tm):
    tm.register_series(1)
    tm.start_series_download(1)
    t0 = time.perf_counter()
    tm.complete_series_download(1)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < _SINGLE_CALL_BUDGET_MS, (
        f"complete_series_download took {elapsed_ms:.2f} ms (budget {_SINGLE_CALL_BUDGET_MS} ms)"
    )


def test_100_progress_updates_total_under_budget(tm):
    """100 rapid progress calls for one series must finish within budget."""
    tm.register_series(1)
    tm.start_series_download(1)
    t0 = time.perf_counter()
    for pct in range(101):
        tm.update_series_progress(1, float(pct))
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < _100_UPDATES_BUDGET_MS, (
        f"100 progress updates took {elapsed_ms:.2f} ms (budget {_100_UPDATES_BUDGET_MS} ms)"
    )


def test_register_100_series_under_budget(tm):
    """Registering 100 series must complete within the overview budget."""
    t0 = time.perf_counter()
    for sn in range(1, 101):
        tm.register_series(sn)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < _100_REGISTER_BUDGET_MS, (
        f"Registering 100 series took {elapsed_ms:.2f} ms (budget {_100_REGISTER_BUDGET_MS} ms)"
    )


def test_full_lifecycle_under_budget(tm):
    """Complete pending→downloading→(progress×10)→complete lifecycle under budget."""
    tm.register_series(1)
    t0 = time.perf_counter()
    tm.start_series_download(1)
    for p in range(0, 101, 10):
        tm.update_series_progress(1, float(p))
    tm.complete_series_download(1)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < _FULL_LIFECYCLE_BUDGET_MS, (
        f"Full lifecycle took {elapsed_ms:.2f} ms (budget {_FULL_LIFECYCLE_BUDGET_MS} ms)"
    )


def test_10_series_concurrent_progress_stream_under_budget(tm):
    """Progress stream across 10 series (10 updates each = 100 ops) under budget."""
    for sn in range(1, 11):
        tm.register_series(sn)
        tm.start_series_download(sn)

    t0 = time.perf_counter()
    for _ in range(10):
        for sn in range(1, 11):
            tm.update_series_progress(sn, 50.0)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < _100_UPDATES_BUDGET_MS, (
        f"10-series progress stream took {elapsed_ms:.2f} ms (budget {_100_UPDATES_BUDGET_MS} ms)"
    )
