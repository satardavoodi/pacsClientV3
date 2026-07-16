"""
Rendering for the Two-Stage 3D Cursor — the search region and the candidates.

Deliberately self-contained (rather than extending `visualization.py`) so the
two-stage feature can be flag-disabled without touching a single line of the
legacy arc renderer.

VISUAL LANGUAGE — designed so that "we are unsure" is legible at a glance:

    ── the region ───────────────────────────────────────────────────────────
    solid cyan line      the predicted locus (nominal)
    dashed cyan lines    the inner / high-confidence band edges (±inner mm)
    faint cyan lines     the outer / search band edges (±outer mm)

    ── the candidates ───────────────────────────────────────────────────────
    GREEN  box + "MATCH"     one confident correspondence  (MatchResult.MATCH)
    AMBER  boxes + "ALT n"   several near-tied alternatives (AMBIGUOUS)
    GREY   boxes             ranked but rejected (below the confidence floor)

There is intentionally NO green box in the AMBIGUOUS or NO_MATCH states. Green is
reserved for a claim we are willing to stand behind. If the algorithm is unsure,
the radiologist must SEE that it is unsure — an amber pair of equals, or a bare
region with no box at all, is the honest picture.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from .candidate_matching import AMBIGUOUS, MATCH, MatchResult, ScoredCandidate
from .search_region import SearchRegion


COLOR_LOCUS = (0.20, 0.85, 1.00)        # cyan — the prediction
COLOR_BAND_INNER = (0.20, 0.75, 0.95)
COLOR_BAND_OUTER = (0.25, 0.55, 0.70)
COLOR_NIPPLE = (1.00, 0.15, 0.15)       # red — matches the guided picker's marker
# Second-pass (lower-threshold) predicted lesions render in CYAN — a distinct
# colour from the first-pass AI detections (green boxes + yellow segmentation
# overlay), so the radiologist can tell at a glance which lesion was surfaced only
# by dropping the threshold. Requested 2026-07-15; replaces the old green/amber.
COLOR_MATCH = (0.10, 0.95, 1.00)        # cyan — the confident lower-threshold prediction
COLOR_ALTERNATIVE = (0.45, 0.75, 1.00)  # light blue — ambiguous (NOT yellow)
COLOR_REJECTED = (0.55, 0.58, 0.62)     # grey — considered and rejected
# Multiple-findings UX (2026-07-15): the SELECTED finding uses COLOR_MATCH (bright
# cyan); every OTHER finding is a small dim marker so the breast is not flooded.
COLOR_FINDING_OTHER = (0.45, 0.72, 1.00)  # dim blue — a non-selected finding marker
COLOR_LEADER = (0.82, 0.88, 0.95)         # light grey — label-to-box leader line


def _viewer_bits(vtk_widget):
    """(image_viewer, renderer, ijk_to_world) or (None, None, None)."""
    try:
        iv = getattr(vtk_widget, "image_viewer", None)
        if iv is None:
            return None, None, None
        renderer = getattr(iv, "renderer", None)
        ijk_to_world = getattr(iv, "ijk_to_world", None)
        if renderer is None or ijk_to_world is None:
            return None, None, None
        return iv, renderer, ijk_to_world
    except Exception:
        return None, None, None


def _render(vtk_widget) -> None:
    try:
        iv = getattr(vtk_widget, "image_viewer", None)
        rw = getattr(iv, "image_render_window", None)
        if rw is None and iv is not None:
            get_rw = getattr(iv, "GetRenderWindow", None)
            rw = get_rw() if callable(get_rw) else None
        if rw is not None:
            rw.Render()
    except Exception:
        pass


def _track(vtk_widget, actor) -> None:
    """Register an actor on BOTH cleanup lists the AI widget already knows about."""
    for attr in ("_projected_actors", "_3d_cursor_region_actors"):
        if not hasattr(vtk_widget, attr) or getattr(vtk_widget, attr) is None:
            setattr(vtk_widget, attr, [])
        getattr(vtk_widget, attr).append(actor)


def clear_region_actors(vtk_widget) -> None:
    """
    Remove everything this module drew.

    Called at the START of every draw, so re-running the 3D Cursor within one
    series replaces the overlay instead of stacking it. (The legacy heatmap path
    omitted this and leaked actors across re-runs.)
    """
    try:
        iv, renderer, _ = _viewer_bits(vtk_widget)
        for attr in ("_projected_actors", "_3d_cursor_region_actors"):
            actors = getattr(vtk_widget, attr, None) or []
            if renderer is not None:
                for a in actors:
                    try:
                        renderer.RemoveActor(a)
                    except Exception:
                        pass
            setattr(vtk_widget, attr, [])
    except Exception:
        pass


# ─── Primitives ──────────────────────────────────────────────────────────────

def _polyline_actor(
    _vtk, ijk_to_world,
    points_px: Sequence[Tuple[float, float]],
    color: Tuple[float, float, float],
    opacity: float,
    line_width: float,
    dashed: bool = False,
):
    pts = [p for p in points_px if p is not None]
    if len(pts) < 2:
        return None
    try:
        vtk_points = _vtk.vtkPoints()
        for (px, py) in pts:
            vtk_points.InsertNextPoint(ijk_to_world(px, py, None, y_flip=True))

        polyline = _vtk.vtkPolyLine()
        polyline.GetPointIds().SetNumberOfIds(len(pts))
        for i in range(len(pts)):
            polyline.GetPointIds().SetId(i, i)

        cells = _vtk.vtkCellArray()
        cells.InsertNextCell(polyline)

        poly = _vtk.vtkPolyData()
        poly.SetPoints(vtk_points)
        poly.SetLines(cells)

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly)

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


def _box_actor(
    _vtk, ijk_to_world,
    box_px: Sequence[float],
    color: Tuple[float, float, float],
    opacity: float,
    line_width: float,
):
    try:
        x1, y1, x2, y2 = [float(v) for v in box_px]
    except Exception:
        return None
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
    return _polyline_actor(_vtk, ijk_to_world, corners, color, opacity, line_width)


def _nipple_px(region: SearchRegion) -> Optional[Tuple[float, float]]:
    """The target-view nipple, in pixels, recovered from the region's own geometry."""
    try:
        nx_mm, ny_mm = region._nipple_mm
        sx, sy = region._spacing
        if sx <= 0 or sy <= 0:
            return None
        return (nx_mm / sx, ny_mm / sy)
    except Exception:
        return None


