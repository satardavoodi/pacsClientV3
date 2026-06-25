# Dental Curve MPR — Code & Architecture Review (read-only)

**Date:** 2026-06-22
**Scope:** Review-only. No code was modified. This is the as-found map of the
"Dental Curve MPR" feature (Patient Tab → MPR dropdown), produced before any
optimization or behavior change.

---

## 0. Headline findings (read these first)

1. **There are THREE separate curved-MPR engines in the repo.** The "Dental Curve
   MPR" button uses two of them; the third is a *different button*. This is the
   single biggest source of confusion and risk.
   - `modules/mpr/zeta_mpr/curved_mpr.py` → `CurvedMPRGenerator` — **the Dental
     button's generation engine** (slice stack + panoramic).
   - `modules/mpr/curved_mpr/` package → `CurvedMPRPanoramicView` / `CurvedMPRViewport`
     (Dental's **display**) + `CurvedMPRModule` / a *second* `CurvedMPRGenerator`
     (used by the legacy advanced viewer, **not** by the Dental button).
   - `modules/mpr/zeta_mpr/CurveMPR/` package → `CurveMPRCore` / `CurveMPRWidget` /
     `CurveMPRInteractorStyle` — backs the **separate "Curve MPR" button**
     (`toggle_new_curve_mpr`), **not** "Dental Curve MPR".

2. **Two different classes are both named `CurvedMPRGenerator`** —
   `zeta_mpr/curved_mpr.py:1382` (has `generate_panoramic_view`) and
   `curved_mpr/curved_mpr_module.py:31` (does not). The Dental path depends on
   importing the *zeta* one by its exact path. Easy to wire the wrong one.

3. **The Dental result display instantiates VTK render windows even in FAST/V2
   mode.** `CurvedMPRPanoramicView` creates a `QVTKRenderWindowInteractor` plus two
   `vtkImageViewer2` pipelines. This is in tension with the project rule "FAST viewer
   mode must NEVER instantiate VTK render windows." (Point *collection* respects the
   rule by being a no-op on the FAST bridge — see §6/§9.)

4. **Showing the result performs a GLOBAL layout teardown.**
   `_show_curved_mpr_result` calls `patient_widget.cleanup_all_viewers()` +
   `lst_nodes_viewer.clear()` and rebuilds the grid to a single 1×1 cell — destroying
   any open MPR and every other viewport, with no restore of the prior layout.

5. **All generation diagnostics are `print()` to stdout, not `logging`.** Nothing
   from the Dental generation/display path lands in `user_data/logs/`. Debug output
   is verbose and contains Unicode glyphs (`✓ ⚠ ×`) that can raise
   `UnicodeEncodeError` on a legacy Windows console codepage.

---

## 1. Entry point

| Step | Location | Detail |
|---|---|---|
| Menu item | `toolbar_manager.py:3342-3345` | `curved_mpr_btn = create_dropdown_tool('Dental Curve MPR', 'fa5s.bezier-curve', '#8b5cf6')` inside the MPR dropdown builder |
| Signal | `toolbar_manager.py:3344` | `curved_mpr_btn.clicked.connect(partial(self._on_curved_mpr_dropdown_clicked, dropdown=dropdown))` |
| Dropdown handler | `toolbar_manager.py:7860` | `_on_curved_mpr_dropdown_clicked` → `self._show_curved_mpr_panel()` then `dropdown.close()` |
| Panel | `toolbar_manager.py:836` | `_show_curved_mpr_panel` — floating `QDialog` "Curved MPR Path Builder" |

The *sibling* button "Curve MPR" (`toolbar_manager.py:3348-3350` →
`_on_new_curve_mpr_dropdown_clicked:7865` → `toggle_new_curve_mpr:4993`) is a
**different feature** backed by `zeta_mpr/CurveMPR/`. Do not conflate them.

---

## 2. Main classes & functions involved (the wired Dental path)

