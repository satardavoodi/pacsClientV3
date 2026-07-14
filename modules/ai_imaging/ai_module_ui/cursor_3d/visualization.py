"""
3D Cursor Visualization — Arc-based projected cursor rendering.

This module renders the correspondence ARC on mammogram viewers for
lesion localization between CC and MLO views.

NO rectangles are drawn. The visualization is exclusively arc-based:
    - Three concentric arcs (inner/nominal/outer) representing ±10% uncertainty.
    - A shaded uncertainty band between inner and outer arcs.
    - Ruler lines from nipple to lesion with mm distance labels.
    - Nipple and pectoral line markers.

The arc represents the geometric locus of all physically plausible
positions at the preserved nipple-to-lesion distance (Kopans' Rule).

All geometric computation is done in millimeters.
Pixel coordinates are used only at the final rendering step.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np

from .correlator import Cursor3DResult, CursorMatch, LateralityResult, ViewData
from .arc_probability import ArcProbabilityResult


# ─── Text Summary ────────────────────────────────────────────────────────────


def format_3d_cursor_summary(result: Cursor3DResult) -> str:
    """
    Format a Cursor3DResult into a human-readable text summary.

    Returns a multi-line string describing each laterality's matches,
    distances, and confidence.
    """
    lines = ["═══ 3D Cursor — CC/MLO Correlation ═══", ""]

    if not result.lateralities:
        lines.append("No correlations found.")
        return "\n".join(lines)

    for laterality, lat_result in result.lateralities.items():
        lines.append(f"── {laterality} Breast ──")

        if not lat_result.cursor_matches:
            lines.append("  No lesion matches.")
            lines.append("")
            continue

        for i, match in enumerate(lat_result.cursor_matches, 1):
            mtype = match.match_type
            src = match.source_view
            tgt = match.target_view
            depth = match.depth_mm

            if mtype == 'paired':
                lines.append(
                    f"  [{i}] PAIRED — Lesion found in both {src} and {tgt}"
                )
                lines.append(f"       Distance from nipple: {depth:.1f} mm")
            elif mtype in ('projected', 'arc_projected'):
                lines.append(
                    f"  [{i}] PROJECTED — Lesion in {src} → arc on {tgt}"
                )
                lines.append(f"       Distance from nipple: {depth:.1f} mm")
                if match.correspondence_arc:
                    arc = match.correspondence_arc
                    lower = arc.radius_mm * 0.90
                    upper = arc.radius_mm * 1.10
                    lines.append(
                        f"       Uncertainty band: {lower:.1f}–{upper:.1f} mm (±10%)"
                    )
                    lines.append(
                        f"       Arc confidence: {arc.confidence:.0%}"
                    )
            elif mtype == 'out_of_field':
                lines.append(
                    f"  [{i}] ⚠ خارج از ناحیه تصویر — Lesion in {src} projects outside {tgt}"
                )
                lines.append(f"       Distance from nipple: {depth:.1f} mm")
                lines.append(f"       (فاصله از نوک پستان خارج از محدوده تصویر است)")
            else:
                lines.append(f"  [{i}] {mtype.upper()} — {src} → {tgt}")
                lines.append(f"       Distance: {depth:.1f} mm")

            lines.append("")

    lines.append("═══════════════════════════════════════")
    return "\n".join(lines)


# ─── Colors ──────────────────────────────────────────────────────────────────

COLOR_PAIRED = (0.1, 0.4, 1.0)       # Blue — confirmed match in both views
COLOR_PROJECTED = (0.0, 0.5, 1.0)    # Blue — projected arc location
COLOR_OUT_OF_FIELD = (0.8, 0.2, 0.2) # Red — invalid projection (out of field)
COLOR_RULER = (0.0, 0.6, 1.0)        # Blue — ruler line (nipple to lesion)
COLOR_RULER_TEXT = (0.8, 0.95, 1.0)  # Light blue — distance label
COLOR_LESION_RULER = (1.0, 0.6, 0.0) # Orange — lesion-to-lesion ruler
COLOR_LESION_RULER_TEXT = (1.0, 0.9, 0.6)  # Light orange — distance label

# Arc visualization colors
ARC_NOMINAL_COLOR = (0.0, 0.7, 1.0)   # Cyan — nominal arc
ARC_INNER_COLOR = (0.0, 0.5, 0.9)     # Darker cyan — inner bound
ARC_OUTER_COLOR = (0.0, 0.5, 0.9)     # Darker cyan — outer bound
ARC_BAND_COLOR = (0.0, 0.6, 1.0)      # Cyan — uncertainty band fill
ARC_NOMINAL_OPACITY = 0.85
ARC_BOUND_OPACITY = 0.50
ARC_BAND_OPACITY = 0.12
ARC_NOMINAL_WIDTH = 3.0               # Line width for nominal arc
ARC_BOUND_WIDTH = 1.5                 # Line width for bound arcs

# Nipple / pectoral line marker colors
NIPPLE_MARKER_COLOR = (1.0, 0.3, 0.3)   # Red
PECTORAL_LINE_COLOR = (0.3, 1.0, 0.5)   # Green

# Angular parameters
ARC_ANGULAR_EXTENT_DEG = 140.0  # Angular span of the arc (centered on lesion)
ARC_NUM_SEGMENTS = 64            # Number of line segments per arc (smoothness)

# Arc offset / spacing parameters
ARC_RADIUS_OFFSET_PX = 25.0     # Extra pixels added to arc radius (clears lesion box)
ARC_BAND_SPACING_PX = 50.0      # Pixel spacing between inner/nominal/outer arcs
ARC_LABEL_OFFSET_PX = 22.0      # Label offset outside the outer arc


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
        views_by_key: Dict mapping "{laterality}_{view}" (e.g. "R_CC") to ViewData.
        draw_rulers: If True (default), also draw ruler lines with mm distance labels.
    """
    for laterality, lat_result in result.lateralities.items():
        _draw_laterality_results(laterality, lat_result, views_by_key)

    if draw_rulers:
        draw_rulers_for_results(result, views_by_key)


