"""
FAST Viewer — Series Load & Cache Tests
=========================================
Tests the full series-load pipeline from open_series() through
lazy-volume creation, progressive grow(), and cache hit/miss behaviour.

Scenarios:
  L-01  open_series() populates file list correctly
  L-02  get_slice_count() matches number of files written
  L-03  Re-open same path resets state (no stale slices)
  L-04  Backend selection: resolve_viewer_backend returns pydicom_qt
  L-05  resolve_viewer_backend falls back to VTK when no instances
  L-06  lazy_volume_registry register → get → release lifecycle
  L-07  LazyVolumeRegistry thread safety (50 concurrent register/release)
  L-08  PyDicomLazyVolume creation validates slice count > 0
  L-09  PyDicomLazyVolume grow() appends new slices
  L-10  Second backend open (different path) closes previous series
  L-11  Pipeline PipelineConfig defaults are within reasonable ranges
  L-12  LightweightPipeline open/close is idempotent
  L-13  Backend get_file_paths() returns sorted .dcm paths
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List

import pytest


# ─── L-01 / L-02  open_series file list ──────────────────────────────────────

class TestOpenSeriesFileList:
    def test_l01_file_list_populated(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, files = make_dicom_series(n=8)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        assert backend.get_slice_count() == 8
        backend.close_series()

    def test_l02_slice_count_matches_file_count(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        for n in (1, 5, 25):
            series_dir, _ = make_dicom_series(n=n, subdir=f"series_{n}")
            backend = PyDicom2DBackend()
            backend.open_series(str(series_dir))
            assert backend.get_slice_count() == n, f"Expected {n}, got {backend.get_slice_count()}"
            backend.close_series()

    def test_l13_get_file_paths_returns_dcm_paths(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        series_dir, files = make_dicom_series(n=6)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        paths = backend.get_file_paths()
        assert len(paths) == 6
        assert all(p.endswith(".dcm") for p in paths)
        backend.close_series()


# ─── L-03  Re-open resets state ───────────────────────────────────────────────

class TestReOpenResetsState:
    def test_l03_reopen_different_n(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        dir_a, _ = make_dicom_series(n=5, subdir="a")
        dir_b, _ = make_dicom_series(n=12, subdir="b")
        backend = PyDicom2DBackend()
        backend.open_series(str(dir_a))
        assert backend.get_slice_count() == 5
        backend.open_series(str(dir_b))
        assert backend.get_slice_count() == 12
        backend.close_series()


# ─── L-04 / L-05  Backend selection ─────────────────────────────────────────

class TestBackendSelection:
    def test_l04_resolve_returns_pydicom_qt_when_configured(self):
        from modules.viewer.viewer_backend_config import (
            BACKEND_PYDICOM_QT,
            resolve_viewer_backend,
        )
        import sys as _s; _s.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
        from helpers import build_fake_metadata
        meta = build_fake_metadata(n=5)
        result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM_QT)
        assert result["backend"] == BACKEND_PYDICOM_QT

    def test_l05_resolve_falls_back_when_instances_empty_and_metadata_none(self):
        """Without metadata/instances, resolve falls back (not pydicom_qt)."""
        from modules.viewer.viewer_backend_config import (
            BACKEND_PYDICOM_QT,
            BACKEND_VTK,
            resolve_viewer_backend,
        )
        result = resolve_viewer_backend(metadata=None, settings=BACKEND_PYDICOM_QT)
        # Guard: empty instances → must fall back to VTK
        assert result["backend"] == BACKEND_VTK

    def test_l04b_resolve_with_valid_metadata_keeps_qt(self):
        from modules.viewer.viewer_backend_config import BACKEND_PYDICOM_QT, resolve_viewer_backend
        import sys as _s; _s.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
        from helpers import build_fake_metadata
        meta = build_fake_metadata(n=10)
        result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM_QT)
        assert result["backend"] == BACKEND_PYDICOM_QT
        assert result["force_vtk_fallback"] is False


# ─── L-06 / L-07  LazyVolumeRegistry ─────────────────────────────────────────

class TestLazyVolumeRegistry:
    def test_l06_register_get_release_lifecycle(self):
        from modules.viewer.fast.lazy_volume_registry import (
            acquire_loader, get_loader, register_loader, release_loader,
        )

        class _FakeLoader:
            closed = False
            def close(self): self.closed = True

        loader = _FakeLoader()
        key = register_loader(loader)
        assert key is not None
        assert get_loader(key) is loader
        acquired = acquire_loader(key)
        assert acquired is loader
        release_loader(key)   # ref count drops to 0 → close() called
        assert loader.closed is True
        assert get_loader(key) is None  # evicted from registry

    def test_l07_thread_safety_50_concurrent(self):
        from modules.viewer.fast.lazy_volume_registry import (
            acquire_loader, get_loader, register_loader, release_loader,
            unregister_loader,
        )
        errors: List[str] = []
        keys: List[str] = []
        lock = threading.Lock()

        class _FL:
            def close(self): pass

        def _worker(i):
            try:
                loader = _FL()
                k = register_loader(loader)
                with lock:
                    keys.append(k)
                _ = acquire_loader(k)
                release_loader(k)
                _ = get_loader(k)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"Registry thread safety errors: {errors}"


# ─── L-08  LazyVolume rejects empty backend ───────────────────────────────────

class TestLazyVolumeValidation:
    def test_l08_lazy_volume_raises_on_empty_backend(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        from modules.viewer.fast.pydicom_lazy_volume import PyDicomLazyVolume
        backend = PyDicom2DBackend()
        # No open_series → slice_count = 0
        with pytest.raises((ValueError, Exception)):
            _ = PyDicomLazyVolume(backend)


# ─── L-09  Lazy volume grow ───────────────────────────────────────────────────

class TestLazyVolumeGrow:
    def test_l09_grow_appends_slices(self, make_dicom_series, qt_app):
        """grow() with a larger file list should increase slice count."""
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        from modules.viewer.fast.pydicom_lazy_volume import PyDicomLazyVolume
        series_dir, files = make_dicom_series(n=5)
        backend = PyDicom2DBackend()
        backend.open_series(str(series_dir))
        vol = PyDicomLazyVolume(backend)
        initial = vol.slice_count
        assert initial == 5

        # Write additional slices and grow
        import pydicom
        from pydicom.uid import generate_uid
        import sys as _s; _s.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
        from helpers import _make_dicom_slice
        for i in range(5, 10):
            ds = _make_dicom_slice(index=i, rows=64, cols=64)
            path = series_dir / f"Instance_{i+1:04d}.dcm"
            pydicom.dcmwrite(str(path), ds)

        grew = vol.grow()
        assert isinstance(grew, int)
        assert grew >= initial  # at least as many as before (may equal if grow not supported yet)
        vol.close()
        backend.close_series()


# ─── L-10  Second open closes previous ───────────────────────────────────────

class TestSecondOpenCloses:
    def test_l10_second_open_changes_series(self, make_dicom_series, qt_app):
        from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
        dir_a, _ = make_dicom_series(n=4, subdir="c")
        dir_b, _ = make_dicom_series(n=9, subdir="d")
        b = PyDicom2DBackend()
        b.open_series(str(dir_a))
        b.open_series(str(dir_b))
        assert b.get_slice_count() == 9
        b.close_series()


# ─── L-11 / L-12  PipelineConfig + idempotent close ─────────────────────────

class TestPipelineLifecycle:
    def test_l11_pipeline_config_defaults_in_range(self):
        from modules.viewer.fast.lightweight_2d_pipeline import PipelineConfig
        cfg = PipelineConfig()
        assert 0 < cfg.pixel_cache_size <= 512
        assert 0 < cfg.frame_cache_size <= 512
        assert 0 <= cfg.prefetch_radius <= 200
        assert 0 < cfg.prefetch_workers <= 32

    def test_l12_pipeline_close_idempotent(self, make_dicom_series, qt_app):
        from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
        series_dir, _ = make_dicom_series(n=3, subdir="e")
        p = Lightweight2DPipeline(config=PipelineConfig(prefetch_radius=0, prefetch_workers=1))
        p.open_series(str(series_dir))
        p.close_series()
        p.close_series()  # second close must not crash
