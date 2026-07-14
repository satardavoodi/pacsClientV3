"""
Anchor Validation — Comprehensive validation for the nipple anchor system.

Validates:
    - Image metadata completeness (PixelSpacing, dimensions)
    - Anchor coordinates (bounds, NaN, Inf, negative)
    - Distance computation preconditions
    - Out-of-image detection (distinct from calculation error)
    - Cross-view consistency (CC vs MLO same breast)

Design principle:
    Every validation function returns a structured result.
    NEVER silently continue on validation failure.
    Always provide a meaningful, actionable error message.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .anchor_nipple import (
    AnchorPair,
    AnchorState,
    BreastSide,
    DicomImageInfo,
    MammogramView,
    NippleAnchor,
)


# ─── Validation Result ───────────────────────────────────────────────────────

@dataclass
class AnchorValidationResult:
    """Structured result of anchor validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]

    @classmethod
    def ok(cls) -> "AnchorValidationResult":
        return cls(is_valid=True, errors=[], warnings=[])

    @classmethod
    def error(cls, message: str) -> "AnchorValidationResult":
        return cls(is_valid=False, errors=[message], warnings=[])

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def summary(self) -> str:
        """Single-line summary of validation state."""
        if self.is_valid and not self.warnings:
            return "Valid"
        parts = []
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        return "; ".join(parts)

    @property
    def full_message(self) -> str:
        """Full human-readable validation report."""
        lines = []
        for e in self.errors:
            lines.append(f"ERROR: {e}")
        for w in self.warnings:
            lines.append(f"WARNING: {w}")
        return "\n".join(lines) if lines else "All checks passed."


# ─── Image Info Validation ───────────────────────────────────────────────────

def validate_image_info(info: Optional[DicomImageInfo]) -> AnchorValidationResult:
    """
    Validate that image metadata is complete and usable.

    Checks:
        ✓ info is not None
        ✓ width > 0
        ✓ height > 0
        ✓ pixel_spacing_x > 0
        ✓ pixel_spacing_y > 0
        ✓ no NaN values in spacing
        ✓ no Inf values in spacing
        ✓ spacing is reasonable (0.01 – 10.0 mm/pixel for mammography)

    Returns:
        AnchorValidationResult with detailed error messages.
    """
    result = AnchorValidationResult.ok()

    if info is None:
        result.add_error("No DICOM image information available.")
        return result

    # Dimension checks
    if info.width_px <= 0:
        result.add_error(f"Image width must be positive, got {info.width_px}.")
    if info.height_px <= 0:
        result.add_error(f"Image height must be positive, got {info.height_px}.")

    # Pixel spacing checks
    sx = info.pixel_spacing_x_mm
    sy = info.pixel_spacing_y_mm

    if sx <= 0:
        result.add_error(f"PixelSpacing X must be positive, got {sx}.")
    if sy <= 0:
        result.add_error(f"PixelSpacing Y must be positive, got {sy}.")

    if math.isnan(sx):
        result.add_error("PixelSpacing X is NaN.")
    if math.isnan(sy):
        result.add_error("PixelSpacing Y is NaN.")
    if math.isinf(sx):
        result.add_error("PixelSpacing X is infinite.")
    if math.isinf(sy):
        result.add_error("PixelSpacing Y is infinite.")

    # Sanity range for mammography (typical: 0.05 – 0.2 mm/pixel)
    # Allow broader range (0.01 – 10.0) for unusual acquisitions
    SPACING_MIN = 0.01
    SPACING_MAX = 10.0

    if not result.errors:  # Only check range if values are finite
        if sx < SPACING_MIN or sx > SPACING_MAX:
            result.add_warning(
                f"PixelSpacing X ({sx:.4f} mm) is outside typical range "
                f"[{SPACING_MIN}, {SPACING_MAX}] mm/pixel."
            )
        if sy < SPACING_MIN or sy > SPACING_MAX:
            result.add_warning(
                f"PixelSpacing Y ({sy:.4f} mm) is outside typical range "
                f"[{SPACING_MIN}, {SPACING_MAX}] mm/pixel."
            )

    return result


# ─── Anchor Position Validation ──────────────────────────────────────────────