**Orchestration — `PacsClient/.../patient_toolbar/toolbar_manager.py`:**
- `_show_curved_mpr_panel` (836) — builds the path-builder dialog; captures
  `self._curved_mpr_viewer = selected_widget.image_viewer` (980).
- `_toggle_point_adding` (993) — turns picking on/off; **monkeypatches**
  `_curved_mpr_viewer._add_curved_mpr_point` to also refresh the list (1003-1007).
- `_update_points_list` (1020), `_clear_curved_mpr_points` (1030).
- `_generate_curved_mpr` (1039) — guards `len(points) >= 2`, then
  `_generate_curved_mpr_from_points(points, viewer.vtk_image_data)`.
- `_generate_curved_mpr_from_points` (1183) — imports
  `from modules.mpr.zeta_mpr.curved_mpr import CurvedMPRGenerator`; runs generation
  under `QApplication.setOverrideCursor(WaitCursor)`.
- `_show_curved_mpr_result` (1239) — builds panoramic, creates
  `CurvedMPRPanoramicView`, **rebuilds grid to 1×1**.
- `_show_curved_mpr_result_simple` (1316) — `QDialog` fallback if the grid path throws.
- `_close_curved_mpr_panel` (1066), `is_vtk_widget` (1478, must accept
  `CurvedMPRViewport`).

**Point collection — `modules/viewer/advanced/viewer_2d.py`, class `ImageViewer2D` (172):**
- `enable_curved_mpr_mode` (3769) — registers `LeftButtonPressEvent` observer.
- `_on_curved_mpr_click` (3806) — display→world via `vtkWorldPointPicker` (fallback:
  manual `vtkCoordinate` + slice/orientation reconstruction).
- `_add_curved_mpr_point` (3904) — adds `vtkSphereSource` marker + centerline actor.
- `_clear_curved_mpr_visuals` (4005), `get_curved_mpr_points` (4266).
- State: `curved_mpr_points`, `curved_mpr_observer_id`, `vtk_image_data` (init 205-239).
- **FAST bridge stub — `modules/viewer/fast/qt_viewer_bridge.py:1887`:**
  `enable_curved_mpr_mode` sets `self.curved_mpr_mode = False  # Not supported in Qt mode`;
  `vtk_image_data` is a `_MockVTKImageData` shell (no real volume).

**Generation engine — `modules/mpr/zeta_mpr/curved_mpr.py`:**
- `Path3D` (41) — hand-rolled Catmull-Rom spline (tension=0.5, 50 samples/segment),
  `sample_uniform` (195), `get_tangent_at` (245). No scipy / no `vtkParametricSpline`.
- `PlaneGenerator` (280) — parallel-transport frames; `_initial_normal` (438) is
  **explicitly biased for a dental arch in the axial XY plane** (forces Binormal → +Z).
- `ResliceEngine` (721) — `reslice_along_path` (749, cubic `vtkImageReslice` per slice),
  `generate_panoramic_image_slicer_method` (799, Slicer two-step).
- `CurvedMPRGenerator` (1382) — `__init__(image_data)` (1397, expects prebuilt
  `vtkImageData`), `set_centerline` (1410), `generate_curved_mpr` (1449),
  `generate_panoramic_view` (1514).
- Also present but **not on the Dental path:** `InteractiveCurvedMPR` (1572),
  `MandibularUnfoldingModule` (1734), `MultiPlanarSync` (1931),
  `create_vessel_curved_mpr` (2111, documented placeholder).

**Display — `modules/mpr/curved_mpr/curved_mpr_panoramic_view.py`:**
- `CurvedMPRViewport` (188, `QWidget` wrapping a `QVTKRenderWindowInteractor:203`) —
  the cell the toolbar treats as the active viewport.
- `CurvedMPRPanoramicView` (331, `QWidget`) — dual panel: left panoramic
  (`vtkImageViewer2:653`), right cross-section (`vtkImageViewer2:715`).
- `CurvedMPRInteractorStyle` (125) — L/R drag = W/L, middle = pan.
- `ImageViewerWrapper` (22) — duck-typed shim so toolbar `InteractorStyle` tools work.

