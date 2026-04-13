# FAST Mode VTK Dependency/Coupling Analysis

**Date:** 2026-04-13  
**Version:** v2.3.3  
**Companion to:** [FAST_RENDERER_EVALUATION.md](FAST_RENDERER_EVALUATION.md)

---

## 1. VTK Dependency Map

### VTK-FREE modules (zero VTK imports or runtime usage)

| Module | Lines | Role in FAST | Notes |
|--------|-------|-------------|-------|
| `modules/viewer/viewer_backend_config.py` | ~200 | Backend decision hub | Enum strings only |
| `modules/viewer/fast/contracts.py` | ~60 | Protocol + dataclasses | Pure Python |
| `modules/viewer/fast/lightweight_2d_pipeline.py` | ~900 | Decode+filter+W/L+QImage | PyDicom + OpenCV |
| `modules/viewer/fast/qt_viewer_bridge.py` | ~900 | ImageViewer2D adapter | Mock VTK objects |
| `modules/viewer/fast/qt_slice_viewer.py` | ~900 | QPainter rendering | Pure Qt |
| `modules/viewer/fast/pydicom_2d_backend.py` | ~200 | Slice extraction | PyDicom only |
| `modules/viewer/fast/lazy_volume_registry.py` | ~100 | Registry dict | No VTK |
| `modules/viewer/fast/stale_frame_guard.py` | ~100 | Stale frame detect | No VTK |
| `modules/viewer/tools/*` | ~2000 | Measurement tools | Qt tool system |

### CONDITIONALLY VTK modules (imported but guarded in FAST mode)

| Module | Guard Pattern | VTK Calls in FAST | Effort to Decouple |
|--------|--------------|-------------------|-------------------|
| `vtk_widget/_vw_scroll.py` | `if _qt_bridge_active:` | None (early return) | LOW |
| `vtk_widget/_vw_backend.py` | `if backend == BACKEND_PYDICOM_QT:` | None (dispatch only) | LOW |
| `vtk_widget/_vw_camera.py` | `if _qt_bridge_active:` | None (mocked camera) | LOW |
| `vtk_widget/_vw_render.py` | `if _qt_bridge_active: return` | None (skipped) | LOW |

### MANDATORY VTK modules (loaded at import time, even in FAST mode)

| Module | Import Statement | Why It Exists | Removal Effort |
|--------|-----------------|---------------|---------------|
| `vtk_widget/widget.py` | `from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor` | Base class inheritance | **MEDIUM** |
| `image_io.py` | `import vtkmodules.all as vtk` (line 12) | VTK stub creation + ITK pipeline | **MEDIUM** |
| `patient_widget_viewer_controller.py` | `import vtk` (line 15) | Unused in FAST path | **NONE** (just delete) |
| `pydicom_lazy_volume.py` | `import vtkmodules.all as vtk` + `numpy_support` | VTK array type enum + backing store | **LOW** |

---

## 2. The 4 Decoupling Points

### Point 1: VTKWidget Base Class (MEDIUM effort)

`VTKWidget` inherits `QVTKRenderWindowInteractor`, which forces:
- VTK DLL loading (~200ms startup cost)
- VTK render window allocation (unused memory)
- The entire VTK Qt integration layer

**Current architecture:**
```
VTKWidget(QVTKRenderWindowInteractor)
  ├─ _qt_bridge_active = True → QtSliceViewer stacked on top
  └─ _qt_bridge_active = False → VTK renders to self
```

**Target architecture:**
```
FastViewerWidget(QWidget)
  └─ QtSliceViewer (child widget, always used)

VTKWidget(QVTKRenderWindowInteractor)  # unchanged, Advanced only
```

### Point 2: image_io.py Module-Level VTK Import (MEDIUM effort)

`import vtkmodules.all as vtk` at module level means every import of `image_io` triggers VTK loading, even when only the FAST path (`BACKEND_PYDICOM_QT` early exit) is used.

**Fix:** Move VTK imports inside the non-FAST code paths, or split `image_io.py` into `image_io_fast.py` (metadata only) and `image_io_vtk.py` (ITK pipeline).

### Point 3: pydicom_lazy_volume.py VTK Array Types (LOW effort)

Uses `numpy_support.get_vtk_array_type()` to map NumPy dtypes to VTK enum constants. This is trivially replaceable with a static dict:

```python
_NUMPY_TO_VTK_TYPE = {
    np.uint8: 3,    # VTK_UNSIGNED_CHAR
    np.int16: 4,    # VTK_SHORT
    np.uint16: 5,   # VTK_UNSIGNED_SHORT
    np.int32: 6,    # VTK_INT
    np.float32: 10, # VTK_FLOAT
    np.float64: 11, # VTK_DOUBLE
}
```

### Point 4: patient_widget_viewer_controller.py Unused Import (NONE effort)

`import vtk` is imported but never called in the FAST path. Safe to delete.

---

## 3. Signal/Data Flow Through VTK Boundary

### FAST mode (pydicom_qt) — current flow

```
                    ┌─ VTK loaded at import ─┐
                    │  (wasted ~200ms)       │
User scrolls ──►   │                        │
VTKWidget.wheelEvent ──► _vw_scroll.py ──►  │
  if _qt_bridge_active: ──────────────────► QtViewerBridge.set_slice()
                                             │
                                             ▼
                                   Lightweight2DPipeline.get_rendered_frame()
                                             │
                                             ▼
                                     PyDicom decode → NumPy → QImage
                                             │
                                             ▼
                                     QtSliceViewer.paintEvent() (QPainter)
```

### Target flow (no VTK in path)

```
User scrolls ──►
FastViewerWidget.wheelEvent ──► QtViewerBridge.set_slice()
                                  │
                                  ▼
                        Lightweight2DPipeline.get_rendered_frame()
                                  │
                                  ▼
                          PyDicom decode → NumPy → QImage
                                  │
                                  ▼
                          QtSliceViewer.paintEvent() (QPainter)
```

---

## 4. Cache Key Dependency

Several caches use `vtkImageData` as values or presence checks:

| Cache | Key | Value | VTK? | Fix |
|-------|-----|-------|------|-----|
| `lst_thumbnails_data` | series_number | `{vtk_data, metadata}` | Yes (stub) | Replace with metadata-only dict |
| `_get_series_by_number_fast` | series_number | `vtkImageData` stub | Yes | Use `metadata is not None` check |
| In-memory image cache | study+series | `vtkImageData` | Advanced only | No change needed |

The VTK stubs in FAST mode carry **no pixel data** — they exist only to satisfy `vtk_data is not None` cache checks. Replacing with a sentinel (e.g., `_FAST_CACHE_STUB = object()`) would remove this dependency.

---

## 5. Risk Matrix for Decoupling

| Decoupling Point | Risk | Mitigation |
|-----------------|------|------------|
| VTKWidget → FastViewerWidget | Medium: all mixins reference `self` as VTKWidget | Create mixin-compatible QWidget subclass |
| image_io lazy imports | Low: function-level imports are standard Python | Test import timing |
| pydicom_lazy_volume dict replacement | Very Low: static mapping | Unit test dtype coverage |
| Remove unused vtk import | None: unused symbol | Grep verification |
| Cache stub replacement | Low: limited usage points | Search all `vtk_data is not None` checks |
