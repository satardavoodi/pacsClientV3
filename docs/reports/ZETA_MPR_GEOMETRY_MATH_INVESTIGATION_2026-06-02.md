# Zeta MPR — Raw DICOM Geometry & Math Investigation (4 cases)

> **Note (2026-06-03):** the raw geometry/math below remains valid and is the empirical basis of
> the shipped fix. The fix itself is **anatomical grid-aligned cameras + plane-aware viewport
> routing** (world→patient `A = [-IOP_row, -IOP_col, slice_axis_lps]`; per-pane look-axis =
> `argmax_k|A[:,k]·plane_normal|`), **live-validated 2026-06-03**. Authoritative as-built:
> `docs/pipelines/mpr-geometry-pipeline.md` §10b/§10c.

**Date:** 2026-06-02 **Status:** Investigation only — **no code changed.**
**Raw data file:** `docs/analysis/data/2026-06/ZETA_MPR_GEOMETRY_RAW_2026-06-02.json` (all tags + computed matrices).
**Series analyzed = the exact ones loaded in each open MPR** (identified by slice count
from the live review): 44614→ser 201 (82), 44608→ser 5 (24), 44082→ser 4 (21),
44313→ser 7 (20). Extraction via pydicom, read-only.

All coordinates are **LPS** (DICOM): +X = patient **L**eft, +Y = **P**osterior, +Z =
**S**uperior. Orientation matrix `R = [row_cos | col_cos | normal]` (columns), where
`normal = row_cos × col_cos`.

---

## Deliverable 1 — Raw DICOM tag extraction (MPR-input series)

| Tag | 44614 CT pelvis | 44608 brain MR | 44082 shoulder MR | 44313 sag-T1 MR |
|---|---|---|---|---|
| Series / desc | 201 `Bone` | 5 `t2_tse_tra` | 4 `t2_tse_fs_tra_LT` | 7 `t1_se_sag_320` |
| Modality | CT | MR | MR | MR |
| PatientPosition | HFS | HFS | HFS | HFS |
| Rows × Cols | 512×512 | 896×616 | 512×512 | 640×620 |
| PixelSpacing (mm) | 0.292 | 0.257 | 0.246 | 0.344 |
| SliceThickness | 2.5 | 3.0 | 3.0 | 5.0 |
| SpacingBetweenSlices | (absent) | 6.18 | 4.83 | 7.0 |
| n slices | 82 | 24 | 21 | 20 |
| **IOP** | `[1,0,0, 0,1,0]` | `[0.998,−0.061,−0.018, 0.061,0.998,−0.006]` | `[0.966,−0.104,0.235, −0.017,0.886,0.463]` | `[−0.113,0.994,0.013, 0.011,0.014,−1.0]` |
| IPP first | (−65.7,−74.6,−32.7) | (−89.0,−107.6,−86.4) | (74.4,−107.2,8.2) | (−55.1,−112.8,99.2) |
| IPP last | (−65.7,−74.6,−235.2) | (−86.3,−106.9,55.7) | (99.2,−63.5,−74.4) | (77.1,−97.9,100.9) |
| FrameOfReferenceUID | …254.86256 | …772.0.0.0 | …987.0.0.0 | …926.0.0.0 |

(Full StudyInstanceUID / SeriesInstanceUID and every series per patient are in the JSON.)

### Derived per-axis directions
| | 44614 CT | 44608 brain | 44082 shoulder | 44313 sag-T1 |
|---|---|---|---|---|
| row_cos → label | (1,0,0) **L** | (0.998,−0.061,−0.018) **L** | (0.966,−0.104,0.235) **L** | (−0.113,0.994,0.013) **P** |
| col_cos → label | (0,1,0) **P** | (0.061,0.998,−0.006) **P** | (−0.017,0.886,0.463) **P** | (0.011,0.014,−1.0) **I** |
| normal → label | (0,0,1) **S** | (0.019,0.004,1.0) **S** | (−0.256,−0.451,0.855) **S** | (−0.994,−0.112,−0.013) **R** |
| **Plane / dominance** | **Axial 1.000** | **Axial 1.000** | **Axial 0.855** | **Sagittal 0.994** |
| Oblique? (tilt) | No (0.0°) | No (1.1°) | **Yes (31.3°)** | No (6.5°) |
| slice order vs InstanceNumber | **DECREASES** (S→I) | **INCREASES** (I→S) | DECREASES | DECREASES |