def _crosshair_actor(
    _vtk, ijk_to_world,
    at_px: Tuple[float, float],
    color: Tuple[float, float, float],
    size_px: float = 20.0,
):
    """A simple '+' marker. Two short polylines — no sphere, so it stays legible at
    any zoom without occluding the tissue underneath it."""
    x, y = at_px
    h = [(x - size_px, y), (x + size_px, y)]
    v = [(x, y - size_px), (x, y + size_px)]
    try:
        append = _vtk.vtkAppendPolyData()
        for pts in (h, v):
            vp = _vtk.vtkPoints()
            for (px, py) in pts:
                vp.InsertNextPoint(ijk_to_world(px, py, None, y_flip=True))
            line = _vtk.vtkPolyLine()
            line.GetPointIds().SetNumberOfIds(2)
            line.GetPointIds().SetId(0, 0)
            line.GetPointIds().SetId(1, 1)
            cells = _vtk.vtkCellArray()
            cells.InsertNextCell(line)
            poly = _vtk.vtkPolyData()
            poly.SetPoints(vp)
            poly.SetLines(cells)
            append.AddInputData(poly)
        append.Update()

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputData(append.GetOutput())
        actor = _vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetLineWidth(2.5)
        prop.LightingOff()
        return actor
    except Exception:
        return None


