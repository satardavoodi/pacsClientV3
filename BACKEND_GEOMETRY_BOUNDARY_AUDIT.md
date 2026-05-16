# Backend Geometry Boundary Audit

Date: 2026-05-16
Scope: Whole-application audit of geometry and order boundaries between Advanced and FAST rendering engines.
Status: Audit only. No runtime behavior changes were applied in this pass.

## Core Boundary Rule

1. Any path that uses VTK, SimpleITK, vtkImageData, vtkImageReslice, MPR, curved MPR, volume rendering, MIP, or ITK-based image loading must use the Advanced geometry contract, or have an explicit migration task:
   - SourceGeometry
   - DisplayGeometry
   - GeometryAPI
   - explicit IJK <-> LPS mapping
   - explicit display_k <-> raw_k mapping where stack display is involved
   - no geometry-sensitive reliance on filename, InstanceNumber, or DB order alone

2. Any FAST path that uses pydicom, NumPy, OpenCV, QPainter, or Qt 2D rendering must remain FAST-native:
   - FAST display order
   - FAST metadata order
   - FAST sync/reference flow
   - no Advanced DisplayGeometry / SourceGeometry / K-flip leakage
   - no mutation of FAST metadata into Advanced/IPP order

3. FAST and Advanced remain separate rendering engines with separate index/order contracts.

## Contract Legend

- Advanced contract: SourceGeometry + DisplayGeometry + GeometryAPI + LPS-based cross-view mapping.
- FAST native: SliceMeta / SliceGeometry + FAST display order + pure-DICOM LPS math.
- Partial / local affine: explicit geometry math exists, but it is not the shared Advanced contract.
- Violation: current path is geometry-sensitive and does not use the required contract for its backend.
- Migration task: not immediately unsafe in all cases, but should be moved behind the required contract boundary.

## A. VTK / SimpleITK / MPR / 3D Audit

