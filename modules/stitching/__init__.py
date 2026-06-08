"""
Stitching Module — Landmark-based 2D radiograph stitching.

Public API
----------
StitchingWidget      Main UI window (standalone, top-level).
get_stitching_widget Factory function returning the singleton widget.
LandmarkStore        Physical-coordinate landmark pair manager.
"""

from .stitching_widget import StitchingWidget, get_stitching_widget
from .landmark_store import LandmarkStore

__all__ = [
    "StitchingWidget",
    "get_stitching_widget",
    "LandmarkStore",
]
