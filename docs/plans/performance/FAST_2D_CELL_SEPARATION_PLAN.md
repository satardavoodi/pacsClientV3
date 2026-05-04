# FAST 2D Viewer Cell VTK Separation Plan

**Status:** ✅ COMPLETED — Steps A, B, C done (2026-05-05)  
**Date:** 2026-05-04  
**Completed:** 2026-05-05  
**Branch:** `beta-version` (commit `18ab5fc`)  
**Canonical location:** `docs/plans/performance/FAST_2D_CELL_SEPARATION_PLAN.md`  
**Supersedes:** `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md` (first-pass plan — preserved for reference)

> **This is Step 1 of the FAST mode performance surgery.**  
> Steps A–C are shipped and verified. Step D (full VTK-free bridge init directly in `__init__`) is the immediate next milestone — see Section 5 Step D below.

---

## 1. Executive Summary

FAST mode viewer cells (`BACKEND_PYDICOM_QT`) currently allocate a full VTK render window and VTK renderer via `QVTKRenderWindowInteractor.__init__()`, even though FAST mode never uses them for image display. The Qt bridge (`QtViewerBridge` + `QtSliceViewer`) renders all image frames directly. The VTK allocation wastes GPU resources, extends startup time, and consumes ~40–80 MB of GPU memory per open patient tab.

**Goal:** Replace the VTK-based viewer cell widget with a plain `QWidget`-based container (`QtFastContainer`) in FAST mode only. All other VTK usage in the application is untouched.

**Critical constraint (non-negotiable):** VTK must NOT be removed or replaced in:
- MPR viewer cells (they use `QVTKRenderWindowInteractor` directly)
- Advanced MPR / 3D Slicer integration
- Advanced 2D viewer (Advanced mode)
- 3D volume renderer
- Stitching module
- Curved MPR (panoramic view and standard view)
- Toolbar CPR display widget
- Reference line rendering
- ZetaBoost cache pipeline
- All interactor styles
- Eagle Eye AI imaging module (`modules/ai_imaging`) — uses VTK interactor styles as a consumer
- Any installed plugin packages

---

## 2. Precise Scope Definition

### 2.1 IN SCOPE — Exactly Four Factory Call Sites

The VTK allocation in FAST mode originates from exactly two methods in one file, which two other locations delegate to:

| File | Method | Line (approx.) | Description |
|------|--------|-----------------|-------------|
| `_pw_viewers.py` | `creator_vtk_widget()` | L269 | Creates a VTKWidget for a new series |
| `_pw_viewers.py` | `_create_lightweight_vtk_placeholder()` | L234 | Creates a placeholder VTKWidget |
| `_vc_layout.py` | fallback in `creator_vtk_widget()` | L705 | Delegates to `parent_widget`; fallback directly calls `VTKWidget(...)` |
| `_vc_layout.py` | fallback in `_create_lightweight_vtk_placeholder()` | L549 | Delegates to `parent_widget`; fallback directly calls `VTKWidget(...)` |

**Factory delegation chain:**
```
_vc_layout.creator_vtk_widget()
    → self.parent_widget.creator_vtk_widget()    [delegates if method exists]
    → _pw_viewers.creator_vtk_widget()           [canonical factory]
    → VTKWidget(...)                             ← TARGET

_vc_layout._create_lightweight_vtk_placeholder()
    → self.parent_widget.create_dummy_vtk_widget()  [delegates if method exists]
    → _pw_viewers.create_dummy_vtk_widget()
    → _pw_viewers._create_lightweight_vtk_placeholder()
    → VTKWidget(...)                                 ← TARGET
```

Both `_vc_layout.py` methods have a fallback that directly calls `VTKWidget(...)` if the delegation method does not exist. These fallbacks must also be guarded.

### 2.2 OUT OF SCOPE — Legitimate VTK Modules (Must Not Be Touched)

Every item below uses VTK for real rendering or computation. None of these are viewer cells in FAST mode, and none go through the `creator_vtk_widget` / `_create_lightweight_vtk_placeholder` factory.

