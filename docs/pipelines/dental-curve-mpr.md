# Dental Curve MPR — Pipeline (as-built)

**Status:** as-built record + regression guard. Last updated 2026-06-22.
**Companion review:** `docs/reports/DENTAL_CURVE_MPR_CODE_REVIEW_2026-06-22.md`
(the full read-only audit this doc was distilled from).

This documents the Patient-Tab **Dental Curve MPR** feature: what it is, the exact
click-to-render path, the three same-named code areas it touches, the clean-up
landed on 2026-06-22, and the invariants that must not be broken.

> Clinical guardrail: the 2026-06-22 pass was **documentation + safe cleanup only**.
> It did **not** change the reconstruction math, the layout teardown, or FAST-mode
> behaviour. Those remain staged (see §7).

---

## 1. What it is

Dental Curve MPR builds a **Curved Planar Reformation (CPR)** from a volume: the user
clicks points along the dental arch, the app fits a smooth curve, reslices the volume
along that curve into a stack of perpendicular cross-sections, and projects a
**panoramic (OPG-style)** image. It is dual-panel: panoramic on the left (with a
reference line), the perpendicular cross-section on the right.

---

## 2. THREE engines — only two are this feature (read this first)

The repository contains three curved-MPR code areas. Mixing them up is the single
biggest hazard when editing.

| Area | Key classes | Used by | Role here |
|---|---|---|---|
| `modules/mpr/zeta_mpr/curved_mpr.py` | `CurvedMPRGenerator` (+ `Path3D`, `PlaneGenerator`, `ResliceEngine`) | **Dental Curve MPR button** | **Generation engine** (slice stack + panoramic). |
| `modules/mpr/curved_mpr/` | `CurvedMPRPanoramicView`, `CurvedMPRViewport` | **Dental Curve MPR button** | **Display** (dual-panel VTK widget). |
| `modules/mpr/curved_mpr/curved_mpr_module.py` | `CurvedMPRGenerator` (**namesake!**), `CurvedMPRModule` | advanced `viewer_2d.py`; point-collection visuals | Legacy generator + point-pick centerline polydata. |
| `modules/mpr/zeta_mpr/CurveMPR/` | `CurveMPRCore`, `CurveMPRWidget`, `CurveMPRInteractorStyle` | the **separate "Curve MPR" button** (`toggle_new_curve_mpr`) | **Not** this feature. |

**Name collision:** `CurvedMPRGenerator` exists in BOTH
`zeta_mpr/curved_mpr.py` (Dental, has `generate_panoramic_view`, ctor takes only
`image_data`) and `curved_mpr/curved_mpr_module.py` (legacy advanced viewer,
different ctor, no panoramic). The Dental button imports the **zeta** one. The import
in `toolbar_manager._generate_curved_mpr_from_points` must stay
`from modules.mpr.zeta_mpr.curved_mpr import CurvedMPRGenerator`. (Class docstrings in
both files now cross-reference each other.)

---

## 3. Entry point & click→render data flow

```
"Dental Curve MPR" button         toolbar_manager.py:3343 (icon fa5s.bezier-curve)
  └─ clicked → _on_curved_mpr_dropdown_clicked         :7860
       └─ _show_curved_mpr_panel()                     :836   (floating QDialog path-builder)
            • requires is_vtk_widget(selected_widget) + selected_widget.image_viewer
            • self._curved_mpr_viewer = selected_widget.image_viewer   (an ImageViewer2D)
  └─ "Start Adding Points" → _toggle_point_adding       :993
       • viewer.enable_curved_mpr_mode(True)   viewer_2d.py:3769  (adds LeftButtonPress observer)
       • monkeypatch viewer._add_curved_mpr_point → also refresh the list
  └─ click on image → _on_curved_mpr_click   viewer_2d.py:3806
       • vtkWorldPointPicker display→world; _add_curved_mpr_point draws a sphere marker
  └─ "Generate Curved MPR" → _generate_curved_mpr       :1039
       • points = get_curved_mpr_points()  (>= 2 required)
       • _generate_curved_mpr_from_points(points, viewer.vtk_image_data)   :1183
            from modules.mpr.zeta_mpr.curved_mpr import CurvedMPRGenerator
            gen = CurvedMPRGenerator(image_data); gen.set_centerline(points)
            slice_size=150.0 (hardcoded); num_slices=min(len(points)*15, 60)
            curved_image = gen.generate_curved_mpr(...)        # N × vtkImageReslice (cubic)
  └─ _show_curved_mpr_result(curved_image, n, generator)       :1239
       • panoramic_image = gen.generate_panoramic_view(thickness=10mm, height=80mm, 'mean')
       • viewer_widget = CurvedMPRPanoramicView(curved_image, n, panoramic_image)
       • patient_widget.cleanup_all_viewers(); lst_nodes_viewer.clear()   ← GLOBAL teardown
       • vtk_layout.addWidget(viewer_widget, 0, 0)                        ← grid → 1×1
       • selected_widget = viewer_widget.active_viewport
       (on exception → _show_curved_mpr_result_simple QDialog fallback   :1316)
```

