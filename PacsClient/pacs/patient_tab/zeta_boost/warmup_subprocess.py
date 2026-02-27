"""Warmup Subprocess — GIL-free Mode B series pre-caching.

v2.2.3.2.3: Replaces the in-process DL_WARMUP thread with a fully isolated
subprocess.  The previous thread-based approach could not avoid GIL contention
because:
  - 8 pydicom ThreadPool workers acquire/release GIL at high frequency
  - SimpleITK RecursiveGaussian acquires GIL between C++ passes (~4× per series)
  - SQLite bulk_insert_instances holds GIL for the entire commit
  - Even at IDLE OS priority, Python's 5ms GIL switch interval causes
    10-50ms stalls on the main thread (VTK render)

By running in a separate *process*, all DICOM/ITK/DB work is truly isolated.
The viewer process only receives the result (numpy array + metadata dict) via
a multiprocessing.Queue, deserialises to vtkImageData in ~5-15ms, and feeds
the ZetaBoost cache.

Architecture
------------
::

    [Viewer Process]                     [Warmup Subprocess]
    ┌──────────────┐                     ┌──────────────────┐
    │ QTimer 100ms │ ◄─── result_queue ──│                  │
    │  poll result  │                     │ load_single_     │
    │  deserialize  │                     │ series_by_number │
    │  zeta.put()   │                     │ + apply_filters  │
    │               │ ───► request_queue ─│ + itk2numpy      │
    │               │       (sn, path)    │                  │
    └──────────────┘                     └──────────────────┘

Thread/GIL isolation
--------------------
multiprocessing.Process with start_method='spawn' (Windows default) creates
a fresh Python interpreter.  There is ZERO GIL sharing between viewer and
warmup.  The only shared state is the two Queues (lock-free pipe under the
hood on Windows).
"""
from __future__ import annotations

import logging
import multiprocessing
import multiprocessing.queues
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel / data classes
# ---------------------------------------------------------------------------
_SHUTDOWN = "__SHUTDOWN__"


@dataclass
class WarmupRequest:
    """Sent from viewer process → warmup subprocess."""
    series_number: str
    study_path: str
    patient_pk: Optional[int] = None
    study_pk: Optional[int] = None
    ordering_by_instances_number: Optional[bool] = True
    max_itk_threads: int = 2
    filter_config_path: str = ""


@dataclass
class WarmupResult:
    """Sent from warmup subprocess → viewer process."""
    series_number: str
    success: bool
    # Serialised VTK-ready data (None on failure)
    numpy_array: Optional[np.ndarray] = None  # The pixel data, Y-flipped, ready for VTK
    dimensions: Optional[Tuple[int, int, int]] = None  # (x, y, z)
    spacing: Optional[Tuple[float, float, float]] = None
    origin: Optional[Tuple[float, float, float]] = None
    direction: Optional[Tuple[float, ...]] = None  # 9-element direction cosine
    metadata: Optional[Dict[str, Any]] = None
    elapsed_ms: float = 0.0
    error: str = ""


