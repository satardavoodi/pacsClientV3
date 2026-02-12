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
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import reference_line


def _safe_dcmread(path: str):
    from PacsClient.pacs.patient_tab.utils.utils import _safe_dcmread as safe
    return safe(path, stop_before_pixels=False)


def _safe_dcmread_header(path: str):
    from PacsClient.pacs.patient_tab.utils.utils import _safe_dcmread as safe
    return safe(path, stop_before_pixels=True)


def _is_scout_dataset(ds) -> bool:
    try:
        image_type = getattr(ds, "ImageType", None)
        if image_type:
            if isinstance(image_type, (list, tuple)):
                image_type_str = "\\".join([str(x).upper() for x in image_type])
            else:
                image_type_str = str(image_type).upper()
            if "LOCALIZER" in image_type_str or "SCOUT" in image_type_str:
                return True

        series_desc = str(getattr(ds, "SeriesDescription", "")).upper()
        if "LOCALIZER" in series_desc or "SCOUT" in series_desc:
            return True

        protocol_name = str(getattr(ds, "ProtocolName", "")).upper()
        if "LOCALIZER" in protocol_name or "SCOUT" in protocol_name:
            return True
    except Exception:
        return False
    return False


def find_scout_and_slices(paths: List[str]) -> Tuple[Optional[str], List[str]]:
    """
    Find scout/localizer image path among the provided DICOM paths.
    Returns (scout_path, slice_paths). If no scout found, uses first path as scout.
    """
    if not paths:
        return None, []

    scout_path = None
    for path in paths:
        try:
            ds = _safe_dcmread_header(path)
            if _is_scout_dataset(ds):
                scout_path = path
                break
        except Exception:
            continue

    if scout_path is None:
        scout_path = paths[0]

    slice_paths = [p for p in paths if p != scout_path]
    return scout_path, slice_paths


def compute_scout_reference_lines(
    scout_path: str,
    slice_paths: List[str],
) -> Tuple[int, int, List[Tuple[float, float, float, float]]]:
    """
    Compute reference lines for slice planes on the scout image.
    Returns (rows, cols, lines) where lines are (x0, y0, x1, y1) in scout pixel coords.
    """
    lines: List[Tuple[float, float, float, float]] = []
    try:
        scout_ds = _safe_dcmread_header(scout_path)
        iop_s = getattr(scout_ds, "ImageOrientationPatient", None)
        ipp_s = getattr(scout_ds, "ImagePositionPatient", None)
        ps_s = getattr(scout_ds, "PixelSpacing", None)
        rows_s = int(getattr(scout_ds, "Rows", 0) or 0)
        cols_s = int(getattr(scout_ds, "Columns", 0) or 0)
        if not iop_s or not ipp_s or not ps_s or rows_s <= 0 or cols_s <= 0:
            return 0, 0, []

        row_s = np.asarray(iop_s[3:6], dtype=float)
        col_s = np.asarray(iop_s[0:3], dtype=float)
        pos_s = np.asarray(ipp_s, dtype=float)
        sy = float(ps_s[0])
        sx = float(ps_s[1])

        quad = reference_line.rl_quad_corners_lps(rows_s, cols_s, pos_s, row_s, col_s, sy, sx)

        for path in slice_paths:
            try:
                ds = _safe_dcmread_header(path)
                iop = getattr(ds, "ImageOrientationPatient", None)
                ipp = getattr(ds, "ImagePositionPatient", None)
                if not iop or not ipp:
                    continue

                row = np.asarray(iop[3:6], dtype=float)
                col = np.asarray(iop[0:3], dtype=float)
                n = np.cross(row, col)
                n = n / (np.linalg.norm(n) + reference_line.rl_eps())
                p = np.asarray(ipp, dtype=float)

                ok, seg = reference_line.rl_clip_plane_with_quad(p, n, quad)
                if not ok:
                    continue
                P0_lps, P1_lps = seg

                I0 = reference_line.rl_lps_to_target_index(P0_lps, pos_s, col_s, row_s, sx, sy, 0)
                I1 = reference_line.rl_lps_to_target_index(P1_lps, pos_s, col_s, row_s, sx, sy, 0)
                lines.append((float(I0[0]), float(I0[1]), float(I1[0]), float(I1[1])))
            except Exception:
                continue

        return rows_s, cols_s, lines
    except Exception:
        return 0, 0, []


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
    # Do not clamp to image bounds; allow pan beyond the viewport (fills with black)

    # Calculate crop origin based on normalized pan translation
    center_x = width // 2 + int(pan_x * crop_w // 2)
    center_y = height // 2 + int(pan_y * crop_h // 2)

    x0 = center_x - crop_w // 2
    y0 = center_y - crop_h // 2
    x1 = x0 + crop_w
    y1 = y0 + crop_h

    # Create output canvas and copy overlapping region
    output = np.zeros((crop_h, crop_w), dtype=arr.dtype)

    src_x0 = max(0, x0)
    src_y0 = max(0, y0)
    src_x1 = min(width, x1)
    src_y1 = min(height, y1)

    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return output

    dst_x0 = max(0, -x0)
    dst_y0 = max(0, -y0)
    dst_x1 = dst_x0 + (src_x1 - src_x0)
    dst_y1 = dst_y0 + (src_y1 - src_y0)

    output[dst_y0:dst_y1, dst_x0:dst_x1] = arr[src_y0:src_y1, src_x0:src_x1]
    return output


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
