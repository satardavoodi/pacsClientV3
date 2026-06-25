# Dental Curve MPR vs Standard MPR — Alignment Verification

**Date:** 2026-06-22
**Question:** Is the proposed Dental Curve MPR improvement path aligned with the existing,
working standard (Zeta) MPR pipeline (geometry, orientation, VTK rendering, volume construction,
coordinate handling, viewport behavior, interaction)?
**Method:** Read-only comparison of both pipelines in the live source (entry points, volume source,
geometry contract, lifecycle, layout). Reads with `docs/pipelines/mpr-geometry-pipeline.md` (the
authoritative standard-MPR geometry as-built) and `docs/reports/DENTAL_CURVE_MPR_CODE_REVIEW_2026-06-22.md`.

---

## VERDICT — CONDITIONAL PASS (revise the plan before proceeding)

The two pipelines **already share the same source volume** (good), but the Dental Curve MPR
**diverges from standard MPR on the three things the acceptance rule cares about most: patient
geometry/coordinate handling, viewport/layout behavior, and the activation/lifecycle flow.**

Therefore the improvement plan **must be revised before any code is written**:

1. **DROP the QPainter/FAST-display idea (old plan item B1).** Standard MPR is **fully VTK**
   (`vtkImageResliceMapper` + `vtkImageSlice` + GPU volume). A QPainter renderer would create a
   *second, divergent* rendering path — the opposite of what is wanted. Dental Curve MPR should
   **reuse standard MPR's VTK rendering**, not replace it. (The "FAST viewer must never instantiate
   VTK render windows" rule governs the *2D stack viewer*; an explicitly-activated MPR is the
   sanctioned VTK path — standard MPR itself instantiates render windows by design.)
2. **ADD a new top-priority item: adopt standard MPR's geometry contract** (X-flip +
   `DirectionMatrix`/`ZetaAnatA` LPS triad + IPP slice-sign + radiological correction). The dental
   engine currently ignores all of it → it can mismatch L/R and mis-orient oblique/non-axial volumes.
3. **PROMOTE the "non-destructive layout" item** (old B3) and re-rate it **lower risk**, because
   there is a proven pattern to copy: standard MPR's in-place single-cell swap with
   `_mpr_grid_position` save/restore and `_zeta_mpr_widget`/`_original_widget` cross-link.

Items A1 (no-HU labeling), A5 (exception guard), C1 (async generation), D1 (slider), D2
(measurements), D3 (param UI), D4 (canal overlay) remain compatible and additive.

The remaining sections give the evidence.

---

## Part 1 — Standard MPR: entry point & main classes

- **Entry:** `toolbar_manager.py::toggle_zeta_mpr` (~`:4581`). Toggles MPR on/off for the **selected
  viewport**. On open it: `check_and_deactivate_tools()` → resolve series → **`_resolve_mpr_volume_for_route(...)`**
  (`:5250`, FAST→full-VTK bridge) → read W/L → optional `canonicalize_volume()` → instantiate the
  viewer at the **same grid cell** → cross-link `_zeta_mpr_widget`/`_original_widget` → set
  `tool_selected = MPR`.
- **Main class:** `StandardMPRViewer` — `modules/mpr/zeta_mpr/mpr_viewer/widget.py:69`, a `QWidget`
  composed of 11 `_Mpr*` mixins (layout, rendering, oblique, series, crosshair state/interact/render,
  views, orientation, segmentation, VRT). `standard_mpr_viewer_original.py` (225 KB) is **dead/un-imported**
  legacy; `toolbar_integration.py::toggle_new_mpr_zeta` is a **legacy secondary** activation of the
  same class. Live class is unambiguously `mpr_viewer/widget.py::StandardMPRViewer`.
- **Geometry authority:** `_mpr_canonicalize.py` (+ `_mpr_orientation.py`), with the contract documented
  in `docs/pipelines/mpr-geometry-pipeline.md`. Guard test
  `tests/code/architecture/test_backend_geometry_boundary_guards.py`; provenance log
  `[MPR_GEOMETRY_PROVENANCE]`.

## Part 2 — Dental Curve MPR: entry point & main classes

