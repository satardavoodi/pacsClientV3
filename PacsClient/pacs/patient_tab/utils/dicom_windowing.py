import math
import os
from typing import Any, Optional, Tuple

import numpy as np


_LEGACY_DB_WINDOW_WIDTH = 127.5
_LEGACY_DB_WINDOW_CENTER = 255.0
_LEGACY_EPS = 1e-3
_MG_FULL_RANGE_MIN_WW = 4096.0
_MG_FULL_RANGE_EQUAL_EPS = 1.0
_VOI_WL_FALLBACK_ENV = "AIPACS_ENABLE_VOI_WL_FALLBACK"


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


def is_mg_full_range_window_placeholder(
    window_width: Any,
    window_center: Any,
    *,
    modality: Any = None,
    photometric: Any = None,
    presentation_intent_type: Any = None,
) -> bool:
    """Heuristic for MG datasets that encode non-diagnostic default W/L tags.

    Some MG MONOCHROME1 datasets carry broad equal-valued defaults
    (for example 32768/32768) that wash out contrast in both FAST and
    Advanced paths. In that case we treat tag W/L as missing and fall
    back to percentile auto-windowing.
    """
    ww = coerce_window_value(window_width)
    wc = coerce_window_value(window_center)
    if ww is None or wc is None or ww <= 0.0:
        return False

    mod = str(modality or "").strip().upper()
    photo = str(photometric or "").strip().upper()
    intent = str(presentation_intent_type or "").strip().upper()

    if mod != "MG":
        return False
    # MG placeholder windows are observed on multiple photometric variants;
    # do not hard-reject non-MONOCHROME1 here.
    if not math.isclose(ww, wc, abs_tol=_MG_FULL_RANGE_EQUAL_EPS):
        return False
    if ww < _MG_FULL_RANGE_MIN_WW:
        return False
    if intent and "FOR PRESENTATION" not in intent:
        return False
    return True


def normalize_window_level(
    window_width: Any,
    window_center: Any,
    *,
    treat_legacy_placeholder_as_missing: bool = False,
    treat_mg_full_range_placeholder_as_missing: bool = False,
    modality: Any = None,
    photometric: Any = None,
    presentation_intent_type: Any = None,
) -> Tuple[Optional[float], Optional[float]]:
    ww = coerce_window_value(window_width)
    wc = coerce_window_value(window_center)
    if ww is None or wc is None:
        return None, None
    if ww <= 0.0:
        return None, None
    if treat_legacy_placeholder_as_missing and is_legacy_window_placeholder(ww, wc):
        return None, None
    if treat_mg_full_range_placeholder_as_missing and is_mg_full_range_window_placeholder(
        ww,
        wc,
        modality=modality,
        photometric=photometric,
        presentation_intent_type=presentation_intent_type,
    ):
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


def should_invert_for_display(
    photometric: Any,
    presentation_lut_shape: Any = None,
) -> bool:
    """Return True when grayscale pixels should be inverted for display.

    AIPacs runtime policy aligns with Advanced viewer behavior for clinical
    MG workflows: MONOCHROME1 is always inverted for display.
    Presentation LUT Shape is intentionally ignored here.
    """
    photo = str(photometric or "MONOCHROME2").strip().upper()
    return photo == "MONOCHROME1"


