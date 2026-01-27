# ignore pylint
# pylint: disable-msg=E0611,E0602
import numpy as np
from VtkBaseDirect import VtkBaseDirect

from vtk import *
import vtk.qt
vtk.qt.QVTKRWIBase = "QGLWidget"
from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

SLICE_ORIENTATION_YZ  = vtkResliceImageViewer.SLICE_ORIENTATION_YZ
SLICE_ORIENTATION_XZ  = vtkResliceImageViewer.SLICE_ORIENTATION_XZ
SLICE_ORIENTATION_XY  = vtkResliceImageViewer.SLICE_ORIENTATION_XY

class VtkViewerDirect(QVTKRenderWindowInteractor):
    """
    Modified VtkViewer that works with VtkBaseDirect
    (no imageReader, uses vtk_image_data directly)
    """

    # Constructor
    def __init__(self, label:str, vtkBaseClass:VtkBaseDirect):
        super(VtkViewerDirect, self).__init__()
        
        # Properties
        self.label = label
        self.vtkBaseClass = vtkBaseClass
        
        # Vtk Stuff
        ## Image Shift Scale
        self.imageShiftScale = self.vtkBaseClass.imageShiftScale
        
        ## Image Window Level
        self.imageWindowLevel = self.vtkBaseClass.imageWindowLevel
        
        ## Image Blend
        self.imageBlend = self.vtkBaseClass.imageBlend
        
        ## Renderer
        self.renderer = vtkRenderer()
        
        ## Render Window
        self.renderWindow = self.GetRenderWindow()
        self.renderWindow.SetMultiSamples(0)
        self.renderWindow.AddRenderer(self.renderer)
                
        ## Interactor
        self.renderWindowInteractor = self.renderWindow.GetInteractor()
        
        ## Label Text Actor
        self.labelTextActor = vtkTextActor() 
        s = f"{self.label}"
        self.labelTextActor.SetInput(s)
        self.labelTextActor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        self.labelTextActor.GetPositionCoordinate().SetValue(0.7, 0.87)
        self.renderer.AddViewProp(self.labelTextActor)

        # Render 
        self.render()

    # Destructor
    def closeEvent(self, QCloseEvent):
        super().closeEvent(QCloseEvent)
        self.renderer.FastDelete()
        self.Finalize()

    # Connect on data
    def connect_on_data(self, path:str):
        """
        For VtkBaseDirect, path is not used since data is already loaded
        This method is kept for compatibility but does nothing
        """
        pass
    
    def update(self):
        """Update method that doesn't rely on imageReader"""
        # Update the pipeline
        self.imageShiftScale.Update()
        self.imageWindowLevel.Update()
        self.imageBlend.Update()
        
        # Update render window
        self.GetRenderWindow().Modified()
        self.renderer.ResetCamera()

    # Render       
    def render(self):
        self.update()
        self.GetRenderWindow().Render()

