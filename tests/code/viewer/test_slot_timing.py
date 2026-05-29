"""Behavior tests for `modules.viewer.fast.slot_timing` (G6).

Covers:
  * Decorator wraps function transparently.
  * Threshold-gated emit (no log when fast + idle).
  * Drag-active threshold is lower than idle threshold.
  * Env-disabled is a no-op.
  * Exception in wrapped fn does NOT swallow the original exception.
  * Exception in `extra_factory` is swallowed (observability never breaks
    the wrapped function).
  * `time_slot` context manager emits on exit, even on exception.
"""
from __future__ import annotations

import logging
import os
import time

import pytest

from modules.viewer.fast import slot_timing as st


@pytest.fixture
def capture_log(monkeypatch):
    """Capture INFO log records on the slot_timing logger."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    log = logging.getLogger("aipacs.viewer.slot_timing")
    handler = _Capture(level=logging.INFO)
    prev_level = log.level
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    yield records
    log.removeHandler(handler)
    log.setLevel(prev_level)


@pytest.fixture
def force_idle(monkeypatch):
    """Force `_resolve_drag_active()` to return False."""
    monkeypatch.setattr(st, "_resolve_drag_active", lambda: False)


@pytest.fixture
def force_drag(monkeypatch):
    """Force `_resolve_drag_active()` to return True."""
    monkeypatch.setattr(st, "_resolve_drag_active", lambda: True)


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    """Reset env to defaults for each test."""
    for k in (
        "AIPACS_SLOT_TIMING_TRACE",
        "AIPACS_SLOT_TIMING_THRESHOLD_MS",
        "AIPACS_SLOT_TIMING_DRAG_THRESHOLD_MS",
    ):
        monkeypatch.delenv(k, raising=False)


def test_is_slot_timing_enabled_default_on():
    assert st.is_slot_timing_enabled() is True


def test_is_slot_timing_enabled_disabled_via_env(monkeypatch):
    monkeypatch.setenv("AIPACS_SLOT_TIMING_TRACE", "0")
    assert st.is_slot_timing_enabled() is False


def test_thresholds_default():
    idle, drag = st.current_slot_timing_thresholds()
    assert idle == 30.0
    assert drag == 8.0


def test_thresholds_env_override(monkeypatch):
    monkeypatch.setenv("AIPACS_SLOT_TIMING_THRESHOLD_MS", "100")
    monkeypatch.setenv("AIPACS_SLOT_TIMING_DRAG_THRESHOLD_MS", "20")
    idle, drag = st.current_slot_timing_thresholds()
    assert idle == 100.0
    assert drag == 20.0


def test_thresholds_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("AIPACS_SLOT_TIMING_THRESHOLD_MS", "not-a-number")
    idle, _ = st.current_slot_timing_thresholds()
    assert idle == 30.0


def test_emit_below_threshold_idle_does_not_log(capture_log, force_idle):
    emitted = st.emit_slot_timing("foo", 5.0)
    assert emitted is False
    assert capture_log == []


def test_emit_above_threshold_idle_logs(capture_log, force_idle):
    emitted = st.emit_slot_timing("foo", 50.0)
    assert emitted is True
    assert len(capture_log) == 1
    msg = capture_log[0].getMessage()
    assert "[SLOT_TIMING]" in msg
    assert "tag=foo" in msg
    assert "drag_active=False" in msg
    assert "threshold_ms=30.0" in msg


def test_emit_drag_lowers_threshold(capture_log, force_drag):
    """Under drag, 10 ms emits (10 > 8) but would not emit idle (10 < 30)."""
    emitted_drag = st.emit_slot_timing("foo", 10.0)
    assert emitted_drag is True
    assert capture_log[-1].getMessage().endswith("extra=") or \
        "drag_active=True" in capture_log[-1].getMessage()


def test_emit_drag_below_drag_threshold_does_not_log(capture_log, force_drag):
    emitted = st.emit_slot_timing("foo", 5.0)
    assert emitted is False
    assert capture_log == []


def test_emit_force_bypasses_threshold(capture_log, force_idle):
    emitted = st.emit_slot_timing("foo", 1.0, force=True)
    assert emitted is True
    assert len(capture_log) == 1


def test_emit_disabled_via_env_returns_false(capture_log, force_idle, monkeypatch):
    monkeypatch.setenv("AIPACS_SLOT_TIMING_TRACE", "0")
    emitted = st.emit_slot_timing("foo", 999.0, force=True)
    assert emitted is False
    assert capture_log == []


def test_emit_includes_series_and_extra(capture_log, force_idle):
    st.emit_slot_timing(
        "foo",
        100.0,
        series="201",
        extra={"k1": "v1", "k2": 42},
    )
    msg = capture_log[-1].getMessage()
    assert "series=201" in msg
    assert "k1=v1" in msg
    assert "k2=42" in msg


def test_decorator_wraps_function_transparently(force_idle):
    @st.slot_timing("test.fn")
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
    assert add.__name__ == "add"


def test_decorator_emits_when_slow(capture_log, force_idle):
    @st.slot_timing("test.slow")
    def slow_fn():
        time.sleep(0.05)  # 50 ms > 30 ms idle threshold
        return "ok"

    assert slow_fn() == "ok"
    assert any(
        "tag=test.slow" in r.getMessage() for r in capture_log
    )


def test_decorator_no_emit_when_fast(capture_log, force_idle):
    @st.slot_timing("test.fast")
    def fast_fn():
        return "ok"

    fast_fn()
    assert all("tag=test.fast" not in r.getMessage() for r in capture_log)


def test_decorator_resolves_series_kwarg(capture_log, force_idle):
    @st.slot_timing("test.s", series_arg="series_number")
    def fn(self, series_number=None):
        time.sleep(0.05)
        return series_number

    fn(object(), series_number="201")
    msg = capture_log[-1].getMessage()
    assert "series=201" in msg


def test_decorator_resolves_series_positional(capture_log, force_idle):
    @st.slot_timing("test.s", series_arg="series_number")
    def fn(self, series_number=None):
        time.sleep(0.05)
        return series_number

    fn(object(), "202")
    msg = capture_log[-1].getMessage()
    assert "series=202" in msg


def test_decorator_propagates_exception(force_idle):
    @st.slot_timing("test.boom")
    def boom():
        raise RuntimeError("expected")

    with pytest.raises(RuntimeError, match="expected"):
        boom()


def test_decorator_emits_even_when_function_raises(capture_log, force_idle):
    @st.slot_timing("test.boom_slow")
    def boom_slow():
        time.sleep(0.05)
        raise RuntimeError("expected")

    with pytest.raises(RuntimeError):
        boom_slow()
    assert any("tag=test.boom_slow" in r.getMessage() for r in capture_log)


def test_decorator_swallows_extra_factory_exception(capture_log, force_idle):
    def bad_factory(*a, **k):
        raise ValueError("factory broken")

    @st.slot_timing("test.bad_factory", extra_factory=bad_factory)
    def fn():
        time.sleep(0.05)
        return 1

    # Wrapped function still completes normally.
    assert fn() == 1
    # Log emission still happens (without extra payload).
    assert any("tag=test.bad_factory" in r.getMessage() for r in capture_log)


def test_decorator_disabled_via_env_is_noop_at_call_time(capture_log, force_idle, monkeypatch):
    @st.slot_timing("test.disabled")
    def fn():
        return "ok"

    # Disable AFTER decoration; current code re-checks on each call.
    monkeypatch.setenv("AIPACS_SLOT_TIMING_TRACE", "0")
    assert fn() == "ok"
    assert all("tag=test.disabled" not in r.getMessage() for r in capture_log)


def test_time_slot_context_manager_emits_on_exit(capture_log, force_idle):
    with st.time_slot("test.cm"):
        time.sleep(0.05)
    assert any("tag=test.cm" in r.getMessage() for r in capture_log)


def test_time_slot_context_manager_emits_on_exception(capture_log, force_idle):
    with pytest.raises(RuntimeError):
        with st.time_slot("test.cm_boom"):
            time.sleep(0.05)
            raise RuntimeError("expected")
    assert any("tag=test.cm_boom" in r.getMessage() for r in capture_log)


def test_time_slot_disabled_via_env_no_op(capture_log, force_idle, monkeypatch):
    monkeypatch.setenv("AIPACS_SLOT_TIMING_TRACE", "0")
    with st.time_slot("test.disabled_cm"):
        time.sleep(0.05)
    assert capture_log == []


def test_resolve_drag_active_handles_missing_module(monkeypatch):
    """Lazy import failure is tolerated — never raises."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "modules.viewer.fast.ui_throttle":
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Must not raise.
    assert st._resolve_drag_active() is False


def test_extra_with_special_chars_sanitized(capture_log, force_idle):
    """Field separators in `extra` values are converted, not breaking format."""
    st.emit_slot_timing(
        "foo",
        100.0,
        extra={"k": "a;b=c"},
    )
    msg = capture_log[-1].getMessage()
    # `;` and `=` in the value are replaced so they don't collide with the
    # k=v;k=v field separator.
    assert "k=a,b:c" in msg