### Generation engine (`zeta_mpr/curved_mpr.py`)
- Receives a prebuilt `vtkImageData` (no volume building/decoding/caching).
- `Path3D` = hand-rolled Catmull-Rom spline (tension 0.5). `PlaneGenerator` = parallel
  transport frames; `_initial_normal` is **biased for a dental arch in the axial (XY)
  plane** (Z = superior-inferior).
- `generate_curved_mpr` = one cubic `vtkImageReslice` per slice (slices are square —
  `slice_height` is ignored). `generate_panoramic_view` = Slicer two-step (straightened
  volume → mean/MIP projection across radial thickness; correct anisotropic spacing).
- Fully **synchronous on the calling (GUI) thread**.

### Display (`curved_mpr/curved_mpr_panoramic_view.py`)
- `CurvedMPRPanoramicView` = dual `QVTKRenderWindowInteractor` + two `vtkImageViewer2`
  (panoramic + cross-section). **Instantiates VTK render windows** (see §7.1).
- `CurvedMPRInteractorStyle`: L/R-drag = W/L, middle-drag = pan; camera-zoom presets.
- Reference line on the panoramic tracks the cross-section slice via a **100 ms QTimer
  poll** (`_check_slice_change`).
- No slice slider; no measurements/annotations (only a `widgets_by_slice = {}`
  compatibility stub).

### Feature handling summary
Volume = reused from the active viewport. Window/Level = auto from scalar range +
interactive (independent of the main viewport WL). Zoom/pan = camera presets +
middle-drag. Cross-sections = the reslice stack (right panel). Slice nav = VTK
interactor / toolbar stack tool. Measurements/annotations = none. Caching = none in the
engine.

---

## 4. Relationship to normal MPR & viewports

- **Decoupled from the MPR tool toggle.** Dental does NOT call `toggle_zeta_mpr` /
  `check_and_deactivate_tools` / `turn_off_all_tools`; it runs as a standalone dialog +
  observer + monkeypatch and never sets `tool_selected`.
- **Result display is a GLOBAL layout change.** `_show_curved_mpr_result` calls
  `cleanup_all_viewers()` and rebuilds the grid to a single 1×1 cell — destroying any
  open MPR and every other viewport, with no restore.
- **FAST dependency.** Point picking only works on the non-FAST VTK path
  (`ImageViewer2D`). The FAST bridge stubs `enable_curved_mpr_mode`
  (`qt_viewer_bridge.py:1887`, sets `curved_mpr_mode = False`), so on a FAST/Qt viewport
  the panel opens but no points register.

---

## 5. Logging

As of 2026-06-22 the engine and display files route their legacy `print()` diagnostics
to the **logging** subsystem (so they reach `user_data/logs/`) via a module-scope
`print` shadow — the same pattern as
`PacsClient/.../patient_widget_core/_pw_viewers.py`
("Redirect print() to logger to avoid synchronous console I/O on Windows").
Messages land at **DEBUG** level under the module loggers
`modules.mpr.zeta_mpr.curved_mpr`, `modules.mpr.curved_mpr.curved_mpr_panoramic_view`,
`modules.mpr.curved_mpr.curved_mpr_module`. The shadow also neutralizes the prior
`UnicodeEncodeError` crash risk from `✓ ⚠ ×` glyphs (logging swallows handler encode
errors; `print` to a cp1252 console did not).

The ~16 `print()` calls inside the Dental methods of the large shared `toolbar_manager.py`
were intentionally **left as-is** (adding a module-wide `print` shadow to that 9k-line
shared file is out of scope for a minimal-safe pass).

---

## 6. Changes landed 2026-06-22 (docs + safe cleanup)

All behaviour-affecting edits are **flag-gated default-ON** with the legacy path kept as
a kill switch.

1. **`print()` → logging** via a module `print` shadow in `curved_mpr.py`,
   `curved_mpr_panoramic_view.py`, `curved_mpr_module.py` (§5). Not gated (logging is not
   a clinical behaviour change); call sites preserved byte-for-byte.
