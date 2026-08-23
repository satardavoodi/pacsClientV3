# Zeta MPR — Geometry & Orientation Pipeline (As‑Built)

**Status:** authoritative as‑built record. Last updated **2026‑06‑03**.
**Scope:** the DICOM‑geometry → MPR reconstruction → on‑screen orientation path for the
**Zeta MPR** viewer (`modules/mpr/zeta_mpr/`), which is what the toolbar **"MPR"** button
opens. Read this before touching any MPR geometry, the canonicalization pre‑filter, the
camera/view‑up logic, or the orientation markers.

> ### ⚠️ Which sections describe the SHIPPED design — read this first
>
> This document grew by accretion and **not all of it is current**. Reading a
> superseded section as if it were live nearly caused an MPR geometry regression
> on 2026-08-23. The map, as of that date:
>
> | sections | status |
> |---|---|
> | **§0, §10, §10b–§10h** | **CURRENT — this is the shipped design.** |
> | §1–§2 | current (data provenance, contract boundaries) |
> | §3–§6 | **HISTORICAL.** The fixed world‑axis camera table in §5 and the `Roll`/`Azimuth` correction scheme in §6 were **retired** by §10b. `_needs_radiological_correction()` returns `False` on the anatomical path, disabling them at all six sites. §3.3's transpose caveat still applies to the code it describes. |
> | §7–§9 | historical/background |
>
> Two more traps worth knowing before you start:
> * **The canonicalization flag is default ON** (`_BUILD_DEFAULT_CANONICALIZE = True`,
>   since 2026‑06‑11), so §10b–§10f is what runs. Several older lines in this doc
>   said "default OFF"; see §10.6.
> * **In oblique mode the camera does NOT select the plane** — an explicit
>   `vtkPlane` on the mapper does (v1.09.Fix‑E). See §10.9. This is the specific
>   thing that was nearly "fixed" into a regression.
>
> Companion: `docs/plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`
> — the full constraints inventory, the guard‑test regression surface, and the
> fixed‑character‑window landmines in the MPR test suite.

This document supersedes the resample‑based approach described in the earlier investigation
notes. Historical/background docs (still useful for *how we got here*): repo‑root
`docs/reports/ZETA_MPR_ORIENTATION_INVESTIGATION_2026-06-02.md`, `docs/reports/ZETA_MPR_GEOMETRY_MATH_INVESTIGATION_2026-06-02.md`,
`docs/reports/ZETA_MPR_FOURCASE_REVIEW_2026-06-02.md`, `ZETA_MPR_GEOMETRY_RAW_2026-06-02.json`, and the module
journal `modules/mpr/zeta_mpr/ZETA_MPR_ENGINEERING_JOURNAL.md`.

---

## 0. TL;DR — the one rule that matters

We do **not** resample — the native acquired plane is always shown faithfully. Canonicalization
attaches one matrix, **`ZetaAnatA`** = world→patient

```
A = [ −IOP_row , −IOP_col , slice_axis_lps ]      (columns; patient LPS)
slice_axis_lps = normal × sign( (IPP_last − IPP_first) · normal )   # = volume +Z, in patient LPS
```

and **everything orientation flows from `A`**, with no `Roll/Azimuth` and no per‑case ifs:

1. **Cameras** (`_anatomical_camera`) are built from the volume's **own world grid axes**, taking
   only the **sign** of each axis from `A` → clean upright rectangles (no oblique tilt), canonical
   orientation (axial up≈A/right≈L; sagittal up≈S/right≈P; coronal up≈S/right≈L).
2. **Plane-aware routing (§10c):** each pane looks down the volume axis whose patient direction
   best matches that pane's plane‑normal — `look_k = argmax_k |A[:,k]·plane_normal|` — so the
   **native acquisition plane lands in its matching pane** (sagittal acq → Sagittal pane, axial →
   Axial, coronal → Coronal). Axial‑acquired volumes reduce to the old look=Z/X/Y (no regression).
3. **Markers** (`_anatomical_labels`) are computed from those same camera vectors, so the letters
   always match the rendered image.

Flag‑gated (`AIPACS_ZETA_MPR_CANONICALIZE`, default OFF; unknown IPP → legacy path).
**Live‑validated 2026‑06‑03 (44608):** native sagittal → Sagittal pane (S‑top, face viewer‑LEFT),
native axial → Axial pane (no regression), reconstructions canonical. Full design: §10b + §10c.

---

## 1. Where the data comes from

### 1.1 On disk + database
- DICOM files: `user_data/patients/dicom/<study_uid>/<series_number>/`
  (`data_paths.DICOM_IMAGES_DIR`). A series' folder is also stored as `series.series_path`.
- Database `user_data/database/dicom.db` (`data_paths.DATABASE_FILE`). The **`instances`**
  table stores per‑slice geometry directly:
  `image_orientation_patient` (IOP, 6 floats), `image_position_patient` (IPP, 3 floats),
  `direction`, `pixel_spacing`, `slice_thickness`, `spacing_between_slices`, `instance_number`.
  The **`series`** table has `series_number`, `modality`, `series_description`, `series_path`,
  `orientation`.

### 1.2 FAST mode data source (this is what feeds MPR)
`modules/viewer/fast/pydicom_lazy_volume.py` — `PyDicomLazyVolume` (backed by
`PyDicom2DBackend`) builds a single **NumPy‑backed `vtkImageData`** with on‑demand per‑slice
decode. It attaches geometry as **field‑data arrays** on the `vtkImageData`:
- `"DirectionMatrix"` (16 floats, 4×4) — built by `_to_iop_matrix()` (see §3).
- `"Spacing"`, `"Dimensions"`.

