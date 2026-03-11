# MPR Oblique Rotation Bug Analysis Report

**Date:** 2026-02-16  
**Module:** `PacsClient/pacs/patient_tab/zeta mpr/standard_mpr_viewer.py`  
**Version:** v1.06 (file) / v1.08.9.8.3 (app)  
**Backup:** `backups/zeta_mpr_backup_2026-02-16/` (12 files, 421 KB)

---

## 1. Reported Bugs

| # | Bug | Severity |
|---|-----|----------|
| A | Crosshair movement causes sudden issues during rotation, especially along Y-axis | High |
| B | Coronal images flip during rotation | Critical |
| C | Rotating axial X-axis 10–20° swaps left/right eyes in coronal | Critical |
| D | Reconstruction line locations sometimes incorrect | Medium |

---

## 2. Architecture Overview

### Camera-Based Oblique MPR (R1 Approach)

The viewer uses `vtkImageResliceMapper` with `SliceFacesCameraOn()` +
`SliceAtFocalPointOn()`. Instead of computing oblique reslice volumes at runtime,
it **repositions the camera** so the mapper auto-slices along the oblique plane.

### Coordinate Pipeline

```
DICOM (LPS) → SimpleITK (ZYX array) → convert_itk2vtk (Y-flip)
→ vtkImageFlip (X-flip, axis=0) → VTK image_data
→ Camera with CT corrections (sagittal: Roll(180), coronal: Azimuth(180)+Roll(180))
→ Display
```

### Key Data Transformations

1. **Y-flip**: Applied in `convert_itk2vtk`. The stored DirectionMatrix in field
   data has **row 1 negated** as compensation.
2. **X-flip**: Applied via `vtkImageFlip(axis=0)` in `__init__`. Direction matrix
   column 0 is negated to compensate.
3. **CT Camera Corrections**: Sagittal gets `Roll(180)`, coronal gets
   `Azimuth(180) + Roll(180)` for radiological convention.

### 9-Point Oblique Algorithm

When crosshairs rotate in a source view, two crosshair lines trace the
intersection of two perpendicular oblique planes with the source slice:

```
oblique_normal = cross(line_direction, source_slice_normal)
```

Two tiers of sample points per line (outer at 25%, inner at 1/6 of shortest
axis span) provide robustness against FOV edge cases.

---

## 3. Root Cause Analysis

### Root Cause 1: View-Up Instability in Oblique Camera (Bugs B, C)

**Location:** `_set_oblique_camera()` (lines 3993–4069)

**Mechanism:** The v1.08 fix correctly uses `baseline_up` instead of drifted
camera view-up. However, when the camera direction changes obliquely, the
`baseline_up` is used as a **raw hint** to VTK's camera. VTK internally
orthogonalizes view-up via the "look-at" construction:

```
f = normalize(focal - pos)      # viewing direction
s = normalize(f × view_up)      # right vector
u = s × f                       # corrected up
```

The problem arises because the right vector `s` is computed from a cross
product of the new viewing direction with the baseline view-up. When working
in the **left-handed** coordinate system (due to X-flip), this cross product
may produce a right vector that points in the opposite direction compared
to the baseline, causing a **sudden mirror/flip** in the rendered image.

**Key insight from 3D Slicer:** Slicer's `RotateToAxes()` method explicitly
preserves **handedness** (determinant sign) of the orientation matrix when
computing the orthogonal frame for rotated views. This prevents the flip
that occurs when the cross product switches sign in a left-handed space.

**Fix:** Compute the full camera basis (right, corrected-up, direction)
explicitly with handedness preservation:
1. Compute `right = cross(viewing_dir, baseline_up)`
2. Check if `det([right, up, dir])` has the same sign as the baseline determinant
3. If handedness flipped, negate `right`
4. Compute `corrected_up = cross(right, viewing_dir)`
5. Pass `corrected_up` to `camera.SetViewUp()`

### Root Cause 2: Incomplete Focal Point Update in Oblique Mode (Bugs A, D)

**Location:** `_update_slice_positions()` (lines 3481–3516)

**Mechanism:** When `_oblique_cameras_active` is True, only the **through-plane
component** of each view's focal point is updated:

```python
# For coronal: only Y is updated
current_focal[1] = self.current_position[1]
```

