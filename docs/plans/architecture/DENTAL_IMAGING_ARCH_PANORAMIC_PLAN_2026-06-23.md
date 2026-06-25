# Dental Imaging — Arch-Curve → Panoramic / Cross-Section Reconstruction Plan (2026-06-23)

**Module:** `modules/dental_imaging/` (the professional Advanced-Analysis pop-up).
**Goal:** the user defines a dental arch on the Axial view; the module reconstructs a
**panoramic** and a scrollable **cross-section** strip from the bound CBCT volume.
**Method:** REUSE the existing curved-MPR engine + the shared volume + standard-MPR
geometry. **No new geometry pipeline.** Static `QImage` rendering (no VTK render
windows in the module). Flag-gated, default-off until live-validated.

> This is a PLAN. Implementation lands in small, flag-gated, guard-tested steps,
> each verified on the Windows source build before the next.

---

## 1. What already exists (reuse, don't rebuild)

| Asset | Where | Role in this feature |
|---|---|---|
| **Bound shared volume** `DentalVolume` | `modules/dental_imaging/core/` | Single source of truth: `image_data` (vtk_image_data) + `dimensions`/`spacing`/`origin`/`direction_matrix`. Input to everything below. |
| **Curved-MPR engine** `CurvedMPRGenerator` | `modules/mpr/zeta_mpr/curved_mpr.py` | `set_centerline(points)` → `generate_panoramic_view(...)` (panoramic) + `generate_curved_mpr(...)` (perpendicular cross-section stack). Already cubic reslice + robust-WL + unsharp + thin-slab projection work landed. |
| **Static ortho previews** | `modules/dental_imaging/workspace.py::_render_ortho_previews` | The pattern for turning a `vtkImageData`/numpy slice into a windowed `QImage` cell — reuse for panoramic/cross-section output. |
| **Geometry contract** (IOP/IPP → `DirectionMatrix`) | `pydicom_lazy_volume.py`, `docs/pipelines/mpr-geometry-pipeline.md` | Index↔world mapping + L/R orientation. NEVER recomputed here. |
| **Arch-point picker** `DentalCurvePicker` | `modules/mpr/curved_mpr/dental_curve_vtk_host.py` | Reference for point collection + live spline (the simple Dental Curve MPR uses it on a VTK host). |
| **Panoramic quality review** | `docs/plans/architecture/PANORAMIC_RECONSTRUCTION_QUALITY_REVIEW_2026-06-23.md` | Projection/thickness/sharpening decisions already made. |

**Net-new code is small:** an arch-picking interaction on the Axial cell + glue that
feeds picked world points to `CurvedMPRGenerator` and renders its output into the
Panoramic / Cross-section cells. The reconstruction math is unchanged.

## 2. Reconstruction data flow

```
DentalVolume.image_data (shared vtk_image_data)
      │
Axial cell  ──user clicks arch points──►  display px → axial (col,row) → volume index
      │                                     → WORLD coords via origin+index·spacing·DirectionMatrix
      ▼
arch points (world)  ──►  CurvedMPRGenerator(image_data).set_centerline(points)
      │
      ├─► generate_panoramic_view(thickness, height, projection)  ──► panoramic vtkImageData ─► QImage ─► Panoramic cell
      └─► generate_curved_mpr(slice_size, num_slices)            ──► cross-section stack    ─► QImage ─► Cross-section cell (+ slider)
```

Everything is the SAME engine the simple Dental Curve MPR uses; the module just hosts
the picking + display.

## 3. Arch-curve picking on the Axial cell (the one new interaction)

Two options; **recommend Option A** (fits the module's static, VTK-render-window-free
design):