def _draw_laterality_results(
    laterality: str,
    lat_result: LateralityResult,
    views_by_key: Dict[str, ViewData],
):
    """Draw results for one laterality.

    Draws correspondence arcs for ALL matches to provide visual feedback,
    including paired matches where both views have detected lesions.
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

    # If ALL matches are paired, still draw arcs to visually indicate
    # the correspondence (user expects visual feedback on the clicked region)
    for match in lat_result.cursor_matches:
        if match.match_type == 'paired':
            # Both views have AI boxes — draw a confirmation arc to highlight
            # the correspondence between the views.
            _draw_correspondence_arc(match, views_by_key, laterality)
        elif match.match_type in ('projected', 'arc_projected'):
            # Draw correspondence ARC on the target view
            _draw_correspondence_arc(match, views_by_key, laterality)
        # 'out_of_field' — no visualization (reported in text summary only)


# ─── Correspondence Arc Drawing ──────────────────────────────────────────────


def _draw_correspondence_arc(
    match: CursorMatch,
    views_by_key: Dict[str, ViewData],
    laterality: str,
):
    """
    Draw the correspondence arc on the target view.

    The arc is centered at the nipple in the target view, with radius equal
    to the nipple-to-lesion distance from the source view. Three concentric
    arcs (inner/nominal/outer) represent the ±10% clinical uncertainty band.

    FOV clipping: if the entire arc lies outside the image boundaries,
    nothing is drawn and a warning is printed. If only part of the arc
    is outside, the arc is clipped to the image bounds.

    No rectangles are drawn.
    """
    if match.target_lesion is None and match.correspondence_arc is None:
        return

    target_key = f"{laterality}_{match.target_view}"
    target_view = views_by_key.get(target_key)

    if not (target_view and target_view.vtk_widget):
        return

    arc = match.correspondence_arc
    if arc is None:
        return

    # Arc must have a valid radius
    if arc.radius_mm <= 0 or arc.radius_px < 5.0:
        return

    # ── FOV clipping: get image dimensions ──
    img_rows, img_cols = _get_image_dimensions(target_view.vtk_widget)

    if img_rows > 0 and img_cols > 0:
        # Check how many arc sample points fall inside the image
        outer_radius_px = arc.radius_px + ARC_RADIUS_OFFSET_PX + 2 * ARC_BAND_SPACING_PX
        start_a = arc.start_angle_rad
        end_a = arc.end_angle_rad

        # Sample the OUTER arc (largest radius) to check FOV
        n_check = 32
        inside_count = 0
        clipped_start = None
        clipped_end = None

        for i in range(n_check + 1):
            t = i / float(n_check)
            angle = start_a + t * (end_a - start_a)
            px = arc.center_x_px + outer_radius_px * math.cos(angle)
            py = arc.center_y_px + outer_radius_px * math.sin(angle)

            if 0 <= px < img_cols and 0 <= py < img_rows:
                inside_count += 1
                if clipped_start is None:
                    clipped_start = angle
                clipped_end = angle

        if inside_count == 0:
            # Entire arc is outside the image → do NOT draw
            print(f"[3D-Cursor][ARC] SKIPPED: entire arc outside FOV "
                  f"(center=({arc.center_x_px:.0f},{arc.center_y_px:.0f}) "
                  f"r={arc.radius_px:.0f}px, image={img_cols}x{img_rows})")

            # Draw "Outside FOV" text label at nipple position instead
            _draw_outside_fov_label(target_view.vtk_widget, arc.center_x_px, arc.center_y_px,
                                    arc.radius_mm)
            return

        # If only a partial arc is inside, clip the angles
        if inside_count < n_check + 1 and clipped_start is not None:
            # Add a small margin to avoid cutting right at the edge
            margin = (end_a - start_a) / n_check * 0.5
            start_a = clipped_start - margin
            end_a = clipped_end + margin
            print(f"[3D-Cursor][ARC] Clipped arc to FOV: "
                  f"{math.degrees(start_a):.0f}°–{math.degrees(end_a):.0f}° "
                  f"({inside_count}/{n_check + 1} samples inside)")
    else:
        start_a = arc.start_angle_rad
        end_a = arc.end_angle_rad

    _draw_arc_with_uncertainty_band(
        vtk_widget=target_view.vtk_widget,
        nipple_x_px=arc.center_x_px,
        nipple_y_px=arc.center_y_px,
        radius_px=arc.radius_px,
        radius_mm=arc.radius_mm,
        start_angle_rad=start_a,
        end_angle_rad=end_a,
        tolerance=0.10,
        img_rows=img_rows,
        img_cols=img_cols,
    )


def _draw_arc_with_uncertainty_band(
    vtk_widget,
    nipple_x_px: float,
    nipple_y_px: float,
    radius_px: float,
    radius_mm: float,
    start_angle_rad: float,
    end_angle_rad: float,
    tolerance: float = 0.10,
    img_rows: int = 0,
    img_cols: int = 0,
):
    """
    Render three concentric arcs + uncertainty band on the VTK viewer.

    Draws:
        1. Filled uncertainty band (annular sector between inner and outer radii).
        2. Inner arc — dashed.
        3. Nominal arc — solid.
        4. Outer arc — dashed.
        5. Nipple crosshair marker.
        6. Distance label OUTSIDE the outer arc.

    Layout (from center outward):
        inner_radius  = radius + ARC_RADIUS_OFFSET_PX
        nominal_radius = inner_radius + ARC_BAND_SPACING_PX
        outer_radius   = nominal_radius + ARC_BAND_SPACING_PX

    The arcs are spaced with fixed pixel gaps so they remain visually
    distinct regardless of the actual nipple-to-lesion distance.
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

        # ── Compute arc radii with fixed pixel spacing ──
        inner_radius_px = radius_px + ARC_RADIUS_OFFSET_PX
        nominal_radius_px = inner_radius_px + ARC_BAND_SPACING_PX
        outer_radius_px = nominal_radius_px + ARC_BAND_SPACING_PX

        all_actors = []

        # ── 1. Filled uncertainty band (annular sector) ──
        band_actor = _create_annular_sector_actor(
            _vtk, ijk_to_world,
            cx=nipple_x_px, cy=nipple_y_px,
            inner_r=inner_radius_px, outer_r=outer_radius_px,
            start_angle=start_angle_rad, end_angle=end_angle_rad,
            num_segments=ARC_NUM_SEGMENTS,
            color=ARC_BAND_COLOR, opacity=ARC_BAND_OPACITY,
        )
        if band_actor:
            renderer.AddActor(band_actor)
            all_actors.append(band_actor)

        # ── 2. Inner bound arc (dashed) ──
        inner_actor = _create_arc_line_actor(
            _vtk, ijk_to_world,
            cx=nipple_x_px, cy=nipple_y_px,
            radius=inner_radius_px,
            start_angle=start_angle_rad, end_angle=end_angle_rad,
            num_segments=ARC_NUM_SEGMENTS,
            color=ARC_INNER_COLOR, opacity=ARC_BOUND_OPACITY,
            line_width=ARC_BOUND_WIDTH, dashed=True,
        )
        if inner_actor:
            renderer.AddActor(inner_actor)
            all_actors.append(inner_actor)

        # ── 3. Nominal arc (solid) ──
        nominal_actor = _create_arc_line_actor(
            _vtk, ijk_to_world,
            cx=nipple_x_px, cy=nipple_y_px,
            radius=nominal_radius_px,
            start_angle=start_angle_rad, end_angle=end_angle_rad,
            num_segments=ARC_NUM_SEGMENTS,
            color=ARC_NOMINAL_COLOR, opacity=ARC_NOMINAL_OPACITY,
            line_width=ARC_NOMINAL_WIDTH, dashed=False,
        )
        if nominal_actor:
            renderer.AddActor(nominal_actor)
            all_actors.append(nominal_actor)

        # ── 4. Outer bound arc (dashed) ──
        outer_actor = _create_arc_line_actor(
            _vtk, ijk_to_world,
            cx=nipple_x_px, cy=nipple_y_px,
            radius=outer_radius_px,
            start_angle=start_angle_rad, end_angle=end_angle_rad,
            num_segments=ARC_NUM_SEGMENTS,
            color=ARC_OUTER_COLOR, opacity=ARC_BOUND_OPACITY,
            line_width=ARC_BOUND_WIDTH, dashed=True,
        )
        if outer_actor:
            renderer.AddActor(outer_actor)
            all_actors.append(outer_actor)

        # ── 5. Nipple marker (small crosshair) ──
        nipple_actor = _create_nipple_marker_actor(
            _vtk, ijk_to_world,
            cx=nipple_x_px, cy=nipple_y_px,
        )
        if nipple_actor:
            renderer.AddActor(nipple_actor)
            all_actors.append(nipple_actor)

        # ── 6. Distance label OUTSIDE the outer arc ──
        mid_angle = (start_angle_rad + end_angle_rad) / 2.0
        label_radius = outer_radius_px + ARC_LABEL_OFFSET_PX
        label_x_px = nipple_x_px + label_radius * math.cos(mid_angle)
        label_y_px = nipple_y_px + label_radius * math.sin(mid_angle)
        lower_mm = radius_mm * (1.0 - tolerance)
        upper_mm = radius_mm * (1.0 + tolerance)
        label_text = (
            f"{radius_mm:.1f} mm\n"
            f"\u00b1{tolerance * 100:.0f}%\n"
            f"{lower_mm:.1f}\u2013{upper_mm:.1f} mm"
        )
        label_actor = _create_text_label_actor(
            _vtk, ijk_to_world,
            x_px=label_x_px, y_px=label_y_px,
            text=label_text,
        )
        if label_actor:
            renderer.AddActor(label_actor)
            all_actors.append(label_actor)

        # ── Track actors for cleanup ──
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.extend(all_actors)

        if not hasattr(vtk_widget, '_3d_cursor_region_actors'):
            vtk_widget._3d_cursor_region_actors = []
        vtk_widget._3d_cursor_region_actors.extend(all_actors)

        # ── Render ──
        renderer.ResetCameraClippingRange()
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

        print(f"[3D-Cursor][ARC] Drew correspondence arc: "
              f"center=({nipple_x_px:.0f},{nipple_y_px:.0f}) "
              f"radius={radius_mm:.1f}mm ({radius_px:.0f}px) "
              f"span={math.degrees(end_angle_rad - start_angle_rad):.1f}deg "
              f"inner/nom/outer={inner_radius_px:.0f}/{nominal_radius_px:.0f}/{outer_radius_px:.0f}px")

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw correspondence arc: {e}")