This `vtkImageData` is the object stored in the home/viewer thumbnail data as
`series_data['vtk_image_data']`, and it is exactly what gets handed to the MPR viewer. The
FAST path is pydicom + NumPy + VTK; **SimpleITK is used elsewhere in FAST (e.g.
`lightweight_2d_pipeline.py`, `qt_slice_viewer.py`) but is not on the Zeta MPR build path.**

### 1.3 Advanced mode data source
`modules/viewer/advanced/` (`viewer_2d.py`, `series_geometry_index.py`) is the heavier
VTK + SimpleITK 3D path used by the *advanced* viewer. It has its own geometry contract
(`docs/architecture/ADVANCED_VTK_GEOMETRY_CONTRACT.md`). **It is a separate viewer and is not
the Zeta MPR data source** — do not conflate the two. The advanced path was not modified by
this MPR geometry work.

### 1.4 The two MPR implementations (don't confuse them)
- **Zeta MPR** — `modules/mpr/zeta_mpr/`, `StandardMPRViewer` (in `mpr_viewer/widget.py`).
  Pure **VTK**. Opened by the toolbar **"MPR"** button. **This is the viewer this document
  and all the recent fixes are about.**
- **Orthogonal MPR** — `modules/mpr/orthogonal/` (`OrthogonalMPRWidget`,
  `core/resampler.py`, `core/volume_loader.py`, `utils/sitk_helpers.py`). **SimpleITK**‑based,
  a separate/alternative implementation (referenced from `toolbar_manager.py` ~L1126). Not
  modified by this work; documented here only so future devs don't edit the wrong module.

---

## 2. Slice reading & slice ordering

- Slices are read per‑instance (pydicom) and **ordered by `InstanceNumber`** when geometry is
  evaluated. The canonicalizer's `_read_dicom_slice_axis_sign(dicom_directory, normal)` reads
  each file's `ImagePositionPatient`, sorts by `InstanceNumber`, and returns
  `normal × sign((IPP_last − IPP_first) · normal)`.
- **Why ordering matters:** the volume's k‑axis (world +Z) follows the instance order. Two
  series can share the same IOP/normal yet stack in opposite directions (ascending vs.
  descending IPP). That sign is the difference between "superior is up" and "upside down" in
  the reconstructed planes — see §6.

---

## 3. Orientation matrices (how image direction is determined)

### 3.1 Construction — `pydicom_lazy_volume.py::_to_iop_matrix(iop)`
```python
row    = iop[0:3] (normalized)          # Image X (row) direction, patient LPS
col    = iop[3:6] (normalized)          # Image Y (col) direction, patient LPS
normal = row × col                      # slice/through-plane direction, patient LPS
M = I(4)
M[:,0] = row ; M[:,1] = col ; M[:,2] = normal     # COLUMNS = (row, col, normal)
M[1, :] = -M[1, :]                       # negate ROW 1 (Y-flip) — "match legacy convert_itk2vtk()"
```
So the field‑data `DirectionMatrix` has **columns = (row, col, normal)** with **row 1 negated**
(an ITK→VTK Y‑flip convention). This is attached to the `vtkImageData` as `"DirectionMatrix"`.

### 3.2 Consumption — `mpr_viewer/widget.py::__init__`
1. **X‑flip the pixel data**: `vtkImageFlip` on axis 0 (radiological left↔right). The field
   data (incl. `DirectionMatrix`) is copied onto the flipped image.
2. Read `"DirectionMatrix"` into `self.direction_matrix` (4×4), then **negate column 0** to
   compensate for the X‑flip:
   ```python
   for i in range(3): self.direction_matrix.SetElement(i, 0, -self.direction_matrix.GetElement(i, 0))
   ```
3. The widget then reads the matrix **by rows** as
   `row_dir = M[0,:]`, `col_dir = M[1,:]`, `slice_dir = M[2,:]`.

> **Verified worked example (shoulder 44082 S4).** DICOM IOP
> `row=[0.966,−0.104,0.235]`, `col=[−0.017,0.886,0.463]` ⇒ `normal=[−0.256,−0.451,0.855]`.
> After `_to_iop_matrix` (cols row/col/normal, row‑1 negated) and the widget's column‑0
> negation, `self.direction_matrix` rows are
> `row_dir=[−0.966,−0.017,−0.256]`, `col_dir=[−0.104,−0.886,0.451]`,
> `slice_dir=[−0.235,0.463,0.855]` — matches the live log (`ZETA_NPR_SOURCE_CLASSIFICATION`,
> `dominant_value=0.855`) to 6 decimals. Use this as the regression oracle if you refactor
> the matrix handling.

### 3.3 Important caveat (known, do not "fix" blindly)
`_get_camera_vectors_for_view` reads the matrix **by rows** while `_to_iop_matrix` wrote the
IOP vectors as **columns** — i.e. the matrix is effectively consumed transposed. For diagonal
(axis‑aligned) matrices this is a no‑op; for oblique inputs it differs. The current pipeline
does **not** rely on the camera reorienting by this matrix (cameras use fixed world‑axis
vectors, §5); it relies on the §6 correction rule. Do not "correct the transpose" in isolation
— that would change behavior the §6 rule was calibrated against. See
`docs/reports/ZETA_MPR_GEOMETRY_MATH_INVESTIGATION_2026-06-02.md`.

---

## 4. Canonicalization logic — `modules/mpr/zeta_mpr/_mpr_canonicalize.py`

