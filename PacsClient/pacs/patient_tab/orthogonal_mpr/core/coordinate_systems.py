"""
Coordinate System Management for Medical Imaging

This module handles coordinate transformations between different coordinate systems
used in medical imaging:

- LPS (Left-Posterior-Superior): DICOM standard
  - X+: Patient's Left
  - Y+: Patient's Posterior (back)
  - Z+: Patient's Superior (head)

- RAS (Right-Anterior-Superior): ITK/VTK/NIfTI standard
  - X+: Patient's Right
  - Y+: Patient's Anterior (front)
  - Z+: Patient's Superior (head)

The transformation between LPS and RAS is:
    RAS = [-1, 0, 0]   [LPS_x]
          [0, -1, 0] * [LPS_y]
          [0,  0, 1]   [LPS_z]
"""

import numpy as np
from typing import Tuple, List, Optional, Union
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Transformation matrix from LPS to RAS
LPS_TO_RAS_MATRIX = np.array([
    [-1, 0, 0],
    [0, -1, 0],
    [0, 0, 1]
], dtype=np.float64)

# Inverse transformation (RAS to LPS)
RAS_TO_LPS_MATRIX = LPS_TO_RAS_MATRIX  # Same matrix (self-inverse)


@dataclass
class ImageGeometry:
    """
    Represents the spatial geometry of a 3D medical image.
    
    Attributes:
        origin: Image origin in world coordinates (mm)
        spacing: Voxel spacing in each direction (mm)
        direction: 3x3 direction cosine matrix
        size: Image dimensions in voxels
    """
    origin: Tuple[float, float, float]
    spacing: Tuple[float, float, float]
    direction: np.ndarray  # 3x3 matrix
    size: Tuple[int, int, int]
    
    def __post_init__(self):
        """Validate and convert inputs."""
        self.origin = tuple(float(x) for x in self.origin)
        self.spacing = tuple(float(x) for x in self.spacing)
        self.size = tuple(int(x) for x in self.size)
        
        if isinstance(self.direction, (list, tuple)):
            self.direction = np.array(self.direction, dtype=np.float64).reshape(3, 3)
        
        assert self.direction.shape == (3, 3), "Direction must be 3x3 matrix"
    
    @property
    def physical_size(self) -> Tuple[float, float, float]:
        """Get physical size of volume in mm."""
        return tuple(s * sp for s, sp in zip(self.size, self.spacing))
    
    @property
    def center(self) -> Tuple[float, float, float]:
        """Get center of volume in world coordinates."""
        half_size = np.array(self.size) / 2.0
        center_index = half_size
        return tuple(self.index_to_world(center_index))