def draw_arc_probability_heatmap(
    vtk_widget,
    prob_result: ArcProbabilityResult,
    arc_radius_offset_px: float = ARC_RADIUS_OFFSET_PX,
    arc_band_spacing_px: float = ARC_BAND_SPACING_PX,
):
    """
    Render a probability heatmap overlay on the correspondence arc.

    The heatmap uses color-coded segments along the arc where:
    - Red/hot = high probability of lesion
    - Blue/cool = low probability of lesion

    The heatmap is drawn on the nominal arc (middle band) with varying
    color intensity per segment.

    Args:
        vtk_widget: The VTK widget to render on.
        prob_result: ArcProbabilityResult with per-sample probabilities.
        arc_radius_offset_px: Offset from the base radius.
        arc_band_spacing_px: Spacing between arc bands.
    """
    try:
        import vtk as _vtk
    except ImportError:
        return

    if prob_result is None or len(prob_result.probabilities) < 2:
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

        n_samples = len(prob_result.probabilities)
        probs = prob_result.probabilities

        cx = prob_result.center_x_px
        cy = prob_result.center_y_px
        radius = prob_result.radius_px

        # The heatmap is drawn on the nominal arc radius
        nominal_radius = radius + arc_radius_offset_px + arc_band_spacing_px
        # Band width for the heatmap segments
        band_half_width = arc_band_spacing_px * 0.6

        start_angle = prob_result.start_angle_rad
        end_angle = prob_result.end_angle_rad

        all_actors = []

        # Draw each segment with color mapped to probability
        for i in range(n_samples - 1):
            prob_val = (probs[i] + probs[i + 1]) / 2.0  # Average of neighbors

            # Color mapping: blue (cold/low) → yellow → red (hot/high)
            r, g, b = _probability_to_color(prob_val)

            # Opacity proportional to probability (min 0.15, max 0.75)
            opacity = 0.15 + prob_val * 0.60

            # Segment angles
            t0 = i / float(n_samples - 1)
            t1 = (i + 1) / float(n_samples - 1)
            seg_start = start_angle + t0 * (end_angle - start_angle)
            seg_end = start_angle + t1 * (end_angle - start_angle)

            # Create a small annular segment for this probability value
            seg_actor = _create_annular_sector_actor(
                _vtk, ijk_to_world,
                cx=cx, cy=cy,
                inner_r=nominal_radius - band_half_width,
                outer_r=nominal_radius + band_half_width,
                start_angle=seg_start,
                end_angle=seg_end,
                num_segments=3,  # Small segment, few subdivisions needed
                color=(r, g, b),
                opacity=opacity,
            )
            if seg_actor:
                renderer.AddActor(seg_actor)
                all_actors.append(seg_actor)

        # Draw probability peak indicator (brightest point on arc)
        peak_idx = int(np.argmax(probs))
        if probs[peak_idx] > 0.6:  # Only show peak marker if significant
            t_peak = peak_idx / float(n_samples - 1)
            peak_angle = start_angle + t_peak * (end_angle - start_angle)
            peak_x = cx + nominal_radius * math.cos(peak_angle)
            peak_y = cy + nominal_radius * math.sin(peak_angle)

            peak_actor = _create_peak_probability_marker(
                _vtk, ijk_to_world,
                x_px=peak_x, y_px=peak_y,
                probability=float(probs[peak_idx]),
            )
            if peak_actor:
                renderer.AddActor(peak_actor)
                all_actors.append(peak_actor)

        # Track actors for cleanup
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.extend(all_actors)

        if not hasattr(vtk_widget, '_3d_cursor_region_actors'):
            vtk_widget._3d_cursor_region_actors = []
        vtk_widget._3d_cursor_region_actors.extend(all_actors)

        # Render
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw:
            rw.Render()

        print(f"[3D-Cursor][HEATMAP] Drew probability heatmap: "
              f"{n_samples} segments, peak={float(probs.max()):.2f} "
              f"at idx={peak_idx}")

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw probability heatmap: {e}")


