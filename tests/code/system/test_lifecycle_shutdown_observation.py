"""Synthetic shutdown owners only; no application, database, or native teardown."""

import threading
import weakref

import pytest

from PacsClient.components.lifecycle_manager import LifecycleManager


def test_nested_shutdown_cannot_reopen_registration():
    manager = LifecycleManager()
    observed = []

    def stop():
        assert manager.shutdown_all() == {}
        observed.append(manager.is_shutting_down)
        manager.register("late", lambda: None)

    manager.register("owner", stop)
    assert manager.shutdown_all() == {"owner": None}
    assert observed == [True]
    assert manager.resource_count == 0
    assert not manager.is_shutting_down


def test_concurrent_shutdown_cannot_release_active_owner_guard():
    manager = LifecycleManager()
    entered, release = threading.Event(), threading.Event()
    manager.register("owner", lambda: (entered.set(), release.wait(3)))
    worker = threading.Thread(target=manager.shutdown_all)
    worker.start()
    try:
        assert entered.wait(2)
        assert manager.shutdown_all() == {}
        assert manager.is_shutting_down
        manager.register("late", lambda: None)
        assert manager.resource_count == 0
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()


@pytest.mark.parametrize("answer,expected", [
    (True, "complete"), (False, "pending"), (None, "unknown"), (1, "unknown"),
])
def test_callback_return_and_owner_completion_are_separate(answer, expected):
    manager = LifecycleManager()
    manager.register("owner", lambda: None)
    manager.register_completion_probe("owner", lambda: answer)
    assert manager.shutdown_all() == {"owner": None}
    record, = manager.last_shutdown_snapshot()
    assert record["callback_outcome"] == "returned"
    assert record["owner_completion"] == expected
    record["owner_completion"] = "tampered"
    assert manager.last_shutdown_snapshot()[0]["owner_completion"] == expected
    assert not manager._completion_probes


def test_probe_error_does_not_abort_lifo_or_change_callback_result():
    manager = LifecycleManager()
    calls = []
    manager.register("first", lambda: calls.append("first"))
    manager.register("last", lambda: calls.append("last"))

    def probe():
        assert manager.is_shutting_down  # Not called under the manager lock.
        raise ValueError("synthetic")

    manager.register_completion_probe("last", probe)
    assert manager.shutdown_all() == {"last": None, "first": None}
    assert calls == ["last", "first"]
    assert [r["owner_completion"] for r in manager.last_shutdown_snapshot()] == [
        "probe_error", "unknown"]


def test_unregister_removes_probe_and_callback_error_still_runs_next_owner():
    manager = LifecycleManager()
    manager.register_completion_probe("removed", lambda: True)
    manager.unregister("removed")
    assert not manager._completion_probes
    manager.register("first", lambda: None)

    def fail():
        raise ValueError("synthetic")

    manager.register("last", fail)
    assert manager.shutdown_all() == {"last": "synthetic", "first": None}
    assert manager.last_shutdown_snapshot()[0]["callback_outcome"] == "error"
    manager.register("next-run", lambda: None)
    assert manager.shutdown_all() == {"next-run": None}


def test_base_exception_releases_guard_without_swallowing_it():
    manager = LifecycleManager()

    def abort():
        raise KeyboardInterrupt()

    manager.register("owner", abort)
    with pytest.raises(KeyboardInterrupt):
        manager.shutdown_all()
    assert not manager.is_shutting_down


def test_probe_time_is_separate_from_callback_advisory_budget(monkeypatch):
    from PacsClient.components import lifecycle_manager as mod
    clock = iter([0.0, 0.1, 0.1, 9.1])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(clock))
    manager = LifecycleManager()
    manager.register("owner", lambda: None, timeout=1)
    manager.register_completion_probe("owner", lambda: False)
    assert manager.shutdown_all() == {"owner": None}
    record, = manager.last_shutdown_snapshot()
    assert record["callback_ms"] == pytest.approx(100)
    assert record["probe_ms"] == pytest.approx(9000)


def test_over_budget_callback_is_not_relabelled_as_drained(monkeypatch):
    from PacsClient.components import lifecycle_manager as mod
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(clock))
    manager = LifecycleManager()
    manager.register("owner", lambda: None, timeout=1)
    assert "exceeded timeout" in manager.shutdown_all()["owner"]
    record, = manager.last_shutdown_snapshot()
    assert record["callback_outcome"] == "over_budget"
    assert record["owner_completion"] == "unknown"


def test_observations_do_not_retain_owner_and_reject_late_probes():
    class Owner:
        def stop(self):
            pass

        def probe(self):
            manager.register_completion_probe("late", self.probe)
            return True

    manager = LifecycleManager()
    owner = Owner()
    ref = weakref.ref(owner)
    manager.register("owner", owner.stop)
    manager.register_completion_probe("owner", owner.probe)
    manager.shutdown_all()
    del owner
    assert ref() is None
    assert not manager._completion_probes
