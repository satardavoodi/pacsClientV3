from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pydicom
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from PacsClient.pacs.patient_tab.utils.dicom_windowing import (
    auto_window_level_from_array,
    normalize_window_level,
    window_to_uint8,
)

from .contracts import FrameData, GeometryData
from ._decode_guard import (
    decode_serialisation_guard,
    log_decode_entry,
    log_decode_exit,
    extract_codec_info,
    thread_state_canary,
)

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        if isinstance(value, (list, tuple)):
            if not value:
                return default
            value = value[0]
        return float(value)
    except Exception:
        return default


def _as_float_tuple(value: Any, n: int, default: Sequence[float]) -> Tuple[float, ...]:
    try:
        if value is None:
            return tuple(float(x) for x in default[:n])
        seq = list(value)
        if len(seq) < n:
            return tuple(float(x) for x in default[:n])
        return tuple(float(seq[i]) for i in range(n))
    except Exception:
        return tuple(float(x) for x in default[:n])


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n <= 1e-12:
        return v
    return v / n


def _normal_from_iop(iop: Sequence[float]) -> np.ndarray:
    row = np.asarray(iop[0:3], dtype=np.float64)
    col = np.asarray(iop[3:6], dtype=np.float64)
    n = np.cross(row, col)
    return _normalize(n)


def _window_level_to_uint8(arr: np.ndarray, window: float, level: float) -> np.ndarray:
    return window_to_uint8(arr, window, level)


@dataclass
class _SliceMeta:
    path: str
    rows: int
    cols: int
    pixel_spacing: Tuple[float, float]
    iop: Tuple[float, float, float, float, float, float]
    ipp: Tuple[float, float, float]
    slice_thickness: Optional[float]
    spacing_between_slices: Optional[float]
    photometric: str
    bits_allocated: int
    pixel_representation: int
    samples_per_pixel: int
    window_width: Optional[float]
    window_center: Optional[float]
    slope: float
    intercept: float
    instance_number: Optional[int]