def _get_image_dimensions(vtk_widget) -> Tuple[int, int]:
    """Get image dimensions (rows, cols) from a VTK viewer widget."""
    try:
        iv = getattr(vtk_widget, 'image_viewer', None)
        if iv is None:
            return (0, 0)
        meta = getattr(iv, 'metadata', {}) or {}
        instances = meta.get('instances', [])
        if isinstance(instances, list) and instances:
            inst = instances[0]
            rows = int(inst.get('rows', 0) or 0)
            cols = int(inst.get('columns', 0) or 0)
            if rows > 0 and cols > 0:
                return (rows, cols)
        # Fallback: try VTK image data dimensions
        vtk_data = getattr(iv, 'vtk_image_data', None) or \
                   getattr(iv, 'GetInput', lambda: None)()
        if vtk_data is not None:
            dims = vtk_data.GetDimensions()
            if dims and len(dims) >= 2 and dims[0] > 0 and dims[1] > 0:
                return (dims[1], dims[0])  # rows=Y, cols=X
    except Exception:
        pass
    return (0, 0)


def _draw_outside_fov_label(vtk_widget, nipple_x_px: float, nipple_y_px: float,
                            radius_mm: float):
    """Draw an 'Outside FOV' warning label at the nipple position."""
    try:
        import vtk as _vtk
        iv = getattr(vtk_widget, 'image_viewer', None)
        if iv is None:
            return
        renderer = getattr(iv, 'renderer', None)
        ijk_to_world = getattr(iv, 'ijk_to_world', None)
        if renderer is None or ijk_to_world is None:
            return

        label_text = (
            f"Outside FOV\n"
            f"({radius_mm:.1f} mm from nipple)\n"
            f"Predicted location is outside image"
        )
        actor = _create_text_label_actor(
            _vtk, ijk_to_world,
            x_px=nipple_x_px, y_px=nipple_y_px,
            text=label_text, font_size=14,
        )
        if actor:
            # Use red-ish color for warning
            actor.GetTextProperty().SetColor(1.0, 0.4, 0.3)
            renderer.AddActor(actor)
            if not hasattr(vtk_widget, '_projected_actors'):
                vtk_widget._projected_actors = []
            vtk_widget._projected_actors.append(actor)

            rw = getattr(iv, 'image_render_window', None) or \
                 getattr(iv, 'GetRenderWindow', lambda: None)()
            if rw:
                rw.Render()
    except Exception as e:
        print(f"[3D-Cursor] Failed to draw Outside FOV label: {e}")


