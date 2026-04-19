# FAST vs Advanced Viewer — User-Facing Behavior Parity Audit

**Date:** 2026-04-15  
**Version:** v2.3.3  
**Purpose:**  
Full audit of every user-visible interaction (mouse, toolbar buttons, keyboard)
between **FAST mode** (`pydicom_qt` → `QtSliceViewer` + QPainter) and **Advanced mode**
(`vtk_simpleitk` → `ImageViewer2D` + VTK render pipeline).  

> **Design goal:** Both modes must feel identical to the user.  
> Backends are completely separate; unification happens at the toolbar/bridge layer only.

---

## Evidence files

| File | Role |
|------|------|
| `modules/viewer/fast/qt_slice_viewer.py` | All FAST mouse handling and drawing |
| `PacsClient/.../vtk_widget/_vw_interactor.py` | `_QtBridgeStyle` (FAST toolbar→Qt routing) + `_VWInteractorMixin` (Qt mouse overrides) |
| `modules/viewer/interactor_styles/abstract_interactorstyle.py` | Advanced base: VTK observer setup, default mouse handlers |
| `modules/viewer/interactor_styles/default_interaction_interactorstyle.py` | Advanced zoom/pan/W-L/stacked/capture |
| `modules/viewer/interactor_styles/rotate_interactorstyles.py` | Advanced rotation/flip via VTK camera |
| `modules/viewer/interactor_styles/ruler_interactorstyle.py` | Advanced ruler (vtkDistanceWidget) |
| `modules/viewer/interactor_styles/eraser_interactorstyle.py` | Advanced eraser (proximity deletion) |
| `PacsClient/.../patient_toolbar/toolbar_manager.py` | Shared toolbar — calls `set_new_interactorstyle()` for both backends |
| `PacsClient/.../vtk_widget/_vw_scroll.py` | `wheelEvent` for both backends (fast-path at top) |

---

## 1. Mouse Button Behavior (No Tool Active)

| Interaction | Advanced Mode | FAST Mode | Status |
|-------------|--------------|-----------|--------|
| **Right-click drag** | W/L (tracked in `on_right_button_press/move`) | W/L (always, unconditional in `mousePressEvent`) | ✅ Same |
| **Middle-click drag** | **Zoom** (`change_zoom()` called from `on_mouse_move`) | **Zoom** (starts `_zoom_dragging`, same 0.005/px sensitivity) | ✅ Fixed (was Pan) |
| **Left-click drag (no tool)** | **Stacked scroll** (`change_quickly_slices()`) | **Stacked scroll** (`_stacked_dragging` started when `TOOL_NONE`) | ✅ Fixed (was nothing) |
| **Left + Right simultaneous** | Pan (VTK middle-button simulation) | **Pan** (`_lr_pan_active` flag, `_pan_dragging`) | ✅ Fixed (was not implemented) |
| **Ctrl + Left drag** | Not implemented | Always Pan override | ❌ FAST-only |
| **Scroll wheel** | Slice navigation | Slice navigation | ✅ Same direction |
| **Ctrl + Scroll wheel** | **Not implemented** — wheelEvent has no Ctrl check | Zoom toward cursor (`zoom_factor = 1.1/0.909 per notch`) | ❌ FAST-only |

### Notes
- Advanced `on_mouse_move` dispatches based on which button is down:
  `right_down → change_window_level`, `middle_down → change_zoom`,
  `left_down → change_quickly_slices` (the default left-drag when no tool is active),
  `pan_active → super().OnMouseMove()`.
- FAST `mousePressEvent` is hard-coded: right→W/L, middle→zoom, ctrl+left→pan, left→depends on `_tool_mode`.
- **The middle-click inversion is the most surprising difference for users:**
  in Advanced mode middle-click zooms; in FAST mode it pans.

---

