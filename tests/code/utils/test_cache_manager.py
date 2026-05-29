"""Unit tests for ``PacsClient.utils.cache_manager`` (Phase 1.2)."""

from __future__ import annotations

import threading
from typing import List

import pytest

from PacsClient.utils import cache_manager
from PacsClient.utils.cache_manager import (
    CacheManager,
    CacheRegion,
    RegionStats,
    get_global_cache_manager,
    reset_global_cache_manager,
)


# ---------------------------------------------------------------------------
# CacheRegion construction
# ---------------------------------------------------------------------------


class TestRegionConstruction:
    def test_basic_construction(self):
        r = CacheRegion("pixels", max_entries=10)
        assert r.name == "pixels"
        assert r.max_entries == 10
        assert r.max_bytes == 0
        assert len(r) == 0

    def test_rejects_empty_name(self):
        with pytest.raises(ValueError):
            CacheRegion("", max_entries=10)

    def test_rejects_non_string_name(self):
        with pytest.raises(ValueError):
            CacheRegion(None, max_entries=10)  # type: ignore[arg-type]

    def test_rejects_zero_max_entries(self):
        with pytest.raises(ValueError):
            CacheRegion("x", max_entries=0)

    def test_rejects_negative_max_bytes(self):
        with pytest.raises(ValueError):
            CacheRegion("x", max_entries=10, max_bytes=-1)


# ---------------------------------------------------------------------------
# Basic put/get/pop/contains
# ---------------------------------------------------------------------------


class TestBasicOperations:
    def test_put_then_get(self):
        r = CacheRegion("p", max_entries=5)
        r.put("a", 1)
        assert r.get("a") == 1

    def test_get_missing_returns_default(self):
        r = CacheRegion("p", max_entries=5)
        assert r.get("missing", default=42) == 42

    def test_contains(self):
        r = CacheRegion("p", max_entries=5)
        r.put("a", 1)
        assert "a" in r
        assert "b" not in r

    def test_pop_returns_and_removes(self):
        r = CacheRegion("p", max_entries=5)
        r.put("a", 1)
        assert r.pop("a") == 1
        assert "a" not in r

    def test_pop_missing_raises_by_default(self):
        r = CacheRegion("p", max_entries=5)
        with pytest.raises(KeyError):
            r.pop("missing")

    def test_pop_missing_returns_default_when_provided(self):
        r = CacheRegion("p", max_entries=5)
        assert r.pop("missing", default=7) == 7

    def test_clear(self):
        r = CacheRegion("p", max_entries=5)
        r.put("a", 1)
        r.put("b", 2)
        r.clear()
        assert len(r) == 0

    def test_put_replaces_existing(self):
        r = CacheRegion("p", max_entries=5)
        r.put("a", 1)
        r.put("a", 2)
        assert r.get("a") == 2
        assert len(r) == 1

    def test_peek_does_not_change_lru(self):
        r = CacheRegion("p", max_entries=2)
        r.put("a", 1)
        r.put("b", 2)
        # peek 'a' — should NOT promote it
        assert r.peek("a") == 1
        # insert 'c' — should evict 'a' since it's still oldest
        r.put("c", 3)
        assert "a" not in r
        assert "b" in r
        assert "c" in r


# ---------------------------------------------------------------------------
# LRU semantics
# ---------------------------------------------------------------------------


class TestLRUEviction:
    def test_evicts_oldest_when_over_max_entries(self):
        r = CacheRegion("p", max_entries=2)
        r.put("a", 1)
        r.put("b", 2)
        r.put("c", 3)
        assert "a" not in r
        assert "b" in r
        assert "c" in r
        assert len(r) == 2

    def test_get_promotes_to_most_recent(self):
        r = CacheRegion("p", max_entries=2)
        r.put("a", 1)
        r.put("b", 2)
        r.get("a")  # promote a
        r.put("c", 3)
        # Now 'b' should have been evicted, not 'a'.
        assert "a" in r
        assert "b" not in r
        assert "c" in r

    def test_keys_in_lru_order(self):
        r = CacheRegion("p", max_entries=5)
        r.put("a", 1)
        r.put("b", 2)
        r.put("c", 3)
        keys = list(r.keys())
        assert keys == ["a", "b", "c"]
        r.get("a")
        keys = list(r.keys())
        assert keys == ["b", "c", "a"]


# ---------------------------------------------------------------------------
# Bytes budget
# ---------------------------------------------------------------------------