def auto_window_level_for_mg_array(
    arr: np.ndarray,
    lo_pct: float = 5.0,
    hi_pct: float = 99.0,
) -> Tuple[float, float]:
    """MG-specific fallback windowing with floor-background suppression.

    Mammography FOR PRESENTATION images often contain a very large background
    plateau at the minimum pixel value. Using a direct 1/99 percentile over the
    full image can produce an overly wide/bright window. This helper computes
    percentiles on foreground pixels above the image minimum when possible.
    """
    try:
        arr = np.asarray(arr)
        if arr.size == 0:
            return 256.0, 128.0

        # Baseline for MG FOR PRESENTATION: full-image 1/99 percentile.
        lo_all = float(np.percentile(arr, 1.0))
        hi_all = float(np.percentile(arr, 99.0))
        ww_all, wc_all = auto_window_level_from_range(lo_all, hi_all)

        floor = float(np.min(arr))
        ceil = float(np.max(arr))
        fg = arr[arr > floor]
        if fg.size < 1024:
            return ww_all, wc_all

        fg_ratio = float(fg.size) / float(arr.size)
        ceil_ratio = float(np.count_nonzero(arr >= ceil)) / float(arr.size)

        # For some MG FOR PRESENTATION datasets a large fraction of pixels sits
        # at the maximum code value, which pins high percentiles to ``ceil`` and
        # yields a too-wide, washed-out window. Use an interior band estimate as
        # a corrective candidate when enough non-saturated pixels exist.
        interior = arr[(arr > floor) & (arr < ceil)]
        has_reliable_interior = interior.size >= 4096

        # Foreground estimate. This lifts center level compared with full-image
        # stats so dense tissue doesn't wash out to white.
        lo_fg = float(np.percentile(fg, max(1.0, float(lo_pct))))
        hi_fg = float(np.percentile(fg, float(hi_pct)))
        ww_fg, wc_fg = auto_window_level_from_range(lo_fg, hi_fg)

        ww_int = wc_int = None
        if has_reliable_interior:
            lo_int = float(np.percentile(interior, 0.5))
            hi_int = float(np.percentile(interior, 99.5))
            ww_int, wc_int = auto_window_level_from_range(lo_int, hi_int)

        # Extremely sparse foreground: prefer foreground estimate.
        if fg_ratio < 0.20:
            if ww_int is not None and wc_int is not None and ceil_ratio > 0.25:
                return ww_int, wc_int
            return ww_fg, wc_fg

        # Ceiling-saturated case: prefer interior estimate to avoid white wash.
        if ww_int is not None and wc_int is not None and ceil_ratio > 0.25:
            return ww_int, wc_int

        # Mixed occupancy (common in MG): blend full-image and foreground
        # windows. This avoids the "too white" look of full-image only and
        # the "too dark" look of foreground-only.
        w_fg = 0.55
        w_all = 1.0 - w_fg
        ww = (w_fg * ww_fg) + (w_all * ww_all)
        wc = (w_fg * wc_fg) + (w_all * wc_all)
        return float(max(1.0, ww)), float(wc)

        return ww_all, wc_all
    except Exception:
        return auto_window_level_from_array(arr, 1.0, 99.0)