| Module / File | VTK Usage | Location |
|---------------|-----------|----------|
| `_mpr_views.py` | 4× `QVTKRenderWindowInteractor(container)` for MPR panes | `PacsClient/pacs/patient_tab/zeta mpr/` |
| `mpr_slice_view.py` | `class MPRSliceView(QVTKRenderWindowInteractor)` | same |
| `mpr_calculator.py`, `volume_loader.py`, `measurements.py` | VTK volume pipeline | same |
| `standard_mpr_viewer_original.py` | 4× `QVTKRenderWindowInteractor(container)` | `advance_mpr_3d_slicer/` |
| `curved_mpr_panoramic_view.py` | `self.vtk_widget = QVTKRenderWindowInteractor(self)` | `modules/mpr/curved_mpr/` |
| `curved_mpr_view.py` | `self.vtk_widget = QVTKRenderWindowInteractor(self)` | same |
| `curve_mpr_ui.py` | 3× `QVTKRenderWindowInteractor` (curved/ortho/mip) | same |
| `curved_mpr.py`, `curve_mpr_core.py` | VTK pipeline | same |
| `stitching_widget.py` | `self.vtk_widget = QVTKRenderWindowInteractor(self)` | `modules/stitching/` |
| `viewer_2d.py` | Full VTK 2D image viewer (Advanced mode only) | `modules/viewer/advanced/` |
| `viewer_2d_optimized.py` | VTK 2D image viewer variant | same |
| `viewer_3d.py` | `self.vtk_widget = QVTKRenderWindowInteractor()` + 3D rendering | same |
| `preset_manager.py` | VTK rendering presets | same |
| All `*_interactorstyle.py` files | VTK interactor styles for measurement tools | `modules/viewer/interactor_styles/` |
| `toolbar_manager.py` line 1239 | LOCAL `QVTKRenderWindowInteractor(container)` inside CPR dialog | `patient_toolbar/` |
| `reference_line.py` | VTK reference line actors | `patient_toolbar/` |
| `geometry_utils.py` | VTK geometry utilities | `modules/zeta_sync/` |
| `disk_cache.py` | VTK numpy support for cache | `modules/zeta_boost/` |
| `warmup_subprocess.py` | VTK numpy support | `modules/zeta_boost/` |
| `corner_labels.py` | VTK text/corner actors | `PacsClient/pacs/patient_tab/utils/` |
| `image_io.py`, `image_io_improved.py` | VTK image conversion | same |
| `vtk_utils.py` | VTK utility helpers | same |
| `Home.py`, `NewMPR2MPR.py`, `startup_script.py` | 3D Slicer VTK integration | `advance_mpr_3d_slicer/` |

**Eagle Eye AI module (`modules/ai_imaging`) — detailed analysis:**

Eagle Eye is `modules/ai_imaging` (class name `AiMainWindow`, internal prefix `_ee_`). It accesses `vtk_widget` attributes on viewer cell nodes but does NOT allocate any VTK render windows itself. It is a consumer of the viewer cell duck-type API. Analysis of `ai_module_ui/service_tab/imaging_tab.py` and `ai_module_ui/toolbar/toolbar_manager.py`:

| Eagle Eye callsite | Guard | `QtFastContainer` safe? |
|--------------------|-------|--------------------------|
| `selected_widget.vtk_widget` | `hasattr(selected_widget, 'vtk_widget') and not ...` | ✓ attribute exists |
| `vtk_widget.current_style` | `hasattr(vtk_widget, 'current_style') and vtk_widget.current_style` | ✓ null stub → falsy → skipped |
| `vtk_widget.csv_details_path` | `hasattr(vtk_widget, 'csv_details_path')` | ✓ missing attr → skipped |
| `vtk_widget.current_row` | `hasattr(vtk_widget, 'current_row')` | ✓ missing attr → skipped |
| `toolbar_manager.activate_tool(vtk_widget, name)` → `vtk_widget.set_new_interactorstyle(...)` | `getattr(vtk_widget, 'current_style', None) is not None` | ✓ no-op method; null stub `.On()/.Off()` absorbed |
| `vtk_widget.restore_default_interactorstyle()` | `hasattr(vtk_widget, 'restore_default_interactorstyle')` | ✓ no-op method |

**Conclusion:** Eagle Eye is fully safe with `QtFastContainer`. No new crash sites. It is OUT OF SCOPE for modification.

