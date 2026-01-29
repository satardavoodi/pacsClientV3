"""
New MPR4 Module
===============

Main module for New MPR4 functionality - ITK-SNAP integration layer.

This module provides the entry point for accessing New MPR4 features
from the Patient Tab UI. It serves as a bridge to ITK-SNAP functionality
for segmentation, MPR, and 3D visualization.

Features:
- VTK to NIfTI conversion with metadata preservation
- Automatic ITK-SNAP binary detection
- Cross-platform ITK-SNAP launching
- DICOM metadata preservation (spacing, origin, orientation)
"""

import logging
import tempfile
import subprocess
import platform
from pathlib import Path
from typing import Optional

from .newmpr4_widget import NewMPR4Widget

logger = logging.getLogger(__name__)


def open_newmpr4(parent=None) -> NewMPR4Widget:
    """
    Entry point function to open/create the New MPR4 tool.
    
    This function can be called from the Patient Tab UI to launch
    the New MPR4 module.
    
    TODO: ITK-SNAP Integration Steps:
    1. Check if ITK-SNAP is available (check external/itksnap/ path)
    2. Load ITK-SNAP Python bindings or C++ libraries
    3. Initialize ITK-SNAP configuration
    4. Set up communication channel (if using external binary)
    5. Configure ITK-SNAP settings (paths, preferences, etc.)
    
    Args:
        parent: Parent widget (optional)
        
    Returns:
        NewMPR4Widget: The widget instance for the New MPR4 module
    """
    widget = NewMPR4Widget(parent)
    # TODO: Initialize ITK-SNAP components
    # TODO: Load ITK-SNAP libraries from external/itksnap/
    # TODO: Configure ITK-SNAP settings and preferences
    # TODO: Set up ITK-SNAP image processing pipeline
    return widget


def show_newmpr4_tool(parent=None) -> None:
    """
    Alternative entry point - shows the New MPR4 tool.
    
    TODO: This function will launch ITK-SNAP or show the integrated UI
    
    Args:
        parent: Parent widget (optional)
    """
    widget = open_newmpr4(parent)
    widget.show()
    # TODO: Launch ITK-SNAP binary if needed
    # TODO: Show integrated ITK-SNAP UI


def launch_itk_mpr_for_active_series(vtk_image_data, metadata, series_index, parent_widget=None):
    """
    Launch ITK-SNAP MPR for the active DICOM series.
    
    This function:
    1. Converts VTK image data to NIfTI format
    2. Preserves DICOM metadata (spacing, origin, orientation)
    3. Exports to temporary file
    4. Launches ITK-SNAP with the exported file
    
    Args:
        vtk_image_data: VTK image data object containing the DICOM series volume
        metadata: Dictionary containing DICOM metadata for the series
        series_index: Index of the series in the patient's series list
        parent_widget: Parent widget for displaying dialogs (optional)
    """
    import logging
    import tempfile
    import subprocess
    import platform
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("=" * 60)
        logger.info("Launching ITK-SNAP MPR for active series")
        logger.info(f"Series index: {series_index}")
        logger.info(f"VTK image data dimensions: {vtk_image_data.GetDimensions() if vtk_image_data else 'None'}")
        logger.info("=" * 60)
        
        # Get series information from metadata
        series_metadata = metadata.get('series', {})
        series_number = series_metadata.get('series_number', 'Unknown')
        series_description = series_metadata.get('series_description', 'Unknown')
        series_uid = series_metadata.get('series_instance_uid', 'Unknown')
        
        logger.info(f"Series Number: {series_number}")
        logger.info(f"Series Description: {series_description}")
        logger.info(f"Series UID: {series_uid}")
        
        # Step 1: Convert VTK to NIfTI using SimpleITK
        logger.info("Step 1: Converting VTK image to NIfTI format...")
        nifti_file = _convert_vtk_to_nifti(
            vtk_image_data, 
            series_number, 
            series_description,
            series_uid
        )
        logger.info(f"✅ NIfTI file created: {nifti_file}")
        
        # Step 2: Find ITK-SNAP binary
        logger.info("Step 2: Searching for ITK-SNAP binary...")
        itksnap_path = _find_itksnap_binary()
        
        if not itksnap_path:
            error_msg = (
                "ITK-SNAP binary not found!\n\n"
                "Please install ITK-SNAP:\n"
                "1. Download from: http://www.itksnap.org/pmwiki/pmwiki.php?n=Downloads.SNAP3\n"
                "2. Install to default location\n"
                "   OR\n"
                "3. Add ITK-SNAP to your system PATH\n\n"
                f"The NIfTI file has been saved to:\n{nifti_file}\n\n"
                "You can open it manually in ITK-SNAP."
            )
            logger.warning(error_msg)
            
            if parent_widget:
                QMessageBox.warning(
                    parent_widget,
                    "ITK-SNAP Not Found",
                    error_msg
                )
            return
        
        logger.info(f"✅ Found ITK-SNAP at: {itksnap_path}")
        
        # Step 3: Launch ITK-SNAP with the NIfTI file
        logger.info("Step 3: Launching ITK-SNAP...")
        _launch_itksnap(itksnap_path, nifti_file)
        
        logger.info("✅ ITK-SNAP launched successfully!")
        logger.info("=" * 60)
        
        # Show success message
        if parent_widget:
            QMessageBox.information(
                parent_widget,
                "ITK-SNAP Launched",
                f"✅ ITK-SNAP launched successfully!\n\n"
                f"Series: {series_number} - {series_description}\n"
                f"Dimensions: {vtk_image_data.GetDimensions()}\n\n"
                f"File exported to:\n{nifti_file}\n\n"
                f"ITK-SNAP Path:\n{itksnap_path}"
            )
        
    except Exception as e:
        error_msg = f"Error launching ITK-SNAP: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        if parent_widget:
            QMessageBox.critical(
                parent_widget,
                "Error",
                f"{error_msg}\n\nSee logs for details."
            )


