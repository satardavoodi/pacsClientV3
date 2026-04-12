# AIPacs Viewer Backends Reference

**Version:** v2.2.9.2 | **Updated:** 2026-04-09

## Overview

AIPacs has **two** distinct viewer backends for displaying DICOM images.
The backend is selected per-series at load time by `resolve_viewer_backend()`.

| Backend | ID Constant | Technology | Primary Use |
|---------|-------------|------------|-------------|
| **Advanced** | `vtk_simpleitk` | VTK + SimpleITK + OpenGL | Full 3D volume, filters, measurements, MPR |
| **Fast** | `pydicom_2d` / `pydicom_qt` | pydicom + numpy + Qt QPainter | Lightweight browsing, download-time viewing |

---

## 1. Advanced Backend (`vtk_simpleitk`)

### Pipeline

```
DICOM files on disk
  │
  ▼
┌──────────────────────────────────────────────────┐
│ A1. DICOM I/O (SimpleITK)                         │
│     sitk.ImageSeriesReader reads all slices into  │
│     a single 3D ITK volume (ZYX, LPS directions) │
│     Timing: 30–400ms depending on slice count     │
└────────────────┬─────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│ A2. ITK Filters (image_filters.py)                │
│     Gaussian noise reduction, contrast enhance,   │
│     sharpening — modality-dependent chain          │
│     Timing: 150ms–3s                               │
└────────────────┬─────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│ A3. ITK→VTK Conversion (convert_itk2vtk)          │
│     ITK array → numpy → vtkImageData              │
│     ⚠  Y-axis is FLIPPED (row 1 of direction      │
│        matrix is NEGATED in field data)            │
│     Timing: 2–45ms                                 │
└────────────────┬─────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│ A4. vtkImageReslice (pass-through by default)     │
│     Applies direction-matrix transform to align   │
│     the volume for display.  Normally cubic       │
│     interpolation; produces a corrected volume    │
│     Timing: <1ms (identity case)                   │
└────────────────┬─────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│ A5. ImageViewer2D (viewer_2d.py)                   │
│     vtkImageViewer2 wrapper with:                  │
│     ├─ SetSlice(index) — select Z slice            │
│     ├─ Window/level mapping                        │
│     ├─ Corner text annotations                     │
│     ├─ Overlay sync (measurements, rulers)         │
│     └─ Render() — OpenGL composite to screen       │
│     Timing: 5–80ms per frame (software GL)         │
└────────────────┬─────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│ A6. Interactive Scroll                             │
│     wheelEvent → coalesce → set_slice →            │
│       SetSlice + Render                            │
│     Stack drag → same set_slice path               │
│     Adaptive throttle, GC suppression              │
│     Target: ≤16ms per frame (60 Hz)                │
└──────────────────────────────────────────────────┘
```

### Graphics Modes

The Advanced backend supports **two** OpenGL modes, configured at startup
in `main.py` → `configure_graphics_fallback()` → `aipacs_runtime.py`:

| Mode | Config Key | How Detected | Environment |
|------|-----------|--------------|-------------|
| **Hardware GPU** | `cpu_physical_gpu` | `probe_gpu_support()` + `user_declared_gpu=True` | `QT_OPENGL=desktop`, `VTK_USE_HARDWARE=1`, `ANGLE=d3d11` |
| **Software OpenGL** | `cpu_software_opengl` | Default when no GPU declared | `QT_OPENGL=software`, Mesa/llvmpipe DLLs on PATH, `VTK_USE_HARDWARE=0` |

**GPU Detection Flow:**

```
aipacs_runtime.resolve_graphics_profile()
  ├─ Load runtime_profile.json → graphics.user_declared_gpu
  ├─ If GPU requested: probe_gpu_support() via WMI/dxdiag
  ├─ use_gpu = requested AND detected
  └─ Return profile with execution_mode
        │
        ▼
main.py → build_windows_graphics_environment(profile)
  ├─ GPU mode: set desktop OpenGL env vars, ANGLE=d3d11
  └─ Software mode: set Mesa env vars, software OpenGL DLLs
        │
        ▼
widget_viewer.py → resolve_gpu_boost_plan()
  ├─ Determines per-session GPU/CPU task routing
  └─ Logged in [SERIES SWITCH] gpu_plan stage
```

