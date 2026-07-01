"""VTK-hosted point picking for Dental Curve MPR (FAST-compatible).

PROBLEM
-------
On the FAST/Qt viewer (the default), Dental Curve MPR collected no points: the FAST
bridge's ``enable_curved_mpr_mode`` is a no-op stub ("Not supported in Qt mode") and its
``vtk_image_data`` is a mock with no scalars. So clicks drew no markers and "Generate"
had < 2 points.

FIX (this module)
-----------------
Make Dental Curve MPR pick points on a REAL VTK surface, exactly like standard MPR and
the working "Curve MPR" button (``toggle_new_curve_mpr``): host a ``StandardMPRViewer``
on the real scalar volume (resolved via ``_resolve_mpr_volume_for_route`` →
``_load_full_vtk_for_mpr`` on FAST) and pick on its axial pane with a
``vtkWorldPointPicker``.

``DentalCurvePicker`` exposes the SAME interface the toolbar's curved-MPR panel already
expects from an ``ImageViewer2D`` — ``enable_curved_mpr_mode`` / ``_add_curved_mpr_point``
/ ``curved_mpr_points`` / ``get_curved_mpr_points`` / ``_clear_curved_mpr_visuals`` /
``vtk_image_data`` — so the existing panel + generation code (CurvedMPRGenerator +
CurvedMPRPanoramicView) works unchanged. The picking observer mirrors
``modules/mpr/zeta_mpr/CurveMPR/curve_mpr_interactor.py`` (high-priority
LeftButtonPress observer that does NOT consume the event); the sphere markers mirror
``ImageViewer2D._add_curved_mpr_point``.

PROFESSIONAL CURVE DRAWING (2026-06-22)
---------------------------------------
On top of the markers, the picker draws a live **arch spline** (vtkParametricSpline)
through the control points and **numbered labels**, and supports **undo**
(``remove_last_point``) — so the dental-arch setup feels like commercial CBCT tools
(Romexis / CS 3D). The live spline is gated by ``AIPACS_CURVED_MPR_LIVE_SPLINE``
(default on; ``=0`` → markers only). The spline is a VISUAL preview only — the actual
reconstruction still uses ``CurvedMPRGenerator``'s own centerline fit, so geometry is
unchanged.

Gated by ``AIPACS_CURVED_MPR_VTK_PICK`` (default off) at the call site. This module is
only imported on the VTK-pick path.

See docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md and
docs/reports/DENTAL_CURVE_MPR_VS_STANDARD_MPR_ALIGNMENT_2026-06-22.md.
"""

from __future__ import annotations

import logging
import os

import vtkmodules.all as vtk

logger = logging.getLogger(__name__)

# Live arch-spline preview (default on). Set AIPACS_CURVED_MPR_LIVE_SPLINE=0 for
# markers-only (kill switch if the spline drawing ever misbehaves).
_LIVE_SPLINE = os.environ.get("AIPACS_CURVED_MPR_LIVE_SPLINE", "1") != "0"