def _convert_vtk_to_nifti(vtk_image_data, series_number, series_description, series_uid):
    """
    Convert VTK image data to NIfTI format using SimpleITK.
    
    Preserves:
    - Image dimensions
    - Voxel spacing
    - Origin
    - Direction (orientation)
    
    Args:
        vtk_image_data: VTK image data object
        series_number: DICOM series number
        series_description: DICOM series description
        series_uid: DICOM series UID
    
    Returns:
        Path: Path to the exported NIfTI file
    """
    import SimpleITK as sitk
    import numpy as np
    from vtk.util.numpy_support import vtk_to_numpy
    
    logger.info("Converting VTK image to SimpleITK...")
    
    # Get VTK image properties
    dimensions = vtk_image_data.GetDimensions()
    spacing = vtk_image_data.GetSpacing()
    origin = vtk_image_data.GetOrigin()
    
    logger.info(f"  Dimensions: {dimensions}")
    logger.info(f"  Spacing: {spacing}")
    logger.info(f"  Origin: {origin}")
    
    # Convert VTK scalar data to numpy array
    vtk_array = vtk_image_data.GetPointData().GetScalars()
    numpy_array = vtk_to_numpy(vtk_array)
    
    # Reshape to 3D (VTK uses Fortran ordering: x, y, z)
    numpy_array = numpy_array.reshape(dimensions[::-1])  # Reverse for numpy (z, y, x)
    numpy_array = np.transpose(numpy_array, (2, 1, 0))  # Convert to (x, y, z)
    
    logger.info(f"  NumPy array shape: {numpy_array.shape}")
    logger.info(f"  Data type: {numpy_array.dtype}")
    logger.info(f"  Value range: [{numpy_array.min()}, {numpy_array.max()}]")
    
    # Create SimpleITK image
    sitk_image = sitk.GetImageFromArray(numpy_array.T)  # SimpleITK expects (z, y, x)
    sitk_image.SetSpacing(spacing)
    sitk_image.SetOrigin(origin)
    
    # Try to get direction matrix from VTK if available
    try:
        direction_matrix = vtk_image_data.GetDirectionMatrix()
        if direction_matrix:
            # Convert VTK 3x3 matrix to ITK direction (column-major)
            direction = []
            for i in range(3):
                for j in range(3):
                    direction.append(direction_matrix.GetElement(i, j))
            sitk_image.SetDirection(direction)
            logger.info(f"  Direction matrix set from VTK")
    except AttributeError:
        # VTK version doesn't have direction matrix
        logger.info("  Using identity direction matrix (no direction info in VTK)")
    
    # Create temporary file
    temp_dir = Path(tempfile.gettempdir()) / "itk_mpr_export"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Sanitize series description for filename
    safe_description = "".join(c if c.isalnum() or c in ('-', '_') else '_' 
                               for c in str(series_description))
    
    # Create filename with series info
    filename = f"series_{series_number}_{safe_description}.nii.gz"
    nifti_file = temp_dir / filename
    
    # Write NIfTI file
    logger.info(f"Writing NIfTI file: {nifti_file}")
    sitk.WriteImage(sitk_image, str(nifti_file))
    
    # Verify file was created
    if not nifti_file.exists():
        raise RuntimeError(f"Failed to create NIfTI file: {nifti_file}")
    
    file_size_mb = nifti_file.stat().st_size / (1024 * 1024)
    logger.info(f"✅ NIfTI file created successfully ({file_size_mb:.2f} MB)")
    
    return nifti_file


