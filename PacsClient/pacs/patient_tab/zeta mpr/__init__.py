"""
Zeta MPR Module

Primary MPR (Multi-Planar Reconstruction) viewer implementation for AI-PACS.
Features proper crosshair interaction following medical imaging best practices.

Main Components:
- StandardMPRViewer: The main Zeta MPR viewer widget with three orthogonal views
- preset_manager: Window/Level preset management
- advanced_rendering: Volume rendering and thick slab features
- segmentation_tools: Lung, airway, vessel, and bone segmentation
- surface_reconstruction: 3D surface extraction and rendering
- curved_mpr: Curved multi-planar reconstruction
- mpr_measurement_tools: Distance, angle, and ROI measurement tools

Version History:
- v1.09.8.2: Stable release alignment and documentation sync
- v1.05: Drag-only crosshair (Phase 1 - separating 3D Cursor from Crosshair)
- v1.02: Stable baseline with input-level flip correction
- v1.01: Input-level flip correction for anatomical orientation
"""

from .standard_mpr_viewer import StandardMPRViewer
from .preset_manager import get_preset_manager, PresetCategory

__all__ = [
    'StandardMPRViewer',
    'get_preset_manager',
    'PresetCategory',
]

__version__ = '1.09.8.2'
__author__ = 'PACS Development Team'
