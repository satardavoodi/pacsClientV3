# -*- coding: utf-8 -*-
"""Mandibular (inferior alveolar) canal store — pure geometry, stdlib only.

The inferior alveolar nerve canal is traced on CBCT as a series of control points
along its course (AAOMR / ACR structured-report use: canal path + length + proximity
to structures for third-molar / implant planning). This module owns the control-point
model + the report math (resampled path, length, nearest-distance proximity) and is
fully unit-testable headless — no Qt, no VTK, no numpy. The workspace converts view
clicks to world/index coordinates and does the drawing; it never recomputes geometry.

Each control point is a dict with at least ``world`` = (x, y, z) in the volume's VTK
world frame (the same frame the ortho/curved views use) and ``index`` = (i, j, k).
Canals are bilateral: ``"left"`` and ``"right"``.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

WorldPoint = Tuple[float, float, float]
SIDES = ("left", "right")


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)))


def _resample_polyline(points: List[WorldPoint], count: int) -> List[WorldPoint]:
    """Uniform arc-length resampling of a 3-D polyline (linear between control points)."""
    if not points:
        return []
    if len(points) == 1 or count <= 1:
        return [tuple(float(v) for v in points[0])] * max(1, count)
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[-1] + _dist(points[i - 1], points[i]))
    total = cum[-1]
    if total <= 1e-9:
        return [tuple(float(v) for v in points[0])] * count
    out: List[WorldPoint] = []
    j = 0
    for n in range(count):
        target = total * n / (count - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = max(cum[j + 1] - cum[j], 1e-9)
        f = (target - cum[j]) / seg
        out.append(tuple(
            float(points[j][a]) + (float(points[j + 1][a]) - float(points[j][a])) * f
            for a in range(3)
        ))
    return out


class NerveCanalStore:
    """Bilateral inferior-alveolar canal control points + report geometry."""

    def __init__(self) -> None:
        self._canals: Dict[str, List[dict]] = {"left": [], "right": []}

    # -- editing -----------------------------------------------------------
    def points(self, side: str) -> List[dict]:
        return list(self._canals.get(side, []))

    def count(self, side: str) -> int:
        return len(self._canals.get(side, []))

    def add_point(self, side: str, point: dict) -> None:
        if side in self._canals and isinstance(point, dict) and "world" in point:
            self._canals[side].append(dict(point))

    def undo(self, side: str) -> bool:
        canal = self._canals.get(side)
        if canal:
            canal.pop()
            return True
        return False

    def clear(self, side: str) -> None:
        if side in self._canals:
            self._canals[side] = []

    def clear_all(self) -> None:
        for s in SIDES:
            self._canals[s] = []

    def nearest_control(self, side: str, world: WorldPoint, *, max_dist: float = 6.0) -> Optional[int]:
        """Index of the control point nearest to ``world`` within ``max_dist`` mm, else None."""
        canal = self._canals.get(side) or []
        best_i, best_d = None, float("inf")
        for i, p in enumerate(canal):
            d = _dist(p.get("world", (0, 0, 0)), world)
            if d < best_d:
                best_i, best_d = i, d
        if best_i is not None and best_d <= float(max_dist):
            return best_i
        return None

    def move_control(self, side: str, idx: int, point: dict) -> bool:
        canal = self._canals.get(side) or []
        if 0 <= int(idx) < len(canal) and isinstance(point, dict) and "world" in point:
            canal[int(idx)] = dict(point)
            return True
        return False

    def remove_control(self, side: str, idx: int) -> bool:
        """Delete a single control point by index (right-click 'delete point')."""
        canal = self._canals.get(side)
        if canal and 0 <= int(idx) < len(canal):
            canal.pop(int(idx))
            return True
        return False

    # -- report geometry ---------------------------------------------------
    def world_polyline(self, side: str) -> List[WorldPoint]:
        return [tuple(float(v) for v in p["world"]) for p in (self._canals.get(side) or []) if "world" in p]

    def resampled_world(self, side: str, count: int = 64) -> List[WorldPoint]:
        return _resample_polyline(self.world_polyline(side), int(count))

    def length_mm(self, side: str) -> float:
        """Total traced canal length (mm) — a structured-report metric."""
        pts = self.world_polyline(side)
        return sum(_dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))

    def nearest_distance_mm(self, side: str, query_world: WorldPoint, *, samples: int = 128) -> Optional[float]:
        """Minimum distance (mm) from ``query_world`` to the canal path — the proximity
        an implant/third-molar report needs. None if the canal has < 2 points."""
        line = self.resampled_world(side, samples)
        if len(line) < 2:
            if len(line) == 1:
                return _dist(line[0], query_world)
            return None
        best = float("inf")
        for i in range(1, len(line)):
            best = min(best, _point_segment_distance(query_world, line[i - 1], line[i]))
        return best


def _point_segment_distance(p: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay, az = float(a[0]), float(a[1]), float(a[2])
    abx, aby, abz = float(b[0]) - ax, float(b[1]) - ay, float(b[2]) - az
    apx, apy, apz = float(p[0]) - ax, float(p[1]) - ay, float(p[2]) - az
    denom = abx * abx + aby * aby + abz * abz
    t = 0.0 if denom <= 1e-12 else max(0.0, min(1.0, (apx * abx + apy * aby + apz * abz) / denom))
    cx, cy, cz = ax + abx * t, ay + aby * t, az + abz * t
    return math.sqrt((float(p[0]) - cx) ** 2 + (float(p[1]) - cy) ** 2 + (float(p[2]) - cz) ** 2)