**Toggle:** Users change GPU preference in Viewer Configuration UI →
`save_gpu_boost_enabled(True/False)` → takes effect on **next launch**.

### Key Files

| File | Role |
|------|------|
| `modules/viewer/advanced/viewer_2d.py` | ImageViewer2D: VTK rendering, SetSlice, Render |
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/` | VTKWidget mixins: scroll handling, backend binding, lazy callbacks |
| `PacsClient/pacs/patient_tab/utils/image_io.py` | Series loading, DICOM I/O |
| `PacsClient/pacs/patient_tab/utils/image_filters.py` | ITK filter pipeline |
| `modules/viewer/gpu_boost.py` | GPU preference persistence & task routing |
| `aipacs_runtime.py` | Graphics profile resolution, Mesa detection |

---

## 2. Fast Backend (`pydicom_2d` / `pydicom_qt`)

### Pipeline

```
DICOM files on disk
  │
  ▼
┌──────────────────────────────────────────────────┐
│ F1. Lazy Per-Slice Decode (pydicom)               │
│     Only decode the requested slice — no 3D vol   │
│     Uses pydicom + transfer syntax handlers       │
│     (pylibjpeg, openjpeg, GDCM fallback)          │
│     Timing: 1–15ms per slice                       │
└────────────────┬─────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│ F2. Pixel Array → numpy                            │
│     dataset.pixel_array (lazy) → uint16/int16     │
│     Apply window/level in numpy                    │
│     Timing: <1ms                                   │
└────────────────┬─────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│ F3. Qt 2D Render (QPainter / QPixmap)             │
│     numpy → QImage → QPainter blit                │
│     No VTK, no OpenGL dependency                   │
│     Timing: 1–3ms per frame                        │
│                                                    │
│     OR (pydicom_qt variant):                       │
│     Feed decoded array back into VTK viewer as     │
│     single-slice vtkImageData for VTK render       │
└──────────────────────────────────────────────────┘
```

### When It's Used

- During progressive download (series not fully on disk)
- When software OpenGL runtime is missing (`AIPACS_FORCE_SAFE_VIEWER_BACKEND`)
- When user explicitly selects "Fast" backend in Viewer Configuration

### Limitations (Phase 1)

- No ITK filters applied (raw DICOM pixel data)
- Measurements/annotations use VTK overlay path (unchanged)
- No 3D volume operations (MPR, MIP)
- No GPU acceleration

### Key Files

| File | Role |
|------|------|
| `modules/viewer/fast/pydicom_lazy_volume.py` | Per-slice lazy decode + VTK scalar backing (`pydicom_2d`) |
| `modules/viewer/fast/qt_viewer_bridge.py` | Qt bridge adapter (`pydicom_qt`) |
| `modules/viewer/fast/qt_slice_viewer.py` | Qt/QPainter render widget |
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/` | Backend routing, `_qt_bridge_active`, series binding |

---

## 3. Backend Selection

The single authoritative resolver is `resolve_viewer_backend()` in
`modules/viewer/viewer_backend_config.py`.

**Decision tree:**

```
resolve_viewer_backend(metadata, settings)
  │
  ├─ If AIPACS_FORCE_SAFE_VIEWER_BACKEND is set → pydicom_qt
  │
  ├─ If metadata has lazy_loader_key and backend=pydicom_2d → pydicom_2d
  │     (but fallback to vtk_simpleitk if lazy key is invalid)
  │
  ├─ If viewer_backend_settings.json says pydicom_2d
  │     AND series is fully downloaded → vtk_simpleitk (upgrade)
  │
  └─ Default → vtk_simpleitk
```

---

## 4. Known Bug History — Reslice NN Interpolation Corruption

> **Version fixed:** v2.2.6 (2026-03-15)
> **Symptom:** Image freezes during wheel scroll; scrollbar moves but image
> stays fixed. After freeze, neither stack drag nor wheel scroll works.
> **Root cause:** See next section.

### 4.1 What Happened

The `wheelEvent()` performance optimization (v2.2.3.4.0) included:

