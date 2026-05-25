# AI CSV to VTK Geometry Conversion (Advanced/Eagle Eye)

## Goal
Keep the current Advanced VTK geometry untouched (it is correct), and map CSV AI results into that geometry safely.

## Current Contract
- Advanced viewer geometry is authoritative.
- CSV AI boxes must be interpreted as pixel-space boxes in the viewer's current raw IJK convention.
- Rendering path uses `draw_boxes_ijk(...)` in `modules/viewer/advanced/viewer_2d.py`.

## What Was Wrong in CSV-to-Geometry Conversion
The prior CSV load path in `modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py` had no coordinate-space conversion layer.

It assumed:
- CSV `box`, `new_box`, `removed` were already in the current VTK raw-IJK coordinate space.

That assumption fails for older server outputs that were generated under different geometry/coordinate conventions.

## Implemented Fix (Non-regressive)
A dedicated conversion layer is now applied in `AIVTKWidget._compute_boxes_scores_for_metadata(...)` before drawing:

- Resolve source coordinate space from CSV row metadata columns:
  - `coord_space`
  - `geometry_version`
  - `coord_system`
- Convert to current VTK raw-IJK using `AIVTKWidget._convert_boxes_to_current_geometry(...)`.
- Normalize and clamp boxes to image bounds.

Supported source spaces:
- `vtk_raw_ijk_v2` (current, pass-through)
- `legacy_bottom_left_ijk` (Y-origin inversion)
- `normalized_xyxy` (0..1 to pixel-space)
- `world_mm_xyxy` (physical mm to pixel-space via spacing)

This keeps current geometry intact and only adapts incoming CSV coordinates.

## Why This Is Safe
- No changes were made to VTK geometry contracts (`DisplayGeometry`, `SourceGeometry`, camera/orientation logic).
- Conversion is data-layer only, before overlay draw.
- If CSV has no coordinate metadata, behavior remains current-compatible (`vtk_raw_ijk_v2`) to avoid regressions.

## Expected Server-Side CSV Contract (Recommended)
Add these columns for every row:

- `coord_space`:
  - `vtk_raw_ijk_v2` (preferred for current app)
  - or one of the legacy identifiers above
- `image_width_px` (Columns)
- `image_height_px` (Rows)
- `pixel_spacing_x` (mm)
- `pixel_spacing_y` (mm)
- `geometry_version` (optional but recommended)

## Migration Guidance for Server Team
1. Choose one canonical output space for all new files: `vtk_raw_ijk_v2`.
2. Stamp `coord_space=vtk_raw_ijk_v2` for every generated row.
3. Include width/height and spacing columns for auditability.
4. Stop emitting legacy coordinate spaces once all clients are migrated.
5. For backfills, either:
   - regenerate boxes in canonical space, or
   - correctly set `coord_space` so client conversion can map them.

## Runtime Diagnostics
Conversion path emits:
- `[MG][GEOM_CONVERT] series_uid=... coord_space=... dims=(w,h) spacing=(sx,sy) boxes=...`

Use this to verify whether a file is interpreted as current or legacy.

## Known Failure Modes to Watch
1. Missing/incorrect `coord_space` on legacy files.
2. Wrong pixel spacing for `world_mm_xyxy` files.
3. Mixed coordinate spaces inside one CSV without per-row metadata.
4. Mismatched image dimensions (CSV produced on resized/cropped images).

## Summary
- Current VTK geometry is correct and unchanged.
- The root issue is missing/incorrect CSV coordinate-space mapping.
- The app now has a compatibility conversion structure.
- Long-term fix is server-side canonical CSV generation (`vtk_raw_ijk_v2`).
