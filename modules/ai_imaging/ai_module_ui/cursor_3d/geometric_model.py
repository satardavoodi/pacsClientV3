"""
GM — the Geometric Model locus (accuracy-plan Phase 4 / the "GM upgrade").

The Straight-Strip (SS) and Annular-Band (AB) loci are 2-D→2-D heuristics: SS
assumes the pectoral-tilted AXIAL distance is preserved, AB assumes the RADIAL
(Kopans) distance is preserved. Both fail in a predictable regime — a lesion far
SUPERIOR to the nipple, where the MLO obliquity projects the vertical offset into
the "axial" measure. That is exactly the 50258 failure: the source lesion is
36.6 mm axial from the nipple in CC, but the SS strip lands 18–25 mm from the true
corresponding detections in MLO, and NO pectoral angle rescues it (tested 15–50°;
the error only grows).

The Geometric Model (Duan et al., IEEE Access 2019; Wang et al., BMC Med Imaging
2025 — median absolute error 3.03 mm vs SS 4.59 / AB 5.78) fixes this by going
through a 3-D intermediate instead of a flat 2-D assumption:

    1. Reconstruct the lesion's position in an (uncompressed) 3-D breast frame
       anchored at the nipple, from the source view. Two coordinates are known
       (anterior-posterior depth + in-plane tangential); the third (the depth along
       the source X-ray beam) is UNKNOWN and sweeps the breast thickness.
    2. ROTATE that frame by the CC↔MLO obliquity about the anterior-posterior axis
       (this is the step SS/AB skip — it is what mixes the source's tangential and
       the unknown depth into the target's tangential).
    3. PROJECT into the target view. The unknown depth traces a CURVE (Duan fits it
       with a quadratic; we sample it densely and expose the same polyline the
       renderer / matcher / AE-harness already consume).

THE KEY PROPERTY — and why it beats SS on 50258:
The anterior-posterior distance (nipple → lesion, toward the chest wall) is a
physical 3-D length; rotation about the anterior axis does NOT change it. GM
preserves it along the target's OWN anterior axis (the horizontal nipple line),
instead of SS's pectoral-tilted axis. So the locus sits at the correct anterior
depth regardless of the pectoral angle, and spans the superior-inferior extent as
the free (depth) parameter — reaching the superior detection SS could not.

Purity: stdlib + math only. NO Qt/VTK/numpy/pydicom. Slots into `SearchRegion`
via `search_region.compute_search_region(method="gm")`.

Units: millimetres internally; pixels only at the boundary, per-axis (anisotropic
PixelSpacing honoured).
"""

from __future__ import annotations

import math
import os
from typing import List, Optional, Tuple

from .geometry import LesionLocation, MammogramGeometry


# Default CC↔MLO obliquity (degrees) when it cannot be inferred. The MLO is
# acquired ~40–60° from the CC; the exact value only sets the nominal (most-likely)
# point and the sweep rate — NOT the anterior placement — so GM is far less
# sensitive to it than SS is to the pectoral angle.
_DEFAULT_OBLIQUITY_DEG = float(os.getenv("AIPACS_CURSOR3D_GM_OBLIQUITY_DEG", "45.0"))

# Quadratic bow of the locus (Duan's curve). 0.0 = straight line (the dominant
# correction is the anterior preservation; the bow is a second-order refinement
# that needs the labelled-set calibration before it is trusted). Kept small.
_DEFAULT_CURVATURE = float(os.getenv("AIPACS_CURSOR3D_GM_CURVATURE", "0.0"))

# Sampling step along the locus, in mm.
_STEP_MM = 0.5


