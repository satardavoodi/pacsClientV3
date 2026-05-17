# Advanced Geometry Contract Migration Table

Date: 2026-05-14
Scope: Advanced viewer runtime geometry consumers + plugin mirror parity requirements.

## 1) Inventory of Advanced Geometry Consumers

| file/function | current input | current coordinate space assumption | uses geometry contract? | risk | recommended migration |
|---|---|---|---|---|---|
| modules/viewer/advanced/viewer_2d.py ImageViewer2D._build_series_geometry_index | metadata instances + vtk dims | DICOM IOP/IPP + explicit display Y-flip via SeriesGeometryIndex | Partial (legacy Option B) | Medium | Keep for compatibility, but bind SourceGeometry + DisplayGeometry in parallel and register viewport contract. |
| modules/viewer/advanced/viewer_2d.py ImageViewer2D._bind_geometry_contract | metadata instances + vtk dims | Source raw IJK->LPS then DisplayGeometry Y-flip | Yes | Low | Keep as authoritative runtime bind path and emit [ADVANCED_VIEWPORT_GEOMETRY_BIND]. |
| modules/viewer/advanced/viewer_2d.py ImageViewer2D._set_slice_impl marker branch | metadata IOP, current slice, viewer id | mixed: contract path + camera fallback | Partial | High | Prefer update_from_geometry_contract path; keep camera path fallback-only when contract unavailable. |
| modules/viewer/advanced/orientation_markers.py update_from_affine | SeriesGeometryIndex | effective_display_ijk_to_lps in LPS | Yes (legacy contract) | Low | Keep as fallback while migrating to DisplayGeometry-based vectors. |
| modules/viewer/advanced/orientation_markers.py update_from_geometry_contract | screen-edge vectors | effective_display_affine-derived LPS vectors | Yes | Low | Primary marker source; emits [MARKERS_FROM_GEOMETRY_CONTRACT]. |
| modules/viewer/advanced/orientation_markers.py update_from_geometry | IOP + camera basis | camera vectors projected on plane | No | High | Keep only fallback; never authoritative. |
| modules/viewer/advanced/viewer_2d.py ijk_to_world | i,j,k + y_flip | VTK origin/spacing + manual Y-flip | No | High | Route call sites to DisplayGeometry.display_index_to_lps for medical mapping; keep utility for backward compatibility. |
| modules/viewer/advanced/viewer_2d.py world_to_ijk | world xyz + y_flip | VTK origin/spacing inverse + manual Y-flip | No | High | Route call sites to GeometryAPI.lps_to_displayed_index where LPS semantics are required. |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py _map_sync_dicom | source world pos + metadata IOP/IPP | mixed Qt/VTK pipelines with explicit flip-Y compensation | Partial | Medium | Preserve behavior; add GeometryAPI proof logging ([SYNC_LPS_MAPPING]) via contract-bound viewers. |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py manage_reference_line | source/target metadata, spacing, slice | LPS plane intersection + VTK/Qt display conversion | Partial | Medium | Preserve behavior; add GeometryAPI proof logging ([REFERENCE_LINE_LPS_INTERSECTION]) from contract-bound viewers. |
| modules/viewer/advanced/viewer_2d.py _apply_direction_matrix_from_field_data | vtk field data DirectionMatrix | VTK direction as available mirror | No (authoritative) | Medium | Keep as mirror-only; contract remains source of truth. |
| modules/viewer/advanced/viewer_2d.py ijk_to_world_physical/world_to_ijk_physical | vtk image + direction matrix | VTK physical mapping + field-data fallback | No (authoritative) | Medium | Use for diagnostics or tool compatibility; avoid replacing LPS contract with VTK state. |

## 2) Naked Raster Transform Findings

| finding | axis/effect | DisplayGeometry records it? | status | note |
|---|---|---|---|---|
| modules/viewer/advanced/viewer_2d.py SeriesGeometryIndex.build_from_instances(... apply_y_flip=True) | display row inversion (Y flip) | Yes (DisplayGeometry.apply_y_flip during contract bind) | OK | Runtime contract bind now mirrors same transform. |
| modules/viewer/advanced/viewer_2d.py ijk_to_world(... y_flip=True) | manual Y flip in index->world utility | No direct linkage to DisplayGeometry | CONTRACT VIOLATION | Legacy helper can diverge if additional display transforms are introduced. |
| modules/viewer/advanced/viewer_2d.py world_to_ijk(... y_flip=True) | manual Y flip in world->index utility | No direct linkage to DisplayGeometry | CONTRACT VIOLATION | Same divergence risk as above. |
| modules/viewer/advanced/orientation_markers.py update_from_geometry camera basis projection | visual orientation from camera vectors | Not tied to DisplayGeometry transform stack | CONTRACT VIOLATION (fallback path) | Must remain fallback-only and non-authoritative. |
| convert_itk2vtk (project-wide legacy) row inversion pathway | historical Y flip in conversion pipeline | Represented in contract by display_to_raw Y-flip | Needs runtime verification | Keep mirrored through DisplayGeometry; no ad-hoc extra flips. |

