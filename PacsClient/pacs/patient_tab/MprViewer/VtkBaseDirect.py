# VTK
from vtk import *

# Slice Orientation Constants
SLICE_ORIENTATION_YZ  = vtkResliceImageViewer.SLICE_ORIENTATION_YZ
SLICE_ORIENTATION_XZ  = vtkResliceImageViewer.SLICE_ORIENTATION_XZ
SLICE_ORIENTATION_XY  = vtkResliceImageViewer.SLICE_ORIENTATION_XY

# CommandSliceSelect
from CommandSliceSelect import *

class VtkBaseDirect:
    """
    Modified VtkBase that works directly with vtkImageData
    instead of reading from MHD file
    """

    def __init__(self, vtk_image_data=None):
        """
        Initialize with optional vtkImageData
        
        Args:
            vtk_image_data: Optional vtkImageData to use directly
        """
        # Image Reader - will be set later or use provided data
        self.imageReader = None
        self.vtk_image_data = vtk_image_data
        
        # Image Shift Scale
        self.imageShiftScale = vtkImageShiftScale()
        self.imageShiftScale.SetOutputScalarTypeToUnsignedChar()
        
        # Grayscale LUT
        self.grayscaleLut = vtkLookupTable()
        self.grayscaleLut.SetRange(0, 255)
        self.grayscaleLut.SetSaturationRange(0, 0)
        self.grayscaleLut.SetHueRange(0, 0)
        self.grayscaleLut.SetValueRange(0, 1)
        self.grayscaleLut.SetAlphaRange(1, 1)
        self.grayscaleLut.Build()
        
        # Image Map To Colors
        self.imageMapToColors = vtkImageMapToColors()
        self.imageMapToColors.SetLookupTable(self.grayscaleLut)
        
        # Image Window Level
        self.imageWindowLevel = vtkImageMapToWindowLevelColors()
        self.imageWindowLevel.SetWindow(255)
        self.imageWindowLevel.SetLevel(127)
        
        # Image Blend
        self.imageBlend = vtkImageBlend()
        self.imageBlend.SetOpacity(0, 1.0)
        self.imageBlend.SetOpacity(1, 0.0)
        
        # Picker
        self.picker = vtkCellPicker()
        self.picker.SetTolerance(0.005)
        
        # Property
        self.property = vtkProperty()
        
        # Reslice Cursor
        self.resliceCursor = vtkResliceCursor()
        
        # Command Slice Select
        self.commandSliceSelect = CommandSliceSelect()
        
        # Scaler Range
        self.scalerRange = [0, 0]
        
        # Connect pipeline if data is provided
        if vtk_image_data is not None:
            self._connect_pipeline(vtk_image_data)
    
    def _connect_pipeline(self, vtk_image_data):
        """Connect VTK pipeline with provided vtkImageData"""
        
        # Set the image data
        self.vtk_image_data = vtk_image_data
        
        # Get scaler range
        self.scalerRange = vtk_image_data.GetScalarRange()
        
        # Image Shift Scale - normalize to 0-255
        shift = -self.scalerRange[0]
        scale = 255.0 / (self.scalerRange[1] - self.scalerRange[0]) if self.scalerRange[1] != self.scalerRange[0] else 1.0
        
        self.imageShiftScale.SetShift(shift)
        self.imageShiftScale.SetScale(scale)
        self.imageShiftScale.SetInputData(vtk_image_data)
        self.imageShiftScale.Update()
        
        # Image Window Level
        self.imageWindowLevel.SetInputConnection(self.imageShiftScale.GetOutputPort())
        self.imageWindowLevel.Update()
        
        # Image Map To Colors
        self.imageMapToColors.SetInputConnection(self.imageWindowLevel.GetOutputPort())
        self.imageMapToColors.Update()
        
        # Image Blend
        self.imageBlend.AddInputConnection(self.imageWindowLevel.GetOutputPort())
        self.imageBlend.AddInputConnection(self.imageWindowLevel.GetOutputPort())
        self.imageBlend.Update()
        
        # Set center for reslice cursor
        center = vtk_image_data.GetCenter()
        self.resliceCursor.SetCenter(center)
        self.resliceCursor.SetImage(self.imageBlend.GetOutput())
        self.resliceCursor.SetThickMode(0)
        self.resliceCursor.SetThickness(10, 10, 10)
    
    def connect_on_data(self, vtk_image_data):
        """
        Connect to new vtkImageData
        
        Args:
            vtk_image_data: vtkImageData object to visualize
        """
        if vtk_image_data is None:
            raise ValueError("vtk_image_data cannot be None")
        
        self._connect_pipeline(vtk_image_data)

