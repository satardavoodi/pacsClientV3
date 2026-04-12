# patient_widget_core — PatientWidget Mixin Package

**Split from:** `patient_widget.py` (7,454 lines)  
**Version:** v2.2.9.1  
**Pattern:** Mixin classes assembled via multiple inheritance  

## Purpose

`PatientWidget` was a 7,454-line God-class mixing UI layout, sync/reference
lines, pipelines, advanced analysis, series loading, viewer creation, and
lifecycle management. It has been decomposed into **9 focused mixin files**
plus a **core widget file** that assembles them via Python MRO.

The original `patient_widget.py` is now a **backward-compatible shim** that
re-exports `PatientWidget` and all module-level helpers — zero import breakage.

## Files

| File | Class | Lines | Responsibility |
|------|-------|------:|----------------|
| `widget.py` | `PatientWidget` | 368 | Core class: `__init__`, signals, properties, mixin assembly |
| `_pw_sync.py` | `_PWSyncMixin` | 1,050 | Sync point, lock sync, reference lines, DICOM↔VTK mapping |
| `_pw_advanced.py` | `_PWAdvancedMixin` | 1,068 | Advanced Analysis panel, MPR, stitching, Eagle Eye |
| `_pw_panels.py` | `_PWPanelsMixin` | 775 | Header, sidebar, thumbnails panel, reception, AI chat, center layout |
| `_pw_viewers.py` | `_PWViewersMixin` | 638 | Viewer creation, VTK widgets, slider, grid layout, batch creation |
| `_pw_series.py` | `_PWSeriesMixin` | 898 | Series loading, display, search, download progress, retry |
| `_pw_pipeline.py` | `_PWPipelineMixin` | 1,298 | Pipeline startup, managers (server/import/local), progressive display |
| `_pw_thumbnails.py` | `_PWThumbnailsMixin` | 386 | Server thumbnails, series info, resolution, download status |
| `_pw_metadata.py` | `_PWMetadataMixin` | 407 | Series metadata, caching, grid config, patient data |
| `_pw_lifecycle.py` | `_PWLifecycleMixin` | 726 | Priority queue, cleanup, closeEvent, theme, tools, tab lifecycle |
| `__init__.py` | — | 3 | Re-exports `PatientWidget` |

## Class Assembly (MRO)

```python
class PatientWidget(
    _PWSyncMixin,
    _PWAdvancedMixin,
    _PWPanelsMixin,
    _PWViewersMixin,
    _PWSeriesMixin,
    _PWPipelineMixin,
    _PWThumbnailsMixin,
    _PWMetadataMixin,
    _PWLifecycleMixin,
    QWidget,
):
```

All mixins use `self` to access the PatientWidget instance. No mixin should
be instantiated on its own.

## Integration Points

- **ViewerController** (`patient_widget_viewer_controller.py`): The `widget.py`
  creates `self.viewer_controller = ViewerController(self)` in `__init__`.
  ViewerController has its own mixin split (`_vc_*.py`).
- **ToolbarManager**: Created in `_pw_panels.py::header_layout_ui()`.
- **SyncManager**: Created in `widget.py::__init__()`, methods in `_pw_sync.py`.
- **ThumbnailManager**: Created in `widget.py::__init__()`, methods in `_pw_thumbnails.py`.
- **Signals**: `series_downloaded`, `series_images_progress`, `loading_complete`
  defined on `PatientWidget` in `widget.py`.

## Critical Rules

- Do NOT re-sort `metadata['instances']` by IPP (reference line rule).
- Reference line round-robin pattern in `_pw_sync.py` must stay intact.
- Lock sync re-entrancy guard (`_lock_sync_updating`) must not be split.
- `closeEvent` cleanup order in `_pw_lifecycle.py` is critical.
- Progressive display guards (`_progressive_display_inflight`, `_progressive_display_done`)
  managed by ViewerController — not this package.

## Related Tests

```bash
# Smoke tests (imports)
python -m pytest tests/smoke/test_import_smoke.py -v

# Viewer pipeline tests
python -m pytest tests/viewer/test_fast_viewer_pipeline.py -v

# Cross-module connections
python -m pytest tests/connection_between_modules/ -v

# Download manager
python tests/download_manager/run_dm_test.py
```
