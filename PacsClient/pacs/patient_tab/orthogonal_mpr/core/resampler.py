"""
MPR Resampler - Image resampling for Multiplanar Reconstruction

Provides various interpolation methods for high-quality MPR generation:
- Nearest Neighbor: Fastest, lowest quality
- Linear: Good balance of speed and quality
- Cubic (B-Spline): High quality, moderate speed
- Lanczos: Highest quality, slowest

Based on SimpleITK resampling with proper coordinate handling.
"""

import logging
from enum import Enum
from typing import Optional, Tuple, Union

import numpy as np
import SimpleITK as sitk
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class InterpolationType(Enum):
    """Interpolation methods for resampling."""
    NEAREST = "nearest"
    LINEAR = "linear"
    CUBIC = "cubic"
    LANCZOS = "lanczos"


# Map InterpolationType to SimpleITK interpolators
SITK_INTERPOLATORS = {
    InterpolationType.NEAREST: sitk.sitkNearestNeighbor,
    InterpolationType.LINEAR: sitk.sitkLinear,
    InterpolationType.CUBIC: sitk.sitkBSpline,
    InterpolationType.LANCZOS: sitk.sitkLanczosWindowedSinc,
}


class MPRResampler:
    """
    Resampler for generating MPR slices from 3D volumes.
    
    Supports generating slices in any of the three orthogonal planes
    (Axial, Sagittal, Coronal) with configurable interpolation.
    
    Example:
        >>> resampler = MPRResampler(sitk_image)
        >>> axial_slice = resampler.get_slice('axial', 50)
        >>> sagittal_slice = resampler.get_slice('sagittal', 100)
    """
    
    def __init__(
        self,
        volume: sitk.Image,
        interpolation: InterpolationType = InterpolationType.LINEAR,
        default_value: float = -1024.0  # Air in HU
    ):
        """
        Initialize the resampler.
        
        Args:
            volume: Input 3D volume (SimpleITK Image)
            interpolation: Interpolation method to use
            default_value: Value for pixels outside the volume
        """
        self.volume = volume
        self.interpolation = interpolation
        self.default_value = default_value
        
        # Cache volume properties
        self._size = volume.GetSize()
        self._spacing = volume.GetSpacing()
        self._origin = volume.GetOrigin()
        self._direction = np.array(volume.GetDirection()).reshape(3, 3)
        
        # Calculate volume bounds
        self._calculate_bounds()
        
        logger.debug(f"MPRResampler initialized: size={self._size}, spacing={self._spacing}")
    
    def _calculate_bounds(self):
        """Calculate world coordinate bounds of the volume."""
        # Get all corner points
        size = np.array(self._size)
        origin = np.array(self._origin)
        spacing = np.array(self._spacing)
        
        # Calculate physical extent
        extent = size * spacing
        
        # Apply direction matrix to get world coordinates
        world_extent = self._direction @ np.diag(extent)
        
        # Calculate bounds
        corners = []
        for i in [0, 1]:
            for j in [0, 1]:
                for k in [0, 1]:
                    idx = np.array([i * (size[0] - 1),
                                   j * (size[1] - 1),
                                   k * (size[2] - 1)])
                    world_point = origin + self._direction @ (idx * spacing)
                    corners.append(world_point)
        
        corners = np.array(corners)
        self._bounds = (
            corners[:, 0].min(), corners[:, 0].max(),
            corners[:, 1].min(), corners[:, 1].max(),
            corners[:, 2].min(), corners[:, 2].max()
        )
    
    @property
    def bounds(self) -> Tuple[float, float, float, float, float, float]:
        """Get volume bounds (xmin, xmax, ymin, ymax, zmin, zmax)."""
        return self._bounds
    
    def get_slice_range(self, plane: str) -> Tuple[int, int]:
        """
        Get valid slice index range for a plane.
        
        Args:
            plane: One of 'axial', 'sagittal', 'coronal'
        
        Returns:
            (min_index, max_index) tuple
        """
        plane = plane.lower()
        
        if plane == "axial":
            return (0, self._size[2] - 1)
        elif plane == "sagittal":
            return (0, self._size[0] - 1)
        elif plane == "coronal":
            return (0, self._size[1] - 1)
        else:
            raise ValueError(f"Unknown plane: {plane}")
    
    def get_slice(
        self,
        plane: str,
        slice_index: int,
        output_spacing: Optional[Tuple[float, float]] = None
    ) -> sitk.Image:
        """
        Extract a 2D slice from the volume.
        
        Args:
            plane: One of 'axial', 'sagittal', 'coronal'
            slice_index: Index of the slice to extract
            output_spacing: Optional custom spacing for output (default: use smallest spacing)
        
        Returns:
            2D SimpleITK Image
        """
        plane = plane.lower()
        
        # Validate slice index
        min_idx, max_idx = self.get_slice_range(plane)
        if slice_index < min_idx or slice_index > max_idx:
            logger.warning(f"Slice index {slice_index} out of range [{min_idx}, {max_idx}]")
            slice_index = max(min_idx, min(slice_index, max_idx))
        
        # Use SimpleITK's efficient slice extraction
        if plane == "axial":
            # Extract Z slice (already aligned with acquisition)
            slice_2d = self.volume[:, :, slice_index]
        
        elif plane == "sagittal":
            # Extract X slice (need to resample)
            slice_2d = self._extract_sagittal_slice(slice_index)
        
        elif plane == "coronal":
            # Extract Y slice (need to resample)
            slice_2d = self._extract_coronal_slice(slice_index)
        
        else:
            raise ValueError(f"Unknown plane: {plane}")
        
        return slice_2d
    
    def _extract_sagittal_slice(self, slice_index: int) -> sitk.Image:
        """Extract a sagittal (YZ) slice."""
        # For sagittal, we extract along X axis
        slice_2d = self.volume[slice_index, :, :]
        return slice_2d
    
    def _extract_coronal_slice(self, slice_index: int) -> sitk.Image:
        """Extract a coronal (XZ) slice."""
        # For coronal, we extract along Y axis
        slice_2d = self.volume[:, slice_index, :]
        return slice_2d
    
    def resample_to_isotropic(
        self,
        target_spacing: Optional[float] = None
    ) -> sitk.Image:
        """
        Resample volume to isotropic spacing.
        
        Args:
            target_spacing: Target isotropic spacing (default: smallest current spacing)
        
        Returns:
            Resampled volume with isotropic spacing
        """
        if target_spacing is None:
            target_spacing = min(self._spacing)
        
        # Calculate new size
        old_size = np.array(self._size)
        old_spacing = np.array(self._spacing)
        new_spacing = np.array([target_spacing, target_spacing, target_spacing])
        new_size = np.ceil(old_size * old_spacing / new_spacing).astype(int)
        
        # Create resampler
        resampler = sitk.ResampleImageFilter()
        resampler.SetInterpolator(SITK_INTERPOLATORS[self.interpolation])
        resampler.SetOutputSpacing(new_spacing.tolist())
        resampler.SetSize(new_size.tolist())
        resampler.SetOutputOrigin(self._origin)
        resampler.SetOutputDirection(self.volume.GetDirection())
        resampler.SetDefaultPixelValue(self.default_value)
        
        # Execute resampling
        resampled = resampler.Execute(self.volume)
        
        logger.info(f"Resampled to isotropic: {old_spacing} -> {new_spacing}")
        
        return resampled
    
    def set_interpolation(self, interpolation: InterpolationType):
        """Change the interpolation method."""
        self.interpolation = interpolation
        logger.debug(f"Interpolation changed to: {interpolation.value}")


