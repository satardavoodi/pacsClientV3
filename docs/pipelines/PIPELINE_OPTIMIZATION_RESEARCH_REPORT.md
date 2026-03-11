# AIPacs Pipeline Optimization Research Report
**Date:** 2026-02-26  
**Scope:** Filter alternatives, execution timing, rendering efficiency, pipeline architecture, code cleanup  
**Current Version:** v2.2.3.0.9

---

## Executive Summary

After deep analysis of the full DICOM→filter→VTK→render pipeline, **the largest gains come not from replacing filter libraries, but from eliminating redundant work, restructuring execution timing, and reducing unnecessary memory copies**. The current pipeline has significant inefficiencies at the integration layer (duplicate renders, wasted Cast operations, dead code, unconverged cache layers) that can yield 30-50% improvement without touching filter algorithms.

---

## Area 1: Filter Alternatives (MRI)

### Current MRI Filter Chain (4 stages)
| # | Filter | ITK Calls | Est. Time (PC B, 500×640×24) |
|---|--------|-----------|------------------------------|
| 1 | Noise reduction (`SmoothingRecursiveGaussian`) | 1 | ~0.8s |
| 2 | Multiscale sharpening (2-3 Gaussian passes + numpy) | 2-3 | ~1.5-2.5s |
| 3 | Laplacian sharpening (`LaplacianRecursiveGaussian` + numpy) | 1 | ~0.6s |
| 4 | Adaptive sharpening (2 Gaussians + numpy, skipped in mild_mode) | 0-2 | 0-1.2s |

**Total ITK Gaussian kernel calls per MR series: 4-7 (each is a full 3D C++ convolution)**

### Option A: Replace SimpleITK with VTK Filters

| SimpleITK Filter | VTK Equivalent | Quality Match | Performance |
|---|---|---|---|
| `SmoothingRecursiveGaussian` | `vtkImageGaussianSmooth` | **Approximate** — VTK uses discrete kernel (truncated), ITK uses IIR (infinite impulse response). Slight quality difference at low sigma. | VTK is ~10-20% slower for small kernels (discrete convolution vs IIR), but VTK is multi-threaded natively |
| `RecursiveGaussian` (per-axis) | `vtkImageGaussianSmooth` with `SetDimensionality(2)` | **Approximate** — same discrete vs IIR difference | Similar |
| `GradientMagnitudeRecursiveGaussian` | `vtkImageGradientMagnitude` + `vtkImageGaussianSmooth` | **Two-step pipeline** vs one-step ITK. Less elegant, same result | Slightly slower due to two-pass |
| `LaplacianRecursiveGaussian` | `vtkImageLaplacian` | **Different algorithm** — VTK uses finite differences, ITK uses Gaussian-smoothed Laplacian (LoG). Quality difference noticeable at low sigma | VTK is faster but lower quality |

