"""
Oblique Reslice - Arbitrary angle slicing for MPR

Allows slicing at any angle, not just the standard orthogonal planes.
Useful for visualizing structures that don't align with standard planes.
"""

import logging
from typing import Optional, Tuple, Union, List

import numpy as np
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class ObliqueReslice:
    """
    Oblique (arbitrary angle) reslicing for MPR.
    
    Provides the ability to define slicing planes at any orientation,
    specified either by three points or by rotation angles.
    
    Example:
        >>> oblique = ObliqueReslice(vtk_image)
        >>> oblique.set_rotation(15, 0, 0)  # 15 degrees around X
        >>> output = oblique.get_output()
    """
    
    def __init__(
        self,
        image_data: vtk.vtkImageData,
        interpolation: str = "linear"
    ):
        """
        Initialize oblique reslice.
        
        Args:
            image_data: Input 3D volume
            interpolation: Interpolation method ('nearest', 'linear', 'cubic', 'lanczos')
        """
        self.image_data = image_data
        
        # Get image properties
        self._dimensions = image_data.GetDimensions()
        self._spacing = image_data.GetSpacing()
        self._origin = image_data.GetOrigin()
        self._bounds = image_data.GetBounds()
        
        # Calculate center
        self._center = np.array([
            (self._bounds[0] + self._bounds[1]) / 2,
            (self._bounds[2] + self._bounds[3]) / 2,
            (self._bounds[4] + self._bounds[5]) / 2
        ])
        
        # Current rotation angles
        self._rotation = np.array([0.0, 0.0, 0.0])  # Rx, Ry, Rz in degrees
        
        # Create reslice filter
        self._reslice = vtk.vtkImageReslice()
        self._reslice.SetInputData(image_data)
        self._reslice.SetOutputDimensionality(2)
        
        # Set interpolation
        self._set_interpolation(interpolation)
        
        # Create transform
        self._transform = vtk.vtkTransform()
        
        # Initialize with identity
        self._update_reslice_axes()
        
        logger.info("ObliqueReslice initialized")
    
    def _set_interpolation(self, method: str):
        """Set interpolation method."""
        method = method.lower()
        
        if method == "nearest":
            self._reslice.SetInterpolationModeToNearestNeighbor()
        elif method == "linear":
            self._reslice.SetInterpolationModeToLinear()
        elif method == "cubic":
            self._reslice.SetInterpolationModeToCubic()
        elif method == "lanczos":
            interpolator = vtk.vtkImageSincInterpolator()
            interpolator.SetWindowFunctionToLanczos()
            interpolator.AntialiasingOn()
            self._reslice.SetInterpolator(interpolator)
        else:
            logger.warning(f"Unknown interpolation '{method}', using linear")
            self._reslice.SetInterpolationModeToLinear()
    
    def _update_reslice_axes(self):
        """Update reslice axes based on current rotation."""
        # Build rotation matrix
        self._transform.Identity()
        
        # Translate to center
        self._transform.Translate(*self._center)
        
        # Apply rotations (order: Z, Y, X for intuitive control)
        self._transform.RotateZ(self._rotation[2])
        self._transform.RotateY(self._rotation[1])
        self._transform.RotateX(self._rotation[0])
        
        # Get matrix
        matrix = vtk.vtkMatrix4x4()
        self._transform.GetMatrix(matrix)
        
        # Set reslice axes
        self._reslice.SetResliceAxes(matrix)
        self._reslice.Update()
    
    def set_rotation(
        self,
        rx: float = 0.0,
        ry: float = 0.0,
        rz: float = 0.0
    ):
        """
        Set rotation angles.
        
        Args:
            rx: Rotation around X axis (degrees)
            ry: Rotation around Y axis (degrees)
            rz: Rotation around Z axis (degrees)
        """
        self._rotation = np.array([rx, ry, rz])
        self._update_reslice_axes()
    
    def get_rotation(self) -> Tuple[float, float, float]:
        """Get current rotation angles."""
        return tuple(self._rotation)
    
    def add_rotation(
        self,
        drx: float = 0.0,
        dry: float = 0.0,
        drz: float = 0.0
    ):
        """
        Add incremental rotation.
        
        Args:
            drx: Delta rotation around X axis (degrees)
            dry: Delta rotation around Y axis (degrees)
            drz: Delta rotation around Z axis (degrees)
        """
        self._rotation += np.array([drx, dry, drz])
        self._update_reslice_axes()
    
    def reset_rotation(self):
        """Reset to no rotation (standard orthogonal view)."""
        self._rotation = np.array([0.0, 0.0, 0.0])
        self._update_reslice_axes()
    
    def set_center(self, center: Union[np.ndarray, List, Tuple]):
        """
        Set center point for rotation.
        
        Args:
            center: New center point [x, y, z]
        """
        self._center = np.array(center, dtype=np.float64)
        self._update_reslice_axes()
    
    def get_center(self) -> np.ndarray:
        """Get current center point."""
        return self._center.copy()
    
    def set_plane_from_points(
        self,
        origin: Union[np.ndarray, List, Tuple],
        point1: Union[np.ndarray, List, Tuple],
        point2: Union[np.ndarray, List, Tuple]
    ):
        """
        Define oblique plane by three points.
        
        Args:
            origin: Origin point of the plane
            point1: Point defining first axis direction
            point2: Point defining second axis direction
        """
        origin = np.array(origin, dtype=np.float64)
        point1 = np.array(point1, dtype=np.float64)
        point2 = np.array(point2, dtype=np.float64)
        
        # Calculate axes
        x_axis = point1 - origin
        x_axis = x_axis / np.linalg.norm(x_axis)
        
        y_axis = point2 - origin
        y_axis = y_axis / np.linalg.norm(y_axis)
        
        # Orthogonalize y_axis
        y_axis = y_axis - np.dot(y_axis, x_axis) * x_axis
        y_axis = y_axis / np.linalg.norm(y_axis)
        
        # Calculate normal (z_axis)
        z_axis = np.cross(x_axis, y_axis)
        
        # Build matrix
        matrix = vtk.vtkMatrix4x4()
        
        for i in range(3):
            matrix.SetElement(i, 0, x_axis[i])
            matrix.SetElement(i, 1, y_axis[i])
            matrix.SetElement(i, 2, z_axis[i])
            matrix.SetElement(i, 3, origin[i])
        
        self._reslice.SetResliceAxes(matrix)
        self._reslice.Update()
        
        # Update center
        self._center = origin
        
        logger.debug(f"Plane set from points: origin={origin}")
    
    def set_plane_from_normal(
        self,
        origin: Union[np.ndarray, List, Tuple],
        normal: Union[np.ndarray, List, Tuple]
    ):
        """
        Define oblique plane by origin and normal vector.
        
        Args:
            origin: Origin point on the plane
            normal: Normal vector to the plane
        """
        origin = np.array(origin, dtype=np.float64)
        normal = np.array(normal, dtype=np.float64)
        normal = normal / np.linalg.norm(normal)
        
        # Generate two perpendicular vectors in the plane
        # Start with arbitrary vector not parallel to normal
        if abs(normal[0]) < 0.9:
            arbitrary = np.array([1, 0, 0])
        else:
            arbitrary = np.array([0, 1, 0])
        
        x_axis = np.cross(normal, arbitrary)
        x_axis = x_axis / np.linalg.norm(x_axis)
        
        y_axis = np.cross(normal, x_axis)
        y_axis = y_axis / np.linalg.norm(y_axis)
        
        # Build matrix
        matrix = vtk.vtkMatrix4x4()
        
        for i in range(3):
            matrix.SetElement(i, 0, x_axis[i])
            matrix.SetElement(i, 1, y_axis[i])
            matrix.SetElement(i, 2, normal[i])
            matrix.SetElement(i, 3, origin[i])
        
        self._reslice.SetResliceAxes(matrix)
        self._reslice.Update()
        
        self._center = origin
    
    def get_output(self) -> vtk.vtkImageData:
        """
        Get resliced output.
        
        Returns:
            2D vtkImageData of oblique slice
        """
        self._reslice.Update()
        return self._reslice.GetOutput()
    
    def get_output_port(self) -> vtk.vtkAlgorithmOutput:
        """Get output port for pipeline connection."""
        return self._reslice.GetOutputPort()
    
    def get_reslice_axes(self) -> vtk.vtkMatrix4x4:
        """Get current reslice axes matrix."""
        return self._reslice.GetResliceAxes()
    
    def set_output_spacing(self, spacing: Tuple[float, float]):
        """
        Set output image spacing.
        
        Args:
            spacing: (x_spacing, y_spacing) for output
        """
        self._reslice.SetOutputSpacing(spacing[0], spacing[1], 1.0)
        self._reslice.Update()
    
    def set_output_extent(self, extent: Tuple[int, int, int, int]):
        """
        Set output image extent.
        
        Args:
            extent: (x_min, x_max, y_min, y_max) for output
        """
        self._reslice.SetOutputExtent(extent[0], extent[1], extent[2], extent[3], 0, 0)
        self._reslice.Update()
    
    def update(self):
        """Force update of reslice."""
        self._reslice.Update()