- **Option A — Qt picking on the static axial `QImage` (recommended).** The Axial cell
  is a `QLabel` showing a windowed mid-axial slice. Add a thin click-capture overlay:
  map click (display px) → slice pixel `(col,row)` (account for `KeepAspectRatio`
  letterboxing) → volume index `(i,j,k_mid)` → **world** via the volume's
  `origin + index·spacing` rotated by `DirectionMatrix` (the contract — reused, not
  recomputed). Draw the points + a polyline spline as a Qt overlay. Pros: no VTK render
  window (FAST-rule clean), self-contained, fast. Cons: 2-D picking only (the arch Z is
  the axial slice's Z — fine for a flat arch; tilt handled later per the panoramic review §9).
- **Option B — embed a `StandardMPRViewer` + `DentalCurvePicker`** in the Axial cell
  (as the simple Dental Curve MPR does on FAST). Pros: reuses the proven 3-D picker +
  live VTK spline. Cons: a VTK render window inside the module (heavier; must follow the
  sanctioned-explicit-MPR exception), more lifecycle to manage.

Either way the **output is a list of world-space arch points**, which is the engine's
input — so the choice is isolated and swappable.

## 4. Phased milestones (each flag-gated, default-off, guard-tested)

| Step | Deliverable | Reuse | Flag |
|---|---|---|---|
| **M2a** | Click arch points on the Axial cell; show numbered markers + spline overlay; "Generate"/"Clear"/"Undo" | Option A picking + the volume geometry contract | `AIPACS_DENTAL_ARCH_PICK` |
| **M2b** | Panoramic reconstruction from the arch → Panoramic cell (static QImage) | `CurvedMPRGenerator.generate_panoramic_view` (incl. robust-WL + unsharp already landed) | `AIPACS_DENTAL_PANORAMIC` |
| **M2c** | Perpendicular cross-section strip + slice slider + index/position readout → Cross-section cell | `CurvedMPRGenerator.generate_curved_mpr` | `AIPACS_DENTAL_XSECTION` |
| **M2d** | mm scale rulers + R/L markers on all cells (from `DirectionMatrix`) | panoramic review §8 L/R method | `AIPACS_DENTAL_ORIENT_MARKERS` |
| **M3 (later)** | ruler measurement, nerve tracing, 3D VRT | future; reuse measurement primitives + sanctioned VTK | — |

Ship M2a→M2c first (that is "reconstruct each window" for panoramic + cross-section).
M2d (orientation) and M3 follow.

## 5. Coordinate / geometry correctness (non-negotiable)

- Arch points are mapped to **world coordinates using the volume's own
  `origin`/`spacing`/`DirectionMatrix`** (IOP/IPP-derived). The engine then fits its
  Catmull-Rom centerline in that world frame. We do **not** invent a coordinate system.
- The engine's reconstruction (reslice, projection, spacing) is **unchanged** — the
  feature only supplies points and displays output.
- **L/R** is derived (not assumed) by projecting the arch-traversal vector onto the
  patient L→R axis of the `DirectionMatrix` (panoramic review §8). Guard test pins the
  sign so a mirrored arch can't flip R/L.
- Off-thread heavy compute: `generate_panoramic_view` over hundreds of positions runs in
  a `QThread` worker with a "Reconstructing…" status, so the pop-up never blocks
  (consistent with the from_series concern already flagged).

## 6. Architecture alignment (the §5 safety contract)

- **One engine, one geometry.** Reuses `CurvedMPRGenerator` + the shared volume + the
  standard-MPR `DirectionMatrix`. No parallel reconstruction or geometry system (per
  `UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md`).
- **No VTK render window in the module** (Option A) → the FAST rule and the
  "skeleton/core VTK-free" guard hold; output is static `QImage`s.
- **Isolated + additive:** all behind new default-off flags; the simple Patient-Tab
  Dental Curve MPR, standard MPR, and the existing Patient Viewer are untouched.
- **Single source of truth for** volume / arch points / panoramic plane / cross-section
  planes / measurement world coords — owned by `DentalVolume` + the engine, exactly as
  the original Dental Imaging spec required.

## 7. Risks & validation

| Risk | Mitigation |
|---|---|
| Wrong index→world mapping → distorted/mirrored panoramic | Unit-test the mapping against the `DirectionMatrix` with a synthetic volume; L/R sign guard test |
| Slow panoramic on the GUI thread | QThread worker + status; the engine is already optimized (cubic + thin-slab) |
| Aspect/letterbox math on the axial `QLabel` | Pure helper `display_px → slice_index` unit-tested (no Qt) |
| Picking only flat arches (tilt) | Documented; panoramic review §9 curve Z/tilt is a later, separate step |
| Regression to the simple Dental Curve MPR / standard MPR | This module never imports/edits them; engine is read-only reuse; guard tests enforce |

**Tests (offscreen, no VTK/Qt):** pure `display↔slice↔world` mapping; arch→centerline
ordering; L/R sign from `DirectionMatrix`; flags default-off; engine-call wiring
(source-pin). Live (Windows): pick → Generate → panoramic + cross-section render; scroll
slices; R/L correct on a known-orientation CBCT.

## 8. Estimated effort

| Step | Effort | Risk |
|---|---|---|
| M2a arch picking (Option A) | M | Med (coord mapping) |
| M2b panoramic render | S–M | Low (engine reuse) |
| M2c cross-section + slider | S–M | Low |
| M2d orientation markers | S | Low |
| (M3 ruler/nerve/3D) | L | later |

**Recommended first implementation step:** **M2a** — arch picking on the Axial cell with
the pure, unit-tested `display→world` mapping (no engine yet), flag-gated. It's the only
genuinely new interaction; once arch points are reliable, M2b/M2c are mostly engine
wiring + the static-QImage rendering already in `workspace.py`.

---

## Sources / references
- `docs/plans/architecture/PANORAMIC_RECONSTRUCTION_QUALITY_REVIEW_2026-06-23.md`
- `docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md`
- `docs/pipelines/dental-curve-mpr.md`, `docs/pipelines/mpr-geometry-pipeline.md`
- `modules/dental_imaging/README.md`
