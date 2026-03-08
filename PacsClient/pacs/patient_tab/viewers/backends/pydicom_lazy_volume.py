from __future__ import annotations

import logging
import os
import queue
import tempfile
import threading
import time
import itertools
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, Signal
import vtkmodules.all as vtk
from vtkmodules.util import numpy_support

from .lazy_volume_registry import register_loader
from .pydicom_2d_backend import PyDicom2DBackend

logger = logging.getLogger(__name__)


def _vtk_array_type_for(dtype: np.dtype) -> int:
    try:
        return int(numpy_support.get_vtk_array_type(dtype))
    except Exception:
        if np.issubdtype(dtype, np.uint8):
            return int(vtk.VTK_UNSIGNED_CHAR)
        if np.issubdtype(dtype, np.int16):
            return int(vtk.VTK_SHORT)
        if np.issubdtype(dtype, np.uint16):
            return int(vtk.VTK_UNSIGNED_SHORT)
        if np.issubdtype(dtype, np.float32):
            return int(vtk.VTK_FLOAT)
        return int(vtk.VTK_FLOAT)


def _to_iop_matrix(iop: Tuple[float, float, float, float, float, float]) -> np.ndarray:
    row = np.asarray(iop[0:3], dtype=np.float64)
    col = np.asarray(iop[3:6], dtype=np.float64)
    row_norm = float(np.linalg.norm(row))
    col_norm = float(np.linalg.norm(col))
    if row_norm > 1e-12:
        row = row / row_norm
    if col_norm > 1e-12:
        col = col / col_norm
    normal = np.cross(row, col)
    normal_norm = float(np.linalg.norm(normal))
    if normal_norm > 1e-12:
        normal = normal / normal_norm
    M = np.eye(4, dtype=np.float64)
    M[0:3, 0] = row
    M[0:3, 1] = col
    M[0:3, 2] = normal
    # Match legacy convert_itk2vtk(): array Y-flip + negate row-1 in direction.
    M[1, 0:3] = -M[1, 0:3]
    return M


