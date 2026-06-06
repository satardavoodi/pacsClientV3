# Zeta MPR — Four-Case Comparative Review (44082 / 44614 / 44608 / 44313)

> **✅ CLOSED (2026-06-03).** The issues catalogued here (oblique sag/cor flips, sagittal A/P
> reversal, input-always-axial) are **fixed and live-validated**. Shipped fix = anatomical
> grid-aligned cameras + plane-aware viewport routing (native plane → matching pane). Kept for
> case history. Authoritative as-built: `docs/pipelines/mpr-geometry-pipeline.md` §10b/§10c.

**Date:** 2026-06-02
**Companion to:** `ZETA_MPR_ORIENTATION_INVESTIGATION_2026-06-02.md` (root-cause +
Phase 1 implementation). This document compares the four live cases side by side
and answers the specific questions raised during the review.
**Status:** Investigation/analysis only. **No code changed in this pass.**

> **Evidence note.** Screen-capture access to Monitor A was requested twice and the
> approval dialog timed out (not approved), so the four images here are **not** my
> own screenshots — the visual symptoms are taken from the operator's direct
> description and cross-checked against (a) the **measured on-disk DICOM geometry**
> for each patient and (b) the MPR source code. The geometry + code fully explain
> the reported symptoms. I can capture the screenshots myself if the access dialog
> is approved.

---

## 1. The four cases at a glance

| Patient | Acquisition (measured) | Orthogonal? | Reported MPR behavior | Verdict |
|---|---|---|---|---|
| **44614** | CT, primary axial (ser 201/202), IOP **[1,0,0,0,1,0]**, normal **+Z (1.000)** | **Yes, exact** | Axial / sagittal A-P / coronal all correct | **Correct (calibrated path)** |
| **44608** | Brain MRI, axial T2/FLAIR + sag T1; tilt **~1°** (orthogonal) | Yes (~1°) | Mostly correct, **not** upside down; **sagittal A/P direction wrong** | Near-correct; sagittal in-plane handedness off |
| **44082** | LEFT joint (shoulder-type) MRI, **every series oblique 31–51°** | **No (heavily oblique)** | **Sagittal & coronal reconstructions upside-down** | Uncalibrated oblique MR |
| **44313** | Brain MRI; operator opened the **sagittal T1** (ser 7, sagittal, ~6°) | Sagittal acquisition | **Sagittal input shown in the Axial box; recon rotated/disorganized; VRT/3D wrong** | Wrong viewport + legacy geometry |

Measured slice-order (projection on slice-normal vs InstanceNumber): 44614 primary
axial **decreases** (scanned head→foot in array order); 44608/44313 axials
**increase**; 44082 all **decrease**. This inconsistency matters (see §3, Q-slice).

---

## 2. Why CT (44614) is the only correct case

44614's diagnostic series (201 Bone / 202 Tissue) are **textbook true-axial CT**:
`ImageOrientationPatient = [1,0,0, 0,1,0]`, slice normal exactly **+Z**, zero tilt.

This is the **single orientation the legacy Zeta MPR was hand-tuned for**. The MPR
pipeline applies, in fixed combination:
1. an **unconditional X-flip** of the input volume (`widget.py::__init__`, `vtkImageFlip`
   axis 0) calibrated for radiological left-right, and
2. **CT-only** camera corrections — `Roll(180)` on sagittal and
   `Azimuth(180)+Roll(180)` on coronal (and `Elevation/Roll` on 3D) — gated by
   `if self.detected_modality == "CT"` in `_mpr_views.py::_create_sagittal_view` /
   `_create_coronal_view` / `_create_3d_view` (mirrored in `_mpr_rendering._reset_rendering`,
   `_mpr_oblique._reset_all_to_orthogonal`, `_mpr_series._reload_with_series`).

For a true-axial CT, X-flip + those exact rolls = radiologically canonical. Because
the acquisition is already axis-aligned, "cut the volume along world axes" (what the
`vtkImageResliceMapper` + world-axis cameras do) coincides with true axial / sagittal
/ coronal. Everything lines up — but **only for this case**.

---

## 3. Per-case root cause

### 44082 — oblique shoulder MRI: sagittal & coronal **upside-down**
- **Geometry:** every series is oblique by **31–51°** (e.g. axial-intent `t2_tse_fs_tra`
  tilt 31°). No axis is axis-aligned.
