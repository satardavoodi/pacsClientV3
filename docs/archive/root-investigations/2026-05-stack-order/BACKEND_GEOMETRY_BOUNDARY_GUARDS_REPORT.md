# Backend Geometry Boundary Guards Report

Date: 2026-05-16
Mode: Guard-only enforcement (no broad behavior migration)
Official baseline: BACKEND_GEOMETRY_BOUNDARY_AUDIT.md

## Summary

This pass implements runtime visibility guards for boundary violations before migration work:

- Added `[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH]` emits on audited VTK/SimpleITK/MPR geometry-sensitive entry points.
- Added `[FAST_ADVANCED_GEOMETRY_LEAK_BLOCKED]` emits on FAST/shared paths that must remain isolated from Advanced contract objects.
- Added `[SHARED_METADATA_ORDER_MUTATION_BLOCKED]` emit in shared sync/reference helper for metadata order mutation attempts.
- Preserved runtime behavior, except mutation remains blocked by returning local sorted copies (existing safe behavior), now explicitly tagged with `action=blocked_mutation`.

## Files Modified

### Core/shared
- PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py

### Advanced viewer
- modules/viewer/advanced/viewer_2d.py

### FAST viewer
- modules/viewer/fast/qt_viewer_bridge.py
- modules/viewer/fast/lightweight_2d_pipeline.py

### MPR / SITK paths
- modules/mpr/zeta_mpr/advanced_rendering.py
- modules/mpr/zeta_mpr/mpr_viewer/widget.py
- modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py
- modules/mpr/zeta_mpr/mpr_viewer/_mpr_crosshair_interact.py
- modules/mpr/zeta_mpr/mpr_viewer/_mpr_oblique.py
- modules/mpr/curved_mpr/curved_mpr_module.py
- modules/mpr/zeta_mpr/CurveMPR/curve_mpr_core.py
- modules/mpr/orthogonal/core/volume_loader.py
- modules/mpr/orthogonal/core/resampler.py

### Viewer plugin parity (required)
- builder/plugin package/packages/viewer/payload/python/modules/viewer/advanced/viewer_2d.py
- builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/qt_viewer_bridge.py
- builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/lightweight_2d_pipeline.py

### Test added
- tests/architecture/test_backend_geometry_boundary_guards.py

## Guard Insertion Points Implemented

### `[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH]`
- modules/viewer/advanced/viewer_2d.py
  - ImageViewer2D._bind_geometry_contract
  - emits on invalid SourceGeometry and bind exception (`action=warn_only`)
- modules/mpr/zeta_mpr/mpr_viewer/widget.py
  - StandardMPRViewer.__init__ (`action=warn_only`)
- modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py
  - _create_axial_view / _create_sagittal_view / _create_coronal_view (`action=warn_only`)
- modules/mpr/zeta_mpr/mpr_viewer/_mpr_crosshair_interact.py
  - CrosshairInteractorStyle._move_along_stack (`action=warn_only`)
- modules/mpr/zeta_mpr/mpr_viewer/_mpr_oblique.py
  - _update_oblique_reslicing (`action=warn_only`)
- modules/mpr/curved_mpr/curved_mpr_module.py
  - CurvedMPRGenerator.generate (`action=warn_only`)
- modules/mpr/zeta_mpr/CurveMPR/curve_mpr_core.py
  - CurveMPRCore.generate_orthogonal_slice (`action=warn_only`)
- modules/mpr/orthogonal/core/volume_loader.py
  - load_dicom_series / load_mhd / load_nifti (`action=warn_only`)
- modules/mpr/orthogonal/core/resampler.py
  - MPRResampler.__init__ / get_slice (`action=warn_only`)
- modules/mpr/zeta_mpr/advanced_rendering.py
  - AdvancedVolumeRenderer.create_thick_slab_mpr (`action=warn_only`)

### `[FAST_ADVANCED_GEOMETRY_LEAK_BLOCKED]`
- PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py
  - _geometry_instances_for_viewer FAST branch
  - checks for DisplayGeometry/SourceGeometry/GeometryAPI/registry leakage (`action=warn_only`)
- modules/viewer/fast/qt_viewer_bridge.py
  - QtViewerBridge.__init__
  - _on_stack_drag_target
  - _on_qt_scroll
  - warns if Advanced contract objects/order contract leak into FAST bridge (`action=warn_only`)
- modules/viewer/fast/lightweight_2d_pipeline.py
  - open_series
  - warns if metadata carries Advanced contract objects/K-flip semantics (`action=warn_only`)

### `[SHARED_METADATA_ORDER_MUTATION_BLOCKED]`
- PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py
  - _geometry_instances_for_viewer (Advanced no-contract fallback sort copy)
  - emits explicit blocked mutation tag when order differs (`action=blocked_mutation`)
  - legacy tag `[SYNC_METADATA_ORDER_MUTATION_BLOCKED]` retained for compatibility.

## Sample Log Payloads

### 1) Geometry contract missing (warn-only)
```text
[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] feature=zeta_mpr_oblique_update reason=local_oblique_plane_update_without_advanced_contract_adapter fallback_behavior=continue_legacy_mpr_oblique_path action=warn_only
```

### 2) FAST receives Advanced contract leakage (warn-only)
```text
[FAST_ADVANCED_GEOMETRY_LEAK_BLOCKED] source=Lightweight2DPipeline.open_series leaked_object_type=DisplayGeometry|K_FLIP backend=FAST blocked_reason=fast_pipeline_must_not_consume_advanced_geometry_contract action=warn_only
```

