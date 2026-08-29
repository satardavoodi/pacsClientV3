"""Pure-DICOM geometry for the Eagle Eye lumbar pipeline.

No Qt, no VTK, no pydicom. Every function takes plain instance dicts of the
shape the workstation already carries in ``metadata['instances']``::

    {'image_position_patient':    [x, y, z],
     'image_orientation_patient': [rx, ry, rz, cx, cy, cz],
     'pixel_spacing':             [row_mm, col_mm],
     'rows': int, 'columns': int,
     'sop_uid': str, 'instance_number': int, 'instance_path': str}

so the whole module is headless-testable.

The slice-normal / nearest-slice math is NOT reimplemented here: it is imported
from ``modules.viewer.fast.dicom_sync_geometry``, the single geometry authority
both viewer backends already route through (``_pw_sync`` imports it for the
Advanced path too). Duplicating it would be exactly the kind of bespoke second
implementation that has bitten this codebase before.

Coordinate convention (DICOM patient LPS):
    +x -> patient LEFT, +y -> patient POSTERIOR, +z -> patient SUPERIOR (head)
so a sagittal slice's position along x tells you right-vs-left, and an axial
slice's position along z tells you head-vs-feet.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from modules.viewer.fast.dicom_sync_geometry import (
    compute_slice_normal,
    compute_slice_positions,
    find_closest_slice_physical,
    image_pixel_to_lps,
)

from .constants import (
    ORDER_INFERIOR_TO_SUPERIOR,
    ORDER_LEFT_TO_RIGHT,
    ORDER_RIGHT_TO_LEFT,
    ORDER_SUPERIOR_TO_INFERIOR,
    ORDER_UNKNOWN,
    PLANE_AXIAL,
    PLANE_CORONAL,
    PLANE_OBLIQUE,
    PLANE_SAGITTAL,
    PLANE_UNKNOWN,
    PREFERRED_ORDER,
)

logger = logging.getLogger(__name__)

# A slice normal counts as "in plane" when its dominant axis carries at least
# this fraction of the unit vector. cos(30 deg) = 0.866, so a scan tilted up to
# ~30 degrees off a cardinal plane is still classified as that plane - which is
# what lumbar sagittals and disc-angled axials actually are. Anything flatter
# than that is reported as oblique rather than guessed.
_DOMINANT_AXIS_MIN = 0.866

# Lateral bands measured from the estimated patient midline, in millimetres.
# Chosen for the lumbar spine: the central canal is ~10 mm wide, the lateral
# recess sits just off midline, and the neural foramen is roughly 12-22 mm out.
_BAND_CENTRAL_MM = 5.0
_BAND_PARACENTRAL_MM = 12.0
_BAND_FORAMINAL_MM = 22.0


# ---------------------------------------------------------------------------
# Plane classification
# ---------------------------------------------------------------------------

def classify_plane(iop: Optional[Sequence[float]]) -> str:
    """Return the acquisition plane implied by ``ImageOrientationPatient``.

    Uses the slice normal only - never a series description. Returns one of
    ``sagittal`` / ``axial`` / ``coronal`` / ``oblique`` / ``unknown``.
    """
    if iop is None:
        return PLANE_UNKNOWN
    try:
        iop = [float(v) for v in iop]
    except (TypeError, ValueError):
        return PLANE_UNKNOWN
    if len(iop) < 6:
        return PLANE_UNKNOWN

    normal = compute_slice_normal(iop)
    if normal is None:
        return PLANE_UNKNOWN

    components = np.abs(np.asarray(normal, dtype=float))
    axis = int(np.argmax(components))
    if float(components[axis]) < _DOMINANT_AXIS_MIN:
        return PLANE_OBLIQUE
    # normal along x -> slices stack left-right -> sagittal
    # normal along y -> slices stack front-back -> coronal
    # normal along z -> slices stack head-feet  -> axial
    return (PLANE_SAGITTAL, PLANE_CORONAL, PLANE_AXIAL)[axis]


def series_plane(instances: Sequence[Dict[str, Any]]) -> str:
    """Plane of a whole series, taken from its first geometry-bearing instance."""
    for inst in instances or ():
        iop = (inst or {}).get("image_orientation_patient")
        if iop:
            return classify_plane(iop)
    return PLANE_UNKNOWN


# ---------------------------------------------------------------------------
# Capture ordering
# ---------------------------------------------------------------------------

class CaptureOrder:
    """A deterministic walk over a loaded stack.

    ``indices`` are VIEWER slice indices in the anatomical order the sweep
    should visit them. The stack itself is never re-sorted: re-sorting
    ``metadata['instances']`` by IPP is explicitly forbidden (it breaks the
    reference-line engine), so the anatomical order lives here as an index
    permutation instead.
    """

    __slots__ = ("indices", "direction", "axis", "positions_mm", "from_geometry")

    def __init__(self, indices, direction, axis, positions_mm, from_geometry):
        self.indices: List[int] = list(indices)
        self.direction: str = direction
        self.axis: str = axis
        self.positions_mm: List[float] = list(positions_mm)
        self.from_geometry: bool = bool(from_geometry)

    def __len__(self) -> int:
        return len(self.indices)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "axis": self.axis,
            "slice_count": len(self.indices),
            "from_geometry": self.from_geometry,
            "viewer_index_order": list(self.indices),
        }


def _axis_for_plane(plane: str) -> Tuple[int, str]:
    """(LPS component index, human axis name) the given plane advances along."""
    if plane == PLANE_SAGITTAL:
        return 0, "lps_x"
    if plane == PLANE_AXIAL:
        return 2, "lps_z"
    if plane == PLANE_CORONAL:
        return 1, "lps_y"
    return 2, "lps_z"


def axis_values(instances: Sequence[Dict[str, Any]], component: int) -> Optional[List[float]]:
    """Raw LPS component of every instance's ImagePositionPatient, or None."""
    out: List[float] = []
    for inst in instances or ():
        ipp = (inst or {}).get("image_position_patient")
        if ipp is None:
            return None
        try:
            out.append(float(ipp[component]))
        except (TypeError, ValueError, IndexError):
            return None
    return out or None