## 2. Scroll Wheel Behavior

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Scroll direction** | `step = -step if delta > 0` (up = prev slice) | `slices_delta = -1 if delta > 0` | ✅ Same |
| **Scroll step (all series sizes)** | Always ±1 per wheel input | Always ±1 per wheel input | ✅ Fixed parity |
| **Ctrl + wheel zoom** | Not supported | Zoom toward cursor | ❌ FAST-only |
| **VTK default zoom from wheel** | Blocked (`SetMouseWheelMotionFactor(0)`, `AbortFlagOn`) | N/A (not VTK) | ✅ Both suppress VTK zoom |

---

## 3. Window/Level Drag Sensitivity

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Axes** | `dx → window width`, `dy → level` | `dx → window width`, `dy → level` | ✅ Same |
| **Window sensitivity** | Fixed `dx * 1.5` | Adaptive `dx * (current_window / 500)` | ❌ Different formula |
| **Level sensitivity** | Fixed `dy * 1.3` | Adaptive `dy * (current_window / 500)` | ❌ Different formula |
| **MG (Mammography) boost** | ×10 multiplier for MG modality | **×10 multiplier for MG, DX, CR, XR** (set via `set_modality_hint`) | ✅ Fixed (was not implemented) |
| **Direction (up = higher level?)** | Drag down → level increases (VTK display-Y up, then `dy = -dy`) | Drag up → level increases (`new_level = start - dy*s`) | ✅ Net result same |

### Notes
- FAST uses a single-step formula (`_wl_start_window + dx * sensitivity`) from start of
  drag, so there is no accumulated drift. Advanced accumulates `last_pos → current_pos` per
  frame.
- FAST's adaptive sensitivity means W/L adjustment feels "faster" on a narrow window (like
  bone CT, W=400) and "slower" at large windows (like PET, W=20000). Advanced applies fixed
  gain regardless of current window.
- **Implemented:** FAST W/L applies 10× sensitivity for MG/DX/CR/XR via `_modality_hint`
  (set by `QtViewerBridge.set_modality_hint()` on series load/reset).

---

## 4. Zoom Tool (Toolbar)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Activation** | `set_new_interactorstyle(DefaultInteractionInteractorStyle)` + `activate(ZOOM)` | `_QtBridgeStyle.activate()` → `qv.set_tool_mode(TOOL_ZOOM)` | ✅ Same flow |
| **Gesture** | Left-drag vertical — `camera.Zoom(1.0 + abs(dy)*0.005)` | Left-drag vertical — `_zoom *= (1.0 + (-dy)*0.005)` | ✅ Same sensitivity (0.005/px) |
| **Center point** | Camera center (screen center) | Image center (shifts visible area) | ❌ Slightly different feel |
| **Cursor** | VTK arrow (no explicit set) | `SizeBDiagCursor` (set in `_apply_cursor_for_tool`) | ❌ FAST has cursor, Advanced does not |

---

## 5. Pan Tool (Toolbar)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Gesture** | Left-drag → VTK `super().OnMouseMove()` (turn_on_pan) | Left-drag → `_pan_offset += delta` | ✅ Net behavior same |
| **Cursor** | VTK default | `OpenHandCursor` | ❌ FAST has cursor, Advanced does not |

---

## 6. Window/Level Tool (Toolbar)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Gesture** | Left-drag → `change_window_level()` (same as right-click) | Left-drag → same as right-click W/L | ✅ Same |
| **Cursor** | VTK arrow | `SizeVerCursor` | ❌ FAST has cursor, Advanced does not |
| **Sets flag** | `flag_set_custom_window_level = True` | Emits `window_level_changed` signal | ✅ Both suppress default W/L |

---

## 7. Stacked Scroll Tool (Toolbar)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Gesture** | Left-drag vertical, adaptive threshold | Left-drag vertical, adaptive threshold | ✅ Fixed parity |
| **Step threshold** | Adaptive by stack size (10→4 px tiers) | Adaptive by stack size (10→4 px tiers) | ✅ Fixed parity |
| **Step size** | Adaptive, bounded acceleration (cap by stack size) | Adaptive, bounded acceleration (cap by stack size) | ✅ Fixed parity |
| **Top→bottom traversal model** | Drag distance mapped to stack progression | Drag distance mapped to stack progression | ✅ Added (FAST) |
| **Out-of-bounds handling** | Toolkit-bound interaction lifecycle | Stack stops immediately outside viewer/image area | ✅ Added (FAST) |
| **Via queue** | `queue_interactive_slice_target()` (coalesced) | `slice_scroll_requested.emit(step)` | ✅ Both coalesced |

