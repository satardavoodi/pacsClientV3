# Unified MPR / 3D Pipeline — Architecture Direction

**Date:** 2026-06-22
**Status:** Direction / design intent (no code yet). Governs all future MPR/3D work.
**Directive (user, 2026-06-22):** The **layout, viewport usage, and viewing structure** of Dental
Curve MPR — and of **every** MPR/3D module — must follow the **same structure as standard (Zeta)
MPR**, to create **one unified pipeline and structure for all 3D and all MPR modules**, with **the
ability to add each module's own tools on top** of that shared foundation.

**Why standard MPR is the base:** it already works correctly and reliably — geometry, slice
orientation, VTK rendering, volume construction, coordinate handling, viewport behavior, and
interaction. So it is the reference; everything else conforms to it.

**Reads with:** `docs/reports/DENTAL_CURVE_MPR_VS_STANDARD_MPR_ALIGNMENT_2026-06-22.md` (the
evidence), `docs/pipelines/mpr-geometry-pipeline.md` (the geometry contract),
`docs/plans/DENTAL_CURVE_MPR_IMPROVEMENT_PLAN_2026-06-22.md`, `docs/pipelines/dental-curve-mpr.md`.

---

## 1. The principle (one structure for all MPR/3D)

```
                    ┌─────────────────────────────────────────────┐
                    │      Per-module TOOL layer (varies)          │
                    │  Dental Curve: curve draw + panoramic +      │
                    │   cross-sections + dental UI                 │
                    │  Curve MPR: vessel/airway centerline         │
                    │  Orthogonal: 3-view dialog tools             │
                    │  VRT/3D: presets, clip, segmentation         │
                    └───────────────▲─────────────────────────────┘
                                    │ adds only its own tools
   ┌────────────────────────────────┴────────────────────────────────┐
   │             SHARED MPR/3D FOUNDATION  (= standard Zeta MPR)        │
   │  L4  Viewport / layout: in-place single-cell swap, grid save/     │
   │      restore, cross-link, NO global wipe, viewport-scoped gates    │
   │  L3  VTK rendering: vtkImageResliceMapper+vtkImageSlice (2D),      │
   │      vtkGPUVolumeRayCastMapper (3D), QVTKRenderWindowInteractor    │
   │  L2  Geometry contract: DirectionMatrix/ZetaAnatA LPS triad,       │
   │      X-flip, IPP slice-sign, radiological correction               │
   │  L1  Volume: ONE shared PyDicomLazyVolume.vtk_image_data           │
   │  L5  Lifecycle: cleanup()/Finalize() before deleteLater()         │
   └───────────────────────────────────────────────────────────────────┘
```

A module is "unified" when L1–L5 come **entirely** from the shared foundation and the module only
contributes the top tool layer.

---

## 2. Module inventory & conformance scorecard

Entry points all in `PacsClient/.../patient_toolbar/toolbar_manager.py`.

| Module | Entry | Implementation | L1 volume | L2 geometry | L3 VTK render | L4 viewport/layout | L5 lifecycle | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Standard (Zeta) MPR** ⭐ reference | `toggle_zeta_mpr:4581` | `zeta_mpr/mpr_viewer/widget.py::StandardMPRViewer` | shared | ✅ contract | ✅ reslice+VRT | ✅ in-place cell | ✅ cleanup/Finalize | **BASE** |
| **Dental Curve MPR** | `_show_curved_mpr_panel:836` | `zeta_mpr/curved_mpr.py` + `curved_mpr/curved_mpr_panoramic_view.py` | shared object, no prep | ❌ ignores contract | ❌ `vtkImageViewer2` shim | ❌ `cleanup_all_viewers()` wipe | ◑ flag-gated teardown | **DIVERGES** |
| **Curve MPR** (vessel/airway) | `toggle_new_curve_mpr:4998` | `zeta_mpr/CurveMPR/` (`CurveMPRWidget`) | reuses MPR volume route | ◑ partial | ◑ own VTK panes | ◑ reuses `_restore_selected_viewer` | ◑ | **PARTIAL** |
| **Orthogonal MPR** | `_show_orthogonal_mpr_viewer:1081` | `modules/mpr/orthogonal/` (`OrthogonalMPRWidget`) | **separate SimpleITK builder** | ◑ own | ◑ own | ❌ separate `QDialog` | ◑ | **DIVERGES** |
| **Advanced 3D Slicer** | `slicer_launcher:4499` | `modules/mpr/advanced_3d_slicer/` | external app (own) | n/a (3D Slicer) | external process | external window | external | **OUT OF SCOPE** (separate app) |
| **Legacy curved (vessel)** | `toggle_curved_mpr:5781` | `ImageViewer2D` legacy path | — | — | — | — | — | **LEGACY/retire** |

