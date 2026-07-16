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
    pectoral_angle_deg: Optional[float] = None  # Angle from vertical in MLO
    # A point ON the pectoral reference line (mm from image origin). Set only for
    # the MLO view (the pectoral muscle is imaged only there). Combined with
    # `pectoral_angle_deg` it fully defines the pectoral line, so the perpendicular
    # nipple→pectoral distance (the Posterior Nipple Line) can be measured for PNL
    # cross-view depth normalisation. None → the line position is unknown and PNL
    # normalisation is skipped (legacy absolute-depth behaviour). Additive/optional
    # so every existing construction site stays byte-identical.
    pectoral_ref_point_mm: Optional[Tuple[float, float]] = None
    # Measured CC posterior-nipple-line length (mm): the nipple -> posterior breast
    # TISSUE boundary distance, from the segmentation contour. Used as the CC
    # chest-wall reference INSTEAD of the raw image edge (which over-estimates when
    # the breast does not fill the image to the edge). None -> fall back to the
    # image edge. Ignored for MLO (which uses its own pectoral line).
    cc_reference_distance_mm: Optional[float] = None
    # The manually drawn reference line (both endpoints, mm) for THIS view — the MLO
    # pectoral muscle line or the CC chest-wall line. When set it is AUTHORITATIVE:
    # the nipple->pectoral distance is the PERPENDICULAR from the nipple to this
    # exact line, computed the same way as the on-screen ruler (sign-preserving). It
    # replaces the MLO midpoint + abs(angle) method, whose abs() dropped the line's
    # direction sign and under-measured the MLO PNL (50107: 43 mm vs ~100 mm true).
    manual_reference_line_mm: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None

    def _depth_normal_unit_vector(self) -> Tuple[float, float]:
        """
        Unit vector (nx, ny) for the depth direction (perpendicular to chest wall).

        For CC this remains horizontal toward chest wall.
        For MLO, if pectoral angle is available, the depth normal tilts by that angle.
        """
        # Base normal: horizontal toward chest wall.
        if self.chest_wall == ChestWallOrientation.RIGHT:
            base_angle = 0.0
            side_sign = 1.0
        else:
            base_angle = math.pi
            side_sign = -1.0

        # MLO depth is measured along the normal to oblique chest wall.
        if self.view_position == 'MLO' and self.pectoral_angle_deg is not None:
            tilt = math.radians(float(self.pectoral_angle_deg))
            # In image coords y-down, pectoral muscle is at TOP of MLO.
            # Depth goes UPWARD (negative y) toward chest wall.
            # R-MLO: angle = 0 - 60° = -60° → (0.5, -0.866) = up-right ✓
            # L-MLO: angle = π + 60° → (-0.5, -0.866) = up-left ✓
            angle = base_angle - side_sign * tilt
        else:
            angle = base_angle

        return (math.cos(angle), math.sin(angle))

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
        lesion_cx_mm, lesion_cy_mm = lesion.center_mm
        nipple_x_mm = self.nipple.x_mm
        nipple_y_mm = self.nipple.y_mm
        nx, ny = self._depth_normal_unit_vector()

        dx = lesion_cx_mm - nipple_x_mm
        dy = lesion_cy_mm - nipple_y_mm
        # Perpendicular distance to chest wall line through nipple.
        return abs(dx * nx + dy * ny)

    def pectoral_reference_distance_mm(self) -> Optional[float]:
        """
        Perpendicular nipple → pectoral-reference distance — the Posterior Nipple
        Line (PNL) length, in mm. This is the anatomical DEPTH SCALE of the breast
        in this view: the nipple and the pectoral/chest-wall are the two stable
        landmarks, so a lesion's depth expressed as a FRACTION of this distance is
        far more view-invariant than its absolute nipple-distance (which changes
        with the different compression/geometry of CC vs MLO).

            • CC view — the pectoral muscle is not imaged, so the posterior image
              EDGE is the chest-wall reference. PNL = horizontal nipple→edge
              distance. Always available.

            • MLO view — the reference is the pectoral MUSCLE line. PNL =
              perpendicular distance from the nipple to that line, which needs both
              `pectoral_ref_point_mm` (a point on the line) and `pectoral_angle_deg`.
              Returns None when either is missing — the MLO image EDGE is NOT the
              pectoral muscle, so we never silently substitute it.

        Returns None when the reference cannot be established; the PNL normaliser
        then falls back to the legacy absolute-depth behaviour.
        """
        # AUTHORITATIVE (both views): a manually drawn reference line — the
        # perpendicular from the nipple to that exact line, sign-preserving, computed
        # identically to the on-screen ruler. This replaces the MLO midpoint +
        # abs(angle) below, whose abs() dropped the line direction and under-measured
        # the MLO PNL (50107: 43 mm vs ~100 mm true, scaling the depth wrongly).
        if self.manual_reference_line_mm is not None:
            _p1, _p2 = self.manual_reference_line_mm
            _d = perpendicular_point_to_line_mm(
                (self.nipple.x_mm, self.nipple.y_mm), _p1, _p2)
            if _d is not None and _d > 1e-6:
                return float(_d)

        view = (self.view_position or "").upper()

        if view != "MLO":
            # CC (or any non-MLO view): the chest-wall reference.
            # Prefer the MEASURED posterior tissue-boundary distance (from the
            # segmentation contour); fall back to the raw image edge only when it is
            # unavailable.
            if self.cc_reference_distance_mm is not None and self.cc_reference_distance_mm > 1e-6:
                return float(self.cc_reference_distance_mm)
            if self.chest_wall == ChestWallOrientation.RIGHT:
                d = self.image.width_mm - self.nipple.x_mm
            else:
                d = self.nipple.x_mm
            return d if d > 1e-6 else None

        # MLO: perpendicular distance from the nipple to the pectoral muscle line.
        if self.pectoral_ref_point_mm is None or self.pectoral_angle_deg is None:
            return None
        theta = math.radians(float(self.pectoral_angle_deg))  # angle from vertical
        # Line direction (unit): θ measured from the vertical (y) axis.
        dir_x, dir_y = math.sin(theta), math.cos(theta)
        ax = self.nipple.x_mm - self.pectoral_ref_point_mm[0]
        ay = self.nipple.y_mm - self.pectoral_ref_point_mm[1]
        # Perpendicular distance = |A × d| with d a unit vector (2-D cross product).
        dist = abs(ax * dir_y - ay * dir_x)
        return dist if dist > 1e-6 else None

    def depth_normal_unit_vector(self) -> Tuple[float, float]:
        """
        Public accessor for the depth-normal unit vector (nx, ny).

        Points from the nipple toward the chest wall. For MLO with a known
        pectoral angle it is tilted by that angle (see _depth_normal_unit_vector).

        This is the axis of the SS (Straight Strip) "axial distance" and is the
        single source of truth for chest-wall direction. Consumers MUST use this
        rather than re-deriving a direction from laterality — re-derivation is
        what produced the left-breast arc mirror defect.
        """
        return self._depth_normal_unit_vector()

    def compute_lesion_radial_distance_mm(self, lesion: LesionLocation) -> float:
        """
        Straight-line (radial) distance from the nipple to the lesion centre, in mm.

            dr = sqrt(dx^2 + dy^2)

        This is the classic Kopans nipple-to-lesion distance ("NOD"), and it is the
        quantity the AB (Annular Band / arc) method assumes is preserved between
        the CC and MLO views.

        NOTE — this is NOT the same as compute_lesion_depth_mm(), which returns the
        AXIAL (perpendicular) component `dl` used by the SS (Straight Strip) method.
        Always: dl <= dr, with equality only when the lesion lies exactly on the
        posterior nipple line. Feeding `dl` in as an arc radius (as the legacy
        correspondence_arc did) yields a systematically undersized arc.

        Returns:
            Radial distance in millimetres (always >= 0).
        """
        lesion_cx_mm, lesion_cy_mm = lesion.center_mm
        dx = lesion_cx_mm - self.nipple.x_mm
        dy = lesion_cy_mm - self.nipple.y_mm
        return math.hypot(dx, dy)

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
        nx, ny = self._depth_normal_unit_vector()
        candidates = []

        # Intersect with vertical image borders in mm-space.
        if abs(nx) > 1e-8:
            if nx > 0:
                tx = (self.image.width_mm - self.nipple.x_mm) / nx
            else:
                tx = (0.0 - self.nipple.x_mm) / nx
            if tx >= 0:
                candidates.append(tx)

        # Intersect with horizontal image borders in mm-space.
        if abs(ny) > 1e-8:
            if ny > 0:
                ty = (self.image.height_mm - self.nipple.y_mm) / ny
            else:
                ty = (0.0 - self.nipple.y_mm) / ny
            if ty >= 0:
                candidates.append(ty)

        if not candidates:
            return 0.0
        return max(0.0, min(candidates))

    def project_depth_to_pixel(self, depth_mm: float) -> Tuple[float, float]:
        """
        Project a depth from nipple along depth-normal direction into pixel space.
        """
        nx, ny = self._depth_normal_unit_vector()
        x_mm = self.nipple.x_mm + nx * depth_mm
        y_mm = self.nipple.y_mm + ny * depth_mm
        return self.image.mm_to_px(x_mm, y_mm)

    def project_depth_to_pixel_x(self, depth_mm: float) -> float:
        """
        Given a lesion depth (mm from nipple along PNL), compute the pixel x coordinate.

        Args:
            depth_mm: The perpendicular distance from nipple in mm.

        Returns:
            x coordinate in pixels.
        """
        x_px, _ = self.project_depth_to_pixel(depth_mm)
        return x_px

    def is_depth_within_field(self, depth_mm: float) -> bool:
        """Check if a given depth (mm) falls within the imaging field."""
        return depth_mm <= self.max_available_depth_mm()


