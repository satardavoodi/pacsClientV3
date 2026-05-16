# DICOM_TO_DISPLAY_ORDER_CHAIN

## Complete Ordering Pipeline Audit — AIPacs v3.0.2

**Scope:** Axial HFS (Head-First Supine) CT — the canonical reference case.
For sagittal and coronal variants, the directional labels change but the structural analysis is identical.

**Canonical Clinical Convention (target state):**
- AXIAL: `display_k` increasing → Superior → Inferior (patient Z decreases)
- SAGITTAL: `display_k` increasing → Left → Right (patient X decreases in LPS)
- CORONAL: `display_k` increasing → Posterior → Anterior (patient Y decreases in LPS)

---

## Pipeline 1: FAST Backend (PYDICOM_QT / Lightweight2DPipeline)

| # | Stage Name | File / Function | Input Order Basis | Output Order Basis | uses_instance_number | uses_filename_order | uses_ipp_projection | uses_display_policy | First Slice LPS (axial HFS) | Last Slice LPS (axial HFS) | First Slice Label | Last Slice Label | Movement When Index Increases | Axis Sign | Possible Flip Here |
|---|-----------|----------------|------------------|--------------------|----------------------|---------------------|---------------------|---------------------|----------------------------|---------------------------|-------------------|-----------------|------------------------------|-----------|-------------------|
| 1 | **DICOM_ACQUISITION_RAW** | Scanner → PACS server | Hardware acquisition order | InstanceNumber assignment | True | False | False | False | Superior (large +Z for HFS) | Inferior (small/negative Z) | InstanceNumber=1 | InstanceNumber=N | S→I | negative-Z | No |
| 2 | **FILESYSTEM_ORDER** | `image_io._list_unique_dicom_files` (line 263) | Filenames `Instance_NNNN.dcm` | `natsorted` (natural sort) = ascending InstanceNumber | True (via filename) | True | False | False | Superior (InstanceNumber=1) | Inferior (InstanceNumber=N) | Instance_0001.dcm | Instance_NNNN.dcm | S→I | negative-Z | No |
| 3 | **METADATA_INSTANCE_LIST** | `lightweight_2d_pipeline._from_metadata_instances` | DB `instances` rows (ORDER BY instance_number) | Ascending InstanceNumber | True | False | False | False | Superior | Inferior | InstanceNumber=1 | InstanceNumber=N | S→I | negative-Z | No |
| 4 | **FAST_SORT_SLICES** | `lightweight_2d_pipeline._sort_slices` (line 2823) | SliceMeta list | **ascending `instance_number`; explicitly rejects IPP sort** (see docstring: "IPP-based sorting reverses CT head-to-feet order") | True | False | False | False | Superior (k=0) | Inferior (k=N-1) | InstanceNumber=1 | InstanceNumber=N | S→I | negative-Z | No |
| 5 | **FAST_DISPLAY_INDEX** | `lightweight_2d_pipeline._current_index` | SliceMeta[k] | `display_k` = direct SliceMeta index | True | False | False | False | Superior (k=0) | Inferior (k=N-1) | Superior | Inferior | S→I **CANONICAL** | negative-Z | No |
| 6 | **FAST_RENDER** | `qt_viewer_bridge.set_slice_index` | `_current_index` | Passes to `QtSliceViewer.update_slice` which renders `self._slices[k]` pixel file | True | False | False | False | Superior | Inferior | Superior | Inferior | S→I **CANONICAL** | negative-Z | No |
| 7 | **WHEEL_TRAVERSAL_FAST** | `vtk_widget._vw_scroll.wheelEvent` (line 1005) | `event.angleDelta().y()` | `step = -1 if delta > 0 else 1`; scroll-up = index-decreases | False | False | False | True | n/a | n/a | scroll-up = more Superior | scroll-down = more Inferior | S→I when scrolling down | negative-Z | No |
| 8 | **SLIDER_TRAVERSAL_FAST** | `_vw_scroll.slider.setValue(new_idx)` | User drag | Directly maps to `_current_index` | False | False | False | True | 0 = Superior | N-1 = Inferior | Superior | Inferior | S→I when dragging down | negative-Z | No |
| 9 | **SYNC_REFERENCE_FAST** | `GeometryAPI.compute_slice_normal` | `DisplayGeometry.effective_display_ijk_to_lps_4x4` | Maps display_k to patient LPS via affine | False | False | False | True | From display_k → LPS via affine | — | — | — | S→I | negative-Z | Only if K-flip applied |