---

## 8. Rotation Left / Right (Toolbar — One-shot)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Implementation** | `camera.Roll(90)` or `camera.Roll(-90)` on the VTK camera | `_rotation_angle = (_rotation_angle ∓ 90) % 360` + QPainter repaint | ✅ Net visual same |
| **Cumulative** | Yes — each press adds 90° to camera Roll | Yes — `_rotation_angle` accumulates | ✅ Same |
| **Deactivation** | `restore_default_interactorstyle()` immediately (one-shot) | N/A (no lingering state) | ✅ Same |
| **Fit-zoom aware** | No (VTK camera not re-fit after Roll) | `_calculate_fit_zoom()` swaps W/H at 90°/270° | ❌ FAST handles fit-zoom correctly; Advanced does not |

---

## 9. Flip Horizontal / Vertical (Toolbar — One-shot)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Implementation** | `camera.Azimuth(180)` (H) or `camera.Roll(180)` (V) | Boolean flags `_flip_h`, `_flip_v` + QPainter `scale(-1,1)` / `scale(1,-1)` | ✅ Net visual same |
| **Toggle** | Each press re-applies the camera transform (not toggle-aware) | Toggles flag (second press undoes first) | ❌ Advanced always adds, FAST toggles |
| **One-shot** | `restore_default_interactorstyle()` immediately | N/A | ✅ One-shot in both |

> **Note:** Advanced flip is NOT a true toggle — calling flip_horizontal twice applies Azimuth(360°) = no change visually but camera state is drifted. FAST's flag-based approach is correct.

---

## 10. Zoom to Fit (Toolbar — One-shot)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Implementation** | `image_viewer.zoom_to_fit()` (VTK `ResetCamera`) | `qv.zoom_to_fit()` → `_calculate_fit_zoom()` + `_pan_offset=(0,0)` | ✅ Net same |
| **Rotation-aware** | No (VTK ResetCamera ignores Roll) | Yes (swaps W/H at 90°/270°) | ❌ FAST handles rotation correctly; Advanced does not |

---

## 11. Capture (Toolbar — One-shot)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Implementation** | `vtkWindowToImageFilter` + `vtkPNGWriter` | `qv.grab()` (Qt grab) → PNG | ✅ Net same (PNG file saved) |
| **Includes overlays** | Yes (VTK renders everything) | Yes (`grab()` captures all Qt paint layers) | ✅ Same |
| **Timing** | Fires immediately on tool activation | Fires immediately on tool activation | ✅ Same |

---

## 12. Measurement Tools (Ruler, Angle, Arrow, Text, ROI, Two-Line Angle)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Storage** | `widgets_by_slice` dict keyed by VTK slice index | `ToolController` — Qt annotation objects | ✅ Both per-slice |
| **Rendering** | VTK widgets (`vtkDistanceWidget`, `vtkAngleWidget`, etc.) | QPainter drawing in `_paint_tool_annotations` | ✅ Net same visual |
| **Placement** | Click-to-place (VTK event observer handles placement) | Click-to-place (ToolController `on_mouse_press`) | ✅ Same UX |
| **Auto-deactivate after placing** | Yes (VTK `auto_deactivate_tool()`) | Yes (PLACING→IDLE callback chain to `_QtBridgeStyle`) | ✅ Fixed parity |
| **Drag-to-move existing annotation** | Yes — `_find_any_drag_target()` on left-click → hover shows `VTK_CURSOR_HAND` | Depends on ToolController | ⚠️ Needs verification |
| **Visibility per-slice** | Yes — `update_slice()` shows/hides VTK widgets | Yes — ToolController per-slice | ✅ Both per-slice |
| **Cursor on placement** | VTK default (`VTK_CURSOR_POINTER`) | `CrossCursor` (set in `set_tool_mode`) | ❌ Different cursors |

