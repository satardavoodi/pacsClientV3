"""
New MPR Zeta Module

This module contains the original/alternative MPR (Multi-Planar Reconstruction) viewer
implementation, kept for comparison and backwards compatibility with the newer MPR implementations.

Main Components:
- StandardMPRViewer: The main MPR viewer widget with three orthogonal views
- preset_manager: Window/Level preset management
- advanced_rendering: Volume rendering and thick slab features
- segmentation_tools: Lung, airway, vessel, and bone segmentation
- surface_reconstruction: 3D surface extraction and rendering
- curved_mpr: Curved multi-planar reconstruction
- mpr_measurement_tools: Distance, angle, and ROI measurement tools
"""

from .standard_mpr_viewer import StandardMPRViewer
from .preset_manager import get_preset_manager, PresetCategory

__all__ = [
    'StandardMPRViewer',
    'get_preset_manager',
    'PresetCategory',
]

__version__ = '2.0.0'
__author__ = 'PACS Development Team'