---

## 3. Data flow — menu click → render

```
Dental Curve MPR button (3343)
  └─> _on_curved_mpr_dropdown_clicked (7860) ─> _show_curved_mpr_panel (836)
        • validates selected_widget via is_vtk_widget + has image_viewer
        • opens floating QDialog "Curved MPR Path Builder"
        • self._curved_mpr_viewer = selected_widget.image_viewer   (= ImageViewer2D)
        • resets curved_mpr_points=[]; _clear_curved_mpr_visuals()
  └─> user: "Start Adding Points" ─> _toggle_point_adding (993)
        • viewer.enable_curved_mpr_mode(True)  (viewer_2d.py:3769)
            └─ AddObserver('LeftButtonPressEvent', _on_curved_mpr_click)
        • monkeypatch viewer._add_curved_mpr_point -> also refresh list
  └─> user clicks on image ─> _on_curved_mpr_click (3806)
        • vtkWorldPointPicker display->world
        • _add_curved_mpr_point (3904): vtkSphere marker + centerline actor
        • point appended to curved_mpr_points
  └─> user: "Generate Curved MPR" ─> _generate_curved_mpr (1039)
        • points = get_curved_mpr_points()  (>=2 required)
        • _generate_curved_mpr_from_points(points, viewer.vtk_image_data) (1183)
              from modules.mpr.zeta_mpr.curved_mpr import CurvedMPRGenerator
              gen = CurvedMPRGenerator(image_data); gen.set_centerline(points)
              slice_size=150.0 (hardcoded); num_slices=min(len(points)*15, 60)
              curved_image = gen.generate_curved_mpr(...)   # N x vtkImageReslice (cubic)
  └─> _show_curved_mpr_result (1239)
        • panoramic_image = gen.generate_panoramic_view(thickness=10mm, height=80mm,
                                                        projection='mean')   # up to 500 reslices
        • viewer_widget = CurvedMPRPanoramicView(curved_image, n, panoramic_image)
              └─ QVTKRenderWindowInteractor + 2x vtkImageViewer2 (VTK render windows)
        • patient_widget.cleanup_all_viewers()      <-- DESTROYS ALL VIEWPORTS
        • patient_widget.lst_nodes_viewer.clear()
        • patient_widget.vtk_layout.addWidget(viewer_widget, 0, 0)   <-- grid -> 1x1
        • NodeViewer wrapper; selected_widget = viewer_widget.active_viewport
        (on exception -> _show_curved_mpr_result_simple QDialog fallback, 1316)
```

---

## 4. Per-question findings

**1. Where the menu item is defined** — §1 (`toolbar_manager.py:3343`).

**2. Command/event on click** — Qt `clicked` signal → `partial(_on_curved_mpr_dropdown_clicked)`
→ `_show_curved_mpr_panel`. There is **no command bus / ViewModel**; it is a direct
Qt slot chain on the toolbar manager.

**3. Which ViewModel/service/control/renderer handles it** — No MVVM. The toolbar
manager is the controller; `ImageViewer2D` is the point-collection control; the
*renderer* split is `CurvedMPRGenerator` (compute, headless VTK) + `CurvedMPRPanoramicView`
(VTK display). See §2.

**4. How it receives the active series/viewport** — Via
`self.patient_widget.selected_widget` and its `.image_viewer` (`ImageViewer2D`) and
`.vtk_image_data` (the prebuilt `vtkImageData` volume). It does **not** re-resolve the
series from disk/DB; it reuses whatever volume the active VTK viewport already holds.

**5. How it creates / switches into Dental Curve MPR mode** — Two stages:
*picking mode* (an extra VTK observer on the existing interactor — it does **not** swap
the interactor style and does **not** go through the normal MPR tool toggle), then
*result mode* (replace the whole grid with the `CurvedMPRPanoramicView` cell, §3/§9).

