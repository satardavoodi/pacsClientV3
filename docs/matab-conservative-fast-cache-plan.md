# Conservative FAST Cache Architecture Plan

## Summary

Implement the change as a controlled structural update to the FAST viewer pipeline, not as scattered fixes. The work is split into clear phases with bounded goals, measurable outcomes, and internal verification at each phase.

Primary architectural intent:

- Progressive download growth updates the available slice set additively.
- Viewer navigation state remains owned by user interaction, not by cache growth.
- Active FAST viewers cache decoded pixels, rendered/filter-applied frames, and reusable geometry metadata more completely.
- Verification relies mostly on unit/integration tests and cache/slice KPIs, with live testing reserved for final real-world coordination.

Branch/push constraints:

- Create branch `matab-conservative` before code changes.
- Preserve unrelated dirty worktree changes.
- Push later only when instructed.
- Push only to `origin`, never `account2`.

## Phase 1: Architecture Baseline And Safety Checks

Goal:
- Establish the exact FAST data flow before changing behavior.

Expected outcome:
- A verified map of the involved components: progressive download signal flow, FAST viewer grow path, slice-count update path, current-slice ownership, and pixel/frame/geometry cache ownership.

Must achieve:
- Identify which paths are allowed to mutate cache membership.
- Identify which paths are allowed to mutate current slice.
- Confirm Advanced/VTK paths are out of scope.

Success criteria:
- The implementation target is limited to FAST/Qt progressive paths.
- No ambiguous ownership remains for `setSlice` or cache invalidation.

Verification:
- Static inspection of `Lightweight2DPipeline`, `QtViewerBridge`, progressive grow controller, and FAST series refresh path.
- Add code/test comments documenting the ownership rule: growth changes availability; user interaction changes current slice.

## Phase 2: Additive Slice And Frame Cache Growth

Goal:
- Make progressive growth additive without clearing existing useful cache entries.

Expected outcome:
- When new slices arrive, existing decoded pixels and compatible rendered frames remain cached.
- Only new slice metadata is appended and sorted.
- Cache pruning happens only after growth and only according to configured limits.

Must achieve:
- Replace whole-frame-cache clearing during FAST growth with compatibility-preserving behavior.
- Preserve frame-cache entries when their slice index, window/level, filter state, and slice identity remain valid.
- Keep existing full invalidation for true presentation changes such as window/level or filter-configuration changes.

Success criteria:
- Growing from N slices to N+M does not clear the entire pixel or frame cache.
- Existing cached entries remain usable after growth.
- New slices become available for scrolling without rebuilding old cache.

Verification:
- Unit test: populate `_pixel_cache` and `_frame_cache`, call `refresh_file_list()` with additional slice headers, assert old cache entries remain.
- Unit test: confirm cache pruning still respects effective limits.
- KPI/log assertion includes old count, new count, pixel-cache preserved count, and frame-cache preserved count.

## Phase 3: Stable Current-Slice Ownership

Goal:
- Ensure progressive growth never moves the current slice unless the user or an explicit navigation feature requests it.

Expected outcome:
- Initial display still chooses the intended initial slice.
- Later additive growth preserves `QtViewerBridge.GetSlice()`.
- Slider value stays aligned with current slice without triggering a render/navigation loop.

Must achieve:
- Separate "slice count changed" from "current slice changed."
- Avoid calling `set_slice()` from additive growth unless initializing a newly opened viewer.
- Same-series FAST refresh must preserve current slice and avoid unnecessary re-render/reset.
- Slider max/range may update; slider value must not jump.

Success criteria:
- If the viewer is on slice 20 and slices 21-25 arrive, the viewer remains on slice 20.
- The current slice is not reset to 0 or midpoint during progressive growth.
- The initial display still opens on the configured initial slice.

Verification:
- Unit/integration test: simulate a Qt bridge at slice 20, grow slice count, assert bridge current slice, pipeline current index, and slider value remain 20 while slider maximum increases.
- Regression test around existing reset-slider behavior.
- Static assertion by code structure: additive grow path updates count/metadata only; navigation calls remain in user interaction or explicit sync paths.

## Phase 4: Geometry And Viewer-Metadata Cache Layer

Goal:
- Cache reusable geometry and viewer metadata for active FAST layouts without changing clinical behavior.

Expected outcome:
- Repeated stacking/sync/reference-line operations reuse derived geometry data instead of recomputing it every time.
- Cache grows additively with new slices.
- Geometry cache invalidates only when slice metadata identity/order changes.

Must achieve:
- Add a dedicated derived-metadata cache boundary inside the FAST pipeline or geometry helper layer.
- Cache data such as slice positions, slice normal, spacing-derived values, and reusable reference-line geometry inputs.
- Keep raw DICOM metadata as the source of truth.
- Avoid caching anything tied to transient UI state unless it has a clear invalidation rule.

Success criteria:
- Geometry lookups for unchanged slice metadata are cache hits.
- Adding new slices extends or refreshes only the affected derived geometry.
- Reference-line/sync tests continue to pass.

Verification:
- Unit test: repeated geometry calculation returns same result and records/cache-detects reuse.
- Unit test: after additive growth, geometry cache updates to include new slices.
- Existing sync/reference-line tests continue to pass.

## Phase 5: Cache Capacity Policy For Active FAST Layouts

Goal:
- Increase RAM caching conservatively where it benefits active FAST viewers.

Expected outcome:
- Active layouts can retain more decoded pixels and rendered/filter-applied frames.
- Existing environment overrides remain respected.
- Memory growth is bounded and explainable.

