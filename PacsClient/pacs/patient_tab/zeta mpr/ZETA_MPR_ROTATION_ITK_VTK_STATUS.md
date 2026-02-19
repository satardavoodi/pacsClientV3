# Zeta MPR Rotation (ITK/VTK) Status and Forward Plan

Module: `PacsClient/pacs/patient_tab/zeta mpr/`
Primary reference: `docs/IMAGE_PIPELINE_REFERENCE.md`
Secondary reference: `PacsClient/pacs/patient_tab/zeta mpr/ZETA_MPR_PIPELINE_REFERENCE.md`
Engineering journal: `PacsClient/pacs/patient_tab/zeta mpr/ZETA_MPR_ENGINEERING_JOURNAL.md`
Document date: 2026-02-17
Owner area: Standard MPR rotation and oblique reconstruction

## 1) Scope

This document tracks the full rotation path for crosshair-driven MPR rotation, including:
- what was attempted historically,
- what failed,
- what is currently implemented,
- what still remains for future versions.

Target behavior for this track:
- user rotates the **axial** crosshair by angle `theta`,
- sagittal and coronal must be reconstructed obliquely by the same `theta`,
- no center drift,
- no left/right inversion,
- no unintended flip,
- no geometry distortion.

## 2) Non-negotiable coordinate facts (from IMAGE_PIPELINE_REFERENCE)

The pipeline already has important axis transforms before MPR rotation code executes:
- `convert_itk2vtk()` applies a **Y flip** to the SimpleITK array.
- direction matrix is compensated and stored in VTK field data (`DirectionMatrix`).
- `StandardMPRViewer` applies an additional **X flip** to enforce radiological orientation.
- `StandardMPRViewer` adjusts direction interpretation after this X flip.

Practical implication:
- all rotation math must work in the current transformed VTK world space,
- oblique code must not assume raw DICOM axes directly,
- small sign mistakes can look like mirror inversion.

## 3) Historical summary

### R0 (pre-lock, legacy oblique transform path)

Legacy path in `standard_mpr_viewer.py` used:
- `vtkImageReslice` transforms,
- generated temporary oblique volumes,
- mapper replacement per target view.

Observed failures:
- center drift after rotation,
- occasional mirror/flip perception,
- unstable behavior between datasets,
- occasional black/empty output.

### R0.5 (stability lock)

Rotation interaction was locked by setting:
- `rotation_enabled = False`

This prevented production regressions but blocked real oblique reconstruction.

## 4) Current implementation (R1, active)

### 4.1 Design choice

R1 intentionally avoids runtime mapper swapping for crosshair rotation.
Instead, it uses a camera-plane approach on top of existing `vtkImageResliceMapper` views:
- keep each 2D view mapper bound to the source `self.image_data`,
- rotate sagittal/coronal camera plane orientation around axial normal,
- lock camera focal point to `self.current_position`.

### 4.2 Why this is safer for now

- no repeated `vtkImageReslice` volume replacement,
- no per-frame mapper churn,
- deterministic center lock (`focal = current_position`),
- lower probability of hidden axis-sign regressions.

### 4.3 R1 behavior rules

- Axial crosshair angle drives oblique update.
- Sagittal/coronal are reconstructed by rotating their camera normal and view-up around axial normal.
- Rotation uses Rodrigues formula.
- Effective rotation sign is currently `-axial_angle` to match interaction orientation in current coordinate space.
- When axial angle returns to near zero, views are restored to baseline orthogonal camera states.

### 4.4 Code map for R1

File: `PacsClient/pacs/patient_tab/zeta mpr/standard_mpr_viewer.py`

Key switches and state:
- `rotation_enabled = True`
- `oblique_enabled = True`
- `_base_camera_state`
- `_axial_oblique_active`

New/updated methods:
- `_capture_base_camera_state()`
- `_normalize_vector()`
- `_dot_product()`
- `_cross_product()`
- `_rotate_vector_around_axis()`
- `_set_view_camera_orientation()`
- `_update_oblique_reslicing()` (axial-first camera-driven path)
- `_reset_all_to_orthogonal(force=False)`
- `_update_slice_positions()` (preserves oblique orientation during center updates)

Lifecycle integration points:
- baseline camera cache after initial UI setup,
- baseline camera cache after series reload,
- baseline camera cache after Reset workflow.

