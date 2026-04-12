"""
Pure-DICOM geometry engine for FAST sync and reference lines.

All functions work exclusively in patient-LPS space using IOP/IPP/PixelSpacing.
No VTK world-space or mock-VTK conventions are used.

Used by:
  - _pw_sync._map_sync_dicom  (FAST Qt target branch)
  - qt_viewer_bridge.set_sync_point / _find_closest_slice
  - Future: FAST reference line overlay

Convention (matches pydicom_2d_backend.patient_xyz_to_image_xy):
  IOP[0:3] = row direction  → defines increasing column (image X)
  IOP[3:6] = col direction  → defines increasing row   (image Y)
  PixelSpacing[0] = row spacing   = physical mm per row step
  PixelSpacing[1] = column spacing = physical mm per column step

  col_idx = dot(P - IPP, iop[0:3]) / pixel_spacing[1]
  row_idx = dot(P - IPP, iop[3:6]) / pixel_spacing[0]
"""

import logging
import numpy as np
from typing import Optional, Tuple, List, Dict, Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Low-level pixel ↔ LPS transforms
# ─────────────────────────────────────────────────────────────────────────────

def lps_to_image_pixel(
    P_lps: np.ndarray,
    ipp: np.ndarray,
    iop: List[float],
    pixel_spacing: List[float],
) -> Tuple[float, float]:
    """Patient-LPS point → image pixel (col_idx, row_idx).

    Exact inverse of image_pixel_to_lps.  Matches pydicom_2d_backend
    patient_xyz_to_image_xy exactly so round-trip error is sub-micron.

    Returns (col_idx, row_idx) — NOT (x, y) in screen space.
    col_idx grows along IOP row direction (image X).
    row_idx grows along IOP col direction (image Y).
    """
    d = np.asarray(P_lps, float) - np.asarray(ipp, float)
    row_dir = np.asarray(iop[0:3], float)   # IOP row direction = column axis
    col_dir = np.asarray(iop[3:6], float)   # IOP col direction = row axis
    sx = float(pixel_spacing[1]) if len(pixel_spacing) > 1 else float(pixel_spacing[0])
    sy = float(pixel_spacing[0])
    col_idx = float(np.dot(d, row_dir) / (sx or 1.0))
    row_idx = float(np.dot(d, col_dir) / (sy or 1.0))
    return col_idx, row_idx


def image_pixel_to_lps(
    col_idx: float,
    row_idx: float,
    ipp: np.ndarray,
    iop: List[float],
    pixel_spacing: List[float],
) -> np.ndarray:
    """Image pixel (col_idx, row_idx) → patient-LPS point.

    Exact inverse of lps_to_image_pixel.
    """
    row_dir = np.asarray(iop[0:3], float)
    col_dir = np.asarray(iop[3:6], float)
    sx = float(pixel_spacing[1]) if len(pixel_spacing) > 1 else float(pixel_spacing[0])
    sy = float(pixel_spacing[0])
    return np.asarray(ipp, float) + col_idx * sx * row_dir + row_idx * sy * col_dir


# ─────────────────────────────────────────────────────────────────────────────
# Slice-normal geometry
# ─────────────────────────────────────────────────────────────────────────────

def compute_slice_normal(iop: List[float]) -> Optional[np.ndarray]:
    """Return normalised slice-normal from IOP.

    n = cross(IOP_col_dir, IOP_row_dir) — same convention as reference_line.py.
    Returns None if IOP is degenerate.
    """
    row_dir = np.asarray(iop[0:3], float)
    col_dir = np.asarray(iop[3:6], float)
    n = np.cross(col_dir, row_dir)
    n_len = float(np.linalg.norm(n))
    if n_len < 1e-12:
        return None
    return n / n_len


