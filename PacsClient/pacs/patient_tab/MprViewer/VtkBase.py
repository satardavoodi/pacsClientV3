"""
MPR VTK Base Module

To enable orientation fix for MHD files:
    MPR_FIX_ORIENTATION=1 python main.py

To disable:
    unset MPR_FIX_ORIENTATION
    (or on Windows: set MPR_FIX_ORIENTATION=0)
"""

import os
from vtk import *
from CommandSliceSelect import *

class VtkBase():
    
    # Constructor
    def __init__(self) -> None:
        
        ## Reader
        self.imageReader = vtkMetaImageReader()
        temp_path = "./temp/out.mhd"
        self.imageReader.SetFileName(temp_path) 
        self.imageReader.UpdateWholeExtent()
        
        ## Update the data information
        self.update_data_information()
        
        ## Filters 
        ### Image Shift Scale
        self.imageShiftScale = vtkImageShiftScale()
        self.imageShiftScale.SetInputData(self.imageReader.GetOutput())
        self.imageShiftScale.SetOutputScalarTypeToUnsignedChar()
        self.imageShiftScale.SetShift(-float(self.scalerRange[0]))
        self.imageShiftScale.UpdateWholeExtent()
        
        ### Image Window Level *
        self.imageWindowLevel = vtkImageMapToWindowLevelColors()
        self.imageWindowLevel.SetInputConnection(self.imageShiftScale.GetOutputPort())
        self.imageWindowLevel.UpdateWholeExtent()
        
        ### Image Map To Colors **
        self.imageMapToColors = vtkImageMapToColors()
        self.imageMapToColors.SetOutputFormatToRGBA()
        self.imageMapToColors.SetInputData(self.imageWindowLevel.GetOutput())

        ### Grayscale LUT. **
        self.grayscaleLut = vtkLookupTable()
        self.grayscaleLut.SetNumberOfTableValues(256)
        self.grayscaleLut.SetTableRange(0, 255)
        self.grayscaleLut.SetRampToLinear()
        self.grayscaleLut.SetHueRange(0, 0)
        self.grayscaleLut.SetSaturationRange(0, 0)
        self.grayscaleLut.SetValueRange(0, 1)
        self.grayscaleLut.SetAlphaRange(1, 1)
        self.grayscaleLut.Build()
        self.imageMapToColors.SetLookupTable(self.grayscaleLut)
        self.imageMapToColors.UpdateWholeExtent()
        
        ## Image Blend
        self.imageBlend = vtkImageBlend()
        self.imageBlend.AddInputData(self.imageMapToColors.GetOutput())
        self.imageBlend.UpdateWholeExtent()
        
        ## Picker        
        self.picker = vtkCellPicker()
        self.picker.SetTolerance(0.05)
        
        ## Property
        self.property = vtkProperty()

        ## Image Reslice
        self.resliceCursor = vtkResliceCursor()
        self.resliceCursor.SetThickMode(0)
        self.resliceCursor.SetImage(self.imageBlend.GetOutput())
        self.resliceCursor.SetCenter(self.imageBlend.GetOutput().GetCenter())
       
        ## Command Slice Select
        self.commandSliceSelect = CommandSliceSelect()

    # Connect to data
    def connect_on_data(self, path:str):
        if path == "":
            return
        
        # Check if orientation fix is enabled
        fix_orientation = os.environ.get("MPR_FIX_ORIENTATION", "0") == "1"
        use_sitk_loader = fix_orientation and path.lower().endswith(".mhd")
        
        # Debug logging
        print(f"[VtkBase DEBUG] path: {path}")
        print(f"[VtkBase DEBUG] MPR_FIX_ORIENTATION env: {os.environ.get('MPR_FIX_ORIENTATION', 'NOT SET')}")
        print(f"[VtkBase DEBUG] fix_orientation: {fix_orientation}")
        print(f"[VtkBase DEBUG] path.lower().endswith('.mhd'): {path.lower().endswith('.mhd')}")
        print(f"[VtkBase DEBUG] use_sitk_loader: {use_sitk_loader}")
        
        if use_sitk_loader:
            # Use SimpleITK loader for proper orientation handling
            try:
                from .mpr_volume_loader import read_mhd_via_sitk_and_make_identity, numpy_to_vtk_image
            except ImportError:
                # Fallback for when running outside package context
                import sys
                loader_dir = os.path.dirname(os.path.abspath(__file__))
                if loader_dir not in sys.path:
                    sys.path.insert(0, loader_dir)
                from mpr_volume_loader import read_mhd_via_sitk_and_make_identity, numpy_to_vtk_image
            
            np_zyx, spacing, origin = read_mhd_via_sitk_and_make_identity(path)
            vtk_img = numpy_to_vtk_image(np_zyx, spacing, origin)
            
            # Update scalar range from vtk image
            self.scalerRange = vtk_img.GetScalarRange()
            
            # Update dimensions and bounds
            self.imageDimensions = vtk_img.GetDimensions()
            self.bounds = vtk_img.GetBounds()
            
            # Set input directly to imageShiftScale (bypass vtkMetaImageReader)
            self.imageShiftScale.SetInputData(vtk_img)
        else:
            # Default path: use vtkMetaImageReader
            self.imageReader.SetFileName(path)
            self.imageReader.Update()  # بجای UpdateWholeExtent
            self.imageReader.UpdateWholeExtent()
            
            # Update the data information
            self.update_data_information()
            
            # Set input from reader
            self.imageShiftScale.SetInputData(self.imageReader.GetOutput())
        
        ## Image Shift Scale
        self.imageShiftScale.SetShift(-float(self.scalerRange[0]))
        if self.scalerRange[1] != self.scalerRange[0]:
            self.imageShiftScale.SetScale(255.0/(float(self.scalerRange[1] - self.scalerRange[0])))
        else:
            self.imageShiftScale.SetScale(1.0)
        self.imageShiftScale.Update()  # اضافه شد
        self.imageShiftScale.UpdateWholeExtent()

        ### Image Window Level
        self.imageWindowLevel.SetInputConnection(self.imageShiftScale.GetOutputPort())
        self.imageWindowLevel.SetWindow(100.0)
        self.imageWindowLevel.SetLevel(50.0)
        self.imageWindowLevel.Update()  # اضافه شد
        self.imageWindowLevel.UpdateWholeExtent()

        ### Image Map To Colors
        self.imageMapToColors.SetOutputFormatToRGBA()
        self.imageMapToColors.SetInputData(self.imageWindowLevel.GetOutput())
        self.imageMapToColors.Update()  # اضافه شد
        self.imageMapToColors.UpdateWholeExtent()
        
        ### Image Blend
        self.imageBlend.RemoveAllInputs()
        self.imageBlend.AddInputData(self.imageMapToColors.GetOutput())
        self.imageBlend.SetOpacity(0, 1.0)
        self.imageBlend.Update()  # اضافه شد
        self.imageBlend.UpdateWholeExtent()
        
        ### Reslice Cursor        
        self.resliceCursor.SetImage(self.imageBlend.GetOutput())
        self.resliceCursor.SetCenter(self.imageBlend.GetOutput().GetCenter())
        self.resliceCursor.Update()  # اضافه شد
        
    # Update data information
    def update_data_information(self):
        # Calculate the scaler range of data
        self.scalerRange = self.imageReader.GetOutput().GetScalarRange()
        
        # Calculate the dimensions of data
        self.imageDimensions = self.imageReader.GetOutput().GetDimensions()
        
        # Calculate the bounds of the data
        self.bounds = self.imageReader.GetOutput().GetBounds()
    
    def set_window_level(self, window_width, window_center):
        """
        Set window/level using DICOM HU values.
        Converts DICOM window/level to 0-255 range used internally.
        
        Args:
            window_width: Window width in HU (e.g., 400 for soft tissue)
            window_center: Window center/level in HU (e.g., 40 for soft tissue)
        """
        if window_width is None or window_center is None:
            return
            
        try:
            # Get the scale factor used in imageShiftScale
            scaler_min = self.scalerRange[0]
            scaler_max = self.scalerRange[1]
            
            if scaler_max != scaler_min:
                scale = 255.0 / (scaler_max - scaler_min)
            else:
                scale = 1.0
            
            # Convert DICOM window/level to 0-255 range
            # Since shift = -scaler_min, the new value = (original + shift) * scale
            # new_center = (window_center - scaler_min) * scale
            # new_width = window_width * scale
            new_center = (float(window_center) - scaler_min) * scale
            new_width = float(window_width) * scale
            
            # Apply to imageWindowLevel
            self.imageWindowLevel.SetWindow(new_width)
            self.imageWindowLevel.SetLevel(new_center)
            self.imageWindowLevel.Update()
            self.imageWindowLevel.UpdateWholeExtent()
            
            # Update downstream pipeline
            self.imageMapToColors.Update()
            self.imageMapToColors.UpdateWholeExtent()
            self.imageBlend.Update()
            self.imageBlend.UpdateWholeExtent()
            
            print(f"[VtkBase] Window/Level set: DICOM W={window_width}, C={window_center} -> Internal W={new_width:.1f}, C={new_center:.1f}")
            
        except Exception as e:
            print(f"[VtkBase] Error setting window/level: {e}")