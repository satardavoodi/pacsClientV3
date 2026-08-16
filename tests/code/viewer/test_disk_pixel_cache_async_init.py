"""Disk pixel cache: off-GUI-thread index scan (2026-08-16).

Live evidence: `DiskPixelCache.initialize()` ran synchronously on whichever
thread first touched the module singleton — in practice the GUI thread, during
the first series switch. The scan is an `iterdir` per study dir plus a `stat`
per cache file; on the reporting workstation that is 44 dirs / 1,593 `.apc`
files / ~1.97 GB and it accounted for ~4 s of one contiguous 9.1 s frozen UI
(stall stack: `disk_pixel_cache.initialize` -> `Path.iterdir` / `Path.stat`).
It grows with the cache, so it only gets worse.

The fix keeps `initialize()` SYNCHRONOUS for every direct caller (so existing
behaviour and tests are untouched) and makes only the singleton index in the
background. These pins cover the property that makes deferring safe — an
unindexed lookup is just a cache miss — and the two things that could go wrong
in the merge: double-counted bytes and broken LRU ordering.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.viewer.fast import disk_pixel_cache as DPC          # noqa: E402
from modules.viewer.fast.disk_pixel_cache import DiskPixelCache  # noqa: E402


def _seed_cache_files(root: Path, cache: DiskPixelCache, n: int) -> list[str]:
    """Write n real cache entries through the cache, then return their keys."""
    keys = []
    for i in range(n):
        sop = f"sop_seed_{i}"
        cache.put(sop, "study_seed", np.full((16, 16), i, dtype=np.int16))
        keys.append(DPC._uid_hash(sop))
    cache._write_queue.join()
    return keys


# ---------------------------------------------------------------------------
# Default stays synchronous — no existing caller changes behaviour.
# ---------------------------------------------------------------------------
def test_initialize_is_synchronous_by_default(tmp_path):
    seed = DiskPixelCache(tmp_path, max_size_mb=64)
    seed.initialize()
    _seed_cache_files(tmp_path, seed, 3)

    fresh = DiskPixelCache(tmp_path, max_size_mb=64)
    fresh.initialize()                      # no background=
    # index is fully populated the instant initialize() returns
    assert fresh.stats()["entries"] == 3
    assert fresh._index_ready.is_set() is True


def test_uninitialised_cache_still_noops(tmp_path):
    """The pre-existing contract: no initialize() -> get None, put no-op."""
    c = DiskPixelCache(tmp_path)
    assert c.get("sop_x", "study_x") is None
    c.put("sop_x", "study_x", np.zeros((8, 8), dtype=np.int16))
    time.sleep(0.1)
    assert c.get("sop_x", "study_x") is None


# ---------------------------------------------------------------------------
# Background mode — returns immediately, indexes later.
# ---------------------------------------------------------------------------
def test_background_initialize_returns_before_the_scan(tmp_path, monkeypatch):
    seed = DiskPixelCache(tmp_path, max_size_mb=64)
    seed.initialize()
    _seed_cache_files(tmp_path, seed, 3)

    release = threading.Event()
    real_scan = DiskPixelCache._scan_index

    def _slow_scan(self):
        release.wait(5.0)
        return real_scan(self)

    monkeypatch.setattr(DiskPixelCache, "_scan_index", _slow_scan)

    fresh = DiskPixelCache(tmp_path, max_size_mb=64)
    t0 = time.perf_counter()
    fresh.initialize(background=True)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.5, f"background initialize blocked for {elapsed:.2f}s"
    assert fresh._initialized is True, "cache must be usable immediately"
    assert fresh._index_ready.is_set() is False
    # ...and while the scan is pending, a lookup is simply a MISS (not a crash,
    # not a wait) — the caller decodes from DICOM exactly as on a cold cache.
    assert fresh.get("sop_seed_0", "study_seed") is None

    release.set()
    assert fresh.wait_until_indexed(5.0) is True
    assert fresh.stats()["entries"] == 3
    assert fresh.get("sop_seed_0", "study_seed") is not None


def test_kill_switch_forces_synchronous_scan(tmp_path, monkeypatch):
    seed = DiskPixelCache(tmp_path, max_size_mb=64)
    seed.initialize()
    _seed_cache_files(tmp_path, seed, 2)

    monkeypatch.setenv("AIPACS_PIXEL_CACHE_ASYNC_INIT", "0")
    fresh = DiskPixelCache(tmp_path, max_size_mb=64)
    fresh.initialize(background=True)
    assert fresh._index_ready.is_set() is True
    assert fresh.stats()["entries"] == 2


def test_index_ready_is_set_even_when_the_scan_fails(tmp_path, monkeypatch):
    """A failed scan must never leave waiters hanging or the cache unusable."""
    c = DiskPixelCache(tmp_path, max_size_mb=64)

    def _boom(self):
        raise OSError("simulated scan failure")

    monkeypatch.setattr(Path, "iterdir", _boom)
    c.initialize()                       # synchronous; must swallow + set
    assert c._index_ready.is_set() is True
    assert c._initialized is True


# ---------------------------------------------------------------------------
# Merge correctness — the two things a concurrent put() could break.
# ---------------------------------------------------------------------------
def test_put_during_scan_is_not_double_counted(tmp_path):
    """A key written while the scan runs must be counted exactly once."""
    seed = DiskPixelCache(tmp_path, max_size_mb=64)
    seed.initialize()
    _seed_cache_files(tmp_path, seed, 2)
    on_disk_bytes = sum(p.stat().st_size for p in tmp_path.rglob("*.apc"))

    fresh = DiskPixelCache(tmp_path, max_size_mb=64)
    fresh._initialized = True                 # usable, scan not run yet
    # Simulate a live put() landing before the merge: register one of the very
    # keys the scan is about to report.
    existing = list(tmp_path.rglob("*.apc"))[0]
    with fresh._lock:
        fresh._index[existing.stem] = (existing, existing.stat().st_size, time.time())
        fresh._total_bytes += existing.stat().st_size

    fresh._scan_index()

    assert fresh.stats()["entries"] == 2, "the merge duplicated or dropped a key"
    assert fresh._total_bytes == on_disk_bytes, (
        f"byte accounting drifted: {fresh._total_bytes} vs {on_disk_bytes}")


def test_merge_restores_lru_order_oldest_first(tmp_path):
    """Index ORDER is the LRU order (_evict_if_needed pops the front).

    A freshly written entry must not become the first eviction candidate just
    because the scan appended older entries after it.
    """
    seed = DiskPixelCache(tmp_path, max_size_mb=64)
    seed.initialize()
    _seed_cache_files(tmp_path, seed, 3)

    fresh = DiskPixelCache(tmp_path, max_size_mb=64)
    fresh._initialized = True
    # A brand-new entry registered by a live put() during the scan window.
    new_path = tmp_path / "live" / "livekey.apc"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_bytes(b"x" * 32)
    with fresh._lock:
        fresh._index["livekey"] = (new_path, 32, time.time() + 60)  # newest
        fresh._total_bytes += 32

    fresh._scan_index()

    access_times = [v[2] for v in fresh._index.values()]
    assert access_times == sorted(access_times), (
        "index order must be oldest-first so eviction takes the oldest")
    assert list(fresh._index)[-1] == "livekey", (
        "the newest entry must be LAST (evicted last), not first")


def test_scan_merge_does_not_disturb_existing_entry_metadata(tmp_path):
    seed = DiskPixelCache(tmp_path, max_size_mb=64)
    seed.initialize()
    _seed_cache_files(tmp_path, seed, 1)

    fresh = DiskPixelCache(tmp_path, max_size_mb=64)
    fresh._initialized = True
    existing = list(tmp_path.rglob("*.apc"))[0]
    sentinel = (existing, 4242, 999999.0)
    with fresh._lock:
        fresh._index[existing.stem] = sentinel
        fresh._total_bytes += 4242

    fresh._scan_index()
    assert fresh._index[existing.stem] == sentinel, (
        "the merge overwrote a live put()'s entry")


# ---------------------------------------------------------------------------
# The singleton — the actual GUI-thread path that froze.
# ---------------------------------------------------------------------------
def test_singleton_indexes_in_the_background(tmp_path, monkeypatch):
    monkeypatch.setattr(DPC, "_instance", None, raising=False)
    calls = {}
    real_init = DiskPixelCache.initialize

    def _spy(self, *, background=False):
        calls["background"] = background
        return real_init(self, background=background)

    monkeypatch.setattr(DiskPixelCache, "initialize", _spy)
    try:
        inst = DPC.get_disk_pixel_cache()
        assert calls.get("background") is True, (
            "the singleton must index off-thread — it is created on the GUI "
            "thread during a series switch")
        assert inst.wait_until_indexed(10.0) is True
    finally:
        monkeypatch.setattr(DPC, "_instance", None, raising=False)


def test_concurrent_put_and_scan_keep_accounting_consistent(tmp_path):
    """Stress the real race: writer thread + scan merging at the same time."""
    seed = DiskPixelCache(tmp_path, max_size_mb=64)
    seed.initialize()
    _seed_cache_files(tmp_path, seed, 8)

    fresh = DiskPixelCache(tmp_path, max_size_mb=64)
    fresh._initialized = True

    stop = threading.Event()

    def _writer():
        i = 0
        while not stop.is_set() and i < 40:
            fresh.put(f"sop_race_{i}", "study_race",
                      np.full((8, 8), i % 7, dtype=np.int16))
            i += 1
            time.sleep(0.002)

    t = threading.Thread(target=_writer, daemon=True)
    t.start()
    fresh._scan_index()
    stop.set()
    t.join(5.0)
    fresh._write_queue.join()

    with fresh._lock:
        summed = sum(v[1] for v in fresh._index.values())
        total = fresh._total_bytes
        keys = list(fresh._index)
    assert summed == total, (
        f"_total_bytes ({total}) drifted from the sum of entries ({summed})")
    assert len(keys) == len(set(keys)), "duplicate keys in the index"