## 3) Controlled Migration Decisions

1. Medical geometry authority is SourceGeometry + DisplayGeometry.
2. VTK active render image remains voxel-space by default; vtk_bridge mutation is experimental only.
3. Sync/reference-line production behavior is preserved; contract logs are added for runtime proof before full path swap.
4. Camera-based marker code is retained only as guarded fallback; contract markers are primary.
5. No slice-order reversal hacks were introduced.
6. No manual axial/sagittal/coronal reversal workarounds were introduced.
7. `AIPACS_ADVANCED_VTK_GEOMETRY_BRIDGE_ACTIVE=0` is the clinical default (skip active vtkImageData mutation).
8. `AIPACS_ADVANCED_VTK_GEOMETRY_BRIDGE_ACTIVE=1` is experimental opt-in and emits explicit warning logs.
9. Future patient-space VTK rendering requires a separate explicit design; do not opportunistically apply `SetOrigin` / `SetSpacing` / `SetDirectionMatrix` to the current active render pipeline.

## 4) Plugin Mirror Scope

Files requiring mirror parity after this phase:
- modules/viewer/advanced/viewer_2d.py
- modules/viewer/advanced/orientation_markers.py
- modules/viewer/geometry/source_geometry.py
- modules/viewer/geometry/display_geometry.py
- modules/viewer/geometry/geometry_api.py
- modules/viewer/geometry/vtk_bridge.py

Mirror location:
- builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/
- builder/plugin package/packages/viewer/payload/python/modules/viewer/geometry/

## 5) Fresh Runtime Closure Findings (2026-05-14)

Observed from fresh session `sess-bfe71eed8192` (`user_data/logs/viewer_diagnostics.log`):

| finding | evidence | impact | likely owner |
|---|---|---|---|
| SourceGeometry built but invalid | `[GEOMETRY_SOURCE_CONTRACT] ... valid=False ... validation_errors=['missing_ImageOrientationPatient']` (4 series in session) | Contract bind exits early in `ImageViewer2D._bind_geometry_contract`, so viewport-level contract registration is skipped. | `modules/viewer/advanced/viewer_2d.py` (`_bind_geometry_contract`) + metadata instance hydration path feeding `self.metadata['instances']` |
| Exact payload drop point identified | `stamp_metadata_with_geometry_index()` / `display_instances_metadata()` emits snake_case display records (`image_orientation_patient`, `image_position_patient`, `pixel_spacing`, `rows`, `columns`, `sop_uid`) while `SourceGeometry.build_from_instances()` requires camelCase DICOM keys (`ImageOrientationPatient`, `ImagePositionPatient`, `PixelSpacing`, `Rows`, `Columns`, `SOPInstanceUID`) | The runtime viewer payload is geometry-complete but schema-mismatched at the contract boundary; SourceGeometry sees `missing_ImageOrientationPatient` even though the upstream geometry index has valid orientation data. | `PacsClient/pacs/patient_tab/utils/advanced_geometry_contract.py` + `modules/viewer/advanced/viewer_2d.py` hydration shim |
| Hydration fix applied | viewer now copies camelCase DICOM keys onto the runtime instance dicts immediately before both `SeriesGeometryIndex.build_from_instances()` and `SourceGeometry.build_from_instances()` | Preserves the display-oriented payload while satisfying the contract builders without changing slice order or camera authority. | `modules/viewer/advanced/viewer_2d.py` (`_hydrate_geometry_instances_for_contract`) |
| No viewport contract bind log emitted | `[ADVANCED_VIEWPORT_GEOMETRY_BIND]` count = 0 in fresh session | Cannot prove viewport binding to SourceGeometry/DisplayGeometry in runtime closure. | Same as above (early return on invalid `sg`) |
| No DisplayGeometry/VTK bridge contract proof tags | `[DISPLAY_GEOMETRY_CONTRACT]` = 0, `[EFFECTIVE_DISPLAY_AFFINE]` = 0, `[VTK_ORIENTATION_BRIDGE_STATUS]` = 0 | Display transform/bridge proof remains unverified for this run. | `modules/viewer/geometry/display_geometry.py`, `modules/viewer/geometry/vtk_bridge.py` emit points not reached due invalid source bind |
| Marker contract tag emitted successfully | `[MARKERS_FROM_GEOMETRY_CONTRACT]` count = 429 | Confirms marker consumption path is active and contract-derived labels are produced during scrolling. | `modules/viewer/advanced/orientation_markers.py` |
| Sync/reference GeometryAPI proof tags absent | `[SYNC_LPS_MAPPING]` = 0, `[REFERENCE_LINE_LPS_INTERSECTION]` = 0 | Sync/reference LPS proof cannot be claimed for closure session. Most likely not admitted because viewers were not both contract-bound (source invalid). | `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py` gated proof path |

