import math
from typing import Any, Optional, Tuple

import numpy as np


_LEGACY_DB_WINDOW_WIDTH = 127.5
_LEGACY_DB_WINDOW_CENTER = 255.0
_LEGACY_EPS = 1e-3


def coerce_window_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, (list, tuple)):
            if not value:
                return None
            value = value[0]
        elif hasattr(value, "__iter__") and not isinstance(value, (str, bytes, bytearray)):
            seq = list(value)
            if not seq:
                return None
            value = seq[0]
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    except Exception:
        return None


def is_legacy_window_placeholder(window_width: Any, window_center: Any) -> bool:
    ww = coerce_window_value(window_width)
    wc = coerce_window_value(window_center)
    if ww is None or wc is None:
        return False
    return (
        math.isclose(ww, _LEGACY_DB_WINDOW_WIDTH, abs_tol=_LEGACY_EPS)
        and math.isclose(wc, _LEGACY_DB_WINDOW_CENTER, abs_tol=_LEGACY_EPS)
    )


def normalize_window_level(
    window_width: Any,
    window_center: Any,
    *,
    treat_legacy_placeholder_as_missing: bool = False,
) -> Tuple[Optional[float], Optional[float]]:
    ww = coerce_window_value(window_width)
    wc = coerce_window_value(window_center)
    if ww is None or wc is None:
        return None, None
    if ww <= 0.0:
        return None, None
    if treat_legacy_placeholder_as_missing and is_legacy_window_placeholder(ww, wc):
        return None, None
    return float(ww), float(wc)


def is_hu_like_range(min_value: float, max_value: float) -> bool:
    return float(min_value) < -500.0 and float(max_value) > 1000.0


def auto_window_level_from_range(min_value: float, max_value: float) -> Tuple[float, float]:
    lo = float(min_value)
    hi = float(max_value)
    if is_hu_like_range(lo, hi):
        return 400.0, 40.0
    return max(1.0, hi - lo), (hi + lo) / 2.0


def auto_window_level_from_array(arr: np.ndarray, lo_pct: float = 1.0, hi_pct: float = 99.0) -> Tuple[float, float]:
    lo = float(np.percentile(arr, lo_pct))
    hi = float(np.percentile(arr, hi_pct))
    return auto_window_level_from_range(lo, hi)


def dicom_window_bounds(window_width: Any, window_center: Any) -> Tuple[float, float]:
    ww = max(float(coerce_window_value(window_width) or 1.0), 1.0)
    wc = float(coerce_window_value(window_center) or 0.0)
    lower = wc - 0.5 - (ww - 1.0) / 2.0
    upper = wc - 0.5 + (ww - 1.0) / 2.0
    return lower, upper


def window_to_uint8(arr: np.ndarray, window_width: Any, window_center: Any) -> np.ndarray:
    lower, upper = dicom_window_bounds(window_width, window_center)
    clipped = np.clip(arr, lower, upper)
    span = upper - lower
    if span <= 0.0:
        return np.zeros_like(arr, dtype=np.uint8)
    return ((clipped - lower) / span * 255.0).astype(np.uint8, copy=False)