def compute_inter_slice_spacing(instances: List[Dict[str, Any]]) -> Optional[float]:
    """Compute inter-slice spacing (ds) from IPP[0] and IPP[1] along the normal."""
    if len(instances) < 2:
        return None
    iop = instances[0].get('image_orientation_patient')
    ipp_0 = instances[0].get('image_position_patient')
    ipp_1 = instances[1].get('image_position_patient')
    if not iop or ipp_0 is None or ipp_1 is None:
        return None
    n = compute_slice_normal(iop)
    if n is None:
        return None
    ds = float(np.dot(np.asarray(ipp_1, float) - np.asarray(ipp_0, float), n))
    return ds if abs(ds) > 1e-9 else None


def project_lps_onto_plane(P_lps: np.ndarray, ipp_k: np.ndarray, n: np.ndarray) -> Tuple[np.ndarray, float]:
    """Project P_lps onto the plane defined by (ipp_k, n).

    Returns (P_proj, dp) where dp = signed perpendicular distance.
    P_proj = P_lps - dp * n is on the plane.
    """
    dp = float(np.dot(P_lps - ipp_k, n))
    P_proj = P_lps - dp * n
    return P_proj, dp


# ─────────────────────────────────────────────────────────────────────────────
# Sparse / discontinuous stack analysis
# ─────────────────────────────────────────────────────────────────────────────

# A spacing gap is classified as "large" (inter-group boundary) when it exceeds
# this multiple of the median intra-stack spacing.  For lumbar axial
# disc-by-disc MRI the intra-group spacing is ~1–2 mm and the inter-group gap
# is 8–20 mm; a factor of 3 reliably separates continuous acquisition from
# inter-disc gaps.
_SPARSE_GAP_FACTOR: float = 3.0


def compute_slice_positions(
    instances: List[Dict[str, Any]],
    n_t: Optional[np.ndarray] = None,
) -> Optional[np.ndarray]:
    """Return per-slice scalar positions along the slice normal.

    pos[k] = dot(IPP_k − IPP_0, n_t)

    This is the only correct way to locate each slice for any spacing pattern
    (uniform, sparse, discontinuous).  The two-point approximation used by
    ``compute_inter_slice_spacing`` (ds = IPP_1 − IPP_0) only works for
    uniformly-spaced acquisitions.

    Returns None if any IPP is missing or the normal cannot be computed.
    """
    if not instances:
        return None
    iop = instances[0].get('image_orientation_patient')
    ipp_0 = instances[0].get('image_position_patient')
    if not iop or ipp_0 is None:
        return None
    if n_t is None:
        n_t = compute_slice_normal(iop)
        if n_t is None:
            return None
    ipp_0_arr = np.asarray(ipp_0, float)
    positions: List[float] = []
    for inst in instances:
        ipp = inst.get('image_position_patient')
        if ipp is None:
            return None      # cannot classify if any IPP is missing
        positions.append(float(np.dot(np.asarray(ipp, float) - ipp_0_arr, n_t)))
    return np.asarray(positions, float)