def _probability_to_color(prob: float) -> Tuple[float, float, float]:
    """
    Map a probability value [0, 1] to a color (R, G, B).

    Color ramp: Blue (0.0) → Cyan (0.25) → Green (0.5) → Yellow (0.75) → Red (1.0)
    """
    prob = max(0.0, min(1.0, prob))

    if prob < 0.25:
        # Blue → Cyan
        t = prob / 0.25
        return (0.0, t, 1.0)
    elif prob < 0.5:
        # Cyan → Green
        t = (prob - 0.25) / 0.25
        return (0.0, 1.0, 1.0 - t)
    elif prob < 0.75:
        # Green → Yellow
        t = (prob - 0.5) / 0.25
        return (t, 1.0, 0.0)
    else:
        # Yellow → Red
        t = (prob - 0.75) / 0.25
        return (1.0, 1.0 - t, 0.0)


def _create_peak_probability_marker(
    _vtk, ijk_to_world,
    x_px: float, y_px: float,
    probability: float,
):
    """Create a diamond-shaped marker at the peak probability location."""
    try:
        world_pt = ijk_to_world(x_px, y_px, None, y_flip=True)

        marker = _vtk.vtkSphereSource()
        marker.SetCenter(world_pt)
        marker.SetRadius(4.0)
        marker.SetPhiResolution(12)
        marker.SetThetaResolution(12)
        marker.Update()

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(marker.GetOutputPort())

        actor = _vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(1.0, 0.2, 0.0)  # Bright red-orange
        actor.GetProperty().SetOpacity(0.9)

        return actor
    except Exception:
        return None