def validate_anchor_position(
    x_px: float,
    y_px: float,
    image_info: DicomImageInfo,
) -> AnchorValidationResult:
    """
    Validate that an anchor position is geometrically valid.

    Checks:
        ✓ coordinates are not NaN
        ✓ coordinates are not Inf
        ✓ coordinates are not negative
        ✓ coordinates are within image bounds

    Does NOT clamp — returns an error for out-of-bounds.
    The caller decides how to handle the error.
    """
    result = AnchorValidationResult.ok()

    # NaN check
    if math.isnan(x_px) or math.isnan(y_px):
        result.add_error(
            f"Anchor coordinates contain NaN: ({x_px}, {y_px})."
        )
        return result

    # Inf check
    if math.isinf(x_px) or math.isinf(y_px):
        result.add_error(
            f"Anchor coordinates contain infinite values: ({x_px}, {y_px})."
        )
        return result

    # Negative coordinate check
    if x_px < 0:
        result.add_error(
            f"Anchor X coordinate is negative: {x_px:.1f}. "
            f"Coordinates must be >= 0."
        )
    if y_px < 0:
        result.add_error(
            f"Anchor Y coordinate is negative: {y_px:.1f}. "
            f"Coordinates must be >= 0."
        )

    # Bounds check
    if x_px >= image_info.width_px:
        result.add_error(
            f"⚠ خارج از ناحیه تصویر | "
            f"Anchor X coordinate ({x_px:.1f}) exceeds image width "
            f"({image_info.width_px})."
        )
    if y_px >= image_info.height_px:
        result.add_error(
            f"⚠ خارج از ناحیه تصویر | "
            f"Anchor Y coordinate ({y_px:.1f}) exceeds image height "
            f"({image_info.height_px})."
        )

    # Edge proximity warning (anchor very close to border — likely misplaced)
    EDGE_WARNING_PX = 10
    if result.is_valid:
        if x_px < EDGE_WARNING_PX or x_px > image_info.width_px - EDGE_WARNING_PX:
            result.add_warning(
                f"Anchor is very close to the image edge (x={x_px:.0f}). "
                f"Verify nipple placement."
            )
        if y_px < EDGE_WARNING_PX or y_px > image_info.height_px - EDGE_WARNING_PX:
            result.add_warning(
                f"Anchor is very close to the image edge (y={y_px:.0f}). "
                f"Verify nipple placement."
            )

    return result


# ─── Distance Precondition Validation ────────────────────────────────────────

def validate_distance_preconditions(
    anchor: Optional[NippleAnchor],
    target_x_px: float,
    target_y_px: float,
) -> AnchorValidationResult:
    """
    Validate all preconditions for a distance computation.

    Checks:
        ✓ anchor exists
        ✓ anchor is in valid state
        ✓ anchor has valid image info
        ✓ target point is not NaN/Inf
        ✓ PixelSpacing is available and valid

    Returns:
        AnchorValidationResult — if is_valid is False, do NOT compute distance.
    """
    result = AnchorValidationResult.ok()

    # Anchor existence
    if anchor is None:
        result.add_error(
            "No nipple anchor placed. "
            "Please click the nipple position on the image first."
        )
        return result

    # Anchor state
    if not anchor.is_valid:
        result.add_error(
            f"Nipple anchor is in invalid state: {anchor.state.value}. "
            f"Please reposition the anchor within the image."
        )
        return result

    # Image info
    info_result = validate_image_info(anchor.image_info)
    if not info_result.is_valid:
        for e in info_result.errors:
            result.add_error(e)
        return result

    # Target point
    if math.isnan(target_x_px) or math.isnan(target_y_px):
        result.add_error(
            f"Target point contains NaN values: ({target_x_px}, {target_y_px})."
        )
        return result

    if math.isinf(target_x_px) or math.isinf(target_y_px):
        result.add_error(
            f"Target point contains infinite values: ({target_x_px}, {target_y_px})."
        )
        return result

    return result


# ─── Out-of-Image Detection ─────────────────────────────────────────────────