def cc_posterior_tissue_distance_mm(
    contour_points_px,
    nipple_x_px: float,
    laterality: str,
    spacing_x_mm: float,
) -> Optional[float]:
    """
    CC PNL from the breast-tissue contour — the nipple -> posterior TISSUE boundary
    horizontal distance (mm), a better chest-wall reference than the raw image edge.

    The posterior boundary is the chest-wall-side extreme of the contour:
    max x for a RIGHT breast (chest wall on the right), min x for LEFT.

    Returns None when the contour is empty/degenerate or the boundary is not
    posterior to the nipple (a bad/failed segmentation) -> the caller then keeps the
    image-edge fallback rather than trusting a wrong tissue boundary.

    Pure: iterates (x, y) points; no numpy/cv2 (the caller flattens the cv2 contour).
    """
    xs = []
    for p in contour_points_px or []:
        try:
            xs.append(float(p[0]))
        except Exception:
            continue
    if not xs:
        return None
    nipple_x = float(nipple_x_px)
    if str(laterality).upper().startswith("L"):
        boundary_x = min(xs)                 # chest wall on the LEFT edge
        dist_px = nipple_x - boundary_x
    else:
        boundary_x = max(xs)                 # chest wall on the RIGHT edge
        dist_px = boundary_x - nipple_x
    if dist_px <= 1e-6:
        return None
    return dist_px * float(spacing_x_mm)


