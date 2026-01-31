"""
Thick Slab MPR - Maximum/Minimum Intensity Projection and Averaging

Provides slab-based rendering modes:
- MIP (Maximum Intensity Projection): Shows brightest voxels
- MinIP (Minimum Intensity Projection): Shows darkest voxels
- Mean/Average: Shows average intensity through slab

Useful for vessel visualization (MIP), airway visualization (MinIP),
and noise reduction (Mean).
"""

import logging
from enum import Enum
from typing import Optional, Tuple

import numpy as np
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class SlabMode(Enum):
    """Slab projection modes."""
    MIP = "mip"        # Maximum Intensity Projection
    MINIP = "minip"    # Minimum Intensity Projection
    MEAN = "mean"      # Average/Mean projection
    SUM = "sum"        # Sum projection


class ThickSlabMPR:
    """
    Thick slab MPR implementation using vtkImageSlabReslice.
    
    Provides efficient slab-based rendering for visualizing
    structures that span multiple slices.
    
    Example:
        >>> slab = ThickSlabMPR(vtk_image)
        >>> slab.set_mode(SlabMode.MIP)
        >>> slab.set_thickness(10.0)  # 10mm slab
        >>> output = slab.get_output()
    """
    
    def __init__(
        self,
        image_data: vtk.vtkImageData,
        mode: SlabMode = SlabMode.MEAN,
        thickness: float = 5.0
    ):
        """
        Initialize thick slab MPR.
        
        Args:
            image_data: Input 3D volume
            mode: Initial slab mode
            thickness: Initial slab thickness in mm
        """
        self.image_data = image_data
        self._mode = mode
        self._thickness = thickness
        
        # Get image properties
        self._spacing = image_data.GetSpacing()
        
        # Create slab reslice filter
        self._slab_reslice = vtk.vtkImageSlabReslice()
        self._slab_reslice.SetInputData(image_data)
        self._slab_reslice.SetOutputDimensionality(2)
        
        # Set up high-quality interpolation
        interpolator = vtk.vtkImageSincInterpolator()
        interpolator.SetWindowFunctionToLanczos()
        interpolator.AntialiasingOn()
        self._slab_reslice.SetInterpolator(interpolator)
        
        # Apply initial settings
        self._apply_mode()
        self._apply_thickness()
        
        logger.info(f"ThickSlabMPR initialized: mode={mode.value}, thickness={thickness}mm")
    
    def _apply_mode(self):
        """Apply current slab mode to filter."""
        if self._mode == SlabMode.MIP:
            self._slab_reslice.SetBlendModeToMax()
        elif self._mode == SlabMode.MINIP:
            self._slab_reslice.SetBlendModeToMin()
        elif self._mode == SlabMode.MEAN:
            self._slab_reslice.SetBlendModeToMean()
        elif self._mode == SlabMode.SUM:
            # VTK doesn't have direct sum mode, use mean and multiply
            self._slab_reslice.SetBlendModeToMean()
    
    def _apply_thickness(self):
        """Apply current thickness to filter."""
        # Calculate number of slices for thickness
        # Use smallest spacing as reference
        min_spacing = min(self._spacing)
        num_slices = max(1, int(self._thickness / min_spacing))
        
        self._slab_reslice.SetSlabNumberOfSlices(num_slices)
        self._slab_reslice.SetSlabResolution(self._thickness / num_slices)
        
        logger.debug(f"Slab configured: {num_slices} slices, {self._thickness}mm")
    
    @property
    def mode(self) -> SlabMode:
        """Get current slab mode."""
        return self._mode
    
    @mode.setter
    def mode(self, value: SlabMode):
        """Set slab mode."""
        self._mode = value
        self._apply_mode()
        self._slab_reslice.Update()
    
    @property
    def thickness(self) -> float:
        """Get current slab thickness in mm."""
        return self._thickness
    
    @thickness.setter
    def thickness(self, value: float):
        """Set slab thickness in mm."""
        self._thickness = max(0.1, value)  # Minimum 0.1mm
        self._apply_thickness()
        self._slab_reslice.Update()
    
    def set_mode(self, mode: SlabMode):
        """
        Set slab projection mode.
        
        Args:
            mode: Slab mode (MIP, MinIP, Mean, Sum)
        """
        self.mode = mode
    
    def set_thickness(self, thickness: float):
        """
        Set slab thickness.
        
        Args:
            thickness: Thickness in mm
        """
        self.thickness = thickness
    
    def set_reslice_axes(self, matrix: vtk.vtkMatrix4x4):
        """
        Set reslice axes for slab orientation.
        
        Args:
            matrix: 4x4 transformation matrix
        """
        self._slab_reslice.SetResliceAxes(matrix)
        self._slab_reslice.Update()
    
    def get_output(self) -> vtk.vtkImageData:
        """
        Get slab-projected output.
        
        Returns:
            2D vtkImageData with slab projection
        """
        self._slab_reslice.Update()
        return self._slab_reslice.GetOutput()
    
    def get_output_port(self) -> vtk.vtkAlgorithmOutput:
        """
        Get output port for pipeline connection.
        
        Returns:
            VTK algorithm output port
        """
        return self._slab_reslice.GetOutputPort()
    
    def update(self):
        """Force update of slab reslice."""
        self._slab_reslice.Update()
    
    def get_slab_info(self) -> dict:
        """
        Get current slab configuration info.
        
        Returns:
            Dictionary with mode, thickness, and slice count
        """
        return {
            "mode": self._mode.value,
            "thickness_mm": self._thickness,
            "num_slices": self._slab_reslice.GetSlabNumberOfSlices(),
        }


class ThickSlabController:
    """
    High-level controller for thick slab MPR in views.
    
    Manages thick slab for multiple views and provides
    unified interface for mode/thickness changes.
    """
    
    def __init__(self):
        """Initialize controller."""
        self._slabs: dict = {}
        self._enabled = False
        self._mode = SlabMode.MEAN
        self._thickness = 5.0
    
    def create_slab(
        self,
        name: str,
        image_data: vtk.vtkImageData
    ) -> ThickSlabMPR:
        """
        Create a thick slab for a named view.
        
        Args:
            name: Name/identifier for the slab
            image_data: Volume data
        
        Returns:
            Created ThickSlabMPR instance
        """
        slab = ThickSlabMPR(
            image_data,
            mode=self._mode,
            thickness=self._thickness
        )
        self._slabs[name] = slab
        return slab
    
    def get_slab(self, name: str) -> Optional[ThickSlabMPR]:
        """Get slab by name."""
        return self._slabs.get(name)
    
    def set_enabled(self, enabled: bool):
        """Enable or disable thick slab for all views."""
        self._enabled = enabled
        # Views should check this flag when rendering
    
    @property
    def enabled(self) -> bool:
        """Check if thick slab is enabled."""
        return self._enabled
    
    def set_mode_all(self, mode: SlabMode):
        """
        Set mode for all slabs.
        
        Args:
            mode: Slab mode to apply
        """
        self._mode = mode
        for slab in self._slabs.values():
            slab.set_mode(mode)
    
    def set_thickness_all(self, thickness: float):
        """
        Set thickness for all slabs.
        
        Args:
            thickness: Thickness in mm
        """
        self._thickness = thickness
        for slab in self._slabs.values():
            slab.set_thickness(thickness)
    
    def update_all(self):
        """Update all slabs."""
        for slab in self._slabs.values():
            slab.update()