| file/function | feature | backend type | uses VTK/SimpleITK? | uses PyDicom/OpenCV/FAST? | required geometry contract | current contract | violation? | proposed fix |
|---|---|---:|---:|---:|---|---|---|---|
| modules/viewer/advanced/viewer_2d.py::ImageViewer2D._bind_geometry_contract | Advanced 2D viewer geometry bind | Advanced | Yes | No | Advanced contract | SourceGeometry + DisplayGeometry + GeometryAPI registry + optional vtk bridge | No | Keep authoritative. Add explicit missing-contract guard emit when bind exits early. |
| modules/viewer/advanced/viewer_2d.py::ImageViewer2D.get_count_of_slices / display_k->raw_k path | Advanced stack index mapping | Advanced | Yes | No | Advanced contract with explicit display_k <-> raw_k | Uses DisplayGeometry K-flip / raw_k mapping | No | Keep as model for all VTK stack views. |
| modules/viewer/advanced/viewer_2d.py::ImageViewer2D._hydrate_geometry_instances_for_contract | Advanced metadata schema hydration | Advanced | Yes | No | Advanced contract input normalization | Local hydration into camelCase DICOM keys | Partial | Keep, but emit missing-contract guard if hydration still leaves SourceGeometry invalid. |
| modules/viewer/geometry/geometry_api.py::GeometryAPI.map_lps_between_viewports | Cross-view mapping | Advanced shared | Yes | No | Advanced contract via LPS | Full LPS-space GeometryAPI | No | Keep as authoritative mapping layer for VTK/SITK views. |
| modules/viewer/geometry/geometry_api.py::GeometryAPI.reference_line_in_viewport | Advanced reference-line computation | Advanced shared | Yes | No | Advanced contract via LPS | Full LPS-space GeometryAPI | No | Keep. Prefer VTK reference-line consumers to route here. |
| modules/viewer/geometry/vtk_bridge.py::apply_source_geometry_to_vtk | Optional VTK orientation bridge | Advanced | Yes | No | Advanced contract | SourceGeometry/DisplayGeometry to vtkImageData bridge | No | Keep experimental; only contract-bound use. |
| modules/viewer/advanced/orientation_markers.py::update_from_geometry_contract | Orientation markers | Advanced | Yes | No | Advanced contract | DisplayGeometry-derived screen-edge vectors | No | Keep primary. |
| modules/viewer/advanced/orientation_markers.py::update_from_geometry | Orientation markers fallback | Advanced | Yes | No | Advanced contract | Camera/vector fallback outside shared contract | Yes (fallback-only tolerated) | Keep fallback-only. Block authoritative use when contract exists. |
| modules/viewer/advanced/viewer_3d.py::Viewer3DWidget.setup_volume_renderer | 3D volume rendering | Advanced | Yes | No | Advanced contract or explicit Advanced geometry handoff | Direct vtkGPUVolumeRayCastMapper over vtkImageData, no explicit SourceGeometry / DisplayGeometry use observed | Migration task | Bind 3D volume paths to Advanced geometry contract metadata or document them as render-only, not geometry-authoritative. Emit missing-contract guard if used for cross-view mapping later. |
| PacsClient/pacs/patient_tab/utils/image_io.py::get_itk_image | SimpleITK series load | Advanced load path | Yes | FAST can bypass | Advanced contract input preparation | SITK load + dominant-size fallback; no SourceGeometry bind here | Migration task | Keep loading, but require downstream bind validation for VTK/SITK consumers. Emit missing-contract guard at first VTK consumer if bind absent. |
| PacsClient/pacs/patient_tab/utils/utils.py::convert_itk2vtk | ITK -> VTK conversion | Advanced / MPR support | Yes | No | Advanced contract-compatible affine handoff | Local direction/origin/spacing handling + field-data DirectionMatrix | Migration task | Centralize under Advanced contract bridge or formalize as Advanced-only preprocessing stage with explicit LPS/IJK proof log. |
| PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_scroll.py::_reenable_gc_impl and scroll path | Advanced VTK scroll / stack interaction | Advanced | Yes | FAST throttle utilities only for latch | Advanced contract for any geometry-sensitive mapping | VTK viewer path; geometry ownership remains in ImageViewer2D | No direct boundary violation | Keep. Do not introduce FAST order assumptions into VTK scroll. |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py::manage_reference_line (Advanced branch) | Shared reference line used by VTK views | Shared, backend-branching | Yes | Yes | Advanced contract or local Advanced geometry sort copy | Uses backend detection; Advanced returns contract-owned instances or local IPP-sorted copy | Partial | Prefer Advanced GeometryAPI for contract-bound VTK views. Keep branch isolation. |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py::_map_sync_dicom (Advanced target/source path) | Shared sync path for VTK views | Shared, backend-branching | Yes | Yes | Advanced contract via LPS | Mixed backend branch model; not purely GeometryAPI-driven end-to-end | Migration task | Move Advanced-to-Advanced mapping fully behind GeometryAPI when both viewports are contract-bound. |
| modules/mpr/orthogonal/core/volume_loader.py::VolumeLoader.load_dicom_series/load_mhd/load_nifti | Orthogonal MPR volume loading | MPR / VTK / SITK | Yes | No | Advanced contract | SimpleITK + local CoordinateSystem object | Yes | Migrate to SourceGeometry / DisplayGeometry or formal adapter from local CoordinateSystem to Advanced contract. Emit [GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] until migrated. |
| modules/mpr/orthogonal/core/coordinate_systems.py::CoordinateSystem.index_to_world/world_to_index | Orthogonal MPR coordinate math | MPR | Yes | No | Advanced contract or explicit adapter to it | Local affine LPS/RAS system | Yes | Replace local ownership with Advanced contract adapter or mark as temporary shim. |
| modules/mpr/orthogonal/core/resampler.py / mpr_calculator.py (by module role) | Orthogonal reslice math | MPR | Yes | No | Advanced contract | Local orthogonal MPR stack | Likely yes | Route reslice inputs through SourceGeometry-derived affine. |
| modules/mpr/zeta_mpr/mpr_viewer/widget.py::StandardMPRViewer.__init__ | Zeta MPR viewer state | MPR | Yes | No | Advanced contract | Current state uses origin/spacing/center/current_position directly | Yes | Introduce Advanced geometry adapter for current_position, focal point, and plane ownership. |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py::_create_axial_view/_create_sagittal_view/_create_coronal_view | Zeta MPR orthogonal view creation | MPR | Yes | No | Advanced contract | vtkImageResliceMapper + camera vectors + direct image_data | Yes | Replace direct orientation assumptions with contract-derived row/column/normal vectors. |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_crosshair_interact.py::CrosshairInteractorStyle._move_along_stack and click handlers | Zeta MPR rotate/flip/scroll/crosshair updates | MPR | Yes | No | Advanced contract + explicit LPS mapping | Mutates current_position in world coordinates derived from spacing/origin/focal point | Yes | Move crosshair center and scroll direction to contract-owned LPS/display index APIs. |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_crosshair_render.py | Zeta MPR slice numbering / text overlays | MPR | Yes | No | Advanced contract display_k/raw_k | Computes slice number from current_position and origin/spacing | Yes | Derive slice labels from contract mapping instead of raw axis arithmetic. |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_oblique.py | Oblique MPR plane updates | MPR | Yes | No | Advanced contract + LPS plane definitions | Camera-driven / current_position-based oblique logic | Yes | Migrate oblique plane computation to SourceGeometry / GeometryAPI-compatible LPS plane math. |
| modules/mpr/zeta_mpr/advanced_rendering.py::create_thick_slab_mpr / ThickSlabController | Thick slab / MIP / MinIP rendering | MPR / 3D-like | Yes | No | Advanced contract | Direct SetResliceAxesDirectionCosines using hard-coded orientation axes | Yes | Replace hard-coded orientation cosines with contract-derived anatomical axes. |
| modules/mpr/curved_mpr/curved_mpr_module.py::CurvedMPRGenerator.generate_orthogonal_slice | Curved MPR | Curved MPR | Yes | No | Advanced contract + explicit LPS / IJK mapping | Direct vtkImageReslice over vtkImageData with local tangent/normal/binormal math | Yes | Wrap curved-MPR slice extraction around SourceGeometry / GeometryAPI-derived transforms. Emit missing-contract guard. |
| modules/mpr/zeta_mpr/CurveMPR/curve_mpr_core.py::vtk_to_patient_space / generate_orthogonal_slice | Legacy curved MPR core | Curved MPR | Yes | No | Advanced contract | Reads DirectionMatrix field data and applies local patient transform | Yes | Replace local DirectionMatrix ownership with SourceGeometry-derived transform adapter. |
| modules/mpr/zeta_mpr/curved_mpr.py::* vtkImageReslice call sites | Legacy curved MPR pipeline | Curved MPR | Yes | No | Advanced contract | Direct vtkImageReslice axes/origin setup | Yes | Migrate or isolate as legacy-only behind explicit clinical-risk warning. |

