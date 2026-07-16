"""
Threshold policy for the Two-Stage 3D Cursor's second pass.

Split out of `second_pass.py` (which must subclass QObject and therefore hard-
requires Qt) so that the POLICY — a business rule with real correctness traps — is
importable, testable and reusable without a GUI stack. The offline accuracy harness
and the guard tests both need it, and neither should have to import PySide6.

Purity: stdlib only.
"""

from __future__ import annotations

import os
from typing import List


# How far below the user's analysis threshold the FIRST second-pass rung runs.
THRESHOLD_STEP = float(os.getenv("AIPACS_CURSOR3D_THRESHOLD_STEP", "0.05"))

# Floor. A threshold at/below zero would return every candidate box the detector
# has ever considered — useless, and slow.
MIN_THRESHOLD = 0.05

# The routine default used by the Eagle Eye analysis dialog.
DEFAULT_THRESHOLD = 0.45


# ─── The escalation ladder ───────────────────────────────────────────────────
#
# WHY A LADDER AND NOT A SINGLE STEP (live finding, study 50016, 2026-07-14):
#
# A single −0.05 step is often not enough. On patient 50016 the lesion was found
# in L-CC at 0.4627, the second pass ran correctly at 0.41 — and L-MLO came back
# EMPTY. Checking every run on disk, L-MLO had zero detections at 0.41, 0.42,
# 0.43, 0.44, 0.45 and 0.46. The corresponding lesion simply scores below 0.41.
# One rung down could never have surfaced it.
#
# So we step down repeatedly until a detection actually lands INSIDE the predicted
# region, or the floor is reached.
#
# This is only safe *because* Stage 1 exists. A 0.21 threshold on its own would
# bury the radiologist in false positives — but we do not show raw detections, we
# show the ones that fall in a geometrically-constrained band. The region is what
# buys us the right to look this deep. (Same logic as the published two-view search
# areas, which remove ~25 % of single-view false positives.)
#
# Offsets are from the ORIGINAL threshold, and grow, so we reach a genuinely low
# threshold in few backend calls: 0.46 → 0.41, 0.31, 0.21.
_DEFAULT_LADDER = "0.05,0.15,0.25"

# Below this, FCOS output is mostly noise; going lower costs time and buys nothing.
LADDER_FLOOR = float(os.getenv("AIPACS_CURSOR3D_LADDER_FLOOR", "0.20"))


def _parse_offsets(raw: str) -> List[float]:
    out: List[float] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
        except ValueError:
            continue
        if v > 0:
            out.append(v)
    return out or [THRESHOLD_STEP]


LADDER_OFFSETS = _parse_offsets(os.getenv("AIPACS_CURSOR3D_LADDER", _DEFAULT_LADDER))


def second_pass_threshold(original: float, step: float = THRESHOLD_STEP) -> float:
    """
    `original - step`, clamped to MIN_THRESHOLD and rounded to 2 decimal places.

    This is the FIRST rung of the ladder — the −0.05 the spec calls for.

    THE ROUNDING IS NOT COSMETIC. The backend writes its result to
    `updated_csv_with_boxes_{threshold:.2f}.csv`, and the manifest re-parses the
    threshold back OUT of that filename with a regex. Passing 0.44999999 would be
    written as `_0.45.csv` — silently colliding with the first-pass result and
    making the second pass indistinguishable from the run it was meant to
    supplement. Round here, once, at the source.
    """
    return round(max(MIN_THRESHOLD, float(original) - float(step)), 2)


def threshold_ladder(original: float) -> List[float]:
    """
    The full descending ladder of second-pass thresholds for `original`.

    Each rung is strictly below the original and strictly below the rung before it,
    clamped to LADDER_FLOOR, de-duplicated, rounded to 2 dp (see the rounding note
    above — the filename/manifest round-trip depends on it).

        threshold_ladder(0.46) -> [0.41, 0.31, 0.21]
        threshold_ladder(0.45) -> [0.40, 0.30, 0.20]     (the routine default)
        threshold_ladder(0.25) -> [0.20]                 (floor reached at once)
        threshold_ladder(0.20) -> []                     (already at the floor)

    Rung 0 equals `second_pass_threshold(original)` — the documented −0.05 — EXCEPT
    when LADDER_FLOOR (0.20) clamps it. The two functions apply different floors on
    purpose: `second_pass_threshold` bottoms out at MIN_THRESHOLD (0.05) because it
    is the raw policy, while the ladder refuses to go below 0.20 because rungs below
    that are noise. When they disagree, the ladder floor wins.
    """
    base = round(float(original), 2)
    out: List[float] = []
    for off in LADDER_OFFSETS:
        t = round(max(LADDER_FLOOR, base - float(off)), 2)
        if t >= base:
            continue                      # not actually lower — useless rung
        if out and t >= out[-1]:
            continue                      # not lower than the previous rung
        out.append(t)
    return out



def second_pass_threshold(original: float, step: float = THRESHOLD_STEP) -> float:
    """
    `original - step`, clamped to MIN_THRESHOLD and rounded to 2 decimal places.

    THE ROUNDING IS NOT COSMETIC. The backend writes its result to
    `updated_csv_with_boxes_{threshold:.2f}.csv`, and the manifest re-parses the
    threshold back OUT of that filename with a regex. Passing 0.44999999 would be
    written as `_0.45.csv` — silently colliding with the first-pass result and
    making the second pass indistinguishable from the run it was meant to
    supplement. Round here, once, at the source.
    """
    return round(max(MIN_THRESHOLD, float(original) - float(step)), 2)