# ---------------------------------------------------------------------------
# Subprocess entry point (runs in a SEPARATE Python interpreter)
# ---------------------------------------------------------------------------
def _warmup_subprocess_main(
    request_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    log_level: int = logging.INFO,
):
    """Main loop of the warmup subprocess.

    This function runs in a completely separate Python process.
    It has its own GIL, its own memory space, and its own imports.
    Nothing here can stall the viewer process.
    """
    # ── Set up logging ──
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | pid=%(process)d | warmup-subprocess | %(message)s",
    )
    _log = logging.getLogger("warmup_subprocess")

    # ── Set process priority to IDLE (Windows) ──
    # v2.2.3.4.0: Lowered from BELOW_NORMAL to IDLE.  During wheel scroll
    # (the user's primary interaction mode), even BELOW_NORMAL causes
    # memory-bus contention from ITK allocations that spikes the UI
    # thread's SetSlice from 8-15ms up to 20-45ms.  IDLE priority lets
    # the OS scheduler fully favour the viewer process; the warmup runs
    # during natural scroll pauses and between frames.  The warmup is
    # background cache-fill work, so taking longer is acceptable.
    try:
        if sys.platform == "win32":
            import ctypes
            IDLE_PRIORITY_CLASS = 0x00000040
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(),
                IDLE_PRIORITY_CLASS,
            )
            _log.info("Process priority set to IDLE")
    except Exception as e:
        _log.warning(f"Could not set process priority: {e}")

    _log.info("Warmup subprocess started (pid=%d)", os.getpid())

    while True:
        try:
            # Block until a request arrives (or SHUTDOWN sentinel)
            item = request_queue.get()

            if item == _SHUTDOWN:
                _log.info("Received SHUTDOWN — exiting")
                break

            if not isinstance(item, WarmupRequest):
                _log.warning(f"Ignoring unknown item type: {type(item)}")
                continue

            req: WarmupRequest = item
            _t0 = time.perf_counter()
            _log.info(f"Loading series={req.series_number} from {req.study_path}")

            try:
                result = _load_series_in_subprocess(req)
                result.elapsed_ms = (time.perf_counter() - _t0) * 1000.0
                _log.info(
                    f"Series={req.series_number} {'OK' if result.success else 'FAIL'} "
                    f"in {result.elapsed_ms:.0f}ms"
                )
            except Exception as e:
                result = WarmupResult(
                    series_number=req.series_number,
                    success=False,
                    error=f"{type(e).__name__}: {e}",
                    elapsed_ms=(time.perf_counter() - _t0) * 1000.0,
                )
                _log.error(f"Series={req.series_number} error: {e}")
                traceback.print_exc()

            # Send result back to viewer process
            result_queue.put(result)

        except KeyboardInterrupt:
            _log.info("KeyboardInterrupt — exiting")
            break
        except Exception as e:
            _log.error(f"Unexpected error in main loop: {e}")
            traceback.print_exc()
            # Don't crash — keep processing

    _log.info("Warmup subprocess exiting (pid=%d)", os.getpid())


