# Zeta NPR/MPR Pipeline Audit (Forensic, No-Fix)

## Scope
This document captures the real launch/runtime path for Zeta NPR/MPR in the current codebase, with audit-only instrumentation added.
No behavioral fix is implemented here.

## Added Forensic Tags
- [ZETA_NPR_SOURCE_CLASSIFICATION]
- [ZETA_NPR_VIEWPORT_ASSIGNMENT]
- [ZETA_NPR_RESLICE_AXES_AUDIT]
- [ZETA_NPR_STACK_ORDER_AUDIT]

## Stage Map
| stage | file/function | input | output | plane/order decision | risk |
|---|---|---|---|---|---|
| MPR button click | PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py :: toggle_zeta_mpr | selected viewport + thumbnail metadata | route request | source series resolved by series_number from viewer metadata | wrong metadata could point to wrong source series |
| Route resolve | PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py :: _resolve_mpr_volume_for_route | series_data + backend + instances[0] IOP/IPP | launch-ready vtk or block | backend-driven route: use existing vtk or force full load for FAST stub | if metadata IOP/IPP missing, classification becomes unknown |
| Full-volume bridge | PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py :: _load_full_vtk_for_mpr | series folder/preferred path files | vtkImageData with scalars | file order uses natsorted path order | filename order may differ from true geometric order in edge cases |
| DICOM->SITK->VTK | PacsClient/pacs/patient_tab/utils/image_io.py :: load_vtk_from_dicom_paths | list of dicom paths | vtkImageData | order currently natsorted path order in this helper | stack orientation/order errors can propagate if filename order is non-geometric |
| Viewer init | modules/mpr/zeta_mpr/mpr_viewer/widget.py :: StandardMPRViewer.__init__ | vtkImageData | flipped source volume + direction matrix | global X-axis flip applied to input before view creation | global flip can change perceived left-right conventions |
| View layout creation | modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py :: _setup_ui + _create_axial/_create_sagittal/_create_coronal | flipped vtk + direction/camera vectors | 2x2 fixed viewport layout | fixed mapping: axial at (0,0), sagittal at (1,0), coronal at (1,1) | no runtime remap of source-plane to viewport box |
| Camera/baseline capture | modules/mpr/zeta_mpr/mpr_viewer/_mpr_orientation.py :: _capture_baseline_camera_state | renderer cameras + direction matrix | baseline camera state + axis audit | camera vectors become effective reslice orientation contract | CT-specific camera transforms may invert perceived orientation |

## Exact Finding 1: Why sagittal source is assigned to axial box
Reason is deterministic fixed-layout behavior, not a dynamic classifier bug in viewport selection.

1. _setup_ui always calls _create_axial_view first and places it at grid (0,0).
2. _create_axial_view always binds the input volume directly to axial view as the primary source role.
3. There is no conditional branch that remaps the input source plane (from IOP dominant axis) into sagittal/coronal viewport positions.
4. Therefore, even if source IOP indicates a sagittal acquisition, the source stack is still rendered in the axial viewport slot by design.

Audit evidence now emitted in:
- [ZETA_NPR_SOURCE_CLASSIFICATION] with used_default_axial=True and fallback_reason.
- [ZETA_NPR_VIEWPORT_ASSIGNMENT] for axial with source_role=input_volume_primary and fixed-layout reason.

## Exact Finding 2: Why reconstructed sagittal/coronal are flipped
The observed flip behavior is produced by explicit transform/camera policy in the current path:

1. Input-level left-right flip is applied globally in StandardMPRViewer.__init__ via vtkImageFlip on axis 0.
2. Sagittal and coronal views are then reconstructed using camera-facing slice mapping.
3. Additional CT-specific camera corrections are explicitly applied:
   - sagittal: camera.Roll(180)
   - coronal: camera.Azimuth(180) + camera.Roll(180)
4. The combination of global input flip plus CT camera corrections can produce perceived reversed orientation relative to expected anatomical display.

Audit evidence now emitted in:
- [ZETA_NPR_RESLICE_AXES_AUDIT] (row_dir/col_dir/slice_dir and camera vectors per viewport)
- [ZETA_NPR_VIEWPORT_ASSIGNMENT] (view role and interpolation policy)

## Stack Ordering Evidence Contract
Stack-order evidence is now logged at two active points:
- Toolbar bridge before full-load call
- image_io.load_vtk_from_dicom_paths after natsorted ordering

Fields include:
- ordering_method
- file_count
- first_file/last_file
- first_instance_number/last_instance_number
- first_ipp/last_ipp
- first_iop (image_io emit)
- inferred_plane (from first IOP normal)

## Current Forensic Conclusion (No Fix Applied)
- Viewport assignment is fixed-layout and defaults primary source to axial box.
- Source-plane classification exists only as audit signal today; it does not drive viewport remapping.
- Reconstructed sagittal/coronal orientation is affected by both global input X-flip and CT-specific camera rotations.
- Stack order in the full-load path is currently filename-natural, not explicitly geometric in this helper.