```python
# IN wheelEvent — first scroll event of burst:
reslice.SetInterpolationModeToNearestNeighbor()
reslice.Modified()
actor.InterpolateOff()
```

This was intended to reduce reslice cost during fast scrolling by temporarily
degrading interpolation quality from Cubic to NearestNeighbor, then restoring
quality 2000ms after the last scroll event.

### 4.2 Why It Broke

The `vtkImageReslice` in the Advanced backend carries a **non-identity
direction-matrix transform** (Y-flip from `convert_itk2vtk`). When the
interpolation mode is changed and `Modified()` is called:

1. VTK marks the reslice filter as dirty
2. On the next `UpdateDisplayExtent()` inside `SetSlice()`, VTK recomputes
   the output extent
3. **The recomputation with NearestNeighbor produces a wrong output extent**
   — the Z dimension collapses from the full slice count to 1
4. `GetSliceMin()` == `GetSliceMax()` == the current slice
5. All subsequent `SetSlice()` calls are clamped to that single slice

**Diagnostic evidence** (from `%TEMP%\aipacs_wheel_diag.log`):

```
[FLUSH_DIAG] target=14 before=13 after=14 range=(0,24) range_after=(0,14) data_z=25   ← range shrinking
[FLUSH_DIAG] target=15 before=14 after=14 range=(14,14) data_z=1                      ← collapsed to 1 slice
[FLUSH_DIAG] target=16 before=14 after=14 range=(14,14) data_z=1                      ← stuck forever
```

### 4.3 Why Stack Drag Wasn't Affected

Stack drag events go through the VTK interactor style, NOT through
`wheelEvent()`. They reach `queue_interactive_slice_target(source="stack_drag")`
directly. The reslice interpolation mode change only happened inside
`wheelEvent()`, so stack drag never triggered the corruption.

The bug manifested specifically in the **stack drag → wheel scroll** transition:
stack drag worked fine, then the first wheel event corrupted the reslice.

### 4.4 The Fix (v2.2.6)

```python
# BEFORE (v2.2.3.4.0 – v2.2.5):
_skip_nn_degrade = self._active_backend in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT)

# AFTER (v2.2.6):
_skip_nn_degrade = True  # Skip for ALL backends
```

The NN degradation is now permanently disabled. The reslice is always kept at
Cubic interpolation. The performance gain from NN was negligible (<1ms per
frame) compared to the catastrophic freeze bug it caused.

`_restore_reslice_quality()` was also made a no-op since there is nothing to
restore.

### 4.5 How to Detect If This Recurs

1. Check `%TEMP%\aipacs_wheel_diag.log` for `[FLUSH_DIAG]` entries
2. Look for `changed=False` with `data_z=1` — indicates collapsed extent
3. Look for `range=(N,N)` where min == max — indicates single-slice clamping

### 4.6 Rule: Never Modify Reslice During Scroll

> **CRITICAL RULE:** Do NOT call `reslice.SetInterpolationMode*()`,
> `reslice.Modified()`, or any method that dirties the reslice pipeline
> during interactive scroll. The reslice carries a direction-matrix
> transform; dirtying it causes VTK to recompute the output extent,
> which can corrupt the slice range.
>
> If future performance optimization needs to degrade quality during
> scroll, use `actor.InterpolateOff()` alone (display-only, does not
> touch the reslice pipeline).

---

## 5. Graphics Mode Verification Checklist

When modifying anything in the viewer or build pipeline, verify both
graphics modes still work:

### Software OpenGL Mode (default)

- [ ] `runtime_profile.json` → `graphics.user_declared_gpu = false`
- [ ] Console shows: `[GRAPHICS] Mode: SOFTWARE_OPENGL`
- [ ] Console shows: `[GRAPHICS] QT_OPENGL: software`
- [ ] Console shows: `[GRAPHICS] VTK_USE_HARDWARE: 0` (in env)
- [ ] Mesa DLLs loaded (check PATH for `graphics_runtime/`)
- [ ] Series loads and displays correctly
- [ ] Wheel scroll works (image follows scrollbar)
- [ ] Stack drag works

### Hardware GPU Mode