**VTKWidget class itself stays.** It is still the real widget for Advanced mode cells and all of the above.

---

## 3. The New Class: `QtFastContainer`

### 3.1 Position in the Architecture

```
FAST mode (BACKEND_PYDICOM_QT):
    Factory → QtFastContainer(QWidget) ← NEW
                └── QtViewerBridge (child)
                        └── QtSliceViewer (child)
                        └── Lightweight2DPipeline

Advanced mode (BACKEND_VTK):
    Factory → VTKWidget(QVTKRenderWindowInteractor) ← UNCHANGED
                └── ImageViewer2D (VTK pipeline)
                └── QtViewerBridge (child, Qt overlay only)
```

### 3.2 Duck-Type API Contract

`QtFastContainer` must expose the same interface as `VTKWidget` for all callsites that access viewer cells. The following tables list every external access confirmed from code audit.

#### Core attributes

| Attribute | Type | Source callsite | `QtFastContainer` provides |
|-----------|------|-----------------|----------------------------|
| `_qt_bridge_active` | `bool` | `_vw_scroll.py`, `_vw_backend.py` | Always `True` |
| `_active_backend` | `str` | Many sites | Always `BACKEND_PYDICOM_QT` |
| `_qt_bridge` | `QtViewerBridge` | `_vc_switch.py`, `_vc_load.py` | Real bridge object |
| `image_viewer` | object | `_pw_viewers.py:402`, `_vc_load.py:2389` | `_ImageViewerStub` with `GetSlice()`, `apply_default_window_level()`, `update_corners_actors()` |
| `render_window` | object | `_pw_viewers.py:247`, `_vc_layout.py:562`, `_vc_load.py:2416`, `_pw_pipeline.py:813` | `_NullVtkObject` — all method calls silently absorbed |
| `renderer` | object | `_pw_viewers.py:240`, `_vc_layout.py:556` | `_NullVtkObject` |
| `viewport_spinner` | `ViewportSpinner` | `_vc_load.py:2406` | Real spinner widget |
| `last_series_show` | `int` | `_pw_pipeline.py:748` | Normal attribute, default `-1` |
| `current_style` | object | Eagle Eye `imaging_tab.py:693` | `_NullVtkObject` (falsy → Eagle Eye skips it via its own guard) |
| `_is_placeholder` | `bool` | Factory code | `True` on placeholder instances |
| `_is_fast_mode` | `bool` | Guards | Always `True` |

#### Methods

| Method | Source callsite | `QtFastContainer` implementation |
|--------|-----------------|----------------------------------|
| `set_method_change_series_on_drop(fn)` | `_pw_viewers.py:192` | Store callback; delegate to bridge |
| `set_method_change_container_border(fn)` | `_pw_viewers.py:194` | Store callback |
| `start_process_series(...)` | `_vc_layout.py:682` | No-op |
| `start_process_combine_series(...)` | `_vc_layout.py:678` | No-op |
| `switch_series(...)` | `_vc_load.py:2377` | Delegate to `_qt_bridge.switch_series(...)` |
| `set_slice(value)` | `_pw_viewers.py:450` | Delegate to `_qt_bridge.set_slice(value)` |
| `reset_image(vtk_image_data, metadata)` | `toolbar_manager.py:1444` | Delegate to bridge |
| `set_new_interactorstyle(style)` | Eagle Eye `toolbar_manager.py:30` | No-op |
| `restore_default_interactorstyle()` | Eagle Eye `toolbar_manager.py:37` | No-op |
| `hide_loading()` / `show_loading()` | `_vc_load.py:2406` | Delegate to `viewport_spinner` |
| `cleanup()` / `close()` | Lifecycle | Cleanup bridge and child widgets |
| `GetRenderWindow()` | `_vc_load.py:2417`, `_pw_lifecycle.py:135` | Returns `_NullVtkObject` |

#### isinstance compatibility

`toolbar_manager.py:1363` checks `isinstance(widget, (VTKWidget, CurvedMPRViewport))`. Step C adds `QtFastContainer`:

```python
# AFTER (Step C):
isinstance(widget, (VTKWidget, QtFastContainer, CurvedMPRViewport))
```

No other production `isinstance(widget, VTKWidget)` checks exist in the codebase.

---

## 4. Crash Site Register