def find_closest_slice_physical(
    P_lps: np.ndarray,
    instances: List[Dict[str, Any]],
    n_t: np.ndarray,
    positions: Optional[np.ndarray] = None,
    prev_k: Optional[int] = None,
    hysteresis_mm: float = 0.0,
) -> Tuple[int, float, float]:
    """Find the physically nearest slice by scanning all per-slice positions.

    This is correct for ANY spacing pattern — uniform, sparse, or
    discontinuous.  The formula-based ``find_closest_slice`` computes
    ``k_float = d0 / ds`` using only the first two slices to estimate ``ds``,
    which gives catastrophically wrong results for sparse stacks.

    Example failure: lumbar axial disc-by-disc with ds≈1 mm between slices
    0–1, but a 15 mm inter-group gap between the L5-S1 group and L4-L5 group.
    A source point 40 mm above IPP_0 gives k_float=40, clamped to the last
    disc group instead of selecting the anatomically correct nearby group.

    Args:
        P_lps:        Patient-LPS source point.
        instances:    Target series instance list.
        n_t:          Normalised slice normal.
        positions:    Pre-computed scalar positions (avoids redundant work).
        prev_k:       Previous slice index for hysteresis.
        hysteresis_mm: Hold on prev_k unless nearest slice is this much closer.

    Returns:
        (k_nearest, d_src, min_dist_mm)
        k_nearest    = index of physically nearest slice
        d_src        = dot(P_lps − IPP_0, n_t)
        min_dist_mm  = physical distance from P_lps to nearest slice plane
    """
    if positions is None:
        positions = compute_slice_positions(instances, n_t)
    if positions is None or len(positions) == 0:
        return 0, 0.0, 0.0

    ipp_0 = instances[0].get('image_position_patient')
    if ipp_0 is None:
        return 0, 0.0, 0.0
    ipp_0_arr = np.asarray(ipp_0, float)
    d_src = float(np.dot(np.asarray(P_lps, float) - ipp_0_arr, n_t))

    dists = np.abs(positions - d_src)
    k_nearest = int(np.argmin(dists))
    min_dist = float(dists[k_nearest])

    # Physical hysteresis: only switch away from prev_k if the new nearest
    # slice is meaningfully closer (more than hysteresis_mm difference).
    if prev_k is not None and hysteresis_mm > 0.0:
        prev_k_clamped = max(0, min(int(prev_k), len(positions) - 1))
        dist_to_prev = float(dists[prev_k_clamped])
        if dist_to_prev <= min_dist + hysteresis_mm:
            k_nearest = prev_k_clamped
            min_dist = dist_to_prev

    return k_nearest, d_src, min_dist


