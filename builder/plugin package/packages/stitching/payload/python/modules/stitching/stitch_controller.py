"""
Stitch Controller — Multi-series pick-mode state machine.

Orchestrates the landmark placement workflow across N series.
The controller manages the pick state for the *active pair* and
delegates to the ``LandmarkStore`` for persistence.

State machine (per pair):

    IDLE  →  user clicks "Place Landmark Pair"  →  PICKING_LEFT
    PICKING_LEFT  →  click on left viewer      →  PICKING_RIGHT
    PICKING_RIGHT →  click on right viewer     →  pair complete → PICKING_LEFT (auto-cycle)

Author : AI Pacs Team
Created: 2026-02-20  (rewritten for multi-series support)
"""

from __future__ import annotations

import enum
from typing import List, Optional

from PySide6.QtCore import QObject, Signal

from .landmark_store import LandmarkStore
from .stitch_worker import StitchWorker


class PickState(enum.Enum):
    IDLE = "idle"
    PICKING_LEFT = "picking_left"
    PICKING_RIGHT = "picking_right"


class StitchController(QObject):
    """High-level orchestrator for the multi-series stitching workflow."""

    # ------------------------------------------------------------------
    #  Signals
    # ------------------------------------------------------------------
    state_changed = Signal(str)            # PickState.value
    stitch_progress = Signal(str, float)   # (status, fraction)
    stitch_completed = Signal(object)      # sitk.Image
    stitch_error = Signal(str)

    # ------------------------------------------------------------------
    #  Construction
    # ------------------------------------------------------------------
    def __init__(
        self,
        landmark_store: LandmarkStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = landmark_store or LandmarkStore(self)
        self._state = PickState.IDLE
        self._active_pair: int = 0
        self._worker: Optional[StitchWorker] = None

    # ------------------------------------------------------------------
    #  Properties
    # ------------------------------------------------------------------

    @property
    def landmark_store(self) -> LandmarkStore:
        return self._store

    @property
    def pick_state(self) -> PickState:
        return self._state

    @property
    def active_pair(self) -> int:
        return self._active_pair

    @active_pair.setter
    def active_pair(self, value: int) -> None:
        self._active_pair = value

    # ------------------------------------------------------------------
    #  Pick-mode state machine
    # ------------------------------------------------------------------

    def start_pick_mode(self) -> None:
        """Enter landmark placement mode (start accepting left clicks)."""
        self._set_state(PickState.PICKING_LEFT)

    def stop_pick_mode(self) -> None:
        """Exit pick mode entirely (cancel pending pair if any)."""
        if self._store.has_pending(self._active_pair):
            idx = self._store.pending_index(self._active_pair)
            if idx is not None:
                self._store.remove_landmark(self._active_pair, idx)
        self._set_state(PickState.IDLE)

    def on_left_point_picked(self, x: float, y: float) -> None:
        """Called when the user clicks on the left viewer."""
        if self._state != PickState.PICKING_LEFT:
            return
        self._store.add_left_point(self._active_pair, (x, y))
        self._set_state(PickState.PICKING_RIGHT)

    def on_right_point_picked(self, x: float, y: float) -> None:
        """Called when the user clicks on the right viewer."""
        if self._state != PickState.PICKING_RIGHT:
            return
        idx = self._store.pending_index(self._active_pair)
        if idx is not None:
            self._store.set_right_point(self._active_pair, idx, (x, y))
        # Auto-cycle back to left for next pair
        self._set_state(PickState.PICKING_LEFT)

    # ------------------------------------------------------------------
    #  Stitch execution
    # ------------------------------------------------------------------

    def run_stitch(
        self,
        series_dirs: List[str],
        transform_type: str = "affine",
    ) -> None:
        """Launch the N-series chain-stitching pipeline."""
        if self._worker is not None and self._worker.isRunning():
            self.stitch_error.emit("A stitching operation is already running.")
            return

        self._worker = StitchWorker(
            series_dirs=series_dirs,
            landmark_store=self._store,
            transform_type=transform_type,
        )
        self._worker.progress.connect(self.stitch_progress.emit)
        self._worker.completed.connect(self.stitch_completed.emit)
        self._worker.error.connect(self.stitch_error.emit)
        self._worker.start()

    def cancel_stitch(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    def _set_state(self, new_state: PickState) -> None:
        self._state = new_state
        self.state_changed.emit(new_state.value)
        print(f"[StitchController] state → {new_state.value}")
