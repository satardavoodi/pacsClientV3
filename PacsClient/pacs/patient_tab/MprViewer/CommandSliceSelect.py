from vtk import *
from PySide6.QtWidgets import QSlider

class CommandSliceSelect(object):
    
    # Constructor
    def __init__(self) -> None:
        super().__init__()
        self.imagePlaneWidgets = [vtkImagePlaneWidget(), vtkImagePlaneWidget(), vtkImagePlaneWidget()]
        self.resliceCursorWidgets = [vtkResliceCursorWidget(), vtkResliceCursorWidget(), vtkResliceCursorWidget()]
        self.sliders = [QSlider(), QSlider(), QSlider()]
        self.resliceCursor = None
        self.segmentationRenderWindow = None  # Reference to 3D view render window
        
    def __call__(self, caller, ev) -> None:
        # If the reslice cursor has changed, update it on the 3D widget and the slice sliders
        if not isinstance(caller, vtkResliceCursorWidget):
            return
            
        rep = vtkResliceCursorLineRepresentation.SafeDownCast(caller.GetRepresentation())
        if not rep:
            return
            
        rc = rep.GetResliceCursorActor().GetCursorAlgorithm().GetResliceCursor()
        
        # Update image plane widgets (for 3D view)
        for i in range(0, 3):
            polyDataAlgo = self.imagePlaneWidgets[i].GetPolyDataAlgorithm()
            polyDataAlgo.SetNormal(rc.GetPlane(i).GetNormal())
            polyDataAlgo.SetCenter(rc.GetPlane(i).GetOrigin())
            self.imagePlaneWidgets[i].UpdatePlacement()
            
            # Update sliders
            if self.resliceCursor:
                self.sliders[i].setValue(int(self.resliceCursor.GetCenter()[i]))
        
        # Render 3D segmentation view
        if self.segmentationRenderWindow:
            self.segmentationRenderWindow.Render()