class DentalCurvePicker:
    """Collects Dental Curve MPR control points on a StandardMPRViewer's axial pane via
    vtkWorldPointPicker, drawing numbered markers + a live arch spline, and exposing the
    ImageViewer2D-compatible interface the curved-MPR panel calls.

    Parameters
    ----------
    host : StandardMPRViewer
        The VTK host whose ``viewers['axial']`` provides the renderer + interactor.
    vtk_image_data : vtkImageData
        The REAL scalar volume the generation step reslices (NOT the FAST mock).
    """

    def __init__(self, host, vtk_image_data):
        self.host = host
        self.vtk_image_data = vtk_image_data
        self.curved_mpr_mode = False
        self.curved_mpr_points = []
        self._sphere_actors = []
        self._label_actors = []
        self._spline_actor = None
        self._observer_tag = None
        self._style = None
        self._closed = False

    # -- internal: resolve the axial renderer/interactor-style off the host --------

    def _axial(self):
        viewers = getattr(self.host, "viewers", None) or {}
        return viewers.get("axial") or {}

    def _axial_renderer(self):
        return self._axial().get("renderer")

    def _axial_interactor(self):
        widget = self._axial().get("widget")
        if widget is None:
            return None
        try:
            render_window = widget.GetRenderWindow()
            if render_window is not None:
                return render_window.GetInteractor()
        except Exception:
            pass
        try:
            return widget.GetInteractor()
        except Exception:
            return None

    def _axial_style(self):
        interactor = self._axial_interactor()
        if interactor is not None:
            try:
                style = interactor.GetInteractorStyle()
                if style is not None:
                    return style
            except Exception:
                pass
        widget = self._axial().get("widget")
        try:
            return widget.GetInteractorStyle()
        except Exception:
            return None

    # -- panel-compatible interface ------------------------------------------------

    def enable_curved_mpr_mode(self, enable: bool) -> None:
        """Arm/disarm point picking on the axial pane (panel calls this)."""
        if self._closed and enable:
            return
        if not enable:
            if self._observer_tag is not None and self._style is not None:
                try:
                    self._style.RemoveObserver(self._observer_tag)
                except Exception:
                    pass
            self._observer_tag = None
            self._style = None
            self.curved_mpr_mode = False
            return

        style = self._axial_style()
        if style is None:
            logger.warning("[DENTAL-CURVE-PICK] No axial interactor style; cannot arm picking")
            return
        if self._observer_tag is None or self._style is not style:
            if self._observer_tag is not None and self._style is not None:
                try:
                    self._style.RemoveObserver(self._observer_tag)
                except Exception:
                    pass
            # High priority (1.0), non-consuming — mirrors CurveMPRInteractorStyle.
            self._style = style
            self._observer_tag = style.AddObserver(
                "LeftButtonPressEvent", self._on_left_button_press, 1.0
            )
        self.curved_mpr_mode = True

    def _on_left_button_press(self, obj, event):
        """VTK observer: convert the axial click to a 3D world point (does not consume)."""
        if not self.curved_mpr_mode or self._closed:
            return
        try:
            interactor = None
            if hasattr(obj, "GetInteractor"):
                interactor = obj.GetInteractor()
            if interactor is None:
                interactor = self._axial_interactor()
            if interactor is None:
                return
            pos = interactor.GetEventPosition()
            renderer = self._axial_renderer()
            if renderer is None:
                return
            picker = vtk.vtkWorldPointPicker()
            picked = bool(picker.Pick(pos[0], pos[1], 0.0, renderer))
            world = picker.GetPickPosition() if picked else None
            if not self._point_is_in_volume(world):
                world = self._display_to_axial_world(renderer, pos[0], pos[1])
            if not self._point_is_in_volume(world):
                return
            self._add_curved_mpr_point(world)
        except Exception:
            logger.exception("[DENTAL-CURVE-PICK] Error handling axial click")

    # CurveMPRInteractorStyle-compatible alias (in case that style is reused).
    def add_point(self, world_pos):
        self._add_curved_mpr_point(world_pos)

    def _add_curved_mpr_point(self, point_3d) -> None:
        """Append a control point and draw its marker, label, and the live arch spline."""
        if self._closed:
            return
        try:
            point = (float(point_3d[0]), float(point_3d[1]), float(point_3d[2]))
        except (TypeError, ValueError, IndexError):
            logger.warning("[DENTAL-CURVE-PICK] Ignoring invalid curve point: %r", point_3d)
            return
        self.curved_mpr_points.append(point)
        renderer = self._axial_renderer()
        if renderer is None:
            return
        try:
            self._draw_point_marker(renderer, point, len(self.curved_mpr_points))
            self._rebuild_spline(renderer)
            self._render_axial()
        except Exception:
            logger.exception("[DENTAL-CURVE-PICK] Error drawing point marker")

    def remove_last_point(self) -> None:
        """Undo: remove the most recently added control point + its marker/label."""
        if not self.curved_mpr_points:
            return
        self.curved_mpr_points.pop()
        renderer = self._axial_renderer()
        if self._sphere_actors:
            actor = self._sphere_actors.pop()
            if renderer is not None:
                try:
                    renderer.RemoveActor(actor)
                except Exception:
                    pass
        if self._label_actors:
            label = self._label_actors.pop()
            if renderer is not None:
                try:
                    renderer.RemoveActor(label)
                except Exception:
                    pass
        if renderer is not None:
            self._rebuild_spline(renderer)
            self._render_axial()

    def get_curved_mpr_points(self):
        return list(self.curved_mpr_points)

    def _point_is_in_volume(self, point) -> bool:
        if point is None:
            return False
        try:
            if len(point) < 3:
                return False
            bounds = self.vtk_image_data.GetBounds()
            eps = 1e-3
            return (
                bounds[0] - eps <= point[0] <= bounds[1] + eps
                and bounds[2] - eps <= point[1] <= bounds[3] + eps
                and bounds[4] - eps <= point[2] <= bounds[5] + eps
            )
        except Exception:
            return True

    def _display_to_axial_world(self, renderer, x, y):
        """Project a display click onto the current axial camera focal plane."""
        try:
            focal = renderer.GetActiveCamera().GetFocalPoint()
            renderer.SetWorldPoint(focal[0], focal[1], focal[2], 1.0)
            renderer.WorldToDisplay()
            display_z = renderer.GetDisplayPoint()[2]
            renderer.SetDisplayPoint(float(x), float(y), display_z)
            renderer.DisplayToWorld()
            world = renderer.GetWorldPoint()
            if world is None or world[3] == 0:
                return None
            return (world[0] / world[3], world[1] / world[3], world[2] / world[3])
        except Exception:
            return None

    def _clear_curved_mpr_visuals(self) -> None:
        renderer = self._axial_renderer()
        if renderer is not None:
            for actor in self._sphere_actors + self._label_actors:
                try:
                    renderer.RemoveActor(actor)
                except Exception:
                    pass
            if self._spline_actor is not None:
                try:
                    renderer.RemoveActor(self._spline_actor)
                except Exception:
                    pass
            self._render_axial()
        self._sphere_actors = []
        self._label_actors = []
        self._spline_actor = None

    def cleanup(self) -> None:
        """Disable picking and remove preview actors before the VTK host is destroyed."""
        if self._closed:
            return
        try:
            self.enable_curved_mpr_mode(False)
        except Exception:
            pass
        try:
            self._clear_curved_mpr_visuals()
        except Exception:
            pass
        self._closed = True

    # -- drawing helpers -----------------------------------------------------------

    def _draw_point_marker(self, renderer, point_3d, index):
        """Numbered sphere marker (first = green, rest = amber)."""
        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(point_3d[0], point_3d[1], point_3d[2])
        sphere.SetRadius(4.0)
        sphere.SetPhiResolution(12)
        sphere.SetThetaResolution(12)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        if index == 1:
            actor.GetProperty().SetColor(0.0, 1.0, 0.0)   # first point = green
        else:
            actor.GetProperty().SetColor(1.0, 0.85, 0.0)  # subsequent = amber
        renderer.AddActor(actor)
        self._sphere_actors.append(actor)

        # Numbered label (best-effort; needs vtkBillboardTextActor3D on this VTK build).
        try:
            label = vtk.vtkBillboardTextActor3D()
            label.SetInput(str(index))
            label.SetPosition(point_3d[0], point_3d[1], point_3d[2])
            prop = label.GetTextProperty()
            prop.SetFontSize(14)
            prop.SetColor(1.0, 1.0, 1.0)
            prop.SetJustificationToCentered()
            renderer.AddActor(label)
            self._label_actors.append(label)
        except Exception:
            pass  # markers still work without numbers

    def _rebuild_spline(self, renderer):
        """Redraw the live arch spline (visual preview) through the control points."""
        if self._spline_actor is not None:
            try:
                renderer.RemoveActor(self._spline_actor)
            except Exception:
                pass
            self._spline_actor = None
        if not _LIVE_SPLINE or len(self.curved_mpr_points) < 2:
            return
        try:
            vpoints = vtk.vtkPoints()
            for p in self.curved_mpr_points:
                vpoints.InsertNextPoint(p[0], p[1], p[2])
            spline = vtk.vtkParametricSpline()
            spline.SetPoints(vpoints)
            func = vtk.vtkParametricFunctionSource()
            func.SetParametricFunction(spline)
            func.SetUResolution(max(50, len(self.curved_mpr_points) * 20))
            func.Update()
            tube = vtk.vtkTubeFilter()
            tube.SetInputConnection(func.GetOutputPort())
            tube.SetRadius(1.2)
            tube.SetNumberOfSides(12)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(tube.GetOutputPort())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0.1, 0.8, 1.0)  # cyan dental arch
            renderer.AddActor(actor)
            self._spline_actor = actor
        except Exception:
            logger.exception("[DENTAL-CURVE-PICK] Error building arch spline")

    def _render_axial(self):
        widget = self._axial().get("widget")
        try:
            if widget is not None:
                widget.GetRenderWindow().Render()
        except Exception:
            pass