- **Entry:** `toolbar_manager.py::_show_curved_mpr_panel` (`:836`) — a **standalone floating QDialog**
  path-builder; point picking via a **monkeypatched** `_add_curved_mpr_point` on the active
  `ImageViewer2D`. **Does not** go through the MPR tool-state machine (`toggle_zeta_mpr` /
  `check_and_deactivate_tools`). Generate → `_generate_curved_mpr_from_points` (`:1183`) →
  `_show_curved_mpr_result` (`:1239`).
- **Generation:** `modules/mpr/zeta_mpr/curved_mpr.py::CurvedMPRGenerator` — receives a `vtkImageData`,
  reslices along parallel-transport frames.
- **Display:** `modules/mpr/curved_mpr/curved_mpr_panoramic_view.py::CurvedMPRPanoramicView` /
  `CurvedMPRViewport` — a dual-panel `vtkImageViewer2` display of the **pre-computed** curved/panoramic
  output.

## Part 3 — Shared VTK components (and where they diverge)

| | Standard MPR | Dental Curve MPR |
|---|---|---|
| Source volume object | **`PyDicomLazyVolume.vtk_image_data`** (shared) | **same object** (`image_viewer.vtk_image_data`) ✅ |
| 2D render tech | `vtkImageResliceMapper` + `vtkImageSlice`, `SliceFacesCameraOn`, live reslice off the volume | `vtkImageViewer2` showing a pre-computed 2D image ❌ |
| 3D | `vtkGPUVolumeRayCastMapper` + `vtkVolume` | none |
| Render windows | 4 (or 1–3 subset) `QVTKRenderWindowInteractor` + `vtkRenderer` | 2 `QVTKRenderWindowInteractor` (dual panel) |
| Interactor styles | crosshair style ↔ `MPRToolbarInteractorStyle`; `VRTInteractorStyle` (3D) | bespoke `CurvedMPRInteractorStyle` + `ImageViewerWrapper` shim |

**Both are VTK** (so "use VTK" is satisfied), **but they do not share the rendering infrastructure** —
standard MPR reslices a live volume per-camera; curved MPR renders a precomputed image with a
different mapper/viewer and a duck-typed `ImageViewerWrapper` to fake the `ImageViewer2D` API for the
toolbar. This is duplicated rendering plumbing, not reuse.

## Part 4 — Differences in volume construction

- **Construction is SHARED.** One canonical builder — `PyDicomLazyVolume.__init__`
  (`modules/viewer/fast/pydicom_lazy_volume.py`) — stacks slices into a numpy-backed `vtkImageData`,
  sets **spacing** from `PixelSpacing`/`SpacingBetweenSlices`/`SliceThickness`, **origin** from slice-0
  `ImagePositionPatient`, and attaches IOP as a **`"DirectionMatrix"` field-data array** (not
  `SetDirectionMatrix`). The 2D viewer, standard MPR, and Dental Curve MPR all consume that one object.
- **Preparation DIVERGES.** Standard MPR, in `StandardMPRViewer.__init__`, additionally applies a
  **`vtkImageFlip` on X** (radiological L↔R), reads `"DirectionMatrix"` into a `vtkMatrix4x4`, **negates
  column 0** to compensate the flip, and derives the `ZetaAnatA` triad. **Dental Curve MPR does none of
  this** — `CurvedMPRGenerator`/`ResliceEngine` read only `GetSpacing/GetOrigin/GetDimensions/GetBounds`.
- **Resolution safety DIVERGES.** Standard MPR routes through `_resolve_mpr_volume_for_route` +
  `_load_full_vtk_for_mpr`, which **loads the full decoded scalar volume** when the active viewer is a
  FAST stub and **blocks with a message** if it can't — never building VTK on an empty volume. Dental
  Curve MPR grabs `image_viewer.vtk_image_data` directly (works only because point-picking is gated to
  the non-FAST `ImageViewer2D`, which holds the real volume), bypassing that safety.

## Part 5 — Differences in geometry/orientation handling ⟵ the crux

