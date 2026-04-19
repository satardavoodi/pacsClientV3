from __future__ import annotations

from modules.viewer.fast.stack_drag_profile import build_stack_drag_profile


def test_stack_drag_profile_changes_with_slice_count():
    p20 = build_stack_drag_profile(20)
    p100 = build_stack_drag_profile(100)
    p200 = build_stack_drag_profile(200)

    assert p20.drag_max_steps_per_event == 1
    assert p100.drag_max_steps_per_event > p20.drag_max_steps_per_event
    assert p200.drag_max_steps_per_event > p100.drag_max_steps_per_event
    assert p20.drag_fullscreen_slices < p100.drag_fullscreen_slices < p200.drag_fullscreen_slices


def test_small_stack_drag_remains_deliberate():
    p20 = build_stack_drag_profile(20)

    assert p20.drag_max_steps_per_event == 1
    assert p20.drag_fullscreen_slices == 19


def test_large_stack_drag_uses_bounded_burst_limits():
    p100 = build_stack_drag_profile(100)
    p200 = build_stack_drag_profile(200)

    assert p100.drag_max_steps_per_event == 2
    assert p200.drag_max_steps_per_event == 3
    assert p200.drag_fullscreen_slices > p100.drag_fullscreen_slices
    assert p100.first_step_threshold_scale == 0.65
