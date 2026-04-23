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
    - small stacks: deliberate drag, single-step precision
    - medium stacks: balanced drag, bounded multi-step motion
    - large stacks: more responsive drag, still burst-limited
    """
    n = max(0, int(total_slices or 0))

    if n <= 1:
        return StackDragProfile(
            drag_fullscreen_slices=1,
            drag_max_steps_per_event=1,
        )

    if n <= 24:
        return StackDragProfile(
            drag_fullscreen_slices=max(1, n - 1),
            drag_max_steps_per_event=1,
        )

    if n <= 80:
        return StackDragProfile(
            drag_fullscreen_slices=min(n - 1, 32),
            drag_max_steps_per_event=2,
        )

    if n <= 140:
        return StackDragProfile(
            drag_fullscreen_slices=min(n - 1, 40),
            drag_max_steps_per_event=2,
        )

    if n <= 220:
        return StackDragProfile(
            drag_fullscreen_slices=min(n - 1, 56),
            drag_max_steps_per_event=3,
        )

    return StackDragProfile(
        drag_fullscreen_slices=min(n - 1, 90),
        drag_max_steps_per_event=3,
    )