| Geometry concern | Standard MPR | Dental Curve MPR |
|---|---|---|
| Patient coordinate system | **LPS**, via `DirectionMatrix`/`ZetaAnatA` | **none** — raw VTK index/world space |
| Image Orientation (IOP) cosines | parsed → cameras + reslice axes | **ignored** |
| Slice-direction sign | from first/last `ImagePositionPatient` (`slice_axis_lps`) | **ignored** (uses geometric order) |
| Radiological L↔R | `vtkImageFlip` X + column-0 negation + `Roll/Azimuth` correction | **none** |
| Oblique / non-axial input | plane-aware anatomical cameras (`canonicalize_volume`, default-ON) | **assumes arch in axial XY** (`PlaneGenerator._initial_normal` bias) |
| Spacing / origin | read from shared volume (consistent) | read from shared volume (consistent) ✅ |

**Consequence:** because the Dental Curve engine ignores the `DirectionMatrix`/`ZetaAnatA`/X-flip/LPS
handling, its output can be **left-right mirrored and mis-oriented relative to standard MPR**, and it is
fragile on oblique/non-axial acquisitions — exactly the "geometric mismatch vs standard MPR" the
acceptance rule forbids. There is also a **coordinate-frame hazard**: the curve control points are picked
on the `ImageViewer2D`'s rendered image (which carries the viewer's orientation/flip), but the engine
reslices the **unflipped raw volume** — points and reslice frame may not be in the same space.
⚠ This specific point-frame consistency needs a live check.

Note: a curved reformat is *inherently* a different reslice than orthogonal MPR (it follows a drawn
curve), so it cannot use identical reslice axes — but it **must start from the same canonicalized,
oriented, LPS volume space** so the result is in the same patient frame as standard MPR.

## Part 6 — Differences in viewport state management

| | Standard MPR | Dental Curve MPR |
|---|---|---|
| Open | replaces **one** grid cell in place; other viewports untouched | **`cleanup_all_viewers()` + `lst_nodes_viewer.clear()`** → wipes grid to 1×1 ❌ |
| Layout restore | per-cell via saved `_mpr_grid_position` in `_restore_selected_viewer` | none (grid was wiped) |
| Tool state | routes through `check_and_deactivate_tools` MPR branch; `[MPR-PRESERVE]`/`[MPR-TEARDOWN]` gates protect other viewports | standalone QDialog + monkeypatch; bypasses tool-state machine |
| Other MPR instances | preserved unless the selection IS that MPR host | n/a (everything wiped) |
| Teardown | `cleanup()` (stop auto-rotate timer + per-pane `Finalize()`) **before** `deleteLater()`, via the restore path; auto-rotation OFF by default | flag-gated `closeEvent` → `_teardown_curved_mpr_vtk()` (parents+stops 100 ms timer, `Finalize()`s) — added 2026-06-22 |

Standard MPR is **viewport-scoped and non-destructive**; Dental Curve MPR is **globally destructive**.
The teardown *mechanisms* differ (standard relies on the restore path calling `cleanup()`; dental uses a
`closeEvent`) but both now `Finalize()` — same spirit, different hook.

## Part 7 — Do the planned improvements follow the same safe route? (the 10 checks)

| # | Check | Today | After the (revised) plan |
|---|---|---|---|
| 1 | Same VTK rendering infrastructure | ❌ different mappers/viewers | ✅ if it reuses standard MPR's VTK render path (revised) |
| 2 | Builds/receives volume the same safe way | ⚠ same object, bypasses route-safety + flip/direction prep | ✅ if routed through `_resolve_mpr_volume_for_route` + same prep |
| 3 | Spacing/orientation/origin/slice-order/patient-coords consistent | ❌ ignores DirectionMatrix/ZetaAnatA/X-flip/LPS | ✅ only after adopting the geometry contract (new top item) |
| 4 | Reuses proven MPR pipeline vs duplicating fragile geometry | ❌ own parallel-transport geometry, separate | ◑ partial — curve geometry is intrinsically separate, but seed it from the contract |
| 5 | Improvement path compatible with MPR architecture | ⚠ not as originally written (QPainter diverged) | ✅ after revision |
| 6 | Similar viewport/MPR activation flow | ❌ standalone QDialog + global wipe | ✅ if it adopts the in-place cell swap + cross-link |
| 7 | Preserves same viewer-state safety rules | ❌ wipes grid, bypasses MPR gates | ✅ after viewport-scoping |
| 8 | Avoids unnecessary global layout refresh | ❌ calls `cleanup_all_viewers()` | ✅ after the non-destructive layout change |
| 9 | VTK init/dispose same safe pattern | ◑ has `Finalize()` teardown (different hook) | ✅ if aligned to `cleanup()`-before-`deleteLater()` |
| 10 | Caching/decoding/volume prep same logic | ◑ shares the decode/volume; skips MPR-side flip/direction prep | ✅ after #2/#3 |