### 4.1 What it is now (ORIENTATION‑ONLY — never resamples)
`canonicalize_volume(vtk_image_data, dicom_directory)`:
1. Reads the `"DirectionMatrix"` field data → decodes `row, col, normal`; classifies the
   acquisition plane by the dominant `|normal|` axis (Z→axial, X→sagittal, Y→coronal).
2. Computes `slice_axis_lps = _read_dicom_slice_axis_sign(dicom_directory, normal)` = the
   volume's +Z axis expressed in patient LPS (§2).
3. **Decision (the §0 rule):**
   - `slice_axis_lps[2] < 0` (or unknown) → **+Z points Inferior** → attach the
     `"ZetaCanonical"` field‑data marker to a *shallow copy* and return it (native pixels
     untouched). The marker tells the viewer to apply the radiological correction.
   - `slice_axis_lps[2] ≥ 0` → **+Z points Superior** → return the input **unmarked** (no
     correction; the reconstructions are already upright).
4. **Fail‑safe:** any error returns the original object unchanged.

It **never resamples** (the resample block is retained but unreachable for easy revert).
Resampling was tried and rejected — it re‑cut oblique acquisitions into a true‑axial grid and
**distorted the native input plane** (the input plane must stay visually faithful).

### 4.2 Feature flag (default OFF; reversible)
Enabled via env `AIPACS_ZETA_MPR_CANONICALIZE` ∈ {1,true,yes,on}, **or**
`<USER_DATA_ROOT>/config/zeta_mpr.json` `{"canonicalize": true}`. Env wins over config. Read
**fresh on every MPR open** (no restart needed once the new code is loaded). When disabled,
`canonicalize_volume` is a no‑op and `_needs_radiological_correction()` reduces to the legacy
`modality=="CT"` test — i.e. **flag OFF ⇒ byte‑identical to the original viewer.**

### 4.3 Where it's called (the LIVE path)
`PacsClient/.../patient_toolbar/toolbar_manager.py::toggle_zeta_mpr` (~L4346). It resolves
`vtk_image_data` + `dicom_directory` from `series_data`, calls `canonicalize_volume(...)`
behind the flag, then constructs `StandardMPRViewer(...)` (orthogonal MPR ~L4655; curved
MPR ~L4859). **`modules/mpr/zeta_mpr/toolbar_integration.py` (`toggle_new_mpr_zeta` /
`replace_selected_viewport_with_new_mpr_zeta`) is DEAD/legacy — the button is not wired to it.
Editing it has no runtime effect.** (This cost a full debugging loop; see the journal.)

---

## 5. MPR reconstruction & VTK usage

`StandardMPRViewer` builds three 2D views + one 3D view (no SimpleITK):
- **2D views** (`_mpr_views.py::_create_axial/sagittal/coronal_view`): a `vtkImageResliceMapper`
  with `SliceFacesCameraOn()` + `SliceAtFocalPointOn()` + a `vtkImageSlice`. The slice plane is
  perpendicular to the camera direction, so **the camera vectors choose the plane**.
- **3D view** (`_create_3d_view`): `vtkGPUVolumeRayCastMapper` VRT. (FAST viewer mode must
  never instantiate VTK render windows — that constraint is about the FAST 2D viewer, not this
  MPR viewer, which is a deliberate VTK viewer opened on demand.)
- Camera vectors come from `_mpr_orientation.py::_get_camera_vectors_for_view` and are **fixed
  world‑axis vectors** (they do not reorient by the direction matrix):
  | View | camera position | view‑up | looks along |
  |---|---|---|---|
  | axial | center − Z | `[0,1,0]` (+Y) | +Z |
  | sagittal | center + X | `[0,0,1]` (+Z) | −X |
  | coronal | center + Y | `[0,0,1]` (+Z) | −Y |
- **Radiological correction** (applied only when `_needs_radiological_correction()` — §6):
  sagittal `camera.Roll(180)`; coronal `camera.Azimuth(180)+Roll(180)`; 3D `Roll(180)`.
  Re‑applied identically in `_mpr_rendering.py::_reset_rendering`, `_mpr_series.py::_reload_with_series`,
  and `_mpr_oblique.py` — **all four sites must stay in sync.**

---

## 6. How the correction decision is made (the general rule)

`_mpr_orientation.py::_needs_radiological_correction()`:
```python
return (self.detected_modality == "CT") or bool(self._mpr_canonicalized)
```
- `self._mpr_canonicalized` is set in `widget.py` from the `"ZetaCanonical"` marker, which the
  canonicalizer attaches **iff the volume +Z points Inferior** (§4.1).
- `detected_modality == "CT"` stays as an independent trigger so CT keeps working even when the
  flag is OFF (CT data is +Z‑Inferior anyway, so the two agree).

### 6.1 Why this is correct (the geometry)
The reconstructed sag/cor use `view_up = +Z` (world). World +Z = the volume's k‑axis = the
slice‑stacking direction = `slice_axis_lps` in patient LPS. So:
- `slice_axis_lps[2] > 0` (+Z → **Superior**): uncorrected screen‑up = Superior ⇒ **already
  upright** ⇒ applying `Roll(180)` would invert it.
- `slice_axis_lps[2] < 0` (+Z → **Inferior**): uncorrected screen‑up = Inferior ⇒ **upside
  down** ⇒ `Roll(180)` flips it upright.