**First/last slice & ordering direction:** for CT (HFS) the InstanceNumber order runs
**superior→inferior** (Z: −32.7 → −235.2); for the brain MR it runs **inferior→superior**
(IPP·normal increases). So the **stack direction relative to the slice normal is opposite
between CT and brain** — and the volume is built in InstanceNumber order (FAST), so the
grid k-axis points along **−normal for CT** but **+normal for brain**. This sign is *not*
normalized anywhere in MPR.

---

## Deliverable 2 — Geometry matrix comparison (true vs as-consumed by MPR)

For each series: the **field-data `DirectionMatrix`** is built by
`modules/viewer/fast/pydicom_lazy_volume.py::_to_iop_matrix` as **columns = (row, col,
normal)** with **row 1 negated** (upstream Y-flip). MPR then (a) negates **column 0**
(its X-flip compensation) and (b) **reads the rows** of the result as
`row_dir / col_dir / slice_dir` (`_mpr_orientation.py::_get_camera_vectors_for_view`).
Reading rows of a column-built matrix = **using its transpose.**

| Case | True row_cos (col 0) | **MPR's row_dir (row 0, post X-flip)** | transpose error |
|---|---|---|---|
| 44614 CT | (1,0,0) | (−1,0,0) | **0** (matrix diagonal → rows = cols, only the intended X sign) |
| 44608 brain | (0.998,−0.061,−0.018) | (−0.998,0.061,0.019) | **~0.06** (near-diagonal) |
| 44082 shoulder | (0.966,−0.104,0.235) | (−0.966,−0.017,−0.256) | **large** (off-diagonals 0.10–0.46) |
| 44313 sag-T1 | (−0.113,0.994,0.013) | (0.113,0.011,−0.994) | **large** (axes permuted) |

**This is the central mathematical result:** the transpose is **benign for axis-aligned
matrices** (44614 is exactly diagonal; 44608 is within ~1°) but **corrupts the basis for
oblique/non-axial acquisitions** (44082 off-diagonals up to 0.46; 44313 the row/normal are
swapped — `slice_dir` comes out ≈(0,−1,0) while the TRUE normal is ≈(−0.994,…)=patient R).
`is_identity_branch = False` for **all four** (the X-flip turns even CT into
`diag(−1,−1,1)`), so every case takes the "non-identity" code path — which then returns
**hard-coded world-axis cameras** and ignores the (transposed) matrix for camera setup
anyway.

