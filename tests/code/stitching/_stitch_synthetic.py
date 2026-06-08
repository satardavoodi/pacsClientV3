"""Deterministic synthetic fixtures shared by the stitching tests.

Kept separate so the golden-reference capture script and the test suite use
the *identical* generator (no drift between the recorded golden and the test
input).
"""
from __future__ import annotations

import numpy as np

CANVAS_H = 80
CANVAS_W = 200


def make_overlap_arrays() -> list:
    """Two positive images on a shared canvas with a partial overlap.

    Image A covers columns [0, 120), image B covers columns [80, 200);
    overlap is columns [80, 120). Background is exactly 0.0 (the blend treats
    ``!= 0`` as the data mask). Values are deterministic and strictly > 0
    inside each region so the mask is unambiguous.
    """
    h, w = CANVAS_H, CANVAS_W
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)

    a = np.zeros((h, w), dtype=np.float64)
    b = np.zeros((h, w), dtype=np.float64)

    # Smooth, distinct intensity fields (kept well above zero)
    field_a = 1000.0 + 300.0 * np.sin(xx / 17.0) + 2.0 * yy
    field_b = 1400.0 + 250.0 * np.cos(xx / 13.0) + 1.5 * yy

    a[:, 0:120] = field_a[:, 0:120]
    b[:, 80:200] = field_b[:, 80:200]
    return [a, b]


def make_landmark_sets():
    """Return (fixed_flat, moving_flat, known_shift) for a pure translation.

    moving = fixed shifted by (+5.0, -3.0) mm, so a recovered transform must
    map fixed → moving with ~0 residual.
    """
    fixed_pts = [(10.0, 20.0), (60.0, 25.0), (35.0, 70.0), (80.0, 15.0)]
    shift = (5.0, -3.0)
    fixed_flat = [c for p in fixed_pts for c in p]
    moving_flat = [
        c for p in fixed_pts for c in (p[0] + shift[0], p[1] + shift[1])
    ]
    return fixed_flat, moving_flat, shift
