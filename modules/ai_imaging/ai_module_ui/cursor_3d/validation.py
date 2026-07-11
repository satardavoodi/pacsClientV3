"""
Validation & Sanity Checks — Prevent 3D Cursor from projecting outside valid bounds.

This module addresses the critical bug where projected cursors escape the image/tissue
boundary due to invalid intermediate values (e.g., pectoral angle = 70° when clinical
range is 15–60°).

Three layers of defense:
    1. Pectoral angle validation (clinical range enforcement)
    2. Breast contour clipping (point must be inside tissue)
    3. Viewport bounds checking (point must be inside image frame)

All checks produce structured diagnostic logs for easy root-cause analysis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


# ─── Clinical Constants ──────────────────────────────────────────────────────

# Valid pectoral angle range (degrees from vertical) — evidence-based
PECTORAL_ANGLE_MIN_DEG = 15.0
PECTORAL_ANGLE_MAX_DEG = 60.0
PECTORAL_ANGLE_DEFAULT_DEG = 45.0  # Population mean

# Padding for viewport bounds (pixels) — never draw right at the edge
VIEWPORT_PADDING_PX = 5


# ─── Result Types ────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Result of a validation check on a projected point."""
    point_px: Tuple[float, float]  # Final (possibly clamped) point
    is_valid: bool  # True if original point was valid without clamping
    was_clamped: bool  # True if the point was moved to fit bounds
    warning_message: str  # Human-readable warning (empty if valid)
    details: str  # Technical detail for log


@dataclass
class PectoralAngleValidation:
    """Result of pectoral angle validation."""
    angle_deg: float  # Final angle (possibly clamped)
    original_angle_deg: float  # Raw detected angle
    is_valid: bool  # True if original was within range
    was_clamped: bool  # True if angle was adjusted
    warning_message: str  # Warning for UI (empty if valid)


# ─── Pectoral Angle Validation ───────────────────────────────────────────────

def validate_pectoral_angle(
    angle_deg: Optional[float],
    valid_range: Tuple[float, float] = (PECTORAL_ANGLE_MIN_DEG, PECTORAL_ANGLE_MAX_DEG),
    default_deg: float = PECTORAL_ANGLE_DEFAULT_DEG,
) -> PectoralAngleValidation:
    """
    Validate a detected pectoral muscle angle against the clinical range.

    If the angle is outside the valid range, it is clamped to the nearest
    boundary or replaced with the default, and a warning is generated.

    Args:
        angle_deg: Detected angle in degrees from vertical.
                   None means detection completely failed.
        valid_range: (min_deg, max_deg) acceptable clinical range.
        default_deg: Default value when angle is None or wildly invalid.

    Returns:
        PectoralAngleValidation with the final usable angle and warning info.

    Clinical evidence:
        In routine MLO mammography, the pectoral muscle angle is typically 20–55°
        from vertical. Values outside 15–60° suggest detection error (e.g., skin fold
        or rib edge misidentified as pectoral margin).

    Example:
        >>> result = validate_pectoral_angle(70.0)
        >>> result.angle_deg  # 60.0 (clamped to max)
        >>> result.is_valid  # False
        >>> result.warning_message
        'زاویه پکتورال تشخیص‌داده‌شده نامعتبر (70.0°) ...'
    """
    min_deg, max_deg = valid_range

    if angle_deg is None:
        return PectoralAngleValidation(
            angle_deg=default_deg,
            original_angle_deg=0.0,
            is_valid=False,
            was_clamped=True,
            warning_message=(
                f"تشخیص زاویه پکتورال ناموفق — مقدار پیش‌فرض ({default_deg:.0f}°) استفاده شد. "
                f"نتیجه ممکن است نادقیق باشد."
            ),
        )

    if min_deg <= angle_deg <= max_deg:
        # Valid — no action needed
        return PectoralAngleValidation(
            angle_deg=angle_deg,
            original_angle_deg=angle_deg,
            is_valid=True,
            was_clamped=False,
            warning_message="",
        )

    # Invalid — clamp to nearest boundary
    clamped = max(min_deg, min(max_deg, angle_deg))

    return PectoralAngleValidation(
        angle_deg=clamped,
        original_angle_deg=angle_deg,
        is_valid=False,
        was_clamped=True,
        warning_message=(
            f"⚠ زاویه پکتورال تشخیص‌داده‌شده نامعتبر ({angle_deg:.1f}°) — "
            f"بازه مجاز: [{min_deg:.0f}°, {max_deg:.0f}°]. "
            f"مقدار به {clamped:.1f}° محدود شد. "
            f"نتیجه ممکن است نیاز به بازبینی دستی داشته باشد."
        ),
    )