class CoordinateSystem:
    """
    Manages coordinate transformations for medical images.
    
    Handles conversions between:
    - Index space (i, j, k voxel indices)
    - World space (x, y, z in mm, typically LPS)
    - Display space (for visualization)
    
    Example:
        >>> geometry = ImageGeometry(
        ...     origin=(0, 0, 0),
        ...     spacing=(1, 1, 1),
        ...     direction=np.eye(3),
        ...     size=(256, 256, 100)
        ... )
        >>> cs = CoordinateSystem(geometry)
        >>> world_point = cs.index_to_world([128, 128, 50])
    """
    
    def __init__(
        self,
        geometry: ImageGeometry,
        coordinate_system: str = "LPS"
    ):
        """
        Initialize coordinate system.
        
        Args:
            geometry: Image geometry information
            coordinate_system: Either "LPS" (DICOM) or "RAS" (ITK/VTK)
        """
        self.geometry = geometry
        self.coordinate_system = coordinate_system.upper()
        
        # Build transformation matrices
        self._build_transformation_matrices()
        
        logger.debug(f"CoordinateSystem initialized: {self.coordinate_system}")
    
    def _build_transformation_matrices(self):
        """Build index-to-world and world-to-index transformation matrices."""
        origin = np.array(self.geometry.origin)
        spacing = np.array(self.geometry.spacing)
        direction = self.geometry.direction
        
        # Index to World: W = D * S * I + O
        # Where D = direction, S = spacing diagonal, I = index, O = origin
        spacing_matrix = np.diag(spacing)
        
        # 4x4 affine transformation matrix
        self._index_to_world_matrix = np.eye(4)
        self._index_to_world_matrix[:3, :3] = direction @ spacing_matrix
        self._index_to_world_matrix[:3, 3] = origin
        
        # World to Index: inverse transformation
        self._world_to_index_matrix = np.linalg.inv(self._index_to_world_matrix)
    
    def index_to_world(
        self,
        index_point: Union[np.ndarray, List, Tuple]
    ) -> np.ndarray:
        """
        Convert index coordinates to world coordinates.
        
        Args:
            index_point: Point in index space (i, j, k)
        
        Returns:
            Point in world coordinates (x, y, z) in mm
        """
        point = np.array(index_point, dtype=np.float64)
        
        # Apply affine transformation
        homogeneous = np.append(point, 1.0)
        world = self._index_to_world_matrix @ homogeneous
        
        return world[:3]
    
    def world_to_index(
        self,
        world_point: Union[np.ndarray, List, Tuple]
    ) -> np.ndarray:
        """
        Convert world coordinates to index coordinates.
        
        Args:
            world_point: Point in world space (x, y, z) in mm
        
        Returns:
            Point in index space (i, j, k)
        """
        point = np.array(world_point, dtype=np.float64)
        
        # Apply inverse affine transformation
        homogeneous = np.append(point, 1.0)
        index = self._world_to_index_matrix @ homogeneous
        
        return index[:3]
    
    def lps_to_ras(
        self,
        lps_point: Union[np.ndarray, List, Tuple]
    ) -> np.ndarray:
        """
        Convert LPS coordinates to RAS coordinates.
        
        Args:
            lps_point: Point in LPS space
        
        Returns:
            Point in RAS space
        """
        point = np.array(lps_point, dtype=np.float64)
        return LPS_TO_RAS_MATRIX @ point
    
    def ras_to_lps(
        self,
        ras_point: Union[np.ndarray, List, Tuple]
    ) -> np.ndarray:
        """
        Convert RAS coordinates to LPS coordinates.
        
        Args:
            ras_point: Point in RAS space
        
        Returns:
            Point in LPS space
        """
        point = np.array(ras_point, dtype=np.float64)
        return RAS_TO_LPS_MATRIX @ point
    
    def get_direction_for_plane(self, plane: str) -> np.ndarray:
        """
        Get direction vectors for a specific anatomical plane.
        
        Following radiological display convention:
        - Row direction: positive goes from left to right on screen
        - Column direction: positive goes from bottom to top on screen
        
        Args:
            plane: One of 'axial', 'sagittal', 'coronal'
        
        Returns:
            2x3 array of direction vectors [row_direction, column_direction]
        """
        plane = plane.lower()
        
        # Standard anatomical directions for radiological view
        if plane == "axial":
            # Looking from feet toward head
            # Row: Left to Right (patient's right to left on screen)
            # Col: Posterior to Anterior (anterior at top)
            row_dir = np.array([1, 0, 0])   # X axis
            col_dir = np.array([0, -1, 0])  # -Y axis (flip for display)
        elif plane == "sagittal":
            # Looking from patient's left side
            # Row: Posterior to Anterior  
            # Col: Inferior to Superior
            row_dir = np.array([0, -1, 0])  # -Y axis
            col_dir = np.array([0, 0, 1])   # Z axis
        elif plane == "coronal":
            # Looking from front (anterior)
            # Row: Left to Right
            # Col: Inferior to Superior
            row_dir = np.array([1, 0, 0])   # X axis
            col_dir = np.array([0, 0, 1])   # Z axis
        else:
            raise ValueError(f"Unknown plane: {plane}")
        
        # Apply image direction matrix
        row_dir = self.geometry.direction @ row_dir
        col_dir = self.geometry.direction @ col_dir
        
        return np.array([row_dir, col_dir])
    
    def get_slice_position(
        self,
        plane: str,
        slice_index: int
    ) -> float:
        """
        Get world position for a slice.
        
        Args:
            plane: One of 'axial', 'sagittal', 'coronal'
            slice_index: Slice index
        
        Returns:
            Position in mm along the slice normal
        """
        plane = plane.lower()
        
        # Determine which axis corresponds to the slice normal
        if plane == "axial":
            axis = 2  # Z axis
        elif plane == "sagittal":
            axis = 0  # X axis
        elif plane == "coronal":
            axis = 1  # Y axis
        else:
            raise ValueError(f"Unknown plane: {plane}")
        
        # Calculate world position
        index_point = [0, 0, 0]
        index_point[axis] = slice_index
        world_point = self.index_to_world(index_point)
        
        return world_point[axis]
    
    def get_bounds(self) -> Tuple[float, float, float, float, float, float]:
        """
        Get world coordinate bounds of the volume.
        
        Returns:
            (x_min, x_max, y_min, y_max, z_min, z_max) in mm
        """
        # Get all corners of the volume
        corners = []
        for i in [0, self.geometry.size[0] - 1]:
            for j in [0, self.geometry.size[1] - 1]:
                for k in [0, self.geometry.size[2] - 1]:
                    corners.append(self.index_to_world([i, j, k]))
        
        corners = np.array(corners)
        
        return (
            corners[:, 0].min(), corners[:, 0].max(),
            corners[:, 1].min(), corners[:, 1].max(),
            corners[:, 2].min(), corners[:, 2].max()
        )


def get_orientation_label(direction_vector: np.ndarray) -> str:
    """
    Get anatomical orientation label for a direction vector.
    
    Args:
        direction_vector: 3D direction vector
    
    Returns:
        Orientation label (e.g., 'L', 'R', 'A', 'P', 'S', 'I')
    """
    # Find dominant axis
    abs_vec = np.abs(direction_vector)
    dominant_axis = np.argmax(abs_vec)
    sign = np.sign(direction_vector[dominant_axis])
    
    # Labels in LPS convention
    labels = {
        0: ('R', 'L'),  # X axis: Right (-) / Left (+)
        1: ('A', 'P'),  # Y axis: Anterior (-) / Posterior (+)
        2: ('I', 'S'),  # Z axis: Inferior (-) / Superior (+)
    }
    
    if sign > 0:
        return labels[dominant_axis][1]
    else:
        return labels[dominant_axis][0]


def parse_image_orientation_patient(iop: List[float]) -> np.ndarray:
    """
    Parse DICOM Image Orientation Patient tag to direction matrix.
    
    Args:
        iop: Image Orientation Patient (6 values from DICOM tag 0020,0037)
    
    Returns:
        3x3 direction matrix
    """
    if len(iop) != 6:
        raise ValueError("IOP must have 6 values")
    
    # Row direction (first 3 values)
    row_dir = np.array(iop[:3], dtype=np.float64)
    row_dir = row_dir / np.linalg.norm(row_dir)
    
    # Column direction (last 3 values)
    col_dir = np.array(iop[3:], dtype=np.float64)
    col_dir = col_dir / np.linalg.norm(col_dir)
    
    # Slice direction (cross product)
    slice_dir = np.cross(row_dir, col_dir)
    slice_dir = slice_dir / np.linalg.norm(slice_dir)
    
    # Build direction matrix
    direction = np.column_stack([row_dir, col_dir, slice_dir])
    
    return direction