# ─── VTK Actor Builders ──────────────────────────────────────────────────────


def _create_annular_sector_actor(
    _vtk, ijk_to_world,
    cx: float, cy: float,
    inner_r: float, outer_r: float,
    start_angle: float, end_angle: float,
    num_segments: int,
    color: tuple, opacity: float,
):
    """
    Create a filled annular sector (the shaded uncertainty band between
    inner and outer arcs).

    The sector is built as a triangle strip between inner and outer arc points.
    """
    if inner_r <= 0 or outer_r <= inner_r:
        return None

    try:
        vtk_points = _vtk.vtkPoints()
        cells = _vtk.vtkCellArray()

        # Build triangle strip: alternating outer/inner points
        n = num_segments + 1
        num_pts = 2 * n

        for i in range(n):
            t = i / float(num_segments)
            angle = start_angle + t * (end_angle - start_angle)
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)

            # Outer point
            ox = cx + outer_r * cos_a
            oy = cy + outer_r * sin_a
            outer_world = ijk_to_world(ox, oy, None, y_flip=True)
            vtk_points.InsertNextPoint(outer_world)

            # Inner point
            ix = cx + inner_r * cos_a
            iy = cy + inner_r * sin_a
            inner_world = ijk_to_world(ix, iy, None, y_flip=True)
            vtk_points.InsertNextPoint(inner_world)

        # Triangle strip connectivity
        strip = _vtk.vtkTriangleStrip()
        strip.GetPointIds().SetNumberOfIds(num_pts)
        for i in range(num_pts):
            strip.GetPointIds().SetId(i, i)

        cells.InsertNextCell(strip)

        poly_data = _vtk.vtkPolyData()
        poly_data.SetPoints(vtk_points)
        poly_data.SetStrips(cells)

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly_data)

        actor = _vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(opacity)
        actor.GetProperty().LightingOff()

        return actor
    except Exception:
        return None


def _create_arc_line_actor(
    _vtk, ijk_to_world,
    cx: float, cy: float,
    radius: float,
    start_angle: float, end_angle: float,
    num_segments: int,
    color: tuple, opacity: float,
    line_width: float, dashed: bool,
):
    """
    Create a polyline arc actor (a single smooth curve).

    Mathematical basis:
        For each segment i in [0, num_segments]:
            t = i / num_segments
            angle = start_angle + t * (end_angle - start_angle)
            x = cx + radius * cos(angle)
            y = cy + radius * sin(angle)
    """
    if radius < 2.0:
        return None

    try:
        vtk_points = _vtk.vtkPoints()
        n = num_segments + 1

        for i in range(n):
            t = i / float(num_segments)
            angle = start_angle + t * (end_angle - start_angle)
            px = cx + radius * math.cos(angle)
            py = cy + radius * math.sin(angle)
            world_pt = ijk_to_world(px, py, None, y_flip=True)
            vtk_points.InsertNextPoint(world_pt)

        # Polyline
        polyline = _vtk.vtkPolyLine()
        polyline.GetPointIds().SetNumberOfIds(n)
        for i in range(n):
            polyline.GetPointIds().SetId(i, i)

        cells = _vtk.vtkCellArray()
        cells.InsertNextCell(polyline)

        poly_data = _vtk.vtkPolyData()
        poly_data.SetPoints(vtk_points)
        poly_data.SetLines(cells)

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly_data)

        actor = _vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetOpacity(opacity)
        prop.SetLineWidth(line_width)
        prop.LightingOff()

        if dashed:
            prop.SetLineStipplePattern(0xF0F0)
            prop.SetLineStippleRepeatFactor(1)

        return actor
    except Exception:
        return None