**FAST Pipeline Verdict for Axial HFS CT:**
- Current ordering is CANONICAL (S→I when index increases) **IFF InstanceNumber=1 is the most superior slice.**
- If scanner assigns InstanceNumber=1 to the inferior end (some manufacturers), FAST is also reversed.
- The FAST pipeline has NO IPP-based normalization fallback → it is fully scanner-dependent.

---

## Pipeline 2: Advanced Backend (VTK / ImageViewer2D)

| # | Stage Name | File / Function | Input Order Basis | Output Order Basis | uses_instance_number | uses_filename_order | uses_ipp_projection | uses_display_policy | First Slice LPS (axial HFS) | Last Slice LPS (axial HFS) | First Slice Label | Last Slice Label | Movement When Index Increases | Axis Sign | Possible Flip Here |
|---|-----------|----------------|------------------|--------------------|----------------------|---------------------|---------------------|---------------------|----------------------------|---------------------------|-------------------|-----------------|------------------------------|-----------|-------------------|
| 1 | **DICOM_ACQUISITION_RAW** | Scanner | Hardware order | InstanceNumber assignment | True | False | False | False | Superior (typical HFS CT) | Inferior | InstanceNumber=1 | InstanceNumber=N | S→I | negative-Z | No |
| 2 | **FILESYSTEM_ORDER** | `image_io._list_unique_dicom_files` (line 263) | Filenames | `natsorted` = ascending InstanceNumber | True (via filename) | True | False | False | Superior | Inferior | Instance_0001.dcm | Instance_NNNN.dcm | S→I | negative-Z | No |
| 3 | **CANONICAL_SORT** | `image_io.canonical_sort_instances` (line ~670) | natsorted file list | **ascending `dot(IPP, cross(IOP_row, IOP_col))`** = ascending IPP-Z for axial HFS = **Inferior first** | False (tie-break only) | False | True | False | Inferior (min IPP·n = min Z) | Superior (max Z) | InstanceNumber for lowest Z | InstanceNumber for highest Z | **I→S REVERSED** | positive-Z | **YES — canonical_sort reverses InstanceNumber order for standard HFS** |
| 4 | **SITK_SETFILENAMES** | `image_io._execute_series_reader` (line 149) | canonical_sort output order | Preserves exact order passed via `reader.SetFileNames(...)` | False | False | False | False | Inferior (k=0 file) | Superior (k=N-1 file) | Instance for min Z | Instance for max Z | I→S | positive-Z | No (ITK preserves order) |
| 5 | **SITK_EXECUTE** | `sitk.ImageSeriesReader.Execute()` | Order from SetFileNames | Preserves exactly; does NOT reorder. `arr = GetArrayFromImage()` → shape (Z,Y,X) C-order | False | False | False | False | Inferior (arr[0]) | Superior (arr[N-1]) | arr[0] = min-Z slice | arr[N-1] = max-Z slice | I→S | positive-Z | No |
| 6 | **Y_FLIP_NUMPY** | `utils.convert_itk2vtk` (line 204) | ITK array (Z,Y,X) | `arr[:, ::-1, :]` — ONLY reverses Y dimension (col axis), does NOT change slice (Z) order | False | False | False | False | Inferior (k=0 preserved) | Superior (k=N-1 preserved) | Same as pre-flip | Same as pre-flip | I→S **UNCHANGED** | positive-Z | No — Y-flip is column display, not slice order |
| 7 | **NUMPY_TO_VTK** | `utils.convert_itk2vtk` (line 265) | arr.ravel(order='C') | `numpy_to_vtk`: C-order maps to VTK i+j*nx+k*nx*ny indexing. arr[z,y,x] → VTK(x,y,z). VTK k=0 = arr[0] = Inferior | False | False | False | False | Inferior (VTK k=0) | Superior (VTK k=N-1) | arr[0] = Inferior | arr[N-1] = Superior | I→S | positive-Z | No |
| 8 | **VTKSOURCEGEOMETRY** | `source_geometry.SourceGeometry.from_metadata` (line ~336) | metadata instances | **ascending `dot(IPP, slice_normal)`** = same as canonical_sort = Inferior first | False | False | True | False | Inferior | Superior | min dot-product | max dot-product | I→S | positive-Z | No |
| 9 | **VTK_DISPLAY_INDEX** | `ImageViewer2D.SetSlice(k)` = `vtkResliceImageViewer.SetSlice` | VTK k integer | VTK k directly indexes Z-dimension. k=0 = Inferior for HFS axial | False | False | False | False | Inferior (k=0) | Superior (k=N-1) | Inferior | Superior | **I→S NOT CANONICAL** | positive-Z | **YES — this is the output of the wrong sort direction** |
| 10 | **WHEEL_TRAVERSAL_VTK** | `_vw_scroll.wheelEvent` (line 1130) | `event.angleDelta().y()` | `step = -1 if delta > 0 else 1`; scroll-up = index-decreases | False | False | False | True | n/a | n/a | scroll-up = less inferior | scroll-down = more inferior | I→S when scrolling down **WRONG** | positive-Z | No |
| 11 | **SLIDER_TRAVERSAL_VTK** | Slider min=0, max=N-1 | User drag | Directly maps to VTK slice index | False | False | False | True | 0 = Inferior | N-1 = Superior | Inferior | Superior | I→S when dragging down **WRONG** | positive-Z | No |
| 12 | **DISPLAY_GEOMETRY_KFLIP** | `display_geometry.apply_k_flip_for_stack_order` | VTK k-index | Remaps k_display = (N-1) - k_raw; **effectively reverses to S→I** | False | False | False | True | Superior (after flip: k=0) | Inferior (k=N-1) | Superior | Inferior | S→I CANONICAL (when enabled) | negative-Z | YES — this is the correction layer |
| 13 | **SYNC_REFERENCE_VTK** | `GeometryAPI` via `effective_display_ijk_to_lps_4x4` | `DisplayGeometry` effective affine | All subsystems (markers, sync, MPR) receive corrected patient LPS via this contract | False | False | False | True | Superior (via corrected affine) | Inferior | — | — | S→I when K-flip active | negative-Z | No |

