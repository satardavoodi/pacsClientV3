"""
3D Cursor Correlator — Lesion correlation between CC and MLO views.

This module implements the core 3D cursor algorithm:
    1. For each breast (R/L), compare lesions in CC and MLO views.
    2. If a lesion appears in both views at matching depths → paired (Case 1).
    3. If a lesion appears in only one view → project to the other (Case 2).

All matching and projection is performed in millimeters using the anatomical
principle that perpendicular distance from nipple to chest wall is preserved
between views.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .geometry import (
    ChestWallOrientation,
    ImageGeometry,
    LesionLocation,
    MammogramGeometry,
    NipplePosition,
    PixelSpacing,
)
from .nipple_detect import detect_nipple_position
from .correspondence_arc import (
    CorrespondenceArc,
    compute_correspondence_arc,
    refine_arc_with_density_correlation,
)
from .pectoral_detection import (
    detect_pectoral_angle,
    estimate_pectoral_angle_fallback,
)
from .breast_contour import segment_breast_contour
from .validation import (
    validate_pectoral_angle,
    validate_projected_point,
    format_calc_log,
    PectoralAngleValidation,
    FullValidationResult,
)


# ─── Result Data Structures ──────────────────────────────────────────────────

@dataclass
class CursorMatch:
    """A single 3D cursor result for one lesion."""
    # Source lesion (detected by AI)
    source_view: str  # 'CC' or 'MLO'
    source_lesion: LesionLocation
    # Target (paired or projected)
    target_view: str  # 'CC' or 'MLO'
    target_lesion: Optional[LesionLocation]  # None if projection failed
    # Classification
    match_type: str  # 'paired', 'projected', 'out_of_field', 'arc_projected'
    # Physical measurements (mm)
    depth_mm: float  # perpendicular distance from nipple to lesion
    depth_difference_mm: float = 0.0  # for paired: difference in depth between views
    # Confidence
    confidence: float = 0.0
    # Correspondence arc (for arc-based projections)
    correspondence_arc: Optional[CorrespondenceArc] = None
    # Validation message (for out_of_field or warnings)
    message: str = ""


@dataclass
class LateralityResult:
    """Results for one breast (R or L)."""
    laterality: str
    cursor_matches: List[CursorMatch] = field(default_factory=list)
    cc_geometry: Optional[MammogramGeometry] = None
    mlo_geometry: Optional[MammogramGeometry] = None

    @property
    def total_cursors(self) -> int:
        return len(self.cursor_matches)

    @property
    def paired_count(self) -> int:
        return sum(1 for m in self.cursor_matches if m.match_type == 'paired')

    @property
    def projected_count(self) -> int:
        return sum(1 for m in self.cursor_matches if m.match_type in ('projected', 'arc_projected'))

    @property
    def out_of_field_count(self) -> int:
        return sum(1 for m in self.cursor_matches if m.match_type == 'out_of_field')


@dataclass
class Cursor3DResult:
    """Complete result of the 3D cursor computation for all lateralities."""
    lateralities: Dict[str, LateralityResult] = field(default_factory=dict)

    @property
    def total_cursors(self) -> int:
        return sum(r.total_cursors for r in self.lateralities.values())


# ─── Configuration ───────────────────────────────────────────────────────────

# Maximum depth difference (mm) to consider two lesions as the same abnormality.
# Based on breast imaging literature: ~15mm accounts for compression differences.
MATCHING_THRESHOLD_MM = 15.0

# Relative threshold as fraction of the larger depth (for larger lesion depths).
MATCHING_THRESHOLD_RELATIVE = 0.30


# ─── View Data Input ─────────────────────────────────────────────────────────

@dataclass
class ViewData:
    """Input data for one mammogram view."""
    laterality: str  # 'R' or 'L'
    view_position: str  # 'CC' or 'MLO'
    dicom_path: Optional[str] = None
    boxes_px: List[list] = field(default_factory=list)  # [[x1,y1,x2,y2], ...]
    scores: List[float] = field(default_factory=list)
    img_width: Optional[int] = None
    img_height: Optional[int] = None
    pixel_spacing_x: Optional[float] = None
    pixel_spacing_y: Optional[float] = None
    vtk_widget: object = None  # Reference to viewer widget for visualization
    manual_nipple_px: Optional[Tuple[float, float]] = None  # User-selected nipple (x_px, y_px)
    manual_pectoral_angle_deg: Optional[float] = None  # User-drawn pectoral line angle


# ─── Main Correlator Class ───────────────────────────────────────────────────

class CursorCorrelator3D:
    """
    3D Cursor correlator for mammography CC/MLO views.

    Workflow:
        1. Build MammogramGeometry for each view (detect nipple, set up coordinates).
        2. Convert all lesion boxes to physical (mm) LesionLocations.
        3. For each breast: match lesions by depth, project unmatched ones.
        4. Validate projections against available imaging field.
    """

    def __init__(self, matching_threshold_mm: float = MATCHING_THRESHOLD_MM):
        self.matching_threshold_mm = matching_threshold_mm

    def correlate(self, views: List[ViewData]) -> Cursor3DResult:
        """
        Run the 3D cursor correlation on a set of mammogram views.

        Args:
            views: List of ViewData objects (CC and/or MLO for R and/or L breast).

        Returns:
            Cursor3DResult with all correlations and projections.
        """
        result = Cursor3DResult()

        # Group views by laterality
        groups = self._group_by_laterality(views)

        for laterality, lat_views in groups.items():
            lat_result = self._process_laterality(laterality, lat_views)
            result.lateralities[laterality] = lat_result

        return result

    def _group_by_laterality(self, views: List[ViewData]) -> Dict[str, Dict[str, ViewData]]:
        """Group views by laterality, keeping only CC and MLO."""
        groups: Dict[str, Dict[str, ViewData]] = {}

        for vd in views:
            if vd.view_position not in ('CC', 'MLO'):
                continue
            lat = vd.laterality
            if lat not in groups:
                groups[lat] = {}

            if vd.view_position not in groups[lat]:
                groups[lat][vd.view_position] = vd
            else:
                # Merge boxes from duplicate views
                existing = groups[lat][vd.view_position]
                existing.boxes_px.extend(vd.boxes_px)
                existing.scores.extend(vd.scores)

        return groups

    def _process_laterality(self, laterality: str, views: Dict[str, ViewData]) -> LateralityResult:
        """Process one laterality (R or L): build geometry, correlate lesions."""
        lat_result = LateralityResult(laterality=laterality)

        cc_view = views.get('CC')
        mlo_view = views.get('MLO')

        # Extract pectoral angle from MLO view
        pectoral_angle_deg = None
        # Prefer user-drawn pectoral line angle (from either view, MLO preferred)
        if mlo_view and mlo_view.manual_pectoral_angle_deg is not None:
            pectoral_angle_deg = mlo_view.manual_pectoral_angle_deg
            print(f"[3D-Cursor] Using MANUAL pectoral angle from MLO: {pectoral_angle_deg:.1f}°")
        elif cc_view and cc_view.manual_pectoral_angle_deg is not None:
            pectoral_angle_deg = cc_view.manual_pectoral_angle_deg
            print(f"[3D-Cursor] Using MANUAL pectoral angle from CC: {pectoral_angle_deg:.1f}°")
        elif mlo_view and mlo_view.dicom_path:
            pectoral_angle_deg = self._extract_pectoral_angle(mlo_view, laterality)

        # Build geometry for available views
        cc_geom = self._build_geometry(cc_view) if cc_view else None
        mlo_geom = self._build_geometry(mlo_view, pectoral_angle_deg=pectoral_angle_deg) if mlo_view else None

        lat_result.cc_geometry = cc_geom
        lat_result.mlo_geometry = mlo_geom

        # Extract breast contours
        cc_contour = self._extract_breast_contour(cc_view) if cc_view else None
        mlo_contour = self._extract_breast_contour(mlo_view) if mlo_view else None

        # Convert boxes to LesionLocation objects
        cc_lesions = self._build_lesions(cc_view, cc_geom) if cc_view and cc_geom else []
        mlo_lesions = self._build_lesions(mlo_view, mlo_geom) if mlo_view and mlo_geom else []

        # Determine if we need pairing or just projection
        if cc_lesions and mlo_lesions and cc_geom and mlo_geom:
            # Both views have lesions → try to pair them
            matches = self._pair_lesions(
                cc_lesions, mlo_lesions, cc_geom, mlo_geom,
                cc_contour=cc_contour,
                mlo_contour=mlo_contour,
                pectoral_angle_deg=pectoral_angle_deg,
            )
            lat_result.cursor_matches = matches
        elif cc_lesions and mlo_geom:
            # Only CC has lesions → project each to MLO
            for lesion in cc_lesions:
                match = self._project_lesion_with_arc(
                    lesion, cc_geom, mlo_geom, 'CC', 'MLO',
                    pectoral_angle_deg=pectoral_angle_deg,
                    breast_contour=mlo_contour,
                )
                lat_result.cursor_matches.append(match)
        elif mlo_lesions and cc_geom:
            # Only MLO has lesions → project each to CC
            for lesion in mlo_lesions:
                match = self._project_lesion_with_arc(
                    lesion, mlo_geom, cc_geom, 'MLO', 'CC',
                    pectoral_angle_deg=pectoral_angle_deg,
                    breast_contour=cc_contour,
                )
                lat_result.cursor_matches.append(match)

        return lat_result

    def _build_geometry(
        self,
        view: ViewData,
        pectoral_angle_deg: Optional[float] = None,
    ) -> Optional[MammogramGeometry]:
        """Build a MammogramGeometry from view data."""
        # Determine pixel spacing
        sp_x = view.pixel_spacing_x
        sp_y = view.pixel_spacing_y

        if not sp_x or sp_x <= 0 or not sp_y or sp_y <= 0:
            # Cannot proceed without valid pixel spacing
            return None

        # Image dimensions required
        if not view.img_width or not view.img_height:
            return None

        spacing = PixelSpacing(x=sp_x, y=sp_y)
        image_geom = ImageGeometry(
            width_px=view.img_width,
            height_px=view.img_height,
            pixel_spacing=spacing,
        )

        # Determine chest wall orientation
        if view.laterality == 'R':
            chest_wall = ChestWallOrientation.RIGHT
        else:
            chest_wall = ChestWallOrientation.LEFT

        # Use manual nipple if provided, else auto-detect
        if view.manual_nipple_px is not None:
            nipple = NipplePosition.from_pixels(
                x_px=float(view.manual_nipple_px[0]),
                y_px=float(view.manual_nipple_px[1]),
                spacing=spacing,
                detected=True,
            )
            print(f"[3D-Cursor] Using MANUAL nipple for {view.laterality}-{view.view_position}: "
                  f"({view.manual_nipple_px[0]:.1f}, {view.manual_nipple_px[1]:.1f})")
        else:
            nipple = detect_nipple_position(
                dicom_path=view.dicom_path,
                laterality=view.laterality,
                view_position=view.view_position,
                image_geom=image_geom,
                lesion_boxes_px=view.boxes_px if view.boxes_px else None,
            )

        return MammogramGeometry(
            image=image_geom,
            nipple=nipple,
            chest_wall=chest_wall,
            laterality=view.laterality,
            view_position=view.view_position,
            pectoral_angle_deg=pectoral_angle_deg if view.view_position == 'MLO' else None,
        )

    def _build_lesions(self, view: ViewData, geom: MammogramGeometry) -> List[LesionLocation]:
        """Convert pixel box lists to LesionLocation objects."""
        lesions = []
        for i, box in enumerate(view.boxes_px):
            score = view.scores[i] if i < len(view.scores) else 0.5
            lesion = LesionLocation.from_pixel_box(box, geom.image.pixel_spacing, score=score)
            lesions.append(lesion)
        return lesions

    def _pair_lesions(
        self,
        cc_lesions: List[LesionLocation],
        mlo_lesions: List[LesionLocation],
        cc_geom: MammogramGeometry,
        mlo_geom: MammogramGeometry,
        cc_contour: Optional[object] = None,
        mlo_contour: Optional[object] = None,
        pectoral_angle_deg: Optional[float] = None,
    ) -> List[CursorMatch]:
        """
        Pair CC and MLO lesions by matching their depths (mm from nipple).

        Algorithm:
            For each CC lesion, find the MLO lesion with the closest depth.
            If the depth difference is within the matching threshold → paired.
            Otherwise → project using arc-based method.
        """
        matches: List[CursorMatch] = []
        used_mlo_indices: set = set()

        # Compute depths for all lesions
        cc_depths = [cc_geom.compute_lesion_depth_mm(l) for l in cc_lesions]
        mlo_depths = [mlo_geom.compute_lesion_depth_mm(l) for l in mlo_lesions]

        # Match CC lesions to MLO lesions by depth similarity
        for i, cc_lesion in enumerate(cc_lesions):
            cc_depth = cc_depths[i]
            best_j = -1
            best_diff = float('inf')

            for j, mlo_lesion in enumerate(mlo_lesions):
                if j in used_mlo_indices:
                    continue
                mlo_depth = mlo_depths[j]
                diff = abs(cc_depth - mlo_depth)
                if diff < best_diff:
                    best_diff = diff
                    best_j = j

            # Determine threshold: max of absolute and relative
            threshold = max(
                self.matching_threshold_mm,
                max(cc_depth, mlo_depths[best_j] if best_j >= 0 else 0) * MATCHING_THRESHOLD_RELATIVE,
            )

            if best_j >= 0 and best_diff <= threshold:
                # Case 1: Paired — same lesion seen in both views
                used_mlo_indices.add(best_j)
                confidence = max(0.5, 1.0 - (best_diff / threshold))

                # Also compute the correspondence arc for visual feedback
                paired_arc = None
                try:
                    paired_arc = compute_correspondence_arc(
                        source_lesion=cc_lesion,
                        source_geom=cc_geom,
                        target_geom=mlo_geom,
                        source_view='CC',
                        target_view='MLO',
                        pectoral_angle_deg=pectoral_angle_deg,
                        breast_contour=mlo_contour,
                        angular_resolution_deg=1.0,
                        angle_margin_deg=30.0,
                    )
                except Exception:
                    pass

                matches.append(CursorMatch(
                    source_view='CC',
                    source_lesion=cc_lesion,
                    target_view='MLO',
                    target_lesion=mlo_lesions[best_j],
                    match_type='paired',
                    depth_mm=cc_depth,
                    depth_difference_mm=best_diff,
                    confidence=round(confidence, 2),
                    correspondence_arc=paired_arc,
                ))
            else:
                # Case 2: CC only → project to MLO using arc
                match = self._project_lesion_with_arc(
                    cc_lesion, cc_geom, mlo_geom, 'CC', 'MLO',
                    pectoral_angle_deg=pectoral_angle_deg,
                    breast_contour=mlo_contour,
                )
                matches.append(match)

        # Unmatched MLO lesions → project to CC using arc
        for j, mlo_lesion in enumerate(mlo_lesions):
            if j in used_mlo_indices:
                continue
            match = self._project_lesion_with_arc(
                mlo_lesion, mlo_geom, cc_geom, 'MLO', 'CC',
                pectoral_angle_deg=pectoral_angle_deg,
                breast_contour=cc_contour,
            )
            matches.append(match)

        return matches

    def _project_lesion(
        self,
        source_lesion: LesionLocation,
        source_geom: MammogramGeometry,
        target_geom: MammogramGeometry,
        source_view: str,
        target_view: str,
    ) -> CursorMatch:
        """
        Project a lesion from one view to another using physical depth preservation.

        The perpendicular distance from nipple to the lesion (in mm) is computed
        in the source view, then applied in the target view to find the expected
        location.

        Out-of-field validation: if the depth exceeds the available breast depth
        in the target image, the projection is marked as 'out_of_field'.
        """
        # Compute the physical depth in the source view
        depth_mm = source_geom.compute_lesion_depth_mm(source_lesion)

        # Validate: is this depth achievable in the target image?
        if not target_geom.is_depth_within_field(depth_mm):
            return CursorMatch(
                source_view=source_view,
                source_lesion=source_lesion,
                target_view=target_view,
                target_lesion=None,
                match_type='out_of_field',
                depth_mm=depth_mm,
                confidence=0.0,
                message=(
                    f"⚠ خارج از ناحیه تصویر | "
                    f"Projected location is outside the breast area. "
                    f"Depth {depth_mm:.1f}mm exceeds available "
                    f"{target_geom.max_available_depth_mm():.1f}mm in {target_view} view."
                ),
            )

        # Project: same depth from nipple in target view
        proj_x_px = target_geom.project_depth_to_pixel_x(depth_mm)

        # Vertical position: use relative offset from nipple with attenuation.
        # CC→MLO and MLO→CC vertical mapping is inherently ambiguous because
        # the views are orthogonal projections. We apply a conservative estimate.
        source_height_mm = source_geom.compute_lesion_height_mm(source_lesion)
        if source_view == 'CC' and target_view == 'MLO':
            # CC vertical → MLO vertical: moderate attenuation (50%)
            target_height_mm = source_height_mm * 0.5
        elif source_view == 'MLO' and target_view == 'CC':
            # MLO vertical → CC vertical: moderate attenuation (30%)
            target_height_mm = source_height_mm * 0.3
        else:
            target_height_mm = source_height_mm * 0.4

        proj_y_mm = target_geom.nipple.y_mm + target_height_mm
        proj_y_px = proj_y_mm / target_geom.image.pixel_spacing.y

        # Compute projected box size (preserve physical size)
        box_width_mm = source_lesion.width_mm
        box_height_mm = source_lesion.height_mm
        box_w_px = box_width_mm / target_geom.image.pixel_spacing.x
        box_h_px = box_height_mm / target_geom.image.pixel_spacing.y

        # Clamp to image boundaries
        proj_x_px = max(box_w_px / 2, min(target_geom.image.width_px - box_w_px / 2, proj_x_px))
        proj_y_px = max(box_h_px / 2, min(target_geom.image.height_px - box_h_px / 2, proj_y_px))

        # Build the projected LesionLocation
        x1 = proj_x_px - box_w_px / 2
        y1 = proj_y_px - box_h_px / 2
        x2 = proj_x_px + box_w_px / 2
        y2 = proj_y_px + box_h_px / 2

        # Clamp final coords
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(target_geom.image.width_px, x2)
        y2 = min(target_geom.image.height_px, y2)

        projected_lesion = LesionLocation.from_pixel_box(
            [x1, y1, x2, y2],
            target_geom.image.pixel_spacing,
            score=0.0,
        )

        return CursorMatch(
            source_view=source_view,
            source_lesion=source_lesion,
            target_view=target_view,
            target_lesion=projected_lesion,
            match_type='projected',
            depth_mm=depth_mm,
            confidence=0.6,
            message=f"3D Cursor projected at depth {depth_mm:.1f}mm from nipple.",
        )

    def _project_lesion_with_arc(
        self,
        source_lesion: LesionLocation,
        source_geom: MammogramGeometry,
        target_geom: MammogramGeometry,
        source_view: str,
        target_view: str,
        pectoral_angle_deg: Optional[float] = None,
        breast_contour: Optional[object] = None,
    ) -> CursorMatch:
        """
        Project a lesion using the correspondence arc method.

        Instead of a single point, this computes a geometrically valid arc
        representing all possible lesion locations in the target view.

        Args:
            source_lesion: Lesion in source view.
            source_geom: Geometry of source view.
            target_geom: Geometry of target view.
            source_view: 'CC' or 'MLO'
            target_view: 'CC' or 'MLO'
            pectoral_angle_deg: Detected pectoral angle (if available).
            breast_contour: Breast tissue contour for clipping.

        Returns:
            CursorMatch with correspondence_arc field populated.
        """
        # Compute the correspondence arc
        arc = compute_correspondence_arc(
            source_lesion=source_lesion,
            source_geom=source_geom,
            target_geom=target_geom,
            source_view=source_view,
            target_view=target_view,
            pectoral_angle_deg=pectoral_angle_deg,
            breast_contour=breast_contour,
            angular_resolution_deg=1.0,
            angle_margin_deg=30.0,
        )

        # If arc computation succeeded and we have valid points
        if arc.best_point_px is not None:
            # Build a bounding box around the best point
            best_x, best_y = arc.best_point_px

            # ── VALIDATE projected point against bounds + contour ──
            full_validation = validate_projected_point(
                point_px=(best_x, best_y),
                image_width=target_geom.image.width_px,
                image_height=target_geom.image.height_px,
                breast_contour=breast_contour,
                pectoral_angle_deg=pectoral_angle_deg,
                source_depth_mm=arc.radius_mm,
                source_view=source_view,
                target_view=target_view,
            )

            # Log diagnostic line
            pec_valid = getattr(self, '_last_pectoral_validation', None)
            calc_log = format_calc_log(
                source_view=source_view,
                target_view=target_view,
                depth_mm=arc.radius_mm,
                pectoral_angle_deg=pectoral_angle_deg,
                pectoral_valid=pec_valid.is_valid if pec_valid else True,
                clamped_angle_deg=pec_valid.angle_deg if pec_valid else pectoral_angle_deg,
                target_point_px=(best_x, best_y),
                in_bounds=full_validation.bounds_validation.is_valid if full_validation.bounds_validation else True,
                in_contour=full_validation.contour_validation.is_valid if full_validation.contour_validation else True,
                final_point_px=full_validation.final_point_px,
            )
            print(calc_log)

            # Use the validated (possibly clamped) point
            final_x, final_y = full_validation.final_point_px

            # Use source lesion dimensions
            box_width_mm = source_lesion.width_mm
            box_height_mm = source_lesion.height_mm
            box_w_px = box_width_mm / target_geom.image.pixel_spacing.x
            box_h_px = box_height_mm / target_geom.image.pixel_spacing.y

            x1 = final_x - box_w_px / 2
            y1 = final_y - box_h_px / 2
            x2 = final_x + box_w_px / 2
            y2 = final_y + box_h_px / 2

            # Clamp to image boundaries
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(target_geom.image.width_px, x2)
            y2 = min(target_geom.image.height_px, y2)

            projected_lesion = LesionLocation.from_pixel_box(
                [x1, y1, x2, y2],
                target_geom.image.pixel_spacing,
                score=0.0,
            )

            # Build message with any warnings
            msg = arc.message
            if full_validation.any_warning:
                msg += f" | VALIDATION: {full_validation.combined_warning}"

            return CursorMatch(
                source_view=source_view,
                source_lesion=source_lesion,
                target_view=target_view,
                target_lesion=projected_lesion,
                match_type='arc_projected',
                depth_mm=arc.radius_mm,
                confidence=arc.confidence * (0.6 if full_validation.any_warning else 1.0),
                correspondence_arc=arc,
                message=msg,
            )
        else:
            # Arc computation failed → fallback to out_of_field
            depth_mm = source_geom.compute_lesion_depth_mm(source_lesion)
            return CursorMatch(
                source_view=source_view,
                source_lesion=source_lesion,
                target_view=target_view,
                target_lesion=None,
                match_type='out_of_field',
                depth_mm=depth_mm,
                confidence=0.0,
                correspondence_arc=arc,
                message=arc.message,
            )

    def _extract_pectoral_angle(self, view: ViewData, laterality: str) -> Optional[float]:
        """
        Extract the pectoral muscle angle from an MLO view.

        Includes clinical range validation (15°–60°). If the detected angle falls
        outside this range, it is clamped and a warning is logged.

        Args:
            view: ViewData for MLO view.
            laterality: 'R' or 'L'

        Returns:
            Validated pectoral angle in degrees from vertical, or None if detection failed.
        """
        if view.view_position != 'MLO':
            return None

        # Try to load image for pectoral detection
        try:
            import pydicom
            import numpy as np

            ds = pydicom.dcmread(view.dicom_path)
            image = ds.pixel_array.astype(np.uint8)

            # Detect pectoral angle
            pectoral_line = detect_pectoral_angle(
                image=image,
                laterality=laterality,
            )

            if pectoral_line is not None:
                raw_angle = pectoral_line.angle_deg
                print(f"[3D-Cursor] Detected pectoral angle (raw): {raw_angle:.1f}°")

                # ── VALIDATE against clinical range ──
                validation = validate_pectoral_angle(raw_angle)
                if not validation.is_valid:
                    print(f"[3D-Cursor][WARN] {validation.warning_message}")
                    print(f"[3D-Cursor][WARN] Pectoral angle clamped: "
                          f"{raw_angle:.1f}° -> {validation.angle_deg:.1f}°")
                else:
                    print(f"[3D-Cursor] Pectoral angle validated OK: {validation.angle_deg:.1f}°")

                # Store validation result for downstream use
                self._last_pectoral_validation = validation
                return validation.angle_deg
            else:
                # Use fallback estimate
                angle = estimate_pectoral_angle_fallback(laterality, view.view_position)
                print(f"[3D-Cursor] Using fallback pectoral angle: {angle:.1f}°")
                self._last_pectoral_validation = validate_pectoral_angle(angle)
                return angle

        except Exception as e:
            print(f"[3D-Cursor] Pectoral angle detection failed: {e}")
            # Use fallback
            angle = estimate_pectoral_angle_fallback(laterality, view.view_position)
            self._last_pectoral_validation = validate_pectoral_angle(angle)
            return angle

    def _extract_breast_contour(self, view: ViewData) -> Optional[object]:
        """
        Extract the breast tissue contour from a mammogram view.

        Args:
            view: ViewData for the view.

        Returns:
            Breast contour (numpy array) or None if segmentation failed.
        """
        if view.dicom_path is None:
            return None

        try:
            import pydicom
            import numpy as np

            ds = pydicom.dcmread(view.dicom_path)
            image = ds.pixel_array.astype(np.uint8)

            # Segment breast contour
            contour = segment_breast_contour(image)

            if contour is not None:
                print(f"[3D-Cursor] Breast contour extracted: {len(contour)} points")
            else:
                print(f"[3D-Cursor] Breast contour segmentation failed")

            return contour

        except Exception as e:
            print(f"[3D-Cursor] Breast contour extraction failed: {e}")
            return None
