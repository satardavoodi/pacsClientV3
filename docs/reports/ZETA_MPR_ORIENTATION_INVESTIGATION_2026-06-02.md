# Zeta MPR — Orientation & Viewport-Assignment Investigation

> **⚠️ SUPERSEDED (updated 2026-06-03).** Kept for root-cause history only. The shipped solution
> is **neither** the resample described here **nor** the interim `Roll/Azimuth` rule. Authoritative
> as-built: **`docs/pipelines/mpr-geometry-pipeline.md`** §10b + §10c. Final design in one line:
> canonicalization is **orientation-only (never resamples)** and attaches `ZetaAnatA`
> (world→patient `A = [-IOP_row, -IOP_col, slice_axis_lps]`); each MPR camera is built from the
> volume's grid axes with **sign from `A`** (canonical, no Roll/Azimuth), and **plane-aware
> routing** sends the native acquisition plane to its matching pane (`look_k =
> argmax_k|A[:,k]·plane_normal|`). Markers are camera-derived. **Live-validated 2026-06-03 on
> 44608** (sagittal→Sagittal pane, axial→Axial pane, no regression). Live path =
> `toolbar_manager.py::toggle_zeta_mpr` (the `toolbar_integration.py` path is dead).

**Date:** 2026-06-02
**Scope:** Read-only investigation. **No code changed.** This is a pre-edit
investigation report + reversible correction plan, as requested.
**Status:** Awaiting approval before any edit. Live visual verification (CT +
shoulder MRI) is the recommended next gate.

---

## 0. Executive summary

Two reported problems are real and have a **single shared structural root
cause**: the Zeta MPR viewer is a **legacy local geometry path** that was
hand-tuned for **true-axial CT only**, and it treats every input volume as if
its acquisition (k) axis were anatomical-axial.

1. **Reconstructed axial looks upside-down on some MRI / oblique cases.**
   The radiological-orientation corrections (`Roll(180)` / `Azimuth(180)`) are
   gated **`if self.detected_modality == "CT"`**. MR and any non-CT / oblique
   series receive **no** orientation correction, while the unconditional X-flip
   was calibrated *together with* those CT-only corrections. The DICOM direction
   matrix is read but the camera path does not actually re-orient by it (it falls
   to world-axis cameras). Net: CT true-axial is the only calibrated path;
   everything else is uncalibrated and flips depending on the case's
   `ImageOrientationPatient` signs.

2. **The input series always lands in the Axial viewport.**
   `_setup_ui()` hardcodes the input volume into the axial cell at grid (0,0) and
   cuts the volume's native ij-plane there. There is **no acquisition-plane
   classification driving viewport assignment**. A sagittal- or coronal-acquired
   series therefore shows its native slices in the box labelled "Axial".

**The module's own documentation already predicted both.** The Engineering
Journal (`modules/mpr/zeta_mpr/ZETA_MPR_ENGINEERING_JOURNAL.md`) lists these as
open, **untested** questions (§6 Q1, Q2; Bug-2 "remaining question"), and the
Pipeline Reference (`ZETA_MPR_PIPELINE_REFERENCE.md` §7.3) already prescribes the
safe fix: **pre-canonicalize the input volume before constructing the viewer**,
leaving the fragile MPR internals untouched.