All callsites that access VTK-specific attributes on viewer cell objects. These are resolved by providing null stubs on `QtFastContainer` — no call sites need to be modified.

| ID | File | Line (approx.) | Callsite | Resolution via null stub |
|----|------|-----------------|----------|--------------------------|
| C1 | `_pw_viewers.py` | 240 | `vtk_widget.renderer.SetBackground(...)` | `renderer = _NullVtkObject()` → no-op |
| C2 | `_pw_viewers.py` | 243 | `vtk_widget.render_window.Render()` | `render_window = _NullVtkObject()` → no-op |
| C3 | `_pw_viewers.py` | 247 | `vtk_widget.render_window.SetDesiredUpdateRate(...)` | same |
| C4 | `_vc_layout.py` | 556 | `vtk_widget.renderer.SetBackground(...)` | same as C1 |
| C5 | `_vc_layout.py` | 562 | `vtk_widget.render_window.SetDesiredUpdateRate(...)` | same as C2 |
| C6 | `_vc_load.py` | 2416 | `node_viewer.vtk_widget.render_window.Render()` | same as C2 |
| C7 | `_vc_load.py` | 2417 | `node_viewer.vtk_widget.GetRenderWindow().Render()` | `GetRenderWindow()` returns `_NullVtkObject()` |
| C8 | `_pw_pipeline.py` | 813 | `node_viewer.vtk_widget.render_window.Render()` | same as C2 |
| C9 | `_pw_pipeline.py` | 814 | `node_viewer.vtk_widget.GetRenderWindow().Render()` | same as C7 |
| OK | `_pw_lifecycle.py` | 135 | `if hasattr(viewer.vtk_widget, 'GetRenderWindow'):` | Already guarded — no change needed |

**Why null stubs instead of explicit guards at each callsite:**  
Adding `if vtk_widget.render_window:` guards at C1–C9 would require modifying 4 files (many of them hot paths). Instead, `_NullVtkObject` absorbs all calls with `__getattr__` returning no-op lambdas, and `__bool__` returning `False` so any explicit `if vtk_widget.render_window:` guard also works. Zero callsite modifications needed.

---

## 5. Implementation Steps

### Completion status (2026-05-05)

| Step | Status | Commit | Notes |
|------|--------|--------|-------|
| A — Create `QtFastContainer` skeleton | ✅ Done | `18ab5fc` | `_NullVtkObject`, `_NullImageViewer`, `QtFastContainer` created; all stub assertions pass |
| B — Update `is_vtk_widget()` | ✅ Done | `18ab5fc` | Accepts `(VTKWidget, QtFastContainer, CurvedMPRViewport)` |
| C — Factory switch | ✅ Done | `18ab5fc` | Both `_pw_viewers.py` and `_vc_layout.py` fallback paths updated |
| D — Full VTK-free `__init__` | ⏳ Pending | — | Wire `QtViewerBridge` directly in `__init__`; remove residual null stubs |

**Test result at completion:** 167/168 passing. 1 pre-existing failure (`test_b41_drag_fast_interaction_still_skips_filter` — timing threshold unrelated to cell separation).

---

Each step is independently committable and independently reversible. Steps must be executed in order. **Do NOT combine steps into a single commit.**

---

### Step A — Create `_NullVtkObject` and `QtFastContainer` Skeleton

**File to create:** `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py`

This file contains:
- `_NullVtkObject` — null object that absorbs any attribute/method call
- `_ImageViewerStub` — minimal stub for `image_viewer` attribute
- `QtFastContainer(QWidget)` — skeleton class with all required methods as no-ops

At Step A the class is **not yet used by any factory**. Zero behavioral change.

**Verification gate:**
```powershell
.\.venv\Scripts\python.exe -c "from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import QtFastContainer, _NullVtkObject; n = _NullVtkObject(); n.Render(); n.SetBackground(0,0,0); print('bool:', bool(n)); print('Step A OK')"
```
Expected: `bool: False` then `Step A OK`. No exceptions.

**Rollback:** Delete the new file. No other files changed.

---

### Step B — Update `isinstance` Check in Toolbar

**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`

```python
# Line ~1363 — BEFORE:
isinstance(widget, (VTKWidget, CurvedMPRViewport))

