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
            self.active_widget = self.create_widget()
            self.__On_active_widget()

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
