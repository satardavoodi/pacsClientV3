# Zeta NPR Reslice Axes Audit Table

## What Is Logged
The [ZETA_NPR_RESLICE_AXES_AUDIT] tag is emitted per 2D viewport when baseline camera state is captured.

Fields:
- view_name
- row_dir
- col_dir
- slice_dir
- camera_position
- camera_focal_point
- camera_view_up
- camera_direction
- camera_distance
- parallel_scale

## Effective Axes Source Chain
| stage | source | detail |
|---|---|---|
| direction extraction | StandardMPRViewer.__init__ | direction matrix read from field data when present |
| input correction | StandardMPRViewer.__init__ | direction first column negated to account for input X-flip |
| view camera vectors | _get_camera_vectors_for_view | camera vectors derived from center + view type policy |
| CT camera adjustments | _create_sagittal_view / _create_coronal_view | sagittal Roll(180), coronal Azimuth(180)+Roll(180) |
| baseline capture | _capture_baseline_camera_state | final camera vectors logged for each viewport |

## Interpretation Guide
| symptom in rendered view | likely matching audit signature |
|---|---|
| left-right inversion | row_dir/camera_direction sign mismatch after input X-flip |
| sagittal/coronal appears rotated/flipped | CT-specific camera correction present with large 180-degree transforms |
| inconsistent orientation between views | row_dir/col_dir/slice_dir not matching expected orthogonal basis |

## Stack Order Companion Tag
Use [ZETA_NPR_STACK_ORDER_AUDIT] with this table to correlate:
- file-order strategy (natsorted path)
- first/last IPP
- first IOP inferred plane
with
- final viewport camera axes

This correlation is required to separate ordering issues from camera/orientation transform issues.