But the in-plane components (X and Z for coronal) are NOT updated. This means
if the crosshair center moves in X (by dragging in axial or sagittal), the
coronal focal point X stays at its old value. Since `_set_oblique_camera` uses
`camera.GetFocalPoint()` to compute the new camera position:

```python
old_focal = np.array(camera.GetFocalPoint())
new_pos = old_focal + oblique_normal * distance
```

The camera is positioned relative to an **outdated focal point**, causing the
oblique slice to pass through the wrong location. This explains:
- Incorrect reconstruction line positions (Bug D)
- Sudden positional jumps when moving crosshair center during rotation (Bug A)

**Fix:** In oblique mode, update ALL three focal point components to match
`current_position`, not just the through-plane component.

### Root Cause 3: Hardcoded Axis-Aligned Slice Normals (Bug D)

**Location:** `_update_oblique_reslicing()` (lines 3906–3920)

**Mechanism:** The source slice normals are hardcoded:

```python
if source_view == 'axial':
    slice_normal = np.array([0.0, 0.0, 1.0])
elif source_view == 'sagittal':
    slice_normal = np.array([1.0, 0.0, 0.0])
elif source_view == 'coronal':
    slice_normal = np.array([0.0, 1.0, 0.0])
```

These are correct for standard axis-aligned views but become incorrect when:
- The DICOM direction matrix is non-identity (oblique acquisitions)
- After CT camera corrections change the actual viewing direction

For the standard case (identity direction matrix), the camera corrections
(Roll/Azimuth) don't change the actual slice normal — they only change the
up/right vectors. So the hardcoded normals are coincidentally correct in the
standard case.

**Fix:** Derive slice normals from the baseline camera state rather than
using hardcoded axis vectors. This provides future robustness for non-standard
acquisitions and direction matrices.

---

## 4. Reference: 3D Slicer's Approach

Source: `Slicer/Libs/MRML/Core/vtkMRMLSliceNode.cxx`

### SliceToRAS Matrix
```
Column 0 = X axis (right direction on screen)
Column 1 = Y axis (up direction on screen)
Column 2 = Z axis (slice normal)
Column 3 = Translation (slice position)
```

### SetSliceToRASByNTP (Normal, Tangent, Position)
```cpp
Cross = Normal × Tangent
Tangent = Cross × Normal
// Normalize all three vectors
// Assign to matrix based on Orientation enum
```

### RotateToAxes (preserves handedness)
```cpp
originalHandedness = sign(det(SliceToRAS[0:3,0:3]))
Z = X × Y    // if originalHandedness > 0
Z = Y × X    // if originalHandedness < 0
// This ensures the determinant sign never flips
```

### Orientation Presets
| View | X (right) | Y (up) | Z (normal) |
|------|-----------|--------|------------|
| Axial | [-1,0,0] | [0,1,0] | [0,0,1] |
| Sagittal | [0,-1,0] | [0,0,1] | [-1,0,0] |
| Coronal | [-1,0,0] | [0,0,1] | [0,-1,0] |

---

## 5. Implemented Fixes

### Fix 1: Handedness-Preserving View-Up (Critical)
- Compute camera basis explicitly with cross products
- Check determinant sign before/after to preserve handedness
- Prevents the left-right flip that occurs in left-handed (X-flipped) space

### Fix 2: Complete Focal Point Update (High)
- In oblique mode, update all three focal components from `current_position`
- Ensures oblique slice correctly tracks crosshair center
- Fixes reconstruction line position errors

### Fix 3: Baseline-Derived Slice Normals (Medium)
- Use baseline camera direction as slice normal
- Provides correctness for non-identity direction matrices
- Future-proofs for oblique acquisitions

---

## 6. Testing Checklist

- [ ] Rotate axial crosshair 0→30°: coronal should NOT flip/mirror
- [ ] Rotate axial crosshair 0→30°: sagittal should NOT flip/mirror
- [ ] Move crosshair center while rotated: reconstruction lines follow
- [ ] Scroll through slices while rotated: no drift, no flip
- [ ] Reset rotation to 0°: all views return to standard display
- [ ] Non-CT modality (MR): rotation works without CT-specific corrections
- [ ] Full 360° rotation: no sudden flips at any angle