2. **Leaked-timer / use-after-free fix** in `CurvedMPRPanoramicView`
   (`AIPACS_CURVED_MPR_TEARDOWN`, default on):
   - the 100 ms `_reference_line_timer` is now **parented to the widget**
     (`QTimer(self)`) so it dies with the widget and can't fire against a finalized
     render window;
   - new **`_teardown_curved_mpr_vtk()`** (idempotent, exception-guarded) stops the timer
     and `Finalize()`s both render windows;
   - new **`closeEvent()`** calls the teardown.
   - Flag off ⇒ exact legacy behaviour (parentless `QTimer()`, no teardown).
3. **Docstrings** clarifying the three engines and the `CurvedMPRGenerator` name
   collision, on both generators + the display widget + the toolbar import site.

No change to: reconstruction math, `slice_height`/spacing handling, `cleanup_all_viewers`
global teardown, FAST stubs, or the generation thread.

### Flags
| Flag | Default | Effect |
|---|---|---|
| `AIPACS_CURVED_MPR_TEARDOWN` | `1` (on) | Parent the reference-line timer + run `closeEvent`/`_teardown_curved_mpr_vtk`. `0` = legacy (no teardown). |

---

## 7. Known risks still OPEN (deliberately not changed — staged)

These were identified in the review and **left untouched** this pass. Treat as the
backlog; each needs live source-build validation before changing.

1. **FAST-rule tension.** `CurvedMPRPanoramicView` instantiates real VTK render windows
   even under FAST/V2. Resolving this (a Qt/raster panoramic display, or an explicit
   sanctioned exception) is a design decision, not a safe cleanup.
2. **Destructive global layout teardown.** `cleanup_all_viewers()` wipes every viewport
   (and any open MPR) to show the 1×1 result, with no save/restore.
3. **Synchronous heavy compute on the GUI thread** (panoramic up to 500 reslices + a
   main-thread scipy MIP fallback). Move off-thread / chunk + progress.
4. **Geometry simplifications** (`slice_height` ignored → square slices; isotropic output
   spacing on the curved stack; dental-axial `_initial_normal` bias). Clinically
   load-bearing — change only with dental-CBCT validation.
5. **Duplicate `CurvedMPRGenerator` name** — now documented; a rename is still the clean
   long-term fix but touches the legacy advanced-viewer path.

---

## 8. Invariants — protect before any future change

- Keep the Dental import as `modules.mpr.zeta_mpr.curved_mpr` (the engine with
  `generate_panoramic_view`).
- `is_vtk_widget()` must keep accepting `CurvedMPRViewport`, or the toolbar disables all
  tools on the result cell.
- Point picking requires the non-FAST `ImageViewer2D` (renderer + `vtkWorldPointPicker`);
  don't silently "enable" Dental on the FAST bridge.
- Keep the `_add_curved_mpr_point` monkeypatch restore symmetric.
- Don't weaken the new teardown: the timer must stay parented and `closeEvent` must run
  the teardown when `AIPACS_CURVED_MPR_TEARDOWN` is on.
- Don't alter frame seeding / output spacing without dental-CBCT validation.

---

## 9. Verification status

- **Added logic compiles + runs offscreen** (teardown idempotency + flag/shadow logic
  validated in isolation in the Linux sandbox).
- **Full-file `py_compile` / offscreen pytest was BLOCKED** this session by the known
  FUSE-mount staleness/truncation (the bash mount served a stale, truncated copy of every
  large file; CLAUDE.md "sandbox FUSE served STALE edits"). Edits were instead verified
  through the file Read path against the true on-disk content.
- **NEEDS Windows source-build verification (clinical lane):** open Dental Curve MPR on a
  CBCT, generate, scroll the cross-section (reference line follows), then close the cell /
  switch patients / close the app and confirm (a) no crash on teardown, (b) the
  `[CURVED MPR]` / `[REF LINE]` / `[PANORAMIC]` lines now appear in `user_data/logs/`
  (DEBUG) rather than the console. Re-run `tests/code/viewer` once the mount is fresh.
- **Guard test:** `tests/code/viewer/test_curved_mpr_teardown.py` (source-pin; run on
  Windows or a fresh sandbox).

---

## 10. Window/Level inheritance + normal-2D mouse (2026-06-23)