## B. FAST Audit

| file/function | feature | backend type | uses VTK/SimpleITK? | uses PyDicom/OpenCV/FAST? | required geometry contract | current contract | violation? | proposed fix |
|---|---|---:|---:|---:|---|---|---|---|
| modules/viewer/fast/lightweight_2d_pipeline.py::Lightweight2DPipeline | FAST render pipeline | FAST | No | Yes | FAST-native | SliceMeta/SliceGeometry + InstanceNumber/path order + pure-DICOM geometry | No | Keep authoritative FAST order owner. |
| modules/viewer/fast/lightweight_2d_pipeline.py::_sort_slices | FAST display order authority | FAST | No | Yes | FAST-native | InstanceNumber + path tie-break; explicitly rejects IPP sort | No | Keep unchanged. Treat as load-bearing invariant. |
| modules/viewer/fast/lightweight_2d_pipeline.py::patient_xyz_to_image_xy / image_xy_to_patient_xyz | FAST pixel/LPS transforms | FAST | No | Yes | FAST-native | Pure-DICOM IOP/IPP/PixelSpacing | No | Keep as canonical FAST geometry conversion. |
| modules/viewer/fast/dicom_sync_geometry.py::* | FAST sync/reference geometry math | FAST | No | Yes | FAST-native | Pure LPS math, no VTK, no DisplayGeometry, no K-flip | No | Keep isolated. |
| modules/viewer/fast/qt_viewer_bridge.py::QtViewerBridge | FAST viewer adapter | FAST | No direct VTK rendering | Yes | FAST-native | Bridge to QtSliceViewer + Lightweight2DPipeline | No | Keep isolated. Add leak-block guard if Advanced contract objects ever appear on bridge. |
| modules/viewer/fast/qt_slice_viewer.py | FAST 2D Qt rendering | FAST | No | Yes | FAST-native | QPainter / Qt display only | No | Keep isolated. |
| modules/viewer/fast/pydicom_2d_backend.py::patient_xyz_to_image_xy and geometry methods | FAST backend geometry | FAST | No | Yes | FAST-native | Pure-DICOM geometry matching sync engine | No | Keep paired with dicom_sync_geometry invariants. |
| PacsClient/pacs/patient_tab/utils/opencv_filter_pipeline.py::apply_pooyan_opencv_to_volume_int16 | FAST/volume filter utility | Mixed utility | SimpleITK wrapper exists | Yes | FAST-native for FAST path; Advanced contract for SITK/VTK path | Volume filter preserves dimensions, but not contract-aware | Partial | Keep FAST 2D path isolated. For SITK/volume use, treat as Advanced-adjacent preprocessing only. |
| modules/viewer/fast/pydicom_lazy_volume.py | FAST progressive loading | FAST | VTK stub only as data carrier | Yes | FAST-native | Lazy volume over pydicom data; not DisplayGeometry-based | No boundary violation | Keep. Do not upgrade to Advanced contract implicitly. |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py::_geometry_instances_for_viewer (FAST branch) | FAST sync/reference order handoff | Shared, backend-branching | No | Yes | FAST-native | Local-copy InstanceNumber sorting matching Lightweight2DPipeline._sort_slices | No | Keep as required isolation point. |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py::manage_reference_line (FAST branch) | FAST reference line entry | Shared, backend-branching | No | Yes | FAST-native | Uses backend-aware geometry instances; no metadata mutation | No | Keep backend branch. |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py::_map_sync_dicom (FAST branch) | FAST sync target mapping | Shared, backend-branching | No | Yes | FAST-native | Uses pure-DICOM LPS projection and FAST display order | No | Keep. |
| PacsClient/pacs/patient_tab/ui/patient_ui/_slice_tick_slider.py and FAST interaction wiring | FAST slider / scroll path | FAST | No | Yes | FAST-native | Index path goes through Qt bridge / lightweight pipeline | No clear violation from audited owners | Keep isolated. Add leak-block guard in bridge if Advanced contract object injected. |
| PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py and FAST embed path | FAST embedded in VTK shell | Hybrid host, FAST engine | Host shell only | Yes | FAST-native | FAST engine kept separate behind bridge | No | Keep as host/container only; do not share Advanced geometry objects into FAST child. |

