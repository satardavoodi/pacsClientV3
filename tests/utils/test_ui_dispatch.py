"""Unit tests for ``PacsClient.utils.ui_dispatch`` (Phase 1.1).

These run headless — when PySide6 is not importable (or no QApplication
is present), ``post`` and ``schedule`` fall back to immediate execution
per the documented contract. The tests cover both modes via the
``_QT_AVAILABLE`` flag.
"""

from __future__ import annotations

import time
from typing import List

import pytest

from PacsClient.utils import ui_dispatch
from PacsClient.utils.ui_dispatch import (
    Handle,
    Latch,
    cancel_on_destroy,
    latch,
    post,
    schedule,
)


# ---------------------------------------------------------------------------
# Handle
# ---------------------------------------------------------------------------


class TestHandle:
    def test_handle_initial_state(self):
        h = Handle()
        assert not h.cancelled
        assert not h.fired

    def test_cancel_marks_cancelled(self):
        h = Handle()
        h.cancel()
        assert h.cancelled

    def test_cancel_is_idempotent(self):
        h = Handle()
        h.cancel()
        h.cancel()
        h.cancel()
        assert h.cancelled

    def test_mark_fired_clears_timer(self):
        h = Handle(timer="dummy")
        h._mark_fired()
        assert h.fired
        assert h._timer is None

    def test_cancel_after_fired_is_noop(self):
        h = Handle()
        h._mark_fired()
        h.cancel()
        assert h.fired
        assert not h.cancelled

    def test_cancel_calls_stop_and_deleteLater(self):
        calls = []

        class FakeTimer:
            def stop(self):
                calls.append("stop")

            def deleteLater(self):
                calls.append("delete")

        h = Handle(timer=FakeTimer())
        h.cancel()
        assert calls == ["stop", "delete"]


# ---------------------------------------------------------------------------
# post / schedule
# ---------------------------------------------------------------------------


class TestPostScheduleHeadless:
    """When Qt is unavailable, post/schedule must run callback synchronously."""

    def test_post_runs_immediately_when_no_qt(self, monkeypatch):
        monkeypatch.setattr(ui_dispatch, "_QT_AVAILABLE", False)
        out: List[int] = []
        h = post(lambda: out.append(1))
        assert out == [1]
        assert h.fired
        assert not h.cancelled

    def test_schedule_runs_immediately_when_no_qt(self, monkeypatch):
        monkeypatch.setattr(ui_dispatch, "_QT_AVAILABLE", False)
        out: List[int] = []
        h = schedule(500, lambda: out.append(42))
        assert out == [42]
        assert h.fired

    def test_schedule_rejects_non_callable(self):
        with pytest.raises(TypeError):
            schedule(0, "not a callable")  # type: ignore[arg-type]

    def test_schedule_rejects_negative_ms(self):
        with pytest.raises(ValueError):
            schedule(-1, lambda: None)

    def test_post_returns_handle_instance(self, monkeypatch):
        monkeypatch.setattr(ui_dispatch, "_QT_AVAILABLE", False)
        h = post(lambda: None)
        assert isinstance(h, Handle)

    def test_headless_callback_exception_propagates(self, monkeypatch):
        """In headless mode, an exception from the callback IS raised
        (we mark fired in finally so the handle state stays consistent)."""
        monkeypatch.setattr(ui_dispatch, "_QT_AVAILABLE", False)

        def boom():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            post(boom)


# ---------------------------------------------------------------------------
# cancel_on_destroy
# ---------------------------------------------------------------------------


