"""
Quadrant Consistency — Anatomical quadrant-based geometric constraint.

Mammography quadrants divide the breast into five clinically standard regions:
    UO = Upper Outer
    UI = Upper Inner
    LO = Lower Outer
    LI = Lower Inner
    C  = Central (retroareolar / subareolar)

Quadrant Assignment:
    Given a nipple anchor (defines the reference center) and optionally a
    pectoral line (defines the axis system), each lesion is assigned to the
    quadrant containing its center.

    CC View:
        The nipple divides the breast into medial/lateral (left/right of nipple)
        and upper/lower (above/below nipple). "Outer" = lateral, "Inner" = medial.

    MLO View:
        The nipple still divides medial/lateral along the pectoral line's normal.
        Upper/Lower is determined relative to the nipple along the perpendicular
        to the pectoral line direction.

Quadrant Consistency Penalty:
    When matching a CC lesion to an MLO lesion, quadrant information provides
    a geometric constraint:
    - Same quadrant → 0 penalty
    - Adjacent quadrant → small penalty
    - Opposite quadrant → large penalty (anatomically unlikely)

    The penalty is a soft constraint (not a hard veto) because:
    - Quadrant boundaries are approximate.
    - Compression changes apparent position.
    - Lesions near boundaries can shift between views.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from .anchor_nipple import BreastSide, MammogramView, NippleAnchor
from .pectoral_line_anchor import PectoralLineAnchor


# ─── Quadrant Definitions ────────────────────────────────────────────────────

# Standard mammography quadrants
QUADRANT_UO = "UO"  # Upper Outer
QUADRANT_UI = "UI"  # Upper Inner
QUADRANT_LO = "LO"  # Lower Outer
QUADRANT_LI = "LI"  # Lower Inner
QUADRANT_C = "C"    # Central (near nipple, within ~20mm radius)

# Central zone radius in mm (retroareolar region)
CENTRAL_ZONE_RADIUS_MM = 20.0


# ─── Quadrant Penalty Matrix ────────────────────────────────────────────────

# Penalty for matching lesions in different quadrants.
# Key = (cc_quadrant, mlo_quadrant), Value = penalty [0, 1].
# Same quadrant = 0, adjacent = 0.3, opposite = 1.0, central = 0.1 (always mild).

_PENALTY_MATRIX = {
    # Same quadrant → zero penalty
    (QUADRANT_UO, QUADRANT_UO): 0.0,
    (QUADRANT_UI, QUADRANT_UI): 0.0,
    (QUADRANT_LO, QUADRANT_LO): 0.0,
    (QUADRANT_LI, QUADRANT_LI): 0.0,
    (QUADRANT_C, QUADRANT_C): 0.0,
    # Adjacent quadrants → small penalty
    (QUADRANT_UO, QUADRANT_UI): 0.3,
    (QUADRANT_UI, QUADRANT_UO): 0.3,
    (QUADRANT_UO, QUADRANT_LO): 0.3,
    (QUADRANT_LO, QUADRANT_UO): 0.3,
    (QUADRANT_UI, QUADRANT_LI): 0.3,
    (QUADRANT_LI, QUADRANT_UI): 0.3,
    (QUADRANT_LO, QUADRANT_LI): 0.3,
    (QUADRANT_LI, QUADRANT_LO): 0.3,
    # Opposite quadrants → high penalty
    (QUADRANT_UO, QUADRANT_LI): 1.0,
    (QUADRANT_LI, QUADRANT_UO): 1.0,
    (QUADRANT_UI, QUADRANT_LO): 1.0,
    (QUADRANT_LO, QUADRANT_UI): 1.0,
    # Central → any: mild penalty (central can project anywhere nearby)
    (QUADRANT_C, QUADRANT_UO): 0.1,
    (QUADRANT_C, QUADRANT_UI): 0.1,
    (QUADRANT_C, QUADRANT_LO): 0.1,
    (QUADRANT_C, QUADRANT_LI): 0.1,
    (QUADRANT_UO, QUADRANT_C): 0.1,
    (QUADRANT_UI, QUADRANT_C): 0.1,
    (QUADRANT_LO, QUADRANT_C): 0.1,
    (QUADRANT_LI, QUADRANT_C): 0.1,
}


def quadrant_penalty(cc_quadrant: str, mlo_quadrant: str) -> float:
    """
    Look up the penalty for assigning a CC lesion in one quadrant
    to an MLO lesion in another quadrant.

    Returns:
        Penalty value in [0, 1]. Zero means perfectly consistent.
    """
    return _PENALTY_MATRIX.get((cc_quadrant, mlo_quadrant), 0.5)


# ─── Quadrant Assignment ─────────────────────────────────────────────────────


def assign_quadrant_cc(
    lesion_x_mm: float,
    lesion_y_mm: float,
    nipple_x_mm: float,
    nipple_y_mm: float,
    side: BreastSide,
) -> str:
    """
    Assign an anatomical quadrant to a lesion in a CC view.

    In CC view:
        - Horizontal axis = medial-lateral (inner-outer)
        - Vertical axis = superior-inferior (upper-lower)
        - Nipple is the reference center

    Coordinate system (image space, y-down):
        - For RIGHT breast: "outer" = LEFT side of image (toward axilla)
        - For LEFT breast: "outer" = RIGHT side of image (toward axilla)
        - "upper" = ABOVE nipple (negative dy in image coords)

    Args:
        lesion_x_mm, lesion_y_mm: Lesion center in mm.
        nipple_x_mm, nipple_y_mm: Nipple position in mm.
        side: Breast laterality.

    Returns:
        Quadrant string: 'UO', 'UI', 'LO', 'LI', or 'C'.
    """
    dx = lesion_x_mm - nipple_x_mm
    dy = lesion_y_mm - nipple_y_mm
    distance = math.sqrt(dx * dx + dy * dy)

    # Central zone check
    if distance <= CENTRAL_ZONE_RADIUS_MM:
        return QUADRANT_C

    # Determine upper/lower (y-axis in image coords: negative = above = upper)
    is_upper = dy < 0

    # Determine outer/inner based on laterality
    # RIGHT breast: outer = more negative x (toward left side of image = axilla)
    # LEFT breast: outer = more positive x (toward right side of image = axilla)
    if side == BreastSide.RIGHT:
        is_outer = dx < 0
    else:
        is_outer = dx > 0

    if is_upper and is_outer:
        return QUADRANT_UO
    elif is_upper and not is_outer:
        return QUADRANT_UI
    elif not is_upper and is_outer:
        return QUADRANT_LO
    else:
        return QUADRANT_LI


def assign_quadrant_mlo(
    lesion_x_mm: float,
    lesion_y_mm: float,
    nipple_x_mm: float,
    nipple_y_mm: float,
    side: BreastSide,
    pectoral_line: Optional[PectoralLineAnchor] = None,
) -> str:
    """
    Assign an anatomical quadrant to a lesion in an MLO view.

    In MLO view:
        - The pectoral line defines the "posterior" direction.
        - "Depth" = perpendicular distance from pectoral line (into breast).
        - "Along pectoral" = superior-inferior direction.
        - Medial-lateral is partially collapsed but preserved at nipple level.

    Without a pectoral line:
        Falls back to a simplified model similar to CC assignment.

    With a pectoral line:
        - The line's direction defines superior-inferior.
        - The line's normal defines the depth axis.
        - Upper/lower is determined by position along the pectoral direction
          relative to the nipple.

    Args:
        lesion_x_mm, lesion_y_mm: Lesion center in mm.
        nipple_x_mm, nipple_y_mm: Nipple position in mm.
        side: Breast laterality.
        pectoral_line: Optional user-defined pectoral line.

    Returns:
        Quadrant string: 'UO', 'UI', 'LO', 'LI', or 'C'.
    """
    dx = lesion_x_mm - nipple_x_mm
    dy = lesion_y_mm - nipple_y_mm
    distance = math.sqrt(dx * dx + dy * dy)

    # Central zone check
    if distance <= CENTRAL_ZONE_RADIUS_MM:
        return QUADRANT_C

    if pectoral_line is None:
        # Fallback: use simplified assignment (same logic as CC)
        return assign_quadrant_cc(
            lesion_x_mm, lesion_y_mm,
            nipple_x_mm, nipple_y_mm,
            side,
        )

    # ── With pectoral line: use anatomical axes ──

    # Project lesion onto pectoral line direction to get "along-pectoral" component.
    # This corresponds to the superior-inferior axis in MLO.
    dir_x = pectoral_line.direction_x
    dir_y = pectoral_line.direction_y
    norm_x = pectoral_line.normal_x
    norm_y = pectoral_line.normal_y

    # Component along pectoral direction (superior = toward line start = negative t)
    t_along = dx * dir_x + dy * dir_y

    # Component perpendicular to pectoral (depth into breast = positive)
    t_perp = dx * norm_x + dy * norm_y

    # In MLO:
    # "Upper" = toward the superior end of the pectoral line (negative t_along,
    #           because pectoral line typically runs top-to-bottom)
    # "Outer" = further from chest wall (larger perpendicular depth)
    #           for MLO this corresponds to the lateral tissue.

    # The pectoral direction typically points downward (positive dir_y in image).
    # "Upper" = against the direction = negative t_along.
    is_upper = t_along < 0

    # "Outer" in MLO: the lateral tissue is further from the pectoral line.
    # For both sides, "outer" = larger depth (more anterior).
    # The threshold is the nipple's own depth.
    nipple_depth = pectoral_line.signed_distance_to_point_mm(nipple_x_mm, nipple_y_mm)
    lesion_depth = pectoral_line.signed_distance_to_point_mm(lesion_x_mm, lesion_y_mm)

    # In MLO, "outer" tissue tends to be at similar or greater depth than nipple
    # and above the nipple horizontally. But the mapping is imperfect.
    # We use a simplified heuristic: outer = same side as in CC.
    if side == BreastSide.RIGHT:
        is_outer = dx < 0
    else:
        is_outer = dx > 0

    if is_upper and is_outer:
        return QUADRANT_UO
    elif is_upper and not is_outer:
        return QUADRANT_UI
    elif not is_upper and is_outer:
        return QUADRANT_LO
    else:
        return QUADRANT_LI