def build_capture_order(
    instances: Sequence[Dict[str, Any]],
    plane: Optional[str] = None,
    preferred_direction: Optional[str] = None,
) -> CaptureOrder:
    """Order a stack anatomically and say, explicitly, which way it runs.

    ``InstanceNumber == 1`` is never assumed to mean right (or superior): the
    direction comes from ImagePositionPatient. When the geometry is unusable the
    stack order is kept as-is and the direction is reported as ``unknown`` -
    the manifest then says so rather than claiming an anatomical direction the
    data could not support.
    """
    count = len(instances or ())
    if count == 0:
        return CaptureOrder([], ORDER_UNKNOWN, "", [], False)

    if plane is None:
        plane = series_plane(instances)
    component, axis_name = _axis_for_plane(plane)
    values = axis_values(instances, component)

    if values is None:
        return CaptureOrder(range(count), ORDER_UNKNOWN, axis_name, [], False)

    ascending = sorted(range(count), key=lambda k: values[k])
    if plane == PLANE_SAGITTAL:
        # +x is patient LEFT, so ascending x runs right -> left.
        asc_dir, desc_dir = ORDER_RIGHT_TO_LEFT, ORDER_LEFT_TO_RIGHT
    elif plane == PLANE_AXIAL:
        # +z is patient SUPERIOR, so ascending z runs feet -> head.
        asc_dir, desc_dir = ORDER_INFERIOR_TO_SUPERIOR, ORDER_SUPERIOR_TO_INFERIOR
    else:
        asc_dir, desc_dir = ORDER_UNKNOWN, ORDER_UNKNOWN

    if preferred_direction is None:
        preferred_direction = PREFERRED_ORDER.get(plane)

    if preferred_direction == desc_dir:
        indices = list(reversed(ascending))
        direction = desc_dir
    else:
        indices = ascending
        direction = asc_dir

    return CaptureOrder(indices, direction, axis_name, [values[k] for k in indices], True)


# ---------------------------------------------------------------------------
# Sagittal T2 <-> T1 matching
# ---------------------------------------------------------------------------

class SliceMatch:
    """Result of projecting one slice of a series onto another series."""

    __slots__ = ("index", "distance_mm", "matched")

    def __init__(self, index: int, distance_mm: float, matched: bool):
        self.index = int(index)
        self.distance_mm = float(distance_mm)
        self.matched = bool(matched)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "distance_mm": round(self.distance_mm, 3),
            "matched": self.matched,
        }


def slice_center_lps(inst: Dict[str, Any]) -> Optional[np.ndarray]:
    """Patient-LPS point at the centre of one slice's image plane."""
    if not inst:
        return None
    ipp = inst.get("image_position_patient")
    iop = inst.get("image_orientation_patient")
    if ipp is None or not iop:
        return None
    spacing = inst.get("pixel_spacing") or [1.0, 1.0]
    try:
        rows = float(inst.get("rows") or 0.0)
        cols = float(inst.get("columns") or 0.0)
    except (TypeError, ValueError):
        rows = cols = 0.0
    try:
        return image_pixel_to_lps(cols / 2.0, rows / 2.0, np.asarray(ipp, float), list(iop), list(spacing))
    except Exception:
        return None


