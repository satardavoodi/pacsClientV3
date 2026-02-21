import vtkmodules.all as vtk

class CurveMPRInteractorStyle:
    """
    Helper class to attach point capturing to an existing interactor style.
    """
    def __init__(self, viewer, curve_mpr_widget):
        self.viewer = viewer
        self.curve_mpr_widget = curve_mpr_widget
        
    def attach(self, interactor_style):
        self.interactor_style = interactor_style
        self.observer_id = interactor_style.AddObserver("LeftButtonPressEvent", self.on_left_button_press, 1.0) # High priority
        
    def on_left_button_press(self, obj, event):
        interactor = obj.GetInteractor()
        pos = interactor.GetEventPosition()
        
        # Convert display coordinates to world coordinates
        renderer = interactor.GetRenderWindow().GetRenderers().GetFirstRenderer()
        picker = vtk.vtkWorldPointPicker()
        picker.Pick(pos[0], pos[1], 0.0, renderer)
        
        world_pos = picker.GetPickPosition()
        
        if world_pos:
            # Add point to Curve MPR
            self.curve_mpr_widget.add_point(world_pos)
            
        # We don't call OnLeftButtonDown here because we are just an observer.
        # The original interactor style will still process the event.
