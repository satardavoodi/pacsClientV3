"""
New MPR4 Module
===============

Integration module for ITK-SNAP functionality in the Patient Tab.

This module provides:
- New MPR4 widget for UI integration
- Entry point functions for launching the module
- Bridge to ITK-SNAP segmentation and MPR capabilities

ITK-SNAP source code location: external/itksnap/
"""

from .newmpr4_module import (
    open_newmpr4,
    show_newmpr4_tool,
    launch_itk_mpr_for_active_series,
    OpenNewMPR4,
    ShowNewMPR4Tool
)
from .newmpr4_widget import NewMPR4Widget

__all__ = [
    'NewMPR4Widget',
    'open_newmpr4',
    'show_newmpr4_tool',
    'launch_itk_mpr_for_active_series',
    'OpenNewMPR4',
    'ShowNewMPR4Tool',
]
