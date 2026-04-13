# FAST Mode Renderer Evaluation — VTK Replacement Analysis

**Date:** 2026-04-13  
**Version:** v2.3.3  
**Scope:** FAST viewer only — Advanced mode (VTK/SimpleITK) unchanged  
**Trigger:** H13 investigation confirmed VTK PyPI wheel's lack of `VTK_PYTHON_FULL_THREADSAFE` as root cause of GIL crashes

---

## 1. Executive Summary

**The codebase already contains a fully VTK-free Qt rendering path** (`pydicom_qt` backend) that is nearly feature-complete for 2D FAST viewing. A new dependency (pyqtgraph) is **NOT needed** — the existing Qt-native pipeline is the correct target.

The correct strategy is: **complete and harden the existing `pydicom_qt` path, make it the exclusive FAST renderer, and eliminate the `pydicom_2d` (lazy VTK) path.**

---

## 2. Candidate Evaluation

### Candidate A: pyqtgraph (user's suggested candidate)

| Dimension | Assessment |
|-----------|------------|
| **Rendering** | NumPy-based `ImageItem` with excellent LUT/W/L support. Fast 2D rendering via OpenGL or QPainter |
| **Integration** | PySide6-compatible. Would require new adapter layer for VTKWidget |
| **Dependency** | New dependency (~5MB). Pulls in pyopengl |
| **Measurement tools** | Has ROI tools but they don't match the existing medical measurement requirements (mm units, DICOM geometry) |
| **Progressive display** | Would need custom `grow()` integration |
| **Risk** | Introduces an entirely new rendering stack. Every tool, overlay, and interaction needs re-wiring |
| **Verdict** | **NOT RECOMMENDED** — solving a problem that's already solved |

### Candidate B: Qt-native (QImage/QGraphicsView/QPainter)

| Dimension | Assessment |
|-----------|------------|
| **Rendering** | QPainter-based rendering via QPixmap. Proven ~1-2ms per slice |
| **Integration** | **Already integrated** as `pydicom_qt` backend |
| **Dependency** | Zero new dependencies — PySide6 already required |
| **Measurement tools** | **Already implemented** — full ruler/angle/ROI/arrow/text/eraser via `ToolController` + `QPainterToolRenderer` |
| **Progressive display** | **Already implemented** — `refresh_file_list()` + `grow()` on `QtViewerBridge` |
| **Risk** | Minimal — existing code, existing tests, existing integration |
| **Verdict** | **RECOMMENDED** — complete what's already built |

### Why pyqtgraph is unnecessary

The user's original proposal was based on the assumption that FAST mode has no VTK-free rendering path. **This is incorrect.** The codebase already contains:

1. **`QtSliceViewer`** (~900 lines) — QPainter-based 2D viewer  
2. **`Lightweight2DPipeline`** (~900 lines) — VTK-free decode+filter+W/L+QImage pipeline  
3. **`QtViewerBridge`** (~900 lines) — drop-in adapter implementing the full `ImageViewer2D` API  
4. **`ToolController` + `QPainterToolRenderer`** — VTK-free measurement tools  
5. **`CoordinateResolver`** — VTK-free DICOM geometry transforms  

**~3600 lines of VTK-free FAST rendering code already exist and are integrated.**

Introducing pyqtgraph would:
- Add a new dependency where none is needed
- Require writing adapter code that already exists in `QtViewerBridge`
- Require re-implementing measurement tools that already work in the Qt tool system
- Not address the actual remaining work (backend selection, VTKWidget refactoring)

---

## 3. Existing `pydicom_qt` Feature Completeness

### Fully working (VTK-free)

| Feature | Component | Status |
|---------|-----------|--------|
| 2D image display | `QtSliceViewer` (QPainter) | ✅ |
| Window/Level (mouse drag + presets) | `QtSliceViewer` + `QtViewerBridge` | ✅ |
| Zoom (wheel, drag, zoom-to-fit) | `QtSliceViewer` | ✅ |
| Pan (middle-button, Ctrl+Left) | `QtSliceViewer` | ✅ |
| Slice scrolling | `QtSliceViewer` → signal → bridge | ✅ |
| Corner annotations (all 4 corners) | `CornerAnnotations` in `QtSliceViewer` | ✅ |
| Measurement tools (ruler, angle, ROI, etc.) | `ToolController` + `QPainterToolRenderer` | ✅ |
| DICOM geometry (IPP/IOP ↔ patient) | `CoordinateResolver` + `Lightweight2DPipeline` | ✅ |
| Cross-viewer sync point | `QtViewerBridge.set_sync_point()` | ✅ |
| Progressive download (grow/refresh) | `QtViewerBridge.grow()` + `pipeline.refresh_file_list()` | ✅ |
| OpenCV image filter | `pooyan_filter_center` in pipeline | ✅ |
| Background prefetch | `ThreadPoolExecutor` in pipeline | ✅ |
| Drag-and-drop forwarding | Event forwarding to VTKWidget parent | ✅ |
| Rotation/flip | `_rotation_angle`, `_flip_h`, `_flip_v` | ✅ |
| Reference lines | `_overlay_lines` via QPainter | ✅ |

