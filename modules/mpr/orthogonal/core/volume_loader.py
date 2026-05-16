"""
Volume Loader for Medical Images

Supports loading DICOM series and volumetric files (MHD, NIfTI)
using SimpleITK, with proper handling of coordinate systems
and metadata extraction.
"""

import os
import logging
from typing import Dict, Optional, Tuple, List, Any
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import vtkmodules.all as vtk
from vtkmodules.util import numpy_support

from .coordinate_systems import (
    CoordinateSystem,
    ImageGeometry,
    parse_image_orientation_patient
)

logger = logging.getLogger(__name__)

# Suppress SimpleITK warnings
sitk.ProcessObject.SetGlobalWarningDisplay(False)
sitk.ImageSeriesReader.SetGlobalWarningDisplay(False)


class VolumeLoader:
    """
    Loads medical image volumes from various formats.
    
    Supports:
    - DICOM series
    - MHD/MHA files
    - NIfTI files
    
    Example:
        >>> loader = VolumeLoader()
        >>> loader.load_dicom_series("/path/to/dicom")
        >>> vtk_image = loader.to_vtk_image()
        >>> metadata = loader.get_metadata()
    """
    
    def __init__(self):
        """Initialize the volume loader."""
        self._sitk_image: Optional[sitk.Image] = None
        self._vtk_image: Optional[vtk.vtkImageData] = None
        self._metadata: Dict[str, Any] = {}
        self._coordinate_system: Optional[CoordinateSystem] = None
    
    @property
    def is_loaded(self) -> bool:
        """Check if a volume is loaded."""
        return self._sitk_image is not None
    
    @property
    def sitk_image(self) -> Optional[sitk.Image]:
        """Get the SimpleITK image."""
        return self._sitk_image
    
    @property
    def coordinate_system(self) -> Optional[CoordinateSystem]:
        """Get the coordinate system."""
        return self._coordinate_system
    
    def load_dicom_series(
        self,
        directory: str,
        series_id: Optional[str] = None
    ) -> sitk.Image:
        """
        Load a DICOM series from a directory.
        
        Args:
            directory: Path to directory containing DICOM files
            series_id: Optional specific series ID to load
        
        Returns:
            Loaded SimpleITK Image
        
        Raises:
            FileNotFoundError: If directory doesn't exist
            ValueError: If no DICOM series found
        """
        logger.warning(
            "[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] feature=orthogonal_volume_loader_load_dicom_series "
            "reason=sitk_vtk_path_without_advanced_contract_adapter fallback_behavior=continue_local_coordinate_system "
            "action=warn_only"
        )
        directory = Path(directory)
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        logger.info(f"Loading DICOM series from: {directory}")
        
        # Get series IDs in directory
        reader = sitk.ImageSeriesReader()
        
        if series_id:
            series_ids = [series_id]
        else:
            series_ids = reader.GetGDCMSeriesIDs(str(directory))
        
        if not series_ids:
            raise ValueError(f"No DICOM series found in: {directory}")
        
        # Use first series if multiple found
        selected_series = series_ids[0]
        if len(series_ids) > 1:
            logger.warning(
                f"Multiple series found ({len(series_ids)}), using first: {selected_series}"
            )
        
        # Get file names for series
        dicom_names = reader.GetGDCMSeriesFileNames(str(directory), selected_series)
        
        if not dicom_names:
            raise ValueError(f"No DICOM files found for series: {selected_series}")
        
        logger.info(f"Loading {len(dicom_names)} DICOM files")
        
        # Configure reader for optimal performance
        reader.SetFileNames(dicom_names)
        reader.MetaDataDictionaryArrayUpdateOn()
        reader.LoadPrivateTagsOn()
        
        # Execute read
        self._sitk_image = reader.Execute()
        
        # Extract metadata
        self._extract_dicom_metadata(reader)
        
        # Build coordinate system
        self._build_coordinate_system()
        
        # Clear VTK cache
        self._vtk_image = None
        
        logger.info(
            f"Loaded volume: size={self._sitk_image.GetSize()}, "
            f"spacing={self._sitk_image.GetSpacing()}"
        )
        
        return self._sitk_image
    
    def load_mhd(self, path: str) -> sitk.Image:
        """
        Load a volume from MHD/MHA file.
        
        Args:
            path: Path to MHD or MHA file
        
        Returns:
            Loaded SimpleITK Image
        """
        logger.warning(
            "[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] feature=orthogonal_volume_loader_load_mhd "
            "reason=sitk_vtk_path_without_advanced_contract_adapter fallback_behavior=continue_local_coordinate_system "
            "action=warn_only"
        )
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        logger.info(f"Loading MHD file: {path}")
        
        self._sitk_image = sitk.ReadImage(str(path))
        
        # Extract basic metadata
        self._metadata = {
            "source_file": str(path),
            "file_format": "MHD",
        }
        
        # Build coordinate system
        self._build_coordinate_system()
        
        # Clear VTK cache
        self._vtk_image = None
        
        logger.info(
            f"Loaded volume: size={self._sitk_image.GetSize()}, "
            f"spacing={self._sitk_image.GetSpacing()}"
        )
        
        return self._sitk_image
    
    def load_nifti(self, path: str) -> sitk.Image:
        """
        Load a volume from NIfTI file.
        
        Args:
            path: Path to NIfTI file (.nii or .nii.gz)
        
        Returns:
            Loaded SimpleITK Image
        """
        logger.warning(
            "[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] feature=orthogonal_volume_loader_load_nifti "
            "reason=sitk_vtk_path_without_advanced_contract_adapter fallback_behavior=continue_local_coordinate_system "
            "action=warn_only"
        )
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        logger.info(f"Loading NIfTI file: {path}")
        
        self._sitk_image = sitk.ReadImage(str(path))
        
        # NIfTI uses RAS, convert to LPS for DICOM compatibility
        # Note: SimpleITK handles this internally for most operations
        
        self._metadata = {
            "source_file": str(path),
            "file_format": "NIfTI",
        }
        
        # Build coordinate system
        self._build_coordinate_system()
        
        # Clear VTK cache
        self._vtk_image = None
        
        return self._sitk_image
    
    def _extract_dicom_metadata(self, reader: sitk.ImageSeriesReader):
        """Extract DICOM metadata from reader."""
        self._metadata = {}
        
        # Common DICOM tags to extract
        dicom_tags = {
            "0010|0010": "patient_name",
            "0010|0020": "patient_id",
            "0008|0060": "modality",
            "0008|103e": "series_description",
            "0008|0020": "study_date",
            "0018|0050": "slice_thickness",
            "0018|0088": "spacing_between_slices",
            "0028|1050": "window_center",
            "0028|1051": "window_width",
            "0028|1052": "rescale_intercept",
            "0028|1053": "rescale_slope",
        }
        
        # Try to get metadata from first slice
        try:
            for tag, name in dicom_tags.items():
                if reader.HasMetaDataKey(0, tag):
                    value = reader.GetMetaData(0, tag)
                    self._metadata[name] = value
        except Exception as e:
            logger.warning(f"Error extracting DICOM metadata: {e}")
        
        # Add image properties
        if self._sitk_image:
            self._metadata["size"] = self._sitk_image.GetSize()
            self._metadata["spacing"] = self._sitk_image.GetSpacing()
            self._metadata["origin"] = self._sitk_image.GetOrigin()
            self._metadata["direction"] = self._sitk_image.GetDirection()
    
    def _build_coordinate_system(self):
        """Build coordinate system from loaded image."""
        if self._sitk_image is None:
            return
        
        # Get image properties
        origin = self._sitk_image.GetOrigin()
        spacing = self._sitk_image.GetSpacing()
        direction = self._sitk_image.GetDirection()
        size = self._sitk_image.GetSize()
        
        # Convert direction from flat tuple to 3x3 matrix
        direction_matrix = np.array(direction).reshape(3, 3)
        
        # Create geometry
        geometry = ImageGeometry(
            origin=origin,
            spacing=spacing,
            direction=direction_matrix,
            size=size
        )
        
        # Create coordinate system (SimpleITK uses LPS)
        self._coordinate_system = CoordinateSystem(geometry, "LPS")
    
    def get_metadata(self) -> Dict[str, Any]:
        """
        Get extracted metadata.
        
        Returns:
            Dictionary of metadata values
        """
        return self._metadata.copy()
    
    def get_window_level(self) -> Tuple[float, float]:
        """
        Get default window/level from metadata.
        
        Returns:
            (window_width, window_center) tuple
        """
        # Try to get from DICOM metadata
        try:
            wc = float(self._metadata.get("window_center", 40))
            ww = float(self._metadata.get("window_width", 400))
            return (ww, wc)
        except (ValueError, TypeError):
            # Return default CT soft tissue values
            return (400.0, 40.0)
    
    def get_scalar_range(self) -> Tuple[float, float]:
        """
        Get scalar value range of the volume.
        
        Returns:
            (min_value, max_value) tuple
        """
        if self._sitk_image is None:
            return (0.0, 255.0)
        
        stats = sitk.StatisticsImageFilter()
        stats.Execute(self._sitk_image)
        
        return (stats.GetMinimum(), stats.GetMaximum())
    
    def to_vtk_image(self) -> vtk.vtkImageData:
        """
        Convert loaded image to VTK ImageData.
        
        Returns:
            vtkImageData with proper spacing and origin
        """
        if self._sitk_image is None:
            raise ValueError("No image loaded")
        
        # Return cached if available
        if self._vtk_image is not None:
            return self._vtk_image
        
        # Get numpy array (SimpleITK uses [z, y, x] order)
        np_array = sitk.GetArrayFromImage(self._sitk_image)
        
        # Get image properties
        spacing = self._sitk_image.GetSpacing()
        origin = self._sitk_image.GetOrigin()
        direction = np.array(self._sitk_image.GetDirection()).reshape(3, 3)
        
        # Create VTK image
        self._vtk_image = self._numpy_to_vtk_image(
            np_array,
            spacing,
            origin,
            direction
        )
        
        return self._vtk_image
    
    def _numpy_to_vtk_image(
        self,
        np_array: np.ndarray,
        spacing: Tuple[float, float, float],
        origin: Tuple[float, float, float],
        direction: np.ndarray
    ) -> vtk.vtkImageData:
        """
        Convert numpy array to vtkImageData.
        
        Args:
            np_array: 3D numpy array in [z, y, x] order
            spacing: Voxel spacing (x, y, z)
            origin: Volume origin (x, y, z)
            direction: 3x3 direction matrix
        
        Returns:
            vtkImageData with proper geometry
        """
        # Ensure contiguous array in correct order
        # VTK expects [x, y, z] order, SimpleITK gives [z, y, x]
        # We need to handle this correctly
        
        # Get dimensions
        depth, height, width = np_array.shape
        
        # Create VTK image data
        vtk_image = vtk.vtkImageData()
        vtk_image.SetDimensions(width, height, depth)
        vtk_image.SetSpacing(spacing)
        vtk_image.SetOrigin(origin)
        
        # Set direction matrix (VTK 9.0+)
        try:
            direction_vtk = vtk.vtkMatrix3x3()
            for i in range(3):
                for j in range(3):
                    direction_vtk.SetElement(i, j, direction[i, j])
            vtk_image.SetDirectionMatrix(direction_vtk)
        except AttributeError:
            # Older VTK versions don't support direction matrix
            logger.warning("VTK version doesn't support direction matrix")
        
        # Convert numpy to VTK array
        # Need to flatten in Fortran order for VTK
        flat_array = np_array.flatten(order='F')
        
        # Determine VTK data type
        dtype = np_array.dtype
        if dtype == np.int16:
            vtk_type = vtk.VTK_SHORT
        elif dtype == np.int32:
            vtk_type = vtk.VTK_INT
        elif dtype == np.float32:
            vtk_type = vtk.VTK_FLOAT
        elif dtype == np.float64:
            vtk_type = vtk.VTK_DOUBLE
        elif dtype == np.uint8:
            vtk_type = vtk.VTK_UNSIGNED_CHAR
        elif dtype == np.uint16:
            vtk_type = vtk.VTK_UNSIGNED_SHORT
        else:
            # Convert to float
            flat_array = flat_array.astype(np.float32)
            vtk_type = vtk.VTK_FLOAT
        
        # Create VTK array
        vtk_array = numpy_support.numpy_to_vtk(
            flat_array,
            deep=True,
            array_type=vtk_type
        )
        
        # Set scalars
        vtk_image.GetPointData().SetScalars(vtk_array)
        
        return vtk_image
    
    def save_as_mhd(self, path: str):
        """
        Save loaded volume as MHD file.
        
        Args:
            path: Output path for MHD file
        """
        if self._sitk_image is None:
            raise ValueError("No image loaded")
        
        sitk.WriteImage(self._sitk_image, path)
        logger.info(f"Saved volume to: {path}")
    
    def get_slice_count(self, plane: str) -> int:
        """
        Get number of slices for a given plane.
        
        Args:
            plane: One of 'axial', 'sagittal', 'coronal'
        
        Returns:
            Number of slices
        """
        if self._sitk_image is None:
            return 0
        
        size = self._sitk_image.GetSize()
        plane = plane.lower()
        
        if plane == "axial":
            return size[2]  # Z slices
        elif plane == "sagittal":
            return size[0]  # X slices
        elif plane == "coronal":
            return size[1]  # Y slices
        else:
            raise ValueError(f"Unknown plane: {plane}")


def load_dicom_to_vtk(directory: str) -> Tuple[vtk.vtkImageData, Dict]:
    """
    Convenience function to load DICOM and get VTK image.
    
    Args:
        directory: Path to DICOM directory
    
    Returns:
        (vtkImageData, metadata) tuple
    """
    loader = VolumeLoader()
    loader.load_dicom_series(directory)
    return loader.to_vtk_image(), loader.get_metadata()
