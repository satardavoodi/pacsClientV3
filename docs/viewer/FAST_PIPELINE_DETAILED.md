# FAST Pipeline Detailed Trace

## 1) Entry and backend decision

- Entry points:
  - `ViewerController.change_series_on_viewer(...)` (`_vc_switch.py`)
  - `_schedule_async_load_and_switch(...)` on cache miss
  - `_load_single_series_on_demand(...)` (`_vc_load.py`)
- Backend request comes from viewer settings via `_get_requested_viewer_backend()` and is passed into loader.

Resolver and metadata:
- `modules/viewer/viewer_backend_config.py` -> `resolve_viewer_backend(...)`
- `PacsClient/pacs/patient_tab/utils/image_io.py` annotates metadata with `series.viewer_backend`, optional `lazy_loader_key`, and fallback flags.

## 2) FAST loader behavior

In `load_single_series_by_number(...)` (`image_io.py`):
- For `BACKEND_PYDICOM_QT`: early exit path, metadata-focused, minimal VTK stub, skips heavy ITK/filter chain.
  - If DB metadata is slightly behind the filesystem during active download, the fast path reconciles DB instances with on-disk `.dcm` files and reads headers only for the missing files instead of rebuilding metadata for the entire series.
  - Geometry backfill is only attempted when sampled metadata is incomplete; complete DB/header metadata should not pay a full per-instance backfill pass on interactive opens.
- For lazy `pydicom_2d`: creates lazy backend state and keys for on-demand decode.

## 3) Viewer switch and startup

`VTKWidget.switch_series(...)` (`_vw_series.py`):
- calls `_bind_backend_from_metadata(...)`.
- if `_active_backend == BACKEND_PYDICOM_QT`:
  - `_start_qt_viewer(...)`
  - builds bridge via `_create_qt_viewer_bridge(...)` (`_vw_globals.py`)
  - sets `_qt_bridge_active = True`
- else path uses `ImageViewer2D` (VTK render path).

## 4) FAST-Qt render chain (`pydicom_qt`)

Construction:
- `_create_qt_viewer_bridge(...)` creates:
  - `Lightweight2DPipeline`
  - `QtSliceViewer`
  - `QtViewerBridge`

Slice path:
- `VTKWidget.set_slice(...)` detects `_qt_bridge_active` and delegates to `image_viewer.set_slice(...)`.
- `QtViewerBridge.set_slice(...)`:
  - `pipeline.get_rendered_frame(idx)`
  - `qt_viewer.set_image(frame.qimage)`
- `QtSliceViewer.paintEvent(...)` draws final pixels using `QPainter`.

Critical paint bypass:
- `VTKWidget.paintEvent(...)` returns immediately when `_qt_bridge_active=True`, preventing VTK overwrite.

## 5) FAST-lazy VTK render chain (`pydicom_2d`)

Hot paths:
- scroll path: `_vw_scroll.py` -> `set_slice(...)`
- async decode callback: `_vw_backend.py` -> `_on_lazy_slice_ready_impl(...)`

Both paths do:
1. ensure/request lazy slice
2. call `loader.mark_vtk_modified()`
3. call `_call_image_viewer_set_slice(...)`
4. `ImageViewer2D.set_slice(...)` does `SetSlice`, WL/corners, then `Render()`

Data ownership:
- `PyDicomLazyVolume` maintains mmap NumPy store + VTK scalars.
- `mark_vtk_modified()` triggers VTK pipeline notice without reslice update hacks in this path.

## 6) Progressive growth in FAST

Main logic in `_vc_progressive.py`:
- `on_series_images_progress(...)` throttles and routes first-display vs grow.
- `_grow_progressive_fast(...)`:
  - prefers `loader.grow()` (or Qt bridge `grow()`)
  - updates slider/max + metadata sync + corner text
  - handles stale flush retries
  - exits progressive mode on completion paths.

## 7) TOCTOU-sensitive point (for T6 prep)

Function: `VTKWidget._on_lazy_slice_ready_impl(...)` in `_vw_backend.py`.

Current gating before render:
- current backend must be lazy backend
- `_lazy_loader` must exist
- stale-frame guard uses:
  - `ready_slice`
  - `requested_slice` (`self._lazy_requested_slice`)
  - `current_slice` (or `guard_current_slice`)
  - `ready_generation` (`_lazy_requested_generation`)
  - `current_generation` (`_series_generation_id`)

Potential re-check candidates at render boundary:
- `_current_slice_index` (effective viewer-selected target)
- `_lazy_requested_slice` (latest requested decode)

No fix applied here; this is the identified insertion zone.
