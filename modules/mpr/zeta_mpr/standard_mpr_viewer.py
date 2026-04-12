"""
Backward-compatible shim -- re-exports from ``mpr_viewer/`` package.

All code has been split into mixin files under ``mpr_viewer/``.
This file exists solely so that existing ``from .standard_mpr_viewer import ...``
statements continue to work without modification.
"""

from .mpr_viewer import StandardMPRViewer
from .mpr_viewer._interactor_styles import MPRToolbarInteractorStyle, VRTInteractorStyle

__all__ = [
    "StandardMPRViewer",
    "MPRToolbarInteractorStyle",
    "VRTInteractorStyle",
]
