"""
Pectoral Line Anchor — User-defined chest wall reference for mammography.

The pectoral line is the anatomical boundary between the chest wall and
breast tissue. In MLO views it is typically the visible pectoral muscle edge.
In CC views it corresponds to the posterior image boundary.

This module replaces the automatic pectoral detection AND the fixed 45-degree
assumption. The user manually defines the pectoral line by placing two points
on the image. All projection geometry derives from this line.

Coordinate Convention:
    - Pixel coordinates: origin at top-left, x-right, y-down.
    - Physical coordinates: origin at top-left, same axes, units in mm.
    - The direction vector points from start to end (user-defined orientation).
    - The normal vector points INTO the breast tissue (away from the chest wall).

Mathematical Definitions:
    Given two points P1 = (x1, y1) and P2 = (x2, y2) in mm:

    Direction vector D = (P2 - P1) / |P2 - P1|
    Normal vector N = perpendicular to D, pointing into breast tissue.

    For a RIGHT breast (chest wall on image-right):
        N points to the LEFT (negative x direction).
    For a LEFT breast (chest wall on image-left):
        N points to the RIGHT (positive x direction).

    Pectoral angle θ from vertical:
        θ = arctan2(|Dx|, |Dy|) in degrees.
        Typical range for MLO: 30° to 60°.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Tuple

from .anchor_nipple import BreastSide, DicomImageInfo, MammogramView


# ─── Data Model ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PectoralLineAnchor:
    """
    Immutable pectoral line defined by two user-placed points.

    All coordinates exist in both pixel and physical (mm) domains.
    Physical coordinates are computed from DICOM PixelSpacing at construction.

    Use replace() from dataclasses to create modified copies.
    """

    # ── Endpoint 1 (pixel) ──
    x1_px: float
    y1_px: float
    # ── Endpoint 2 (pixel) ──
    x2_px: float
    y2_px: float

    # ── Endpoint 1 (mm) ──
    x1_mm: float
    y1_mm: float
    # ── Endpoint 2 (mm) ──
    x2_mm: float
    y2_mm: float

    # ── Metadata ──
    side: BreastSide
    view: MammogramView
    image_info: DicomImageInfo

    # ── Derived geometry (computed at construction) ──
    # Direction vector (unit, in mm space)
    direction_x: float = 0.0
    direction_y: float = 0.0
    # Normal vector (unit, pointing INTO breast tissue)
    normal_x: float = 0.0
    normal_y: float = 0.0
    # Angle from vertical in degrees (0° = vertical, 90° = horizontal)
    angle_from_vertical_deg: float = 0.0
    # Line length in mm
    length_mm: float = 0.0

    @classmethod
    def from_pixels(
        cls,
        x1_px: float,
        y1_px: float,
        x2_px: float,
        y2_px: float,
        side: BreastSide,
        view: MammogramView,
        image_info: DicomImageInfo,
    ) -> "PectoralLineAnchor":
        """
        Construct a PectoralLineAnchor from pixel coordinates.

        Validates inputs and computes all derived geometry.

        Args:
            x1_px, y1_px: First endpoint in pixel coordinates.
            x2_px, y2_px: Second endpoint in pixel coordinates.
            side: Breast laterality (LEFT or RIGHT).
            view: Mammogram view (CC or MLO).
            image_info: DICOM image metadata with PixelSpacing.

        Returns:
            Fully initialized PectoralLineAnchor.

        Raises:
            ValueError: If coordinates are NaN/Inf or line is degenerate.
        """
        # ── Validate inputs ──
        for val, name in [
            (x1_px, "x1_px"), (y1_px, "y1_px"),
            (x2_px, "x2_px"), (y2_px, "y2_px"),
        ]:
            if math.isnan(val):
                raise ValueError(f"Pectoral line coordinate {name} is NaN.")
            if math.isinf(val):
                raise ValueError(f"Pectoral line coordinate {name} is infinite.")

        # ── Convert to mm ──
        sp_x = image_info.pixel_spacing_x_mm
        sp_y = image_info.pixel_spacing_y_mm

        x1_mm = x1_px * sp_x
        y1_mm = y1_px * sp_y
        x2_mm = x2_px * sp_x
        y2_mm = y2_px * sp_y

        # ── Compute direction vector in mm space ──
        dx_mm = x2_mm - x1_mm
        dy_mm = y2_mm - y1_mm
        length_mm = math.sqrt(dx_mm * dx_mm + dy_mm * dy_mm)

        if length_mm < 1e-9:
            raise ValueError(
                "Pectoral line is degenerate (zero length). "
                "Place two distinct points."
            )

        # Unit direction
        dir_x = dx_mm / length_mm
        dir_y = dy_mm / length_mm

        # ── Compute normal vector (perpendicular, into breast tissue) ──
        # The perpendicular in 2D: rotate direction by 90° CW or CCW.
        # Choose the direction that points AWAY from the chest wall.
        #
        # For RIGHT breast: chest wall is on the RIGHT side of the image.
        #   Normal should point LEFT (negative x) → into breast tissue.
        # For LEFT breast: chest wall is on the LEFT side of the image.
        #   Normal should point RIGHT (positive x) → into breast tissue.

        # CW rotation of (dir_x, dir_y) → (dir_y, -dir_x)
        # CCW rotation of (dir_x, dir_y) → (-dir_y, dir_x)

        # We pick the rotation whose x-component matches the expected direction.
        norm_cw_x = dir_y
        norm_cw_y = -dir_x

        if side == BreastSide.RIGHT:
            # Normal should point left (negative x)
            if norm_cw_x <= 0:
                norm_x, norm_y = norm_cw_x, norm_cw_y
            else:
                norm_x, norm_y = -norm_cw_x, -norm_cw_y
        else:
            # Normal should point right (positive x)
            if norm_cw_x >= 0:
                norm_x, norm_y = norm_cw_x, norm_cw_y
            else:
                norm_x, norm_y = -norm_cw_x, -norm_cw_y

        # ── Compute angle from vertical ──
        # Vertical is the y-axis direction (0, 1) in image coords (y-down).
        # Angle between direction vector and vertical:
        #   cos(θ) = |dir · (0,1)| = |dir_y|
        #   θ = arccos(|dir_y|) → degrees
        # Equivalently: θ = arctan2(|dir_x|, |dir_y|)
        angle_from_vertical = math.degrees(math.atan2(abs(dir_x), abs(dir_y)))

        return cls(
            x1_px=x1_px, y1_px=y1_px,
            x2_px=x2_px, y2_px=y2_px,
            x1_mm=x1_mm, y1_mm=y1_mm,
            x2_mm=x2_mm, y2_mm=y2_mm,
            side=side, view=view, image_info=image_info,
            direction_x=dir_x, direction_y=dir_y,
            normal_x=norm_x, normal_y=norm_y,
            angle_from_vertical_deg=angle_from_vertical,
            length_mm=length_mm,
        )

    # ── Properties ──

    @property
    def start_px(self) -> Tuple[float, float]:
        """Start point in pixels."""
        return (self.x1_px, self.y1_px)

    @property
    def end_px(self) -> Tuple[float, float]:
        """End point in pixels."""
        return (self.x2_px, self.y2_px)

    @property
    def start_mm(self) -> Tuple[float, float]:
        """Start point in mm."""
        return (self.x1_mm, self.y1_mm)

    @property
    def end_mm(self) -> Tuple[float, float]:
        """End point in mm."""
        return (self.x2_mm, self.y2_mm)

    @property
    def midpoint_px(self) -> Tuple[float, float]:
        """Midpoint in pixels."""
        return ((self.x1_px + self.x2_px) / 2.0, (self.y1_px + self.y2_px) / 2.0)

    @property
    def midpoint_mm(self) -> Tuple[float, float]:
        """Midpoint in mm."""
        return ((self.x1_mm + self.x2_mm) / 2.0, (self.y1_mm + self.y2_mm) / 2.0)

    @property
    def direction(self) -> Tuple[float, float]:
        """Unit direction vector in mm space."""
        return (self.direction_x, self.direction_y)

    @property
    def normal(self) -> Tuple[float, float]:
        """Unit normal vector pointing into breast tissue."""
        return (self.normal_x, self.normal_y)

    @property
    def is_valid(self) -> bool:
        """True if the line has valid geometry."""
        return self.length_mm > 0.0

    # ── Geometric Operations ──

    def signed_distance_to_point_mm(self, x_mm: float, y_mm: float) -> float:
        """
        Signed perpendicular distance from the line to a point (in mm).

        Positive = point is on the normal side (inside breast tissue).
        Negative = point is on the chest wall side.

        Mathematical derivation:
            The signed distance from point P to line (P1, D) is:
                d = (P - P1) · N
            where N is the unit normal vector.
        """
        # Vector from line start to point
        vx = x_mm - self.x1_mm
        vy = y_mm - self.y1_mm
        # Dot product with normal
        return vx * self.normal_x + vy * self.normal_y

    def signed_distance_to_point_px(self, x_px: float, y_px: float) -> float:
        """
        Signed perpendicular distance from the line to a point (in mm),
        given pixel coordinates.
        """
        x_mm = x_px * self.image_info.pixel_spacing_x_mm
        y_mm = y_px * self.image_info.pixel_spacing_y_mm
        return self.signed_distance_to_point_mm(x_mm, y_mm)

    def project_point_onto_line_mm(
        self, x_mm: float, y_mm: float
    ) -> Tuple[float, float]:
        """
        Project a point onto the pectoral line (closest point on line, in mm).

        Returns the projected point coordinates in mm.

        Mathematical derivation:
            Projection of P onto line (P1, D):
                t = (P - P1) · D
                P_proj = P1 + t × D
        """
        vx = x_mm - self.x1_mm
        vy = y_mm - self.y1_mm
        t = vx * self.direction_x + vy * self.direction_y
        proj_x = self.x1_mm + t * self.direction_x
        proj_y = self.y1_mm + t * self.direction_y
        return (proj_x, proj_y)

    def is_point_within_breast(self, x_px: float, y_px: float) -> bool:
        """
        Check if a point is on the breast tissue side of the pectoral line.

        Returns True if the point is in front of (breast-side of) the line.
        """
        return self.signed_distance_to_point_px(x_px, y_px) > 0.0

    def clip_angle_range(
        self, center_px: Tuple[float, float], radius_px: float
    ) -> Tuple[float, float]:
        """
        Compute the angular range of an arc (centered at center_px with given
        radius) that lies on the breast-tissue side of the pectoral line.

        Returns (start_angle_rad, end_angle_rad) in image coordinates
        (0 = right, π/2 = down, measured counter-clockwise).

        This is used to clip correspondence arcs so they don't extend
        behind the chest wall.
        """
        cx, cy = center_px

        # Convert pectoral line to pixel space for intersection
        sp_x = self.image_info.pixel_spacing_x_mm
        sp_y = self.image_info.pixel_spacing_y_mm

        # Line direction in pixel space (unnormalized)
        ldx = (self.x2_mm - self.x1_mm) / sp_x
        ldy = (self.y2_mm - self.y1_mm) / sp_y

        # Find intersection of the arc circle with the pectoral line.
        # Circle: (x - cx)² + (y - cy)² = r²
        # Line parametric: (x1_px + t*ldx, y1_px + t*ldy)
        #
        # Substitute into circle equation and solve quadratic for t.
        p1x = self.x1_px - cx
        p1y = self.y1_px - cy

        a = ldx * ldx + ldy * ldy
        b = 2.0 * (p1x * ldx + p1y * ldy)
        c = p1x * p1x + p1y * p1y - radius_px * radius_px

        discriminant = b * b - 4.0 * a * c

        if discriminant < 0 or a < 1e-12:
            # No intersection — entire arc is either valid or invalid.
            # Test center's breast-tissue side:
            if self.is_point_within_breast(cx, cy):
                # Arc center is on the breast side → full arc is valid.
                return (0.0, 2.0 * math.pi)
            else:
                # Arc center is behind chest wall → no valid arc region.
                return (0.0, 0.0)

        sqrt_disc = math.sqrt(discriminant)
        t1 = (-b - sqrt_disc) / (2.0 * a)
        t2 = (-b + sqrt_disc) / (2.0 * a)

        # Intersection points relative to circle center
        ix1 = p1x + t1 * ldx
        iy1 = p1y + t1 * ldy
        ix2 = p1x + t2 * ldx
        iy2 = p1y + t2 * ldy

        # Angles of intersection points
        angle1 = math.atan2(iy1, ix1)
        angle2 = math.atan2(iy2, ix2)

        # Determine which arc segment is on the breast side.
        # Test midpoint of each segment.
        mid_angle = (angle1 + angle2) / 2.0
        test_x = cx + radius_px * math.cos(mid_angle)
        test_y = cy + radius_px * math.sin(mid_angle)

        if self.is_point_within_breast(test_x, test_y):
            # The segment from angle1 to angle2 (shorter arc) is valid
            return (angle1, angle2)
        else:
            # The opposite segment is valid
            return (angle2, angle1 + 2.0 * math.pi)