**6. Feature handling:**
- **Volume data** — Receives a prebuilt `vtkImageData`; never builds/decodes/caches a
  volume itself (`CurvedMPRGenerator.__init__:1397`). Only reads spacing/origin/dims.
- **Axial source images** — Implicit: the volume is whatever the active viewport built
  from the axial stack. Frame seeding (`_initial_normal:438`) **assumes the arch lies
  in the axial XY plane** with Z = superior-inferior.
- **Curved plane generation** — Catmull-Rom spline through clicked points →
  parallel-transport frames → per-frame cubic `vtkImageReslice`
  (`reslice_along_path:749` / `_extract_slice:1211`). Slices are forced **square**
  (`slice_height` arg is ignored: `slice_size = max(slice_width, slice_height)`).
- **Panoramic / dental-curve reconstruction** — `generate_panoramic_view:1514` →
  Slicer-style two-step (`generate_panoramic_image_slicer_method:799`): build a
  straightened volume, then mean (or max/MIP) projection across the radial thickness
  (`slice_thickness_mm`, Dental passes 10 mm). Correct anisotropic output spacing from
  real path length. (If the generator's panoramic is `None`, the display widget builds
  its own MIP via `_create_mip_image` — numpy + `scipy.ndimage.zoom`, on the main thread.)
- **Cross-sections** — The curved stack itself is the set of perpendicular cross-sections
  (right panel). `MultiPlanarSync` (1931) can produce on-demand orthogonal slices but is
  not wired into the Dental flow.
- **Slice navigation** — **No slider/buttons** in the result widget. Scrolling relies on
  the VTK interactor and, if a toolbar stack tool is active, on the synthesized
  `FunctionalSlider` → `ImageViewerWrapper.set_slice`. A red reference line on the
  panoramic tracks the current cross-section slice, synced by a **100 ms `QTimer` poll**
  (`_check_slice_change`).
- **Window/Level** — Generator preserves raw scalars (no WL). The display widget computes
  auto-WL from `GetScalarRange()` and supports interactive WL via the custom interactor
  (L/R drag). Independent of the main viewport's WL.
- **Zoom/Pan** — Pan = middle-drag (`StartPan/EndPan`); zoom = camera presets
  (`Zoom(3.0)` panoramic, `Zoom(1.1)` cross-section) + `ResetCamera` for "fit". No
  dedicated wheel-zoom override; relies on inherited `vtkInteractorStyleImage`/toolbar.
- **Measurements / annotations** — **None implemented** in the curved-MPR display
  (`widgets_by_slice = {}` exists only as a compatibility stub). The only overlay is the
  red reference line.

**7. Interaction with the normal MPR pipeline** — **Decoupled.** Dental does not call
`toggle_zeta_mpr` / `check_and_deactivate_tools` / `turn_off_all_tools`, and does not set
`tool_selected`. It runs as a standalone dialog + observer + monkeypatch. (By contrast,
"Curve MPR" `toggle_new_curve_mpr:5037` and the older `toggle_curved_mpr:5816` *do* go
through `check_and_deactivate_tools`.)

**8. Reuse vs separate logic** — Mostly **separate**. It shares the active viewport's
volume and the toolbar's `is_vtk_widget`/tool-gating, and reuses `ImageViewer2D`'s
picking infrastructure, but the spline/frames/reslice/panoramic math
(`zeta_mpr/curved_mpr.py`) and the dual-panel display (`curved_mpr/curved_mpr_panoramic_view.py`)
are bespoke and do **not** reuse the standard MPR viewer (`zeta_mpr/mpr_viewer/`).

**9. Global layout vs active viewport** — **Global.** The result path calls
`cleanup_all_viewers()` + `lst_nodes_viewer.clear()` and rebuilds the grid to 1×1
(`toolbar_manager.py:1285-1303`). The *picking* phase, by contrast, only adds an observer
to the active viewport.

**10. Effect on other viewports / existing MPR** — Opening the result **destroys all
other cells and any open MPR** (via `cleanup_all_viewers`). There is no save/restore of
the prior layout, and no selective preservation (unlike `turn_off_all_tools_after_switch`).