| Case | normal·Ẑ | IPP advance vs normal | volume +Z → patient | marked? | result |
|---|---|---|---|---|---|
| Brain MRI 44608 (axial `t2_tse_tra`) | +0.9998 | **+** (head‑ward) | **Superior** | **no** | upright (no flip) |
| Shoulder MRI 44082 (oblique axial) | +0.855 | − | Inferior | yes | corrected |
| Wrist MRI (axial) | ~+1 | − | Inferior | yes | corrected |
| Axial CT (`Bone`) | +1.0 | − | Inferior | yes | corrected |

This is why brain regressed when the correction was (briefly) applied unconditionally to all
marked MR: the brain didn't need it. The rule restores the brain while preserving the others.

### 6.2 How R/L, A/P, S/I are interpreted
- Patient frame is **LPS**: +X = **L**eft, +Y = **P**osterior, +Z = **S**uperior. DICOM IOP/IPP
  are already in LPS.
- The input **X‑flip** (§3.2) intentionally maps patient **Right→viewer‑left, Left→viewer‑right**
  in the axial view (radiological convention). Calibrated against the axial view, which renders
  correctly as **A‑top / P‑bottom / R‑left / L‑right**.
- Screen mapping for any 2D view (parallel projection): **screen‑up = `view_up`**,
  **screen‑right = `camera_direction × view_up`**, each mapped to a patient direction via the
  (flipped) direction matrix. (Verified against the known‑correct axial.)

---

## 7. Native input plane vs. reconstructed planes

- **Native input plane (axial viewport):** shown **as acquired** — no resample, only the
  radiological X‑flip. For an oblique acquisition (e.g. shoulder ~31°) the axial viewport shows
  the native oblique slices faithfully (e.g. 44082 = **10/21 native slices**). This is the
  required behavior; do not resample it to "true axial".
- **Reconstructed planes (sagittal/coronal viewports):** the volume's other two orthogonal
  planes, reconstructed by the reslice mapper. They are made canonical (upright) **via the
  camera correction** (§5/§6), not by altering the data.
- **Updated (§10b/§10c — the shipped anatomical path):** the per‑plane wording above (native →
  *axial* viewport; correction via `Roll/Azimuth` §5/§6) is the **legacy** description. On the
  anatomical/canonical path the cameras are **grid‑aligned with sign from `A`** (no Roll/Azimuth),
  and **plane‑aware routing** sends the native plane to its **matching** pane (sagittal acq →
  Sagittal viewport, coronal → Coronal, axial → Axial) — not always Axial. Reconstructions are the
  remaining two planes, also canonical. Axial‑acquired volumes are unchanged (no regression).

---

## 8. Orientation markers (RESOLVED 2026-06-03 — now camera-derived; see §10b)

> **Resolved.** On the anatomical path `_get_orientation_labels()` delegates to
> `_anatomical_labels()`, which computes the letters from the **actual camera vectors**
> (`screen‑up = A·view_up`, `screen‑right = A·(dir×view_up)`), so markers always match the
> rendered image — including the sagittal A/P pair. The hardcoded table described below is now
> only the **legacy fallback** used when `ZetaAnatA` is absent (flag off / unknown IPP).

`_mpr_orientation.py::_get_orientation_labels()` returns **hardcoded** labels
(axial R/L/A/P; sagittal A/P/H/F; coronal R/L/H/F). They are **not** computed from the actual
camera, so they cannot track a flip and the **sagittal A/P pair can be mislabeled** relative to
the rendered image. The orientation of the *image* is governed by §6; the *labels* are not yet.
**Recommended fix (not yet implemented):** compute each label from the camera vectors —
`screen‑up = view_up→patient`, `screen‑right = direction×view_up→patient` — so the letters
always match the displayed anatomy. Do **not** add more hardcoded per‑plane label tables.

### 8.1 Update 2026-06-03 — sagittal A/P + corrected world→patient model
Investigation of brain MRI **44608** (sagittal A/P reversed — face on viewer‑right) and wrist
CT **44573** found two things; full report:
`docs/reports/ZETA_MPR_SAGITTAL_AP_AND_WRIST_INVESTIGATION_2026-06-03.md`.
1. **Correct volume→patient transform** (use this, not the metadata matrix, which is wrong on
   the Z axis): `A = [ −IOP_row , −IOP_col , slice_axis_lps ]` (columns, patient LPS), where
   `slice_axis_lps` is the *actual* slice‑stacking direction (§2). `A` reproduces the
   known‑correct axial and the working shoulder sagittal (S/P); the field‑data DirectionMatrix
   does not (its 3rd column is the geometric normal, not the stacking direction).
2. **Sagittal A/P root cause:** the single `Roll(180)` couples sagittal up/down **and** A/P.
   Marked (+Z‑Inferior) volumes get the flip → S/P (correct). Unmarked (+Z‑Superior: brain,
   wrist `Bone`) skip it → up/down stays correct but A/P stays reversed (screen‑right =
   Anterior). Toggling the marker can't fix it (would re‑invert up/down).
**Proposed general rule (decouples the axes, subsumes the +Z‑Inferior marker):** set each 2D
camera directly from the patient‑canonical triad via `A` (axial up=A/right=L; sagittal
up=S/right=P; coronal up=S/right=L), replacing the fixed cameras + `Roll/Azimuth`. One rule,
no per‑case/per‑modality branches; preserves shoulder/CT/oblique. Not yet implemented.

---

## 9. What was tested

