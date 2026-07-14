"""
Distance Computation — Physically-accurate distance measurements for mammography.

All distances are computed in millimeters using DICOM PixelSpacing.
Pixel-only distances are NEVER used for clinical measurements.

Key Measurements:
    1. Nipple-to-point distance: Euclidean distance in mm from anchor to any point.
    2. Nipple-to-nipple correspondence: Distance between CC and MLO anchors (for QC).
    3. Arc radius: The preserved depth distance projected between views.

Uncertainty Model:
    A ±10% tolerance band accounts for:
    - Breast compression differences between CC and MLO.
    - Patient repositioning between exposures.
    - Tissue deformation under compression.

    This is a clinically accepted approximation (Kopans, 2007).

Coordinate System:
    All calculations are performed in detector coordinates (mm on the detector
    surface). No magnification correction is applied here — document that
    calculations are in detector coordinates unless the project provides a
    magnification factor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from .anchor_nipple import (
    AnchorPair,
    BreastSide,
    DicomImageInfo,
    MammogramView,
    NippleAnchor,
)


# ─── Tolerance Constants ─────────────────────────────────────────────────────

# Clinical tolerance for nipple-to-lesion depth correspondence between views.
# Based on Kopans' Rule: distances should match within ~10%.
TOLERANCE_FRACTION = 0.10  # ±10%


# ─── Result Types ────────────────────────────────────────────────────────────

@dataclass
class DistanceResult:
    """
    Result of a physical distance computation.

    All values are in millimeters unless otherwise noted.
    """
    # Primary measurement
    distance_mm: float
    # Uncertainty band
    lower_bound_mm: float  # distance × (1 - tolerance)
    upper_bound_mm: float  # distance × (1 + tolerance)
    tolerance_fraction: float  # 0.10 for ±10%
    # Source information
    from_anchor: NippleAnchor
    to_point_px: Tuple[float, float]
    to_point_mm: Tuple[float, float]
    # Validation
    is_valid: bool
    error_message: str = ""
    # Whether target point is inside image
    target_inside_image: bool = True

    @property
    def range_str(self) -> str:
        """Human-readable range string, e.g. '57.9–70.7 mm'."""
        return f"{self.lower_bound_mm:.1f}–{self.upper_bound_mm:.1f} mm"

    @property
    def distance_str(self) -> str:
        """Human-readable distance, e.g. '64.3 mm'."""
        return f"{self.distance_mm:.1f} mm"

    @property
    def tolerance_str(self) -> str:
        """Human-readable tolerance, e.g. '±10%'."""
        return f"±{self.tolerance_fraction * 100:.0f}%"


@dataclass
class ArcParameters:
    """
    Parameters for drawing the correspondence arc with uncertainty band.

    The arc is centered on the nipple anchor in the TARGET view.
    Three concentric arcs represent the uncertainty band:
        - inner_radius_mm: lower bound (distance × 0.90)
        - nominal_radius_mm: best estimate (distance)
        - outer_radius_mm: upper bound (distance × 1.10)
    """
    center_px: Tuple[float, float]  # Nipple anchor position in target view
    center_mm: Tuple[float, float]
    # Radii in mm
    nominal_radius_mm: float
    inner_radius_mm: float  # distance × (1 - tolerance)
    outer_radius_mm: float  # distance × (1 + tolerance)
    # Radii in pixels (for rendering) — averaged pixel spacing
    nominal_radius_px: float
    inner_radius_px: float
    outer_radius_px: float
    # Angular extent (radians, image coordinate system, 0=right, π/2=down)
    start_angle_rad: float
    end_angle_rad: float
    # Source info
    source_anchor: NippleAnchor
    target_image_info: DicomImageInfo
    # Validity
    is_valid: bool
    error_message: str = ""


# ─── Core Distance Functions ─────────────────────────────────────────────────

def compute_anchor_distance(
    anchor: NippleAnchor,
    target_x_px: float,
    target_y_px: float,
    tolerance: float = TOLERANCE_FRACTION,
) -> DistanceResult:
    """
    Compute the physical distance from a nipple anchor to a target point.

    This is the primary distance measurement function. It:
    1. Validates all inputs.
    2. Converts to millimeters using PixelSpacing.
    3. Computes Euclidean distance in mm.
    4. Applies ±10% tolerance band.
    5. Checks if target is within image bounds.

    Mathematical basis:
        dx_mm = (target_x_px - anchor.x_px) × pixel_spacing_x
        dy_mm = (target_y_px - anchor.y_px) × pixel_spacing_y
        distance = √(dx_mm² + dy_mm²)
        lower = distance × (1 - tolerance)
        upper = distance × (1 + tolerance)

    Args:
        anchor: The nipple anchor (reference point).
        target_x_px: Target point x-coordinate in pixels.
        target_y_px: Target point y-coordinate in pixels.
        tolerance: Fractional tolerance (default 0.10 = ±10%).

    Returns:
        DistanceResult with the measurement and uncertainty band.
    """
    # ── Input Validation ──
    if not anchor.is_valid:
        return DistanceResult(
            distance_mm=0.0,
            lower_bound_mm=0.0,
            upper_bound_mm=0.0,
            tolerance_fraction=tolerance,
            from_anchor=anchor,
            to_point_px=(target_x_px, target_y_px),
            to_point_mm=(0.0, 0.0),
            is_valid=False,
            error_message="Nipple anchor is not in a valid state.",
        )

    if math.isnan(target_x_px) or math.isnan(target_y_px):
        return DistanceResult(
            distance_mm=0.0,
            lower_bound_mm=0.0,
            upper_bound_mm=0.0,
            tolerance_fraction=tolerance,
            from_anchor=anchor,
            to_point_px=(target_x_px, target_y_px),
            to_point_mm=(0.0, 0.0),
            is_valid=False,
            error_message="Target point contains NaN values.",
        )

    if math.isinf(target_x_px) or math.isinf(target_y_px):
        return DistanceResult(
            distance_mm=0.0,
            lower_bound_mm=0.0,
            upper_bound_mm=0.0,
            tolerance_fraction=tolerance,
            from_anchor=anchor,
            to_point_px=(target_x_px, target_y_px),
            to_point_mm=(0.0, 0.0),
            is_valid=False,
            error_message="Target point contains infinite values.",
        )

    # ── Check if target is inside image ──
    info = anchor.image_info
    target_inside = info.is_inside(target_x_px, target_y_px)

    # ── Compute physical distance ──
    # Convert displacement to mm using per-axis PixelSpacing
    dx_px = target_x_px - anchor.x_px
    dy_px = target_y_px - anchor.y_px
    dx_mm = dx_px * info.pixel_spacing_x_mm
    dy_mm = dy_px * info.pixel_spacing_y_mm

    # Euclidean distance in millimeters
    distance_mm = math.sqrt(dx_mm * dx_mm + dy_mm * dy_mm)

    # ── Compute uncertainty band ──
    lower_bound_mm = distance_mm * (1.0 - tolerance)
    upper_bound_mm = distance_mm * (1.0 + tolerance)

    # ── Physical coordinates of target ──
    target_x_mm, target_y_mm = info.pixel_to_mm(target_x_px, target_y_px)

    # ── Build error message for out-of-image ──
    error_msg = ""
    if not target_inside:
        error_msg = (
            "⚠ خارج از ناحیه تصویر | "
            "Projected point is outside the image area. "
            f"(dx={dx_mm:.1f}mm, dy={dy_mm:.1f}mm)"
        )

    return DistanceResult(
        distance_mm=distance_mm,
        lower_bound_mm=lower_bound_mm,
        upper_bound_mm=upper_bound_mm,
        tolerance_fraction=tolerance,
        from_anchor=anchor,
        to_point_px=(target_x_px, target_y_px),
        to_point_mm=(target_x_mm, target_y_mm),
        is_valid=True,
        error_message=error_msg,
        target_inside_image=target_inside,
    )


def compute_arc_parameters(
    source_anchor: NippleAnchor,
    target_anchor: NippleAnchor,
    target_point_px: Tuple[float, float],
    tolerance: float = TOLERANCE_FRACTION,
    angular_extent_deg: float = 120.0,
) -> ArcParameters:
    """
    Compute parameters for drawing a correspondence arc on the target view.

    The arc represents the locus of points at a preserved distance from the
    nipple. The ±10% band shows the clinically accepted uncertainty.

    The arc is drawn centered on the TARGET view's nipple anchor, with radius
    equal to the distance from the SOURCE view's nipple to the lesion/point.

    Mathematical basis:
        radius_mm = distance(source_anchor, source_point)
        This radius is preserved in the target view (Kopans' Rule).

        Arc center = target_anchor position (the nipple in the target view).
        Arc radii:
            inner = radius_mm × 0.90
            nominal = radius_mm
            outer = radius_mm × 1.10

    Args:
        source_anchor: Nipple anchor in the source (measured) view.
        target_anchor: Nipple anchor in the target (projection) view.
        target_point_px: Point in source view to project (x_px, y_px).
        tolerance: Fractional tolerance (default 0.10).
        angular_extent_deg: Total angular span of the arc (degrees).

    Returns:
        ArcParameters for rendering the arc with uncertainty band.
    """
    # Compute distance from source anchor to target point
    dist_result = compute_anchor_distance(
        source_anchor,
        target_point_px[0],
        target_point_px[1],
        tolerance=tolerance,
    )

    if not dist_result.is_valid:
        return ArcParameters(
            center_px=target_anchor.position_px,
            center_mm=target_anchor.position_mm,
            nominal_radius_mm=0.0,
            inner_radius_mm=0.0,
            outer_radius_mm=0.0,
            nominal_radius_px=0.0,
            inner_radius_px=0.0,
            outer_radius_px=0.0,
            start_angle_rad=0.0,
            end_angle_rad=0.0,
            source_anchor=source_anchor,
            target_image_info=target_anchor.image_info,
            is_valid=False,
            error_message=dist_result.error_message,
        )

    # ── Convert radii from mm to pixels ──
    # Use average pixel spacing for isotropic arc rendering.
    # Note: If pixel spacing is highly anisotropic, the arc would be an ellipse;
    # here we use the geometric mean for a circular approximation.
    target_info = target_anchor.image_info
    avg_spacing_mm = math.sqrt(
        target_info.pixel_spacing_x_mm * target_info.pixel_spacing_y_mm
    )

    nominal_radius_mm = dist_result.distance_mm
    inner_radius_mm = dist_result.lower_bound_mm
    outer_radius_mm = dist_result.upper_bound_mm

    nominal_radius_px = nominal_radius_mm / avg_spacing_mm
    inner_radius_px = inner_radius_mm / avg_spacing_mm
    outer_radius_px = outer_radius_mm / avg_spacing_mm

    # ── Compute angular extent ──
    # Arc is centered toward the chest wall direction.
    # Determine chest wall direction based on laterality and view.
    center_angle_rad = _compute_arc_center_angle(target_anchor)
    half_span_rad = math.radians(angular_extent_deg / 2.0)
    start_angle_rad = center_angle_rad - half_span_rad
    end_angle_rad = center_angle_rad + half_span_rad

    return ArcParameters(
        center_px=target_anchor.position_px,
        center_mm=target_anchor.position_mm,
        nominal_radius_mm=nominal_radius_mm,
        inner_radius_mm=inner_radius_mm,
        outer_radius_mm=outer_radius_mm,
        nominal_radius_px=nominal_radius_px,
        inner_radius_px=inner_radius_px,
        outer_radius_px=outer_radius_px,
        start_angle_rad=start_angle_rad,
        end_angle_rad=end_angle_rad,
        source_anchor=source_anchor,
        target_image_info=target_info,
        is_valid=True,
    )


def compute_pair_distance(pair: AnchorPair) -> Optional[DistanceResult]:
    """
    Compute the distance between CC and MLO nipple anchors of the same breast.

    This serves as a quality control check — the nipple should be at approximately
    the same distance from the chest wall in both views. A large difference
    may indicate incorrect nipple placement.

    Returns:
        DistanceResult if both anchors are present and valid, else None.
    """
    if not pair.is_complete:
        return None

    cc = pair.cc_anchor
    mlo = pair.mlo_anchor

    # Distance from CC nipple to MLO nipple is not directly meaningful
    # across views, but we can compare their distances to their respective
    # chest walls (image edges) as a sanity check.
    # For now, return the straight-line mm distance between the two anchors
    # in their respective coordinate systems — this is informational only.
    return compute_anchor_distance(cc, mlo.x_px, mlo.y_px)


# ─── Helper Functions ────────────────────────────────────────────────────────

def _compute_arc_center_angle(anchor: NippleAnchor) -> float:
    """
    Compute the center angle for the correspondence arc.

    The arc sweeps toward the chest wall side.

    In standard mammography display:
        - Right breast (R): chest wall is on the RIGHT side of image → angle 0° (right)
        - Left breast (L): chest wall is on the LEFT side of image → angle π (left)

    For MLO views, the angle tilts upward (toward pectoral muscle):
        - R-MLO: arc tilts upper-right → ~−π/6
        - L-MLO: arc tilts upper-left → ~π + π/6

    Returns:
        Center angle in radians (image coordinate system: 0=right, π/2=down).
    """
    side = anchor.image_info.laterality
    view = anchor.image_info.view

    if side == BreastSide.RIGHT:
        # Chest wall on the right
        if view == MammogramView.CC:
            return 0.0  # Arc sweeps rightward
        else:  # MLO
            # Tilt upward by ~30° (typical pectoral angle direction)
            return -math.pi / 6.0
    else:
        # Chest wall on the left
        if view == MammogramView.CC:
            return math.pi  # Arc sweeps leftward
        else:  # MLO
            return math.pi + math.pi / 6.0


def mm_distance_between_points(
    x1_px: float, y1_px: float,
    x2_px: float, y2_px: float,
    pixel_spacing_x_mm: float,
    pixel_spacing_y_mm: float,
) -> float:
    """
    Compute the physical distance between two points given pixel spacing.

    This is a stateless utility for cases where you don't have a NippleAnchor object.

    Mathematical basis:
        dx_mm = (x2 - x1) × spacing_x
        dy_mm = (y2 - y1) × spacing_y
        distance = √(dx_mm² + dy_mm²)

    Args:
        x1_px, y1_px: First point in pixels.
        x2_px, y2_px: Second point in pixels.
        pixel_spacing_x_mm: Column spacing (mm/pixel).
        pixel_spacing_y_mm: Row spacing (mm/pixel).

    Returns:
        Distance in millimeters.

    Raises:
        ValueError: If any input is NaN, Inf, or spacing <= 0.
    """
    if pixel_spacing_x_mm <= 0 or pixel_spacing_y_mm <= 0:
        raise ValueError(
            f"Pixel spacing must be > 0, got ({pixel_spacing_x_mm}, {pixel_spacing_y_mm})"
        )

    for val in (x1_px, y1_px, x2_px, y2_px):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Coordinate contains NaN or Inf: {val}")

    dx_mm = (x2_px - x1_px) * pixel_spacing_x_mm
    dy_mm = (y2_px - y1_px) * pixel_spacing_y_mm
    return math.sqrt(dx_mm * dx_mm + dy_mm * dy_mm)
