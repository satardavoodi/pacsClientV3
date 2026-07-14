"""
3D Cursor Module — Mammography CC/MLO Lesion Correlation

This module implements a physically-based (millimeter) 3D cursor system for
correlating lesion positions between CC and MLO mammography views.

All geometric calculations are performed in millimeters using DICOM Pixel Spacing.
Pixel coordinates are only used at the visualization boundary.

Architecture:
    geometry.py             — Physical-space (mm) geometric computations
    nipple_detect.py        — Nipple position detection from DICOM pixel data
    correlator.py           — 3D cursor correlation logic (pairing + projection)
    visualization.py        — Arc-based projected cursor on viewer widgets (NO rectangles)
    anchor_nipple.py        — Nipple anchor data model (the scientific anchor system)
    distance_computation.py — Physical distance measurements with ±10% uncertainty
    arc_renderer.py         — Anti-aliased arc visualization with uncertainty band
    anchor_interaction.py   — User interaction controller (click/drag/undo/redo)
    anchor_validation.py    — Comprehensive validation for all anchor operations
"""

from .correlator import CursorCorrelator3D
from .geometry import MammogramGeometry, ChestWallOrientation
from .nipple_detect import detect_nipple_position
from .nipple_picker import NipplePickerController
from .pectoral_picker import PectoralLinePickerController, PickedPectoralLine
from .visualization import draw_3d_cursor_results, draw_rulers_for_results, draw_arc_probability_heatmap
from .coord_utils import widget_to_image_coords, get_pixel_array_from_viewer
from .arc_probability import compute_arc_probability, ArcProbabilityResult
from .validation import (
    validate_pectoral_angle,
    validate_projected_point,
    PectoralAngleValidation,
    ValidationResult,
    FullValidationResult,
)

# ── Anchor Nipple System (scientific mammography localization) ──
from .anchor_nipple import (
    NippleAnchor,
    AnchorPair,
    DicomImageInfo,
    MammogramView,
    BreastSide,
    AnchorState,
)
from .distance_computation import (
    compute_anchor_distance,
    compute_arc_parameters,
    compute_pair_distance,
    mm_distance_between_points,
    DistanceResult,
    ArcParameters,
    TOLERANCE_FRACTION,
)
from .arc_renderer import (
    render_anchor_system,
    render_nipple_marker,
    render_arc_with_uncertainty,
    render_distance_label,
    ArcRenderState,
)
from .anchor_interaction import (
    AnchorInteractionController,
    InteractionMode,
    UndoStack,
)
from .anchor_validation import (
    validate_image_info,
    validate_anchor_position,
    validate_distance_preconditions,
    validate_before_computation,
    validate_anchor_pair,
    detect_out_of_image,
    AnchorValidationResult,
)

__all__ = [
    # Legacy 3D Cursor
    "CursorCorrelator3D",
    "MammogramGeometry",
    "ChestWallOrientation",
    "detect_nipple_position",
    "NipplePickerController",
    "PectoralLinePickerController",
    "PickedPectoralLine",
    "draw_3d_cursor_results",
    "draw_rulers_for_results",
    "draw_arc_probability_heatmap",
    "widget_to_image_coords",
    "get_pixel_array_from_viewer",
    "compute_arc_probability",
    "ArcProbabilityResult",
    "validate_pectoral_angle",
    "validate_projected_point",
    "PectoralAngleValidation",
    "ValidationResult",
    "FullValidationResult",
    # Anchor Nipple System
    "NippleAnchor",
    "AnchorPair",
    "DicomImageInfo",
    "MammogramView",
    "BreastSide",
    "AnchorState",
    "compute_anchor_distance",
    "compute_arc_parameters",
    "compute_pair_distance",
    "mm_distance_between_points",
    "DistanceResult",
    "ArcParameters",
    "TOLERANCE_FRACTION",
    "render_anchor_system",
    "render_nipple_marker",
    "render_arc_with_uncertainty",
    "render_distance_label",
    "ArcRenderState",
    "AnchorInteractionController",
    "InteractionMode",
    "UndoStack",
    "validate_image_info",
    "validate_anchor_position",
    "validate_distance_preconditions",
    "validate_before_computation",
    "validate_anchor_pair",
    "detect_out_of_image",
    "AnchorValidationResult",
]
