"""
MPR Calculator - Core computation for Multiplanar Reconstruction

Handles the mathematical computation of MPR slices, including:
- Orthogonal plane definitions (Axial, Sagittal, Coronal)
- Transformation matrix computation
- Slice position calculations
- Crosshair intersection points
"""

import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass

import numpy as np
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class PlaneType(Enum):
    """Types of anatomical planes for MPR."""
    AXIAL = "axial"
    SAGITTAL = "sagittal"
    CORONAL = "coronal"
    OBLIQUE = "oblique"


@dataclass
class PlaneDefinition:
    """
    Definition of an MPR plane.
    
    Attributes:
        normal: Normal vector to the plane (perpendicular)
        x_axis: Direction of image X axis (columns)
        y_axis: Direction of image Y axis (rows)
        slice_axis: Which volume axis this plane slices through
    """
    normal: np.ndarray
    x_axis: np.ndarray
    y_axis: np.ndarray
    slice_axis: int  # 0=X, 1=Y, 2=Z


# Standard orthogonal plane definitions
# VTK uses a right-handed coordinate system
# For medical imaging display conventions:
# - Axial: view from feet toward head (looking at patient from below)
# - Sagittal: view from patient's left side
# - Coronal: view from front of patient
STANDARD_PLANES: Dict[PlaneType, PlaneDefinition] = {
    PlaneType.AXIAL: PlaneDefinition(
        normal=np.array([0, 0, 1]),       # Z axis - slice normal
        x_axis=np.array([1, 0, 0]),       # X axis - columns (left-right)
        y_axis=np.array([0, -1, 0]),      # -Y axis - rows (flip for display: anterior at top)
        slice_axis=2
    ),
    PlaneType.SAGITTAL: PlaneDefinition(
        normal=np.array([1, 0, 0]),       # X axis - slice normal
        x_axis=np.array([0, -1, 0]),      # -Y axis - columns (anterior-posterior, flipped)
        y_axis=np.array([0, 0, 1]),       # Z axis - rows (inferior to superior)
        slice_axis=0
    ),
    PlaneType.CORONAL: PlaneDefinition(
        normal=np.array([0, 1, 0]),       # Y axis - slice normal
        x_axis=np.array([1, 0, 0]),       # X axis - columns (left-right)
        y_axis=np.array([0, 0, 1]),       # Z axis - rows (inferior to superior)
        slice_axis=1
    ),
}