def _label_actor(
    _vtk, ijk_to_world, renderer,
    text: str,
    at_px: Tuple[float, float],
    color: Tuple[float, float, float],
    scale: float = 5.0,
):
    try:
        src = _vtk.vtkVectorText()
        src.SetText(str(text))
        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(src.GetOutputPort())

        actor = _vtk.vtkFollower()
        actor.SetMapper(mapper)
        actor.SetScale(scale, scale, scale)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().LightingOff()

        wx, wy, wz = ijk_to_world(at_px[0], at_px[1], None, y_flip=True)
        actor.SetPosition(wx, wy, wz)

        cam = renderer.GetActiveCamera()
        if cam:
            actor.SetCamera(cam)
        return actor
    except Exception:
        return None


# ─── Public draw ─────────────────────────────────────────────────────────────

def draw_search_region(
    vtk_widget,
    region: SearchRegion,
    *,
    clear_first: bool = True,
) -> bool:
    """Draw the Stage-1 predicted region on the TARGET viewer. Returns success."""
    if region is None or region.is_empty:
        return False

    try:
        import vtk as _vtk
    except Exception:
        return False

    iv, renderer, ijk_to_world = _viewer_bits(vtk_widget)
    if renderer is None:
        return False

    if clear_first:
        clear_region_actors(vtk_widget)

    drawn = 0

    # Outer (search) band — faint.
    for offset in (-region.outer_band_mm, region.outer_band_mm):
        a = _polyline_actor(
            _vtk, ijk_to_world, region.band_points_px(offset),
            COLOR_BAND_OUTER, 0.35, 1.5, dashed=True,
        )
        if a is not None:
            renderer.AddActor(a)
            _track(vtk_widget, a)
            drawn += 1

    # Inner (high-confidence) band — dashed.
    for offset in (-region.inner_band_mm, region.inner_band_mm):
        a = _polyline_actor(
            _vtk, ijk_to_world, region.band_points_px(offset),
            COLOR_BAND_INNER, 0.65, 2.0, dashed=True,
        )
        if a is not None:
            renderer.AddActor(a)
            _track(vtk_widget, a)
            drawn += 1

    # The locus itself — solid.
    a = _polyline_actor(
        _vtk, ijk_to_world, region.points_px,
        COLOR_LOCUS, 0.95, 3.0,
    )
    if a is not None:
        renderer.AddActor(a)
        _track(vtk_widget, a)
        drawn += 1

    # Nipple marker — the anchor the whole prediction hangs off.
    # The legacy arc renderer used to draw this; in the two-stage path that
    # renderer is (deliberately) suppressed, so we draw it here. Without it the
    # radiologist cannot see the landmark their own click established, and has no
    # way to sanity-check a locus that is measured FROM that point.
    nipple_px = _nipple_px(region)
    if nipple_px is not None:
        nm = _crosshair_actor(_vtk, ijk_to_world, nipple_px, COLOR_NIPPLE, size_px=22.0)
        if nm is not None:
            renderer.AddActor(nm)
            _track(vtk_widget, nm)
            drawn += 1

    # Label at the end of the locus.
    if region.points_px:
        tip = region.points_px[-1]
        label = f"{region.method.upper()} {region.distance_mm:.0f}mm"
        la = _label_actor(_vtk, ijk_to_world, renderer, label, tip, COLOR_LOCUS, scale=6.0)
        if la is not None:
            renderer.AddActor(la)
            _track(vtk_widget, la)

    _render(vtk_widget)
    print(
        f"[3D-Cursor][REGION] drawn method={region.method} "
        f"{region.distance_kind}={region.distance_mm:.1f}mm "
        f"band=±{region.inner_band_mm:.0f}/±{region.outer_band_mm:.0f}mm "
        f"actors={drawn}"
    )
    return drawn > 0