def perpendicular_point_to_line_mm(
    p_mm, a_mm, b_mm,
) -> Optional[float]:
    """
    Perpendicular distance (mm) from point `p` to the INFINITE line through `a`,`b`.

    Used for the MANUAL CC reference line: the CC Posterior Nipple Line is the
    perpendicular distance from the CC nipple to the user-drawn chest-wall/pectoral
    line — the same measure the MLO uses, but drawn by hand because the CC image
    edge / tissue contour is not a reliable chest-wall reference. All inputs in mm.

    Returns None for a degenerate (zero-length) line. Pure stdlib.
    """
    try:
        px, py = float(p_mm[0]), float(p_mm[1])
        ax, ay = float(a_mm[0]), float(a_mm[1])
        bx, by = float(b_mm[0]), float(b_mm[1])
    except Exception:
        return None
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    # |(P - A) x (B - A)| / |B - A|
    cross = (px - ax) * dy - (py - ay) * dx
    return abs(cross) / length


def pectoral_angle_from_positioner_angle(
    positioner_angle_deg,
    *,
    min_deg: float = 10.0,
    max_deg: float = 80.0,
) -> Optional[float]:
    """
    Map the DICOM MLO acquisition angle — Positioner Primary Angle (0018,1510) — to a
    pectoral "angle from vertical" MAGNITUDE usable as `pectoral_angle_deg`.

    The 3D-Cursor geometry needs only the MAGNITUDE: `_depth_normal_unit_vector`
    applies the left/right sign itself from the laterality, so we return a positive
    value in [0, 90]. Vendors store the MLO gantry angle with different sign/quadrant
    conventions (+45, -45, 135, …), so we fold it: `abs`, wrap into [0, 180], reflect
    across 90.

    Returns None (→ the caller keeps its legacy behaviour) when the value is absent,
    non-numeric, or outside the plausible MLO band [min_deg, max_deg] — a CC's ~0°,
    a ~90° lateral, or garbage must never be fed in as a pectoral tilt. This is a
    per-unit APPROXIMATION (the gantry angle is not exactly the pectoral-line angle),
    which is why it is only ever a FALLBACK for when the radiologist has not drawn the
    pectoral line, and is flag-gated at the call site. Pure stdlib.
    """
    if positioner_angle_deg is None:
        return None
    try:
        a = abs(float(positioner_angle_deg))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(a):
        return None
    a = a % 180.0
    if a > 90.0:
        a = 180.0 - a
    if min_deg <= a <= max_deg:
        return a
    return None