## C. Shared Helpers Classification

### 1. Safe shared pure DICOM helpers

| helper | file | reason |
|---|---|---|
| lps_to_image_pixel / image_pixel_to_lps | modules/viewer/fast/dicom_sync_geometry.py | Pure LPS + IOP/IPP/PixelSpacing math; no backend mutation |
| compute_slice_normal / compute_slice_positions / find_closest_slice_physical | modules/viewer/fast/dicom_sync_geometry.py | Pure DICOM slice-plane math |

### 2. FAST-only

| helper | file | reason |
|---|---|---|
| Lightweight2DPipeline._sort_slices | modules/viewer/fast/lightweight_2d_pipeline.py | FAST order authority |
| Lightweight2DPipeline.patient_xyz_to_image_xy | modules/viewer/fast/lightweight_2d_pipeline.py | FAST pixel geometry |
| QtViewerBridge / QtSliceViewer coordination | modules/viewer/fast/qt_viewer_bridge.py | FAST rendering adapter |

### 3. Advanced-only

| helper | file | reason |
|---|---|---|
| ImageViewer2D._bind_geometry_contract | modules/viewer/advanced/viewer_2d.py | Builds SourceGeometry + DisplayGeometry |
| GeometryAPI.* | modules/viewer/geometry/geometry_api.py | Shared Advanced contract API for LPS mapping |
| apply_source_geometry_to_vtk | modules/viewer/geometry/vtk_bridge.py | Advanced VTK bridge only |
| DicomOrientationMarkers.update_from_geometry_contract | modules/viewer/advanced/orientation_markers.py | Advanced marker geometry |

### 4. Must branch by backend