def _heat_color(v: float) -> Tuple[float, float, float]:
    """Blue(low) → cyan → green → yellow → red(high) for a [0,1] confidence."""
    v = max(0.0, min(1.0, float(v)))
    if v < 0.25:
        t = v / 0.25;  return (0.0, t, 1.0)
    if v < 0.5:
        t = (v - 0.25) / 0.25;  return (0.0, 1.0, 1.0 - t)
    if v < 0.75:
        t = (v - 0.5) / 0.25;   return (t, 1.0, 0.0)
    t = (v - 0.75) / 0.25;      return (1.0, 1.0 - t, 0.0)


def draw_heatmap_field(vtk_widget, field, *, min_show: float = 0.35, opacity: float = 0.45) -> bool:
    """
    Render the dense three-factor confidence field as translucent colored cells over
    the target viewport. Additive: drawn UNDER the candidate boxes; cells below
    `min_show` are skipped so the anatomy stays visible. Never raises.

    NEEDS LIVE SOURCE-BUILD VERIFY — VTK rendering is not exercised in the sandbox.
    """
    if field is None or getattr(field, "values", None) is None:
        return False
    try:
        import vtk as _vtk
    except Exception:
        return False
    iv, renderer, ijk_to_world = _viewer_bits(vtk_widget)
    if renderer is None:
        return False
    try:
        import numpy as _np
        vals = field.values
        x1, y1, x2, y2 = field.bbox_px
        step = max(1, int(field.step_px))
        h, w = vals.shape
        pts = _vtk.vtkPoints()
        cells = _vtk.vtkCellArray()
        colors = _vtk.vtkUnsignedCharArray()
        colors.SetNumberOfComponents(3)
        colors.SetName("heat")
        nid = 0
        for iy in range(h):
            for ix in range(w):
                v = float(vals[iy, ix])
                if v < min_show:
                    continue
                cx = x1 + ix * step
                cy = y1 + iy * step
                corners = [(cx, cy), (cx + step, cy), (cx + step, cy + step), (cx, cy + step)]
                quad = _vtk.vtkQuad()
                for k, (px, py) in enumerate(corners):
                    pts.InsertNextPoint(ijk_to_world(px, py, None, y_flip=True))
                    quad.GetPointIds().SetId(k, nid)
                    nid += 1
                cells.InsertNextCell(quad)
                r, g, b = _heat_color(v)
                colors.InsertNextTuple3(int(r * 255), int(g * 255), int(b * 255))
        if nid == 0:
            return False
        poly = _vtk.vtkPolyData()
        poly.SetPoints(pts)
        poly.SetPolys(cells)
        poly.GetCellData().SetScalars(colors)
        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly)
        actor = _vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetOpacity(opacity)
        prop.LightingOff()
        renderer.AddActor(actor)
        _track(vtk_widget, actor)
        _render(vtk_widget)
        print(f"[3D-Cursor][HEATMAP] drawn cells={cells.GetNumberOfCells()} peak={field.peak_px}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[3D-Cursor][HEATMAP] draw failed: {exc}")
        return False


def draw_candidates(
    vtk_widget,
    match: MatchResult,
    *,
    max_rejected: int = 3,
) -> bool:
    """
    Draw the Stage-2 candidates over the region (does NOT clear — the region must
    stay visible underneath, including when nothing matched).
    """
    if match is None or not match.ranked:
        return False

    try:
        import vtk as _vtk
    except Exception:
        return False

    iv, renderer, ijk_to_world = _viewer_bits(vtk_widget)
    if renderer is None:
        return False

    def _add(sc: ScoredCandidate, color, opacity, width, text):
        b = _box_actor(_vtk, ijk_to_world, sc.candidate.box_px, color, opacity, width)
        if b is not None:
            renderer.AddActor(b)
            _track(vtk_widget, b)
        cx, cy = sc.center_px
        top_y = min(float(sc.candidate.box_px[1]), float(sc.candidate.box_px[3]))
        lab = _label_actor(
            _vtk, ijk_to_world, renderer, text, (cx, top_y - 6.0), color, scale=5.5
        )
        if lab is not None:
            renderer.AddActor(lab)
            _track(vtk_widget, lab)

    if match.status == MATCH and match.best is not None:
        _add(match.best, COLOR_MATCH, 1.0, 3.5, f"MATCH {match.best.total:.2f}")
        for sc in match.alternatives[:max_rejected]:
            _add(sc, COLOR_REJECTED, 0.55, 1.5, f"{sc.total:.2f}")

    elif match.status == AMBIGUOUS:
        # No green. Every near-tied candidate gets equal amber weight — the UI must
        # not imply an ordering we have not earned.
        for i, sc in enumerate(match.alternatives, start=1):
            _add(sc, COLOR_ALTERNATIVE, 0.95, 3.0, f"ALT {i} · {sc.total:.2f}")

    else:  # NO_MATCH — show what was considered, in grey, so the user can judge.
        for sc in match.ranked[:max_rejected]:
            _add(sc, COLOR_REJECTED, 0.55, 1.5, f"{sc.total:.2f}")

    _render(vtk_widget)
    print(
        f"[3D-Cursor][CANDIDATES] status={match.status} "
        f"ranked={len(match.ranked)} margin={match.margin:.2f}"
    )
    return True


