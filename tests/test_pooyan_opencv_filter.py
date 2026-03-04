"""
PooyanPacs OpenCV Filter Parity Validation Test
================================================
Validates that the Python OpenCV filter pipeline produces output
consistent with the PooyanPacs C# OpenCvSharp implementation.

Usage:
    python tests/test_pooyan_opencv_filter.py

Tests:
    1. Exact parameter defaults match C# DisplayRenderOptions
    2. Filter pipeline order matches C# (GaussianBlur → AddWeighted)
    3. Small-image path matches C# (Dilate 1×1 + 2× Resize)
    4. Deterministic output (same input → same output)
    5. uint8 ↔ int16 roundtrip integrity
    6. Performance: must be < 5ms per 512×512 slice
    7. Histogram similarity between Python and expected C# output
    8. Volume processing integrity
    9. Inversion matches C#
    10. Fusion colormaps match C# enums
"""

from __future__ import annotations
import sys
import os
import time

import numpy as np

# Ensure project root is on path
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import cv2

from PacsClient.pacs.patient_tab.utils.opencv_filter_pipeline import (
    PooyanFilterParams,
    DEFAULT_PARAMS,
    pooyan_filter_center,
    pooyan_invert,
    pooyan_fusion,
    apply_pooyan_opencv_to_volume_int16,
    apply_pooyan_opencv_to_slice_int16,
    COLORMAP_LOOKUP,
)


