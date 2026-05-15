# ADVANCED_OPTION_B_AFFINE_IMPLEMENTATION.md
**Status:** Implemented — v3.0.3 (2026-05-14)  
**Branch:** matab-conservative

---

## Summary

This document describes the **Option B explicit affine contract** for the Advanced VTK viewer orientation pipeline. Option B fixes incorrect orientation marker labels (L/R/A/P/S/I) without modifying the VTK render pipeline.

---

## Root Cause (Recap)

| Stage | What happens | Effect |
|---|---|---|
| `sitk.ImageFileReader` | Reads DICOM IOP/IPP correctly | Geometry correct |
| `convert_itk2vtk` | Applies hard Y-flip: `arr[:, ::-1, :]` | Pixel array flipped, **origin not updated** |
| VTK active rendering | `vtkImageData.GetDirectionMatrix()` is **identity** | No DICOM orientation in VTK geometry |
| Old orientation markers | Uses camera right/up via `_camera_basis_vectors()` | Camera is axis-aligned → wrong labels for non-axial-HFS series |

---

## Architecture: Option B

> Advanced VTK rendering stays in voxel/index space.  
> All geometry-sensitive logic uses an explicit `SeriesGeometryIndex` affine contract.  
> VTK direction matrix is ignored by design (explicitly logged).

### Files Changed

| File | Change | Plugin Mirror |
|---|---|---|
| `modules/viewer/advanced/series_geometry_index.py` | **NEW** — core affine contract class | `builder/plugin package/.../series_geometry_index.py` |
| `modules/viewer/advanced/orientation_markers.py` | Added `update_from_affine()` method | Mirrored |
| `modules/viewer/advanced/viewer_2d.py` | Import + field + build + wire-up + `[ADVANCED_VTK_DIRECTION_IGNORED_BY_DESIGN]` | Mirrored |

---

## DICOM Affine Math

**Raw DICOM IJK → LPS:**
```
P_lps(i, j, k) = IPP_first
               + i * col_spacing  * row_cosines    ← i grows along row-direction
               + j * row_spacing  * col_cosines    ← j grows along column-direction
               + k * slice_spacing * slice_normal

IJK_to_LPS columns:
  col 0 = row_cosines   * col_spacing     (i-axis)
  col 1 = col_cosines   * row_spacing     (j-axis)
  col 2 = slice_normal  * slice_spacing   (k-axis)
  col 3 = IPP_first                       (origin, homogeneous)
```

**Y-flip compensation (`convert_itk2vtk` applies `arr[:, ::-1, :]`):**

After the flip: `j_display = (N_rows - 1) - j_original`

Effective display affine for VTK index `(i, j_display, k)`:
```
  col 0 = row_cosines  * col_spacing                           (unchanged)
  col 1 = -col_cosines * row_spacing                           (sign flipped)
  col 2 = slice_normal * slice_spacing                         (unchanged)
  col 3 = IPP_first + (N_rows - 1) * row_spacing * col_cosines (origin shifted)
```

**Screen-edge directions from effective affine:**
```
  screen_right_lps = normalize(effective_col0) = row_cosines
  screen_up_lps    = normalize(effective_col1) = -col_cosines
```

**Validation (axial HFS):**
```
  row_cosines = (1,0,0), col_cosines = (0,1,0)
  screen_right = (1,0,0) = L direction  ✓ (screen right = patient Left)
  screen_up    = (0,-1,0) = A direction ✓ (Anterior at top)
```

---

## Correct Orientation Labels by Series Type

| Series | row_cosines | col_cosines | screen_right | screen_up | Right | Left | Top | Bottom |
|---|---|---|---|---|---|---|---|---|
| Axial HFS | (1,0,0) | (0,1,0) | (1,0,0)=L | (0,-1,0)=A | L | R | A | P |
| Sagittal HFS | (0,1,0) | (0,0,-1) | (0,1,0)=P | (0,0,1)=S | P | A | S | I |
| Coronal HFS | (1,0,0) | (0,0,-1) | (1,0,0)=L | (0,0,1)=S | L | R | S | I |

---

## New Log Tags

All emitted at `logger.warning(..., extra={"component": "viewer"})`.

### `[ADVANCED_GEOMETRY_AFFINE_CONTRACT]`
Emitted once per series build. Contains raw DICOM affine, determinant, orthonormal error, validation errors.

```
[ADVANCED_GEOMETRY_AFFINE_CONTRACT] series_uid=<UID> n_instances=<N>
  row_cosines=(...) col_cosines=(...) slice_normal=(...)
  pixel_spacing=[...] slice_spacing=... origin_ipp=(...)
  n_rows=... n_cols=... n_slices=...
  ijk_to_lps_4x4=[...] lps_to_ijk_4x4=[...]
  determinant=... orthonormal_error=... spacing_error=...
  valid=True/False validation_errors=<list|none>
  ijk_to_lps_hash=<6hex>
```

### `[ADVANCED_EFFECTIVE_DISPLAY_AFFINE]`
Emitted once per series build. Contains Y-flip model, effective affine, screen-edge directions.

