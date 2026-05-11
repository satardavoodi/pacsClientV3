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
    - below 50 slices: keep the whole stack hot whenever practical
    - 50 to 100: mild cache expansion, still conservative
    - 100 to 200: faster drag requires a noticeably wider hot band
    - 200 to 300: larger stacks need wider surrogate and prefetch windows
    - 300 to 400: widen the hot working set again to avoid immediate cache gaps
    - above 400: keep scaling, but remain bounded for safety
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

    if n < 50:
        full_series_radius = max(1, n - 1)
        fast_radius = min(full_series_radius, 4)
        return StackCacheProfile(
            drag_fullscreen_slices=max(1, n - 1),
            drag_max_steps_per_event=1,
            fast_prefetch_radius=fast_radius,
            medium_prefetch_radius=full_series_radius,
            idle_prefetch_radius=full_series_radius,
            surrogate_distance=min(full_series_radius, 6),
            widened_surrogate_distance=min(full_series_radius, 10),
            decode_relevance_window=max(8, full_series_radius),
        )

    if n <= 100:
        return StackCacheProfile(
            drag_fullscreen_slices=min(n - 1, 36),
            drag_max_steps_per_event=2,
            fast_prefetch_radius=8,
            medium_prefetch_radius=6,
            idle_prefetch_radius=8,
            surrogate_distance=10,
            widened_surrogate_distance=18,
            decode_relevance_window=18,
        )

    if n <= 200:
        return StackCacheProfile(
            drag_fullscreen_slices=min(n - 1, 54),
            drag_max_steps_per_event=2,
            fast_prefetch_radius=18,
            medium_prefetch_radius=8,
            idle_prefetch_radius=12,
            surrogate_distance=14,
            widened_surrogate_distance=24,
            decode_relevance_window=28,
        )

    if n <= 300:
        return StackCacheProfile(
            drag_fullscreen_slices=min(n - 1, 72),
            drag_max_steps_per_event=3,
            fast_prefetch_radius=24,
            medium_prefetch_radius=12,
            idle_prefetch_radius=16,
            surrogate_distance=18,
            widened_surrogate_distance=32,
            decode_relevance_window=36,
        )

    if n <= 400:
        return StackCacheProfile(
            drag_fullscreen_slices=min(n - 1, 96),
            drag_max_steps_per_event=4,
            fast_prefetch_radius=28,
            medium_prefetch_radius=14,
            idle_prefetch_radius=18,
            surrogate_distance=22,
            widened_surrogate_distance=40,
            decode_relevance_window=44,
        )

    return StackCacheProfile(
        drag_fullscreen_slices=min(n - 1, 120),
        drag_max_steps_per_event=4,
        fast_prefetch_radius=32,
        medium_prefetch_radius=16,
        idle_prefetch_radius=20,
        surrogate_distance=26,
        widened_surrogate_distance=48,
        decode_relevance_window=52,
    )
