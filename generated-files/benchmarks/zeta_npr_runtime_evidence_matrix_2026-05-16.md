# Zeta NPR Runtime Evidence Matrix (2026-05-16)

| case | source_plane | expected_source_box | actual_source_box | fallback_reason | output_view | row_axis_error | col_axis_error | normal_axis_error | first_label | last_label | stack_order_ok | orientation_ok | failure_cause |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| shoulder_axial_source | axial | Axial | Axial | zeta_mpr_fixed_layout_axial_receives_input_volume | axial(primary), sagittal(recon), coronal(recon) | 178.465 | 157.962 | 21.984 | Superior | Inferior | False | False | orientation_axis_mismatch |
| shoulder_sagittal_source | sagittal | Sagittal | Axial | zeta_mpr_fixed_layout_axial_receives_input_volume | axial(primary), sagittal(recon), coronal(recon) | 125.084 | 136.391 | 42.16 | Right | Left | False | False | fixed_layout_source_bound_to_axial |
| shoulder_coronal_source | sagittal | Sagittal | Axial | zeta_mpr_fixed_layout_axial_receives_input_volume | axial(primary), sagittal(recon), coronal(recon) | 130.897 | 71.766 | 116.173 | Right | Left | False | False | fixed_layout_source_bound_to_axial |

## Additional Checks
- sagittal_source_to_axial_box_confirmed: True
- coronal_source_to_axial_box_confirmed: True
- camera_roll_azimuth_active_any_case: False
- xflip_compensated_in_axes_any_case: True
- output_stack_k_policy: raw_vtk_k_direct (crosshair/current_position mapped by spacing/origin)
- sourcegeometry_displaygeometry_geometryapi_used_in_zeta_mpr: False