```
[ADVANCED_EFFECTIVE_DISPLAY_AFFINE] series_uid=<UID>
  y_flip_detected=True origin_adjusted=True
  vtk_pixel_array_transform_ijk=flip_j n_rows=<N>
  original_ijk_to_lps=[...] effective_display_ijk_to_lps=[...]
  screen_right_lps=(...) screen_up_lps=(...)
  ijk_to_lps_hash=<6hex>
```

### `[ADVANCED_MARKERS_FROM_AFFINE]`
Emitted once per slice render when affine path is used. Contains final marker labels.

```
[ADVANCED_MARKERS_FROM_AFFINE] viewport_id=<VP> series_uid=<UID>
  series_number=<SN> slice_index=<K>
  ijk_to_lps_hash=<6hex> y_flip_detected=True
  screen_right_lps=(...) screen_up_lps=(...)
  right_label=L left_label=R top_label=A bottom_label=P
  confidence=high source=SeriesGeometryIndexAffine
```

### `[ADVANCED_VTK_DIRECTION_IGNORED_BY_DESIGN]`
Emitted once per series. Confirms VTK direction matrix is identity and Option B is active.

```
[ADVANCED_VTK_DIRECTION_IGNORED_BY_DESIGN] viewport_id=<VP> series_uid=<UID>
  vtk_direction_is_identity=True geometry_valid=True
  option_b_active=True ijk_to_lps_hash=<6hex>
```

---

## Implementation Details

### `SeriesGeometryIndex.build_from_instances()`

1. Extract IOP from first instance → `row_cosines`, `col_cosines`, `slice_normal`
2. Validate IOP consistency across all slices (< 2° deviation)
3. Extract PixelSpacing → `pixel_spacing_row`, `pixel_spacing_col`
4. Extract IPP from first instance → `origin_ipp`
5. Compute slice spacing from IPP projections onto `slice_normal`
6. Determine `n_rows`, `n_cols`, `n_slices` (VTK dims preferred, fallback to metadata)
7. Build raw 4×4 `ijk_to_lps_4x4` and its inverse `lps_to_ijk_4x4`
8. Compute validation metrics: `determinant`, `orthonormal_error`, `spacing_error`
9. Build lookup maps: `index_to_sop_uid`, `sop_uid_to_display_index`, `display_index_to_ijk_k`
10. Model Y-flip → `effective_display_ijk_to_lps` (col1 sign flip, origin shift)
11. Emit diagnostic logs

### `DicomOrientationMarkers.update_from_affine()`

- Calls `geometry.screen_right_lps()` and `geometry.screen_up_lps()`
- Calls `_vector_to_lps_label()` for all four screen edges
- Calls `_render_markers()` with the computed labels
- Emits `[ADVANCED_MARKERS_FROM_AFFINE]`
- Returns `False` gracefully if geometry is invalid → caller uses legacy fallback

### `ImageViewer2D._build_series_geometry_index()`

- Called after `self.metadata` and `self.vtk_image_data` are set
- Extracts `instances`, `series_uid`, and VTK dimensions
- Calls `SeriesGeometryIndex.build_from_instances(..., apply_y_flip=True)`
- Emits `[ADVANCED_VTK_DIRECTION_IGNORED_BY_DESIGN]`

### `ImageViewer2D._set_slice_impl()` marker update

```python
_gi = getattr(self, "_series_geometry_index", None)
if _gi is not None and _gi.valid:
    # Option B: affine-based, correct for all orientations
    self.orientation_markers.update_from_affine(_gi, ...)
else:
    # Legacy fallback: camera-based (may be wrong for non-axial-HFS)
    self.orientation_markers.update_from_geometry(...)
```

---

## Test Coverage

**File:** `tests/viewer/test_series_geometry_index.py`  
**Count:** 50 tests, all passing  
**Run:** `.venv\Scripts\python.exe -m pytest tests/viewer/test_series_geometry_index.py -v`

| Class | Tests | What is tested |
|---|---|---|
| `TestAxialHFS` | 12 | Full affine build, Y-flip math, inverse, lookup maps |
| `TestSagittal` | 5 | Sagittal affine, normal, screen vectors |
| `TestCoronal` | 4 | Coronal affine, normal, screen vectors |
| `TestObliqueNearAxial` | 3 | 15° oblique, homogeneous row |
| `TestYFlipModel` | 5 | Exact origin shift, col1 sign, col0/col2 unchanged, no-flip case |
| `TestOrientationLabels` | 6 | screen_right/screen_up unit vectors for axial/sagittal/coronal |
| `TestValidation` | 8 | Empty, missing IOP/IPP, degenerate vectors, inconsistent IOP, n_rows=0 |
| `TestIopConsistency` | 2 | All-consistent passes, slight deviation OK |
| `TestOrientationMarkersIntegration` | 4 | Labels via `update_from_affine` for axial/sagittal/coronal + invalid fallback |

---

## Invariants Preserved

1. **Plugin mirror parity** — all three files SHA-equal between canonical and plugin package  
2. **Fallback** — `update_from_geometry` (camera-based) is still called when `_series_geometry_index` is None or invalid  
3. **No render pipeline change** — only marker label computation changed  
4. **No FAST viewer touch** — all changes in `modules/viewer/advanced/` only  
5. **Y-flip modeled, not fixed** — `apply_y_flip=True` always; no compensating flip added to VTK pipeline  
6. **Log level** — all `[ADVANCED_*]` at `logger.warning(..., extra={"component": "viewer"})`  