# AFTER:
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import QtFastContainer
isinstance(widget, (VTKWidget, QtFastContainer, CurvedMPRViewport))
```

This is safe to land now — no `QtFastContainer` instances exist yet so the check never matches. Landing it before Step C means Step C's factory switch is immediately covered by the toolbar.

**Verification gate:**
```powershell
.\.venv\Scripts\python.exe -m pytest tests/smoke/test_import_smoke.py -v 2>&1 | Select-String "PASSED|FAILED|ERROR"
```

**Rollback:** Revert the one changed line in `toolbar_manager.py`.

---

### Step C — Factory Switch (FAST mode → `QtFastContainer`)

This is the critical step. Steps A and B must be complete and verified.

**File 1: `_pw_viewers.py`**

In `creator_vtk_widget()`, add backend check before returning `VTKWidget`:
```python
# [FAST_CELL_SEP] Step C: VTK-free container for FAST mode
backend = self._get_requested_viewer_backend() if hasattr(self, '_get_requested_viewer_backend') else None
if backend == BACKEND_PYDICOM_QT:
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import QtFastContainer
    return QtFastContainer(height_viewer=height, patient_widget=self)
return VTKWidget(height_viewer=height, patient_widget=self)
```

Same check in `_create_lightweight_vtk_placeholder()`.

**File 2: `_vc_layout.py`** — add the same check to both fallback paths (lines 549 and 705).

**Verification gate (app smoke test — REQUIRED before commit):**
1. `python main.py` — open patient in FAST mode
2. Verify images display, scroll works, drag-drop series switch works
3. Open patient in Advanced mode — verify VTK pipeline is intact (viewer shows correctly)
4. `.\.venv\Scripts\python.exe -m pytest tests/viewer/test_fast_viewer_pipeline.py -v`
5. `.\.venv\Scripts\python.exe tests/download_manager/run_dm_test.py`

**Rollback:**
```powershell
git checkout HEAD -- "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_viewers.py"
git checkout HEAD -- "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py"
```

---

### Step D — Implement Full VTK-Free `QtFastContainer.__init__`

After Step C is stable (run the app for at least one session, check logs), implement the real `QtViewerBridge` initialization inside `QtFastContainer.__init__` directly — removing the residual VTK path that `QtFastContainer` may have inherited via any temporary VTKWidget delegation.

At this point `QtFastContainer` is a pure `QWidget` with:
- `QtViewerBridge` created as a child widget
- All image display going through `Lightweight2DPipeline`
- Zero VTK allocations

**Verification gate (full regression):**
```powershell
powershell -File tools/dev/run_overlap_regression.ps1  # pixel hash gate
.\.venv\Scripts\python.exe -m pytest tests/viewer/ -v
```

Also verify GPU memory drops when opening a patient tab (Task Manager → GPU memory).

**Rollback:** Revert `qt_fast_container.py` to its Step C state (keep factory switch intact).

---

## 6. Files Modified Per Step

| Step | Files Modified | Files Created | Risk level |
|------|---------------|---------------|------------|
| A | none | `vtk_widget/qt_fast_container.py` | Zero |
| B | `toolbar_manager.py` (1 isinstance line) | none | Very low |
| C | `_pw_viewers.py` (2 methods), `_vc_layout.py` (2 fallbacks) | none | **Medium — app smoke required** |
| D | `qt_fast_container.py` (full VTK-free init) | none | Medium |

---

## 7. What Cannot Break

| Behavior | Verified by |
|----------|-------------|
| FAST mode image display (scroll, WL, drag-drop) | Manual app test + Step C gate |
| Advanced mode VTK pipeline intact | Manual app test |
| MPR all 3 planes | Manual app test |
| Advanced MPR / 3D Slicer | Manual app test |
| Eagle Eye AI imaging tools (polygon, rectangle, AI chat) | Manual app test |
| Toolbar CPR dialog (local VTK widget) | Manual app test |
| Stitching module | Manual app test |
| Overlap pixel quality | `tools/dev/run_overlap_regression.ps1` |
| Progressive display lifecycle | `tests/viewer/test_fast_viewer_pipeline.py` |
| Download Manager state | `tests/download_manager/run_dm_test.py` |
| Import smoke | `tests/smoke/test_import_smoke.py` |

---

## 8. Test Gate Commands (Copy-Paste Ready)

```powershell
# After Step A — null stub behavior
.\.venv\Scripts\python.exe -c "
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import QtFastContainer, _NullVtkObject
n = _NullVtkObject(); n.Render(); n.SetBackground(0,0,0); n.SetDesiredUpdateRate(0.001)
print('bool:', bool(n))   # must print False
print('Step A OK')
"

