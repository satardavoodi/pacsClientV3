from __future__ import annotations

from modules.viewer.fast.stack_cache_profile import build_stack_cache_profile


def test_stack_cache_profile_changes_with_slice_count():
    p20 = build_stack_cache_profile(20)
    p100 = build_stack_cache_profile(100)
    p200 = build_stack_cache_profile(200)
    p350 = build_stack_cache_profile(350)

    assert p20.fast_prefetch_radius != p100.fast_prefetch_radius or p20.idle_prefetch_radius != p100.idle_prefetch_radius
    assert p200.fast_prefetch_radius > p100.fast_prefetch_radius
    assert p350.fast_prefetch_radius > p200.fast_prefetch_radius
    assert p350.surrogate_distance > p200.surrogate_distance > p100.surrogate_distance > p20.surrogate_distance


def test_small_stack_idle_prefetch_can_cache_whole_series():
    p20 = build_stack_cache_profile(20)

    assert p20.fast_prefetch_radius == 4
    assert p20.idle_prefetch_radius == 19


def test_large_stack_profile_uses_wider_block_c_windows():
    p100 = build_stack_cache_profile(100)
    p200 = build_stack_cache_profile(200)
    p350 = build_stack_cache_profile(350)

    assert p200.medium_prefetch_radius > p100.medium_prefetch_radius
    assert p350.medium_prefetch_radius > p200.medium_prefetch_radius
    assert p200.idle_prefetch_radius > p100.idle_prefetch_radius
    assert p350.widened_surrogate_distance > p200.widened_surrogate_distance > p100.widened_surrogate_distance
    assert p350.decode_relevance_window > p200.decode_relevance_window > p100.decode_relevance_window


def test_high_slice_drag_lookahead_expands_across_large_stack_ranges():
    p120 = build_stack_cache_profile(120)
    p200 = build_stack_cache_profile(200)
    p320 = build_stack_cache_profile(320)
    p450 = build_stack_cache_profile(450)

    assert p120.fast_prefetch_radius == 18
    assert p120.surrogate_distance == 14
    assert p120.widened_surrogate_distance == 24
    assert p200.fast_prefetch_radius == 18
    assert p320.fast_prefetch_radius == 28
    assert p450.fast_prefetch_radius == 32
