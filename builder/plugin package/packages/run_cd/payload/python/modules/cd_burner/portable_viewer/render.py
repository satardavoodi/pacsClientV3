"""Pixel pipeline for the AI-PACS Lite Viewer.

Loads one slice (file or multi-frame frame) into a numpy array, applies
Modality rescale, resolves the default window/level, and converts a
windowed slice to a ``QImage``.

Only numpy + pydicom (+ optional bundled codecs) are used. ``QImage`` is the
single Qt type touched here; it is safe headless (offscreen) and in tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from pydicom import dcmread

from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)


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
        ds = dcmread(path)
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
        return SliceData(
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

    return SliceData(
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
        ds = dcmread(path, stop_before_pixels=True)
        return max(1, int(getattr(ds, "NumberOfFrames", 1) or 1))
    except Exception:
        return 1