### How VTK / SimpleITK would interpret the same data
- **SimpleITK / `vtkImageData.SetDirectionMatrix`** expect **columns** = axis direction
  cosines in LPS — i.e. exactly `R = [row|col|normal]`. Feeding the **rows** (MPR's read)
  applies the transpose `Rᵀ`, a *different rotation* unless `R` is symmetric (only true
  near the diagonal). So a correct ITK/VTK consumer would reorient the volume to patient
  axes; MPR neither applies `R` to the VTK image (it stays identity-direction) nor uses it
  for the camera (world-axis branch) — the matrix is effectively **decorative**.
- **LPS/RAS:** everything here is **LPS**; there is **no** RAS conversion in the 2D/Advanced
  or MPR paths, so RAS is **not** the bug. (3D Slicer uses RAS = `diag(−1,−1,1)·LPS`; only
  relevant if we port its preset numbers — convert, don't blend.)

---

## Deliverable 3 — Current Zeta MPR pipeline math trace

1. **Volume build (upstream, FAST):** slices ordered by **InstanceNumber** (not by
   `IPP·normal`); pixel array Y-flipped; `vtkImageData` gets **identity** VTK direction +
   a `DirectionMatrix` field array = `_to_iop_matrix(IOP)` (cols row,col,normal; row1 neg).
2. **`StandardMPRViewer.__init__`** (`widget.py`): unconditional `vtkImageFlip(axis 0)`
   on the pixels; loads the field matrix; **negates column 0** of it ("X-flip
   compensation"). Result for CT = `diag(−1,−1,1)`; for oblique = column-0-negated `_to_iop`.
3. **`_get_camera_vectors_for_view`** (`_mpr_orientation.py`): reads `row_dir/col_dir/
   slice_dir` = **rows** of that matrix (transpose), checks `_is_identity_direction`
   (always **False** post-flip) → enters the branch that returns **fixed world-axis
   cameras**: axial `pos=center+(0,0,−1), up=(0,1,0)`; sagittal `pos=center+(1,0,0),
   up=(0,0,1)`; coronal `pos=center+(0,1,0), up=(0,0,1)`. **The matrix is read but not used
   to orient the camera.**
4. **`_create_*_view`** (`_mpr_views.py`): `vtkImageResliceMapper` + `SliceFacesCameraOn`
   cuts the volume perpendicular to the camera = **world-axis planes of the raw grid**.
   Then **`if self.detected_modality == "CT"`**: sagittal `Roll(180)`, coronal
   `Azimuth(180)+Roll(180)`, 3D `Elevation/Roll`. **MR gets none.**
5. **Scroll** (`_get_scroll_direction`): `−slice_dir` (axial) etc., where `slice_dir` is the
   transposed row → wrong axis for obliques.

**Net:** the displayed "axial/sagittal/coronal" are world-axis cuts of the **acquisition
grid**, never reoriented by `R`; radiological correction exists **only for CT**; the matrix
is consumed transposed.

---

## Deliverable 4 — Difference analysis (working vs failing)

| | Raw DICOM | 2D/Advanced viewer | **Zeta MPR** | Canonical expectation |
|---|---|---|---|---|
| Slice sort | by IPP | **`dot(IPP,normal)` asc** | **InstanceNumber** | by `IPP·normal` |
| Uses `R`=[row\|col\|normal] | — | columns (correct) | **rows (transpose)** + ignored for camera | columns |
| Reorients to patient axes | — | yes (contract/affine) | **no** (world-axis cut of raw grid) | yes |
| Orientation correction | — | geometry-derived | **`Roll/Azimuth` gated to CT only** | geometry-derived, modality-independent |
| Plane→viewport | — | n/a | **always Axial (hard-coded)** | by acquisition plane |

- **44614 CT works** because `R = I`: grid axes **= patient axes**, so world-axis cuts =
  true anatomical planes; the transpose is exactly 0; `diag(−1,−1,1)`+pixel-X-flip+`up(0,1,0)`
  +CT rolls were tuned for precisely this; HFS k→inferior matches the tuned scroll.
- **44082 shoulder fails (sag/cor upside-down):** (a) MR ⇒ **no `Roll(180)`** (the exact
  vertical flip) on sag/cor; (b) 31° oblique ⇒ grid ≠ patient ⇒ world cuts tilted; (c) the
  transpose error is large here, corrupting `slice_dir`/scroll and the oblique baseline.
- **44608 brain (sagittal A/P off):** orthogonal (1°) ⇒ axial fine and transpose ~0; but
  MR ⇒ sagittal gets no correction and the unconditional pixel **X-flip** is uncompensated
  for MR ⇒ the sagittal in-plane horizontal (A↔P) is **mirrored** (image not upside-down).
- **44313 sagittal-T1 (input in Axial box, recon rotated, VRT wrong):** the acquisition
  **normal ≈ patient R/L** (dominance 0.994). The hard-coded axial camera cuts world-Z =
  the grid's native ij-plane = **the acquired sagittal slices** ⇒ sagittal shown in the
  "Axial" box. The rest of the camera/`ViewUp(0,0,1)`/VRT assumes k = superior, but here
  k ≈ L/R ⇒ recon and 3D rotated ~90°.

---

## Deliverable 5 — Root-cause hypothesis (mathematical)

The single mathematical fault is that **Zeta MPR never maps voxel space to patient space
via the orientation matrix `R`.** It assumes voxel axes ≈ patient axes (an *implicit
identity* assumption), which is true **only for a true-axial acquisition (44614 CT).**
Three concrete defects implement that fault:

1. **No reorientation by `R`.** The volume is cut along **world axes of the raw grid**;
   `R` is loaded but the camera path returns fixed world-axis vectors (the
   `is_identity_branch` is always False, so even the partial matrix logic is bypassed).
   ⇒ obliques tilt (44082), and a sagittal/coronal acquisition's native plane lands in the
   wrong viewport (44313).
2. **`R` is consumed transposed.** `_to_iop_matrix` writes **columns** = (row,col,normal);
   `_get_camera_vectors_for_view`/`_get_scroll_direction` read **rows**. Harmless when `R`
   is ~diagonal (CT, brain), corrupting when oblique (shoulder) — proven by
   `transpose_mismatch` magnitude (0 → 0.06 → 0.46 across the cases).
3. **Radiological correction is modality-gated** (`== "CT"`) and built from empirical
   `Roll/Azimuth` instead of the matrix ⇒ all MR loses the flips ⇒ upside-down (44082) /
   A-P mirror (44608). (Per VTK, `Roll(180)≠Azimuth(180)`, and a mirror can't come from
   camera motion — so a roll scheme can only ever be hand-tuned for one geometry.)

Supporting: slices are ordered by **InstanceNumber**, and the grid-k sign vs the normal is
inconsistent (CT −normal, brain +normal), so through-plane/scroll direction isn't
geometrically guaranteed; and the corner orientation labels are **hard-coded**
(`_get_orientation_labels`), so they cannot reveal any of this.

---

## Deliverable 6 — Proposed correction strategy (math-first, conservative, reversible)

Adopt the **matrix-driven** approach used by 3D Slicer (`SliceToRAS`), Cornerstone3D, and
VTK's own examples — *identical code path for CT and MR*, derived from `R`, not from
modality or empirical rolls. Three flag-gated, independently reversible phases; **CT
(44614) must stay byte-identical at every phase (regression anchor).**

- **Phase 1 — canonicalize the volume (built, default OFF).** Resample to an axis-aligned
  LPS grid: reslice axes `= R⁻¹·R_target` (= `Rᵀ` for `R_target=I`), which maps the slice
  normal → output +Z. This is the standard `vtkImageReslice` recipe (output axes expressed
  in input coords). Fixes the *oblique* error (44082) and gives 44313/44608 a clean grid.
  Fix the k-sign from **IPP** (pass `slice_axis_lps` = sign of `IPP_last−IPP_first` along
  the normal) so scroll is superior→inferior.
- **Phase 2 — plane-aware viewport assignment.** Classify the acquisition plane from `R`'s
  dominant normal axis and route the native slices to the matching viewport
  (axial→Axial, sagittal→Sagittal, coronal→Coronal); reconstruct the other two. Fixes
  44313's "sagittal in the Axial box" + VRT.
- **Phase 3 — geometry-driven cameras + labels (the real cure).** Replace
  `_get_camera_vectors_for_view` + the four `if modality=="CT"` roll gates with constant
  per-plane `(right, up, normal)` triads (Cornerstone LPS: axial normal `(0,0,−1)`/up
  `(0,−1,0)`; sagittal `(1,0,0)`/`(0,0,1)`; coronal `(0,−1,0)`/`(0,0,1)`), setting the
  camera from the triad and choosing the **normal sign** to put the camera on the viewer
  side; derive `view_up` from the triad each update (no read-back). Make
  `_get_orientation_labels` compute from the triad too. Consume `R` by **columns** (fix the
  transpose) and feed it to `SetDirectionMatrix`/the contract rather than the camera hack.
  Calibrate one sign against 44614 so CT is unchanged.

---

## Deliverable 7 — Risk analysis & rollback

| Phase | Risk | Mitigation | Rollback |
|---|---|---|---|
| 1 canonicalize | Wrong reslice could distort obliques | default OFF env flag; fail-safe returns input on any error/no-op for axis-aligned; headless math tests (18/18) | flag OFF = byte-identical; delete the one guarded call |
| 2 viewport routing | Mis-route if plane mis-classified | gate on dominance ≥ threshold; own flag; only changes which mapper feeds which cell | flag OFF |
| 3 cameras/labels | **Highest** — edits the camera path (reference lines, rotation/oblique, baseline capture) | smallest diff; **44614 = regression anchor (must not change)**; preserve R1.2 baseline-camera + sign-check + reference/rotation logic; live-validate all four before enabling | flag OFF restores empirical CT-roll path |

Global guardrails: back up touched files to `backups/zeta_mpr_orientation_2026-06-02/`;
no DB/network/protocol changes; FAST viewer untouched (no VTK windows); preserve overlays,
measurements, sync, reference/rotation lines; run `tests/code/mpr/` + the `ZETA_MPR_DIAG=1`
invariant checks; verify the matrix: CT unchanged, 44082 sag/cor upright, 44608 sagittal
A/P correct, 44313 native sagittal in the Sagittal box + upright VRT.

---

---

## Deliverable 8 — Implementation status (2026-06-02, DEFAULT OFF)

The matrix-driven fix is implemented behind the existing default-OFF flag. **Flag OFF ⇒
byte-identical legacy** (verified: `_needs_radiological_correction()` reduces to
`detected_modality=="CT"` when no canonical marker is present, and the toolbar skips
canonicalization entirely).

**Changed files** (backups in `backups/zeta_mpr_orientation_2026-06-02/`):
- `modules/mpr/zeta_mpr/_mpr_canonicalize.py` — `canonicalize_volume()` now resamples
  oblique/non-axial input to axis-aligned LPS (reslice axes `R⁻¹·I = Rᵀ`, slice-normal→+Z),
  derives the **through-plane sign from DICOM IPP** (`slice_axis_sign` / `_read_dicom_slice_axis_sign`)
  so scroll is superior→inferior, and attaches a `ZetaCanonical` field marker (axis-aligned
  inputs like true-axial CT and near-axial MR are *marked, not resampled*). Flag reads env
  **or** `<USER_DATA_ROOT>/config/zeta_mpr.json` {"canonicalize": true}.
- `modules/mpr/zeta_mpr/mpr_viewer/widget.py` — reads the marker into `self._mpr_canonicalized`.
- `modules/mpr/zeta_mpr/mpr_viewer/_mpr_orientation.py` — new `_needs_radiological_correction()`
  = `detected_modality=="CT" or _mpr_canonicalized`.
- `_mpr_views.py` (×3), `_mpr_rendering.py`, `_mpr_oblique.py`, `_mpr_series.py` — the six
  `if self.detected_modality == "CT":` orientation gates now call the predicate, so the
  proven CT corrections also apply to canonicalized/axis-aligned volumes (fixes 44082 sag/cor,
  44608 A/P, 44313 once axis-aligned). The dead `standard_mpr_viewer_original.py` is untouched.
- `tests/code/mpr/test_mpr_canonicalize.py` — headless math tests (classification, no-op vs
  needs, decode round-trip, reslice axes, **slice_axis_sign**, sign override, flag). Validated
  here (numpy only; run the committed suite on the Windows venv where VTK/PySide6 exist).

**How it fixes each case (design intent — pending live confirmation):** 44614 CT = no-op
(unchanged anchor); 44082 oblique = resampled to axial + corrections; 44608 axial MR = marked
+ corrections (A/P); 44313 sagittal = resampled to true axial (native sagittal then lands in
the Sagittal box) + corrections + corrected VRT.

**NOT yet live-validated (flag stays OFF until then):** the VTK resample end-to-end and the
output L/R · A/P · S/I signs once routed through the CT path. These need the source build
**relaunched with the flag enabled** (the running instance won't pick up new code) — then
verify CT unchanged and the four cases canonical, with `ZETA_MPR_DIAG=1` + `tests/code/mpr/`.
To enable: set env `AIPACS_ZETA_MPR_CANONICALIZE=1` (or the config file) and restart.

*Raw data: `docs/analysis/data/2026-06/ZETA_MPR_GEOMETRY_RAW_2026-06-02.json`. Companion analyses:
`ZETA_MPR_ORIENTATION_INVESTIGATION_2026-06-02.md`, `ZETA_MPR_FOURCASE_REVIEW_2026-06-02.md`.*