**11. Caching / decoding / volume-building** — The generator does **no** caching and
**no** volume building/decoding; each generate call recomputes spline→frames→all reslices
from scratch and keeps only `self.curved_image`. The display widget holds live
`vtkImageViewer2` + `vtkImageData` objects but has **no `closeEvent`/`Finalize`/timer
stop** — so they (and the 100 ms timer) leak until Qt parent-destruction.

**12. Logs produced** — All `print()` to stdout (VS Code terminal), e.g.
`[CURVED MPR] Starting generation with N points...`, `[CURVED MPR] Generating N slices...`,
`[PANORAMIC] ✓ Generated: ...`, `[PTF ...]`, `[AUTO-CROP] ...`, `[REF LINE] ...` (every
~100 ms while scrolling). **Nothing routes to `user_data/logs/`.** The lone real
`logging.warning` (`[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] ...`) lives in the *legacy*
`curved_mpr_module.py`, not the zeta engine the Dental button uses.

---

## 5. Dependence on normal MPR / viewer state

- **Hard dependency on the non-FAST VTK path.** Point picking needs a real
  `ImageViewer2D` (renderer + interactor + `vtkWorldPointPicker`) and a real
  `vtk_image_data` volume. On a FAST/Qt viewport the bridge stub makes
  `enable_curved_mpr_mode` a no-op and `vtk_image_data` a mock, so the panel opens but
  **clicks register no points and generation cannot proceed.**
- **Depends on `selected_widget` + `.image_viewer` + `.vtk_image_data`** being populated
  by the active viewport at the moment the panel opens.
- **Depends on `is_vtk_widget()` accepting `CurvedMPRViewport`** so toolbar tools keep
  working on the result cell.
- **Independent of** the MPR tool-state machine (`tool_selected`, `toggle_zeta_mpr`).

---

## 6. Known risks & fragile areas

1. **FAST-rule tension (highest architectural risk).** `CurvedMPRPanoramicView`
   instantiates VTK render windows (`QVTKRenderWindowInteractor` + 2× `vtkImageViewer2`)
   even under FAST/V2. Documented as a `QVTKRenderWindowInteractor` site in
   `docs/plans/performance/FAST_2D_CELL_SEPARATION_PLAN.md`.
2. **No teardown → leaked timer + render windows → use-after-free.** No `closeEvent`,
   no `Finalize()`, the 100 ms reference-line `QTimer` is never stopped. When the next
   `cleanup_all_viewers()` or app shutdown finalizes the VTK objects, a still-queued
   timer tick calls `crosssection_viewer.GetSlice()` on a dead render window (only a bare
   `except: pass` protects it). This matches the PySide6 use-after-free crash class noted
   elsewhere in the project history.
3. **Destructive global layout change with no restore.** `cleanup_all_viewers()` wipes
   every viewport (and any open MPR) to show a 1×1 curved-MPR cell. Returning to the
   prior layout is not implemented here.
4. **Duplicate `CurvedMPRGenerator` class name** (zeta vs curved_mpr package); only the
   zeta one has `generate_panoramic_view`. A future refactor that changes the import path
   silently breaks panoramic generation.
5. **Synchronous heavy compute on the GUI thread.** The reslice stack and (especially)
   the up-to-500-position panoramic + the main-thread MIP (`scipy.ndimage.zoom` 2×/10×)
   run on the UI thread. `processEvents()` is called *before* the heavy loops, not during,
   so the UI freezes for the duration.
6. **Monkeypatch asymmetry.** `_add_curved_mpr_point` is restored only in the
   `_toggle_point_adding` else-branch; `_close_curved_mpr_panel` disables the mode but
   does not restore the original method. An abnormal close can leave the viewer's method
   patched.
7. **Dental-axial orientation bias.** `_initial_normal` assumes the arch is in the axial
   plane (Z = superior-inferior). A rotated/oblique or non-dental volume gets the wrong
   frame seeding → distorted panoramic/cross-sections.
