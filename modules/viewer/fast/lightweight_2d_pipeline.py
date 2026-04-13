"""
Lightweight 2D DICOM Slice Pipeline
====================================
Provides a complete per-slice pipeline from DICOM file → QImage *without*
VTK or SimpleITK.  Uses PyDicom for decoding and OpenCV for filtering.

This replaces the heavy VTK rendering path for 2D viewing:
    Old: SimpleITK read → apply_filters (full vol) → convert_itk2vtk → VTK Render
    New: PyDicom decode (per-slice) → OpenCV filter → W/L → QImage → QPainter

Performance target: <5ms per slice on warm cache (vs 8-50ms VTK Render).

Dependencies: pydicom, numpy, cv2 (opencv-python-headless), PySide6
Does NOT depend on: VTK, SimpleITK

Version: v1.0.0 (2026-03-02)
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
from PacsClient.pacs.patient_tab.utils.opencv_filter_pipeline import PooyanFilterParams, pooyan_filter_center

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SliceGeometry:
    """Per-slice DICOM spatial geometry."""
    image_position_patient: Tuple[float, float, float]
    image_orientation_patient: Tuple[float, float, float, float, float, float]
    pixel_spacing: Tuple[float, float]
    slice_thickness: Optional[float]
    spacing_between_slices: Optional[float]
    rows: int
    cols: int


@dataclass
class SliceMeta:
    """Per-slice metadata extracted from DICOM headers or DB."""
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
    is_rgb: bool = False


@dataclass(frozen=True)
class RenderedFrame:
    """A fully-rendered 2D frame ready for display."""
    qimage: QImage
    width: int
    height: int
    slice_index: int
    window_width: float
    window_center: float
    photometric: str
    decode_ms: float
    filter_ms: float
    wl_ms: float
    total_ms: float


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PipelineConfig:
    """Configuration for the lightweight 2D pipeline."""
    # Cache sizes
    pixel_cache_size: int = 96       # raw decoded slices
    frame_cache_size: int = 96       # rendered QImages
    # Prefetch
    prefetch_radius: int = 20        # slices ahead/behind to warm
    prefetch_workers: int = 4        # background decode/render threads
    # OpenCV filter (PooyanPacs unsharp mask)
    opencv_filter_enabled: bool = True
    opencv_sigma_x: float = 1.0
    opencv_alpha: float = 1.4
    opencv_beta: float = -0.5
    opencv_invert: bool = False
    opencv_small_threshold: int = 280
    opencv_preserve_dimensions: bool = True
    # Performance
    decode_timeout_ms: float = 500.0  # max decode time before marking slow


# ═══════════════════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════════════════

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


def _normalize_vec(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def _normal_from_iop(iop: Sequence[float]) -> np.ndarray:
    row = np.asarray(iop[0:3], dtype=np.float64)
    col = np.asarray(iop[3:6], dtype=np.float64)
    return _normalize_vec(np.cross(row, col))


def _window_level_to_uint8(arr: np.ndarray, window: float, level: float) -> np.ndarray:
    """Apply DICOM window/level and convert to uint8."""
    return window_to_uint8(arr, window, level)


def _apply_opencv_filter_uint8(
    gray: np.ndarray,
    sigma_x: float = 1.0,
    alpha: float = 1.4,
    beta: float = -0.5,
    invert: bool = False,
    small_threshold: int = 280,
    preserve_dimensions: bool = True,
) -> np.ndarray:
    params = PooyanFilterParams(
        sigma_x=float(sigma_x),
        alpha=float(alpha),
        beta=float(beta),
        enabled=True,
        invert=bool(invert),
        small_threshold=int(small_threshold),
        preserve_dimensions=bool(preserve_dimensions),
    )
    return pooyan_filter_center(gray, params)


def _numpy_to_qimage_gray(arr: np.ndarray, width: int, height: int) -> QImage:
    """Convert a uint8 grayscale numpy array to QImage.

    We keep *arr* alive by stashing it on the QImage so the buffer is not
    collected before the QImage is discarded.  This avoids a full-frame
    memcpy that .copy() would do (~0.3ms for 512×512, adds up at high fps).
    """
    arr = np.ascontiguousarray(arr)
    qimg = QImage(arr.data, width, height, width, QImage.Format.Format_Grayscale8)
    qimg._np_buffer = arr  # prevent GC of backing memory
    return qimg


def _numpy_to_qimage_rgb(arr: np.ndarray, width: int, height: int) -> QImage:
    """Convert a uint8 RGB numpy array to QImage."""
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=2)
    if arr.shape[2] > 3:
        arr = arr[:, :, :3]
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    arr = np.ascontiguousarray(arr)
    bpl = int(arr.strides[0])
    qimg = QImage(arr.data, width, height, bpl, QImage.Format.Format_RGB888)
    qimg._np_buffer = arr  # prevent GC of backing memory
    return qimg


# ═══════════════════════════════════════════════════════════════════════════
# Lightweight 2D Pipeline
# ═══════════════════════════════════════════════════════════════════════════

class Lightweight2DPipeline(QObject):
    """
    Complete VTK-free 2D DICOM viewing pipeline.

    Provides:
    - Per-slice DICOM decode via PyDicom
    - OpenCV-based PooyanPacs filtering
    - Window/Level application
    - QImage output for Qt rendering
    - LRU caching for decoded pixels and rendered frames
    - Background prefetch with ThreadPoolExecutor

    Signals:
        frame_ready(int, float, bool): slice_index, decode_ms, cache_hit
        decode_failed(str): reason string
    """

    frame_ready = Signal(int, float, bool)   # slice_index, decode_ms, cache_hit
    decode_failed = Signal(str)              # reason

    def __init__(self, config: Optional[PipelineConfig] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._config = config or PipelineConfig()

        # Slice metadata
        self._slices: List[SliceMeta] = []
        self._current_index: int = 0

        # Window/Level state
        self._window: Optional[float] = None
        self._level: Optional[float] = None

        # Fast-scroll state (v2.3.3-perf)
        # When True, get_rendered_frame skips the OpenCV filter and serves
        # a "draft" frame from a separate unfiltered cache.  The filter is
        # re-applied on scroll-stop via rerender_current_filtered().
        self._fast_interaction: bool = False

        # Caches (LRU via OrderedDict)
        self._pixel_cache: "OrderedDict[int, np.ndarray]" = OrderedDict()
        self._frame_cache: "OrderedDict[Tuple[int, float, float, bool], QImage]" = OrderedDict()

        # Prefetch
        self._prefetch_pending: set = set()
        self._frame_prefetch_pending: set = set()
        self._prefetch_lock = threading.Lock()
        self._decode_executor = ThreadPoolExecutor(
            max_workers=self._config.prefetch_workers,
            thread_name_prefix="LW2D-Decode",
        )
        self._frame_executor = ThreadPoolExecutor(
            max_workers=max(2, min(4, int(self._config.prefetch_workers))),
            thread_name_prefix="LW2D-Frame",
        )

        # Metrics
        self._metrics_lock = threading.Lock()
        self._metrics = {
            "decode_count": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_decode_ms": 0.0,
            "total_filter_ms": 0.0,
            "total_wl_ms": 0.0,
        }

        # FAST timeline: track first-render and filter-signature events
        self._first_render_logged: bool = False
        self._filter_first_slices: set = set()  # slice indices whose filter was first applied

        # Series state
        self._series_path: Optional[str] = None
        self._is_open: bool = False

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def slice_count(self) -> int:
        return len(self._slices)

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open_series(
        self,
        series_path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Open a DICOM series from metadata instances or by scanning directory."""
        self.close_series()
        self._series_path = str(series_path)

        if metadata and metadata.get("instances"):
            self._slices = self._from_metadata_instances(metadata["instances"])
        else:
            self._slices = self._scan_series_headers(series_path)

        self._slices = self._sort_slices(self._slices)
        self._attach_spacing_between_slices()
        self._current_index = 0
        self._is_open = True

        # Set initial window/level from first slice
        if self._slices:
            self._window, self._level = normalize_window_level(
                self._slices[0].window_width,
                self._slices[0].window_center,
                treat_legacy_placeholder_as_missing=True,
            )
            # NOTE: Do NOT prefetch around slice 0 here.  The caller will
            # immediately call set_slice_index(mid) which triggers
            # _prefetch_around(mid) — pre-fetching around 0 wastes CPU
            # decoding slices far from the initial view.

        logger.info(
            "lw2d-pipeline open_series slices=%d path=%s",
            len(self._slices), series_path,
        )

    def close_series(self) -> None:
        """Release all resources."""
        self._pixel_cache.clear()
        self._frame_cache.clear()
        with self._prefetch_lock:
            self._prefetch_pending.clear()
            self._frame_prefetch_pending.clear()
        self._slices.clear()
        self._current_index = 0
        self._window = None
        self._level = None
        self._series_path = None
        self._is_open = False
        self._first_render_logged = False
        self._filter_first_slices.clear()

    def get_file_paths(self) -> List[str]:
        return [s.path for s in self._slices]

    def refresh_file_list(self) -> int:
        """Re-scan the series directory for newly-downloaded DICOM files.

        Only reads headers for files not already in ``_slices``.  Existing
        SliceMeta entries (and their cached pixel data) are preserved.
        Returns the new slice count.

        This mirrors ``PyDicom2DBackend.refresh_file_list()`` and is called by
        ``QtViewerBridge.grow()`` during progressive download.
        """
        if not self._series_path:
            return len(self._slices)
        from pathlib import Path as _Path
        series_dir = _Path(self._series_path)
        if not series_dir.is_dir():
            return len(self._slices)

        existing_paths = {s.path for s in self._slices}
        new_files = [
            f for f in series_dir.iterdir()
            if f.is_file()
            and f.suffix.lower() in {".dcm", ".dicom", ""}
            and str(f) not in existing_paths
        ]
        if not new_files:
            return len(self._slices)

        new_slices: List[SliceMeta] = []
        for f in new_files:
            try:
                ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
                iop = _as_float_tuple(getattr(ds, "ImageOrientationPatient", None), 6, (1, 0, 0, 0, 1, 0))
                ipp = _as_float_tuple(getattr(ds, "ImagePositionPatient", None), 3, (0, 0, 0))
                ps = _as_float_tuple(getattr(ds, "PixelSpacing", None), 2, (1, 1))
                spp = int(getattr(ds, "SamplesPerPixel", 1) or 1)
                new_slices.append(SliceMeta(
                    path=str(f),
                    rows=int(getattr(ds, "Rows", 0) or 0),
                    cols=int(getattr(ds, "Columns", 0) or 0),
                    pixel_spacing=(float(ps[0]), float(ps[1])),
                    iop=(float(iop[0]), float(iop[1]), float(iop[2]),
                         float(iop[3]), float(iop[4]), float(iop[5])),
                    ipp=(float(ipp[0]), float(ipp[1]), float(ipp[2])),
                    slice_thickness=_safe_float(getattr(ds, "SliceThickness", None)),
                    spacing_between_slices=_safe_float(getattr(ds, "SpacingBetweenSlices", None)),
                    photometric=str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")),
                    bits_allocated=int(getattr(ds, "BitsAllocated", 16) or 16),
                    pixel_representation=int(getattr(ds, "PixelRepresentation", 1) or 1),
                    samples_per_pixel=spp,
                    window_width=_safe_float(getattr(ds, "WindowWidth", None)),
                    window_center=_safe_float(getattr(ds, "WindowCenter", None)),
                    slope=_safe_float(getattr(ds, "RescaleSlope", None), 1.0) or 1.0,
                    intercept=_safe_float(getattr(ds, "RescaleIntercept", None), 0.0) or 0.0,
                    instance_number=(
                        int(getattr(ds, "InstanceNumber"))
                        if getattr(ds, "InstanceNumber", None) is not None
                        else None
                    ),
                    is_rgb=(spp >= 3),
                ))
            except Exception:
                continue

        if new_slices:
            self._slices.extend(new_slices)
            self._slices = self._sort_slices(self._slices)
            # Invalidate rendered-frame cache so new slices get fresh frames;
            # pixel cache is keyed by path so existing decoded pixels are kept.
            self._frame_cache.clear()
            logger.debug(
                "lw2d-pipeline refresh_file_list: +%d files total=%d path=%s",
                len(new_slices), len(self._slices), self._series_path,
            )
        return len(self._slices)

    def set_window_level(self, window: Optional[float], level: Optional[float]) -> None:
        old_frame_cache_size = len(self._frame_cache)
        self._window = float(window) if window is not None else None
        self._level = float(level) if level is not None else None
        # Invalidate rendered frame cache (pixel cache stays valid)
        self._frame_cache.clear()
        if old_frame_cache_size > 0 and self._config.opencv_filter_enabled:
            logger.debug(
                "FAST:frame_cache_invalidated wl_change window=%.1f level=%.1f "
                "purged=%d filter_will_recompute=True",
                float(window or 0), float(level or 0), old_frame_cache_size,
            )
        if self._is_open and self._slices:
            self._prefetch_around(self._current_index)

    def get_window_level(self) -> Tuple[Optional[float], Optional[float]]:
        return self._window, self._level

    def get_default_window_level(self, slice_index: int) -> Tuple[float, float]:
        """Get the default W/L for a slice from DICOM header or auto-calc."""
        idx = self._clamp(slice_index)
        sm = self._slices[idx]

        ww, wc = normalize_window_level(
            sm.window_width,
            sm.window_center,
            treat_legacy_placeholder_as_missing=True,
        )

        if ww is None or wc is None:
            arr = self._get_pixel_array(idx)
            if arr is not None:
                ww, wc = auto_window_level_from_array(arr, 1.0, 99.0)
            else:
                ww = ww or 256.0
                wc = wc or 128.0

        return float(ww), float(wc)

    def get_geometry(self, slice_index: int) -> SliceGeometry:
        idx = self._clamp(slice_index)
        sm = self._slices[idx]
        return SliceGeometry(
            image_position_patient=sm.ipp,
            image_orientation_patient=sm.iop,
            pixel_spacing=sm.pixel_spacing,
            slice_thickness=sm.slice_thickness,
            spacing_between_slices=sm.spacing_between_slices,
            rows=sm.rows,
            cols=sm.cols,
        )

    def get_slice_meta(self, slice_index: int) -> SliceMeta:
        return self._slices[self._clamp(slice_index)]

    def get_pixel_array(self, slice_index: int) -> Optional[np.ndarray]:
        """Return raw decoded pixel array for *slice_index* (HU / stored values).

        Used by ROI statistics computation in ToolController.
        Returns None if decoding fails.
        """
        return self._get_pixel_array(self._clamp(slice_index))

    def image_xy_to_patient_xyz(
        self, x: float, y: float, slice_index: int
    ) -> Tuple[float, float, float]:
        sm = self._slices[self._clamp(slice_index)]
        row = np.asarray(sm.iop[0:3], dtype=np.float64)
        col = np.asarray(sm.iop[3:6], dtype=np.float64)
        ipp = np.asarray(sm.ipp, dtype=np.float64)
        sx, sy = float(sm.pixel_spacing[1]), float(sm.pixel_spacing[0])
        p = ipp + float(x) * sx * row + float(y) * sy * col
        return float(p[0]), float(p[1]), float(p[2])

    def patient_xyz_to_image_xy(
        self, xyz: Tuple[float, float, float], slice_index: int
    ) -> Tuple[float, float]:
        sm = self._slices[self._clamp(slice_index)]
        row = np.asarray(sm.iop[0:3], dtype=np.float64)
        col = np.asarray(sm.iop[3:6], dtype=np.float64)
        ipp = np.asarray(sm.ipp, dtype=np.float64)
        d = np.asarray(xyz, dtype=np.float64) - ipp
        sx = float(sm.pixel_spacing[1]) or 1.0
        sy = float(sm.pixel_spacing[0]) or 1.0
        return float(np.dot(d, row) / sx), float(np.dot(d, col) / sy)

    def get_rendered_frame(self, slice_index: int) -> RenderedFrame:
        """
        Get a fully-rendered frame for display (decode + filter + W/L + QImage).
        Uses cache when available.

        During fast interaction (_fast_interaction=True), the OpenCV filter is
        skipped to reduce per-frame cost by 3-5ms.  The unfiltered frame is
        served from the same cache (keyed with filter_enabled=False).
        Call rerender_current_filtered() on scroll-stop to refine.
        """
        idx = self._clamp(slice_index)
        sm = self._slices[idx]
        ww, wc = self._resolve_window_level(idx)
        # During fast scroll, skip filter for lower latency
        filter_enabled = self._config.opencv_filter_enabled and not self._fast_interaction
        cache_key = self._frame_cache_key(idx, ww, wc, filter_enabled)
        if cache_key in self._frame_cache:
            qimg = self._frame_cache.pop(cache_key)
            self._frame_cache[cache_key] = qimg
            self._record_cache_hit()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "FAST:frame_cache source=hit slice=%d ww=%.0f wc=%.0f filter=%s "
                    "cache_size=%d pixel_cache_size=%d",
                    idx, ww, wc, filter_enabled,
                    len(self._frame_cache), len(self._pixel_cache),
                )
            return RenderedFrame(
                qimage=qimg, width=qimg.width(), height=qimg.height(),
                slice_index=idx, window_width=ww, window_center=wc,
                photometric=sm.photometric, decode_ms=0.0, filter_ms=0.0,
                wl_ms=0.0, total_ms=0.0,
            )
        # Also check the filtered cache when we're in fast mode —
        # a fully filtered frame is always acceptable.
        if self._fast_interaction and self._config.opencv_filter_enabled:
            full_key = self._frame_cache_key(idx, ww, wc, True)
            if full_key in self._frame_cache:
                qimg = self._frame_cache.pop(full_key)
                self._frame_cache[full_key] = qimg
                self._record_cache_hit()
                return RenderedFrame(
                    qimage=qimg, width=qimg.width(), height=qimg.height(),
                    slice_index=idx, window_width=ww, window_center=wc,
                    photometric=sm.photometric, decode_ms=0.0, filter_ms=0.0,
                    wl_ms=0.0, total_ms=0.0,
                )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "FAST:frame_cache source=miss slice=%d ww=%.0f wc=%.0f filter=%s "
                "cache_size=%d pixel_cache_size=%d",
                idx, ww, wc, filter_enabled,
                len(self._frame_cache), len(self._pixel_cache),
            )
        frame = self._render_frame_uncached(idx, ww, wc, filter_enabled, record_metrics=True)
        self._prefetch_around(idx)
        return frame

    def set_fast_interaction(self, fast: bool) -> None:
        """Set fast-interaction mode. When True, filter is skipped during scroll."""
        self._fast_interaction = bool(fast)

    def rerender_current_filtered(self) -> Optional[RenderedFrame]:
        """Re-render current slice with filter enabled (called on scroll-stop).

        Returns the filtered frame if filter was skipped, None if already cached.
        """
        if not self._config.opencv_filter_enabled or not self._slices:
            return None
        idx = self._current_index
        ww, wc = self._resolve_window_level(idx)
        cache_key = self._frame_cache_key(idx, ww, wc, True)
        if cache_key in self._frame_cache:
            return None  # Already have filtered version
        return self._render_frame_uncached(idx, ww, wc, True, record_metrics=False)

    def _frame_cache_key(self, idx: int, ww: float, wc: float, filter_enabled: bool) -> Tuple[int, float, float, bool]:
        return int(idx), float(ww), float(wc), bool(filter_enabled)

    def _render_frame_uncached(
        self,
        idx: int,
        ww: float,
        wc: float,
        filter_enabled: bool,
        *,
        record_metrics: bool,
    ) -> RenderedFrame:
        t_start = time.perf_counter()
        sm = self._slices[idx]
        cache_key = self._frame_cache_key(idx, ww, wc, filter_enabled)

        t_decode = time.perf_counter()
        arr = self._get_pixel_array(idx)
        decode_ms = (time.perf_counter() - t_decode) * 1000.0

        if arr is None:
            qimg = QImage(sm.cols or 512, sm.rows or 512, QImage.Format.Format_Grayscale8)
            qimg.fill(0)
            return RenderedFrame(
                qimage=qimg, width=qimg.width(), height=qimg.height(),
                slice_index=idx, window_width=ww, window_center=wc,
                photometric=sm.photometric, decode_ms=decode_ms, filter_ms=0.0,
                wl_ms=0.0, total_ms=(time.perf_counter() - t_start) * 1000.0,
            )

        if sm.samples_per_pixel >= 3 or sm.is_rgb:
            qimg = _numpy_to_qimage_rgb(arr, sm.cols, sm.rows)
            self._put_frame_cache(cache_key, qimg)
            return RenderedFrame(
                qimage=qimg, width=qimg.width(), height=qimg.height(),
                slice_index=idx, window_width=ww, window_center=wc,
                photometric=sm.photometric, decode_ms=decode_ms, filter_ms=0.0,
                wl_ms=0.0, total_ms=(time.perf_counter() - t_start) * 1000.0,
            )

        t_wl = time.perf_counter()
        # Pass raw array directly — window_to_uint8 now has a fast LUT path
        # for int16/uint16 that avoids the float32 cast entirely.
        disp = _window_level_to_uint8(arr, ww, wc)
        wl_ms = (time.perf_counter() - t_wl) * 1000.0

        t_filter = time.perf_counter()
        filter_is_first = False
        if filter_enabled:
            filter_is_first = idx not in self._filter_first_slices
            disp = _apply_opencv_filter_uint8(
                disp,
                sigma_x=self._config.opencv_sigma_x,
                alpha=self._config.opencv_alpha,
                beta=self._config.opencv_beta,
                invert=self._config.opencv_invert,
                small_threshold=self._config.opencv_small_threshold,
                preserve_dimensions=self._config.opencv_preserve_dimensions,
            )
            if filter_is_first:
                self._filter_first_slices.add(idx)
        filter_ms = (time.perf_counter() - t_filter) * 1000.0

        if filter_enabled and record_metrics and logger.isEnabledFor(logging.DEBUG):
            _filter_sig = (
                f"sigma={self._config.opencv_sigma_x:.2f} "
                f"alpha={self._config.opencv_alpha:.2f} "
                f"beta={self._config.opencv_beta:.2f} "
                f"invert={self._config.opencv_invert} "
                f"small_thresh={self._config.opencv_small_threshold}"
            )
            logger.debug(
                "FAST:filter_apply slice=%d first=%s filter_ms=%.2f "
                "wl_ms=%.2f decode_ms=%.2f sig=[%s]",
                idx, filter_is_first, filter_ms, wl_ms, decode_ms, _filter_sig,
            )

        qimg = _numpy_to_qimage_gray(disp, sm.cols, sm.rows)
        self._put_frame_cache(cache_key, qimg)
        if record_metrics:
            self._record_decode(decode_ms, filter_ms, wl_ms)
            if not self._first_render_logged:
                self._first_render_logged = True
                logger.info(
                    "FAST:first_renderable_frame slice=%d decode_ms=%.2f "
                    "filter_ms=%.2f wl_ms=%.2f total_ms=%.2f filter_enabled=%s",
                    idx, decode_ms, filter_ms, wl_ms,
                    (time.perf_counter() - t_start) * 1000.0, filter_enabled,
                )
        return RenderedFrame(
            qimage=qimg, width=qimg.width(), height=qimg.height(),
            slice_index=idx, window_width=ww, window_center=wc,
            photometric=sm.photometric, decode_ms=decode_ms, filter_ms=filter_ms,
            wl_ms=wl_ms, total_ms=(time.perf_counter() - t_start) * 1000.0,
        )

    def set_slice_index(self, index: int) -> bool:
        """Set current slice and trigger prefetch. Returns True if cached."""
        if not self._slices:
            return False
        prev = self._current_index
        self._current_index = self._clamp(index)
        direction = 1 if self._current_index > prev else -1 if self._current_index < prev else 0
        cached = self._current_index in self._pixel_cache
        self._prefetch_around(self._current_index, direction=direction)
        return cached

    def get_pixel_value_at(self, slice_index: int, x: int, y: int) -> Optional[float]:
        """Get raw pixel value at (x, y) in image coordinates."""
        arr = self._get_pixel_array(self._clamp(slice_index))
        if arr is None:
            return None
        try:
            if 0 <= y < arr.shape[0] and 0 <= x < arr.shape[1]:
                return float(arr[y, x])
        except Exception:
            pass
        return None

    def get_scalar_range(self, slice_index: Optional[int] = None) -> Tuple[float, float]:
        """Get min/max pixel values for a slice or entire series."""
        if slice_index is not None:
            arr = self._get_pixel_array(self._clamp(slice_index))
            if arr is not None:
                return float(arr.min()), float(arr.max())
        # Series-level: sample first, middle, last slices
        indices = set()
        n = len(self._slices)
        if n > 0:
            indices.update([0, n // 2, n - 1])
        lo, hi = 0.0, 1.0
        for idx in indices:
            arr = self._get_pixel_array(idx)
            if arr is not None:
                lo = min(lo, float(arr.min()))
                hi = max(hi, float(arr.max()))
        return lo, hi

    def get_metrics(self) -> Dict[str, Any]:
        with self._metrics_lock:
            return dict(self._metrics)

    def shutdown(self) -> None:
        """Clean shutdown of background threads."""
        self.close_series()
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ── Private: decode ───────────────────────────────────────────────

    def _get_pixel_array(self, idx: int) -> Optional[np.ndarray]:
        """Get decoded pixel array (from cache or by decoding)."""
        if idx in self._pixel_cache:
            arr = self._pixel_cache.pop(idx)
            self._pixel_cache[idx] = arr
            logger.debug(
                "FAST:pixel_cache source=hit idx=%d cache_size=%d",
                idx, len(self._pixel_cache),
            )
            return arr
        logger.debug(
            "FAST:pixel_cache source=miss idx=%d cache_size=%d",
            idx, len(self._pixel_cache),
        )
        try:
            arr = self._decode_slice(idx)
            self._put_pixel_cache(idx, arr)
            return arr
        except Exception as e:
            logger.warning("lw2d-pipeline decode failed idx=%d: %s", idx, e)
            self.decode_failed.emit(str(e))
            return None

    def _decode_slice(self, idx: int) -> np.ndarray:
        """Decode a single DICOM slice using pydicom.

        Performance note (v2.3.3-perf): For typical CT/MR data (slope=1,
        int intercept, MONOCHROME2), keeps data as int16 instead of
        converting to float32.  The downstream W/L function uses a LUT
        for int16/uint16 which is ~3-5× faster than the float path.
        Float32 is only used when slope ≠ 1 (fractional) or when
        MONOCHROME1 inversion needs float arithmetic.
        """
        sm = self._slices[idx]

        ds = pydicom.dcmread(sm.path, stop_before_pixels=False, force=True)
        arr = np.asarray(ds.pixel_array)

        if arr.ndim == 3 and sm.samples_per_pixel < 3:
            arr = arr[0]  # multi-frame fallback

        if sm.samples_per_pixel >= 3:
            if arr.ndim == 4:
                arr = arr[0]
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
            return np.ascontiguousarray(arr)

        # Apply rescale slope/intercept
        slope = _safe_float(getattr(ds, "RescaleSlope", sm.slope), 1.0) or 1.0
        intercept = _safe_float(getattr(ds, "RescaleIntercept", sm.intercept), 0.0) or 0.0

        # Handle MONOCHROME1 (invert)
        photometric = str(getattr(ds, "PhotometricInterpretation", sm.photometric or "MONOCHROME2")).upper()

        # Fast path: slope == 1.0 and integer intercept — keep int16
        # This enables the LUT-based W/L path downstream (3-5× faster)
        _slope_is_unity = math.isclose(slope, 1.0)
        _intercept_is_int = math.isclose(intercept, round(intercept))
        _is_monochrome2 = (photometric != "MONOCHROME1")

        if _slope_is_unity and _intercept_is_int and _is_monochrome2:
            if not math.isclose(intercept, 0.0):
                # Integer offset only — keep as int16 for LUT path
                int_offset = int(round(intercept))
                if arr.dtype in (np.uint16, np.int16):
                    # Safe range check: int16 can hold -32768 to 32767
                    # Typical CT intercept is -1024, well within range
                    arr = arr.astype(np.int16, copy=False)
                    arr = (arr + np.int16(int_offset))
                else:
                    arr = arr.astype(np.float32, copy=False)
                    arr = arr + float(intercept)
            elif arr.dtype not in (np.int16, np.uint16, np.float32):
                arr = arr.astype(np.int16, copy=False)
            return np.ascontiguousarray(arr)

        # Slow path: fractional slope or MONOCHROME1 — use float32
        arr = arr.astype(np.float32, copy=False)
        if not _slope_is_unity or not math.isclose(intercept, 0.0):
            arr = arr * float(slope) + float(intercept)

        if not _is_monochrome2:
            arr = float(arr.max()) + float(arr.min()) - arr

        return np.ascontiguousarray(arr)

    # ── Private: cache management ─────────────────────────────────────

    def _put_pixel_cache(self, idx: int, arr: np.ndarray) -> None:
        self._pixel_cache[idx] = arr
        while len(self._pixel_cache) > self._config.pixel_cache_size:
            self._pixel_cache.popitem(last=False)

    def _put_frame_cache(self, key: tuple, image: QImage) -> None:
        self._frame_cache[key] = image
        while len(self._frame_cache) > self._config.frame_cache_size:
            self._frame_cache.popitem(last=False)

    # ── Private: prefetch ─────────────────────────────────────────────

    def _prefetch_around(self, center: int, direction: int = 0) -> None:
        if self._config.prefetch_radius <= 0:
            return
        for offset in range(1, self._config.prefetch_radius + 1):
            if direction < 0:
                candidates = (center - offset, center + offset)
            else:
                candidates = (center + offset, center - offset)
            for idx in candidates:
                if 0 <= idx < len(self._slices):
                    if idx not in self._pixel_cache:
                        self._submit_prefetch(idx)
                    else:
                        self._submit_frame_prefetch(idx)

    def _submit_prefetch(self, idx: int) -> None:
        with self._prefetch_lock:
            if idx in self._pixel_cache or idx in self._prefetch_pending:
                return
            self._prefetch_pending.add(idx)
        self._decode_executor.submit(self._decode_into_cache, idx)

    def _submit_frame_prefetch(self, idx: int) -> None:
        with self._prefetch_lock:
            if idx in self._frame_prefetch_pending:
                return
            self._frame_prefetch_pending.add(idx)
        self._frame_executor.submit(self._render_into_cache, idx)

    def _decode_into_cache(self, idx: int) -> None:
        if idx in self._pixel_cache:
            with self._prefetch_lock:
                self._prefetch_pending.discard(idx)
            return
        try:
            arr = self._decode_slice(idx)
            self._put_pixel_cache(idx, arr)
            self._submit_frame_prefetch(idx)
        except Exception:
            pass
        finally:
            with self._prefetch_lock:
                self._prefetch_pending.discard(idx)

    def _render_into_cache(self, idx: int) -> None:
        try:
            ww, wc = self._resolve_window_level(idx)
            filter_enabled = self._config.opencv_filter_enabled
            cache_key = self._frame_cache_key(idx, ww, wc, filter_enabled)
            if cache_key in self._frame_cache:
                return
            self._render_frame_uncached(idx, ww, wc, filter_enabled, record_metrics=False)
        except Exception:
            pass
        finally:
            with self._prefetch_lock:
                self._frame_prefetch_pending.discard(idx)

    # ── Private: window/level ─────────────────────────────────────────

    def _resolve_window_level(self, idx: int) -> Tuple[float, float]:
        """Get effective W/L for a slice."""
        ww, wc = normalize_window_level(self._window, self._level)
        sm = self._slices[idx]

        if ww is None or wc is None:
            ww, wc = normalize_window_level(
                sm.window_width,
                sm.window_center,
                treat_legacy_placeholder_as_missing=True,
            )

        if ww is None or wc is None:
            arr = self._get_pixel_array(idx)
            if arr is not None:
                ww, wc = auto_window_level_from_array(arr, 1.0, 99.0)
            else:
                ww, wc = 256.0, 128.0

        return float(ww), float(wc)

    # ── Private: metrics ──────────────────────────────────────────────

    def _record_decode(self, decode_ms: float, filter_ms: float, wl_ms: float) -> None:
        with self._metrics_lock:
            self._metrics["decode_count"] += 1
            self._metrics["cache_misses"] += 1
            self._metrics["total_decode_ms"] += decode_ms
            self._metrics["total_filter_ms"] += filter_ms
            self._metrics["total_wl_ms"] += wl_ms

    def _record_cache_hit(self) -> None:
        with self._metrics_lock:
            self._metrics["cache_hits"] += 1

    # ── Private: metadata parsing ─────────────────────────────────────

    def _from_metadata_instances(self, instances: Sequence[Dict[str, Any]]) -> List[SliceMeta]:
        out: List[SliceMeta] = []
        for inst in instances:
            path = str(inst.get("instance_path", "")).strip()
            if not path:
                continue
            rows = int(inst.get("rows", 0) or 0)
            cols = int(inst.get("columns", 0) or 0)
            iop = _as_float_tuple(inst.get("image_orientation_patient"), 6, (1, 0, 0, 0, 1, 0))
            ipp = _as_float_tuple(inst.get("image_position_patient"), 3, (0, 0, 0))
            ps = _as_float_tuple(inst.get("pixel_spacing"), 2, (1, 1))
            is_rgb = bool(inst.get("is_rgb", False))
            out.append(SliceMeta(
                path=path, rows=rows, cols=cols,
                pixel_spacing=(float(ps[0]), float(ps[1])),
                iop=(float(iop[0]), float(iop[1]), float(iop[2]), float(iop[3]), float(iop[4]), float(iop[5])),
                ipp=(float(ipp[0]), float(ipp[1]), float(ipp[2])),
                slice_thickness=_safe_float(inst.get("slice_thickness")),
                spacing_between_slices=_safe_float(inst.get("spacing_between_slices")),
                photometric="RGB" if is_rgb else "MONOCHROME2",
                bits_allocated=int(inst.get("bits_allocated", 16) or 16),
                pixel_representation=int(inst.get("pixel_representation", 1) or 1),
                samples_per_pixel=3 if is_rgb else 1,
                window_width=_safe_float(inst.get("window_width")),
                window_center=_safe_float(inst.get("window_center")),
                slope=_safe_float(inst.get("rescale_slope"), 1.0) or 1.0,
                intercept=_safe_float(inst.get("rescale_intercept"), 0.0) or 0.0,
                instance_number=int(inst["instance_number"]) if inst.get("instance_number") is not None else None,
                is_rgb=is_rgb,
            ))
        # Fill missing rows/cols from headers
        for i, sm in enumerate(out):
            if sm.rows > 0 and sm.cols > 0:
                continue
            try:
                ds = pydicom.dcmread(sm.path, stop_before_pixels=True, force=True)
                sm.rows = int(getattr(ds, "Rows", 0) or 0)
                sm.cols = int(getattr(ds, "Columns", 0) or 0)
            except Exception:
                continue
        return out

    def _scan_series_headers(self, series_path: str) -> List[SliceMeta]:
        from pathlib import Path
        p = Path(series_path)
        files = []
        if p.is_dir():
            files = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in {".dcm", ".dicom", ""}]
        out: List[SliceMeta] = []
        for f in sorted(files):
            try:
                ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
                iop = _as_float_tuple(getattr(ds, "ImageOrientationPatient", None), 6, (1, 0, 0, 0, 1, 0))
                ipp = _as_float_tuple(getattr(ds, "ImagePositionPatient", None), 3, (0, 0, 0))
                ps = _as_float_tuple(getattr(ds, "PixelSpacing", None), 2, (1, 1))
                spp = int(getattr(ds, "SamplesPerPixel", 1) or 1)
                out.append(SliceMeta(
                    path=str(f),
                    rows=int(getattr(ds, "Rows", 0) or 0),
                    cols=int(getattr(ds, "Columns", 0) or 0),
                    pixel_spacing=(float(ps[0]), float(ps[1])),
                    iop=(float(iop[0]), float(iop[1]), float(iop[2]), float(iop[3]), float(iop[4]), float(iop[5])),
                    ipp=(float(ipp[0]), float(ipp[1]), float(ipp[2])),
                    slice_thickness=_safe_float(getattr(ds, "SliceThickness", None)),
                    spacing_between_slices=_safe_float(getattr(ds, "SpacingBetweenSlices", None)),
                    photometric=str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")),
                    bits_allocated=int(getattr(ds, "BitsAllocated", 16) or 16),
                    pixel_representation=int(getattr(ds, "PixelRepresentation", 1) or 1),
                    samples_per_pixel=spp,
                    window_width=_safe_float(getattr(ds, "WindowWidth", None)),
                    window_center=_safe_float(getattr(ds, "WindowCenter", None)),
                    slope=_safe_float(getattr(ds, "RescaleSlope", None), 1.0) or 1.0,
                    intercept=_safe_float(getattr(ds, "RescaleIntercept", None), 0.0) or 0.0,
                    instance_number=int(getattr(ds, "InstanceNumber")) if getattr(ds, "InstanceNumber", None) is not None else None,
                    is_rgb=(spp >= 3),
                ))
            except Exception:
                continue
        return out

    def _sort_slices(self, slices: List[SliceMeta]) -> List[SliceMeta]:
        """Sort slices by DICOM InstanceNumber (acquisition order).

        IPP-based sorting is intentionally NOT used here — it broke reference
        lines in v1.09.5-v1.09.7, reverses CT head-to-feet order, and
        interleaves diffusion b-value groups.  The rest of the pipeline
        (file naming, DB queries, VTK backend) all use InstanceNumber order.
        """
        if len(slices) <= 1:
            return slices
        return sorted(slices, key=lambda s: (s.instance_number if s.instance_number is not None else 10**9, s.path))

    def _attach_spacing_between_slices(self) -> None:
        if len(self._slices) <= 1:
            return
        try:
            normal = _normal_from_iop(self._slices[0].iop)
            proj = [float(np.dot(np.asarray(s.ipp, dtype=np.float64), normal)) for s in self._slices]
            diffs = [abs(proj[i + 1] - proj[i]) for i in range(len(proj) - 1)]
            diffs = [d for d in diffs if d > 1e-6]
            spacing = float(np.median(diffs)) if diffs else None
        except Exception:
            spacing = None
        if spacing is not None:
            for s in self._slices:
                s.spacing_between_slices = spacing

    def _clamp(self, index: int) -> int:
        if not self._slices:
            raise IndexError("No series loaded")
        return max(0, min(int(index), len(self._slices) - 1))
