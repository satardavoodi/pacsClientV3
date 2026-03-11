"""
Landmark Interactor Style — VTK point-picking mode for placing landmarks.

Extends ``vtkInteractorStyleImage`` so the user can click on a 2-D viewer
to place landmark points.  Each click calls the viewer's
``pick_world_point()`` and emits a ``point_picked`` signal with the physical
coordinates.

Visual markers are **target / crosshair** shapes with a hollow centre so the
user can see exactly where the marker is placed.  Text labels are rendered
**below** the crosshair on a high Z-layer so they always appear on top.

Colour convention — **per-landmark-index colour families** so that A/A' share
one colour, B/B' share another, etc.:

    index 0 (A/A')  → green   ``(0.2, 0.9, 0.2)``
    index 1 (B/B')  → orange  ``(1.0, 0.6, 0.1)``
    index 2 (C/C')  → cyan    ``(0.1, 0.8, 0.9)``
    index 3 (D/D')  → magenta ``(0.9, 0.3, 0.8)``
    index 4 (E/E')  → yellow  ``(1.0, 0.9, 0.2)``
    index 5+        → cycled back through the palette

Author : AI Pacs Team
Created: 2026-02-20  (crosshair markers rewrite)
"""

from __future__ import annotations

from typing import List, Literal, Tuple

import vtkmodules.all as vtk
from PySide6.QtCore import QObject, Signal


# ======================================================================
#  Signal relay (QObject cannot mix with VTK base)
# ======================================================================

class _LandmarkSignals(QObject):
    """Thin QObject relay so we can emit Qt signals from VTK callbacks."""
    point_picked = Signal(str, float, float)  # (role, x_phys, y_phys)


# ======================================================================
#  Colour palette — shared between fixed (left) and moving (right)
# ======================================================================

_LANDMARK_PALETTE = [
    (0.20, 0.90, 0.20),   # 0  green    — A/A'
    (1.00, 0.60, 0.10),   # 1  orange   — B/B'
    (0.10, 0.80, 0.90),   # 2  cyan     — C/C'
    (0.90, 0.30, 0.80),   # 3  magenta  — D/D'
    (1.00, 0.90, 0.20),   # 4  yellow   — E/E'
    (0.40, 0.55, 1.00),   # 5  blue     — F/F'
    (1.00, 0.40, 0.40),   # 6  red      — G/G'
    (0.60, 1.00, 0.60),   # 7  lime     — H/H'
]

_MARKER_RADIUS = 3.0   # fallback (mm)
_LABEL_SCALE = 2.5      # fallback

# Z-layers (higher = closer to camera = rendered on top)
_Z_MARKER = 0.5         # crosshair markers
_Z_LABEL = 1.0          # text labels — always on top


def _colour_for_index(index: int) -> Tuple[float, float, float]:
    """Return the palette colour for a 0-based landmark index."""
    return _LANDMARK_PALETTE[index % len(_LANDMARK_PALETTE)]


def _build_crosshair_polydata(
    cx: float, cy: float, cz: float,
    radius: float,
) -> vtk.vtkPolyData:
    """Build a target / crosshair marker as combined ``vtkPolyData``.

    The marker consists of:
    * An outer circle ring (no polygon fill → hollow centre).
    * Four crosshair arms that extend from a gap around the centre
      to beyond the outer ring — giving a classic gun-sight look.

    Parameters
    ----------
    cx, cy, cz : centre coordinates.
    radius : outer circle radius (physical units).

    Returns
    -------
    vtkPolyData  (wireframe-compatible; render with SetLineWidth).
    """
    append = vtk.vtkAppendPolyData()

    # ── Outer circle ring (polyline, no fill) ───────────────────────
    circle = vtk.vtkRegularPolygonSource()
    circle.SetCenter(cx, cy, cz)
    circle.SetRadius(radius)
    circle.SetNumberOfSides(48)
    circle.GeneratePolygonOff()          # outline only → hollow centre
    circle.SetNormal(0, 0, 1)
    circle.Update()
    append.AddInputData(circle.GetOutput())

    # ── Crosshair arms (4 line segments with hollow-centre gap) ──────
    gap = radius * 0.35                   # inner gap (keeps centre hollow)
    arm_end = radius * 1.5                # arms extend past the ring

    arms = [
        (cx - arm_end, cy, cz,  cx - gap, cy, cz),   # left
        (cx + gap,     cy, cz,  cx + arm_end, cy, cz),  # right
        (cx, cy - arm_end, cz,  cx, cy - gap, cz),    # up / top
        (cx, cy + gap,     cz,  cx, cy + arm_end, cz),  # down / bottom
    ]

    for x1, y1, z1, x2, y2, z2 in arms:
        line = vtk.vtkLineSource()
        line.SetPoint1(x1, y1, z1)
        line.SetPoint2(x2, y2, z2)
        line.Update()
        append.AddInputData(line.GetOutput())

    append.Update()
    return append.GetOutput()


# ======================================================================
#  Default 2-D navigation style (LMB = Pan, RMB = W/L, Scroll = Zoom)
# ======================================================================