- [ ] `runtime_profile.json` → `graphics.user_declared_gpu = true`
- [ ] Console shows: `[GRAPHICS] Mode: GPU`
- [ ] Console shows: `[GRAPHICS] QT_OPENGL: desktop`
- [ ] Console shows: `[GRAPHICS] GPU device: <name>`
- [ ] Series loads and displays correctly
- [ ] Wheel scroll works (image follows scrollbar)
- [ ] Stack drag works

### Fallback Behavior

- [ ] If GPU requested but not detected → falls back to Software OpenGL
- [ ] If Software OpenGL DLLs missing → falls back to `pydicom_qt` backend
- [ ] `AIPACS_FORCE_SAFE_VIEWER_BACKEND` env var forces PyDicom Qt backend

---

## 6. FAST-Mode Sync Geometry Pipeline

> **Version introduced:** v2.2.9.2 (2026-04-09)
> **File:** `modules/viewer/fast/dicom_sync_geometry.py`
> **Scope:** FAST backend only.  The Advanced (VTK) backend uses a
> separate world-space path via `vtkImageReslice`.

### 6.1 Overview

When a user moves the sagittal/coronal cursor source on an Advanced viewer,
the system must determine which slice in any linked FAST Qt viewer corresponds
to the same anatomical point.  This is pure-DICOM geometry: no VTK world-space,
no mock-VTK conventions.  All math operates entirely in patient-LPS space using
IOP/IPP/PixelSpacing from the DICOM metadata.

```
Sagittal/Coronal source click (patient-LPS point)
                │
                ▼
      _map_sync_dicom()  (_pw_sync.py)
                │
                ├─── FAST Qt target? ───► project_lps_to_target()
                │                         (dicom_sync_geometry.py)
                │
                └─── Advanced VTK target? ──► legacy VTK world-space path
```

### 6.2 Coordinate System

All FAST sync geometry uses **DICOM Patient-LPS space** throughout:

| Symbol | Definition | Example (axial) |
|--------|-----------|-----------------|
| `IPP_k` | Image Position Patient of slice k | `(x, y, z_k)` |
| `IOP[0:3]` | Row direction cosine | `(1, 0, 0)` → columns increase Left |
| `IOP[3:6]` | Column direction cosine | `(0, 1, 0)` → rows increase Posterior |
| `n_t` | Slice normal = `cross(col_dir, row_dir)` | `(0, 0, -1)` for axial |
| `P_lps` | Source point in patient-LPS | `(x, y, z_src)` |
| `d_src` | `dot(P_lps − IPP_0, n_t)` | Signed distance along normal |
| `P_proj` | `P_lps − dp·n_t` | Projection onto target slice plane |

> **Sign note:** `compute_slice_normal` returns `cross(col_dir, row_dir)`.
> For a standard axial DICOM acquisition (IOP = `[1,0,0, 0,1,0]`) this
> yields `n_t = (0,0,−1)`.  Positions computed via `dot(IPP_k − IPP_0, n_t)`
> are therefore negative-valued even though z increases positively.  The code
> uses signed median spacing throughout to remain consistent.

### 6.3 Full Pipeline — `project_lps_to_target()`