- **Cause A (dominant — the upside-down):** the corrective **`Roll(180)`** (sagittal)
  and **`Azimuth(180)+Roll(180)`** (coronal) are applied **only when modality == "CT".**
  This is MR, so **none** are applied. `Roll(180)` is exactly the vertical (top↔bottom)
  flip; its absence on a non-CT series is what makes the sagittal/coronal reconstructions
  appear **upside-down**. (The engineering journal §6-Q1 explicitly says these were found
  empirically for CT and "moving to non-CT (MR) requires understanding whether `Roll(180)`
  is needed there too" — it is, and it isn't being applied.)
- **Cause B (compounding):** the volume is cut along **world** axes, but the acquisition
  is tilted 31–51°, so the "sagittal"/"coronal" boxes are not true anatomical planes;
  the residual tilt rides on top of the flip error.

### 44614 — CT pelvis: **correct** (see §2). Preserve this behavior exactly.

### 44608 — brain MRI: mostly correct, **sagittal A/P wrong**
- **Geometry:** orthogonal (~1° tilt). Axial T2/FLAIR are clean; sag T1 (ser 7) is a
  clean orthogonal sagittal.
- **Why axial/most views look fine:** an **axial** view needs **no** CT roll (axial gets
  none even for CT), so an orthogonal axial renders the same for CT and MR → correct.
- **Why sagittal A/P (the in-plane horizontal = anterior↔posterior) is mirrored:** the
  sagittal viewport's horizontal axis is set by the camera **side/azimuth** and the
  **unconditional X-flip**. For CT the sagittal camera is corrected (`Roll(180)`); for
  MR it is not, and the X-flip (applied to *all* inputs) is only compensated correctly in
  combination with the CT correction. The net effect on an orthogonal MR sagittal is a
  **left-right (A/P) mirror** — the image isn't upside-down (vertical S/I is fine because
  the acquisition is orthogonal), but anterior and posterior are swapped. This is the
  same root family as 44082, just milder because the acquisition is orthogonal.

### 44313 — sagittal T1 input: **wrong viewport + rotated recon + wrong VRT**
- **Geometry:** the opened series is the **sagittal** T1 (ser 7): slice normal dominant
  **X** (left-right), so the volume's stacking (k) axis ≈ patient L–R, and the in-plane
  axes are A–P (rows) and S–I (cols).
- **Why the sagittal input appears in the Axial box:** `_setup_ui` **hardcodes**
  `_create_axial_view(...,0,0)` and binds the input volume there; the axial camera looks
  along world −Z and the `vtkImageResliceMapper` cuts the volume's **native ij-plane** =
  the **acquired sagittal slices**. There is **no acquisition-plane classification** that
  would route a sagittal acquisition to the sagittal viewport (logged in-code as
  `used_default_axial=True, fallback_reason=...binds_input_volume_to_axial`).
- **Why the reconstructed sag/cor are rotated/disorganized:** the rest of the pipeline
  assumes the k-axis is superior-inferior. Here k ≈ L–R, so the world-Y/world-X reslices
  for the "sagittal"/"coronal" boxes sample the volume across planes that don't match
  their labels, and the camera **view-up** vectors (tuned for axial-stacked volumes)
  produce rotated output.
- **Why VRT/3D orientation is wrong:** `_create_3d_view` sets `camera.SetViewUp(0,0,1)`
  (assumes +Z = superior) and positions the camera assuming axial stacking. With grid-Z =
  L–R, "up" points sideways → the volume renders rotated ~90°.

---

## 4. Direct answers to the key questions

- **Why does CT pelvis work while MRI fails?** CT 44614 is the only **true-axial,
  axis-aligned** input, which is the single geometry the legacy MPR was calibrated for
  (X-flip + CT-gated `Roll/Azimuth`). MR inputs (a) skip the `Roll/Azimuth` (gated to
  `modality=="CT"`) and (b) are often oblique or non-axial, which the world-axis reslice
  path doesn't reorient. It's not "CT vs MR" intrinsically — it's "axis-aligned-with-CT-
  corrections vs everything else."
- **Why do oblique shoulder reconstructions become upside-down?** The vertical-flip
  correction `Roll(180)` (and coronal `Azimuth(180)+Roll(180)`) is never applied to MR;
  without it the sag/cor planes render vertically inverted, and the 31–51° obliquity adds
  tilt on top.
