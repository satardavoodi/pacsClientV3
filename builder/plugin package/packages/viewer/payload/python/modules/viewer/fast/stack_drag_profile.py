from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StackDragProfile:
    """Slice-count-aware policy for stack-drag interaction only.

    This module intentionally owns user interaction semantics and nothing else.
    Cache/prefetch/surrogate policy remains in ``stack_cache_profile.py``.
    """

    drag_fullscreen_slices: int
    drag_max_steps_per_event: int
    first_step_threshold_scale: float = 0.65


def build_stack_drag_profile(total_slices: int) -> StackDragProfile:
    """Return the drag-only policy for *total_slices*.

    Design intent:
    - below 50 slices: deliberate drag, no skipping
    - 50 to 100: moderate responsiveness, bounded 2-step motion
    - 100 to 200: faster travel, still capped at 2-step motion
    - 200 to 300: enter a controlled 3-step lane for fast drags
    - 300 to 400: larger stacks get more travel per fullscreen gesture
    - above 400: remain responsive without allowing chaotic jumps
    """
    n = max(0, int(total_slices or 0))

    if n <= 1:
        return StackDragProfile(
            drag_fullscreen_slices=1,
            drag_max_steps_per_event=1,
            first_step_threshold_scale=0.70,
        )

    if n < 50:
        return StackDragProfile(
            drag_fullscreen_slices=max(1, n - 1),
            drag_max_steps_per_event=1,
            first_step_threshold_scale=0.72,
        )

    if n <= 100:
        return StackDragProfile(
            drag_fullscreen_slices=min(n - 1, 36),
            drag_max_steps_per_event=2,
            first_step_threshold_scale=0.68,
        )

    if n <= 200:
        return StackDragProfile(
            drag_fullscreen_slices=min(n - 1, 54),
            drag_max_steps_per_event=2,
            first_step_threshold_scale=0.65,
        )

    if n <= 300:
        return StackDragProfile(
            drag_fullscreen_slices=min(n - 1, 72),
            drag_max_steps_per_event=3,
            first_step_threshold_scale=0.62,
        )

    if n <= 400:
        return StackDragProfile(
            drag_fullscreen_slices=min(n - 1, 96),
            drag_max_steps_per_event=4,
            first_step_threshold_scale=0.60,
        )

    return StackDragProfile(
        drag_fullscreen_slices=min(n - 1, 120),
        drag_max_steps_per_event=4,
        first_step_threshold_scale=0.58,
    )
