"""
3D Cursor Module — Mammography CC/MLO Lesion Correlation

This module implements a physically-based (millimeter) 3D cursor system for
correlating lesion positions between CC and MLO mammography views.

All geometric calculations are performed in millimeters using DICOM Pixel Spacing.
Pixel coordinates are only used at the visualization boundary.

Architecture:
    geometry.py      — Physical-space (mm) geometric computations
    nipple_detect.py — Nipple position detection from DICOM pixel data
    correlator.py    — 3D cursor correlation logic (pairing + projection)
    visualization.py — Drawing projected boxes on viewer widgets
"""

from .correlator import CursorCorrelator3D
from .geometry import MammogramGeometry, ChestWallOrientation
from .nipple_detect import detect_nipple_position
from .nipple_picker import NipplePickerController
from .visualization import draw_rulers_for_results
from .validation import (
    validate_pectoral_angle,
    validate_projected_point,
    PectoralAngleValidation,
    ValidationResult,
    FullValidationResult,
)

__all__ = [
    "CursorCorrelator3D",
    "MammogramGeometry",
    "ChestWallOrientation",
    "detect_nipple_position",
    "NipplePickerController",
    "draw_rulers_for_results",
    "validate_pectoral_angle",
    "validate_projected_point",
    "PectoralAngleValidation",
    "ValidationResult",
    "FullValidationResult",
]
