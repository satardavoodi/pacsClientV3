from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StackCacheProfile:
    """Shared slice-count-aware policy for drag and cache behavior.

    The policy is intentionally piecewise and allocation-free at call sites so
    Block C can adapt to stack size without introducing additional runtime load.

        Note:
        - Active FAST drag interaction now uses ``stack_drag_profile.py``.
        - The drag fields remain here for backward compatibility with existing
            callers/tests and to avoid destabilizing unrelated paths during the
            refactor.
    """

    drag_fullscreen_slices: int
    drag_max_steps_per_event: int
    fast_prefetch_radius: int
    medium_prefetch_radius: int
    idle_prefetch_radius: int
    surrogate_distance: int
    widened_surrogate_distance: int
    decode_relevance_window: int


def build_stack_cache_profile(total_slices: int) -> StackCacheProfile:
    """Return the shared drag/cache policy for *total_slices*.

    Design intent:
    - small stacks: deliberate drag, aggressive cache fill
    - medium stacks: balanced drag, moderate prefetch
    - large stacks: faster drag, wider surrogate/cache windows
    - heavy-download protection is still enforced elsewhere by
      ``SystemLoadController`` / ``cap_prefetch_radius``.
    """
    n = max(0, int(total_slices or 0))

    if n <= 1:
        return StackCacheProfile(
            drag_fullscreen_slices=1,
            drag_max_steps_per_event=1,
            fast_prefetch_radius=1,
            medium_prefetch_radius=1,
            idle_prefetch_radius=1,
            surrogate_distance=0,
            widened_surrogate_distance=0,
            decode_relevance_window=1,
        )

    if n <= 24:
        full_series_radius = max(1, n - 1)
        return StackCacheProfile(
            drag_fullscreen_slices=max(1, n - 1),
            drag_max_steps_per_event=1,
            fast_prefetch_radius=full_series_radius,
            medium_prefetch_radius=full_series_radius,
            idle_prefetch_radius=full_series_radius,
            surrogate_distance=min(full_series_radius, 6),
            widened_surrogate_distance=min(full_series_radius, 10),
            decode_relevance_window=max(8, full_series_radius),
        )

    if n <= 80:
        return StackCacheProfile(
            drag_fullscreen_slices=min(n - 1, 32),
            drag_max_steps_per_event=2,
            fast_prefetch_radius=4,
            medium_prefetch_radius=5,
            idle_prefetch_radius=7,
            surrogate_distance=8,
            widened_surrogate_distance=16,
            decode_relevance_window=14,
        )

    if n <= 140:
        return StackCacheProfile(
            drag_fullscreen_slices=min(n - 1, 40),
            drag_max_steps_per_event=2,
            fast_prefetch_radius=16,
            medium_prefetch_radius=6,
            idle_prefetch_radius=8,
            surrogate_distance=10,
            widened_surrogate_distance=20,
            decode_relevance_window=24,
        )

    if n <= 220:
        return StackCacheProfile(
            drag_fullscreen_slices=min(n - 1, 56),
            drag_max_steps_per_event=3,
            fast_prefetch_radius=20,
            medium_prefetch_radius=10,
            idle_prefetch_radius=12,
            surrogate_distance=16,
            widened_surrogate_distance=32,
            decode_relevance_window=32,
        )

    return StackCacheProfile(
        drag_fullscreen_slices=min(n - 1, 90),
        drag_max_steps_per_event=3,
        fast_prefetch_radius=20,
        medium_prefetch_radius=10,
        idle_prefetch_radius=12,
        surrogate_distance=20,
        widened_surrogate_distance=40,
        decode_relevance_window=40,
    )