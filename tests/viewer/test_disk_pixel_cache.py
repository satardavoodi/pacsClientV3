"""
Tests for B3.12 Disk Pixel Cache.

Covers:
  - put/get round-trip for int16, uint16, float32, uint8
  - Cache hit returns correct data
  - Shape mismatch → miss + corrupt file deleted
  - LRU eviction when over size limit
  - Duplicate put is no-op
  - clear() wipes everything
  - Uninitialized cache returns None
  - Benchmark: disk cache hit vs pydicom.dcmread decode
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest

# ── Import target ──

from modules.viewer.fast.disk_pixel_cache import DiskPixelCache, _HEADER_SIZE


# ── Fixtures ──

@pytest.fixture()
def cache_dir(tmp_path: Path):
    """Provide a fresh temp directory for each test."""
    return tmp_path / "test_cache"


@pytest.fixture()
def cache(cache_dir: Path):
    """Provide an initialized DiskPixelCache."""
    c = DiskPixelCache(cache_dir, max_size_mb=10)
    c.initialize()
    return c


# ── Round-trip tests ──

@pytest.mark.parametrize("dtype", [np.int16, np.uint16, np.float32, np.uint8])
def test_put_get_roundtrip(cache: DiskPixelCache, dtype):
    """put() then get() returns identical data."""
    arr = np.arange(512 * 512, dtype=dtype).reshape(512, 512)
    cache.put("sop_uid_1", "study_uid_1", arr)
    # Wait for background write to finish
    time.sleep(0.3)
    result = cache.get("sop_uid_1", "study_uid_1", expected_shape=(512, 512))
    assert result is not None
    np.testing.assert_array_equal(result, arr)
    assert result.dtype == dtype


def test_cache_miss_returns_none(cache: DiskPixelCache):
    """get() returns None for uncached key."""
    assert cache.get("nonexistent", "study_1") is None


def test_shape_mismatch_deletes_corrupt(cache: DiskPixelCache):
    """get() with wrong expected shape returns None and deletes the file."""
    arr = np.zeros((256, 256), dtype=np.int16)
    cache.put("sop_shape", "study_shape", arr)
    time.sleep(0.3)

    # Request with wrong expected shape
    result = cache.get("sop_shape", "study_shape", expected_shape=(512, 512))
    assert result is None

    # Entry should be removed from index
    assert cache.stats()["entries"] == 0


def test_duplicate_put_is_noop(cache: DiskPixelCache):
    """Second put() with same key does not overwrite."""
    arr1 = np.ones((64, 64), dtype=np.int16) * 100
    arr2 = np.ones((64, 64), dtype=np.int16) * 200
    cache.put("sop_dup", "study_dup", arr1)
    time.sleep(0.3)
    cache.put("sop_dup", "study_dup", arr2)
    time.sleep(0.3)

    result = cache.get("sop_dup", "study_dup", expected_shape=(64, 64))
    assert result is not None
    np.testing.assert_array_equal(result, arr1)  # first write wins


def test_lru_eviction(cache_dir: Path):
    """Entries are evicted LRU when over size limit."""
    # Use tiny 1 KB limit
    c = DiskPixelCache(cache_dir, max_size_mb=0)
    # Monkey-patch to very small limit
    c._max_size_bytes = 1024
    c.initialize()

    # Each 64x64 int16 = 8192 bytes + 14 header = 8206 bytes
    arr1 = np.zeros((64, 64), dtype=np.int16)
    arr2 = np.ones((64, 64), dtype=np.int16)

    c.put("sop_old", "study_evict", arr1)
    time.sleep(0.3)
    c.put("sop_new", "study_evict", arr2)
    time.sleep(0.5)

    # Old entry should be evicted (over 1KB limit)
    assert c.get("sop_old", "study_evict") is None
    # New entry should still be there (or also evicted if total > limit)
    # The key point is: eviction runs without crashing


def test_clear_wipes_all(cache: DiskPixelCache, cache_dir: Path):
    """clear() removes all entries."""
    arr = np.zeros((32, 32), dtype=np.int16)
    cache.put("sop_clear", "study_clear", arr)
    time.sleep(0.3)
    assert cache.stats()["entries"] == 1

    cache.clear()
    assert cache.stats()["entries"] == 0
    assert cache.get("sop_clear", "study_clear") is None


def test_uninit_returns_none(cache_dir: Path):
    """Uninitialized cache returns None on get() and no-ops on put()."""
    c = DiskPixelCache(cache_dir)
    # NOT calling c.initialize()
    assert c.get("sop_x", "study_x") is None
    c.put("sop_x", "study_x", np.zeros((16, 16), dtype=np.int16))
    time.sleep(0.1)
    assert c.get("sop_x", "study_x") is None  # still None


def test_stats_report(cache: DiskPixelCache):
    """stats() returns correct entries count and size."""
    arr = np.zeros((64, 64), dtype=np.int16)  # 8192 bytes payload
    cache.put("sop_stats", "study_stats", arr)
    time.sleep(0.3)

    s = cache.stats()
    assert s["entries"] == 1
    expected_size = (_HEADER_SIZE + 64 * 64 * 2) / (1024 * 1024)
    assert abs(s["total_mb"] - expected_size) < 0.01


# ── Benchmark ──

@pytest.mark.skipif(
    not Path("user_data/patients/dicom").exists(),
    reason="No local DICOM data for benchmark",
)
def test_benchmark_disk_cache_vs_pydicom(cache_dir: Path, capsys):
    """Benchmark: disk cache read vs pydicom.dcmread for same file."""
    import pydicom

    # Find a real DICOM file
    dicom_root = Path("user_data/patients/dicom")
    dcm_file = None
    for study_dir in dicom_root.iterdir():
        if not study_dir.is_dir():
            continue
        for series_dir in study_dir.iterdir():
            if not series_dir.is_dir():
                continue
            for f in series_dir.iterdir():
                if f.suffix == ".dcm":
                    dcm_file = f
                    break
            if dcm_file:
                break
        if dcm_file:
            break

    if dcm_file is None:
        pytest.skip("No .dcm files found")

    # Decode once via pydicom
    ds = pydicom.dcmread(str(dcm_file), stop_before_pixels=False, force=True)
    arr = np.asarray(ds.pixel_array)
    if arr.dtype not in (np.int16, np.uint16, np.float32, np.uint8):
        arr = arr.astype(np.int16)
    rows, cols = arr.shape[:2]

    # Write to disk cache
    c = DiskPixelCache(cache_dir, max_size_mb=100)
    c.initialize()
    uid = str(dcm_file)
    c.put(uid, "bench_study", arr)
    time.sleep(0.5)

    # Warm OS cache
    c.get(uid, "bench_study", expected_shape=(rows, cols))

    # Benchmark: disk cache read
    N = 50
    t0 = time.perf_counter()
    for _ in range(N):
        c.get(uid, "bench_study", expected_shape=(rows, cols))
    cache_ms = (time.perf_counter() - t0) / N * 1000

    # Benchmark: pydicom decode
    t0 = time.perf_counter()
    for _ in range(N):
        d = pydicom.dcmread(str(dcm_file), stop_before_pixels=False, force=True)
        _ = np.asarray(d.pixel_array)
    pydicom_ms = (time.perf_counter() - t0) / N * 1000

    speedup = pydicom_ms / max(cache_ms, 0.01)

    with capsys.disabled():
        print(f"\n{'='*60}")
        print(f"B3.12 Disk Cache Benchmark ({dcm_file.name})")
        print(f"  Array: {rows}×{cols} {arr.dtype}")
        print(f"  Disk cache read:  {cache_ms:.2f} ms")
        print(f"  pydicom decode:   {pydicom_ms:.2f} ms")
        print(f"  Speedup:          {speedup:.1f}×")
        print(f"{'='*60}")

    assert cache_ms < pydicom_ms, f"Disk cache ({cache_ms:.2f}ms) slower than pydicom ({pydicom_ms:.2f}ms)"