# ─── Multiple-findings UX: one finding, leader-lined, others as small markers ──

def _leader_actor(_vtk, ijk_to_world, from_px, to_px, color, opacity=0.9, width=1.2):
    """A thin line from a label to its box, so the text is never detached."""
    return _polyline_actor(_vtk, ijk_to_world, [from_px, to_px], color, opacity, width)


def draw_finding(
    vtk_widget,
    box_px,
    number: int,
    *,
    selected: bool,
    score: Optional[float] = None,
    clear_first: bool = False,
) -> bool:
    """
    Draw ONE finding's box on the TARGET viewer.

    selected=True  -> a bright cyan box + a numbered label OFFSET from the box with a
                      LEADER LINE back to it, so the text never sits detached on top
                      of the tissue.
    selected=False -> a small dim numbered marker only (no big box/label), so two or
                      three findings do not clutter the breast. The full box + region
                      + heatmap for a non-selected finding appear only when the user
                      selects it.

    Additive: tracked via `_track`, so `clear_region_actors` removes it with the rest.
    """
    if not box_px:
        return False
    try:
        import vtk as _vtk
    except Exception:
        return False
    iv, renderer, ijk_to_world = _viewer_bits(vtk_widget)
    if renderer is None:
        return False
    if clear_first:
        clear_region_actors(vtk_widget)
    try:
        x1, y1, x2, y2 = [float(v) for v in box_px]
    except Exception:
        return False

    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    top_y = min(y1, y2)

    def _add(actor):
        if actor is not None:
            renderer.AddActor(actor)
            _track(vtk_widget, actor)

    if selected:
        _add(_box_actor(_vtk, ijk_to_world, box_px, COLOR_MATCH, 1.0, 3.5))
        anchor = (max(x1, x2), top_y)                 # box top corner
        label_at = (max(x1, x2) + 45.0, top_y - 45.0)  # clear of the tissue
        _add(_leader_actor(_vtk, ijk_to_world, anchor, label_at, COLOR_LEADER, 0.9, 1.3))
        txt = f"#{number}" if score is None else f"#{number}  {score:.2f}"
        _add(_label_actor(_vtk, ijk_to_world, renderer, txt, label_at, COLOR_MATCH, scale=6.5))
    else:
        half = 16.0
        _add(_box_actor(_vtk, ijk_to_world,
                        [cx - half, cy - half, cx + half, cy + half],
                        COLOR_FINDING_OTHER, 0.75, 1.6))
        label_at = (cx + 24.0, cy - 24.0)
        _add(_leader_actor(_vtk, ijk_to_world, (cx, cy), label_at, COLOR_LEADER, 0.6, 1.0))
        _add(_label_actor(_vtk, ijk_to_world, renderer, f"#{number}", label_at,
                          COLOR_FINDING_OTHER, scale=5.0))

    _render(vtk_widget)
    return True
