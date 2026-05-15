# Advanced VTK Orientation Deep Audit

Date: 2026-05-14
Scope: Advanced VTK viewer orientation math pipeline only (no visual workaround, no slice reversal, no reference-line rewrite, no display-convention change).

## Executive Result

Definitive answer:
The current Advanced VTK path does not maintain a single consistent patient-LPS physical transform through DICOM -> SimpleITK -> vtkImageData -> reslice/display.

Observed behavior from live session and code:
1. SimpleITK geometry can be correct relative to DICOM.
2. During conversion/display path, VTK direction effectively becomes identity in active rendering context.
3. A hard Y pixel flip is applied pre-VTK handoff, while active world mapping paths include direction-agnostic assumptions.
4. Marker/audit mismatches (large col-axis error) are therefore expected even when callback paths execute.

Recommended architecture decision: Option B (explicit geometry owner with explicit IJK<->LPS matrices), not mixed with implicit VTK direction assumptions.

Reason:
Current pipeline has clear evidence that direction is not reliably preserved/used end-to-end by all active components.

## Article Comparison Status

The article content was not provided in this chat turn as a file/path or text block. This report compares your code and runtime behavior against the required mathematical contract from your investigation instructions.

## 1) Coordinate Contract (Required A-E)

A. DICOM patient LPS:
- +X Left, -X Right
- +Y Posterior, -Y Anterior
- +Z Superior, -Z Inferior

B. DICOM image plane:
- row_cosines = IOP[0:3]
- col_cosines = IOP[3:6]
- slice_normal = row_cosines x col_cosines
- IPP_k = physical LPS of pixel (row=0, col=0) for slice k

C. SimpleITK image:
- index i,j,k
- physical = origin + direction @ (index * spacing)

D. VTK image:
- voxel index space + origin/spacing/extent
- direction may exist in vtkImageData or field-data only
- actor/reslice/camera can override or ignore expected patient-space direction semantics

E. Screen vectors in patient LPS:
- screen_right_lps
- screen_up_lps
- must be compared against expected vectors from DICOM row/col axes for current plane

## 2) Intended Affine (DICOM IJK->LPS)

For voxel index i,j,k where i=column, j=row, k=slice:

P(i,j,k) = IPP_first + i*col_spacing*row_cosines + j*row_spacing*col_cosines + k*slice_spacing*slice_normal

with slice_spacing derived from sorted IPP projections onto slice_normal.

Equivalent 4x4:

IJK_to_LPS =
[
  row_cosines*col_spacing,
  col_cosines*row_spacing,
  slice_normal*slice_spacing,
  IPP_first
]

### Numeric matrix proof (from real session logs)

Series UID: 1.3.12.2.1107.5.2.46.174759.20260513082847460710698.0.0.0

DICOM IJK->LPS (computed from logged IOP/IPP/spacing):
[
  [-0.0196738394,  0.0129576170, -4.7982602094,  -9.7242830948],
  [ 0.8747787949,  0.0002914176, -0.1079132246, -95.4863240269],
  [-0.0000000002, -0.8749040034, -0.0710997615, 222.8549967219],
  [ 0.0000000000,  0.0000000000,  0.0000000000,   1.0000000000]
]

Series UID: 1.3.12.2.1107.5.2.46.174759.2026051311301939962774171.0.0.0

DICOM IJK->LPS (computed from logged IOP/IPP/spacing):
[
  [ 0.5992385274, -0.1775025430, -0.0496029120, -18.2141853728],
  [ 0.1774233504,  0.5992307841, -0.0736517704,-123.8720468386],
  [ 0.0076903807,  0.0063493735,  5.5642915064,  16.5419960908],
  [ 0.0000000000,  0.0000000000,  0.0000000000,   1.0000000000]
]

## 3) DICOM vs SimpleITK Comparison

Live evidence:
- [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17433)

For the logged sitk_read_db stage above:
- sitk_origin equals first IPP in log.
- sitk_spacing equals expected spacing tuple.
- sitk_direction is non-identity and consistent with DICOM row/col/normal.

Assessment:
- origin_error_mm: near 0
- row_angle_error_deg: near 0
- col_angle_error_deg: near 0
- normal_angle_error_deg: near 0
- spacing_error: near 0
- valid: True

Interpretation:
Failure class A is not the dominant root for this series; SITK appears geometrically correct at read stage.

## 4) SimpleITK vs VTK After Conversion

Live evidence:
- [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17440)
- [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17014)

Observed:
- VTK origin/spacing/dimensions are present.
- VTK direction matrix in logs is identity.
- Active per-slice audit lines repeatedly show vtk_direction_matrix identity and large axis mismatch.

Quantified axis-angle mismatch (representative series from session):
- row_vs_x ~ 91.29 deg
- col_vs_y ~ 89.98 deg
- normal_vs_z ~ 90.85 deg

Assessment:
- direction_lost: True in active rendering interpretation.
- Dominant failure class: B/C/F depending exact path segment.

## 5) Hard Flip Audit

