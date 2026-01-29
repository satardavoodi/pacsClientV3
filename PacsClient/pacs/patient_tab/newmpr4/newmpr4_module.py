"""
New MPR4 Module
===============

Main module for New MPR4 functionality - ITK-SNAP integration layer.

This module provides the entry point for accessing New MPR4 features
from the Patient Tab UI. It serves as a bridge to ITK-SNAP functionality
for segmentation, MPR, and 3D visualization.

TODO: Integrate ITK-SNAP libraries and expose its capabilities through this module.
"""

from typing import Optional
from .newmpr4_widget import NewMPR4Widget


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
    Launch ITK MPR for the active DICOM series.
    
    This function receives the active series data and prepares it for ITK-SNAP processing.
    It exports the series to a temporary format/location and logs where ITK-SNAP
    integration will be invoked.
    
    TODO: ITK-SNAP Integration Points:
    1. Export VTK image data to DICOM or NIfTI format for ITK-SNAP
    2. Save to temporary location (e.g., temp directory)
    3. Launch ITK-SNAP binary with the exported file
    4. Or integrate ITK-SNAP libraries for in-process MPR processing
    5. Display ITK-SNAP MPR visualization
    
    Args:
        vtk_image_data: VTK image data object containing the DICOM series volume
        metadata: Dictionary containing DICOM metadata for the series
        series_index: Index of the series in the patient's series list
        parent_widget: Parent widget for displaying dialogs (optional)
    """
    import logging
    import tempfile
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("=" * 60)
        logger.info("Launching ITK MPR for active series")
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
        
        # TODO: Export VTK image data to temporary DICOM or NIfTI format
        # This is where ITK-SNAP integration will happen
        temp_dir = Path(tempfile.gettempdir()) / "itk_mpr_export"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # TODO: Convert VTK image data to ITK image format
        # TODO: Save to temporary file (DICOM series or NIfTI)
        # Example:
        #   temp_file = temp_dir / f"series_{series_number}_{series_uid[:8]}.nii.gz"
        #   itk_image = convert_vtk_to_itk(vtk_image_data)
        #   itk.imwrite(itk_image, str(temp_file))
        
        logger.info(f"TODO: Export series to temporary location: {temp_dir}")
        logger.info("TODO: Convert VTK image data to ITK-SNAP compatible format")
        logger.info("TODO: Launch ITK-SNAP binary or integrate ITK-SNAP libraries")
        logger.info("TODO: Display ITK-SNAP MPR visualization")
        
        # Display informational message
        if parent_widget:
            QMessageBox.information(
                parent_widget,
                "ITK MPR (ITK-SNAP)",
                f"ITK MPR requested for Series {series_number}\n\n"
                f"Series Description: {series_description}\n\n"
                f"TODO: ITK-SNAP integration will:\n"
                f"  - Export series to temporary format\n"
                f"  - Launch ITK-SNAP MPR processing\n"
                f"  - Display ITK-SNAP visualization\n\n"
                f"VTK Image Dimensions: {vtk_image_data.GetDimensions()}\n"
                f"Temporary export location: {temp_dir}"
            )
        else:
            logger.info(f"ITK MPR requested for Series {series_number}")
            logger.info(f"Series Description: {series_description}")
            logger.info(f"VTK Image Dimensions: {vtk_image_data.GetDimensions()}")
        
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"ERROR launching ITK MPR for active series: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        
        if parent_widget:
            QMessageBox.critical(
                parent_widget,
                "Error",
                f"Error launching ITK MPR:\n{str(e)}"
            )


# Alias for backward compatibility
OpenNewMPR4 = open_newmpr4
ShowNewMPR4Tool = show_newmpr4_tool
