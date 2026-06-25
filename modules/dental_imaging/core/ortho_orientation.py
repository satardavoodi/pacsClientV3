# -*- coding: utf-8 -*-
"""Pure ortho-view orientation for Dental Imaging (stdlib only — unit-testable).

REUSES the standard-MPR geometry contract: the volume's own ``DirectionMatrix``
(field-data 4x4, columns = patient-LPS direction of each VTK volume axis x/y/z) is
the single source of truth. From it we derive, for each anatomical view, which
volume axis is the through-plane (slice) axis, which two are in-plane, and the flips
needed so the rendered slice follows the SAME radiological convention the standard
(Zeta) MPR renders (see docs/pipelines/mpr-geometry-pipeline.md §6.2/§10b):

    axial    : up = Anterior , right = patient Left   (A-top, R-left, L-right)
    sagittal : up = Superior , right = Posterior       (S-top, A-left, P-right)
    coronal  : up = Superior , right = patient Left     (S-top, R-left, L-right)

We do NOT recompute geometry — we read the volume's DirectionMatrix and snap each
volume axis to its dominant patient axis (exact for axis-aligned CBCT; the dental
case). No Qt, no VTK, no numpy. The workspace converts the returned VTK-axis plan to
numpy slicing.

Patient frame is LPS: +X = Left, +Y = Posterior, +Z = Superior.
VTK volume axes: 0 = x (columns/i), 1 = y (rows/j), 2 = z (slices/k).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# Per-view radiological target as patient-LPS unit vectors: (normal, right, up).
_VIEW_TARGETS = {
    "axial":    ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),  # n=S, right=L, up=A
    "sagittal": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),   # n=L, right=P, up=S
    "coronal":  ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),   # n=A/P, right=L, up=S
}
# Letter for the +/- end of each patient axis.
_POS_LABEL = ("L", "P", "S")   # +X=L, +Y=P, +Z=S
_NEG_LABEL = ("R", "A", "I")   # -X=R, -Y=A, -Z=I  (I = Inferior / Foot)


def axis_patient_dirs(direction16: Optional[List[float]]) -> List[Tuple[float, float, float]]:
    """Patient-LPS direction of each VTK volume axis (x, y, z) = the 3 columns of the
    3x3 part of the row-major 4x4 ``DirectionMatrix``. Identity if not provided."""
    if not direction16 or len(direction16) < 16:
        return [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    m = direction16
    # column c = (M[0,c], M[1,c], M[2,c])
    return [(m[0 + c], m[4 + c], m[8 + c]) for c in range(3)]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _label_for(dirs, axis: int, positive: bool) -> str:
    """Letter for the +/- end of a volume axis: snap its patient dir to the dominant
    patient axis, then pick the L/R, A/P or S/I letter for that signed end."""
    d = dirs[axis]
    k = max(range(3), key=lambda i: abs(d[i]))   # dominant patient axis (0=X,1=Y,2=Z)
    pos_toward_plus = (d[k] >= 0) == positive     # does this end point toward +patient-axis?
    return _POS_LABEL[k] if pos_toward_plus else _NEG_LABEL[k]


def plan_view(direction16: Optional[List[float]], view: str) -> Dict:
    """Return the display plan for ``view`` ('axial'|'coronal'|'sagittal').

    Keys: ``through`` / ``h`` / ``v`` (VTK axis 0/1/2), ``flip_h`` / ``flip_v`` (bool),
    and ``labels`` = {top,bottom,left,right}. Pure; deterministic.
    """
    if view not in _VIEW_TARGETS:
        raise ValueError(f"unknown view: {view}")
    normal_pat, right_pat, up_pat = _VIEW_TARGETS[view]
    dirs = axis_patient_dirs(direction16)

    # through-plane axis = volume axis most parallel to the view's plane normal
    through = max(range(3), key=lambda a: abs(_dot(dirs[a], normal_pat)))
    remaining = [a for a in range(3) if a != through]
    # horizontal axis = the remaining axis most parallel to the view's "right"
    h = max(remaining, key=lambda a: abs(_dot(dirs[a], right_pat)))
    v = remaining[0] if remaining[1] == h else remaining[1]

    # display columns increase left->right; we want rightmost = +right_pat
    flip_h = _dot(dirs[h], right_pat) < 0.0
    # display rows increase top->bottom; we want top row = +up_pat end
    flip_v = _dot(dirs[v], up_pat) > 0.0

    # labels: after flips, the rightmost end is +right_pat, top is +up_pat
    right_lbl = _label_for(dirs, h, positive=not flip_h)
    left_lbl = _label_for(dirs, h, positive=flip_h)
    top_lbl = _label_for(dirs, v, positive=flip_v)
    bottom_lbl = _label_for(dirs, v, positive=not flip_v)

    return {
        "through": through, "h": h, "v": v,
        "flip_h": flip_h, "flip_v": flip_v,
        "labels": {"top": top_lbl, "bottom": bottom_lbl, "left": left_lbl, "right": right_lbl},
    }