def _anterior_axis(geom: MammogramGeometry) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    (p_hat, t_hat) unit vectors for a view, in image mm coordinates.

        p_hat = anterior→posterior: from the nipple toward the CHEST-WALL EDGE
                of the image. Horizontal. L breast → chest wall on the left → (-1, 0);
                R breast → (+1, 0).
        t_hat = the in-image perpendicular (tangential): (0, +1) = inferior (image y
                grows downward). In CC this is medial-lateral; in MLO superior-inferior.

    NOTE — this is deliberately the UNTILTED horizontal, unlike the SS strip which
    tilts by the pectoral angle. Preserving the anterior distance along this axis is
    the GM's core correction (verified on 50258: CC 36.6 mm ≈ MLO 39 mm horizontal,
    vs 55 mm under the pectoral tilt).
    """
    if str(geom.laterality).upper().startswith("L"):
        p_hat = (-1.0, 0.0)
    else:
        p_hat = (1.0, 0.0)
    t_hat = (0.0, 1.0)
    return p_hat, t_hat


def _resolve_obliquity_deg(target_geom: MammogramGeometry, obliquity_deg: Optional[float]) -> float:
    """Obliquity used for the rotation. Explicit value wins; else the target's
    pectoral angle if in a sane band; else the default. Clamped to [15, 75]."""
    if obliquity_deg is not None:
        theta = float(obliquity_deg)
    else:
        pec = getattr(target_geom, "pectoral_angle_deg", None)
        if pec is not None and 15.0 <= float(pec) <= 75.0:
            theta = float(pec)
        else:
            theta = _DEFAULT_OBLIQUITY_DEG
    return max(15.0, min(75.0, theta))


def raw_anterior_distance_mm(
    source_lesion: LesionLocation,
    source_geom: MammogramGeometry,
) -> float:
    """
    The GM anterior depth (untilted horizontal nipple→lesion), in mm — the value
    GM preserves absolutely by default. Extracted so both `sample_gm_points_px` and
    the PNL diagnostic in `search_region` derive it from ONE definition.
    """
    p_src, _ = _anterior_axis(source_geom)
    lc = source_lesion.center_mm
    dx = lc[0] - source_geom.nipple.x_mm
    dy = lc[1] - source_geom.nipple.y_mm
    return abs(dx * p_src[0] + dy * p_src[1])


def sample_gm_points_px(
    source_lesion: LesionLocation,
    source_geom: MammogramGeometry,
    target_geom: MammogramGeometry,
    *,
    obliquity_deg: Optional[float] = None,
    curvature: float = _DEFAULT_CURVATURE,
    step_mm: float = _STEP_MM,
) -> Tuple[List[Tuple[float, float]], float, Optional[Tuple[float, float]]]:
    """
    Build the GM locus in TARGET-view pixel coordinates.

    Returns (points_px, anterior_distance_mm, nominal_point_px):
      * points_px  — the sampled locus (the curve), clipped to the target image.
      * anterior_distance_mm — the preserved nipple→lesion anterior depth (the
        quantity the band brackets; analogous to SS's `dl` / AB's `dr`).
      * nominal_point_px — the single most-likely point (the projection at zero
        source-beam depth), advisory only.
    """
    sx = target_geom.image.pixel_spacing.x
    sy = target_geom.image.pixel_spacing.y

    # --- 1. Decompose the source lesion into anterior (a) + tangential (t), mm ---
    p_src, t_src_hat = _anterior_axis(source_geom)
    lc = source_lesion.center_mm
    dx = lc[0] - source_geom.nipple.x_mm
    dy = lc[1] - source_geom.nipple.y_mm
    a_src = dx * p_src[0] + dy * p_src[1]            # anterior depth (preserved)
    t_src = dx * t_src_hat[0] + dy * t_src_hat[1]    # in-plane tangential

    a_src = abs(a_src)  # depth toward the chest wall is a magnitude

    # --- 1b. OPTIONAL PNL normalisation (flag-gated, default OFF) ---------------
    # Replace the ABSOLUTE preserved depth with the depth renormalised to the
    # target view's own breast-depth scale (nipple→pectoral PNL ratio). Only when
    # the flag is on AND both pectoral references exist (the MLO pectoral line was
    # drawn); otherwise a_src is untouched → byte-identical legacy GM. Only the
    # anterior depth is scaled; the tangential (t_src, the height axis) is never
    # touched, so the locus ORIENTATION and factor-2 height prior are unchanged.
    from .pnl_normalization import compute_pnl_normalization, pnl_normalize_enabled
    _pnl = compute_pnl_normalization(
        source_lesion, source_geom, target_geom, horizontal_a_src_mm=a_src
    )
    if pnl_normalize_enabled() and _pnl.available:
        a_src = _pnl.a_normalized_mm

    # --- 2. Rotate CC↔MLO by the obliquity about the anterior axis ---
    theta = math.radians(_resolve_obliquity_deg(target_geom, obliquity_deg))
    cos_t = math.cos(theta)
    # Nominal target tangential (source-beam depth d = 0): T0 = t_src·cosθ.
    t0_tgt = t_src * cos_t

    # --- 3. Project: sweep the target tangential over the image, at anterior a_src ---
    p_tgt, t_tgt_hat = _anterior_axis(target_geom)
    n_x = target_geom.nipple.x_mm
    n_y = target_geom.nipple.y_mm
    w_mm = target_geom.image.width_mm
    h_mm = target_geom.image.height_mm

    # Sweep t over a range that comfortably covers the breast in the tangential
    # (superior-inferior) direction; out-of-image points are dropped below.
    span = math.hypot(w_mm, h_mm)
    steps = int((2.0 * span) / step_mm) + 1
    # A normalisation scale for the (optional) quadratic bow.
    bow_scale = max(h_mm * 0.5, 1e-6)

    points: List[Tuple[float, float]] = []
    nominal: Optional[Tuple[float, float]] = None
    for i in range(steps):
        t_val = -span + i * step_mm
        # Optional Duan-style quadratic bow of the anterior depth away from centre.
        a_val = a_src * (1.0 + curvature * ((t_val - t0_tgt) / bow_scale) ** 2)
        x_mm = n_x + p_tgt[0] * a_val + t_tgt_hat[0] * t_val
        y_mm = n_y + p_tgt[1] * a_val + t_tgt_hat[1] * t_val
        if 0.0 <= x_mm <= w_mm and 0.0 <= y_mm <= h_mm:
            points.append((x_mm / sx, y_mm / sy))

    # Nominal = the projection at t = t0 (source-beam depth zero), if in-image.
    nx_mm = n_x + p_tgt[0] * a_src + t_tgt_hat[0] * t0_tgt
    ny_mm = n_y + p_tgt[1] * a_src + t_tgt_hat[1] * t0_tgt
    if 0.0 <= nx_mm <= w_mm and 0.0 <= ny_mm <= h_mm:
        nominal = (nx_mm / sx, ny_mm / sy)

    return points, a_src, nominal


def gm_normal_px_offset(
    target_geom: MammogramGeometry,
    offset_mm: float,
) -> Tuple[float, float]:
    """
    Pixel-space displacement of the GM band edge for a given anterior offset (mm).

    The GM locus runs tangentially, so its band brackets the ANTERIOR direction —
    the same `p_hat` used to build it. Returned as a (dx_px, dy_px) to add to each
    locus point. Used by SearchRegion.band_points_px for method='gm'.
    """
    p_tgt, _ = _anterior_axis(target_geom)
    return (p_tgt[0] * offset_mm / target_geom.image.pixel_spacing.x,
            p_tgt[1] * offset_mm / target_geom.image.pixel_spacing.y)
