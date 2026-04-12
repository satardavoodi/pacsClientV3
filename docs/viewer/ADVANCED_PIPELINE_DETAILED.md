# ADVANCED Pipeline Detailed Trace

## 1) Entry

Primary user entry:
- `ViewerController.change_series_on_viewer(...)` (`_vc_switch.py`)
- cache miss path -> `_schedule_async_load_and_switch(...)`
- background load -> `_load_single_series_on_demand(...)` (`_vc_load.py`)

## 2) Loader path

`load_single_series_by_number(...)` in `PacsClient/pacs/patient_tab/utils/image_io.py`:
- for `vtk_simpleitk`/advanced path, performs full series load and conversion path.
- produces VTK image + metadata used by viewer apply/switch.

## 3) Switch/apply path

`_perform_series_switch_optimized(...)` (`_vc_switch.py`) calls:
- `vtk_widget.switch_series(...)` (`_vw_series.py`)
- with advanced backend, `_qt_bridge_active` is false and `ImageViewer2D` path is used.

## 4) Viewer construction (ADVANCED)

`ImageViewer2D` (`modules/viewer/advanced/viewer_2d.py`):
- derives from `vtkResliceImageViewer`
- constructs `ImageReslice`
- connects to image actor/color mapper
- initializes camera and annotations

Important render ownership:
- `ImageViewer2D.Render()` delegates to VTK render path.
- `VTKWidget.paintEvent(...)` uses base behavior when not Qt-bridge, so VTK owns drawing.

## 5) Slice render chain (ADVANCED)

Scroll/event enters `VTKWidget.set_slice(...)` (`_vw_scroll.py`):
- `_call_image_viewer_set_slice(...)` -> `ImageViewer2D.set_slice(...)`
- `ImageViewer2D.set_slice(...)`:
  1. `SetSlice(...)`
  2. default WL (if not custom)
  3. update corner actors
  4. sync overlays
  5. `Render()`

## 6) Progressive note for ADVANCED

`_vc_progressive.py` contains both fast and advanced branches:
- advanced branch uses reload/grow style (`_grow_progressive_viewer_async`) when relevant.
- however practical default progressive behavior is tuned for FAST; advanced commonly displays at full load completion path.

## 7) Performance-sensitive points

From code path structure (no changes made):
- expensive stages are full load + conversion and VTK render updates.
- `VTKWidget` has scroll throttling and stale-event guards to limit redundant render work.
- lock/signal architecture prevents UI-thread hard blocks where possible.