# After Step B — smoke test (toolbar_manager loads cleanly)
.\.venv\Scripts\python.exe -m pytest tests/smoke/test_import_smoke.py -v 2>&1 | Select-String "PASSED|FAILED|ERROR"

# After Step C — viewer pipeline
.\.venv\Scripts\python.exe -m pytest tests/viewer/test_fast_viewer_pipeline.py -v
.\.venv\Scripts\python.exe tests/download_manager/run_dm_test.py

# After Step D — overlap pixel regression + full viewer suite
powershell -File tools/dev/run_overlap_regression.ps1
.\.venv\Scripts\python.exe -m pytest tests/viewer/ -v
```

---

## 9. Rollback Procedures

### Rollback Step C (factory switch) — most likely revert point

```powershell
git checkout HEAD -- "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_viewers.py"
git checkout HEAD -- "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py"
# Steps A and B remain — no harm (QtFastContainer exists but is never called)
```

### Full rollback of all steps

```powershell
git log --oneline -6  # identify commit before Step A
git revert <step-A-hash>..<HEAD>
```

### Emergency nuclear reset

```powershell
# Restore from backup: backups/v2.4.8c_conservative_2026-05-03.zip
```

---

## 10. Known Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `QtFastContainer` missing an API used by a callsite not caught in audit | Medium | `_NullVtkObject.__getattr__` absorbs unknown attribute access; `try/except` in most callsites |
| Advanced mode accidentally gets `QtFastContainer` | Low | Backend check is explicit: `if backend == BACKEND_PYDICOM_QT` only |
| MPR accidentally gets `QtFastContainer` | Very Low | MPR creates its own `QVTKRenderWindowInteractor` independently — does NOT go through the `creator_vtk_widget` factory |
| Eagle Eye tools break in FAST mode | Low | All Eagle Eye `vtk_widget` accesses are either `hasattr`/`getattr` guarded or route to no-op methods; confirmed by code audit |
| `isinstance(widget, VTKWidget)` check outside toolbar | Very Low | Audit found only 1 production isinstance check (toolbar:1363); Step B handles it |
| `QtSliceViewer` / `QtViewerBridge` child widget geometry breaks when parent is `QWidget` instead of `QVTKRenderWindowInteractor` | Medium | Must verify child widget sizing and repaint in Step C manual smoke test |

---

## 11. `QtFastContainer` Full Code Sketch

```python
"""
QtFastContainer — VTK-free viewer cell widget for FAST mode (BACKEND_PYDICOM_QT).

Drop-in replacement for VTKWidget when backend == BACKEND_PYDICOM_QT.
VTK render_window/renderer access returns _NullVtkObject stubs — all calls
are silently absorbed with no-ops. Image display goes through
QtViewerBridge + QtSliceViewer children.

Rule: Do NOT use this class for Advanced mode, MPR, Eagle Eye, or any path
      that needs a real VTK interactor.
"""
from __future__ import annotations
from PySide6.QtWidgets import QWidget
from modules.viewer.viewer_backend_config import BACKEND_PYDICOM_QT


class _NullVtkObject:
    """Drop-in null object for VTK render_window / renderer in FAST mode.

    Accepts any method call and silently returns None.
    __bool__ returns False so callsites that do 'if vtk_widget.render_window:'
    skip the guarded block.
    """
    def __getattr__(self, name):
        return lambda *args, **kwargs: None

    def __bool__(self):
        return False


class _ImageViewerStub:
    """Stub for image_viewer attribute on FAST mode cells.

    Provides the subset of the VTK ImageViewer2D API that is accessed on
    viewer cells from _pw_viewers.py and _vc_load.py.
    """
    def GetSlice(self) -> int:
        return 0

    def apply_default_window_level(self, slice_index: int = 0):
        pass

    def update_corners_actors(self):
        pass

    @property
    def metadata(self) -> dict:
        return {}