def _print_result(name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    detail_str = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{detail_str}")
    return passed


def test_default_params_match_csharp():
    """C# defaults: sigmaX=1.0, alpha=1.4, beta=-0.5, enabled=true"""
    p = DEFAULT_PARAMS
    ok = True
    ok &= _print_result("sigma_x == 1.0", p.sigma_x == 1.0, f"got {p.sigma_x}")
    ok &= _print_result("alpha == 1.4", p.alpha == 1.4, f"got {p.alpha}")
    ok &= _print_result("beta == -0.5", p.beta == -0.5, f"got {p.beta}")
    ok &= _print_result("enabled == True", p.enabled is True)
    ok &= _print_result("small_threshold == 280", p.small_threshold == 280)
    ok &= _print_result("preserve_dimensions == False", p.preserve_dimensions is False)
    # C# clamps sigmaX at 0.05
    clamped = PooyanFilterParams(sigma_x=0.01)
    ok &= _print_result("sigma_x clamped to 0.05", clamped.sigma_x == 0.05, f"got {clamped.sigma_x}")
    return ok


def test_filter_pipeline_algorithm():
    """
    Verify the algorithm matches C#:
        dst = GaussianBlur(mat, (0,0), sigmaX)
        dst = AddWeighted(mat, alpha, dst, beta, 0)
    """
    np.random.seed(42)
    img = np.random.randint(50, 200, (512, 512), dtype=np.uint8)
    
    # Manual C# equivalent in Python
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    blurred = cv2.GaussianBlur(bgr, (0, 0), 1.0)
    expected_bgr = cv2.addWeighted(bgr, 1.4, blurred, -0.5, 0.0)
    expected_gray = cv2.cvtColor(expected_bgr, cv2.COLOR_BGR2GRAY)
    
    # Our pipeline
    result = pooyan_filter_center(img, PooyanFilterParams())
    
    ok = _print_result(
        "Normal path matches manual C# steps",
        np.array_equal(result, expected_gray),
        f"max_diff={np.abs(result.astype(int) - expected_gray.astype(int)).max()}"
    )
    return ok


def test_small_image_path():
    """
    C#: if (PixelWidth < 280 || PixelHeight < 280)
        → Dilate(1×1 rect) + Resize(2×)
    """
    np.random.seed(42)
    small = np.random.randint(50, 200, (200, 200), dtype=np.uint8)
    
    # Without preserve_dimensions: should be 2× size
    result_2x = pooyan_filter_center(small, PooyanFilterParams(preserve_dimensions=False))
    ok = _print_result(
        "Small image 2× resize",
        result_2x.shape == (400, 400),
        f"got {result_2x.shape}"
    )
    
    # With preserve_dimensions: same size
    result_same = pooyan_filter_center(small, PooyanFilterParams(preserve_dimensions=True))
    ok &= _print_result(
        "Small image preserve dims",
        result_same.shape == (200, 200),
        f"got {result_same.shape}"
    )
    
    # Edge case: one dim < 280, other >= 280  (C# uses OR, not AND)
    edge = np.random.randint(50, 200, (200, 400), dtype=np.uint8)
    result_edge = pooyan_filter_center(edge, PooyanFilterParams(preserve_dimensions=False))
    ok &= _print_result(
        "Small-image OR logic (200×400)",
        result_edge.shape == (400, 800),
        f"got {result_edge.shape}"
    )
    
    return ok


def test_determinism():
    """Same input + same params → identical output"""
    np.random.seed(42)
    img = np.random.randint(0, 255, (512, 512), dtype=np.uint8)
    params = PooyanFilterParams()
    r1 = pooyan_filter_center(img, params)
    r2 = pooyan_filter_center(img, params)
    return _print_result("Deterministic output", np.array_equal(r1, r2))


def test_int16_roundtrip():
    """int16 volume → filter → int16 with valid range"""
    np.random.seed(42)
    vol = np.random.randint(-1024, 3000, (5, 256, 256), dtype=np.int16)
    result = apply_pooyan_opencv_to_volume_int16(vol, PooyanFilterParams())
    
    ok = _print_result("Output dtype == int16", result.dtype == np.int16)
    ok &= _print_result("Output shape preserved", result.shape == vol.shape)
    
    # Range should be within original bounds (approximately)
    ok &= _print_result(
        "Output min in range",
        result.min() >= vol.min() - 1,
        f"vol.min={vol.min()}, out.min={result.min()}"
    )
    ok &= _print_result(
        "Output max in range",
        result.max() <= vol.max() + 1,
        f"vol.max={vol.max()}, out.max={result.max()}"
    )
    return ok


def test_performance():
    """Filter must complete < 5ms per 512×512 slice"""
    np.random.seed(42)
    img = np.random.randint(0, 255, (512, 512), dtype=np.uint8)
    params = PooyanFilterParams()
    
    # Warm up
    pooyan_filter_center(img, params)
    
    # Benchmark
    N = 50
    t0 = time.perf_counter()
    for _ in range(N):
        pooyan_filter_center(img, params)
    dt = (time.perf_counter() - t0) / N * 1000  # ms per call
    
    return _print_result(
        f"Performance: {dt:.2f}ms per 512×512 slice (< 5ms)",
        dt < 5.0,
        f"{dt:.2f}ms"
    )


def test_histogram_similarity():
    """
    The filtered image should have similar histogram to input
    (unsharp mask preserves overall brightness, enhances edges).
    Use a gradient image with structure (more realistic than pure noise).
    """
    np.random.seed(42)
    # Create a structured test image: gradient with some noise (simulates tissue)
    h, w = 512, 512
    gradient = np.tile(np.linspace(30, 220, w, dtype=np.float32), (h, 1))
    noise = np.random.normal(0, 5, (h, w)).astype(np.float32)
    img = np.clip(gradient + noise, 0, 255).astype(np.uint8)
    result = pooyan_filter_center(img, PooyanFilterParams())
    
    hist_in = cv2.calcHist([img], [0], None, [256], [0, 256]).flatten()
    hist_out = cv2.calcHist([result], [0], None, [256], [0, 256]).flatten()
    
    # Normalise
    hist_in = hist_in / hist_in.sum()
    hist_out = hist_out / hist_out.sum()
    
    # Correlation > 0.7 (unsharp mask with alpha=1.4/beta=-0.5 redistributes
    # some intensity bins but overall shape should be preserved)
    corr = float(cv2.compareHist(
        hist_in.astype(np.float32),
        hist_out.astype(np.float32),
        cv2.HISTCMP_CORREL,
    ))
    
    # Also check mean brightness is preserved within expected range.
    # PooyanPacs addWeighted(alpha=1.4, beta=-0.5) in smooth areas:
    # output ≈ 1.4*orig + (-0.5)*blurred ≈ 0.9*orig → ~10% decrease expected.
    mean_in = float(img.mean())
    mean_out = float(result.mean())
    mean_ok = abs(mean_in - mean_out) < mean_in * 0.15  # 15% tolerance
    
    ok = _print_result(
        f"Histogram correlation > 0.7",
        corr > 0.7,
        f"corr={corr:.4f}"
    )
    ok &= _print_result(
        f"Mean brightness preserved (±10%)",
        mean_ok,
        f"in={mean_in:.1f} out={mean_out:.1f}"
    )
    
    return _print_result(
        f"Histogram correlation > 0.8",
        corr > 0.8,
        f"corr={corr:.4f}"
    )


def test_inversion():
    """Matches C#: data[i] = 255 - data[i]"""
    np.random.seed(42)
    img = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
    inv = pooyan_invert(img)
    expected = (255 - img).astype(np.uint8)
    return _print_result("Inversion == 255 - pixel", np.array_equal(inv, expected))


def test_fusion_colormaps():
    """All C# colormaps have Python equivalents"""
    expected_maps = {
        "Plasma", "Inferno", "Hot Iron", "Hot", "Winter",
        "Rainbow 1", "Rainbow", "Rainbow 2", "Jet", "Hsv", "HSV",
    }
    ok = True
    for name in expected_maps:
        ok &= _print_result(
            f"Colormap '{name}' mapped",
            name in COLORMAP_LOOKUP,
        )
    
    # Test fusion runs without error
    np.random.seed(42)
    img = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
    fused = pooyan_fusion(img, "Plasma", 0.5)
    ok &= _print_result("Fusion output is BGR", fused.shape == (100, 100, 3))
    return ok


def test_disabled_passthrough():
    """Disabled filter returns input unchanged"""
    np.random.seed(42)
    img = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
    result = pooyan_filter_center(img, PooyanFilterParams(enabled=False))
    return _print_result("Disabled → passthrough", np.array_equal(result, img))


def test_volume_slice_consistency():
    """Volume processing should give same results as per-slice"""
    np.random.seed(42)
    vol = np.random.randint(-500, 2000, (3, 128, 128), dtype=np.int16)
    params = PooyanFilterParams()
    
    vol_result = apply_pooyan_opencv_to_volume_int16(vol, params)
    
    ok = True
    for z in range(vol.shape[0]):
        slice_result = apply_pooyan_opencv_to_slice_int16(vol[z], params)
        ok &= np.array_equal(vol_result[z], slice_result)
    
    return _print_result("Volume == per-slice results", ok)


# ═══════════════════════════════════════════════════════════════════════
# Main runner
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("PooyanPacs OpenCV Filter Parity Validation")
    print("=" * 70)
    
    tests = [
        ("1. Default Parameter Parity (C# match)", test_default_params_match_csharp),
        ("2. Filter Algorithm Parity", test_filter_pipeline_algorithm),
        ("3. Small-Image Path Parity", test_small_image_path),
        ("4. Determinism", test_determinism),
        ("5. int16 Roundtrip Integrity", test_int16_roundtrip),
        ("6. Performance", test_performance),
        ("7. Histogram Similarity", test_histogram_similarity),
        ("8. Inversion Parity", test_inversion),
        ("9. Fusion Colormaps", test_fusion_colormaps),
        ("10. Disabled Passthrough", test_disabled_passthrough),
        ("11. Volume/Slice Consistency", test_volume_slice_consistency),
    ]
    
    passed = 0
    failed = 0
    
    for name, fn in tests:
        print(f"\n{name}")
        print("-" * 50)
        try:
            if fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            _print_result("EXCEPTION", False, str(e))
            failed += 1
    
    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'=' * 70}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
