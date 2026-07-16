"""
Three-factor cross-view localization heatmap.

Combines three independent signals into one confidence field over the TARGET view,
so the corresponding lesion is both scored (Stage 2 matching) and shown (heatmap):

  Factor 1 — GEOMETRIC (across the locus).
      How close a point is to the GM/SS locus. This is the well-constrained
      direction (the ±8/±32 mm band). `geometric_score`.

  Factor 2 — MEDIAL-LATERAL → MLO-HEIGHT (along the locus).
      The lesion's medial-lateral position in CC biases WHERE ALONG the locus it
      should sit: lateral-in-CC → higher in MLO, medial-in-CC → lower. This is the
      `x_CC·cos θ` term (the locus nominal). CRITICAL: on real data (50258) this
      term explains only ~34 % of the true height — the rest is the CC-invisible
      superior-inferior depth. So it is a WIDE, SOFT bias (large sigma), never a
      hard constraint. `height_score`.

  Factor 3 — APPEARANCE (histogram similarity).
      The source box's intensity signature (dense microcalc vs fatty lipoma vs
      iso/hyperdense mass) should recur in the true correspondence. Computed by
      `appearance_similarity.py` (pixels) and injected here as a value or map.

The SCORING helpers (`geometric_score`, `height_score`, `combine`) are PURE
(stdlib + math) so `candidate_matching` uses them with no numpy. The dense visual
FIELD builder uses numpy (it is a 2-D array) and is guarded to no-op without it.

Why a heatmap and not a narrower region (the 50258 lesson): the height factor
biases but cannot pin the height (~66 % is unobservable in CC), so the honest
output is a probability field — bright where all three factors agree, fading along
the epipolar/height direction — matching the published dual-view uncertainty
ellipse. Narrowing the geometry to the predicted height would REGRESS accuracy.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from .search_region import SearchRegion


# Wide by design — 50258 showed the height factor is only ~34 % reliable, so a
# candidate 35 mm off the predicted height still scores exp(-1)=0.37. Do NOT
# tighten this without the labelled set; a narrow height prior repeats the "pin
# the height" mistake.
_HEIGHT_SIGMA_MM = float(os.getenv("AIPACS_CURSOR3D_HEIGHT_SIGMA_MM", "35.0"))

# Default factor weights (the three the radiologist named). They renormalise over
# whatever is available, so 'appearance unavailable' does not dilute the ranking.
W_GEOMETRIC = float(os.getenv("AIPACS_CURSOR3D_W_GEOMETRIC", "0.50"))
W_HEIGHT = float(os.getenv("AIPACS_CURSOR3D_W_HEIGHT", "0.20"))
W_APPEARANCE = float(os.getenv("AIPACS_CURSOR3D_W_APPEARANCE", "0.30"))

# When the corresponding lesion is FOUND, the hot core is pulled onto it by a
# Gaussian of this width (mm). The geometric height along the band is a weak prior
# (superior-inferior is unobservable in CC), so the found detection — not the
# geometric nominal — should own the bright core. Wide enough to keep the band
# visible as the uncertainty; `=0` disables the pull (core stays at the nominal).
_EMPHASIS_SIGMA_MM = float(os.getenv("AIPACS_CURSOR3D_EMPHASIS_SIGMA_MM", "28.0"))


# ─── Factor 1 — geometric ────────────────────────────────────────────────────

def geometric_score(region: SearchRegion, point_px: Tuple[float, float]) -> float:
    """
    1.0 on the locus, ~0.5 at the inner-band edge, → 0 by the outer-band edge.
    Uses the region's OWN band widths so it recalibrates when the bands do.
    """
    dev = region.deviation_mm(point_px)
    inner = max(region.inner_band_mm, 1e-6)
    if dev <= inner:
        return 1.0 - 0.5 * (dev / inner)
    outer = max(region.outer_band_mm, inner + 1e-6)
    if dev >= outer:
        return 0.0
    return 0.5 * (1.0 - (dev - inner) / (outer - inner))


# ─── Factor 2 — medial-lateral → MLO height ──────────────────────────────────

def height_score(
    region: SearchRegion,
    point_px: Tuple[float, float],
    *,
    sigma_mm: float = _HEIGHT_SIGMA_MM,
) -> float:
    """
    Soft prior on WHERE ALONG the locus the point sits, peaked at the nominal
    (the `x_CC·cosθ` prediction), decaying with a WIDE sigma. Neutral 1.0 when the
    region has no nominal (can't bias) — so it never penalises in the absence of
    information.
    """
    nominal_h = region.nominal_height_mm()
    if nominal_h is None or sigma_mm <= 0:
        return 1.0
    cand_h = region.height_offset_mm(point_px)
    return math.exp(-abs(cand_h - nominal_h) / sigma_mm)


# ─── Factor 4 support — AI box ↔ predicted-region overlap ────────────────────

def region_overlap_fraction(
    region: SearchRegion,
    box_px: Sequence[float],
    *,
    samples: int = 5,
) -> float:
    """
    How much of an AI detection box sits inside the predicted region, in [0, 1].

    This is the "amount of overlap between each AI box and the predicted heatmap
    region" that factor 4 needs. It samples a `samples × samples` grid across the
    box and averages the geometric confidence (`geometric_score`) at each point —
    so a box centred on the locus with area spanning the high-confidence band scores
    high, an off-locus box scores low, and (deliberately) a LARGER box that covers
    more of the band scores higher than a tiny one on the same spot. That rewards
    exactly the "larger boxes at a lower threshold" the radiologist described.

    Pure: uses only the region's geometry (always available), never pixels/numpy.
    """
    try:
        x1, y1, x2, y2 = [float(v) for v in box_px]
    except Exception:
        return 0.0
    xlo, xhi = sorted((x1, x2))
    ylo, yhi = sorted((y1, y2))
    n = max(2, int(samples))
    total = 0.0
    count = 0
    for i in range(n):
        fx = xlo + (xhi - xlo) * (i / (n - 1))
        for j in range(n):
            fy = ylo + (yhi - ylo) * (j / (n - 1))
            total += geometric_score(region, (fx, fy))
            count += 1
    return total / count if count else 0.0


def detection_support(
    ai_score: float,
    overlap: float,
    *,
    w_ai: float = 0.5,
    w_overlap: float = 0.5,
) -> float:
    """
    Factor 4 — lower-threshold AI detection support, in [0, 1].

    Blends the detector's own confidence (`ai_score`) with how well the box overlaps
    the predicted region (`overlap`). A box needs BOTH to score high: a confident
    detection in the wrong place, or a perfectly-placed box the detector barely
    believes in, each score only moderately; the corresponding lesion tends to have
    both — a real detection that also lands in the geometrically-predicted zone.
    """
    ai = max(0.0, min(1.0, float(ai_score)))
    ov = max(0.0, min(1.0, float(overlap)))
    return max(0.0, min(1.0, w_ai * ai + w_overlap * ov))


# ─── Combination ─────────────────────────────────────────────────────────────

def combine(
    geometric: float,
    height: float,
    appearance: Optional[float],
    *,
    w_geometric: float = W_GEOMETRIC,
    w_height: float = W_HEIGHT,
    w_appearance: float = W_APPEARANCE,
) -> float:
    """
    Weighted combination of the three factors, renormalised over the AVAILABLE
    ones. `appearance=None` (no pixel data) drops that term and reweights the other
    two — so scores stay comparable whether or not appearance could be computed.
    """
    terms = [(w_geometric, geometric), (w_height, height)]
    if appearance is not None:
        terms.append((w_appearance, appearance))
    wsum = sum(w for w, _ in terms)
    if wsum <= 0:
        return 0.0
    return max(0.0, min(1.0, sum(w * v for w, v in terms) / wsum))


# ─── Dense visual field (numpy) ──────────────────────────────────────────────

@dataclass
class HeatmapField:
    """A dense combined-confidence field over a target-view bounding box."""
    values: "np.ndarray"                       # HxW combined score in [0,1]
    bbox_px: Tuple[int, int, int, int]         # x1,y1,x2,y2 of the field
    step_px: int
    geometric: Optional["np.ndarray"] = None
    height: Optional["np.ndarray"] = None
    appearance: Optional["np.ndarray"] = None
    peak_px: Optional[Tuple[float, float]] = None   # brightest point (image px)
    ok: bool = True


def _region_bbox_px(region: SearchRegion) -> Optional[Tuple[int, int, int, int]]:
    if region.is_empty:
        return None
    xs = [p[0] for p in region.points_px]
    ys = [p[1] for p in region.points_px]
    # Expand across the locus by the outer band (in px, via averaged spacing).
    sx, sy = region._spacing
    pad = region.outer_band_mm / max((sx + sy) / 2.0, 1e-6)
    return (int(min(xs) - pad), int(min(ys) - pad),
            int(max(xs) + pad), int(max(ys) + pad))


def build_heatmap_field(
    region: SearchRegion,
    *,
    appearance_map: Optional[Tuple["np.ndarray", Tuple[int, int, int, int], int]] = None,
    emphasis_px: Optional[Tuple[float, float]] = None,
    emphasis_sigma_mm: float = _EMPHASIS_SIGMA_MM,
    step_px: int = 16,
    sigma_mm: float = _HEIGHT_SIGMA_MM,
) -> Optional[HeatmapField]:
    """
    Build the dense combined heatmap over the region's bounding box.

    `appearance_map` is the (map2d, bbox, step) tuple from
    `appearance_similarity.build_appearance_map`, or None. It is sampled by nearest
    cell; where it does not cover, appearance is treated as unavailable (factor
    drops out via `combine`). Returns None if numpy is missing or the region is
    empty — the caller then falls back to the plain locus overlay.

    `emphasis_px` — when the corresponding lesion has actually been FOUND (a matched
    AI detection), its centre. The geometric HEIGHT along the band is only a weak
    prior (the superior-inferior component is unobservable in CC), so the hot core
    should not sit at the geometric nominal when we already know where the lesion is.
    A wide Gaussian centred on `emphasis_px` gently pulls the bright core ONTO the
    found lesion while leaving the surrounding band visible as the uncertainty. No
    emphasis (no match) → the core stays at the geometric nominal, unchanged.
    """
    if np is None:
        return None
    bbox = _region_bbox_px(region)
    if bbox is None:
        return None
    x1, y1, x2, y2 = bbox
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None

    xs = list(range(x1, x2, max(1, step_px)))
    ys = list(range(y1, y2, max(1, step_px)))
    combined = np.zeros((len(ys), len(xs)), dtype="float32")
    geo_f = np.zeros_like(combined)
    hgt_f = np.zeros_like(combined)
    app_f = np.full_like(combined, np.nan)

    amap = abox = astep = None
    if appearance_map is not None:
        amap, abox, astep = appearance_map

    # Detection emphasis (found lesion): centre of a wide Gaussian, in mm.
    sx_sp, sy_sp = region._spacing
    ex_mm = ey_mm = None
    if emphasis_px is not None and emphasis_sigma_mm > 0:
        ex_mm = float(emphasis_px[0]) * sx_sp
        ey_mm = float(emphasis_px[1]) * sy_sp
    _two_sig2 = 2.0 * emphasis_sigma_mm * emphasis_sigma_mm if emphasis_sigma_mm > 0 else 1.0

    for iy, cy in enumerate(ys):
        for ix, cx in enumerate(xs):
            g = geometric_score(region, (cx, cy))
            h = height_score(region, (cx, cy), sigma_mm=sigma_mm)
            a = None
            if amap is not None:
                ax = int((cx - abox[0]) / max(1, astep))
                ay = int((cy - abox[1]) / max(1, astep))
                if 0 <= ay < amap.shape[0] and 0 <= ax < amap.shape[1]:
                    a = float(amap[ay, ax])
            geo_f[iy, ix] = g
            hgt_f[iy, ix] = h
            if a is not None:
                app_f[iy, ix] = a
            c = combine(g, h, a)
            if ex_mm is not None:
                _dx = cx * sx_sp - ex_mm
                _dy = cy * sy_sp - ey_mm
                c *= math.exp(-(_dx * _dx + _dy * _dy) / _two_sig2)
            combined[iy, ix] = c

    peak = None
    try:
        pi = int(np.argmax(combined))
        py, px = np.unravel_index(pi, combined.shape)
        peak = (float(xs[px]), float(ys[py]))
    except Exception:
        peak = None

    return HeatmapField(
        values=combined, bbox_px=bbox, step_px=max(1, step_px),
        geometric=geo_f, height=hgt_f,
        appearance=(None if amap is None else app_f),
        peak_px=peak,
    )
