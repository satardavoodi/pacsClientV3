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
    span = upper - lower
    if span <= 0.0:
        return np.zeros_like(arr, dtype=np.uint8)
    return window_to_uint8_fast(arr, lower, upper, span)


def window_to_uint8_fast(arr: np.ndarray, lower: float, upper: float, span: float) -> np.ndarray:
    """Optimized W/L → uint8 conversion.

    For integer data (int16/uint16) uses a 65536-entry LUT with fancy
    indexing.  For float data, uses ``_window_direct_fast`` which creates
    a clean output array without mutating the input (important when the
    input comes from the pixel cache).
    """
    # Integer fast path: LUT-based mapping
    if arr.dtype in (np.int16, np.uint16):
        return _window_lut_int(arr, lower, upper, span)

    # Any other type: non-mutating direct expression
    return _window_direct_fast(arr, lower, upper, span)


# Pre-allocated LUT cache — keyed by (lower, upper) rounded to 0.1
_LUT_CACHE: dict = {}
_LUT_CACHE_MAX = 16


def _window_lut_int(arr: np.ndarray, lower: float, upper: float, span: float) -> np.ndarray:
    """Apply W/L via pre-computed LUT for integer arrays.

    For int16 data, the LUT has 65536 entries (128KB — fits in L1/L2 cache).
    Uses numpy fancy indexing (``lut[view]``) which is faster than ``np.take``
    because it avoids the ravel/reshape overhead.

    The LUT is built in uint16 index order: indices 0..32767 map to int16
    values 0..32767, and indices 32768..65535 map to int16 values -32768..-1
    (two's complement reinterpretation).  This allows direct ``lut[arr.view(uint16)]``
    without any offset arithmetic.
    """
    global _LUT_CACHE
    # Round to 0.5 to allow some cache reuse during W/L drag
    cache_key = (round(lower * 2) / 2, round(upper * 2) / 2, arr.dtype.str)

    lut = _LUT_CACHE.get(cache_key)
    if lut is None:
        if arr.dtype == np.int16:
            # Build LUT indexed by uint16 — reinterpret uint16 range as int16
            # so that lut[arr.view(uint16)] gives the correct W/L output.
            int_vals = np.arange(65536, dtype=np.uint16).view(np.int16).astype(np.float64)
        elif arr.dtype == np.uint16:
            int_vals = np.arange(0, 65536, dtype=np.float64)
        elif arr.dtype == np.int32:
            return _window_direct_fast(arr, lower, upper, span)
        else:
            return _window_direct_fast(arr, lower, upper, span)

        np.clip(int_vals, lower, upper, out=int_vals)
        int_vals -= lower
        int_vals *= (255.0 / span)
        lut = int_vals.astype(np.uint8)

        # Evict oldest if cache is full
        if len(_LUT_CACHE) >= _LUT_CACHE_MAX:
            _LUT_CACHE.pop(next(iter(_LUT_CACHE)))
        _LUT_CACHE[cache_key] = lut

    # Reinterpret int16 → uint16 for indexing (no copy, same bit pattern)
    if arr.dtype == np.int16:
        view = arr.view(np.uint16)
    else:
        view = arr
    return lut[view]


def _window_direct_fast(arr: np.ndarray, lower: float, upper: float, span: float) -> np.ndarray:
    """Direct W/L for int32 or other types — single allocation."""
    clipped = np.clip(arr, lower, upper)
    return ((clipped - lower) * (255.0 / span)).astype(np.uint8, copy=False)
