"""
Decode Service (B3.11)
======================
Subprocess-based DICOM decode for GIL isolation.

Architecture:
    Main process → ProcessPoolExecutor(1, spawn) → decode subprocess
    - Subprocess has its own Python GIL — decode does NOT block UI thread
    - Uses pickle for IPC (~0.3ms overhead for 512KB slice)
    - Worker auto-restarts after ``max_tasks_per_child`` decodes (memory guard)
    - Falls back to in-process decode on failure/timeout

Integration:
    ``Lightweight2DPipeline._decode_into_cache()`` calls
    ``service.decode()`` for background prefetch.  Foreground (main thread)
    cache misses still use in-process decode (lowest latency).

This is a **CPU efficiency** optimization, not a latency optimization.
B3.7 (surrogate) handles latency; B3.12 (disk cache) handles re-opens;
B3.11 reduces GIL contention from background decode workers.

Enable/disable:
    ``AIPACS_DECODE_SERVICE=0`` env var disables the service (default: enabled).
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _is_content_decode_error(exc: Exception) -> bool:
    """Return True for per-file decode failures that should not poison service health.

    During active download overlap we may probe partially-written or malformed
    DICOM files. Those are valid per-request misses for the subprocess path, not
    evidence that the worker pool itself is unhealthy.
    """
    if isinstance(exc, (FutureTimeoutError, BrokenProcessPool)):
        return False
    msg = str(exc).lower()
    soft_markers = (
        "pixel data",
        "transfersyntaxuid",
        "transfer syntax",
        "dicom",
        "dicom file meta",
        "file meta information",
        "missing dicom",
        "photometric",
        "cannot reshape array",
        "end of file",
        "unexpected eof",
        "buffer is smaller",
        "bytes length",
        "bytes not long enough",
        "no pixel data",
        "unable to decode",
        "could not read",
    )
    return any(marker in msg for marker in soft_markers)

# ── Env toggle ────────────────────────────────────────────────────────────
_ENABLED = os.environ.get("AIPACS_DECODE_SERVICE", "1") != "0"

# Worker config
_MAX_WORKERS = 1
_MAX_TASKS_PER_CHILD = 200  # auto-restart worker after 200 decodes
_DECODE_TIMEOUT_S = 10.0    # generous timeout for large slices
_STARTUP_DECODE_TIMEOUT_S = 30.0
_STARTUP_GRACE_S = 30.0
_MAX_HARD_FAILURE_STREAK = 3
_MAX_RESTART_ATTEMPTS = 2


# ── Subprocess worker function ────────────────────────────────────────────
# This runs in a SEPARATE process with its own GIL.
# MUST be importable at module level (no closures, no Qt, no VTK).

def _decode_worker(
    file_path: str,
    rows: int,
    cols: int,
    slope: float,
    intercept: float,
    photometric: str,
    samples_per_pixel: int,
) -> np.ndarray:
    """Decode a single DICOM slice.  Runs in subprocess.

    Same logic as ``Lightweight2DPipeline._decode_slice()`` minus disk cache.
    Returns a contiguous numpy array (int16, uint16, float32, or uint8).
    """
    import math as _math

    import numpy as _np
    import pydicom
    from pydicom.dataset import FileMetaDataset
    from pydicom.uid import (
        ExplicitVRBigEndian,
        ExplicitVRLittleEndian,
        ImplicitVRLittleEndian,
    )

    ds = pydicom.dcmread(file_path, stop_before_pixels=False, force=True)
    tsuid = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
    if tsuid is None:
        file_meta = getattr(ds, "file_meta", None)
        if file_meta is None:
            file_meta = FileMetaDataset()
            ds.file_meta = file_meta
        if getattr(ds, "is_little_endian", True):
            file_meta.TransferSyntaxUID = (
                ImplicitVRLittleEndian
                if getattr(ds, "is_implicit_VR", True)
                else ExplicitVRLittleEndian
            )
        else:
            file_meta.TransferSyntaxUID = ExplicitVRBigEndian
    arr = _np.asarray(ds.pixel_array)

    if arr.ndim == 3 and samples_per_pixel < 3:
        arr = arr[0]  # multi-frame fallback

    # ── RGB path ──
    if samples_per_pixel >= 3:
        if arr.ndim == 4:
            arr = arr[0]
        if arr.dtype != _np.uint8:
            arr = _np.clip(arr, 0, 255).astype(_np.uint8)
        return _np.ascontiguousarray(arr)

    # ── Rescale slope/intercept ──
    _slope = float(getattr(ds, "RescaleSlope", slope) or slope or 1.0)
    _intercept = float(getattr(ds, "RescaleIntercept", intercept) or intercept or 0.0)
    _photo = str(
        getattr(ds, "PhotometricInterpretation", photometric or "MONOCHROME2")
    ).upper()

    slope_is_unity = _math.isclose(_slope, 1.0)
    intercept_is_int = _math.isclose(_intercept, round(_intercept))
    is_monochrome2 = _photo != "MONOCHROME1"

    # ── Fast int16 path ──
    if slope_is_unity and intercept_is_int and is_monochrome2:
        if not _math.isclose(_intercept, 0.0):
            int_offset = int(round(_intercept))
            if arr.dtype in (_np.uint16, _np.int16):
                arr = arr.astype(_np.int16, copy=False)
                arr = arr + _np.int16(int_offset)
            else:
                arr = arr.astype(_np.float32, copy=False)
                arr = arr + float(_intercept)
        elif arr.dtype not in (_np.int16, _np.uint16, _np.float32):
            arr = arr.astype(_np.int16, copy=False)
        return _np.ascontiguousarray(arr)

    # ── Float32 slow path ──
    arr = arr.astype(_np.float32, copy=False)
    if not slope_is_unity or not _math.isclose(_intercept, 0.0):
        arr = arr * float(_slope) + float(_intercept)
    if not is_monochrome2:
        arr = float(arr.max()) + float(arr.min()) - arr

    return _np.ascontiguousarray(arr)


# ── Service class ─────────────────────────────────────────────────────────

class DecodeService:
    """Subprocess-based decode pool with auto-restart and fallback.

    Usage::

        service = DecodeService()
        service.start()
        arr = service.decode(path, rows, cols, slope, intercept, photo, spp)
        if arr is None:
            # fallback to in-process
        service.shutdown()
    """

    def __init__(
        self,
        max_workers: int = _MAX_WORKERS,
        max_tasks_per_child: int = _MAX_TASKS_PER_CHILD,
        timeout: float = _DECODE_TIMEOUT_S,
    ):
        self._max_workers = max_workers
        self._max_tasks = max_tasks_per_child
        self._timeout = timeout
        self._pool: Optional[ProcessPoolExecutor] = None
        self._available = False
        self._lock = threading.Lock()
        self._total_requests = 0
        self._total_failures = 0
        self._health_window_requests = 0
        self._health_window_failures = 0
        self._hard_failure_streak = 0
        self._restart_attempts = 0
        self._max_restart_attempts = _MAX_RESTART_ATTEMPTS
        self._restart_in_progress = False
        self._pool_generation = 0
        self._last_start_ts = 0.0

    @property
    def is_available(self) -> bool:
        return self._available

    def start(self) -> None:
        """Start the subprocess pool.  No-op if already started or disabled."""
        if not _ENABLED:
            logger.info("[B3.11] Decode service DISABLED (AIPACS_DECODE_SERVICE=0)")
            return
        if self._available:
            return
        with self._lock:
            if self._available:
                return
            try:
                import multiprocessing as mp
                ctx = mp.get_context("spawn")
                self._pool = ProcessPoolExecutor(
                    max_workers=self._max_workers,
                    mp_context=ctx,
                    max_tasks_per_child=self._max_tasks,
                )
                self._available = True
                self._pool_generation += 1
                self._last_start_ts = time.monotonic()
                self._reset_health_window_locked()
                self._restart_in_progress = False
                logger.info(
                    "[B3.11] Decode service started: %d worker(s), "
                    "max_tasks_per_child=%d",
                    self._max_workers,
                    self._max_tasks,
                )
            except Exception:
                logger.exception("[B3.11] Failed to start decode service")
                self._available = False
                self._restart_in_progress = False

    def decode(
        self,
        file_path: str,
        rows: int,
        cols: int,
        slope: float,
        intercept: float,
        photometric: str,
        samples_per_pixel: int,
    ) -> Optional[np.ndarray]:
        """Decode via subprocess.  Returns None on failure (caller must fallback).

        Thread-safe — multiple callers can submit concurrently.
        """
        if not self._available:
            return None
        try:
            with self._lock:
                self._total_requests += 1
                self._health_window_requests += 1
                pool = self._pool
                pool_generation = self._pool_generation
            if pool is None:
                return None
            future = pool.submit(
                _decode_worker,
                file_path,
                rows,
                cols,
                slope,
                intercept,
                photometric,
                samples_per_pixel,
            )
            timeout = self._timeout
            if (time.monotonic() - self._last_start_ts) < _STARTUP_GRACE_S:
                timeout = max(timeout, _STARTUP_DECODE_TIMEOUT_S)
            result = future.result(timeout=timeout)
            with self._lock:
                if pool_generation == self._pool_generation:
                    self._hard_failure_streak = 0
            return result
        except Exception as exc:
            if isinstance(exc, FutureTimeoutError):
                if (time.monotonic() - self._last_start_ts) < _STARTUP_GRACE_S:
                    logger.debug(
                        "[B3.11] Subprocess decode timed out during worker cold start",
                        exc_info=True,
                    )
                    return None
            if _is_content_decode_error(exc):
                logger.debug(
                    "[B3.11] Subprocess decode soft-failed for content/input issue",
                    exc_info=True,
                )
            else:
                with self._lock:
                    stale_generation = pool_generation != self._pool_generation
                    stale_pool = pool is not None and pool is not self._pool
                    if stale_generation or stale_pool:
                        return None
                    self._total_failures += 1
                    self._health_window_failures += 1
                    self._hard_failure_streak += 1
                    total_failures = self._total_failures
                    total_requests = self._total_requests
                if total_failures <= 5:
                    logger.debug(
                        "[B3.11] Subprocess decode failed (%d/%d)",
                        total_failures,
                        total_requests,
                        exc_info=True,
                    )
                # Check if pool is broken
                self._check_health(exc)
            return None

    def stats(self) -> dict:
        return {
            "available": self._available,
            "requests": self._total_requests,
            "failures": self._total_failures,
            "health_window_requests": self._health_window_requests,
            "health_window_failures": self._health_window_failures,
        }

    def shutdown(self) -> None:
        """Shutdown the pool.  Safe to call multiple times."""
        with self._lock:
            self._available = False
            self._restart_in_progress = False
            if self._pool:
                self._shutdown_pool_locked()
                logger.info("[B3.11] Decode service shut down")

    def _reset_health_window_locked(self) -> None:
        self._health_window_requests = 0
        self._health_window_failures = 0
        self._hard_failure_streak = 0

    def _shutdown_pool_locked(self) -> None:
        pool = self._pool
        self._pool = None
        if pool:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def _restart_pool(self, reason: str) -> bool:
        with self._lock:
            if self._restart_in_progress:
                return True
            if self._restart_attempts >= self._max_restart_attempts:
                return False
            self._restart_in_progress = True
            self._restart_attempts += 1
            attempt = self._restart_attempts
            self._available = False
            self._shutdown_pool_locked()
        logger.warning(
            "[B3.11] Decode service hard failure (%s) — restarting pool (%d/%d)",
            reason,
            attempt,
            self._max_restart_attempts,
        )
        self.start()
        with self._lock:
            restarted = self._available
            if restarted:
                self._reset_health_window_locked()
            self._restart_in_progress = False
        return restarted

    def _disable_service(self, reason: str, fail_rate: float | None = None) -> None:
        if fail_rate is None:
            logger.warning("[B3.11] Decode service disabling — %s", reason)
        else:
            logger.warning(
                "[B3.11] Decode service failure rate %.0f%% — disabling (%s)",
                fail_rate * 100,
                reason,
            )
        with self._lock:
            self._available = False
            self._restart_in_progress = False
            self._shutdown_pool_locked()

    def _check_health(self, exc: Exception | None = None) -> None:
        """Attempt bounded restart recovery before fully disabling the service."""
        is_broken_pool = isinstance(exc, BrokenProcessPool)
        with self._lock:
            total_failures = self._health_window_failures
            total_requests = self._health_window_requests
            hard_failure_streak = self._hard_failure_streak

        if is_broken_pool and self._restart_pool("broken_process_pool"):
            return

        if hard_failure_streak >= _MAX_HARD_FAILURE_STREAK and self._restart_pool("hard_failure_streak"):
            return

        if total_failures > 10 and total_requests > 0:
            fail_rate = total_failures / total_requests
            if fail_rate > 0.5:
                self._disable_service("failure_rate_exhausted", fail_rate=fail_rate)


# ── Module-level singleton ────────────────────────────────────────────────
_instance: Optional[DecodeService] = None
_instance_lock = threading.Lock()


def get_decode_service() -> DecodeService:
    """Get or create the global decode service singleton.

    First call starts the subprocess pool (takes ~1s on Windows).
    """
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is not None:
            return _instance
        _instance = DecodeService()
        _instance.start()
        return _instance


def shutdown_decode_service() -> None:
    """Shutdown the global decode service.  Called at app exit."""
    global _instance
    if _instance is not None:
        _instance.shutdown()
        _instance = None
