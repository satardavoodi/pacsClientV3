"""
Shared VTK overlay helpers for the 3D Cursor pickers (markers + lines).

Used by the guided workflow (`guided_picker.py`). The legacy pickers
(`nipple_picker.py` / `pectoral_picker.py`) keep their own private copies so the
legacy path stays byte-identical — do not "clean that up" without re-validating
the legacy flow.

Every function is defensive: a missing renderer / dead widget must never raise
into the picking flow.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

COLOR_NIPPLE = (1.0, 0.15, 0.15)      # red
COLOR_PECTORAL = (0.30, 1.0, 0.50)    # green
COLOR_PENDING = (1.0, 0.85, 0.20)     # amber (first click of a 2-click line)


def _viewer_bits(vtk_widget):
    iv = getattr(vtk_widget, 'image_viewer', None)
    if iv is None:
        return None, None, None
    renderer = getattr(iv, 'renderer', None)
    ijk_to_world = getattr(iv, 'ijk_to_world', None)
    if renderer is None or not callable(ijk_to_world):
        return iv, None, None
    return iv, renderer, ijk_to_world


def _render(image_viewer) -> None:
    try:
        rw = getattr(image_viewer, 'image_render_window', None) or \
             getattr(image_viewer, 'GetRenderWindow', lambda: None)()
        if rw is not None:
            rw.Render()
    except Exception:
        pass


def draw_point_marker(vtk_widget, x_px: float, y_px: float,
                      color: Tuple[float, float, float] = COLOR_NIPPLE,
                      radius: float = 3.0) -> Optional[object]:
    """Draw a sphere marker at an image pixel. Returns the actor (or None)."""
    try:
        import vtk as _vtk
    except Exception:
        return None
    try:
        iv, renderer, ijk_to_world = _viewer_bits(vtk_widget)
        if renderer is None:
            return None

        p_world = ijk_to_world(float(x_px), float(y_px), None, y_flip=True)

        src = _vtk.vtkSphereSource()
        src.SetCenter(p_world)
        src.SetRadius(float(radius))
        src.SetPhiResolution(14)
        src.SetThetaResolution(14)
        src.Update()

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(src.GetOutputPort())

        actor = _vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(0.95)
        renderer.AddActor(actor)

        # keep the viewer's own cleanup list working (series switch clears these)
        if not hasattr(vtk_widget, '_nipple_marker_actors'):
            vtk_widget._nipple_marker_actors = []
        vtk_widget._nipple_marker_actors.append(actor)

        _render(iv)
        return actor
    except Exception as e:
        print(f"[3D-Cursor][OVERLAY] marker draw failed: {e}")
        return None


def draw_line(vtk_widget, p1: Tuple[float, float], p2: Tuple[float, float],
              color: Tuple[float, float, float] = COLOR_PECTORAL,
              line_width: float = 2.5) -> List[object]:
    """Draw a dashed line + endpoint markers. Returns the created actors."""
    actors: List[object] = []
    try:
        import vtk as _vtk
    except Exception:
        return actors
    try:
        iv, renderer, ijk_to_world = _viewer_bits(vtk_widget)
        if renderer is None:
            return actors

        p1_world = ijk_to_world(float(p1[0]), float(p1[1]), None, y_flip=True)
        p2_world = ijk_to_world(float(p2[0]), float(p2[1]), None, y_flip=True)

        src = _vtk.vtkLineSource()
        src.SetPoint1(p1_world)
        src.SetPoint2(p2_world)
        src.SetResolution(20)
        src.Update()

        mapper = _vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(src.GetOutputPort())

        actor = _vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetLineWidth(float(line_width))
        prop.SetLineStipplePattern(0xF0F0)
        prop.SetLineStippleRepeatFactor(1)
        prop.SetOpacity(0.9)
        renderer.AddActor(actor)
        actors.append(actor)

        for p in (p1, p2):
            a = draw_point_marker(vtk_widget, p[0], p[1], color=color, radius=2.5)
            if a is not None:
                actors.append(a)

        if not hasattr(vtk_widget, '_pectoral_line_actors'):
            vtk_widget._pectoral_line_actors = []
        vtk_widget._pectoral_line_actors.extend(actors)

        _render(iv)
    except Exception as e:
        print(f"[3D-Cursor][OVERLAY] line draw failed: {e}")
    return actors


def remove_actors(vtk_widget, actors: List[object]) -> None:
    """Remove actors from a viewer (used by Back/Undo and Cancel)."""
    if not actors:
        return
    try:
        iv, renderer, _ = _viewer_bits(vtk_widget)
        if renderer is None:
            return
        for a in actors:
            try:
                renderer.RemoveActor(a)
            except Exception:
                pass
            for lst_name in ('_nipple_marker_actors', '_pectoral_line_actors'):
                lst = getattr(vtk_widget, lst_name, None)
                if isinstance(lst, list) and a in lst:
                    try:
                        lst.remove(a)
                    except Exception:
                        pass
        _render(iv)
    except Exception as e:
        print(f"[3D-Cursor][OVERLAY] actor removal failed: {e}")