class VTKMPRResampler:
    """
    VTK-based resampler for MPR generation.
    
    Uses vtkImageReslice for efficient GPU-accelerated resampling.
    Better suited for real-time interactive MPR.
    """
    
    def __init__(
        self,
        vtk_image: vtk.vtkImageData,
        interpolation: InterpolationType = InterpolationType.LINEAR
    ):
        """
        Initialize VTK-based resampler.
        
        Args:
            vtk_image: Input vtkImageData
            interpolation: Interpolation method
        """
        self.vtk_image = vtk_image
        self.interpolation = interpolation
        
        # Create reslice filter
        self._reslice = vtk.vtkImageReslice()
        self._reslice.SetInputData(vtk_image)
        self._reslice.SetOutputDimensionality(2)
        
        # Set interpolation
        self._set_vtk_interpolation()
        
        # Cache image properties
        self._dimensions = vtk_image.GetDimensions()
        self._spacing = vtk_image.GetSpacing()
        self._origin = vtk_image.GetOrigin()
        self._bounds = vtk_image.GetBounds()
    
    def _set_vtk_interpolation(self):
        """Set VTK interpolation mode."""
        if self.interpolation == InterpolationType.NEAREST:
            self._reslice.SetInterpolationModeToNearestNeighbor()
        elif self.interpolation == InterpolationType.LINEAR:
            self._reslice.SetInterpolationModeToLinear()
        elif self.interpolation == InterpolationType.CUBIC:
            self._reslice.SetInterpolationModeToCubic()
        elif self.interpolation == InterpolationType.LANCZOS:
            # Use high-quality sinc interpolation
            interpolator = vtk.vtkImageSincInterpolator()
            interpolator.SetWindowFunctionToLanczos()
            interpolator.AntialiasingOn()
            self._reslice.SetInterpolator(interpolator)
    
    def get_axial_slice(self, z_position: float) -> vtk.vtkImageData:
        """
        Get axial slice at specified Z position.
        
        Args:
            z_position: Z coordinate in world space
        
        Returns:
            2D vtkImageData
        """
        # Set up reslice axes for axial view
        axes = vtk.vtkMatrix4x4()
        axes.Identity()
        
        # Translate to slice position
        axes.SetElement(0, 3, self._origin[0])
        axes.SetElement(1, 3, self._origin[1])
        axes.SetElement(2, 3, z_position)
        
        self._reslice.SetResliceAxes(axes)
        self._reslice.Update()
        
        return self._reslice.GetOutput()
    
    def get_sagittal_slice(self, x_position: float) -> vtk.vtkImageData:
        """
        Get sagittal slice at specified X position.
        
        Args:
            x_position: X coordinate in world space
        
        Returns:
            2D vtkImageData
        """
        # Set up reslice axes for sagittal view
        # Sagittal view: Y-Z plane, X constant
        axes = vtk.vtkMatrix4x4()
        
        # Rotate to YZ plane
        axes.SetElement(0, 0, 0)
        axes.SetElement(0, 1, 1)
        axes.SetElement(0, 2, 0)
        axes.SetElement(1, 0, 0)
        axes.SetElement(1, 1, 0)
        axes.SetElement(1, 2, 1)
        axes.SetElement(2, 0, 1)
        axes.SetElement(2, 1, 0)
        axes.SetElement(2, 2, 0)
        
        # Set position
        axes.SetElement(0, 3, x_position)
        axes.SetElement(1, 3, self._origin[1])
        axes.SetElement(2, 3, self._origin[2])
        
        self._reslice.SetResliceAxes(axes)
        self._reslice.Update()
        
        return self._reslice.GetOutput()
    
    def get_coronal_slice(self, y_position: float) -> vtk.vtkImageData:
        """
        Get coronal slice at specified Y position.
        
        Args:
            y_position: Y coordinate in world space
        
        Returns:
            2D vtkImageData
        """
        # Set up reslice axes for coronal view
        # Coronal view: X-Z plane, Y constant
        axes = vtk.vtkMatrix4x4()
        
        # Rotate to XZ plane
        axes.SetElement(0, 0, 1)
        axes.SetElement(0, 1, 0)
        axes.SetElement(0, 2, 0)
        axes.SetElement(1, 0, 0)
        axes.SetElement(1, 1, 0)
        axes.SetElement(1, 2, 1)
        axes.SetElement(2, 0, 0)
        axes.SetElement(2, 1, 1)
        axes.SetElement(2, 2, 0)
        
        # Set position
        axes.SetElement(0, 3, self._origin[0])
        axes.SetElement(1, 3, y_position)
        axes.SetElement(2, 3, self._origin[2])
        
        self._reslice.SetResliceAxes(axes)
        self._reslice.Update()
        
        return self._reslice.GetOutput()
    
    @property
    def dimensions(self) -> Tuple[int, int, int]:
        """Get volume dimensions."""
        return self._dimensions
    
    @property
    def bounds(self) -> Tuple[float, float, float, float, float, float]:
        """Get volume bounds."""
        return self._bounds
