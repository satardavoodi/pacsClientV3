"""
PooyanPacs-Compatible OpenCV Filter Pipeline
=============================================
Exact port of the PooyanPacs C# OpenCV filter chain to Python OpenCV (cv2).

Source of truth: PooyanPacs C# ``ImageFilter.FilterCenter`` (OpenCvSharp)
    File: IP.View.workstation/Handler/ImageFilter.cs
    File: CSharpRender2D.Sidecar/Services/DicomFrameMetadataReader.cs

Pipeline (C# reference):
    1. GaussianBlur(src, dst, (0,0), sigmaX)
    2. AddWeighted(src, alpha, blurred, beta, 0, dst)       # unsharp mask
    3. [if width<280 or height<280: Dilate(1×1 rect) + 2× Resize]

Default parameters (from ``DisplayRenderOptions`` record):
    FilterSigmaX  = 1.0
    FilterAlpha    = 1.4
    FilterBeta     = -0.5
    PreserveDimensions = False

Integration notes
-----------------
* This module operates on **numpy arrays** (grayscale, uint8 or int16).
* For 16-bit DICOM data the pipeline normalises to uint8, applies filters,
  then maps back — matching PooyanPacs which always works on 8-bit
  BitmapSource data after Window/Level.
* The module exposes two main APIs:
    - ``pooyan_filter_center()``   – single-image filter (matches C# exactly)
    - ``apply_pooyan_opencv_pipeline()``  – whole-volume filter for VTK integration
* Deterministic: same input + same params → same output.

Version history
---------------
v1.0.0 (2026-03-02): Initial port from PooyanPacs C# OpenCvSharp code.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None  # type: ignore
    CV2_AVAILABLE = False
import numpy as np
from PacsClient.pacs.patient_tab.utils.dicom_windowing import normalize_window_level, window_to_uint8

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Filter Parameters (matches C# DisplayRenderOptions defaults)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PooyanFilterParams:
    """
    Parameters for the PooyanPacs ``FilterCenter`` unsharp-mask filter.

    Defaults match the current AIPacs FAST-viewer tuning:
        sigmaX=1.0, alpha=1.4, beta=-0.45

    The C# code: ``Cv2.GaussianBlur(mat, dst, (0,0), sigmaX)``
    followed by: ``Cv2.AddWeighted(mat, alpha, dst, beta, 0, dst)``
    """
    sigma_x: float = 1.0       # GaussianBlur sigma (auto kernel from sigma)
    alpha: float = 1.4         # weight for original image
    beta: float = -0.45        # weight for blurred image (negative = sharpen)
    enabled: bool = True       # master enable flag
    small_threshold: int = 280  # pixels; triggers dilate + 2× resize path
    preserve_dimensions: bool = False  # if True, skip small-image resize
    invert: bool = False       # per-pixel colour inversion (255 - pixel)

    def __post_init__(self):
        # C# clamps sigmaX: Math.Max(0.05, sigmaX)
        if self.sigma_x < 0.05:
            object.__setattr__(self, 'sigma_x', 0.05)


# Singleton default params (avoid repeated allocation)
DEFAULT_PARAMS = PooyanFilterParams()


# ═══════════════════════════════════════════════════════════════════════════
# Core Filter: FilterCenter (Unsharp Mask via Gaussian + AddWeighted)
# ═══════════════════════════════════════════════════════════════════════════

def pooyan_filter_center(
    image: np.ndarray,
    params: PooyanFilterParams = DEFAULT_PARAMS,
) -> np.ndarray:
    """
    Exact Python port of PooyanPacs ``ImageFilter.FilterCenter``.

    C# algorithm::

        Mat mat = source.ToMat().CvtColor(BGR2RGB);
        Cv2.GaussianBlur(mat, dst, Size(0,0), sigmaX);
        Cv2.AddWeighted(mat, alpha, dst, beta, 0, dst);
        // if small: Dilate(1×1 rect) + Resize(2×)

    Parameters
    ----------
    image : np.ndarray
        Grayscale image, uint8 (H, W) or (H, W, 1).
        Also accepts int16 – will be windowed to uint8 internally.
    params : PooyanFilterParams
        Filter parameters (default matches C# defaults exactly).

    Returns
    -------
    np.ndarray
        Filtered image, same spatial layout.  dtype is uint8.
        If the small-image path fires and ``preserve_dimensions`` is False,
        dimensions are 2× the input.
    """
    if not params.enabled or not CV2_AVAILABLE:
        return image

    # Normalise input shape: ensure 2D grayscale
    if image.ndim == 3 and image.shape[2] == 1:
        image = image[:, :, 0]

    h, w = image.shape[:2]

    # ── Convert to uint8 if needed (PooyanPacs always processes 8-bit) ──
    src_dtype = image.dtype
    if src_dtype == np.uint8:
        gray = image
    elif np.issubdtype(src_dtype, np.integer):
        # 16-bit signed/unsigned → normalise to uint8 [0,255]
        # This matches PooyanPacs which receives BitmapSource (8-bit)
        # after DicomImage.RenderImage() applies Window/Level.
        mn, mx = float(image.min()), float(image.max())
        if mx > mn:
            gray = ((image.astype(np.float32) - mn) / (mx - mn) * 255.0).astype(np.uint8)
        else:
            gray = np.zeros_like(image, dtype=np.uint8)
    else:
        # float → assume [0,1] or arbitrary range → normalise
        mn, mx = float(image.min()), float(image.max())
        if mx > mn:
            gray = ((image - mn) / (mx - mn) * 255.0).astype(np.uint8)
        else:
            gray = np.zeros((h, w), dtype=np.uint8)

    # ── Step 1: Match C# colour-space handling ──
    # C# does: source.ToMat().CvtColor(BGR2RGB). For a WPF BitmapSource
    # this converts the internal BGR Mat to RGB.  For our grayscale input
    # we convert GRAY→BGR (matching C# Sidecar ``ApplyPooyanFilterCenter``).
    mat = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # ── Step 2: GaussianBlur + AddWeighted (unsharp mask) ──
    # C#: Cv2.GaussianBlur(mat, dst, new Size(0,0), sigmaX);
    # OpenCV auto-calculates kernel size from sigma when ksize=(0,0).
    dst = cv2.GaussianBlur(mat, (0, 0), params.sigma_x)
    # C#: Cv2.AddWeighted(mat, alpha, dst, beta, 0, dst);
    dst = cv2.addWeighted(mat, params.alpha, dst, params.beta, 0.0)

    # ── Step 3: Small-image path ──
    # C#: if (source.PixelWidth < 280 || source.PixelHeight < 280)
    if w < params.small_threshold or h < params.small_threshold:
        # Dilate with 1×1 rect kernel (effectively a no-op, but kept for parity)
        element = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
        dst = cv2.dilate(dst, element)
        # 2× resize unless PreserveDimensions
        if not params.preserve_dimensions:
            dst = cv2.resize(dst, (w * 2, h * 2))

    # ── Step 4: Convert back to grayscale ──
    # C# Sidecar: Cv2.CvtColor(dst, outGray, BGR2GRAY);
    out_gray = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY)

    return out_gray


def pooyan_invert(image: np.ndarray) -> np.ndarray:
    """
    Pixel inversion matching PooyanPacs ``InvertColor``.

    C# code: ``data[i] = (byte)(255 - data[i]);`` for R, G, B, A channels.
    For grayscale uint8 this is simply ``255 - pixel``.
    """
    if not CV2_AVAILABLE:
        if image.dtype == np.uint8:
            return (255 - image).astype(np.uint8)
        info = np.iinfo(image.dtype) if np.issubdtype(image.dtype, np.integer) else None
        return (info.max - image).astype(image.dtype) if info is not None else image
    if image.dtype == np.uint8:
        return cv2.bitwise_not(image)
    # For other dtypes, invert within dtype range
    info = np.iinfo(image.dtype) if np.issubdtype(image.dtype, np.integer) else None
    if info is not None:
        return (info.max - image).astype(image.dtype)
    return image


# ═══════════════════════════════════════════════════════════════════════════
# Fusion / ColorMap Overlay (matches C# OpenCvImageProcessor.Fusion)
# ═══════════════════════════════════════════════════════════════════════════

# C# ColormapTypes → cv2 equivalents
if CV2_AVAILABLE:
    COLORMAP_LOOKUP = {
        "Plasma":    cv2.COLORMAP_PLASMA,
        "Inferno":   cv2.COLORMAP_INFERNO,
        "Hot Iron":  cv2.COLORMAP_HOT,
        "Hot":       cv2.COLORMAP_HOT,
        "Winter":    cv2.COLORMAP_WINTER,
        "Rainbow 1": cv2.COLORMAP_RAINBOW,
        "Rainbow":   cv2.COLORMAP_RAINBOW,
        "Rainbow 2": cv2.COLORMAP_JET,
        "Jet":       cv2.COLORMAP_JET,
        "Hsv":       cv2.COLORMAP_HSV,
        "HSV":       cv2.COLORMAP_HSV,
    }
else:
    COLORMAP_LOOKUP = {}


def pooyan_fusion(
    image: np.ndarray,
    colormap_name: str = "Plasma",
    opacity: float = 0.5,
) -> np.ndarray:
    """
    Exact port of PooyanPacs ``OpenCvImageProcessor.Fusion``.

    Applies a colour map with alpha blending, preserving black background.

    Parameters
    ----------
    image : np.ndarray
        Grayscale uint8 image (H, W).
    colormap_name : str
        One of the PooyanPacs colormap names.
    opacity : float
        Blend weight for the coloured image (0–1).

    Returns
    -------
    np.ndarray
        BGR image (H, W, 3), uint8.
    """
    if not CV2_AVAILABLE:
        return image
    if image.ndim == 2:
        bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        bgr = image.copy()

    # C#: normalise → apply colormap
    _norm_dst = np.empty_like(bgr)
    normalized = cv2.normalize(bgr, _norm_dst, 0, 255, cv2.NORM_MINMAX, cv2.CV_8UC1)
    if normalized.ndim == 3:
        normalized = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
    map_type = COLORMAP_LOOKUP.get(colormap_name, cv2.COLORMAP_PLASMA)
    colored = cv2.applyColorMap(normalized, map_type)

    # C#: alpha blend
    result = cv2.addWeighted(colored, opacity, bgr, 1.0 - opacity, 0.0)

    # C#: preserve black pixels from original
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    value_channel = hsv[:, :, 2]
    _, black_mask = cv2.threshold(value_channel, 0, 255, cv2.THRESH_BINARY_INV)

    # Keep original black areas, use blended result elsewhere
    original_black = cv2.bitwise_and(bgr, bgr, mask=black_mask)
    inverted_mask = cv2.bitwise_not(black_mask)
    result_non_black = cv2.bitwise_and(result, result, mask=inverted_mask)
    result = cv2.add(original_black, result_non_black)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Volume-level integration: apply PooyanPacs filters to a whole VTK volume
# ═══════════════════════════════════════════════════════════════════════════

def apply_pooyan_opencv_to_volume_int16(
    volume: np.ndarray,
    params: PooyanFilterParams = DEFAULT_PARAMS,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
) -> np.ndarray:
    """
    Apply PooyanPacs OpenCV filter pipeline to a 3D int16 DICOM volume.

    This is the **primary integration function** for the ITK pipeline.
    It processes the volume slice-by-slice (matching PooyanPacs 2D approach):

    For each slice:
        1. Apply Window/Level to normalise int16 → uint8 [0,255]
        2. Run ``pooyan_filter_center()`` (GaussianBlur + AddWeighted unsharp)
        3. Map filtered uint8 back to int16 range

    Parameters
    ----------
    volume : np.ndarray
        3D array with shape (Z, Y, X), dtype typically int16.
    params : PooyanFilterParams
        Filter parameters.
    window_center, window_width : float, optional
        DICOM window/level.  If not provided, uses per-slice min/max.

    Returns
    -------
    np.ndarray
        Filtered 3D volume, same shape and dtype as input.
    """
    if not params.enabled:
        return volume

    orig_dtype = volume.dtype
    nz = volume.shape[0]
    out = np.empty_like(volume)

    for z in range(nz):
        sl = volume[z]
        filtered_u8 = _filter_slice_int16_to_u8(sl, params, window_center, window_width)
        out[z] = _map_u8_back_to_original(
            filtered_u8,
            sl,
            orig_dtype,
            window_center=window_center,
            window_width=window_width,
        )

    return out


def apply_pooyan_opencv_to_slice_int16(
    slice_2d: np.ndarray,
    params: PooyanFilterParams = DEFAULT_PARAMS,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
) -> np.ndarray:
    """
    Apply PooyanPacs OpenCV filter pipeline to a single 2D int16 slice.

    Convenience wrapper for per-slice filtering (e.g., lazy backend).

    Parameters
    ----------
    slice_2d : np.ndarray
        2D array (Y, X), typically int16.
    params : PooyanFilterParams
        Filter parameters.

    Returns
    -------
    np.ndarray
        Filtered slice, same shape and dtype as input.
    """
    if not params.enabled:
        return slice_2d

    orig_dtype = slice_2d.dtype
    filtered_u8 = _filter_slice_int16_to_u8(slice_2d, params, window_center, window_width)
    return _map_u8_back_to_original(
        filtered_u8,
        slice_2d,
        orig_dtype,
        window_center=window_center,
        window_width=window_width,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════

def _filter_slice_int16_to_u8(
    sl: np.ndarray,
    params: PooyanFilterParams,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
) -> np.ndarray:
    """
    Window-level a single int16 slice to uint8, apply PooyanPacs filter.

    Returns the filtered uint8 image.
    """
    # Window/Level → uint8
    ww, wc = normalize_window_level(
        window_width,
        window_center,
        treat_legacy_placeholder_as_missing=True,
    )
    if ww is not None and wc is not None:
        u8 = window_to_uint8(sl.astype(np.float32), ww, wc)
    else:
        # Auto-window: per-slice min/max (matches PooyanPacs default-window behavior)
        mn, mx = float(sl.min()), float(sl.max())
        if mx > mn:
            u8 = ((sl.astype(np.float32) - mn) / (mx - mn) * 255.0).astype(np.uint8)
        else:
            u8 = np.zeros_like(sl, dtype=np.uint8)

    # PooyanPacs FilterCenter (the core filter)
    # preserve_dimensions=True because we don't want to change volume geometry
    safe_params = PooyanFilterParams(
        sigma_x=params.sigma_x,
        alpha=params.alpha,
        beta=params.beta,
        enabled=params.enabled,
        small_threshold=params.small_threshold,
        preserve_dimensions=True,  # ALWAYS preserve for volume integration
        invert=params.invert,
    )
    filtered = pooyan_filter_center(u8, safe_params)

    # Inversion (if requested)
    if params.invert:
        filtered = pooyan_invert(filtered)

    return filtered


def _map_u8_back_to_original(
    filtered_u8: np.ndarray,
    original_slice: np.ndarray,
    orig_dtype: np.dtype,
    *,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
) -> np.ndarray:
    """
    Map a filtered uint8 image back to the original intensity domain.

    If a DICOM window/level is known, map [0,255] back into that exact
    window interval. This preserves the semantics of later VTK windowing
    much better than stretching the filtered result across the full raw
    slice min/max range.

    Without a known window/level, fall back to [original_min, original_max].
    """
    if orig_dtype == np.uint8:
        return filtered_u8

    # Resize back if filter changed dimensions (small-image path)
    oh, ow = original_slice.shape[:2]
    fh, fw = filtered_u8.shape[:2]
    if (fh, fw) != (oh, ow):
        if CV2_AVAILABLE:
            filtered_u8 = cv2.resize(filtered_u8, (ow, oh))
        else:
            filtered_u8 = filtered_u8[:oh, :ow] if fh >= oh and fw >= ow else filtered_u8

    ww, wc = normalize_window_level(
        window_width,
        window_center,
        treat_legacy_placeholder_as_missing=True,
    )
    if ww is not None and wc is not None:
        mn = float(wc) - 0.5 - (float(ww) - 1.0) / 2.0
        mx = float(wc) - 0.5 + (float(ww) - 1.0) / 2.0
    else:
        mn = float(original_slice.min())
        mx = float(original_slice.max())
    if mx > mn:
        # Linear map: uint8 [0,255] → [min, max] of original
        result = (filtered_u8.astype(np.float32) / 255.0 * (mx - mn) + mn)
        if np.issubdtype(orig_dtype, np.integer):
            info = np.iinfo(orig_dtype)
            result = np.clip(result, info.min, info.max)
        return result.astype(orig_dtype)
    else:
        return np.full_like(original_slice, mn, dtype=orig_dtype)


# ═══════════════════════════════════════════════════════════════════════════
# Standalone / in-place volume filter for ITK-pipeline integration
# ═══════════════════════════════════════════════════════════════════════════

def apply_pooyan_opencv_to_sitk(
    itk_image,
    params: PooyanFilterParams = DEFAULT_PARAMS,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
):
    """
    Apply PooyanPacs OpenCV filter to a SimpleITK image (3D or 2D).

    This wraps :func:`apply_pooyan_opencv_to_volume_int16` for seamless
    integration at the same point where ``apply_filters()`` is called
    in ``image_io.py``.

    Parameters
    ----------
    itk_image : sitk.Image
        Input SimpleITK image (any pixel type — will be handled).
    params : PooyanFilterParams
        Filter parameters.
    window_center, window_width : float, optional
        DICOM Window/Level for normalisation.

    Returns
    -------
    sitk.Image
        Filtered image with same geometry/metadata.
    """
    import SimpleITK as sitk

    if not params.enabled:
        return itk_image

    arr = sitk.GetArrayFromImage(itk_image)  # shape (Z, Y, X) or (Y, X)

    if arr.ndim == 3:
        filtered = apply_pooyan_opencv_to_volume_int16(
            arr, params, window_center, window_width,
        )
    elif arr.ndim == 2:
        filtered = apply_pooyan_opencv_to_slice_int16(
            arr, params, window_center, window_width,
        )
    else:
        return itk_image

    result = sitk.GetImageFromArray(filtered)
    result.CopyInformation(itk_image)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Configuration loading (matches C# gRPC ParseDisplayRenderOptions)
# ═══════════════════════════════════════════════════════════════════════════

def load_pooyan_filter_params_from_json(json_path: Optional[str] = None) -> PooyanFilterParams:
    """
    Load PooyanPacs filter parameters from a JSON config file.

    Matches C# ``ParseDisplayRenderOptions`` key names:
    ``sigma_x`` / ``sigmaX`` / ``sigma``, ``alpha``, ``beta``,
    ``enabled``, ``invert``, ``preserve_dimensions``.

    Falls back to defaults if file doesn't exist or parsing fails.
    """
    import json
    from pathlib import Path

    if json_path is None:
        try:
            from PacsClient.utils.config import SOCKET_CONFIG_PATH
            json_path = str(Path(SOCKET_CONFIG_PATH) / "pooyan_opencv_filter.json")
        except Exception:
            json_path = "config/pooyan_opencv_filter.json"

    try:
        p = Path(json_path)
        if not p.exists():
            return DEFAULT_PARAMS
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        sigma = d.get("sigma_x", d.get("sigmaX", d.get("sigma", 1.0)))
        return PooyanFilterParams(
            sigma_x=float(sigma),
            alpha=float(d.get("alpha", 1.4)),
            beta=float(d.get("beta", -0.5)),
            enabled=bool(d.get("enabled", True)),
            small_threshold=int(d.get("small_threshold", 280)),
            preserve_dimensions=bool(d.get("preserve_dimensions", False)),
            invert=bool(d.get("invert", False)),
        )
    except Exception as e:
        logger.warning("Failed to load PooyanPacs filter config from %s: %s", json_path, e)
        return DEFAULT_PARAMS


# ═══════════════════════════════════════════════════════════════════════════
# Quick self-test
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== PooyanPacs OpenCV Filter Pipeline Self-Test ===\n")

    # Create synthetic test image (gradient + noise)
    np.random.seed(42)
    h, w = 512, 512
    gradient = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))
    noise = np.random.normal(0, 15, (h, w)).astype(np.float32)
    test_u8 = np.clip(gradient.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    # Test 1: Normal-size image with default params
    params = PooyanFilterParams()
    t0 = time.perf_counter()
    result = pooyan_filter_center(test_u8, params)
    dt = (time.perf_counter() - t0) * 1000
    print(f"1. Normal (512×512): in={test_u8.shape} out={result.shape} dt={dt:.1f}ms")
    assert result.shape == test_u8.shape, f"Shape mismatch: {result.shape}"
    assert result.dtype == np.uint8

    # Test 2: Small image (triggers dilate + resize)
    small = test_u8[:200, :200]
    params_normal = PooyanFilterParams(preserve_dimensions=False)
    result_small = pooyan_filter_center(small, params_normal)
    print(f"2. Small (200×200, no preserve): in={small.shape} out={result_small.shape}")
    assert result_small.shape == (400, 400), f"Expected (400,400), got {result_small.shape}"

    # Test 3: Small image with preserve_dimensions
    params_preserve = PooyanFilterParams(preserve_dimensions=True)
    result_preserved = pooyan_filter_center(small, params_preserve)
    print(f"3. Small (200×200, preserve): in={small.shape} out={result_preserved.shape}")
    assert result_preserved.shape == small.shape

    # Test 4: int16 volume
    vol_int16 = np.random.randint(-1024, 3000, (10, 256, 256), dtype=np.int16)
    t0 = time.perf_counter()
    vol_result = apply_pooyan_opencv_to_volume_int16(vol_int16, params)
    dt = (time.perf_counter() - t0) * 1000
    print(f"4. Volume int16 (10×256×256): dt={dt:.1f}ms dtype={vol_result.dtype}")
    assert vol_result.shape == vol_int16.shape
    assert vol_result.dtype == vol_int16.dtype

    # Test 5: Disabled filter passes through unchanged
    params_off = PooyanFilterParams(enabled=False)
    result_off = pooyan_filter_center(test_u8, params_off)
    assert np.array_equal(result_off, test_u8), "Disabled filter should pass through"
    print("5. Disabled: pass-through OK")

    # Test 6: Inversion
    inv = pooyan_invert(test_u8)
    assert np.array_equal(inv, 255 - test_u8), "Inversion mismatch"
    print("6. Inversion: OK")

    # Test 7: Determinism
    r1 = pooyan_filter_center(test_u8, params)
    r2 = pooyan_filter_center(test_u8, params)
    assert np.array_equal(r1, r2), "Non-deterministic output!"
    print("7. Determinism: OK")

    # Test 8: Fusion
    fused = pooyan_fusion(test_u8, "Plasma", 0.5)
    print(f"8. Fusion: in={test_u8.shape} out={fused.shape} dtype={fused.dtype}")
    assert fused.shape == (h, w, 3)

    print("\n=== All tests passed ===")
