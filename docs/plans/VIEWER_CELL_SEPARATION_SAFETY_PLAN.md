# Viewer-Cell Separation — Comprehensive Safety Plan
**Date:** 2026-05-05  
**Branch:** `beta-version` (commit `18ab5fc`)  
**Previous attempt result:** Catastrophic — required full code re-download. Root cause: incomplete API contract + missing call-site guards + simultaneous multi-phase execution.  
**Approach:** This plan sequences every sub-step, identifies every dependency surface, specifies every guard, and defines rollback at each commit boundary.

> ✅ **Phase P1 (Viewer-Cell Separation) is COMPLETE as of 2026-05-05.**  
> See `docs/plans/performance/FAST_2D_CELL_SEPARATION_PLAN.md` for the authoritative spec and completion record.  
> Phases P2–P7 below remain the planned next steps of the performance surgery.

---

## Table of Contents
1. [Codebase Truth (What Exists Today)](#1-codebase-truth-what-exists-today)  
2. [Why the Previous Attempt Failed](#2-why-the-previous-attempt-failed)  
3. [Phase P1 — Viewer-Cell Separation](#3-phase-p1--viewer-cell-separation)  
4. [Phase P2 — Catalog Service](#4-phase-p2--catalog-service)  
5. [Phase P3 — DM Control-Plane Subprocess](#5-phase-p3--dm-control-plane-subprocess)  
6. [Phase P4 — DM UI Rate Limiting](#6-phase-p4--dm-ui-rate-limiting)  
7. [Phase P5 — CPU Budget File](#7-phase-p5--cpu-budget-file)  
8. [Phase P6 — Signal Routing](#8-phase-p6--signal-routing)  
9. [Phase P7 — Architecture Tests](#9-phase-p7--architecture-tests)  
10. [Implementation Schedule](#10-implementation-schedule)  
11. [Test Gates](#11-test-gates)

---

## 1. Codebase Truth (What Exists Today)

### 1.1 What does NOT exist yet (plan is 100% greenfield)
- No `qt_fast_container.py` anywhere in the tree
- No `QtFastContainer` class
- `_create_lightweight_vtk_placeholder()` in BOTH `_vc_layout.py` AND `_pw_viewers.py` still constructs a real `VTKWidget(QVTKRenderWindowInteractor)`
- `creator_vtk_widget()` in BOTH files still constructs a real `VTKWidget`
- No phase from any submitted plan has been implemented

### 1.2 What DOES exist and is healthy
- `VTKWidget` with 9 mixins — works for both FAST and Advanced mode via `_qt_bridge_active` flag
- `QtViewerBridge` + `QtSliceViewer` + `Lightweight2DPipeline` in `modules/viewer/fast/` — the FAST rendering stack
- All R1–R25 guards already in place in the existing VTKWidget mixins
- `DownloadStateStore` singleton in-process with 14+ direct importers

### 1.3 Import chain health
```
VTKWidget → QVTKRenderWindowInteractor (VTK window allocated in __init__)
QtViewerBridge → (no VTK window — pure Qt)
```
Both import cleanly. The `patient_widget_viewer_controller` module imports OK with venv Python.

---

## 2. Why the Previous Attempt Failed

Reconstructed from codebase archaeology:

**Reason 1 — Incomplete API shim (the core failure)**  
QtFastContainer (or equivalent) was created but did not expose the full 25-method duck-typed VTKWidget API. Every one of the 50+ external callsites that touches `vtk_widget.image_viewer`, `vtk_widget.render_window`, `vtk_widget.renderer`, `vtk_widget.viewport_spinner`, etc. broke with `AttributeError`.

**Reason 2 — No crash-site guards added before factory switch**  
The 6+ direct VTK attribute accesses in `_vc_layout.py`, `_pw_viewers.py`, `_pw_pipeline.py`, `_vc_load.py` (listed fully in §3.4) were never guarded. The moment a QtFastContainer was returned from the factory, any lifecycle event triggered `render_window.Render()` → crash.

**Reason 3 — Multiple phases started simultaneously**  
P1, P2, or P3 code changes were mixed. P3 changes to `state_store.py` broke the in-process import chain across 14+ files. Recovery required full re-download.

**Rule derived from failure:** Every phase is implemented in isolation, gate-tested, committed, and verified on both PCs before the next phase starts. No exceptions.

---

## 3. Phase P1 — Viewer-Cell Separation

### 3.1 What is being moved
In FAST mode (`_selected_backend == BACKEND_PYDICOM_QT`), the viewer cell creation code in:
- `_vc_layout.py:_create_lightweight_vtk_placeholder()` (line ~540)
- `_vc_layout.py:creator_vtk_widget()` (line ~698)
- `_pw_viewers.py:_create_lightweight_vtk_placeholder()` (line ~226)
- `_pw_viewers.py:creator_vtk_widget()` (line ~266)

...currently creates a `VTKWidget(QVTKRenderWindowInteractor)` which allocates a real VTK render window, VTK renderer, and VTK interactor — regardless of mode. This is ~40–80ms overhead per viewer cell and holds GPU/driver resources unnecessarily in FAST mode.

**Target state:** In FAST mode, these factory methods return a `QtFastContainer(QWidget)` instead. Advanced mode creation is **completely unchanged** — it still returns `VTKWidget`.

### 3.2 What replaces it

`QtFastContainer` is a new `QWidget` subclass that:
- Sets `_qt_bridge_active = True` from construction
- Creates a real `ViewportSpinner(self)` (same as VTKWidget does)
- Creates a `QtViewerBridge` internally (becomes `self.image_viewer`)
- Holds a `_NullRenderWindow` no-op mock for `self.render_window`  
- Holds a `_NullRenderer` no-op mock for `self.renderer`
- Exposes all 25 methods/attributes listed in §3.3
- Does NOT allocate any VTK window, renderer, or interactor

**File location:** `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py`

### 3.3 Complete API Contract — Everything QtFastContainer Must Expose

The following table was compiled by auditing every callsite in the controller hierarchy. Every item with a ✳ is a **new finding** vs the previous attempt's analysis.

#### 3.3.1 Direct attributes (read/write from outside)

| Attribute | Type | Notes | Source callsite |
|-----------|------|-------|----------------|
| `image_viewer` | `QtViewerBridge` or `None` | Set in `__init__`, returned for all image operations | `_vc_load.py:2389`, `_vc_switch.py:218`, `_pw_series.py:154`, many more |
| `render_window` | `_NullRenderWindow` (mock) | Needs `.Render()`, `.SetDesiredUpdateRate(x)`, `.SetDoubleBuffer(x)` | `_vc_load.py:2416`, `_pw_pipeline.py:813`, `_vc_layout.py:562`, `_pw_viewers.py:243,247` |
| `renderer` | `_NullRenderer` (mock) | Needs `.SetBackground(r,g,b)` | `_vc_layout.py:556`, `_pw_viewers.py:240` |
| `viewport_spinner` | `ViewportSpinner` | Real spinner; must be constructed in `__init__` | `_vc_load.py:2406`, `_pw_pipeline.py:803`, `_vc_switch.py:462,656` |
| `_qt_bridge_active` | `bool = True` | Must be True at all times on this class | `_vw_series.py`, `_vw_scroll.py`, `_vw_camera.py` |
| `last_series_show` | `str or None` | Read by controller loop to detect what's on screen | `_vc_load.py:2355`, `_pw_pipeline.py:748`, `toolbar_manager.py:1439,1450` |
| `_selected_backend` | `str` | Backend name for checks | `_vc_backend.py`, `_vc_load.py` |
| `_active_backend` | `str` | Active backend name | `_vc_backend.py` |

#### 3.3.2 Methods called from controller files

| Method | Signature | Notes | Source callsite |
|--------|-----------|-------|----------------|
| `switch_series` | `(vtk_image_data, metadata, ...)` → `bool` | Routes to QtViewerBridge | `_vc_load.py:2377`, `_vc_switch.py:936`, `_pw_series.py:140,687` |
| `start_process_series` | `(...)` | Single caller: `viewer_state_controller.py:188` — do NOT add callers | `viewer_state_controller.py:188` |
| `start_process_combine_series` | `(...)` | VTK-specific combine; **no-op in FAST mode** | `_vc_layout.py:678`, `_pw_viewers.py:348` |
| `enter_progressive_mode` | `(total: int, series_number: str)` | Delegates to QtViewerBridge | `_vc_progressive.py:2676`, `_vc_switch.py:988` |
| `exit_progressive_mode` | `()` | Delegates to QtViewerBridge | progressive completion code |
| `update_available_slice_count` | `(avail: int)` | Delegates to QtViewerBridge | `_vc_progressive.py:2677`, `_vc_switch.py:989` |
| `cleanup_image_viewer` | `()` | Calls `image_viewer.cleanup()` if present | `_vc_warmup.py:869`, `_pw_lifecycle.py:265` |
| `cleanup_widget` | `()` | Full widget teardown | lifecycle code |
| `set_slice` | `(value: int)` | Delegates to `image_viewer.set_slice(value)` | `_pw_viewers.py:450` |
| `set_method_change_series_on_drop` | `(method)` | Stores reference for drag-drop | `_vc_layout.py:528`, `_pw_viewers.py:192` |
| `set_method_change_container_border` | `(method)` | Stores reference for border | `_vc_layout.py:530`, `_pw_viewers.py:194` |
| `reset_image` | `(vtk_image_data, metadata)` | Called from toolbar to reset; **no-op in FAST** (FAST uses `switch_series`) | `toolbar_manager.py:1444,1454` |
| `GetRenderWindow` | `()` → `_NullRenderWindow` | Must not crash; returns mock with `Render()`, `GetInteractor()` | `_pw_lifecycle.py:135`, `_pw_pipeline.py:814` |
| `grow` | `()` | B3.8b Layer 2b: delegates to `QtViewerBridge.grow()` | `_vc_progressive.py` (B3.8b path) |
| `set_new_interactorstyle` | `(style_class)` | VTK interactor op; **no-op in FAST mode** ✳ | `toolbar_manager.py:1456` |
| `restore_default_interactorstyle` | `()` | VTK interactor op; **no-op in FAST mode** ✳ | `toolbar_manager.py:1459` |
| `current_style` | attribute | Accessed as `current_style.delete_all_widgets()` ✳ | `toolbar_manager.py:1457` |
| `manage_reference_line` | `(...)` | Reference line management; **no-op in FAST** | `_vw_overlay.py` |
| `apply_default_window_level` | `(slice_idx)` | Delegates to `image_viewer` | `_pw_viewers.py:436` (via image_viewer) |

#### 3.3.3 Methods on `image_viewer` that external code accesses

| Access path | Notes |
|-------------|-------|
| `image_viewer.update_corners_actors()` | Called after series switch — QtViewerBridge must expose this |
| `image_viewer.Render()` | Called at load completion — QtViewerBridge already has a no-op Render |
| `image_viewer.metadata` | Dict; returned by QtViewerBridge |
| `image_viewer.GetSlice()` → `int` | Read from `_pw_viewers.py:402` to get current slice |
| `image_viewer.apply_default_window_level(n)` | Via `_pw_viewers.py:436` |
| `image_viewer.metadata.get('series', {}).get('series_uid')` | Via `_pw_sync.py:190,226` |

#### 3.3.4 _NullRenderWindow mock interface
Must support:
```python
class _NullRenderWindow:
    def Render(self): pass
    def SetDesiredUpdateRate(self, rate): pass
    def SetDoubleBuffer(self, val): pass
    def GetInteractor(self): return self._null_interactor  # returns _NullInteractor
```

#### 3.3.5 _NullInteractor mock interface
Must support:
```python
class _NullInteractor:
    def SetInteractorStyle(self, style): pass
```

#### 3.3.6 _NullRenderer mock interface
Must support:
```python
class _NullRenderer:
    def SetBackground(self, r, g, b): pass
```

#### 3.3.7 current_style mock interface (for no-op calls)
Must support:
```python
class _NullInteractorStyle:
    def delete_all_widgets(self): pass
```
`QtFastContainer.current_style = _NullInteractorStyle()`

### 3.4 Crash Site Registry (Must Be Guarded Before Factory Switch)

These are the sites where calling VTK operations on a non-VTK container WILL crash. Each must be guarded before `QtFastContainer` is ever returned from a factory.

**CRASH SEVERITY: IMMEDIATE** — crashes as soon as lifecycle event fires after FAST cell is created.

| # | File | Line | Current code | Guard required |
|---|------|------|-------------|----------------|
| C1 | `_vc_load.py` | 2416 | `node_viewer.vtk_widget.render_window.Render()` | `if getattr(node_viewer.vtk_widget, 'render_window', None):` |
| C2 | `_vc_load.py` | 2417 | `node_viewer.vtk_widget.GetRenderWindow().Render()` | `if hasattr(node_viewer.vtk_widget, 'GetRenderWindow'):` |
| C3 | `_pw_pipeline.py` | 813 | `node_viewer.vtk_widget.render_window.Render()` | Same pattern as C1 |
| C4 | `_pw_pipeline.py` | 814 | `node_viewer.vtk_widget.GetRenderWindow().Render()` | Same pattern as C2 |
| C5 | `_vc_layout.py` | 556 | `vtk_widget.renderer.SetBackground(0.10, 0.10, 0.18)` | `if getattr(vtk_widget, 'renderer', None):` — or expose `_NullRenderer` on QtFastContainer (preferred) |
| C6 | `_vc_layout.py` | 562 | `vtk_widget.render_window.SetDesiredUpdateRate(0.001)` | Expose `_NullRenderWindow` on QtFastContainer (preferred) |
| C7 | `_pw_viewers.py` | 240 | `vtk_widget.renderer.SetBackground(0.10, 0.10, 0.18)` | Same as C5 |
| C8 | `_pw_viewers.py` | 243 | `vtk_widget.render_window.Render()` | `_NullRenderWindow` |
| C9 | `_pw_viewers.py` | 247 | `vtk_widget.render_window.SetDesiredUpdateRate(0.001)` | `_NullRenderWindow` |

**Note for C5–C9:** The preferred fix is to expose `_NullRenderer` and `_NullRenderWindow` as real attributes on `QtFastContainer` — no call-site guards needed, the mocks absorb the calls silently. This is cleaner than 5 individual `hasattr` guards.

**Already guarded (no action needed):**
- `_pw_lifecycle.py:135` — `if hasattr(viewer.vtk_widget, 'GetRenderWindow'):` ✅ already guarded

### 3.5 Implementation Sub-Steps (Ordered by Safety)

**RULE:** Each sub-step is a separate Git commit. Never squash steps until P1 is fully verified on both PCs.

---

#### Step 1.A — Add `_NullRenderWindow`, `_NullRenderer`, `_NullInteractor`, `_NullInteractorStyle` mocks

**File:** New file `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_null_vtk_mocks.py`

**What it contains:**
- `_NullRenderWindow` (§3.3.4)
- `_NullInteractor` (§3.3.5)
- `_NullRenderer` (§3.3.6)
- `_NullInteractorStyle` (§3.3.7)

**Risk:** Zero. New file, nothing imports it yet.  
**Rollback:** `git rm` the file. One-line revert.  
**Gate:** File must be importable: `python -c "from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._null_vtk_mocks import _NullRenderWindow; print('OK')"`

---

#### Step 1.B — Create `QtFastContainer` skeleton (wraps real VTKWidget internally as temporary scaffold)

**File:** New file `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py`

**Architecture:** For the first version, `QtFastContainer` does NOT need to be a pure QWidget. It can be a thin wrapper class that IS a `VTKWidget` internally but sets `_qt_bridge_active = True` from birth. This is the safest incremental approach — the full API contract is already satisfied because `VTKWidget` has everything.

Actually even better: **Phase 1 intermediate form** = modify the factory to call `QtFastContainer(parent)` which internally is just:

```python
class QtFastContainer(VTKWidget):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        # Force FAST mode from birth
        self._qt_bridge_active = False  # will be set True when bridge activates
        # Override with null mocks for unused VTK resources
        # (deferred — real VTK still allocated in intermediate form)
```

Wait — this doesn't save VTK allocation. The REAL goal of P1 is to NOT allocate VTK. For a safe intermediate step, the factory switch can happen first, then the VTK elimination second.

**REVISED two-part approach:**

**Step 1.B (safe scaffold):** `QtFastContainer(VTKWidget)` subclass — allocates VTK (same cost as before), but marks the class boundary. Factory can be switched safely. Zero behavioral change.

**Step 1.C (VTK elimination):** Change `QtFastContainer(QWidget)` — replace VTK with mocks. Requires crash-site guards (Step 1.D) done first.

**Risk for 1.B:** Functionally zero. Same behavior as VTKWidget. Creates a type boundary for future changes.  
**Rollback for 1.B:** Remove subclass file + revert factory. One-commit revert.

---

#### Step 1.C — Switch factory methods to return `QtFastContainer`

**Files modified:**
- `_vc_layout.py:_create_lightweight_vtk_placeholder()` — add `if backend == BACKEND_PYDICOM_QT: return QtFastContainer(parent)` path
- `_vc_layout.py:creator_vtk_widget()` — same
- `_pw_viewers.py:_create_lightweight_vtk_placeholder()` — same
- `_pw_viewers.py:creator_vtk_widget()` — same

**What MUST be true before this step:**
- Step 1.A complete (mocks exist)
- Step 1.B complete (QtFastContainer class exists)

**Risk:** LOW if Step 1.B uses VTKWidget subclass. MEDIUM if using pure QWidget.  
**Rollback:** Revert the 4 factory methods to unconditional `VTKWidget(parent)`. Single-commit revert.  
**Gate after this step:** Run the app in FAST mode, open a study, verify viewer cells display correctly.

---

#### Step 1.D — Add crash-site guards at C1–C4

These guards are ONLY needed if Step 1.E (VTK elimination) is being done. If QtFastContainer still wraps VTKWidget (Step 1.B form), these guards are optional but harmless belt-and-suspenders.

**Files:**
- `_vc_load.py:2415–2417` — wrap the triple-Render block with `if not getattr(node_viewer.vtk_widget, '_qt_bridge_active', False):`
- `_pw_pipeline.py:811–814` — same pattern

**Risk:** Zero. Guards only skip VTK renders in FAST mode (which are already no-ops via bridge).  
**Rollback:** Remove the `if not _qt_bridge_active` wrappers. Clean revert.

---

#### Step 1.E — VTK elimination (convert QtFastContainer to pure QWidget)

**PREREQUISITE: Steps 1.A, 1.B, 1.C, 1.D all committed and verified on BOTH PCs.**

**What changes in `QtFastContainer`:**
1. Base class changes from `VTKWidget` → `QWidget`
2. `__init__` removes ALL VTK allocation (`GetRenderWindow()`, `interactor.Initialize()`, `render_window.*`)
3. Assigns `self.render_window = _NullRenderWindow()`
4. Assigns `self.renderer = _NullRenderer()`
5. Assigns `self.current_style = _NullInteractorStyle()`
6. Creates `self.viewport_spinner = ViewportSpinner(self)`
7. Sets `self._qt_bridge_active = True`
8. All 25 methods in §3.3.2 are implemented as delegators to `QtViewerBridge`

**Risk:** HIGH if done without prior steps. MEDIUM if all prior steps done.  
**Rollback:** Revert `qt_fast_container.py` to VTKWidget subclass version. Single-file revert.  
**Gate:**
```
python -m pytest tests/viewer/test_fast_viewer_pipeline.py -v --tb=short
.\tools\dev\run_overlap_regression.ps1
```
Both must pass. App must run in FAST mode and open a study fully.

### 3.6 Connection Restoration Checklist

After P1.E, verify these are all working end-to-end:

- [ ] Patient opens — viewer cells created (FAST mode uses QtFastContainer, Advanced uses VTKWidget)
- [ ] Series drag-drop — `switch_series()` routes through QtViewerBridge → QtSliceViewer
- [ ] Progressive display — `enter_progressive_mode` / `update_available_slice_count` / `exit_progressive_mode` via QtViewerBridge
- [ ] Download complete — `grow()` called via B3.8b → bridge.grow()
- [ ] Viewport spinner shows/hides correctly during load
- [ ] Corner labels update via `update_corners_actors()`
- [ ] Window-level toolbar reset (`reset_image`) is a no-op in FAST mode without crash
- [ ] `set_new_interactorstyle` called from toolbar → no-op, no crash
- [ ] Cross-viewer sync reads `image_viewer.metadata.get('series', {}).get('series_uid')` — returns real metadata
- [ ] `GetSlice()` on `image_viewer` returns current slice index correctly

### 3.7 Rollback Decision Tree

```
Any test fails after Step 1.C factory switch?
  → git revert Step 1.C (one commit) → back to VTKWidget everywhere
  → Investigate test failure with old code restored

App crashes at study open after Step 1.E VTK elimination?
  → git revert Step 1.E → QtFastContainer reverts to VTKWidget subclass
  → Read the traceback, add missing API or guard to the crash site
  → Re-try 1.E only after fixing the gap

Overlap regression fails after Step 1.E?
  → git revert Step 1.E → investigate which render path changed
  → Likely: QtViewerBridge is not being connected properly, or
    frame_cache is not being seeded on first load
```

---

## 4. Phase P2 — Catalog Service

### 4.1 What it does
Centralizes the scattered `pydicom.dcmread(stop_before_pixels=True)` header-scan calls into a single `DicomCatalogService`. Currently, header-scan reads exist in:
- `_vc_cache.py:331,331` (primary path — `_fill_stub_from_dicom_header`)
- `_vc_backend.py:340,400` (backend detection)
- `image_io.py:115,660,1661,1662` (image loading)
- `viewer_2d.py:1595,1635` (Advanced mode)
- `lightweight_2d_pipeline.py:2603` (geometry scan in FAST)

### 4.2 Risk assessment
**Risk: MEDIUM-HIGH**

1. `_fill_stub_from_dicom_header` (from `_vc_cache.py`) is the ONLY source of per-slice IPP/IOP/geometry data during progressive grow. If this call fails or is moved incorrectly, reference lines disappear for progressively-added slices (this is the B35 regression).

2. `pydicom.dcmread` in `lightweight_2d_pipeline.py:2603` is on the prefetch-decode path — any change that adds latency or changes error handling could affect the R1 surrogate-staleness break.

3. `image_io.py` is used by both FAST and Advanced mode. A catalog abstraction that changes the calling conventions would need updates in both.

### 4.3 Recommendation: **DEFER — implement P2 after P1 is stable for ≥1 week on both PCs**

P2 has near-zero KPI gain and significant regression risk. The scattered reads work correctly today. The only benefit is architectural tidiness.

---

## 5. Phase P3 — DM Control-Plane Subprocess

### 5.1 What it does
Moves `DownloadStateStore` and `SeriesIntentCoordinator` out of the main process into a subprocess, accessed via IPC.

### 5.2 Risk assessment: **DO NOT START**

**The dependency graph:**

| File | state_store usage | Impact if removed |
|------|------------------|-------------------|
| `modules/download_manager/ui/widget/widget.py` | `get_state_store()` at line 153, all 9 mixin bases via `self.state_store` | Entire DM UI breaks |
| `modules/download_manager/ui/widget/_dm_controls.py` | 20 direct `self.state_store.*` calls | DM control panel dead |
| `modules/download_manager/ui/widget/_dm_workers.py` | 31 direct `self.state_store.*` calls | Worker lifecycle dead |
| `modules/download_manager/ui/widget/_dm_retry.py` | 21 direct `self.state_store.*` calls | Retry logic dead |
| `modules/download_manager/ui/widget/_dm_priority.py` | 12 direct calls | Priority management dead |
| `modules/download_manager/ui/widget/_dm_queue.py` | 10 direct calls | Queue management dead |
| `modules/download_manager/ui/widget/_dm_details.py` | 4 direct calls | Detail panel dead |
| `modules/download_manager/ui/widget/_dm_theming.py` | 2 direct calls | Theme-by-status dead |
| `modules/download_manager/ui/widget/_dm_reception.py` | 1 direct call | Reception integration dead |
| `modules/network/zeta_adapter.py` | 20 direct calls including `get_state_store()` × 6 | Entire download bridge dead |
| `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py` | Lazy import + `get_state_store().get_active_downloads()` | Download activity check dead |

**Total: 104+ `state_store.*` call sites across 11 files.**

Moving `state_store` out of process without first creating a `DmClientProxy` shim that implements the identical `DownloadStateStore` interface in-process would break ALL of these at import time.

### 5.3 Minimum prerequisites for P3 (if ever started)
These must be complete and tested before a single line of P3 is written:

1. **P3.pre-1:** Create `DmClientProxy` as an in-process shim implementing the exact `DownloadStateStore` interface. Initially it wraps the real `DownloadStateStore`. Wire `get_state_store()` to return the proxy. Verify all 11 files work with the proxy.

2. **P3.pre-2:** Add an integration test that exercises all state_store operations through the proxy interface.

3. **P3.pre-3:** Only AFTER proxy is verified → migrate the real `DownloadStateStore` behind the proxy to a subprocess.

4. **P3.pre-4:** The R13 IPC priority-inversion warning applies. Any subprocess state channel using mutex-locked queues will re-introduce the priority inversion fixed in R13. Use lock-free IPC or `PROCESS_MODE_BACKGROUND_BEGIN` for the subprocess thread.

### 5.4 Recommendation: **DO NOT START P3 until P1 and P4 are stable for ≥2 weeks on both PCs.**

---

## 6. Phase P4 — DM UI Rate Limiting

### 6.1 What it does
Tightens the event coalesce interval for `_refresh_table_order` and `_on_priority_changed` in the DM widget. The R22 `blockSignals` fix is already in place.

### 6.2 Risk assessment: **LOW — safe to implement independently**

This is purely an interval tuning change in `_dm_details.py` and potentially `_dm_controls.py`. It does not touch the state store import graph or any viewer code.

### 6.3 Required care
- Any change to `_refresh_table_order` interval must keep the `[DM_REBUILD]` instrumentation intact (R22)
- `priority_combo.blockSignals(True/False)` wrap at line 233 of `_dm_details.py` is the load-bearing fix — DO NOT remove during rate limiting changes
- The reentrancy guard `_refresh_table_order_in_progress` must remain

### 6.4 Plugin-package parity
After any change to `_dm_details.py` or `_dm_controls.py`, the plugin-package copies at `builder/plugin package/packages/download_manager/payload/python/modules/download_manager/ui/widget/` MUST be updated to match (Get-FileHash comparison before commit).

---

## 7. Phase P5 — CPU Budget File

### 7.1 What it does
Creates a new file that enforces per-thread CPU budgets, likely wrapping the existing `AIPACS_PRIORITY` mechanism.

### 7.2 Risk assessment: **LOW — new file only**

This is architecturally independent. Creating a new module does not affect any existing import chain. The main risk is accidentally importing from a module that requires VTK or Qt at module level (which would break headless tests).

### 7.3 Recommendation: Safe to do any time, but low priority. Defer until P1 is complete.

---

## 8. Phase P6 — Signal Routing

### 8.1 What it does
Restructures how `HomeDownloadService` fans out `seriesProgressUpdated` signals to multiple `PatientWidget` consumers.

### 8.2 Risk assessment: **HIGH — touches B4.x progress fan-out gate and R5**

The existing `HomeDownloadService` already has `_ConnectionRecord`-based lifecycle tracking and the coalesce-behind-admission gateway (B4.x). Any routing change that breaks the:
- `_flush_progress` coalesce timer
- `_emit_final_progress` completion pulse (Layer 2a)
- `series_images_progress.emit` fan-out
- `_ConnectionRecord` lifecycle teardown

...will regress progressive display and break the 4-layer completion protocol.

### 8.3 Recommendation: **DEFER until after P1, P4 are proven stable. Implement as a surgical scalpel-only change with full B4.x test suite green before and after.**

---

## 9. Phase P7 — Architecture Tests

### 9.1 What it does
Adds new `tests/viewer/test_architecture_invariants.py` that:
- Verifies `QtFastContainer` does NOT have a live VTK render window
- Verifies `VTKWidget` does NOT have `_qt_bridge_active=True` at construction
- Verifies factory method returns correct type per backend

### 9.2 Risk assessment: **ZERO — pure additions to test suite**

These tests can be written NOW, before any P1 implementation. They will fail (expected) until P1 is complete, and then serve as regression guards.

### 9.3 Recommendation: **Write these in parallel with P1 Steps 1.A–1.B. The failing tests document intent; they become passing as P1 completes.**

---

## 10. Implementation Schedule

```
Week 1 (current): 
  - This plan reviewed and approved
  - P7 architecture tests written (failing — intent documentation)
  - Step 1.A: _null_vtk_mocks.py created and imported
  - Step 1.B: QtFastContainer(VTKWidget) skeleton
  
Week 2:
  - Step 1.C: Factory switch to QtFastContainer
  - Step 1.D: Crash-site guards C1–C4
  - Gate: App runs in FAST mode, study opens, no regression
  - PUSH TO GITHUB — verify on PC B
  
Week 3:
  - Step 1.E: VTK elimination (pure QWidget)
  - Full test suite green
  - Overlap regression green
  - PUSH — verify on PC B

Week 4+:
  - P4 (DM UI rate limiting) — independent, safe
  - P5 (CPU budget file) — independent, low risk
  - P7 additional coverage

Month 2+:
  - P2 (Catalog service) — after P1 stable 1+ week
  - P6 (Signal routing) — after P1/P4 stable
  - P3 (DM subprocess) — ONLY after proxy shim architecture, P3.pre-1 through P3.pre-4 complete
```

---

## 11. Test Gates

### 11.1 Before ANY code change
```powershell
# Verify import chain is clean
.\.venv\Scripts\python.exe -c "import PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_viewer_controller; print('OK')"
```

### 11.2 After Step 1.C (factory switch)
```powershell
# Smoke test: open app, load a study in FAST mode
# (manual verification — no automated headless path yet)
```

### 11.3 After Step 1.E (VTK elimination) — MANDATORY
```powershell
# Viewer pipeline tests
.\.venv\Scripts\python.exe -m pytest tests/viewer/test_fast_viewer_pipeline.py -v --tb=short

# Overlap regression (pixel hash gate)
.\tools\dev\run_overlap_regression.ps1

# DM test suite (verify download flow unaffected)
.\.venv\Scripts\python.exe tests/download_manager/run_dm_test.py

# Import smoke
.\.venv\Scripts\python.exe -m pytest tests/smoke/test_import_smoke.py -v
```

### 11.4 Before P3 (if ever started)
```powershell
# All DM tests
.\.venv\Scripts\python.exe tests/download_manager/run_dm_test.py
.\.venv\Scripts\python.exe tests/download_manager/test_dm_stress.py
.\.venv\Scripts\python.exe tests/load/run_load_test.py
```

---

## Appendix A — VTK Crash Site Code Reference

### C1 + C2 (currently in `_vc_load.py:2413–2417`)
```python
# CURRENT (will crash with QtFastContainer):
if node_viewer.vtk_widget.image_viewer:
    node_viewer.vtk_widget.image_viewer.Render()       # OK: bridge has no-op Render
    node_viewer.vtk_widget.render_window.Render()      # CRASH if QtFastContainer
    node_viewer.vtk_widget.GetRenderWindow().Render()  # CRASH if QtFastContainer

# FIXED (Step 1.D guard):
if node_viewer.vtk_widget.image_viewer:
    node_viewer.vtk_widget.image_viewer.Render()
    if not getattr(node_viewer.vtk_widget, '_qt_bridge_active', False):
        node_viewer.vtk_widget.render_window.Render()
        node_viewer.vtk_widget.GetRenderWindow().Render()
```

### C3 + C4 (currently in `_pw_pipeline.py:811–814`)
Same pattern as C1+C2.

### C5–C9 (factory setup calls — preferred fix via _NullRenderWindow/_NullRenderer)
```python
# In _vc_layout.py / _pw_viewers.py after factory returns QtFastContainer:
vtk_widget.renderer.SetBackground(0.10, 0.10, 0.18)    # OK: _NullRenderer absorbs
vtk_widget.render_window.Render()                       # OK: _NullRenderWindow absorbs
vtk_widget.render_window.SetDesiredUpdateRate(0.001)    # OK: _NullRenderWindow absorbs
# No guards needed — mocks handle these silently
```

---

## Appendix B — Quick Rollback Reference

| Step | What to revert | Files affected | Risk |
|------|---------------|----------------|------|
| 1.A mocks | `git rm vtk_widget/_null_vtk_mocks.py` | 1 file | Zero |
| 1.B skeleton | `git rm vtk_widget/qt_fast_container.py` | 1 file | Zero |
| 1.C factory | Revert `_vc_layout.py`, `_pw_viewers.py` factory methods | 2 files, ~4 lines each | Zero |
| 1.D guards | Remove `if not _qt_bridge_active:` wrappers | 2 files, ~4 lines each | Zero |
| 1.E VTK elim | Revert `qt_fast_container.py` to VTKWidget subclass | 1 file | Low |
| P4 rate limit | Revert `_dm_details.py` interval change | 1 file | Low |

**Golden rule:** If a rollback is needed, revert ONLY the most recent step. Never skip steps in rollback.

---

*Document last updated: 2026-05-05. Update this document each time a step completes or a new crash site is found.*
