"""
Contralateral (Right ↔ Left) symmetry matcher — the second clinical question.

The 3D Cursor answers "where is this lesion in the OTHER VIEW of the same breast?"
(CC↔MLO). This module answers the COMPLEMENTARY question a radiologist asks to
decide whether a finding is real: "does the OTHER BREAST have a matching finding
at the mirror location?" —

        Right-CC  vs  Left-CC          (same projection, opposite breast)
        Right-MLO vs  Left-MLO

A finding with a good symmetric counterpart is usually benign (bilateral symmetric
tissue); a finding with NO counterpart is a **developing/asymmetry** — the thing
that must not be missed. So the output is inverted relative to the cross-view
matcher: finding a match here LOWERS concern, and finding NO match RAISES it.

WHY THIS IS A PURE ENGINE OVER THE STORED RECORDS
────────────────────────────────────────────────────────────────────────────────
The lesion feature store already records each lesion's geometry in BREAST-RELATIVE
coordinates — depth measured from the nipple toward THAT breast's own chest wall
(the laterality-aware depth normal), radial nipple distance, and height offset from
the nipple. For a symmetric finding these values are ~EQUAL in the two breasts, so
**the mirror is already baked into the coordinates** — no pixel flipping is needed.
And the appearance descriptors we persist (density, rotation-averaged GLCM, the
microcalcification constellation count/size/spacing, the lesion-type tag) are all
mirror-INVARIANT, so they compare directly too.

Therefore this matcher reads ONLY the stored `LesionFeatureRecord` dicts and needs
no images, no Qt, no VTK, no numpy. It is fully unit-testable in the sandbox lane.

CLINICAL POSTURE
────────────────────────────────────────────────────────────────────────────────
This is decision SUPPORT, not a diagnosis. "No contralateral counterpart found"
means "possible asymmetry — review", never "malignant". The thresholds are
deliberately conservative and the natural left/right asymmetry of normal breasts is
respected by wide tolerances. It NEVER downgrades a lesion on its own; it only
raises an asymmetry flag for the radiologist.

Purity: stdlib + math only.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .lesion_feature_store import (
    CMP_RCC_LCC,
    CMP_RMLO_LMLO,
    contralateral_pair_kind,
    load_features_for_patient,
)


# ─── Outcome codes ───────────────────────────────────────────────────────────

SYMMETRIC = "symmetric"       # a good mirror counterpart exists → lower concern
ASYMMETRIC = "asymmetric"     # counterpart(s) EXIST but none match → possible asymmetry
AMBIGUOUS = "ambiguous"       # several plausible counterparts (still symmetric-ish)
INSUFFICIENT = "insufficient_data"  # the other breast has NO analysed finding in this
#                                     view → nothing to compare. This is ABSENCE OF
#                                     DATA, not absence of a finding, so it must NEVER
#                                     be presented as an asymmetry.


# ─── Gates + tolerances (conservative; respect natural L/R asymmetry) ─────────

# A counterpart must reach this symmetry score to count as "a mirror was found".
SYMMETRIC_FLOOR = float(os.getenv("AIPACS_CURSOR3D_SYMMETRY_FLOOR", "0.60"))
# Two counterparts within this of each other → AMBIGUOUS (both plausible mirrors).
AMBIGUOUS_MARGIN = float(os.getenv("AIPACS_CURSOR3D_SYMMETRY_MARGIN", "0.08"))

# mm tolerances at which a geometric agreement decays to ~1/e. Wider than the
# cross-view matcher because healthy breasts are not perfectly symmetric.
_DEPTH_TOL_MM = float(os.getenv("AIPACS_CURSOR3D_SYMMETRY_DEPTH_TOL_MM", "18.0"))
_RADIAL_TOL_MM = float(os.getenv("AIPACS_CURSOR3D_SYMMETRY_RADIAL_TOL_MM", "18.0"))
_HEIGHT_TOL_MM = float(os.getenv("AIPACS_CURSOR3D_SYMMETRY_HEIGHT_TOL_MM", "18.0"))


# ─── Weights (geometry dominant; renormalised over AVAILABLE components) ──────

WEIGHTS: Dict[str, float] = {
    "axial_depth_agree": 0.28,   # depth nipple→chest-wall — the strongest symmetry cue
    "radial_agree": 0.18,        # nipple→lesion straight-line distance
    "height_agree": 0.18,        # offset from nipple along the chest wall
    "density_agree": 0.12,       # mirror-invariant density level
    "microcalc_agree": 0.12,     # constellation count/size/spacing
    "texture_agree": 0.06,       # rotation-averaged GLCM (mirror-invariant)
    "type_agree": 0.06,          # same lesion-type tag
}

_EPS = 1e-9


# ─── Data model ──────────────────────────────────────────────────────────────

@dataclass
class SymmetryMatch:
    candidate: Dict[str, Any]                 # the contralateral record
    total: float
    components: Dict[str, float] = field(default_factory=dict)
    is_symmetric: bool = False


@dataclass
class SymmetryResult:
    query: Dict[str, Any]
    status: str                               # SYMMETRIC | ASYMMETRIC | AMBIGUOUS
    best: Optional[SymmetryMatch] = None
    ranked: List[SymmetryMatch] = field(default_factory=list)
    asymmetry_flag: bool = False
    message: str = ""


# ─── Record access (accepts a dict OR a LesionFeatureRecord) ─────────────────

def _rec(r: Any) -> Dict[str, Any]:
    if isinstance(r, dict):
        return r
    to_dict = getattr(r, "to_dict", None)
    return to_dict() if callable(to_dict) else dict(getattr(r, "__dict__", {}) or {})


def _geom(r: Dict[str, Any]) -> Dict[str, Any]:
    g = r.get("geometry")
    return g if isinstance(g, dict) else {}


def _appear(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    a = r.get("appearance")
    return a if (isinstance(a, dict) and a.get("ok")) else None


# ─── Agreement primitives (each returns [0,1], or None when not computable) ──

def _decay(diff: Optional[float], tol: float) -> Optional[float]:
    if diff is None or tol <= 0:
        return None
    return math.exp(-abs(diff) / tol)


def _both(a: Any, b: Any):
    try:
        if a is None or b is None:
            return None
        return float(a), float(b)
    except (TypeError, ValueError):
        return None


def _rel_agree(a: Any, b: Any) -> Optional[float]:
    """Symmetric relative agreement: 1 at equality, 0 at maximal disparity."""
    pair = _both(a, b)
    if pair is None:
        return None
    x, y = pair
    denom = abs(x) + abs(y)
    if denom <= _EPS:
        return 1.0
    return max(0.0, 1.0 - min(1.0, abs(x - y) / denom))


def _ratio_agree(a: Any, b: Any) -> Optional[float]:
    """min/max ratio — for counts and sizes."""
    pair = _both(a, b)
    if pair is None:
        return None
    x, y = pair
    if x <= 0 and y <= 0:
        return 1.0
    if x <= 0 or y <= 0:
        return 0.0
    return min(x, y) / max(x, y)


def _diff(a: Any, b: Any) -> Optional[float]:
    pair = _both(a, b)
    return None if pair is None else (pair[0] - pair[1])


# ─── Component scores ────────────────────────────────────────────────────────

def _geometry_components(q: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, float]:
    gq, gc = _geom(q), _geom(c)
    out: Dict[str, float] = {}
    v = _decay(_diff(gq.get("axial_depth_mm"), gc.get("axial_depth_mm")), _DEPTH_TOL_MM)
    if v is not None:
        out["axial_depth_agree"] = v
    v = _decay(_diff(gq.get("radial_distance_mm"), gc.get("radial_distance_mm")), _RADIAL_TOL_MM)
    if v is not None:
        out["radial_agree"] = v
    v = _decay(_diff(gq.get("height_mm"), gc.get("height_mm")), _HEIGHT_TOL_MM)
    if v is not None:
        out["height_agree"] = v
    return out


def _microcalc_agree(aq: Dict[str, Any], ac: Dict[str, Any]) -> Optional[float]:
    mq, mc = aq.get("microcalc") or {}, ac.get("microcalc") or {}
    dq, dc = bool(mq.get("detected")), bool(mc.get("detected"))
    if not dq and not dc:
        return None                     # neither has calcs → not evidence either way
    if dq != dc:
        return 0.2                      # one has a cluster, the other doesn't → poor symmetry
    parts = [
        _ratio_agree(mq.get("count"), mc.get("count")),
        _rel_agree(mq.get("mean_area_mm2"), mc.get("mean_area_mm2")),
        _rel_agree(mq.get("mean_nn_spacing_mm"), mc.get("mean_nn_spacing_mm")),
    ]
    parts = [p for p in parts if p is not None]
    return sum(parts) / len(parts) if parts else None


def _texture_agree(aq: Dict[str, Any], ac: Dict[str, Any]) -> Optional[float]:
    gq, gc = aq.get("glcm"), ac.get("glcm")
    if not isinstance(gq, dict) or not isinstance(gc, dict):
        return None
    parts = []
    for k in ("contrast", "homogeneity", "asm", "correlation", "entropy"):
        p = _rel_agree(gq.get(k), gc.get(k))
        if p is not None:
            parts.append(p)
    return sum(parts) / len(parts) if parts else None


def _appearance_components(q: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, float]:
    aq, ac = _appear(q), _appear(c)
    if aq is None or ac is None:
        return {}
    out: Dict[str, float] = {}
    dens = _rel_agree(
        aq.get("density_mean", (aq.get("first_order") or {}).get("mean")),
        ac.get("density_mean", (ac.get("first_order") or {}).get("mean")),
    )
    if dens is not None:
        out["density_agree"] = dens
    mc = _microcalc_agree(aq, ac)
    if mc is not None:
        out["microcalc_agree"] = mc
    tex = _texture_agree(aq, ac)
    if tex is not None:
        out["texture_agree"] = tex
    tq, tc = aq.get("lesion_type"), ac.get("lesion_type")
    if tq and tc:
        out["type_agree"] = 1.0 if str(tq) == str(tc) else 0.4
    return out


def _weighted_total(components: Dict[str, float]) -> float:
    avail = [k for k in components if k in WEIGHTS]
    wsum = sum(WEIGHTS[k] for k in avail)
    if wsum <= 0:
        return 0.0
    return sum(WEIGHTS[k] * components[k] for k in avail) / wsum


# ─── Scoring one pair ────────────────────────────────────────────────────────

def score_symmetry(query: Any, candidate: Any) -> SymmetryMatch:
    """
    Symmetry score in [0,1] between a query lesion and a contralateral candidate.

    Geometry (breast-relative, so directly comparable across the mirror) carries the
    bulk of the weight; mirror-invariant appearance refines it. Weights renormalise
    over whatever is present, so a geometry-only record (no appearance stored) still
    scores on position alone without penalty.
    """
    q, c = _rec(query), _rec(candidate)
    components = _geometry_components(q, c)
    components.update(_appearance_components(q, c))
    total = round(_weighted_total(components), 4)
    return SymmetryMatch(
        candidate=c,
        total=total,
        components={k: round(v, 4) for k, v in components.items()},
        is_symmetric=(total >= SYMMETRIC_FLOOR),
    )


# ─── Matching one lesion against the contralateral breast ────────────────────

def _same_view_opposite_laterality(query: Dict[str, Any], records: Sequence[Any]) -> List[Dict[str, Any]]:
    qv = str(query.get("view_position", "")).upper()
    ql = str(query.get("laterality", "")).upper()
    out = []
    for r in records:
        rr = _rec(r)
        if str(rr.get("view_position", "")).upper() != qv:
            continue
        rl = str(rr.get("laterality", "")).upper()
        if rl and ql and rl != ql:
            out.append(rr)
    return out


def match_contralateral(query: Any, candidates: Sequence[Any]) -> SymmetryResult:
    """
    Rank the contralateral candidates for one query lesion and decide whether a
    symmetric counterpart exists.

    Outcome:
      SYMMETRIC    — a counterpart clears the floor (and is not tied with another).
      AMBIGUOUS    — two or more counterparts clear the floor within the margin.
      ASYMMETRIC   — counterpart(s) EXIST but none match → `asymmetry_flag=True` (the
                     one to surface: a finding that has candidates in the other breast
                     yet none correspond).
      INSUFFICIENT — the other breast has NO analysed finding in this view. NOT an
                     asymmetry (it is missing data — the other breast may simply not
                     have been run through the 3D cursor); `asymmetry_flag=False`.
    """
    q = _rec(query)
    scored = sorted(
        (score_symmetry(q, c) for c in candidates),
        key=lambda m: m.total, reverse=True,
    )

    if not scored:
        return SymmetryResult(
            query=q, status=INSUFFICIENT, best=None, ranked=[], asymmetry_flag=False,
            message=("No analysed finding in the contralateral breast in this view — "
                     "nothing to compare against (insufficient data, NOT an asymmetry)."),
        )

    best = scored[0]
    above = [m for m in scored if m.total >= SYMMETRIC_FLOOR]

    if not above:
        return SymmetryResult(
            query=q, status=ASYMMETRIC, best=best, ranked=scored, asymmetry_flag=True,
            message=(f"No symmetric counterpart (best {best.total:.2f} < "
                     f"{SYMMETRIC_FLOOR:.2f}). Possible asymmetry — review."),
        )

    if len(above) > 1 and (above[0].total - above[1].total) < AMBIGUOUS_MARGIN:
        return SymmetryResult(
            query=q, status=AMBIGUOUS, best=best, ranked=scored, asymmetry_flag=False,
            message=(f"{len(above)} plausible symmetric counterparts "
                     f"({', '.join(f'{m.total:.2f}' for m in above[:3])}) — likely "
                     f"symmetric tissue."),
        )

    return SymmetryResult(
        query=q, status=SYMMETRIC, best=best, ranked=scored, asymmetry_flag=False,
        message=(f"Symmetric counterpart found (score {best.total:.2f}) — bilateral "
                 f"symmetry, lower concern."),
    )


# ─── Patient-level analysis ──────────────────────────────────────────────────

def analyze_records(
    records: Sequence[Any],
    *,
    origins: Optional[Sequence[str]] = ("picked",),
) -> List[SymmetryResult]:
    """
    For each query lesion, find its contralateral counterpart (same view, other
    breast) and flag asymmetries.

    `origins` filters WHICH lesions are treated as queries (default: only 'picked'
    source lesions — the real findings, not predicted candidates). The candidate
    pool for each query is every lesion of the opposite laterality in the same view,
    regardless of origin.
    """
    recs = [_rec(r) for r in records]
    results: List[SymmetryResult] = []
    for q in recs:
        if origins is not None and str(q.get("origin", "")) not in origins:
            continue
        if contralateral_pair_kind(q.get("view_position", "")) is None:
            continue  # only CC and MLO are mirrored
        cands = _same_view_opposite_laterality(q, recs)
        results.append(match_contralateral(q, cands))
    return results


def analyze_patient_symmetry_from_store(
    patient_id: str,
    attachments_path: str,
    *,
    origins: Optional[Sequence[str]] = ("picked",),
) -> List[SymmetryResult]:
    """
    Convenience: load every stored lesion for a patient and run the symmetry
    analysis. Reads the per-study feature files under `attachments_path`. Never
    raises — returns [] on any failure (this is background decision support).
    """
    try:
        records = load_features_for_patient(patient_id, attachments_path)
        return analyze_records(records, origins=origins)
    except Exception:
        return []


def contralateral_enabled() -> bool:
    """
    `AIPACS_CURSOR3D_CONTRALATERAL` — gate for the UI/workflow that SURFACES the
    asymmetry flag. **Default ON (promoted 2026-07-15 per directive.)** The note is
    decision support only (never a diagnosis, never downgrades a lesion), text-only,
    and wrapped so it can never raise into the finalize path — so it is safe to run
    by default. `=0` restores the silent-engine legacy behaviour (the pure engine can
    still be called directly, e.g. by tests or an offline audit).
    """
    # Reverted to default-OFF 2026-07-20 while isolating a 3D-Cursor close regression
    # (the pass runs at finalize; kept off by default until the crash cause is confirmed).
    raw = os.environ.get("AIPACS_CURSOR3D_CONTRALATERAL")
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")
