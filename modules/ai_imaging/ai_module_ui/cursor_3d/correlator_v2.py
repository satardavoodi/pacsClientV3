"""
Correlator V2 — Clinically-accurate lesion matching with Hungarian algorithm.

This module replaces the greedy matching approach with:
    1. User-defined pectoral lines (no fixed 45° assumption).
    2. Hungarian (globally optimal) assignment between CC and MLO lesions.
    3. Quadrant consistency as a geometric constraint in the cost function.
    4. Arc-based projection for unmatched lesions, clipped by pectoral line.

The correlator takes manual landmarks (nipple + pectoral line) as inputs
and produces arc-based projections that respect the actual breast anatomy.

All distances are in millimeters.
No pixel-only computations are used for clinical measurements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .anchor_nipple import (
    BreastSide,
    DicomImageInfo,
    MammogramView,
    NippleAnchor,
)
from .pectoral_line_anchor import PectoralLineAnchor
from .hungarian_matching import (
    HungarianMatchResult,
    LesionDescriptor,
    MatchAssignment,
    solve_hungarian,
)
from .quadrant_consistency import (
    assign_quadrant_cc,
    assign_quadrant_mlo,
    quadrant_penalty,
)
from .distance_computation import (
    ArcParameters,
    DistanceResult,
    compute_anchor_distance,
    compute_arc_parameters,
    TOLERANCE_FRACTION,
)
from .correspondence_arc import (
    CorrespondenceArc,
    compute_correspondence_arc,
)
from .geometry import (
    ChestWallOrientation,
    ImageGeometry,
    LesionLocation,
    MammogramGeometry,
    NipplePosition,
    PixelSpacing,
)


# ─── Result Structures ───────────────────────────────────────────────────────


@dataclass
class CorrelationMatch:
    """A single matched or projected lesion pair."""

    source_view: str  # 'CC' or 'MLO'
    source_lesion: LesionLocation
    target_view: str
    target_lesion: Optional[LesionLocation]

    match_type: str  # 'paired', 'arc_projected', 'out_of_field'

    # Physical measurements (mm)
    source_nad_mm: float  # NAD in source view
    target_nad_mm: float = 0.0  # NAD in target view (for paired)
    nad_difference_mm: float = 0.0

    # Quadrant info
    source_quadrant: str = ""
    target_quadrant: str = ""

    # Confidence [0, 1]
    confidence: float = 0.0

    # Arc data (for projected lesions)
    correspondence_arc: Optional[CorrespondenceArc] = None
    arc_params: Optional[ArcParameters] = None

    # Diagnostic
    message: str = ""


@dataclass
class BreastCorrelationResult:
    """Results for one breast (left or right)."""

    side: BreastSide
    matches: List[CorrelationMatch] = field(default_factory=list)
    hungarian_result: Optional[HungarianMatchResult] = None

    # Landmarks used
    cc_nipple: Optional[NippleAnchor] = None
    mlo_nipple: Optional[NippleAnchor] = None
    pectoral_line: Optional[PectoralLineAnchor] = None

    @property
    def paired_count(self) -> int:
        return sum(1 for m in self.matches if m.match_type == 'paired')

    @property
    def projected_count(self) -> int:
        return sum(1 for m in self.matches if m.match_type == 'arc_projected')

    @property
    def out_of_field_count(self) -> int:
        return sum(1 for m in self.matches if m.match_type == 'out_of_field')


@dataclass
class FullCorrelationResult:
    """Complete correlation result for all breasts."""

    breasts: Dict[str, BreastCorrelationResult] = field(default_factory=dict)

    @property
    def total_matches(self) -> int:
        return sum(len(b.matches) for b in self.breasts.values())


# ─── Input Data ──────────────────────────────────────────────────────────────


@dataclass
class ViewLandmarks:
    """
    User-defined landmarks for a single mammography view.

    The user MUST define both nipple and (for MLO) pectoral line
    before correlation can be performed.
    """

    view: MammogramView
    side: BreastSide
    image_info: DicomImageInfo

    # User-placed nipple anchor (mandatory)
    nipple: Optional[NippleAnchor] = None

    # User-placed pectoral line (mandatory for MLO)
    pectoral_line: Optional[PectoralLineAnchor] = None

    # Lesion boxes from AI detection [x1, y1, x2, y2] in pixels
    lesion_boxes_px: List[List[float]] = field(default_factory=list)
    lesion_scores: List[float] = field(default_factory=list)


# ─── Correlator V2 ───────────────────────────────────────────────────────────


class LesionCorrelatorV2:
    """
    Clinically-accurate lesion correlator using manual landmarks.

    Workflow:
        1. User places nipple on CC and MLO images.
        2. User places pectoral line on MLO image.
        3. For each lesion, compute NAD and quadrant.
        4. Run Hungarian matching between CC and MLO lesions.
        5. For unmatched lesions, compute arc-based projection.
        6. Clip arcs using the pectoral line.

    This class does NOT perform:
        - Automatic nipple detection
        - Automatic pectoral detection
        - Fixed-angle assumptions
    """

    def __init__(
        self,
        max_assignment_cost_mm: float = 25.0,
    ):
        """
        Args:
            max_assignment_cost_mm: Maximum cost (mm-equivalent) for a valid
                assignment. Pairs above this threshold are left unmatched.
        """
        self._max_cost = max_assignment_cost_mm

    def correlate(
        self,
        cc_landmarks: Optional[ViewLandmarks],
        mlo_landmarks: Optional[ViewLandmarks],
    ) -> BreastCorrelationResult:
        """
        Perform lesion correlation between CC and MLO views.

        Both views must have a nipple anchor placed. MLO must additionally
        have a pectoral line defined.

        Args:
            cc_landmarks: CC view data with landmarks.
            mlo_landmarks: MLO view data with landmarks.

        Returns:
            BreastCorrelationResult with all matches and projections.
        """
        # Determine side
        side = cc_landmarks.side if cc_landmarks else (
            mlo_landmarks.side if mlo_landmarks else BreastSide.RIGHT
        )
        result = BreastCorrelationResult(side=side)

        # ── Validate landmarks ──
        errors = self._validate_landmarks(cc_landmarks, mlo_landmarks)
        if errors:
            result.matches.append(CorrelationMatch(
                source_view='CC',
                source_lesion=LesionLocation(0, 0, 0, 0),
                target_view='MLO',
                target_lesion=None,
                match_type='out_of_field',
                source_nad_mm=0.0,
                confidence=0.0,
                message="; ".join(errors),
            ))
            return result

        # Store landmarks
        if cc_landmarks:
            result.cc_nipple = cc_landmarks.nipple
        if mlo_landmarks:
            result.mlo_nipple = mlo_landmarks.nipple
            result.pectoral_line = mlo_landmarks.pectoral_line

        # ── Build lesion descriptors ──
        cc_descriptors = self._build_descriptors(
            cc_landmarks, MammogramView.CC
        ) if cc_landmarks else []

        mlo_descriptors = self._build_descriptors(
            mlo_landmarks, MammogramView.MLO
        ) if mlo_landmarks else []

        # ── Case 1: Both views have lesions → Hungarian matching ──
        if cc_descriptors and mlo_descriptors:
            hungarian = solve_hungarian(
                cc_descriptors=cc_descriptors,
                mlo_descriptors=mlo_descriptors,
                quadrant_penalty_fn=quadrant_penalty,
                max_cost=self._max_cost,
            )
            result.hungarian_result = hungarian

            # Convert matched assignments to CorrelationMatch objects
            for assignment in hungarian.assignments:
                if assignment.is_matched:
                    match = self._build_paired_match(
                        assignment, cc_landmarks, mlo_landmarks,
                        cc_descriptors, mlo_descriptors,
                    )
                    result.matches.append(match)

            # Project unmatched CC lesions → MLO
            for cc_idx in hungarian.unmatched_cc:
                match = self._project_lesion(
                    cc_landmarks, mlo_landmarks,
                    cc_idx, 'CC', 'MLO', cc_descriptors,
                )
                result.matches.append(match)

            # Project unmatched MLO lesions → CC
            for mlo_idx in hungarian.unmatched_mlo:
                match = self._project_lesion(
                    mlo_landmarks, cc_landmarks,
                    mlo_idx, 'MLO', 'CC', mlo_descriptors,
                )
                result.matches.append(match)

        # ── Case 2: Only CC has lesions → project all to MLO ──
        elif cc_descriptors and mlo_landmarks:
            for i in range(len(cc_descriptors)):
                match = self._project_lesion(
                    cc_landmarks, mlo_landmarks,
                    i, 'CC', 'MLO', cc_descriptors,
                )
                result.matches.append(match)

        # ── Case 3: Only MLO has lesions → project all to CC ──
        elif mlo_descriptors and cc_landmarks:
            for i in range(len(mlo_descriptors)):
                match = self._project_lesion(
                    mlo_landmarks, cc_landmarks,
                    i, 'MLO', 'CC', mlo_descriptors,
                )
                result.matches.append(match)

        return result

    # ── Private Methods ──

    def _validate_landmarks(
        self,
        cc: Optional[ViewLandmarks],
        mlo: Optional[ViewLandmarks],
    ) -> List[str]:
        """Validate that all required landmarks are present."""
        errors = []

        if cc is None and mlo is None:
            errors.append("No view data provided.")
            return errors

        if cc is not None and cc.nipple is None:
            errors.append("CC nipple anchor is not placed.")

        if mlo is not None and mlo.nipple is None:
            errors.append("MLO nipple anchor is not placed.")

        if mlo is not None and mlo.pectoral_line is None:
            errors.append(
                "MLO pectoral line is not defined. "
                "Please draw the pectoral line before computing projections."
            )

        return errors

    def _build_descriptors(
        self,
        landmarks: ViewLandmarks,
        view: MammogramView,
    ) -> List[LesionDescriptor]:
        """
        Build LesionDescriptor objects from view landmarks.

        Each lesion gets:
        - NAD (distance from nipple in mm)
        - Height (vertical offset from nipple in mm)
        - Quadrant assignment
        """
        if landmarks.nipple is None:
            return []

        descriptors = []
        nipple = landmarks.nipple
        info = landmarks.image_info
        sp_x = info.pixel_spacing_x_mm
        sp_y = info.pixel_spacing_y_mm

        for i, box in enumerate(landmarks.lesion_boxes_px):
            if len(box) < 4:
                continue

            # Lesion center in pixels
            cx_px = (box[0] + box[2]) / 2.0
            cy_px = (box[1] + box[3]) / 2.0

            # Convert to mm
            cx_mm = cx_px * sp_x
            cy_mm = cy_px * sp_y
            nip_x_mm = nipple.x_mm
            nip_y_mm = nipple.y_mm

            # NAD: Euclidean distance from nipple to lesion center in mm
            dx = cx_mm - nip_x_mm
            dy = cy_mm - nip_y_mm
            nad_mm = math.sqrt(dx * dx + dy * dy)

            # Height: vertical offset from nipple (positive = below)
            height_mm = dy

            # Quadrant assignment
            if view == MammogramView.CC:
                quad = assign_quadrant_cc(
                    cx_mm, cy_mm, nip_x_mm, nip_y_mm, landmarks.side
                )
            else:
                quad = assign_quadrant_mlo(
                    cx_mm, cy_mm, nip_x_mm, nip_y_mm,
                    landmarks.side, landmarks.pectoral_line,
                )

            score = landmarks.lesion_scores[i] if i < len(landmarks.lesion_scores) else 0.5

            descriptors.append(LesionDescriptor(
                index=i,
                nad_mm=nad_mm,
                height_mm=height_mm,
                center_x_mm=cx_mm,
                center_y_mm=cy_mm,
                quadrant=quad,
                score=score,
            ))

        return descriptors

    def _build_paired_match(
        self,
        assignment: MatchAssignment,
        cc_lm: ViewLandmarks,
        mlo_lm: ViewLandmarks,
        cc_desc: List[LesionDescriptor],
        mlo_desc: List[LesionDescriptor],
    ) -> CorrelationMatch:
        """Build a CorrelationMatch for a paired assignment."""
        cc_d = cc_desc[assignment.cc_index]
        mlo_d = mlo_desc[assignment.mlo_index]

        # Build LesionLocation objects
        cc_box = cc_lm.lesion_boxes_px[assignment.cc_index]
        mlo_box = mlo_lm.lesion_boxes_px[assignment.mlo_index]

        sp_cc = PixelSpacing(
            x=cc_lm.image_info.pixel_spacing_x_mm,
            y=cc_lm.image_info.pixel_spacing_y_mm,
        )
        sp_mlo = PixelSpacing(
            x=mlo_lm.image_info.pixel_spacing_x_mm,
            y=mlo_lm.image_info.pixel_spacing_y_mm,
        )

        cc_lesion = LesionLocation.from_pixel_box(cc_box, sp_cc, score=cc_d.score)
        mlo_lesion = LesionLocation.from_pixel_box(mlo_box, sp_mlo, score=mlo_d.score)

        confidence = max(0.5, 1.0 - (assignment.cost / self._max_cost))

        return CorrelationMatch(
            source_view='CC',
            source_lesion=cc_lesion,
            target_view='MLO',
            target_lesion=mlo_lesion,
            match_type='paired',
            source_nad_mm=cc_d.nad_mm,
            target_nad_mm=mlo_d.nad_mm,
            nad_difference_mm=assignment.nad_difference_mm,
            source_quadrant=cc_d.quadrant,
            target_quadrant=mlo_d.quadrant,
            confidence=round(confidence, 3),
            message=(
                f"Paired: NAD diff={assignment.nad_difference_mm:.1f}mm, "
                f"cost={assignment.cost:.1f}, "
                f"quadrants={cc_d.quadrant}→{mlo_d.quadrant}"
            ),
        )

    def _project_lesion(
        self,
        source_lm: ViewLandmarks,
        target_lm: ViewLandmarks,
        lesion_idx: int,
        source_view_str: str,
        target_view_str: str,
        descriptors: List[LesionDescriptor],
    ) -> CorrelationMatch:
        """
        Project an unmatched lesion from source view to target view using arc.

        The arc is centered on the target nipple with radius = source NAD.
        It is clipped by the pectoral line to exclude anatomically impossible regions.
        """
        desc = descriptors[lesion_idx]
        box = source_lm.lesion_boxes_px[lesion_idx]
        sp = PixelSpacing(
            x=source_lm.image_info.pixel_spacing_x_mm,
            y=source_lm.image_info.pixel_spacing_y_mm,
        )
        source_lesion = LesionLocation.from_pixel_box(box, sp, score=desc.score)

        # ── Validate projection feasibility ──
        target_nipple = target_lm.nipple
        if target_nipple is None:
            return CorrelationMatch(
                source_view=source_view_str,
                source_lesion=source_lesion,
                target_view=target_view_str,
                target_lesion=None,
                match_type='out_of_field',
                source_nad_mm=desc.nad_mm,
                source_quadrant=desc.quadrant,
                confidence=0.0,
                message="Target view nipple not placed.",
            )

        # ── Compute arc parameters ──
        # Arc radius = source NAD (preserved between views by Kopans' Rule)
        radius_mm = desc.nad_mm

        # Convert radius to pixels in target view
        target_sp_x = target_lm.image_info.pixel_spacing_x_mm
        target_sp_y = target_lm.image_info.pixel_spacing_y_mm
        avg_sp = (target_sp_x + target_sp_y) / 2.0
        radius_px = radius_mm / avg_sp

        # Arc center = target nipple
        center_px = target_nipple.position_px

        # ── Determine angular extent ──
        # Use pectoral line to clip the arc if available
        pectoral = target_lm.pectoral_line

        if pectoral is not None:
            start_angle, end_angle = pectoral.clip_angle_range(center_px, radius_px)
        else:
            # Without pectoral line: use full 180° on the breast side
            if target_lm.side == BreastSide.RIGHT:
                # Breast tissue is to the LEFT of chest wall
                start_angle = math.pi / 2.0   # pointing down
                end_angle = 3.0 * math.pi / 2.0  # pointing up (through left)
            else:
                # Breast tissue is to the RIGHT
                start_angle = -math.pi / 2.0
                end_angle = math.pi / 2.0

        # ── Check if arc is within image bounds ──
        target_w = target_lm.image_info.width_px
        target_h = target_lm.image_info.height_px
        cx, cy = center_px

        arc_outside = (
            cx + radius_px < 0 or cx - radius_px > target_w or
            cy + radius_px < 0 or cy - radius_px > target_h
        )

        if arc_outside:
            return CorrelationMatch(
                source_view=source_view_str,
                source_lesion=source_lesion,
                target_view=target_view_str,
                target_lesion=None,
                match_type='out_of_field',
                source_nad_mm=desc.nad_mm,
                source_quadrant=desc.quadrant,
                confidence=0.0,
                message=(
                    f"Projected localization extends outside image boundaries. "
                    f"NAD={desc.nad_mm:.1f}mm exceeds available field."
                ),
            )

        # ── Build ArcParameters for rendering ──
        inner_radius_mm = radius_mm * (1.0 - TOLERANCE_FRACTION)
        outer_radius_mm = radius_mm * (1.0 + TOLERANCE_FRACTION)

        arc_params = ArcParameters(
            center_px=center_px,
            center_mm=target_nipple.position_mm,
            nominal_radius_mm=radius_mm,
            inner_radius_mm=inner_radius_mm,
            outer_radius_mm=outer_radius_mm,
            nominal_radius_px=radius_px,
            inner_radius_px=inner_radius_mm / avg_sp,
            outer_radius_px=outer_radius_mm / avg_sp,
            start_angle_rad=start_angle,
            end_angle_rad=end_angle,
            source_anchor=target_nipple,
            target_image_info=target_lm.image_info,
            is_valid=True,
        )

        return CorrelationMatch(
            source_view=source_view_str,
            source_lesion=source_lesion,
            target_view=target_view_str,
            target_lesion=None,
            match_type='arc_projected',
            source_nad_mm=desc.nad_mm,
            source_quadrant=desc.quadrant,
            confidence=0.6,
            arc_params=arc_params,
            message=(
                f"Arc projection: NAD={desc.nad_mm:.1f}mm, "
                f"range={inner_radius_mm:.1f}–{outer_radius_mm:.1f}mm (±10%), "
                f"quadrant={desc.quadrant}"
            ),
        )
