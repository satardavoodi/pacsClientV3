"""
PNL (Posterior Nipple Line) cross-view depth normalisation.

THE PROBLEM (patient 50513, MLO→CC).
A lesion sitting deep/posterior near the pectoral muscle in the MLO view was
mapped to a near-ANTERIOR location in the CC view. The GM locus preserves the
ABSOLUTE nipple→lesion depth, but the breast is NOT the same depth in the two
views — the MLO includes more posterior tissue (axillary tail, pectoral) than the
CC. So an absolute depth of, say, 55 mm is "mid-breast" in a 90 mm-deep CC yet
"posterior" in a 110 mm-deep MLO. Preserving the absolute number therefore slides
a posterior MLO lesion forward (anterior) in CC — exactly the reported error.

THE FIX (the radiologist's proposal, and the standard mammography PNL rule).
The nipple and the pectoral/chest-wall are two STABLE anatomical landmarks. The
distance between them (the Posterior Nipple Line, PNL) is the breast's depth SCALE
in each view. A lesion's depth expressed as a FRACTION of the PNL is preserved
across views far better than its absolute value:

        f = depth_source / PNL_source                     (fractional depth)
        depth_target = f * PNL_target = depth_source * (PNL_target / PNL_source)

`PNL_target / PNL_source` is the "correction ratio" between the two views (the
CC PNL is typically ~10 % shorter than the MLO PNL). Applying it renormalises the
predicted depth to the target view's own scale, so a posterior lesion stays
posterior.

`depth_source` here is the PERPENDICULAR (chest-wall-normal) depth — the same
`compute_lesion_depth_mm` the SS strip uses — because that is the depth the PNL
scales; the pectoral distance is measured along the same normal.

Purity: stdlib only. No Qt/VTK/numpy/pydicom. Unit-testable in the sandbox lane.
It reads geometry ONLY through `MammogramGeometry.pectoral_reference_distance_mm()`
and `.compute_lesion_depth_mm()`, so the two files stay decoupled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


# A lesion cannot sit DEEPER than the chest wall. Cap the normalised depth at this
# fraction of the target PNL so an over-large ratio (a small source PNL, e.g. a
# high/close pectoral line) can never push the predicted region PAST the chest wall
# and off the image — which silently DROPPED a finding (patient 50513: ratio 1.79 →
# 76.4 mm > the 74 mm CC PNL → "outside the CC image field", only 1 of 2 findings
# survived). Env-tunable; `>=1.0` disables the cap.
_PNL_DEPTH_CAP_FRAC = float(os.getenv("AIPACS_CURSOR3D_PNL_DEPTH_CAP", "0.97"))


def pnl_normalize_enabled() -> bool:
    """
    AIPACS_CURSOR3D_PNL_NORMALIZE — default ON (promoted 2026-07-15).

    On = the target locus is placed at the PNL-normalised depth WHEN both pectoral
    references are available (the user has drawn the MLO pectoral line); otherwise
    it silently falls back to legacy absolute depth. `=0` is the byte-identical
    legacy kill switch.

    Promoted to default after live validation in BOTH directions — the same
    discipline by which GM itself was promoted:
      • 50513 (MLO→CC): the reported bug — the region moved +23 mm posterior
        (55 → 78.4 mm), landing in the posterior CC breast to match the posterior
        MLO lesion.
      • 50258 (CC→MLO): no regression — the region (19.0 mm, ±32 mm band) still
        covers the true MLO detection.
    Only active when the pectoral line is drawn; the ±32 mm search band + the
    honest-failure matcher remain the safety net for the CC→MLO axis approximation.
    """
    raw = os.environ.get("AIPACS_CURSOR3D_PNL_NORMALIZE")
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


@dataclass
class PnlResult:
    """
    Outcome of the PNL normalisation for one source→target mapping.

    Carries BOTH the legacy and the normalised depth plus every intermediate
    (the two PNLs and the ratio) so the controller can log a full side-by-side
    for live validation and persist it to the session, whether or not the flag is
    on.
    """
    available: bool
    a_source_horizontal_mm: float   # the legacy GM anterior depth (untilted)
    a_source_perp_mm: float         # perpendicular (chest-wall-normal) source depth
    a_normalized_mm: float          # the value GM should place when enabled
    d_source_mm: Optional[float] = None   # PNL in the source view
    d_target_mm: Optional[float] = None   # PNL in the target view
    ratio: Optional[float] = None         # d_target / d_source (the correction ratio)
    reason: str = ""

    def as_log_dict(self) -> dict:
        """Compact dict for logging / session persistence."""
        def _r(v):
            return None if v is None else round(float(v), 2)
        return {
            "available": self.available,
            "a_horizontal_mm": _r(self.a_source_horizontal_mm),
            "a_perp_mm": _r(self.a_source_perp_mm),
            "a_normalized_mm": _r(self.a_normalized_mm),
            "pnl_source_mm": _r(self.d_source_mm),
            "pnl_target_mm": _r(self.d_target_mm),
            "ratio": _r(self.ratio),
            "reason": self.reason,
        }


def compute_pnl_normalization(
    source_lesion,
    source_geom,
    target_geom,
    *,
    horizontal_a_src_mm: float,
) -> PnlResult:
    """
    Compute the PNL-normalised target anterior depth.

    Args:
        source_lesion: the lesion in the source view (LesionLocation).
        source_geom / target_geom: the two MammogramGeometry views.
        horizontal_a_src_mm: the legacy GM anterior depth (untilted horizontal),
            carried through for the diagnostic and used as the safe fallback.

    Returns a PnlResult. When the pectoral reference is missing in either view
    (`available=False`) the normalised value equals the legacy horizontal depth,
    so a caller that blindly used `a_normalized_mm` would still get legacy
    behaviour — but callers should gate on `pnl_normalize_enabled() and available`.
    """
    try:
        d_src = source_geom.pectoral_reference_distance_mm()
        d_tgt = target_geom.pectoral_reference_distance_mm()
        perp = float(source_geom.compute_lesion_depth_mm(source_lesion))
    except Exception as exc:  # never raise into the geometry/render path
        return PnlResult(
            available=False,
            a_source_horizontal_mm=horizontal_a_src_mm,
            a_source_perp_mm=horizontal_a_src_mm,
            a_normalized_mm=horizontal_a_src_mm,
            reason=f"error:{exc!r}",
        )

    if d_src is None or d_tgt is None:
        which = []
        if d_src is None:
            which.append(f"source({source_geom.view_position})")
        if d_tgt is None:
            which.append(f"target({target_geom.view_position})")
        return PnlResult(
            available=False,
            a_source_horizontal_mm=horizontal_a_src_mm,
            a_source_perp_mm=perp,
            a_normalized_mm=horizontal_a_src_mm,
            d_source_mm=d_src,
            d_target_mm=d_tgt,
            ratio=None,
            reason="pectoral distance unavailable: " + ", ".join(which),
        )

    if d_src <= 1e-6:
        return PnlResult(
            available=False,
            a_source_horizontal_mm=horizontal_a_src_mm,
            a_source_perp_mm=perp,
            a_normalized_mm=horizontal_a_src_mm,
            d_source_mm=d_src,
            d_target_mm=d_tgt,
            ratio=None,
            reason="source PNL ~0",
        )

    ratio = d_tgt / d_src
    a_norm = perp * ratio   # f * PNL_target, with f = perp / PNL_source
    # Physical cap: never predict a lesion deeper than the chest wall (keeps the
    # region on the image; stops an over-large ratio from dropping the finding).
    if _PNL_DEPTH_CAP_FRAC < 1.0:
        cap = d_tgt * _PNL_DEPTH_CAP_FRAC
        if a_norm > cap:
            a_norm = cap
    return PnlResult(
        available=True,
        a_source_horizontal_mm=horizontal_a_src_mm,
        a_source_perp_mm=perp,
        a_normalized_mm=a_norm,
        d_source_mm=d_src,
        d_target_mm=d_tgt,
        ratio=ratio,
        reason="ok",
    )