# ─── Breast Contour Clipping ────────────────────────────────────────────────

def clamp_point_to_contour(
    point_px: Tuple[float, float],
    contour: Optional[np.ndarray],
) -> ValidationResult:
    """
    Ensure a point lies inside the breast tissue contour; if not, snap to boundary.

    Uses OpenCV's pointPolygonTest to check containment, and if the point is
    outside, finds the closest point on the contour boundary.

    Args:
        point_px: (x, y) pixel coordinates of the projected point.
        contour: Breast contour in OpenCV format (N, 1, 2) ndarray.
                 If None, validation is skipped (assumed valid).

    Returns:
        ValidationResult with the original or clamped point.

    Algorithm:
        1. cv2.pointPolygonTest(contour, point, measureDist=True)
            - Positive: point is inside → valid
            - Zero: point is on edge → valid
            - Negative: point is outside → snap to nearest boundary point

        2. If outside: find nearest point by iterating contour vertices
           (or projecting onto edges for sub-vertex accuracy).
    """
    x, y = point_px

    if contour is None:
        return ValidationResult(
            point_px=point_px,
            is_valid=True,
            was_clamped=False,
            warning_message="",
            details="contour=None, skip",
        )

    try:
        import cv2
    except ImportError:
        return ValidationResult(
            point_px=point_px,
            is_valid=True,
            was_clamped=False,
            warning_message="",
            details="cv2 unavailable, skip",
        )

    # Check if point is inside contour
    dist = cv2.pointPolygonTest(contour, (float(x), float(y)), measureDist=True)

    if dist >= 0:
        # Point is inside or on boundary — valid
        return ValidationResult(
            point_px=point_px,
            is_valid=True,
            was_clamped=False,
            warning_message="",
            details=f"inside_contour dist={dist:.1f}px",
        )

    # Point is OUTSIDE — snap to nearest boundary point
    nearest = _find_nearest_contour_point(point_px, contour)

    return ValidationResult(
        point_px=nearest,
        is_valid=False,
        was_clamped=True,
        warning_message=(
            f"⚠ نقطه محاسبه‌شده خارج از بافت سینه بود ({abs(dist):.0f}px) — "
            f"به نزدیک‌ترین نقطه روی مرز بافت محدود شد. "
            f"بازبینی دستی توصیه می‌شود."
        ),
        details=f"outside_contour dist={dist:.1f}px, snapped ({x:.0f},{y:.0f})->({nearest[0]:.0f},{nearest[1]:.0f})",
    )


def _find_nearest_contour_point(
    point_px: Tuple[float, float],
    contour: np.ndarray,
) -> Tuple[float, float]:
    """Find the nearest point on a contour boundary to the given point."""
    x, y = point_px

    # Reshape contour to (N, 2)
    pts = contour.reshape(-1, 2).astype(np.float64)

    # Compute distances to all contour vertices
    distances = np.sqrt((pts[:, 0] - x) ** 2 + (pts[:, 1] - y) ** 2)
    nearest_idx = np.argmin(distances)

    # For better accuracy, project onto the edge segments around the nearest vertex
    n = len(pts)
    best_point = pts[nearest_idx]
    best_dist = distances[nearest_idx]

    # Check the two adjacent edges for a closer projection
    for offset in [-1, 0]:
        i = (nearest_idx + offset) % n
        j = (i + 1) % n
        proj = _project_point_onto_segment(point_px, tuple(pts[i]), tuple(pts[j]))
        d = math.sqrt((proj[0] - x) ** 2 + (proj[1] - y) ** 2)
        if d < best_dist:
            best_dist = d
            best_point = proj

    return (float(best_point[0]), float(best_point[1]))


