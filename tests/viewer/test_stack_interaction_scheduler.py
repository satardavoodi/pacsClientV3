from modules.viewer.fast.stack_interaction_scheduler import (
    FastWorkKind,
    FastWorkPriority,
    StackInteractionScheduler,
)


def test_stack_scheduler_emits_p0_and_directional_p1_neighbors():
    scheduler = StackInteractionScheduler()
    scheduler.begin(10)

    decision = scheduler.target(13, slice_count=100, series_uid="s1")

    assert decision.accepted is True
    assert decision.direction == 1
    assert [item.slice_index for item in decision.work_items] == [13, 14, 15, 12]
    assert decision.work_items[0].priority == int(FastWorkPriority.P0_CURRENT)
    assert decision.work_items[0].kind == FastWorkKind.PRESENT
    assert all(item.generation == decision.generation for item in decision.work_items)


def test_stack_scheduler_bumps_generation_on_reversal():
    scheduler = StackInteractionScheduler()
    scheduler.begin(10)
    forward = scheduler.target(12, slice_count=100)
    backward = scheduler.target(8, slice_count=100)

    assert backward.accepted is True
    assert backward.reversed_direction is True
    assert backward.generation > forward.generation
    assert [item.slice_index for item in backward.work_items] == [8, 7, 6, 9]


def test_stack_scheduler_rejects_repeated_target():
    scheduler = StackInteractionScheduler()
    scheduler.begin(10)
    first = scheduler.target(11, slice_count=100)
    repeated = scheduler.target(11, slice_count=100)

    assert first.accepted is True
    assert repeated.accepted is False
