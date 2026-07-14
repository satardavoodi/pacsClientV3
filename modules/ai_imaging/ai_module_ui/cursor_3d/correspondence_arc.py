"""
Correspondence Arc — Physically-accurate CC↔MLO lesion correspondence.

Instead of projecting a lesion to a single point in the target view, this module
computes a "correspondence arc" — a curved search band representing all physically
plausible locations where the lesion could appear.

Physical Basis:
    The breast is a 3D volume. A lesion seen in only one 2D projection has an
    unknown depth component in the orthogonal direction. The correspondence arc
    represents the geometric uncertainty inherent in this under-determined problem.

Mathematical Model:
    Let (X, Y, Z) be the 3D breast coordinate system:
        X = medial-lateral axis
        Y = posterior-anterior axis (nipple to chest wall)
        Z = cranio-caudal axis

    In CC view (vertical beam):
        - Z is collapsed → image shows (X, Y)
        - A lesion's Z position is unknown

    In MLO view (angled beam at θ from vertical):
        - The projection is (X, H) where H = Y·sin(θ) + Z·cos(θ)
        - Given only CC data, Z is free → H varies along a range

    The correspondence arc is the locus of all (X, H) points in MLO that are
    consistent with the observed (X, Y) in CC, for all plausible Z values.

Kopans' Rule:
    "The distance from the nipple to a lesion should be approximately the same
    in both views."

    This gives:  d_CC ≈ d_MLO
    where d = √(X² + Y²) in CC and d = √(X² + H²) in MLO.

    Geometrically, this means the lesion lies on a circle of radius d centered
    at the nipple in the target view.

Implementation:
    1. Compute d = distance from nipple in source view.
    2. Generate an arc of radius d in the target view.
    3. Clip the arc to:
        - Anatomically valid angle range (based on pectoral angle).
        - The breast tissue contour.
    4. Optionally weight points on the arc by likelihood (e.g., density correlation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .geometry import (
    ChestWallOrientation,
    ImageGeometry,
    LesionLocation,
    MammogramGeometry,
    NipplePosition,
    PixelSpacing,
)


@dataclass
class CorrespondenceArc:
    """
    A correspondence arc in the target view.

    This is a curved search band representing all geometrically plausible
    locations for a lesion based on its position in the source view.
    """
    # Arc center (nipple position in target view)
    center_x_px: float
    center_y_px: float
    # Arc radius (preserved distance from nipple)
    radius_mm: float
    radius_px: float
    # Arc angular extent (radians)
    start_angle_rad: float
    end_angle_rad: float
    # Arc points (pixels) after clipping to valid tissue
    arc_points_px: List[Tuple[float, float]]
    # Optional: weighted points with likelihood scores
    weighted_points: Optional[List[Tuple[float, float, float]]] = None  # (x, y, weight)
    # Best guess point (highest weight or geometric center)
    best_point_px: Optional[Tuple[float, float]] = None
    # Confidence in the correspondence (0-1)
    confidence: float = 0.5
    # Diagnostic message
    message: str = ""

    @property
    def arc_length_mm(self) -> float:
        """Total arc length in millimeters."""
        angle_span = abs(self.end_angle_rad - self.start_angle_rad)
        return self.radius_mm * angle_span

    @property
    def num_points(self) -> int:
        """Number of valid arc points."""
        return len(self.arc_points_px)


def compute_correspondence_arc(
    source_lesion: LesionLocation,
    source_geom: MammogramGeometry,
    target_geom: MammogramGeometry,
    source_view: str,
    target_view: str,
    pectoral_angle_deg: Optional[float] = None,
    breast_contour: Optional[np.ndarray] = None,
    angular_resolution_deg: float = 1.0,
    angle_margin_deg: float = 30.0,
) -> CorrespondenceArc:
    """
    Compute the correspondence arc for a lesion from source view to target view.

    Args:
        source_lesion: Lesion detected in source view.
        source_geom: Geometry of source view.
        target_geom: Geometry of target view.
        source_view: 'CC' or 'MLO'
        target_view: 'CC' or 'MLO'
        pectoral_angle_deg: Pectoral muscle angle in MLO view (if available).
        breast_contour: Breast tissue contour in target view (for clipping).
        angular_resolution_deg: Spacing between arc points (degrees).
        angle_margin_deg: Angular margin around the anatomically expected range.

    Returns:
        CorrespondenceArc object with valid arc points.

    Physical Interpretation:
        The arc radius equals the distance from nipple to lesion in the source view.
        This distance should be preserved in the target view (Kopans' Rule).

        The arc angular range is constrained by:
            - Physical anatomy (lesion must be within breast tissue).
            - View geometry (pectoral angle for MLO).
            - Image field of view.
    """
    # Step 1: Compute distance from nipple in source view (preserved radius)
    distance_mm = source_geom.compute_lesion_depth_mm(source_lesion)

    # Convert to pixels in target view
    # Approximate conversion: use average pixel spacing
    avg_spacing = (target_geom.image.pixel_spacing.x + target_geom.image.pixel_spacing.y) / 2.0
    radius_px = distance_mm / avg_spacing

    # Arc center = nipple position in target view
    center_x_px = target_geom.nipple.x_px
    center_y_px = target_geom.nipple.y_px

    # Step 2: Determine angular range for the arc
    if source_view == 'CC' and target_view == 'MLO':
        # CC → MLO projection
        start_angle_rad, end_angle_rad = _compute_cc_to_mlo_arc_range(
            source_lesion=source_lesion,
            source_geom=source_geom,
            target_geom=target_geom,
            pectoral_angle_deg=pectoral_angle_deg,
            angle_margin_deg=angle_margin_deg,
        )
    elif source_view == 'MLO' and target_view == 'CC':
        # MLO → CC projection
        start_angle_rad, end_angle_rad = _compute_mlo_to_cc_arc_range(
            source_lesion=source_lesion,
            source_geom=source_geom,
            target_geom=target_geom,
            pectoral_angle_deg=pectoral_angle_deg,
            angle_margin_deg=angle_margin_deg,
        )
    else:
        # Default: full circle (maximum uncertainty)
        start_angle_rad = 0.0
        end_angle_rad = 2.0 * math.pi

    # Step 3: Generate arc points
    angle_step_rad = math.radians(angular_resolution_deg)
    num_steps = max(1, int((end_angle_rad - start_angle_rad) / angle_step_rad))

    arc_points_px: List[Tuple[float, float]] = []
    for i in range(num_steps + 1):
        angle = start_angle_rad + i * (end_angle_rad - start_angle_rad) / num_steps
        x = center_x_px + radius_px * math.cos(angle)
        y = center_y_px + radius_px * math.sin(angle)
        arc_points_px.append((x, y))

    # Step 4: Clip arc points to breast contour
    if breast_contour is not None:
        from .breast_contour import is_point_inside_contour
        arc_points_px = [
            pt for pt in arc_points_px
            if is_point_inside_contour(pt, breast_contour)
        ]

    # Step 5: Clip to image boundaries
    arc_points_px = [
        (x, y) for x, y in arc_points_px
        if 0 <= x < target_geom.image.width_px and 0 <= y < target_geom.image.height_px
    ]

    # Step 6: Compute best guess point from valid arc samples.
    # Use centroid only as a guide, then snap to nearest arc point so the point
    # always stays on the validated arc set.
    if arc_points_px:
        avg_x = sum(x for x, y in arc_points_px) / len(arc_points_px)
        avg_y = sum(y for x, y in arc_points_px) / len(arc_points_px)
        best_point_px = min(
            arc_points_px,
            key=lambda p: (p[0] - avg_x) ** 2 + (p[1] - avg_y) ** 2,
        )
        confidence = min(1.0, len(arc_points_px) / 50.0)  # More points = higher confidence
        message = f"Correspondence arc: {len(arc_points_px)} valid points at radius {distance_mm:.1f}mm"
    else:
        best_point_px = None
        confidence = 0.0
        message = f"No valid arc points within breast contour at radius {distance_mm:.1f}mm"

    return CorrespondenceArc(
        center_x_px=center_x_px,
        center_y_px=center_y_px,
        radius_mm=distance_mm,
        radius_px=radius_px,
        start_angle_rad=start_angle_rad,
        end_angle_rad=end_angle_rad,
        arc_points_px=arc_points_px,
        best_point_px=best_point_px,
        confidence=confidence,
        message=message,
    )


def _compute_cc_to_mlo_arc_range(
    source_lesion: LesionLocation,
    source_geom: MammogramGeometry,
    target_geom: MammogramGeometry,
    pectoral_angle_deg: Optional[float],
    angle_margin_deg: float,
) -> Tuple[float, float]:
    """
    Compute the angular range for a CC → MLO correspondence arc.

    Physical reasoning:
        In CC, lesion has known (X, Y) but unknown Z.
        In MLO, the projected position H = Y·sin(θ) + Z·cos(θ) varies with Z.

        The anatomically plausible range for Z is constrained by:
            - Z_min ≈ 0 (at the level of the nipple)
            - Z_max ≈ breast_height (full superior-inferior extent)

        This maps to an angular range in MLO centered around the CC-derived
        medial-lateral position (X preserved), with vertical spread determined
        by the pectoral angle.

    Args:
        source_lesion: Lesion in CC view.
        source_geom: CC geometry.
        target_geom: MLO geometry.
        pectoral_angle_deg: Pectoral angle in MLO (if detected).
        angle_margin_deg: Additional angular margin for safety.

    Returns:
        (start_angle_rad, end_angle_rad) in target view coordinate system.
    """
    # Determine the direction toward chest wall in target view
    if target_geom.chest_wall == ChestWallOrientation.RIGHT:
        # R-MLO: chest wall on right → angle 0° points right
        chest_wall_angle_rad = 0.0
    else:
        # L-MLO: chest wall on left → angle 180° points left
        chest_wall_angle_rad = math.pi

    # Use pectoral angle to determine the anatomically expected range
    if pectoral_angle_deg is not None:
        theta_pec_rad = math.radians(pectoral_angle_deg)
    else:
        # Fallback: assume typical MLO pectoral angle (50°)
        theta_pec_rad = math.radians(50.0)

    # The arc should roughly align with the pectoral angle direction.
    # In image coords (y-down), pectoral is at TOP of MLO image.
    # Subtract theta so arc sweeps through upper quadrant (negative y).
    center_angle_rad = chest_wall_angle_rad - theta_pec_rad

    # Angular span: allow ±70° from the center (140° total arc)
    span_rad = math.radians(70.0)

    start_angle_rad = center_angle_rad - span_rad
    end_angle_rad = center_angle_rad + span_rad

    # Normalize to [0, 2π)
    start_angle_rad = start_angle_rad % (2.0 * math.pi)
    end_angle_rad = end_angle_rad % (2.0 * math.pi)

    # Handle wrap-around
    if end_angle_rad < start_angle_rad:
        end_angle_rad += 2.0 * math.pi

    return start_angle_rad, end_angle_rad


def _compute_mlo_to_cc_arc_range(
    source_lesion: LesionLocation,
    source_geom: MammogramGeometry,
    target_geom: MammogramGeometry,
    pectoral_angle_deg: Optional[float],
    angle_margin_deg: float,
) -> Tuple[float, float]:
    """
    Compute the angular range for an MLO → CC correspondence arc.

    Physical reasoning:
        In MLO, lesion has known (X, H) but Z is coupled with Y via H = Y·sin(θ) + Z·cos(θ).
        In CC, the lesion should appear at a consistent radial distance from the nipple,
        but its medial-lateral position (X) and anterior-posterior position (Y) can vary
        subject to the constraint √(X² + Y²) ≈ √(X² + H²) (preserved distance).

        The arc in CC is centered around the anatomically expected posterior-anterior axis.

    Args:
        source_lesion: Lesion in MLO view.
        source_geom: MLO geometry.
        target_geom: CC geometry.
        pectoral_angle_deg: Pectoral angle in source MLO view.
        angle_margin_deg: Additional angular margin.

    Returns:
        (start_angle_rad, end_angle_rad) in target view coordinate system.
    """
    # In CC, lesions typically distribute along the posterior-anterior axis (horizontal)
    if target_geom.chest_wall == ChestWallOrientation.RIGHT:
        # R-CC: chest wall on right
        chest_wall_angle_rad = 0.0
    else:
        # L-CC: chest wall on left
        chest_wall_angle_rad = math.pi

    # The arc should be centered toward the chest wall direction
    center_angle_rad = chest_wall_angle_rad

    # Allow ±70° from the center (140° total arc, same as CC→MLO)
    span_rad = math.radians(70.0)

    start_angle_rad = center_angle_rad - span_rad
    end_angle_rad = center_angle_rad + span_rad

    # Normalize
    start_angle_rad = start_angle_rad % (2.0 * math.pi)
    end_angle_rad = end_angle_rad % (2.0 * math.pi)

    if end_angle_rad < start_angle_rad:
        end_angle_rad += 2.0 * math.pi

    return start_angle_rad, end_angle_rad


def refine_arc_with_density_correlation(
    arc: CorrespondenceArc,
    source_lesion_patch: np.ndarray,
    target_image: np.ndarray,
    target_geom: MammogramGeometry,
    patch_size_mm: float = 20.0,
) -> CorrespondenceArc:
    """
    Refine the correspondence arc by correlating lesion density with target image.

    This is an advanced step that can reduce the uncertainty by matching the
    lesion appearance (shape, density profile) across views.

    Args:
        arc: Initial correspondence arc.
        source_lesion_patch: Cropped image patch of the lesion in source view.
        target_image: Target view image.
        target_geom: Target view geometry.
        patch_size_mm: Size of patches to extract for correlation (mm).

    Returns:
        Refined CorrespondenceArc with weighted_points and updated best_point_px.

    Algorithm:
        1. For each point on the arc, extract a patch from the target image.
        2. Compute correlation (e.g., normalized cross-correlation) with source patch.
        3. Weight each arc point by its correlation score.
        4. Select the highest-scoring point as the best guess.
    """
    if not arc.arc_points_px or source_lesion_patch is None or target_image is None:
        return arc

    # Convert patch size to pixels
    avg_spacing = (target_geom.image.pixel_spacing.x + target_geom.image.pixel_spacing.y) / 2.0
    patch_size_px = int(patch_size_mm / avg_spacing)
    half_patch = patch_size_px // 2

    # Resize source patch to target patch size
    source_patch_resized = cv2.resize(source_lesion_patch, (patch_size_px, patch_size_px))

    # Normalize source patch
    source_patch_norm = (source_patch_resized - source_patch_resized.mean()) / (source_patch_resized.std() + 1e-8)

    weighted_points: List[Tuple[float, float, float]] = []

    for x, y in arc.arc_points_px:
        # Extract patch from target image
        x_min = int(x - half_patch)
        y_min = int(y - half_patch)
        x_max = x_min + patch_size_px
        y_max = y_min + patch_size_px

        # Check boundaries
        if x_min < 0 or y_min < 0 or x_max >= target_image.shape[1] or y_max >= target_image.shape[0]:
            continue

        target_patch = target_image[y_min:y_max, x_min:x_max]

        if target_patch.shape != source_patch_resized.shape:
            continue

        # Normalize target patch
        target_patch_norm = (target_patch - target_patch.mean()) / (target_patch.std() + 1e-8)

        # Compute normalized cross-correlation
        correlation = np.sum(source_patch_norm * target_patch_norm) / (patch_size_px * patch_size_px)
        # Map correlation [-1, 1] to weight [0, 1]
        weight = (correlation + 1.0) / 2.0
        weight = max(0.0, min(1.0, weight))

        weighted_points.append((x, y, weight))

    if not weighted_points:
        return arc

    # Sort by weight
    weighted_points.sort(key=lambda pt: pt[2], reverse=True)

    # Best point = highest weight
    best_x, best_y, best_weight = weighted_points[0]
    best_point_px = (best_x, best_y)

    # Update confidence based on correlation scores
    avg_weight = sum(w for _, _, w in weighted_points) / len(weighted_points)
    confidence = min(1.0, (best_weight + avg_weight) / 2.0)

    # Update arc
    arc.weighted_points = weighted_points
    arc.best_point_px = best_point_px
    arc.confidence = confidence
    arc.message += f" | Density correlation: best_score={best_weight:.2f}"

    return arc


# Import cv2 for patch correlation
try:
    import cv2
except ImportError:
    cv2 = None