---

## 13. Eraser Tool

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Hit detection** | Pixel-distance to nearest annotation (10px threshold) | ToolController proximity deletion | ✅ Same concept |
| **Cursor** | VTK default (no explicit set in `EraserInteractorStyle`) | `ForbiddenCursor` ✅ (fixed — was overridden by `_apply_cursor_for_tool`) | ⚠️ Advanced has no custom cursor — should add |
| **Auto-deactivate after erase** | Yes (`auto_deactivate_tool()`) | Depends on ToolController | ⚠️ Needs verification |

---

## 14. Sync Point (Cross-Viewer Reference Dot)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Activation** | `toggle_sync_point()` → `_sync_point_enabled = True` | Same | ✅ Same |
| **Dot visual** | VTK actor (rendered in VTK scene) | `_paint_sync_point()` — QPainter red dot with white halo | ✅ Net same |
| **Dragging** | Via `_VWInteractorMixin.mousePressEvent` → `_apply_sync_point(world_pos)` | Same path (Qt bridge delegates to parent VTKWidget) | ✅ Same |

---

## 15. Toolbar Toggle State (Button Highlighting)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **State tracking** | `tool_selected` in `ToolbarManager` | Same `tool_selected` | ✅ Same |
| **Toggle off** | `restore_default_interactorstyle()` → `DefaultInteractionInteractorStyle` | `restore_default_interactorstyle()` → `_QtBridgeStyle` with `TOOL_NONE` | ✅ Same result |
| **`handle_buttons_checked()`** | Called after every state change | Same | ✅ Same |

---

## 16. Default Cursor (No Tool Active)

| Aspect | Advanced Mode | FAST Mode | Status |
|--------|--------------|-----------|--------|
| **Cursor** | VTK `VTK_CURSOR_ARROW` | unsetCursor() (inherits OS default) | ✅ Both show arrow |
| **Hover over annotation** | `VTK_CURSOR_HAND` (from `_find_any_drag_target`) | `SizeAllCursor` or `CrossCursor` (from `ToolController.get_hover_cursor_shape`) | ❌ Different hover cursors |

---

## Summary: P1 Issues (Must Fix for Parity)

| # | Issue | Where to Fix | Status |
|---|-------|-------------|-------|
| ~~P1-1~~ | ~~Middle-click = zoom in Advanced, pan in FAST~~ | Fixed in `qt_slice_viewer.py` | ✅ Done |
| ~~P1-2~~ | ~~Default left-drag (no tool) = stacked in Advanced, nothing in FAST~~ | Fixed in `qt_slice_viewer.py` | ✅ Done |
| P1-3 | **Ctrl+Wheel zoom FAST-only** — by design, no change needed | — | ℹ️ Intentional |
| ~~P1-4~~ | ~~Stacked threshold fixed at 10px in FAST, adaptive in Advanced~~ | Fixed in `qt_slice_viewer.py` + `abstract_interactorstyle.py` | ✅ Done |
| ~~P1-5~~ | ~~MG W/L 10× sensitivity FAST-missing~~ | Fixed — also covers DX/CR/XR | ✅ Done |
| ~~P1-6~~ | ~~Left+Right simultaneous pan Advanced-only~~ | Fixed in `qt_slice_viewer.py` | ✅ Done |

---

## Recommendation Policy (adopted)

1. **Wheel = precision mode:** always navigate by exactly one slice per wheel step.
2. **Stack drag = speed mode:** adaptive threshold/acceleration by total slice count.
3. **Do not share one step formula** between wheel and stack drag.
4. **Tool lifecycle parity rule:** placement complete → restore default mode → clear toolbar selection.

---

## Summary: P2 Issues (Should Fix)

