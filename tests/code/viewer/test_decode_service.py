"""
Tests for B3.11 Decode Service.

Covers:
  - Service start/shutdown lifecycle
  - Subprocess decode returns correct array
  - Fallback when service is disabled
  - Multiple concurrent requests
  - Timeout/error handling
  - Benchmark: subprocess decode vs in-process decode
"""

from __future__ import annotations

import os
import time
from concurrent.futures import Future
from pathlib import Path

import numpy as np
import pytest


# ── Import targets ──

from modules.viewer.fast.decode_service import (
    DecodeService,
    _decode_worker,
    _ENABLED,
    BrokenProcessPool,
    _is_content_decode_error,
)


# ── Unit test for the worker function (in-process) ──

@pytest.mark.skipif(
    not Path("user_data/patients/dicom").exists(),
    reason="No local DICOM data",
)
def test_decode_worker_produces_valid_array():
    """_decode_worker returns a valid numpy array for a real DICOM file."""
    dcm = _find_dicom_file()
    if dcm is None:
        pytest.skip("No .dcm file found")

    import pydicom
    ds = pydicom.dcmread(str(dcm), stop_before_pixels=True, force=True)
    rows = int(getattr(ds, "Rows", 0))
    cols = int(getattr(ds, "Columns", 0))
    slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
    photo = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2"))
    spp = int(getattr(ds, "SamplesPerPixel", 1))

    arr = _decode_worker(str(dcm), rows, cols, slope, intercept, photo, spp)

    assert isinstance(arr, np.ndarray)
    assert arr.shape[0] == rows
    assert arr.shape[1] == cols
    assert arr.flags["C_CONTIGUOUS"]


# ── Service lifecycle tests ──

def test_service_start_shutdown():
    """Service starts and shuts down cleanly."""
    svc = DecodeService(max_workers=1)
    svc.start()
    assert svc.is_available
    svc.shutdown()
    assert not svc.is_available


def test_service_double_start_is_noop():
    """Calling start() twice doesn't create duplicate pools."""
    svc = DecodeService(max_workers=1)
    svc.start()
    svc.start()  # should be no-op
    assert svc.is_available
    svc.shutdown()


def test_service_double_shutdown_is_safe():
    """Calling shutdown() twice doesn't raise."""
    svc = DecodeService(max_workers=1)
    svc.start()
    svc.shutdown()
    svc.shutdown()  # should be safe


def test_service_decode_returns_none_when_not_started():
    """decode() returns None when service hasn't been started."""
    svc = DecodeService(max_workers=1)
    result = svc.decode("fake.dcm", 512, 512, 1.0, 0.0, "MONOCHROME2", 1)
    assert result is None


def test_service_stats():
    """stats() returns correct structure."""
    svc = DecodeService(max_workers=1)
    s = svc.stats()
    assert "available" in s
    assert "requests" in s
    assert "failures" in s


def test_content_decode_error_does_not_disable_service():
    """Per-file decode errors should not count as pool health failures."""
    svc = DecodeService(max_workers=1)
    svc._available = True

    fut = Future()
    fut.set_exception(AttributeError(
        "Unable to convert the pixel data: one of Pixel Data, Float Pixel Data or Double Float Pixel Data must be present in the dataset"
    ))

    class _FakePool:
        def submit(self, *args, **kwargs):
            return fut

    svc._pool = _FakePool()

    result = svc.decode("bad.dcm", 512, 512, 1.0, 0.0, "MONOCHROME2", 1)
    assert result is None
    assert svc.is_available is True
    assert svc.stats()["requests"] == 1
    assert svc.stats()["failures"] == 0


def test_content_decode_error_recognizes_missing_file_meta_messages():
    """Malformed/partial DICOM header messages should stay in the soft-failure bucket."""
    exc = RuntimeError(
        "File is missing DICOM File Meta Information header or the 'DICM' prefix is missing"
    )

    assert _is_content_decode_error(exc) is True


def test_broken_process_pool_triggers_bounded_restart(monkeypatch):
    """Hard pool failures should attempt restart before permanent disable."""
    svc = DecodeService(max_workers=1)
    svc._available = True

    fut = Future()
    fut.set_exception(BrokenProcessPool("worker died"))

    class _FakePool:
        def submit(self, *args, **kwargs):
            return fut

        def shutdown(self, wait=False, cancel_futures=True):
            return None

    restart_calls = []

    def _fake_start():
        restart_calls.append("start")
        svc._available = True
        svc._pool = _FakePool()

    svc._pool = _FakePool()
    monkeypatch.setattr(svc, "start", _fake_start)

    result = svc.decode("bad.dcm", 512, 512, 1.0, 0.0, "MONOCHROME2", 1)

    assert result is None
    assert restart_calls == ["start"]
    assert svc.is_available is True
    assert svc.stats()["failures"] == 1


