"""
Example Usage - Orthogonal MPR Module

This file demonstrates how to use the OrthogonalMPRWidget
for viewing medical imaging data.

Run this file directly to see a demo with test data.
"""

import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_with_dicom():
    """
    Example: Load and display DICOM series.
    """
    from PySide6.QtWidgets import QApplication
    from orthogonal_mpr import OrthogonalMPRWidget
    
    # Create application
    app = QApplication(sys.argv)
    
    # Create widget
    widget = OrthogonalMPRWidget()
    widget.setWindowTitle("Orthogonal MPR Viewer - DICOM Example")
    widget.resize(1400, 600)
    
    # Load DICOM series
    dicom_path = "path/to/your/dicom/series"
    if Path(dicom_path).exists():
        widget.load_dicom_series(dicom_path)
    else:
        logger.warning(f"DICOM path not found: {dicom_path}")
        logger.info("Please update the dicom_path variable with a valid path")
    
    # Show widget
    widget.show()
    
    # Run application
    sys.exit(app.exec())


def example_with_test_volume():
    """
    Example: Create and display a test volume (no DICOM required).
    """
    from PySide6.QtWidgets import QApplication
    from orthogonal_mpr.widgets import OrthogonalMPRWidget
    from orthogonal_mpr.utils.sitk_helpers import create_test_volume, sitk_to_numpy
    from orthogonal_mpr.utils.vtk_helpers import create_vtk_image_from_numpy
    
    # Create application
    app = QApplication(sys.argv)
    
    # Create test volume
    logger.info("Creating test volume...")
    sitk_image = create_test_volume(
        size=(128, 128, 64),
        spacing=(1.0, 1.0, 2.0)
    )
    
    # Convert to numpy then to VTK
    np_array = sitk_to_numpy(sitk_image)
    vtk_image = create_vtk_image_from_numpy(
        np_array,
        spacing=sitk_image.GetSpacing(),
        origin=sitk_image.GetOrigin()
    )
    
    # Create widget
    widget = OrthogonalMPRWidget()
    widget.setWindowTitle("Orthogonal MPR Viewer - Test Volume")
    widget.resize(1400, 600)
    
    # Load test volume
    widget.load_vtk_image(vtk_image)
    
    # Apply default preset
    widget.apply_preset("default")
    
    # Show widget
    widget.show()
    
    logger.info("Test volume loaded. Use mouse wheel to scroll through slices.")
    
    # Run application
    sys.exit(app.exec())


def example_programmatic_control():
    """
    Example: Programmatic control of the MPR viewer.
    """
    from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
    from orthogonal_mpr.widgets import OrthogonalMPRWidget
    from orthogonal_mpr.core.mpr_calculator import PlaneType
    
    # Create application
    app = QApplication(sys.argv)
    
    # Create main window with controls
    main_window = QMainWindow()
    main_window.setWindowTitle("MPR Viewer with Controls")
    main_window.resize(1400, 700)
    
    # Central widget
    central = QWidget()
    layout = QVBoxLayout(central)
    
    # MPR widget
    mpr_widget = OrthogonalMPRWidget()
    layout.addWidget(mpr_widget, stretch=1)
    
    # Control buttons
    btn_layout = QVBoxLayout()
    
    # Window/Level presets
    for preset in ["lung", "bone", "brain", "soft_tissue"]:
        btn = QPushButton(f"Apply {preset.replace('_', ' ').title()} Preset")
        btn.clicked.connect(lambda checked, p=preset: mpr_widget.apply_preset(p))
        btn_layout.addWidget(btn)
    
    # Toggle crosshairs
    crosshair_btn = QPushButton("Toggle Crosshairs")
    crosshair_visible = [True]
    def toggle_crosshairs():
        crosshair_visible[0] = not crosshair_visible[0]
        mpr_widget.set_crosshairs_visible(crosshair_visible[0])
    crosshair_btn.clicked.connect(toggle_crosshairs)
    btn_layout.addWidget(crosshair_btn)
    
    # Enable thick slab
    slab_btn = QPushButton("Enable MIP Slab (10mm)")
    slab_enabled = [False]
    def toggle_slab():
        slab_enabled[0] = not slab_enabled[0]
        if slab_enabled[0]:
            mpr_widget.enable_thick_slab(10.0, "mip")
            slab_btn.setText("Disable MIP Slab")
        else:
            mpr_widget.disable_thick_slab()
            slab_btn.setText("Enable MIP Slab (10mm)")
    slab_btn.clicked.connect(toggle_slab)
    btn_layout.addWidget(slab_btn)
    
    layout.addLayout(btn_layout)
    
    main_window.setCentralWidget(central)
    
    # Load test data (you would load real DICOM here)
    # mpr_widget.load_dicom_series("/path/to/dicom")
    
    main_window.show()
    
    logger.info("Example window opened. Load DICOM data to see MPR views.")
    
    sys.exit(app.exec())


def print_usage():
    """Print usage information."""
    print("""
Orthogonal MPR Module - Example Usage
=====================================

This module provides a complete implementation of orthogonal MPR visualization.

Quick Start:
-----------
    from orthogonal_mpr import OrthogonalMPRWidget
    
    # Create widget
    widget = OrthogonalMPRWidget()
    
    # Load DICOM series
    widget.load_dicom_series("/path/to/dicom")
    
    # Or load MHD file
    widget.load_mhd("/path/to/file.mhd")
    
    # Or load VTK image directly
    widget.load_vtk_image(vtk_image_data)
    
    # Show widget
    widget.show()

Features:
---------
    - Three orthogonal views: Axial, Sagittal, Coronal
    - Synchronized crosshairs between views
    - Window/Level presets (CT: Lung, Bone, Brain, etc.)
    - Thick Slab MPR (MIP, MinIP, Mean)
    - Distance and angle measurements
    - Mouse wheel scrolling
    
API Examples:
-------------
    # Window/Level
    widget.set_window_level(1500, -600)  # Lung window
    widget.apply_preset("lung")
    
    # Crosshairs
    widget.set_crosshairs_visible(True)
    
    # Thick Slab
    widget.enable_thick_slab(10.0, "mip")
    widget.disable_thick_slab()
    
    # Get current state
    window, level = widget.get_window_level()
    metadata = widget.get_metadata()

Run Examples:
-------------
    python example_usage.py test      # Test volume demo
    python example_usage.py dicom     # DICOM demo (requires data)
    python example_usage.py control   # Programmatic control demo
""")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "test":
            example_with_test_volume()
        elif command == "dicom":
            example_with_dicom()
        elif command == "control":
            example_programmatic_control()
        else:
            print_usage()
    else:
        print_usage()
