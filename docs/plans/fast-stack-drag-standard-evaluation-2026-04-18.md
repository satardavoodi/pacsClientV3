# FAST Block C stack-drag standard evaluation

Date: 2026-04-18
Scope: FAST viewer only (`modules/viewer/fast/**`), Block C drag/stack behavior, coordination with lazy cache/load.

## Goal

Define what the stack-drag function in Block C should do, what it should **not** do, and where the current implementation diverges from a clean standard.

This evaluation focuses on one rule:

> Stack drag should be a small, deterministic input-to-step converter.
> Cache/lazy-load should support it, not shape its core behavior.

## External reference patterns

### 1. Cornerstone3D `StackScrollTool`
Reference:
- `https://raw.githubusercontent.com/cornerstonejs/cornerstone3D/main/packages/tools/src/tools/StackScrollTool.ts`
- `https://raw.githubusercontent.com/cornerstonejs/cornerstone3D/main/packages/core/src/utilities/scroll.ts`

Observed pattern:
- drag code keeps one accumulator (`deltaY`)
- threshold is simple: `pixelsPerImage`
- when threshold crossed, emit logical slice delta
- viewport scroll utility owns clamping / out-of-bounds / load debounce
- input layer does **not** know cache window, surrogate distance, decode relevance, etc.

Standard takeaway:
- input layer emits **intent**
- viewport/loader layer enforces **availability and loading policy**

### 2. vtk.js `MouseRangeManipulator`
Reference:
- `https://raw.githubusercontent.com/Kitware/vtk-js/master/Sources/Interaction/Manipulators/MouseRangeManipulator/index.js`

Observed pattern:
- keeps `incrementalDelta`
- converts movement to stepped value with one simple `processDelta()`
- preserves sub-threshold remainder
- resets remainder on reversal or hard bounds
- listener range/clamp is separated from mouse math

Standard takeaway:
- the drag function should be:
  1. accumulate
  2. quantize to steps
  3. clamp emitted step count
  4. preserve valid remainder
- that is all

## Current Block C architecture

### Current path
- `QtSliceViewer.mouseMoveEvent()`
- `QtSliceViewer._consume_stack_drag_delta()`
- `QtViewerBridge._on_qt_scroll()`
- `QtViewerBridge.set_slice(... fast_interaction=True, interaction_type='drag')`
- `Lightweight2DPipeline.get_rendered_frame()`
- prefetch / surrogate / cache policy in `Lightweight2DPipeline`

### Good parts already present
1. Input and render are at least **functionally** separated by signal boundary:
   - `slice_scroll_requested.emit(delta)`
2. Bridge clamps navigation to currently available slices:
   - `_get_interaction_slice_count_hint()`
   - `_available_slice_count`
3. Pipeline already owns lazy-load behavior:
   - pixel cache
   - frame cache
   - surrogate reuse
   - prefetch radius
   - decode relevance window
4. Wheel precision and drag fast-navigation are already separated in pipeline:
   - wheel = exact
   - drag = surrogate allowed

These are strong foundations.

## Main problems in current design

### Problem 1 — drag policy and cache policy are coupled in one profile
File:
- `modules/viewer/fast/stack_cache_profile.py`

Current design:
- one function returns both:
  - drag settings
  - prefetch settings
  - surrogate settings
  - decode relevance settings

Why this is not standard:
- changing cache strategy changes drag feel
- changing drag feel changes cache assumptions
- one tuning pass can accidentally destabilize the other

For Block C this is the biggest architectural smell.

### Problem 2 — drag function has too much policy knowledge
File:
- `modules/viewer/fast/qt_slice_viewer.py`

`_consume_stack_drag_delta()` currently knows about:
- adaptive policy mode
- threshold by slice count
- per-event cap by slice count
- reversal reset
- startup assist

This is already pushing past the ideal size for a "simple function".

Standard target:
- drag function should only know:
  - accumulator
  - threshold
  - max steps per event
  - reversal behavior

It should not be the place where Block C strategy is invented.

### Problem 3 — the first-step startup assist is useful UX-wise but not a clean standard
Recent local fix introduced:
- `_stacked_first_step_pending`
- reduced first-step threshold
- first emitted step capped to 1
- accumulator reset after first step

Why it helps:
- removes initial sticky feel

Why it is not ideal as a standard:
- the startup rule is special-case behavior inside the core step function
- it discards remainder after first emission
- that means first-step motion is not handled by the same math as the rest of the gesture

This is acceptable as a tactical patch, but not the clean end-state.

