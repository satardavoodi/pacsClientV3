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
            self.active_widget = self.create_widget()
            self.active_widget.On()
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

        if not self.is_active:
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

        # Only handle events if the ruler tool is active
        if not self.is_active:
            # Pass the event to the parent class
            return super(RulerInteractorStyle, self).on_left_button_release(obj, event)

        # Let the vtkDistanceWidget handle the event
        return False  # Return False to indicate we've handled the event
