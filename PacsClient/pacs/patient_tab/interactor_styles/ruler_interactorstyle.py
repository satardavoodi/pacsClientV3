import vtk
from . import AbstractInteractorStyle
from .tools_object_manager import RulerObject


class RulerInteractorStyle(AbstractInteractorStyle):
    def __init__(self, image_viewer):
        """
        Initialize the RulerInteractorStyle for handling ruler interactions.
        """
        # super().__init__()
        super().__init__(image_viewer)
        self.image_viewer = image_viewer

        self.title = ""
        self.title_format = "%-#6.3g mm"
        self.color = (0, 0.9, 0)

        self.cursor_mode = vtk.VTK_CURSOR_ARROW
        self.n_clicks = 0

        self.active_widget = self.create_widget()
        # Make sure the widget is off initially
        self.active_widget.Off()

        # Flag to track if ruler is active
        self.is_active = False

        # Store the current slice for slice-specific measurements
        self.current_slice = self.image_viewer.GetSlice()

        # # Dictionary to store widgets by slice
        # self.widgets_by_slice = {}
        self.interactor_name = self.tool_access.RULER
        self._dragging_obj = None
        self._drag_start_world = None
        self._drag_start_points = None
        self._hover_obj = None
        self._drag_hit_distance_px = 10
        self._drag_edge_ratio = 0.1

    def create_widget(self):
        widget = vtk.vtkDistanceWidget()
        widget.CreateDefaultRepresentation()
        widget.SetInteractor(self.image_viewer.image_interactor)
        widget.AddObserver(vtk.vtkCommand.PlacePointEvent, self.place_point_event)
        widget.KeyPressActivationOff()
        return widget

    def place_point_event(self, obj, event):
        # Only process events if the ruler tool is active

        if not self.is_active:
            return

        self.n_clicks += 1
        
        if self.n_clicks == 2:
            # Store the widget with its slice
            ruler_object = RulerObject(self.active_widget, default_color=self.color)
            self.add_object_to_store_widgets(ruler_object, self.tool_access.RULER)

            # reset to default
            self.n_clicks = 0
            self.active_widget.Off()
            self.is_active = False
            self.active_widget = self.create_widget()
            self.auto_deactivate_tool()
        else:
            self.emit_interaction()
            self.set_widget_repr(self.active_widget, self.color, self.title + self.title_format)

        self.image_viewer.renderer.Render()

    def set_widget_repr(self, widget, color, title):
        repr = widget.GetRepresentation()
        repr.GetAxisProperty().SetLineWidth(1)
        repr.GetAxisProperty().SetColor(color)
        # repr.GetAxis().SetTitlePosition(0.5)
        repr.GetAxis().SetTickLength(1)
        repr.SetLabelFormat(title)

        # Set font size for the measurement label
        axis = repr.GetAxis()
        axis.UseFontSizeFromPropertyOn()
        axis.GetTitleTextProperty().SetFontSize(24)

    def activate(self, tool=None):
        """
        Activate the ruler tool.
        
        Args:
            tool: Optional tool identifier (for compatibility)
        """
        if not self.is_active:
            self.is_active = True
            # Enable the active widget
            self.active_widget.On()

            # Update current slice
            self.current_slice = self.image_viewer.GetSlice()

            # Show only widgets for the current slice
            self.update_slice()

            # Update the cursor
            self.set_cursor(vtk.VTK_CURSOR_CROSSHAIR)
            self.image_viewer.GetRenderWindow().Render()

    def deactivate(self, tool=None):
        """
        Deactivate the ruler tool.
        
        Args:
            tool: Optional tool identifier (for compatibility)
        """
        if self.is_active:
            self.is_active = False
            # Disable the active widget
            self.active_widget.Off()
            self.set_cursor(vtk.VTK_CURSOR_ARROW)
            # print("Ruler tool deactivated")
            self.image_viewer.GetRenderWindow().Render()

    def set_cursor(self, cursor_type):
        """
        Set the cursor type.
        """
        self.cursor_mode = cursor_type
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
            if not hasattr(obj, self.tool_access.RULER):
                continue

            point1_world, point2_world = obj.get_position_world()
            point1_display = self.world_to_display(point1_world)
            point2_display = self.world_to_display(point2_world)
            if not point1_display or not point2_display:
                continue

            distance, t = self.point_to_line_distance_and_t(mouse_pos, point1_display, point2_display)
            if distance <= min_distance and self.is_middle_segment_hit(t, self._drag_edge_ratio):
                min_distance = distance
                closest_obj = obj
                closest_points = (point1_world, point2_world)

        if closest_obj is None:
            return None
        return closest_obj, closest_points

    # def clear_all_measurements(self):
    #     """
    #     Clear all measurements.
    #     """
    #     # Remove all widgets
    #     for widget in self.widgets:
    #         widget.Off()
    #         self.image_viewer.GetMeasurements().RemoveItem(widget)
    #
    #     # Clear the widgets list and dictionary
    #     self.widgets = []
    #     self.widgets_by_slice = {}
    #
    #     # Reset the active widget
    #     self.active_widget.Off()
    #     self.active_widget = self.create_widget()
    #     if self.is_active:
    #         self.active_widget.On()
    #
    #     # Reset the click counter
    #     self.n_clicks = 0
    #
    #     # Update the render window
    #     self.image_viewer.GetRenderWindow().Render()
    #     print("All measurements cleared")

    def on_left_button_press(self, obj, event):
        """
        Handle left mouse button press events.
        """
        # self.emit_interaction()
        mouse_pos = self.GetInteractor().GetEventPosition()
        if self.n_clicks == 0:
            drag_target = self._find_drag_target(mouse_pos)
            if drag_target is not None:
                obj_to_drag, points = drag_target
                self._dragging_obj = obj_to_drag
                self._drag_start_points = points
                self._drag_start_world = self.display_to_world(mouse_pos[0], mouse_pos[1])
                self.set_cursor(vtk.VTK_CURSOR_HAND)
                return True

        # Only handle events if the ruler tool is active
        if not self.is_active:
            # Pass the event to the parent class
            self.OnLeftButtonDown()  # Forward event to parent
            return True

        # Update current slice
        self.current_slice = self.image_viewer.GetSlice()

        # Let the vtkDistanceWidget handle the event
        # It will call place_point_event when needed
        return False  # Return False to indicate we've handled the event

    def on_mouse_move(self, obj, event):
        """
        Handle mouse movement events.
        """
        # Only handle events if the ruler tool is active
        flag_draw_line = super(RulerInteractorStyle, self).on_mouse_move(obj, event)
        if flag_draw_line:
            return True

        if self._dragging_obj is not None and self._drag_start_points is not None:
            current_pos = self.GetInteractor().GetEventPosition()
            current_world = self.display_to_world(current_pos[0], current_pos[1])
            if current_world is None or self._drag_start_world is None:
                return True

            dx = current_world[0] - self._drag_start_world[0]
            dy = current_world[1] - self._drag_start_world[1]
            dz = current_world[2] - self._drag_start_world[2]

            p1_start, p2_start = self._drag_start_points
            new_p1 = [p1_start[0] + dx, p1_start[1] + dy, p1_start[2] + dz]
            new_p2 = [p2_start[0] + dx, p2_start[1] + dy, p2_start[2] + dz]

            widget = self._dragging_obj.get_widget()
            repr_obj = widget.GetRepresentation()
            if hasattr(repr_obj, 'SetPoint1WorldPosition'):
                repr_obj.SetPoint1WorldPosition(new_p1)
            if hasattr(repr_obj, 'SetPoint2WorldPosition'):
                repr_obj.SetPoint2WorldPosition(new_p2)

            self.image_viewer.renderer.ResetCameraClippingRange()
            self.image_viewer.Render()
            return True

        if not self.is_active:
            if self.n_clicks == 0:
                hover_target = self._find_drag_target(self.GetInteractor().GetEventPosition())
                if hover_target is not None:
                    if self._hover_obj != hover_target[0]:
                        self._hover_obj = hover_target[0]
                        self.set_cursor(vtk.VTK_CURSOR_HAND)
                else:
                    if self._hover_obj is not None:
                        self._hover_obj = None
                        self.set_cursor(vtk.VTK_CURSOR_ARROW)
            # Pass the event to the parent class
            return super(RulerInteractorStyle, self).on_mouse_move(obj, event)

        # Check if we've changed slices
        current_slice = self.image_viewer.GetSlice()
        if current_slice != self.current_slice:
            self.current_slice = current_slice
            self.update_slice()

        # Let the vtkDistanceWidget handle the event
        return False  # Return False to indicate we've handled the event

    def on_left_button_release(self, obj, event):
        """
        Handle left mouse button release events.
        """
        # self.emit_interaction()

        if self._dragging_obj is not None:
            self._dragging_obj = None
            self._drag_start_world = None
            self._drag_start_points = None
            self.set_cursor(vtk.VTK_CURSOR_ARROW)
            return True

        # Only handle events if the ruler tool is active
        if not self.is_active:
            # Pass the event to the parent class
            return super(RulerInteractorStyle, self).on_left_button_release(obj, event)

        # Let the vtkDistanceWidget handle the event
        return False  # Return False to indicate we've handled the event