def detect_out_of_image(
    point_px: Tuple[float, float],
    image_info: DicomImageInfo,
) -> AnchorValidationResult:
    """
    Determine if a computed point falls outside the image boundary.

    This is DISTINCT from a calculation error:
    - Out-of-image: the geometry is correct but the projection exceeds
      the available imaging field. This is clinically meaningful.
    - Calculation error: the math produced garbage (NaN, Inf, negative spacing).

    Returns:
        AnchorValidationResult with specific out-of-image messaging.
    """
    result = AnchorValidationResult.ok()
    x, y = point_px

    # First rule out calculation errors
    if math.isnan(x) or math.isnan(y):
        result.add_error(
            "Calculation error: projected position is NaN. "
            "This indicates a computation failure, not an out-of-field projection."
        )
        return result

    if math.isinf(x) or math.isinf(y):
        result.add_error(
            "Calculation error: projected position is infinite. "
            "This indicates a computation failure."
        )
        return result

    # Now check bounds — this is a legitimate out-of-image condition
    out_reasons = []

    if x < 0:
        dist_mm = abs(x) * image_info.pixel_spacing_x_mm
        out_reasons.append(
            f"left edge by {dist_mm:.1f} mm"
        )
    elif x >= image_info.width_px:
        dist_mm = (x - image_info.width_px) * image_info.pixel_spacing_x_mm
        out_reasons.append(
            f"right edge by {dist_mm:.1f} mm"
        )

    if y < 0:
        dist_mm = abs(y) * image_info.pixel_spacing_y_mm
        out_reasons.append(
            f"top edge by {dist_mm:.1f} mm"
        )
    elif y >= image_info.height_px:
        dist_mm = (y - image_info.height_px) * image_info.pixel_spacing_y_mm
        out_reasons.append(
            f"bottom edge by {dist_mm:.1f} mm"
        )

    if out_reasons:
        reasons_str = " and ".join(out_reasons)
        result.add_error(
            f"Projected nipple is outside image. "
            f"Distance exceeds image boundary ({reasons_str}). "
            f"The computed position extends beyond the available imaging field."
        )

    return result


# ─── Cross-View Consistency ──────────────────────────────────────────────────

def validate_anchor_pair(pair: AnchorPair) -> AnchorValidationResult:
    """
    Validate consistency between CC and MLO anchors of the same breast.

    Checks:
        ✓ Both anchors are for the same laterality
        ✓ Both anchors are in valid state
        ✓ Both have compatible image info

    Does NOT check distance equivalence (that's the measurement itself).
    """
    result = AnchorValidationResult.ok()

    if pair.cc_anchor is None and pair.mlo_anchor is None:
        result.add_error("No anchors placed in either view.")
        return result

    if pair.cc_anchor is None:
        result.add_warning("CC anchor not placed. Place nipple on CC view.")
        return result

    if pair.mlo_anchor is None:
        result.add_warning("MLO anchor not placed. Place nipple on MLO view.")
        return result

    # Laterality match
    cc_side = pair.cc_anchor.side
    mlo_side = pair.mlo_anchor.side
    if cc_side != mlo_side:
        result.add_error(
            f"Laterality mismatch: CC is {cc_side.value} but MLO is {mlo_side.value}. "
            f"Both views must be from the same breast."
        )

    # Both valid
    if not pair.cc_anchor.is_valid:
        result.add_error("CC anchor is not in a valid state.")
    if not pair.mlo_anchor.is_valid:
        result.add_error("MLO anchor is not in a valid state.")

    # Image info compatibility
    cc_info = pair.cc_anchor.image_info
    mlo_info = pair.mlo_anchor.image_info

    info_v1 = validate_image_info(cc_info)
    if not info_v1.is_valid:
        result.add_error(f"CC image info invalid: {info_v1.errors[0]}")

    info_v2 = validate_image_info(mlo_info)
    if not info_v2.is_valid:
        result.add_error(f"MLO image info invalid: {info_v2.errors[0]}")

    return result


# ─── Convenience: Full Pre-Computation Validation ────────────────────────────

def validate_before_computation(
    anchor: Optional[NippleAnchor],
    target_x_px: float,
    target_y_px: float,
) -> AnchorValidationResult:
    """
    Run all validations needed before computing a distance.

    This is the single entry point for pre-computation validation.
    If the result is not is_valid, do NOT proceed with the calculation.

    Order:
        1. Distance preconditions (anchor, image info, spacing)
        2. Target position (bounds, NaN, Inf)
        3. Out-of-image detection (if point is outside)

    Returns:
        Combined AnchorValidationResult.
    """
    # Step 1: Preconditions
    pre = validate_distance_preconditions(anchor, target_x_px, target_y_px)
    if not pre.is_valid:
        return pre

    # Step 2: Target position within image
    pos_result = validate_anchor_position(
        target_x_px, target_y_px, anchor.image_info
    )

    # Merge warnings (out-of-bounds becomes a warning here, not a hard stop)
    result = AnchorValidationResult.ok()
    result.warnings = pos_result.warnings[:]

    # Step 3: Out-of-image is NOT a hard error for distance computation
    # (we still compute the distance — we just flag it)
    if not pos_result.is_valid:
        ooi = detect_out_of_image(
            (target_x_px, target_y_px), anchor.image_info
        )
        if ooi.errors:
            # Distinguish: calculation error vs legitimate out-of-field
            for e in ooi.errors:
                if "Calculation error" in e:
                    result.add_error(e)
                else:
                    result.add_warning(e)

    return result