**Advanced Pipeline Verdict for Axial HFS CT:**
- **Without K-flip**: k_increasing = I→S. NOT canonical. Scroll-down moves from inferior to superior (backwards).
- **With K-flip (DisplayGeometry.apply_k_flip_for_stack_order)**: k_increasing = S→I. CANONICAL.
- The K-flip correction is already implemented; needs to be reliably activated via `audit_stack_order_convention`.

---

## Root Cause Summary

```
FAST Pipeline:
  canonical_sort_instances?  NO  (uses InstanceNumber)
  k=0 location:              Scanner-dependent (typically Superior for HFS CT)
  k_increasing direction:    S→I (canonical) IF scanner assigns InstanceNumber ascending S→I

Advanced/VTK Pipeline:
  canonical_sort_instances?  YES (uses ascending dot(IPP, normal))
  k=0 location:              INFERIOR for axial HFS (ascending Z = I→S)
  k_increasing direction:    I→S (NOT canonical)
  Correction mechanism:      DisplayGeometry.apply_k_flip_for_stack_order(N) reverses to S→I
```

## Critical Asymmetry

The FAST and Advanced pipelines have OPPOSITE default orderings for axial HFS CT:
- FAST: InstanceNumber (scanner-defined, typically S→I)  
- Advanced: IPP ascending (geometry-defined, always I→S for axial HFS)

This means they disagree on which slice is k=0. The DisplayGeometry K-flip corrects the Advanced path to match the canonical convention independently, without depending on the FAST pipeline.

## Wheel Scroll Convention (Both Paths)

```python
# _vw_scroll.py line 1005 (FAST) and line 1130 (VTK):
step = -1 if delta > 0 else 1
```

- `delta > 0` = physical scroll UP = step = -1 = index DECREASES
- `delta < 0` = physical scroll DOWN = step = +1 = index INCREASES

With canonical ordering (k=0 at Superior):
- Scroll DOWN → index increases → moves Inferiorly → radiologist scrolls "through" the body top-to-bottom ✓
- Scroll UP → index decreases → moves Superiorly ✓

This matches the clinical "scroll down = go toward feet" PACS convention.