8. **Geometry simplifications.** `slice_height` is ignored (square slices), and the
   straightened curved volume is written with isotropic spacing — both can mismeasure on
   anisotropic CBCT. Panoramic spacing is correct; the curved stack is not.
9. **`print()`-only, Unicode-laden diagnostics.** Not captured in `user_data/logs/`, and
   `✓/⚠/×` can raise `UnicodeEncodeError` on a cp1252 Windows console mid-reconstruction.
10. **Exception-unguarded VTK calls + reshape.** The generator has essentially one
    `try/except`; `vtkImageReslice` / `reshape` failures propagate straight to the GUI.
11. **Three divergent display paths drift** (panoramic view / simple `QDialog` / legacy
    `CurvedMPRView` window) — only the panoramic path is maintained.

---

## 7. Bottlenecks (performance)

| Hot spot | Location | Cost |
|---|---|---|
| Curved slice stack | `ResliceEngine.reslice_along_path` / `_extract_slice` | N × `vtkImageReslice` (cubic) + DeepCopy + vtk→numpy, synchronous. Dental caps `num_slices ≤ 60`. |
| Panoramic | `generate_panoramic_image_slicer_method` | up to **500** reslices + a `(positions × height × thickness)` float32 intermediate volume. |
| MIP fallback | `CurvedMPRPanoramicView._create_mip_image` | full-volume numpy reshape + `np.max` slab + `scipy.ndimage.zoom` 2×/10×, **on the GUI thread**, at widget construction (only when no panoramic supplied). |
| Reference line | `_check_slice_change` | 100 ms polling `QTimer` (also the leak source). |
| (off-path) Mandibular unfold | `MandibularUnfoldingModule._sample_panoramic` | O(width×height) Python point inserts — not on the Dental path, avoid wiring in. |

---

## 8. Areas that MUST be protected before any change

- **The non-FAST VTK requirement.** Any change must keep point picking working on the
  `ImageViewer2D` path (real renderer + `vtkWorldPointPicker`) and must not silently
  enable a broken Dental flow on the FAST bridge.
- **`is_vtk_widget()` must keep accepting `CurvedMPRViewport`** or the toolbar disables
  all tools on the result cell.
- **The exact import `from modules.mpr.zeta_mpr.curved_mpr import CurvedMPRGenerator`** —
  it must resolve to the zeta class (the one with `generate_panoramic_view`).
- **`cleanup_all_viewers()` semantics.** It is clinically destructive; any layout rework
  must not orphan or corrupt other patients'/studies' viewports, and should consider
  saving/restoring the prior layout rather than hard-wiping.
- **Geometry/orientation seeding and spacing** (`_initial_normal`, frame transport,
  output spacing) are clinically load-bearing for panoramic/cross-section accuracy — do
  not alter casually; changes need live dental-CBCT validation.
- **The monkeypatch restore symmetry** of `_add_curved_mpr_point`.
- **Clinical guardrails from CLAUDE.md:** preserve overlays/measurements/sync/reference
  lines elsewhere; FAST mode must never instantiate VTK render windows (note the existing
  tension in finding §0.3); minimal, reversible edits only.

---

## 9. Suggested safe next steps (not yet applied)

These are *candidates* for when change requests begin — none are implemented:
- Add a `closeEvent`/teardown to `CurvedMPRPanoramicView` that stops
  `_reference_line_timer` and finalizes the two `vtkImageViewer2` render windows
  (addresses the leak/use-after-free, finding §6.2) — flag-gated, behavior-preserving.
- Consider not calling `cleanup_all_viewers()` (open the result in a dedicated cell/tab,
  or save+restore the prior layout) — but only with live multi-study validation.
- Move generation off the GUI thread (or chunk it) and route diagnostics through
  `logging` so they reach `user_data/logs/`.
- Rename one of the two `CurvedMPRGenerator` classes to remove the ambiguity.

*All findings above are read-only observations; await specific change requests before
editing.*
