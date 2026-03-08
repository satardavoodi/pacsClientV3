"""Image Slice Booster — Mode B per-slice prefetch for the single active series.

Purpose
-------
In Mode B (concurrent download + viewing) the series-level ZetaBoost cache is
disabled to avoid the 1–2 GB RAM overhead of pre-loading adjacent entire series.
Instead, ``ImageSliceBooster`` maintains a small (≤ 2·WINDOW + 1 slices)
decoded-pixel window around the user's current scroll position for the **single
active series** only, keeping typical Mode B overhead under ~25 MB.

How it fits into the existing VTK architecture
-----------------------------------------------
The VTK viewer already stores the loaded series in a full ``vtkImageData``
volume.  The Image Slice Booster works *alongside* it:

1. When a series becomes active, ``set_active()`` is called. A low-OS-priority
   daemon thread begins reading DICOM pixel arrays for slices
   ``[center - WINDOW .. center + WINDOW]`` into an in-memory dict.
2. As the user scrolls, ``on_slice_changed()`` shifts the window.  New boundary
   slices are read in; slices outside ``[center - WINDOW - HYSTERESIS ..
   center + WINDOW + HYSTERESIS]`` are evicted to bound memory use.
3. External code may call ``get_decoded(sn, idx)`` to retrieve a pre-decoded
   numpy array.  When ``grow_current_series_inplace()`` needs pixel data during
   progressive Mode B loading the pixels are already in Python memory, avoiding
   a second disk read.

VTK / ITK feasibility note
---------------------------
VTK's ``vtkImageData`` supports incremental Z-extension via
``grow_vtk_inplace()``.  Supplying pre-decoded pixel arrays through this path
means the extension cost is a pointer-swap on the VTK scalar array rather than
a full disk-read + DICOM-decode.  This is safe while the viewer is rendering;
VTK's render pipeline re-reads the scalar pointer on every ``Render()`` call.

Threading
---------
One daemon thread with OS priority ``THREAD_PRIORITY_IDLE`` (−15 on Windows,
``nice +15`` on Linux).  The thread is cancelled via ``threading.Event`` before
any new series is activated or before the booster is cleared.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Dict, List, Optional

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_WINDOW: int = 20   # slices each side of center
_HYSTERESIS: int = 5        # keep extra slices beyond window before evicting


def _set_thread_low_priority() -> None:
    """Demote current thread to lowest OS scheduling priority (best-effort)."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), -15
            )
        else:
            os.nice(15)
    except Exception:
        pass