def test_hard_failure_streak_resets_after_success():
    """A successful decode should clear the hard-failure streak."""
    svc = DecodeService(max_workers=1)
    svc._available = True

    good = Future()
    good.set_result(np.zeros((2, 2), dtype=np.int16))

    class _FakePool:
        def __init__(self):
            self.calls = 0

        def submit(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                bad = Future()
                bad.set_exception(RuntimeError("temporary hard failure"))
                return bad
            return good

        def shutdown(self, wait=False, cancel_futures=True):
            return None

    svc._pool = _FakePool()

    assert svc.decode("bad.dcm", 512, 512, 1.0, 0.0, "MONOCHROME2", 1) is None
    assert svc._hard_failure_streak == 1

    arr = svc.decode("good.dcm", 2, 2, 1.0, 0.0, "MONOCHROME2", 1)

    assert isinstance(arr, np.ndarray)
    assert svc._hard_failure_streak == 0


def test_successful_restart_resets_health_window(monkeypatch):
    """A recovered pool gets a fresh health window instead of inheriting old failures."""
    svc = DecodeService(max_workers=1)
    svc._available = True
    svc._health_window_requests = 12
    svc._health_window_failures = 11
    svc._hard_failure_streak = 3

    class _FakePool:
        def shutdown(self, wait=False, cancel_futures=True):
            return None

    def _fake_start():
        svc._available = True
        svc._pool = _FakePool()
        svc._pool_generation += 1

    svc._pool = _FakePool()
    monkeypatch.setattr(svc, "start", _fake_start)

    restarted = svc._restart_pool("hard_failure_streak")

    assert restarted is True
    assert svc._health_window_requests == 0
    assert svc._health_window_failures == 0
    assert svc._hard_failure_streak == 0


def test_stale_failure_from_old_pool_does_not_poison_restarted_service():
    """Failures from a replaced pool should not count against the new pool health window."""
    svc = DecodeService(max_workers=1)
    svc._available = True

    fut = Future()
    fut.set_exception(RuntimeError("old pool failure"))

    class _NewPool:
        def submit(self, *args, **kwargs):
            raise AssertionError("new pool should not be used in this test")

    class _OldPool:
        def submit(self, *args, **kwargs):
            svc._pool = _NewPool()
            svc._pool_generation += 1
            svc._available = True
            return fut

        def shutdown(self, wait=False, cancel_futures=True):
            return None

    svc._pool = _OldPool()
    svc._pool_generation = 1

    result = svc.decode("bad.dcm", 512, 512, 1.0, 0.0, "MONOCHROME2", 1)

    assert result is None
    assert svc.stats()["failures"] == 0
    assert svc.stats()["health_window_failures"] == 0
    assert svc._hard_failure_streak == 0


def test_failure_rate_disables_after_restart_budget_exhausted(monkeypatch):
    """Once restart attempts are exhausted, high hard-failure rate disables the service."""
    svc = DecodeService(max_workers=1)
    svc._available = True
    svc._restart_attempts = svc._max_restart_attempts
    svc._health_window_requests = 11
    svc._health_window_failures = 11
    svc._hard_failure_streak = 3

    shutdown_calls = []

    class _FakePool:
        def shutdown(self, wait=False, cancel_futures=True):
            shutdown_calls.append((wait, cancel_futures))

    svc._pool = _FakePool()
    monkeypatch.setattr(svc, "start", lambda: pytest.fail("start should not be called once restart budget is exhausted"))

    svc._check_health(RuntimeError("persistent hard failure"))

    assert svc.is_available is False
    assert shutdown_calls == [(False, True)]


# ── Real decode via subprocess ──

@pytest.mark.skipif(
    not Path("user_data/patients/dicom").exists(),
    reason="No local DICOM data",
)
def test_subprocess_decode_matches_inprocess():
    """Subprocess decode produces identical result to in-process decode."""
    dcm = _find_dicom_file()
    if dcm is None:
        pytest.skip("No .dcm file found")

    import pydicom
    ds = pydicom.dcmread(str(dcm), stop_before_pixels=True, force=True)
    rows = int(getattr(ds, "Rows", 0))
    cols = int(getattr(ds, "Columns", 0))
    slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
    photo = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2"))
    spp = int(getattr(ds, "SamplesPerPixel", 1))

    # In-process reference
    ref = _decode_worker(str(dcm), rows, cols, slope, intercept, photo, spp)

    # Subprocess decode
    svc = DecodeService(max_workers=1)
    svc.start()
    try:
        result = svc.decode(str(dcm), rows, cols, slope, intercept, photo, spp)
        assert result is not None, "Subprocess decode returned None"
        np.testing.assert_array_equal(result, ref)
        assert result.dtype == ref.dtype
    finally:
        svc.shutdown()


@pytest.mark.skipif(
    not Path("user_data/patients/dicom").exists(),
    reason="No local DICOM data",
)
def test_subprocess_multiple_decodes():
    """Subprocess handles multiple sequential requests."""
    dcm = _find_dicom_file()
    if dcm is None:
        pytest.skip("No .dcm file found")

    import pydicom
    ds = pydicom.dcmread(str(dcm), stop_before_pixels=True, force=True)
    rows = int(getattr(ds, "Rows", 0))
    cols = int(getattr(ds, "Columns", 0))

    svc = DecodeService(max_workers=1)
    svc.start()
    try:
        for _ in range(5):
            result = svc.decode(
                str(dcm), rows, cols, 1.0, 0.0, "MONOCHROME2", 1
            )
            assert result is not None
        assert svc.stats()["requests"] == 5
        assert svc.stats()["failures"] == 0
    finally:
        svc.shutdown()


# ── Benchmark ──

@pytest.mark.skipif(
    not Path("user_data/patients/dicom").exists(),
    reason="No local DICOM data for benchmark",
)
def test_benchmark_subprocess_vs_inprocess(capsys):
    """Benchmark subprocess decode overhead vs in-process."""
    dcm = _find_dicom_file_512()
    if dcm is None:
        dcm = _find_dicom_file()
    if dcm is None:
        pytest.skip("No .dcm file found")

    import pydicom
    ds = pydicom.dcmread(str(dcm), stop_before_pixels=True, force=True)
    rows = int(getattr(ds, "Rows", 0))
    cols = int(getattr(ds, "Columns", 0))
    slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
    photo = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2"))
    spp = int(getattr(ds, "SamplesPerPixel", 1))

    svc = DecodeService(max_workers=1)
    svc.start()
    try:
        # Warm up subprocess (first call has pool startup overhead)
        svc.decode(str(dcm), rows, cols, slope, intercept, photo, spp)
        _decode_worker(str(dcm), rows, cols, slope, intercept, photo, spp)

        N = 20

        # Subprocess decode
        t0 = time.perf_counter()
        for _ in range(N):
            svc.decode(str(dcm), rows, cols, slope, intercept, photo, spp)
        sub_ms = (time.perf_counter() - t0) / N * 1000

        # In-process decode
        t0 = time.perf_counter()
        for _ in range(N):
            _decode_worker(str(dcm), rows, cols, slope, intercept, photo, spp)
        inp_ms = (time.perf_counter() - t0) / N * 1000

        overhead_ms = sub_ms - inp_ms

        with capsys.disabled():
            print(f"\n{'='*60}")
            print(f"B3.11 Decode Service Benchmark ({dcm.name})")
            print(f"  Array: {rows}x{cols}")
            print(f"  Subprocess decode:  {sub_ms:.2f} ms")
            print(f"  In-process decode:  {inp_ms:.2f} ms")
            print(f"  IPC overhead:       {overhead_ms:.2f} ms")
            print(f"  Overhead ratio:     {overhead_ms/max(inp_ms,0.01):.0%}")
            print(f"{'='*60}")

        # Subprocess should be within 5x of in-process (generous for IPC)
        assert sub_ms < inp_ms * 5, (
            f"Subprocess ({sub_ms:.1f}ms) too slow vs in-process ({inp_ms:.1f}ms)"
        )
    finally:
        svc.shutdown()


# ── Helpers ──

def _find_dicom_file() -> Path | None:
    """Find any .dcm file in user_data."""
    root = Path("user_data/patients/dicom")
    for sd in root.iterdir():
        if not sd.is_dir():
            continue
        for sr in sd.iterdir():
            if not sr.is_dir():
                continue
            for f in sr.iterdir():
                if f.suffix == ".dcm":
                    return f
    return None


def _find_dicom_file_512() -> Path | None:
    """Find a 512x512 .dcm file."""
    import pydicom
    root = Path("user_data/patients/dicom")
    for sd in root.iterdir():
        if not sd.is_dir():
            continue
        for sr in sd.iterdir():
            if not sr.is_dir():
                continue
            for f in sr.iterdir():
                if f.suffix == ".dcm":
                    try:
                        ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
                        if int(getattr(ds, "Rows", 0)) == 512:
                            return f
                    except Exception:
                        pass
    return None