def _find_itksnap_binary():
    """
    Find ITK-SNAP binary on the system.
    
    Searches in common installation locations:
    - Windows: C:/Program Files/ITK-SNAP */bin/ITK-SNAP.exe
    - Linux: /usr/bin/itksnap, /usr/local/bin/itksnap
    - macOS: /Applications/ITK-SNAP.app/Contents/MacOS/ITK-SNAP
    - System PATH
    - Project external/itksnap directory
    
    Returns:
        Path or None: Path to ITK-SNAP binary if found
    """
    import shutil
    
    system = platform.system()
    logger.info(f"Searching for ITK-SNAP on {system}...")
    
    # Check project external directory first
    project_itksnap = Path(__file__).parent.parent.parent.parent.parent / "external" / "itksnap"
    
    if system == "Windows":
        search_paths = [
            project_itksnap / "bin" / "ITK-SNAP.exe",
            Path("C:/Program Files/ITK-SNAP 4.0/bin/ITK-SNAP.exe"),
            Path("C:/Program Files/ITK-SNAP 3.8/bin/ITK-SNAP.exe"),
            Path("C:/Program Files (x86)/ITK-SNAP 4.0/bin/ITK-SNAP.exe"),
            Path("C:/Program Files (x86)/ITK-SNAP 3.8/bin/ITK-SNAP.exe"),
        ]
        binary_name = "ITK-SNAP.exe"
        
    elif system == "Linux":
        search_paths = [
            project_itksnap / "bin" / "itksnap",
            Path("/usr/bin/itksnap"),
            Path("/usr/local/bin/itksnap"),
            Path.home() / "bin" / "itksnap",
        ]
        binary_name = "itksnap"
        
    elif system == "Darwin":  # macOS
        search_paths = [
            Path("/Applications/ITK-SNAP.app/Contents/MacOS/ITK-SNAP"),
            Path.home() / "Applications/ITK-SNAP.app/Contents/MacOS/ITK-SNAP",
        ]
        binary_name = "ITK-SNAP"
    else:
        logger.warning(f"Unknown platform: {system}")
        return None
    
    # Search in predefined paths
    for path in search_paths:
        if path.exists():
            logger.info(f"Found ITK-SNAP at: {path}")
            return path
    
    # Search in system PATH
    path_binary = shutil.which(binary_name)
    if path_binary:
        logger.info(f"Found ITK-SNAP in PATH: {path_binary}")
        return Path(path_binary)
    
    logger.warning("ITK-SNAP binary not found")
    return None


def _launch_itksnap(itksnap_path, nifti_file):
    """
    Launch ITK-SNAP with the given NIfTI file.
    
    Args:
        itksnap_path: Path to ITK-SNAP binary
        nifti_file: Path to NIfTI file to open
    """
    try:
        # Launch ITK-SNAP as a separate process (non-blocking)
        if platform.system() == "Windows":
            # Use CREATE_NEW_PROCESS_GROUP to detach from parent
            subprocess.Popen(
                [str(itksnap_path), "-g", str(nifti_file)],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            # Unix-like systems
            subprocess.Popen(
                [str(itksnap_path), "-g", str(nifti_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        
        logger.info(f"✅ ITK-SNAP launched with file: {nifti_file}")
        
    except Exception as e:
        raise RuntimeError(f"Failed to launch ITK-SNAP: {e}")


# Alias for backward compatibility
OpenNewMPR4 = open_newmpr4
ShowNewMPR4Tool = show_newmpr4_tool
