"""
Two-Line Angle Measurement InteractorStyle
===========================================

Measures the angle between two independent lines.
User clicks 4 points to draw 2 lines.
"""

import math
import vtkmodules.all as vtk
from . import AbstractInteractorStyle
from .tools_object_manager import TwoLineAngleObject


class TwoLineAngleInteractorStyle(AbstractInteractorStyle):
    """
    InteractorStyle for measuring angle between two independent lines
    - Click 4 times to define 2 lines (P1-P2, P3-P4)
    - Angle between the lines is calculated and displayed
    """

    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.image_viewer = image_viewer
        self.color = (0.0, 0.9, 0.9)  # Cyan color

        self.n_clicks = 0  # 0 to 4 clicks
        self.is_active = False

        # Current widget being used for point placement
        self.active_widget = self.create_widget()
        self.active_widget.Off()

        # Completed line widgets (will store vtkDistanceWidget for each line)
        self.line1_widget = None
        self.line2_widget = None

        # Text actor for angle display
        self.text_actor = None

        self.interactor_name = self.tool_access.TWO_LINE_ANGLE
        self._dragging_obj = None
        self._drag_start_world = None
        self._drag_start_points = None
        self._hover_obj = None
        self._drag_hit_distance_px = 10
        self._drag_edge_ratio = 0.1

    def create_widget(self):
        """Create a distance widget for drawing lines"""
        widget = vtk.vtkDistanceWidget()
        widget.CreateDefaultRepresentation()
        widget.SetInteractor(self.image_viewer.image_interactor)
        widget.AddObserver(vtk.vtkCommand.PlacePointEvent, self.place_point_event)
        return widget

    def activate(self, tool=None):
        """Activate the tool"""
        if not self.is_active:
            self.is_active = True
            self.__On_active_widget()  # Turn on first widget
            self.update_slice()
            self.image_viewer.Render()

    def deactivate(self, tool=None):
        """Deactivate the tool"""
        if self.is_active:
            self.is_active = False
            self.active_widget.Off()
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
            if not hasattr(obj, self.tool_access.TWO_LINE_ANGLE):
                continue

            points = obj.get_position_world()
            if not points or len(points) < 4:
                continue

            p1, p2, p3, p4 = points
            p1_display = self.world_to_display(p1)
            p2_display = self.world_to_display(p2)
            p3_display = self.world_to_display(p3)
            p4_display = self.world_to_display(p4)
            if not p1_display or not p2_display or not p3_display or not p4_display:
                continue

            dist_1, t1 = self.point_to_line_distance_and_t(mouse_pos, p1_display, p2_display)
            dist_2, t2 = self.point_to_line_distance_and_t(mouse_pos, p3_display, p4_display)

            if dist_1 <= min_distance and self.is_middle_segment_hit(t1, self._drag_edge_ratio):
                min_distance = dist_1
                closest_obj = obj
                closest_points = points
            elif dist_2 <= min_distance and self.is_middle_segment_hit(t2, self._drag_edge_ratio):
                min_distance = dist_2
                closest_obj = obj
                closest_points = points

        if closest_obj is None:
            return None
        return closest_obj, closest_points

    def place_point_event(self, obj, event):
        """Handle point placement (similar to AngleInteractorStyle)"""
        if not self.is_active:
            return

        self.n_clicks += 1

        if self.n_clicks == 2:
            # Second point of first line - complete line 1
            self.line1_widget = self.active_widget
            self.active_widget = self.create_widget()
            self.__On_active_widget()  # Turn on second widget
            
        elif self.n_clicks == 4:
            # Second point of second line - complete line 2
            self.line2_widget = self.active_widget
            
            # Calculate and display angle
            self._calculate_and_display_angle()
            
            # Save measurement
            self._complete_measurement()
            
            # Reset for next measurement
            self.n_clicks = 0
            self.active_widget.Off()
            self.is_active = False
            self.active_widget = self.create_widget()
            self.line1_widget = None
            self.line2_widget = None
            self.text_actor = None
            self.auto_deactivate_tool()
            return

        self.image_viewer.Render()

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

            p1, p2, p3, p4 = self._drag_start_points
            new_p1 = [p1[0] + dx, p1[1] + dy, p1[2] + dz]
            new_p2 = [p2[0] + dx, p2[1] + dy, p2[2] + dz]
            new_p3 = [p3[0] + dx, p3[1] + dy, p3[2] + dz]
            new_p4 = [p4[0] + dx, p4[1] + dy, p4[2] + dz]

            line1_widget, line2_widget, text_actor, _point_actors = self._dragging_obj.get_widget()
            if line1_widget:
                rep1 = line1_widget.GetDistanceRepresentation()
                rep1.SetPoint1WorldPosition(new_p1)
                rep1.SetPoint2WorldPosition(new_p2)
            if line2_widget:
                rep2 = line2_widget.GetDistanceRepresentation()
                rep2.SetPoint1WorldPosition(new_p3)
                rep2.SetPoint2WorldPosition(new_p4)

            if text_actor is not None:
                midpoint = [
                    (new_p1[0] + new_p2[0] + new_p3[0] + new_p4[0]) / 4,
                    (new_p1[1] + new_p2[1] + new_p3[1] + new_p4[1]) / 4,
                    (new_p1[2] + new_p2[2] + new_p3[2] + new_p4[2]) / 4
                ]
                display_pos = self.world_to_display(midpoint)
                if display_pos:
                    text_actor.SetPosition(display_pos[0], display_pos[1])

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

    def __On_active_widget(self):
        """Turn on and style the active widget"""
        self.active_widget.On()
        self.set_widget_repr(self.active_widget)

    def set_widget_repr(self, widget):
        """Set widget representation style for vtkDistanceWidget"""
        dist_rep = widget.GetDistanceRepresentation()
        # Style the line (axis)
        dist_rep.GetAxisProperty().SetLineWidth(3)
        dist_rep.GetAxisProperty().SetColor(self.color)
        # Hide the distance label (we only want the line)
        dist_rep.SetLabelFormat("")

    def _calculate_and_display_angle(self):
        """Calculate angle between two lines and display it"""
        # Get points from both distance widgets
        line1_rep = self.line1_widget.GetDistanceRepresentation()
        line2_rep = self.line2_widget.GetDistanceRepresentation()
        
        p1 = [0, 0, 0]
        p2 = [0, 0, 0]
        p3 = [0, 0, 0]
        p4 = [0, 0, 0]
        
        line1_rep.GetPoint1WorldPosition(p1)
        line1_rep.GetPoint2WorldPosition(p2)
        line2_rep.GetPoint1WorldPosition(p3)
        line2_rep.GetPoint2WorldPosition(p4)
        
        # Calculate angle
        angle = self._calculate_angle_between_lines(p1, p2, p3, p4)
        
        # Calculate midpoint for text placement
        midpoint = [
            (p1[0] + p2[0] + p3[0] + p4[0]) / 4,
            (p1[1] + p2[1] + p3[1] + p4[1]) / 4,
            (p1[2] + p2[2] + p3[2] + p4[2]) / 4
        ]
        
        # Create text actor
        self.text_actor = self._create_text_actor(midpoint, angle)
        self.image_viewer.renderer.AddActor(self.text_actor)

    def _calculate_angle_between_lines(self, p1, p2, p3, p4):
        """
        Calculate angle between two lines
        Line 1: p1 -> p2
        Line 2: p3 -> p4
        Returns angle in degrees (0-180)
        """
        # Calculate direction vectors
        v1 = [p2[i] - p1[i] for i in range(3)]
        v2 = [p4[i] - p3[i] for i in range(3)]
        
        # Normalize vectors
        mag1 = math.sqrt(sum(x**2 for x in v1))
        mag2 = math.sqrt(sum(x**2 for x in v2))
        
        if mag1 == 0 or mag2 == 0:
            return 0.0
        
        v1_norm = [x / mag1 for x in v1]
        v2_norm = [x / mag2 for x in v2]
        
        # Calculate dot product
        dot_product = sum(v1_norm[i] * v2_norm[i] for i in range(3))
        
        # Clamp to avoid numerical errors
        dot_product = max(-1.0, min(1.0, dot_product))
        
        # Calculate angle in radians then convert to degrees
        angle_rad = math.acos(dot_product)
        angle_deg = math.degrees(angle_rad)
        
        # Return the acute angle (0-180)
        return min(angle_deg, 180.0 - angle_deg)

    def _create_text_actor(self, position, angle):
        """Create text actor to display the angle"""
        text = f"{angle:.1f}°"
        
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(text)
        
        # Convert world coordinates to display coordinates
        display_pos = self.world_to_display(position)
        if display_pos:
            text_actor.SetPosition(display_pos[0], display_pos[1])
        
        # Style the text
        text_property = text_actor.GetTextProperty()
        text_property.SetFontSize(24)
        text_property.SetColor(self.color)
        text_property.SetBold(True)
        text_property.SetFontFamilyToArial()
        text_property.SetJustificationToCentered()
        text_property.SetVerticalJustificationToCentered()
        
        return text_actor

    def _complete_measurement(self):
        """Store the completed measurement"""
        # Get points for storage
        line1_rep = self.line1_widget.GetDistanceRepresentation()
        line2_rep = self.line2_widget.GetDistanceRepresentation()
        
        p1 = [0, 0, 0]
        p2 = [0, 0, 0]
        p3 = [0, 0, 0]
        p4 = [0, 0, 0]
        
        line1_rep.GetPoint1WorldPosition(p1)
        line1_rep.GetPoint2WorldPosition(p2)
        line2_rep.GetPoint1WorldPosition(p3)
        line2_rep.GetPoint2WorldPosition(p4)
        
        points = [list(p1), list(p2), list(p3), list(p4)]
        
        measurement_obj = TwoLineAngleObject(
            line1_actor=self.line1_widget,
            line2_actor=self.line2_widget,
            text_actor=self.text_actor,
            point_actors=[],
            points=points,
            default_color=self.color
        )
        
        self.add_object_to_store_widgets(measurement_obj, self.tool_access.TWO_LINE_ANGLE)