class PyDicom2DBackend(QObject):
    """Lazy 2D backend using pydicom decoding and per-slice cache."""

    wl_changed = Signal(float, float)
    slice_changed = Signal(int)

    def __init__(self, cache_size: int = 32, prefetch_radius: int = 2):
        super().__init__()
        self._cache_size = max(4, int(cache_size))
        self._prefetch_radius = max(0, int(prefetch_radius))
        self._pixel_cache: "OrderedDict[int, np.ndarray]" = OrderedDict()
        self._frame_cache: "OrderedDict[Tuple[int, Optional[float], Optional[float]], QImage]" = OrderedDict()
        self._prefetch_pending = set()
        self._prefetch_lock = threading.Lock()
        self._decode_metrics: Dict[int, Dict[str, float]] = {}
        self._decode_metrics_lock = threading.Lock()
        self._slices: List[_SliceMeta] = []
        self._slice_index: int = 0
        self._window: Optional[float] = None
        self._level: Optional[float] = None
        max_workers = max(1, int(os.getenv("AIPACS_PYDICOM_DECODE_WORKERS", "2") or "2"))
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="PyDicom2D")
        self._series_path: Optional[str] = None
        self._series_modality: str = ""

    @property
    def capabilities(self) -> Dict[str, Any]:
        return {
            "supports_filters": False,
            "supports_rgb": True,
            "supports_lazy_load": True,
            "supports_window_level": True,
        }

    def open_series(self, series_path: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.close_series()
        self._series_path = str(series_path)
        self._series_modality = ""
        series_number = "-"
        if isinstance(metadata, dict):
            series_meta = metadata.get("series", {}) or {}
            series_number = str(series_meta.get("series_number", "-"))
            self._series_modality = str(series_meta.get("modality", "") or "").upper()
        if metadata and metadata.get("instances"):
            self._slices = self._from_metadata_instances(metadata["instances"])
        else:
            self._slices = self._scan_series_headers(Path(series_path))
        if not self._series_modality and self._slices:
            try:
                ds0 = pydicom.dcmread(self._slices[0].path, stop_before_pixels=True, force=True)
                self._series_modality = str(getattr(ds0, "Modality", "") or "").upper()
            except Exception:
                self._series_modality = ""
        self._slices = self._sort_slices(self._slices)
        self._attach_spacing_between_slices()
        self._slice_index = 0
        first_path = self._slices[0].path if self._slices else ""
        last_path = self._slices[-1].path if self._slices else ""

        if self._slices:
            ww, wc = normalize_window_level(
                self._slices[0].window_width,
                self._slices[0].window_center,
                treat_legacy_placeholder_as_missing=True,
            )
            self._window = ww
            self._level = wc
        logger.info(
            "pydicom-backend stage=open_series series=%s slices=%d metadata_instances=%s initial_slice=%d "
            "first_path=%s last_path=%s path=%s",
            series_number,
            int(len(self._slices)),
            int(len(metadata.get("instances", []))) if isinstance(metadata, dict) else 0,
            int(self._slice_index),
            first_path,
            last_path,
            str(series_path),
            extra={
                "component": "viewer",
                "function": "PyDicom2DBackend.open_series",
                "stage": "open_series",
            },
        )
        if logger.isEnabledFor(logging.DEBUG) and self._slices:
            _n = len(self._slices)
            _mid = _n // 2
            _s0 = self._slices[0]
            _sm = self._slices[_mid]
            _sl = self._slices[-1]
            _iop = _s0.iop
            # Classify orientation from IOP normal (cross product of row × col)
            try:
                _row = (_iop[0], _iop[1], _iop[2])
                _col = (_iop[3], _iop[4], _iop[5])
                _nx = _row[1] * _col[2] - _row[2] * _col[1]
                _ny = _row[2] * _col[0] - _row[0] * _col[2]
                _nz = _row[0] * _col[1] - _row[1] * _col[0]
                _abs = (abs(_nx), abs(_ny), abs(_nz))
                _orient_class = ["Sagittal", "Coronal", "Axial"][_abs.index(max(_abs))]
            except Exception:
                _orient_class = "Unknown"
            logger.debug(
                "[GEOM] series=%s orient=%s slices=%d\n"
                "  IOP          = %s\n"
                "  IPP[0]       = %s\n"
                "  IPP[mid=%d]  = %s\n"
                "  IPP[-1]      = %s\n"
                "  pixel_spacing= %s  slice_thickness=%s  spacing_between=%s\n"
                "  rows=%s  cols=%s",
                series_number, _orient_class, _n,
                _iop,
                _s0.ipp,
                _mid, _sm.ipp,
                _sl.ipp,
                _s0.pixel_spacing, _s0.slice_thickness, _s0.spacing_between_slices,
                _s0.rows, _s0.cols,
            )

    def close_series(self) -> None:
        self._pixel_cache.clear()
        self._frame_cache.clear()
        with self._prefetch_lock:
            self._prefetch_pending.clear()
        with self._decode_metrics_lock:
            self._decode_metrics.clear()
        self._slices.clear()
        self._slice_index = 0
        self._window = None
        self._level = None
        self._series_path = None
        self._series_modality = ""

    def get_slice_count(self) -> int:
        return len(self._slices)

    def get_file_paths(self) -> List[str]:
        return [s.path for s in self._slices]

    def set_prefetch_radius(self, radius: int) -> None:
        self._prefetch_radius = max(0, int(radius))

    def set_window_level(self, window: Optional[float], level: Optional[float]) -> None:
        self._window = float(window) if window is not None else None
        self._level = float(level) if level is not None else None
        self._frame_cache.clear()
        self.wl_changed.emit(float(self._window or 0.0), float(self._level or 0.0))

    def get_window_level(self) -> Tuple[Optional[float], Optional[float]]:
        return self._window, self._level

    def get_default_window_level(self, slice_index: int) -> Tuple[float, float]:
        idx = self._clamp_index(slice_index)
        sm = self._slices[idx]
        ww, wc = normalize_window_level(
            sm.window_width,
            sm.window_center,
            treat_legacy_placeholder_as_missing=True,
        )
        if ww is None or wc is None:
            arr = self.get_pixel_array(idx)
            ww, wc = auto_window_level_from_array(arr, 5.0, 95.0)
        return float(ww), float(wc)

    def get_modality(self) -> str:
        return str(self._series_modality or "")

    def set_slice_index(self, index: int) -> None:
        if not self._slices:
            self._slice_index = 0
            return
        prev_idx = int(self._slice_index)
        self._slice_index = max(0, min(int(index), len(self._slices) - 1))
        self.slice_changed.emit(self._slice_index)
        direction = 0
        if self._slice_index > prev_idx:
            direction = 1
        elif self._slice_index < prev_idx:
            direction = -1
        self._prefetch_around(self._slice_index, direction=direction)

    def get_geometry(self, slice_index: int) -> GeometryData:
        sm = self._slices[self._clamp_index(slice_index)]
        return GeometryData(
            image_position_patient=sm.ipp,
            image_orientation_patient=sm.iop,
            pixel_spacing=sm.pixel_spacing,
            slice_thickness=sm.slice_thickness,
            spacing_between_slices=sm.spacing_between_slices,
            rows=sm.rows,
            cols=sm.cols,
        )

    def image_xy_to_patient_xyz(self, x: float, y: float, slice_index: int) -> Tuple[float, float, float]:
        sm = self._slices[self._clamp_index(slice_index)]
        row = np.asarray(sm.iop[0:3], dtype=np.float64)
        col = np.asarray(sm.iop[3:6], dtype=np.float64)
        ipp = np.asarray(sm.ipp, dtype=np.float64)
        sx = float(sm.pixel_spacing[1])
        sy = float(sm.pixel_spacing[0])
        p = ipp + float(x) * sx * row + float(y) * sy * col
        return float(p[0]), float(p[1]), float(p[2])

    def patient_xyz_to_image_xy(self, xyz: Tuple[float, float, float], slice_index: int) -> Tuple[float, float]:
        sm = self._slices[self._clamp_index(slice_index)]
        row = np.asarray(sm.iop[0:3], dtype=np.float64)
        col = np.asarray(sm.iop[3:6], dtype=np.float64)
        ipp = np.asarray(sm.ipp, dtype=np.float64)
        d = np.asarray(xyz, dtype=np.float64) - ipp
        sx = float(sm.pixel_spacing[1]) or 1.0
        sy = float(sm.pixel_spacing[0]) or 1.0
        x = float(np.dot(d, row) / sx)
        y = float(np.dot(d, col) / sy)
        return x, y

    def get_frame(self, slice_index: int) -> FrameData:
        idx = self._clamp_index(slice_index)
        sm = self._slices[idx]
        cache_key = (idx, self._window, self._level)
        if cache_key in self._frame_cache:
            img = self._frame_cache.pop(cache_key)
            self._frame_cache[cache_key] = img
            logger.debug("[IMAGE_CACHE_HIT] idx=%d", idx)
            return FrameData(
                image=img,
                width=img.width(),
                height=img.height(),
                photometric=sm.photometric,
                dtype=str(self._pixel_cache.get(idx, np.array([], dtype=np.int16)).dtype),
                window_applied=True,
            )

        arr = self.get_pixel_array(idx)
        if sm.samples_per_pixel >= 3:
            qimg = self._rgb_to_qimage(arr, sm.cols, sm.rows)
        else:
            ww, wc = normalize_window_level(self._window, self._level)
            if ww is None or wc is None:
                ww, wc = normalize_window_level(
                    sm.window_width,
                    sm.window_center,
                    treat_legacy_placeholder_as_missing=True,
                )
            if ww is None or wc is None:
                ww, wc = auto_window_level_from_array(arr, 5.0, 95.0)
            disp = _window_level_to_uint8(arr.astype(np.float32, copy=False), float(ww), float(wc))
            qimg = QImage(disp.data, sm.cols, sm.rows, sm.cols, QImage.Format_Grayscale8).copy()

        self._put_frame_cache(cache_key, qimg)
        self._prefetch_around(idx)
        return FrameData(
            image=qimg,
            width=qimg.width(),
            height=qimg.height(),
            photometric=sm.photometric,
            dtype=str(arr.dtype),
            window_applied=True,
        )

    def get_pixel_array(self, slice_index: int) -> np.ndarray:
        idx = self._clamp_index(slice_index)
        if idx in self._pixel_cache:
            arr = self._pixel_cache.pop(idx)
            self._pixel_cache[idx] = arr
            return arr
        arr = self._decode_slice(idx)
        self._put_pixel_cache(idx, arr)
        return arr

    def pop_decode_metrics(self, slice_index: int) -> Dict[str, float]:
        idx = int(slice_index)
        with self._decode_metrics_lock:
            return dict(self._decode_metrics.pop(idx, {}))

    def _decode_slice(self, idx: int) -> np.ndarray:
        sm = self._slices[idx]
        t_total = time.perf_counter()

        thread_state_canary("lazy_backend", "pre_decode")
        log_decode_entry("lazy_backend", idx, sm.path)

        t_read = time.perf_counter()
        with decode_serialisation_guard():
            ds = pydicom.dcmread(sm.path, stop_before_pixels=False, force=True)
            read_ms = (time.perf_counter() - t_read) * 1000.0

            t_pixel = time.perf_counter()
            arr = np.asarray(ds.pixel_array)
            pixel_decode_ms = (time.perf_counter() - t_pixel) * 1000.0

        codec_info = extract_codec_info(ds)
        log_decode_exit(
            "lazy_backend", idx,
            decode_ms=read_ms + pixel_decode_ms,
            **codec_info,
        )
        thread_state_canary("lazy_backend", "post_decode")

        t_post = time.perf_counter()
        if arr.ndim == 3 and sm.samples_per_pixel < 3:
            # Multi-frame single-slice fallback
            arr = arr[0]
        if sm.samples_per_pixel >= 3:
            if arr.ndim == 4:
                arr = arr[0]
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
            out = np.ascontiguousarray(arr)
            post_ms = (time.perf_counter() - t_post) * 1000.0
            with self._decode_metrics_lock:
                self._decode_metrics[int(idx)] = {
                    "read_ms": float(read_ms),
                    "pixel_decode_ms": float(pixel_decode_ms),
                    "post_ms": float(post_ms),
                    "total_ms": float((time.perf_counter() - t_total) * 1000.0),
                }
            return out

        arr = arr.astype(np.float32, copy=False)
        slope = _safe_float(getattr(ds, "RescaleSlope", sm.slope), 1.0) or 1.0
        intercept = _safe_float(getattr(ds, "RescaleIntercept", sm.intercept), 0.0) or 0.0
        if not math.isclose(slope, 1.0) or not math.isclose(intercept, 0.0):
            arr = arr * float(slope) + float(intercept)
        photometric = str(getattr(ds, "PhotometricInterpretation", sm.photometric or "MONOCHROME2")).upper()
        if photometric == "MONOCHROME1":
            arr = float(arr.max()) + float(arr.min()) - arr
        out = np.ascontiguousarray(arr)
        post_ms = (time.perf_counter() - t_post) * 1000.0
        with self._decode_metrics_lock:
            self._decode_metrics[int(idx)] = {
                "read_ms": float(read_ms),
                "pixel_decode_ms": float(pixel_decode_ms),
                "post_ms": float(post_ms),
                "total_ms": float((time.perf_counter() - t_total) * 1000.0),
            }
        return out

    def _rgb_to_qimage(self, arr: np.ndarray, cols: int, rows: int) -> QImage:
        if arr.ndim == 2:
            arr = np.repeat(arr[..., None], 3, axis=2)
        if arr.shape[2] > 3:
            arr = arr[:, :, :3]
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        arr = np.ascontiguousarray(arr)
        bytes_per_line = int(arr.strides[0])
        return QImage(arr.data, cols, rows, bytes_per_line, QImage.Format_RGB888).copy()

    def _prefetch_around(self, center: int, direction: int = 0) -> None:
        if self._prefetch_radius <= 0:
            return
        for offset in range(1, self._prefetch_radius + 1):
            if direction < 0:
                candidate_indices = (center - offset, center + offset)
            else:
                candidate_indices = (center + offset, center - offset)
            for idx in candidate_indices:
                if idx < 0 or idx >= len(self._slices):
                    continue
                if idx in self._pixel_cache:
                    continue
                self._submit_prefetch(idx)

    def _submit_prefetch(self, idx: int) -> None:
        with self._prefetch_lock:
            if idx in self._pixel_cache or idx in self._prefetch_pending:
                return
            self._prefetch_pending.add(int(idx))
        self._executor.submit(self._decode_into_cache, int(idx))

    def _decode_into_cache(self, idx: int) -> None:
        if idx in self._pixel_cache:
            with self._prefetch_lock:
                self._prefetch_pending.discard(int(idx))
            return
        try:
            arr = self._decode_slice(idx)
            self._put_pixel_cache(idx, arr)
        except Exception:
            return
        finally:
            with self._prefetch_lock:
                self._prefetch_pending.discard(int(idx))

    def _put_pixel_cache(self, idx: int, arr: np.ndarray) -> None:
        self._pixel_cache[idx] = arr
        while len(self._pixel_cache) > self._cache_size:
            self._pixel_cache.popitem(last=False)

    def _put_frame_cache(self, key: Tuple[int, Optional[float], Optional[float]], image: QImage) -> None:
        self._frame_cache[key] = image
        while len(self._frame_cache) > self._cache_size:
            self._frame_cache.popitem(last=False)

    def _clamp_index(self, index: int) -> int:
        if not self._slices:
            raise IndexError("No series is loaded")
        return max(0, min(int(index), len(self._slices) - 1))

    def _sort_slices(self, slices: List[_SliceMeta]) -> List[_SliceMeta]:
        """Sort slices by DICOM InstanceNumber (acquisition order).

        IPP-based sorting is intentionally NOT used here — it broke reference
        lines in v1.09.5-v1.09.7, reverses CT head-to-feet order, and
        interleaves diffusion b-value groups.  The rest of the pipeline
        (file naming, DB queries, VTK backend) all use InstanceNumber order.
        """
        if len(slices) <= 1:
            return slices
        return sorted(
            slices,
            key=lambda s: (
                s.instance_number if s.instance_number is not None else 10**9,
                s.path,
            ),
        )

    def _attach_spacing_between_slices(self) -> None:
        if len(self._slices) <= 1:
            return
        try:
            iop = self._slices[0].iop
            normal = _normal_from_iop(iop)
            proj = [float(np.dot(np.asarray(s.ipp, dtype=np.float64), normal)) for s in self._slices]
            diffs = [abs(proj[i + 1] - proj[i]) for i in range(len(proj) - 1)]
            diffs = [d for d in diffs if d > 1e-6]
            spacing = float(np.median(diffs)) if diffs else None
        except Exception:
            spacing = None
        if spacing is None:
            return
        updated = []
        for s in self._slices:
            updated.append(
                _SliceMeta(
                    path=s.path,
                    rows=s.rows,
                    cols=s.cols,
                    pixel_spacing=s.pixel_spacing,
                    iop=s.iop,
                    ipp=s.ipp,
                    slice_thickness=s.slice_thickness,
                    spacing_between_slices=spacing,
                    photometric=s.photometric,
                    bits_allocated=s.bits_allocated,
                    pixel_representation=s.pixel_representation,
                    samples_per_pixel=s.samples_per_pixel,
                    window_width=s.window_width,
                    window_center=s.window_center,
                    slope=s.slope,
                    intercept=s.intercept,
                    instance_number=s.instance_number,
                )
            )
        self._slices = updated

    def _from_metadata_instances(self, instances: Sequence[Dict[str, Any]]) -> List[_SliceMeta]:
        out: List[_SliceMeta] = []
        for inst in instances:
            path = str(inst.get("instance_path", "")).strip()
            if not path:
                continue
            rows = int(inst.get("rows", 0) or 0)
            cols = int(inst.get("columns", 0) or 0)
            iop = _as_float_tuple(inst.get("image_orientation_patient"), 6, (1, 0, 0, 0, 1, 0))
            ipp = _as_float_tuple(inst.get("image_position_patient"), 3, (0, 0, 0))
            ps = _as_float_tuple(inst.get("pixel_spacing"), 2, (1, 1))
            out.append(
                _SliceMeta(
                    path=path,
                    rows=rows,
                    cols=cols,
                    pixel_spacing=(float(ps[0]), float(ps[1])),
                    iop=(float(iop[0]), float(iop[1]), float(iop[2]), float(iop[3]), float(iop[4]), float(iop[5])),
                    ipp=(float(ipp[0]), float(ipp[1]), float(ipp[2])),
                    slice_thickness=_safe_float(inst.get("slice_thickness")),
                    spacing_between_slices=_safe_float(inst.get("spacing_between_slices")),
                    photometric="RGB" if bool(inst.get("is_rgb", False)) else "MONOCHROME2",
                    bits_allocated=int(inst.get("bits_allocated", 16) or 16),
                    pixel_representation=int(inst.get("pixel_representation", 1) or 1),
                    samples_per_pixel=3 if bool(inst.get("is_rgb", False)) else 1,
                    window_width=_safe_float(inst.get("window_width")),
                    window_center=_safe_float(inst.get("window_center")),
                    slope=_safe_float(inst.get("rescale_slope"), 1.0) or 1.0,
                    intercept=_safe_float(inst.get("rescale_intercept"), 0.0) or 0.0,
                    instance_number=int(inst["instance_number"]) if inst.get("instance_number") is not None else None,
                )
            )
        # Fill missing detail from headers for robust decode.
        for i, sm in enumerate(out):
            if sm.rows > 0 and sm.cols > 0 and sm.samples_per_pixel > 0:
                continue
            try:
                ds = pydicom.dcmread(sm.path, stop_before_pixels=True, force=True)
                out[i] = self._slice_meta_from_ds(sm.path, ds, fallback=sm)
            except Exception:
                continue
        return out

    def refresh_file_list(self) -> int:
        """Re-scan the series directory for newly downloaded DICOM files.

        Only adds files not already tracked — never removes existing entries.
        New headers are read with ``stop_before_pixels=True`` (fast, no pixel I/O).
        Returns the updated total slice count.

        Thread-safety: should be called from a single thread (e.g. the Qt main
        thread or a dedicated executor).  Concurrent callers should be
        serialised externally.
        """
        if not self._series_path:
            return len(self._slices)
        series_dir = Path(self._series_path)
        if not series_dir.is_dir():
            return len(self._slices)

        existing_paths = {s.path for s in self._slices}
        new_files = [
            p for p in series_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() in {".dcm", ".dicom", ""}
            and str(p) not in existing_paths
        ]
        if not new_files:
            return len(self._slices)

        new_metas: List[_SliceMeta] = []
        for p in sorted(new_files):
            try:
                ds = pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
                new_metas.append(self._slice_meta_from_ds(str(p), ds))
            except Exception:
                continue

        if new_metas:
            self._slices.extend(new_metas)
            self._slices = self._sort_slices(self._slices)
            self._attach_spacing_between_slices()
            logger.info(
                "pydicom-backend stage=refresh_file_list added=%d total=%d path=%s",
                len(new_metas), len(self._slices), self._series_path,
            )
        return len(self._slices)

    def _scan_series_headers(self, series_path: Path) -> List[_SliceMeta]:
        files = []
        if series_path.is_dir():
            files = [p for p in series_path.iterdir() if p.is_file() and p.suffix.lower() in {".dcm", ".dicom", ""}]
        out: List[_SliceMeta] = []
        for p in sorted(files):
            try:
                ds = pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
                out.append(self._slice_meta_from_ds(str(p), ds))
            except Exception:
                continue
        return out

    def _slice_meta_from_ds(self, path: str, ds: pydicom.Dataset, fallback: Optional[_SliceMeta] = None) -> _SliceMeta:
        rows = int(getattr(ds, "Rows", getattr(fallback, "rows", 0)) or 0)
        cols = int(getattr(ds, "Columns", getattr(fallback, "cols", 0)) or 0)
        iop = _as_float_tuple(
            getattr(ds, "ImageOrientationPatient", getattr(fallback, "iop", (1, 0, 0, 0, 1, 0))),
            6,
            (1, 0, 0, 0, 1, 0),
        )
        ipp = _as_float_tuple(
            getattr(ds, "ImagePositionPatient", getattr(fallback, "ipp", (0, 0, 0))),
            3,
            (0, 0, 0),
        )
        ps = _as_float_tuple(
            getattr(ds, "PixelSpacing", getattr(fallback, "pixel_spacing", (1, 1))),
            2,
            (1, 1),
        )
        samples = int(getattr(ds, "SamplesPerPixel", getattr(fallback, "samples_per_pixel", 1)) or 1)
        bits = int(getattr(ds, "BitsAllocated", getattr(fallback, "bits_allocated", 16)) or 16)
        repr_val = int(getattr(ds, "PixelRepresentation", getattr(fallback, "pixel_representation", 1)) or 1)
        return _SliceMeta(
            path=path,
            rows=rows,
            cols=cols,
            pixel_spacing=(float(ps[0]), float(ps[1])),
            iop=(float(iop[0]), float(iop[1]), float(iop[2]), float(iop[3]), float(iop[4]), float(iop[5])),
            ipp=(float(ipp[0]), float(ipp[1]), float(ipp[2])),
            slice_thickness=_safe_float(getattr(ds, "SliceThickness", getattr(fallback, "slice_thickness", None))),
            spacing_between_slices=_safe_float(
                getattr(ds, "SpacingBetweenSlices", getattr(fallback, "spacing_between_slices", None))
            ),
            photometric=str(getattr(ds, "PhotometricInterpretation", getattr(fallback, "photometric", "MONOCHROME2"))),
            bits_allocated=bits,
            pixel_representation=repr_val,
            samples_per_pixel=samples,
            window_width=_safe_float(getattr(ds, "WindowWidth", getattr(fallback, "window_width", None))),
            window_center=_safe_float(getattr(ds, "WindowCenter", getattr(fallback, "window_center", None))),
            slope=_safe_float(getattr(ds, "RescaleSlope", getattr(fallback, "slope", 1.0)), 1.0) or 1.0,
            intercept=_safe_float(getattr(ds, "RescaleIntercept", getattr(fallback, "intercept", 0.0)), 0.0) or 0.0,
            instance_number=int(getattr(ds, "InstanceNumber")) if getattr(ds, "InstanceNumber", None) is not None else None,
        )
