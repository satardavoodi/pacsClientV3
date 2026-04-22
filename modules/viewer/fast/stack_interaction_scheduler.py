"""Protected stack-drag scheduling primitives for the FAST viewer.

This module keeps the stack-review policy explicit and separate from wheel
precision browsing.  It does not execute work itself; callers use it to label
current-target and neighbor work consistently.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import List, Optional


class FastWorkPriority(IntEnum):
    P0_CURRENT = 0
    P1_NEIGHBOR = 1
    P2_SETTLE_WARM = 2
    P3_NONCRITICAL_UI = 3
    P4_BULK = 4


class FastWorkKind(str, Enum):
    PRESENT = "present"
    DECODE = "decode"
    PREFETCH = "prefetch"
    RENDER = "render"
    CACHE_WRITE = "cache_write"
    OBJECT_FETCH = "object_fetch"


@dataclass(order=True, frozen=True)
class FastWorkItem:
    priority: int
    deadline_ms: int
    created_at: float = field(default_factory=time.perf_counter, compare=True)
    generation: int = field(default=0, compare=False)
    kind: FastWorkKind = field(default=FastWorkKind.PREFETCH, compare=False)
    series_uid: str = field(default="", compare=False)
    slice_index: int = field(default=0, compare=False)
    direction: int = field(default=0, compare=False)
    quality_class: str = field(default="full", compare=False)


@dataclass(frozen=True)
class StackTargetDecision:
    accepted: bool
    generation: int
    direction: int
    reversed_direction: bool
    work_items: tuple[FastWorkItem, ...]


class StackInteractionScheduler:
    """Small state machine for stack-drag P0/P1 admission.

    Wheel events intentionally do not use this scheduler.
    """

    def __init__(self) -> None:
        self._active = False
        self._generation = 0
        self._last_target: Optional[int] = None
        self._last_direction = 0

    @property
    def generation(self) -> int:
        return int(self._generation)

    def begin(self, current_slice: int) -> int:
        self._active = True
        self._generation += 1
        self._last_target = int(current_slice)
        self._last_direction = 0
        return self._generation

    def end(self) -> int:
        self._active = False
        self._last_target = None
        self._last_direction = 0
        return self._generation

    def target(
        self,
        target_slice: int,
        *,
        slice_count: int,
        series_uid: str = "",
    ) -> StackTargetDecision:
        if not self._active:
            self._active = True
            self._generation += 1
            self._last_target = None
            self._last_direction = 0

        count = max(0, int(slice_count))
        if count <= 0:
            return StackTargetDecision(False, self._generation, 0, False, ())

        target = max(0, min(int(target_slice), count - 1))
        if self._last_target == target:
            return StackTargetDecision(False, self._generation, 0, False, ())

        prev = self._last_target
        direction = 0 if prev is None else (1 if target > prev else -1 if target < prev else 0)
        reversed_direction = bool(
            direction != 0
            and self._last_direction != 0
            and direction != self._last_direction
        )

        # Every accepted target gets a new generation so stale P1 decode/render
        # cannot present over the latest drag target. Reversal is called out for
        # metrics/tests, but the generation rule is intentionally uniform.
        self._generation += 1
        if direction != 0:
            self._last_direction = direction
        self._last_target = target

        items: List[FastWorkItem] = [
            FastWorkItem(
                priority=int(FastWorkPriority.P0_CURRENT),
                deadline_ms=16,
                generation=self._generation,
                kind=FastWorkKind.PRESENT,
                series_uid=series_uid,
                slice_index=target,
                direction=direction,
                quality_class="preview",
            )
        ]

        neighbor_offsets = [1, 2, -1] if direction >= 0 else [-1, -2, 1]
        for offset in neighbor_offsets:
            idx = target + offset
            if 0 <= idx < count:
                items.append(
                    FastWorkItem(
                        priority=int(FastWorkPriority.P1_NEIGHBOR),
                        deadline_ms=120,
                        generation=self._generation,
                        kind=FastWorkKind.PREFETCH,
                        series_uid=series_uid,
                        slice_index=idx,
                        direction=direction,
                        quality_class="preview",
                    )
                )

        return StackTargetDecision(
            True,
            self._generation,
            direction,
            reversed_direction,
            tuple(items),
        )


__all__ = [
    "FastWorkItem",
    "FastWorkKind",
    "FastWorkPriority",
    "StackInteractionScheduler",
    "StackTargetDecision",
]
