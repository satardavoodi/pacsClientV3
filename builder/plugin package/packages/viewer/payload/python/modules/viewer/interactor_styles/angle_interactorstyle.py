import math
import vtkmodules.all as vtk
from . import AbstractInteractorStyle
from .tools_object_manager import AngleObject


class AngleInteractorStyle(AbstractInteractorStyle):
    """
      - (A, B, C) ➜ angle ABC
    """

    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.image_viewer = image_viewer

        # self.cursor_mode = vtk.VTK_CURSOR_ARROW
        self.n_clicks = 0
        self.active_widget = self.create_widget()

        # Make sure the widget is off initially
        self.active_widget.Off()
        self.is_active = False
        self.color = (0, 0.9, 0)
        self.interactor_name = self.tool_access.ANGLE
        self._dragging_obj = None
        self._drag_start_world = None
        self._drag_start_points = None
        self._hover_obj = None
        self._drag_hit_distance_px = 10
        self._drag_edge_ratio = 0.1

    def create_widget(self):
        widget = vtk.vtkAngleWidget()
        widget.CreateDefaultRepresentation()
        widget.SetInteractor(self.image_viewer.image_interactor)
        widget.AddObserver(vtk.vtkCommand.PlacePointEvent, self.place_point_event)
        # widget.KeyPressActivationOff()
        return widget

    def place_point_event(self, obj, event):
        # Only process events if the ruler tool is active

        if not self.is_active:
            return

        self.n_clicks += 1

        if self.n_clicks == 3:
            # Store the widget with its slice
            angle_object = AngleObject(self.active_widget, default_color=self.color)
            # angle_object.change_color((0.1, 0.5, 1.0))
            self.add_object_to_store_widgets(angle_object, self.tool_access.ANGLE)

            # reset to default
            self.n_clicks = 0
            self.active_widget.Off()
            self.is_active = False
            self.active_widget = self.create_widget()
            self.auto_deactivate_tool()
            return

        self.image_viewer.Render()

    def activate(self, tool=None):
        """
        Activate the angle tool.
        """
        if not self.is_active:
            self.is_active = True
            self.__On_active_widget()

            # # Update current slice
            # self.current_slice = self.image_viewer.GetSlice()

            # # Show only widgets for the current slice
            self.update_slice()

            # Update the cursor
            # self.set_cursor(vtk.VTK_CURSOR_CROSSHAIR)
            # print("Angle tool activated")
            self.image_viewer.Render()

    def deactivate(self, tool=None):
        """
        Deactivate the ruler tool.
        """
        if self.is_active:
            self.is_active = False
            # Disable the active widget
            self.active_widget.Off()
            # print("Angle tool deactivated")
            self.image_viewer.Render()

    def _set_cursor(self, cursor_type):
        if hasattr(self.image_viewer.image_interactor, 'SetCursor'):
            self.image_viewer.image_interactor.SetCursor(cursor_type)

    def _find_drag_target(self, mouse_pos):
        current_slice = self.image_viewer.GetSlice()
        if current_slice not in self.widgets_by_slice:
            return None

        closest_obj = None
        closest_points = None
        min_distance = self._drag_hit_distance_px

        for obj in self.widgets_by_slice[current_slice]:
            if not hasattr(obj, self.tool_access.ANGLE):
                continue

            point_a, point_b, point_c = obj.get_position_world()
            point_a_display = self.world_to_display(point_a)
            point_b_display = self.world_to_display(point_b)
            point_c_display = self.world_to_display(point_c)
            if not point_a_display or not point_b_display or not point_c_display:
                continue

            dist_ab, t_ab = self.point_to_line_distance_and_t(mouse_pos, point_a_display, point_b_display)
            dist_bc, t_bc = self.point_to_line_distance_and_t(mouse_pos, point_b_display, point_c_display)

            if dist_ab <= min_distance and self.is_middle_segment_hit(t_ab, self._drag_edge_ratio):
                min_distance = dist_ab
                closest_obj = obj
                closest_points = (point_a, point_b, point_c)
            elif dist_bc <= min_distance and self.is_middle_segment_hit(t_bc, self._drag_edge_ratio):
                min_distance = dist_bc
                closest_obj = obj
                closest_points = (point_a, point_b, point_c)

        if closest_obj is None:
            return None
        return closest_obj, closest_points

    def set_widget_repr(self, widget):
        angle_rep = vtk.vtkAngleRepresentation2D()
        widget.SetRepresentation(angle_rep)

        # set default new color
        angle_rep.GetPoint1Representation().GetProperty().SetColor(self.color)  # change points color
        angle_rep.GetRay1().GetProperty().SetColor(self.color)  # change line 1 color
        angle_rep.GetRay2().GetProperty().SetColor(self.color)  # change line 2 color
        angle_rep.GetArc().GetProperty().SetColor(self.color)  # change arc color

    def __On_active_widget(self):
        self.active_widget.On()
        self.set_widget_repr(self.active_widget)

    def on_left_button_press(self, obj, event):
        if self.n_clicks == 0:
            mouse_pos = self.GetInteractor().GetEventPosition()
            drag_target = self._find_drag_target(mouse_pos)
            if drag_target is not None:
                obj_to_drag, points = drag_target
                self._dragging_obj = obj_to_drag
                self._drag_start_points = points
                self._drag_start_world = self.display_to_world(mouse_pos[0], mouse_pos[1])
                self._set_cursor(vtk.VTK_CURSOR_HAND)
                return True

        return super().on_left_button_press(obj, event)

    def on_mouse_move(self, obj, event):
        flag_active = super().on_mouse_move(obj, event)
        if flag_active:
            return True

        if self._dragging_obj is not None and self._drag_start_points is not None:
            current_pos = self.GetInteractor().GetEventPosition()
            current_world = self.display_to_world(current_pos[0], current_pos[1])
            if current_world is None or self._drag_start_world is None:
                return True

            dx = current_world[0] - self._drag_start_world[0]
            dy = current_world[1] - self._drag_start_world[1]
            dz = current_world[2] - self._drag_start_world[2]

            p1_start, p2_start, p3_start = self._drag_start_points
            new_p1 = [p1_start[0] + dx, p1_start[1] + dy, p1_start[2] + dz]
            new_p2 = [p2_start[0] + dx, p2_start[1] + dy, p2_start[2] + dz]
            new_p3 = [p3_start[0] + dx, p3_start[1] + dy, p3_start[2] + dz]

            widget = self._dragging_obj.get_widget()
            repr_obj = widget.GetRepresentation()
            if hasattr(repr_obj, 'SetPoint1WorldPosition'):
                repr_obj.SetPoint1WorldPosition(new_p1)
            if hasattr(repr_obj, 'SetCenterWorldPosition'):
                repr_obj.SetCenterWorldPosition(new_p2)
            if hasattr(repr_obj, 'SetPoint2WorldPosition'):
                repr_obj.SetPoint2WorldPosition(new_p3)

            self.image_viewer.renderer.ResetCameraClippingRange()
            self.image_viewer.Render()
            return True

        if self.n_clicks == 0:
            hover_target = self._find_drag_target(self.GetInteractor().GetEventPosition())
            if hover_target is not None:
                if self._hover_obj != hover_target[0]:
                    self._hover_obj = hover_target[0]
                    self._set_cursor(vtk.VTK_CURSOR_HAND)
            else:
                if self._hover_obj is not None:
                    self._hover_obj = None
                    self._set_cursor(vtk.VTK_CURSOR_ARROW)

        return False

    def on_left_button_release(self, obj, event):
        if self._dragging_obj is not None:
            self._dragging_obj = None
            self._drag_start_world = None
            self._drag_start_points = None
            self._set_cursor(vtk.VTK_CURSOR_ARROW)
            return True

        return super().on_left_button_release(obj, event)