**Takeaways:**
- Dental Curve MPR and Orthogonal MPR are the two that diverge most (Orthogonal even builds its own
  SimpleITK volume — a second volume pipeline).
- Curve MPR is the closest non-standard module (it already reuses parts of the standard route).
- Advanced 3D Slicer is an external application launch — it is **not** part of this in-app unified
  pipeline and should be left as-is (interop, not a viewport).
- `standard_mpr_viewer_original.py` (225 KB) and `toolbar_integration.py::toggle_new_mpr_zeta` are
  dead/legacy duplicates of the standard viewer — candidates for removal once the unified base is
  factored.

---

## 3. The shared foundation contract (what every module must reuse)

**L1 — Volume (one builder).** All MPR/3D consume `modules/viewer/fast/pydicom_lazy_volume.py::
PyDicomLazyVolume.vtk_image_data` (the same object the 2D viewer holds). No module builds its own
volume. → *Orthogonal MPR's SimpleITK `volume_loader.py` must converge onto this.*

**L2 — Geometry contract.** Orientation rides as the `"DirectionMatrix"` field-data array; standard
MPR derives the patient-LPS `ZetaAnatA` triad (IOP cosines + IPP slice-direction sign), applies the
`vtkImageFlip` X + column-0 negation, and the radiological correction. Plane-aware anatomical cameras
handle oblique/non-axial. This is the single source of geometric truth
(`_mpr_canonicalize.py` / `_mpr_orientation.py`, `docs/pipelines/mpr-geometry-pipeline.md`). Every
module derives its reslice frame **from this**, never from raw `GetSpacing/GetOrigin` alone, and
transforms any picked points (curve control points, crosshairs) into this frame.

**L3 — VTK rendering.** 2D panes = `vtkImageResliceMapper` + `vtkImageSlice` with
`SliceFacesCameraOn`/`SliceAtFocalPointOn` on a `QVTKRenderWindowInteractor` + `vtkRenderer`; 3D =
`vtkGPUVolumeRayCastMapper` + `vtkVolume`. Interactor styles = the standard MPR crosshair/toolbar/VRT
styles. → *No bespoke `vtkImageViewer2` + `ImageViewerWrapper` shim (Dental Curve), and **no QPainter
raster path** — that idea is withdrawn; explicit MPR is the sanctioned VTK path, exempt from the
"FAST 2D viewer never instantiates VTK render windows" rule.*

**L4 — Viewport / layout.** Open **in place at the source cell** (save `_mpr_grid_position`,
`addWidget` at the same row/col), cross-link `_<module>_widget`/`_original_widget`, set
`tool_selected`, and route open/close through `check_and_deactivate_tools` + `_restore_selected_viewer`
so the `[MPR-PRESERVE]`/`[MPR-TEARDOWN]` viewport-scoped safety applies. → ***Never*** call
`cleanup_all_viewers()` or wipe the grid (Dental Curve MPR must stop doing this).

**L5 — Lifecycle.** `cleanup()` (stop timers + per-pane `Finalize()`) **before** `deleteLater()` in
every close path; keep heavy timers off by default (auto-rotation pattern) or parented + stopped.

**Top layer — per module.** Only the module-specific tools live above the foundation:
- Dental Curve MPR: arch curve drawing/control points, panoramic curved reconstruction, perpendicular
  cross-sections, dental-specific UI (trough width, slice interval, canal overlay).