class _PanZoomImageStyle(vtk.vtkInteractorStyleImage):
    """Default 2-D image interaction: LMB = Pan, RMB = W/L, Scroll = Zoom.

    Overrides VTK's default ``vtkInteractorStyleImage`` mapping
    (LMB→WindowLevel, RMB→Zoom) to provide a more intuitive layout:

    * **Left mouse drag** — Pan
    * **Right mouse drag** — Window / Level adjustment
    * **Scroll wheel** — Zoom (VTK default Dolly)
    """

    def __init__(self) -> None:
        super().__init__()
        # LMB → Pan
        self.AddObserver("LeftButtonPressEvent", self._start_pan)
        self.AddObserver("LeftButtonReleaseEvent", self._end_pan)
        # RMB → Window / Level
        self.AddObserver("RightButtonPressEvent", self._start_wl)
        self.AddObserver("RightButtonReleaseEvent", self._end_wl)
        # Scroll → Zoom (VTK default Dolly — no override needed)

    def _start_pan(self, obj, event):  # noqa: ARG002
        self.StartPan()

    def _end_pan(self, obj, event):  # noqa: ARG002
        self.EndPan()

    def _start_wl(self, obj, event):  # noqa: ARG002
        self.StartWindowLevel()

    def _end_wl(self, obj, event):  # noqa: ARG002
        self.EndWindowLevel()


# ======================================================================
#  Interactor style
# ======================================================================

