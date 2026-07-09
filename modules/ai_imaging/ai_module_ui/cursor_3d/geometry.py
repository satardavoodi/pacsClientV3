"""
Mammogram Geometry — Physical-space (mm) calculations for mammography.

All distances and coordinates in this module are expressed in millimeters
unless explicitly marked with a _px suffix.

Key anatomical assumptions:
    - The chest wall is the posterior edge of the mammogram image.
    - The nipple is the anterior-most point of the breast tissue.
    - The Posterior Nipple Line (PNL) is perpendicular to the chest wall.
    - Lesion depth = perpendicular distance from nipple along PNL direction.
    - This depth is approximately preserved between CC and MLO views (Kopans' Rule).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class ChestWallOrientation(Enum):
    """Which image edge represents the chest wall."""
    RIGHT = "right"   # R breast standard: chest wall on the right edge
    LEFT = "left"     # L breast standard: chest wall on the left edge


@dataclass
class PixelSpacing:
    """DICOM pixel spacing in mm/pixel."""
    x: float  # column spacing (mm per pixel horizontally)
    y: float  # row spacing (mm per pixel vertically)

    def is_valid(self) -> bool:
        return self.x > 0 and self.y > 0


@dataclass
class ImageGeometry:
    """Physical geometry of a single mammogram image."""
    width_px: int
    height_px: int
    pixel_spacing: PixelSpacing

    @property
    def width_mm(self) -> float:
        return self.width_px * self.pixel_spacing.x

    @property
    def height_mm(self) -> float:
        return self.height_px * self.pixel_spacing.y

    def px_to_mm(self, x_px: float, y_px: float) -> Tuple[float, float]:
        """Convert pixel coordinates to millimeters from image origin."""
        return (x_px * self.pixel_spacing.x, y_px * self.pixel_spacing.y)

    def mm_to_px(self, x_mm: float, y_mm: float) -> Tuple[float, float]:
        """Convert millimeter coordinates to pixel coordinates."""
        return (x_mm / self.pixel_spacing.x, y_mm / self.pixel_spacing.y)


@dataclass
class NipplePosition:
    """Nipple position in both pixel and physical coordinates."""
    x_px: float
    y_px: float
    x_mm: float = 0.0
    y_mm: float = 0.0
    detected: bool = False  # True if detected from image data, False if estimated

    @classmethod
    def from_pixels(cls, x_px: float, y_px: float, spacing: PixelSpacing,
                    detected: bool = False) -> "NipplePosition":
        return cls(
            x_px=x_px, y_px=y_px,
            x_mm=x_px * spacing.x, y_mm=y_px * spacing.y,
            detected=detected,
        )


@dataclass
class LesionLocation:
    """A lesion bounding box in both pixel and physical (mm) coordinates."""
    # Pixel coordinates [x1, y1, x2, y2]
    x1_px: float
    y1_px: float
    x2_px: float
    y2_px: float
    # Physical coordinates (mm from image origin)
    x1_mm: float = 0.0
    y1_mm: float = 0.0
    x2_mm: float = 0.0
    y2_mm: float = 0.0
    # Detection score
    score: float = 0.5

    @classmethod
    def from_pixel_box(cls, box: list, spacing: PixelSpacing, score: float = 0.5) -> "LesionLocation":
        x1, y1, x2, y2 = box
        return cls(
            x1_px=x1, y1_px=y1, x2_px=x2, y2_px=y2,
            x1_mm=x1 * spacing.x, y1_mm=y1 * spacing.y,
            x2_mm=x2 * spacing.x, y2_mm=y2 * spacing.y,
            score=score,
        )

    @property
    def center_px(self) -> Tuple[float, float]:
        return ((self.x1_px + self.x2_px) / 2.0, (self.y1_px + self.y2_px) / 2.0)

    @property
    def center_mm(self) -> Tuple[float, float]:
        return ((self.x1_mm + self.x2_mm) / 2.0, (self.y1_mm + self.y2_mm) / 2.0)

    @property
    def width_mm(self) -> float:
        return abs(self.x2_mm - self.x1_mm)

    @property
    def height_mm(self) -> float:
        return abs(self.y2_mm - self.y1_mm)

    def to_pixel_box(self) -> list:
        return [self.x1_px, self.y1_px, self.x2_px, self.y2_px]


@dataclass
class MammogramGeometry:
    """
    Complete geometric description of a single mammogram view.

    Encapsulates the image geometry, nipple position, chest wall orientation,
    and provides methods for computing physical distances.
    """
    image: ImageGeometry
    nipple: NipplePosition
    chest_wall: ChestWallOrientation
    laterality: str  # 'R' or 'L'
    view_position: str  # 'CC' or 'MLO'

    def compute_lesion_depth_mm(self, lesion: LesionLocation) -> float:
        """
        Compute the perpendicular distance from the nipple to the lesion center,
        measured along the direction normal to the chest wall (the PNL direction).

        In standard mammography display:
            - The chest wall is a vertical edge (left or right).
            - The PNL is horizontal (perpendicular to chest wall).
            - Lesion depth = horizontal distance from nipple to lesion center, in mm.

        This is the key measurement that is preserved between CC and MLO views.

        Returns:
            Depth in millimeters (always >= 0).
        """
        lesion_cx_mm = lesion.center_mm[0]
        nipple_x_mm = self.nipple.x_mm
        return abs(lesion_cx_mm - nipple_x_mm)

    def compute_lesion_height_mm(self, lesion: LesionLocation) -> float:
        """
        Compute the vertical distance from the nipple to the lesion center (mm).

        This is the component along the chest wall direction.
        In CC view this encodes medial/lateral position.
        In MLO view this encodes superior/inferior position.
        """
        lesion_cy_mm = lesion.center_mm[1]
        nipple_y_mm = self.nipple.y_mm
        return lesion_cy_mm - nipple_y_mm  # signed: positive = inferior

    def depth_direction_sign(self) -> int:
        """
        Returns +1 or -1 indicating which direction from the nipple is 'deeper'
        (toward the chest wall).

        R breast: chest wall on right → deeper = positive x
        L breast: chest wall on left → deeper = negative x
        """
        if self.chest_wall == ChestWallOrientation.RIGHT:
            return 1  # R breast: depth increases to the right
        else:
            return -1  # L breast: depth increases to the left

    def max_available_depth_mm(self) -> float:
        """
        Maximum available breast depth in this image (nipple to chest wall edge).

        Used for out-of-field validation.
        """
        if self.chest_wall == ChestWallOrientation.RIGHT:
            # Chest wall on right edge → max depth = right_edge_mm - nipple_x_mm
            return self.image.width_mm - self.nipple.x_mm
        else:
            # Chest wall on left edge → max depth = nipple_x_mm - left_edge_mm
            return self.nipple.x_mm

    def project_depth_to_pixel_x(self, depth_mm: float) -> float:
        """
        Given a lesion depth (mm from nipple along PNL), compute the pixel x coordinate.

        Args:
            depth_mm: The perpendicular distance from nipple in mm.

        Returns:
            x coordinate in pixels.
        """
        direction = self.depth_direction_sign()
        x_mm = self.nipple.x_mm + direction * depth_mm
        x_px = x_mm / self.image.pixel_spacing.x
        return x_px

    def is_depth_within_field(self, depth_mm: float) -> bool:
        """Check if a given depth (mm) falls within the imaging field."""
        return depth_mm <= self.max_available_depth_mm()
