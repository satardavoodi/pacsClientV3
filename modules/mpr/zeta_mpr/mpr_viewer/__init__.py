"""
Zeta MPR Viewer — mixin-based module.

This package splits the monolithic StandardMPRViewer into focused mixins
while preserving 100 % behavioral compatibility.  The original import
path (``modules.mpr.zeta_mpr.standard_mpr_viewer``) is kept as a thin
backward-compatible shim that re-exports from here.
"""

from .widget import StandardMPRViewer
from ._interactor_styles import MPRToolbarInteractorStyle, VRTInteractorStyle

__all__ = [
    "StandardMPRViewer",
    "MPRToolbarInteractorStyle",
    "VRTInteractorStyle",
]
