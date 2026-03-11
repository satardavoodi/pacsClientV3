"""
NewMPR2 Package

This package contains the integration with 3D Slicer custom application (NewMPR2Slicer).
"""

from .slicer_launcher import (
    SlicerLauncher, 
    get_slicer_launcher,
    SlicerPrewarmManager,
    get_prewarm_manager,
    terminate_all_slicer_processes
)

__all__ = [
    'SlicerLauncher', 
    'get_slicer_launcher',
    'SlicerPrewarmManager',
    'get_prewarm_manager',
    'terminate_all_slicer_processes'
]
