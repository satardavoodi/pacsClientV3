"""
Crosshair interaction — extracted CrosshairInteractorStyle (was inner class)
and the _add_click_handler factory method for StandardMPRViewer.
"""

import logging
import math

import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class CrosshairInteractorStyle(vtk.vtkInteractorStyleImage):
    """VTK interactor style for crosshair interaction in MPR views.

    Originally an inner class of ``_add_click_handler`` that captured
    ``parent_viewer`` via closure.  Now a top-level class with an
    explicit ``parent`` parameter.
    """

    def __init__(self, picker, renderer, view_name, orientation, parent_viewer):
        super().__init__()
        self.prop_picker = picker
        self.renderer = renderer
        self.view_name = view_name
        self.orientation = orientation
        self.parent = parent_viewer
        self.dragging_handle = False
        self.current_handle = None
        self.dragging_line = False
        self.drag_axis = None
        self.drag_offset = [0, 0, 0]
        self.left_button_down = False
        self.right_button_down = False
        self.middle_button_down = False
        self.pan_active = False
        self.stack_dragging = False
        self.last_pos = None

        self.AddObserver("LeftButtonPressEvent", self.on_left_button_press)
        self.AddObserver("RightButtonPressEvent", self.on_right_button_press)
        self.AddObserver("MiddleButtonPressEvent", self.on_middle_button_press)
        self.AddObserver("MouseMoveEvent", self.on_mouse_move)
        self.AddObserver("LeftButtonReleaseEvent", self.on_left_button_release)
        self.AddObserver("RightButtonReleaseEvent", self.on_right_button_release)
        self.AddObserver("MiddleButtonReleaseEvent", self.on_middle_button_release)
        self.AddObserver("MouseWheelForwardEvent", self.on_mouse_wheel_forward)
        self.AddObserver("MouseWheelBackwardEvent", self.on_mouse_wheel_backward)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _distance_to_line_segment(self, point, line_start, line_end):
        """Calculate perpendicular distance from point to line segment"""
        dx = line_end[0] - line_start[0]
        dy = line_end[1] - line_start[1]

        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return math.sqrt((point[0] - line_start[0]) ** 2 + (point[1] - line_start[1]) ** 2)

        t = max(0, min(1, ((point[0] - line_start[0]) * dx +
                            (point[1] - line_start[1]) * dy) / length_sq))

        closest_x = line_start[0] + t * dx
        closest_y = line_start[1] + t * dy

        return math.sqrt((point[0] - closest_x) ** 2 + (point[1] - closest_y) ** 2)

    def _world_to_display(self, world_pos):
        """Convert world coordinates to display coordinates"""
        coord_converter = vtk.vtkCoordinate()
        coord_converter.SetCoordinateSystemToWorld()
        coord_converter.SetValue(world_pos[0], world_pos[1], world_pos[2])
        return coord_converter.GetComputedDisplayValue(self.renderer)

    def _get_axis_index(self):
        if self.view_name == 'axial':
            return 2
        if self.view_name == 'sagittal':
            return 0
        return 1  # coronal

    def _get_basic_slice_change(self, max_slice):
        if max_slice <= 25:
            return 10
        if max_slice <= 50:
            return 8
        if max_slice <= 75:
            return 7
        return 5

    # ------------------------------------------------------------------
    # Stack / WL / Zoom helpers
    # ------------------------------------------------------------------

    def _move_along_stack(self, delta_mm):
        scroll_dir = self.parent._get_scroll_direction(self.view_name)
        self.parent.current_position[0] += scroll_dir[0] * delta_mm
        self.parent.current_position[1] += scroll_dir[1] * delta_mm
        self.parent.current_position[2] += scroll_dir[2] * delta_mm

        self.parent._clamp_current_position()
        self.parent._update_all_crosshairs()
        self.parent._update_slice_positions()
        self.parent._synchronize_oblique_views()
        self.parent._update_slice_info_texts()
        self.parent._update_coordinates_label()
        self.parent._render_immediately(self.view_name)

    def _change_stack(self):
        if self.last_pos is None:
            return
        current_pos = self.GetInteractor().GetEventPosition()
        dy = current_pos[1] - self.last_pos[1]

        axis_index = self._get_axis_index()
        max_slice = self.parent.dims[axis_index]
        if max_slice <= 1:
            return

        basic_slice_change = self._get_basic_slice_change(max_slice)
        if abs(dy) < basic_slice_change:
            return

        step_slices = round(dy / basic_slice_change)
        if step_slices == 0:
            return

        spacing_mm = self.parent.spacing[axis_index]
        delta_mm = -step_slices * spacing_mm
        self._move_along_stack(delta_mm)
        self.last_pos = current_pos

    def _change_window_level(self):
        if self.last_pos is None:
            return
        current_pos = self.GetInteractor().GetEventPosition()
        dx = current_pos[0] - self.last_pos[0]
        dy = current_pos[1] - self.last_pos[1]

        actor = self.parent.viewers[self.view_name]['actor']
        window = actor.GetProperty().GetColorWindow()
        level = actor.GetProperty().GetColorLevel()

        dy = -dy
        new_window_center = level + (dy * 1.3)
        new_window_width = window + (dx * 1.5)

        self.parent._apply_window_level(new_window_width, new_window_center)
        self.last_pos = current_pos

    def _change_zoom(self):
        if self.last_pos is None:
            return
        current_pos = self.GetInteractor().GetEventPosition()
        dy = current_pos[1] - self.last_pos[1]

        camera = self.renderer.GetActiveCamera()
        zoom_sensitivity = 0.005

        if dy > 0:
            zoom_factor = 1 + abs(dy) * zoom_sensitivity
        elif dy < 0:
            zoom_factor = 1 / (1 + abs(dy) * zoom_sensitivity)
        else:
            return

        camera.Zoom(zoom_factor)
        self.parent._request_render(self.view_name)
        self.last_pos = current_pos

    # ------------------------------------------------------------------
    # Pan helpers
    # ------------------------------------------------------------------

    def _start_pan(self):
        if self.pan_active:
            return
        self.pan_active = True
        self.dragging_handle = False
        self.dragging_line = False
        self.parent.dragging_center = False
        self.stack_dragging = False
        try:
            super().OnMiddleButtonDown()
        except Exception:
            pass

    def _end_pan(self):
        if not self.pan_active:
            return
        self.pan_active = False
        try:
            super().OnMiddleButtonUp()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Rotation zone detection
    # ------------------------------------------------------------------

    def _is_in_rotation_zone(self, point, line_start, line_end, threshold=15):
        """Check if point is in the last 10% of a line (rotation zone)"""
        dx = line_end[0] - line_start[0]
        dy = line_end[1] - line_start[1]
        line_length = math.sqrt(dx * dx + dy * dy)

        if line_length == 0:
            return False

        t = max(0, min(1, ((point[0] - line_start[0]) * dx +
                            (point[1] - line_start[1]) * dy) / (line_length * line_length)))

        closest_x = line_start[0] + t * dx
        closest_y = line_start[1] + t * dy

        perp_distance = math.sqrt((point[0] - closest_x) ** 2 + (point[1] - closest_y) ** 2)
        if perp_distance > threshold:
            return False

        if t < 0.10:
            return 'start'
        elif t > 0.90:
            return 'end'
        else:
            return False

    # ------------------------------------------------------------------
    # Hover / cursor management
    # ------------------------------------------------------------------

    def check_handle_hover(self, click_pos):
        """Check if mouse is hovering over rotation zones, lines, or center"""
        if self.view_name not in self.parent.crosshair_actors:
            self.GetInteractor().GetRenderWindow().SetCurrentCursor(0)
            return None

        actors = self.parent.crosshair_actors[self.view_name]
        h_line_source = actors['h_line_source']
        v_line_source = actors['v_line_source']

        h_p1 = self._world_to_display(h_line_source.GetPoint1())
        h_p2 = self._world_to_display(h_line_source.GetPoint2())
        v_p1 = self._world_to_display(v_line_source.GetPoint1())
        v_p2 = self._world_to_display(v_line_source.GetPoint2())

        # PRIORITY 1: Rotation zones
        rotation_threshold = 20
        h_rotation_zone = self._is_in_rotation_zone(click_pos, h_p1, h_p2, rotation_threshold)
        if h_rotation_zone:
            self.parent._set_view_cursor(self.view_name, self.parent._get_rotation_cursor())
            return 'h_rotation'

        v_rotation_zone = self._is_in_rotation_zone(click_pos, v_p1, v_p2, rotation_threshold)
        if v_rotation_zone:
            self.parent._set_view_cursor(self.view_name, self.parent._get_rotation_cursor())
            return 'v_rotation'

        # PRIORITY 2: Visual handles
        self.prop_picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
        picked_actor = self.prop_picker.GetActor()

        if picked_actor and self.view_name in self.parent.crosshair_actors:
            handles = self.parent.crosshair_actors[self.view_name].get('handles', [])
            for handle in handles:
                if handle['actor'] == picked_actor:
                    self.parent._set_view_cursor(self.view_name, self.parent._get_rotation_cursor())
                    return 'handle'

        # PRIORITY 3: Center region (20px)
        center_world = self.parent.current_position
        center_display = self._world_to_display(center_world)

        center_distance = math.sqrt((click_pos[0] - center_display[0]) ** 2 +
                                    (click_pos[1] - center_display[1]) ** 2)

        if center_distance <= 20:
            self.parent._set_view_cursor(self.view_name, None)
            self.GetInteractor().GetRenderWindow().SetCurrentCursor(10)
            return 'center'

        # PRIORITY 4: Line hover (15px)
        h_distance = self._distance_to_line_segment(click_pos, h_p1, h_p2)
        v_distance = self._distance_to_line_segment(click_pos, v_p1, v_p2)

        line_threshold = 15

        if h_distance <= line_threshold:
            self.parent._set_view_cursor(self.view_name, None)
            angle = math.atan2(h_p2[1] - h_p1[1], h_p2[0] - h_p1[0])
            angle_deg = abs(math.degrees(angle))
            if angle_deg < 30 or angle_deg > 150:
                self.GetInteractor().GetRenderWindow().SetCurrentCursor(6)
            else:
                self.GetInteractor().GetRenderWindow().SetCurrentCursor(10)
            return 'h_line'

        if v_distance <= line_threshold:
            self.parent._set_view_cursor(self.view_name, None)
            angle = math.atan2(v_p2[1] - v_p1[1], v_p2[0] - v_p1[0])
            angle_deg = abs(math.degrees(angle))
            if 60 < angle_deg < 120:
                self.GetInteractor().GetRenderWindow().SetCurrentCursor(7)
            else:
                self.GetInteractor().GetRenderWindow().SetCurrentCursor(10)
            return 'v_line'

        # Reset cursor
        self.parent._set_view_cursor(self.view_name, None)
        self.GetInteractor().GetRenderWindow().SetCurrentCursor(0)
        return None

    # ------------------------------------------------------------------
    # Mouse button events
    # ------------------------------------------------------------------

    def on_left_button_press(self, obj, event):
        """Handle left mouse button press - rotation zones, center, or lines"""
        self.parent._set_active_view(self.view_name)
        self.left_button_down = True
        self.stack_dragging = False
        click_pos = self.GetInteractor().GetEventPosition()

        # Left + Right = Pan
        if self.right_button_down:
            self._start_pan()
            return

        if self.view_name not in self.parent.crosshair_actors:
            self.stack_dragging = True
            self.last_pos = click_pos
            self.OnLeftButtonDown()
            return

        actors = self.parent.crosshair_actors[self.view_name]
        h_line_source = actors['h_line_source']
        v_line_source = actors['v_line_source']

        h_p1 = self._world_to_display(h_line_source.GetPoint1())
        h_p2 = self._world_to_display(h_line_source.GetPoint2())
        v_p1 = self._world_to_display(v_line_source.GetPoint1())
        v_p2 = self._world_to_display(v_line_source.GetPoint2())

        # PRIORITY 1: Rotation (if enabled)
        if self.parent.rotation_enabled:
            rotation_threshold = 20

            h_rotation_zone = self._is_in_rotation_zone(click_pos, h_p1, h_p2, rotation_threshold)
            if h_rotation_zone:
                self.dragging_handle = True
                self.current_handle = 'h1' if h_rotation_zone == 'start' else 'h2'
                logger.info(f"Started rotating via horizontal line end ({self.current_handle})")
                self.OnLeftButtonDown()
                return

            v_rotation_zone = self._is_in_rotation_zone(click_pos, v_p1, v_p2, rotation_threshold)
            if v_rotation_zone:
                self.dragging_handle = True
                self.current_handle = 'v1' if v_rotation_zone == 'start' else 'v2'
                logger.info(f"Started rotating via vertical line end ({self.current_handle})")
                self.OnLeftButtonDown()
                return

            # PRIORITY 2: Visual handles
            self.prop_picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
            picked_actor = self.prop_picker.GetActor()

            if picked_actor:
                handles = self.parent.crosshair_actors[self.view_name].get('handles', [])
                for handle in handles:
                    if handle['actor'] == picked_actor:
                        self.dragging_handle = True
                        self.current_handle = handle['id']
                        logger.info(f"Started rotating via visual handle {handle['id']}")
                        self.OnLeftButtonDown()
                        return

        # PRIORITY 3: Center grab (20px)
        center_world = self.parent.current_position
        center_display = self._world_to_display(center_world)

        center_distance = math.sqrt((click_pos[0] - center_display[0]) ** 2 +
                                    (click_pos[1] - center_display[1]) ** 2)

        if center_distance <= 20:
            self.parent.dragging_center = True
            self.parent.drag_start_pos = click_pos
            logger.debug(f"Grabbed crosshair center (distance: {center_distance:.1f}px)")
            self.OnLeftButtonDown()
            return

        # PRIORITY 4: Line drag (15px)
        h_distance = self._distance_to_line_segment(click_pos, h_p1, h_p2)
        v_distance = self._distance_to_line_segment(click_pos, v_p1, v_p2)

        line_threshold = 15

        if h_distance <= line_threshold or v_distance <= line_threshold:
            picker = vtk.vtkWorldPointPicker()
            picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
            clicked_world_pos = picker.GetPickPosition()

            self.drag_offset = [
                clicked_world_pos[0] - center_world[0],
                clicked_world_pos[1] - center_world[1],
                clicked_world_pos[2] - center_world[2]
            ]

            self.dragging_line = True
            self.drag_axis = 'h' if h_distance <= v_distance else 'v'
            self.parent.drag_start_pos = click_pos

            which_line = 'horizontal' if self.drag_axis == 'h' else 'vertical'
            logger.debug(f"Grabbed {which_line} line at offset {self.drag_offset}")
            self.OnLeftButtonDown()
            return

        # Default: stack drag
        self.stack_dragging = True
        self.last_pos = click_pos
        self.OnLeftButtonDown()

    def on_mouse_move(self, obj, event):
        """Handle mouse move — drag handle to rotate or drag to move"""
        if self.pan_active:
            self.OnMouseMove()
            return

        if self.middle_button_down:
            self._change_zoom()
            return

        if self.right_button_down:
            self._change_window_level()
            return

        click_pos = self.GetInteractor().GetEventPosition()

        # Handle rotation by dragging handle
        if self.dragging_handle and self.current_handle:
            picker = vtk.vtkWorldPointPicker()
            picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
            picked_pos = picker.GetPickPosition()

            cx, cy, cz = self.parent.current_position

            if self.view_name == 'axial':
                angle = math.atan2(picked_pos[1] - cy, picked_pos[0] - cx)
            elif self.view_name == 'sagittal':
                angle = math.atan2(picked_pos[2] - cz, picked_pos[1] - cy)
            elif self.view_name == 'coronal':
                angle = math.atan2(picked_pos[2] - cz, picked_pos[0] - cx)

            if self.current_handle in ('h2', 'v2'):
                angle += math.pi

            if self.current_handle.startswith('v'):
                angle -= math.pi / 2

            angle = (angle + math.pi) % (2 * math.pi) - math.pi

            logger.debug(
                "Rotation handle=%s view=%s angle=%.2f°",
                self.current_handle,
                self.view_name,
                math.degrees(angle)
            )

            self.parent.crosshair_angles[self.view_name] = angle
            self.parent._update_all_crosshairs()
            self.parent._synchronize_oblique_views()
            return

        # Drag from line (with offset)
        if self.dragging_line:
            picker = vtk.vtkWorldPointPicker()
            picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
            picked_pos = picker.GetPickPosition()

            new_center = [
                picked_pos[0] - self.drag_offset[0],
                picked_pos[1] - self.drag_offset[1],
                picked_pos[2] - self.drag_offset[2]
            ]

            if self.view_name == 'axial':
                if self.drag_axis == 'h':
                    self.parent.current_position[1] = new_center[1]
                elif self.drag_axis == 'v':
                    self.parent.current_position[0] = new_center[0]
            elif self.view_name == 'sagittal':
                if self.drag_axis == 'h':
                    self.parent.current_position[2] = new_center[2]
                elif self.drag_axis == 'v':
                    self.parent.current_position[1] = new_center[1]
            elif self.view_name == 'coronal':
                if self.drag_axis == 'h':
                    self.parent.current_position[2] = new_center[2]
                elif self.drag_axis == 'v':
                    self.parent.current_position[0] = new_center[0]

            self.parent._update_all_crosshairs()
            self.parent._update_slice_positions()
            self.parent._synchronize_oblique_views()
            self.parent._update_slice_info_texts()
            return

        # Drag from center
        if self.parent.dragging_center:
            picker = vtk.vtkWorldPointPicker()
            picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
            picked_pos = picker.GetPickPosition()

            if self.view_name == 'axial':
                self.parent.current_position[0] = picked_pos[0]
                self.parent.current_position[1] = picked_pos[1]
            elif self.view_name == 'sagittal':
                self.parent.current_position[1] = picked_pos[1]
                self.parent.current_position[2] = picked_pos[2]
            elif self.view_name == 'coronal':
                self.parent.current_position[0] = picked_pos[0]
                self.parent.current_position[2] = picked_pos[2]

            self.parent._update_all_crosshairs()
            self.parent._update_slice_positions()
            self.parent._synchronize_oblique_views()
            self.parent._update_slice_info_texts()
            return

        if self.stack_dragging and self.left_button_down:
            self._change_stack()
            return

        # Hover cursor update
        if not self.dragging_handle and not self.parent.dragging_center and not self.dragging_line:
            self.check_handle_hover(click_pos)

        self.OnMouseMove()

    def on_left_button_release(self, obj, event):
        """Handle mouse button release"""
        self.left_button_down = False
        self.stack_dragging = False
        if self.dragging_handle:
            logger.info("Stopped rotating")
            self.dragging_handle = False
            self.current_handle = None

        if self.dragging_line:
            logger.debug("Stopped dragging from line")
            self.dragging_line = False
            self.drag_axis = None
            self.drag_offset = [0, 0, 0]

        if self.parent.dragging_center:
            self.parent.dragging_center = False

        self.parent.drag_start_pos = None
        if self.pan_active and not self.right_button_down:
            self._end_pan()
        elif self.pan_active and self.right_button_down:
            self._end_pan()
            self.last_pos = self.GetInteractor().GetEventPosition()
        if not self.right_button_down and not self.middle_button_down:
            self.last_pos = None
        self.OnLeftButtonUp()

    def on_right_button_press(self, obj, event):
        self.parent._set_active_view(self.view_name)
        self.right_button_down = True

        if self.left_button_down:
            self._start_pan()
            return

        self.last_pos = self.GetInteractor().GetEventPosition()

    def on_right_button_release(self, obj, event):
        self.right_button_down = False

        if self.pan_active and not self.left_button_down:
            self._end_pan()
            self.last_pos = None
            return

        if self.pan_active and self.left_button_down:
            self._end_pan()
            self.stack_dragging = True
            self.last_pos = self.GetInteractor().GetEventPosition()
            return

        self.last_pos = None

    def on_middle_button_press(self, obj, event):
        self.parent._set_active_view(self.view_name)
        self.middle_button_down = True
        self.last_pos = self.GetInteractor().GetEventPosition()

    def on_middle_button_release(self, obj, event):
        self.middle_button_down = False
        self.last_pos = None

    # ------------------------------------------------------------------
    # Mouse wheel (scroll through slices)
    # ------------------------------------------------------------------

    def on_mouse_wheel_forward(self, obj, event):
        """Scroll forward through slices"""
        self.parent._set_active_view(self.view_name)
        camera = self.renderer.GetActiveCamera()
        focal = list(camera.GetFocalPoint())
        pos = list(camera.GetPosition())

        scroll_dir = self.parent._get_scroll_direction(self.view_name)
        step = 2.0

        focal[0] += scroll_dir[0] * step
        focal[1] += scroll_dir[1] * step
        focal[2] += scroll_dir[2] * step
        pos[0] += scroll_dir[0] * step
        pos[1] += scroll_dir[1] * step
        pos[2] += scroll_dir[2] * step

        self.parent.current_position[0] = focal[0]
        self.parent.current_position[1] = focal[1]
        self.parent.current_position[2] = focal[2]

        camera.SetFocalPoint(focal)
        camera.SetPosition(pos)

        self.parent._update_all_crosshairs()
        self.parent._synchronize_oblique_views()
        self.parent._update_slice_info_texts()
        self.parent._update_coordinates_label()
        self.parent._render_immediately(self.view_name)

    def on_mouse_wheel_backward(self, obj, event):
        """Scroll backward through slices"""
        self.parent._set_active_view(self.view_name)
        camera = self.renderer.GetActiveCamera()
        focal = list(camera.GetFocalPoint())
        pos = list(camera.GetPosition())

        scroll_dir = self.parent._get_scroll_direction(self.view_name)
        step = 2.0

        focal[0] -= scroll_dir[0] * step
        focal[1] -= scroll_dir[1] * step
        focal[2] -= scroll_dir[2] * step
        pos[0] -= scroll_dir[0] * step
        pos[1] -= scroll_dir[1] * step
        pos[2] -= scroll_dir[2] * step

        self.parent.current_position[0] = focal[0]
        self.parent.current_position[1] = focal[1]
        self.parent.current_position[2] = focal[2]

        camera.SetFocalPoint(focal)
        camera.SetPosition(pos)

        self.parent._update_all_crosshairs()
        self.parent._synchronize_oblique_views()
        self.parent._update_slice_info_texts()
        self.parent._update_coordinates_label()
        self.parent._render_immediately(self.view_name)


class _MprCrosshairInteractMixin:
    """Mixin: _add_click_handler factory that creates CrosshairInteractorStyle."""

    def _add_click_handler(self, vtk_widget, renderer, view_name):
        """Add click and drag handlers for crosshair position and rotation"""
        interactor = vtk_widget.GetRenderWindow().GetInteractor()

        prop_picker = vtk.vtkPropPicker()

        if view_name == 'axial':
            orientation = 2
        elif view_name == 'sagittal':
            orientation = 0
        else:
            orientation = 1

        style = CrosshairInteractorStyle(
            prop_picker, renderer, view_name, orientation, parent_viewer=self
        )
        interactor.SetInteractorStyle(style)
        self.crosshair_styles[view_name] = style