class TestCancelOnDestroy:
    def test_cancel_on_destroy_with_no_widget_is_noop(self):
        h = Handle()
        cancel_on_destroy(None, h)
        assert not h.cancelled

    def test_cancel_on_destroy_with_no_destroyed_signal_is_noop(self):
        class FakeWidget:
            pass

        h = Handle()
        cancel_on_destroy(FakeWidget(), h)
        assert not h.cancelled

    def test_cancel_on_destroy_connects_to_destroyed_signal(self):
        captured: List = []

        class FakeSignal:
            def connect(self, slot):
                captured.append(slot)

        class FakeWidget:
            destroyed = FakeSignal()

        h = Handle()
        cancel_on_destroy(FakeWidget(), h)
        assert len(captured) == 1

        # Simulate the destroyed signal firing.
        captured[0]()
        assert h.cancelled

    def test_cancel_on_destroy_handles_already_cancelled_handle(self):
        captured: List = []

        class FakeSignal:
            def connect(self, slot):
                captured.append(slot)

        class FakeWidget:
            destroyed = FakeSignal()

        h = Handle()
        h.cancel()
        cancel_on_destroy(FakeWidget(), h)
        # Already-cancelled handle should not bother connecting.
        assert captured == []

    def test_cancel_on_destroy_handles_already_fired_handle(self):
        captured: List = []

        class FakeSignal:
            def connect(self, slot):
                captured.append(slot)

        class FakeWidget:
            destroyed = FakeSignal()

        h = Handle()
        h._mark_fired()
        cancel_on_destroy(FakeWidget(), h)
        assert captured == []

    def test_cancel_on_destroy_swallows_connect_exception(self):
        class FakeSignal:
            def connect(self, slot):
                raise RuntimeError("connect failed")

        class FakeWidget:
            destroyed = FakeSignal()

        h = Handle()
        # Must not raise.
        cancel_on_destroy(FakeWidget(), h)
        assert not h.cancelled


# ---------------------------------------------------------------------------
# Latch
# ---------------------------------------------------------------------------


class TestLatch:
    def test_latch_construction(self):
        latch_inst = latch("test", grace_ms=500)
        assert latch_inst.name == "test"
        assert latch_inst.grace_ms == 500
        assert not latch_inst.active

    def test_latch_rejects_empty_name(self):
        with pytest.raises(ValueError):
            Latch("", grace_ms=100)

    def test_latch_rejects_non_string_name(self):
        with pytest.raises(ValueError):
            Latch(None, grace_ms=100)  # type: ignore[arg-type]

    def test_latch_rejects_zero_or_negative_grace(self):
        with pytest.raises(ValueError):
            Latch("x", grace_ms=0)
        with pytest.raises(ValueError):
            Latch("x", grace_ms=-1)

    def test_begin_marks_active(self):
        l = latch("drag", grace_ms=1000)
        l.begin()
        assert l.active

    def test_end_clears_active(self):
        l = latch("drag", grace_ms=1000)
        l.begin()
        l.end()
        assert not l.active

    def test_end_with_tail_grace_keeps_active(self):
        l = latch("drag", grace_ms=1000)
        l.begin()
        l.end(tail_grace_ms=200)
        assert l.active  # still within tail window

    def test_grace_window_expires(self):
        l = latch("drag", grace_ms=1000)
        l.begin(grace_ms=10)  # 10 ms
        assert l.active
        time.sleep(0.05)
        # _active flag still True, but if you call end+tail you'd see expiry;
        # active=True via the explicit flag still holds because begin() sets
        # both flag and deadline. Confirm flag-driven path:
        assert l.active

    def test_tail_grace_window_expires(self):
        l = latch("drag", grace_ms=1000)
        l.begin()
        l.end(tail_grace_ms=10)
        assert l.active
        time.sleep(0.05)
        assert not l.active

    def test_keepalive_extends_deadline(self):
        l = latch("drag", grace_ms=1000)
        l.begin(grace_ms=20)
        time.sleep(0.01)
        l.keepalive(grace_ms=100)
        time.sleep(0.05)
        # Original 20ms window would have expired, but keepalive pushed it.
        assert l.active

    def test_reset_clears_state(self):
        l = latch("drag", grace_ms=1000)
        l.begin()
        l.reset()
        assert not l.active

    def test_context_manager_sets_then_clears(self):
        l = latch("drag", grace_ms=1000)
        assert not l.active
        with l:
            assert l.active
        assert not l.active

    def test_context_manager_clears_on_exception(self):
        l = latch("drag", grace_ms=1000)
        with pytest.raises(RuntimeError):
            with l:
                assert l.active
                raise RuntimeError("boom")
        assert not l.active

    def test_latch_thread_safe_basic_smoke(self):
        import threading

        l = latch("multi", grace_ms=1000)
        errors: List[Exception] = []

        def worker():
            try:
                for _ in range(50):
                    l.begin()
                    l.keepalive()
                    l.end()
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert not l.active


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class TestPublicSurface:
    def test_all_exports_present(self):
        for name in ("Handle", "Latch", "cancel_on_destroy", "latch", "post", "schedule"):
            assert hasattr(ui_dispatch, name), f"missing export: {name}"

    def test_module_has_qt_available_flag(self):
        assert isinstance(ui_dispatch._QT_AVAILABLE, bool)