**Verdict: NOT RECOMMENDED**
- VTK discrete Gaussian ≠ ITK recursive Gaussian mathematically
- VTK's `vtkImageGaussianSmooth` sigma is in **pixel units** (not mm) — requires manual conversion per-spacing
- All VTK filter calls hold the Python GIL during `Update()` — **worse** than SimpleITK which releases GIL during C++ computation
- Would require adding sitk→vtk conversion BEFORE filters (currently filters run in ITK domain, then convert once)
- No GPU acceleration in standard VTK image filters (they're CPU threaded only)
- Risk: changing filter behavior may alter diagnostic image quality

### Option B: Replace SimpleITK with scipy.ndimage (numpy-native)

| SimpleITK Filter | scipy.ndimage Equivalent | Quality Match | Performance |
|---|---|---|---|
| `SmoothingRecursiveGaussian` | `scipy.ndimage.gaussian_filter(sigma=...)` | **Close** — scipy uses truncated Gaussian (order=0). For sigma≤1.0, nearly identical. | scipy is single-threaded (no GIL release) — **2-3× slower** than ITK for 3D volumes |
| `GradientMagnitudeRecursiveGaussian` | `scipy.ndimage.gaussian_gradient_magnitude(sigma=...)` | **Close** | Single-threaded, slower |
| `LaplacianRecursiveGaussian` | `scipy.ndimage.gaussian_laplace(sigma=...)` | **Good match** — same LoG approach | Single-threaded, slower |

**Verdict: NOT RECOMMENDED**
- scipy.ndimage is **single-threaded** — would double filter time vs ITK's 2-thread mode
- Adds a new dependency (scipy ~150MB) that's not currently in requirements.txt
- No advantage over ITK for 3D medical volumes

### Option C: Keep SimpleITK but Optimize Usage (RECOMMENDED)

**Specific optimizations with same filter output:**

1. **Eliminate intermediate Cast operations** — Currently each filter function does `Cast(input, float32)` at entry and `Cast(result, orig_type)` at exit. For 4 chained MR filters, that's **8 unnecessary Cast calls** (4 to float32, 4 back to int16). Fix: Cast to float32 once in `apply_filters()`, run all 4 filters in float32, cast back once at the end. **Estimated saving: 100-300ms per MR series.**

2. **Merge multiscale + laplacian into single pass** — Both compute `SmoothingRecursiveGaussian` at similar sigmas. The multiscale pass at sigma=0.5 and the laplacian pass at sigma=0.5 could share the blurred result. **Estimated saving: 1 full Gaussian pass (~0.5-0.8s).**

3. **Single-pass unsharp-like formulation** — The entire 4-filter chain (smooth → multiscale sharpen → laplacian sharpen → adaptive sharpen) can be reformulated as: `result = original + Σ(weight_i × (original - Gaussian_i(original)))` with edge-dependent weights. This reduces to N Gaussian passes + numpy arithmetic, eliminating redundant intermediate results. Currently the chain does: (a) blur input, (b) compute sharpening details from (a), (c) blur result of b, (d) compute more sharpening from (c). Steps c and d work on already-sharpened data — the Gaussians are filtering artifacts from prior sharpening.

4. **Reduce MR filter count** — `apply_laplacian_sharpening(alpha=0.12)` and `apply_adaptive_sharpening(base_amount=0.12)` have very similar effect at these low alpha values. Testing with only one of them (adaptive, which is edge-aware) may produce equivalent visual quality. **Potential saving: eliminate 1 filter = ~0.6s.**

---

## Area 2: Alternative Execution Timing

### Current Timing: Filters at Load Time (inside `load_single_series_by_number`)
```
DICOM Read → apply_filters() → convert_itk2vtk() → yield vtk_data
```
Both warmup (background) and interactive (user-click) paths run the identical pipeline.

### Option 2A: Filter at Download Time

| Aspect | Assessment |
|---|---|
| When | As each series finishes downloading |
| Pro | All filtering done before user ever clicks; instant series switching |
| Con | **Download is already the bottleneck.** Adding 3-7s filter time per series would slow download completion by 30-50%. User sees slower progress bar |
| Con | Requires storing FILTERED data to disk (doubles disk usage or requires separate filtered cache) |
| Con | If filter settings change, all pre-filtered data must be recomputed |
| Risk | HIGH — this was essentially what Mode B tried to do and caused severe problems |

**Verdict: NOT RECOMMENDED** — Filtering during download competes for CPU with the download network I/O and disk writes.

### Option 2B: Filter at Save-to-Disk Time (after download, before user access)

| Aspect | Assessment |
|---|---|
| When | After download completes, as a background job |
| Pro | Download not slowed; filtered data ready when user clicks |
| Con | Time gap between download complete and filter complete = user may click before ready |
| Con | Disk cache grows: must store both raw (for re-filter) and filtered versions |
| Con | 3D filters need the FULL volume — can't do partial/incremental |
| Concern | This is exactly what ZetaBoost warmup already does, just at a different trigger point |

**Verdict: PARTIALLY APPLICABLE** — This is essentially the current warmup flow but triggered earlier. The v2.2.3.0.9 "download warmup" already implements this for small completed series.

### Option 2C: Filter at Drag-and-Drop Time (when user drops series into layout)

| Aspect | Assessment |
|---|---|
| When | User explicitly places a series into a viewer slot |
| Pro | Only filters series the user actually wants to view |
| Con | User experiences a delay (3-7s) between drop and display |
| Con | This is exactly the current interactive load path |

**Verdict: ALREADY THE CURRENT BEHAVIOR** — This is what happens on cache-miss today.

### Option 2D: Split Filtering — Light Filter Now, Full Filter Later (RECOMMENDED)

| Aspect | Assessment |
|---|---|
| When | Phase 1: Noise reduction only at load time (~0.8s). Phase 2: Sharpening in background after display |
| Pro | User sees clean (denoised) image in <1s, then sharpened version auto-updates |
| Pro | Background sharpening can run at IDLE priority with generous yields |
| Con | Brief visual "pop" when sharpening applies (image subtly changes) |
| Con | Requires marking the cached volume as "partially filtered" and replacing it |
| Complexity | MEDIUM — need a two-phase cache state |

**Estimated impact: Reduce perceived load time from 3-7s to ~1s for MR series.**

### Option 2E: Cache Filtered Volumes to Disk (npz) and Skip Re-filtering

| Aspect | Assessment |
|---|---|
| When | First load filters + saves to disk; subsequent loads read pre-filtered from disk |
| Pro | Second and all future loads of same series skip filters entirely |
| Con | ZetaBoost L2 disk cache already does this — but only for series that went through warmup |
| Concern | Interactive-loaded series currently bypass disk cache write |

**Verdict: PARTIALLY IMPLEMENTED** — The ZetaBoost disk cache already persists filtered+converted VTK data. The gap is that **interactively loaded series don't always get written to disk cache**. Fixing this would make re-opening a study instant.

---

## Area 3: Rendering/Display Efficiency

### Why 400-500MB Series Causes Slowdown

A 512×512×400 int16 CT volume = **~200MB raw**. The memory journey:

| Step | Allocation | Cumulative Peak |
|---|---|---|
| 1. `sitk.ImageSeriesReader` → ITK image | 200MB | 200MB |
| 2. `apply_filters()` (float32 temporaries) | +800MB transient (4 float32 copies of volume during filter chain) | **~1000MB peak** |
| 3. `sitk.GetArrayFromImage()` → numpy | 200MB (ITK freed) | 400MB |
| 4. Y-flip `.copy()` → contiguous array | 200MB (original freed) | 400MB |
| 5. `numpy_to_vtk(deep=False)` → VTK wraps numpy | 0MB (shared pointer) | 200MB |
| 6. `display_upsample_xy()` (CT ≤160 slices, 2× factor) | +800MB | **1000MB peak** |
| 7. `vtkImageReslice.Update()` | +200MB output buffer | 1200MB |
| 8. ZetaBoost cache stores VTK volume | 200MB (persisted) | 200MB steady-state |

**Key finding: Peak memory during CT load with upsampling can reach ~1.2GB for a single series.**

### Rendering Bottleneck #1: Triple Render Per Series Switch

`reset_image_viewer()` triggers:
1. `vtkImageReslice.Update()` — full 3D reslice computation
2. `UpdateDisplayExtent()` — pipeline metadata update
3. `image_render_window.Render()` — GPU submission

Then the caller (`switch_series()`) may additionally call `apply_default_window_level()` → `color_mapper.Update()`, and check zoom → another `Render()`.

**Net: 2-4 VTK pipeline updates + 1-2 Render calls per series switch.**

### Rendering Bottleneck #2: Double Render Per Scroll

Every `set_slice()` triggers:
1. `SetSlice(n)` + `apply_default_window_level()` → `color_mapper.Update()` + `update_corners_actors()` + `Render()`
2. Zoom-protection check → potentially second `Render()`

**`update_corners_actors()` is called TWICE per scroll event.**

### Rendering Bottleneck #3: Display Upsampling (CT)

For CT volumes ≤160 slices, `display_upsample_xy()` applies `vtkImageResample` with cubic interpolation to double XY resolution. This:
- Creates a volume 4× larger in XY (512→1024 per axis)
- Takes 200-500ms on CPU
- The `_preprocess_cache` (max 8 entries) bypasses this for repeated access, but **skips caching for series ≥160 slices** → every switch recomputes

### Rendering Bottleneck #4: VTK Holds GIL

Unlike SimpleITK (which releases GIL during C++ execution), VTK Python wrapping **holds the GIL** during `Update()` and `Render()` calls. This means:
- `vtkImageReslice.Update()` on a 200MB volume = 100-300ms GIL hold
- `vtkImageResample.Update()` (upsampling) = 200-500ms GIL hold  
- `Render()` = 60-80ms GIL hold (PC B software rendering)
- **Total GIL hold per series switch: 360-880ms** during which no Python thread can execute

### Recommended Rendering Fixes

| Fix | Impact | Complexity |
|---|---|---|
| **R1: Eliminate double `update_corners_actors()` per scroll** | Save 1-3ms per scroll | LOW |
| **R2: Guard `color_mapper.Update()` with value-change check** | Save 1-2ms per scroll when WL unchanged | LOW |
| **R3: Remove zoom-protection second Render in `set_slice()`** | Save 60-80ms when zoom unchanged | LOW |
| **R4: Lazy `ImageReslice.Update()` — defer from `__init__` to first read** | Save 100-300ms on series switch | MEDIUM |
| **R5: Size-aware preprocess cache eviction** | Prevent re-upsampling of same CT series | MEDIUM |
| **R6: Merge `reset_image_viewer()` pipeline updates into single flush** | Reduce 3-4 pipeline updates to 1 | MEDIUM |
| **R7: Skip CT display upsampling for large series (>160 slices already skipped, but threshold can be tuned)** | Save 200-500ms for medium CT series | LOW |

---

## Area 4: Pipeline Architecture Review

### Current End-to-End Pipeline

```
[DICOM Disk] → sitk.ImageSeriesReader → sitk.Image (ITK domain)
         ↓
    apply_filters() — 4-7 ITK Gaussian kernels in float32
         ↓
    sitk.GetArrayFromImage() → numpy array (COPY #1)
         ↓
    arr[:, ::-1, :] → Y-flip view → .copy() → contiguous array (COPY #2)
         ↓
    numpy_to_vtk(deep=False) → vtkImageData (zero-copy wrap)
         ↓
    [Optional] display_upsample_xy() → vtkImageResample (COPY #3, CT ≤160 slices)
         ↓
    vtkImageReslice → 3D re-orientation (COPY #4)
         ↓
    vtkImageMapToWindowLevelColors → W/L mapping
         ↓
    vtkImageActor → GPU texture → Screen
```

**Total array copies: 2 mandatory + 2 optional = up to 4 full-volume copies per series load.**

### Architecture Problem #1: Two Separate Domains

The pipeline spans two libraries (SimpleITK and VTK) with a costly bridge:
- Filters run in **ITK domain** (sitk.Image)
- Rendering runs in **VTK domain** (vtkImageData)
- The bridge (`convert_itk2vtk`) requires: ITK→numpy (copy) + Y-flip (view→copy) + numpy→VTK (zero-copy)

The Y-flip is needed because VTK's coordinate convention differs from ITK's. This is a **permanent architectural cost** that adds one full-volume copy.

### Architecture Problem #2: No Streaming / Slice-Level Processing

All filters operate on the **full 3D volume** at once. For a 400-slice series, the filter must process all 400 slices even though only 1 is initially displayed. Alternative approaches:

| Approach | Description | Feasibility |
|---|---|---|
| **Slice-at-a-time filtering** | Filter only the current slice + neighbors | NOT FEASIBLE — Gaussian smoothing in Z requires the full Z extent |
| **Block filtering** | Filter chunks of 50 slices at a time | PARTIALLY FEASIBLE — works for XY-only filtering (noise reduction), not for Z-dependent sharpening |
| **Display-first, filter-later** | Show raw slice immediately, filter in background, update when ready | FEASIBLE — requires two-phase cache |
| **Pre-filter during download** | Filter as download progresses | NOT FEASIBLE — 3D filters need complete volume |

### Architecture Problem #3: Dual Cache Systems

The system has **5 separate cache layers** that don't share data efficiently:

1. `_hot_series_cache` (ViewerController) — 3 entries, may be preview-only
2. `_series_cache` (ViewerController) — references into `lst_thumbnails_data`
3. `_series_number_to_index` (ViewerController) — index lookup only
4. **ZetaBoost L1** (RAM) — 8-40 entries, filtered+converted VTK volumes
5. **ZetaBoost L2** (disk) — up to 600 entries, compressed npz

Cache lookup walk in `_get_series_by_number_fast()` probes **4 layers sequentially**: hot → main → index → ZetaBoost. A cache miss at all levels triggers a full DICOM+filter+convert pipeline.

**Recommended architecture changes:**

| Change | Impact | Complexity |
|---|---|---|
| **A1: Single cast-once pattern in filter chain** | Eliminate 6 unnecessary sitk.Cast calls | LOW |
| **A2: Write interactive loads to disk cache** | Ensure reopening a study is instant | MEDIUM |
| **A3: Two-phase display (raw → filtered)** | Reduce perceived load from 3-7s to <1s | HIGH |
| **A4: Consolidate thumbnail-level caches with ZetaBoost** | Simplify lookup, avoid stale references | HIGH |
| **A5: Eliminate Y-flip copy via numpy `ascontiguousarray` with negative stride** | Not possible — the copy is inherent. But could flip in VTK via `vtkImageFlip` on the GPU side | MEDIUM |

---

## Area 5: Code Cleanup and Redundancy Audit

### 5.1 Dead Code (functions defined but never called from main pipeline)

| Function | File | Lines | Status |
|---|---|---|---|
| `edge_smooth_ultrafast()` | image_filters.py:118 | ~110 lines | Not called from `apply_filters()` — only from batch dispatch functions |
| `smoothing()` | image_filters.py:288 | ~30 lines | Not called from `apply_filters()` |
| `apply_gaussian_sharpening()` | image_filters.py:329 | ~55 lines | Not called from `apply_filters()` |
| `apply_unsharp_mask()` | image_filters.py:232 | ~50 lines | Only called from `smoothing()` which is itself dead |
| `enhance_resolution()` | image_filters.py:840 | ~30 lines | Only from dispatch |
| `enhance_local_contrast()` | image_filters.py:870 | ~40 lines | Only from dispatch |
| `convert_itk2vtk_fast_first()` | utils.py:277 | ~100 lines | **Never called** — dead duplicate of `convert_itk2vtk()` |
| `get_itk_image_fast_first()` | image_io.py:341 | ~25 lines | Appears unused — main pipeline uses `get_itk_image()` |
| `switch_series_backup()` | vtk_widget.py:876 | ~60 lines | Superseded by `switch_series()` |
| `flip_image_y()` | viewer_2d.py:60 | ~25 lines | Never called (commented out) |
| `ImageReslice.apply_orientation()` | viewer_2d.py:55 | Empty method (`pass`) |
| `grow_vtk_inplace()` (module-level) | vtk_widget.py:33 | ~15 lines | Superseded by class method |

**Total dead code: ~540 lines across 5 files**

### 5.2 Redundant Processing

| Issue | Location | Impact |
|---|---|---|
| **8 unnecessary `sitk.Cast()` calls in MR filter chain** | image_filters.py (each filter function) | ~100-300ms wasted per MR load |
| **Double `update_corners_actors()` per scroll** | viewer_2d.py in `set_slice()` + `set_window_level()` | 1-3ms per scroll event |
| **Potential double `Render()` per scroll (zoom protection)** | vtk_widget.py `set_slice()` | 60-80ms per scroll if triggered |
| **`ImageReslice.Update()` in `__init__` + again in `reset_image_viewer()`** | viewer_2d.py | 100-300ms wasted on series switch |
| **Triple pipeline update in `reset_image_viewer()`** | viewer_2d.py | Reslice.Update + UpdateDisplayExtent + Render = 3 flushes |
| **Inconsistent `_update_overlay_extent()`** | viewer_2d.py vs vtk_widget.py — viewer version does full pipeline flush, widget doesn't | Unpredictable timing |

### 5.3 Entangled / "Dirty" Code Paths

| Issue | Location | Description |
|---|---|---|
| **5 cache layers with overlapping scope** | patient_widget_viewer_controller.py | `_hot_series_cache`, `_series_cache`, `_series_number_to_index`, ZetaBoost L1, ZetaBoost L2 — lookup must probe all 5 |
| **Both VTKWidget and ImageViewer2D have `_do_render()` and `_schedule_render()`** | vtk_widget.py, viewer_2d.py | Viewer's `_schedule_render` is effectively dead but still in code; risk of double-scheduling |
| **`_series_metadata_cache` never cleared on study close** | image_io.py | Unbounded growth during long sessions; max 100 entries with FIFO eviction but no lifecycle management |
| **`_global_preprocess_cache` has no size-awareness** | viewer_2d.py | 8 entries regardless of size; could hold 800MB+ of upsampled volumes |
| **~200+ `print()` statements vs ~85 `logger.*()` calls** | Across all pipeline files | Inconsistent logging; `print()` is synchronous and can block on Windows codepage issues |

### 5.4 Specific Code Issues

1. **`apply_filters()` — Laplacian and Adaptive blocks are indented inside the MR multiscale `if` block** (image_filters.py:773-795). If `multiscale_sharpening` is disabled, laplacian and adaptive are **also skipped** because they're inside the same `if modality == "MR":` block but further indented under multiline_sharpening's `if` clause. This appears intentional but is fragile — if anyone restructures the block, the nesting breaks.

2. **`load_filter_settings_from_json()` has 200+ lines of duplicate DEFAULT_FILTERS** (image_filters.py:1000-1240). The defaults are defined both inline in `apply_filters()` AND in the fallback return of `load_filter_settings_from_json()` AND in the exception handler. Three copies of the same defaults.

3. **`convert_itk2vtk()` prints a diagnostic line on every call**: `print(f"[PIPELINE ITK→VTK] size=... spacing=...")` — this fires on every series load including warmup, producing noise in production logs.

---

## Recommended Implementation Plan (Priority-Ordered)

### Phase 1: Quick Wins (Low Risk, High Impact) — v2.2.3.1.0

| # | Change | Est. Saving | Risk |
|---|---|---|---|
| 1 | **Cast-once pattern**: Cast to float32 at start of `apply_filters()`, cast back once at end | 100-300ms per MR | LOW |
| 2 | **Remove double `update_corners_actors()` per scroll** | 1-3ms per scroll | LOW |
| 3 | **Guard `color_mapper.Update()` with value-change check** | 1-2ms per scroll | LOW |
| 4 | **Remove zoom-protection second Render in `set_slice()`** | 60-80ms per scroll when zoom unchanged | LOW |

### Phase 2: Dead Code + Cleanup — v2.2.3.1.1

| # | Change | Lines Saved | Risk |
|---|---|---|---|
| 5 | Delete `convert_itk2vtk_fast_first()`, `get_itk_image_fast_first()`, `switch_series_backup()`, `flip_image_y()`, `grow_vtk_inplace()` (module-level) | ~225 lines | LOW |
| 6 | Consolidate 3 copies of DEFAULT_FILTERS into single source | ~400 lines | LOW |
| 7 | Replace pipeline `print()` with `logger.debug()` in hot paths | Consistency | LOW |

### Phase 3: Rendering Pipeline Optimization — v2.2.3.1.2

| # | Change | Est. Saving | Risk |
|---|---|---|---|
| 8 | **Lazy `ImageReslice.Update()`** — defer from `__init__`  | 100-300ms per switch | MEDIUM |
| 9 | **Merge `reset_image_viewer()` triple pipeline update into single flush** | 100-200ms per switch | MEDIUM |
| 10 | **Size-aware preprocess cache eviction** | Prevent re-upsampling | MEDIUM |

### Phase 4: Architecture Improvements — v2.2.3.2.x

| # | Change | Est. Impact | Risk |
|---|---|---|---|
| 11 | **Two-phase display** (noise-only → full sharpen) | Perceived load: 3-7s → ~1s | HIGH |
| 12 | **Write interactive loads to disk cache** | Reopening study = instant | MEDIUM |
| 13 | **Merge shared Gaussian passes** (multiscale sigma=0.5 + laplacian sigma=0.5) | Save 1 Gaussian pass (~0.5-0.8s) | MEDIUM |
| 14 | **Evaluate eliminating laplacian sharpening** (similar effect as adaptive at alpha=0.12) | Save 1 filter stage (~0.6s) | MEDIUM — needs visual comparison |

### Phase 5: Major Architectural Changes (Future)

| # | Change | Description | Risk |
|---|---|---|---|
| 15 | **Consolidate 5 cache layers into unified cache** | Single lookup instead of probing 4-5 layers | HIGH |
| 16 | **Single-pass filter reformulation** | Rewrite 4 filters as `result = orig + Σ(w_i × details_i)` | HIGH — needs radiologist validation |
| 17 | **Stream-based filtering for XY-only stages** | Process in slabs of 50 slices for memory efficiency | HIGH |

---

## Key Constraints to Preserve

1. **Do NOT re-sort metadata['instances'] by IPP** — VTK slices are in instance_number order
2. **Do NOT change filter output quality** without radiologist comparison
3. **The stored DirectionMatrix has row 1 negated** — Y-flip compensation
4. **Mode B caching must remain controlled** — v2.2.3.0.9 limits apply
5. **ITK thread count must be restored** after filter pipeline
6. **`numpy_to_vtk(deep=False)`** requires the numpy backing store to be pinned

---

## Summary of Expected Gains

| Area | Current Cost | After Phase 1-3 | Improvement |
|---|---|---|---|
| MR filter chain | 3-7s | 2-5s | ~30% faster |
| Series switch (cache hit) | 200-600ms | 80-200ms | ~60% faster |
| Scroll rendering | 80-160ms (PC B) | 40-100ms | ~40% faster |
| Peak memory (CT) | ~1.2GB | ~0.8GB (with lazy reslice) | ~33% less |
| Dead code | ~540 lines | 0 | Cleaner codebase |
| Perceived MR load (Phase 4) | 3-7s | <1s | ~80% improvement |
