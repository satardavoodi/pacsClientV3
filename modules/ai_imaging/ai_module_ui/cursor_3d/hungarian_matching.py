"""
Hungarian Matching — Globally optimal lesion assignment between CC and MLO views.

Replaces the greedy matching strategy with the Hungarian (Kuhn-Munkres) algorithm
which finds the GLOBAL minimum-cost assignment between lesions in two views.

Cost Function:
    The cost of assigning CC lesion i to MLO lesion j is a weighted combination of:
    1. NAD difference: |d_CC(i) - d_MLO(j)| in mm.
    2. Relative anatomical position (height offset in mm).
    3. Quadrant consistency penalty (from quadrant_consistency module).

    cost(i, j) = w1 × |NAD_CC - NAD_MLO|
               + w2 × |height_offset|
               + w3 × quadrant_penalty(i, j)

Unmatched Lesions:
    If cost exceeds a threshold, the lesion is left unmatched and projected
    as an arc in the target view. The algorithm handles rectangular cost
    matrices (different numbers of lesions in each view) by padding.

References:
    - Kuhn, H.W. (1955). "The Hungarian Method for the assignment problem."
    - scipy.optimize.linear_sum_assignment (C implementation)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ─── Cost Function Weights ───────────────────────────────────────────────────

# Weight for NAD (nipple-to-abnormality distance) difference
W_NAD = 1.0
# Weight for vertical position offset
W_HEIGHT = 0.3
# Weight for quadrant inconsistency penalty
W_QUADRANT = 5.0
# Maximum allowable cost for a valid assignment (above → unmatched)
MAX_ASSIGNMENT_COST = 25.0  # mm-equivalent


# ─── Data Structures ─────────────────────────────────────────────────────────


@dataclass
class LesionDescriptor:
    """
    A lesion's geometric properties used for matching.

    All measurements are in millimeters (physical space).
    """
    index: int  # Original index in the lesion list
    nad_mm: float  # Distance from nipple to lesion center (mm)
    height_mm: float  # Vertical position relative to nipple (mm, positive=below)
    center_x_mm: float
    center_y_mm: float
    quadrant: str  # Anatomical quadrant: 'UO', 'UI', 'LO', 'LI', 'C'
    score: float  # AI detection confidence


@dataclass
class MatchAssignment:
    """
    Result of the global matching: one CC-MLO pair or an unmatched lesion.
    """
    cc_index: int  # Index in CC lesion list (-1 if unmatched)
    mlo_index: int  # Index in MLO lesion list (-1 if unmatched)
    cost: float  # Assignment cost (mm-equivalent)
    nad_difference_mm: float
    height_difference_mm: float
    quadrant_penalty: float
    is_matched: bool  # True if below threshold


@dataclass
class HungarianMatchResult:
    """
    Complete result of the Hungarian matching algorithm.
    """
    assignments: List[MatchAssignment] = field(default_factory=list)
    unmatched_cc: List[int] = field(default_factory=list)
    unmatched_mlo: List[int] = field(default_factory=list)
    cost_matrix: Optional[np.ndarray] = None

    @property
    def matched_count(self) -> int:
        return sum(1 for a in self.assignments if a.is_matched)

    @property
    def total_cost(self) -> float:
        return sum(a.cost for a in self.assignments if a.is_matched)


# ─── Cost Matrix Construction ────────────────────────────────────────────────


def compute_assignment_cost(
    cc_desc: LesionDescriptor,
    mlo_desc: LesionDescriptor,
    quadrant_penalty_fn: Optional[object] = None,
) -> Tuple[float, float, float, float]:
    """
    Compute the cost of assigning a CC lesion to an MLO lesion.

    Returns:
        (total_cost, nad_diff, height_diff, quadrant_penalty)

    Mathematical basis:
        NAD difference: Kopans' Rule states that nipple-to-lesion distance
        should be approximately preserved between views (within ±10%).

        Height offset: In CC view, vertical = medial-lateral axis.
                       In MLO view, vertical = combined cranio-caudal + anterior-posterior.
                       These don't correspond directly, hence lower weight.

        Quadrant penalty: Anatomically, a lesion's quadrant is partially
                         preserved across views (UO in CC should map to a
                         compatible region in MLO).
    """
    nad_diff = abs(cc_desc.nad_mm - mlo_desc.nad_mm)
    height_diff = abs(cc_desc.height_mm - mlo_desc.height_mm)

    # Quadrant penalty
    quad_penalty = 0.0
    if quadrant_penalty_fn is not None:
        quad_penalty = quadrant_penalty_fn(cc_desc.quadrant, mlo_desc.quadrant)

    total = W_NAD * nad_diff + W_HEIGHT * height_diff + W_QUADRANT * quad_penalty
    return (total, nad_diff, height_diff, quad_penalty)


def build_cost_matrix(
    cc_descriptors: List[LesionDescriptor],
    mlo_descriptors: List[LesionDescriptor],
    quadrant_penalty_fn: Optional[object] = None,
) -> np.ndarray:
    """
    Build the cost matrix for Hungarian assignment.

    Shape: (n_cc, n_mlo).
    Entry [i, j] = cost of assigning CC lesion i to MLO lesion j.

    If n_cc ≠ n_mlo, the caller should handle the rectangular case
    (scipy.optimize.linear_sum_assignment handles it natively).
    """
    n_cc = len(cc_descriptors)
    n_mlo = len(mlo_descriptors)

    if n_cc == 0 or n_mlo == 0:
        return np.zeros((n_cc, n_mlo), dtype=np.float64)

    cost = np.zeros((n_cc, n_mlo), dtype=np.float64)

    for i, cc in enumerate(cc_descriptors):
        for j, mlo in enumerate(mlo_descriptors):
            total, _, _, _ = compute_assignment_cost(cc, mlo, quadrant_penalty_fn)
            cost[i, j] = total

    return cost


# ─── Hungarian Solver ────────────────────────────────────────────────────────


def solve_hungarian(
    cc_descriptors: List[LesionDescriptor],
    mlo_descriptors: List[LesionDescriptor],
    quadrant_penalty_fn: Optional[object] = None,
    max_cost: float = MAX_ASSIGNMENT_COST,
) -> HungarianMatchResult:
    """
    Solve the global assignment problem using the Hungarian algorithm.

    Finds the assignment that minimizes total matching cost across all
    CC-MLO pairs. Pairs with cost above max_cost are rejected (unmatched).

    Args:
        cc_descriptors: Lesion descriptors from CC view.
        mlo_descriptors: Lesion descriptors from MLO view.
        quadrant_penalty_fn: Optional function(cc_quad, mlo_quad) -> float.
        max_cost: Maximum cost for a valid assignment.

    Returns:
        HungarianMatchResult with optimal assignments and unmatched lists.

    Complexity: O(n³) where n = max(n_cc, n_mlo).
    """
    result = HungarianMatchResult()
    n_cc = len(cc_descriptors)
    n_mlo = len(mlo_descriptors)

    if n_cc == 0 and n_mlo == 0:
        return result

    if n_cc == 0:
        result.unmatched_mlo = list(range(n_mlo))
        return result

    if n_mlo == 0:
        result.unmatched_cc = list(range(n_cc))
        return result

    # Build cost matrix
    cost_matrix = build_cost_matrix(cc_descriptors, mlo_descriptors, quadrant_penalty_fn)
    result.cost_matrix = cost_matrix

    # Solve using scipy Hungarian implementation
    try:
        from scipy.optimize import linear_sum_assignment
        row_ind, col_ind = linear_sum_assignment(cost_matrix)
    except ImportError:
        # Fallback: use our own simple implementation for small matrices
        row_ind, col_ind = _hungarian_fallback(cost_matrix)

    # Build assignments
    matched_cc = set()
    matched_mlo = set()

    for r, c in zip(row_ind, col_ind):
        cc_desc = cc_descriptors[r]
        mlo_desc = mlo_descriptors[c]
        total, nad_diff, height_diff, quad_pen = compute_assignment_cost(
            cc_desc, mlo_desc, quadrant_penalty_fn
        )

        is_matched = total <= max_cost
        assignment = MatchAssignment(
            cc_index=r,
            mlo_index=c,
            cost=total,
            nad_difference_mm=nad_diff,
            height_difference_mm=height_diff,
            quadrant_penalty=quad_pen,
            is_matched=is_matched,
        )
        result.assignments.append(assignment)

        if is_matched:
            matched_cc.add(r)
            matched_mlo.add(c)

    # Unmatched lesions
    result.unmatched_cc = [i for i in range(n_cc) if i not in matched_cc]
    result.unmatched_mlo = [j for j in range(n_mlo) if j not in matched_mlo]

    return result


# ─── Fallback Hungarian Implementation ──────────────────────────────────────


def _hungarian_fallback(cost_matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Simple greedy fallback when scipy is unavailable.

    This is NOT optimal — it's a greedy nearest-neighbor assignment.
    For production, scipy should always be available.

    For small matrices (n ≤ 10), the greedy result is often near-optimal.
    """
    n_rows, n_cols = cost_matrix.shape
    row_indices = []
    col_indices = []
    used_cols = set()

    # Flatten and sort all entries by cost
    entries = []
    for i in range(n_rows):
        for j in range(n_cols):
            entries.append((cost_matrix[i, j], i, j))
    entries.sort(key=lambda x: x[0])

    used_rows = set()
    for cost, i, j in entries:
        if i in used_rows or j in used_cols:
            continue
        row_indices.append(i)
        col_indices.append(j)
        used_rows.add(i)
        used_cols.add(j)
        if len(row_indices) == min(n_rows, n_cols):
            break

    return np.array(row_indices), np.array(col_indices)