```
P_lps  (patient-LPS source point)
  │
  ▼
╔══════════════════════════════════════════════════════════╗
║  Step 1 — Slice normal                                   ║
║  n_t = compute_slice_normal(IOP)  = cross(col, row)      ║
║  Returns None → abort (no IOP in metadata)               ║
╚══════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════╗
║  Step 2 — Physical per-slice positions  (NEW v2.2.9.2)   ║
║  positions[k] = dot(IPP_k − IPP_0, n_t)                  ║
║  O(n) scan of ALL instance IPPs                          ║
║  Returns None → fall back to legacy formula path         ║
╚══════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════╗
║  Step 3 — Stack classification  (NEW v2.2.9.2)           ║
║  analyse_target_stack():                                 ║
║    spacings[k] = |positions[k+1] − positions[k]|         ║
║    typical   = median(spacings)   (intra-group)          ║
║    max_gap   = max(spacings)      (inter-group candidate) ║
║    is_sparse = max_gap > 3.0 × typical                   ║
╚══════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════╗
║  Step 4 — Physically nearest slice  (NEW v2.2.9.2)       ║
║  find_closest_slice_physical():                          ║
║    d_src     = dot(P_lps − IPP_0, n_t)                   ║
║    k_nearest = argmin |positions − d_src|                ║
║    min_dist  = |positions[k_nearest] − d_src|            ║
║    (optional hysteresis: stay on prev_k if new is not    ║
║    more than hysteresis_mm closer)                       ║
║  k_float = d_src / signed_median_spacing  (diagnostics)  ║
╚══════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════╗
║  Step 5 — Between-groups detection  (NEW v2.2.9.2)       ║
║  between_groups = is_sparse                              ║
║                   AND min_dist > 0.7 × typical_spacing   ║
║  Clinical meaning: source is in an anatomical gap        ║
║  between disc levels; showing sync is misleading         ║
╚══════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════╗
║  Step 6 — IPP of chosen slice + plane projection         ║
║  ipp_k  = IPP[k_nearest]                                 ║
║  dp     = dot(P_lps − ipp_k, n_t)                        ║
║  P_proj = P_lps − dp * n_t    (onto target slice plane)  ║
╚══════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════╗
║  Step 7 — LPS → pixel coordinates                        ║
║  col_idx = dot(P_proj − ipp_k, row_dir) / pixel_sp[1]    ║
║  row_idx = dot(P_proj − ipp_k, col_dir) / pixel_sp[0]    ║
╚══════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════╗
║  Step 8 — Validity classification                        ║
║  slab_valid    = d_src ∈ [pos_min−½t, pos_max+½t]        ║
║  inplane_valid = col_idx ∈ [0,cols) AND row_idx ∈ [0,rows)║
║  between_groups → rejection_reason = 'between_groups'    ║
║  final_valid   = slab ∧ inplane ∧ ¬between_groups        ║
╚══════════════════════════════════════════════════════════╝
  │
  ├─ final_valid=False → _map_sync_dicom returns None
  │                      SyncManager hides cursor overlay
  │
  └─ final_valid=True  → returns P_proj (patient-LPS)
                         set_sync_point draws crosshair
```

### 6.4 Why the Old Formula Failed for Sparse Stacks

**Before v2.2.9.2**, `find_closest_slice` estimated slice spacing from only
the first two slice positions:

```python
# WRONG for sparse stacks:
ds = dot(IPP_1 − IPP_0, n_t)     # uses ONLY slices 0 and 1
k_float = d0 / ds                 # assumes ALL slices equally spaced
k_tgt   = clamp(round(k_float), 0, n−1)  # always clamps to edge
```

**Clinical failure scenario — Lumbar MRI disc-by-disc acquisition:**

```
Group L5-S1:  slices 0,1,2   z = 0, 1, 2 mm    ds(0→1) = 1 mm
              ← 15 mm anatomical gap →
Group L4-L5:  slices 3,4,5   z = 18, 19, 20 mm
              ← 15 mm anatomical gap →
Group L3-L4:  slices 6,7,8   z = 36, 37, 38 mm
  …
```

With `ds = 1 mm` and source at `z_src = 19 mm` (inside L4-L5 group):

```
d0      = dot(P − IPP_0, n_t) = −19   (n_t points opposite to +z)
k_float = −19 / −1 = 19               ← formula gives INDEX 19
k_tgt   = clamp(19, 0, 14) = 14       ← clamped to LAST slice (L1 group!)
```

The viewer snapped to the sacral group instead of L4-L5.  Physical scan:

```
positions = [0, −1, −2, −18, −19, −20, −36, −37, −38, …]
d_src    = −19
argmin   = 4   ← index 4 (z=19 mm, correct L4-L5 disc)
```

### 6.5 Between-Groups Rejection

When the sagittal cursor is between disc levels — in an anatomical space
with no axial slices — the system must hide the sync marker entirely rather
than snap to the nearest (wrong) disc group.

**Threshold:** `min_dist_mm > 0.7 × typical_spacing`

On a continuous CT stack this NEVER triggers: between two adjacent slices
(spacing = `s`) the maximum distance to the nearest slice is `s/2 ≈ 0.5s`,
which is always below `0.7s`.