def _create_nipple_marker_actor(
    _vtk, ijk_to_world,
    cx: float, cy: float,
    size_px: float = 8.0,
):
    """
    Create a small crosshair marker at the nipple position.

    Draws two perpendicular lines crossing at (cx, cy).
    """
    try:
        vtk_points = _vtk.vtkPoints()
        # Horizontal line
        p0 = ijk_to_world(cx - size_px, cy, None, y_flip=True)
        p1 = ijk_to_world(cx + size_px, cy, None, y_flip=True)
        # Vertical line
        p2 = ijk_to_world(cx, cy - size_px, None, y_flip=True)
        p3 = ijk_to_world(cx, cy + size_px, None, y_flip=True)

        vtk_points.InsertNextPoint(p0)  # 0
        vtk_points.InsertNextPoint(p1)  # 1
        vtk_points.InsertNextPoint(p2)  # 2
        vtk_points.InsertNextPoint(p3)  # 3

        cells = _vtk.vtkCellArray()
        # Line 1: horizontal
        line1 = _vtk.vtkLine()
        line1.GetPointIds().SetId(0, 0)
        line1.GetPointIds().SetId(1, 1)
        cells.InsertNextCell(line1)
        # Line 2: vertical
        line2 = _vtk.vtkLine()
        line2.GetPointIds().SetId(0, 2)
        line2.GetPointIds().SetId(1, 3)
        cells.InsertNextCell(line2)

        poly_data = _vtk.vtkPolyData()
        poly_data.SetPoints(vtk_points)
        poly_data.SetLines(cells)

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly_data)

        actor = _vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*NIPPLE_MARKER_COLOR)
        prop.SetOpacity(0.9)
        prop.SetLineWidth(2.5)
        prop.LightingOff()

        return actor
    except Exception:
        return None


def _create_text_label_actor(
    _vtk, ijk_to_world,
    x_px: float, y_px: float,
    text: str,
    font_size: int = 12,
):
    """
    Create a VTK text follower (billboard) label at the given pixel position.
    """
    try:
        world_pt = ijk_to_world(x_px, y_px, None, y_flip=True)

        text_actor = _vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(text)
        text_actor.SetPosition(world_pt)
        text_actor.GetTextProperty().SetFontSize(font_size)
        text_actor.GetTextProperty().SetColor(0.9, 0.95, 1.0)
        text_actor.GetTextProperty().SetJustificationToCentered()
        text_actor.GetTextProperty().SetVerticalJustificationToCentered()
        text_actor.GetTextProperty().SetBackgroundColor(0.0, 0.0, 0.0)
        text_actor.GetTextProperty().SetBackgroundOpacity(0.6)

        return text_actor
    except Exception:
        # Fallback: try vtkTextActor3D if billboard is unavailable
        try:
            text_actor = _vtk.vtkTextActor3D()
            text_actor.SetInput(text)
            text_actor.SetPosition(world_pt)
            text_actor.GetTextProperty().SetFontSize(font_size)
            text_actor.GetTextProperty().SetColor(0.9, 0.95, 1.0)
            return text_actor
        except Exception:
            return None


# ─── Cleanup ─────────────────────────────────────────────────────────────────


