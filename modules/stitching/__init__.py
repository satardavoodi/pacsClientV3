"""
Stitching Module — Landmark-based 2D radiograph stitching.

Public API
----------
StitchingWidget      Main UI window (standalone, top-level).
get_stitching_widget Factory function returning the singleton widget.
StitchController     Headless orchestrator (for programmatic / test use).
LandmarkStore        Physical-coordinate landmark pair manager.
"""

from .stitching_widget import StitchingWidget, get_stitching_widget
from .stitch_controller import StitchController
from .landmark_store import LandmarkStore

__all__ = [
    "StitchingWidget",
    "get_stitching_widget",
    "StitchController",
    "LandmarkStore",
]
