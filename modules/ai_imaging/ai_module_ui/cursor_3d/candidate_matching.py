"""
Stage 2 of the Two-Stage 3D Cursor — rank the lower-threshold AI detections
against the Stage-1 search region and pick the most likely corresponding lesion.

CLINICAL CONTRACT (this is the part that matters)
────────────────────────────────────────────────────────────────────────────────
This module is allowed to say "I don't know", and it is REQUIRED to say so rather
than guess. Three outcomes only:

    MATCH      — one candidate is both good enough AND clearly better than the
                 runner-up. Highlight it.
    AMBIGUOUS  — several candidates score similarly. Show them ALL as alternatives.
                 Never silently pick the top of a near-tie.
    NO_MATCH   — nothing scores above the floor. Keep the geometric region on
                 screen and tell the user no reliable AI correspondence was found.

A false "confirmed match" in a cancer workflow is worse than an honest "unknown":
it moves the radiologist's eye AWAY from the true lesion. So the gates below are
deliberately conservative, and `is_confident` is False unless BOTH the absolute
score floor and the margin-over-runner-up are cleared.

SCORING — provisional, and honestly labelled as such
────────────────────────────────────────────────────────────────────────────────
The weights below are NOT validated. There is no ground-truth correspondence set
yet (this is the same blocker CL-Net's authors hit — DDSM ships no correspondence
labels). They are principled starting values, ordered by what the literature says
carries signal:

  • region_fit    (0.35) — deviation from the Stage-1 locus. The strongest single
                           geometric cue; it IS the published error metric.
  • axial_agree   (0.20) — |dl_source - dl_candidate|. The SS quantity; correlates
                           0.923 across views (Wang 2025) — the best of the two.
  • radial_agree  (0.15) — |dr_source - dr_candidate|. The Kopans/NOD quantity;
                           correlates 0.917. Kept because it is a genuinely
                           independent cue from the axial one, and radiologists
                           reason in it.
  • ai_score      (0.10) — the detector's own confidence.
  • size_agree    (0.10) — physical size is preserved across views far better than
                           shape is (compression differs per view).
  • class_agree   (0.05) — same predicted finding label in both views.
  • shape_agree   (0.05) — aspect-ratio similarity. Weakest: compression genuinely
                           deforms lesions differently in CC vs MLO, so a shape
                           mismatch is weak evidence of non-correspondence.

Every component is normalised to [0, 1] and the weights sum to 1.0, so `total` is
directly interpretable and the gates below are meaningful. Calibrate these against
a labelled set before trusting them (see the accuracy plan, Phase 0).

Purity: stdlib + math only. No Qt, VTK, numpy, cv2, pydicom.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .geometry import LesionLocation, MammogramGeometry
from .search_region import SearchRegion


# ─── Outcome codes ───────────────────────────────────────────────────────────

MATCH = "match"
AMBIGUOUS = "ambiguous"
NO_MATCH = "no_match"


# ─── Gates (conservative on purpose) ─────────────────────────────────────────

# A candidate must score at least this to be called a match at all.
MIN_CONFIDENT_SCORE = float(os.getenv("AIPACS_CURSOR3D_MIN_SCORE", "0.55"))

# ...and must beat the runner-up by at least this, else the result is AMBIGUOUS.
MIN_MARGIN = float(os.getenv("AIPACS_CURSOR3D_MIN_MARGIN", "0.10"))

# A candidate further than (outer_band * this) from the locus is not considered a
# correspondence at all. It can still be listed, but never selected.
OUT_OF_REGION_FACTOR = 1.5


# ─── Weights ─────────────────────────────────────────────────────────────────

# The FOUR radiologist-named FACTORS:
#   factor 1  region_fit         — geometric localization (across the locus)
#   factor 2  height_agree       — CC medial-lateral → expected MLO height
#   factor 3  appearance_sim     — density / histogram / pattern similarity
#   factor 4  detection_support  — lower-threshold AI detection: the box's own AI
#                                  confidence blended with its OVERLAP with the
#                                  predicted region (cross_view_heatmap.detection_support).
# The remaining entries are finer geometry sub-signals. Weights renormalise over
# whatever is AVAILABLE (see `_weighted_total`), so an absent appearance signal
# never dilutes the ranking.
WEIGHTS: Dict[str, float] = {
    "region_fit": 0.25,          # factor 1
    "height_agree": 0.12,        # factor 2
    "appearance_sim": 0.18,      # factor 3
    "detection_support": 0.20,   # factor 4 (AI confidence + heatmap overlap)
    "axial_agree": 0.11,
    "radial_agree": 0.06,
    "size_agree": 0.04,
    "class_agree": 0.02,
    "shape_agree": 0.02,
}

# Tolerances (mm) at which an agreement component decays to ~0.37 (1/e).
# 15 mm mirrors the correlator's existing MATCHING_THRESHOLD_MM, and is consistent
# with the published finding that |NOD difference| < 16 mm for 83 % of lesions.
_AXIAL_TOLERANCE_MM = 15.0
_RADIAL_TOLERANCE_MM = 15.0


# ─── Data model ──────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    """
    One detection from the SECOND-PASS (lower threshold) analysis in the target view.

    `index` is the row/box index in the second-pass CSV so the UI can map a ranked
    result straight back to the drawn actor.
    """
    index: int
    box_px: List[float]                       # [x1, y1, x2, y2]
    score: float = 0.5                        # AI confidence
    classification: Optional[str] = None      # labels_pred, when available
    finding_uid: Optional[str] = None

    def to_lesion(self, geom: MammogramGeometry) -> LesionLocation:
        return LesionLocation.from_pixel_box(
            list(self.box_px), geom.image.pixel_spacing, score=self.score
        )


@dataclass
class ScoredCandidate:
    candidate: Candidate
    total: float
    components: Dict[str, float] = field(default_factory=dict)
    deviation_mm: float = 0.0
    in_inner_band: bool = False
    in_outer_band: bool = False
    rank: int = 0

    @property
    def center_px(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.candidate.box_px
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


@dataclass
class MatchResult:
    """Outcome of Stage 2. `status` is one of MATCH / AMBIGUOUS / NO_MATCH."""
    status: str
    ranked: List[ScoredCandidate] = field(default_factory=list)
    best: Optional[ScoredCandidate] = None
    alternatives: List[ScoredCandidate] = field(default_factory=list)
    margin: float = 0.0
    message: str = ""

    @property
    def is_confident(self) -> bool:
        """True ONLY for an unambiguous, above-floor match. The UI must not draw a
        'corresponding lesion found' affordance unless this is True."""
        return self.status == MATCH and self.best is not None


# ─── Scoring ─────────────────────────────────────────────────────────────────

def _decay(value: float, tolerance: float) -> float:
    """Exponential decay: 1.0 at zero difference, ~0.37 at `tolerance`."""
    if tolerance <= 0:
        return 0.0
    return math.exp(-abs(value) / tolerance)


def _score_region_fit(deviation_mm: float, region: SearchRegion) -> float:
    """
    1.0 on the locus, ~0.5 at the inner band edge, ->0 by the outer band edge.

    Uses the region's OWN band widths, so when the bands are recalibrated from
    measured data this component recalibrates with them automatically.
    """
    inner = max(region.inner_band_mm, 1e-6)
    if deviation_mm <= inner:
        # Linear 1.0 -> 0.5 across the high-confidence band.
        return 1.0 - 0.5 * (deviation_mm / inner)
    outer = max(region.outer_band_mm, inner + 1e-6)
    if deviation_mm >= outer:
        return 0.0
    # Linear 0.5 -> 0.0 across the remainder of the search band.
    return 0.5 * (1.0 - (deviation_mm - inner) / (outer - inner))


def _score_size(source: LesionLocation, cand: LesionLocation) -> float:
    """Ratio of physical areas (mm^2), symmetric: min/max."""
    a1 = max(source.width_mm * source.height_mm, 1e-6)
    a2 = max(cand.width_mm * cand.height_mm, 1e-6)
    return min(a1, a2) / max(a1, a2)


def _score_shape(source: LesionLocation, cand: LesionLocation) -> float:
    """Aspect-ratio similarity. Weak evidence — compression differs per view."""
    def aspect(l: LesionLocation) -> float:
        w = max(l.width_mm, 1e-6)
        h = max(l.height_mm, 1e-6)
        return w / h
    a1 = aspect(source)
    a2 = aspect(cand)
    return min(a1, a2) / max(a1, a2)


def _score_class(source_class: Optional[str], cand_class: Optional[str]) -> float:
    """
    1.0 same label, 0.0 different, 0.5 unknown.

    Unknown scores NEUTRAL, not zero: the classification CSV is joined to the
    detection CSV by exact float box equality, which fails often. A missing label
    is a data-plumbing artefact, and must not be read as evidence against a
    candidate.
    """
    if not source_class or not cand_class:
        return 0.5
    return 1.0 if str(source_class).strip().lower() == str(cand_class).strip().lower() else 0.0


def dominant_index(results: Sequence["MatchResult"]) -> Optional[int]:
    """
    Index of THE single dominant lesion across several MatchResults, or None.

    Clinical assumption: a breast has one dominant suspicious focus, so the final
    output should be ONE lesion, not many. Only `MATCH` results qualify (an
    ambiguous or no-match result must never be promoted to "the lesion"); among
    them, the one with the highest confident-candidate score wins. Pure + testable.
    """
    best_i = None
    best_total = -1.0
    for i, r in enumerate(results):
        if r is not None and r.status == MATCH and r.best is not None:
            if r.best.total > best_total:
                best_total = r.best.total
                best_i = i
    return best_i


def focused_indices(results: Sequence["MatchResult"]) -> List[int]:
    """
    Indices of ALL confident (MATCH) lesions across several MatchResults, strongest
    first — so a study with more than one true corresponding lesion (two on a side,
    or bilateral) shows EVERY confident match, not just the single strongest.

    Ambiguous / no-match results are still excluded, so the output stays focused on
    real correspondences instead of scattering across every low-confidence region.
    `dominant_index` remains the single-best convenience (== the first of these, or
    None). Pure + testable.
    """
    matches = [
        (i, r.best.total)
        for i, r in enumerate(results)
        if r is not None and r.status == MATCH and r.best is not None
    ]
    matches.sort(key=lambda t: t[1], reverse=True)
    return [i for i, _ in matches]


def _weighted_total(components: Dict[str, float], available: Sequence[str]) -> float:
    """
    Weighted mean over the AVAILABLE components, renormalised by their weights.

    This is what lets appearance_sim drop out cleanly when there is no pixel data:
    its weight is simply excluded, so the remaining factors keep their relative
    proportions and the total stays comparable to a run that had appearance. A
    naive fixed-weight sum with a neutral 0.5 would instead hand every candidate the
    same constant, nudging borderline cases over the confidence floor for free.
    """
    wsum = sum(WEIGHTS[k] for k in available)
    if wsum <= 0:
        return 0.0
    return sum(WEIGHTS[k] * components[k] for k in available) / wsum


def score_candidate(
    candidate: Candidate,
    region: SearchRegion,
    source_lesion: LesionLocation,
    source_geom: MammogramGeometry,
    target_geom: MammogramGeometry,
    *,
    source_classification: Optional[str] = None,
    appearance_score_fn: Optional[Callable[[Sequence[float]], float]] = None,
) -> ScoredCandidate:
    """
    Score ONE candidate against the region and the source lesion, over the three
    factors (+ sub-signals).

    Args:
        appearance_score_fn: optional `box_px -> [0,1]` histogram/appearance
            similarity (factor 3). When None (no pixel data), the appearance term
            is EXCLUDED and the weights renormalise over the rest — it is never
            faked as neutral.
    """
    cand_lesion = candidate.to_lesion(target_geom)
    center = cand_lesion.center_px

    deviation = region.deviation_mm(center)

    src_axial = source_geom.compute_lesion_depth_mm(source_lesion)
    src_radial = source_geom.compute_lesion_radial_distance_mm(source_lesion)
    cand_axial = target_geom.compute_lesion_depth_mm(cand_lesion)
    cand_radial = target_geom.compute_lesion_radial_distance_mm(cand_lesion)

    # Factor 2 — medial-lateral → MLO height (soft, wide prior along the locus).
    # Factor 4 — lower-threshold AI detection support = the box's AI confidence
    # blended with its OVERLAP with the predicted region (area-based, so a larger
    # low-threshold box covering more of the band is rewarded).
    from .cross_view_heatmap import height_score, region_overlap_fraction, detection_support
    height_agree = height_score(region, center)
    overlap = region_overlap_fraction(region, candidate.box_px)

    components = {
        "region_fit": _score_region_fit(deviation, region),                 # factor 1
        "height_agree": height_agree,                                       # factor 2
        "detection_support": detection_support(candidate.score, overlap),   # factor 4
        "axial_agree": _decay(src_axial - cand_axial, _AXIAL_TOLERANCE_MM),
        "radial_agree": _decay(src_radial - cand_radial, _RADIAL_TOLERANCE_MM),
        "size_agree": _score_size(source_lesion, cand_lesion),
        "class_agree": _score_class(source_classification, candidate.classification),
        "shape_agree": _score_shape(source_lesion, cand_lesion),
    }
    available = list(components.keys())

    # Factor 3 — appearance similarity, only when pixel data is available.
    if appearance_score_fn is not None:
        try:
            appear = float(appearance_score_fn(candidate.box_px))
            components["appearance_sim"] = max(0.0, min(1.0, appear))
            available.append("appearance_sim")
        except Exception:
            pass  # appearance failed → excluded, weights renormalise

    total = _weighted_total(components, available)

    return ScoredCandidate(
        candidate=candidate,
        total=round(total, 4),
        components={k: round(components[k], 4) for k in available},
        deviation_mm=round(deviation, 2),
        in_inner_band=deviation <= region.inner_band_mm,
        in_outer_band=deviation <= region.outer_band_mm,
    )


# ─── Stage 2 entry point ─────────────────────────────────────────────────────

def rank_candidates(
    candidates: Sequence[Candidate],
    region: SearchRegion,
    source_lesion: LesionLocation,
    source_geom: MammogramGeometry,
    target_geom: MammogramGeometry,
    *,
    source_classification: Optional[str] = None,
    appearance_score_fn: Optional[Callable[[Sequence[float]], float]] = None,
    min_score: float = MIN_CONFIDENT_SCORE,
    min_margin: float = MIN_MARGIN,
) -> MatchResult:
    """
    Rank second-pass detections and decide MATCH / AMBIGUOUS / NO_MATCH.

    `appearance_score_fn` (optional) supplies factor 3 (histogram/appearance
    similarity) per candidate box; when omitted, matching runs on the geometric
    factors 1+2 alone (weights renormalise — no dilution).

    Returns a MatchResult whose `ranked` list is always sorted best-first — even
    when the status is NO_MATCH, so the UI can still show "nearest, but rejected"
    detections if it wants to. Only `is_confident` licenses a "found it" claim.
    """
    if not region.ok or region.is_empty:
        return MatchResult(
            status=NO_MATCH,
            message="No valid search region — cannot rank candidates.",
        )

    if not candidates:
        return MatchResult(
            status=NO_MATCH,
            message="Lower-threshold analysis returned no detections in this view.",
        )

    scored = [
        score_candidate(
            c, region, source_lesion, source_geom, target_geom,
            source_classification=source_classification,
            appearance_score_fn=appearance_score_fn,
        )
        for c in candidates
    ]
    scored.sort(key=lambda s: s.total, reverse=True)
    for i, s in enumerate(scored):
        s.rank = i + 1

    # Anything absurdly far from the locus can be shown but never selected.
    reachable = [
        s for s in scored
        if s.deviation_mm <= region.outer_band_mm * OUT_OF_REGION_FACTOR
    ]

    if not reachable:
        return MatchResult(
            status=NO_MATCH,
            ranked=scored,
            message=(
                "No lower-threshold detection lies within the predicted region. "
                "The geometric region remains valid — review it manually."
            ),
        )

    best = reachable[0]
    runner_up = reachable[1] if len(reachable) > 1 else None
    margin = best.total - (runner_up.total if runner_up else 0.0)

    if best.total < min_score:
        return MatchResult(
            status=NO_MATCH,
            ranked=scored,
            margin=round(margin, 4),
            message=(
                f"Best candidate scored {best.total:.2f}, below the {min_score:.2f} "
                f"confidence floor. No reliable corresponding detection found — "
                f"the predicted region remains for manual review."
            ),
        )

    if runner_up is not None and margin < min_margin:
        close = [s for s in reachable if best.total - s.total < min_margin]
        return MatchResult(
            status=AMBIGUOUS,
            ranked=scored,
            best=None,                      # deliberately NOT selected
            alternatives=close,
            margin=round(margin, 4),
            message=(
                f"{len(close)} candidates scored within {min_margin:.2f} of each "
                f"other ({', '.join(f'{s.total:.2f}' for s in close)}). "
                f"Shown as alternatives — no single match asserted."
            ),
        )

    return MatchResult(
        status=MATCH,
        ranked=scored,
        best=best,
        alternatives=[s for s in reachable[1:4]],
        margin=round(margin, 4),
        message=(
            f"Corresponding lesion found (score {best.total:.2f}, "
            f"{best.deviation_mm:.1f} mm from the predicted locus)."
        ),
    )
