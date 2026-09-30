import vtkmodules.all as vtk

class CurveMPRInteractorStyle:
    """
    Helper class to attach point capturing to an existing interactor style.
    """
    def __init__(self, viewer, curve_mpr_widget, view_name='axial'):
        self.viewer = viewer
        self.curve_mpr_widget = curve_mpr_widget
        self.view_name = view_name
        
    def attach(self, interactor_style):
        self.interactor_style = interactor_style
        if interactor_style is None:
            return
        self.observer_id = interactor_style.AddObserver("LeftButtonPressEvent", self.on_left_button_press, 1.0) # High priority
        
    def on_left_button_press(self, obj, event):
        if self.curve_mpr_widget._closed or self.curve_mpr_widget._source_view != self.view_name:
            return
        interactor = obj.GetInteractor()
        pos = interactor.GetEventPosition()
        
        # Convert display coordinates to world coordinates
        info = self.viewer.viewers[self.view_name]
        renderer = info['renderer']
        picker = vtk.vtkCellPicker()
        picker.PickFromListOn()
        picker.AddPickList(info['actor'])
        if not picker.Pick(pos[0], pos[1], 0.0, renderer):
            return
        
        world_pos = picker.GetPickPosition()
        
        if world_pos:
            # Add point to Curve MPR
            self.curve_mpr_widget.add_point(world_pos)
            
        # We don't call OnLeftButtonDown here because we are just an observer.
        # The original interactor style will still process the event.

    def detach(self):
        if hasattr(self, 'observer_id'):
            self.interactor_style.RemoveObserver(self.observer_id)
            del self.observer_id