def _project_point_onto_segment(
    point: Tuple[float, float],
    seg_a: Tuple[float, float],
    seg_b: Tuple[float, float],
) -> Tuple[float, float]:
    """Project a point onto a line segment, clamping to endpoints."""
    px, py = point
    ax, ay = seg_a
    bx, by = seg_b

    dx = bx - ax
    dy = by - ay
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq < 1e-10:
        return seg_a

    # Parameter t along segment [0, 1]
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))

    return (ax + t * dx, ay + t * dy)


# ─── Viewport Bounds Check ───────────────────────────────────────────────────

def check_viewport_bounds(
    point_px: Tuple[float, float],
    image_width: int,
    image_height: int,
    padding: int = VIEWPORT_PADDING_PX,
) -> ValidationResult:
    """
    Check whether a point is within the visible image bounds.

    If outside, clamps to the image edge (with padding) and flags the error.

    Args:
        point_px: (x, y) pixel coordinates.
        image_width: Image width in pixels.
        image_height: Image height in pixels.
        padding: Minimum distance from image edge (pixels).

    Returns:
        ValidationResult with clipped point if needed.

    Note:
        This is an absolute hard boundary — a point outside the image frame
        is a definite error, not a soft warning.
    """
    x, y = point_px
    x_min = padding
    y_min = padding
    x_max = image_width - padding
    y_max = image_height - padding

    if x_min <= x <= x_max and y_min <= y <= y_max:
        return ValidationResult(
            point_px=point_px,
            is_valid=True,
            was_clamped=False,
            warning_message="",
            details=f"in_bounds ({x:.0f},{y:.0f}) within [{x_min},{y_min}]-[{x_max},{y_max}]",
        )

    # Clamp to image boundaries
    clamped_x = max(x_min, min(x_max, x))
    clamped_y = max(y_min, min(y_max, y))

    # How far out was it?
    overshoot_x = max(0, x_min - x, x - x_max)
    overshoot_y = max(0, y_min - y, y - y_max)
    overshoot_px = math.sqrt(overshoot_x ** 2 + overshoot_y ** 2)

    return ValidationResult(
        point_px=(clamped_x, clamped_y),
        is_valid=False,
        was_clamped=True,
        warning_message=(
            f"⚠ نقطه محاسبه‌شده خارج از محدوده تصویر است "
            f"({overshoot_px:.0f}px بیرون از کادر) — "
            f"لطفاً موقعیت نوک سینه یا زاویه پکتورال را بازبینی کنید."
        ),
        details=(
            f"out_of_bounds ({x:.0f},{y:.0f})->({clamped_x:.0f},{clamped_y:.0f}) "
            f"image={image_width}x{image_height} overshoot={overshoot_px:.0f}px"
        ),
    )


# ─── Combined Validation Pipeline ───────────────────────────────────────────

@dataclass
class FullValidationResult:
    """Combined result of all validation layers."""
    final_point_px: Tuple[float, float]
    original_point_px: Tuple[float, float]
    pectoral_validation: Optional[PectoralAngleValidation]
    contour_validation: Optional[ValidationResult]
    bounds_validation: Optional[ValidationResult]
    any_warning: bool
    combined_warning: str  # All warnings joined
    log_line: str  # Structured single-line log entry