### Problem 4 — the bridge still mixes gesture handling with UI side effects
File:
- `modules/viewer/fast/qt_viewer_bridge.py`

`_on_qt_scroll()` currently does all of this:
- nav clamp
- interaction-mode switching
- settle timer behavior
- slider updates
- lock sync throttling
- reference-line update throttling
- render call routing

This makes drag bugs harder to reason about because one delta event triggers multiple control-plane effects.

Standard target:
- `_on_qt_scroll()` should be a narrow "apply requested logical delta" handler
- sync, slider, ref-lines should be downstream observers or clearly isolated helpers

### Problem 5 — Block C contract is implicit, not explicit
The real Block C rule should be:

> Only navigate within the slice range that is already interactively available.
> Lazy cache/load may prepare future slices, but drag must feel correct even if nothing new loads.

Today this contract is implemented across several places, but not defined as one explicit invariant.

## Correct Block C standard

## 1. Input layer standard
The drag function should:
- accumulate raw pixel movement
- convert to logical slice steps using one threshold
- cap emitted steps per event
- preserve sub-threshold remainder
- reset remainder on sign reversal or invalid pointer exit

The drag function should **not**:
- inspect pixel cache
- inspect frame cache
- know surrogate distance
- know prefetch radius
- know decode relevance window
- know whether a slice is on disk but not admitted yet

## 2. Bridge layer standard
The bridge should:
- clamp requested delta to interactive slice range
- mark interaction type (`wheel` vs `drag`)
- own settle timing
- send one logical target index to render path

The bridge should **not** decide drag sensitivity.

## 3. Pipeline/cache standard
The pipeline should:
- decide exact vs surrogate frame
- decide prefetch radius
- decide stale decode discard
- decide cache warming
- never change the meaning of a user drag delta

This is the correct place for lazy-load coordination.

## 4. Progressive/lazy-load coordination standard
For Block C:
- user drag can only land on `interactive_slice_count`
- if total downloaded grows, drag threshold may update for future moves
- already accumulated drag may be rescaled carefully, but should not be reset unless necessary
- cache should help nearby future moves, but drag correctness must not depend on cache being warm

## Verdict on current implementation

### What is correct
- the overall signal flow is directionally correct
- interactive slice clamp exists
- wheel and drag have separate render semantics
- lazy cache behavior is already mostly pipeline-owned

### What is not correct
- drag and cache share one policy object (`stack_cache_profile`)
- drag feel is being tuned indirectly via Block C cache policy knobs
- `_consume_stack_drag_delta()` has grown beyond a clean "simple function"
- `_on_qt_scroll()` still has too many side effects for such a central input path

## Recommended refactor order

### Phase 1 — split policy objects
Create two separate policy functions/modules:
1. `stack_drag_profile.py`
   - threshold model
   - max-steps-per-event
   - maybe startup behavior if kept
2. `stack_cache_profile.py`
   - prefetch radii
   - surrogate distance
   - decode relevance window

This is the most important change.

### Phase 2 — make drag function pure
Target function shape:
- input: `dy`, `accumulator`, `threshold`, `max_steps`
- output: `emit_steps`, `new_accumulator`

Keep pointer-validity and gesture-start/stop outside it.

### Phase 3 — isolate bridge side effects
Split `_on_qt_scroll()` into helpers:
- `_resolve_target_slice_from_delta()`
- `_apply_fast_scroll_render()`
- `_update_scroll_side_effects()`

So the logical step path becomes auditable.

### Phase 4 — codify Block C invariants in tests
Add tests for:
- drag delta independent of cache state
- same drag sequence with cold vs warm cache produces same logical slice path
- same drag sequence with download active vs inactive produces same logical slice path, limited only by available slice count
- progressive growth updates admissible range without changing already emitted step history

## Engineering conclusion

If Block C must be reliable, then:

> Drag standard must be defined by interaction math.
> Lazy-load standard must be defined by render/cache policy.
> The two may coordinate through `interactive_slice_count`, but they should not share one tuning brain.

Right now the repo is close, but not fully there yet.

The current implementation is **partially correct operationally** and **not yet correct architecturally**.

## Immediate practical recommendation

Do **not** keep solving this by only changing numbers in `build_stack_cache_profile()`.

That may improve one log and break another because it mixes two jobs:
- user interaction semantics
- lazy cache/load semantics

The next correct implementation step is to split drag policy from cache policy and reduce `_consume_stack_drag_delta()` back to a small deterministic step quantizer.
