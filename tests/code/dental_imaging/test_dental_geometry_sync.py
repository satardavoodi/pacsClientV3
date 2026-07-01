# -*- coding: utf-8 -*-
"""Guard: Dental Imaging geometry-sync regression (2026-06-24).

The panoramic + cross-section group desynced from the axial/sagittal/coronal group
because ``_axial_geom`` stored ``dz // 2`` (the middle slice) in element [2], while
``_vtk_world_to_volume_index`` unpacks (dx, dy, dz) and uses element [2] as the k-axis
CLAMP LIMIT (``min(limit-1, idx)``). That clamped every world->index depth to
``[0, dz//2-1]`` — the axial through-slice could never follow a panoramic/cross-section
selection past the middle. Fix: store the full ``dz``.

Pins: (1) the world<->index round-trip is consistent across the FULL k range (the pure
transform, replicated); (2) ``_axial_geom`` stores ``dz`` not ``dz // 2`` (source-pin).
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO / "modules" / "dental_imaging" / "workspace.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace").replace("\r\n", "\n")


# Mirror of _volume_index_to_vtk_world / _vtk_world_to_volume_index (kept in lock-step
# with the source-pin below).
def _to_world(index, origin, spacing):
    return tuple(origin[a] + index[a] * spacing[a] for a in range(3))


def _to_index(world, origin, spacing, limits):
    out = []
    for a in range(3):
        sp = float(spacing[a]) or 1.0
        idx = int(round((float(world[a]) - float(origin[a])) / sp))
        out.append(max(0, min(int(limits[a]) - 1, idx)))
    return tuple(out)


def test_world_index_roundtrip_full_k_range_with_dz():
    origin = (-99.8, -219.5, -420.9)
    spacing = (0.3906, 0.3906, 0.625)
    dx, dy, dz = 512, 512, 222
    # FIXED clamp limits = full dims -> round-trip holds for EVERY slice
    fixed_failures = 0
    for k in range(0, dz):
        idx = (256, 300, k)
        w = _to_world(idx, origin, spacing)
        if _to_index(w, origin, spacing, (dx, dy, dz))[2] != k:
            fixed_failures += 1
    assert fixed_failures == 0

    # REGRESSION reproduction: dz//2 as the k limit clamps depth to the middle
    buggy = _to_index(_to_world((256, 300, 150), origin, spacing), origin, spacing, (dx, dy, dz // 2))
    assert buggy[2] == (dz // 2) - 1        # stuck at ~middle, not 150
    fixed = _to_index(_to_world((256, 300, 150), origin, spacing), origin, spacing, (dx, dy, dz))
    assert fixed[2] == 150                  # follows the true depth


def test_axial_geom_stores_full_dz_not_half():
    s = _read(WORKSPACE)
    # the assignment must carry the full z dimension, not the middle slice
    assert "dx, dy, dz,\n" in s
    assert "dx, dy, dz // 2,\n" not in s
    # the consumer still uses element [2] as the k clamp limit
    assert "for a, limit in enumerate((dx, dy, dz))" in s