On a sparse lumbar stack the inter-group gap is 15 mm while typical spacing
is 1 mm.  A source point mid-gap has `min_dist ≈ 7.5 mm >> 0.7 mm`.

| Scenario | typical_spacing | min_dist | between_groups |
|----------|----------------|----------|----------------|
| CT continuous, source on slice | 1.5 mm | 0 mm | ❌ False |
| CT continuous, source between slices | 1.5 mm | 0.75 mm | ❌ False |
| Lumbar, source inside disc group | 1.0 mm | 0.3 mm | ❌ False |
| Lumbar, source in inter-disc gap | 1.0 mm | 7.2 mm | ✅ True → HIDE |

### 6.6 Slice Navigation in `_find_closest_slice` (qt_viewer_bridge)

When `set_sync_point(adjust_slice=True)` is called on a FAST Qt viewer, it needs
to navigate to the correct slice index.  This also uses `find_closest_slice_physical`
so that sparse stacks navigate correctly:

```python
# qt_viewer_bridge._find_closest_slice() — v2.2.9.2
n_t       = compute_slice_normal(iop)
positions = compute_slice_positions(instances, n_t)
k, _, _   = find_closest_slice_physical(patient_lps, instances, n_t, positions)
return k
```

The legacy `find_closest_slice` is **kept** for backward compatibility (it is
still used in `compute_roundtrip_error_mm` and the Advanced sync fallback path).
All FAST sync paths use the physical scan functions.

### 6.7 `SliceProjectionResult` Fields

`project_lps_to_target()` returns a `SliceProjectionResult` with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `P_proj` | `ndarray` | Projected point on target slice plane (patient-LPS) |
| `k_tgt` | `int` | Nearest slice index |
| `k_float` | `float` | Continuous slice index (diagnostics; uses signed median spacing) |
| `dp` | `float` | Perpendicular dist from chosen slice plane (mm) |
| `col_idx` | `float` | Pixel column coordinate in target image |
| `row_idx` | `float` | Pixel row coordinate in target image |
| `in_bounds` | `bool` | `col_idx`/`row_idx` within image dimensions |
| `outside_reason` | `list[str]` | `['left'/'right'/'top'/'bottom']` if out of FOV |
| `n_t` | `ndarray` | Slice normal used |
| `ipp_k` | `ndarray` | IPP of chosen slice |
| `slice_count` | `int` | Total slices in target |
| `k_min` / `k_max` | `int` | 0 / slice_count−1 |
| `k_tgt_after_clamp` | `int` | Same as `k_tgt` (physical scan never clamps) |
| `clamp_occurred` | `bool` | True when source is outside the physical extent |
| `through_plane_distance_mm` | `float` | `dp` (alias) |
| `world_delta_mm` | `float` | `|P_proj − P_lps|` — perpendicular distance magnitude |
| `slab_valid` | `bool` | `d_src ∈ [pos_min−½t, pos_max+½t]` |
| `inplane_valid` | `bool` | Pixel coords within image FOV |
| `final_valid_sync_point` | `bool` | `slab ∧ inplane ∧ ¬between_groups` |
| `rejection_reason` | `str` | `'none'` / `'out_of_stack'` / `'out_of_fov'` / `'between_groups'` |
| `stack_is_sparse` | `bool` | `max_gap > 3.0 × typical_spacing` *(v2.2.9.2)* |
| `typical_stack_spacing_mm` | `float` | Median intra-group spacing *(v2.2.9.2)* |
| `max_stack_gap_mm` | `float` | Largest inter-slice gap *(v2.2.9.2)* |
| `min_distance_to_slice_mm` | `float` | Physical distance to nearest slice *(v2.2.9.2)* |
| `between_groups` | `bool` | Source is in an anatomical gap *(v2.2.9.2)* |

### 6.8 FAST-SYNC-VALIDATION Log

Every sync mapping attempt emits a `[FAST-SYNC-VALIDATION]` log line at
`INFO` level.  This is the primary debugging tool for sync geometry issues:

```
[FAST-SYNC-VALIDATION] source_P_lps=(x,y,z) slice_count=N k_min=0 k_max=N
  k_float_before_clamp=K k_tgt_after_clamp=K clamp_occurred=False
  signed_through_plane_distance_mm=D world_delta_mm=D
  slab_valid=True inplane_valid=True final_valid_sync_point=True
  rejection_reason=none
  stack_is_sparse=False typical_spacing_mm=1.500 max_gap_mm=1.500
  min_dist_to_slice_mm=0.123 between_groups=False
```

On rejection:

```
[FAST-SYNC-REJECT] target=<id> reason=between_groups slab_valid=True inplane_valid=True
```

### 6.9 Key Constants and Thresholds

| Constant | Value | File | Meaning |
|----------|-------|------|---------|
| `_SPARSE_GAP_FACTOR` | `3.0` | `dicom_sync_geometry.py` | Gap > 3× typical → sparse classification |
| between-groups threshold | `0.7 × typical_spacing` | `project_lps_to_target()` | Distance beyond this is "in a gap" |
| `_HYSTERESIS_MM` | `0.0` (default) | `_pw_sync.py` | Hysteresis disabled unless overridden |

### 6.10 Functions Reference

| Function | Signature | Purpose |
|----------|-----------|---------|
| `compute_slice_normal` | `(iop) → ndarray\|None` | `cross(col_dir, row_dir)`, normalised |
| `compute_slice_positions` | `(instances, n_t) → ndarray\|None` | Per-slice `dot(IPP_k−IPP_0, n_t)` |
| `analyse_target_stack` | `(instances, positions, n_t) → dict` | Classify sparse/continuous, find gap indices |
| `find_closest_slice_physical` | `(P_lps, instances, n_t, …) → (k, d_src, min_dist)` | O(n) argmin physical scan |
| `find_closest_slice` | `(P_lps, instances, …) → (k, k_float, dp, n_t)` | Legacy formula path — **uniform stacks only** |
| `project_lps_onto_plane` | `(P, ipp_k, n) → (P_proj, dp)` | Project onto slice plane |
| `lps_to_image_pixel` | `(P_proj, ipp_k, iop, px_sp) → (col, row)` | LPS → pixel coordinates |
| `image_pixel_to_lps` | `(col, row, ipp_k, iop, px_sp) → ndarray` | Pixel → LPS (exact inverse) |
| `project_lps_to_target` | `(P_lps, instances, …) → SliceProjectionResult\|None` | **Main entry point** — full pipeline |
| `compute_roundtrip_error_mm` | `(src_instances, tgt_instances, k_src) → float` | Roundtrip LPS error for testing |

### 6.11 Rejection Flow

```
project_lps_to_target() → SliceProjectionResult
  │
  │  final_valid_sync_point = False?
  ├──────────────────────────────────►  _map_sync_dicom returns (None, ijk_diag, True, reason)
  │                                     └── SyncManager._hide_cursor(target_viewer)
  │                                         └── qt_viewer_bridge.hide_sync_point()
  │                                             └── overlay cleared from screen
  │
  └──  True  ──► returns P_proj (patient-LPS tuple)
                 └── set_sync_point(P_proj, adjust_slice=True)
                     ├── _find_closest_slice(P_proj) → k   [physical scan]
                     ├── navigate viewer to slice k
                     └── draw crosshair at (col_idx, row_idx)
```

### 6.12 Test Coverage

| Test file | Scenarios |
|-----------|-----------|
| `tests/fast/test_sync_sparse_stack.py` | 24 tests — sparse classification, physical scan, gap rejection, rapid-cursor no-jump regression |
| `tests/fast/test_sync_validity_classification.py` | 7 tests — slab/FOV valid/invalid, oblique-to-orthogonal |
| `tests/fast/test_sync_point_roundtrip.py` | Roundtrip error < 0.01 mm for axial/sagittal/coronal |
| `tests/fast/test_sync_non_axial_projection.py` | Oblique IOP targets |
| `tests/fast/test_sync_inplane_bounds.py` | Left/right/top/bottom FOV rejection |
| `tests/fast/test_sync_slice_rounding.py` | k_tgt determinism at half-spacing boundaries |
| `tests/fast/test_sync_reference_line_geometry.py` | Reference line geometry correctness |

Run all FAST sync tests:

```powershell
.venv\Scripts\python.exe -m pytest tests/fast/ -v
# Expected: 149 passed
```