| helper | file | reason |
|---|---|---|
| _geometry_instances_for_viewer | PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py | Must preserve FAST order and Advanced contract/order separately |
| manage_reference_line | PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py | Shared entry, but geometry/order semantics differ by backend |
| _map_sync_dicom | PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py | Shared sync entry, backend-specific geometry engine |

### 5. Must be split into separate implementations or adapters

| helper/path | file | reason |
|---|---|---|
| Zeta MPR current_position/origin/spacing stack math | modules/mpr/zeta_mpr/mpr_viewer/* | Geometry-sensitive VTK/MPR logic does not use Advanced contract |
| Orthogonal MPR CoordinateSystem / VolumeLoader | modules/mpr/orthogonal/core/* | Owns a parallel geometry contract; should adapt to Advanced contract |
| Curved MPR patient transform logic | modules/mpr/curved_mpr/* and modules/mpr/zeta_mpr/CurveMPR/* | Owns local vtkImageReslice + DirectionMatrix geometry instead of Advanced contract |

## Violations and Migration Tasks

### Proven or high-confidence violations

1. modules/mpr/zeta_mpr/mpr_viewer/*
- Uses VTK image slicing, camera-driven reslice mappers, crosshair motion, and oblique updates.
- Current geometry ownership is origin/spacing/current_position/focal-point based.
- Required boundary: Advanced geometry contract.
- Risk: crosshair drift, flip ambiguity, camera-sign regressions, oblique plane mismatch.

2. modules/mpr/curved_mpr/* and modules/mpr/zeta_mpr/CurveMPR/*
- Uses vtkImageReslice and local direction-matrix math.
- Current geometry ownership is local Frenet/parallel-transport frame plus VTK field data.
- Required boundary: Advanced geometry contract.
- Risk: slice extraction plane mismatch, patient-space conversion drift, direction-matrix divergence.

3. modules/mpr/orthogonal/core/*
- Uses SimpleITK and a local CoordinateSystem abstraction.
- Current geometry ownership is explicit affine math, but not the shared Advanced contract.
- Required boundary: Advanced geometry contract or formal adapter.
- Risk: long-term drift from the main Advanced viewer, duplicated geometry policy.

4. modules/mpr/zeta_mpr/advanced_rendering.py
- Uses hard-coded SetResliceAxesDirectionCosines for slab orientation.
- Required boundary: Advanced contract-derived anatomical axes.
- Risk: wrong slab orientation on non-canonical direction matrices.

### Partial / migration-needed paths

1. PacsClient/pacs/patient_tab/utils/utils.py::convert_itk2vtk
- Good explicit affine handling, but still separate from the central Advanced contract.

2. PacsClient/pacs/patient_tab/utils/image_io.py::get_itk_image
- Safe as a loader, but contract proof starts too late unless downstream bind is verified.

3. modules/viewer/advanced/viewer_3d.py
- Uses Advanced VTK volume rendering but no explicit shared geometry contract was observed.
- Low immediate risk if render-only, but must not become geometry-authoritative without contract adoption.

## Proposed Guard Emits

### 1. [GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH]
Emit when a VTK / SimpleITK / MPR path starts geometry-sensitive work without an Advanced geometry contract.

Recommended insertion points:
- modules/viewer/advanced/viewer_2d.py::ImageViewer2D._bind_geometry_contract
  - on early return when SourceGeometry is invalid
- modules/mpr/zeta_mpr/mpr_viewer/widget.py::__init__ or first geometry-sensitive view setup
- modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py::_create_*_view
- modules/mpr/zeta_mpr/mpr_viewer/_mpr_crosshair_interact.py::CrosshairInteractorStyle._move_along_stack
- modules/mpr/zeta_mpr/mpr_viewer/_mpr_oblique.py::* oblique update entry points
- modules/mpr/curved_mpr/curved_mpr_module.py::CurvedMPRGenerator.generate_orthogonal_slice
- modules/mpr/zeta_mpr/CurveMPR/curve_mpr_core.py::generate_orthogonal_slice
- modules/mpr/orthogonal/core/volume_loader.py::load_dicom_series and downstream resampler entry points

Suggested payload:
- file/function
- feature
- series_uid if present
- viewport_id if present
- reason
- fallback_behavior

### 2. [FAST_ADVANCED_GEOMETRY_LEAK_BLOCKED]
Emit when FAST receives Advanced contract objects or K-flip/display-order semantics.

Recommended insertion points:
- PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py::_geometry_instances_for_viewer
  - if FAST branch sees _display_geometry_contract / _source_geometry_contract being used as authority
- modules/viewer/fast/qt_viewer_bridge.py::__init__ and sync entry points
- modules/viewer/fast/lightweight_2d_pipeline.py::open_series / geometry load entry points
- FAST reference-line callbacks if Advanced display-order metadata is detected

Suggested payload:
- caller
- leaked_object_type
- backend
- blocked_reason
- metadata_order_contract if present

### 3. [SHARED_METADATA_ORDER_MUTATION_BLOCKED]
Emit when shared metadata order is about to be changed globally.

Recommended insertion points:
- PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py::_geometry_instances_for_viewer
  - existing mutation-blocked log is already close to this role
- any helper that sorts or reverses metadata['instances'] in-place
- progressive metadata refresh helpers if reordering is attempted

Suggested payload:
- caller
- backend
- original_hash
- attempted_hash
- attempted_operation

## Minimal Migration Plan Ordered by Clinical Risk

### P0 - Immediate / highest clinical risk

1. Zeta MPR crosshair / oblique / slice-position pipeline
- Create an adapter from Advanced geometry contract into Zeta MPR state.
- Stop using origin/spacing/current_position as the sole geometry authority.
- All cross-view mapping and oblique plane definitions should use LPS through the Advanced contract.

2. Curved MPR vtkImageReslice paths
- Require SourceGeometry / DisplayGeometry or a formal adapter before any patient-space slice extraction.
- Remove local direction-matrix ownership as the primary patient-space authority.

3. Guard rollout for missing Advanced contract on VTK/MPR paths
- Add [GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] first, before any larger refactor.

### P1 - High risk, lower immediacy

4. Replace hard-coded reslice axes in thick-slab / MIP paths
- Use contract-derived row/column/normal vectors.

5. Bring orthogonal MPR local CoordinateSystem behind an adapter
- Keep local class only as a thin wrapper around the Advanced contract or remove it.

6. Ensure Advanced-to-Advanced sync/reference-line paths prefer GeometryAPI directly when both viewports are contract-bound.

### P2 - Hardening / maintenance

7. Add FAST leak-block guards in Qt bridge and sync entry points.
8. Add shared metadata mutation assertions in progressive and sync/reference helpers.
9. Decide whether Viewer3D remains render-only or becomes contract-bound for future geometry-sensitive features.

## FAST Isolation Assessment

FAST isolation is currently good in the audited owners:
- no observed SourceGeometry / DisplayGeometry / GeometryAPI imports inside FAST core modules
- pure-DICOM LPS math remains isolated in modules/viewer/fast/dicom_sync_geometry.py
- _pw_sync.py now preserves FAST order with a local-copy sort and blocks shared metadata mutation
- no evidence that FAST metadata is being globally rewritten into IPP order from the audited sync/reference owners

Residual FAST risks:
- future bridge code may accidentally pass Advanced contract state into FAST containers
- shared helpers outside the audited owners could still mutate metadata order if changed later

## Recommended Release Gate for Geometry Work

Run this whenever changing sync, reference-line, FAST order logic, or geometry boundaries:

```powershell
.venv/Scripts/python.exe -m pytest tests/fast_viewer/test_sync.py tests/fast_viewer/test_reference_lines.py tests/fast/test_sync_reference_line_geometry.py -v --tb=short
```

Additional gate required for Advanced/MPR refactors:
- any targeted MPR/oblique/curved-MPR test suite available for the touched module
- manual check: crosshair center, oblique plane, and slice position remain anatomically stable

## Audit Summary

- Advanced viewer core is already aligned to the required contract.
- FAST core is already aligned to its required native semantics.
- The main boundary risk is not FAST vs Advanced viewer core; it is the parallel MPR stacks that still own their own geometry contracts.
- Shared sync/reference helpers are mostly safe now because they branch by backend and avoid metadata mutation, but Advanced-side shared paths should increasingly prefer GeometryAPI when both viewports are contract-bound.
- No broad behavior changes are recommended without a proven violation and a surgical fix. The first safe step is adding the three guard emits above.
