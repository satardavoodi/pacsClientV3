# AIPacs Viewer Backends Reference

**Version:** v2.2.6 | **Updated:** 2026-03-15

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
| `PacsClient/pacs/patient_tab/ui/patient_ui/widget_viewer.py` | VTKWidget: scroll handling, backend binding, GC |
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
| `modules/viewer/pydicom_backend/lazy_loader.py` | Per-slice decode engine |
| `modules/viewer/pydicom_backend/qt_bridge.py` | Qt QPainter rendering |
| `PacsClient/pacs/patient_tab/ui/patient_ui/widget_viewer.py` | Backend routing, `_qt_bridge_active` flag |

---

## 3. Backend Selection

The single authoritative resolver is `resolve_viewer_backend()` in
`modules/viewer/backend_resolver.py`.

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