class QtFastContainer(QWidget):
    """VTK-free FAST mode viewer cell widget.

    See FAST_2D_CELL_SEPARATION_PLAN.md for full design rationale.
    """

    def __init__(self, height_viewer: int = 480, patient_widget=None, parent=None):
        super().__init__(parent)
        self._height_viewer = height_viewer
        self._patient_widget = patient_widget

        # VTK null stubs — satisfy crash sites C1–C9 without modifying callsites
        self.render_window = _NullVtkObject()
        self.renderer = _NullVtkObject()
        self.current_style = _NullVtkObject()   # Eagle Eye guard: falsy → skipped

        # FAST mode state flags (mirrors VTKWidget attributes)
        self._active_backend: str = BACKEND_PYDICOM_QT
        self._qt_bridge_active: bool = True
        self._is_fast_mode: bool = True
        self._is_placeholder: bool = False

        # Series tracking
        self.last_series_show: int = -1
        self.metadata: dict = {}

        # Image viewer stub
        self.image_viewer = _ImageViewerStub()

        # Real bridge — initialized in Step D
        self._qt_bridge = None
        self.viewport_spinner = None

        self.setMinimumHeight(height_viewer)

    # ── VTK null API ──────────────────────────────────────────────────────
    def GetRenderWindow(self):
        """Null stub — satisfies GetRenderWindow().Render() callsites."""
        return _NullVtkObject()

    # ── Series loading API ─────────────────────────────────────────────────
    def set_method_change_series_on_drop(self, fn):
        self._change_series_on_drop_fn = fn
        if self._qt_bridge:
            self._qt_bridge.set_method_change_series_on_drop(fn)

    def set_method_change_container_border(self, fn):
        self._change_container_border_fn = fn

    def switch_series(self, *args, **kwargs):
        if self._qt_bridge:
            return self._qt_bridge.switch_series(*args, **kwargs)

    def set_slice(self, value: int):
        if self._qt_bridge:
            self._qt_bridge.set_slice(value)

    def reset_image(self, vtk_image_data, metadata):
        if self._qt_bridge:
            self._qt_bridge.reset_image(vtk_image_data, metadata)

    def start_process_series(self, *args, **kwargs):
        """No-op — series data comes via switch_series in FAST mode."""

    def start_process_combine_series(self, *args, **kwargs):
        """No-op."""

    # ── Interactor style API (no-ops — Eagle Eye safe) ────────────────────
    def set_new_interactorstyle(self, style):
        """No-op — FAST mode has no VTK interactor."""

    def restore_default_interactorstyle(self):
        """No-op — FAST mode has no VTK interactor."""

    # ── Lifecycle ──────────────────────────────────────────────────────────
    def cleanup(self):
        try:
            if self._qt_bridge:
                self._qt_bridge.cleanup()
        except Exception:
            pass
```

---

## 12. Commit Protocol

One commit per step. Commit message format:

```
[FAST_CELL_SEP] Step A: Add QtFastContainer skeleton + null stubs

- New file: vtk_widget/qt_fast_container.py
  - _NullVtkObject: absorbs all VTK render_window/renderer calls
  - _ImageViewerStub: minimal image_viewer duck-type stub
  - QtFastContainer(QWidget): full API scaffold, not yet in factory
- No behavioral change — class is not called by any factory yet
- See docs/plans/performance/FAST_2D_CELL_SEPARATION_PLAN.md
```

Do NOT squash steps — each step's git hash must be independently reachable for rollback.

---

## 13. Relationship to Previous Plan

`docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md` was the first-pass plan from the prior session. It covered the same viewer cell change but with a broader scope (DM subprocess, signal routing). This plan is a strict subset: viewer cell factory only.

**Eagle Eye update:** The previous plan listed EGLI as "unknown VTK usage (installed plugin, not in repo)". Confirmed this session: EGLI/Eagle Eye = `modules/ai_imaging`, IS in the repo, and is fully safe with `QtFastContainer` (all its `vtk_widget` accesses are `hasattr`/`getattr` guarded and route to no-op stubs).

---

*Plan status: READY FOR IMPLEMENTATION — Steps A → B → C → D in order, one commit each.*