class MPRCalculator:
    """
    Calculator for MPR slice generation and coordinate transformations.
    
    Manages the computation of slice positions, crosshair intersections,
    and provides the transformation matrices needed for reslicing.
    
    Example:
        >>> calc = MPRCalculator(vtk_image)
        >>> calc.set_center([100, 100, 50])
        >>> axial_matrix = calc.get_reslice_matrix(PlaneType.AXIAL)
    """
    
    def __init__(self, vtk_image: vtk.vtkImageData):
        """
        Initialize MPR calculator.
        
        Args:
            vtk_image: Input 3D volume
        """
        self._vtk_image = vtk_image
        
        # Get volume properties
        self._dimensions = vtk_image.GetDimensions()
        self._spacing = vtk_image.GetSpacing()
        self._origin = vtk_image.GetOrigin()
        self._bounds = vtk_image.GetBounds()
        
        # Get direction matrix if available (VTK 9.0+)
        try:
            dir_matrix = vtk_image.GetDirectionMatrix()
            self._direction = np.array([
                [dir_matrix.GetElement(i, j) for j in range(3)]
                for i in range(3)
            ])
        except AttributeError:
            self._direction = np.eye(3)
        
        # Current center point (crosshair intersection)
        self._center = np.array([
            (self._bounds[0] + self._bounds[1]) / 2,
            (self._bounds[2] + self._bounds[3]) / 2,
            (self._bounds[4] + self._bounds[5]) / 2
        ])
        
        # Create VTK reslice cursor for synchronized slicing
        self._reslice_cursor = vtk.vtkResliceCursor()
        self._reslice_cursor.SetImage(vtk_image)
        self._reslice_cursor.SetCenter(self._center)
        
        logger.debug(f"MPRCalculator initialized: dims={self._dimensions}, center={self._center}")
    
    @property
    def center(self) -> np.ndarray:
        """Get current center point."""
        return self._center.copy()
    
    @property
    def vtk_image(self) -> vtk.vtkImageData:
        """Get the VTK image data."""
        return self._vtk_image
    
    @property
    def dimensions(self) -> Tuple[int, int, int]:
        """Get volume dimensions."""
        return self._dimensions
    
    @property
    def spacing(self) -> Tuple[float, float, float]:
        """Get volume spacing."""
        return self._spacing
    
    @property
    def bounds(self) -> Tuple[float, float, float, float, float, float]:
        """Get volume bounds."""
        return self._bounds
    
    @property
    def reslice_cursor(self) -> vtk.vtkResliceCursor:
        """Get VTK reslice cursor."""
        return self._reslice_cursor
    
    def set_center(self, center: Union[np.ndarray, List, Tuple]):
        """
        Set the center point (crosshair intersection).
        
        Args:
            center: New center point in world coordinates
        """
        self._center = np.array(center, dtype=np.float64)
        
        # Clamp to bounds
        self._center[0] = np.clip(self._center[0], self._bounds[0], self._bounds[1])
        self._center[1] = np.clip(self._center[1], self._bounds[2], self._bounds[3])
        self._center[2] = np.clip(self._center[2], self._bounds[4], self._bounds[5])
        
        # Update reslice cursor
        self._reslice_cursor.SetCenter(self._center)
        
        logger.debug(f"Center set to: {self._center}")
    
    def get_slice_index(self, plane_type: PlaneType) -> int:
        """
        Get current slice index for a plane.
        
        Args:
            plane_type: Type of plane
        
        Returns:
            Slice index
        """
        plane_def = STANDARD_PLANES[plane_type]
        axis = plane_def.slice_axis
        
        # Convert world coordinate to index
        position = self._center[axis]
        origin = self._origin[axis]
        spacing = self._spacing[axis]
        
        index = int((position - origin) / spacing)
        
        # Clamp to valid range
        max_index = self._dimensions[axis] - 1
        index = max(0, min(index, max_index))
        
        return index
    
    def set_slice_index(self, plane_type: PlaneType, index: int):
        """
        Set slice index for a plane.
        
        Args:
            plane_type: Type of plane
            index: New slice index
        """
        plane_def = STANDARD_PLANES[plane_type]
        axis = plane_def.slice_axis
        
        # Convert index to world coordinate
        origin = self._origin[axis]
        spacing = self._spacing[axis]
        position = origin + index * spacing
        
        # Update center
        new_center = self._center.copy()
        new_center[axis] = position
        self.set_center(new_center)
    
    def get_slice_range(self, plane_type: PlaneType) -> Tuple[int, int]:
        """
        Get valid slice index range for a plane.
        
        Args:
            plane_type: Type of plane
        
        Returns:
            (min_index, max_index) tuple
        """
        plane_def = STANDARD_PLANES[plane_type]
        axis = plane_def.slice_axis
        
        return (0, self._dimensions[axis] - 1)
    
    def get_slice_position(self, plane_type: PlaneType) -> float:
        """
        Get current slice position in world coordinates.
        
        Args:
            plane_type: Type of plane
        
        Returns:
            Position in mm
        """
        plane_def = STANDARD_PLANES[plane_type]
        axis = plane_def.slice_axis
        
        return self._center[axis]
    
    def get_reslice_matrix(self, plane_type: PlaneType) -> vtk.vtkMatrix4x4:
        """
        Get reslice transformation matrix for a plane.
        
        Args:
            plane_type: Type of plane
        
        Returns:
            4x4 transformation matrix
        """
        plane_def = STANDARD_PLANES[plane_type]
        
        # Apply direction matrix to plane vectors
        x_axis = self._direction @ plane_def.x_axis
        y_axis = self._direction @ plane_def.y_axis
        normal = self._direction @ plane_def.normal
        
        # Build transformation matrix
        matrix = vtk.vtkMatrix4x4()
        
        # Set axes (columns of rotation part)
        for i in range(3):
            matrix.SetElement(i, 0, x_axis[i])
            matrix.SetElement(i, 1, y_axis[i])
            matrix.SetElement(i, 2, normal[i])
        
        # Set translation (origin for slice)
        # The slice should pass through the center point
        for i in range(3):
            matrix.SetElement(i, 3, self._center[i])
        
        return matrix
    
    def get_crosshair_lines(
        self,
        plane_type: PlaneType
    ) -> Tuple[List[float], List[float]]:
        """
        Get crosshair line endpoints for a plane.
        
        Args:
            plane_type: Type of plane
        
        Returns:
            (horizontal_line, vertical_line) - each as [x1, y1, z1, x2, y2, z2]
        """
        plane_def = STANDARD_PLANES[plane_type]
        
        # Get plane-local axes
        x_axis = self._direction @ plane_def.x_axis
        y_axis = self._direction @ plane_def.y_axis
        
        # Calculate extent of crosshair lines
        # Use volume bounds to determine line length
        extent = max(
            self._bounds[1] - self._bounds[0],
            self._bounds[3] - self._bounds[2],
            self._bounds[5] - self._bounds[4]
        )
        half_extent = extent / 2
        
        # Horizontal line (along x_axis)
        h_start = self._center - x_axis * half_extent
        h_end = self._center + x_axis * half_extent
        horizontal = list(h_start) + list(h_end)
        
        # Vertical line (along y_axis)
        v_start = self._center - y_axis * half_extent
        v_end = self._center + y_axis * half_extent
        vertical = list(v_start) + list(v_end)
        
        return horizontal, vertical
    
    def world_to_slice_coords(
        self,
        plane_type: PlaneType,
        world_point: Union[np.ndarray, List, Tuple]
    ) -> Tuple[float, float]:
        """
        Convert world coordinates to 2D slice coordinates.
        
        Args:
            plane_type: Type of plane
            world_point: Point in world coordinates
        
        Returns:
            (x, y) coordinates in slice space
        """
        plane_def = STANDARD_PLANES[plane_type]
        
        # Get plane axes
        x_axis = self._direction @ plane_def.x_axis
        y_axis = self._direction @ plane_def.y_axis
        
        # Vector from slice origin to point
        point = np.array(world_point, dtype=np.float64)
        vec = point - self._center
        
        # Project onto plane axes
        x = np.dot(vec, x_axis)
        y = np.dot(vec, y_axis)
        
        return (x, y)
    
    def slice_to_world_coords(
        self,
        plane_type: PlaneType,
        slice_x: float,
        slice_y: float
    ) -> np.ndarray:
        """
        Convert 2D slice coordinates to world coordinates.
        
        Args:
            plane_type: Type of plane
            slice_x: X coordinate in slice space
            slice_y: Y coordinate in slice space
        
        Returns:
            Point in world coordinates
        """
        plane_def = STANDARD_PLANES[plane_type]
        
        # Get plane axes
        x_axis = self._direction @ plane_def.x_axis
        y_axis = self._direction @ plane_def.y_axis
        
        # Calculate world point
        world_point = self._center + slice_x * x_axis + slice_y * y_axis
        
        return world_point
    
    def get_orientation_labels(
        self,
        plane_type: PlaneType
    ) -> Dict[str, str]:
        """
        Get orientation labels for a plane.
        
        Following radiological convention:
        - Axial: Patient right on viewer's left, anterior at top (view from feet)
        - Sagittal: Anterior on viewer's left, superior at top (view from patient's left)
        - Coronal: Patient left on viewer's left, superior at top (view from posterior/back)
        
        Args:
            plane_type: Type of plane
        
        Returns:
            Dictionary with 'left', 'right', 'top', 'bottom' labels
        """
        if plane_type == PlaneType.AXIAL:
            # Looking from feet toward head (standard radiological view)
            return {
                "left": "R",      # Patient's right appears on viewer's left
                "right": "L",     # Patient's left appears on viewer's right
                "top": "A",       # Anterior at top
                "bottom": "P"     # Posterior at bottom
            }
        elif plane_type == PlaneType.SAGITTAL:
            # Looking from patient's left side
            return {
                "left": "A",      # Anterior
                "right": "P",     # Posterior
                "top": "S",       # Superior (head)
                "bottom": "I"     # Inferior (feet)
            }
        elif plane_type == PlaneType.CORONAL:
            # Looking from posterior (back of patient)
            return {
                "left": "L",      # Patient's left on viewer's left
                "right": "R",     # Patient's right on viewer's right
                "top": "S",       # Superior (head)
                "bottom": "I"     # Inferior (feet)
            }
        else:
            return {"left": "", "right": "", "top": "", "bottom": ""}
    
    def get_output_dimensions(
        self,
        plane_type: PlaneType
    ) -> Tuple[int, int]:
        """
        Get output dimensions for a plane slice.
        
        Args:
            plane_type: Type of plane
        
        Returns:
            (width, height) in pixels
        """
        if plane_type == PlaneType.AXIAL:
            return (self._dimensions[0], self._dimensions[1])  # X, Y
        elif plane_type == PlaneType.SAGITTAL:
            return (self._dimensions[1], self._dimensions[2])  # Y, Z
        elif plane_type == PlaneType.CORONAL:
            return (self._dimensions[0], self._dimensions[2])  # X, Z
        else:
            return (self._dimensions[0], self._dimensions[1])
    
    def get_output_spacing(
        self,
        plane_type: PlaneType
    ) -> Tuple[float, float]:
        """
        Get output spacing for a plane slice.
        
        Args:
            plane_type: Type of plane
        
        Returns:
            (x_spacing, y_spacing) in mm
        """
        if plane_type == PlaneType.AXIAL:
            return (self._spacing[0], self._spacing[1])  # X, Y
        elif plane_type == PlaneType.SAGITTAL:
            return (self._spacing[1], self._spacing[2])  # Y, Z
        elif plane_type == PlaneType.CORONAL:
            return (self._spacing[0], self._spacing[2])  # X, Z
        else:
            return (self._spacing[0], self._spacing[1])