def match_slice_across_series(
    source_instances: Sequence[Dict[str, Any]],
    source_index: int,
    target_instances: Sequence[Dict[str, Any]],
    max_distance_mm: float = 12.0,
) -> SliceMatch:
    """Nearest anatomically-corresponding slice of ``target`` for one source slice.

    Works off ImagePositionPatient / ImageOrientationPatient, so it is correct
    when the two series have different slice counts, different spacing or a
    discontinuous (disc-by-disc) acquisition. ``matched`` is False when the
    nearest target plane is further than ``max_distance_mm`` away - the sweep
    still shows that slice (it is genuinely the closest one) but the manifest
    records that the correspondence is weak.
    """
    if not target_instances:
        return SliceMatch(0, float("inf"), False)
    if not source_instances or not (0 <= source_index < len(source_instances)):
        return SliceMatch(0, float("inf"), False)

    src = source_instances[source_index] or {}
    point = slice_center_lps(src)
    if point is None:
        ipp = src.get("image_position_patient")
        if ipp is None:
            return SliceMatch(0, float("inf"), False)
        point = np.asarray(ipp, float)

    iop_t = (target_instances[0] or {}).get("image_orientation_patient")
    normal_t = compute_slice_normal(iop_t) if iop_t else None
    if normal_t is None:
        return SliceMatch(0, float("inf"), False)

    positions = compute_slice_positions(target_instances, normal_t)
    if positions is None:
        return SliceMatch(0, float("inf"), False)

    k, _d_src, dist = find_closest_slice_physical(point, target_instances, normal_t, positions=positions)
    return SliceMatch(k, dist, dist <= float(max_distance_mm))


# ---------------------------------------------------------------------------
# Spatial context labels (spec 5 / spec 10)
# ---------------------------------------------------------------------------

def estimate_midline_x(
    axial_instances: Sequence[Dict[str, Any]],
    sagittal_instances: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[float]:
    """Best estimate of the patient midline as an LPS x-coordinate.

    Preferred source is the centre of the axial field of view, which for a
    lumbar protocol is centred on the spine. Falls back to the midpoint of the
    sagittal stack's own x-range, and finally to None when neither series
    carries usable geometry.
    """
    for inst in axial_instances or ():
        centre = slice_center_lps(inst)
        if centre is not None:
            return float(centre[0])

    values = axis_values(sagittal_instances or (), 0)
    if values:
        return (min(values) + max(values)) / 2.0
    return None


def sagittal_context(x_lps: Optional[float], midline_x: Optional[float]) -> Dict[str, Any]:
    """Describe where a sagittal slice sits relative to the midline.

    Returns ``side`` (right/left/midline), ``region`` (central / paracentral /
    foraminal / extraforaminal) and the signed offset in millimetres, so every
    captured frame carries the spatial context the later analysis stage needs.
    """
    if x_lps is None or midline_x is None:
        return {"side": "unknown", "region": "unknown", "offset_mm": None}

    offset = float(x_lps) - float(midline_x)
    magnitude = abs(offset)

    if magnitude <= _BAND_CENTRAL_MM:
        side = "midline"
        region = "central_canal"
    else:
        side = "left" if offset > 0 else "right"
        if magnitude <= _BAND_PARACENTRAL_MM:
            region = "paracentral_lateral_recess"
        elif magnitude <= _BAND_FORAMINAL_MM:
            region = "neural_foraminal"
        else:
            region = "extraforaminal"

    return {"side": side, "region": region, "offset_mm": round(offset, 2)}


def axial_context(
    z_lps: Optional[float],
    axial_positions: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Describe where an axial slice sits craniocaudally within its own stack.

    No vertebral-level naming is attempted - that needs anatomy the stage-1
    pipeline deliberately does not infer. What is recorded is the z-coordinate
    and the distance from the most superior slice of the stack, which is
    unambiguous and reproducible.
    """
    if z_lps is None:
        return {"z_lps": None, "mm_below_top": None}
    result: Dict[str, Any] = {"z_lps": round(float(z_lps), 2), "mm_below_top": None}
    if axial_positions:
        try:
            top = max(float(v) for v in axial_positions)
            result["mm_below_top"] = round(top - float(z_lps), 2)
        except (TypeError, ValueError):
            pass
    return result
