"""DICOM rendering helpers for print preview and film output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pydicom
try:
    from pydicom.pixels import apply_voi_lut
except Exception:  # fallback for older pydicom
    from pydicom.pixel_data_handlers.util import apply_voi_lut
from PySide6.QtGui import QImage, QPixmap

from printing.core.models import ViewportState


def _safe_dcmread(path: str):
    from PacsClient.pacs.patient_tab.utils.utils import _safe_dcmread as safe
    return safe(path, stop_before_pixels=False)


def _apply_window_level(pixel_array: np.ndarray, window_width: float, window_level: float) -> np.ndarray:
    if window_width is None or window_level is None:
        return pixel_array
    lower = window_level - (window_width / 2.0)
    upper = window_level + (window_width / 2.0)
    clipped = np.clip(pixel_array, lower, upper)
    return clipped


def _parse_window_value(value) -> Optional[float]:
    if value is None:
        return None
    try:
        if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
            value = list(value)[0]
        if isinstance(value, str):
            if "\\" in value:
                value = value.split("\\")[0]
        return float(value)
    except Exception:
        return None


def get_dicom_window_level(path: str) -> Tuple[Optional[float], Optional[float]]:
    try:
        dcm = _safe_dcmread(path)
        window_width = _parse_window_value(getattr(dcm, "WindowWidth", None))
        window_level = _parse_window_value(getattr(dcm, "WindowCenter", None))

        if window_width is not None and window_level is not None:
            return window_width, window_level

        pixel_array = dcm.pixel_array
        if pixel_array.ndim > 2:
            pixel_array = pixel_array[0]

        min_val = float(np.min(pixel_array))
        max_val = float(np.max(pixel_array))
        window_width = max_val - min_val
        window_level = (max_val + min_val) / 2.0
        return window_width, window_level
    except Exception:
        return None, None


def _normalize_to_uint8(pixel_array: np.ndarray) -> np.ndarray:
    arr = pixel_array.astype(np.float32)
    if np.ptp(arr) == 0:
        return np.zeros_like(arr, dtype=np.uint8)
    arr = (arr - arr.min()) / np.ptp(arr)
    return (arr * 255.0).astype(np.uint8)


def _apply_viewport(arr: np.ndarray, viewport: ViewportState) -> np.ndarray:
    if viewport is None:
        return arr
    zoom = max(viewport.zoom, 1.0)
    pan_x, pan_y = viewport.pan
    height, width = arr.shape

    crop_w = int(width / zoom)
    crop_h = int(height / zoom)

    # Uniform pan translation: pan values move viewport in normalized [-1, 1] range
    # Clamp pan to keep viewport within image bounds
    max_pan_x = (width - crop_w) / crop_w
    max_pan_y = (height - crop_h) / crop_h
    pan_x = max(min(pan_x, max_pan_x), -max_pan_x) if crop_w < width else 0
    pan_y = max(min(pan_y, max_pan_y), -max_pan_y) if crop_h < height else 0

    # Calculate crop origin based on normalized pan translation
    center_x = width // 2 + int(pan_x * crop_w // 2)
    center_y = height // 2 + int(pan_y * crop_h // 2)

    x0 = max(center_x - crop_w // 2, 0)
    y0 = max(center_y - crop_h // 2, 0)
    x1 = min(x0 + crop_w, width)
    y1 = min(y0 + crop_h, height)

    cropped = arr[y0:y1, x0:x1]
    if cropped.size == 0:
        return arr
    return cropped


@dataclass
class RenderedImage:
    pixmap: QPixmap
    rows: int
    columns: int
    aspect: float


def load_dicom_as_pixmap(path: str, viewport: Optional[ViewportState] = None) -> RenderedImage | None:
    try:
        dcm = _safe_dcmread(path)
        pixel_array = dcm.pixel_array
        photometric = str(getattr(dcm, "PhotometricInterpretation", "MONOCHROME2")).upper()
        is_rgb = photometric in {"RGB", "YBR_FULL", "YBR_FULL_422"}
        if pixel_array.ndim > 2 and not (is_rgb and pixel_array.ndim == 3):
            pixel_array = pixel_array[0]

        if hasattr(dcm, "RescaleSlope") or hasattr(dcm, "RescaleIntercept"):
            slope = float(getattr(dcm, "RescaleSlope", 1.0))
            intercept = float(getattr(dcm, "RescaleIntercept", 0.0))
            pixel_array = pixel_array * slope + intercept

        use_manual_window = viewport and (viewport.window_width is not None or viewport.window_level is not None)

        window_width = _parse_window_value(getattr(dcm, "WindowWidth", None))
        window_level = _parse_window_value(getattr(dcm, "WindowCenter", None))
        if not is_rgb and (window_width is None or window_level is None):
            window_width, window_level = get_dicom_window_level(path)

        if viewport and viewport.window_width is not None:
            window_width = viewport.window_width
        if viewport and viewport.window_level is not None:
            window_level = viewport.window_level

        if is_rgb:
            if pixel_array.dtype != np.uint8:
                pixel_array = _normalize_to_uint8(pixel_array)
            if pixel_array.ndim == 2:
                pixel_array = np.stack([pixel_array] * 3, axis=-1)
            image_rgb = np.ascontiguousarray(pixel_array)
            height, width, _ = image_rgb.shape
            bytes_per_line = image_rgb.strides[0]
            qimage = QImage(image_rgb.data, width, height, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimage.copy())
            aspect = width / height if height else 1.0
            return RenderedImage(pixmap=pixmap, rows=height, columns=width, aspect=aspect)

        if not is_rgb:
            if use_manual_window:
                pixel_array = _apply_window_level(pixel_array, window_width, window_level)
            else:
                # Use DICOM default WL/WW instead of VOI LUT to avoid uniform outputs
                pixel_array = _apply_window_level(pixel_array, window_width, window_level)
        pixel_array = _apply_viewport(pixel_array, viewport)

        image_8bit = _normalize_to_uint8(pixel_array)
        if photometric == "MONOCHROME1":
            image_8bit = 255 - image_8bit

        image_8bit = np.ascontiguousarray(image_8bit)
        height, width = image_8bit.shape
        bytes_per_line = image_8bit.strides[0]
        qimage = QImage(image_8bit.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimage.copy())
        aspect = width / height if height else 1.0
        return RenderedImage(pixmap=pixmap, rows=height, columns=width, aspect=aspect)
    except Exception:
        return None


def load_series_pixmaps(paths: List[str], viewport: Optional[ViewportState] = None) -> List[RenderedImage]:
    images: List[RenderedImage] = []
    for path in paths:
        rendered = load_dicom_as_pixmap(path, viewport)
        if rendered:
            images.append(rendered)
    return images
