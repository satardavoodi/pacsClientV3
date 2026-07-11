"""
3D Cursor Visualization — Drawing projected cursors on viewer widgets.

This module handles the display of 3D cursor results on mammogram viewers:
    - Paired lesions: highlighted with a confirmation box (cyan).
    - Projected lesions: drawn as a blue bounding box at the estimated location.
    - Out-of-field: no box drawn; the text summary reports the issue.
    - Ruler lines: dashed lines from nipple to lesion with mm distance labels.

Pixel coordinates are used only here (the final visualization step).
All geometric computation is done in the correlator using millimeters.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .correlator import Cursor3DResult, CursorMatch, LateralityResult, ViewData


# ─── Colors ──────────────────────────────────────────────────────────────────

COLOR_PAIRED = (0.1, 0.4, 1.0)       # Blue — confirmed match in both views
COLOR_PROJECTED = (0.0, 0.5, 1.0)    # Blue — projected 3D cursor location
COLOR_OUT_OF_FIELD = (0.8, 0.2, 0.2) # Red — invalid projection (out of field)
COLOR_RULER = (0.0, 0.6, 1.0)        # Blue — ruler line (nipple to lesion)
COLOR_RULER_TEXT = (0.8, 0.95, 1.0)  # Light blue — distance label
COLOR_LESION_RULER = (1.0, 0.6, 0.0) # Orange — lesion-to-lesion ruler
COLOR_LESION_RULER_TEXT = (1.0, 0.9, 0.6)  # Light orange — distance label


def draw_3d_cursor_results(
    result: Cursor3DResult,
    views_by_key: Dict[str, ViewData],
    *,
    draw_rulers: bool = True,
):
    """
    Draw the 3D cursor results onto viewer widgets.

    Args:
        result: The computed Cursor3DResult.
        views_by_key: Dict mapping "{laterality}_{view}" (e.g. "R_CC") to ViewData,
                      which contains the vtk_widget reference for drawing.
        draw_rulers: If True (default), also draw ruler lines with mm distance labels.
    """
    for laterality, lat_result in result.lateralities.items():
        _draw_laterality_results(laterality, lat_result, views_by_key)

    # Draw ruler annotations showing nipple-to-lesion distance on each view
    if draw_rulers:
        draw_rulers_for_results(result, views_by_key)


def _draw_laterality_results(
    laterality: str,
    lat_result: LateralityResult,
    views_by_key: Dict[str, ViewData],
):
    """Draw results for one laterality.

    RULE: If BOTH CC and MLO have detected lesions (i.e. all matches are 'paired'),
    do NOT draw any 3D cursor visualization — the AI boxes already show the lesions
    in both views and no projection is needed.
    """
    cc_key = f"{laterality}_CC"
    mlo_key = f"{laterality}_MLO"

    cc_view = views_by_key.get(cc_key)
    mlo_view = views_by_key.get(mlo_key)

    # Clear previous projected actors
    if cc_view and cc_view.vtk_widget:
        _clear_projected_actors(cc_view.vtk_widget)
    if mlo_view and mlo_view.vtk_widget:
        _clear_projected_actors(mlo_view.vtk_widget)

    # If ALL matches are paired (lesion found in both CC and MLO), skip 3D cursor entirely
    if lat_result.cursor_matches and all(
        m.match_type == 'paired' for m in lat_result.cursor_matches
    ):
        print(f"[3D-Cursor] Skipping visualization for {laterality}: "
              f"lesions found in BOTH CC and MLO — no projection needed.")
        return

    for match in lat_result.cursor_matches:
        if match.match_type == 'paired':
            # Draw confirmation highlight on both views
            _draw_paired_match(match, cc_view, mlo_view)
        elif match.match_type in ('projected', 'arc_projected'):
            # Draw blue semi-transparent REGION overlay on the target view
            _draw_projected_region(match, views_by_key, laterality)
        # 'out_of_field' — no box drawn (reported in text summary only)


def _draw_paired_match(match: CursorMatch, cc_view: Optional[ViewData], mlo_view: Optional[ViewData]):
    """Paired match: both views already have AI boxes — do NOT draw anything new.

    When both CC and MLO have detected lesions, the green AI boxes are already
    rendered by the normal AI pipeline. Adding extra boxes just clutters the view.
    The summary text reports the pairing; no visual change needed on the viewers.
    """
    pass  # Intentionally empty — both views already show their AI detection boxes.


def _draw_projected_cursor(match: CursorMatch, views_by_key: Dict[str, ViewData], laterality: str):
    """Legacy: Draw a projected 3D cursor box on the target view."""
    if match.target_lesion is None:
        return

    target_key = f"{laterality}_{match.target_view}"
    target_view = views_by_key.get(target_key)

    if target_view and target_view.vtk_widget:
        # Use red color if validation clamped the point (warning in message)
        has_warning = "VALIDATION" in match.message or "clamped" in match.message.lower()
        color = COLOR_OUT_OF_FIELD if has_warning else COLOR_PROJECTED

        _draw_box_on_widget(
            target_view.vtk_widget,
            match.target_lesion.to_pixel_box(),
            color=color,
            confidence=match.confidence,
        )

        # Draw warning text overlay if point was clamped
        if has_warning:
            _draw_validation_warning(target_view.vtk_widget, match.message)


def _draw_projected_region(match: CursorMatch, views_by_key: Dict[str, ViewData], laterality: str):
    """
    Draw a semi-transparent blue VERTICAL RECTANGLE overlay showing the probable
    lesion zone at the nipple-distance from the nipple point.

    The rectangle spans the full height of the image (top to bottom) and is centered
    horizontally at the distance from the nipple where the lesion is projected.
    """
    if match.target_lesion is None and match.correspondence_arc is None:
        return

    target_key = f"{laterality}_{match.target_view}"
    target_view = views_by_key.get(target_key)

    if not (target_view and target_view.vtk_widget):
        return

    arc = match.correspondence_arc
    target_center_px = match.target_lesion.center_px if match.target_lesion is not None else None
    if arc and arc.arc_points_px and len(arc.arc_points_px) >= 2:
        # Draw full-height rectangle at the nipple distance
        _draw_distance_rectangle_on_widget(
            vtk_widget=target_view.vtk_widget,
            arc=arc,
            band_width_mm=None,  # Use module default (wider clinical strip)
            view_type=match.target_view,  # 'CC' or 'MLO' — controls tilt angle
            target_center_px=target_center_px,
        )
    elif match.target_lesion is not None:
        # Fallback: draw a full-height rectangle at the target lesion x-position
        _draw_distance_rectangle_fallback(
            vtk_widget=target_view.vtk_widget,
            center_px=match.target_lesion.center_px,
            radius_mm=match.depth_mm,
            nipple_px=(arc.center_x_px, arc.center_y_px) if arc else match.target_lesion.center_px,
            pixel_spacing_x=target_view.pixel_spacing_x or 0.1,
            pixel_spacing_y=target_view.pixel_spacing_y or 0.1,
        )


def _draw_box_on_widget(vtk_widget, box: list, color: tuple, confidence: float):
    """Draw a single bounding box on a viewer widget."""
    try:
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return

        x1, y1, x2, y2 = box
        boxes_scores = [{'box': [x1, y1, x2, y2], 'score': float(confidence)}]

        if hasattr(image_viewer, 'draw_boxes_ijk'):
            lst_actors = image_viewer.draw_boxes_ijk(
                boxes_scores, color=color, line_width=2.5
            )
            if not hasattr(vtk_widget, '_projected_actors'):
                vtk_widget._projected_actors = []
            if lst_actors:
                vtk_widget._projected_actors.extend(lst_actors)
    except Exception as e:
        print(f"[3D-Cursor] Failed to draw box: {e}")


def _draw_validation_warning(vtk_widget, warning_message: str):
    """
    Draw a red warning text overlay on the viewer when a projection was clamped.

    This alerts the radiologist that the projected cursor location was adjusted
    because it fell outside the breast tissue or image boundaries.
    """
    try:
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return

        # Extract short warning text
        if "VALIDATION:" in warning_message:
            short_msg = warning_message.split("VALIDATION:")[-1].strip()
        else:
            short_msg = "⚠ Projection adjusted"

        # Truncate for display
        if len(short_msg) > 60:
            short_msg = short_msg[:57] + "..."

        # Use VTK text actor if available
        add_text_fn = getattr(image_viewer, 'add_text_overlay', None)
        if add_text_fn:
            actor = add_text_fn(
                short_msg,
                position='bottom_center',
                color=COLOR_OUT_OF_FIELD,
                font_size=12,
            )
            if actor:
                if not hasattr(vtk_widget, '_projected_actors'):
                    vtk_widget._projected_actors = []
                vtk_widget._projected_actors.append(actor)
        else:
            # Fallback: just log the warning
            print(f"[3D-Cursor][VISUAL-WARN] {short_msg}")
    except Exception as e:
        print(f"[3D-Cursor] Failed to draw validation warning: {e}")


# ─── Region Overlay Drawing (Radial Sector from Nipple) ──────────────────────

# Colors for the radial sector — inner (near nipple) lighter, outer (lesion) deeper
COLOR_SECTOR_INNER = (0.4, 0.7, 1.0)     # Light blue (near nipple)
COLOR_SECTOR_OUTER = (0.15, 0.45, 1.0)   # Deep blue (at lesion depth)
SECTOR_INNER_OPACITY = 0.08              # Nearly transparent near nipple
SECTOR_OUTER_OPACITY = 0.45              # More opaque at lesion depth
NUM_RADIAL_BANDS = 8                     # Number of radial bands for gradient
SECTOR_ANGULAR_SPREAD_DEG = 30.0         # Angular spread of the sector (degrees)


def _draw_arc_region_on_widget(vtk_widget, arc, band_width_mm: float = 15.0):
    """
    Draw a radial sector (wedge) from the nipple outward to the projected lesion depth.

    The sector starts at the nipple position and extends outward to `arc.radius_px`,
    spanning an angular range centered on the direction toward the best_point.
    Color/opacity gradient goes from transparent near nipple to opaque at lesion depth.

    Args:
        vtk_widget: The VTK widget to draw on.
        arc: CorrespondenceArc with arc geometry.
        band_width_mm: Total width of the band in mm (unused, kept for API compat).
    """
    try:
        import vtk as _vtk
    except ImportError:
        return

    try:
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return

        renderer = getattr(image_viewer, 'renderer', None)
        if renderer is None:
            return

        ijk_to_world = getattr(image_viewer, 'ijk_to_world', None)
        if ijk_to_world is None:
            return

        import math

        # Nipple position (origin of the sector)
        nipple_x = arc.center_x_px
        nipple_y = arc.center_y_px

        # Target point (projected lesion location)
        if arc.best_point_px:
            target_x, target_y = arc.best_point_px
        elif arc.arc_points_px and len(arc.arc_points_px) >= 2:
            mid_idx = len(arc.arc_points_px) // 2
            target_x, target_y = arc.arc_points_px[mid_idx]
        else:
            # Fallback: use arc radius in the arc's angular center direction
            mid_angle = (arc.start_angle_rad + arc.end_angle_rad) / 2.0
            target_x = nipple_x + arc.radius_px * math.cos(mid_angle)
            target_y = nipple_y + arc.radius_px * math.sin(mid_angle)

        # Compute direction from nipple to target
        dx = target_x - nipple_x
        dy = target_y - nipple_y
        sector_radius = math.sqrt(dx * dx + dy * dy)
        if sector_radius < 5.0:
            return  # Too close, nothing to draw

        # Central angle of the sector (direction from nipple to lesion)
        center_angle = math.atan2(dy, dx)

        # Angular spread: use arc's own angular extent if available, else default
        arc_span = abs(arc.end_angle_rad - arc.start_angle_rad)
        if arc_span > 0.01:
            half_spread = arc_span / 2.0
        else:
            half_spread = math.radians(SECTOR_ANGULAR_SPREAD_DEG) / 2.0

        # Clamp spread to reasonable range
        half_spread = max(math.radians(10.0), min(half_spread, math.radians(60.0)))

        num_angular_steps = 32  # Smooth arc edges
        all_actors = []

        # Draw radial bands from nipple outward
        for band_idx in range(NUM_RADIAL_BANDS):
            t_inner = band_idx / float(NUM_RADIAL_BANDS)
            t_outer = (band_idx + 1) / float(NUM_RADIAL_BANDS)

            inner_r = sector_radius * t_inner
            outer_r = sector_radius * t_outer

            # Interpolate color and opacity (transparent near nipple, opaque at depth)
            r = COLOR_SECTOR_INNER[0] + (COLOR_SECTOR_OUTER[0] - COLOR_SECTOR_INNER[0]) * t_outer
            g = COLOR_SECTOR_INNER[1] + (COLOR_SECTOR_OUTER[1] - COLOR_SECTOR_INNER[1]) * t_outer
            b = COLOR_SECTOR_INNER[2] + (COLOR_SECTOR_OUTER[2] - COLOR_SECTOR_INNER[2]) * t_outer
            opacity = SECTOR_INNER_OPACITY + (SECTOR_OUTER_OPACITY - SECTOR_INNER_OPACITY) * t_outer

            # Build annular sector polygon (arc between inner_r and outer_r)
            outer_pts = []
            inner_pts = []

            for i in range(num_angular_steps + 1):
                t_angle = i / float(num_angular_steps)
                angle = center_angle - half_spread + t_angle * (2.0 * half_spread)

                ox = nipple_x + outer_r * math.cos(angle)
                oy = nipple_y + outer_r * math.sin(angle)
                outer_pts.append((ox, oy))

                ix_pt = nipple_x + inner_r * math.cos(angle)
                iy_pt = nipple_y + inner_r * math.sin(angle)
                inner_pts.append((ix_pt, iy_pt))

            # Polygon: outer arc forward + inner arc reversed
            polygon_pts_px = outer_pts + list(reversed(inner_pts))
            if len(polygon_pts_px) < 4:
                continue

            vtk_points = _vtk.vtkPoints()
            for px, py in polygon_pts_px:
                world_pt = ijk_to_world(px, py, None, y_flip=True)
                vtk_points.InsertNextPoint(world_pt)

            polygon = _vtk.vtkPolygon()
            polygon.GetPointIds().SetNumberOfIds(len(polygon_pts_px))
            for i in range(len(polygon_pts_px)):
                polygon.GetPointIds().SetId(i, i)

            cells = _vtk.vtkCellArray()
            cells.InsertNextCell(polygon)

            poly_data = _vtk.vtkPolyData()
            poly_data.SetPoints(vtk_points)
            poly_data.SetPolys(cells)

            mapper = _vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly_data)

            band_actor = _vtk.vtkActor()
            band_actor.SetMapper(mapper)
            band_actor.GetProperty().SetColor(r, g, b)
            band_actor.GetProperty().SetOpacity(opacity)
            band_actor.GetProperty().LightingOff()

            renderer.AddActor(band_actor)
            all_actors.append(band_actor)

        # Track actors for cleanup and Hide Boxes toggle
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.extend(all_actors)

        if not hasattr(vtk_widget, '_3d_cursor_region_actors'):
            vtk_widget._3d_cursor_region_actors = []
        vtk_widget._3d_cursor_region_actors.extend(all_actors)

        # Render
        renderer.ResetCameraClippingRange()
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

        print(f"[3D-Cursor][REGION] Drew radial sector from nipple: "
              f"radius={sector_radius:.0f}px angle={math.degrees(center_angle):.1f}deg "
              f"spread={math.degrees(2*half_spread):.1f}deg bands={NUM_RADIAL_BANDS}")

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw arc region: {e}")


# ─── Full-Height Rectangle at Nipple Distance ───────────────────────────────

RECT_COLOR = (0.1, 0.4, 1.0)         # Deep blue fill
RECT_OPACITY = 0.18                   # Semi-transparent fill
RECT_BORDER_COLOR = (0.3, 0.65, 1.0) # Bright blue border
RECT_BORDER_OPACITY = 0.9
RECT_HALO_COLOR = (0.4, 0.75, 1.0)   # Outer halo glow color
RECT_HALO_OPACITY = 0.08             # Very subtle outer glow
RECT_HALO_LAYERS = 3                  # Number of halo expansion layers
RECT_HALO_EXPAND_PX = 12.0           # Pixels expansion per halo layer
RECT_BAND_WIDTH_MM = 140.0           # Default rectangle width in mm (wider clinical strip)
RECT_LONG_AXIS_ANGLE_DEG = 90.0      # Fixed rectangle long-axis angle (vertical)


def _draw_distance_rectangle_on_widget(
    vtk_widget,
    arc,
    band_width_mm: Optional[float] = None,
    view_type: str = 'CC',
    target_center_px: Optional[Tuple[float, float]] = None,
):
    """
    Draw a full-span rectangle with halo glow at the nipple-distance.

    The long axis of the rectangle is perpendicular to the nipple→target line
    and the strip passes through the target point.

    Args:
        vtk_widget: The VTK widget to draw on.
        arc: CorrespondenceArc with nipple center and radius info.
        band_width_mm: Total width of the rectangle band in mm (default RECT_BAND_WIDTH_MM).
        view_type: 'CC' or 'MLO' — MLO gets a tilted rectangle.
    """
    if band_width_mm is None:
        band_width_mm = RECT_BAND_WIDTH_MM
    try:
        import vtk as _vtk
    except ImportError:
        return

    try:
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return

        renderer = getattr(image_viewer, 'renderer', None)
        if renderer is None:
            return

        ijk_to_world = getattr(image_viewer, 'ijk_to_world', None)
        if ijk_to_world is None:
            return

        import math

        # Nipple position (center of distance measurement)
        nipple_x = arc.center_x_px
        nipple_y = arc.center_y_px

        # Target point (projected lesion location).
        # Prefer validated lesion center so the strip follows in-breast clamped output.
        if target_center_px is not None:
            target_x, target_y = target_center_px
        elif arc.best_point_px:
            target_x, target_y = arc.best_point_px
        elif arc.arc_points_px and len(arc.arc_points_px) >= 2:
            mid_idx = len(arc.arc_points_px) // 2
            target_x, target_y = arc.arc_points_px[mid_idx]
        else:
            mid_angle = (arc.start_angle_rad + arc.end_angle_rad) / 2.0
            target_x = nipple_x + arc.radius_px * math.cos(mid_angle)
            target_y = nipple_y + arc.radius_px * math.sin(mid_angle)

        # Get image dimensions
        metadata = getattr(image_viewer, 'metadata', None)
        img_height = 0
        img_width = 0
        if metadata:
            instances = metadata.get('instances', [])
            if instances:
                first_inst = instances[0] if isinstance(instances, list) else {}
                img_height = first_inst.get('rows', 0) or 0
                img_width = first_inst.get('columns', 0) or 0
            if not img_height:
                series_meta = metadata.get('series', {})
                img_height = series_meta.get('rows', 0) or 0
                img_width = series_meta.get('columns', 0) or 0

        # Fallback: try from VTK image data dimensions
        if not img_height:
            try:
                vtk_data = image_viewer.GetInput()
                if vtk_data:
                    dims = vtk_data.GetDimensions()
                    img_width = dims[0]
                    img_height = dims[1]
            except Exception:
                pass

        if img_height <= 0:
            img_height = 4000  # Fallback for mammography

        # Band half-width in pixels (from mm)
        avg_spacing = arc.radius_px / max(arc.radius_mm, 1.0) if arc.radius_mm > 0 else 1.0
        half_width_px = (band_width_mm / 2.0) * avg_spacing if avg_spacing > 0 else 30.0
        half_width_px = max(30.0, half_width_px)  # Minimum visible width

        # Use fixed vertical orientation (90°) for the long axis.
        perp_angle = math.radians(RECT_LONG_AXIS_ANGLE_DEG)

        # Build a strip centered on target, sized to approximate breast extent.
        # Use image height (breast length in MLO) as the maximum span — not the
        # full diagonal, which makes the rectangle unreasonably long.
        breast_extent_px = float(img_height) if img_height > 0 else 3584.0
        band_half_height = breast_extent_px / 2.0

        cos_perp = math.cos(perp_angle)
        sin_perp = math.sin(perp_angle)

        # Center the strip at projected target
        cx = target_x
        cy = target_y

        # Unit vectors
        perp_ux = cos_perp
        perp_uy = sin_perp
        along_angle = perp_angle - math.pi / 2.0
        along_ux = math.cos(along_angle)
        along_uy = math.sin(along_angle)

        corners_px = [
            (cx - half_width_px * along_ux - band_half_height * perp_ux,
             cy - half_width_px * along_uy - band_half_height * perp_uy),
            (cx + half_width_px * along_ux - band_half_height * perp_ux,
             cy + half_width_px * along_uy - band_half_height * perp_uy),
            (cx + half_width_px * along_ux + band_half_height * perp_ux,
             cy + half_width_px * along_uy + band_half_height * perp_uy),
            (cx - half_width_px * along_ux + band_half_height * perp_ux,
             cy - half_width_px * along_uy + band_half_height * perp_uy),
        ]

        vtk_points = _vtk.vtkPoints()
        for px, py in corners_px:
            world_pt = ijk_to_world(px, py, None, y_flip=True)
            vtk_points.InsertNextPoint(world_pt)

        polygon = _vtk.vtkPolygon()
        polygon.GetPointIds().SetNumberOfIds(4)
        for i in range(4):
            polygon.GetPointIds().SetId(i, i)

        cells = _vtk.vtkCellArray()
        cells.InsertNextCell(polygon)

        poly_data = _vtk.vtkPolyData()
        poly_data.SetPoints(vtk_points)
        poly_data.SetPolys(cells)

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly_data)

        # Filled rectangle actor
        rect_actor = _vtk.vtkActor()
        rect_actor.SetMapper(mapper)
        rect_actor.GetProperty().SetColor(*RECT_COLOR)
        rect_actor.GetProperty().SetOpacity(RECT_OPACITY)
        rect_actor.GetProperty().LightingOff()
        renderer.AddActor(rect_actor)

        all_actors = [rect_actor]

        # ─── Halo glow layers (expanding outward) ───
        for halo_idx in range(1, RECT_HALO_LAYERS + 1):
            expand = RECT_HALO_EXPAND_PX * halo_idx
            hw_px = half_width_px + expand
            halo_corners = [
                (cx - hw_px * along_ux - band_half_height * perp_ux,
                 cy - hw_px * along_uy - band_half_height * perp_uy),
                (cx + hw_px * along_ux - band_half_height * perp_ux,
                 cy + hw_px * along_uy - band_half_height * perp_uy),
                (cx + hw_px * along_ux + band_half_height * perp_ux,
                 cy + hw_px * along_uy + band_half_height * perp_uy),
                (cx - hw_px * along_ux + band_half_height * perp_ux,
                 cy - hw_px * along_uy + band_half_height * perp_uy),
            ]
            halo_pts = _vtk.vtkPoints()
            for hpx, hpy in halo_corners:
                hw = ijk_to_world(hpx, hpy, None, y_flip=True)
                halo_pts.InsertNextPoint(hw)

            halo_polygon = _vtk.vtkPolygon()
            halo_polygon.GetPointIds().SetNumberOfIds(4)
            for i in range(4):
                halo_polygon.GetPointIds().SetId(i, i)

            halo_cells = _vtk.vtkCellArray()
            halo_cells.InsertNextCell(halo_polygon)

            halo_pd = _vtk.vtkPolyData()
            halo_pd.SetPoints(halo_pts)
            halo_pd.SetPolys(halo_cells)

            halo_mapper = _vtk.vtkPolyDataMapper()
            halo_mapper.SetInputData(halo_pd)

            halo_actor = _vtk.vtkActor()
            halo_actor.SetMapper(halo_mapper)
            halo_actor.GetProperty().SetColor(*RECT_HALO_COLOR)
            # Opacity decreases with each layer outward
            layer_opacity = RECT_HALO_OPACITY / halo_idx
            halo_actor.GetProperty().SetOpacity(layer_opacity)
            halo_actor.GetProperty().LightingOff()
            renderer.AddActor(halo_actor)
            all_actors.append(halo_actor)

        # Border rectangle (outline) with glow-style wider line
        border_points = _vtk.vtkPoints()
        for px, py in corners_px:
            world_pt = ijk_to_world(px, py, None, y_flip=True)
            border_points.InsertNextPoint(world_pt)
        # Close the loop
        world_pt = ijk_to_world(corners_px[0][0], corners_px[0][1], None, y_flip=True)
        border_points.InsertNextPoint(world_pt)

        border_line = _vtk.vtkPolyLine()
        border_line.GetPointIds().SetNumberOfIds(5)
        for i in range(5):
            border_line.GetPointIds().SetId(i, i)

        border_cells = _vtk.vtkCellArray()
        border_cells.InsertNextCell(border_line)

        border_poly = _vtk.vtkPolyData()
        border_poly.SetPoints(border_points)
        border_poly.SetLines(border_cells)

        border_mapper = _vtk.vtkPolyDataMapper()
        border_mapper.SetInputData(border_poly)

        border_actor = _vtk.vtkActor()
        border_actor.SetMapper(border_mapper)
        border_actor.GetProperty().SetColor(*RECT_BORDER_COLOR)
        border_actor.GetProperty().SetOpacity(RECT_BORDER_OPACITY)
        border_actor.GetProperty().SetLineWidth(3.0)
        border_actor.GetProperty().LightingOff()
        renderer.AddActor(border_actor)
        all_actors.append(border_actor)

        # Track actors for cleanup and Show/Hide toggle
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.extend(all_actors)

        if not hasattr(vtk_widget, '_3d_cursor_region_actors'):
            vtk_widget._3d_cursor_region_actors = []
        vtk_widget._3d_cursor_region_actors.extend(all_actors)

        # Render
        renderer.ResetCameraClippingRange()
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

        print(f"[3D-Cursor][REGION] Drew perpendicular strip through target: "
              f"target=({target_x:.0f},{target_y:.0f})px width={2*half_width_px:.0f}px "
              f"span={2*band_half_height:.0f}px depth={arc.radius_mm:.1f}mm halo_layers={RECT_HALO_LAYERS}")

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw distance rectangle: {e}")


def _draw_distance_rectangle_fallback(
    vtk_widget,
    center_px: tuple,
    radius_mm: float,
    nipple_px: tuple,
    pixel_spacing_x: float,
    pixel_spacing_y: float,
):
    """
    Fallback: Draw a full-height rectangle when no arc data is available.
    Uses center_px as the target x-position for the rectangle.
    """
    try:
        import vtk as _vtk
    except ImportError:
        return

    try:
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return

        renderer = getattr(image_viewer, 'renderer', None)
        if renderer is None:
            return

        ijk_to_world = getattr(image_viewer, 'ijk_to_world', None)
        if ijk_to_world is None:
            return

        # Get image height
        img_height = 0
        metadata = getattr(image_viewer, 'metadata', None)
        if metadata:
            instances = metadata.get('instances', [])
            if instances:
                first_inst = instances[0] if isinstance(instances, list) else {}
                img_height = first_inst.get('rows', 0) or 0
        if not img_height:
            try:
                vtk_data = image_viewer.GetInput()
                if vtk_data:
                    dims = vtk_data.GetDimensions()
                    img_height = dims[1]
            except Exception:
                pass
        if img_height <= 0:
            img_height = 4000

        cx, cy = center_px
        avg_spacing = (pixel_spacing_x + pixel_spacing_y) / 2.0
        half_width_px = (
            max(30.0, (RECT_BAND_WIDTH_MM / 2.0) / avg_spacing)
            if avg_spacing > 0 else 30.0
        )

        # Rectangle at the target x-position, full image height
        x_left = cx - half_width_px
        x_right = cx + half_width_px
        y_top = 0.0
        y_bottom = float(img_height)

        corners_px = [
            (x_left, y_top),
            (x_right, y_top),
            (x_right, y_bottom),
            (x_left, y_bottom),
        ]

        vtk_points = _vtk.vtkPoints()
        for px, py in corners_px:
            world_pt = ijk_to_world(px, py, None, y_flip=True)
            vtk_points.InsertNextPoint(world_pt)

        polygon = _vtk.vtkPolygon()
        polygon.GetPointIds().SetNumberOfIds(4)
        for i in range(4):
            polygon.GetPointIds().SetId(i, i)

        cells = _vtk.vtkCellArray()
        cells.InsertNextCell(polygon)

        poly_data = _vtk.vtkPolyData()
        poly_data.SetPoints(vtk_points)
        poly_data.SetPolys(cells)

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly_data)

        rect_actor = _vtk.vtkActor()
        rect_actor.SetMapper(mapper)
        rect_actor.GetProperty().SetColor(*RECT_COLOR)
        rect_actor.GetProperty().SetOpacity(RECT_OPACITY)
        rect_actor.GetProperty().LightingOff()
        renderer.AddActor(rect_actor)

        # Track actors
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.append(rect_actor)

        if not hasattr(vtk_widget, '_3d_cursor_region_actors'):
            vtk_widget._3d_cursor_region_actors = []
        vtk_widget._3d_cursor_region_actors.append(rect_actor)

        # Render
        renderer.ResetCameraClippingRange()
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

        print(f"[3D-Cursor][REGION] Drew full-height rectangle (fallback): "
              f"center=({cx:.0f},{cy:.0f}) width={2*half_width_px:.0f}px height={img_height}px")

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw distance rectangle (fallback): {e}")


def _draw_region_box_on_widget(
    vtk_widget,
    center_px: tuple,
    radius_mm: float,
    pixel_spacing_x: float,
    pixel_spacing_y: float,
):
    """
    Fallback: Draw a radial sector region when no arc data is available.

    Uses the center_px as both nipple and target (draws a small sector outward).
    """
    try:
        import vtk as _vtk
    except ImportError:
        return

    try:
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return

        renderer = getattr(image_viewer, 'renderer', None)
        if renderer is None:
            return

        ijk_to_world = getattr(image_viewer, 'ijk_to_world', None)
        if ijk_to_world is None:
            return

        import math

        cx, cy = center_px
        avg_spacing = (pixel_spacing_x + pixel_spacing_y) / 2.0
        sector_radius = max(40.0, radius_mm * 0.5) / avg_spacing

        # Default: sector pointing downward (toward chest wall)
        center_angle = math.pi / 2.0
        half_spread = math.radians(SECTOR_ANGULAR_SPREAD_DEG) / 2.0

        num_angular_steps = 32
        all_actors = []

        for band_idx in range(NUM_RADIAL_BANDS):
            t_inner = band_idx / float(NUM_RADIAL_BANDS)
            t_outer = (band_idx + 1) / float(NUM_RADIAL_BANDS)

            inner_r = sector_radius * t_inner
            outer_r = sector_radius * t_outer

            r = COLOR_SECTOR_INNER[0] + (COLOR_SECTOR_OUTER[0] - COLOR_SECTOR_INNER[0]) * t_outer
            g = COLOR_SECTOR_INNER[1] + (COLOR_SECTOR_OUTER[1] - COLOR_SECTOR_INNER[1]) * t_outer
            b = COLOR_SECTOR_INNER[2] + (COLOR_SECTOR_OUTER[2] - COLOR_SECTOR_INNER[2]) * t_outer
            opacity = SECTOR_INNER_OPACITY + (SECTOR_OUTER_OPACITY - SECTOR_INNER_OPACITY) * t_outer

            outer_pts = []
            inner_pts = []
            for i in range(num_angular_steps + 1):
                t_angle = i / float(num_angular_steps)
                angle = center_angle - half_spread + t_angle * (2.0 * half_spread)
                outer_pts.append((cx + outer_r * math.cos(angle), cy + outer_r * math.sin(angle)))
                inner_pts.append((cx + inner_r * math.cos(angle), cy + inner_r * math.sin(angle)))

            polygon_pts_px = outer_pts + list(reversed(inner_pts))
            if len(polygon_pts_px) < 4:
                continue

            vtk_points = _vtk.vtkPoints()
            for px, py in polygon_pts_px:
                world_pt = ijk_to_world(px, py, None, y_flip=True)
                vtk_points.InsertNextPoint(world_pt)

            polygon = _vtk.vtkPolygon()
            polygon.GetPointIds().SetNumberOfIds(len(polygon_pts_px))
            for i in range(len(polygon_pts_px)):
                polygon.GetPointIds().SetId(i, i)

            cells = _vtk.vtkCellArray()
            cells.InsertNextCell(polygon)

            poly_data = _vtk.vtkPolyData()
            poly_data.SetPoints(vtk_points)
            poly_data.SetPolys(cells)

            mapper = _vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly_data)

            band_actor = _vtk.vtkActor()
            band_actor.SetMapper(mapper)
            band_actor.GetProperty().SetColor(r, g, b)
            band_actor.GetProperty().SetOpacity(opacity)
            band_actor.GetProperty().LightingOff()

            renderer.AddActor(band_actor)
            all_actors.append(band_actor)

        # Track actors
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.extend(all_actors)

        if not hasattr(vtk_widget, '_3d_cursor_region_actors'):
            vtk_widget._3d_cursor_region_actors = []
        vtk_widget._3d_cursor_region_actors.extend(all_actors)

        # Render
        renderer.ResetCameraClippingRange()
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

        print(f"[3D-Cursor][REGION] Drew radial sector (fallback): "
              f"center=({cx:.0f},{cy:.0f}) radius={sector_radius:.0f}px")

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw region box: {e}")


def _clear_projected_actors(vtk_widget):
    """Remove previously drawn projected actors from a widget."""
    try:
        actors = getattr(vtk_widget, '_projected_actors', None)
        if not actors:
            vtk_widget._projected_actors = []
            return

        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is not None:
            remove_fn = getattr(image_viewer, 'remove_actors', None) or \
                        getattr(image_viewer, 'remove_actor', None)
            if remove_fn:
                for a in actors:
                    try:
                        remove_fn(a)
                    except Exception:
                        pass

        vtk_widget._projected_actors = []
    except Exception:
        pass


# ─── Ruler / Distance Measurement Visualization ─────────────────────────────

def draw_rulers_for_results(
    result: Cursor3DResult,
    views_by_key: Dict[str, ViewData],
):
    """
    Draw ruler lines from nipple to each lesion center on all relevant viewers.

    For each cursor match, draws:
        - Source view: ruler from nipple → lesion center, labeled with depth_mm
        - Target view: ruler from nipple → projected lesion, labeled with depth_mm

    This allows visual verification that the computed mm distances are correct.
    """
    for laterality, lat_result in result.lateralities.items():
        _draw_laterality_rulers(laterality, lat_result, views_by_key)


def _draw_laterality_rulers(
    laterality: str,
    lat_result: LateralityResult,
    views_by_key: Dict[str, ViewData],
):
    """Draw ruler annotations for all cursors in one laterality."""
    cc_key = f"{laterality}_CC"
    mlo_key = f"{laterality}_MLO"

    cc_view = views_by_key.get(cc_key)
    mlo_view = views_by_key.get(mlo_key)
    cc_geom = lat_result.cc_geometry
    mlo_geom = lat_result.mlo_geometry

    for match in lat_result.cursor_matches:
        if match.match_type == 'out_of_field':
            continue

        # Determine source and target views/geometries
        if match.source_view == 'CC':
            src_view_data = cc_view
            src_geom = cc_geom
            tgt_view_data = mlo_view
            tgt_geom = mlo_geom
        else:
            src_view_data = mlo_view
            src_geom = mlo_geom
            tgt_view_data = cc_view
            tgt_geom = cc_geom

        # For 'paired' matches: both views already have AI boxes → no new BOXES,
        # but still draw rulers on both views so user can verify depth measurement.

        # Draw ruler on source view (nipple → source lesion center)
        if src_view_data and src_view_data.vtk_widget and src_geom:
            _draw_ruler_on_widget(
                vtk_widget=src_view_data.vtk_widget,
                nipple_px=(src_geom.nipple.x_px, src_geom.nipple.y_px),
                lesion_center_px=match.source_lesion.center_px,
                distance_mm=match.depth_mm,
                label_prefix=f"{match.source_view}",
            )

        # Draw ruler on target view (nipple → projected/paired lesion)
        if match.target_lesion and tgt_view_data and tgt_view_data.vtk_widget and tgt_geom:
            _draw_ruler_on_widget(
                vtk_widget=tgt_view_data.vtk_widget,
                nipple_px=(tgt_geom.nipple.x_px, tgt_geom.nipple.y_px),
                lesion_center_px=match.target_lesion.center_px,
                distance_mm=match.depth_mm,
                label_prefix=f"{match.target_view}",
            )


def _draw_ruler_on_widget(
    vtk_widget,
    nipple_px: tuple,
    lesion_center_px: tuple,
    distance_mm: float,
    label_prefix: str = "",
):
    """
    Draw a ruler line from nipple to lesion center on one viewer widget,
    with a text label showing the distance in mm.

    Uses VTK actors (line + follower text) in the image_viewer's renderer.
    """
    try:
        import vtk as _vtk
    except ImportError:
        return

    try:
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return

        renderer = getattr(image_viewer, 'renderer', None)
        if renderer is None:
            return

        # Convert pixel coords to world coords using image_viewer.ijk_to_world
        ijk_to_world = getattr(image_viewer, 'ijk_to_world', None)
        if ijk_to_world is None:
            return

        # Nipple world position
        p_nipple = ijk_to_world(nipple_px[0], nipple_px[1], None, y_flip=True)
        # Lesion center world position
        p_lesion = ijk_to_world(lesion_center_px[0], lesion_center_px[1], None, y_flip=True)

        # ── Create dashed ruler line ──
        line_source = _vtk.vtkLineSource()
        line_source.SetPoint1(p_nipple)
        line_source.SetPoint2(p_lesion)
        line_source.SetResolution(20)  # segments for dash effect
        line_source.Update()

        line_mapper = _vtk.vtkPolyDataMapper()
        line_mapper.SetInputConnection(line_source.GetOutputPort())

        line_actor = _vtk.vtkActor()
        line_actor.SetMapper(line_mapper)
        line_prop = line_actor.GetProperty()
        line_prop.SetColor(COLOR_RULER[0], COLOR_RULER[1], COLOR_RULER[2])
        line_prop.SetLineWidth(2.0)
        line_prop.SetLineStipplePattern(0xF0F0)  # dashed pattern
        line_prop.SetLineStippleRepeatFactor(1)
        line_prop.SetOpacity(0.85)

        renderer.AddActor(line_actor)

        # ── Create small circle markers at endpoints ──
        for p_world in [p_nipple, p_lesion]:
            marker = _vtk.vtkSphereSource()
            marker.SetCenter(p_world)
            marker.SetRadius(2.0)
            marker.SetPhiResolution(8)
            marker.SetThetaResolution(8)
            marker.Update()

            marker_mapper = _vtk.vtkPolyDataMapper()
            marker_mapper.SetInputConnection(marker.GetOutputPort())

            marker_actor = _vtk.vtkActor()
            marker_actor.SetMapper(marker_mapper)
            marker_actor.GetProperty().SetColor(COLOR_RULER[0], COLOR_RULER[1], COLOR_RULER[2])
            marker_actor.GetProperty().SetOpacity(0.9)
            renderer.AddActor(marker_actor)

            # Track for cleanup
            if not hasattr(vtk_widget, '_projected_actors'):
                vtk_widget._projected_actors = []
            vtk_widget._projected_actors.append(marker_actor)

        # ── Create text label at midpoint ──
        mid_x = (p_nipple[0] + p_lesion[0]) / 2.0
        mid_y = (p_nipple[1] + p_lesion[1]) / 2.0
        mid_z = (p_nipple[2] + p_lesion[2]) / 2.0

        label_text = f"{distance_mm:.1f} mm"
        if label_prefix:
            label_text = f"{label_prefix}: {distance_mm:.1f} mm"

        text_source = _vtk.vtkVectorText()
        text_source.SetText(label_text)

        text_extrude = _vtk.vtkLinearExtrusionFilter()
        text_extrude.SetInputConnection(text_source.GetOutputPort())
        text_extrude.SetExtrusionTypeToNormalExtrusion()
        text_extrude.SetVector(0, 0, 1)
        text_extrude.SetScaleFactor(0.5)

        text_mapper = _vtk.vtkPolyDataMapper()
        text_mapper.SetInputConnection(text_extrude.GetOutputPort())

        text_actor = _vtk.vtkFollower()
        text_actor.SetMapper(text_mapper)
        text_actor.SetScale(4.0, 4.0, 4.0)
        # Position slightly above midpoint of the line
        text_actor.SetPosition(mid_x, mid_y + 4.0, mid_z)
        text_actor.GetProperty().SetColor(
            COLOR_RULER_TEXT[0], COLOR_RULER_TEXT[1], COLOR_RULER_TEXT[2]
        )

        camera = renderer.GetActiveCamera()
        if camera:
            text_actor.SetCamera(camera)

        renderer.AddActor(text_actor)

        # Track all actors for cleanup
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.append(line_actor)
        vtk_widget._projected_actors.append(text_actor)

        # Render update
        renderer.ResetCameraClippingRange()
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw ruler: {e}")


def format_3d_cursor_summary(result: Cursor3DResult) -> str:
    """
    Format a human-readable text summary of the 3D cursor results.

    Returns multiline text suitable for display in the feature panel.
    """
    lines = ["═══ 3D Cursor — CC/MLO Correlation Results ═══", ""]

    if not result.lateralities:
        lines.append("No valid CC/MLO pairs found for 3D cursor analysis.")
        lines.append("")
        lines.append("Ensure:")
        lines.append("  • AI detection has been run for this study.")
        lines.append("  • Both CC and MLO views are available.")
        lines.append("  • DICOM Pixel Spacing metadata is present.")
        return "\n".join(lines)

    for laterality, lat_result in result.lateralities.items():
        lines.append(f"▶ Breast: {laterality} ({'Right' if laterality == 'R' else 'Left'})")
        lines.append(f"  Total 3D Cursors: {lat_result.total_cursors}")
        lines.append(f"  Paired (both views): {lat_result.paired_count}")
        lines.append(f"  Projected (single view): {lat_result.projected_count}")
        if lat_result.out_of_field_count > 0:
            lines.append(f"  Out of Field: {lat_result.out_of_field_count}")

        # Show nipple positions used for measurements
        if lat_result.cc_geometry:
            n = lat_result.cc_geometry.nipple
            lines.append(f"  CC  nipple: pixel ({n.x_px:.0f}, {n.y_px:.0f})"
                         f" = ({n.x_mm:.1f}, {n.y_mm:.1f}) mm"
                         f" [{'detected' if n.detected else 'estimated'}]")
        if lat_result.mlo_geometry:
            n = lat_result.mlo_geometry.nipple
            lines.append(f"  MLO nipple: pixel ({n.x_px:.0f}, {n.y_px:.0f})"
                         f" = ({n.x_mm:.1f}, {n.y_mm:.1f}) mm"
                         f" [{'detected' if n.detected else 'estimated'}]")
        lines.append("")

        for i, match in enumerate(lat_result.cursor_matches, 1):
            lines.append(f"  Cursor #{i} [{match.match_type}]:")
            lines.append(f"    Depth from nipple: {match.depth_mm:.1f} mm")

            if match.match_type == 'paired':
                lines.append(f"    Depth difference between views: {match.depth_difference_mm:.1f} mm")
                lines.append(f"    Confidence: {match.confidence:.0%}")
                src_box = match.source_lesion.to_pixel_box()
                tgt_box = match.target_lesion.to_pixel_box() if match.target_lesion else None
                lines.append(f"    {match.source_view}: [{src_box[0]:.0f}, {src_box[1]:.0f}, "
                             f"{src_box[2]:.0f}, {src_box[3]:.0f}]")
                if tgt_box:
                    lines.append(f"    {match.target_view}: [{tgt_box[0]:.0f}, {tgt_box[1]:.0f}, "
                                 f"{tgt_box[2]:.0f}, {tgt_box[3]:.0f}]")

            elif match.match_type in ('projected', 'arc_projected'):
                src_box = match.source_lesion.to_pixel_box()
                lines.append(f"    Detected in: {match.source_view} "
                             f"[{src_box[0]:.0f}, {src_box[1]:.0f}, "
                             f"{src_box[2]:.0f}, {src_box[3]:.0f}]")
                if match.correspondence_arc and match.correspondence_arc.arc_points_px:
                    arc = match.correspondence_arc
                    lines.append(f"    ➜ Region highlighted in {match.target_view}:")
                    lines.append(f"      Radius: {arc.radius_mm:.1f} mm from nipple")
                    lines.append(f"      Arc span: {len(arc.arc_points_px)} points")
                    lines.append(f"      Probable lesion zone shown as blue gradient circle")
                elif match.target_lesion:
                    tgt_box = match.target_lesion.to_pixel_box()
                    lines.append(f"    ➜ Region in {match.target_view}: "
                                 f"[{tgt_box[0]:.0f}, {tgt_box[1]:.0f}, "
                                 f"{tgt_box[2]:.0f}, {tgt_box[3]:.0f}]")
                lines.append(f"    Confidence: {match.confidence:.0%}")
                lines.append(f"    💡 Use 'Hide Boxes' to show/hide the region")

            elif match.match_type == 'out_of_field':
                lines.append(f"    ⚠ {match.message}")

            lines.append("")

    return "\n".join(lines)


# ─── Correspondence Arc Visualization with Annotations ──────────────────────

def draw_correspondence_arc_with_annotations(
    match: CursorMatch,
    view_data: ViewData,
    laterality: str,
    *,
    show_angle_annotations: bool = True,
    show_info_box: bool = True,
    show_formula: bool = True,
):
    """
    Draw the correspondence arc on the target view with complete annotations.

    This function provides a comprehensive visualization of the arc-based
    projection algorithm, showing:
        1. The correspondence arc itself (curve of possible lesion locations)
        2. Angular annotations (start angle, end angle, center angle)
        3. Radial lines showing the angular bounds
        4. An information box with formulas and calculated values

    Args:
        match: CursorMatch containing the correspondence_arc field.
        view_data: ViewData for the target view where arc is drawn.
        laterality: 'R' or 'L'
        show_angle_annotations: If True, draw angle markers and labels.
        show_info_box: If True, draw a text box with calculations.
        show_formula: If True, include mathematical formulas in the info box.

    Physical Interpretation:
        The arc represents the locus of points in the target view that are
        equidistant (in 3D breast space) from the nipple. For CC→MLO projection:
            - Arc center: nipple position in MLO
            - Arc radius: distance from nipple in CC (preserved by Kopans' Rule)
            - Angular range: constrained by pectoral muscle angle and anatomy

    Example Usage:
        ```python
        # After computing correspondence arc
        for match in cursor_matches:
            if match.match_type == 'arc_projected' and match.correspondence_arc:
                target_key = f"{laterality}_{match.target_view}"
                target_view = views_by_key.get(target_key)
                if target_view:
                    draw_correspondence_arc_with_annotations(
                        match, target_view, laterality
                    )
        ```
    """
    if match.correspondence_arc is None:
        return

    arc = match.correspondence_arc
    vtk_widget = view_data.vtk_widget
    if vtk_widget is None:
        return

    try:
        # Get VTK components
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return

        renderer = getattr(image_viewer, 'renderer', None)
        if renderer is None:
            return

        ijk_to_world = getattr(image_viewer, 'ijk_to_world', None)
        if ijk_to_world is None:
            return

        # ── 1. Draw the Correspondence Arc ──
        _draw_arc_curve(arc, ijk_to_world, renderer)

        # ── 2. Draw Angular Annotations ──
        if show_angle_annotations:
            _draw_arc_angle_annotations(arc, ijk_to_world, renderer)

        # ── 3. Draw Information Box ──
        if show_info_box:
            _draw_arc_info_box(
                arc, match, view_data, renderer,
                show_formula=show_formula
            )

        # ── 4. Highlight Best Point ──
        if arc.best_point_px is not None:
            _draw_best_point_marker(arc.best_point_px, ijk_to_world, renderer)

        # Render update
        renderer.ResetCameraClippingRange()
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw correspondence arc: {e}")


def _draw_arc_curve(arc, ijk_to_world, renderer):
    """Draw the correspondence arc as a smooth curve on the image."""
    import vtk as _vtk

    if not arc.arc_points_px:
        return

    # Create polyline for the arc
    points = _vtk.vtkPoints()
    lines = _vtk.vtkCellArray()

    # Convert pixel points to world coordinates
    world_points = []
    for px, py in arc.arc_points_px:
        pw = ijk_to_world(px, py, None, y_flip=True)
        world_points.append(pw)
        points.InsertNextPoint(pw)

    # Create line segments
    n_points = len(world_points)
    for i in range(n_points - 1):
        line = _vtk.vtkLine()
        line.GetPointIds().SetId(0, i)
        line.GetPointIds().SetId(1, i + 1)
        lines.InsertNextCell(line)

    # Build polydata
    polydata = _vtk.vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetLines(lines)

    # Create tube filter for thick arc
    tube = _vtk.vtkTubeFilter()
    tube.SetInputData(polydata)
    tube.SetRadius(1.5)
    tube.SetNumberOfSides(8)
    tube.Update()

    # Mapper and actor
    mapper = _vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(tube.GetOutputPort())

    actor = _vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(0.0, 0.8, 1.0)  # Cyan
    actor.GetProperty().SetOpacity(0.8)

    renderer.AddActor(actor)


def _draw_arc_angle_annotations(arc, ijk_to_world, renderer):
    """Draw angular annotations showing the arc bounds and center."""
    import vtk as _vtk
    import math

    if not arc.arc_points_px:
        return

    # Arc center in world coordinates
    center_world = ijk_to_world(arc.center_x_px, arc.center_y_px, None, y_flip=True)

    # ── Draw radial lines for start, center, and end angles ──
    angles_to_draw = [
        (arc.start_angle_rad, 'Start', (0.2, 1.0, 0.2)),  # Green
        ((arc.start_angle_rad + arc.end_angle_rad) / 2, 'Center', (1.0, 1.0, 0.2)),  # Yellow
        (arc.end_angle_rad, 'End', (1.0, 0.2, 0.2)),  # Red
    ]

    for angle_rad, label, color in angles_to_draw:
        # Calculate endpoint of radial line
        # Note: VTK world coordinates may have different orientation
        radius_world = arc.radius_px * 0.8  # Slightly shorter than arc radius
        dx = radius_world * math.cos(angle_rad)
        dy = radius_world * math.sin(angle_rad)
        
        # Need to convert this displacement correctly using ijk_to_world
        # For simplicity, we approximate using the first arc point direction
        end_px = (
            arc.center_x_px + dx,
            arc.center_y_px + dy
        )
        end_world = ijk_to_world(end_px[0], end_px[1], None, y_flip=True)

        # Create line
        line_source = _vtk.vtkLineSource()
        line_source.SetPoint1(center_world)
        line_source.SetPoint2(end_world)
        line_source.Update()

        line_mapper = _vtk.vtkPolyDataMapper()
        line_mapper.SetInputConnection(line_source.GetOutputPort())

        line_actor = _vtk.vtkActor()
        line_actor.SetMapper(line_mapper)
        line_actor.GetProperty().SetColor(color[0], color[1], color[2])
        line_actor.GetProperty().SetLineWidth(2.0)
        line_actor.GetProperty().SetOpacity(0.7)

        renderer.AddActor(line_actor)

        # Add text label
        angle_deg = math.degrees(angle_rad)
        text = f"{label}\n{angle_deg:.1f}°"
        _add_text_label(text, end_world, renderer, color)


def _draw_arc_info_box(arc, match, view_data, renderer, show_formula=True):
    """Draw an information box with formulas and calculated values."""
    import vtk as _vtk
    import math

    # Build text content
    lines = []
    lines.append("══ Correspondence Arc ══")
    lines.append("")
    
    if show_formula:
        lines.append("Physical Principle:")
        lines.append("d_CC = d_MLO  (Kopans' Rule)")
        lines.append("where d = √(X² + Y²)")
        lines.append("")

    lines.append(f"Radius: {arc.radius_mm:.1f} mm")
    lines.append(f"        ({arc.radius_px:.1f} px)")
    lines.append("")
    
    # Angular information
    start_deg = math.degrees(arc.start_angle_rad)
    end_deg = math.degrees(arc.end_angle_rad)
    span_deg = abs(end_deg - start_deg)
    
    lines.append(f"Angular Range:")
    lines.append(f"  Start:  {start_deg:.1f}°")
    lines.append(f"  End:    {end_deg:.1f}°")
    lines.append(f"  Span:   {span_deg:.1f}°")
    lines.append("")

    # Arc statistics
    total_points = len(arc.arc_points_px)
    valid_points = len(arc.arc_points_px)  # Already clipped
    
    lines.append(f"Arc Points: {valid_points}")
    lines.append(f"Confidence: {arc.confidence:.1%}")
    lines.append("")

    # View information
    lines.append(f"Source: {match.source_view}")
    lines.append(f"Target: {match.target_view}")

    if show_formula and match.target_view == 'MLO':
        lines.append("")
        lines.append("MLO Projection:")
        lines.append("H = Y·sin(θ) + Z·cos(θ)")
        lines.append(f"  θ_pec ≈ {arc.message.split('pectoral')[1].split('°')[0] if 'pectoral' in arc.message else 'N/A'}°")

    # Create text actor
    text_content = "\n".join(lines)
    text_actor = _vtk.vtkTextActor()
    text_actor.SetInput(text_content)
    
    # Position in upper-left corner
    text_actor.SetDisplayPosition(20, 20)
    
    # Style the text
    text_prop = text_actor.GetTextProperty()
    text_prop.SetFontFamilyToArial()
    text_prop.SetFontSize(12)
    text_prop.SetColor(1.0, 1.0, 1.0)  # White text
    text_prop.SetBold(False)
    text_prop.SetShadow(True)
    text_prop.SetShadowOffset(1, -1)
    
    # Background rectangle
    text_actor.GetPositionCoordinate().SetCoordinateSystemToDisplay()
    text_actor.GetPosition2Coordinate().SetCoordinateSystemToDisplay()
    
    # Enable background
    if hasattr(text_prop, 'SetBackgroundColor'):
        text_prop.SetBackgroundColor(0.1, 0.1, 0.1)  # Dark gray
        text_prop.SetBackgroundOpacity(0.85)
    
    renderer.AddActor2D(text_actor)


def _draw_best_point_marker(best_point_px, ijk_to_world, renderer):
    """Draw a highlighted marker at the best projection point."""
    import vtk as _vtk

    px, py = best_point_px
    world_pos = ijk_to_world(px, py, None, y_flip=True)

    # Create sphere marker
    sphere = _vtk.vtkSphereSource()
    sphere.SetCenter(world_pos)
    sphere.SetRadius(4.0)
    sphere.SetPhiResolution(16)
    sphere.SetThetaResolution(16)
    sphere.Update()

    mapper = _vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(sphere.GetOutputPort())

    actor = _vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(1.0, 0.8, 0.0)  # Gold
    actor.GetProperty().SetOpacity(1.0)

    renderer.AddActor(actor)


def _add_text_label(text, world_pos, renderer, color=(1.0, 1.0, 1.0)):
    """Add a 3D text label at a world position."""
    import vtk as _vtk

    # Create follower text (always faces camera)
    text_actor = _vtk.vtkFollower()
    
    # Create vectorText
    text_source = _vtk.vtkVectorText()
    text_source.SetText(text)
    text_source.Update()

    mapper = _vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(text_source.GetOutputPort())

    text_actor.SetMapper(mapper)
    text_actor.SetPosition(world_pos)
    text_actor.SetScale(8.0, 8.0, 8.0)
    text_actor.GetProperty().SetColor(color[0], color[1], color[2])
    
    # Make text follow camera
    camera = renderer.GetActiveCamera()
    if camera:
        text_actor.SetCamera(camera)

    renderer.AddActor(text_actor)


# ─── Lesion-to-Lesion Ruler Visualization ───────────────────────────────────

def draw_lesion_to_lesion_rulers(
    result: Cursor3DResult,
    views_by_key: Dict[str, ViewData],
    *,
    draw_on_paired: bool = True,
    draw_on_projected: bool = False,
):
    """
    Draw ruler lines between lesions on the same view, showing inter-lesion distances.

    This function draws orange rulers between lesions detected on the same mammogram view,
    allowing clinicians to measure distances between multiple findings.

    Args:
        result: The computed Cursor3DResult containing all cursor matches.
        views_by_key: Dict mapping "{laterality}_{view}" to ViewData.
        draw_on_paired: If True, draw rulers between paired lesions on each view.
        draw_on_projected: If True, also draw rulers involving projected lesions.

    Note:
        Rulers are drawn between lesion centers (not nipple), using pixel-to-mm
        conversion from the image geometry.
    """
    for laterality, lat_result in result.lateralities.items():
        _draw_laterality_lesion_rulers(
            laterality,
            lat_result,
            views_by_key,
            draw_on_paired=draw_on_paired,
            draw_on_projected=draw_on_projected,
        )


def _draw_laterality_lesion_rulers(
    laterality: str,
    lat_result: LateralityResult,
    views_by_key: Dict[str, ViewData],
    draw_on_paired: bool = True,
    draw_on_projected: bool = False,
):
    """Draw lesion-to-lesion rulers for one laterality."""
    cc_key = f"{laterality}_CC"
    mlo_key = f"{laterality}_MLO"

    cc_view = views_by_key.get(cc_key)
    mlo_view = views_by_key.get(mlo_key)
    cc_geom = lat_result.cc_geometry
    mlo_geom = lat_result.mlo_geometry

    # Collect lesions on each view
    cc_lesions = []
    mlo_lesions = []

    for match in lat_result.cursor_matches:
        # Skip out-of-field matches
        if match.match_type == 'out_of_field':
            continue

        # Skip projected matches if not requested
        if match.match_type == 'projected' and not draw_on_projected:
            continue

        # Collect lesions by view
        if match.source_view == 'CC':
            cc_lesions.append(match.source_lesion)
            if match.target_lesion and (draw_on_paired or match.match_type == 'projected'):
                mlo_lesions.append(match.target_lesion)
        else:  # source_view == 'MLO'
            mlo_lesions.append(match.source_lesion)
            if match.target_lesion and (draw_on_paired or match.match_type == 'projected'):
                cc_lesions.append(match.target_lesion)

    # Draw rulers between lesions on CC view
    if cc_view and cc_view.vtk_widget and cc_geom and len(cc_lesions) >= 2:
        for i in range(len(cc_lesions)):
            for j in range(i + 1, len(cc_lesions)):
                _draw_lesion_ruler(
                    vtk_widget=cc_view.vtk_widget,
                    lesion1_center_px=cc_lesions[i].center_px,
                    lesion2_center_px=cc_lesions[j].center_px,
                    pixel_spacing=cc_geom.image.pixel_spacing,
                    label_prefix="CC",
                )

    # Draw rulers between lesions on MLO view
    if mlo_view and mlo_view.vtk_widget and mlo_geom and len(mlo_lesions) >= 2:
        for i in range(len(mlo_lesions)):
            for j in range(i + 1, len(mlo_lesions)):
                _draw_lesion_ruler(
                    vtk_widget=mlo_view.vtk_widget,
                    lesion1_center_px=mlo_lesions[i].center_px,
                    lesion2_center_px=mlo_lesions[j].center_px,
                    pixel_spacing=mlo_geom.image.pixel_spacing,
                    label_prefix="MLO",
                )


def _draw_lesion_ruler(
    vtk_widget,
    lesion1_center_px: tuple,
    lesion2_center_px: tuple,
    pixel_spacing,
    label_prefix: str = "",
):
    """
    Draw a ruler line between two lesion centers on one viewer widget.

    Args:
        vtk_widget: The VTK widget to draw on.
        lesion1_center_px: (x, y) pixel coordinates of first lesion center.
        lesion2_center_px: (x, y) pixel coordinates of second lesion center.
        pixel_spacing: PixelSpacing object for px→mm conversion.
        label_prefix: Optional prefix for the distance label (e.g., "CC", "MLO").
    """
    try:
        import vtk as _vtk
    except ImportError:
        return

    try:
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return

        renderer = getattr(image_viewer, 'renderer', None)
        if renderer is None:
            return

        # Convert pixel coords to world coords
        ijk_to_world = getattr(image_viewer, 'ijk_to_world', None)
        if ijk_to_world is None:
            return

        # Lesion world positions
        p1 = ijk_to_world(lesion1_center_px[0], lesion1_center_px[1], None, y_flip=True)
        p2 = ijk_to_world(lesion2_center_px[0], lesion2_center_px[1], None, y_flip=True)

        # Calculate distance in mm
        dx_px = lesion2_center_px[0] - lesion1_center_px[0]
        dy_px = lesion2_center_px[1] - lesion1_center_px[1]
        distance_px = (dx_px**2 + dy_px**2)**0.5
        distance_mm = distance_px * ((pixel_spacing.col_mm + pixel_spacing.row_mm) / 2.0)

        # ── Create solid ruler line (not dashed) ──
        line_source = _vtk.vtkLineSource()
        line_source.SetPoint1(p1)
        line_source.SetPoint2(p2)
        line_source.Update()

        line_mapper = _vtk.vtkPolyDataMapper()
        line_mapper.SetInputConnection(line_source.GetOutputPort())

        line_actor = _vtk.vtkActor()
        line_actor.SetMapper(line_mapper)
        line_prop = line_actor.GetProperty()
        line_prop.SetColor(COLOR_LESION_RULER[0], COLOR_LESION_RULER[1], COLOR_LESION_RULER[2])
        line_prop.SetLineWidth(3.0)  # Thicker than nipple ruler
        line_prop.SetOpacity(0.9)

        renderer.AddActor(line_actor)

        # ── Create diamond markers at endpoints ──
        for p_world in [p1, p2]:
            # Use cone for diamond-like appearance
            marker = _vtk.vtkConeSource()
            marker.SetCenter(p_world)
            marker.SetRadius(2.5)
            marker.SetHeight(5.0)
            marker.SetResolution(4)  # 4 sides = diamond shape
            marker.SetDirection(0, 0, 1)
            marker.Update()

            marker_mapper = _vtk.vtkPolyDataMapper()
            marker_mapper.SetInputConnection(marker.GetOutputPort())

            marker_actor = _vtk.vtkActor()
            marker_actor.SetMapper(marker_mapper)
            marker_actor.GetProperty().SetColor(
                COLOR_LESION_RULER[0], COLOR_LESION_RULER[1], COLOR_LESION_RULER[2]
            )
            marker_actor.GetProperty().SetOpacity(1.0)
            renderer.AddActor(marker_actor)

            # Track for cleanup
            if not hasattr(vtk_widget, '_projected_actors'):
                vtk_widget._projected_actors = []
            vtk_widget._projected_actors.append(marker_actor)

        # ── Create text label at midpoint ──
        mid_x = (p1[0] + p2[0]) / 2.0
        mid_y = (p1[1] + p2[1]) / 2.0
        mid_z = (p1[2] + p2[2]) / 2.0

        label_text = f"↔ {distance_mm:.1f} mm"
        if label_prefix:
            label_text = f"{label_prefix} {label_text}"

        text_source = _vtk.vtkVectorText()
        text_source.SetText(label_text)

        text_extrude = _vtk.vtkLinearExtrusionFilter()
        text_extrude.SetInputConnection(text_source.GetOutputPort())
        text_extrude.SetExtrusionTypeToNormalExtrusion()
        text_extrude.SetVector(0, 0, 1)
        text_extrude.SetScaleFactor(0.5)

        text_mapper = _vtk.vtkPolyDataMapper()
        text_mapper.SetInputConnection(text_extrude.GetOutputPort())

        text_actor = _vtk.vtkFollower()
        text_actor.SetMapper(text_mapper)
        text_actor.SetScale(4.5, 4.5, 4.5)
        # Position slightly above midpoint of the line
        text_actor.SetPosition(mid_x, mid_y + 5.0, mid_z)
        text_actor.GetProperty().SetColor(
            COLOR_LESION_RULER_TEXT[0], COLOR_LESION_RULER_TEXT[1], COLOR_LESION_RULER_TEXT[2]
        )

        camera = renderer.GetActiveCamera()
        if camera:
            text_actor.SetCamera(camera)

        renderer.AddActor(text_actor)

        # Track all actors for cleanup
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.append(line_actor)
        vtk_widget._projected_actors.append(text_actor)

        # Render update
        renderer.ResetCameraClippingRange()
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw lesion-to-lesion ruler: {e}")


def draw_custom_ruler(
    vtk_widget,
    point1_px: tuple,
    point2_px: tuple,
    pixel_spacing,
    *,
    label: str = None,
    color: tuple = None,
    line_width: float = 3.0,
):
    """
    Draw a custom ruler between any two points on a viewer widget.

    This is a general-purpose ruler function that can be used to measure
    distance between any two arbitrary points on a mammogram view.

    Args:
        vtk_widget: The VTK widget to draw on.
        point1_px: (x, y) pixel coordinates of first point.
        point2_px: (x, y) pixel coordinates of second point.
        pixel_spacing: PixelSpacing object for px→mm conversion.
        label: Optional custom label text. If None, shows distance only.
        color: Optional (R, G, B) color tuple (0-1 range). If None, uses orange.
        line_width: Line thickness in pixels (default: 3.0).

    Returns:
        float: The measured distance in millimeters.

    Example:
        >>> # Draw ruler from point A (100, 200) to point B (300, 400)
        >>> distance = draw_custom_ruler(
        ...     vtk_widget=viewer.vtk_widget,
        ...     point1_px=(100, 200),
        ...     point2_px=(300, 400),
        ...     pixel_spacing=geometry.image.pixel_spacing,
        ...     label="Custom Measurement",
        ...     color=(0.0, 1.0, 0.0),  # Green
        ... )
        >>> print(f"Measured: {distance:.1f} mm")
    """
    if color is None:
        color = COLOR_LESION_RULER

    try:
        import vtk as _vtk
    except ImportError:
        return 0.0

    try:
        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is None:
            return 0.0

        renderer = getattr(image_viewer, 'renderer', None)
        if renderer is None:
            return 0.0

        # Convert pixel coords to world coords
        ijk_to_world = getattr(image_viewer, 'ijk_to_world', None)
        if ijk_to_world is None:
            return 0.0

        p1 = ijk_to_world(point1_px[0], point1_px[1], None, y_flip=True)
        p2 = ijk_to_world(point2_px[0], point2_px[1], None, y_flip=True)

        # Calculate distance in mm
        dx_px = point2_px[0] - point1_px[0]
        dy_px = point2_px[1] - point1_px[1]
        distance_px = (dx_px**2 + dy_px**2)**0.5
        distance_mm = distance_px * ((pixel_spacing.col_mm + pixel_spacing.row_mm) / 2.0)

        # ── Create ruler line ──
        line_source = _vtk.vtkLineSource()
        line_source.SetPoint1(p1)
        line_source.SetPoint2(p2)
        line_source.Update()

        line_mapper = _vtk.vtkPolyDataMapper()
        line_mapper.SetInputConnection(line_source.GetOutputPort())

        line_actor = _vtk.vtkActor()
        line_actor.SetMapper(line_mapper)
        line_prop = line_actor.GetProperty()
        line_prop.SetColor(color[0], color[1], color[2])
        line_prop.SetLineWidth(line_width)
        line_prop.SetOpacity(0.9)

        renderer.AddActor(line_actor)

        # ── Create sphere markers at endpoints ──
        for p_world in [p1, p2]:
            marker = _vtk.vtkSphereSource()
            marker.SetCenter(p_world)
            marker.SetRadius(3.0)
            marker.SetPhiResolution(12)
            marker.SetThetaResolution(12)
            marker.Update()

            marker_mapper = _vtk.vtkPolyDataMapper()
            marker_mapper.SetInputConnection(marker.GetOutputPort())

            marker_actor = _vtk.vtkActor()
            marker_actor.SetMapper(marker_mapper)
            marker_actor.GetProperty().SetColor(color[0], color[1], color[2])
            marker_actor.GetProperty().SetOpacity(1.0)
            renderer.AddActor(marker_actor)

            # Track for cleanup
            if not hasattr(vtk_widget, '_projected_actors'):
                vtk_widget._projected_actors = []
            vtk_widget._projected_actors.append(marker_actor)

        # ── Create text label ──
        mid_x = (p1[0] + p2[0]) / 2.0
        mid_y = (p1[1] + p2[1]) / 2.0
        mid_z = (p1[2] + p2[2]) / 2.0

        if label:
            label_text = f"{label}: {distance_mm:.1f} mm"
        else:
            label_text = f"{distance_mm:.1f} mm"

        text_source = _vtk.vtkVectorText()
        text_source.SetText(label_text)

        text_extrude = _vtk.vtkLinearExtrusionFilter()
        text_extrude.SetInputConnection(text_source.GetOutputPort())
        text_extrude.SetExtrusionTypeToNormalExtrusion()
        text_extrude.SetVector(0, 0, 1)
        text_extrude.SetScaleFactor(0.5)

        text_mapper = _vtk.vtkPolyDataMapper()
        text_mapper.SetInputConnection(text_extrude.GetOutputPort())

        text_actor = _vtk.vtkFollower()
        text_actor.SetMapper(text_mapper)
        text_actor.SetScale(4.5, 4.5, 4.5)
        text_actor.SetPosition(mid_x, mid_y + 5.0, mid_z)
        # Use slightly lighter version of ruler color for text
        text_color = (
            min(1.0, color[0] + 0.3),
            min(1.0, color[1] + 0.3),
            min(1.0, color[2] + 0.3),
        )
        text_actor.GetProperty().SetColor(text_color[0], text_color[1], text_color[2])

        camera = renderer.GetActiveCamera()
        if camera:
            text_actor.SetCamera(camera)

        renderer.AddActor(text_actor)

        # Track all actors for cleanup
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.append(line_actor)
        vtk_widget._projected_actors.append(text_actor)

        # Render update
        renderer.ResetCameraClippingRange()
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

        return distance_mm

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw custom ruler: {e}")
        return 0.0