def _clear_projected_actors(vtk_widget):
    """Remove previously drawn projected actors from a widget."""
    try:
        actors = getattr(vtk_widget, '_projected_actors', None)
        if not actors:
            vtk_widget._projected_actors = []
            return

        image_viewer = getattr(vtk_widget, 'image_viewer', None)
        if image_viewer is not None:
            renderer = getattr(image_viewer, 'renderer', None)
            if renderer:
                for a in actors:
                    try:
                        renderer.RemoveActor(a)
                    except Exception:
                        pass

        vtk_widget._projected_actors = []

        # Also clear the region-specific list
        if hasattr(vtk_widget, '_3d_cursor_region_actors'):
            vtk_widget._3d_cursor_region_actors = []
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
        - Source view: ruler from nipple -> lesion center, labeled with depth_mm
        - Target view: ruler from nipple -> projected lesion, labeled with depth_mm
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

        # Draw ruler on source view (nipple -> source lesion center)
        if src_view_data and src_view_data.vtk_widget and src_geom:
            _draw_ruler_on_widget(
                vtk_widget=src_view_data.vtk_widget,
                nipple_px=(src_geom.nipple.x_px, src_geom.nipple.y_px),
                lesion_center_px=match.source_lesion.center_px,
                distance_mm=match.depth_mm,
                label_prefix=f"{match.source_view}",
            )

        # Draw ruler on target view (nipple -> arc intersection on nominal arc)
        if tgt_view_data and tgt_view_data.vtk_widget and tgt_geom:
            arc = match.correspondence_arc
            if arc and arc.radius_px > 5.0:
                # Compute endpoint on the nominal arc (inner + spacing)
                arc_endpoint_radius = arc.radius_px + ARC_RADIUS_OFFSET_PX + ARC_BAND_SPACING_PX
                # Direction from nipple toward the lesion (or arc midpoint)
                if match.target_lesion:
                    dx = match.target_lesion.center_px[0] - tgt_geom.nipple.x_px
                    dy = match.target_lesion.center_px[1] - tgt_geom.nipple.y_px
                else:
                    mid_angle = (arc.start_angle_rad + arc.end_angle_rad) / 2.0
                    dx = math.cos(mid_angle)
                    dy = math.sin(mid_angle)
                dist = math.sqrt(dx * dx + dy * dy)
                if dist > 0:
                    arc_end_x = tgt_geom.nipple.x_px + (dx / dist) * arc_endpoint_radius
                    arc_end_y = tgt_geom.nipple.y_px + (dy / dist) * arc_endpoint_radius
                else:
                    arc_end_x = tgt_geom.nipple.x_px + arc_endpoint_radius
                    arc_end_y = tgt_geom.nipple.y_px

                _draw_ruler_on_widget(
                    vtk_widget=tgt_view_data.vtk_widget,
                    nipple_px=(tgt_geom.nipple.x_px, tgt_geom.nipple.y_px),
                    lesion_center_px=(arc_end_x, arc_end_y),
                    distance_mm=match.depth_mm,
                    label_prefix=f"{match.target_view}",
                )
            elif match.target_lesion:
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

        p_nipple = ijk_to_world(nipple_px[0], nipple_px[1], None, y_flip=True)
        p_lesion = ijk_to_world(lesion_center_px[0], lesion_center_px[1], None, y_flip=True)

        # ── Dashed ruler line ──
        line_source = _vtk.vtkLineSource()
        line_source.SetPoint1(p_nipple)
        line_source.SetPoint2(p_lesion)
        line_source.SetResolution(20)
        line_source.Update()

        line_mapper = _vtk.vtkPolyDataMapper()
        line_mapper.SetInputConnection(line_source.GetOutputPort())

        line_actor = _vtk.vtkActor()
        line_actor.SetMapper(line_mapper)
        line_prop = line_actor.GetProperty()
        line_prop.SetColor(COLOR_RULER[0], COLOR_RULER[1], COLOR_RULER[2])
        line_prop.SetLineWidth(2.0)
        line_prop.SetLineStipplePattern(0xF0F0)
        line_prop.SetLineStippleRepeatFactor(1)
        line_prop.SetOpacity(0.85)

        renderer.AddActor(line_actor)

        # ── Endpoint markers ──
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

            if not hasattr(vtk_widget, '_projected_actors'):
                vtk_widget._projected_actors = []
            vtk_widget._projected_actors.append(marker_actor)

        # ── Text label at midpoint ──
        mid_x = (p_nipple[0] + p_lesion[0]) / 2.0
        mid_y = (p_nipple[1] + p_lesion[1]) / 2.0
        mid_z = (p_nipple[2] + p_lesion[2]) / 2.0

        label_text = f"{distance_mm:.1f} mm"
        if label_prefix:
            label_text = f"{label_prefix}: {label_text}"

        try:
            text_actor = _vtk.vtkBillboardTextActor3D()
            text_actor.SetInput(label_text)
            text_actor.SetPosition(mid_x, mid_y, mid_z)
            text_actor.GetTextProperty().SetFontSize(12)
            text_actor.GetTextProperty().SetColor(
                COLOR_RULER_TEXT[0], COLOR_RULER_TEXT[1], COLOR_RULER_TEXT[2]
            )
            text_actor.GetTextProperty().SetJustificationToCentered()
            text_actor.GetTextProperty().SetBackgroundColor(0.0, 0.0, 0.0)
            text_actor.GetTextProperty().SetBackgroundOpacity(0.5)
            renderer.AddActor(text_actor)

            if not hasattr(vtk_widget, '_projected_actors'):
                vtk_widget._projected_actors = []
            vtk_widget._projected_actors.append(text_actor)
        except Exception:
            pass

        # Track line actor
        if not hasattr(vtk_widget, '_projected_actors'):
            vtk_widget._projected_actors = []
        vtk_widget._projected_actors.append(line_actor)

    except Exception as e:
        print(f"[3D-Cursor] Failed to draw ruler: {e}")
