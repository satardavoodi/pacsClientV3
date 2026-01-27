# ignore pylint
# pylint: disable-msg=E0611,E0602
"""
VolumeViewer - 3D Volume Rendering using VTK
Provides real 3D visualization of CT/MR data with interactive rotation and zoom.
"""

from vtk import *
from VtkViewer import *


class VolumeViewer(VtkViewer):
    """3D Volume Rendering Viewer using VTK GPU Ray Casting"""

    def __init__(self, vtkBaseClass: VtkBase, label: str = "3D Volume"):
        super(VolumeViewer, self).__init__(label=label, vtkBaseClass=vtkBaseClass)

        self.picker = self.vtkBaseClass.picker
        self.property = self.vtkBaseClass.property
        
        # Volume rendering components
        self.volume = None
        self.volumeMapper = None
        self.volumeProperty = None
        
        # Keep image plane widgets for MPR cross-reference
        self.imagePlaneWidgets = [vtkImagePlaneWidget(), vtkImagePlaneWidget(), vtkImagePlaneWidget()]
        for imagePlaneWidget in self.imagePlaneWidgets:
            imagePlaneWidget.SetInteractor(self.renderWindowInteractor)
            imagePlaneWidget.SetInputData(self.vtkBaseClass.imageBlend.GetOutput())
            imagePlaneWidget.SetDefaultRenderer(self.renderer)
            imagePlaneWidget.SetPicker(self.picker)
            imagePlaneWidget.RestrictPlaneToVolumeOn()
            imagePlaneWidget.SetTexturePlaneProperty(self.property)
            imagePlaneWidget.TextureInterpolateOn()
            imagePlaneWidget.SetResliceInterpolateToLinear()
            imagePlaneWidget.DisplayTextOn()
            imagePlaneWidget.SetPlaneProperty(self._create_plane_property())
            imagePlaneWidget.On()
            imagePlaneWidget.InteractionOn()

        # Renderer Settings
        self.renderer.SetBackground(0.1, 0.1, 0.15)
        self.renderer.GetActiveCamera().Elevation(110)
        self.renderer.GetActiveCamera().SetViewUp(0, 0, -1)
        self.renderer.GetActiveCamera().Azimuth(45)
        self.renderer.GetActiveCamera().Dolly(1.15)
        self.renderer.ResetCameraClippingRange()
        
        # Interactor style for 3D
        style = vtkInteractorStyleTrackballCamera()
        self.renderWindowInteractor.SetInteractorStyle(style)

    def _create_plane_property(self):
        """Create semi-transparent plane property"""
        prop = vtkProperty()
        prop.SetOpacity(0.3)
        return prop

    def _setup_volume_rendering(self):
        """Setup VTK volume rendering pipeline"""
        
        # Get image data from the pipeline
        image_data = self.vtkBaseClass.imageShiftScale.GetOutput()
        if not image_data:
            print("[VolumeViewer] No image data available")
            return
        
        # Get scalar range for transfer function
        scalar_range = image_data.GetScalarRange()
        print(f"[VolumeViewer] Scalar range: {scalar_range}")
        
        # Volume Mapper - use GPU ray casting for best performance
        self.volumeMapper = vtkGPUVolumeRayCastMapper()
        self.volumeMapper.SetInputData(image_data)
        self.volumeMapper.SetBlendModeToComposite()
        self.volumeMapper.SetAutoAdjustSampleDistances(True)
        
        # Volume Property
        self.volumeProperty = vtkVolumeProperty()
        self.volumeProperty.ShadeOn()
        self.volumeProperty.SetInterpolationTypeToLinear()
        self.volumeProperty.SetAmbient(0.4)
        self.volumeProperty.SetDiffuse(0.6)
        self.volumeProperty.SetSpecular(0.2)
        
        # Color Transfer Function - Beautiful colorful chest CT (default)
        colorFunc = vtkColorTransferFunction()
        # Normalized values (0-255 after shift/scale)
        colorFunc.AddRGBPoint(0, 0.0, 0.0, 0.0)        # Air - black
        colorFunc.AddRGBPoint(40, 0.1, 0.1, 0.2)       # Low density - dark blue
        colorFunc.AddRGBPoint(80, 0.8, 0.2, 0.6)       # Soft tissue - magenta/pink
        colorFunc.AddRGBPoint(120, 0.9, 0.4, 0.7)      # Muscle - pink
        colorFunc.AddRGBPoint(150, 0.2, 0.7, 0.7)      # Cartilage - cyan/teal
        colorFunc.AddRGBPoint(180, 0.3, 0.8, 0.6)      # Bone start - teal/green
        colorFunc.AddRGBPoint(200, 0.5, 0.9, 0.8)      # Bone mid - light teal
        colorFunc.AddRGBPoint(220, 0.8, 0.6, 0.9)      # Dense bone - light purple
        colorFunc.AddRGBPoint(240, 0.9, 0.5, 0.7)      # Very dense - pink
        colorFunc.AddRGBPoint(255, 1.0, 0.8, 0.9)      # Densest - light pink
        self.volumeProperty.SetColor(colorFunc)
        
        # Opacity Transfer Function
        opacityFunc = vtkPiecewiseFunction()
        opacityFunc.AddPoint(0, 0.0)
        opacityFunc.AddPoint(60, 0.0)
        opacityFunc.AddPoint(100, 0.15)
        opacityFunc.AddPoint(140, 0.3)
        opacityFunc.AddPoint(180, 0.6)
        opacityFunc.AddPoint(220, 0.85)
        opacityFunc.AddPoint(255, 1.0)
        self.volumeProperty.SetScalarOpacity(opacityFunc)
        
        # Enhanced shading for beautiful rendering
        self.volumeProperty.SetSpecularPower(20)
        
        # Gradient Opacity (enhance edges)
        gradientOpacity = vtkPiecewiseFunction()
        gradientOpacity.AddPoint(0, 0.0)
        gradientOpacity.AddPoint(90, 0.5)
        gradientOpacity.AddPoint(100, 1.0)
        self.volumeProperty.SetGradientOpacity(gradientOpacity)
        
        # Create Volume Actor
        self.volume = vtkVolume()
        self.volume.SetMapper(self.volumeMapper)
        self.volume.SetProperty(self.volumeProperty)
        
        # Add to renderer
        self.renderer.AddVolume(self.volume)
        self.renderer.ResetCamera()
        
        print("[VolumeViewer] Volume rendering setup complete")

    def set_preset(self, preset_name: str):
        """Set volume rendering preset
        
        Args:
            preset_name: One of 'ct_chest_color', 'ct_bone', 'ct_soft', 'ct_lung', 'ct_vessel', 'mip'
        """
        if not self.volumeProperty:
            return
        
        # Reset blend mode to composite (in case MIP was selected before)
        if self.volumeMapper:
            self.volumeMapper.SetBlendModeToComposite()
            
        colorFunc = vtkColorTransferFunction()
        opacityFunc = vtkPiecewiseFunction()
        
        if preset_name == 'ct_chest_color':
            # Beautiful colorful chest CT - like the reference image
            # Pink/Magenta for soft tissue, Cyan/Teal for mid-density, colorful bones
            colorFunc.AddRGBPoint(0, 0.0, 0.0, 0.0)        # Air - black
            colorFunc.AddRGBPoint(40, 0.1, 0.1, 0.2)       # Low density - dark blue
            colorFunc.AddRGBPoint(80, 0.8, 0.2, 0.6)       # Soft tissue - magenta/pink
            colorFunc.AddRGBPoint(120, 0.9, 0.4, 0.7)      # Muscle - pink
            colorFunc.AddRGBPoint(150, 0.2, 0.7, 0.7)      # Cartilage - cyan/teal
            colorFunc.AddRGBPoint(180, 0.3, 0.8, 0.6)      # Bone start - teal/green
            colorFunc.AddRGBPoint(200, 0.5, 0.9, 0.8)      # Bone mid - light teal
            colorFunc.AddRGBPoint(220, 0.8, 0.6, 0.9)      # Dense bone - light purple
            colorFunc.AddRGBPoint(240, 0.9, 0.5, 0.7)      # Very dense - pink
            colorFunc.AddRGBPoint(255, 1.0, 0.8, 0.9)      # Densest - light pink
            
            opacityFunc.AddPoint(0, 0.0)
            opacityFunc.AddPoint(60, 0.0)
            opacityFunc.AddPoint(100, 0.15)
            opacityFunc.AddPoint(140, 0.3)
            opacityFunc.AddPoint(180, 0.6)
            opacityFunc.AddPoint(220, 0.85)
            opacityFunc.AddPoint(255, 1.0)
            
            # Enhanced shading for this preset
            self.volumeProperty.SetAmbient(0.3)
            self.volumeProperty.SetDiffuse(0.7)
            self.volumeProperty.SetSpecular(0.4)
            self.volumeProperty.SetSpecularPower(20)
        
        elif preset_name == 'ct_bone':
            # Bone visualization
            colorFunc.AddRGBPoint(0, 0.0, 0.0, 0.0)
            colorFunc.AddRGBPoint(100, 0.8, 0.5, 0.4)
            colorFunc.AddRGBPoint(200, 1.0, 1.0, 0.9)
            colorFunc.AddRGBPoint(255, 1.0, 1.0, 1.0)
            opacityFunc.AddPoint(0, 0.0)
            opacityFunc.AddPoint(150, 0.0)
            opacityFunc.AddPoint(200, 0.6)
            opacityFunc.AddPoint(255, 1.0)
            
        elif preset_name == 'ct_soft':
            # Soft tissue
            colorFunc.AddRGBPoint(0, 0.0, 0.0, 0.0)
            colorFunc.AddRGBPoint(80, 0.8, 0.4, 0.3)
            colorFunc.AddRGBPoint(150, 1.0, 0.8, 0.7)
            colorFunc.AddRGBPoint(255, 1.0, 1.0, 1.0)
            opacityFunc.AddPoint(0, 0.0)
            opacityFunc.AddPoint(60, 0.0)
            opacityFunc.AddPoint(100, 0.3)
            opacityFunc.AddPoint(180, 0.5)
            opacityFunc.AddPoint(255, 0.8)
            
        elif preset_name == 'ct_lung':
            # Lung visualization
            colorFunc.AddRGBPoint(0, 0.0, 0.0, 0.0)
            colorFunc.AddRGBPoint(50, 0.3, 0.3, 0.5)
            colorFunc.AddRGBPoint(100, 0.6, 0.4, 0.4)
            colorFunc.AddRGBPoint(200, 1.0, 0.9, 0.8)
            colorFunc.AddRGBPoint(255, 1.0, 1.0, 1.0)
            opacityFunc.AddPoint(0, 0.0)
            opacityFunc.AddPoint(30, 0.1)
            opacityFunc.AddPoint(60, 0.0)
            opacityFunc.AddPoint(150, 0.3)
            opacityFunc.AddPoint(255, 0.8)
            
        elif preset_name == 'ct_vessel':
            # Vessel/angio visualization
            colorFunc.AddRGBPoint(0, 0.0, 0.0, 0.0)
            colorFunc.AddRGBPoint(100, 0.8, 0.2, 0.2)
            colorFunc.AddRGBPoint(180, 1.0, 0.4, 0.3)
            colorFunc.AddRGBPoint(255, 1.0, 0.8, 0.7)
            opacityFunc.AddPoint(0, 0.0)
            opacityFunc.AddPoint(100, 0.0)
            opacityFunc.AddPoint(150, 0.5)
            opacityFunc.AddPoint(200, 0.8)
            opacityFunc.AddPoint(255, 1.0)
            
        elif preset_name == 'mip':
            # Maximum Intensity Projection
            if self.volumeMapper:
                self.volumeMapper.SetBlendModeToMaximumIntensity()
            colorFunc.AddRGBPoint(0, 0.0, 0.0, 0.0)
            colorFunc.AddRGBPoint(255, 1.0, 1.0, 1.0)
            opacityFunc.AddPoint(0, 0.0)
            opacityFunc.AddPoint(50, 0.1)
            opacityFunc.AddPoint(255, 1.0)
        
        self.volumeProperty.SetColor(colorFunc)
        self.volumeProperty.SetScalarOpacity(opacityFunc)
        self.GetRenderWindow().Render()

    def toggle_planes_visibility(self, visible: bool):
        """Toggle visibility of MPR planes in 3D view"""
        for widget in self.imagePlaneWidgets:
            if visible:
                widget.On()
            else:
                widget.Off()
        self.GetRenderWindow().Render()

    def connect_on_data(self, path: str):
        """Connect to data and setup volume rendering"""
        super().connect_on_data(path)
        self._setup_volume_rendering()
        self.renderer.ResetCamera()
        self.GetRenderWindow().Render()