- **Why does brain MRI have sagittal A/P issues?** Orthogonal acquisition → axial fine,
  not upside-down; but the sagittal in-plane horizontal (A/P) is **mirrored** because the
  sagittal camera side isn't corrected for MR and the unconditional X-flip is only balanced
  by the (absent) CT correction.
- **Why is sagittal input placed in the axial viewport?** The layout hardcodes the input
  volume into the axial cell and cuts its native slice plane there; there is no plane
  detection driving viewport assignment.
- **Why do sagittal-input reconstructions become rotated/disorganized (incl. VRT)?** The
  whole camera/view-up/3D setup assumes the volume's k-axis is superior-inferior. A
  sagittal acquisition has k ≈ left-right, so every derived plane and the 3D `ViewUp(0,0,1)`
  come out rotated.
- **Which subsystem is the cause?** In order of impact:
  1. **MPR viewport-assignment logic** — input is unconditionally bound to Axial; **no
     acquisition-plane detection** for routing. (Hits 44313 hardest.)
  2. **Old geometry logic still inside MPR** — it never adopted the corrected viewer
     contract (`__init__` logs `continue_legacy_mpr_geometry_path`); orientation
     corrections are **modality-gated to CT**, leaving MR uncalibrated. (Hits 44082, 44608.)
  3. **DICOM direction-matrix handling** — the `DirectionMatrix` field data is built with
     **columns** = (row, col, normal) (`pydicom_lazy_volume._to_iop_matrix`, row-1 negated
     for the Y-flip) but `_get_camera_vectors_for_view` reads axes from the **rows** — i.e.
     it consumes a **transposed** matrix, and even then the oblique branch returns world-axis
     cameras rather than re-orienting by it.
  4. **Slice ordering** — the volume is ordered by **InstanceNumber**, not by `dot(IPP,
     normal)`; measured direction is inconsistent (44614/44082 decrease, 44608/44313
     increase), so through-plane/scroll direction isn't geometrically guaranteed.
  - **Not** the primary cause: there is no LPS↔RAS conversion bug (everything is LPS); VTK
    itself is fine; SimpleITK is not in this hot path. IOP/IPP are the *ground truth* the
    pipeline **fails to use** (it stores IOP in field data, reads it transposed, and ignores
    per-slice IPP for ordering/sign).

**One-sentence root cause:** Zeta MPR is a legacy, CT-only-calibrated path that (1) always
puts the input in the Axial viewport with no plane detection, (2) applies its orientation
corrections only for CT, and (3) reads the DICOM orientation transposed and never actually
reorients the volume by it — so only true-axial CT comes out canonical.

---

## 5. Safe correction strategy (conservative, reversible, CT preserved)

This refines the plan in the companion doc; the four cases map cleanly onto three
flag-gated, independently revertible phases. **44614 (CT) must remain a no-op at every
phase.**

**Phase 1 — Canonicalize oblique/non-axial input (already implemented, default OFF).**
`_mpr_canonicalize.py::canonicalize_volume` resamples to a true axis-aligned LPS volume
before the viewer is built (env `AIPACS_ZETA_MPR_CANONICALIZE`, fail-safe, no-op for
axis-aligned CT). *Fixes 44082's obliquity; helps 44608; gives 44313 a clean axial-aligned
grid.* Headless math validated 18/18.

**Phase 2 — Plane-aware viewport assignment.** Classify the acquisition plane from IOP
(helper already exists: `widget.py::_classify_plane_from_slice_dir`) and route the native
(non-interpolated) slices to the **matching** viewport (axial→Axial, sagittal→Sagittal,
coronal→Coronal), reconstructing the other two. *Fixes 44313's "sagittal input in the Axial
box" and the rotated recon/VRT.* Behind its own flag; touches only the view-binding layer.

**Phase 3 — Make the orientation corrections geometry-driven, not modality-driven.** After
canonicalization the MR volume is geometrically identical to a CT axial, so the `Roll/Azimuth`
corrections should be applied based on **"is this view's canonical plane"**, not on
`modality == "CT"`. Replace the four `if self.detected_modality == "CT"` gates with a single
shared predicate (e.g. `_apply_radiological_corrections()` that is true for canonicalized /
axis-aligned volumes). *Fixes 44082's upside-down sag/cor and 44608's sagittal A/P.* This is
the most sensitive change (it edits the camera path) → smallest possible diff, behind a flag,
**live-validated against 44614 to prove CT is unchanged**, and it must preserve reference-line
and rotation/oblique behavior (the R1.2 baseline-camera + sign-check logic stays intact;
baseline capture already runs *after* these corrections).

