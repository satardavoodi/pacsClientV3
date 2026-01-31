"""
Zeta MPR Module

This module contains the Zeta MPR (Multi-Planar Reconstruction) viewer -
the primary and recommended MPR implementation for the PACS system.

Main Components:
- StandardMPRViewer: The main Zeta MPR viewer widget with three orthogonal views
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

__version__ = '1.04'
__author__ = 'PACS Development Team'