class PyDicomLazyVolume(QObject):
    """Shared NumPy-backed VTK volume with on-demand per-slice decode."""
    slice_ready = Signal(int, float, bool)  # slice_index, decode_ms, cache_hit
    decode_failed = Signal(str)

    def __init__(self, backend: PyDicom2DBackend):
        super().__init__()
        self.backend = backend
        self.slice_count = backend.get_slice_count()
        if self.slice_count <= 0:
            raise ValueError("PyDicomLazyVolume requires a non-empty series")

        g0 = backend.get_geometry(0)
        frame0 = backend.get_pixel_array(0)
        self.rows = int(g0.rows)
        self.cols = int(g0.cols)
        self.components = 1 if frame0.ndim == 2 else int(frame0.shape[2])

        target_dtype = frame0.dtype
        if np.issubdtype(target_dtype, np.floating) and self.components == 1:
            target_dtype = np.int16
        self.dtype = np.dtype(target_dtype)

        self._tmp_file = tempfile.NamedTemporaryFile(prefix="aipacs_lazy_", suffix=".bin", delete=False)
        self._tmp_file_path = self._tmp_file.name
        self._tmp_file.close()

        shape = (self.slice_count, self.rows, self.cols) if self.components == 1 else (
            self.slice_count,
            self.rows,
            self.cols,
            self.components,
        )
        self._volume = np.memmap(self._tmp_file_path, mode="w+", dtype=self.dtype, shape=shape)
        self._loaded = np.zeros((self.slice_count,), dtype=np.bool_)
        self._load_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: Dict[int, int] = {}
        self._closing = threading.Event()
        self._decoder_failed = False
        self._decode_failed_emitted = False
        self._cache_radius = max(2, int(os.getenv("AIPACS_PYDICOM_CACHE_RADIUS", "20") or "20"))
        self._cache_radius_idle = int(self._cache_radius)
        self._cache_radius_fast = max(
            2,
            int(
                os.getenv(
                    "AIPACS_PYDICOM_FAST_CACHE_RADIUS",
                    str(max(6, int(self._cache_radius_idle // 2))),
                )
                or str(max(6, int(self._cache_radius_idle // 2)))
            ),
        )
        self._prefetch_radius_idle = max(
            1,
            int(
                os.getenv("AIPACS_PYDICOM_PREFETCH_RADIUS_IDLE", str(self._cache_radius_idle))
                or str(self._cache_radius_idle)
            ),
        )
        self._prefetch_radius_fast = max(
            1,
            int(
                os.getenv(
                    "AIPACS_PYDICOM_PREFETCH_RADIUS_FAST",
                    str(max(4, int(self._cache_radius_idle // 3))),
                )
                or str(max(4, int(self._cache_radius_idle // 3)))
            ),
        )
        self._prefetch_radius = int(self._prefetch_radius_idle)
        self._interaction_idle_ms = max(
            60.0, float(os.getenv("AIPACS_PYDICOM_INTERACTION_IDLE_MS", "220") or "220")
        )
        self._directional_ratio = min(
            0.9, max(0.05, float(os.getenv("AIPACS_PYDICOM_DIRECTIONAL_RATIO", "0.35") or "0.35"))
        )
        self._high_velocity_sps = max(
            10.0,
            float(os.getenv("AIPACS_PYDICOM_HIGH_VELOCITY_SPS", "24") or "24"),
        )
        self._very_high_velocity_sps = max(
            float(self._high_velocity_sps) + 1.0,
            float(os.getenv("AIPACS_PYDICOM_VERY_HIGH_VELOCITY_SPS", "42") or "42"),
        )
        self._prefetch_radius_high_velocity = max(
            1,
            int(os.getenv("AIPACS_PYDICOM_PREFETCH_RADIUS_HIGH", "2") or "2"),
        )
        self._prefetch_radius_very_high_velocity = max(
            1,
            int(os.getenv("AIPACS_PYDICOM_PREFETCH_RADIUS_VERY_HIGH", "1") or "1"),
        )
        self._relevance_radius_high_velocity = max(
            2,
            int(
                os.getenv(
                    "AIPACS_PYDICOM_RELEVANCE_RADIUS_HIGH",
                    str(max(2, int(self._cache_radius_fast // 2))),
                )
                or str(max(2, int(self._cache_radius_fast // 2)))
            ),
        )
        self._relevance_radius_very_high_velocity = max(
            2,
            int(
                os.getenv(
                    "AIPACS_PYDICOM_RELEVANCE_RADIUS_VERY_HIGH",
                    str(max(2, int(self._cache_radius_fast // 3))),
                )
                or str(max(2, int(self._cache_radius_fast // 3)))
            ),
        )
        self._heavy_series_slice_threshold = max(
            100,
            int(os.getenv("AIPACS_HEAVY_SERIES_SLICE_THRESHOLD", "300") or "300"),
        )
        if int(self.slice_count) >= int(self._heavy_series_slice_threshold):
            # Heavy stacks (300+ slices): keep decode focused on near-target slices
            # to reduce dropped frames and GIL pressure during rapid drag.
            self._cache_radius_fast = max(2, min(int(self._cache_radius_fast), 6))
            self._prefetch_radius_idle = max(2, min(int(self._prefetch_radius_idle), 10))
            self._prefetch_radius_fast = max(1, min(int(self._prefetch_radius_fast), 2))
            self._prefetch_radius_high_velocity = max(
                1,
                min(int(self._prefetch_radius_high_velocity), 1),
            )
            self._prefetch_radius_very_high_velocity = 1
            self._relevance_radius_high_velocity = max(
                2,
                min(int(self._relevance_radius_high_velocity), 3),
            )
            self._relevance_radius_very_high_velocity = max(
                2,
                min(int(self._relevance_radius_very_high_velocity), 2),
            )
            self._directional_ratio = min(float(self._directional_ratio), 0.22)
        self._interactive_until_ms = 0.0
        self._last_hint_ts_ms = 0.0
        self._last_hint_idx = 0
        self._last_hint_velocity_sps = 0.0
        self._request_seq = itertools.count()
        self._request_queue: "queue.PriorityQueue[Tuple[int, int, Optional[int]]]" = queue.PriorityQueue(
            maxsize=max(512, self.slice_count * 4)
        )

        self._requests = 0
        self._cache_hits = 0
        self._decode_count = 0
        self._decode_ms_total = 0.0
        self._decode_read_ms_total = 0.0
        self._decode_pixel_ms_total = 0.0
        self._decode_post_ms_total = 0.0
        self._requested_slice_idx = 0
        self._last_requested_slice_idx = 0
        self._scroll_direction = 0

        try:
            if hasattr(self.backend, "set_prefetch_radius"):
                self.backend.set_prefetch_radius(0)
        except Exception:
            pass

        self.vtk_image_data = vtk.vtkImageData()
        self.vtk_image_data.SetDimensions(self.cols, self.rows, self.slice_count)

        spacing_z = (
            float(g0.spacing_between_slices)
            if g0.spacing_between_slices is not None
            else float(g0.slice_thickness or 1.0)
        )
        spacing = (float(g0.pixel_spacing[1]), float(g0.pixel_spacing[0]), float(spacing_z))
        origin = tuple(float(v) for v in g0.image_position_patient)
        self.vtk_image_data.SetSpacing(spacing)
        self.vtk_image_data.SetOrigin(origin)

        flat = (
            self._volume.reshape(-1, self.components)
            if self.components > 1
            else self._volume.ravel(order="C")
        )
        vtk_arr = numpy_support.numpy_to_vtk(
            num_array=flat,
            deep=False,
            array_type=_vtk_array_type_for(self.dtype),
        )
        self.vtk_image_data.GetPointData().SetScalars(vtk_arr)
        self.vtk_image_data._numpy_backing_store = self._volume

        # Mimic convert_itk2vtk direction field-data for sync/geometry helpers.
        self._attach_direction_field_data(g0.image_orientation_patient, spacing)

        # Prime only the first slice for fast first-frame without expensive startup work.
        self._load_slice_blocking(0, emit_signal=False)

        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="PyDicomLazyVolumeWorker")
        self._worker.start()

    @classmethod
    def from_series(
        cls,
        study_path: str,
        metadata: Dict[str, Any],
    ) -> "PyDicomLazyVolume":
        backend = PyDicom2DBackend()
        backend.open_series(study_path, metadata=metadata)
        return cls(backend)

    def register(self) -> str:
        return register_loader(self)

    def grow(self) -> int:
        """Expand volume to match backend's current file count (progressive download).

        Returns the new slice_count (unchanged if no growth needed).

        After ``refresh_file_list()`` the backend re-sorts ``_slices`` by IPP
        (geometry order).  Newly downloaded files may sort into the *middle* of
        the list, shifting existing indices.  We therefore build a
        ``old_index -> new_index`` mapping from file paths so that already-decoded
        pixel data lands at its correct position in the expanded volume.
        """
        if self._closing.is_set():
            return self.slice_count

        # Snapshot old path order BEFORE refresh re-sorts the list.
        old_paths: list = []
        try:
            old_paths = [s.path for s in self.backend._slices]
        except Exception:
            pass

        # Ask backend for its current file count (includes newly downloaded files)
        try:
            if hasattr(self.backend, "refresh_file_list"):
                self.backend.refresh_file_list()
        except Exception:
            pass
        new_count = self.backend.get_slice_count()
        if new_count <= self.slice_count:
            return self.slice_count

        old_count = self.slice_count
        logger.info("pydicom-lazy grow: %d -> %d slices", old_count, new_count)

        # Build old→new index mapping from file-path identity.  If a slice that
        # was at old position 5 is now at new position 8, its decoded pixels
        # must move from memmap row 5 to row 8.
        old_to_new: Optional[Dict[int, int]] = None
        try:
            new_paths = [s.path for s in self.backend._slices]
            new_path_idx = {p: i for i, p in enumerate(new_paths)}
            mapping = {}
            for old_idx, p in enumerate(old_paths):
                new_idx = new_path_idx.get(p)
                if new_idx is not None:
                    mapping[old_idx] = new_idx
            # Only use the mapping if at least one old slice moved to a
            # different position (otherwise a plain copy is fine).
            if any(o != n for o, n in mapping.items()):
                old_to_new = mapping
                logger.info(
                    "pydicom-lazy grow: IPP re-order detected, remapping %d decoded slices",
                    sum(1 for o, n in mapping.items() if o != n),
                )
        except Exception:
            pass

        with self._load_lock:
            # 1. Create new memmap with expanded shape
            new_shape = (
                (new_count, self.rows, self.cols)
                if self.components == 1
                else (new_count, self.rows, self.cols, self.components)
            )
            old_volume = self._volume
            old_loaded = self._loaded

            new_tmp = tempfile.NamedTemporaryFile(
                prefix="aipacs_lazy_grow_", suffix=".bin", delete=False
            )
            new_tmp_path = new_tmp.name
            new_tmp.close()

            new_volume = np.memmap(new_tmp_path, mode="w+", dtype=self.dtype, shape=new_shape)
            new_loaded = np.zeros((new_count,), dtype=np.bool_)

            # 2. Copy already-decoded slices, respecting index remapping.
            if old_to_new is not None:
                for old_idx in range(old_count):
                    if not old_loaded[old_idx]:
                        continue
                    new_idx = old_to_new.get(old_idx)
                    if new_idx is not None and new_idx < new_count:
                        new_volume[new_idx] = old_volume[old_idx]
                        new_loaded[new_idx] = True
            else:
                new_volume[:old_count] = old_volume[:old_count]
                new_loaded[:old_count] = old_loaded[:old_count]

            # 3. Swap references
            self._volume = new_volume
            self._loaded = new_loaded
            self.slice_count = new_count

            # 4. Update VTK image data dimensions and re-link scalar array
            self.vtk_image_data.SetDimensions(self.cols, self.rows, self.slice_count)
            flat = (
                self._volume.reshape(-1, self.components)
                if self.components > 1
                else self._volume.ravel(order="C")
            )
            vtk_arr = numpy_support.numpy_to_vtk(
                num_array=flat,
                deep=False,
                array_type=_vtk_array_type_for(self.dtype),
            )
            self.vtk_image_data.GetPointData().SetScalars(vtk_arr)
            self.vtk_image_data._numpy_backing_store = self._volume
            self.vtk_image_data.Modified()

        # 5. Resize request queue if needed
        try:
            new_max = max(512, new_count * 4)
            if new_max > self._request_queue.maxsize:
                self._request_queue = queue.PriorityQueue(maxsize=new_max)
        except Exception:
            pass

        # 6. Cleanup old memmap
        try:
            old_tmp_path = self._tmp_file_path
            self._tmp_file_path = new_tmp_path
            if old_volume is not None:
                old_volume.flush()
                mmap_obj = getattr(old_volume, "_mmap", None)
                if mmap_obj is not None:
                    mmap_obj.close()
            if old_tmp_path and os.path.exists(old_tmp_path):
                os.remove(old_tmp_path)
        except Exception:
            pass

        logger.info("pydicom-lazy grow: complete, now %d slices", self.slice_count)
        return self.slice_count

    def close(self) -> None:
        if self._closing.is_set():
            return
        self._closing.set()

        try:
            self._request_queue.put_nowait((99, next(self._request_seq), None))
        except Exception:
            pass
        try:
            if hasattr(self, "_worker") and self._worker is not None and self._worker.is_alive():
                self._worker.join(timeout=1.0)
        except Exception:
            pass

        with self._pending_lock:
            self._pending.clear()

        try:
            while True:
                self._request_queue.get_nowait()
        except Exception:
            pass

        try:
            self.backend.close_series()
        except Exception:
            pass
        try:
            if hasattr(self, "_volume") and self._volume is not None:
                self._volume.flush()
                try:
                    mmap_obj = getattr(self._volume, "_mmap", None)
                    if mmap_obj is not None:
                        mmap_obj.close()
                except Exception:
                    pass
                self._volume = None
        except Exception:
            pass
        try:
            if self._tmp_file_path and os.path.exists(self._tmp_file_path):
                os.remove(self._tmp_file_path)
        except Exception:
            pass

    def get_metrics_snapshot(self) -> Dict[str, float]:
        requests = max(1, int(self._requests))
        return {
            "requests": float(self._requests),
            "cache_hits": float(self._cache_hits),
            "cache_hit_rate": float(self._cache_hits) / float(requests),
            "decode_count": float(self._decode_count),
            "decode_ms_total": float(self._decode_ms_total),
            "decode_read_ms_total": float(self._decode_read_ms_total),
            "decode_pixel_ms_total": float(self._decode_pixel_ms_total),
            "decode_post_ms_total": float(self._decode_post_ms_total),
        }

    @staticmethod
    def _now_ms() -> float:
        return float(time.perf_counter() * 1000.0)

    def _is_interaction_active(self) -> bool:
        return self._now_ms() < float(self._interactive_until_ms)

    def _effective_prefetch_radius(self) -> int:
        if self._is_interaction_active():
            vel = float(self._last_hint_velocity_sps or 0.0)
            if vel >= float(self._very_high_velocity_sps):
                return int(min(self._prefetch_radius_fast, self._prefetch_radius_very_high_velocity))
            if vel >= float(self._high_velocity_sps):
                return int(min(self._prefetch_radius_fast, self._prefetch_radius_high_velocity))
            return int(self._prefetch_radius_fast)
        return int(self._prefetch_radius_idle)

    def _effective_relevance_radius(self) -> int:
        if self._is_interaction_active():
            vel = float(self._last_hint_velocity_sps or 0.0)
            if vel >= float(self._very_high_velocity_sps):
                return int(min(self._cache_radius_fast, self._relevance_radius_very_high_velocity))
            if vel >= float(self._high_velocity_sps):
                return int(min(self._cache_radius_fast, self._relevance_radius_high_velocity))
            return int(self._cache_radius_fast)
        return int(self._cache_radius_idle)

    def set_scroll_hint(
        self,
        target_idx: int,
        direction: int = 0,
        velocity_sps: float = 0.0,
        source: str = "",
    ) -> None:
        i = max(0, min(int(target_idx), self.slice_count - 1))
        dir_i = int(direction)
        if dir_i == 0:
            if int(i) > int(self._requested_slice_idx):
                dir_i = 1
            elif int(i) < int(self._requested_slice_idx):
                dir_i = -1
        self._scroll_direction = int(dir_i)
        try:
            vel = max(0.0, float(velocity_sps))
        except Exception:
            vel = 0.0
        self._last_hint_velocity_sps = float(vel)
        now_ms = self._now_ms()
        if int(dir_i) != 0 or vel > 0.0:
            self._interactive_until_ms = max(
                float(self._interactive_until_ms),
                float(now_ms + self._interaction_idle_ms),
            )
        self._last_hint_ts_ms = float(now_ms)
        self._last_hint_idx = int(i)

    def request_slice_loaded(self, idx: int, prefetch: bool = True) -> bool:
        i = max(0, min(int(idx), self.slice_count - 1))
        now_ms = self._now_ms()
        self._last_requested_slice_idx = int(self._requested_slice_idx)
        self._requested_slice_idx = int(i)
        if self._requested_slice_idx > self._last_requested_slice_idx:
            self._scroll_direction = 1
        elif self._requested_slice_idx < self._last_requested_slice_idx:
            self._scroll_direction = -1
        else:
            self._scroll_direction = 0
        dt_ms = max(1.0, float(now_ms) - float(self._last_hint_ts_ms or 0.0))
        delta = abs(int(i) - int(self._last_hint_idx))
        velocity_sps = float(delta) * 1000.0 / float(dt_ms)
        self.set_scroll_hint(
            target_idx=int(i),
            direction=int(self._scroll_direction),
            velocity_sps=float(velocity_sps),
            source="request",
        )
        self._requests += 1
        if bool(self._loaded[i]):
            self._cache_hits += 1
            if prefetch:
                self._prefetch_around(i)
            return True

        self._enqueue_slice(i, high_priority=True)
        if prefetch:
            self._prefetch_around(i)
        return False

    def ensure_slice_loaded(self, idx: int) -> bool:
        # Kept for compatibility; now intentionally non-blocking.
        return self.request_slice_loaded(idx, prefetch=True)

    def set_slice_index(self, idx: int) -> bool:
        i = max(0, min(int(idx), self.slice_count - 1))
        try:
            self.backend.set_slice_index(i)
        except Exception:
            pass
        cache_hit = self.request_slice_loaded(i, prefetch=True)
        logger.debug("pydicom-lazy route slice=%d cache_hit=%s", i, bool(cache_hit))
        return cache_hit

    def mark_vtk_modified(self) -> None:
        try:
            scalars = self.vtk_image_data.GetPointData().GetScalars()
            if scalars is not None:
                scalars.Modified()
            self.vtk_image_data.Modified()
        except Exception:
            pass

    def _enqueue_slice(self, idx: int, high_priority: bool = False) -> None:
        if self._closing.is_set():
            return
        i = max(0, min(int(idx), self.slice_count - 1))
        priority = 0 if bool(high_priority) else 1
        old_priority = None
        enqueue = False
        with self._pending_lock:
            old_priority = self._pending.get(i)
            if old_priority is None:
                self._pending[i] = priority
                enqueue = True
            elif priority < int(old_priority):
                # Promote requested slices above stale prefetch entries.
                self._pending[i] = priority
                enqueue = True
            else:
                return
        if not enqueue:
            return
        try:
            token = (priority, next(self._request_seq), i)
            self._request_queue.put_nowait(token)
        except queue.Full:
            with self._pending_lock:
                if old_priority is None:
                    self._pending.pop(i, None)
                else:
                    self._pending[i] = int(old_priority)
        except Exception:
            with self._pending_lock:
                if old_priority is None:
                    self._pending.pop(i, None)
                else:
                    self._pending[i] = int(old_priority)

    def _load_slice_blocking(self, idx: int, emit_signal: bool = True) -> bool:
        i = max(0, min(int(idx), self.slice_count - 1))
        if bool(self._loaded[i]):
            if emit_signal:
                self.slice_ready.emit(i, 0.0, True)
            return True
        if self._closing.is_set() or self._decoder_failed:
            return False

        t_decode = time.perf_counter()
        arr = self.backend.get_pixel_array(i)
        decode_ms = (time.perf_counter() - t_decode) * 1000.0
        decode_breakdown = {}
        try:
            if hasattr(self.backend, "pop_decode_metrics"):
                decode_breakdown = self.backend.pop_decode_metrics(i) or {}
        except Exception:
            decode_breakdown = {}
        read_ms = float(decode_breakdown.get("read_ms", 0.0) or 0.0)
        pixel_ms = float(decode_breakdown.get("pixel_decode_ms", 0.0) or 0.0)
        post_ms = float(decode_breakdown.get("post_ms", 0.0) or 0.0)
        arr = self._prepare_slice_for_volume(arr)
        with self._load_lock:
            if bool(self._loaded[i]):
                if emit_signal:
                    self.slice_ready.emit(i, 0.0, True)
                return True
            if self._closing.is_set():
                return False
            self._volume[i] = arr
            self._loaded[i] = True
            scalars = self.vtk_image_data.GetPointData().GetScalars()
            if scalars is not None:
                scalars.Modified()
            self.vtk_image_data.Modified()
        self._decode_count += 1
        self._decode_ms_total += float(decode_ms)
        self._decode_read_ms_total += read_ms
        self._decode_pixel_ms_total += pixel_ms
        self._decode_post_ms_total += post_ms
        _requested = int(i) == int(self._requested_slice_idx)
        _log = logger.info if (_requested or float(decode_ms) >= 20.0) else logger.debug
        _log(
            "pydicom-lazy stage=decode_ready slice=%d read_ms=%.2f decode_ms=%.2f post_ms=%.2f total_ms=%.2f "
            "qimage_ms=0.00 cache_hit=%s",
            int(i),
            float(read_ms),
            float(pixel_ms),
            float(post_ms),
            float(decode_ms),
            False,
            extra={
                "component": "viewer",
                "function": "PyDicomLazyVolume._load_slice_blocking",
                "stage": "decode_ready",
            },
        )
        if emit_signal:
            self.slice_ready.emit(i, float(decode_ms), False)
        return True

    def _prepare_slice_for_volume(self, arr: np.ndarray) -> np.ndarray:
        # Match historical ITK->VTK path: flip Y axis.
        arr2 = np.asarray(arr)
        if arr2.ndim >= 2:
            arr2 = arr2[::-1, ...]
        if self.components == 1 and arr2.ndim == 3:
            arr2 = arr2[..., 0]

        # v2.2.3.4.1: Apply PooyanPacs-exact OpenCV filter (same as C# FilterCenter).
        # This gives the lazy backend the same image quality as the ITK path.
        if getattr(self, '_pooyan_opencv_enabled', True):
            try:
                from PacsClient.pacs.patient_tab.utils.opencv_filter_pipeline import (
                    PooyanFilterParams,
                    apply_pooyan_opencv_to_slice_int16,
                )
                if not hasattr(self, '_pooyan_opencv_params'):
                    self._pooyan_opencv_params = PooyanFilterParams()
                arr2 = apply_pooyan_opencv_to_slice_int16(arr2, self._pooyan_opencv_params)
            except ImportError:
                self._pooyan_opencv_enabled = False
            except Exception:
                pass

        if arr2.dtype != self.dtype:
            if np.issubdtype(self.dtype, np.integer):
                dtype_info = np.iinfo(self.dtype)
                arr2 = np.clip(arr2, dtype_info.min, dtype_info.max).astype(self.dtype)
            else:
                arr2 = arr2.astype(self.dtype)
        return np.ascontiguousarray(arr2)

    def _prefetch_around(self, center: int, radius: Optional[int] = None) -> None:
        if self._closing.is_set():
            return
        if radius is None:
            radius = int(self._effective_prefetch_radius())
        radius = int(radius)
        if radius <= 0:
            return
        direction = int(self._scroll_direction)
        forward_radius = int(radius)
        backward_radius = int(radius)
        if self._is_interaction_active() and direction != 0:
            opposite = max(1, int(round(float(radius) * float(self._directional_ratio))))
            if direction > 0:
                backward_radius = int(opposite)
            else:
                forward_radius = int(opposite)

        if direction < 0:
            primary_dir = -1
        else:
            primary_dir = 1
        secondary_dir = -primary_dir

        primary_radius = backward_radius if primary_dir < 0 else forward_radius
        secondary_radius = backward_radius if secondary_dir < 0 else forward_radius

        for off in range(1, int(primary_radius) + 1):
            idx = int(center) + int(primary_dir) * int(off)
            if idx < 0 or idx >= self.slice_count or bool(self._loaded[idx]):
                continue
            self._enqueue_slice(idx, high_priority=False)
        for off in range(1, int(secondary_radius) + 1):
            idx = int(center) + int(secondary_dir) * int(off)
            if idx < 0 or idx >= self.slice_count or bool(self._loaded[idx]):
                continue
            self._enqueue_slice(idx, high_priority=False)

    def _is_relevant_request(self, idx: int) -> bool:
        target = int(self._requested_slice_idx)
        if idx == target:
            return True
        radius = int(self._effective_relevance_radius())
        delta = int(idx) - int(target)
        direction = int(self._scroll_direction)
        if self._is_interaction_active() and direction != 0:
            opposite = max(1, int(round(float(radius) * float(self._directional_ratio))))
            if direction > 0:
                return int(-opposite) <= int(delta) <= int(radius)
            return int(-radius) <= int(delta) <= int(opposite)
        return abs(int(delta)) <= int(radius)

    def _worker_loop(self) -> None:
        while not self._closing.is_set():
            try:
                item = self._request_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            except Exception:
                continue
            if item is None:
                break
            priority = 1
            idx = None
            try:
                priority = int(item[0])
                idx = item[2]
            except Exception:
                continue
            if idx is None:
                break
            with self._pending_lock:
                current_priority = self._pending.get(int(idx))
            if current_priority is None:
                continue
            if int(priority) > int(current_priority):
                # Stale queue item; a newer/higher-priority request exists.
                continue
            try:
                if not self._is_relevant_request(int(idx)):
                    continue
                if not self._decoder_failed:
                    self._load_slice_blocking(int(idx), emit_signal=True)
            except Exception as e:
                self._decoder_failed = True
                if not self._decode_failed_emitted:
                    self._decode_failed_emitted = True
                    self.decode_failed.emit(
                        f"Slice {idx} decode failed: {e}. "
                        "Install pydicom + pylibjpeg-libjpeg/openjpeg/rle (or python-gdcm)."
                    )
            finally:
                with self._pending_lock:
                    self._pending.pop(int(idx), None)

    def _attach_direction_field_data(
        self,
        iop: Tuple[float, float, float, float, float, float],
        spacing: Tuple[float, float, float],
    ) -> None:
        mat = _to_iop_matrix(iop)
        direction_array = vtk.vtkDoubleArray()
        direction_array.SetName("DirectionMatrix")
        direction_array.SetNumberOfTuples(16)
        for r in range(4):
            for c in range(4):
                direction_array.SetValue(r * 4 + c, float(mat[r, c]))
        self.vtk_image_data.GetFieldData().AddArray(direction_array)

        spacing_arr = vtk.vtkDoubleArray()
        spacing_arr.SetName("ITKSpacing")
        spacing_arr.SetNumberOfTuples(3)
        for i, v in enumerate(spacing):
            spacing_arr.SetValue(i, float(v))
        self.vtk_image_data.GetFieldData().AddArray(spacing_arr)

        dims_arr = vtk.vtkDoubleArray()
        dims_arr.SetName("ITKDimensions")
        dims_arr.SetNumberOfTuples(3)
        dims_arr.SetValue(0, float(self.cols))
        dims_arr.SetValue(1, float(self.rows))
        dims_arr.SetValue(2, float(self.slice_count))
        self.vtk_image_data.GetFieldData().AddArray(dims_arr)