**Validation matrix (before enabling any phase in production):**

| Case | Expected after fix |
|---|---|
| 44614 CT | **Unchanged** (regression guard) |
| 44082 shoulder MR | axial S→I, viewer-right = patient-left; sag/cor upright (not upside-down) |
| 44608 brain MR | sagittal A and P on correct sides; axial unchanged |
| 44313 sagittal T1 | native sagittal in the **Sagittal** box; axial/coronal reconstructed; VRT upright |

Use `ZETA_MPR_DIAG=1` (corner L/R/A/P/S/I labels + the 10 invariant checks in
`mpr_diagnostic_validator.py`) and confirm `ZETA_NPR_VIEWPORT_ASSIGNMENT` /
`ZETA_NPR_RESLICE_AXES_AUDIT` logs. Keep reference-line + rotation behavior unchanged.

---

## 6. What I could not verify in this pass
- My own screenshots of Monitor A (screen-access approval timed out). The analysis relies
  on the operator's reported symptoms + measured geometry + code; visual confirmation of the
  exact flip axis per case is the remaining step and is recommended before enabling Phase 3.
- The through-plane **scroll sign** per case (needs the IPP-derived `slice_axis_lps` passed
  into canonicalization) — see companion doc §11 live-validation items.

---

## 7. Authoritative validation (primary sources) + definitive fix design

I cross-checked the diagnosis against the reference implementations the engineering
journal said to consult (VTK author David Gobbi, 3D Slicer, Cornerstone3D). They
**independently confirm the root cause and the correct fix**.

### 7.1 The reference implementations are all matrix-driven (not camera-roll-driven)
- **3D Slicer** defines each plane by a `SliceToRAS` 4×4 whose **columns are
  (screen-right, screen-up, slice-normal) in patient space**; the camera is *derived
  from the matrix every frame*, and scrolling moves along the normal column. Verified
  radiological presets (RAS): Axial right=`L(-1,0,0)`, up=`A(0,1,0)`, normal=`S(0,0,1)`;
  Sagittal right=`P(0,-1,0)`, up=`S(0,0,1)`, normal=`L(-1,0,0)`; Coronal right=`L(-1,0,0)`,
  up=`S(0,0,1)`, normal=`A(0,1,0)`. (`Libs/MRML/Core/vtkMRMLSliceNode.cxx`.)
- **Cornerstone3D** uses constant per-orientation camera vectors in **LPS**: axial
  `viewPlaneNormal (0,0,-1)`, `viewUp (0,-1,0)`; sagittal `(1,0,0)`,`(0,0,1)`; coronal
  `(0,-1,0)`,`(0,0,1)`. Their fix commit a85a867 ("coronal should not be flipped")
  changed *only* the coronal normal sign `(0,1,0)→(0,-1,0)` — i.e. **the canonical
  remedy for a flipped plane is a sign flip on the orientation vector, not a camera
  roll.** That is exactly the class of bug here.
- **vtkImageReslice** (Gobbi): `ResliceAxesDirectionCosines` columns are the **output
  axes expressed in input coordinates** — confirming the Phase 1 formula
  `reslice_axes = M_inᵀ` (more generally `M_in⁻¹·M_target`) is the correct, standard
  way to regrid an oblique/sagittal/coronal acquisition to canonical axes.

### 7.2 Why this proves the Zeta MPR approach is the problem
Zeta MPR does the opposite of all three references: it leaves the volume on world axes
(never maps voxel→patient via the IOP rotation `M_in`), assumes voxel axes ≈ patient
axes (**true only for axial CT**), and then patches orientation with **empirical camera
`Roll(180)`/`Azimuth(180)` gated to CT**. Per VTK, `Roll(180)` (spin about the view
axis) and `Azimuth(180)` (swing to the opposite side of the focal point) are *not*
equivalent, and a left-right mirror **cannot** be produced by camera motion alone — so a
camera-roll scheme can only ever be hand-tuned for one geometry. That is precisely why
**44614 (axial CT) is the only correct case** and 44082/44608/44313 fail.

