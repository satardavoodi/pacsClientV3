"""
Anchor Nipple — Data model for mammography nipple anchor system.

This module defines the core data structures for the nipple anchor localization
system. Each mammography image (CC or MLO) has exactly ONE nipple anchor that
serves as the anatomical reference point for all distance measurements.

All coordinates are maintained in both pixel and physical (mm) domains.
Physical coordinates are computed from DICOM PixelSpacing.

Coordinate Convention:
    - Pixel coordinates: origin at top-left, x-right, y-down.
    - Physical coordinates: origin at top-left, same axes, units in mm.
    - Physical = Pixel × PixelSpacing (per axis).

Design:
    The NippleAnchor is the single source of truth for the nipple position.
    It is immutable after creation (use replace() to create a modified copy).
    All distance/arc calculations derive from this anchor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Tuple


class MammogramView(Enum):
    """Standard mammography projection views."""
    CC = "CC"    # Cranio-Caudal
    MLO = "MLO"  # Medio-Lateral Oblique


class BreastSide(Enum):
    """Breast laterality."""
    LEFT = "L"
    RIGHT = "R"


class AnchorState(Enum):
    """State of the nipple anchor."""
    EMPTY = "empty"            # No anchor placed
    PLACED = "placed"          # Anchor placed, valid
    INVALID = "invalid"        # Anchor placed but validation failed
    OUT_OF_IMAGE = "out_of_image"  # Anchor coordinates outside image bounds


@dataclass(frozen=True)
class DicomImageInfo:
    """
    DICOM metadata required for physical coordinate computation.

    All fields are validated at construction time.
    """
    # Image dimensions
    width_px: int
    height_px: int
    # Pixel spacing in mm/pixel: (row_spacing, col_spacing)
    # DICOM convention: PixelSpacing[0] = row spacing (y), PixelSpacing[1] = col spacing (x)
    pixel_spacing_x_mm: float  # Column spacing (mm per pixel, horizontal)
    pixel_spacing_y_mm: float  # Row spacing (mm per pixel, vertical)
    # Orientation metadata
    laterality: BreastSide
    view: MammogramView
    # Optional DICOM tags
    image_orientation_patient: Optional[Tuple[float, ...]] = None
    image_position_patient: Optional[Tuple[float, float, float]] = None
    # Series identification
    series_uid: Optional[str] = None
    sop_instance_uid: Optional[str] = None

    def __post_init__(self):
        """Validate all fields at construction."""
        if self.width_px <= 0:
            raise ValueError(f"Image width must be > 0, got {self.width_px}")
        if self.height_px <= 0:
            raise ValueError(f"Image height must be > 0, got {self.height_px}")
        if self.pixel_spacing_x_mm <= 0:
            raise ValueError(
                f"Pixel spacing X must be > 0, got {self.pixel_spacing_x_mm}"
            )
        if self.pixel_spacing_y_mm <= 0:
            raise ValueError(
                f"Pixel spacing Y must be > 0, got {self.pixel_spacing_y_mm}"
            )
        if math.isnan(self.pixel_spacing_x_mm) or math.isinf(self.pixel_spacing_x_mm):
            raise ValueError(
                f"Pixel spacing X is NaN or Inf: {self.pixel_spacing_x_mm}"
            )
        if math.isnan(self.pixel_spacing_y_mm) or math.isinf(self.pixel_spacing_y_mm):
            raise ValueError(
                f"Pixel spacing Y is NaN or Inf: {self.pixel_spacing_y_mm}"
            )

    @property
    def width_mm(self) -> float:
        """Physical image width in millimeters."""
        return self.width_px * self.pixel_spacing_x_mm

    @property
    def height_mm(self) -> float:
        """Physical image height in millimeters."""
        return self.height_px * self.pixel_spacing_y_mm

    def pixel_to_mm(self, x_px: float, y_px: float) -> Tuple[float, float]:
        """
        Convert pixel coordinates to physical millimeter coordinates.

        Args:
            x_px: Horizontal pixel coordinate (column index).
            y_px: Vertical pixel coordinate (row index).

        Returns:
            (x_mm, y_mm): Physical position in millimeters from image origin.

        Mathematical basis:
            x_mm = x_px × pixel_spacing_x_mm
            y_mm = y_px × pixel_spacing_y_mm
        """
        return (x_px * self.pixel_spacing_x_mm, y_px * self.pixel_spacing_y_mm)

    def mm_to_pixel(self, x_mm: float, y_mm: float) -> Tuple[float, float]:
        """
        Convert physical millimeter coordinates to pixel coordinates.

        Args:
            x_mm: Horizontal physical coordinate (mm).
            y_mm: Vertical physical coordinate (mm).

        Returns:
            (x_px, y_px): Pixel coordinates.

        Mathematical basis:
            x_px = x_mm / pixel_spacing_x_mm
            y_px = y_mm / pixel_spacing_y_mm
        """
        return (x_mm / self.pixel_spacing_x_mm, y_mm / self.pixel_spacing_y_mm)

    def is_inside(self, x_px: float, y_px: float) -> bool:
        """Check if pixel coordinates are within image bounds."""
        return 0.0 <= x_px < self.width_px and 0.0 <= y_px < self.height_px


@dataclass(frozen=True)
class NippleAnchor:
    """
    A nipple anchor point on a mammography image.

    This is the fundamental reference point for all measurements.
    Immutable by design — use replace() to create modified copies.

    Attributes:
        x_px: Horizontal pixel coordinate of nipple.
        y_px: Vertical pixel coordinate of nipple.
        x_mm: Horizontal physical coordinate (mm from image origin).
        y_mm: Vertical physical coordinate (mm from image origin).
        image_info: DICOM image metadata for this anchor's image.
        state: Current validation state of the anchor.
    """
    x_px: float
    y_px: float
    x_mm: float
    y_mm: float
    image_info: DicomImageInfo
    state: AnchorState = AnchorState.PLACED

    @classmethod
    def create(
        cls,
        x_px: float,
        y_px: float,
        image_info: DicomImageInfo,
    ) -> "NippleAnchor":
        """
        Create a NippleAnchor from pixel coordinates with automatic mm conversion.

        This is the primary factory method. Physical coordinates are computed
        from the image's PixelSpacing.

        Args:
            x_px: Nipple pixel x-coordinate (column).
            y_px: Nipple pixel y-coordinate (row).
            image_info: DICOM image metadata.

        Returns:
            A validated NippleAnchor instance.

        Raises:
            ValueError: If coordinates contain NaN/Inf values.
        """
        # Validate coordinate values
        if math.isnan(x_px) or math.isnan(y_px):
            raise ValueError(f"Anchor coordinates contain NaN: ({x_px}, {y_px})")
        if math.isinf(x_px) or math.isinf(y_px):
            raise ValueError(f"Anchor coordinates contain Inf: ({x_px}, {y_px})")

        # Compute physical coordinates
        x_mm, y_mm = image_info.pixel_to_mm(x_px, y_px)

        # Determine state based on bounds
        if image_info.is_inside(x_px, y_px):
            state = AnchorState.PLACED
        else:
            state = AnchorState.OUT_OF_IMAGE

        return cls(
            x_px=x_px,
            y_px=y_px,
            x_mm=x_mm,
            y_mm=y_mm,
            image_info=image_info,
            state=state,
        )

    @classmethod
    def from_mm(
        cls,
        x_mm: float,
        y_mm: float,
        image_info: DicomImageInfo,
    ) -> "NippleAnchor":
        """
        Create a NippleAnchor from physical (mm) coordinates.

        Args:
            x_mm: Horizontal physical coordinate in millimeters.
            y_mm: Vertical physical coordinate in millimeters.
            image_info: DICOM image metadata.

        Returns:
            A validated NippleAnchor instance.
        """
        x_px, y_px = image_info.mm_to_pixel(x_mm, y_mm)
        return cls.create(x_px, y_px, image_info)

    def move_to(self, new_x_px: float, new_y_px: float) -> "NippleAnchor":
        """
        Create a new anchor at the given pixel position (for drag operations).

        Returns a new NippleAnchor (immutable pattern).
        """
        return NippleAnchor.create(new_x_px, new_y_px, self.image_info)

    @property
    def is_valid(self) -> bool:
        """True if the anchor is in a usable state."""
        return self.state == AnchorState.PLACED

    @property
    def side(self) -> BreastSide:
        """Breast laterality."""
        return self.image_info.laterality

    @property
    def view(self) -> MammogramView:
        """Mammography projection view."""
        return self.image_info.view

    @property
    def position_px(self) -> Tuple[float, float]:
        """Pixel coordinates as a tuple."""
        return (self.x_px, self.y_px)

    @property
    def position_mm(self) -> Tuple[float, float]:
        """Physical coordinates as a tuple (mm)."""
        return (self.x_mm, self.y_mm)

    def distance_to_px(self, x_px: float, y_px: float) -> float:
        """
        Euclidean distance to a point in PIXEL coordinates.

        Note: This is NOT a physical distance. Use distance_to_mm() for
        clinically meaningful measurements.
        """
        dx = x_px - self.x_px
        dy = y_px - self.y_px
        return math.sqrt(dx * dx + dy * dy)

    def distance_to_mm(self, x_px: float, y_px: float) -> float:
        """
        Physical Euclidean distance (mm) from this anchor to a point.

        Converts both points to mm then computes Euclidean distance.

        Mathematical basis:
            dx_mm = (x_px - nipple_x_px) × pixel_spacing_x
            dy_mm = (y_px - nipple_y_px) × pixel_spacing_y
            distance = √(dx_mm² + dy_mm²)

        Args:
            x_px: Target point x in pixels.
            y_px: Target point y in pixels.

        Returns:
            Distance in millimeters (always >= 0).
        """
        dx_px = x_px - self.x_px
        dy_px = y_px - self.y_px
        dx_mm = dx_px * self.image_info.pixel_spacing_x_mm
        dy_mm = dy_px * self.image_info.pixel_spacing_y_mm
        return math.sqrt(dx_mm * dx_mm + dy_mm * dy_mm)


@dataclass
class AnchorPair:
    """
    A pair of nipple anchors — one from CC and one from MLO of the same breast.

    Both anchors must be for the same laterality (Left or Right).
    """
    cc_anchor: Optional[NippleAnchor] = None
    mlo_anchor: Optional[NippleAnchor] = None

    @property
    def is_complete(self) -> bool:
        """True if both CC and MLO anchors are placed and valid."""
        return (
            self.cc_anchor is not None
            and self.mlo_anchor is not None
            and self.cc_anchor.is_valid
            and self.mlo_anchor.is_valid
        )

    @property
    def side(self) -> Optional[BreastSide]:
        """Laterality of this pair (from whichever anchor is present)."""
        if self.cc_anchor is not None:
            return self.cc_anchor.side
        if self.mlo_anchor is not None:
            return self.mlo_anchor.side
        return None

    def set_anchor(self, anchor: NippleAnchor) -> None:
        """Set the appropriate anchor based on its view."""
        if anchor.view == MammogramView.CC:
            self.cc_anchor = anchor
        elif anchor.view == MammogramView.MLO:
            self.mlo_anchor = anchor

    def get_anchor(self, view: MammogramView) -> Optional[NippleAnchor]:
        """Get anchor for a specific view."""
        if view == MammogramView.CC:
            return self.cc_anchor
        return self.mlo_anchor

    def clear(self, view: Optional[MammogramView] = None) -> None:
        """Clear one or both anchors."""
        if view is None:
            self.cc_anchor = None
            self.mlo_anchor = None
        elif view == MammogramView.CC:
            self.cc_anchor = None
        elif view == MammogramView.MLO:
            self.mlo_anchor = None