def analyse_target_stack(
    instances: List[Dict[str, Any]],
    positions: Optional[np.ndarray] = None,
    n_t: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Classify a target series as continuous or sparse/discontinuous.

    Computes per-slice spacing and identifies large inter-group gaps.
    This is used to decide whether a source sync point falls inside a valid
    slice group or in an anatomical gap between groups (e.g., between lumbar
    disc levels on axial MRI).

    Returns a dict with:
        positions            : ndarray of per-slice scalar positions (length n)
        spacings             : ndarray |pos[k+1]−pos[k]|  (length n−1)
        typical_spacing_mm   : median spacing (intra-group representative)
        max_gap_mm           : largest spacing (inter-group gap for sparse stacks)
        is_sparse            : True when max_gap > _SPARSE_GAP_FACTOR × typical
        gap_indices          : list of k where spacing[k] is a large gap boundary
    """
    result: Dict[str, Any] = {
        'positions': None, 'spacings': None,
        'typical_spacing_mm': 0.0, 'max_gap_mm': 0.0,
        'is_sparse': False, 'gap_indices': [],
    }
    if len(instances) < 2:
        return result

    if positions is None:
        iop = instances[0].get('image_orientation_patient')
        if not iop:
            return result
        if n_t is None:
            n_t = compute_slice_normal(iop)
        if n_t is None:
            return result
        positions = compute_slice_positions(instances, n_t)
        if positions is None:
            return result

    result['positions'] = positions
    spacings = np.abs(np.diff(positions))
    result['spacings'] = spacings

    if len(spacings) == 0:
        return result

    typical = float(np.median(spacings))
    max_gap = float(np.max(spacings))
    result['typical_spacing_mm'] = typical
    result['max_gap_mm'] = max_gap

    if typical > 1e-9:
        threshold = _SPARSE_GAP_FACTOR * typical
        is_sparse = bool(max_gap > threshold)
        gap_indices = [int(k) for k in np.where(spacings > threshold)[0]]
    else:
        is_sparse = False
        gap_indices = []

    result['is_sparse'] = is_sparse
    result['gap_indices'] = gap_indices
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Slice finder with optional hysteresis (legacy — uniform stacks only)
# ─────────────────────────────────────────────────────────────────────────────

def find_closest_slice(
    P_lps: np.ndarray,
    instances: List[Dict[str, Any]],
    prev_k: Optional[int] = None,
    hysteresis_mm: float = 0.0,
) -> Tuple[int, float, float, Optional[np.ndarray]]:
    """Find the slice index closest to P_lps by IPP/IOP projection.

    Args:
        P_lps:         Patient-LPS point to project.
        instances:     Sorted list of DICOM instance dicts (IOP/IPP required).
        prev_k:        Previous slice index (for hysteresis).
        hysteresis_mm: Minimum |d - prev_d| in mm before the slice changes.
                       0 = no hysteresis (pure rounding).

    Returns:
        (k_tgt, k_float, dp, n_t)
        k_tgt   = clamped slice index
        k_float = un-rounded projection value
        dp      = perpendicular distance from chosen slice plane (mm)
        n_t     = normalised slice normal (or None on failure)
    """
    n = len(instances)
    if n == 0:
        return 0, 0.0, 0.0, None

    iop = instances[0].get('image_orientation_patient')
    ipp_0 = instances[0].get('image_position_patient')
    if not iop or ipp_0 is None:
        return 0, 0.0, 0.0, None

    n_t = compute_slice_normal(iop)
    if n_t is None:
        return 0, 0.0, 0.0, None

    ds = compute_inter_slice_spacing(instances)
    if ds is None or abs(ds) < 1e-9:
        return 0, 0.0, 0.0, n_t

    ipp_0_arr = np.asarray(ipp_0, float)
    d0 = float(np.dot(np.asarray(P_lps, float) - ipp_0_arr, n_t))
    k_float = d0 / ds

    # Optional hysteresis: stay on prev_k if k_float is close to it
    if prev_k is not None and hysteresis_mm > 0.0 and abs(ds) > 1e-9:
        hysteresis_slices = hysteresis_mm / abs(ds)
        if abs(k_float - prev_k) < hysteresis_slices:
            k_tgt = prev_k
        else:
            k_tgt = int(round(k_float))
    else:
        k_tgt = int(round(k_float))

    k_tgt = max(0, min(k_tgt, n - 1))

    # dp = distance from the chosen slice plane
    try:
        ipp_k = np.asarray(instances[k_tgt]['image_position_patient'], float)
    except (KeyError, IndexError, TypeError):
        ipp_k = ipp_0_arr + k_tgt * ds * n_t
    dp = float(np.dot(np.asarray(P_lps, float) - ipp_k, n_t))

    return k_tgt, k_float, dp, n_t


# ─────────────────────────────────────────────────────────────────────────────
# Main: project LPS point fully into target image space
# ─────────────────────────────────────────────────────────────────────────────

class SliceProjectionResult:
    """Result of projecting a patient-LPS point onto a target series."""
    __slots__ = (
        'P_proj', 'k_tgt', 'k_float', 'dp',
        'col_idx', 'row_idx',
        'in_bounds', 'outside_reason',
        'n_t', 'ipp_k',
        'slice_count', 'k_min', 'k_max',
        'k_tgt_after_clamp', 'clamp_occurred',
        'through_plane_distance_mm', 'world_delta_mm',
        'slab_valid', 'inplane_valid', 'final_valid_sync_point',
        'rejection_reason',
        # Sparse / discontinuous stack fields (v2.2.9.2)
        'stack_is_sparse', 'typical_stack_spacing_mm', 'max_stack_gap_mm',
        'min_distance_to_slice_mm', 'between_groups',
        # Slice-thickness through-plane validation (v2.2.9.3)
        'slice_thickness_mm', 'through_plane_valid',
    )

    def __init__(self):
        self.P_proj: Optional[np.ndarray] = None
        self.k_tgt: int = 0
        self.k_float: float = 0.0
        self.dp: float = 0.0
        self.col_idx: float = 0.0
        self.row_idx: float = 0.0
        self.in_bounds: bool = False
        self.outside_reason: List[str] = []
        self.n_t: Optional[np.ndarray] = None
        self.ipp_k: Optional[np.ndarray] = None
        self.slice_count: int = 0
        self.k_min: int = 0
        self.k_max: int = 0
        self.k_tgt_after_clamp: int = 0
        self.clamp_occurred: bool = False
        self.through_plane_distance_mm: float = 0.0
        self.world_delta_mm: float = 0.0
        self.slab_valid: bool = False
        self.inplane_valid: bool = False
        self.final_valid_sync_point: bool = False
        self.rejection_reason: str = 'geometry_error'
        # Sparse / discontinuous stack fields (v2.2.9.2)
        self.stack_is_sparse: bool = False
        self.typical_stack_spacing_mm: float = 0.0
        self.max_stack_gap_mm: float = 0.0
        self.min_distance_to_slice_mm: float = 0.0
        self.between_groups: bool = False
        # Slice-thickness through-plane validation (v2.2.9.3)
        self.slice_thickness_mm: float = 0.0
        self.through_plane_valid: bool = True


def project_lps_to_target(
    P_lps: np.ndarray,
    target_instances: List[Dict[str, Any]],
    prev_k: Optional[int] = None,
    hysteresis_mm: float = 0.0,
) -> Optional[SliceProjectionResult]:
    """Project a patient-LPS point fully into target image (col_idx, row_idx, k_tgt).

    This is the single entry point for FAST sync coordinate mapping.
    All geometry is pure-DICOM (IOP/IPP/PixelSpacing).  No VTK world-space.

    Returns None if geometry metadata is insufficient.
    """
    if not target_instances:
        return None

    inst_0 = target_instances[0]
    iop = inst_0.get('image_orientation_patient')
    if not iop or len(iop) < 6:
        return None

    # ── 1. Slice normal ───────────────────────────────────────────────────────
    n_t = compute_slice_normal(iop)
    if n_t is None:
        return None

    # ── 2. Per-slice physical positions (correct for any spacing pattern) ─────
    positions = compute_slice_positions(target_instances, n_t)

    # ── 3. Stack classification (sparse / continuous) ─────────────────────────
    stack_info = analyse_target_stack(target_instances, positions=positions, n_t=n_t)
    is_sparse = bool(stack_info['is_sparse'])
    typical_spacing = float(stack_info['typical_spacing_mm'])
    max_gap = float(stack_info['max_gap_mm'])

    # ── 4. Physically nearest slice ───────────────────────────────────────────
    # For uniform stacks: equivalent to the old formula-based approach.
    # For sparse stacks: scans all slice positions and picks the nearest one,
    # avoiding the catastrophic formula error (k_float = d0/ds assumes equal
    # spacing, but ds is estimated only from the first two slices).
    if positions is not None:
        k_tgt, d_src, min_dist_mm = find_closest_slice_physical(
            P_lps, target_instances, n_t,
            positions=positions,
            prev_k=prev_k,
            hysteresis_mm=hysteresis_mm,
        )
        # k_float: continuous physical index for diagnostics and slab_valid check.
        # Must divide by the SIGNED median spacing (not the absolute typical_spacing)
        # so that k_float is positive when d_src and the stack progress in the same
        # direction.  compute_slice_normal returns cross(col,row) which can be the
        # opposite of the stack's scan direction (e.g. axial DICOM normal = (0,0,-1)
        # while series z increases from 0→N).  Using absolute typical_spacing would
        # give k_float = d_src / +1 = negative → false slab_invalid.
        _signed_spacings = np.diff(positions)
        _signed_typical = float(np.median(_signed_spacings)) if len(_signed_spacings) else 0.0
        if abs(_signed_typical) > 1e-9:
            k_float = d_src / _signed_typical
        else:
            k_float = float(k_tgt)
    else:
        # Fallback: legacy formula for when any IPP is missing.
        k_tgt, k_float, _dp_legacy, _n_legacy = find_closest_slice(
            P_lps, target_instances, prev_k=prev_k, hysteresis_mm=hysteresis_mm)
        min_dist_mm = 0.0
        d_src = k_float * (typical_spacing if typical_spacing > 1e-9 else 1.0)

    # ── 5. Gap-aware between-groups detection ─────────────────────────────────
    # If the stack is sparse (disc-by-disc MRI, etc.) and the source point is
    # physically far from ALL slices, it lies in an anatomical gap between
    # adjacent disc groups.  Displaying a sync marker in this situation is
    # clinically misleading: the nearest slice does NOT correspond to the
    # anatomy at the source point.
    #
    # Threshold: min_dist > 0.7 × typical_spacing puts the point beyond the
    # halfway mark between two adjacent slices in a continuous intra-group
    # sequence.  In a sparse stack any point in an inter-group gap will be
    # much further than this.
    between_groups = False
    if is_sparse and typical_spacing > 1e-9:
        between_groups = bool(min_dist_mm > 0.7 * typical_spacing)

    # ── 6. Get IPP for chosen slice ───────────────────────────────────────────
    try:
        ipp_k = np.asarray(target_instances[k_tgt]['image_position_patient'], float)
    except (KeyError, IndexError, TypeError):
        return None

    # ── 7. Project P_lps onto the target slice plane ──────────────────────────
    P_proj, dp_exact = project_lps_onto_plane(np.asarray(P_lps, float), ipp_k, n_t)

    # ── 8. LPS → pixel using DICOM pixel_spacing ─────────────────────────────
    pixel_spacing = inst_0.get('pixel_spacing') or [1.0, 1.0]
    col_idx, row_idx = lps_to_image_pixel(P_proj, ipp_k, iop, pixel_spacing)

    # ── 9. In-plane bounds check ──────────────────────────────────────────────
    rows = inst_0.get('rows') or 0
    cols = inst_0.get('columns') or 0
    outside_reason: List[str] = []
    if cols:
        if col_idx < 0:        outside_reason.append('left')
        elif col_idx >= cols:  outside_reason.append('right')
    if rows:
        if row_idx < 0:        outside_reason.append('top')
        elif row_idx >= rows:  outside_reason.append('bottom')

    # ── 10. Validity classification ───────────────────────────────────────────
    slice_count = len(target_instances)
    k_min = 0
    k_max = max(0, slice_count - 1)
    inplane_valid = not bool(outside_reason)
    world_delta_mm = float(np.linalg.norm(P_proj - np.asarray(P_lps, float)))

    if positions is not None and len(positions) > 0:
        # Physical slab check: source must project within the stack's physical
        # extent, with half-spacing tolerance at each end for the first/last
        # slice.  This is correct for both uniform and sparse stacks.
        # NOTE: do NOT use k_float in [0, k_max] for sparse stacks — k_float
        # can be large (e.g., 19 for a point at d_src=-19 with typical=1mm)
        # even though it is a valid in-group source point (k≈19 slice units is
        # not a valid slice INDEX, but the physical distance is within the
        # stack extent).
        _pos_lo = float(np.min(positions))
        _pos_hi = float(np.max(positions))
        _half_tol = 0.5 * typical_spacing if typical_spacing > 1e-9 else 1e-9
        slab_valid = bool((d_src >= _pos_lo - _half_tol) and (d_src <= _pos_hi + _half_tol))
        clamp_occurred = not slab_valid
    else:
        # Fallback (positions=None, rare)
        slab_valid = bool((k_float >= float(k_min) - 1e-9) and (k_float <= float(k_max) + 1e-9))
        clamp_occurred = not slab_valid

    # ── 11. Slice-thickness through-plane validation ─────────────────────────
    # The source point is valid only if it lies within the imaged slab of the
    # nearest target slice: |dp| ≤ SliceThickness/2 (DICOM slab criterion).
    #
    # If |dp| > SliceThickness/2 the source is in an acquisition gap between
    # adjacent slices and the sync cursor would not correspond to any imaged
    # anatomy on the target — even though it is within the overall stack extent.
    #
    # SliceThickness source (in priority order):
    #   1. inst_0['slice_thickness']  (DICOM tag 0018,0050, populated by
    #      _fill_stub_from_dicom_header in v2.2.8.7+)
    #   2. typical_spacing            (fallback: assumes contiguous acquisition;
    #      thickness ≈ spacing ↔ gap = 0, so check is equivalent to the
    #      midpoint Voronoi criterion — always satisfied for uniform stacks)
    #   3. No check                   (single-slice or completely unknown)
    _slice_thickness = float(inst_0.get('slice_thickness') or 0.0)
    if _slice_thickness < 1e-6:
        _slice_thickness = typical_spacing   # fallback
    if _slice_thickness > 1e-6:
        # +1e-6 tolerance absorbs floating-point rounding at the exact midpoint.
        through_plane_valid = bool(min_dist_mm <= _slice_thickness / 2.0 + 1e-6)
    else:
        through_plane_valid = True           # single-slice or no metadata → accept

    # between_groups and through_plane_valid both represent "not on any slice";
    # between_groups is more specific (gap inside a SPARSE stack).
    # Rejection priority: between_groups > out_of_stack > between_slices > out_of_fov
    final_valid = bool(slab_valid and through_plane_valid and inplane_valid and not between_groups)

    if between_groups:
        rejection_reason = 'between_groups'
    elif not slab_valid:
        rejection_reason = 'out_of_stack'
    elif not through_plane_valid:
        rejection_reason = 'between_slices'
    elif not inplane_valid:
        rejection_reason = 'out_of_fov'
    else:
        rejection_reason = 'none'

    res = SliceProjectionResult()
    res.P_proj = P_proj
    res.k_tgt = k_tgt
    res.k_float = k_float
    res.dp = dp_exact
    res.col_idx = col_idx
    res.row_idx = row_idx
    res.in_bounds = not bool(outside_reason)
    res.outside_reason = outside_reason
    res.n_t = n_t
    res.ipp_k = ipp_k
    res.slice_count = slice_count
    res.k_min = k_min
    res.k_max = k_max
    res.k_tgt_after_clamp = k_tgt
    res.clamp_occurred = clamp_occurred
    res.through_plane_distance_mm = float(dp_exact)
    res.world_delta_mm = world_delta_mm
    res.slab_valid = slab_valid
    res.inplane_valid = inplane_valid
    res.final_valid_sync_point = final_valid
    res.rejection_reason = rejection_reason
    res.stack_is_sparse = is_sparse
    res.typical_stack_spacing_mm = typical_spacing
    res.max_stack_gap_mm = max_gap
    res.min_distance_to_slice_mm = min_dist_mm
    res.between_groups = between_groups
    res.slice_thickness_mm = _slice_thickness
    res.through_plane_valid = through_plane_valid
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Roundtrip error measurement
# ─────────────────────────────────────────────────────────────────────────────

def compute_roundtrip_error_mm(
    P_lps: np.ndarray,
    instances: List[Dict[str, Any]],
) -> Tuple[float, float]:
    """Measure patient-space roundtrip error for P_lps on this series.

    LPS → pixel → LPS_back.  Ideal error = 0 (limited by float precision).
    Large errors indicate geometry inconsistency.

    Returns (error_lps_mm, inplane_pixel_error).
    """
    if not instances:
        return float('nan'), float('nan')
    iop = instances[0].get('image_orientation_patient')
    ipp_0 = instances[0].get('image_position_patient')
    pixel_spacing = instances[0].get('pixel_spacing') or [1.0, 1.0]
    if not iop or ipp_0 is None:
        return float('nan'), float('nan')
    try:
        k_tgt, _, dp, n_t = find_closest_slice(P_lps, instances)
        if n_t is None:
            return float('nan'), float('nan')
        ipp_k = np.asarray(instances[k_tgt]['image_position_patient'], float)
        P_proj, _ = project_lps_onto_plane(np.asarray(P_lps, float), ipp_k, n_t)
        col_idx, row_idx = lps_to_image_pixel(P_proj, ipp_k, iop, pixel_spacing)
        P_back = image_pixel_to_lps(col_idx, row_idx, ipp_k, iop, pixel_spacing)
        error_mm = float(np.linalg.norm(P_proj - P_back))
        # In-plane pixel error: go back to pixel from P_back
        col2, row2 = lps_to_image_pixel(P_back, ipp_k, iop, pixel_spacing)
        px_err = float(np.hypot(col2 - col_idx, row2 - row_idx))
        return error_mm, px_err
    except Exception:
        return float('nan'), float('nan')