Two display/interaction fixes to the simple viewer (flag-gated default-on; **no
geometry/reconstruction change** — supersedes the "auto W/L" and "L/R-drag = W/L,
middle = pan" notes in §3/§4):

- **Inherit the source CT W/L.** `_setup_viewers` previously computed Window/Level
  from the curved volume's scalar range. It now uses the **source CT viewer's
  current W/L** when provided: `_show_curved_mpr_result` reads
  `self._curved_mpr_viewer.get_window_level()` and passes it to
  `CurvedMPRPanoramicView(..., source_window=, source_level=)`, which applies it
  (the reslice preserves the CT intensity domain, so the same W/L is valid). Falls
  back to the auto W/L when unavailable. Flag `AIPACS_CURVED_MPR_INHERIT_WL`
  (caller-side, default on).
- **Robust per-image Window/Level (washed-out fix, 2026-06-23).** The default
  base window was the **full min/max range** of the volume, applied to BOTH the raw
  cross-section AND the mean-projection panoramic — but a few dense enamel/metal
  voxels stretch that range flat (washed out), and the panoramic lives in a
  different intensity domain than the cross-section, so one window suits neither.
  `_robust_window_level()` now derives W/L from each image's **1st–99th percentile**,
  windowing the panoramic and cross-section **separately** (`pano_window/level`
  vs `cross_window/level`). CBCT gray values are not standardized HU (they vary by
  scanner / FOV / region), so a data-driven window generalizes where a fixed preset
  cannot. The CT-WL inherit still overrides the cross-section when available.
  Appearance only — no geometry/spacing change; interpolation stays the engine's
  cubic reslice. Flag `AIPACS_CURVED_MPR_ROBUST_WL` (default on; `=0` = legacy
  full-range). Guard: `tests/code/viewer/test_curved_mpr_robust_window.py`.

---

## 11. Panoramic sharpening + fallback resample (soft-image fix, step 1, 2026-06-23)

Background + full plan: `docs/plans/architecture/PANORAMIC_RECONSTRUCTION_QUALITY_REVIEW_2026-06-23.md`.
The panoramic looked soft because the **mean projection over a ~10 mm slab** averages out
fine detail (roots, lamina dura, apices) — not because of interpolation (already cubic).
**Step 1** (this change; appearance-only, no geometry/spacing/orientation change):

- **Unsharp mask on the final panoramic.** `_apply_panoramic_unsharp()`
  (`modules/mpr/zeta_mpr/curved_mpr.py`) applies `img + amount·(img − gaussian(img, σ))`
  clipped to range, on the final 2-D `panoramic_flipped` **right before** the VTK output is
  built (`generate_panoramic_image_slicer_method`). Conservative default (amount 0.5, σ 1.0
  px) to avoid oversharpening / fabricated edges. Measurements use world coordinates, not
  these pixel values, so accuracy is unaffected. Flags `AIPACS_CURVED_MPR_SHARPEN` (default
  on), `_AMOUNT`, `_SIGMA`. No-op when disabled, degenerate, or scipy missing.
- **Fallback resample bilinear → cubic.** `_create_mip_image`
  (`curved_mpr_panoramic_view.py`) — the fallback panoramic's 10× vertical
  `scipy.ndimage.zoom` switched from `order=1` (bilinear, visibly soft) to `order=3` (cubic),
  gated `AIPACS_CURVED_MPR_FALLBACK_CUBIC` (default on). Resample quality only; same geometry.
  Only runs when the engine's true panoramic is unavailable.

Guard: `tests/code/viewer/test_curved_mpr_panoramic_sharpen.py` (source-pin + a scipy-guarded
contract check that unsharp restores edge gradient and stays in range).

**Deliberately NOT done yet (review §6, staged):** thin-slab + soft-MIP / weighted ray-sum
projection (the structural sharpness fix), along-curve sampling-density cap, L/R orientation
markers from the DirectionMatrix, and curve Z/tilt adjustment. NEEDS live source-build verify.
- **Normal-2D default mouse.** The default interactor is now the same
  `AbstractInteractorStyle` the normal 2D viewer installs (right-drag = W/L,
  left+right = pan, middle-hold = zoom, left-drag = stack), reused via
  `ImageViewerWrapper` through the new `_make_curved_mpr_default_style()` helper —
  replacing the in-file `CurvedMPRInteractorStyle` (left+right both → W/L, middle →
  pan, no zoom). `CurvedMPRViewport.restore_default_interactorstyle` routes through
  the same helper, so after a measurement tool is turned off the default mouse
  returns. Measurement styles (`RulerInteractorStyle`) already extend the same base
  and are set via `set_new_interactorstyle`, so ruler mode is unaffected. Flag
  `AIPACS_CURVED_MPR_2D_MOUSE` (default on; `=0` = legacy `CurvedMPRInteractorStyle`).
- **Guard:** `tests/code/viewer/test_curved_mpr_2d_mouse_and_wl.py` (source-pin +
  a cross-file mapping-contract check on `AbstractInteractorStyle`).
