"""
Crosshair visual creation, endpoint calculation, handles, and text overlays
for StandardMPRViewer.
"""

import logging
import math

import vtkmodules.all as vtk
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor

logger = logging.getLogger(__name__)


class _MprCrosshairRenderMixin:
    """Mixin: crosshair lines, handles, slice info text, orientation labels."""

    @staticmethod
    def _force_crosshair_on_top(mapper):
        """Make a crosshair line / handle mapper ALWAYS render on top of the MPR image slice.

        The crosshair actors live in the same renderer as the image and sit in (or near) the slice
        plane, so by default they z-fight with the slice and — once the crosshair is rotated and the
        reconstructed views show a tilted oblique plane — parts of the lines fall at/behind the image
        and get clipped/disappear. Biasing the mapper's depth toward the camera (coincident-topology
        polygon/line/point offset, large negative units) makes its fragments win the depth test
        against the coplanar/tilted image so the crosshair is drawn on top in every view. The bias
        only shifts the depth-buffer value used for the test, NOT the on-screen position — so the
        crosshair stays geometrically exact (correct for measurements/orientation).
        """
        try:
            mapper.SetResolveCoincidentTopologyToPolygonOffset()
            if hasattr(mapper, 'SetRelativeCoincidentTopologyPolygonOffsetParameters'):
                mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-1.0, -66000.0)
            if hasattr(mapper, 'SetRelativeCoincidentTopologyLineOffsetParameters'):
                mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -66000.0)
            if hasattr(mapper, 'SetRelativeCoincidentTopologyPointOffsetParameter'):
                mapper.SetRelativeCoincidentTopologyPointOffsetParameter(-66000.0)
        except Exception as exc:
            logger.debug("[ZETA_MPR] crosshair depth-bias (on-top) failed: %r", exc)

    def _create_crosshairs(self, renderer, view_name):
        """Create crosshair lines with interactive handles for a view"""
        bounds = self.image_data.GetBounds()
        h_p1, h_p2, v_p1, v_p2 = self._calculate_crosshair_endpoints(view_name, bounds)

        # Horizontal line
        h_line_source = vtk.vtkLineSource()
        h_line_source.SetPoint1(h_p1)
        h_line_source.SetPoint2(h_p2)
        h_line_mapper = vtk.vtkPolyDataMapper()
        h_line_mapper.SetInputConnection(h_line_source.GetOutputPort())
        h_line_actor = vtk.vtkActor()
        h_line_actor.SetMapper(h_line_mapper)
        h_line_actor.GetProperty().SetColor(*self.crosshair_color)
        h_line_actor.GetProperty().SetLineWidth(self.crosshair_width)

        # Vertical line
        v_line_source = vtk.vtkLineSource()
        v_line_source.SetPoint1(v_p1)
        v_line_source.SetPoint2(v_p2)
        v_line_mapper = vtk.vtkPolyDataMapper()
        v_line_mapper.SetInputConnection(v_line_source.GetOutputPort())
        v_line_actor = vtk.vtkActor()
        v_line_actor.SetMapper(v_line_mapper)
        v_line_actor.GetProperty().SetColor(*self.crosshair_color)
        v_line_actor.GetProperty().SetLineWidth(self.crosshair_width)

        # Keep the crosshair lines on top of the image in every view (incl. rotated/oblique).
        self._force_crosshair_on_top(h_line_mapper)
        self._force_crosshair_on_top(v_line_mapper)

        renderer.AddActor(h_line_actor)
        renderer.AddActor(v_line_actor)

        handles = self._create_crosshair_handles(renderer, h_p1, h_p2, v_p1, v_p2, view_name)

        self.crosshair_actors[view_name] = {
            'h_line_source': h_line_source,
            'h_line_actor': h_line_actor,
            'v_line_source': v_line_source,
            'v_line_actor': v_line_actor,
            'handles': handles
        }
        logger.info(f"Crosshairs with handles created for {view_name} view")

    def _calculate_crosshair_endpoints(self, view_name, bounds):
        """Calculate crosshair line endpoints with rotation support.

        Builds the two lines in this pane's ACTUAL in-plane axes (h_axis, v_axis) from
        _view_axes(): the horizontal line spans h_axis, the vertical line spans v_axis, both held
        at the crosshair's through-plane (look-axis) coordinate. For an axial-native volume the
        axes are the legacy (X,Y)/(Y,Z)/(X,Z) triples, so the result is byte-identical; for a
        routed non-axial-native series the lines correctly lie in the displayed plane.
        """
        look_axis, h_axis, v_axis = self._view_axes(view_name)
        center = list(self.current_position)
        angle = self.crosshair_angles.get(view_name, 0.0)
        extend = 0.4
        len_h = (bounds[2 * h_axis + 1] - bounds[2 * h_axis]) * extend
        len_v = (bounds[2 * v_axis + 1] - bounds[2 * v_axis]) * extend

        def _pt(d_h, d_v):
            p = list(center)
            p[h_axis] += d_h
            p[v_axis] += d_v
            return p

        ca, sa = math.cos(angle), math.sin(angle)
        ca2, sa2 = math.cos(angle + math.pi / 2), math.sin(angle + math.pi / 2)
        h_p1 = _pt(len_h * ca,  len_h * sa)
        h_p2 = _pt(-len_h * ca, -len_h * sa)
        v_p1 = _pt(len_v * ca2,  len_v * sa2)
        v_p2 = _pt(-len_v * ca2, -len_v * sa2)
        return h_p1, h_p2, v_p1, v_p2

    def _create_crosshair_handles(self, renderer, h_p1, h_p2, v_p1, v_p2, view_name):
        """Create rounded handles at crosshair endpoints (modernized)"""
        handles = []
        handle_radius = 5.5
        handle_positions = [('h1', h_p1), ('h2', h_p2), ('v1', v_p1), ('v2', v_p2)]

        for handle_id, pos in handle_positions:
            sphere = vtk.vtkSphereSource()
            sphere.SetRadius(handle_radius)
            sphere.SetThetaResolution(16)
            sphere.SetPhiResolution(16)
            sphere.SetCenter(pos)

            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(sphere.GetOutputPort())
            # Keep the handles on top of the image too (same depth-bias as the lines).
            self._force_crosshair_on_top(mapper)

            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*self.crosshair_handle_color)
            actor.GetProperty().SetOpacity(0.95)
            actor.GetProperty().SetAmbient(0.3)
            actor.GetProperty().SetDiffuse(0.7)
            actor.GetProperty().SetSpecular(0.4)
            actor.GetProperty().SetSpecularPower(25)

            renderer.AddActor(actor)
            handles.append({
                'id': handle_id,
                'actor': actor,
                'source': sphere,
                'position': pos
            })

        return handles

    def _get_rotation_cursor(self):
        """Return a built-in cursor for rotation behavior."""
        if self._rotation_cursor is not None:
            return self._rotation_cursor
        self._rotation_cursor = QCursor(Qt.CursorShape.SizeAllCursor)
        return self._rotation_cursor

    def _set_view_cursor(self, view_name, cursor):
        """Set a Qt cursor on a specific view widget."""
        if view_name in self.viewers:
            widget = self.viewers[view_name]['widget']
            if cursor is None:
                widget.unsetCursor()
            else:
                widget.setCursor(cursor)

    # ── Hover cursors (2026-08-23) ────────────────────────────────────────
    # ONE cursor API, cached. The crosshair hover path used to drive the cursor
    # through BOTH Qt (`_set_view_cursor`, synchronous) and VTK
    # (`RenderWindow.SetCurrentCursor`, which QVTKRenderWindowInteractor applies
    # a full event-loop turn later via `QTimer.singleShot(0, ShowCursor)`). In
    # the centre zone those two writes DISAGREED — Qt was told "no cursor"
    # (arrow) and VTK was told "crosshair" on the same frame — so the pointer
    # alternated between two glyphs with different hotspots at the hover
    # cadence. That is the reported "cursor shakes over the crosshair centre".
    # Every shape the hover path needs, as a real QCursor, so VTK is never used.
    _HOVER_CURSOR_SHAPES = {
        'arrow':   Qt.CursorShape.ArrowCursor,
        'cross':   Qt.CursorShape.CrossCursor,
        'sizeall': Qt.CursorShape.SizeAllCursor,
        'sizever': Qt.CursorShape.SizeVerCursor,
        'sizehor': Qt.CursorShape.SizeHorCursor,
    }

    def _get_hover_cursor(self, shape):
        """Cached QCursor for a hover zone. Unknown names fall back to arrow."""
        cache = getattr(self, '_hover_cursor_cache', None)
        if cache is None:
            cache = {}
            self._hover_cursor_cache = cache
        cur = cache.get(shape)
        if cur is None:
            cur = QCursor(self._HOVER_CURSOR_SHAPES.get(
                shape, Qt.CursorShape.ArrowCursor))
            cache[shape] = cur
        return cur

    def _create_slice_info_text(self, renderer, view_name):
        """Create text annotation showing slice information and orientation labels"""
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(self._get_slice_info_text(view_name))
        text_actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        text_actor.SetPosition(0.02, 0.95)

        text_property = text_actor.GetTextProperty()
        text_property.SetFontSize(12)
        text_property.SetColor(0.6, 0.9, 0.75)
        text_property.SetBold(False)
        text_property.SetShadow(False)
        text_property.SetFontFamilyToArial()

        renderer.AddViewProp(text_actor)
        self.text_actors[view_name] = text_actor
        self._add_orientation_labels(renderer, view_name)
        logger.info(f"Slice info text created for {view_name} view")

    def _add_orientation_labels(self, renderer, view_name):
        """Add anatomical orientation labels to viewport edges"""
        try:
            labels = self._get_orientation_labels()
            view_labels = labels.get(view_name, {})

            positions = [
                ('left',   0.02, 0.5,  None),
                ('right',  0.95, 0.5,  'right'),
                ('top',    0.5,  0.95, 'center'),
                ('bottom', 0.5,  0.02, 'center'),
            ]
            for key, x, y, justify in positions:
                actor = vtk.vtkTextActor()
                actor.SetInput(view_labels.get(key, ''))
                actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
                actor.SetPosition(x, y)
                tp = actor.GetTextProperty()
                tp.SetFontSize(14)
                tp.SetColor(0.8, 0.85, 0.9)
                tp.SetBold(False)
                tp.SetShadow(False)
                if justify == 'right':
                    tp.SetJustificationToRight()
                elif justify == 'center':
                    tp.SetJustificationToCentered()
                renderer.AddViewProp(actor)

            logger.debug(f"Orientation labels added to {view_name} view: {view_labels}")
        except Exception as e:
            logger.warning(f"Could not add orientation labels to {view_name}: {e}")

    def _get_slice_info_text(self, view_name):
        """Get slice information text for a view.

        Uses the pane's ACTUAL look-axis when the plane-aware anatomical cameras are active
        (``self._anat_look_axis``), so the slice count matches the displayed plane even when
        the native acquisition plane was routed to a different pane (e.g. a sagittal-acquired
        series). Falls back to the legacy fixed axis map otherwise."""
        axis_map = {'axial': 2, 'sagittal': 0, 'coronal': 1}
        axis = axis_map.get(view_name, 2)
        if getattr(self, '_mpr_use_anatomical', False):
            la = getattr(self, '_anat_look_axis', None)
            if isinstance(la, dict) and view_name in la:
                axis = int(la[view_name])
        try:
            slice_num = int((self.current_position[axis] - self.origin[axis]) / self.spacing[axis])
            total = int(self.dims[axis])
        except Exception:
            slice_num, total = 0, 0
        label = view_name.capitalize() if view_name else ""
        return f"{label} - Slice: {slice_num}/{total}"