## 5) Exact acceptance criteria for R1

For axial rotation test at `+10 deg` and `-10 deg`:
- sagittal/coronal rotate obliquely by the same angle magnitude,
- crosshair center remains fixed (no jump/drift),
- anatomy does not mirror or flip unexpectedly,
- scrolling still works in all three 2D views,
- Reset returns orthogonal baseline and clears oblique state.

## 6) Manual verification protocol

Use this exact checklist for each dataset:

1. Load MPR with no rotation.
2. Record baseline screenshot (axial/sagittal/coronal).
3. Rotate axial crosshair to `+10 deg`.
4. Verify sagittal/coronal oblique reconstruction quality.
5. Rotate axial crosshair to `-10 deg`.
6. Verify center lock and no mirror/flip artifacts.
7. Drag crosshair center while oblique is active.
8. Verify plane remains oblique and center-locked.
9. Scroll slices in axial/sagittal/coronal.
10. Press Reset Selected / Reset rendering and verify:
- orthogonal baseline restored,
- crosshair angles are zero,
- no oblique residue remains.

Recommended dataset classes:
- near-identity orientation matrix dataset,
- non-identity direction matrix dataset,
- CT dataset with strong bone/air boundaries (easy inversion detection).

## 7) Known limits in R1

- Primary supported path is **axial-driven** oblique reconstruction.
- Compound multi-axis oblique (axial + sagittal + coronal combined) is intentionally deferred.
- Legacy `_apply_oblique_transform()` remains in file as fallback/reference but is not the active R1 path.

## 8) Rollback plan

If R1 fails on target datasets:

1. Disable rotation interaction:
- `rotation_enabled = False`

2. Keep orthogonal mode stable:
- `oblique_enabled = True/False` as needed,
- force `_reset_all_to_orthogonal(force=True)` during reset.

3. Log failure case in Version Log with:
- dataset identifier,
- direction matrix snapshot,
- step where regression appears,
- screenshots before/after.

## 9) Version log

| Version | Date | Status | Code path | Result |
|---|---|---|---|---|
| R0 | pre-2026-02-08 | complete | legacy `vtkImageReslice` + mapper swap path | unstable on multiple datasets |
| R0.5 | pre-2026-02-08 | complete | `rotation_enabled = False` lock | stable orthogonal mode |
| R1 | 2026-02-08 | implemented | axial-first camera-plane oblique reconstruction | pending dataset validation |
| R1.1 | 2026-02-08 | implemented | direction-matrix-aligned camera basis + extended `ROT_DEBUG` diagnostics | pending validation on oblique datasets |
| R1.2 | 2026-02-16 | implemented | baseline-camera + oblique-normal-sign + update-ordering fix | fixes coronal flip bug, see details below |

### R1.2 details (2026-02-16)

Four root-cause bugs were identified and fixed:

1. **`_update_slice_positions` overwrote oblique camera state.**  
   Call order in center/line/scroll drag was `_update_all_crosshairs() → _update_oblique_reslicing() → _update_slice_positions()`.  The last call re-positioned cameras along the orthogonal axis, destroying the oblique normal.  
   *Fix:* a) `_update_all_crosshairs` no longer triggers oblique reslicing.  b) `_update_slice_positions` only moves the focal point when `_oblique_cameras_active` is True.  c) A new `_synchronize_oblique_views()` method is called as the **final** step in every interaction handler.

2. **No baseline camera reference.**  
   `_set_oblique_camera()` read `view_up` from the *current* camera state, which drifted after successive oblique updates.  
   *Fix:* `_capture_baseline_camera_state()` is called once after `_setup_ui()` (and again after `_reset_rendering`).  `_set_oblique_camera` always uses the baseline `view_up` and `distance`.

3. **Oblique normal sign not validated.**  
   `cross(line_dir, slice_normal)` may yield a normal that points to the opposite hemisphere (e.g. anterior instead of posterior for coronal).  This caused the camera to jump behind the volume → left/right eye swap.  
   *Fix:* `_set_oblique_camera` now computes `dot(oblique_normal, baseline_direction)` and negates the normal if the sign is wrong.

4. **Missing `ResetCameraClippingRange`.**  
   After oblique camera repositioning, the clipping planes could exclude the volume.  
   *Fix:* `renderer.ResetCameraClippingRange()` is called at the end of `_set_oblique_camera`.

