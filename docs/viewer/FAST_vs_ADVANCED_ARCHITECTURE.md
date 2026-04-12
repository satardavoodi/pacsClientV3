# FAST vs ADVANCED Viewer Architecture (Read-Only Reverse Engineering)

## Scope and method

This document is based on direct code-path tracing (no code changes), focused on:
- backend selection
- load/switch flow
- render-chain ownership
- progressive download behavior

Primary evidence files:
- `modules/viewer/viewer_backend_config.py`
- `PacsClient/pacs/patient_tab/utils/image_io.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_series.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_scroll.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_backend.py`
- `modules/viewer/advanced/viewer_2d.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/qt_slice_viewer.py`
- `modules/viewer/fast/pydicom_lazy_volume.py`

## Executive architecture split

### ADVANCED path (`vtk_simpleitk`)
- Full load path via `load_single_series_by_number(...)` into VTK/SimpleITK output.
- Viewer object is `ImageViewer2D` (`modules/viewer/advanced/viewer_2d.py`).
- Slice rendering uses VTK chain via `ImageViewer2D.set_slice(...)` -> `Render()`.
- Final pixels are drawn by VTK (`QVTKRenderWindowInteractor` paint path).

### FAST path (two runtime flavors)

#### FAST-Qt bridge (`pydicom_qt`)
- Loader early-exit in `image_io.py` returns metadata + VTK stub (no heavy ITK).
- `VTKWidget._start_qt_viewer(...)` installs `QtViewerBridge` + `QtSliceViewer`.
- `VTKWidget.paintEvent()` returns early when `_qt_bridge_active=True`.
- Final pixels are drawn by **Qt/QPainter** in `QtSliceViewer.paintEvent()`.

#### FAST-lazy VTK (`pydicom_2d` / `BACKEND_PYDICOM`)
- `PyDicomLazyVolume` owns mmap-backed NumPy volume + `vtk_image_data` scalars.
- Scroll/callback path calls `mark_vtk_modified()` then `image_viewer.set_slice(...)`.
- Final pixels are still drawn by **VTK Render()**, but decode is lazy and backend data source is pydicom.

## Actual render-engine conclusion (critical)

FAST mode is not a single renderer:
- `pydicom_qt` => Qt renderer (`QtSliceViewer` + `QPainter`).
- `pydicom_2d` => VTK renderer (`ImageViewer2D.Render()`), with lazy pydicom-backed data.

So, "FAST = VTK-free" is only true for the `pydicom_qt` branch, not for all FAST variants.

## Backend selection and fallback

`resolve_viewer_backend(...)` in `viewer_backend_config.py` governs route selection:
- `pydicom_qt` requires metadata instances and no lazy-key dependency.
- `pydicom_2d` can fallback to `vtk_simpleitk` if metadata/lazy requirements are incomplete.
- metadata flags like `force_vtk_fallback` and `lazy_loader_key` participate in routing.

## High-level flow comparison

1. user action (`change_series_on_viewer`) -> backend-aware switch/load path.
2. cache hit -> immediate switch.
3. cache miss -> `_schedule_async_load_and_switch(...)` -> `_load_single_series_on_demand(...)`.
4. apply -> `VTKWidget.switch_series(...)` -> backend-specific viewer startup.

Difference is primarily in:
- load cost (ITK full vs metadata/lazy)
- render owner (VTK vs Qt)
- progressive growth mechanics (volume grow + slider/update)

## Contradictions resolved

1. Some docs describe FAST as VTK-free globally.
   - Code shows only `pydicom_qt` is VTK-free rendering.
   - `pydicom_2d` still renders via VTK.

2. Some docs imply render source identity from backend name alone.
   - Real decision is runtime state (`_active_backend`, `_qt_bridge_active`, lazy loader presence).

3. FAST path still runs inside `VTKWidget` shell even in Qt mode.
   - true: container remains VTKWidget; render surface switches to Qt child and VTK paint is bypassed.
