"""
Stage 1 of the Two-Stage 3D Cursor — the predicted SEARCH REGION.

Given a lesion detected in ONE mammographic view, produce a *region* in the other
view where the corresponding lesion is expected to lie. The output is deliberately
NOT a point: the CC->MLO mapping is under-determined, and every published method
predicts a curve/band, never a coordinate.

WHY THIS MODULE EXISTS (and why it does not just reuse correspondence_arc.py)
────────────────────────────────────────────────────────────────────────────────
The legacy `correspondence_arc.compute_correspondence_arc()` draws an ANNULAR BAND
(an arc centred on the nipple) but feeds it the STRAIGHT STRIP radius
(`compute_lesion_depth_mm`, the axial/perpendicular component `dl`). That is a
chimera: it honours neither method's assumption. It also mirrors the arc to the
wrong side for LEFT breasts. Both defects are avoided here.

The two published loci (Zheng et al., Acad Radiol 2009; Wang et al., BMC Med
Imaging 2025):

  • SS — Straight Strip (DEFAULT here).
        Assumes the AXIAL distance `dl` — the lesion's projection onto the
        centreline through the nipple, perpendicular to the chest wall — is
        preserved across views. Locus = a straight line perpendicular to that
        centreline, at distance `dl` from the nipple.

  • AB — Annular Band (secondary/overlay only).
        Assumes the RADIAL distance `dr` (= Kopans nipple-to-lesion distance) is
        preserved. Locus = an arc centred on the nipple with radius `dr`.

SS is the DEFAULT because two independent cohorts agree it is more accurate:
    - Zheng 2009 (n=200): search width to capture ALL pairs — SS 28 mm vs AB 68 mm;
      CAD false-positives eliminated — SS 25.0 % vs AB 11.9 %.
    - Wang 2025 (n=711): median absolute error — SS 4.59 mm vs AB 5.78 mm;
      cross-view correlation — axial 0.923 vs radial 0.917.

Purity: stdlib + math only. NO Qt, NO VTK, NO numpy, NO pydicom. This module must
stay unit-testable in the offscreen sandbox lane.

Units: all internal geometry is in millimetres. Pixels appear only at the
boundary (`points_px`), converted per-axis so anisotropic PixelSpacing is honoured.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .geometry import LesionLocation, MammogramGeometry


# ─── Band widths ─────────────────────────────────────────────────────────────
#
# These are the half-widths of the predicted region, in mm.
#
#   inner  = "high confidence" band. Literature SS interquartile upper bound ~8 mm.
#   outer  = "search" band.          Literature SS maximum absolute error ~32 mm.
#
# IMPORTANT: these defaults are LITERATURE-DERIVED PLACEHOLDERS. They are the
# sanity check, not the source of truth. They MUST be replaced by the values
# measured on our own labelled set (see the accuracy plan, Phase 0/3). Until then
# they are deliberately WIDE — an honest wide band is safe; a narrow confident
# band around an uncertain prediction is not.
#
_DEFAULT_INNER_BAND_MM = float(os.getenv("AIPACS_CURSOR3D_INNER_BAND_MM", "8.0"))
_DEFAULT_OUTER_BAND_MM = float(os.getenv("AIPACS_CURSOR3D_OUTER_BAND_MM", "32.0"))

# Sampling step along the locus, in mm.
_LOCUS_STEP_MM = 0.5

# Method selector: 'gm' (default) | 'ss' | 'ab'.
#
# GM (the geometric model) is the DEFAULT as of 2026-07-15, promoted after it was
# validated live on patient 50258 in BOTH directions: the geometry error collapsed
# from SS's 18.0 / 11.5 mm to 4.5 / 2.96 mm (matching the literature's ~3 mm GM
# median), flipping a wrong `no_match` into real, honestly-presented candidates.
# SS remains the one-env-var kill switch: `AIPACS_CURSOR3D_LOCUS=ss`. A guard test
# (test_gm_and_ss_agree_for_a_lesion_on_the_nipple_line) pins that GM does not
# regress the easy on-nipple-line case where SS's tilt does no harm.
_DEFAULT_METHOD = os.getenv("AIPACS_CURSOR3D_LOCUS", "gm").strip().lower()

# Angular half-span of the AB arc, in degrees (only used when method includes 'ab').
_AB_HALF_SPAN_DEG = 70.0


# ─── Result ──────────────────────────────────────────────────────────────────

@dataclass
class SearchRegion:
    """
    The predicted region for the corresponding lesion in the TARGET view.

    `points_px` is the nominal locus (the curve/line itself) — this is what the
    renderer draws and what the absolute-error metric measures against.

    `distance_mm(point_px)` gives the signed-magnitude deviation of an arbitrary
    point from the locus. That single function is used for three different things:
        1. the accuracy metric (absolute error vs a known ground-truth lesion),
        2. candidate scoring in Stage 2,
        3. the "is this inside the region?" test.
    Keeping them on ONE definition is what stops the three from drifting apart.
    """
    method: str                       # 'ss' | 'ab'
    source_view: str                  # 'CC' | 'MLO'
    target_view: str                  # 'CC' | 'MLO'
    laterality: str                   # 'R' | 'L'

    # The preserved quantity that generated this locus.
    distance_mm: float                # dl for SS, dr for AB
    distance_kind: str                # 'axial' | 'radial'

    # Band half-widths (mm).
    inner_band_mm: float
    outer_band_mm: float

    # The locus, in target-view pixel coordinates.
    points_px: List[Tuple[float, float]] = field(default_factory=list)

    # The single most-likely point (locus midpoint). ADVISORY ONLY — the whole
    # point of this module is that a point is not a defensible answer.
    nominal_point_px: Optional[Tuple[float, float]] = None

    # Geometry needed to score arbitrary points against this locus.
    _nipple_mm: Tuple[float, float] = (0.0, 0.0)
    _normal: Tuple[float, float] = (1.0, 0.0)
    _spacing: Tuple[float, float] = (1.0, 1.0)

    ok: bool = True
    message: str = ""

    # PNL cross-view depth-normalisation diagnostic (a pnl_normalization.PnlResult
    # or None). Populated for GM regions so the controller can log the legacy-vs-
    # normalised depths and persist them for live validation — independent of
    # whether the normalisation is actually applied (that is the flag's job).
    pnl: Optional[object] = None

    @property
    def is_empty(self) -> bool:
        return not self.points_px

    def deviation_mm(self, point_px: Tuple[float, float]) -> float:
        """
        Shortest distance (mm) from an arbitrary point to this locus.

        For SS this is the axial-distance error:    | (P - nipple).n  -  dl |
        For GM this is the anterior-distance error: | (P - nipple).p  -  a  |  (n = p_hat)
        For AB this is the radial-distance error:   | ||P - nipple||  -  dr |

        SS and GM share this closed form — they differ only in the axis `n` (SS uses
        the pectoral-tilted depth normal; GM the untilted anterior axis) and the
        preserved distance. It is EXACT for a straight locus (GM's default) and a
        close approximation for a mildly-bowed GM curve. Computed against the true
        (infinite) locus, not the clipped `points_px`, so a lesion beyond the clipped
        end still gets an honest deviation instead of one inflated to the clip point.
        """
        px, py = point_px
        sx, sy = self._spacing
        x_mm = px * sx
        y_mm = py * sy
        nx_mm, ny_mm = self._nipple_mm
        dx = x_mm - nx_mm
        dy = y_mm - ny_mm

        if self.method == "ab":
            return abs(math.hypot(dx, dy) - self.distance_mm)

        nx, ny = self._normal
        axial = dx * nx + dy * ny
        return abs(axial - self.distance_mm)

    def contains(self, point_px: Tuple[float, float], *, band: str = "outer") -> bool:
        """Is `point_px` inside the inner (high-confidence) or outer (search) band?"""
        limit = self.inner_band_mm if band == "inner" else self.outer_band_mm
        return self.deviation_mm(point_px) <= limit

    def height_offset_mm(self, point_px: Tuple[float, float]) -> float:
        """
        Position of `point_px` ALONG the locus (the tangential / height axis), in mm,
        signed, relative to the nipple. This is the axis ORTHOGONAL to `deviation_mm`
        (which measures across the locus): deviation is 'how far off the strip', this
        is 'how far up/down the strip'.

        Factor 2 of the heatmap — the medial-lateral → MLO-height prior — compares a
        candidate's height_offset to the nominal point's height_offset.
        """
        px, py = point_px
        sx, sy = self._spacing
        dx = px * sx - self._nipple_mm[0]
        dy = py * sy - self._nipple_mm[1]
        # Tangential unit vector = perpendicular to the (anterior/depth) normal.
        nx, ny = self._normal
        tx, ty = (-ny, nx)
        return dx * tx + dy * ty

    def nominal_height_mm(self) -> Optional[float]:
        """height_offset_mm of the nominal point (the most-likely locus position)."""
        if self.nominal_point_px is None:
            return None
        return self.height_offset_mm(self.nominal_point_px)

    def band_points_px(self, offset_mm: float) -> List[Tuple[float, float]]:
        """
        The locus shifted by `offset_mm` along its own normal — used to draw the
        band edges. For SS this translates the line; for AB it changes the radius.
        """
        if self.is_empty:
            return []
        sx, sy = self._spacing
        out: List[Tuple[float, float]] = []
        if self.method == "ab":
            nx_mm, ny_mm = self._nipple_mm
            r = self.distance_mm + offset_mm
            if r <= 0:
                return []
            for px, py in self.points_px:
                dx = px * sx - nx_mm
                dy = py * sy - ny_mm
                h = math.hypot(dx, dy)
                if h < 1e-9:
                    continue
                x_mm = nx_mm + dx / h * r
                y_mm = ny_mm + dy / h * r
                out.append((x_mm / sx, y_mm / sy))
            return out

        nx, ny = self._normal
        for px, py in self.points_px:
            x_mm = px * sx + nx * offset_mm
            y_mm = py * sy + ny * offset_mm
            out.append((x_mm / sx, y_mm / sy))
        return out


# ─── Stage 1 entry point ─────────────────────────────────────────────────────

def compute_search_region(
    source_lesion: LesionLocation,
    source_geom: MammogramGeometry,
    target_geom: MammogramGeometry,
    *,
    method: Optional[str] = None,
    inner_band_mm: Optional[float] = None,
    outer_band_mm: Optional[float] = None,
    breast_contour=None,
) -> SearchRegion:
    """
    Compute the predicted search region in the TARGET view for a lesion seen in
    the SOURCE view.

    Args:
        source_lesion: the AI-detected (or human-drawn) lesion in the source view.
        source_geom:   source view geometry (nipple, spacing, laterality, pectoral).
        target_geom:   target view geometry.
        method:        'ss' (default), 'ab', or None to read the env default.
        inner/outer_band_mm: band half-widths; None -> module defaults.
        breast_contour: optional OpenCV-style contour for the target view. When
                        supplied, locus points outside the breast tissue are
                        dropped. Passed through untouched — this module never
                        imports cv2 itself (purity), the caller does the seg.

    Returns:
        SearchRegion. Always returns an object; check `.ok` / `.is_empty`.
    """
    m = (method or _DEFAULT_METHOD or "ss").strip().lower()
    if m not in ("ss", "ab", "gm"):
        m = "ss"

    inner = _DEFAULT_INNER_BAND_MM if inner_band_mm is None else float(inner_band_mm)
    outer = _DEFAULT_OUTER_BAND_MM if outer_band_mm is None else float(outer_band_mm)
    if outer < inner:
        outer = inner

    spacing = (target_geom.image.pixel_spacing.x, target_geom.image.pixel_spacing.y)
    nipple_mm = (target_geom.nipple.x_mm, target_geom.nipple.y_mm)
    normal = target_geom.depth_normal_unit_vector()
    gm_nominal = None
    gm_pnl = None

    if m == "ab":
        distance = source_geom.compute_lesion_radial_distance_mm(source_lesion)
        kind = "radial"
        points = _sample_arc_points_px(distance, target_geom)
    elif m == "gm":
        # GM (geometric model) — imported lazily so this stdlib module stays
        # importable even if the GM file is absent in a stripped build.
        from .geometric_model import (
            sample_gm_points_px, _anterior_axis, raw_anterior_distance_mm,
        )
        from .pnl_normalization import compute_pnl_normalization
        # Diagnostic: legacy-vs-PNL-normalised depth (attached below, always —
        # so the user can validate live even with the flag off).
        gm_pnl = compute_pnl_normalization(
            source_lesion, source_geom, target_geom,
            horizontal_a_src_mm=raw_anterior_distance_mm(source_lesion, source_geom),
        )
        points, distance, gm_nominal = sample_gm_points_px(
            source_lesion, source_geom, target_geom
        )
        kind = "anterior"
        # The GM band brackets the ANTERIOR direction (the locus runs tangentially),
        # so the deviation/band machinery must use the untilted anterior axis — NOT
        # the pectoral-tilted depth normal that SS uses.
        normal = _anterior_axis(target_geom)[0]
    else:
        distance = source_geom.compute_lesion_depth_mm(source_lesion)
        kind = "axial"
        points = _sample_strip_points_px(distance, target_geom)

    region = SearchRegion(
        method=m,
        source_view=source_geom.view_position,
        target_view=target_geom.view_position,
        laterality=target_geom.laterality,
        distance_mm=distance,
        distance_kind=kind,
        inner_band_mm=inner,
        outer_band_mm=outer,
        points_px=points,
        _nipple_mm=nipple_mm,
        _normal=normal,
        _spacing=spacing,
        pnl=gm_pnl,
    )

    if breast_contour is not None and points:
        kept = _clip_points_to_contour(points, breast_contour)
        # Only accept the clip if it left us something usable. A failed/empty
        # segmentation must never silently erase the region — an empty region
        # would be indistinguishable from "no correspondence exists".
        if kept:
            region.points_px = kept

    if not region.points_px:
        region.ok = False
        region.message = (
            f"Predicted {kind} distance {distance:.1f} mm falls outside the "
            f"{target_geom.view_position} image field."
        )
        return region

    # GM has a principled nominal (the obliquity projection at zero source-beam
    # depth); SS/AB use the locus midpoint.
    if m == "gm" and gm_nominal is not None:
        region.nominal_point_px = gm_nominal
    else:
        region.nominal_point_px = region.points_px[len(region.points_px) // 2]

    _label = {"ss": "Straight strip", "ab": "Annular band", "gm": "Geometric model"}[m]
    region.message = (
        f"{_label} at {kind} distance {distance:.1f} mm from the nipple "
        f"(band ±{inner:.0f}/±{outer:.0f} mm)."
    )
    return region


# ─── Locus samplers ──────────────────────────────────────────────────────────

def _sample_strip_points_px(
    distance_mm: float,
    geom: MammogramGeometry,
) -> List[Tuple[float, float]]:
    """
    SS locus: the line perpendicular to the chest-wall normal, at `distance_mm`
    from the nipple along that normal.

        foot = nipple + n * dl
        line = foot + t * perp(n)

    Sampled in mm and converted per-axis, so anisotropic PixelSpacing is honoured
    (the legacy arc collapsed spacing to a scalar average, distorting the locus).
    """
    nx, ny = geom.depth_normal_unit_vector()
    n_x_mm = geom.nipple.x_mm
    n_y_mm = geom.nipple.y_mm

    foot_x = n_x_mm + nx * distance_mm
    foot_y = n_y_mm + ny * distance_mm

    # Direction along the strip = perpendicular to the depth normal.
    px_dir, py_dir = (-ny, nx)

    w_mm = geom.image.width_mm
    h_mm = geom.image.height_mm
    sx = geom.image.pixel_spacing.x
    sy = geom.image.pixel_spacing.y

    # Sweep t far enough to cross the image in any orientation, keep what lands
    # inside. Cheap, exact, and free of line-clipping edge cases.
    max_t = math.hypot(w_mm, h_mm)
    steps = int((2.0 * max_t) / _LOCUS_STEP_MM) + 1

    points: List[Tuple[float, float]] = []
    for i in range(steps):
        t = -max_t + i * _LOCUS_STEP_MM
        x_mm = foot_x + px_dir * t
        y_mm = foot_y + py_dir * t
        if 0.0 <= x_mm <= w_mm and 0.0 <= y_mm <= h_mm:
            points.append((x_mm / sx, y_mm / sy))
    return points


def _sample_arc_points_px(
    radius_mm: float,
    geom: MammogramGeometry,
) -> List[Tuple[float, float]]:
    """
    AB locus: arc centred on the nipple, radius = the RADIAL distance `dr`.

    LEFT/RIGHT CORRECTNESS — the defect this replaces:
        The legacy code used `center_angle = chest_wall_angle - theta_pec` for BOTH
        sides. For a LEFT breast (chest_wall_angle = pi) that yields sin > 0, i.e.
        the arc swept INFERIORLY — the opposite of the anatomy, and the opposite of
        the code's own comment. The pectoral muscle is superior in both MLO views.

        Here the arc centre is taken directly from `depth_normal_unit_vector()` —
        the same laterality-aware, pectoral-tilted vector the SS strip uses. There
        is exactly one definition of "toward the chest wall" in this module, so
        the two loci cannot disagree, and L/R cannot diverge.
    """
    if radius_mm <= 0:
        return []

    nx, ny = geom.depth_normal_unit_vector()
    centre_angle = math.atan2(ny, nx)
    half = math.radians(_AB_HALF_SPAN_DEG)

    n_x_mm = geom.nipple.x_mm
    n_y_mm = geom.nipple.y_mm
    w_mm = geom.image.width_mm
    h_mm = geom.image.height_mm
    sx = geom.image.pixel_spacing.x
    sy = geom.image.pixel_spacing.y

    # Angular step that yields ~_LOCUS_STEP_MM arc length.
    step = _LOCUS_STEP_MM / max(radius_mm, 1e-6)
    steps = int((2.0 * half) / step) + 1

    points: List[Tuple[float, float]] = []
    for i in range(steps):
        a = centre_angle - half + i * step
        x_mm = n_x_mm + radius_mm * math.cos(a)
        y_mm = n_y_mm + radius_mm * math.sin(a)
        if 0.0 <= x_mm <= w_mm and 0.0 <= y_mm <= h_mm:
            points.append((x_mm / sx, y_mm / sy))
    return points


def _clip_points_to_contour(
    points_px: Sequence[Tuple[float, float]],
    contour,
) -> List[Tuple[float, float]]:
    """
    Drop locus points outside the breast tissue.

    cv2 is imported lazily and failure is non-fatal: if OpenCV is missing or the
    contour is malformed we return the points UNCHANGED rather than an empty list.
    Losing the region entirely because a segmentation hiccuped would be a far worse
    failure than showing a slightly over-long strip.
    """
    try:
        import cv2  # noqa: WPS433 (lazy on purpose — keeps this module pure to import)
    except Exception:
        return list(points_px)

    try:
        kept = [
            (x, y)
            for (x, y) in points_px
            if cv2.pointPolygonTest(contour, (float(x), float(y)), False) >= 0
        ]
        return kept
    except Exception:
        return list(points_px)


# ─── Accuracy metric (Phase 0 of the accuracy plan) ──────────────────────────

def absolute_error_mm(
    region: SearchRegion,
    true_lesion_center_px: Tuple[float, float],
) -> float:
    """
    The published accuracy metric: the shortest distance from the TRUE lesion
    centre to the predicted locus, in mm.

    This is exactly the "absolute error (AE)" of Wang et al. 2025 and the matching
    error of Zheng et al. 2009, so numbers produced here are directly comparable to
    the literature:

        method   median AE      >10 mm failures
        ------   ---------      ---------------
        GM        3.03 mm             7 %
        SS        4.59 mm          15.5 %
        AB        5.78 mm          27.4 %

    Use it to (a) baseline the current locus, (b) prove any change is an
    improvement, and (c) calibrate the band widths from our own data.
    """
    return region.deviation_mm(true_lesion_center_px)
