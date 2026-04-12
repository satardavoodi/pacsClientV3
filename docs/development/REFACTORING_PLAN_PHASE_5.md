# Phase 5 — Large File Refactoring Plan

**Created:** 2026-04-05  
**Status:** PLANNING  
**Scope:** Split 12 CRITICAL files (≥2000 lines) into mixin-based modules  
**Approach:** Same proven pattern from Phases 1–4 (patient_widget, home_ui, engine, main_widget)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Target Files](#2-target-files)
3. [Priority Order](#3-priority-order)
4. [Phase 5A — StandardMPRViewer (CRITICAL — detailed plan)](#4-phase-5a--standardmprviewer)
5. [Phase 5B — ToolbarManager](#5-phase-5b--toolbarmanager)
6. [Phase 5C — AI Chat Pages (EchoMind)](#6-phase-5c--ai-chat-pages)
7. [Phase 5D — VTKWidget (widget_viewer.py)](#7-phase-5d--vtkwidget)
8. [Phase 5E — PatientTableWidget](#8-phase-5e--patienttablewidget)
9. [Phase 5F — Secondary Targets](#9-phase-5f--secondary-targets)
10. [Refactoring Pattern](#10-refactoring-pattern)
11. [Validation Protocol](#11-validation-protocol)
12. [Risk Assessment](#12-risk-assessment)

---

## 1. Executive Summary

After Phases 1–4, 4 monolithic files were successfully split into mixin modules. 81 files ≥800 lines remain, with 20 CRITICAL files ≥2000 lines. This plan covers the top 12 production files (excluding test files and VTK merge tools).

**Key principle:** The mixin-based split pattern works. Each large class becomes:
- A thin **core widget file** (`widget.py`) with `__init__`, class attrs, and mixin assembly
- Multiple **mixin files** (`_xx_category.py`) with logically grouped methods
- A **backward-compatible shim** at the original path for zero-breakage imports

---

## 2. Target Files

### CRITICAL (≥2000 lines) — Production code only

| # | File | Lines | Class | Methods | Risk |
|---|------|------:|-------|--------:|------|
| 1 | `modules/mpr/zeta_mpr/standard_mpr_viewer.py` | 5,253 | `StandardMPRViewer` | 109 | **HIGHEST** |
| 2 | `PacsClient/.../patient_toolbar/toolbar_manager.py` | 7,545 | `ToolbarManager` | 95 | HIGH |
| 3 | `modules/EchoMind/viewer_chat/ai_chat_pages.py` | 6,544 | 3 classes | 99 | MEDIUM |
| 4 | `PacsClient/.../patient_ui/widget_viewer.py` | 3,995 | `VTKWidget` | 102 | HIGH |
| 5 | `PacsClient/.../home_ui/patient_table_widget.py` | 3,484 | `PatientTableWidget` | 99 | MEDIUM |
| 6 | `modules/education/education_module_redesigned.py` | 3,612 | 8 classes | 101 | LOW |
| 7 | `modules/viewer/advanced/viewer_2d.py` | 2,635 | `ImageViewer2D` | 64 | HIGH |
| 8 | `modules/EchoMind/viewer_chat/ai_chat_widgets.py` | 4,162 | multiple | — | LOW |
| 9 | `modules/EchoMind/viewer_chat/openai_reporter.py` | 2,541 | — | — | LOW |
| 10 | `modules/web_browser/widget.py` | 2,353 | — | — | LOW |
| 11 | `PacsClient/.../settings_ui/filter_config.py` | 2,190 | — | — | LOW |
| 12 | `modules/printing/ui/printing_widget.py` | 2,010 | — | — | LOW |

### Excluded from scope
- `tools/vtk/_merged_vtk.py` (4,066) — VTK merge conflict tool, not production
- `tools/vtk/_ours_vtk.py` (3,121) — VTK merge tool
- `tools/vtk/_theirs_vtk.py` (2,600) — VTK merge tool
- `tests/download_manager/test_download_manager.py` (2,457) — test file
- `tests/viewer/test_fast_viewer_live_sync.py` (2,079) — test file

---

## 3. Priority Order

| Phase | Target | Justification |
|-------|--------|---------------|
| **5A** | StandardMPRViewer | Most complex, most sensitive, highest risk. Must be done first with full attention |
| **5B** | ToolbarManager | Largest file (7545), many consumers, deeply coupled to MPR |
| **5C** | AI Chat Pages | Large but self-contained EchoMind module |
| **5D** | VTKWidget | Core viewer, performance-critical scroll path |
| **5E** | PatientTableWidget | Home UI, moderate complexity |
| **5F** | Remaining 7 files | Lower priority, can be batched |

---

## 4. Phase 5A — StandardMPRViewer

> **⚠️ THIS IS THE MOST SENSITIVE REFACTORING TARGET IN THE ENTIRE PROJECT**
>
> The Standard MPR viewer is a complex VTK-based medical imaging component with:
> - Input-level X-flip correction (foundational — DO NOT MOVE or alter)
> - Direction matrix handling for DICOM orientation
> - 9-point oblique camera repositioning system
> - Complex crosshair interaction with rotation, dragging, and cursor feedback
> - 3D VRT rendering with preset management
> - Segmentation pipeline integration
> - CT-specific camera corrections (Roll/Azimuth) that are position-dependent
>
> **Any incorrect split will cause black screens, flipped images, or broken crosshairs.**

### 4A.1 Current Architecture

```
standard_mpr_viewer.py (5,253 lines)
├── MPRToolbarInteractorStyle (L147-315, 13 methods) — toolbar tool routing
├── VRTInteractorStyle (L316-478, 13 methods) — 3D view mouse handling  
└── StandardMPRViewer (L479-5253, 109 methods) — THE MAIN CLASS
    ├── __init__ (202 lines) — volume flip, direction matrix, all state init
    ├── Orientation & camera (L686-1200) — 12 methods
    ├── UI setup & toolbar (L1312-1500) — 2 methods
    ├── Series scroller (L1504-1830) — 5 methods
    ├── View creation (L1830-2240) — 4 methods (axial, sagittal, coronal, 3D)
    ├── Window/Level & presets (L2241-2350) — 5 methods
    ├── Event filter & layout (L2352-2463) — 5 methods
    ├── Crosshair rendering (L2464-2780) — 8 methods
    ├── Crosshair interaction (L2783-3505) — 1 GIANT method (722 lines inner class!)
    ├── Crosshair update & sync (L3505-3660) — 5 methods
    ├── Crosshair settings (L3660-3883) — 7 methods
    ├── Oblique reslicing (L3884-4300) — 6 methods
    ├── Rendering modes (L4300-4620) — 5 methods (MIP, MinIP, slab, reset)
    ├── VRT preset menu (L4620-4860) — 3 methods
    ├── VRT interaction (L4860-5060) — 10 methods
    └── Segmentation (L5060-5253) — 6 methods
```

### 4A.2 Proposed Mixin Split

**Target directory:** `modules/mpr/zeta_mpr/mpr_viewer/`

```
modules/mpr/zeta_mpr/
├── standard_mpr_viewer.py          ← SHIM (backward compat, re-exports)
├── mpr_viewer/
│   ├── __init__.py                 ← exports StandardMPRViewer
│   ├── widget.py                   ← core: __init__, class attrs, mixin assembly
│   ├── _interactor_styles.py       ← MPRToolbarInteractorStyle + VRTInteractorStyle
│   ├── _mpr_orientation.py         ← camera vectors, direction matrix, orientation labels
│   ├── _mpr_views.py               ← view creation (axial, sagittal, coronal, 3D), UI setup
│   ├── _mpr_crosshair_render.py    ← crosshair creation, endpoints, handles, appearance
│   ├── _mpr_crosshair_interact.py  ← CrosshairInteractorStyle inner class → top-level class
│   ├── _mpr_crosshair_state.py     ← crosshair update, sync, toggle, settings, close
│   ├── _mpr_oblique.py             ← 9-point oblique, set_oblique_camera, reset_to_orthogonal
│   ├── _mpr_rendering.py           ← MIP, MinIP, thick slab, slab projection, reset
│   ├── _mpr_vrt.py                 ← VRT preset menu, VRT interaction state machine
│   ├── _mpr_segmentation.py        ← lung/airway/vessel/bone segmentation
│   ├── _mpr_series.py              ← series scroller, switch, highlight, reload
│   └── _mpr_layout.py              ← expand/collapse views, event filter, measurement viewport
```

### 4A.3 Method Assignment (detailed)

#### `widget.py` — Core (≈250 lines)
```python
class StandardMPRViewer(_MprOrientationMixin, _MprViewsMixin, _MprCrosshairRenderMixin,
                        _MprCrosshairStateMixin, _MprObliqueMixin, _MprRenderingMixin,
                        _MprVrtMixin, _MprSegmentationMixin, _MprSeriesMixin,
                        _MprLayoutMixin, QWidget):
    def __init__(...)      # volume flip, direction matrix, ALL state initialization
    # Class attributes remain here
```

#### `_interactor_styles.py` — Standalone classes (≈330 lines)
```
MPRToolbarInteractorStyle     (13 methods, L147-315)
VRTInteractorStyle            (13 methods, L316-478)
```
These are **standalone VTK interactor style classes**, NOT mixins — they reference `self.parent` (the viewer), not `self`. They are moved as-is with imports adjusted.

#### `_mpr_orientation.py` — Orientation & camera logic (≈550 lines)
```
_capture_baseline_camera_state()   L686   (40 lines)
_apply_window_level()              L726   (9 lines)
_request_render()                  L735   (14 lines)
_execute_pending_renders()         L749   (8 lines)
_render_immediately()              L757   (5 lines)
_clamp_current_position()          L762   (10 lines)
_detect_series_type()              L879   (38 lines)
_get_camera_vectors_for_view()     L917   (85 lines) ⬅️ CRITICAL: direction matrix handling
_is_identity_direction()           L1002  (11 lines)
_log_orientation_info()            L1013  (103 lines)
_get_standard_camera_vectors()     L1116  (45 lines)
_get_scroll_direction()            L1161  (40 lines)
_get_orientation_labels()          L1201  (76 lines)
_get_best_3d_preset()              L1277  (17 lines)
_get_default_window_level()        L1294  (12 lines)
_get_initial_window_level()        L1306  (6 lines)
```

#### `_mpr_views.py` — View creation & UI setup (≈550 lines)
```
_setup_ui()                        L1312  (50 lines) ⬅️ orchestrates all view creation
_create_toolbar()                  L1362  (134 lines)
_create_separator()                L1496  (8 lines)
_create_axial_view()               L1830  (81 lines)
_create_sagittal_view()            L1911  (92 lines) ⬅️ CT Roll(180) correction
_create_coronal_view()             L2003  (89 lines) ⬅️ CT Azimuth(180)+Roll(180)
_create_3d_view()                  L2092  (149 lines)
_apply_volume_preset()             L2241  (14 lines)
_on_wl_changed()                   L2255  (42 lines)
_on_volume_preset_changed()        L2297  (14 lines)
setup_auto_rotation()              L2311  (16 lines)
auto_rotate_step()                 L2327  (18 lines)
stop_auto_rotation()               L2345  (7 lines)
```

#### `_mpr_crosshair_render.py` — Crosshair visual creation (≈320 lines)
```
_create_crosshairs()               L2464  (52 lines)
_calculate_crosshair_endpoints()   L2516  (102 lines) ⬅️ rotation-aware endpoint math
_create_crosshair_handles()        L2618  (48 lines)
_get_rotation_cursor()             L2666  (7 lines)
_set_view_cursor()                 L2673  (9 lines)
_create_slice_info_text()          L2682  (29 lines)
_add_orientation_labels()          L2711  (59 lines)
_get_slice_info_text()             L2770  (13 lines)
```

#### `_mpr_crosshair_interact.py` — Crosshair interaction (≈730 lines)
```
_add_click_handler()               L2783  (722 lines) ⬅️ LARGEST METHOD
```
**CRITICAL refactoring note:** This method contains a 700-line inner class `CrosshairInteractorStyle`. The split will:
1. Extract `CrosshairInteractorStyle` as a **top-level class** in this file
2. The class currently captures `parent_viewer = self` via closure — change to explicit `__init__` parameter
3. Keep `_add_click_handler()` as a thin factory method that creates and installs the style
4. **DO NOT change any interaction logic, mouse handling, cursor feedback, or rotation math**

#### `_mpr_crosshair_state.py` — Crosshair update & control (≈350 lines)
```
_update_all_crosshairs()           L3505  (45 lines)
_update_slice_positions()          L3550  (56 lines)
_synchronize_oblique_views()       L3606  (10 lines)
_update_slice_info_texts()         L3616  (8 lines)
_toggle_crosshairs()               L3624  (35 lines)
_close_mpr()                       L3659  (52 lines)
_enable_crosshair_interaction()    L3711  (18 lines)
_disable_crosshair_interaction()   L3729  (18 lines)
_show_crosshair_settings_menu()    L3747  (84 lines)
_get_handle_color()                L3831  (8 lines)
_set_crosshair_color()             L3839  (19 lines)
_set_crosshair_width()             L3858  (14 lines)
_reset_crosshair_rotation()        L3872  (12 lines)
```

#### `_mpr_oblique.py` — Oblique reslicing (≈420 lines)
```
_update_oblique_reslicing()        L3884  (189 lines) ⬅️ 9-point dual-tier sampling
_best_line_direction()             L4073  (22 lines)
_point_inside_bounds()             L4095  (6 lines)  [static method]
_set_oblique_camera()              L4101  (74 lines)  ⬅️ camera repositioning along oblique normal
_clamp_to_fov()                    L4175  (42 lines)
_reset_all_to_orthogonal()         L4217  (80 lines) ⬅️ restores baseline camera state
```
**INVARIANT:** `_synchronize_oblique_views()` calls `_update_oblique_reslicing()`. The call chain:
```
interaction → _update_all_crosshairs() → _update_slice_positions() → _synchronize_oblique_views() → _update_oblique_reslicing() → _set_oblique_camera()
```
This chain MUST remain intact across mixin boundaries. Python MRO handles this naturally since all mixins share `self`.

#### `_mpr_rendering.py` — Rendering modes (≈320 lines)
```
_apply_mip()                       L4319  (30 lines)
_apply_minip()                     L4349  (30 lines)
_apply_thick_slab()                L4379  (41 lines)
_apply_slab_projection()           L4420  (28 lines)
_reset_rendering()                 L4448  (172 lines) ⬅️ full view reset, recaptures baseline
```

#### `_mpr_vrt.py` — VRT 3D interaction (≈440 lines)
```
_show_vrt_preset_menu()            L4620  (194 lines)
_show_vrt_preset_menu_from_interactor()  L4814  (11 lines)
_apply_vrt_preset()                L4825  (19 lines)
_reset_vrt_rmb_state()             L4844  (17 lines)
_capture_vrt_baseline()            L4861  (18 lines)
_apply_vrt_appearance_delta()      L4879  (29 lines)
_on_vrt_left_press()               L4908  (19 lines)
_on_vrt_left_release()             L4927  (22 lines)
_on_vrt_right_press()              L4949  (20 lines)
_on_vrt_right_release()            L4969  (26 lines)
_on_vrt_middle_press()             L4995  (9 lines)
_on_vrt_middle_release()           L5004  (10 lines)
_on_vrt_mouse_move()               L5014  (48 lines)
```

#### `_mpr_segmentation.py` — Segmentation (≈200 lines)
```
_show_segment_menu()               L5062  (43 lines)
_segment_lungs()                   L5105  (41 lines)
_segment_airways()                 L5146  (15 lines)
_segment_vessels()                 L5161  (18 lines)
_segment_bone()                    L5179  (33 lines)
_clear_segmentation()              L5212  (15 lines)
```

#### `_mpr_series.py` — Series management (≈330 lines)
```
_create_series_scroller()          L1504  (158 lines)
_switch_series()                   L1662  (26 lines)
_highlight_current_series()        L1688  (36 lines) [first definition]
_reload_with_series()              L1724  (77 lines)
_highlight_current_series()        L1801  (29 lines) [second definition — duplicate!]
```
**NOTE:** There are TWO `_highlight_current_series` definitions (L1688 and L1801). The second overwrites the first. During the split, verify which one is the actual active implementation (the second one, L1801, takes precedence in Python).

#### `_mpr_layout.py` — Layout & measurement viewport (≈120 lines)
```
eventFilter()                      L2352  (59 lines)
_register_view()                   L2411  (8 lines)
_toggle_expand_view()              L2419  (25 lines)
_lock_mpr_size()                   L2444  (12 lines)
_unlock_mpr_size()                 L2456  (8 lines)
activate_ruler()                   L772   (3 lines)
activate_angle()                   L775   (3 lines)
activate_caption()                 L778   (3 lines)
deactivate_tool()                  L781   (3 lines)
activate_toolbar_tool()            L784   (15 lines)
deactivate_toolbar_tool()          L799   (11 lines)
zoom_to_fit()                      L810   (10 lines)
delete_measurement_at()            L820   (9 lines)
reset_to_initial_state()           L829   (11 lines)
_set_active_view()                 L863   (9 lines)
_update_view_highlights()          L872   (7 lines)
get_current_volume()               L4297  (6 lines)
_update_coordinates_label()        L4303  (5 lines)
cleanup()                          L4308  (11 lines)
get_active_viewport_for_measurements()   L5227  (14 lines)
set_active_measurement_viewport()        L5241  (12 lines)
```

### 4A.4 Critical Invariants to Preserve

| Invariant | Location | Risk if broken |
|-----------|----------|---------------|
| Input X-flip on axis 0 | `__init__` L494-498 | All views left-right reversed |
| Direction matrix column negate | `__init__` L535 | Incorrect orientation |
| CT Roll(180) on sagittal | `_create_sagittal_view` | Flipped sagittal |
| CT Azimuth(180)+Roll(180) on coronal | `_create_coronal_view` | Flipped coronal |
| Baseline camera capture after creation | `_setup_ui` final lines | Oblique normal errors |
| `_synchronize_oblique_views()` called LAST | Every interaction path | Oblique planes out of sync |
| CrosshairInteractorStyle closure→param | `_add_click_handler` | Broken crosshair |
| `_highlight_current_series` duplicate | L1688 vs L1801 | Silent override |
| Render batch timing (5ms) | `_request_render` | Performance regression |

### 4A.5 Execution Steps

1. **Create `modules/mpr/zeta_mpr/mpr_viewer/` directory**
2. **Create `_interactor_styles.py`** — move the two standalone classes
3. **Create each mixin file** — one at a time, in dependency order:
   - `_mpr_orientation.py` (no deps on other mixins)
   - `_mpr_crosshair_render.py` (depends on orientation for endpoints)
   - `_mpr_crosshair_interact.py` (depends on render for actors)
   - `_mpr_crosshair_state.py` (depends on render + interact)
   - `_mpr_oblique.py` (depends on state for sync)
   - `_mpr_views.py` (depends on orientation + crosshair)
   - `_mpr_rendering.py` (depends on views for mappers)
   - `_mpr_vrt.py` (depends on views for 3D renderer)
   - `_mpr_segmentation.py` (depends on views for 3D renderer)
   - `_mpr_series.py` (depends on views for reload)
   - `_mpr_layout.py` (depends on views for containers)
4. **Create `widget.py`** — core class with all mixin bases
5. **Create `__init__.py`** — re-export `StandardMPRViewer`
6. **Convert `standard_mpr_viewer.py` to shim** — re-export from `mpr_viewer/`
7. **AST validation** — `python -c "import ast; ast.parse(open(f).read())"` for each file
8. **Import smoke test** — `from modules.mpr.zeta_mpr import StandardMPRViewer`
9. **Manual visual test** — open a CT study, toggle MPR, verify all 4 views

---

## 5. Phase 5B — ToolbarManager

**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py` (7,545 lines)  
**Class:** `ToolbarManager` (95 methods) + `BadgeButton` (7 methods)

### 5B.1 Proposed Split

**Target directory:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/`

```
patient_toolbar/
├── toolbar_manager.py              ← SHIM (backward compat)
├── badge_button.py                 ← BadgeButton class (standalone)
├── toolbar_core/
│   ├── __init__.py
│   ├── widget.py                   ← ToolbarManager core: __init__, mixin assembly
│   ├── _tb_actions.py              ← add_toolbar_actions() — THE 1,053-line method
│   ├── _tb_tool_toggles.py         ← toggle_ruler/eraser/angle/zoom/pan/stacked/etc.
│   ├── _tb_mpr.py                  ← toggle_zeta_mpr, toggle_new_curve_mpr, MPR-related
│   ├── _tb_rendering.py            ← toggle_mip/minip/thick_slab, _restore_*
│   ├── _tb_dropdowns.py            ← _show_*_dropdown methods
│   ├── _tb_capture.py              ← capture, status upload, case-of-day
│   ├── _tb_sync.py                 ← sync dropdown, lock sync, report status
│   ├── _tb_audio.py                ← mic/audio methods
│   └── _tb_utils.py                ← is_vtk_widget, handle_buttons, get_tool_activated
```

### 5B.2 Key Challenge
The `add_toolbar_actions()` method is **1,053 lines**. It creates all toolbar buttons and wires signals. Options:
- **Option A:** Keep in one file as `_tb_actions.py` (acceptable — it's one method)
- **Option B:** Split into sub-methods called from `add_toolbar_actions()` (cleaner but riskier)
- **Recommendation:** Option A for safety, with TODO comments for future sub-splitting

---

## 6. Phase 5C — AI Chat Pages

**File:** `modules/EchoMind/viewer_chat/ai_chat_pages.py` (6,544 lines)  
**Classes:** `ModePickerPage` (13), `OneChatPage` (70), `ChatGPTPage` (16)

### 6C.1 Proposed Split

```
modules/EchoMind/viewer_chat/
├── ai_chat_pages.py                ← SHIM
├── chat_pages/
│   ├── __init__.py                 ← re-exports all 3 classes
│   ├── mode_picker_page.py         ← ModePickerPage (standalone, ~300 lines)
│   ├── chatgpt_page.py             ← ChatGPTPage (standalone, ~500 lines)
│   ├── one_chat_page/
│   │   ├── __init__.py
│   │   ├── widget.py               ← OneChatPage core + mixin assembly
│   │   ├── _ocp_session.py         ← session/persistence (load, delete, open)
│   │   ├── _ocp_send.py            ← send/receive (_on_send_clicked, _send_to_reception, _send_with_mode)
│   │   ├── _ocp_voice.py           ← voice/transcription
│   │   ├── _ocp_render.py          ← bubble rendering, HTML generation
│   │   └── _ocp_usage.py           ← usage logging
```

---

## 7. Phase 5D — VTKWidget

**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/widget_viewer.py` (3,995 lines)  
**Class:** `VTKWidget` (102 methods)

### 7D.1 Proposed Split

```
PacsClient/pacs/patient_tab/ui/patient_ui/
├── widget_viewer.py                ← SHIM
├── vtk_widget/
│   ├── __init__.py
│   ├── widget.py                   ← VTKWidget core: __init__, class attrs, mixin assembly
│   ├── _vw_scroll.py              ← set_slice (358 lines!), wheelEvent (217 lines), queue_interactive, flush
│   ├── _vw_series.py              ← switch_series (360 lines!), start_process_*, reset_image
│   ├── _vw_backend.py             ← _bind_backend, lazy loader signals, _on_lazy_slice_ready
│   ├── _vw_progressive.py         ← enter/exit progressive mode, grow_*, update_available_slice_count
│   ├── _vw_render.py              ← _schedule_render, _do_render, _freeze_render_window
│   ├── _vw_camera.py              ← capture/restore camera state
│   ├── _vw_interactor.py          ← set_new_interactorstyle, restore_default, sync point methods
│   ├── _vw_dragdrop.py            ← all drag-enter/move/leave/drop event handlers
│   ├── _vw_overlay.py             ← overlay, clear_overlay
│   └── _vw_diagnostics.py         ← scroll lag recording, timing, percentile logging
```

### 7D.2 Key Risk
`set_slice()` (358 lines) is the **hottest path** in the application — called on every mouse wheel tick. The `_in_wheel_scroll` fast-path flag must remain respected. All guard conditions must be preserved exactly.

---

## 8. Phase 5E — PatientTableWidget

**File:** `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py` (3,484 lines)  
**Class:** `PatientTableWidget` (99 methods) + 5 helper classes

### 8E.1 Proposed Split

```
PacsClient/pacs/workstation_ui/home_ui/
├── patient_table_widget.py         ← SHIM
├── patient_table/
│   ├── __init__.py
│   ├── widget.py                   ← PatientTableWidget core + mixin assembly
│   ├── _delegates.py               ← CustomHeaderView, SortableItem, PatientNameDelegate, CombinedDelegate, ColumnSettingsDialog
│   ├── _pt_layout.py               ← setup_ui, _setup_layout (303 lines)
│   ├── _pt_data.py                 ← add_patient_data, extract_row_data, get_selected/all
│   ├── _pt_download.py             ← download status methods
│   ├── _pt_report.py               ← report status methods
│   ├── _pt_search.py               ← search_in_table, highlight_rows, sort
│   ├── _pt_columns.py              ← column/font settings load/save/apply
│   ├── _pt_selection.py            ← checkbox/selection methods
│   └── _pt_theme.py                ← theme change handlers
```

---

## 9. Phase 5F — Secondary Targets

### 9F.1 education_module_redesigned.py (3,612 lines)
Already has 8 well-separated classes. Split into **individual class files**:
```
modules/education/
├── education_module_redesigned.py  ← SHIM
├── education_pages/
│   ├── filter_panel.py
│   ├── course_card.py
│   ├── course_details.py
│   ├── library_page.py
│   ├── my_courses_page.py
│   ├── item_meta_dialog.py
│   ├── build_course_page.py
│   └── main_widget.py
```

### 9F.2 viewer_2d.py (2,635 lines)
Split `ImageViewer2D` (64 methods):
```
modules/viewer/advanced/
├── viewer_2d.py                    ← SHIM
├── viewer_2d_core/
│   ├── widget.py                   ← ImageViewer2D core
│   ├── _v2d_rendering.py          ← render, reset, zoom
│   ├── _v2d_overlay.py            ← overlay methods
│   ├── _v2d_corners.py            ← corner text actors
│   ├── _v2d_curved_mpr.py         ← curved MPR interaction
│   ├── _v2d_coordinates.py        ← coordinate transforms
│   └── _v2d_cache.py              ← preprocessing cache
```

### 9F.3 Other files (2,000-2,500 lines)
- **ai_chat_widgets.py** (4,162) — Split widget classes into individual files
- **openai_reporter.py** (2,541) — Split by report type
- **web_browser/widget.py** (2,353) — Split by functionality
- **filter_config.py** (2,190) — Split by filter category
- **printing_widget.py** (2,010) — Split by print pipeline stage

---

## 10. Refactoring Pattern

The proven pattern from Phases 1–4:

### Step 1: Create mixin files
Each mixin is a plain class inheriting from `object`:
```python
# _mpr_oblique.py
class _MprObliqueMixin:
    """Mixin: 9-point oblique reslicing for StandardMPRViewer."""
    
    def _update_oblique_reslicing(self):
        # ... exact same code, moved verbatim ...
```

### Step 2: Create core widget with mixin assembly
```python
# widget.py
from ._mpr_oblique import _MprObliqueMixin
from ._mpr_views import _MprViewsMixin
# ... all mixins ...

class StandardMPRViewer(_MprObliqueMixin, _MprViewsMixin, ..., QWidget):
    def __init__(self, vtk_image_data, parent=None, ...):
        super().__init__(parent)
        # ALL state initialization stays here
```

### Step 3: Create backward-compatible shim
```python
# standard_mpr_viewer.py (original path)
"""Backward-compatible shim — see mpr_viewer/ for implementation."""
from .mpr_viewer import StandardMPRViewer  # noqa: F401

__all__ = ['StandardMPRViewer']
```

### Key Rules
1. **Methods move VERBATIM** — no logic changes during the split
2. **All state init stays in `__init__`** — mixins only add methods
3. **Imports adjusted per file** — each mixin imports only what it needs
4. **Original file becomes a shim** — zero breakage for existing imports
5. **AST-validate every file** before testing
6. **One phase at a time** — never split two files simultaneously

---

## 11. Validation Protocol

For each phase:

### Pre-flight
- [ ] Read and understand ALL methods being moved
- [ ] Identify cross-method dependencies within the class
- [ ] Identify external references (grep for class name imports)
- [ ] Create a backup of the file being split

### During split
- [ ] AST-validate each new file: `python -c "import ast; ast.parse(open(f).read())"`
- [ ] Verify all imports resolve
- [ ] Verify the shim exports correctly

### Post-split verification
- [ ] **Import smoke test:** `from <module> import <Class>` succeeds
- [ ] **Method resolution:** `dir(instance)` contains all expected methods
- [ ] **Existing tests pass:**
  - Smoke tests: `python -m pytest tests/smoke/test_import_smoke.py -v`
  - DM tests: `python tests/download_manager/run_dm_test.py`
  - Viewer tests: `python -m pytest tests/viewer/test_fast_viewer_pipeline.py -v`
- [ ] **Manual visual test** (for viewer/MPR files):
  - Open a CT study
  - Toggle MPR → verify all 4 views render correctly
  - Scroll with mouse wheel in each view
  - Move crosshairs by clicking/dragging
  - Rotate crosshair handles
  - Switch series in the scroller
  - Reset rendering
  - Close MPR

---

## 12. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| MPR orientation broken | Users see flipped anatomy | X-flip stays in `__init__`, CT corrections stay in view creation |
| Oblique reslicing broken | Black screens on rotation | Call chain preserved across mixin boundary (Python MRO) |
| CrosshairInteractorStyle closure broken | Crosshairs don't respond | Convert closure to explicit parameter passing |
| Performance regression in VTKWidget | Scroll lag > 16ms | `set_slice()` moves as-is, `_in_wheel_scroll` guard preserved |
| Import cycles | Module won't load | Each mixin imports only stdlib/VTK/Qt, not other mixins |
| Missing method on mixin | AttributeError at runtime | Full `dir()` check in validation, AST parse each file |
| Duplicate `_highlight_current_series` | Wrong method used | Resolve during split — keep only the active (second) definition |

---

## Appendix A: Line Count Budget

| Phase | Current | Target per file | Files created |
|-------|--------:|----------------:|--------------:|
| 5A MPR viewer | 5,253 | 250-730 | 14 |
| 5B Toolbar | 7,545 | 200-1,100 | 12 |
| 5C AI Chat | 6,544 | 300-700 | 8 |
| 5D VTKWidget | 3,995 | 200-400 | 12 |
| 5E PatientTable | 3,484 | 150-350 | 11 |
| 5F Education | 3,612 | 200-500 | 9 |
| 5F viewer_2d | 2,635 | 200-400 | 8 |
| 5F Others | ~13,256 | varies | ~15 |
| **Total** | **46,324** | — | **~89** |

---

## Appendix B: StandardMPRViewer Method Cross-Reference

Methods that call other methods across proposed mixin boundaries:

```
__init__ (widget.py)
  → _log_orientation_info() [orientation]
  → _detect_series_type() [orientation]
  → _setup_ui() [views]
  → _apply_window_level() [orientation]
  → _highlight_current_series() [series]

_setup_ui (views)
  → _create_axial_view() [views]
  → _create_sagittal_view() [views]
  → _create_coronal_view() [views]
  → _create_3d_view() [views]
  → _capture_baseline_camera_state() [orientation]

_create_*_view (views)
  → _get_initial_window_level() [orientation]
  → _get_camera_vectors_for_view() [orientation]
  → _add_click_handler() [crosshair_interact]
  → _create_crosshairs() [crosshair_render]
  → _create_slice_info_text() [crosshair_render]
  → _register_view() [layout]

CrosshairInteractorStyle (crosshair_interact)
  → parent._update_all_crosshairs() [crosshair_state]
  → parent._update_slice_positions() [crosshair_state]
  → parent._synchronize_oblique_views() [crosshair_state]
  → parent._render_immediately() [orientation]
  → parent._request_render() [orientation]
  → parent._clamp_current_position() [orientation]

_update_oblique_reslicing (oblique)
  → _best_line_direction() [oblique]
  → _point_inside_bounds() [oblique]
  → _set_oblique_camera() [oblique]

_reset_rendering (rendering)
  → _get_initial_window_level() [orientation]
  → _get_camera_vectors_for_view() [orientation]
  → _apply_volume_preset() [views]
  → _create_crosshairs() [crosshair_render]
  → _create_slice_info_text() [crosshair_render]
  → _reset_all_to_orthogonal() [oblique]
  → _capture_baseline_camera_state() [orientation]
  → _update_all_crosshairs() [crosshair_state]
  → _update_slice_positions() [crosshair_state]
  → _update_slice_info_texts() [crosshair_state]
```

All cross-boundary calls are resolved via Python's MRO since all mixins share `self`. No import cycles between mixins. ✅