### Missing (by design — Advanced-only features)

| Feature | Status | Impact on FAST |
|---------|--------|---------------|
| Curved MPR | Stubbed (`_CurvedMPRStub`) | None — Advanced feature only |
| 3D volume rendering | N/A | None — Advanced feature only |
| MIP/MinIP/Thick Slab | N/A | None — Advanced feature only |
| Segmentation overlays | Not in FAST | Potential future work |

### Residual VTK dependency (the actual work remaining)

**The sole remaining VTK dependency in FAST mode is architectural, not functional:**

`VTKWidget` inherits `QVTKRenderWindowInteractor` — even in `pydicom_qt` mode, the VTK render window is created but never rendered to. The `QtSliceViewer` widget is stacked on top of it. This means:

1. VTK libraries are loaded at import time (~200ms)
2. A VTK render window is allocated but unused
3. `vtkImageData` stubs are created for cache compatibility

---

## 4. What the `pydicom_2d` → `pydicom_qt` Consolidation Requires

### 4.1 Items that are already done (from current Qt path)

- Full `ImageViewer2D` API adapter (`QtViewerBridge`)
- All mock VTK objects (camera, renderer, reslice, image data)
- Tool system (ruler, angle, ROI, arrow, text, eraser)
- Corner annotations
- Coordinate resolution (image↔patient space)
- Progressive display support
- W/L adjustment
- Zoom/pan
- Background prefetch/cache

### 4.2 Items that need work

| Work item | Complexity | Description |
|-----------|-----------|-------------|
| **Backend selection consolidation** | Low | Ensure `pydicom_qt` is the default when FAST mode is configured. Remove `pydicom_2d` fallback logic from `resolve_viewer_backend()` |
| **VTKWidget independence from QVTKRenderWindowInteractor** | Medium | Refactor `VTKWidget` to use a plain `QWidget` in FAST mode, only inheriting VTK base when Advanced is active. Or: create a separate `FastWidget` that is `QWidget`-based |
| **`vtkImageData` stub elimination** | Low | `load_single_series_by_number` creates VTK stubs for cache checks. Replace with metadata-only cache keys |
| **H13 diagnostic probes cleanup** | Low | Remove or guard H13 probes (P1-P5, T3-T6) behind env vars. They reference VTK internals |
| **VTK import elimination** | Medium | Remove VTK imports from FAST-path modules. Currently loaded at widget.py module level |
| **`pydicom_lazy_volume.py` retirement** | Low | Mark as Advanced-only or remove from FAST path. The lazy VTK volume is not needed when Qt renders directly from DICOM |
| **`_decode_guard.py` cleanup** | Low | H13 diagnostic module — only needed for VTK path |
| **Testing** | Medium | Verify all FAST scenarios work exclusively through `pydicom_qt`. Run all existing tests |

### 4.3 Items that are NOT needed (things we don't have to build)

- ❌ A new rendering library (pyqtgraph, matplotlib, etc.)
- ❌ A new measurement tool system
- ❌ A new W/L adjustment system
- ❌ A new coordinate transform system
- ❌ A new progressive display integration
- ❌ A new drag-drop handler
- ❌ A new annotation system

---

## 5. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| `pydicom_qt` has undiscovered feature gaps when used exclusively | Low | Medium | Existing usage as active backend + existing tests validate core features |
| Advanced mode tools leak into FAST mode expectations | Low | Low | Clear backend check at every entry point |
| VTKWidget refactoring breaks Advanced mode | Medium | High | Phase the work: first make `pydicom_qt` default, then refactor VTKWidget later |
| Performance regression vs VTK Render() | Very Low | Low | `pydicom_qt` is already faster (~1-2ms vs 8-50ms). No regression expected |
| Memory regression (removing VTK object pool) | Low | Low | Removing VTK objects should reduce memory. Pipeline has its own LRU caches |

---

## 6. Recommendation

**Do NOT add pyqtgraph or any new rendering dependency.**

**Instead:**
1. Make `pydicom_qt` the exclusive FAST backend (configuration change)
2. Remove `pydicom_2d` from the FAST backend selection path
3. Phase the VTKWidget refactoring as a separate, later step
4. Keep VTK for Advanced mode only

This approach:
- Eliminates the H13 crash class entirely (no VTK in FAST path)
- Has minimal code risk (completing existing code, not writing new)
- Requires no new dependencies
- Has a clear rollback point (v2.3.2)
- Can be done incrementally
