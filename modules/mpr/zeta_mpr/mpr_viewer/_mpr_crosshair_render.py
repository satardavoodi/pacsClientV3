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
        """Calculate crosshair line endpoints with rotation support."""
        cx, cy, cz = self.current_position
        angle = self.crosshair_angles.get(view_name, 0.0)
        extend = 0.4

        if view_name == 'axial':
            len_h = (bounds[1] - bounds[0]) * extend
            len_v = (bounds[3] - bounds[2]) * extend
            h_p1 = [cx + len_h * math.cos(angle), cy + len_h * math.sin(angle), cz]
            h_p2 = [cx - len_h * math.cos(angle), cy - len_h * math.sin(angle), cz]
            v_p1 = [cx + len_v * math.cos(angle + math.pi/2), cy + len_v * math.sin(angle + math.pi/2), cz]
            v_p2 = [cx - len_v * math.cos(angle + math.pi/2), cy - len_v * math.sin(angle + math.pi/2), cz]
        elif view_name == 'sagittal':
            len_h = (bounds[3] - bounds[2]) * extend
            len_v = (bounds[5] - bounds[4]) * extend
            h_p1 = [cx, cy + len_h * math.cos(angle), cz + len_h * math.sin(angle)]
            h_p2 = [cx, cy - len_h * math.cos(angle), cz - len_h * math.sin(angle)]
            v_p1 = [cx, cy + len_v * math.cos(angle + math.pi/2), cz + len_v * math.sin(angle + math.pi/2)]
            v_p2 = [cx, cy - len_v * math.cos(angle + math.pi/2), cz - len_v * math.sin(angle + math.pi/2)]
        elif view_name == 'coronal':
            len_h = (bounds[1] - bounds[0]) * extend
            len_v = (bounds[5] - bounds[4]) * extend
            h_p1 = [cx + len_h * math.cos(angle), cy, cz + len_h * math.sin(angle)]
            h_p2 = [cx - len_h * math.cos(angle), cy, cz - len_h * math.sin(angle)]
            v_p1 = [cx + len_v * math.cos(angle + math.pi/2), cy, cz + len_v * math.sin(angle + math.pi/2)]
            v_p2 = [cx - len_v * math.cos(angle + math.pi/2), cy, cz - len_v * math.sin(angle + math.pi/2)]

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
        """Get slice information text for a view"""
        if view_name == 'axial':
            slice_num = int((self.current_position[2] - self.origin[2]) / self.spacing[2])
            return f"Axial - Slice: {slice_num}/{self.dims[2]}"
        elif view_name == 'sagittal':
            slice_num = int((self.current_position[0] - self.origin[0]) / self.spacing[0])
            return f"Sagittal - Slice: {slice_num}/{self.dims[0]}"
        elif view_name == 'coronal':
            slice_num = int((self.current_position[1] - self.origin[1]) / self.spacing[1])
            return f"Coronal - Slice: {slice_num}/{self.dims[1]}"
        return ""