Must achieve:
- Adjust adaptive cache sizing rather than hard-coding unlimited caches.
- Keep explicit env-configured cache sizes authoritative.
- Prefer active-viewer cache expansion over global expansion.
- Keep cache limits deterministic in tests.

Success criteria:
- A 500-slice study can retain a substantially larger active working set.
- Cache size remains bounded by adaptive maximum.
- Tests using small custom cache sizes remain deterministic.

Verification:
- Unit tests for effective cache limit calculation.
- KPI/log check for effective pixel cache limit, effective frame cache limit, and actual cache size after grow.

## Phase 6: Phase-Level Test Harness And KPIs

Goal:
- Verify most goals internally without requiring manual live testing.

Expected outcome:
- Each structural claim has an automated test or measurable KPI.

Must achieve:
- Add tests for additive cache preservation, stable current slice, filtered-frame cache retention, geometry cache reuse, and cache limit policy.
- Add or reuse lightweight fakes/stubs instead of requiring live PACS/download services.

Success criteria:
- Targeted tests pass locally.
- Tests fail clearly if a future change reintroduces full cache clearing or slice jumps.

Verification commands:
- `pytest tests/viewer/test_fast_viewer_pipeline.py`
- `pytest tests/viewer/test_fast_viewer_reset_slider.py`
- `pytest tests/viewer/test_dragdrop_progressive.py`
- `pytest tests/fast`
- `pytest tests/fast_viewer`

KPIs:
- Cache growth event preserves existing entries.
- Current slice before grow equals current slice after grow.
- Frame-cache hit rate does not reset to zero after additive growth.
- Geometry cache hit/reuse is observable in tests.

## Phase 7: Controlled Integration Verification

Goal:
- Confirm the structural change works across the FAST progressive pipeline.

Expected outcome:
- Download progress, viewer grow, cache updates, slider updates, and current-slice preservation coordinate correctly.

Must achieve:
- Run integration-style tests using internal fakes where possible.
- Confirm no regression in FAST drag/drop and progressive lifecycle behavior.
- Confirm Advanced/VTK tests are not affected.

Success criteria:
- Progressive grow updates available slice count.
- Current slice is stable through grow.
- Existing FAST interaction behavior remains intact.
- No new broad cache invalidation appears in logs/tests.

Verification:
- `pytest tests/viewer/test_b43_progressive_lifecycle_state.py`
- `pytest tests/viewer/test_fast_download_scroll_cpu_repro.py`
- `pytest tests/viewer/test_overlap_pixel_quality.py`
- `pytest tests/performance/test_fast_scroll_perf.py`
- Optional broader run: `pytest tests/viewer`

## Phase 8: Live Test Gate

Goal:
- Use live testing only for real-world coordination that internal tests cannot fully simulate.

Expected outcome:
- Manual/live verification is limited to final confirmation of downloader/UI timing.

Must achieve:
- Request live test only after internal tests pass.
- Live test scenario: start progressive FAST download, open first available slices, navigate to a non-initial slice such as slice 20, let additional slices download, confirm image and slider remain on slice 20, confirm newly downloaded slices become reachable, and confirm scrolling remains smooth after growth.

Success criteria:
- No current-slice jump during download.
- No full-cache rebuild symptoms when new slices arrive.
- Newly downloaded slices become available.
- No visible regression in reference lines/sync behavior.

Verification:
- Viewer logs show additive grow with preserved cache counts.
- User-observed behavior matches the scenario above.
- No repeated live loops unless a specific failure is found.

## Stacking Jitter Review

Goal:
- Determine whether small stack-drag jitter comes from `setSlice`, the cache,
  additive cache updates, cache-limit transitions, or another FAST viewer layer.

Finding:
- The most likely cause is the existing drag-time surrogate policy in
  `Lightweight2DPipeline._try_surrogate_frame()`.
- During stack-drag, if the exact target slice is not already cached, FAST can
  show the nearest cached frame or pixel while the requested slice is warmed or
  decoded.
- That means the logical slice and slider may already point at the requested
  slice, while the displayed pixels briefly come from a nearby cached slice.
  This looks like a small one-slice backward/forward movement.

Less likely after the conservative implementation:
- `setSlice`: additive growth no longer calls `set_slice()` for same-slice
  updates.
- Additive cache growth: preserved cache entries are remapped by file path after
  sorting, so growth should not attach cached pixels to the wrong slice.
- Cache-limit transition by itself: LRU pruning can create cache misses at the
  edge, but the visible twitch comes from surrogate substitution after the miss.

Handling:
- Keep wheel scrolling exact; wheel interaction must not use surrogates.
- Keep drag surrogates for responsiveness, but bound their visible use with a
  fidelity guard.
- Terminal slices now force exact rendering during drag, so the first and last
  slice do not wait for mouse release to become visually exact.
- Far cached substitutes now fall through to exact decode instead of being
  displayed as the requested target.
- Repeated reuse of the same non-near surrogate now breaks to exact decode
  sooner, reducing the "one slice behind" feeling in large stacks without
  removing near-neighbor surrogate smoothness.
- Overlap diagnostics now include `source_idx` and `source_dist` so future logs
  can distinguish logical slice state from the actual image source used for a
  surrogate frame.

## Assumptions

- "Main GitHub account" means `origin`.
- `account2` must not be used.
- This work is FAST/Qt-focused; Advanced/VTK behavior should remain unchanged.
- RAM-first caching is acceptable for active layouts, but must remain bounded.
- Raw DICOM metadata remains the source of truth; cached geometry is derived and disposable.
