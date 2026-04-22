# FAST stack-drag session freeze plan — 2026-04-20

## Purpose

Define the safest first implementation step for FAST Block C stack-drag stabilization.

This pass is intentionally narrow:

- stabilize drag semantics
- avoid redesigning Block B / Block C
- preserve wheel behavior exactly
- reduce the chance that progressive growth changes the meaning of an active drag

## Scope

In scope:

- FAST viewer only
- `modules/viewer/fast/qt_slice_viewer.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- targeted drag tests in `tests/viewer/`

Out of scope for this pass:

- wheel interaction behavior
- Block B progressive lifecycle redesign
- decode-service / disk-cache changes
- sync/refline architecture changes
- large cache/prefetch retuning

## Problem statement

The current FAST drag path already shares the lower render/cache engine with wheel, but drag still has extra session semantics that wheel does not:

- drag threshold/cap is derived from a live slice-count hint
- the hint can change while a drag is active
- `set_total_slices_hint()` can rescale `_stacked_accum` during drag growth
- drag alone allows surrogate rendering and wider cache policy windows

This creates a key UX risk:

> the same physical mouse motion can be reinterpreted differently mid-gesture if the interactive slice-count hint changes.

That is the most likely source of the reported laggy / jumpy / confusing stack behavior.

## First implementation target

### Session-freeze rule

When a stack drag starts, freeze the drag session parameters until drag stop.

The active drag session should capture at least:

- session slice-count hint
- drag threshold in pixels
- max steps per event
- whether first-step startup assist is still pending

Optional in the same pass only if cheap and clean:

- a session identifier for logging / tests

### Rule after freeze

During an active drag:

- later calls to `set_total_slices_hint()` may update the viewer's future baseline
- but they must **not** reinterpret the current session's threshold/cap
- they must **not** rescale active `_stacked_accum`
- they must **not** silently change the meaning of already accumulated drag motion

After drag stop:

- clear the frozen session state
- future drag gestures use the newest hint/policy

## Intended behavior after this pass

### What stays the same

- wheel remains exact and precise
- wheel continues to use `interaction_type='wheel'`
- drag still emits atomic multi-slice deltas
- interactive slice-range clamping still happens in the bridge
- post-settle exact rerender still happens through `end_fast_interaction()`

### What changes

- progressive slice-count growth no longer changes drag threshold mid-gesture
- `_stacked_accum` is no longer rescaled during active drag when the hint grows
- drag semantics become deterministic from mouse-down to mouse-up

## Proposed code changes

### 1. `modules/viewer/fast/qt_slice_viewer.py`

Add explicit frozen drag-session state.

Candidate fields:

- `_stack_drag_session_active: bool`
- `_stack_drag_session_slice_hint: int`
- `_stack_drag_session_threshold_px: float`
- `_stack_drag_session_max_steps: int`

Candidate helpers:

- `_begin_stack_drag_session()`
- `_end_stack_drag_session()`
- `_get_active_stack_drag_profile()`

Behavioral change:

- on drag start, compute and store the active threshold/cap once
- `_consume_stack_drag_delta()` uses the frozen session profile when active
- `set_total_slices_hint()` must not rescale `_stacked_accum` while a frozen drag session is active

### 2. `modules/viewer/fast/qt_viewer_bridge.py`

Probably minimal or no logic change required.

Use bridge edits only if needed for:

- extra diagnostics
- ensuring drag-start / drag-stop logging reflects session freeze

Do not change wheel logic in this pass.

## Test plan

## Tests that should remain green unchanged

These define the protected contract and should survive the change:

- `tests/viewer/test_b34_interaction_aware_policy.py`
  - wheel fast-interaction behavior
  - drag fast-interaction behavior
  - unified settle semantics
- `tests/viewer/test_qt_stack_drag_bridge.py`
  - atomic drag delta application
  - progressive clamp behavior
- `tests/viewer/test_fast_viewer_pipeline.py`
  - wheel never uses surrogate
  - drag may use surrogate
  - post-settle exact render path remains intact

## Tests likely needing targeted updates

### `tests/viewer/test_qt_slice_viewer_stack_drag.py`

Most likely behavior change:

- `test_slice_count_growth_preserves_partial_drag_progress`

This test currently protects mid-drag rescaling semantics.
That behavior conflicts with the stabilization target.

Replace it with a new expectation closer to:

- active drag session keeps its original threshold/cap despite hint growth
- active `_stacked_accum` is not reinterpreted by later hint updates

Potential new tests:

1. `test_active_drag_session_freezes_threshold_when_slice_hint_grows`
2. `test_active_drag_session_freezes_max_steps_when_slice_hint_grows`
3. `test_set_total_slices_hint_does_not_rescale_accum_during_active_drag`
4. `test_new_drag_session_uses_latest_hint_after_previous_drag_stops`

## Validation strategy

### Functional validation

Verify:

- no mid-drag jump when progressive count grows
- same drag gesture produces same logical step behavior before and after background count growth
- reversal behavior still clears stale momentum correctly
- pointer-leave cancellation still ends drag cleanly

### Precision validation

Verify:

- wheel tests remain unchanged
- wheel still renders exact target slices
- drag still gets exact final rerender after settle

### Progressive coordination validation

Verify:

- drag is still clamped to interactive slice availability
- growth during drag expands future reachable range only after the current gesture ends
- no regressions in progressive-mode bridge tests

### Risk containment

This pass should not change:

- `stack_cache_profile.py`
- surrogate policy
- prefetch radius policy
- `SystemLoadController`
- `ui_throttle`

If drag still feels too approximate after this pass, address that in a second pass by tightening drag-time surrogate/prefetch windows.

## Follow-up pass if needed

Only after session freeze is validated:

### Pass 2 — drag approximation tightening

Possible follow-up:

- reduce drag-time fast prefetch radius for medium/large stacks
- reduce drag surrogate distance and widened surrogate distance
- keep wheel unchanged
- keep idle/post-settle warming unchanged

This must be measured separately from the session-freeze fix so the root cause remains attributable.

## Acceptance criteria

This pass is complete when all of the following are true:

1. active drag semantics no longer change when slice-count hint grows mid-gesture
2. wheel behavior is unchanged
3. drag boundary/clamp tests still pass
4. progressive-mode drag remains bounded to interactive availability
5. test changes are limited and explainable
6. no new viewer errors are introduced in the touched files

## Recommended execution order

1. Implement frozen drag-session state in `qt_slice_viewer.py`
2. Replace the mid-drag rescale behavior with future-session-only update behavior
3. Update/add the targeted drag tests
4. Run the stack-drag and interaction-aware viewer tests
5. Only then decide whether a second pass on drag-time cache windows is needed

## Summary

The safest first fix is not a wheel rewrite and not a cache rewrite.

It is this:

> Freeze drag semantics for the duration of one drag gesture.

That directly targets the most likely source of positional confusion while leaving the healthy wheel path and the deeper FAST pipeline intact.