Backup: `backups/zeta_mpr_backup_2026-02-16/`

## 10) Next versions

### R2 (planned)

- robust compound multi-axis oblique composition,
- deterministic rotation composition order,
- explicit transform model documented against DICOM orientation.

### R3 (planned)

- automated validation hooks for center-lock and orientation sanity checks,
- regression suite over representative direction matrices.

## 11) Update policy for future edits

For every rotation-related change:
- update this document first,
- add one new row in Version Log,
- update the Engineering Journal (`ZETA_MPR_ENGINEERING_JOURNAL.md`) with:
  - what you tried and why,
  - what new questions arose,
  - what assumptions turned out to be wrong.
- include pass/fail for the full verification protocol,
- include rollback note if behavior regresses.

## 12) Debug logging setup (R1 diagnostics)

For detailed axial-oblique alignment diagnostics, enable:
- `ZETA_MPR_ROT_DEBUG=1`

When enabled, `standard_mpr_viewer.py` emits `[ROT_DEBUG]` lines containing:
- axial angle (deg) and crosshair center,
- axial rotation axis vector,
- per-view camera normal (`cam_n`) and expected oblique normal (`exp_n`),
- normal mismatch angle (`n_err_deg`),
- plane-through-center error (`plane_err_mm`),
- in-plane focal offset from crosshair center (`inplane_offset_mm`),
- max crosshair endpoint plane residual (`endpoint_plane_err_mm`),
- 90-degree swap alignment metric (`swap_alignment_deg`).

Primary implementation references:
- `PacsClient/pacs/patient_tab/zeta mpr/standard_mpr_viewer.py` (`_log_oblique_diagnostics`)
- `PacsClient/pacs/patient_tab/zeta mpr/standard_mpr_viewer.py` (`_update_oblique_reslicing`)

Use this diagnostic mode when validating:
- true sagittal/coronal target planes (for example orbital alignment),
- 90-degree axial rotation plane swap behavior,
- center correctness vs directional correctness separation.

R1.1 note:
- Initial review found a directional mismatch risk for oblique datasets because camera basis selection could fall back to world-aligned assumptions instead of the loaded direction-matrix basis.
- Current implementation uses direction-matrix-aligned row/col/slice vectors for camera normals (when direction metadata exists) and logs the derived basis vectors for each view in `ROT_DEBUG`.

## 13) v1.09 R1.2 — Handedness-Preserving Oblique Camera (2026-02-16)

### Changes made

Three targeted fixes based on 3D Slicer `vtkMRMLSliceNode.cxx` reference:

1. **`_set_oblique_camera` — handedness-preserving view-up**:
   - Computes fresh camera basis (right, corrected_up, direction) via
     cross products from baseline_up hint and new oblique direction.
   - Checks determinant sign of new basis against baseline determinant.
   - If handedness flipped (possible in X-flipped left-handed space),
     negates the right vector and recomputes up.
   - Eliminates the left-right mirror flip in coronal/sagittal.

2. **`_update_slice_positions` — full focal point update in oblique mode**:
   - When oblique cameras are active, ALL three focal components are set
     to `current_position`, not just the through-plane axis.
   - Ensures oblique slice passes through the crosshair center after
     the center is moved in-plane.
   - Fixes reconstruction line location drift (Bug D).

3. **`_update_oblique_reslicing` — baseline-derived slice normals**:
   - Uses `baseline_camera_state['direction']` as the source slice normal
     instead of hardcoded [0,0,1], [1,0,0], [0,1,0].
   - Correct for non-identity direction matrices and after CT camera
     corrections (Roll/Azimuth).
   - Falls back to axis-aligned defaults when baseline is unavailable.

### Backup

Full backup at: `backups/zeta_mpr_backup_2026-02-16/` (12 files, 421 KB)

### Verification status

- [ ] Rotate axial crosshair 0→30°: coronal should NOT flip/mirror
- [ ] Rotate axial crosshair 0→30°: sagittal should NOT flip/mirror
- [ ] Move crosshair center while rotated: reconstruction lines follow
- [ ] Scroll through slices while rotated: no drift, no flip
- [ ] Reset rotation to 0°: all views return to standard display
- [ ] Non-CT modality (MR): rotation works without CT-specific corrections
- [ ] Full 360° rotation: no sudden flips at any angle