### 3) Shared metadata mutation blocked
```text
[SHARED_METADATA_ORDER_MUTATION_BLOCKED] backend=ADVANCED caller=_PWSyncMixin._geometry_instances_for_viewer original_hash=<h1> attempted_hash=<h2> attempted_operation=rl_sort_instances_by_ipp reason=shared_metadata_order_must_not_be_mutated action=blocked_mutation
```

## Tests Added

### New architecture/lint-style test
- tests/architecture/test_backend_geometry_boundary_guards.py

Checks:
1. Mandatory VTK/SITK/MPR geometry-sensitive files are either contract-bound or guard-tagged.
2. FAST modules do not import Advanced geometry contract symbols.
3. Shared sync path does not perform forbidden `metadata["instances"]` mutation assignments.

### Validation run
```text
.venv\Scripts\python.exe -m pytest tests/architecture/test_backend_geometry_boundary_guards.py tests/fast_viewer/test_sync.py -q
57 passed, 3 warnings
```

## Current Violations Detected

### Runtime-visible (by design in this phase)
- Legacy MPR/SITK geometry ownership in:
  - modules/mpr/zeta_mpr/advanced_rendering.py
  - modules/mpr/zeta_mpr/mpr_viewer/*
  - modules/mpr/curved_mpr/*
  - modules/mpr/zeta_mpr/CurveMPR/*
  - modules/mpr/orthogonal/core/*
- Status in this pass: `warn_only`

### Mutation safety
- Shared metadata order mutation attempts are explicitly tagged and prevented from mutating shared metadata.
- Status in this pass: `blocked_mutation`

### Static architecture gate status
- No new FAST contract-import violations detected by the new lint test.
- Mandatory guard/contract checks passed.

## Prepared P0 Migration Plan (Not Implemented)

The following P0 plan is prepared for next phase only. No behavior migration is implemented in this pass.

### A) modules/mpr/zeta_mpr/mpr_viewer/*
- Input geometry source:
  - SourceGeometry built from canonical instances + explicit IJK/LPS affine.
- Output viewport/display geometry:
  - DisplayGeometry per viewport with explicit display_k <-> raw_k mapping.
- MPR plane defined in LPS:
  - Plane origin = crosshair center in LPS.
  - Plane normal = contract-derived view normal in LPS.
  - In-plane axes = contract-derived row/column edge vectors.
- Reslice axes build:
  - vtkImageReslice axes matrix from contract row/column/normal vectors and LPS origin.
- Crosshair/reference/sync in LPS:
  - Move/rotate crosshair by GeometryAPI LPS plane and mapping APIs.
- Old assumptions to remove:
  - direct origin/spacing/current_position ownership,
  - camera-sign inference for plane definition,
  - implicit axis-based slice numbering.

### B) modules/mpr/curved_mpr/*
- Input geometry source:
  - SourceGeometry + contract-normalized path points in LPS.
- Output viewport/display geometry:
  - Explicit curved-CPR display geometry object or adapter carrying arc-length index mapping.
- MPR plane defined in LPS:
  - Frenet/parallel-transport frames anchored in contract LPS space.
- Reslice axes build:
  - Axes columns from frame N/B/T vectors in LPS, translation from contract LPS origin.
- Crosshair/reference/sync in LPS:
  - Curved path index <-> LPS mapping exposed to sync/reference APIs.
- Old assumptions to remove:
  - DirectionMatrix as sole patient transform authority,
  - local frame ownership disconnected from SourceGeometry.

### C) modules/mpr/zeta_mpr/CurveMPR/*
- Input geometry source:
  - SourceGeometry adapter around existing curve core.
- Output viewport/display geometry:
  - DisplayGeometry-compatible adapter for orthogonal slice views.
- MPR plane defined in LPS:
  - Plane origin and normal from contract + curve tangent frame.
- Reslice axes build:
  - vtkImageReslice axes from contract-aligned frame vectors.
- Crosshair/reference/sync in LPS:
  - Use GeometryAPI mapping functions for cross-view interactions.
- Old assumptions to remove:
  - direct DirectionMatrix transform ownership,
  - ad hoc index/world conversions.

### D) modules/mpr/orthogonal/core/*
- Input geometry source:
  - SourceGeometry from SITK image metadata.
- Output viewport/display geometry:
  - DisplayGeometry adapter replacing/bridging local CoordinateSystem.
- MPR plane defined in LPS:
  - Orthogonal planes (axial/sagittal/coronal) from contract-aligned normals.
- Reslice axes build:
  - SITK/VTK resampler transforms derived from contract affines.
- Crosshair/reference/sync in LPS:
  - LPS-first mapping via GeometryAPI bridge, then plane-local indices.
- Old assumptions to remove:
  - independent local affine policy drift,
  - implicit plane/range assumptions not tied to contract.

### E) modules/mpr/zeta_mpr/advanced_rendering.py
- Input geometry source:
  - SourceGeometry and DisplayGeometry-derived orientation vectors.
- Output viewport/display geometry:
  - Slab and projection outputs tagged with contract plane metadata.
- MPR plane defined in LPS:
  - Slab plane and thickness direction from contract normals.
- Reslice axes build:
  - Replace hard-coded `SetResliceAxesDirectionCosines` with contract vectors.
- Crosshair/reference/sync in LPS:
  - Slab center follows contract LPS crosshair center.
- Old assumptions to remove:
  - hard-coded axis cosines and modality-specific orientation shortcuts.

## Behavior Change Statement

- No broad behavior migrations were made.
- Added visibility guards and one explicit mutation-block tag only.
- Existing rendering/sync flows continue unchanged outside guard logging.
