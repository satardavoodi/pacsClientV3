"""S5a contract tests for the by-ViewerHandle cancellation primitive
(``PacsClient/utils/viewer_cancellation.py``). Pure + unwired; locks the teardown / supersession
contract (D1/D2 fix) before any wiring (S5b).

Plan: docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md (S5).
"""
import threading

import pytest

from PacsClient.utils.viewer_identity import ViewerHandle
from PacsClient.utils.viewer_cancellation import (
    CancellationRegistry, CancellationToken, OperationCancelled,
)

HA = ViewerHandle.new()
HB = ViewerHandle.new()


def test_token_basics():
    t = CancellationToken("h")
    assert not t.cancelled
    t.cancel()
    assert t.cancelled
    with pytest.raises(OperationCancelled):
        t.raise_if_cancelled()


def test_cancel_handle_is_isolated():
    reg = CancellationRegistry()
    ta = reg.new_token(HA)
    tb = reg.new_token(HB)
    assert reg.active_count() == 2
    n = reg.cancel_handle(HA)
    assert n == 1
    assert ta.cancelled and not tb.cancelled        # only HA's token cancelled
    assert reg.active_count(HB) == 1


def test_supersede_cancels_prior_for_same_handle():
    reg = CancellationRegistry()
    old = reg.new_token(HA)
    new = reg.new_token(HA, supersede=True)          # new request replaces old
    assert old.cancelled and not new.cancelled
    assert reg.active_count(HA) == 1                  # only the new one remains


def test_retire_prevents_later_cancel():
    reg = CancellationRegistry()
    t = reg.new_token(HA)
    reg.retire(t)                                    # op finished cleanly
    assert reg.active_count(HA) == 0
    reg.cancel_handle(HA)
    assert not t.cancelled                           # retired → never cancelled


def test_cancel_all():
    reg = CancellationRegistry()
    t1 = reg.new_token(HA); t2 = reg.new_token(HB); t3 = reg.new_token(HB)
    assert reg.cancel_all() == 3
    assert t1.cancelled and t2.cancelled and t3.cancelled
    assert reg.active_count() == 0


def test_accepts_handle_or_uuid():
    reg = CancellationRegistry()
    reg.new_token(HA)                                # by handle object
    assert reg.active_count(HA.uuid) == 1            # query by raw uuid string


def test_thread_safety_smoke():
    """Concurrent new_token + cancel_handle must not corrupt the registry or deadlock."""
    reg = CancellationRegistry()
    handles = [ViewerHandle.new() for _ in range(4)]
    stop = threading.Event()

    def churn(h):
        while not stop.is_set():
            t = reg.new_token(h)
            t.raise_if_cancelled() if t.cancelled else None
            reg.retire(t)

    def cancel(h):
        for _ in range(50):
            reg.cancel_handle(h)

    ts = [threading.Thread(target=churn, args=(h,)) for h in handles]
    for t in ts:
        t.start()
    cancellers = [threading.Thread(target=cancel, args=(h,)) for h in handles]
    for c in cancellers:
        c.start()
    for c in cancellers:
        c.join()
    stop.set()
    for t in ts:
        t.join()
    # registry is consistent (no exception, counts are non-negative ints)
    assert reg.active_count() >= 0