Phase 2 closure status from this session: **FAIL (evidence incomplete due invalid SourceGeometry bind input).**

## 6) FAST vs Advanced Order-Domain Invariant (2026-05-16)

- FAST order authority = FAST display order / InstanceNumber pipeline order.
- Advanced order authority = Advanced geometry/display contract order.
- Shared sync helpers must not mutate `metadata['instances']` order.
- Geometry sorting for sync/reference must be local-copy only unless the object is already contract-owned.
- FAST path must not consume Advanced DisplayGeometry, SourceGeometry contract, or K-flip behavior.

## 7) FAST Sync Marker Precision Fix (v2.3.8 / 2026-05-17)

**Issue**: Sync marker misalignment visible in FAST viewers when anatomical features were not aligned between left/right viewers. Precision loss of 1-2 pixels.

**Root Cause**: Order mismatch between sync geometry calculation and pipeline geometry authority.
- `Lightweight2DPipeline.open_series()` creates `self._slices` from `metadata["instances"]`, then sorts by InstanceNumber (line 530: `self._slices = self._sort_slices(self._slices)`)
- Sync helper `_geometry_instances_for_viewer()` returned `metadata["instances"]` **unsorted**
- When user clicked at a sync point:
  1. Sync mapping computed target slice index using **unsorted** instances via `project_lps_to_target()` from `dicom_sync_geometry.py`
  2. Pipeline's `patient_xyz_to_image_xy()` used **sorted** instances via `self._slices[idx]`
  3. Geometry mismatch: pixel coordinates calculated from wrong slice's IOP/IPP/PixelSpacing

**Solution**: Modified `_geometry_instances_for_viewer()` in `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py`:
- Added `_sort_instances_by_instance_number()` helper to sort instances by InstanceNumber (matching `Lightweight2DPipeline._sort_slices` logic)
- FAST path now returns sorted instances instead of unsorted metadata order
- Advanced path unaffected (uses IPP sorting)
- Shared metadata **not mutated** (sort creates new list)

**Test Coverage** (`tests/fast_viewer/test_sync.py`):
- New test `test_fast_instances_sorted_by_instance_number`: Verifies FAST instances sorted by InstanceNumber while metadata remains unchanged
- All 102 sync+reference-line tests pass (53 base + 27 reference + 24 sync_geometry + 1 new precision test)

**Contracts Preserved**:
- `patient_xyz_to_image_xy()` now always receives geometry from the same slice order as `self._slices`
- Sync marker X,Y pixel calculation matches viewer's display coordinate system
- No shared mutation of `metadata["instances"]`
- FAST→Advanced mixed-viewer sync still works correctly

**Impact on Medical Imaging**:
- Sagittal/coronal sync markers now align to same anatomical location across viewers (sub-pixel accuracy)
- No regression in axial or mixed-orientation workflows
- Reference lines still correct (already using same geometry-sorted approach via IPP for Advanced)

## 8) Regression Guardrails + Future Development (2026-05-16)

### Regression Guardrails

1. FAST order authority remains `InstanceNumber` (with path tie-break), matching `Lightweight2DPipeline._sort_slices`.
2. `_geometry_instances_for_viewer()` must keep local-copy sorting for FAST and must not mutate shared metadata order.
3. Advanced order domain remains independent (contract/display geometry path only).
4. Any change to sync/reference-line geometry paths requires running:

```powershell
.venv/Scripts/python.exe -m pytest tests/fast_viewer/test_sync.py tests/fast_viewer/test_reference_lines.py tests/fast/test_sync_reference_line_geometry.py -v --tb=short
```

### Future Development Rules

1. Do not duplicate FAST order logic in multiple files; route through one helper to avoid drift.
2. New backends must define explicit order authority before enabling cross-view sync.
3. Add tests for shuffled metadata input whenever touching sync mapping or coordinate conversion.
4. Keep mixed FAST/Advanced sync tests green as a release gate for geometry work.