class TestBytesBudget:
    def test_zero_max_bytes_disables_byte_budget(self):
        r = CacheRegion("p", max_entries=100, max_bytes=0, size_fn=lambda v: 1_000_000)
        for i in range(50):
            r.put(i, "x")
        assert len(r) == 50

    def test_evicts_when_total_bytes_exceeds_max(self):
        r = CacheRegion("p", max_entries=100, max_bytes=300, size_fn=lambda v: 100)
        r.put("a", "x")
        r.put("b", "x")
        r.put("c", "x")  # total = 300, at limit
        assert len(r) == 3
        r.put("d", "x")  # would push to 400 → evict 'a'
        assert "a" not in r
        assert len(r) == 3

    def test_bytes_decremented_on_pop(self):
        r = CacheRegion("p", max_entries=10, max_bytes=1000, size_fn=lambda v: 100)
        r.put("a", "x")
        r.put("b", "x")
        assert r.stats().bytes == 200
        r.pop("a")
        assert r.stats().bytes == 100

    def test_replace_updates_byte_total(self):
        sizes = {"a": 100, "b": 50}
        r = CacheRegion("p", max_entries=10, max_bytes=1000, size_fn=lambda v: sizes[v])
        r.put("k", "a")
        assert r.stats().bytes == 100
        r.put("k", "b")
        assert r.stats().bytes == 50

    def test_size_fn_exception_treated_as_zero(self):
        def boom(_v):
            raise RuntimeError("boom")

        r = CacheRegion("p", max_entries=10, max_bytes=1000, size_fn=boom)
        r.put("a", "x")
        assert r.stats().bytes == 0

    def test_negative_size_treated_as_zero(self):
        r = CacheRegion("p", max_entries=10, max_bytes=1000, size_fn=lambda v: -50)
        r.put("a", "x")
        assert r.stats().bytes == 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_initial_stats(self):
        r = CacheRegion("p", max_entries=5)
        s = r.stats()
        assert s.entries == 0
        assert s.hit_count == 0
        assert s.miss_count == 0
        assert s.eviction_count == 0
        assert s.hit_ratio == 0.0

    def test_hit_and_miss_counters(self):
        r = CacheRegion("p", max_entries=5)
        r.put("a", 1)
        r.get("a")
        r.get("missing")
        s = r.stats()
        assert s.hit_count == 1
        assert s.miss_count == 1
        assert s.hit_ratio == 0.5

    def test_eviction_counter(self):
        r = CacheRegion("p", max_entries=2)
        r.put("a", 1)
        r.put("b", 2)
        r.put("c", 3)  # evicts 'a'
        assert r.stats().eviction_count == 1

    def test_reset_stats(self):
        r = CacheRegion("p", max_entries=2)
        r.put("a", 1)
        r.get("a")
        r.reset_stats()
        s = r.stats()
        assert s.hit_count == 0
        assert s.miss_count == 0
        assert s.eviction_count == 0


# ---------------------------------------------------------------------------
# Resize
# ---------------------------------------------------------------------------


class TestResize:
    def test_set_max_entries_evicts_immediately(self):
        r = CacheRegion("p", max_entries=5)
        for k in ("a", "b", "c", "d", "e"):
            r.put(k, k)
        r.set_max_entries(2)
        assert len(r) == 2
        # oldest two ('a','b','c') evicted; 'd','e' remain.
        assert "d" in r
        assert "e" in r

    def test_set_max_bytes_evicts_immediately(self):
        r = CacheRegion("p", max_entries=10, max_bytes=1000, size_fn=lambda v: 100)
        for i in range(8):
            r.put(i, "x")
        assert r.stats().bytes == 800
        r.set_max_bytes(300)
        assert r.stats().bytes <= 300

    def test_set_max_entries_rejects_zero(self):
        r = CacheRegion("p", max_entries=5)
        with pytest.raises(ValueError):
            r.set_max_entries(0)

    def test_set_max_bytes_rejects_negative(self):
        r = CacheRegion("p", max_entries=5)
        with pytest.raises(ValueError):
            r.set_max_bytes(-1)


# ---------------------------------------------------------------------------
# Thread safety smoke
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_put_get_smoke(self):
        r = CacheRegion("p", max_entries=200)
        errors: List[Exception] = []

        def worker(start: int):
            try:
                for i in range(start, start + 100):
                    r.put(i, i * 2)
                    _ = r.get(i)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        # Should not exceed the max_entries cap.
        assert len(r) <= 200