- **Headless geometry** (real DICOM, via the canonicalizer's own functions): brain 44608 axial
  `slice_axis_lps=[0.019,0.004,+0.9998]` → not marked; shoulder 44082 `[0.257,0.451,−0.855]` →
  marked; axial CT `[0,0,−1]` → marked. Confirms the §6 table.
- **Unit/math tests:** `tests/code/mpr/test_mpr_canonicalize.py` (numpy‑only geometry helpers).
- **Live (human‑assisted, source build):** axial native faithful (44082 = 10/21 slices);
  sag/cor camera `view_up` flips `+Z→−Z` when marked; shoulder MRI, wrist MRI, axial CT correct.
  Brain 44608 final on‑screen confirmation after the §6 rule is the last verification step.
- **Launch note:** the source build must be launched with a full environment (the agent shell
  lacked `COMPUTERNAME` → license dialog, and `WINDIR` → qtawesome crash). See §11.

---

## 10. DO NOT break without careful review

1. **Never resample in `canonicalize_volume`.** Orientation‑only. Resampling distorts the
   native input plane (the regression that retired the approach).
2. **Keep the §0 rule.** Mark iff `slice_axis_lps[2] < 0`. Do **not** make marking
   unconditional (over‑corrects brain MRI) and do **not** make it modality‑/patient‑specific.
3. **`_needs_radiological_correction()` = `CT or marker`.** The `==CT` branch is the flag‑OFF
   safety net; keep it.
4. **The live path is `toolbar_manager.py::toggle_zeta_mpr`**, not `toolbar_integration.py`
   (dead). Grep the whole repo (incl. `PacsClient/`) when looking for the creation site.
5. **All four correction sites must agree** (`_mpr_views` ×3 create + `_mpr_rendering` reset +
   `_mpr_series` reload + `_mpr_oblique`). Changing one without the others causes
   reset/scroll/reload to diverge from initial render.
6. **Fail‑safe must hold: with the flag OFF the viewer must remain byte‑identical
   to the legacy path.** ⚠️ **The flag itself is default ON, not OFF** — this line
   said "default OFF" until 2026-08-23, which was stale by two months.
   `_mpr_canonicalize._BUILD_DEFAULT_CANONICALIZE = True`, *"flipped ON
   2026-06-11 after extended live validation"*, and it is deliberately a **code**
   default rather than a seeded config value: the frozen installer's config
   seeder only writes files that do not already exist, so an upgraded client
   would keep its old config and never receive a new flag. Resolution order is
   env `AIPACS_ZETA_MPR_CANONICALIZE` → `<USER_DATA_ROOT>/config/zeta_mpr.json`
   `{"canonicalize": bool}` → build default. Set either to `0`/`false` to pin the
   legacy geometry. **Assume the anatomical path (§10b–§10f) is what is running.**
7. **Markers are hardcoded** (§8) — fix by computing from camera vectors, not by adding tables.
8. Run `tests/code/mpr/` after any change; re‑verify the 4 reference cases (brain/shoulder/
   wrist/CT) live before trusting orientation.
9. **In OBLIQUE mode the camera does not select the plane — the mapper's explicit
   `vtkPlane` does. Do NOT "fix" the camera focal point onto the crosshair.**
   This is **v1.09.Fix-E**, and until 2026-08-23 it was recorded *only* in a source
   docstring, which is how it was nearly reverted. `_set_oblique_camera` runs
   `mapper.SliceFacesCameraOff()` + `SliceAtFocalPointOff()` and sets
   `plane.SetOrigin(self.current_position)` / `plane.SetNormal(oblique_normal)`,
   leaving the camera **untouched** — *"the camera stays in its original orthogonal
   position, so the viewport is perfectly stable"*. The earlier v1.09 behaviour
   (update all three focal-point components to the crosshair) made the image pan
   under the cursor during rotation and was **deliberately reverted**.
   Consequences to remember:
   * The displayed oblique plane passes through the crosshair **by construction**
     (`plane.origin IS current_position`) — there is nothing to correct.
   * `_update_slice_positions` moves the camera along the **look axis only**, in
     both modes, and separately re-points the plane origin.
   * `mpr_diagnostic_validator.py` (header `Version: 2026-02-17`) still measures
     the **camera's** plane, so `focal_at_crosshair` and `plane_containment` fire
     on every oblique update. Those warnings are **expected and do not indicate a
     geometry defect** — see
     `docs/plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`.
   * `check_parallel_scale` compares against a baseline captured at view creation
     and after reset only, so a user zoom is reported as a violation.
10. **Bound guard-test source windows at the next `def`, never a fixed character
    count.** Adding lines to an MPR function has produced bogus test failures at
    least four times, once reading as *"the coronal view stopped being built"*.
    The surviving fixed windows are catalogued in the constraints brief above —
    convert the relevant one **before** editing the file it slices.

---

## 10b. FINAL IMPLEMENTATION (2026-06-03) — anatomical grid-aligned cameras

The marker + `Roll/Azimuth` approach (§5/§6) and the resample (§4) are **both retired**. The
shipped design:

1. **`canonicalize_volume` attaches `ZetaAnatA`** — a 3×3 world→patient transform
   `A = [-IOP_row, -IOP_col, slice_axis_lps]` (columns; patient LPS), computed from the DICOM
   IOP + the IPP slice ordering. No resample, no marker, no Roll. Flag-gated as before
   (`AIPACS_ZETA_MPR_CANONICALIZE` / `zeta_mpr.json`); unknown IPP → not attached → legacy path.
2. **`widget.py` reads `ZetaAnatA`** → `self._anat_A`, `self._mpr_use_anatomical = True`.
3. **`_mpr_orientation._anatomical_camera`** sets each 2D camera from the volume's **own world
   grid axes** (`_ANAT_AXES`: axial look=Z/up=Y, sagittal look=X/up=Z, coronal look=Y/up=Z),
   choosing only the **sign** of each axis from `A` so the orientation is canonical (axial
   up≈Anterior/right≈Left; sagittal up≈Superior/right≈Posterior; coronal up≈Superior/right≈Left).
   Because the camera vectors are volume world axes, the image is **grid-aligned — a clean
   upright rectangle, never a tilted/oblique box** — and the axial shows the **native
   acquisition plane** (look=Z = slice axis), faithful.
   **[Superseded by §10c: the look-axis is now chosen per pane via plane-aware routing —
   `look_k = argmax_k |A[:,k]·plane_normal|` — so the native plane lands in its matching pane,
   not always Axial. For axial-acquired volumes this reduces exactly to the look=Z/X/Y here, so
   there is no regression.]**
4. **`_mpr_orientation._anatomical_labels`** computes the single marker layer from those camera
   vectors (`screen-up = A·view_up`, `screen-right = A·(dir×view_up)`), so the letters always
   match the rendered image. The legacy hardcoded `_get_orientation_labels` is the fallback.
5. **`_needs_radiological_correction()` returns False on the anatomical path**, disabling the
   legacy `Roll/Azimuth` at all six sites with one guard.
6. The **yellow** duplicate markers were the `mpr_diagnostic_validator` overlay
   (`DIAG_ENABLED = ZETA_MPR_DIAG==1`) — a debug overlay; production launches must not set
   `ZETA_MPR_DIAG`.

**Live-validated 2026-06-03:** brain MRI 44608 sagittal A/P corrected (A‑left/P‑right), wrist
CT 44573 fingers‑up, shoulder MRI 44082 oblique axial now grid‑aligned/upright (no tilt) and
correct, single marker set throughout. **Do-not-break:** keep the camera vectors on volume grid
axes (snapped) — reverting to exact patient axes reintroduces the oblique tilt; keep the
sign-selection from `A` (don't hardcode signs) — that's what keeps orientation canonical without
per-case ifs. Investigation: `docs/reports/ZETA_MPR_SAGITTAL_AP_AND_WRIST_INVESTIGATION_2026-06-03.md`.

## 10c. PLANE-AWARE VIEWPORT ROUTING (2026-06-03) — native plane → matching pane

Supersedes §10b point 3's **fixed** look=Z/X/Y assignment (`_ANAT_AXES`). The fixed map always
sent the volume's slice (k) axis to the Axial pane, so a **sagittal- or coronal-acquired** series
showed its native plane in the wrong pane (e.g. 44608 Series 7 sagittal appeared in the Axial
viewport, rotated). The router detects the true acquisition plane and places the native series in
its matching viewport.

1. **`_ANAT_PLANE_TARGETS`** (replaces `_ANAT_AXES`/`_ANAT_TARGETS`) gives each pane its patient‑LPS
   `(plane_normal, up, right)`: axial `n=S, up=A, right=L`; sagittal `n=L, up=S, right=P`;
   coronal `n=A/P, up=S, right=L`.
2. **`_anatomical_camera(view)`** picks the **look axis** as the volume world axis whose patient
   direction (`A[:,k]`) is most parallel to that pane's `plane_normal`:
   `look_k = argmax_k |A[:,k] · plane_normal|`. The up axis = the best of the remaining two for
   `up`; signs come from `A`. Cameras stay on **volume grid axes** (still upright, no tilt — §10b
   invariant preserved). It stores `self._anat_look_axis[view] = look_k`.
3. **Routing result:** axial acq → Axial pane shows native (look=Z); sagittal acq → Sagittal pane
   shows native (look=the L/R axis); coronal acq → Coronal pane shows native. The other two panes
   are canonical reconstructions. For an **axial-acquired** volume this reduces *exactly* to the
   old look=Z/X/Y, so those cases are byte-identical (no regression).
4. **`_get_slice_info_text` + `_get_scroll_direction`** (in `_mpr_crosshair_render.py` /
   `_mpr_orientation.py`) read `_anat_look_axis` so the per-pane slice count and the scroll wheel
   follow the rerouted plane. Scroll **snaps to the look axis**, preserving the legacy sign when
   the legacy vector has a component there (axial/CT unchanged), default `+` for the rerouted axes.
5. **`_anatomical_labels` is unchanged** — markers still derive from the actual camera vectors, so
   they always match the displayed plane.

**Live-validated 2026-06-03 (44608 brain MRI, flag ON):** SAGITTAL Series 7 (t1_se_sag_320, 20
slices) → **Sagittal pane** "9/20", crisp, S‑top, A/face viewer‑LEFT, P‑right; axial(/640) +
coronal(/620) canonical reconstructions. AXIAL Series 5 (t2_tse_tra, 24 slices) → **Axial pane**
"11/24", crisp, A‑top, R‑left; sagittal(/616)+coronal(/896) reconstructions — **no regression**.
All panes upright, no 90° rotation, single camera-derived marker set. **Do-not-break:** route by
`argmax|A[:,k]·plane_normal|` (don't restore the fixed `_ANAT_AXES`); keep `_anat_look_axis`
feeding the slice-count + scroll so they track the displayed plane.

## 10d. Crosshair INTERACTION for routed non-axial-native input (2026-06-03 — live-validated)

§10c routes each pane's camera to a different VOLUME axis for non-axial input, but the crosshair
interaction geometry originally hardcoded the axial-native mapping (axial→Z, sagittal→X, coronal→Y)
in four places: `_update_slice_positions`, `_calculate_crosshair_endpoints`, the drag mapping in
`_mpr_crosshair_interact.on_mouse_move`, and the oblique sample points in `_update_oblique_reslicing`.
For a **sagittal (or any non-axial) native series** that drove the WRONG axis when moving the
crosshair → the slice slid out of the volume (**black image**) and crosshairs "didn't move
correctly". Axial-native worked only because its volume world axes already equal the patient axes.

Fix: a single source of truth `_mpr_orientation._view_axes(view)` returns `(look, h, v)` volume-world
axis indices — derived from the routing when anatomical (`_anat_look_axis` = through-plane the camera
looks down; `_anat_up_axis` = screen-vertical; `h` = the third axis), else the **legacy triples**
(axial `(2,0,1)`, sagittal `(0,1,2)`, coronal `(1,0,2)`). All four sites use it: slice-follow moves
the camera along `look`; crosshair lines/drag use `h,v` (drag the H line → change the v-coord, drag V
→ change h-coord, center → both); rotation angle = `atan2(Δv, Δh)`; oblique sample points vary along
`h`(×cos) + `v`(×sin). **Axial-native == legacy triples by construction → byte-identical (no
regression)**; non-axial-native now uses its true axes. Live-validated on 44608 (sagittal Series 7:
crosshair move no longer blacks the axial pane + rotation works; axial Series 5 unchanged).
Do-not-break: route ALL crosshair geometry through `_view_axes`; keep `_anat_up_axis` populated in
`_anatomical_camera` (and its cache).

## 10e. Native plane = ORIGINAL acquired slices (not interpolated) — 2026-06-03 (live-validated)

Symptom: the axial-native axial pane scrolled the ORIGINAL acquired slices, but a sagittal-native
series' sagittal pane felt interpolated and scrolled through many intermediate slices instead of
the 20 acquired ones. Two leftover axial-native assumptions:
1. **Interpolation was hardcoded per pane name** in `_create_*_view`: axial = nearest +
   `SetResampleToScreenPixels(False)` (crisp original slices); sagittal/coronal = linear
   (interpolated reconstructions). A routed sagittal-native plane (now in the Sagittal pane) got
   linear → blended.
2. **`_get_axis_index()` + the wheel `step=2.0`** still used the axial-native axis, so the sagittal
   pane scrolled by the tiny in-plane spacing instead of the slice thickness → many sub-slice steps.

Fix (assign by ROLE, not pane name): `_mpr_views._apply_native_plane_interpolation()` (run at the
end of `_setup_ui`) sets the **native pane = the one whose look-axis is the acquired-slice axis
(world axis 2 = `A[:,2]`=`slice_axis_lps`)** to `Nearest` + `ResampleToScreenPixels(False)` (original
slices) and the other two to `Linear` + screen-resample (smooth reconstructions). `_get_axis_index`
and the wheel step now use `_view_axes(view)[0]` / `spacing[look_axis]`, so one notch = one acquired
slice on the native pane. Axial-native resolves to the same axes/interp as before → no regression.
Live-validated on 44608 (sagittal Series 7): log `sagittal pane interpolation -> native(nearest)`,
axial/coronal `reconstructed(linear)`; the sagittal pane steps consecutive integer slices (9→8→7 of
/20). Do-not-break: assign interpolation by `_view_axes` look-axis (native == 2), never pane name.

## 10f. Crosshair always-on-top (depth bias) — 2026-06-03 (live-validated)

Symptom: rotating the crosshair clipped/hid parts of the lines behind the image. Cause: the
crosshair line actors and sphere handles are added to the SAME renderer as the `vtkImageSlice` and
lie IN the slice plane → coplanar → z-fight; rotated segments fall at/behind the image and lose the
depth test (rotation is visual-only by default, so this is coplanar z-fighting, not true oblique
occlusion). Fix: `_mpr_crosshair_render._force_crosshair_on_top(mapper)` biases each crosshair/handle
mapper toward the camera in the depth buffer (`SetResolveCoincidentTopologyToPolygonOffset` +
`SetRelativeCoincidentTopology{Polygon,Line}OffsetParameters(-1,-66000)` + point offset), so its
fragments always win the depth test and draw on top. The bias shifts only the depth-test value, not
the on-screen position → the crosshair stays geometrically exact. Applied to both line mappers in
`_create_crosshairs` and the handle mapper in `_create_crosshair_handles`. Live-validated (44608
sagittal): a rotated crosshair draws a continuous X fully on top (over bone + soft tissue), all
handles visible, no clipping in any pane. Do-not-break: keep the depth-bias on every crosshair/handle
mapper; it must remain depth-test-only (don't displace the geometry to fake on-top).

## 10g. Render + interaction throttling (documented 2026-08-23)

**This had no documentation at all** — it existed only in source, which meant any
plan to "just add a camera update per crosshair move" had no budget to check
itself against. Two independent throttles:

**1. Render batching — 5 ms** (`_mpr_orientation._request_render`). Adds the view
to a `_render_pending` set and arms a **single-shot 5 ms** `QTimer`;
`_execute_pending_renders` then renders each pending window **once**. N calls
inside one 5 ms window produce **one** render per pane.
`_render_immediately` bypasses this and is docstring'd *"use sparingly"*.

**2. Compute coalescing — 16 ms frame budget**
(`_request_interaction_update` / `_apply_interaction_update`). VTK's
`MouseMoveEvent` fires far faster than the panes can reslice and render; running
the full update on every event saturates the main thread. So: run immediately if
`AIPACS_ZETA_MPR_INTERACT_MS` (**default 16**) has elapsed, else remember the
latest request and arm one trailing timer so the final position always lands.
`=0` restores legacy immediate-every-event.

Interaction kinds coalesce by superset rank **`move ⊃ scroll ⊃ rotate`**, and the
per-kind call sets are pinned by `tests/code/system/test_mpr_interaction_perf.py`
as **exact lists** — adding a step to any of them fails those tests by design:

| kind | calls |
|---|---|
| `move` | `crosshairs`, `slice_positions`, `oblique`, `text` |
| `scroll` | `crosshairs`, `oblique`, `text` — **no `slice_positions`** |
| `rotate` | `crosshairs`, `oblique` |

Note the consequence: **`rotate` deliberately skips `_update_slice_positions`**,
so on a rotate-only frame the camera focal point's look-axis component can be one
frame stale. That is harmless for the displayed image (§10.9) but it is what
makes the stale validator's `plane_containment` check fire — see §10h.

`_mpr_perf_note` logs `[ZETA_MPR_PERF] op=… ms=…` when one interaction step takes
**≥ 12 ms** (`AIPACS_ZETA_MPR_PERF_MS`), gated by `AIPACS_ZETA_MPR_PERF` (off by
default). That threshold is the closest thing to a documented frame budget.

**Do-not-break:** route renders through `_request_render`, never
`_render_immediately`, on any interaction path. An extra camera *write* per
update is cheap; an extra *render* per mouse-move is the regression. Cost scales
hard with slice count — the same VTK steps measured 101 ms on a small MR and
**1 176 ms** on a 512×512×272 CT.

## 10h. The MPR diagnostic validator — and why it currently cries wolf

`mpr_diagnostic_validator.py` runs on **every** oblique update
(`validate_after_oblique`) and after every reset (`validate_after_reset`). It is
constructed unconditionally (`_mpr_views.py:375`); only its *visual overlays* are
gated by `ZETA_MPR_DIAG`.

**Logging asymmetry to know before reading any log:** violations log at
**WARNING always**; passes log **only** under `ZETA_MPR_DIAG=1`. So a clean run
is silent, and "zero `[MPR_DIAG]` lines" means either *clean* or *never
exercised* — it cannot distinguish them. That ambiguity produced a false
regression finding on 2026-08-23: 3.5.9 showed zero failures because it had
almost no oblique activity (7 log lines vs 1 152 on 3.6.2), not because it was
healthy.

The nine checks run on the target view, plus mutual orthogonality across views:

| # | check | measures | threshold |
|---|---|---|---|
| 1 | `handedness` | `sign(right · (up × dir))` vs baseline | sign flip |
| 2 | `normal_hemisphere` | `dot(dir, baseline_dir) > 0` | 0 |
| 3 | `viewup_ortho` | `|dot(view_up, dir)|` | 0.05 (~3°) |
| 4 | `viewup_stability` | angle(view_up, baseline) | 90° |
| 5 | `focal_at_crosshair` | `|camera.focal − crosshair|` | 2.0 mm |
| 6 | `distance_stable` | camera→focal distance drift | 5 % |
| 7 | `right_vector` | angle(right, baseline right) | 120° |
| 8 | `parallel_scale` | zoom drift vs baseline | 1 % |
| 9 | `plane_containment` | `dot(crosshair − camera.focal, camera.dir)` | 0.5 mm |

⚠️ **Checks 5, 8 and 9 are STALE and produce false alarms.** The module header
reads `Version: 2026-02-17` — it encodes the **pre-Fix-E** design, in which the
oblique path repositioned the camera. Since Fix-E (§10.9) the camera no longer
defines the displayed plane, so:

* **5 `focal_at_crosshair`** measures an in-plane offset that Fix-E *deliberately
  preserves*. Firing is the feature working.
* **9 `plane_containment`** measures containment in the **camera's** plane, not
  the mapper's. The meaningful expression is
  `dot(crosshair − plane.origin, plane.normal)` where
  `plane = mapper.GetSlicePlane()` — which is **identically zero**, because
  `plane.origin IS current_position`. It fires only on rotate-only frames where
  the camera focal is one frame stale (§10g).
* **8 `parallel_scale`** compares against a baseline captured at view creation
  and after `_reset_all_to_orthogonal` **only** — never re-captured after a user
  zoom or a pane enlarge, so it reports the user's own zoom as a violation.

**If you fix these, make them mode-aware** rather than deleting them: ask
`mapper.GetSliceFacesCamera()` / `GetSliceAtFocalPoint()`, and validate against
`mapper.GetSlicePlane()` when the pane is in explicit-plane mode. Checks 1–4, 6
and 7 remain valid in both modes.

## 11. Related records
- Live MPR path & dead `toolbar_integration`: memory `zeta-mpr-live-path-toggle-zeta-mpr`.
- Orientation root cause + canonicalize design history: memory `zeta-mpr-orientation-canonicalize`;
  repo‑root `ZETA_MPR_*_2026-06-02.md`; module `ZETA_MPR_ENGINEERING_JOURNAL.md`.
- Launch/license/env (COMPUTERNAME, WINDIR): memory `aipacs-license-computername-env`,
  `aipacs-dual-app-and-license`, `aipacs-launch-control-sop`.
- Advanced (separate) viewer geometry: `docs/architecture/ADVANCED_VTK_GEOMETRY_CONTRACT.md`.
- Pixel spacing (separate clinical fix): memory `radiography-pixel-spacing-fix`.