class LandmarkInteractorStyle(vtk.vtkInteractorStyleImage):
    """Click-to-place landmark interactor for the stitching module.

    Parameters
    ----------
    image_viewer
        Must expose ``pick_world_point(display_x, display_y)``,
        ``renderer``, and ``image_interactor``.
    role
        ``"fixed"`` or ``"moving"`` — used for the signal payload so the
        controller knows which image the click came from.
    label_fn
        Optional callable ``(int) -> str`` that converts a 0-based
        point index to a display label.  Defaults to ``str(index + 1)``.
    """

    def __init__(
        self,
        image_viewer,
        role: Literal["fixed", "moving"] = "fixed",
        label_fn=None,
    ) -> None:
        super().__init__()
        self._viewer = image_viewer
        self._role: str = role
        self._enabled: bool = False
        self._label_fn = label_fn  # (int) -> str

        # Qt signal relay
        self.signals = _LandmarkSignals()

        # Visual state
        self._marker_actors: List[vtk.vtkActor] = []
        self._label_actors: List[vtk.vtkFollower] = []
        self._point_index: int = 0

        # Register VTK observers
        self.AddObserver("LeftButtonPressEvent", self._on_left_press)
        self.AddObserver("LeftButtonReleaseEvent", self._on_left_release)
        # RMB → Window / Level
        self.AddObserver("RightButtonPressEvent", self._on_right_press)
        self.AddObserver("RightButtonReleaseEvent", self._on_right_release)
        # Scroll wheel → Zoom (VTK default Dolly)

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    @property
    def point_picked(self) -> Signal:
        """Convenience accessor — ``signals.point_picked``."""
        return self.signals.point_picked

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def reset_index(self, start: int = 0) -> None:
        """Set the next marker label index (for pair numbering)."""
        self._point_index = start

    def clear_markers(self) -> None:
        """Remove all crosshair + label actors from the overlay renderer."""
        renderer = self._get_overlay_renderer()
        if renderer is None:
            return
        for actor in self._marker_actors:
            renderer.RemoveActor(actor)
        for actor in self._label_actors:
            renderer.RemoveActor(actor)
        self._marker_actors.clear()
        self._label_actors.clear()
        self._point_index = 0
        self._schedule_render()

    def highlight_markers(self, indices: set, flash_colour=(1.0, 0.1, 0.1)) -> None:
        """Visually highlight specific markers to indicate errors.

        Parameters
        ----------
        indices : set of int
            0-based landmark indices to highlight.
        flash_colour : tuple
            RGB colour for the highlighted markers (default: bright red).
        """
        for idx in indices:
            if idx < len(self._marker_actors):
                prop = self._marker_actors[idx].GetProperty()
                prop.SetColor(*flash_colour)
                prop.SetLineWidth(5.0)  # thicker than normal (3.0)
            if idx < len(self._label_actors):
                lprop = self._label_actors[idx].GetProperty()
                lprop.SetColor(*flash_colour)
        self._schedule_render()

    def reset_marker_colours(self) -> None:
        """Restore all markers to their original palette colours."""
        for idx in range(len(self._marker_actors)):
            colour = _colour_for_index(idx)
            if idx < len(self._marker_actors):
                prop = self._marker_actors[idx].GetProperty()
                prop.SetColor(*colour)
                prop.SetLineWidth(3.0)
            if idx < len(self._label_actors):
                self._label_actors[idx].GetProperty().SetColor(*colour)
        self._schedule_render()

    # ------------------------------------------------------------------
    #  Renderer helpers
    # ------------------------------------------------------------------

    def _get_overlay_renderer(self):
        """Return the overlay renderer for markers, or main renderer as fallback."""
        r = getattr(self._viewer, "overlay_renderer", None)
        if r is not None:
            return r
        return getattr(self._viewer, "renderer", None)

    # ------------------------------------------------------------------
    #  VTK callback
    # ------------------------------------------------------------------

    def _on_left_press(self, obj, event) -> None:
        if not self._enabled:
            # LMB when not in pick mode → Pan (not WindowLevel)
            self.StartPan()
            return

        interactor = self.GetInteractor()
        if interactor is None:
            return

        click_pos = interactor.GetEventPosition()
        world = self._viewer.pick_world_point(click_pos[0], click_pos[1])
        if world is None:
            return

        x_phys, y_phys = float(world[0]), float(world[1])

        # Visual feedback
        self._add_marker(world)
        self._point_index += 1

        # Emit Qt signal
        self.signals.point_picked.emit(self._role, x_phys, y_phys)

        print(f"[LandmarkPick] role={self._role} idx={self._point_index - 1} "
              f"phys=({x_phys:.2f}, {y_phys:.2f})")

    def _on_left_release(self, obj, event) -> None:
        if not self._enabled:
            self.EndPan()
            return
        self.OnLeftButtonUp()

    def _on_right_press(self, obj, event) -> None:  # noqa: ARG002
        self.StartWindowLevel()

    def _on_right_release(self, obj, event) -> None:  # noqa: ARG002
        self.EndWindowLevel()

    # ------------------------------------------------------------------
    #  Marker visualisation — crosshair / target
    # ------------------------------------------------------------------

    def _add_marker(self, world_point: Tuple[float, ...]) -> None:
        """Add a crosshair target marker and label **below** the point.

        * Markers and labels are added to the **overlay renderer**
          (layer 1) so they are always rendered on top of the image.
        * Colour is per landmark index from ``_LANDMARK_PALETTE``.
        * Sizing is resolution-independent (based on image physical extent).
        """
        renderer = self._get_overlay_renderer()
        if renderer is None:
            return

        # --- Per-index colour (A/A' = same colour, B/B' = same colour) ---
        colour = _colour_for_index(self._point_index)

        # --- Resolution-independent sizing from image physical extent ---
        vtk_img = getattr(self._viewer, "vtk_image_data", None)
        if vtk_img is not None:
            sp = vtk_img.GetSpacing()
            dims = vtk_img.GetDimensions()
            phys_w = sp[0] * max(dims[0], 1)
            phys_h = sp[1] * max(dims[1], 1)
            max_extent = max(phys_w, phys_h)
            radius = max(max_extent * 0.014, 2.0)        # ~1.4% of extent
            label_scale = max(max_extent * 0.030, 4.0)    # ~3.0% of extent
        else:
            radius = _MARKER_RADIUS
            label_scale = _LABEL_SCALE

        # --- Crosshair / target marker ---
        crosshair_pd = _build_crosshair_polydata(
            world_point[0], world_point[1], _Z_MARKER, radius,
        )

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(crosshair_pd)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*colour)
        prop.SetOpacity(1.0)
        prop.SetLineWidth(3.0)           # thick lines for visibility
        prop.SetAmbient(1.0)             # full self-illumination
        prop.SetDiffuse(0.0)             # no shading dependency
        prop.SetLighting(False)          # ignore scene lights
        renderer.AddActor(actor)
        self._marker_actors.append(actor)

        # --- Label (placed BELOW the crosshair, always on top) ---
        if self._label_fn is not None:
            label_str = self._label_fn(self._point_index)
        else:
            label_str = str(self._point_index + 1)

        label_text = vtk.vtkVectorText()
        label_text.SetText(label_str)
        label_mapper = vtk.vtkPolyDataMapper()
        label_mapper.SetInputConnection(label_text.GetOutputPort())

        label_actor = vtk.vtkFollower()
        label_actor.SetMapper(label_mapper)
        label_prop = label_actor.GetProperty()
        label_prop.SetColor(*colour)
        label_prop.SetOpacity(1.0)
        label_prop.SetAmbient(1.0)
        label_prop.SetDiffuse(0.0)
        label_prop.SetLighting(False)

        # Position: roughly centred horizontally, shifted BELOW the
        # crosshair  (positive Y = down on screen due to camera
        # ViewUp(0, -1, 0)).
        label_offset_down = radius * 1.8 + label_scale * 0.8
        label_offset_x = -label_scale * 0.3 * len(label_str)
        label_actor.SetPosition(
            world_point[0] + label_offset_x,
            world_point[1] + label_offset_down,
            _Z_LABEL,                     # highest Z → always on top
        )
        label_actor.SetScale(label_scale, label_scale, label_scale)
        label_actor.SetCamera(renderer.GetActiveCamera())
        renderer.AddActor(label_actor)
        self._label_actors.append(label_actor)

        self._schedule_render()

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _schedule_render(self) -> None:
        """Request a render refresh from the viewer."""
        try:
            if hasattr(self._viewer, "force_render_now"):
                self._viewer.force_render_now()
            elif hasattr(self._viewer, "Render"):
                self._viewer.Render()
        except Exception:
            pass
