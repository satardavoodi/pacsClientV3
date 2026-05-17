# Zeta NPR Viewport Assignment Table

## Runtime Assignment (Current Behavior)
| viewport | grid position | creator | source role | interpolation | assignment rule | forensic tag |
|---|---|---|---|---|---|---|
| axial | (0,0) | _create_axial_view | input_volume_primary | nearest | fixed-layout default primary source view | [ZETA_NPR_VIEWPORT_ASSIGNMENT] |
| sagittal | (1,0) | _create_sagittal_view | mpr_reconstructed | linear | fixed-layout reconstructed view | [ZETA_NPR_VIEWPORT_ASSIGNMENT] |
| coronal | (1,1) | _create_coronal_view | mpr_reconstructed | linear | fixed-layout reconstructed view | [ZETA_NPR_VIEWPORT_ASSIGNMENT] |
| 3d | (0,1) | _create_3d_view | volume rendering | n/a | fixed-layout 3D slot | n/a |

## Source-Plane vs Viewport Mapping Reality
| source-plane inferred from IOP | expected by strict source-plane mapping | actual current mapping | why |
|---|---|---|---|
| axial | axial box | axial box | fixed layout matches expectation |
| sagittal | sagittal box | axial box receives primary source stack | no dynamic remap branch; input volume bound to axial view by design |
| coronal | coronal box | axial box receives primary source stack | no dynamic remap branch; input volume bound to axial view by design |
| oblique | dynamic strategy required | axial box receives primary source stack | no oblique-specific viewport remap in Zeta MPR layout path |

## Explicit Fallback Reason (Now Logged)
used_default_axial=True
fallback_reason=zeta_mpr_fixed_layout_axial_receives_input_volume

This is emitted in [ZETA_NPR_SOURCE_CLASSIFICATION] during route resolution and again in viewer init context.

## Risk Notes
- If acquisition plane is sagittal/coronal, users may interpret axial box as incorrect assignment.
- Because assignment is static, plane inference currently informs logs only, not placement decisions.