Code evidence:
- Hard Y flip at [PacsClient/pacs/patient_tab/utils/utils.py](PacsClient/pacs/patient_tab/utils/utils.py#L212)
- Direction field-data write at [PacsClient/pacs/patient_tab/utils/utils.py](PacsClient/pacs/patient_tab/utils/utils.py#L220)
- Origin/spacing assignment at [PacsClient/pacs/patient_tab/utils/utils.py](PacsClient/pacs/patient_tab/utils/utils.py#L182)

Hard flip audit record:
- flip_axis: Y
- flip_location: convert_itk2vtk in utils.py
- pixel_array_flipped: True
- origin_adjusted: No explicit origin compensation for pixel flip at active image level
- direction_adjusted: field-data direction row sign inverted, but downstream active direction use is inconsistent
- metadata_adjusted: partial metadata stored (ITKOrigin/ITKSpacing/ITKDimensions in field data)
- reference_line_adjusted: separate geometry logic exists; no single guaranteed compensation contract with this flip in Advanced active path
- marker_adjusted: markers are camera-based and can diverge from true image geometry when geometry path is inconsistent
- risk_level: High

Rule conclusion:
Pixel flip with incomplete/ignored active geometry transform contract can produce wrong patient-space interpretation.

## 6) Architecture Evaluation (Option A vs Option B)

Option A (VTK-native patient LPS everywhere) requires all active components to honor vtkImageData direction through reslice/actor/pickers/markers.

Current evidence does not support that guarantee in this code path.

Option B (explicit geometry owner) keeps display index-space but uses explicit IJK<->LPS affine for all geometry-sensitive logic.

Decision: Option B recommended.

Do not mix both contracts in same active pipeline.

## 7) Real Knee Multi-Viewport Proof Table

From latest session parser output and log lines:

| viewport | plane | DICOM IJK->LPS basis | SITK IJK->LPS status | VTK IJK->World status | actor matrix | camera right/up vs expected | mismatch_deg | failure_class |
|---|---|---|---|---|---|---|---|---|
| 2223831924896 | UNKNOWN | non-identity from IOP (series 3) | SITK not carried into per-slice metadata (None in per-slice line) | identity direction in per-slice audit | identity | major right/up disagreement | row 16.50, col 163.51, normal 0.0 | F (with B/C traits) |
| 2223834560736 | UNKNOWN | non-identity from IOP (series 5) | same | identity direction in per-slice audit | identity | severe mismatch | row 146.63, col 90.02, normal 180.0 | F (with B/D/C traits) |
| 1 | UNKNOWN | non-identity from IOP (series 6) | same | identity direction in per-slice audit | identity | near-180 col-up inversion | row 1.53, col 178.70, normal 0.0 | F |

Per-slice audit evidence:
- [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17014)
- [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17760)

Slice callback and marker path evidence:
- [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17007)
- [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17009)

## 8) Current Deviation Points

1. Conversion path introduces hard pixel flip before VTK handoff.
2. Direction matrix is stored, but active displayed image direction semantics collapse to identity in audit output.
3. Advanced viewer contains direction-aware helpers and direction-agnostic world/index assumptions simultaneously.
4. Per-slice metadata used by audit may not consistently retain stage SITK fields for all series paths.

## 9) Minimal Patch Plan (No behavior change implemented in this report)

1. Add pure-math comparison emitters (no rendering changes):
- [SITK_DICOM_GEOMETRY_COMPARE]
- [VTK_GEOMETRY_COMPARE]
- [VTK_HARD_FLIP_AUDIT]

2. Define one authoritative geometry object per series:
- IJK_to_LPS_4x4
- LPS_to_IJK_4x4
- source-of-truth for markers/reference/sync/pickers

3. Keep Advanced viewer render pipeline unchanged during audit phase, but route orientation diagnostics through explicit affine only.

4. After validation proves affine consistency, implement the minimal functional fix at one contract boundary only (not in this report).

## 10) Files/Functions To Change (Next Implementation Phase)

- [PacsClient/pacs/patient_tab/utils/utils.py](PacsClient/pacs/patient_tab/utils/utils.py)
  - convert_itk2vtk
- [PacsClient/pacs/patient_tab/utils/image_io.py](PacsClient/pacs/patient_tab/utils/image_io.py)
  - stage compare emitters and metadata bridge consistency
- [modules/viewer/advanced/viewer_2d.py](modules/viewer/advanced/viewer_2d.py)
  - geometry consumption and audit-path consistency
- [modules/viewer/advanced/orientation_markers.py](modules/viewer/advanced/orientation_markers.py)
  - consume explicit affine contract (future implementation)
- [builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py](builder/plugin%20package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py)
  - mirror parity

## 11) Files/Functions Not To Touch (Per your constraints)

- display convention routing logic (no convention change)
- slice order reversal logic (no reverse workaround)
- reference-line mathematical model (no ref-line rewrite in this phase)

## 12) Validation Tests Required Before Any Functional Fix

1. Series-level geometry consistency test:
- DICOM affine vs SITK affine must be near-equal within tolerance.

2. Conversion integrity test:
- SITK affine vs VTK active affine must be near-equal, or explicit direction_lost=True must trigger Option B path.

3. Multi-viewport knee runtime test:
- per-viewport expected vs actual right/up mismatch threshold <= 10 deg after eventual fix.

4. Regression guard:
- existing Advanced interaction, sync, and marker diagnostics remain stable.

## 13) Runtime Path Proof (Already verified)

- Active slice path executes in Advanced backend:
  - [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17007)
- Marker update executes:
  - [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17009)
- Audit emitter executes:
  - [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17014)
- Stage sitk/vtk emitters execute:
  - [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17433)
  - [user_data/logs/viewer_diagnostics.log](user_data/logs/viewer_diagnostics.log#L17440)

Conclusion:
This is not a missing-callback problem now; it is a geometry-contract consistency problem.