class ImageSliceBooster:
    """Maintains a decoded-pixel window of ±WINDOW slices for the active series.

    Create one instance per ViewerController / PatientTab.
    All public methods are thread-safe.

    Typical lifecycle
    -----------------
    ::

        booster = ImageSliceBooster()

        # Mode B starts (series displayed in viewer) ─
        booster.set_active(series_number, instance_paths, center_slice=0)

        # User scrolls ─
        booster.on_slice_changed(series_number, new_slice_index)

        # Query pre-decoded pixels (e.g. for grow_current_series_inplace) ─
        arr = booster.get_decoded(series_number, slice_idx)   # → np.ndarray | None

        # Series changed or Mode B ended ─
        booster.clear()
    """

    def __init__(self, window: int = _DEFAULT_WINDOW, logger=None) -> None:
        self._window: int = max(1, int(window))
        self._logger = logger
        self._lock: threading.Lock = threading.Lock()
        self._cancel: threading.Event = threading.Event()
        self._active_series: Optional[str] = None
        self._instance_paths: List[str] = []   # ordered DICOM file paths
        self._center_slice: int = 0
        self._total_slices: int = 0
        # slice_idx → decoded numpy array (dtype uint16 or int16 typically)
        self._pixel_cache: Dict[int, "np.ndarray"] = {}
        self._worker: Optional[threading.Thread] = None

    # ---------------------------------------------------------------------- public API

    def set_active(
        self,
        series_number: str,
        instance_paths: List[str],
        center_slice: int = 0,
    ) -> None:
        """Activate boosting for a new series.

        Any previously active series data is discarded immediately.
        The background worker begins pre-fetching slices
        ``[center - WINDOW .. center + WINDOW]``.

        Parameters
        ----------
        series_number:
            Unique series identifier (string, e.g. "3").
        instance_paths:
            **Ordered** list of absolute DICOM file paths for the series.
            The order must match the Z-axis slice ordering shown by VTK.
        center_slice:
            Initial slice index around which to build the window (0-based).
        """
        sn = str(series_number)
        paths: List[str] = list(instance_paths or [])
        total: int = len(paths)
        center: int = max(0, min(int(center_slice), total - 1)) if total > 0 else 0

        # Cancel and join old worker.
        self._cancel.set()
        if self._worker is not None:
            try:
                self._worker.join(timeout=0.5)
            except Exception:
                pass

        with self._lock:
            self._active_series = sn
            self._instance_paths = paths
            self._center_slice = center
            self._total_slices = total
            self._pixel_cache.clear()

        if not paths or not _NUMPY_AVAILABLE:
            self._log(f"SKIP series={sn} (no paths or numpy unavailable)")
            return

        self._cancel.clear()
        self._worker = threading.Thread(
            target=self._worker_fn,
            args=(sn, paths, center),
            daemon=True,
            name=f"ImgBoost-{sn[:20]}",
        )
        self._worker.start()
        self._log(
            f"ACTIVE series={sn} total={total} center={center} window=±{self._window}"
        )

    def on_slice_changed(self, series_number: str, new_center: int) -> None:
        """Notify the booster that the user scrolled to a new slice index.

        If the new center is more than ``WINDOW // 2`` slices from the last
        known center, the worker is restarted to cover the new position.
        Slices outside ``[new_center - WINDOW - HYSTERESIS ..
        new_center + WINDOW + HYSTERESIS]`` are evicted.
        """
        sn = str(series_number)
        with self._lock:
            if self._active_series != sn:
                return
            old_center = self._center_slice
            total = self._total_slices
            new_pos = max(0, min(int(new_center), total - 1)) if total > 0 else 0
            self._center_slice = new_pos
            paths: List[str] = list(self._instance_paths)
            center = new_pos

        # Only restart the worker when the scroll moved meaningfully.
        if abs(new_pos - old_center) < self._window // 2:
            return  # window covers the new position; existing prefetch is fine

        # Cancel the current worker before mutating the cache.
        self._cancel.set()
        if self._worker is not None:
            try:
                self._worker.join(timeout=0.3)
            except Exception:
                pass

        # Evict slices outside the extended keep-range.
        keep_lo = center - self._window - _HYSTERESIS
        keep_hi = center + self._window + _HYSTERESIS
        with self._lock:
            evict = [i for i in list(self._pixel_cache) if not (keep_lo <= i <= keep_hi)]
            for i in evict:
                del self._pixel_cache[i]

        self._cancel.clear()
        self._worker = threading.Thread(
            target=self._worker_fn,
            args=(sn, paths, center),
            daemon=True,
            name=f"ImgBoost-{sn[:20]}-s{center}",
        )
        self._worker.start()

    def get_decoded(self, series_number: str, slice_idx: int) -> Optional["np.ndarray"]:
        """Return the pre-decoded pixel array for a specific slice index, or None.

        Returns immediately (O(1) dict lookup); never blocks on I/O.
        The returned array belongs to the cache — do not mutate it.
        """
        with self._lock:
            if self._active_series != str(series_number):
                return None
            return self._pixel_cache.get(int(slice_idx))

    def update_paths(self, series_number: str, instance_paths: List[str]) -> None:
        """Update the file list for an active series without full reset.

        This is called when new DICOM files arrive during a progressive
        download.  If the file count grew, the worker is restarted only
        when new indices fall within the current ±WINDOW range and are
        not yet cached.  Already-cached slices are preserved.

        Parameters
        ----------
        series_number:
            Must match the currently active series; ignored otherwise.
        instance_paths:
            Updated **ordered** list of absolute DICOM file paths.
        """
        sn = str(series_number)
        paths: List[str] = list(instance_paths or [])
        with self._lock:
            if self._active_series != sn:
                return
            old_total = self._total_slices
            self._instance_paths = paths
            self._total_slices = len(paths)
            center = self._center_slice

        new_total = len(paths)
        if new_total <= old_total:
            return  # No new files

        # Check if any new indices fall within ±WINDOW of current center
        # and are not yet cached.
        need_restart = False
        lo = max(0, center - self._window)
        hi = min(new_total - 1, center + self._window)
        with self._lock:
            for idx in range(old_total, new_total):
                if lo <= idx <= hi and idx not in self._pixel_cache:
                    need_restart = True
                    break

        if need_restart:
            self._cancel.set()
            if self._worker is not None:
                try:
                    self._worker.join(timeout=0.3)
                except Exception:
                    pass
            self._cancel.clear()
            self._worker = threading.Thread(
                target=self._worker_fn,
                args=(sn, paths, center),
                daemon=True,
                name=f"ImgBoost-{sn[:20]}-upd",
            )
            self._worker.start()
            self._log(
                f"UPDATE_PATHS series={sn} old_total={old_total} new_total={new_total} "
                f"center={center} restarted_worker=True"
            )
        else:
            self._log(
                f"UPDATE_PATHS series={sn} old_total={old_total} new_total={new_total} "
                f"center={center} restarted_worker=False"
            )

    def clear(self) -> None:
        """Deactivate boosting and discard all cached pixel data immediately."""
        self._cancel.set()
        if self._worker is not None:
            try:
                self._worker.join(timeout=0.3)
            except Exception:
                pass
        with self._lock:
            self._active_series = None
            self._instance_paths = []
            self._pixel_cache.clear()
            self._center_slice = 0
            self._total_slices = 0
        self._cancel.clear()
        self._log("CLEARED")

    @property
    def active_series(self) -> Optional[str]:
        """Currently active series number, or None if inactive."""
        with self._lock:
            return self._active_series

    @property
    def cached_count(self) -> int:
        """Number of slices currently held in the pixel cache."""
        with self._lock:
            return len(self._pixel_cache)

    @property
    def is_active(self) -> bool:
        """True when a series is currently registered."""
        with self._lock:
            return self._active_series is not None

    # ---------------------------------------------------------------------- background worker

    def _worker_fn(
        self,
        series_number: str,
        paths: List[str],
        center: int,
    ) -> None:
        """Background worker: reads DICOM pixel arrays for the ±WINDOW slice ring."""
        _set_thread_low_priority()
        try:
            import pydicom  # type: ignore
        except ImportError:
            return

        total = len(paths)
        window = self._window
        indices = self._priority_order(center, total, window)

        for idx in indices:
            if self._cancel.is_set():
                return

            # Skip already-cached slices without holding the lock for long.
            with self._lock:
                if self._active_series != series_number:
                    return
                if idx in self._pixel_cache:
                    continue

            if not (0 <= idx < total):
                continue

            path = paths[idx]
            try:
                ds = pydicom.dcmread(str(path), stop_before_pixels=False, force=True)
                arr: "np.ndarray" = ds.pixel_array
                with self._lock:
                    # Double-check series hasn't changed since the read started.
                    if self._active_series != series_number:
                        return
                    self._pixel_cache[idx] = arr
            except Exception:
                pass  # Non-fatal — skip unreadable file.

            # Yield to other threads between reads (prevents GIL monopolisation).
            time.sleep(0)

        self._log(
            f"WINDOW_DONE series={series_number} center={center} "
            f"cached={self.cached_count}"
        )

    @staticmethod
    def _priority_order(center: int, total: int, window: int) -> List[int]:
        """Return slice indices in prefetch priority: center first, then outward."""
        order: List[int] = []
        if 0 <= center < total:
            order.append(center)
        for offset in range(1, window + 1):
            hi = center + offset
            lo = center - offset
            if 0 <= hi < total:
                order.append(hi)
            if 0 <= lo < total:
                order.append(lo)
        return order

    # ---------------------------------------------------------------------- logging

    def _log(self, msg: str) -> None:
        full = f"[ImageBoost] {msg}"
        try:
            print(full)
        except Exception:
            pass
        if self._logger:
            try:
                self._logger.debug(full)
            except Exception:
                pass