Numeric illustration: for axial CT the input voxel frame already equals the patient
frame, so the one tuned `(X-flip + CT rolls)` recipe yields canonical output. For 44082's
oblique MR (`M_in` tilted 31–51°) or 44313's sagittal MR (`M_in` swaps Z↔X), the *same*
recipe places the camera on the wrong side / wrong up-vector because it ignores `M_in` —
producing the upside-down (44082), mirrored-A/P (44608), and rotated/wrong-viewport
(44313) results.

### 7.3 Definitive fix (upgrades the companion doc's Phase 3)
Replace the empirical, modality-gated camera rolls with the **matrix-driven canonical
recipe** — identical code path for CT and MR:
1. **Phase 1 (built, OFF):** canonicalize the volume to axis-aligned LPS via
   `reslice_axes = M_in⁻¹·M_target` (validated against Gobbi's `ImageSlicing.cxx`).
2. **Phase 2:** plane-aware viewport assignment from `M_in`'s dominant normal axis
   (fixes 44313's "sagittal in the Axial box" + VRT).
3. **Phase 3 (the real cure):** set each 2D view's camera from a constant per-plane
   `(right, up, normal)` triad (use Cornerstone3D's LPS set or Slicer's RAS set —
   converted, never blended), choosing the **normal sign** to put the camera on the
   viewer side; derive `view_up` from the triad each update (no read-back ⇒ no drift).
   Delete the four `if modality=="CT"` roll/azimuth gates. Calibrate one sign against
   the known-good **44614 CT** so CT stays byte-identical, then verify 44082/44608/44313.

This makes orientation **deterministic and modality-independent**, which is what Slicer
and Cornerstone do and what the journal's "SliceToRAS is the gold standard" note pointed
at. Phase 3 edits the camera path, so it stays flag-gated, minimal-diff, and
live-validated (44614 = regression anchor; reference-line + rotation/oblique behavior
preserved).

Primary sources: VTK `vtkImageReslice.h` + Gobbi `ImageSlicing.cxx`; Slicer
`vtkMRMLSliceNode.cxx`; Cornerstone3D `mprCameraValues.ts` + commit a85a867;
VTK `vtkCamera` (Roll vs Azimuth); NiBabel radiological-convention note.

---

## 8. Visual verification — COMPLETED 2026-06-02 (Monitor A, source build)

Screen access was approved; I captured all four open cases on the source build. Each
matches the analysis:

- **44313 (sagittal T1):** the viewport labelled **"Axial - Slice 9/20" displays a
  mid-sagittal head** — the native sagittal input rendered in the axial box. The
  "Sagittal"/"Coronal" boxes show rotated/mislabeled planes (huge reslice indices
  309/620, 319/640) and the 3D/VRT is rotated. **Confirms §3 (wrong viewport + rotated
  recon + wrong VRT).**
- **44082 (SHOULDER):** sidebar reads "Study 1 — SHOULDER (5 series)"; the native
  oblique-axial (`t2_tse_fs_tra_LT`) is in the Axial box; sag/cor are reconstructed; the
  3D/VRT renders as an oddly-oriented slab. **Confirms the oblique-MR case.**
- **44614 (CT pelvis):** **correct** — axial anterior-up (iliac wings/sacrum), coronal
  with symmetric acetabula head-up, sagittal sacrum plausible. **Regression anchor.**
- **44608 (brain MRI):** axial correct (frontal lobes up, symmetric ventricles); sagittal
  A/P as reported. **Confirms the orthogonal-MR case.**

**New finding — the orientation corner labels are STATIC.** `_mpr_orientation.py::
_get_orientation_labels` returns **hardcoded** letters (axial `R/L/A/P`; sagittal
`A/P/H/F`; coronal `R/L/H/F`) independent of the actual rendered orientation. So the
A/P/R/L/H/F overlays always read "correct" even when the image is flipped/upside-down —
they cannot detect or verify orientation (the operator is judging by anatomy, correctly).
The fix must also make these labels **geometry-derived** (from the canonical triad), and
note the `mpr_diagnostic_validator` corner labels inherit the same limitation.

Remaining live check: the through-plane **scroll sign** per case (a quick scroll test)
before enabling Phase 3.

*No source files were modified in this review pass.*