def is_voi_wl_fallback_enabled() -> bool:
    raw = str(os.getenv(_VOI_WL_FALLBACK_ENV, "1") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def auto_window_level_from_dicom_voi(
    dicom_path: str,
    *,
    modality: Any = None,
    presentation_intent_type: Any = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Compute a conservative default WW/WL via DICOM VOI/LUT if available.

    This is intended as a fallback when tag WW/WC are missing or placeholders.
    It is guarded by ``AIPACS_ENABLE_VOI_WL_FALLBACK`` for fast rollback.
    """
    if not is_voi_wl_fallback_enabled():
        return None, None
    try:
        if not dicom_path or not os.path.isfile(dicom_path):
            return None, None

        import pydicom  # local import by design
        try:
            from pydicom.pixels import apply_voi_lut
        except Exception:
            from pydicom.pixel_data_handlers.util import apply_voi_lut

        ds = pydicom.dcmread(dicom_path, stop_before_pixels=False, force=True)
        arr = np.asarray(ds.pixel_array)

        spp = int(getattr(ds, "SamplesPerPixel", 1) or 1)
        if spp >= 3:
            return None, None
        if arr.ndim == 3:
            arr = arr[0]

        slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
        intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
        photo = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2") or "MONOCHROME2").upper()
        plut = str(getattr(ds, "PresentationLUTShape", "") or "").upper()

        arr = arr.astype(np.float32, copy=False)
        if not math.isclose(slope, 1.0) or not math.isclose(intercept, 0.0):
            arr = arr * slope + intercept
        if should_invert_for_display(photo, plut):
            arr = float(arr.max()) + float(arr.min()) - arr

        has_voi = bool(
            getattr(ds, "VOILUTSequence", None)
            or getattr(ds, "VOILUTFunction", None)
        )
        if not has_voi:
            return None, None

        arr_voi = np.asarray(apply_voi_lut(arr, ds))
        if arr_voi.size == 0:
            return None, None

        mod = str(modality or getattr(ds, "Modality", "") or "").upper()
        intent = str(presentation_intent_type or getattr(ds, "PresentationIntentType", "") or "").upper()
        is_mg_fp = mod == "MG" and (not intent or "FOR PRESENTATION" in intent)
        if is_mg_fp:
            ww, wc = auto_window_level_for_mg_array(arr_voi)
        else:
            ww, wc = auto_window_level_from_array(arr_voi, 1.0, 99.0)
        return float(ww), float(wc)
    except Exception:
        return None, None


def resolve_cornerstone_like_window_level_from_dicom(
    dicom_path: str,
    *,
    modality: Any = None,
    presentation_intent_type: Any = None,
    photometric: Any = None,
    enable_pixel_fallback: bool = True,
) -> Tuple[Optional[float], Optional[float], str]:
    """Resolve initial WW/WL with Cornerstone-like precedence.

    Order:
    1) DICOM WindowCenter/WindowWidth (validated/placeholder-filtered)
    2) VOI LUT path (when available)
    3) Pixel-stat fallback (optional)
    """
    try:
        if not dicom_path or not os.path.isfile(dicom_path):
            return None, None, "none"

        import pydicom  # local import by design
        ds = pydicom.dcmread(dicom_path, stop_before_pixels=True, force=True)

        mod = modality or getattr(ds, "Modality", None)
        intent = presentation_intent_type or getattr(ds, "PresentationIntentType", None)
        photo = photometric or getattr(ds, "PhotometricInterpretation", None)

        ww, wc = normalize_window_level(
            ds.get("WindowWidth", None),
            ds.get("WindowCenter", None),
            treat_legacy_placeholder_as_missing=True,
            # Cornerstone-like behavior: if WW/WL exists in DICOM, trust it.
            # MG 32768/32768 is commonly used and should not be auto-rejected
            # at this stage.
            treat_mg_full_range_placeholder_as_missing=False,
            modality=mod,
            photometric=photo,
            presentation_intent_type=intent,
        )
        if ww is not None and wc is not None:
            return float(ww), float(wc), "dicom_tag"

        ww_voi, wc_voi = auto_window_level_from_dicom_voi(
            dicom_path,
            modality=mod,
            presentation_intent_type=intent,
        )
        if ww_voi is not None and wc_voi is not None:
            return float(ww_voi), float(wc_voi), "voi_lut"

        if not enable_pixel_fallback:
            return None, None, "none"

        ds = pydicom.dcmread(dicom_path, stop_before_pixels=False, force=True)
        arr = np.asarray(ds.pixel_array)

        spp = int(getattr(ds, "SamplesPerPixel", 1) or 1)
        if spp >= 3:
            return None, None, "none"
        if arr.ndim == 3:
            arr = arr[0]

        arr = arr.astype(np.float32, copy=False)
        slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
        intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
        if not math.isclose(slope, 1.0) or not math.isclose(intercept, 0.0):
            arr = arr * slope + intercept

        photo2 = str(getattr(ds, "PhotometricInterpretation", photo or "MONOCHROME2") or "MONOCHROME2").upper()
        plut2 = str(getattr(ds, "PresentationLUTShape", "") or "").upper()
        if should_invert_for_display(photo2, plut2):
            arr = float(arr.max()) + float(arr.min()) - arr

        mod2 = str(mod or getattr(ds, "Modality", "") or "").upper()
        intent2 = str(intent or getattr(ds, "PresentationIntentType", "") or "").upper()
        is_mg_fp = mod2 == "MG" and (not intent2 or "FOR PRESENTATION" in intent2)
        if is_mg_fp:
            ww_px, wc_px = auto_window_level_for_mg_array(arr)
        else:
            ww_px, wc_px = auto_window_level_from_array(arr, 1.0, 99.0)
        return float(ww_px), float(wc_px), "pixel_percentile"
    except Exception:
        return None, None, "none"


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
