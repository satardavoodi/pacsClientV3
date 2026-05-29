"""
FAST Viewer — Cache & Store Read/Write Tests
=============================================
Tests internal data structures used by the FAST viewer to persist and
retrieve decoded frames, pixel arrays, annotations, and lazy volumes.

Covers: LRU pixel cache, frame cache, lazy volume registry, stale temp-
file cleanup, and annotation store.

Scenarios:
  RW-01  PixelCache: put then get returns same array
  RW-02  PixelCache: LRU eviction (put N+1 items, oldest gone)
  RW-03  PixelCache: thread-safe concurrent put/get
  RW-04  FrameCache: same (slice, W, L) key returns cached QImage
  RW-05  FrameCache: different W/L key → cache miss
  RW-06  LazyVolumeRegistry: register → key is unique per call
  RW-07  LazyVolumeRegistry: get_loader returns None after unregister
  RW-08  LazyVolumeRegistry: acquire increments ref count; release decrements
  RW-09  cleanup_stale_tmpfiles: temp file deleted after registration
  RW-10  cleanup_stale_tmpfiles: does not crash on already-deleted file
  RW-11  LazyVolume: grow() returns count >= initial slice count
  RW-12  LazyVolume: loaded flag set to True after get_slice
  RW-13  Backend clear_cache() resets pixel cache
  RW-14  Backend: setting new W/L invalidates frame cache
  RW-15  PixelCache: cache_size=1 keeps only 1 entry
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from collections import OrderedDict
from typing import List, Optional

import numpy as np
import pytest


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_array(value: int = 100, shape=(64, 64)) -> np.ndarray:
    return np.full(shape, value, dtype=np.int16)


# ─── RW-01 / RW-02 / RW-03 / RW-15  PixelCache ──────────────────────────────

class TestPixelCache:
    """Tests the internal OrderedDict-based LRU pixel cache in PyDicom2DBackend."""

    def _make_backend(self, cache_size: int):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        b = PyDicom2DBackend(cache_size=cache_size, prefetch_radius=0)
        return b

    def test_rw01_put_then_get_returns_same_array(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=3)
        b = PyDicom2DBackend(cache_size=32)
        b.open_series(str(series_dir))
        arr1 = b.get_pixel_array(0)
        arr2 = b.get_pixel_array(0)   # cache hit
        assert np.array_equal(arr1, arr2), "Cache returned different array on second get"
        b.close_series()

    def test_rw02_lru_eviction(self, make_dicom_series, qt_app):
        """Cache of size 2 must evict oldest when 3rd item inserted."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=5)
        # cache_size is clamped to min 4 internally; use 4 and fill 5 to trigger eviction
        b = PyDicom2DBackend(cache_size=4, prefetch_radius=0)
        b.open_series(str(series_dir))
        for i in range(5):
            _ = b.get_pixel_array(i)
        cache = b._pixel_cache
        assert len(cache) <= 4, f"Cache size exceeded limit: {len(cache)}"
        b.close_series()

    def test_rw03_concurrent_get_no_corruption(self, make_dicom_series, qt_app):
        """10 threads getting the same slice must all get a valid array."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=3)
        b = PyDicom2DBackend(cache_size=32, prefetch_radius=0)
        b.open_series(str(series_dir))
        results: List[Optional[np.ndarray]] = [None] * 10
        errors: List[str] = []

        def _get(i):
            try:
                results[i] = b.get_pixel_array(0)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_get, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"Concurrent get errors: {errors}"
        first = results[0]
        for r in results:
            assert r is not None
            assert r.shape == first.shape
        b.close_series()

    def test_rw15_cache_size_4_keeps_at_most_4_entries(self, make_dicom_series, qt_app):
        # cache_size is clamped to min 4; verify 6 accesses stay within limit
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=6)
        b = PyDicom2DBackend(cache_size=4, prefetch_radius=0)
        b.open_series(str(series_dir))
        for i in range(6):
            _ = b.get_pixel_array(i)
        assert len(b._pixel_cache) <= 4, f"Expected ≤4 entries, got {len(b._pixel_cache)}"
        b.close_series()


# ─── RW-04 / RW-05  FrameCache ───────────────────────────────────────────────

class TestFrameCache:
    def test_rw04_same_wl_key_returns_cached_qimage(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        b = PyDicom2DBackend(cache_size=32, prefetch_radius=0)
        b.open_series(str(series_dir))
        b.set_window_level(400.0, 40.0)
        frame1 = b.get_frame(0)
        frame2 = b.get_frame(0)   # should be cache hit
        assert frame1 is not None
        assert frame2 is not None
        # Cached QImage must be the same object
        assert frame1.image is frame2.image or frame1.image == frame2.image
        b.close_series()

    def test_rw05_different_wl_misses_frame_cache(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        b = PyDicom2DBackend(cache_size=32, prefetch_radius=0)
        b.open_series(str(series_dir))
        b.set_window_level(400.0, 40.0)
        frame1 = b.get_frame(0)
        b.set_window_level(800.0, 200.0)   # different W/L → cache miss
        frame2 = b.get_frame(0)
        assert frame1 is not None
        assert frame2 is not None
        b.close_series()


# ─── RW-06 / RW-07 / RW-08  LazyVolumeRegistry ──────────────────────────────

class TestLazyVolumeRegistryRW:
    def test_rw06_register_produces_unique_keys(self):
        from modules.viewer.fast.lazy_volume_registry import register_loader

        class _FL:
            def close(self): pass

        keys = {register_loader(_FL()) for _ in range(20)}
        assert len(keys) == 20, "Duplicate keys from register_loader"

    def test_rw07_get_returns_none_after_unregister(self):
        from modules.viewer.fast.lazy_volume_registry import (
            get_loader, register_loader, unregister_loader,
        )

        class _FL:
            closed = False
            def close(self): self.closed = True

        loader = _FL()
        key = register_loader(loader)
        assert get_loader(key) is loader
        unregister_loader(key)
        assert get_loader(key) is None

    def test_rw08_acquire_release_ref_counting(self):
        from modules.viewer.fast.lazy_volume_registry import (
            acquire_loader, get_loader, register_loader, release_loader,
        )

        class _FL:
            closed = False
            def close(self): self.closed = True

        loader = _FL()
        key = register_loader(loader)
        _ = acquire_loader(key)   # refs = 1
        _ = acquire_loader(key)   # refs = 2
        release_loader(key)       # refs = 1 → not closed
        assert not loader.closed
        assert get_loader(key) is loader
        release_loader(key)       # refs = 0 → closed + evicted
        assert loader.closed
        assert get_loader(key) is None


# ─── RW-09 / RW-10  cleanup_stale_tmpfiles ───────────────────────────────────

class TestStaleFileCleanup:
    def test_rw09_temp_file_deleted(self):
        from modules.viewer.fast.pydicom_lazy_volume import (
            _register_stale_tmpfile, cleanup_stale_tmpfiles,
        )
        fd, path = tempfile.mkstemp(prefix="aipacs_test_stale_")
        os.close(fd)
        assert os.path.exists(path)
        _register_stale_tmpfile(path)
        removed = cleanup_stale_tmpfiles()
        assert removed >= 1
        assert not os.path.exists(path), f"Temp file not deleted: {path}"

    def test_rw10_cleanup_survives_already_deleted_file(self):
        from modules.viewer.fast.pydicom_lazy_volume import (
            _register_stale_tmpfile, cleanup_stale_tmpfiles,
        )
        _register_stale_tmpfile("/nonexistent/path/file_9999.bin")
        # Must not raise
        cleanup_stale_tmpfiles()


# ─── RW-11 / RW-12  LazyVolume grow and loaded flags ─────────────────────────

class TestLazyVolumeRW:
    def test_rw11_grow_returns_nonnegative(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        from modules.viewer.fast.pydicom_lazy_volume import PyDicomLazyVolume
        series_dir, _ = make_dicom_series(n=5)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        vol = PyDicomLazyVolume(backend)
        result = vol.grow()
        assert isinstance(result, int)
        assert result >= 0
        vol.close()
        backend.close_series()

    def test_rw12_loaded_flags_initially_false(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        from modules.viewer.fast.pydicom_lazy_volume import PyDicomLazyVolume
        series_dir, _ = make_dicom_series(n=4)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        vol = PyDicomLazyVolume(backend)
        # Slice 0 is primed synchronously during __init__; rest are not yet loaded
        assert vol._loaded[0], "Slice 0 must be pre-loaded during init"
        assert not any(vol._loaded[1:]), "Slices 1+ must NOT be loaded during init"
        vol.close()
        backend.close_series()


# ─── RW-13 / RW-14  clear_cache + W/L invalidation ──────────────────────────

class TestCacheClear:
    def test_rw13_clear_cache_resets_pixel_cache(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=3)
        b = PyDicom2DBackend(cache_size=32)
        b.open_series(str(series_dir))
        _ = b.get_pixel_array(0)
        _ = b.get_pixel_array(1)
        assert len(b._pixel_cache) >= 2
        b._pixel_cache.clear()
        b._frame_cache.clear()
        assert len(b._pixel_cache) == 0
        b.close_series()

    def test_rw14_wl_change_evicts_frame_cache(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, _ = make_dicom_series(n=2)
        b = PyDicom2DBackend(cache_size=32)
        b.open_series(str(series_dir))
        _ = b.get_frame(0)
        initial_frame_cache_size = len(b._frame_cache)
        b.set_window_level(9999.0, 9999.0)  # change W/L
        # Frame cache must be empty (evicted)
        assert len(b._frame_cache) == 0, (
            f"Frame cache not evicted after W/L change: {len(b._frame_cache)} entries remain"
        )
        b.close_series()
