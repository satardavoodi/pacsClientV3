"""S4a contract tests for the decoded-volume cache (``PacsClient/utils/volume_cache.py``).
Pure + unwired; locks the pin/unpin, LRU, invalidation, and decode-COALESCING contract before any
wiring into the live decode path (S4b).

Plan: docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md (S4).
"""
import threading
import time

import pytest

from PacsClient.utils.volume_cache import VolumeCache, VolumeCacheError, make_key

K1 = make_key("S1", "U1")
K2 = make_key("S1", "U2")
K3 = make_key("S2", "U3")


def test_make_key_normalizes():
    assert make_key(" S1 ", " U1 ") == ("S1", "U1")
    assert make_key(None, None) == ("", "")


def test_get_or_create_caches():
    c = VolumeCache()
    calls = []
    val = c.get_or_create(K1, lambda: (calls.append(1), "V")[1])
    assert val == "V"
    again = c.get_or_create(K1, lambda: (calls.append(1), "X")[1])
    assert again == "V"            # cached → factory NOT re-run
    assert len(calls) == 1
    assert K1 in c and c.peek(K1) == "V"


def test_pin_survives_eviction():
    c = VolumeCache(max_entries=2)
    c.get_or_create(K1, lambda: "A", pin=True)   # pinned
    c.get_or_create(K2, lambda: "B")
    c.get_or_create(K3, lambda: "C")             # forces eviction (3 > 2)
    assert K1 in c                                # pinned → survived
    assert c.is_pinned(K1)


def test_lru_evicts_oldest_unpinned():
    c = VolumeCache(max_entries=2)
    c.put(K1, "A")
    time.sleep(0.01)
    c.put(K2, "B")
    time.sleep(0.01)
    c.peek(K1)                                    # peek does NOT refresh LRU
    c.put(K3, "C")                                # over cap → evict LRU (K1, oldest)
    assert K1 not in c and K2 in c and K3 in c


def test_unpin_then_evictable():
    c = VolumeCache(max_entries=1)
    c.get_or_create(K1, lambda: "A", pin=True)
    c.put(K2, "B")
    assert K1 in c                                # still pinned, not evicted
    assert c.unpin(K1) is True
    c.put(K3, "C")                                # now K1 is evictable
    assert K1 not in c


def test_invalidation_bus():
    c = VolumeCache()
    c.put(K1, "A"); c.put(K2, "B"); c.put(K3, "C")
    assert c.invalidate(K1) is True and K1 not in c
    assert c.invalidate_study("S1") == 1          # only K2 remains under S1
    assert K2 not in c and K3 in c
    assert c.invalidate_all() == 1


def test_decode_coalescing_runs_factory_once():
    """The C1 / duplicate-decode fix: N concurrent callers for the same key run the factory
    EXACTLY once; the rest wait and share the result."""
    c = VolumeCache(max_entries=4)
    calls = []
    n = 8
    gate = threading.Barrier(n + 1)
    results = []

    def factory():
        calls.append(1)
        time.sleep(0.05)        # simulate a slow decode so the others coalesce
        return "VOL"

    def worker():
        gate.wait()
        results.append(c.get_or_create(K1, factory))

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    gate.wait()                 # release all at once
    for t in threads:
        t.join()

    assert len(calls) == 1                  # factory ran ONCE despite N concurrent callers
    assert results == ["VOL"] * n           # all received the same value
    assert c.stats()["coalesced"] >= 1


def test_factory_error_propagates_to_waiters():
    c = VolumeCache()
    n = 4
    gate = threading.Barrier(n + 1)
    errors = []

    def factory():
        time.sleep(0.03)
        raise ValueError("decode failed")

    def worker():
        gate.wait()
        try:
            c.get_or_create(K1, factory)
        except ValueError:
            errors.append("ValueError")
        except VolumeCacheError:
            errors.append("VolumeCacheError")

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    gate.wait()
    for t in threads:
        t.join()

    assert "ValueError" in errors            # the owner re-raises the real error
    assert "VolumeCacheError" in errors      # waiters get a coalesced-failure error
    assert K1 not in c                        # nothing cached on failure
