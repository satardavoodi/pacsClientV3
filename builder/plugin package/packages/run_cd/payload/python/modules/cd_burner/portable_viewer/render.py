"""Pixel pipeline for the AI-PACS Lite Viewer.

Loads one slice (file or multi-frame frame) into a numpy array, applies
Modality rescale, resolves the default window/level, and converts a
windowed slice to a ``QImage``.

Only numpy + pydicom (+ optional bundled codecs) are used. ``QImage`` is the
single Qt type touched here; it is safe headless (offscreen) and in tests.
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from pydicom import dcmread

from PySide6.QtGui import QImage

try:  # package-relative (dev run inside AI-PACS repo)
    from .optical_io import read_bytes
except ImportError:  # standalone build / direct script execution
    from optical_io import read_bytes  # type: ignore

logger = logging.getLogger(__name__)


def _dcmread_robust(path: str, **kwargs):
    """dcmread via a retry-buffered byte read (reliable on optical media).

    Falls back to a direct path read if the buffered read fails outright.
    """
    try:
        return dcmread(io.BytesIO(read_bytes(path)), **kwargs)
    except Exception:
        return dcmread(path, **kwargs)


def _float_tuple(value, count: int) -> Optional[tuple]:
    try:
        values = [float(v) for v in value]
        if len(values) != count or any(not math.isfinite(v) for v in values):
            return None
        return tuple(values)
    except Exception:
        return None


def _extract_geometry(ds, data: "SliceData") -> None:
    """Populate IPP/IOP/spacing on the slice (best effort, never raises)."""
    try:
        iop = _float_tuple(getattr(ds, "ImageOrientationPatient", None), 6)
        ipp = _float_tuple(getattr(ds, "ImagePositionPatient", None), 3)
        if iop and ipp:
            data.position = ipp
            data.row_dir = iop[0:3]
            data.col_dir = iop[3:6]
        spacing = _float_tuple(getattr(ds, "PixelSpacing", None), 2)
        if spacing and spacing[0] > 0 and spacing[1] > 0:
            data.pixel_spacing = spacing
            data.measure_spacing = spacing
            data.spacing_source = "PixelSpacing"
        else:
            # DICOM CP-586 fallback chain for projection radiography
            # (DX/CR/MG often carry ImagerPixelSpacing only).
            for keyword, label in (
                ("ImagerPixelSpacing", "ImagerPixelSpacing"),
                ("NominalScannedPixelSpacing", "NominalScannedPixelSpacing"),
            ):
                alt = _float_tuple(getattr(ds, keyword, None), 2)
                if alt and alt[0] > 0 and alt[1] > 0:
                    data.measure_spacing = alt
                    data.spacing_source = label
                    break
        data.frame_of_reference = str(getattr(ds, "FrameOfReferenceUID", "") or "")
    except Exception:  # geometry is optional — viewing must never break
        pass


def reference_line_segment(
    target: "SliceData",
    other: "SliceData",
) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """Intersection of `other`'s slice plane with `target`'s plane, as a 2D
    segment in TARGET image-pixel coordinates (clipped to the image rect).

    Returns None when geometry is missing, frames of reference differ, or
    the planes are (nearly) parallel. Pure math — unit-testable headless.
    """
    if (
        target.position is None or target.row_dir is None or target.col_dir is None
        or target.pixel_spacing is None
        or other.position is None or other.row_dir is None or other.col_dir is None
    ):
        return None
    if target.frame_of_reference and other.frame_of_reference:
        if target.frame_of_reference != other.frame_of_reference:
            return None

    t_pos = np.array(target.position, dtype=np.float64)
    t_row = np.array(target.row_dir, dtype=np.float64)   # along columns (u)
    t_col = np.array(target.col_dir, dtype=np.float64)   # along rows (v)
    o_pos = np.array(other.position, dtype=np.float64)
    o_n = np.cross(np.array(other.row_dir, np.float64), np.array(other.col_dir, np.float64))
    t_n = np.cross(t_row, t_col)

    direction = np.cross(t_n, o_n)
    if np.linalg.norm(direction) < 1e-6:
        return None  # parallel planes

    # Point on both planes: solve within the target plane. Express X = t_pos
    # + a*t_row + b*t_col, require (X - o_pos)·o_n = 0.
    rhs = float(np.dot(o_pos - t_pos, o_n))
    ca = float(np.dot(t_row, o_n))
    cb = float(np.dot(t_col, o_n))
    if abs(ca) < 1e-12 and abs(cb) < 1e-12:
        return None
    if abs(ca) >= abs(cb):
        a0, b0 = rhs / ca, 0.0
    else:
        a0, b0 = 0.0, rhs / cb
    point = t_pos + a0 * t_row + b0 * t_col

    # 2D direction in target (u along row_dir in mm, v along col_dir in mm)
    d_u = float(np.dot(direction, t_row))
    d_v = float(np.dot(direction, t_col))
    row_mm, col_mm = target.pixel_spacing  # (row spacing → v step, col spacing → u step)
    u0 = float(np.dot(point - t_pos, t_row)) / col_mm
    v0 = float(np.dot(point - t_pos, t_col)) / row_mm
    du = d_u / col_mm
    dv = d_v / row_mm
    if abs(du) < 1e-12 and abs(dv) < 1e-12:
        return None

    # Clip the infinite 2D line (u0+t*du, v0+t*dv) to [0,cols]x[0,rows]
    t_min, t_max = -1e12, 1e12
    for start, delta, low, high in (
        (u0, du, 0.0, float(target.cols)),
        (v0, dv, 0.0, float(target.rows)),
    ):
        if abs(delta) < 1e-12:
            if start < low or start > high:
                return None
            continue
        t1, t2 = (low - start) / delta, (high - start) / delta
        if t1 > t2:
            t1, t2 = t2, t1
        t_min = max(t_min, t1)
        t_max = min(t_max, t2)
    if t_min >= t_max:
        return None

    p1 = (u0 + t_min * du, v0 + t_min * dv)
    p2 = (u0 + t_max * du, v0 + t_max * dv)
    return p1, p2


def ruler_length_label(
    slice_data: "SliceData",
    p1: Tuple[float, float],
    p2: Tuple[float, float],
) -> str:
    """Length of a ruler between two image-pixel points, honoring the
    measurement spacing chain. Falls back to pixels when no spacing exists
    (never fabricates millimetres)."""
    du = p2[0] - p1[0]
    dv = p2[1] - p1[1]
    spacing = slice_data.measure_spacing
    if spacing:
        row_mm, col_mm = spacing
        length_mm = math.hypot(du * col_mm, dv * row_mm)
        if length_mm >= 100:
            return f"{length_mm / 10:.1f} cm"
        return f"{length_mm:.1f} mm"
    return f"{math.hypot(du, dv):.0f} px"


@dataclass
class SliceData:
    """One decoded, rescaled slice ready for windowing."""

    array: np.ndarray            # float32 (H, W) for mono; uint8 (H, W, 3) for color
    is_color: bool
    invert: bool                 # MONOCHROME1 → render inverted
    default_center: float
    default_width: float
    rows: int
    cols: int
    modality: str = ""
    instance_label: str = ""
    error: str = ""              # non-empty → placeholder slice with message
    # --- geometry (reference lines + measurements) ---
    position: Optional[Tuple[float, float, float]] = None      # IPP
    row_dir: Optional[Tuple[float, float, float]] = None        # IOP[0:3]
    col_dir: Optional[Tuple[float, float, float]] = None        # IOP[3:6]
    pixel_spacing: Optional[Tuple[float, float]] = None         # (row_mm, col_mm) geometric
    measure_spacing: Optional[Tuple[float, float]] = None       # spacing for RULER (mm/px)
    spacing_source: str = ""                                     # PixelSpacing/Imager/Nominal
    frame_of_reference: str = ""

    @classmethod
    def error_slice(cls, message: str) -> "SliceData":
        return cls(
            array=np.zeros((1, 1), dtype=np.float32),
            is_color=False,
            invert=False,
            default_center=0.5,
            default_width=1.0,
            rows=1,
            cols=1,
            error=message,
        )


def _first_number(value, default: Optional[float] = None) -> Optional[float]:
    """DICOM WindowCenter/Width may be a single value or a MultiValue."""
    if value is None:
        return default
    try:
        if isinstance(value, (list, tuple)) or value.__class__.__name__ == "MultiValue":
            value = value[0] if len(value) else None
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _default_window_from_array(array: np.ndarray) -> Tuple[float, float]:
    """Percentile-based fallback window when the header has none."""
    try:
        finite = array[np.isfinite(array)]
        if finite.size == 0:
            return 0.5, 1.0
        lo = float(np.percentile(finite, 1.0))
        hi = float(np.percentile(finite, 99.0))
        if hi <= lo:
            lo = float(finite.min())
            hi = float(finite.max())
        if hi <= lo:
            hi = lo + 1.0
        return (lo + hi) / 2.0, max(hi - lo, 1.0)
    except Exception:
        return 0.5, 1.0


def _to_rgb_uint8(array: np.ndarray, photometric: str, ds) -> Optional[np.ndarray]:
    """Normalize a color pixel array to uint8 RGB (H, W, 3)."""
    try:
        if photometric == "PALETTE COLOR":
            from pydicom.pixel_data_handlers.util import apply_color_lut

            array = apply_color_lut(array, ds)
            # apply_color_lut returns 16-bit RGB; scale down to 8-bit
            if array.dtype != np.uint8:
                array = (array.astype(np.float32) / max(float(array.max()), 1.0) * 255.0)
                array = array.astype(np.uint8)
        elif photometric.startswith("YBR"):
            from pydicom.pixel_data_handlers.util import convert_color_space

            array = convert_color_space(array, photometric, "RGB")

        if array.ndim == 2:  # degenerate single-channel "color"
            array = np.stack([array] * 3, axis=-1)
        if array.ndim != 3 or array.shape[-1] < 3:
            return None
        array = array[..., :3]
        if array.dtype != np.uint8:
            array = np.clip(array, 0, 255).astype(np.uint8)
        return np.ascontiguousarray(array)
    except Exception as exc:
        logger.warning("Color conversion failed: %s", exc)
        return None


def load_slice(path: str, frame_index: int = 0) -> SliceData:
    """Decode one slice. Never raises — returns an error slice instead."""
    try:
        ds = _dcmread_robust(path)
    except Exception as exc:
        return SliceData.error_slice(f"Cannot read file:\n{exc}")

    try:
        array = ds.pixel_array
    except Exception as exc:
        # Most common cause: compressed transfer syntax without a codec.
        syntax = ""
        try:
            syntax = str(ds.file_meta.TransferSyntaxUID.name)
        except Exception:
            pass
        detail = f" ({syntax})" if syntax else ""
        return SliceData.error_slice(
            "This image uses an unsupported compression" + detail + ".\n"
            "Open the study with a full DICOM viewer."
        )

    try:
        frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
    except Exception:
        frames = 1
    if frames > 1:
        try:
            if array.shape[0] == frames:
                array = array[max(0, min(frame_index, frames - 1))]
        except Exception:
            pass

    photometric = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")).upper().strip()
    samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
    modality = str(getattr(ds, "Modality", "") or "")
    instance_label = str(getattr(ds, "InstanceNumber", "") or "")

    # --- Color path -------------------------------------------------------
    if samples >= 3 or photometric in ("RGB", "PALETTE COLOR") or photometric.startswith("YBR"):
        rgb = _to_rgb_uint8(array, photometric, ds)
        if rgb is None:
            return SliceData.error_slice("Unsupported color image format.")
        data = SliceData(
            array=rgb,
            is_color=True,
            invert=False,
            default_center=127.5,
            default_width=255.0,
            rows=rgb.shape[0],
            cols=rgb.shape[1],
            modality=modality,
            instance_label=instance_label,
        )
        _extract_geometry(ds, data)
        return data

    # --- Grayscale path ----------------------------------------------------
    if array.ndim == 3:  # safety: collapse unexpected extra dim
        array = array[0] if array.shape[0] in (1, frames) else array[..., 0]
    array = array.astype(np.float32)

    slope = _first_number(getattr(ds, "RescaleSlope", None), 1.0) or 1.0
    intercept = _first_number(getattr(ds, "RescaleIntercept", None), 0.0) or 0.0
    if slope != 1.0 or intercept != 0.0:
        array = array * np.float32(slope) + np.float32(intercept)

    center = _first_number(getattr(ds, "WindowCenter", None))
    width = _first_number(getattr(ds, "WindowWidth", None))
    if center is None or width is None or not width or width <= 0:
        center, width = _default_window_from_array(array)

    data = SliceData(
        array=np.ascontiguousarray(array),
        is_color=False,
        invert=(photometric == "MONOCHROME1"),
        default_center=float(center),
        default_width=float(max(width, 1e-3)),
        rows=array.shape[0],
        cols=array.shape[1] if array.ndim >= 2 else 1,
        modality=modality,
        instance_label=instance_label,
    )
    _extract_geometry(ds, data)
    return data


def slice_to_qimage(slice_data: SliceData, center: float, width: float) -> QImage:
    """Window a slice into a display ``QImage`` (Grayscale8 or RGB888)."""
    if slice_data.is_color:
        rgb = slice_data.array
        image = QImage(
            rgb.data, rgb.shape[1], rgb.shape[0], rgb.shape[1] * 3, QImage.Format_RGB888
        )
        return image.copy()  # detach from numpy buffer

    width = max(float(width), 1e-3)
    lo = float(center) - width / 2.0
    arr = (slice_data.array - np.float32(lo)) * np.float32(255.0 / width)
    arr8 = np.clip(arr, 0.0, 255.0).astype(np.uint8)
    if slice_data.invert:
        arr8 = np.uint8(255) - arr8
    arr8 = np.ascontiguousarray(arr8)
    image = QImage(
        arr8.data, arr8.shape[1], arr8.shape[0], arr8.shape[1], QImage.Format_Grayscale8
    )
    return image.copy()


def peek_frame_count(path: str) -> int:
    """Header-only read of NumberOfFrames (for single-file cine series)."""
    try:
        ds = _dcmread_robust(path, stop_before_pixels=True)
        return max(1, int(getattr(ds, "NumberOfFrames", 1) or 1))
    except Exception:
        return 1
