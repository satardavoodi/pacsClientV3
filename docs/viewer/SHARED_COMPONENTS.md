# Shared Components Between FAST and ADVANCED

## Common orchestration layer

Both pipelines share:
- `ViewerController` orchestration mixins:
  - `_vc_switch.py`
  - `_vc_load.py`
  - `_vc_layout.py`
  - `_vc_progressive.py`
- same high-level flow:
  - select series
  - lookup cache
  - load if missing
  - apply/switch in target viewer

## Common container widget

Both run inside `VTKWidget` shell (`vtk_widget/widget.py`), but render owner differs by backend state.

Shared responsibilities in `VTKWidget`:
- slider and scroll dispatch
- drag-drop interaction
- backend binding (`_bind_backend_from_metadata`)
- progressive flags and spinner behavior

## Shared metadata and state conventions

Common fields:
- `metadata['series']['series_number']`
- `metadata['instances']`
- backend annotations (`viewer_backend`, `lazy_loader_key`, fallback flags)

Common guards:
- request token guards in `ViewerController` (`_is_request_current`)
- stale/progressive guards in `_vc_progressive.py`

## Shared progressive and completion safety nets

`_vc_progressive.py` is shared across modes:
- `on_series_images_progress(...)`
- `_start_progressive_display(...)`
- completion verification layers (`_completion_verify_series`, sweep timer)

Mode-specific internals differ, but lifecycle guard sets/timers are shared.

## Shared UI elements

- per-viewport spinners (`ViewportSpinner`)
- shared slider/tick behavior (`SliceTickSlider`)
- same toolbar/interaction integration entry points

## Shared caches and prefetch coordination

- `ViewerController` series caches/hot cache/full cache
- zeta/image booster coordination hooks
- async load dedup markers (`_loading_series_numbers`, in-flight sets)

## Where sharing ends

- Pixel generation and final draw surface diverge:
  - Advanced: `ImageViewer2D` + VTK render
  - Fast Qt: `QtViewerBridge` + `QtSliceViewer` + QPainter
  - Fast lazy VTK: VTK render fed by `PyDicomLazyVolume`