✅ aligned · ◑ partial · ⚠ caution · ❌ not aligned

## Part 8 — Parts of Dental Curve MPR to refactor to reuse standard MPR

In priority order (each flag-gated, each needs source-build validation):

1. **Geometry: consume the same prepared volume + contract.** Have the dental path obtain its volume
   the way standard MPR does — through `_resolve_mpr_volume_for_route` and the same `vtkImageFlip` +
   `DirectionMatrix`/`ZetaAnatA` handling (or by sharing a small helper extracted from
   `StandardMPRViewer.__init__`) — and transform the picked curve points into that same frame. This is
   the alignment-critical fix; without it the rest is cosmetic.
2. **Viewport flow: mirror `toggle_zeta_mpr`.** Replace the `cleanup_all_viewers()` 1×1 wipe with an
   in-place single-cell swap, save/restore `_mpr_grid_position`, cross-link `_curved_mpr_widget`/
   `_original_widget`, and route open/close through `check_and_deactivate_tools` + `_restore_selected_viewer`
   so the `[MPR-PRESERVE]`/`[MPR-TEARDOWN]` safety applies.
3. **Rendering: reuse standard MPR's VTK pane construction** (the `vtkImageResliceMapper`/`vtkImageSlice`
   + `QVTKRenderWindowInteractor` + `vtkRenderer` pattern and the `cleanup()`/`Finalize()` lifecycle)
   instead of the `vtkImageViewer2` + `ImageViewerWrapper` shim. The curved/cross-section panels become
   panes built the same way, just fed the curved reslice output.
4. **Lifecycle: align teardown** to `cleanup()`-before-`deleteLater()` (keep the `closeEvent` as a
   belt-and-suspenders; keep `AIPACS_CURVED_MPR_TEARDOWN`).
5. **Geometry-contract compliance:** the dental engine is a VTK geometry path — either bind it to the
   geometry contract or carry the `[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH]` guard tag so
   `tests/code/architecture/test_backend_geometry_boundary_guards.py` covers it.

The **dental-specific layer stays on top and unchanged in spirit**: curve drawing / control points,
panoramic curved reconstruction, perpendicular cross-sections, and dental UI controls. Only the
*foundation* (volume prep, geometry/orientation, VTK pane construction, viewport/lifecycle) is realigned
to standard MPR.

## "Risks to avoid" — current status vs the acceptance rule

| Risk to avoid (user's list) | Dental Curve MPR today | Must become |
|---|---|---|
| Builds volume differently | No (shares the volume) ✅ — but skips the flip/direction prep ⚠ | Use the same prep |
| Ignores DICOM orientation/spacing/origin | **Ignores orientation** (uses spacing/origin) ❌ | Honor `DirectionMatrix`/`ZetaAnatA` |
| Uses a different coordinate system | **Yes — raw VTK, not LPS** ❌ | LPS via the contract |
| Resets the full layout | **Yes — `cleanup_all_viewers()`** ❌ | In-place cell swap |
| Disposes other MPR instances | **Yes — wipes grid** ❌ | Preserve other viewports |
| Breaks existing viewport state | **Yes** ❌ | Viewport-scoped |
| Geometric mismatch vs standard MPR | **Possible (L/R + oblique)** ❌ | Match standard MPR frame |

## Bottom line

The current Dental Curve MPR is **not yet aligned** with standard MPR on geometry/coordinate handling,
viewport behavior, and activation/lifecycle — and the original improvement plan's QPainter display would
have widened the gap. Per the acceptance rule, **do not proceed with the plan as written.** Proceed only
with the **revised** direction: keep the standard-MPR VTK foundation (shared volume + geometry contract +
VTK reslice rendering + viewport-scoped lifecycle) and add the dental-specific curve/panoramic/cross-section
layer on top. The shared volume builder and the existing geometry contract make this realistic — it is a
**reuse-and-realign** effort, not a rewrite. I will update
`docs/plans/DENTAL_CURVE_MPR_IMPROVEMENT_PLAN_2026-06-22.md` to reflect this before any code is written.
