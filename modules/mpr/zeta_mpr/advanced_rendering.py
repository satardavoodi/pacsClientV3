"""
Advanced Volume Rendering Features
===================================

This module provides advanced rendering techniques for medical imaging:
- MIP (Maximum Intensity Projection)
- MinIP (Minimum Intensity Projection)
- Thick Slab MPR with various blend modes
- Average Intensity Projection (AIP)
- Interactive slab thickness control

Based on VTK best practices and medical imaging standards.
"""

import vtkmodules.all as vtk
from typing import Optional, Tuple, Literal
import numpy as np


class AdvancedVolumeRenderer:
    """
    Advanced volume rendering with MIP, MinIP, and Thick Slab support
    """
    
    BlendMode = Literal["mip", "minip", "composite", "average"]
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize advanced renderer
        
        Args:
            image_data: Input VTK image data
        """
        self.image_data = image_data
        self.current_blend_mode = "composite"
        self.slab_thickness = 10.0  # mm
        
        # Store mappers for different modes
        self.volume_mapper = None
        self.slab_reslice = None
        
    def create_mip_volume(
        self,
        auto_adjust_range: bool = True
    ) -> Tuple[vtk.vtkVolume, vtk.vtkVolumeProperty]:
        """
        Create MIP (Maximum Intensity Projection) volume
        
        Args:
            auto_adjust_range: Automatically adjust intensity range
            
        Returns:
            Tuple of (volume, volume_property)
        """
        # Create GPU volume mapper
        mapper = vtk.vtkGPUVolumeRayCastMapper()
        mapper.SetInputData(self.image_data)
        mapper.SetBlendModeToMaximumIntensity()
        
        # Quality settings
        mapper.SetAutoAdjustSampleDistances(0)
        mapper.SetSampleDistance(0.5)
        mapper.SetImageSampleDistance(1.0)
        
        # Create volume property
        volume_property = vtk.vtkVolumeProperty()
        volume_property.ShadeOff()  # No shading for MIP
        volume_property.SetInterpolationTypeToLinear()
        
        # Simple transfer functions for MIP
        scalar_range = self.image_data.GetScalarRange()
        
        color_tf = vtk.vtkColorTransferFunction()
        color_tf.AddRGBPoint(scalar_range[0], 0.0, 0.0, 0.0)
        color_tf.AddRGBPoint(scalar_range[1], 1.0, 1.0, 1.0)
        
        opacity_tf = vtk.vtkPiecewiseFunction()
        opacity_tf.AddPoint(scalar_range[0], 0.0)
        
        if auto_adjust_range:
            # Show only bright structures
            threshold = scalar_range[0] + (scalar_range[1] - scalar_range[0]) * 0.3
            opacity_tf.AddPoint(threshold, 0.0)
            opacity_tf.AddPoint(scalar_range[1], 1.0)
        else:
            opacity_tf.AddPoint(scalar_range[1], 1.0)
        
        volume_property.SetColor(color_tf)
        volume_property.SetScalarOpacity(opacity_tf)
        
        # Create volume
        volume = vtk.vtkVolume()
        volume.SetMapper(mapper)
        volume.SetProperty(volume_property)
        
        self.volume_mapper = mapper
        self.current_blend_mode = "mip"
        
        return volume, volume_property
    
    def create_minip_volume(
        self,
        window_range: Optional[Tuple[float, float]] = None
    ) -> Tuple[vtk.vtkVolume, vtk.vtkVolumeProperty]:
        """
        Create MinIP (Minimum Intensity Projection) volume
        Useful for airways visualization
        
        Args:
            window_range: Optional (min, max) range to display
            
        Returns:
            Tuple of (volume, volume_property)
        """
        # Create GPU volume mapper
        mapper = vtk.vtkGPUVolumeRayCastMapper()
        mapper.SetInputData(self.image_data)
        mapper.SetBlendModeToMinimumIntensity()
        
        # Quality settings
        mapper.SetAutoAdjustSampleDistances(0)
        mapper.SetSampleDistance(0.5)
        mapper.SetImageSampleDistance(1.0)
        
        # Create volume property
        volume_property = vtk.vtkVolumeProperty()
        volume_property.ShadeOff()
        volume_property.SetInterpolationTypeToLinear()
        
        # Transfer functions for MinIP (typically for lung/airways)
        scalar_range = self.image_data.GetScalarRange()
        
        if window_range is None:
            # Default for airways: -1024 to -300 HU
            window_range = (scalar_range[0], -300)
        
        color_tf = vtk.vtkColorTransferFunction()
        # Cyan color for airways
        color_tf.AddRGBPoint(window_range[0], 0.0, 0.4, 0.5)
        color_tf.AddRGBPoint(window_range[1], 0.2, 0.6, 0.8)
        
        opacity_tf = vtk.vtkPiecewiseFunction()
        opacity_tf.AddPoint(window_range[0], 1.0)
        opacity_tf.AddPoint(window_range[1], 1.0)
        opacity_tf.AddPoint(scalar_range[1], 0.0)
        
        volume_property.SetColor(color_tf)
        volume_property.SetScalarOpacity(opacity_tf)
        
        # Create volume
        volume = vtk.vtkVolume()
        volume.SetMapper(mapper)
        volume.SetProperty(volume_property)
        
        self.volume_mapper = mapper
        self.current_blend_mode = "minip"
        
        return volume, volume_property
    
    def create_thick_slab_mpr(
        self,
        slab_thickness: float = 10.0,
        blend_mode: Literal["max", "min", "mean"] = "max",
        orientation: Literal["axial", "sagittal", "coronal"] = "axial"
    ) -> vtk.vtkImageData:
        """
        Create thick slab MPR with selectable blend mode
        
        Args:
            slab_thickness: Thickness in mm
            blend_mode: "max" (MIP), "min" (MinIP), or "mean" (average)
            orientation: Viewing plane orientation
            
        Returns:
            Reformatted image data
        """
        slab = vtk.vtkImageSlabReslice()
        slab.SetInputData(self.image_data)
        slab.SetSlabThickness(slab_thickness)
        
        # Set blend mode
        if blend_mode == "max":
            slab.SetBlendModeToMax()
        elif blend_mode == "min":
            slab.SetBlendModeToMin()
        elif blend_mode == "mean":
            slab.SetBlendModeToMean()
        
        # Set orientation
        if orientation == "axial":
            # Axial view (looking down Z axis)
            slab.SetResliceAxesDirectionCosines(
                1, 0, 0,  # X axis
                0, 1, 0,  # Y axis
                0, 0, 1   # Z axis (viewing direction)
            )
        elif orientation == "sagittal":
            # Sagittal view (looking from side)
            slab.SetResliceAxesDirectionCosines(
                0, 0, 1,  # X axis
                1, 0, 0,  # Y axis
                0, 1, 0   # Z axis (viewing direction)
            )
        elif orientation == "coronal":
            # Coronal view (looking from front)
            slab.SetResliceAxesDirectionCosines(
                1, 0, 0,  # X axis
                0, 0, 1,  # Y axis
                0, 1, 0   # Z axis (viewing direction)
            )
        
        # Set output properties
        slab.SetOutputDimensionality(2)
        slab.Update()
        
        self.slab_reslice = slab
        self.slab_thickness = slab_thickness
        
        return slab.GetOutput()
    
    def update_slab_thickness(self, new_thickness: float):
        """Update slab thickness for existing slab reslice"""
        if self.slab_reslice:
            self.slab_reslice.SetSlabThickness(new_thickness)
            self.slab_reslice.Update()
            self.slab_thickness = new_thickness
    
    def switch_blend_mode(
        self,
        volume: vtk.vtkVolume,
        new_mode: BlendMode,
        volume_property: Optional[vtk.vtkVolumeProperty] = None
    ):
        """
        Switch blend mode on existing volume
        
        Args:
            volume: The volume to modify
            new_mode: New blend mode
            volume_property: Optional property to update
        """
        mapper = volume.GetMapper()
        
        if new_mode == "mip":
            mapper.SetBlendModeToMaximumIntensity()
            if volume_property:
                volume_property.ShadeOff()
        elif new_mode == "minip":
            mapper.SetBlendModeToMinimumIntensity()
            if volume_property:
                volume_property.ShadeOff()
        elif new_mode == "composite":
            mapper.SetBlendModeToComposite()
            if volume_property:
                volume_property.ShadeOn()
        elif new_mode == "average":
            mapper.SetBlendModeToAverageIntensity()
            if volume_property:
                volume_property.ShadeOff()
        
        self.current_blend_mode = new_mode


class ThickSlabController:
    """
    Interactive controller for thick slab MPR with real-time updates
    """
    
    def __init__(
        self,
        image_data: vtk.vtkImageData,
        initial_thickness: float = 10.0
    ):
        """
        Initialize thick slab controller
        
        Args:
            image_data: Input image data
            initial_thickness: Initial slab thickness in mm
        """
        self.image_data = image_data
        self.thickness = initial_thickness
        self.blend_mode = "max"
        self.orientation = "axial"
        
        # Create slab reslice
        self.slab_reslice = vtk.vtkImageSlabReslice()
        self.slab_reslice.SetInputData(image_data)
        self.slab_reslice.SetSlabThickness(initial_thickness)
        self.slab_reslice.SetBlendModeToMax()
        self.slab_reslice.SetOutputDimensionality(2)
        
        # Create image actor for display
        self.image_mapper = vtk.vtkImageSliceMapper()
        self.image_mapper.SetInputConnection(self.slab_reslice.GetOutputPort())
        
        self.image_actor = vtk.vtkImageSlice()
        self.image_actor.SetMapper(self.image_mapper)
    
    def set_thickness(self, thickness: float):
        """Set slab thickness"""
        self.thickness = thickness
        self.slab_reslice.SetSlabThickness(thickness)
        self.slab_reslice.Update()
    
    def set_blend_mode(self, mode: Literal["max", "min", "mean"]):
        """Set blend mode"""
        self.blend_mode = mode
        
        if mode == "max":
            self.slab_reslice.SetBlendModeToMax()
        elif mode == "min":
            self.slab_reslice.SetBlendModeToMin()
        elif mode == "mean":
            self.slab_reslice.SetBlendModeToMean()
        
        self.slab_reslice.Update()
    
    def set_slice_position(self, position: float):
        """Set slice position along viewing axis"""
        center = self.image_data.GetCenter()
        
        if self.orientation == "axial":
            self.slab_reslice.SetResliceAxesOrigin(center[0], center[1], position)
        elif self.orientation == "sagittal":
            self.slab_reslice.SetResliceAxesOrigin(position, center[1], center[2])
        elif self.orientation == "coronal":
            self.slab_reslice.SetResliceAxesOrigin(center[0], position, center[2])
        
        self.slab_reslice.Update()
    
    def get_actor(self) -> vtk.vtkImageSlice:
        """Get the image actor for rendering"""
        return self.image_actor


def create_angio_mip(
    image_data: vtk.vtkImageData,
    vessel_range: Tuple[float, float] = (150, 800),
    color: Literal["red", "white", "blue"] = "red"
) -> Tuple[vtk.vtkVolume, vtk.vtkVolumeProperty]:
    """
    Create angiography MIP with vessel-optimized settings
    
    Args:
        image_data: Input CT angiography data
        vessel_range: HU range for vessels (default: 150-800)
        color: Vessel color
        
    Returns:
        Tuple of (volume, volume_property)
    """
    renderer = AdvancedVolumeRenderer(image_data)
    volume, volume_property = renderer.create_mip_volume(auto_adjust_range=False)
    
    # Custom transfer functions for vessels
    color_tf = vtk.vtkColorTransferFunction()
    
    if color == "red":
        color_tf.AddRGBPoint(vessel_range[0], 0.3, 0.0, 0.0)
        color_tf.AddRGBPoint(vessel_range[1], 1.0, 0.0, 0.0)
    elif color == "white":
        color_tf.AddRGBPoint(vessel_range[0], 0.5, 0.5, 0.5)
        color_tf.AddRGBPoint(vessel_range[1], 1.0, 1.0, 1.0)
    elif color == "blue":
        color_tf.AddRGBPoint(vessel_range[0], 0.0, 0.0, 0.3)
        color_tf.AddRGBPoint(vessel_range[1], 0.0, 0.0, 1.0)
    
    opacity_tf = vtk.vtkPiecewiseFunction()
    opacity_tf.AddPoint(vessel_range[0] - 50, 0.0)
    opacity_tf.AddPoint(vessel_range[0], 0.0)
    opacity_tf.AddPoint(vessel_range[0] + 50, 0.8)
    opacity_tf.AddPoint(vessel_range[1], 1.0)
    
    volume_property.SetColor(color_tf)
    volume_property.SetScalarOpacity(opacity_tf)
    
    return volume, volume_property


def create_lung_minip(
    image_data: vtk.vtkImageData,
    airway_range: Tuple[float, float] = (-1024, -400)
) -> Tuple[vtk.vtkVolume, vtk.vtkVolumeProperty]:
    """
    Create lung/airway MinIP visualization
    
    Args:
        image_data: Input chest CT data
        airway_range: HU range for airways
        
    Returns:
        Tuple of (volume, volume_property)
    """
    renderer = AdvancedVolumeRenderer(image_data)
    volume, volume_property = renderer.create_minip_volume(window_range=airway_range)
    
    return volume, volume_property