def _load_series_in_subprocess(req: WarmupRequest) -> WarmupResult:
    """Load a single series entirely within the subprocess.

    This imports SimpleITK, pydicom, etc. inside the subprocess's own
    Python interpreter — they are NOT shared with the viewer process.
    """
    import SimpleITK as sitk

    # Import the project's loading pipeline
    # NOTE: These imports happen inside the subprocess.  They create
    # their own module objects, their own DB connections, etc.
    from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number

    study_path = req.study_path
    sn = req.series_number

    vtk_ready_array = None
    dimensions = None
    spacing = None
    origin = None
    direction = None
    metadata = None

    for item in load_single_series_by_number(
        study_path=study_path,
        series_number=int(sn),
        patient_pk=req.patient_pk,
        study_pk=req.study_pk,
        ordering_by_instances_number=req.ordering_by_instances_number,
        skip_fs_validation=True,
        max_itk_threads=req.max_itk_threads,
    ):
        vtk_image_data, meta, (_ppk, _spk) = item

        if vtk_image_data is None:
            continue

        # ─── Extract raw data from vtkImageData ───
        # We need to serialize this into numpy + primitives so it can
        # cross the process boundary via Queue (pickle).
        try:
            dims = vtk_image_data.GetDimensions()
            if int(dims[0]) <= 0 or int(dims[1]) <= 0:
                continue

            dimensions = (int(dims[0]), int(dims[1]), int(dims[2]))
            spacing = tuple(float(v) for v in vtk_image_data.GetSpacing())
            origin = tuple(float(v) for v in vtk_image_data.GetOrigin())

            # Extract direction matrix from field data
            fd = vtk_image_data.GetFieldData()
            dir_arr = fd.GetArray("DirectionMatrix") if fd else None
            if dir_arr and dir_arr.GetNumberOfTuples() == 16:
                direction = tuple(dir_arr.GetValue(i) for i in range(16))
            else:
                direction = None

            # Extract pixel data as numpy array
            from vtk.util.numpy_support import vtk_to_numpy
            scalars = vtk_image_data.GetPointData().GetScalars()
            if scalars is None:
                continue
            vtk_ready_array = vtk_to_numpy(scalars).copy()
            # Reshape to match VTK dimension order for reconstruction
            # VTK stores in (z, y, x) flat order with Fortran-style access
            vtk_ready_array = vtk_ready_array.reshape(
                (dimensions[2], dimensions[1], dimensions[0])
            )

            metadata = meta
        except Exception as e:
            logging.getLogger("warmup_subprocess").error(
                f"Error extracting VTK data: {e}"
            )
            traceback.print_exc()
            continue

        break  # Only first group

    if vtk_ready_array is None:
        return WarmupResult(
            series_number=sn,
            success=False,
            error="No valid data produced by load_single_series_by_number",
        )

    return WarmupResult(
        series_number=sn,
        success=True,
        numpy_array=vtk_ready_array,
        dimensions=dimensions,
        spacing=spacing,
        origin=origin,
        direction=direction,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Public API: WarmupSubprocessManager (used by ViewerController)
# ---------------------------------------------------------------------------
class WarmupSubprocessManager:
    """Manages the warmup subprocess lifecycle.

    Usage in ViewerController::

        self._warmup_mgr = WarmupSubprocessManager()
        self._warmup_mgr.start()

        # Enqueue work (non-blocking, returns immediately)
        self._warmup_mgr.submit(WarmupRequest(
            series_number="13", study_path="C:/...", ...
        ))

        # Poll for results (call from QTimer every 100ms)
        result = self._warmup_mgr.try_get_result()
        if result is not None and result.success:
            vtk_image = result_to_vtk(result)
            self.zeta_boost.put(result.series_number, vtk_image, result.metadata, ...)

        # Shutdown
        self._warmup_mgr.shutdown()
    """

    def __init__(self) -> None:
        self._request_queue: Optional[multiprocessing.Queue] = None
        self._result_queue: Optional[multiprocessing.Queue] = None
        self._process: Optional[multiprocessing.Process] = None
        self._started = False
        self._submitted_series: set = set()
        self._pending_count: int = 0

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    @property
    def pending_count(self) -> int:
        return self._pending_count

    def start(self) -> None:
        """Start the subprocess (idempotent — safe to call multiple times)."""
        if self._started and self.is_alive:
            return

        self._request_queue = multiprocessing.Queue(maxsize=32)
        self._result_queue = multiprocessing.Queue(maxsize=32)
        self._submitted_series.clear()
        self._pending_count = 0

        self._process = multiprocessing.Process(
            target=_warmup_subprocess_main,
            args=(self._request_queue, self._result_queue, logging.INFO),
            daemon=True,
            name="AIPacs-WarmupSubprocess",
        )
        self._process.start()
        self._started = True
        logger.info(
            f"[WarmupSubprocess] Started pid={self._process.pid}"
        )

    def submit(self, req: WarmupRequest) -> bool:
        """Submit a warmup request (non-blocking).

        Returns True if enqueued, False if skipped (duplicate or queue full).
        """
        if not self.is_alive:
            logger.warning("[WarmupSubprocess] Cannot submit — process not alive")
            return False

        sn = req.series_number
        if sn in self._submitted_series:
            return False

        try:
            self._request_queue.put_nowait(req)
            self._submitted_series.add(sn)
            self._pending_count += 1
            return True
        except Exception as e:
            logger.warning(f"[WarmupSubprocess] Submit failed: {e}")
            return False

    def try_get_result(self) -> Optional[WarmupResult]:
        """Non-blocking poll for a completed result.

        Returns WarmupResult if one is ready, None otherwise.
        Call this from a QTimer (e.g. every 100ms).
        """
        if self._result_queue is None:
            return None
        try:
            result = self._result_queue.get_nowait()
            if isinstance(result, WarmupResult):
                self._pending_count = max(0, self._pending_count - 1)
                return result
        except Exception:
            pass  # queue.Empty
        return None

    def shutdown(self, timeout: float = 3.0) -> None:
        """Gracefully shut down the subprocess."""
        if not self._started:
            return

        try:
            if self._request_queue is not None:
                self._request_queue.put_nowait(_SHUTDOWN)
        except Exception:
            pass

        if self._process is not None:
            try:
                self._process.join(timeout=timeout)
            except Exception:
                pass
            if self._process.is_alive():
                try:
                    self._process.kill()
                    logger.warning("[WarmupSubprocess] Force-killed subprocess")
                except Exception:
                    pass

        self._started = False
        self._process = None
        self._request_queue = None
        self._result_queue = None
        self._submitted_series.clear()
        self._pending_count = 0
        logger.info("[WarmupSubprocess] Shutdown complete")

    def reset(self) -> None:
        """Reset tracking state without killing subprocess (for new download session)."""
        self._submitted_series.clear()
        self._pending_count = 0
        # Drain any stale results
        while self.try_get_result() is not None:
            pass

    def has_submitted(self, series_number: str) -> bool:
        return series_number in self._submitted_series


def result_to_vtk(result: WarmupResult):
    """Reconstruct vtkImageData from a WarmupResult.

    This runs in the VIEWER process and is very fast (~5-15ms):
    just a numpy→VTK scalar copy + set dimensions/spacing/origin.

    Returns (vtkImageData, metadata_dict) or (None, None).
    """
    if not result.success or result.numpy_array is None:
        return None, None

    try:
        import vtk
        from vtk.util.numpy_support import numpy_to_vtk

        arr = result.numpy_array
        dims = result.dimensions
        spacing = result.spacing
        origin = result.origin

        vtk_image = vtk.vtkImageData()
        vtk_image.SetDimensions(dims[0], dims[1], dims[2])
        vtk_image.SetSpacing(spacing[0], spacing[1], spacing[2])
        vtk_image.SetOrigin(origin[0], origin[1], origin[2])

        # Flatten and convert to VTK array
        flat = arr.ravel(order='C')
        vtk_arr = numpy_to_vtk(flat, deep=True)
        vtk_arr.SetName("ImageScalars")
        vtk_image.GetPointData().SetScalars(vtk_arr)

        # Restore DirectionMatrix field data if available
        if result.direction is not None and len(result.direction) == 16:
            dir_array = vtk.vtkDoubleArray()
            dir_array.SetName("DirectionMatrix")
            dir_array.SetNumberOfTuples(16)
            for i in range(16):
                dir_array.SetValue(i, result.direction[i])
            vtk_image.GetFieldData().AddArray(dir_array)

        # Restore ITKOrigin field data
        if origin is not None:
            # We need the original ITK origin (before Y-flip).
            # The origin stored in the VTK image is already the flipped one.
            # Look for it in metadata if possible.
            _itk_origin = None
            if result.metadata and 'itk_origin' in result.metadata:
                _itk_origin = result.metadata['itk_origin']
            if _itk_origin is None:
                _itk_origin = origin  # Best we have

            origin_arr = vtk.vtkDoubleArray()
            origin_arr.SetName("ITKOrigin")
            origin_arr.SetNumberOfTuples(3)
            for i in range(3):
                origin_arr.SetValue(i, float(_itk_origin[i]))
            vtk_image.GetFieldData().AddArray(origin_arr)

        # Restore ITKSpacing field data
        if spacing is not None:
            spacing_arr = vtk.vtkDoubleArray()
            spacing_arr.SetName("ITKSpacing")
            spacing_arr.SetNumberOfTuples(3)
            for i in range(3):
                spacing_arr.SetValue(i, float(spacing[i]))
            vtk_image.GetFieldData().AddArray(spacing_arr)

        # Restore ITKDimensions field data
        if dims is not None:
            dims_arr = vtk.vtkDoubleArray()
            dims_arr.SetName("ITKDimensions")
            dims_arr.SetNumberOfTuples(3)
            for i in range(3):
                dims_arr.SetValue(i, float(dims[i]))
            vtk_image.GetFieldData().AddArray(dims_arr)

        return vtk_image, result.metadata

    except Exception as e:
        logger.error(f"[result_to_vtk] Error reconstructing VTK: {e}")
        traceback.print_exc()
        return None, None
