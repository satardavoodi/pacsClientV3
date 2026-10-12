"""Yielding to the software that was here first.

The agent is a guest on a machine whose job is registering patients. It shares
that machine with the reception system, MongoDB and the PACS server, and the
one thing it must never be is the reason the reception desk is slow.

CPU priority covers the CPU. It does nothing for the reception system's thread
pool — a below-normal process can still occupy twenty of its connections, and
those queue at ITS priority. That bound used to exist by accident: one question
meant one API call. The gathering loop ended the accident, so the bound is now
explicit, and these tests are what keep it.
"""

from __future__ import annotations

import threading
import time

import pytest

from reception_crm import politeness


@pytest.fixture(autouse=True)
def _fresh_gate(monkeypatch):
    """Each test gets its own gate; a module-level semaphore would carry
    counts between tests and make the failures meaningless."""
    monkeypatch.setattr(politeness, "reception_gate", politeness._ReceptionGate())


def test_only_so_many_reception_calls_run_at_once(monkeypatch):
    """The property the reception desk cares about."""
    monkeypatch.setenv(politeness.ENV_MAX_INFLIGHT, "3")

    peak = 0
    live = 0
    lock = threading.Lock()
    done = threading.Event()

    def worker():
        nonlocal peak, live
        with politeness.reception_gate.slot():
            with lock:
                live += 1
                peak = max(peak, live)
            done.wait(0.05)
            with lock:
                live -= 1

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    done.set()

    assert peak <= 3, f"{peak} reception calls were in flight at once"


def test_all_the_work_still_gets_done():
    """A cap that dropped calls would be a cap that loses answers."""
    completed = []

    def worker(i):
        with politeness.reception_gate.slot():
            completed.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sorted(completed) == list(range(20))


def test_a_slot_is_released_even_when_the_call_raises():
    """A leaked slot is a permanent reduction in throughput that only shows up
    later, as an agent that has mysteriously become slow."""
    for _ in range(10):
        with pytest.raises(RuntimeError):
            with politeness.reception_gate.slot():
                raise RuntimeError("the reception API said no")

    ran = []
    with politeness.reception_gate.slot():
        ran.append(True)
    assert ran == [True]


def test_a_full_gate_proceeds_rather_than_hanging(monkeypatch):
    """Politeness is not worth a hung clinician.

    If the gate is somehow saturated for the whole timeout, going over the
    limit is a worse minute for the reception API and a much better one than a
    request that never returns.
    """
    monkeypatch.setenv(politeness.ENV_MAX_INFLIGHT, "1")
    monkeypatch.setattr(politeness, "ACQUIRE_TIMEOUT_SECONDS", 0.05)

    holder_in = threading.Event()
    release = threading.Event()

    def holder():
        with politeness.reception_gate.slot():
            holder_in.set()
            release.wait(2)

    t = threading.Thread(target=holder)
    t.start()
    assert holder_in.wait(2)

    started = time.perf_counter()
    with politeness.reception_gate.slot():
        pass
    elapsed = time.perf_counter() - started

    release.set()
    t.join(timeout=2)

    assert elapsed < 1.0, "a full gate blocked far longer than its timeout"
    assert politeness.reception_gate.forced == 1, "going over the limit must be counted"


def test_the_limit_is_configurable_and_sane(monkeypatch):
    monkeypatch.setenv(politeness.ENV_MAX_INFLIGHT, "8")
    assert politeness._max_inflight() == 8

    for nonsense in ("0", "-3", "banana", ""):
        monkeypatch.setenv(politeness.ENV_MAX_INFLIGHT, nonsense)
        value = politeness._max_inflight()
        assert 1 <= value <= 32, f"{nonsense!r} produced {value}"


def test_the_limit_is_reported_so_it_can_be_observed(monkeypatch):
    """A cap nobody can see is a cap nobody knows has been hit."""
    monkeypatch.setenv(politeness.ENV_MAX_INFLIGHT, "5")
    with politeness.reception_gate.slot():
        pass
    status = politeness.reception_gate.status()
    assert status["limit"] == 5
    assert status["forced_past_limit"] == 0


def test_lowering_our_own_priority_never_stops_the_service(monkeypatch):
    """A companion that refuses to start because it could not lower its own
    priority is a worse outcome than one running at normal priority."""
    monkeypatch.setattr(politeness, "wanted", lambda: True)
    monkeypatch.setattr(politeness.sys, "platform", "win32")

    def explode():
        raise OSError("no such API")

    monkeypatch.setattr(politeness, "yield_cpu_to_clinical_software",
                        lambda: "unchanged (OSError)")
    politeness.apply()  # must not raise


def test_yielding_can_be_switched_off_for_a_dedicated_machine(monkeypatch):
    monkeypatch.setenv(politeness.ENV_YIELD, "false")
    assert politeness.wanted() is False
    assert "left at default" in politeness.yield_cpu_to_clinical_software()