| # | Issue | Where to Fix | Priority |
|---|-------|-------------|---------|
| P2-1 | **Zoom tool cursor FAST-only** (`SizeBDiagCursor`) | Add `VTK_CURSOR_SIZENNNE` or similar to `DefaultInteractionInteractorStyle.activate(ZOOM)` | P2 |
| P2-2 | **Pan tool cursor FAST-only** (`OpenHandCursor`) | Same — add to `DefaultInteractionInteractorStyle.activate(PAN)` | P2 |
| P2-3 | **W/L tool cursor FAST-only** (`SizeVerCursor`) | Same — add to `DefaultInteractionInteractorStyle.activate(WINDOW_LEVEL)` | P2 |
| P2-4 | **Eraser cursor Advanced missing** | Add cursor set in `EraserInteractorStyle.__init__` or `activate()` | P2 |
| P2-5 | **Flip toggle asymmetry** | Advanced `flip_horizontal/vertical` is not a true toggle (double-press drifts camera). Fix `RotateInteractorStyle` to track and invert on second press | P2 |
| P2-6 | **Guard wheel precision policy** | Keep wheel path at ±1 and prevent future adaptive skip regressions | P2 |
| P2-7 | **Rotation fit-zoom Advanced-missing** | After `camera.Roll()`, call `ResetCamera` or equivalent so image refits viewport | P2 |
| P2-8 | **W/L sensitivity formula mismatch** | Unify to one formula. Recommend: FAST's adaptive `current_window/500` approach (dynamically tuned) + MG 10× | P2 |

---

## Summary: P3 Issues (Nice to Have)

| # | Issue | Where to Fix | Priority |
|---|-------|-------------|---------|
| P3-1 | **Annotation drag-to-move FAST unverified** | Verify `ToolController` supports drag-move of placed annotations; if not, add | P3 |
| P3-2 | **Auto-deactivate parity follow-up** | Add dedicated regression tests for completion callback chain in FAST | P3 |
| P3-3 | **Hover cursor on annotations differs** | Unify: both should show `OpenHandCursor` or `SizeAllCursor` when hovering over a movable annotation | P3 |
| P3-4 | **Measurement cursor differs** | Advanced uses VTK pointer, FAST uses `CrossCursor`. Pick one and implement in both | P3 |

---

## Implementation Notes (Current)

- Wheel and stack-drag now follow separate UX contracts:
  - **Wheel:** fixed ±1 precision browsing.
  - **Stack drag:** adaptive threshold and bounded acceleration by slice count.
- FAST measurement tool completion now mirrors Advanced lifecycle:
  placement complete → restore default mode → clear toolbar selection.
- Remaining parity work is mostly cursor/visual consistency and additional regression tests,
  not core interaction logic.

---

## Fixed This Session

| Fix | File | Notes |
|-----|------|-------|
| Eraser cursor double-set | `_vw_interactor.py` `_apply_cursor_for_tool` | `PointingHandCursor` → `ForbiddenCursor` |
| Middle-click = zoom | `qt_slice_viewer.py` | Was pan; now starts `_zoom_dragging` to match Advanced |
| Default left-drag (TOOL_NONE) = stacked scroll | `qt_slice_viewer.py` | Matches Advanced default left-drag behavior |
| Left+Right simultaneous = pan | `qt_slice_viewer.py` | `_lr_pan_active` + button-down tracking (`_left_button_down`, `_right_button_down`) |
| Radiography W/L 10× sensitivity | `qt_slice_viewer.py` | `_modality_hint` checked; MG/DX/CR/XR get `modality_mult = 10.0` |
| Modality hint wiring | `qt_viewer_bridge.py` | `set_modality_hint()` called in `__init__` and `reset_image_viewer` from `metadata['series']['modality']` |
| FAST auto-deactivate on tool completion | `qt_slice_viewer.py`, `_vw_interactor.py` | Mirrors Advanced `auto_deactivate_tool()` chain; toolbar state clears |
| Wheel precision policy (no skip) | `_vw_scroll.py` | Wheel path forced to ±1 only |
| Adaptive stack policy by slice count | `qt_slice_viewer.py`, `qt_viewer_bridge.py`, `abstract_interactorstyle.py` | Both backends use adaptive threshold + bounded acceleration |