- Curve MPR: vessel/airway centerline + straightened view.
- Orthogonal MPR: the 3-pane synchronized layout tools.
- VRT/3D: presets, clipping, segmentation.

---

## 4. Migration approach (reuse, don't rewrite)

The standard viewer already embodies the foundation as a `QWidget` + `_Mpr*` mixins. The cleanest path
to "unify" without a rewrite:

1. **Factor a reusable foundation** out of `StandardMPRViewer` — either (a) a shared base/mixin set
   (`MprFoundationMixin`: volume prep + geometry contract + pane construction + viewport/lifecycle) that
   `StandardMPRViewer`, a new `DentalCurveMprViewer`, the Curve MPR, and Orthogonal all compose; or
   (b) a small service (`mpr_foundation.py`) exposing `prepare_volume(series) -> (vtkImageData, geometry)`,
   `build_2d_pane(...)`, `build_3d_pane(...)`, and the open/close/teardown helpers. Prefer the mixin/base
   route since the standard viewer is already mixin-structured.
2. **Re-home Dental Curve MPR onto it:** the generator keeps producing the curved/panoramic reslice,
   but the *display* becomes foundation panes, the *volume/geometry* comes from L1/L2, and *activation*
   becomes an in-place cell swap (mirror `toggle_zeta_mpr`). Retire `CurvedMPRPanoramicView`'s
   `vtkImageViewer2`/`ImageViewerWrapper` shim and the `cleanup_all_viewers()` call.
3. **Converge Orthogonal MPR** onto L1 (drop the SimpleITK builder for the shared volume) and L4 (open
   in-cell instead of a separate dialog), or formally mark it legacy if Standard MPR's subset/projection
   layout already covers its use.
4. **Curve MPR** mostly conforms — finish L2/L4 alignment.
5. **Retire dead duplicates** (`standard_mpr_viewer_original.py`, `toolbar_integration.py` secondary
   path, legacy `toggle_curved_mpr`) once the base is factored.

Each step is **flag-gated default-off until source-build-validated**, legacy path preserved as kill
switch, with a guard test — same convention as the rest of the repo.

---

## 5. Sequencing

1. **Define the foundation surface** (the mixin/base API) by extracting it from `StandardMPRViewer`
   *without behavior change* (pure refactor; Standard MPR output byte-identical). Guard test + source-build.
2. **Dental Curve MPR onto the foundation** (this is the active request): geometry contract (A0) →
   in-place viewport (B3) → foundation render panes (revised B1). Then layer the dental tools (slider,
   measurements, params, canal overlay) on top.
3. **Orthogonal MPR + Curve MPR convergence.**
4. **Remove dead duplicates.**

The first step is the keystone: a clean, behavior-preserving extraction of the standard-MPR foundation
is what makes "unified" real and low-risk for everything after it.

---

## 6. Invariants (must hold for every MPR/3D module)

- **One volume** (`PyDicomLazyVolume.vtk_image_data`); no second builder.
- **One geometry source** (`DirectionMatrix`/`ZetaAnatA` contract); never reslice from raw
  spacing/origin alone; transform picked points into the contract frame.
- **One VTK rendering style** (reslice/VRT mappers + standard interactor styles); no parallel raster or
  `vtkImageViewer2` shim.
- **Viewport-scoped, non-destructive** open/close (in-place cell swap; never `cleanup_all_viewers()`;
  never dispose other MPR instances).
- **`cleanup()`/`Finalize()` before `deleteLater()`**.
- **Clinical isolation preserved:** modules still operate on the active viewport's volume only; nothing
  here touches study resolution or the cross-patient/multi-study guards.
- **Standard MPR stays byte-identical** through the refactor (it is the working reference; prove it with
  the geometry provenance log + guard tests).

---

## 7. Open question for the user

The directive ended "…and the ability" (the message appears truncated). I've interpreted it as **"the
ability to add each module's own tools on top of the shared foundation"** (the per-module tool layer in
§1/§3). If you meant a *specific* additional ability (e.g., the ability to switch a viewport between
MPR modes in place, to run multiple MPR types side-by-side, or to save/restore MPR layouts), tell me and
I'll fold it into the foundation surface (§4.1) before any extraction begins.
