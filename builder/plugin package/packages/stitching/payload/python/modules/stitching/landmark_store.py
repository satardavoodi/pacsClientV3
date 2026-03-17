"""
Landmark Store — Multi-pair-set landmark manager for N-series chain stitching.

Manages landmark pairs grouped into "pair sets", where pair-set *k* holds
the corresponding points between the *k*-th and *(k+1)*-th selected series.

Each landmark is named alphabetically within its pair set:
    A / A',  B / B',  C / C',  …,  Z / Z',  AA / AA',  AB / AB',  …

All coordinates are in DICOM / SimpleITK physical space (mm).

Author : AI Pacs Team
Created: 2026-02-20  (rewritten for multi-series support)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

PointXY = Tuple[float, float]
PairEntry = Tuple[Optional[PointXY], Optional[PointXY]]  # (left, right)


class LandmarkStore(QObject):
    """Thread-safe multi-pair-set landmark store.

    *pair_set k* corresponds to the boundary between the *k*-th and
    *(k+1)*-th series in the chain.  Within each pair set, landmarks
    are numbered 0, 1, 2, … and labelled A / A', B / B', C / C', …
    """

    # ------------------------------------------------------------------
    #  Signals
    # ------------------------------------------------------------------
    landmarks_changed = Signal()

    # ------------------------------------------------------------------
    #  Construction
    # ------------------------------------------------------------------
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # pair_set_index → list of (left_point, right_point | None)
        self._pair_sets: Dict[int, List[PairEntry]] = {}

    # ==================================================================
    #  Alphabetical label helpers
    # ==================================================================

    @staticmethod
    def index_to_label(index: int) -> str:
        """Convert 0-based index to spreadsheet-style column label.

        0→A, 1→B, …, 25→Z, 26→AA, 27→AB, …
        """
        label = ""
        i = index
        while True:
            label = chr(ord("A") + i % 26) + label
            i = i // 26 - 1
            if i < 0:
                break
        return label

    @staticmethod
    def pair_label(index: int) -> Tuple[str, str]:
        """Return ``(left_label, right_label)`` for landmark *index*.

        E.g. index 0 → ``('A', "A'")``, index 1 → ``('B', "B'")``.
        """
        base = LandmarkStore.index_to_label(index)
        return base, f"{base}'"

    # ==================================================================
    #  Pair set management
    # ==================================================================

    def ensure_pair_set(self, ps_idx: int) -> None:
        if ps_idx not in self._pair_sets:
            self._pair_sets[ps_idx] = []

    def pair_set_count(self) -> int:
        return len(self._pair_sets)

    def landmark_count(self, ps_idx: int) -> int:
        return len(self._pair_sets.get(ps_idx, []))

    def complete_count(self, ps_idx: int) -> int:
        """Number of fully-placed pairs in pair set *ps_idx*."""
        return sum(
            1
            for left, right in self._pair_sets.get(ps_idx, [])
            if left is not None and right is not None
        )

    # ==================================================================
    #  Add / set / remove
    # ==================================================================

    def add_left_point(self, ps_idx: int, xy: PointXY) -> int:
        """Add a left point with the right slot empty (pending).

        Returns the 0-based landmark index within this pair set.
        """
        self.ensure_pair_set(ps_idx)
        self._pair_sets[ps_idx].append((tuple(xy), None))
        self.landmarks_changed.emit()
        return len(self._pair_sets[ps_idx]) - 1

    def set_right_point(self, ps_idx: int, lm_idx: int, xy: PointXY) -> None:
        """Complete a pending pair by setting the right point."""
        pairs = self._pair_sets.get(ps_idx)
        if pairs is None or lm_idx < 0 or lm_idx >= len(pairs):
            raise IndexError(f"Invalid pair_set={ps_idx} lm_idx={lm_idx}")
        pairs[lm_idx] = (pairs[lm_idx][0], tuple(xy))
        self.landmarks_changed.emit()

    def set_left_point(self, ps_idx: int, lm_idx: int, xy: PointXY) -> None:
        """Update the left point of an existing pair (for repositioning)."""
        pairs = self._pair_sets.get(ps_idx)
        if pairs is None or lm_idx < 0 or lm_idx >= len(pairs):
            raise IndexError(f"Invalid pair_set={ps_idx} lm_idx={lm_idx}")
        pairs[lm_idx] = (tuple(xy), pairs[lm_idx][1])
        self.landmarks_changed.emit()

    def add_pair(self, ps_idx: int, left: PointXY, right: PointXY) -> int:
        """Add a complete pair.  Returns the landmark index."""
        self.ensure_pair_set(ps_idx)
        self._pair_sets[ps_idx].append((tuple(left), tuple(right)))
        self.landmarks_changed.emit()
        return len(self._pair_sets[ps_idx]) - 1

    def remove_landmark(self, ps_idx: int, lm_idx: int) -> None:
        pairs = self._pair_sets.get(ps_idx)
        if pairs is None or lm_idx < 0 or lm_idx >= len(pairs):
            raise IndexError(f"Invalid pair_set={ps_idx} lm_idx={lm_idx}")
        del pairs[lm_idx]
        self.landmarks_changed.emit()

    def clear_pair_set(self, ps_idx: int) -> None:
        if ps_idx in self._pair_sets:
            self._pair_sets[ps_idx].clear()
        self.landmarks_changed.emit()

    def clear_all(self) -> None:
        self._pair_sets.clear()
        self.landmarks_changed.emit()

    # ==================================================================
    #  Queries
    # ==================================================================

    def get_pairs(self, ps_idx: int) -> List[PairEntry]:
        return list(self._pair_sets.get(ps_idx, []))

    def has_pending(self, ps_idx: int) -> bool:
        pairs = self._pair_sets.get(ps_idx, [])
        return bool(pairs) and pairs[-1][1] is None

    def pending_index(self, ps_idx: int) -> Optional[int]:
        if self.has_pending(ps_idx):
            return len(self._pair_sets[ps_idx]) - 1
        return None

    # ==================================================================
    #  Flat lists for SimpleITK
    # ==================================================================

    def get_left_flat(self, ps_idx: int) -> List[float]:
        """Flattened ``[x0, y0, x1, y1, …]`` of left (complete) points."""
        return [
            c
            for left, right in self._pair_sets.get(ps_idx, [])
            if left is not None and right is not None
            for c in left
        ]

    def get_right_flat(self, ps_idx: int) -> List[float]:
        """Flattened ``[x0, y0, x1, y1, …]`` of right (complete) points."""
        return [
            c
            for left, right in self._pair_sets.get(ps_idx, [])
            if left is not None and right is not None
            for c in right
        ]

    # -- Backward-compatible aliases -----------------------------------

    def get_fixed_flat(self) -> List[float]:
        return self.get_left_flat(0)

    def get_moving_flat(self) -> List[float]:
        return self.get_right_flat(0)

    # ==================================================================
    def __repr__(self) -> str:
        info = {k: len(v) for k, v in self._pair_sets.items()}
        return f"<LandmarkStore pair_sets={info}>"