**Recommended safest minimal fix:** an additive, feature-flagged
`canonicalize_volume()` pre-filter inserted in `toolbar_integration.py` *before*
`StandardMPRViewer(...)` (the journal's "Option A"). CT stays byte-identical
(near-identity transform → effectively a no-op); MR/oblique gets resampled to a
true axis-aligned LPS volume so the already-tuned CT path renders it canonically.
Fully reversible (flag off ⇒ legacy path).

---

## 1. What was reviewed (evidence base)

### Code (read in full unless noted)
- `modules/mpr/zeta_mpr/mpr_viewer/widget.py` — `StandardMPRViewer.__init__`, X-flip, direction-matrix load.
- `modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py` — `_setup_ui`, `_create_axial/sagittal/coronal/3d_view`, CT corrections.
- `modules/mpr/zeta_mpr/mpr_viewer/_mpr_orientation.py` — `_detect_series_type`, `_get_camera_vectors_for_view`, `_is_identity_direction`, `_get_scroll_direction`, `_capture_baseline_camera_state`, orientation labels.
- `modules/mpr/zeta_mpr/mpr_viewer/_mpr_series.py` — `_reload_with_series` (series-switch path; duplicates the X-flip + CT corrections).
- `modules/mpr/zeta_mpr/mpr_viewer/_mpr_oblique.py` — 9-point oblique, `_set_oblique_camera`, `_reset_all_to_orthogonal`.
- `modules/mpr/zeta_mpr/mpr_viewer/_mpr_rendering.py` — `_reset_rendering` (re-applies CT corrections).
- `modules/mpr/zeta_mpr/toolbar_integration.py` — `replace_selected_viewport_with_new_mpr_zeta` (the launch path).
- `modules/mpr/zeta_mpr/mpr_diagnostic_validator.py` — `expected_corner_labels` + 10 invariant checks (validation asset).
- Canonical geometry layer (for comparison): `modules/viewer/geometry/{source_geometry,display_geometry,geometry_api,vtk_bridge}.py`, `modules/viewer/advanced/{viewer_2d,series_geometry_index}.py`, `modules/viewer/fast/{pydicom_2d_backend,pydicom_lazy_volume,lightweight_2d_pipeline,dicom_sync_geometry}.py`.
- Reusable resampling helpers: `modules/mpr/orthogonal/core/{resampler,coordinate_systems,volume_loader}.py`, `modules/mpr/orthogonal/utils/vtk_helpers.py`.

### Docs
- `modules/mpr/zeta_mpr/ZETA_MPR_PIPELINE_REFERENCE.md`, `ZETA_MPR_ENGINEERING_JOURNAL.md`, `ZETA_MPR_ROTATION_ITK_VTK_STATUS.md`.
- `docs/archive/root-investigations/2026-05-stack-order/ZETA_NPR_PIPELINE_AUDIT.md`, `ZETA_NPR_VIEWPORT_ASSIGNMENT_TABLE.md`.
- `docs/stack-order/DICOM_TO_DISPLAY_ORDER_CHAIN.md`, `docs/pipelines/IMAGE_PIPELINE_REFERENCE.md`.

### DICOM samples inspected on disk (`user_data/patients/dicom`, read-only)
| Series | Mod | IOP (first slice) | slice-normal | Plane (dom axis) | proj·normal vs InstanceNumber |
|---|---|---|---|---|---|
| CT Tissue 576 (pid 43977) | CT | [1,0,0, 0,1,0] | [0,0,1] | Axial (Z=1.00) | decreases (S→I) |
| CT Bone 198 (pid 40965) | CT | [1,0,0, 0,1,0] | [0,0,1] | Axial (Z=1.00) | decreases (S→I) |
| **MR 44534 tra** (pd_tse_fs_tra) | MR | [0.883,−0.014,−0.469, 0,0.9995,−0.031] | [0.470,0.027,0.883] | **Axial/OBLIQUE (Z=0.883, ~28° tilt)** | decreases |
| MR 44534 cor PD | MR | [0.884,−0.092,−0.459, −0.464,−0.050,−0.884] | [0.059,0.994,−0.087] | Coronal (Y=0.994) | **increases** |
| MR 44534 cor T1 | MR | (same as cor PD) | [0.059,0.994,−0.087] | Coronal (Y=0.994) | increases |
| MR 44534 sag T2 | MR | [−0.018,0.999,−0.045, −0.461,−0.048,−0.886] | [−0.888,0.004,0.461] | Sagittal (X=0.887) | decreases |

Two facts from this table matter:
- The shoulder MR is **genuinely oblique** (no IOP is axis-aligned; tilts ~27–28°).
- The relationship between InstanceNumber order and geometric direction is **not
  consistent** (coronal increases, axial/sagittal decrease). So any path that
  assumes a fixed "stack in InstanceNumber order along +normal" will flip some
  planes relative to others. Geometry must come from IOP/IPP, not InstanceNumber.

---

## 2. How Zeta MPR actually works (as-built)

**Launch / data handoff** — `toolbar_integration.py::replace_selected_viewport_with_new_mpr_zeta` (~:254):
```python
new_mpr_zeta_widget = StandardMPRViewer(vtk_image_data=vtk_image_data, parent=parent_widget)
```
`vtk_image_data` is the **same VTK volume the FAST/2D viewer built** (taken from
`patient_widget.lst_thumbnails_data`). That volume is:
- ordered by **InstanceNumber** (FAST `_sort_slices`, *not* IPP·normal),
- already **Y-flipped** in the pixel array (`convert_itk2vtk` / FAST `arr[::-1]`),
- carries a `DirectionMatrix` (4×4) as VTK **field data** (row-1 negated for the Y-flip),
- has an **identity VTK geometry** (origin+spacing only; the DICOM direction is *not* applied to the `vtkImageData` itself — it lives only in field data).

**`StandardMPRViewer.__init__`** (`widget.py:100-197`):
1. **Unconditional X-flip:** `vtkImageFlip` on axis 0 for *every* input (`:115-121`).
   Comment: *"corrects the consistent right-to-left flip in all views."*
2. **Direction matrix:** loaded from field data, then **column 0 negated**
   (`:152-153`) "to reflect the flip". (Note: §5.3 — this negates column 0 while
   the camera code reads axes from *rows*; a latent inconsistency.)
3. Emits `ZETA_NPR_SOURCE_CLASSIFICATION ... used_default_axial=True,
   fallback_reason=standard_mpr_fixed_layout_binds_input_volume_to_axial` (`:183-197`).
4. `_detect_series_type()` sets `self.detected_modality` (`:310`).

**Modality detection is a pixel-intensity heuristic, not the DICOM tag**
(`_mpr_orientation.py:158-183`): `scalar_min < −500 and scalar_max > 1000 ⇒ "CT"`,
else `"MR"`. This is what gates every orientation correction below.

**View layout** — `_setup_ui` (`_mpr_views.py:79-82`):
```python
self._create_axial_view(views_layout, 0, 0)     # input volume, NEAREST, primary
self._create_3d_view(views_layout, 0, 1)
self._create_sagittal_view(views_layout, 1, 0)  # reconstructed, LINEAR
self._create_coronal_view(views_layout, 1, 1)   # reconstructed, LINEAR
```
Each 2D view uses `vtkImageResliceMapper` + `SliceFacesCameraOn()` +
`SliceAtFocalPointOn()`. The slice shown is **perpendicular to the camera
direction** through the focal point. Because the VTK volume geometry is identity,
the **axial camera (looking along world −Z) cuts the volume's native ij-plane** =
the original acquisition slices. That is the mechanism by which "the input always
appears in the Axial viewport".

**The CT-only corrections** (the heart of Problem 1):
- `_create_sagittal_view` (`_mpr_views.py:347-349`): `if self.detected_modality == "CT": camera.Roll(180)`
- `_create_coronal_view` (`:421-424`): `if CT: camera.Azimuth(180); camera.Roll(180)`
- `_create_3d_view` (`:508-511`): `if CT: Elevation(15); Roll(180); Zoom(1.3)`
- Duplicated in `_reset_rendering` (`_mpr_rendering.py:243-249`), `_reset_all_to_orthogonal` (`_mpr_oblique.py:386-392`), and `_reload_with_series` (`_mpr_series.py:285-291`).
  → **Any change to orientation handling must be mirrored in all four places.**

**Camera vectors** — `_get_camera_vectors_for_view` (`_mpr_orientation.py:189-240`):
- If `_is_identity_direction()` → standard world-axis camera.
- Else (oblique) → **still world-axis camera positions** (axial: center+(0,0,−1), up=(0,1,0); etc.). It reads `row_dir/col_dir/slice_dir` but **does not use them** to build the camera. So the DICOM orientation does not actually re-orient the oblique view; it only influences scroll direction and labels.

---

## 3. Root-cause analysis #1 — reconstructed axial flipped on MRI / oblique

**Why CT is correct and MR is not — three compounding causes:**

**(C1) Orientation corrections are CT-gated.** The `Roll(180)`/`Azimuth(180)`
rolls that make sagittal/coronal/3D radiologically correct run only for
`detected_modality == "CT"`. They were, per the Journal (§6 Q1), *"found
empirically — someone tried different combinations until the images looked
correct"* for CT. MR receives none. The Journal's Bug-2 remaining question states
verbatim: *"For MRI, the baseline should be the raw output of
`_get_camera_vectors_for_view`. **This path has not been tested with real oblique
MRI datasets.**"*

**(C2) The unconditional X-flip is calibrated against the CT path.** The
axis-0 flip + column-0 negation (`widget.py:115-153`) is applied to all inputs and
was tuned so that *CT + the CT rolls* come out correct. Applied to MR **without**
the rolls, the net left/right/up/down parity is no longer guaranteed.

**(C3) The DICOM direction matrix is effectively unused for orientation, and the
oblique branch is untested.** For CT the doubly-compensated matrix is
`diag(−1,−1,1)`, so `_is_identity_direction()` is **always False** even for plain
CT (Journal §6 Q2) — yet CT still works because the oblique branch *also* returns
world-axis cameras and CT's content happens to align. For genuinely oblique MR
(44534: ~28° tilt), cutting the grid along world axes does **not** correspond to
true anatomical planes, and the up/right parity depends on the specific IOP signs
— which differ per series. That is exactly why *"some reconstructed axial views
are correct and others are flipped"*: the result is uncalibrated and
case-dependent.

**Contributing factor (C4) — slice ordering.** The volume is built in
**InstanceNumber** order, but §1 shows InstanceNumber order is anti-parallel to
the slice normal for CT/axial/sag and parallel for coronal. The canonical
2D/Advanced contract sorts by `dot(IPP, normal)` ascending
(`source_geometry.py:328-338`). MPR inherits FAST's InstanceNumber order, so its
through-plane direction is not geometrically guaranteed — a second reason the
reconstructions can invert between acquisition planes.

**Conclusion (P1):** The flip is **not** a single sign bug to patch inside the
reslice/camera code. It is the consequence of an orientation pipeline that is
only calibrated for true-axial CT. The robust, low-risk correction is to make
non-axial/MR inputs *look like* the calibrated case (pre-canonicalize), rather
than to re-derive new per-modality camera rolls inside the fragile oblique path.

---

## 4. Root-cause analysis #2 — input always placed in the Axial viewport

**Direct cause:** `_setup_ui` (`_mpr_views.py:79-82`) unconditionally creates the
axial view at grid (0,0) and binds `self.image_data` to it; the axial reslice cuts
the volume's native ij-plane. No code classifies the acquisition plane to decide
which viewport should receive the native slices. The module logs this itself:
`ZETA_NPR_VIEWPORT_ASSIGNMENT ... view_name="axial" ... source_role="input_volume_primary"
... used_default_axial=True` (`_mpr_views.py:224-235`), and the archived audit
(`ZETA_NPR_VIEWPORT_ASSIGNMENT_TABLE.md`) records *"input volume bound to axial
view by design"*.

**Effect:** For a sagittal- or coronal-acquired series, the native (full-resolution,
nearest-neighbour) slices render in the box labelled **Axial**, while the
genuinely axial plane is a low-resolution reconstruction in another box — the
opposite of the clinical expectation, and especially harmful for thick-slice MR
(44534 MR through-plane = 3–4 mm).

**Conclusion (P2):** This is a fixed-layout design limitation, not a crash/bug.
Two reversible remedies exist (see §6, Phase 2).

---

## 5. Comparison with the current "corrected" 2D / Advanced geometry

| Aspect | Canonical 2D / Advanced contract | Zeta MPR (as-built) |
|---|---|---|
| Geometry authority | `modules/viewer/geometry` `SourceGeometry`/`DisplayGeometry` (declared sole authority) | **Local legacy path**; `__init__` logs `GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH ... continue_legacy_mpr_geometry_path` |
| Slice sort key | `dot(IPP, normal)` ascending | inherits FAST **InstanceNumber** order |
| Plane classification | dominant axis of normal / `display_convention` | **none for viewport routing**; only logged |
| Display flips | modeled in the affine (Y-flip always; K-flip = index renumber) | **pixel** X-flip + **pixel** Y-flip (upstream) + column-0 matrix negation; correctness depends on CT camera rolls |
| Orientation correction | derived from geometry, modality-agnostic | **hardcoded `Roll/Azimuth`, gated to CT only** |
| LPS/RAS | LPS throughout, no RAS | LPS; direction matrix in field-data only (VTK geometry identity) |

**(5.3) Latent row/column inconsistency.** `widget.py:152-153` negates **column 0**
of the direction matrix for the X-flip, but `_get_camera_vectors_for_view`,
`_get_scroll_direction`, and `_capture_baseline_camera_state` read axis vectors
from **rows** (`GetElement(0,j)/(1,j)/(2,j)`). Column-0 negation changes the
patient-X component of *all three* row-vectors, not the row-0 vector. For
axis-aligned CT these coincide enough; for oblique MR they do not. This is
consistent with the Journal's §6 Q2 doubt and is a secondary reason the oblique
path is unreliable. (Flagged for awareness; the recommended pre-filter sidesteps
it rather than rewiring it.)

**Takeaway:** MPR is on an **older, isolated geometry path** that never adopted the
corrected viewer contract. It is not safe to "just route MPR through the new
contract" (large, fragile change). It *is* safe to feed MPR a canonical volume.

---

## 6. Proposed safe correction strategy (reversible, phased)

Design principles honored: preserve all functionality (overlays, crosshairs,
reference lines, rotation/oblique, sync, measurements, VRT); keep the VTK pipeline;
no FAST-mode VTK windows touched; minimal, isolated, reversible edits; CT path
unchanged.

### Phase 1 (recommended first, fixes P1 with lowest risk) — Pre-canonicalization pre-filter
Implements the Journal/Pipeline-Reference §7.3 "Option A".

- **New helper** `canonicalize_volume(vtk_image_data) -> vtk_image_data` (new file,
  e.g. `modules/mpr/zeta_mpr/_mpr_canonicalize.py`). It:
  1. reads IOP/IPP/`DirectionMatrix` (field data) + spacing,
  2. builds the LPS→axis-aligned reslice axes,
  3. resamples via `vtkImageReslice` into a true axial-aligned LPS grid
     (reuse `modules/mpr/orthogonal` `resampler.py` / `utils/vtk_helpers.py` —
     already battle-tested, separate module),
  4. preserves origin/spacing and re-attaches an (identity) `DirectionMatrix`,
  5. returns the original object unchanged if it is already within ~1° of
     axis-aligned (so **CT is a no-op**).
- **Insertion point** `toolbar_integration.py::replace_selected_viewport_with_new_mpr_zeta`,
  immediately before `StandardMPRViewer(...)` (~:254). One guarded call.
- **Feature flag** `AIPACS_ZETA_MPR_CANONICALIZE` (env) and/or
  `config/ui_variant.json`-style toggle, **default OFF** for the first build, so
  rollout is opt-in and instantly reversible.
- **Why safe:** MPR internals untouched; the X-flip + CT rolls now act on an
  axis-aligned volume (the case they were tuned for) → MR/oblique render like CT.
  CT path unaffected (no-op transform).

### Phase 2 (optional, fixes P2 as you literally described) — Plane-aware viewport routing
Only if you want the **native** (non-interpolated) slices to appear in the box
matching the acquisition plane (axial-like→Axial, sagittal-like→Sagittal,
coronal-like→Coronal), reconstructing the other two.
- Classify acquisition plane from IOP (dominant axis of the slice normal — helper
  already exists: `widget.py::_classify_plane_from_slice_dir`).
- Route the native-resolution mapper to the matching viewport and reconstruct the
  others. This is a more invasive change at the view-binding layer and would be
  done **after** Phase 1 is validated, behind its own flag.
- Note: Phase 1 already delivers *clinically canonical* axial/sagittal/coronal for
  oblique input (all reconstructed); Phase 2 is about preserving native pixel
  fidelity in the acquisition plane. Recommend deciding after seeing Phase 1 live.

### Explicitly rejected (higher risk) approaches
- Rewriting `_get_camera_vectors_for_view` to derive per-modality rolls from the
  direction matrix (touches the fragile, admittedly-untested oblique camera path;
  high regression risk to rotation/reference-lines).
- Switching MPR onto the `modules/viewer/geometry` contract (large surface, would
  disturb the working CT path and the R1.2 oblique fixes).

---

## 7. Affected files / functions

**Phase 1 (small, additive):**
- `modules/mpr/zeta_mpr/_mpr_canonicalize.py` *(new)* — `canonicalize_volume()`.
- `modules/mpr/zeta_mpr/toolbar_integration.py::replace_selected_viewport_with_new_mpr_zeta` — one guarded call + flag read.
- (reuse, unchanged) `modules/mpr/orthogonal/core/resampler.py`, `utils/vtk_helpers.py`, `core/coordinate_systems.py`.

**Touched only if Phase 2 is approved:**
- `modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py` (`_setup_ui`, `_create_*_view`).
- `modules/mpr/zeta_mpr/mpr_viewer/_mpr_series.py` (`_reload_with_series`).

**Must remain functionally identical (regression guards):**
- `widget.py` X-flip + direction load; `_mpr_orientation.py` camera/scroll/baseline;
  `_mpr_oblique.py` 9-point oblique + sign check; CT corrections in all four sites;
  `mpr_measurement_tools.py`, `curved_mpr.py`, VRT/3D, crosshairs.

---

## 8. Test cases & before/after validation

**Note:** the headless viewer/VTK suite segfaults under offscreen Qt (see memory
`stability_validation_2026-06-01`). Therefore automated tests must be **math-only**
(no VTK window); visual checks are human-assisted.

### 8.1 New headless unit tests (proposed) — `tests/code/mpr/test_mpr_canonicalize.py`
Using the §1 measured IOP/IPP as fixtures (no GUI):
- CT axial `[1,0,0,0,1,0]` ⇒ `canonicalize_volume` returns **near-identity** (no-op path taken).
- MR tra/cor/sag (44534) ⇒ resulting reslice axes map the dominant normal to world Z (axial), and the ordered IPP projection is monotonic **superior→inferior**.
- Round-trip: a known LPS point maps to the expected ijk after canonicalization (spacing/origin preserved within tolerance).

### 8.2 Before/after live visual protocol (human-assisted; task #8)
With the **source build already running** (per CLAUDE.md bootstrap), open MPR on:
1. **CT** (e.g. pid 43977 / 40965) — expect **no visible change** (regression guard).
2. **Shoulder MR 44534** tra, cor, sag — expect after-fix:
   - Axial scrolls **superior → inferior**; viewer-right = patient-left.
   - Sagittal & coronal: head/superior at **top**, feet at bottom.
   - Coronal reads as looking at the patient **from the front**.
3. Exercise **crosshair rotation / oblique**, **reference lines**, **series switch**,
   **W/L**, **measurements**, **3D/VRT** — confirm all still work (no regression).

### 8.3 Instrumented validation (already in the codebase)
- Launch with `ZETA_MPR_DIAG=1` (+ `ZETA_MPR_DIAG_VERBOSE=1`): enables corner
  L/R/A/P/S/I labels + the **10 invariant checks** in `mpr_diagnostic_validator.py`
  (handedness, normal-hemisphere, view-up stability, focal-at-crosshair, …).
- Scan logs for `ZETA_NPR_SOURCE_CLASSIFICATION`, `ZETA_NPR_VIEWPORT_ASSIGNMENT`,
  `ZETA_NPR_RESLICE_AXES_AUDIT`, and `[MPR_DIAG] ... FAILED`.
- **Acceptance:** CT screenshots unchanged; MR screenshots match the canonical
  rules in 8.2; zero new `MPR_DIAG` failures; oblique/reference-line behavior
  unchanged.

---

## 9. Reversibility & rollback

- **Feature flag default OFF** → byte-identical legacy behavior; instant disable.
- **Backup** the touched files to `backups/zeta_mpr_orientation_2026-06-02/` before editing.
- Phase 1 is **purely additive** (a new file + one guarded call); revert = delete the call.
- No DB/schema/network/protocol changes. No FAST-mode changes. No file deletions.

---

## 10. Open items / honesty notes

- The **exact per-case pixel flip** (which MR series invert and in which axis) is
  case-dependent on IOP signs and is best **confirmed visually** (task #8) — this
  is precisely the "use computer control to inspect MPR output" step you asked for.
  The structural root cause (CT-only calibration + world-axis oblique handling) is
  established from code + the module's own journal; the visual pass confirms the
  fix end-to-end.
- The §5.3 row/column negation inconsistency is real but the pre-filter avoids
  depending on it. If we later pursue Phase 2 or a contract migration, it should be
  resolved explicitly with tests.
- Phase 1 interpolates all planes for oblique input (acceptable, canonical). If
  native-plane fidelity matters to you, Phase 2 addresses it — your call after the
  live CT/MR pass.

---

---

## 11. Implementation status — Phase 1 foundation (2026-06-02)

Phase 1 has been implemented **behind a default-OFF feature flag**, so the running
app is byte-identical until the flag is enabled. Nothing is active in production.

**Added**
- `modules/mpr/zeta_mpr/_mpr_canonicalize.py` *(new)* — pure-geometry helpers
  (`parse_iop`, `classify_acquisition_plane`, `needs_canonicalization`,
  `decode_direction_field_data`, `compute_canonical_reslice_axes`,
  `canonicalize_enabled`) + the fail-safe `canonicalize_volume()` resampler
  (VTK imported lazily; returns input unchanged on no-op/missing-data/any error).
  Recovers true LPS cosines from the upstream `DirectionMatrix` field data
  (undoing the row-1 Y-flip), Gram-Schmidt re-orthonormalizes, and builds reslice
  axes `R_src.T` so the slice normal maps to output +Z (true axial).
- `tests/code/mpr/test_mpr_canonicalize.py` *(new)* + `tests/code/mpr/__init__.py`
  — headless, numpy-only tests (no VTK/Qt), fixtures = the §1 measured IOPs.

**Wired (default OFF, fail-safe)**
- `modules/mpr/zeta_mpr/toolbar_integration.py` — one guarded call before
  `StandardMPRViewer(...)`: runs only when env `AIPACS_ZETA_MPR_CANONICALIZE` ∈
  {1,true,yes,on}; wrapped in try/except so it can never block an MPR launch.

**Backup:** `backups/zeta_mpr_orientation_2026-06-02/toolbar_integration.py.bak`.

**Validated (headless math):** 18/18 checks pass — plane classification (CT/MR
tra/cor/sag), CT no-op vs oblique-needs, `DirectionMatrix` decode round-trip,
reslice-axes orthonormality + `det=+1` + normal→+Z + row→+X + col→+Y, and the
sign-override flip. Run the committed pytest on the Windows venv
(`tests/code/mpr/`) where VTK/PySide6 are present.

**NOT yet validated — gated for the live human-assisted session (task #8):**
1. The VTK resample plumbing end-to-end (enable the flag, open a **CT** → expect
   no visible change; open **44534** tra/cor/sag → expect canonical axial/sag/cor).
2. Through-plane (k) **scroll sign**: pass an IPP-derived `slice_axis_lps` to pin
   superior→inferior (currently assumes +normal and logs a warning).
3. Whether the CT-only `Roll/Azimuth` corrections must also be extended to the
   (now axis-aligned) MR sagittal/coronal views — decide from the live result.

**Rollback:** set/leave the flag OFF (byte-identical legacy), or delete the
guarded call; the new files are otherwise inert.

---

*Investigation complete. Phase 1 foundation implemented behind a default-OFF flag
with headless tests passing. Next gate: a short human-assisted live session
(enable `AIPACS_ZETA_MPR_CANONICALIZE=1`, view one CT + the 44534 shoulder MR with
`ZETA_MPR_DIAG=1`) to validate the resample end-to-end and decide on Phase 2
(plane-aware viewport routing).*