def validate_projected_point(
    point_px: Tuple[float, float],
    *,
    image_width: int,
    image_height: int,
    breast_contour: Optional[np.ndarray] = None,
    pectoral_angle_deg: Optional[float] = None,
    source_depth_mm: float = 0.0,
    source_view: str = "",
    target_view: str = "",
) -> FullValidationResult:
    """
    Run the complete validation pipeline on a projected point.

    Order of checks:
        1. Viewport bounds (hard limit — must be inside image)
        2. Breast contour (soft limit — snap to tissue boundary)

    The pectoral angle validation should be run BEFORE computing the point
    (see validate_pectoral_angle), so here we just carry its result for logging.

    Args:
        point_px: The computed projected point.
        image_width: Target image width.
        image_height: Target image height.
        breast_contour: Target view breast contour (optional).
        pectoral_angle_deg: The (already validated) pectoral angle (for log).
        source_depth_mm: Distance from nipple in source view (for log).
        source_view: 'CC' or 'MLO' (for log).
        target_view: 'CC' or 'MLO' (for log).

    Returns:
        FullValidationResult with final safe point and diagnostic info.
    """
    original = point_px
    current = point_px
    warnings = []

    # Layer 1: Viewport bounds
    bounds_result = check_viewport_bounds(current, image_width, image_height)
    if bounds_result.was_clamped:
        current = bounds_result.point_px
        warnings.append(bounds_result.warning_message)

    # Layer 2: Breast contour
    contour_result = clamp_point_to_contour(current, breast_contour)
    if contour_result.was_clamped:
        current = contour_result.point_px
        warnings.append(contour_result.warning_message)

    # Build structured log
    any_warn = len(warnings) > 0
    log_parts = [
        f"[3D-Cursor][VALIDATE]",
        f"d={source_depth_mm:.1f}mm",
        f"{source_view}->{target_view}",
        f"pec_angle={pectoral_angle_deg if pectoral_angle_deg else 'N/A'}°",
        f"orig=({original[0]:.0f},{original[1]:.0f})",
        f"final=({current[0]:.0f},{current[1]:.0f})",
        f"in_bounds={'Yes' if bounds_result.is_valid else 'NO'}",
        f"in_contour={'Yes' if contour_result.is_valid else 'NO'}",
    ]
    if any_warn:
        log_parts.append("STATUS=CLAMPED")
    else:
        log_parts.append("STATUS=OK")

    log_line = " ".join(log_parts)

    return FullValidationResult(
        final_point_px=current,
        original_point_px=original,
        pectoral_validation=None,  # Set by caller
        contour_validation=contour_result,
        bounds_validation=bounds_result,
        any_warning=any_warn,
        combined_warning="\n".join(warnings),
        log_line=log_line,
    )


# ─── Diagnostic Logging Helper ──────────────────────────────────────────────

def format_calc_log(
    source_view: str,
    target_view: str,
    depth_mm: float,
    pectoral_angle_deg: Optional[float],
    pectoral_valid: bool,
    clamped_angle_deg: Optional[float],
    target_point_px: Tuple[float, float],
    in_bounds: bool,
    in_contour: bool,
    final_point_px: Optional[Tuple[float, float]] = None,
) -> str:
    """
    Format a structured diagnostic log line for a single projection calculation.

    Output format:
        [3D-Cursor][CALC] d=89.8mm phi_src=CC phi_dst=MLO
            pectoral_angle=70.0°(INVALID-clamped-to-45.0°)
            target_point=(1200,2800) in_bounds=False in_contour=False
            clipped_to=(1150,2450)

    This enables quick grep-based debugging of out-of-bounds projections.
    """
    # Pectoral angle part
    if pectoral_angle_deg is None:
        pec_str = "pectoral=N/A"
    elif pectoral_valid:
        pec_str = f"pectoral={pectoral_angle_deg:.1f}°(OK)"
    else:
        pec_str = (
            f"pectoral={pectoral_angle_deg:.1f}°"
            f"(INVALID-clamped-to-{clamped_angle_deg:.1f}°)"
        )

    # Target point
    tp = target_point_px
    tp_str = f"target=({tp[0]:.0f},{tp[1]:.0f})"

    # Bounds
    bounds_str = f"in_bounds={'Yes' if in_bounds else 'NO'}"
    contour_str = f"in_contour={'Yes' if in_contour else 'NO'}"

    # Final
    if final_point_px and final_point_px != target_point_px:
        final_str = f"clipped_to=({final_point_px[0]:.0f},{final_point_px[1]:.0f})"
    else:
        final_str = ""

    parts = [
        f"[3D-Cursor][CALC]",
        f"d={depth_mm:.1f}mm",
        f"{source_view}->{target_view}",
        pec_str,
        tp_str,
        bounds_str,
        contour_str,
    ]
    if final_str:
        parts.append(final_str)

    return " ".join(parts)
