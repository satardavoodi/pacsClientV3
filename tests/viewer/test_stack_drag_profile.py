from __future__ import annotations

from modules.viewer.fast.stack_drag_profile import build_stack_drag_profile


def test_stack_drag_profile_changes_with_slice_count():
    p20 = build_stack_drag_profile(20)
    p100 = build_stack_drag_profile(100)
    p200 = build_stack_drag_profile(200)
    p350 = build_stack_drag_profile(350)

    assert p20.drag_max_steps_per_event == 1
    assert p100.drag_max_steps_per_event > p20.drag_max_steps_per_event
    assert p200.drag_max_steps_per_event >= p100.drag_max_steps_per_event
    assert p350.drag_max_steps_per_event > p200.drag_max_steps_per_event
    assert p20.drag_fullscreen_slices < p100.drag_fullscreen_slices < p200.drag_fullscreen_slices < p350.drag_fullscreen_slices


def test_small_stack_drag_remains_deliberate():
    p20 = build_stack_drag_profile(20)

    assert p20.drag_max_steps_per_event == 1
    assert p20.drag_fullscreen_slices == 19
    assert p20.first_step_threshold_scale > 0.70


def test_large_stack_drag_uses_bounded_burst_limits():
    p100 = build_stack_drag_profile(100)
    p200 = build_stack_drag_profile(200)
    p350 = build_stack_drag_profile(350)
    p500 = build_stack_drag_profile(500)

    assert p100.drag_max_steps_per_event == 2
    assert p200.drag_max_steps_per_event == 2
    assert p350.drag_max_steps_per_event == 4
    assert p500.drag_max_steps_per_event == 4
    assert p500.drag_fullscreen_slices > p350.drag_fullscreen_slices > p200.drag_fullscreen_slices > p100.drag_fullscreen_slices
    assert p100.first_step_threshold_scale == 0.68
    assert p500.first_step_threshold_scale < p100.first_step_threshold_scale
