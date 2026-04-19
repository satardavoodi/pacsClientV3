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
from modules.viewer.fast.perf_metrics import PerfMetrics
from modules.viewer.fast.disk_pixel_cache import get_disk_pixel_cache
from modules.viewer.fast.decode_service import get_decode_service
from modules.viewer.fast.stack_cache_profile import build_stack_cache_profile
from modules.viewer.fast.system_load_controller import WorkClass
from modules.viewer.fast.ui_throttle import (
    cap_prefetch_radius,
    is_heavy_download_active,
    is_viewed_series_complete,
    should_admit,
)
from modules.zeta_boost.cache_engine import _zb_globals

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
        self._fast_interaction_mode: str = ""

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

        # B3.2: Generation-gated adaptive prefetch state
        self._prefetch_generation: int = 0           # monotonic generation counter
        self._prefetch_request_epoch: int = 0        # latest admitted neighborhood
        self._active_prefetch_targets: set[int] = set()
        self._scroll_history: List[Tuple[float, int]] = []  # (timestamp, slice_index) ring
        self._scroll_history_max: int = 12           # keep last N events
        self._last_prefetch_center: int = -1         # dedup: skip if same center

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
        self._interaction_slice_count_hint: int = 0
        self._drag_start_boost_until: float = 0.0

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
        # v2.3.5: cache series_number for series-level readiness queries
        self._series_number: Optional[str] = None
        if metadata:
            try:
                self._series_number = str(metadata.get("series", {}).get("series_number", "") or "")
            except Exception:
                pass

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
            self._prefetch_generation += 1  # invalidate any in-flight tasks
            self._prefetch_request_epoch += 1
            self._active_prefetch_targets.clear()
        self._slices.clear()
        self._current_index = 0
        self._window = None
        self._level = None
        self._series_path = None
        self._is_open = False
        self._interaction_slice_count_hint = 0
        self._drag_start_boost_until = 0.0
        self._first_render_logged = False
        self._filter_first_slices.clear()
        self._scroll_history.clear()
        self._last_prefetch_center = -1

    def notify_drag_started(self, center: Optional[int] = None) -> None:
        """Warm the current neighborhood when a new stack-drag begins.

        This is a targeted Block C startup assist: the first part of a drag can
        still feel sticky when the viewed region has not been warmed yet,
        especially just after a series switch or during progressive fill.

        We arm a short-lived surrogate boost and immediately prefetch around the
        current slice before the first drag delta arrives.  The steady-state
        drag policy is unchanged.
        """
        if not self._slices:
            return
        try:
            idx = self._clamp(self._current_index if center is None else center)
        except Exception:
            return

        self._drag_start_boost_until = time.perf_counter() + 0.35
        self._last_prefetch_center = -1
        logger.debug(
            "FAST:drag_start_warmup center=%d slice_count=%d boost_ms=%d",
            idx,
            len(self._slices),
            350,
        )
        self._prefetch_around(idx, direction=0)

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
            # W/L change: bump generation to invalidate stale W/L frames,
            # and reset dedup so _prefetch_around re-submits.
            with self._prefetch_lock:
                self._prefetch_generation += 1
                self._prefetch_request_epoch += 1
                self._active_prefetch_targets.clear()
            self._last_prefetch_center = -1
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

    def get_rendered_frame(self, slice_index: int, *, interaction_type: str = '') -> RenderedFrame:
        """
        Get a fully-rendered frame for display (decode + filter + W/L + QImage).
        Uses cache when available.

        During fast interaction (_fast_interaction=True), filtering is
        interaction-class aware:

        - wheel: keep the filtered appearance for precision browsing
        - drag: skip the OpenCV filter to reduce per-frame cost by 3-5ms

        Drag-time approximation is refined on scroll-stop.

        B4.1 interaction_type:
          - 'wheel': precision browsing — NEVER serve surrogate (always exact slice)
          - 'drag': fast navigation — surrogate allowed (B3.7 nearest-cached)
          - '' (default): non-interactive call — no surrogate
        """
        idx = self._clamp(slice_index)
        sm = self._slices[idx]
        ww, wc = self._resolve_window_level(idx)
        # During fast interaction, wheel keeps the exact filtered appearance
        # while drag skips the filter for lower latency.
        _keep_filter_during_fast = self._fast_interaction and interaction_type == 'wheel'
        filter_enabled = self._config.opencv_filter_enabled and (
            not self._fast_interaction or _keep_filter_during_fast
        )
        cache_key = self._frame_cache_key(idx, ww, wc, filter_enabled)
        # B2.5: sample queue depths on every frame request
        _pm = PerfMetrics.get()
        if _pm.enabled:
            with self._prefetch_lock:
                _pm.record_queue_depths(len(self._prefetch_pending), len(self._frame_prefetch_pending))

        # During fast interaction, prefer an exact filtered cached frame when
        # available so the scrolling image matches the settled image appearance.
        # Fall back to the exact unfiltered cache only when the filtered frame
        # is not already available.
        if self._fast_interaction and self._config.opencv_filter_enabled and not filter_enabled:
            full_key = self._frame_cache_key(idx, ww, wc, True)
            if full_key in self._frame_cache:
                qimg = self._frame_cache.pop(full_key)
                self._frame_cache[full_key] = qimg
                self._record_cache_hit()
                _pm.record_cache_hit()
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "FAST:frame_cache source=hit_filtered_fast slice=%d ww=%.0f wc=%.0f "
                        "cache_size=%d pixel_cache_size=%d",
                        idx, ww, wc,
                        len(self._frame_cache), len(self._pixel_cache),
                    )
                return RenderedFrame(
                    qimage=qimg, width=qimg.width(), height=qimg.height(),
                    slice_index=idx, window_width=ww, window_center=wc,
                    photometric=sm.photometric, decode_ms=0.0, filter_ms=0.0,
                    wl_ms=0.0, total_ms=0.0,
                )
        if cache_key in self._frame_cache:
            qimg = self._frame_cache.pop(cache_key)
            self._frame_cache[cache_key] = qimg
            self._record_cache_hit()
            _pm.record_cache_hit()
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
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "FAST:frame_cache source=miss slice=%d ww=%.0f wc=%.0f filter=%s "
                "cache_size=%d pixel_cache_size=%d",
                idx, ww, wc, filter_enabled,
                len(self._frame_cache), len(self._pixel_cache),
            )

        # ── B3.7: Cache-first fast scroll ─────────────────────────────
        # During fast interaction (wheel/drag), avoid blocking the main
        # thread for 17-45ms of pydicom decode.  Instead show the nearest
        # cached pixel (0ms decode, ~2ms W/L) as a surrogate.  Background
        # prefetch workers continue filling the cache; scroll-stop
        # (end_fast_interaction) re-renders the exact slice.
        #
        # B4.1: Surrogate is ONLY used for stack-drag navigation.
        # Wheel precision browsing always renders the exact requested
        # slice — a clinical requirement.  Wheel moves ±1 slice so the
        # adjacent slice is almost always already in pixel_cache (cache
        # hit, 0ms decode).  On the rare miss, synchronous decode (≤17ms)
        # is acceptable for precision reading.
        _allow_surrogate = (interaction_type == 'drag')
        surrogate_distance = self._get_drag_surrogate_max_distance()
        if _allow_surrogate and self._fast_interaction:
            nearest_frame = self._find_nearest_cached_frame(
                idx,
                ww,
                wc,
                filter_enabled,
                max_distance=surrogate_distance,
            )
            if nearest_frame is not None:
                nearest_idx, qimg = nearest_frame
                frame = RenderedFrame(
                    qimage=qimg,
                    width=qimg.width(),
                    height=qimg.height(),
                    slice_index=idx,
                    window_width=ww,
                    window_center=wc,
                    photometric=sm.photometric,
                    decode_ms=0.0,
                    filter_ms=0.0,
                    wl_ms=0.0,
                    total_ms=0.0,
                )
                _pm.record_cache_hit()
                _pm.record_frame_render(0.0)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "FAST:nearest_cached_frame idx=%d nearest=%d dist=%d",
                        idx, nearest_idx, abs(idx - nearest_idx),
                    )
                if idx in self._pixel_cache:
                    self._submit_frame_prefetch(idx)
                else:
                    self._prefetch_around(idx)
                return frame

        if _allow_surrogate and self._fast_interaction and idx not in self._pixel_cache:
            nearest_idx = self._find_nearest_cached_pixel(
                idx,
                max_distance=surrogate_distance,
            )
            if nearest_idx is not None:
                t_surr = time.perf_counter()
                surrogate = self._render_frame_uncached(
                    nearest_idx, ww, wc, filter_enabled, record_metrics=False,
                )
                surr_ms = (time.perf_counter() - t_surr) * 1000.0
                frame = RenderedFrame(
                    qimage=surrogate.qimage,
                    width=surrogate.width,
                    height=surrogate.height,
                    slice_index=idx,
                    window_width=ww,
                    window_center=wc,
                    photometric=sm.photometric,
                    decode_ms=0.0,
                    filter_ms=surrogate.filter_ms,
                    wl_ms=surrogate.wl_ms,
                    total_ms=surr_ms,
                )
                _pm.record_cache_hit()  # surrogate counts as cache-assisted
                _pm.record_frame_render(surr_ms)
                if surr_ms > 0:
                    _pm.record_wl(surrogate.wl_ms)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "FAST:nearest_cached idx=%d nearest=%d dist=%d surr_ms=%.1f",
                        idx, nearest_idx, abs(idx - nearest_idx), surr_ms,
                    )
                self._prefetch_around(idx)
                return frame
        # ── End B3.7 ──────────────────────────────────────────────────

        _pm.record_cache_miss()
        frame = self._render_frame_uncached(idx, ww, wc, filter_enabled, record_metrics=True)
        # B2.5: record foreground wait (main-thread decode on cache miss)
        if frame.decode_ms > 0:
            _pm.record_foreground_wait(frame.decode_ms)
        _pm.record_frame_render(frame.total_ms)
        if frame.decode_ms > 0:
            _pm.record_decode(frame.decode_ms)
        if frame.wl_ms > 0:
            _pm.record_wl(frame.wl_ms)
        if frame.filter_ms > 0:
            _pm.record_filter(frame.filter_ms)
        self._prefetch_around(idx)
        return frame

    def set_fast_interaction(self, fast: bool, interaction_type: str = '') -> None:
        """Set fast-interaction mode. When True, filter is skipped during scroll."""
        self._fast_interaction = bool(fast)
        self._fast_interaction_mode = str(interaction_type or '') if fast else ''
        if not fast:
            self._drag_start_boost_until = 0.0

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

    def set_interaction_slice_count_hint(self, slice_count: int) -> None:
        """Set the slice count that current interaction policy should follow."""
        try:
            self._interaction_slice_count_hint = max(0, int(slice_count or 0))
        except Exception:
            self._interaction_slice_count_hint = 0

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

        B3.12: Checks disk pixel cache first.  On miss, decodes via pydicom
        and stores the result to disk cache for future re-opens.

        Performance note (v2.3.3-perf): For typical CT/MR data (slope=1,
        int intercept, MONOCHROME2), keeps data as int16 instead of
        converting to float32.  The downstream W/L function uses a LUT
        for int16/uint16 which is ~3-5× faster than the float path.
        Float32 is only used when slope ≠ 1 (fractional) or when
        MONOCHROME1 inversion needs float arithmetic.
        """
        sm = self._slices[idx]

        # B3.12: Disk cache lookup (L2 cache)
        disk_cache = get_disk_pixel_cache()
        study_uid = self._series_path or ""
        cached = disk_cache.get(
            sop_instance_uid=sm.path,
            study_uid=study_uid,
            expected_shape=(sm.rows, sm.cols),
        )
        if cached is not None:
            return cached

        ds = pydicom.dcmread(sm.path, stop_before_pixels=False, force=True)
        arr = np.asarray(ds.pixel_array)

        if arr.ndim == 3 and sm.samples_per_pixel < 3:
            arr = arr[0]  # multi-frame fallback

        if sm.samples_per_pixel >= 3:
            if arr.ndim == 4:
                arr = arr[0]
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
            result = np.ascontiguousarray(arr)
            disk_cache.put(sm.path, study_uid, result)
            return result

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
            result = np.ascontiguousarray(arr)
            disk_cache.put(sm.path, study_uid, result)
            return result

        # Slow path: fractional slope or MONOCHROME1 — use float32
        arr = arr.astype(np.float32, copy=False)
        if not _slope_is_unity or not math.isclose(intercept, 0.0):
            arr = arr * float(slope) + float(intercept)

        if not _is_monochrome2:
            arr = float(arr.max()) + float(arr.min()) - arr

        result = np.ascontiguousarray(arr)
        disk_cache.put(sm.path, study_uid, result)
        return result

    # ── Private: cache management ─────────────────────────────────────

    def _find_nearest_cached_pixel(self, idx: int, max_distance: int = 10) -> Optional[int]:
        """Find the nearest slice index in pixel_cache within *max_distance*.

        B3.7: Used during fast interaction to locate a surrogate slice that
        can be rendered without a blocking pydicom decode.  Returns None if
        no cached pixel is within range.
        """
        best: Optional[int] = None
        best_dist = max_distance + 1
        for cached_idx in self._pixel_cache:
            dist = abs(cached_idx - idx)
            if dist < best_dist:
                best_dist = dist
                best = cached_idx
                if dist <= 1:
                    break  # can't do better than adjacent
        return best

    def _find_nearest_cached_frame(
        self,
        idx: int,
        ww: float,
        wc: float,
        filter_enabled: bool,
        max_distance: int = 10,
    ) -> Optional[Tuple[int, QImage]]:
        """Find the nearest rendered-frame cache entry within *max_distance*."""
        best_idx: Optional[int] = None
        best_key: Optional[Tuple[int, float, float, bool]] = None
        best_dist = max_distance + 1
        for key in self._frame_cache.keys():
            try:
                cached_idx, cached_ww, cached_wc, cached_filter = key
            except Exception:
                continue
            if bool(cached_filter) != bool(filter_enabled):
                continue
            if float(cached_ww) != float(ww) or float(cached_wc) != float(wc):
                continue
            dist = abs(int(cached_idx) - idx)
            if dist >= best_dist or dist > max_distance:
                continue
            best_dist = dist
            best_idx = int(cached_idx)
            best_key = key
            if dist <= 1:
                break
        if best_key is None or best_idx is None:
            return None
        qimg = self._frame_cache.pop(best_key)
        self._frame_cache[best_key] = qimg
        return best_idx, qimg

    def _get_drag_surrogate_max_distance(self) -> int:
        """Return the surrogate search window for drag navigation.

        Default drag navigation stays at ±10 slices. During active overlap
        (heavy download + incomplete viewed series), widen the search window to
        ±20 so fast drag can prefer a nearby cached surrogate over a blocking
        foreground decode when the cache is still sparse. Very high-speed drag
        may also widen to ±20 even for completed viewed series so transient
        cache gaps still resolve to surrogate instead of an exact foreground
        decode spike.
        """
        profile = build_stack_cache_profile(self._effective_policy_slice_count())

        if not self._fast_interaction:
            return int(profile.surrogate_distance)

        if (
            getattr(self, '_fast_interaction_mode', '') == 'drag'
            and time.perf_counter() < float(getattr(self, '_drag_start_boost_until', 0.0) or 0.0)
        ):
            return int(profile.widened_surrogate_distance)

        series_number = getattr(self, '_series_number', None)
        viewed_complete = bool(
            series_number is not None and is_viewed_series_complete(series_number)
        )
        velocity = self._estimate_scroll_velocity()
        if velocity >= 25.0:
            return int(profile.widened_surrogate_distance)
        if is_heavy_download_active() and not viewed_complete:
            return int(profile.widened_surrogate_distance)
        return int(profile.surrogate_distance)

    def _put_pixel_cache(self, idx: int, arr: np.ndarray) -> None:
        self._pixel_cache[idx] = arr
        while len(self._pixel_cache) > self._config.pixel_cache_size:
            self._pixel_cache.popitem(last=False)

    def _put_frame_cache(self, key: tuple, image: QImage) -> None:
        self._frame_cache[key] = image
        while len(self._frame_cache) > self._config.frame_cache_size:
            self._frame_cache.popitem(last=False)

    def _effective_policy_slice_count(self) -> int:
        """Return the slice count the current drag/cache policy should use."""
        actual = len(self._slices)
        try:
            hinted = int(getattr(self, '_interaction_slice_count_hint', 0) or 0)
        except Exception:
            hinted = 0
        if hinted > 0:
            return max(1, min(actual, hinted))
        return max(0, actual)

    # ── Private: prefetch ─────────────────────────────────────────────

    # -- B3.2: velocity estimation ---

    def _record_scroll_event(self, idx: int) -> None:
        """Record a scroll position sample for velocity estimation."""
        now = time.perf_counter()
        self._scroll_history.append((now, idx))
        # trim to max size
        if len(self._scroll_history) > self._scroll_history_max:
            self._scroll_history = self._scroll_history[-self._scroll_history_max:]

    def _estimate_scroll_velocity(self) -> float:
        """Estimate scroll velocity in slices/second from recent history.

        Returns 0.0 when there are fewer than 2 samples or all samples
        are older than 300ms.
        """
        if len(self._scroll_history) < 2:
            return 0.0
        now = time.perf_counter()
        # only consider events in the last 300ms
        cutoff = now - 0.3
        recent = [(t, i) for t, i in self._scroll_history if t >= cutoff]
        if len(recent) < 2:
            return 0.0
        dt = recent[-1][0] - recent[0][0]
        if dt < 1e-6:
            return 0.0
        d_slices = abs(recent[-1][1] - recent[0][1])
        return d_slices / dt

    def _compute_adaptive_radius(self, velocity: float) -> int:
        """Compute prefetch radius based on scroll velocity and series size.

        Policy (B3.2-i1):
        - Small series (≤30 slices): always full series → max radius
        - Fast scroll (≥20 sl/s):   radius 3  (direction-only)
        - Medium scroll (8-19 sl/s): radius 8  (3 during heavy download)
        - Slow/idle (<8 sl/s):       radius 15 (3 during heavy download)
        - Clamped to series_size // 2 for safety

        During active download, idle/medium radii are capped to 5 to
        reduce background decode worker CPU that competes with the
        download subprocess and Qt event loop.
        """
        n = self._effective_policy_slice_count()
        if n <= 30:
            # Small series: cache everything
            return max(n, 1)
        profile = build_stack_cache_profile(n)
        dl_active = is_heavy_download_active()
        # v2.3.5 Fix 2: relax download throttle for viewed series whose
        # individual download is complete, even if the study is still going.
        if dl_active and self._series_number:
            from modules.viewer.fast.ui_throttle import is_viewed_series_complete
            if is_viewed_series_complete(self._series_number):
                dl_active = False
        if velocity >= 20.0:
            r = profile.fast_prefetch_radius
        elif velocity >= 8.0:
            r = min(profile.medium_prefetch_radius, 3) if dl_active else profile.medium_prefetch_radius
        else:
            r = min(profile.medium_prefetch_radius, 3) if dl_active else profile.idle_prefetch_radius
        r = cap_prefetch_radius(
            r,
            fast_interaction_active=self._fast_interaction,
            interaction_mode=getattr(self, '_fast_interaction_mode', ''),
            series_number=getattr(self, '_series_number', None),
        )
        return min(r, max(n // 2, 1))

    # -- B3.2: adaptive prefetch entry point ---

    def _prefetch_around(self, center: int, direction: int = 0) -> None:
        """Submit prefetch tasks with adaptive window and deduplication.

        B3.2 policy (v2 — generation stays stable during scroll):
        1. Dedup: skip if already prefetching around this exact center.
        2. Record scroll event and estimate velocity.
        3. Compute adaptive radius based on velocity + series size.
        4. During fast/medium scroll, prefetch ONLY in movement direction.
        5. During slow/idle, prefetch bidirectionally.
        6. Generation only bumps on context changes (series close, W/L).
           Position-based invalidation uses pre-decode distance check.
        """
        if self._config.prefetch_radius <= 0:
            return

        # Dedup: skip if we already prefetched around this exact center.
        # Reset by close_series(), set_window_level(), direction changes.
        if center == self._last_prefetch_center:
            return
        self._last_prefetch_center = center

        # Record scroll event and estimate velocity
        self._record_scroll_event(center)
        velocity = self._estimate_scroll_velocity()
        adaptive_radius = self._compute_adaptive_radius(velocity)

        # B3.4→B3.7: Interaction-aware prefetch — during fast scroll, cap radius.
        # B3.7 raised the cap from 1 to 3: the main thread no longer blocks
        # for foreground decode (nearest-cached surrogate), so background
        # workers have more CPU headroom to fill the cache ahead of scroll.
        interaction_mode = self._fast_interaction
        if interaction_mode:
            profile = build_stack_cache_profile(self._effective_policy_slice_count())
            adaptive_radius = min(adaptive_radius, int(profile.fast_prefetch_radius))

        # B3.4 diagnostic: log prefetch decisions periodically (every 20 slices)
        if center % 20 == 0:
            logger.info(
                "[B3.4_DIAG] PREFETCH center=%d velocity=%.1f radius=%d fast=%s dir=%d",
                center, velocity, adaptive_radius, self._fast_interaction, direction,
            )

        # Use current generation (only bumped on W/L or series change)
        gen = self._prefetch_generation
        series_key = str(
            getattr(self, '_series_number', None)
            or getattr(self, '_series_path', None)
            or 'prefetch'
        )

        # Determine direction scope
        # Fast/medium scroll: unidirectional (scroll direction only)
        # Slow/idle: bidirectional
        go_forward = True
        go_backward = True
        if velocity >= 8.0 and direction != 0:
            if direction > 0:
                go_backward = False
            else:
                go_forward = False

        n = len(self._slices)
        target_indices: set[int] = set()
        for offset in range(1, adaptive_radius + 1):
            if go_forward:
                fwd = center + offset
                if 0 <= fwd < n:
                    target_indices.add(fwd)
            if go_backward:
                bwd = center - offset
                if 0 <= bwd < n:
                    target_indices.add(bwd)

        with self._prefetch_lock:
            active_targets = set(getattr(self, '_active_prefetch_targets', set()))
            request_epoch = int(getattr(self, '_prefetch_request_epoch', 0))
            if target_indices != active_targets:
                request_epoch += 1
                self._active_prefetch_targets = set(target_indices)
                self._prefetch_request_epoch = request_epoch

        for offset in range(1, adaptive_radius + 1):
            # Forward
            if go_forward:
                fwd = center + offset
                if 0 <= fwd < n:
                    if fwd not in self._pixel_cache:
                        if should_admit(
                            WorkClass.PREFETCH,
                            {
                                "key": f"{series_key}:prefetch:{center}:{direction}",
                                "series_key": series_key,
                                "distance": offset,
                                "interaction_mode": getattr(self, '_fast_interaction_mode', ''),
                            },
                        ):
                            self._submit_prefetch(fwd, gen, request_epoch=request_epoch)
                    elif not interaction_mode:
                        self._submit_frame_prefetch(fwd)
            # Backward
            if go_backward:
                bwd = center - offset
                if 0 <= bwd < n:
                    if bwd not in self._pixel_cache:
                        if should_admit(
                            WorkClass.PREFETCH,
                            {
                                "key": f"{series_key}:prefetch:{center}:{direction}",
                                "series_key": series_key,
                                "distance": offset,
                                "interaction_mode": getattr(self, '_fast_interaction_mode', ''),
                            },
                        ):
                            self._submit_prefetch(bwd, gen, request_epoch=request_epoch)
                    elif not interaction_mode:
                        self._submit_frame_prefetch(bwd)

    def _submit_prefetch(self, idx: int, generation: int = 0, *, request_epoch: int = 0) -> None:
        with self._prefetch_lock:
            if idx in self._pixel_cache or idx in self._prefetch_pending:
                return
            self._prefetch_pending.add(idx)
        PerfMetrics.get().record_prefetch_submitted()
        self._decode_executor.submit(self._decode_into_cache, idx, generation, request_epoch)

    def _submit_frame_prefetch(self, idx: int) -> None:
        with self._prefetch_lock:
            if idx in self._frame_prefetch_pending:
                return
            self._frame_prefetch_pending.add(idx)
        self._frame_executor.submit(self._render_into_cache, idx)

    def _decode_into_cache(self, idx: int, generation: int = 0, request_epoch: int = 0) -> None:
        # B3.2: generation gate — check BEFORE the expensive pydicom.dcmread.
        # Only fires on true context changes (series close, W/L change).
        if generation > 0 and generation != self._prefetch_generation:
            with self._prefetch_lock:
                self._prefetch_pending.discard(idx)
            _pm = PerfMetrics.get()
            _pm.record_prefetch_completed()
            _pm.record_cancelled_task()
            return

        # C3: request-identity gate — only the newest admitted prefetch
        # neighborhood should continue to burn background decode work.
        with self._prefetch_lock:
            active_epoch = self._prefetch_request_epoch
            active_targets = set(self._active_prefetch_targets)
        if request_epoch > 0 and request_epoch != active_epoch and idx not in active_targets:
            with self._prefetch_lock:
                self._prefetch_pending.discard(idx)
            _pm = PerfMetrics.get()
            _pm.record_prefetch_completed()
            _pm.record_cancelled_task()
            return

        # B3.2: pre-decode position relevance — skip if user has scrolled
        # far past this slice.  Saves GIL time for the decode.
        # B4.x follow-up: keep a modest slack window during fast interaction.
        # The admitted prefetch neighborhood is now radius 3, and under heavy
        # overlap a queued +2/+3 task may not begin immediately.  A hard ±3
        # reject cancels the exact next-wheel warm band too aggressively,
        # leaving precision wheel scroll to fall back to foreground decode.
        # Allow one extra neighborhood of slack (±6) so nearby admitted work
        # survives short scheduler delays without reopening wide stale decode.
        current = self._current_index
        _max_distance = 6 if self._fast_interaction else self._config.prefetch_radius
        if abs(idx - current) > _max_distance:
            with self._prefetch_lock:
                self._prefetch_pending.discard(idx)
            _pm = PerfMetrics.get()
            _pm.record_prefetch_completed()
            _pm.record_cancelled_task()
            return

        if idx in self._pixel_cache:
            with self._prefetch_lock:
                self._prefetch_pending.discard(idx)
            return
        try:
            # B3.11: Try subprocess decode first (GIL isolation for prefetch)
            # EXCEPTION: during active download overlap on an incomplete viewed
            # series, background prefetch may probe files that are still being
            # flushed to disk. Those per-file failures are not user-visible
            # errors, but they can poison the subprocess health counters and
            # trigger restart/disable churn right as the first series is coming
            # on-screen. In that overlap window, keep prefetch decode local and
            # deterministic; foreground decode is already in-process by design.
            arr = None
            use_subprocess_prefetch = True
            if is_heavy_download_active() and self._series_number:
                try:
                    if not is_viewed_series_complete(self._series_number):
                        use_subprocess_prefetch = False
                except Exception:
                    use_subprocess_prefetch = False

            sm = self._slices[idx] if idx < len(self._slices) else None
            if sm is not None:
                disk_cache = get_disk_pixel_cache()
                study_uid = self._series_path or ""
                arr = disk_cache.get(
                    sop_instance_uid=sm.path,
                    study_uid=study_uid,
                    expected_shape=(sm.rows, sm.cols),
                )

            svc = get_decode_service() if use_subprocess_prefetch else None
            if arr is None and svc is not None and svc.is_available and sm is not None:
                arr = svc.decode(
                    file_path=sm.path,
                    rows=sm.rows,
                    cols=sm.cols,
                    slope=sm.slope,
                    intercept=sm.intercept,
                    photometric=sm.photometric or "MONOCHROME2",
                    samples_per_pixel=sm.samples_per_pixel,
                )
                if arr is not None:
                    # Save to disk cache (B3.12)
                    disk_cache.put(sm.path, study_uid, arr)
            # Fallback to in-process decode
            if arr is None:
                arr = self._decode_slice(idx)
            # B3.2: cache pollution guard — check relevance AFTER decode
            # If the user has scrolled far away during our decode, discard
            # the result instead of polluting the cache.
            current = self._current_index
            distance = abs(idx - current)
            # Use a generous relevance window (2× adaptive or minimum 20)
            # to avoid discarding useful nearby results
            profile = build_stack_cache_profile(self._effective_policy_slice_count())
            relevance_limit = max(
                int(profile.decode_relevance_window),
                self._compute_adaptive_radius(self._estimate_scroll_velocity()) * 2,
            )
            if distance <= relevance_limit:
                self._put_pixel_cache(idx, arr)
                self._submit_frame_prefetch(idx)
            else:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "B3.2:discard_stale_decode idx=%d current=%d dist=%d limit=%d",
                        idx, current, distance, relevance_limit,
                    )
        except Exception:
            pass
        finally:
            with self._prefetch_lock:
                self._prefetch_pending.discard(idx)
            _pm = PerfMetrics.get()
            _pm.record_prefetch_completed()
            # B2.5: stale detection — task completed for a slice far from current view
            if _pm.enabled and abs(idx - self._current_index) > self._config.prefetch_radius:
                _pm.record_stale_task()

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