# ---------------------------------------------------------------------------
# CacheManager
# ---------------------------------------------------------------------------


class TestCacheManager:
    def test_create_region(self):
        mgr = CacheManager()
        r = mgr.create_region("pixels", max_entries=10)
        assert isinstance(r, CacheRegion)
        assert mgr.has_region("pixels")
        assert "pixels" in mgr.names()

    def test_create_region_rejects_duplicate(self):
        mgr = CacheManager()
        mgr.create_region("pixels", max_entries=10)
        with pytest.raises(ValueError):
            mgr.create_region("pixels", max_entries=20)

    def test_get_or_create_returns_existing(self):
        mgr = CacheManager()
        r1 = mgr.create_region("pixels", max_entries=10)
        r2 = mgr.get_or_create_region("pixels", max_entries=99)
        assert r1 is r2
        assert r2.max_entries == 10  # original cap preserved

    def test_get_or_create_creates_when_missing(self):
        mgr = CacheManager()
        r = mgr.get_or_create_region("frames", max_entries=5)
        assert mgr.has_region("frames")
        assert r.max_entries == 5

    def test_region_returns_existing(self):
        mgr = CacheManager()
        r1 = mgr.create_region("pixels", max_entries=10)
        assert mgr.region("pixels") is r1

    def test_region_raises_when_missing(self):
        mgr = CacheManager()
        with pytest.raises(KeyError):
            mgr.region("missing")

    def test_remove_region_clears_data(self):
        mgr = CacheManager()
        r = mgr.create_region("pixels", max_entries=10)
        r.put("a", 1)
        mgr.remove_region("pixels")
        assert not mgr.has_region("pixels")
        assert len(r) == 0

    def test_clear_all(self):
        mgr = CacheManager()
        r1 = mgr.create_region("a", max_entries=10)
        r2 = mgr.create_region("b", max_entries=10)
        r1.put("x", 1)
        r2.put("y", 2)
        mgr.clear_all()
        assert len(r1) == 0
        assert len(r2) == 0

    def test_total_bytes_aggregates(self):
        mgr = CacheManager()
        r1 = mgr.create_region("a", max_entries=10, max_bytes=1000, size_fn=lambda v: 100)
        r2 = mgr.create_region("b", max_entries=10, max_bytes=1000, size_fn=lambda v: 50)
        r1.put("x", "v")
        r2.put("y", "v")
        r2.put("z", "v")
        assert mgr.total_bytes() == 100 + 50 + 50

    def test_total_entries_aggregates(self):
        mgr = CacheManager()
        r1 = mgr.create_region("a", max_entries=10)
        r2 = mgr.create_region("b", max_entries=10)
        r1.put(1, 1)
        r2.put(1, 1)
        r2.put(2, 2)
        assert mgr.total_entries() == 3

    def test_stats_returns_dict(self):
        mgr = CacheManager()
        mgr.create_region("a", max_entries=10)
        mgr.create_region("b", max_entries=10)
        stats = mgr.stats()
        assert set(stats.keys()) == {"a", "b"}
        assert all(isinstance(v, RegionStats) for v in stats.values())


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------


class TestGlobalSingleton:
    def setup_method(self):
        reset_global_cache_manager()

    def teardown_method(self):
        reset_global_cache_manager()

    def test_returns_same_instance(self):
        a = get_global_cache_manager()
        b = get_global_cache_manager()
        assert a is b

    def test_reset_creates_new_instance(self):
        a = get_global_cache_manager()
        reset_global_cache_manager()
        b = get_global_cache_manager()
        assert a is not b

    def test_singleton_supports_named_regions(self):
        mgr = get_global_cache_manager()
        mgr.get_or_create_region("pixels", max_entries=10)
        mgr.get_or_create_region("rendered_frames", max_entries=10)
        mgr.get_or_create_region("metadata", max_entries=10)
        mgr.get_or_create_region("volume", max_entries=10)
        assert set(mgr.names()) == {"pixels", "rendered_frames", "metadata", "volume"}


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class TestPublicSurface:
    def test_all_exports_present(self):
        for name in (
            "CacheManager",
            "CacheRegion",
            "RegionStats",
            "SizeFn",
            "get_global_cache_manager",
            "reset_global_cache_manager",
        ):
            assert hasattr(cache_manager, name), f"missing export: {name}"
