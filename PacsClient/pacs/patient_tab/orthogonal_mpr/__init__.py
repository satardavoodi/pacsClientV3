"""
Orthogonal MPR (Multiplanar Reconstruction) Module

This module provides a complete implementation of orthogonal MPR visualization
for medical imaging, supporting DICOM and MHD/NIfTI formats.

Features:
- Three orthogonal views: Axial, Sagittal, Coronal
- Synchronized crosshairs between views
- Window/Level adjustment with presets
- Thick Slab MPR (MIP, MinIP, Average)
- Oblique reslicing
- Distance and angle measurements

Based on SimpleITK for image processing and VTK for visualization.
Follows DICOM LPS coordinate system standard.

Usage:
    from orthogonal_mpr import OrthogonalMPRWidget
    
    widget = OrthogonalMPRWidget()
    widget.load_dicom_series("/path/to/dicom")
    widget.show()
"""

__version__ = "1.0.0"
__author__ = "PacsClient Team"

# Core components
from .core.coordinate_systems import CoordinateSystem, ImageGeometry
from .core.volume_loader import VolumeLoader
from .core.mpr_calculator import MPRCalculator, PlaneType
from .core.resampler import MPRResampler, InterpolationType

# Views
from .views.mpr_slice_view import MPRSliceView
from .views.crosshair_manager import CrosshairManager

# Features
from .features.window_level import WindowLevelManager, CT_PRESETS, MR_PRESETS
from .features.thick_slab import ThickSlabMPR, SlabMode
from .features.oblique_reslice import ObliqueReslice
from .features.measurements import Measurements, DistanceMeasurement, AngleMeasurement

# Main widget
from .widgets.mpr_viewer_widget import OrthogonalMPRWidget
from .widgets.toolbar import MPRToolbar
from .widgets.slice_slider import SliceSlider

__all__ = [
    # Version
    "__version__",
    # Core
    "CoordinateSystem",
    "ImageGeometry",
    "VolumeLoader",
    "MPRCalculator",
    "PlaneType",
    "MPRResampler",
    "InterpolationType",
    # Views
    "MPRSliceView",
    "CrosshairManager",
    # Features
    "WindowLevelManager",
    "CT_PRESETS",
    "MR_PRESETS",
    "ThickSlabMPR",
    "SlabMode",
    "ObliqueReslice",
    "Measurements",
    "DistanceMeasurement",
    "AngleMeasurement",
    # Widgets
    "OrthogonalMPRWidget",
    "MPRToolbar",
    "SliceSlider",
]
