"""Pure multi-frame DICOM geometry + classification.

Stdlib + pydicom ONLY — no Qt / VTK / DB / numpy-heavy work — so it is fully
unit-testable offscreen and can be reused by both the FAST 2D pipeline and (later)
the VTK/MPR volume builder without coupling the two domains.

WHY THIS EXISTS
---------------
A standard series is many single-frame files, one image per file; every file
carries its geometry in the TOP-LEVEL tags (ImagePositionPatient / ...Orientation
/ PixelSpacing). ``entry_from_dataset`` reads those and the whole downstream
geometry stack (overlay slice location, ruler pixel spacing, cross-series
reference lines / sync in ``dicom_sync_geometry.py``) works.

An **Enhanced** multi-frame file (Enhanced MR/CT ``1.2.840.10008.5.1.4.1.1.4.1`` /
``...2.1`` / angio / ophthalmic, one .dcm with N frames) puts its geometry ENTIRELY
in the functional groups and leaves the top-level tags EMPTY. So the FAST
expansion — which copies the single top-level geometry onto every frame — gives
every frame IPP=(0,0,0), IOP=identity, spacing=(1,1): the frames display fine but
have NO real geometry, which breaks measurements, the slice-location overlay, and
reference lines, and would make MPR build a degenerate volume.

This module reads the REAL per-frame geometry from the Shared + Per-Frame
Functional Groups and classifies what the multi-frame series actually is, so the
consumers can (a) stamp each frame with its own geometry and (b) decide whether a
meaningful 3-D reconstruction (MPR) is even possible.

DICOM references: PS3.3 C.7.6.16 (Multi-frame Functional Groups),
C.7.6.16.2.x (Plane Position / Plane Orientation / Pixel Measures / Frame Content),
C.7.6.17 (Dimension Organization).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

# ── Classification kinds ────────────────────────────────────────────────────
KIND_SINGLE = "single_frame"              # NumberOfFrames <= 1 (not multi-frame)
KIND_SPATIAL_VOLUME = "spatial_volume"    # one stack of distinct, ordered slices → MPR-eligible
KIND_MULTI_DIMENSIONAL = "multi_dimensional"  # spatial × parametric (e.g. DWI b-values) → MPR on a sub-stack
KIND_MULTI_STACK = "multi_stack"          # >1 stack / orientation (3-plane localizer) → not one volume
KIND_TEMPORAL = "temporal"                # frames = time at ONE location (cine / angio) → never MPR
KIND_UNKNOWN = "unknown"                  # multi-frame but no usable per-frame geometry


def _to_float(v: Any) -> Optional[float]:
    try:
        if isinstance(v, (list, tuple)):
            if not v:
                return None
            v = v[0]
        return float(v)
    except Exception:
        return None


def _float_tuple(v: Any, n: int) -> Optional[Tuple[float, ...]]:
    try:
        if v is None:
            return None
        seq = list(v)
        if len(seq) < n:
            return None
        return tuple(float(seq[i]) for i in range(n))
    except Exception:
        return None


@dataclass(frozen=True)
class FrameGeometry:
    """Per-frame spatial descriptors, resolved from Per-Frame with a fallback to
    Shared functional groups. Any field may be None when the file omits it."""
    frame_index: int
    ipp: Optional[Tuple[float, float, float]] = None
    iop: Optional[Tuple[float, float, float, float, float, float]] = None
    pixel_spacing: Optional[Tuple[float, float]] = None
    slice_thickness: Optional[float] = None
    spacing_between_slices: Optional[float] = None
    stack_id: Optional[str] = None
    in_stack_position: Optional[int] = None
    dimension_index_values: Tuple[int, ...] = ()
    temporal_position_index: Optional[int] = None

    @property
    def has_spatial_geometry(self) -> bool:
        """True only when this frame carries a real position AND orientation."""
        return self.ipp is not None and self.iop is not None and _iop_is_valid(self.iop)


@dataclass
class MultiFrameClassification:
    kind: str
    number_of_frames: int
    frames: List[FrameGeometry] = field(default_factory=list)
    mpr_eligible: bool = False
    reason: str = ""
    # Ordered frame indices that form the MPR volume (one representative per
    # spatial position of the chosen stack). Empty unless mpr_eligible.
    volume_frame_indices: List[int] = field(default_factory=list)
    stack_count: int = 1
    # True when every frame has usable per-frame spatial geometry (reference
    # lines / sync can be trusted per-frame even if the whole thing isn't a
    # single MPR volume).
    per_frame_geometry_valid: bool = False


# ── Functional-group reading ────────────────────────────────────────────────

def _seq_item(ds: Any, name: str):
    """Return sequence[0] for a named sequence attribute, else None."""
    try:
        seq = getattr(ds, name, None)
        if seq is None:
            return None
        if len(seq) == 0:
            return None
        return seq[0]
    except Exception:
        return None


def _resolve_group(per_frame_item: Any, shared_item: Any, seq_name: str):
    """Per-Frame overrides Shared for a named functional-group sub-sequence."""
    it = _seq_item(per_frame_item, seq_name) if per_frame_item is not None else None
    if it is not None:
        return it
    if shared_item is not None:
        return _seq_item(shared_item, seq_name)
    return None


def read_frame_geometries(ds: Any) -> List[FrameGeometry]:
    """Read per-frame geometry for a multi-frame dataset.

    Merges Shared + Per-Frame Functional Groups (per-frame wins). Returns a list
    of length NumberOfFrames (>= 1). Never raises — a missing group yields None
    fields so the caller can fall back to legacy/top-level geometry.
    """
    try:
        n = int(getattr(ds, "NumberOfFrames", 1) or 1)
    except Exception:
        n = 1
    if n < 1:
        n = 1

    shared_item = _seq_item(ds, "SharedFunctionalGroupsSequence")
    per_frame_seq = getattr(ds, "PerFrameFunctionalGroupsSequence", None)

    out: List[FrameGeometry] = []
    for k in range(n):
        pf_item = None
        try:
            if per_frame_seq is not None and k < len(per_frame_seq):
                pf_item = per_frame_seq[k]
        except Exception:
            pf_item = None

        plane_pos = _resolve_group(pf_item, shared_item, "PlanePositionSequence")
        plane_orient = _resolve_group(pf_item, shared_item, "PlaneOrientationSequence")
        pixel_meas = _resolve_group(pf_item, shared_item, "PixelMeasuresSequence")
        frame_content = _resolve_group(pf_item, shared_item, "FrameContentSequence")

        ipp = _float_tuple(getattr(plane_pos, "ImagePositionPatient", None), 3) if plane_pos is not None else None
        iop = _float_tuple(getattr(plane_orient, "ImageOrientationPatient", None), 6) if plane_orient is not None else None
        px = _float_tuple(getattr(pixel_meas, "PixelSpacing", None), 2) if pixel_meas is not None else None
        thick = _to_float(getattr(pixel_meas, "SliceThickness", None)) if pixel_meas is not None else None
        sbs = _to_float(getattr(pixel_meas, "SpacingBetweenSlices", None)) if pixel_meas is not None else None

        stack_id = None
        in_stack = None
        dim_idx: Tuple[int, ...] = ()
        temporal = None
        if frame_content is not None:
            sid = getattr(frame_content, "StackID", None)
            stack_id = str(sid) if sid is not None else None
            isp = getattr(frame_content, "InStackPositionNumber", None)
            try:
                in_stack = int(isp) if isp is not None else None
            except Exception:
                in_stack = None
            try:
                div = getattr(frame_content, "DimensionIndexValues", None)
                if div is not None:
                    dim_idx = tuple(int(x) for x in list(div))
            except Exception:
                dim_idx = ()
            tpi = getattr(frame_content, "TemporalPositionIndex", None)
            try:
                temporal = int(tpi) if tpi is not None else None
            except Exception:
                temporal = None

        out.append(FrameGeometry(
            frame_index=k, ipp=ipp, iop=iop, pixel_spacing=px,
            slice_thickness=thick, spacing_between_slices=sbs,
            stack_id=stack_id, in_stack_position=in_stack,
            dimension_index_values=dim_idx, temporal_position_index=temporal,
        ))
    return out


# ── Small vector helpers (stdlib math, no numpy) ────────────────────────────

def _cross(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def _norm(a: Sequence[float]) -> float:
    return _dot(a, a) ** 0.5


def _iop_is_valid(iop: Optional[Sequence[float]]) -> bool:
    """A usable orientation: two non-degenerate, non-parallel direction cosines."""
    if iop is None or len(iop) < 6:
        return False
    r = iop[0:3]
    c = iop[3:6]
    if _norm(r) < 1e-6 or _norm(c) < 1e-6:
        return False
    n = _cross(r, c)
    return _norm(n) > 1e-6


def slice_normal(iop: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    if not _iop_is_valid(iop):
        return None
    n = _cross(iop[0:3], iop[3:6])
    m = _norm(n)
    if m < 1e-9:
        return None
    return (n[0] / m, n[1] / m, n[2] / m)


def _position_along(ipp: Sequence[float], normal: Sequence[float]) -> float:
    return _dot(ipp, normal)


def _iop_key(iop: Sequence[float], ndigits: int = 2) -> Tuple[float, ...]:
    return tuple(round(float(x), ndigits) for x in iop)


# ── Classification ──────────────────────────────────────────────────────────

def classify_frames(
    frames: List[FrameGeometry],
    *,
    position_epsilon_mm: float = 0.5,
    spacing_tolerance: float = 0.35,
) -> MultiFrameClassification:
    """Classify a multi-frame series from its per-frame geometry.

    - SPATIAL_VOLUME: one stack, distinct ordered positions, consistent IOP,
      ~uniform spacing → MPR-eligible.
    - MULTI_DIMENSIONAL: spatial × parametric (repeated positions, e.g. DWI) →
      MPR-eligible on ONE representative sub-stack.
    - MULTI_STACK: >1 orientation / StackID (localizer) → not a single volume.
    - TEMPORAL: every frame at the same location (cine / angio) → never MPR.
    - UNKNOWN: multi-frame with no usable per-frame geometry.
    """
    n = len(frames)
    result = MultiFrameClassification(kind=KIND_UNKNOWN, number_of_frames=n, frames=list(frames))
    if n <= 1:
        result.kind = KIND_SINGLE
        result.reason = "single frame"
        result.per_frame_geometry_valid = bool(frames and frames[0].has_spatial_geometry)
        return result

    spatial = [f for f in frames if f.has_spatial_geometry]
    result.per_frame_geometry_valid = (len(spatial) == n)
    if not spatial:
        result.kind = KIND_UNKNOWN
        result.reason = "no per-frame spatial geometry (position/orientation absent)"
        return result

    # Group by orientation (rounded IOP). A localizer has several orientations.
    orient_groups: dict = {}
    for f in spatial:
        orient_groups.setdefault(_iop_key(f.iop), []).append(f)

    # Also note explicit StackIDs when present.
    stack_ids = {f.stack_id for f in spatial if f.stack_id is not None}
    result.stack_count = max(len(orient_groups), len(stack_ids) or 1)

    if len(orient_groups) > 1 or len(stack_ids) > 1:
        result.kind = KIND_MULTI_STACK
        result.reason = (
            f"multiple stacks/orientations "
            f"(orientations={len(orient_groups)}, stack_ids={len(stack_ids) or 1}) "
            f"— localizer / survey, not a single volume"
        )
        # MPR could still work on the LARGEST coherent stack; expose it.
        largest = max(orient_groups.values(), key=len)
        vol = _volume_frames_for_group(largest, position_epsilon_mm, spacing_tolerance)
        if vol and len(vol) >= 3:
            result.mpr_eligible = True
            result.volume_frame_indices = vol
            result.reason += f"; largest stack is volumetric ({len(vol)} slices)"
        return result

    # Single orientation group.
    group = spatial
    normal = slice_normal(group[0].iop)
    if normal is None:
        result.kind = KIND_UNKNOWN
        result.reason = "degenerate orientation"
        return result

    positions = [_position_along(f.ipp, normal) for f in group]
    span = max(positions) - min(positions)
    if span < position_epsilon_mm:
        result.kind = KIND_TEMPORAL
        result.reason = (
            f"all {n} frames at one location (position span {span:.3f} mm) "
            f"— temporal / cine / angio, not spatial"
        )
        return result

    # Distinct positions exist. Are positions repeated (multi-dimensional)?
    distinct = _distinct_positions(positions, position_epsilon_mm)
    vol = _volume_frames_for_group(group, position_epsilon_mm, spacing_tolerance)

    if len(distinct) < n - _duplicate_slack(n):
        # Many frames share positions → parametric dimension present (DWI, multi-echo).
        result.kind = KIND_MULTI_DIMENSIONAL
        result.reason = (
            f"{n} frames over {len(distinct)} spatial positions "
            f"— multi-dimensional (spatial × parametric)"
        )
        if vol and len(vol) >= 3:
            result.mpr_eligible = True
            result.volume_frame_indices = vol
            result.reason += f"; MPR on one sub-stack ({len(vol)} slices)"
        return result

    # Clean one-frame-per-position spatial stack.
    if vol and len(vol) >= 3:
        result.kind = KIND_SPATIAL_VOLUME
        result.mpr_eligible = True
        result.volume_frame_indices = vol
        result.reason = f"spatial volume: {len(vol)} ordered slices, consistent orientation"
    else:
        result.kind = KIND_SPATIAL_VOLUME
        result.mpr_eligible = False
        result.volume_frame_indices = []
        result.reason = "spatial but fewer than 3 usable slices or non-uniform spacing"
    return result


def _duplicate_slack(n: int) -> int:
    # Allow a couple of coincidental near-equal positions before calling it
    # multi-dimensional.
    return max(1, n // 20)


def _distinct_positions(positions: Sequence[float], eps: float) -> List[float]:
    out: List[float] = []
    for p in sorted(positions):
        if not out or abs(p - out[-1]) > eps:
            out.append(p)
    return out


def _volume_frames_for_group(
    group: List[FrameGeometry],
    position_epsilon_mm: float,
    spacing_tolerance: float,
) -> List[int]:
    """Pick one representative frame per distinct spatial position, ordered along
    the normal, and require ~uniform spacing. Returns frame indices, or [] when
    the group is not a valid volume.

    For a multi-dimensional group (several frames at one position), the
    representative is the frame with the smallest DimensionIndexValues /
    temporal index — a deterministic single parametric sub-stack.
    """
    if len(group) < 3:
        return []
    normal = slice_normal(group[0].iop)
    if normal is None:
        return []
    # Consistent orientation across the group.
    for f in group:
        nn = slice_normal(f.iop)
        if nn is None or abs(_dot(nn, normal)) < 0.999:
            return []

    # Bucket frames by position; representative = lowest (dim idx, temporal, frame).
    buckets: dict = {}
    for f in group:
        pos = _position_along(f.ipp, normal)
        placed = False
        for key in list(buckets.keys()):
            if abs(pos - key) <= position_epsilon_mm:
                buckets[key].append((pos, f))
                placed = True
                break
        if not placed:
            buckets[pos] = [(pos, f)]

    reps: List[Tuple[float, int]] = []
    for _key, items in buckets.items():
        def _rank(pf):
            _pos, fr = pf
            return (
                fr.dimension_index_values or (fr.temporal_position_index or 0,),
                fr.temporal_position_index if fr.temporal_position_index is not None else 0,
                fr.frame_index,
            )
        items_sorted = sorted(items, key=_rank)
        rep_pos, rep_frame = items_sorted[0]
        reps.append((rep_pos, rep_frame.frame_index))

    reps.sort(key=lambda t: t[0])
    if len(reps) < 3:
        return []

    gaps = [reps[i + 1][0] - reps[i][0] for i in range(len(reps) - 1)]
    if not gaps:
        return []
    med = sorted(gaps)[len(gaps) // 2]
    if med <= 1e-6:
        return []
    for g in gaps:
        if abs(g - med) > spacing_tolerance * med:
            return []  # non-uniform spacing → not a clean volume
    return [idx for _pos, idx in reps]


# ── Convenience ─────────────────────────────────────────────────────────────

def classify_dataset(ds: Any, **kwargs) -> MultiFrameClassification:
    """Read + classify in one call from a pydicom dataset."""
    return classify_frames(read_frame_geometries(ds), **kwargs)


def classify_series_files(files, *, dcmread=None) -> Optional[MultiFrameClassification]:
    """MPR gate helper. Classify a RESOLVED list of series files.

    Returns a ``MultiFrameClassification`` ONLY when the series is a SINGLE
    multi-frame file (the one case the VTK volume builder cannot assemble, per
    ``image_io.load_vtk_from_dicom_paths``: a multi-frame file becomes one
    degenerate instance). Returns None for a standard MULTI-FILE series or a
    single-frame single-file series, so ordinary MPR proceeds untouched. Never
    raises.
    """
    try:
        seq = list(files or [])
    except Exception:
        return None
    if len(seq) != 1:
        return None  # standard multi-file series (or empty) → not multi-frame
    try:
        import pydicom  # local import: keep module import-light
        rd = dcmread or pydicom.dcmread
        ds = rd(str(seq[0]), stop_before_pixels=True, force=True)
        n = int(getattr(ds, "NumberOfFrames", 1) or 1)
    except Exception:
        return None
    if n <= 1:
        return None  # single-frame single-file → standard behaviour
    try:
        return classify_dataset(ds)
    except Exception:
        return None
