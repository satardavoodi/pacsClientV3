"""
REGRESSION GUARDS: Ensure FAST Progressive Grow Stays < 10ms p95
May 8, 2026

This document outlines safeguards and monitoring to prevent regression of the
May 8, 2026 optimization (50-1000x improvement: 200-3000ms → 2-4ms).

May 12, 2026 addendum: FAST additive grow batching hardening is documented in
`docs/plans/FAST_GROW_BATCHING_HARDENING_2026-05-12.md`. The guards below now
also protect against duplicate/stale grow admission and teardown leakage.

====================================================================
GUARD 1: Metadata Append Cap (16 entries max per tick)
====================================================================
Location: _vc_progressive.py line 60
Constant: _FAST_PROGRESSIVE_METADATA_APPEND_CAP = 16

Why 16?
- Non-terminal grows run every 150ms (base interval)
- Series with 100 slices would grow 16/tick = 6-7 ticks to complete
- Balances responsiveness (16 entries ≈ 50ms sync work) vs responsiveness

Guard rule:
- This MUST be passed to _refresh_and_sync_metadata() for non-terminal path
- Line 1780: _refresh_and_sync_metadata(series_number, max_new_entries=_FAST_PROGRESSIVE_METADATA_APPEND_CAP)
- If missing or hardcoded differently, will regress to unbounded syncs

Test: tests/viewer/test_fast_viewer_pipeline.py::TestProgressiveGrow::test_progressive_nonterm_metadata_batched_on_grow

====================================================================
GUARD 2: Metadata Sync Interval Throttle (700ms minimum)
====================================================================
Location: _vc_progressive.py line 57
Constant: _FAST_PROGRESSIVE_METADATA_SYNC_MIN_INTERVAL_MS = 700.0

Why 700ms?
- Non-terminal grows try every 150ms, but metadata sync only happens if > 700ms elapsed
- Allows 4-5 grow ticks to batch metadata updates
- Reduces update storms from 1-per-150ms to 1-per-700ms = 82% reduction

Guard rule:
- Check condition at line ~1775:
    if _last_ms >= 0.0 and (_now_ms - _last_ms) < _FAST_PROGRESSIVE_METADATA_SYNC_MIN_INTERVAL_MS:
        return  # Skip deferred sync
- If this condition is removed or threshold is lowered, will regress to rapid re-entry

Test: tests/viewer/test_fast_viewer_pipeline.py::TestProgressiveGrow::test_progressive_metadata_sync_throttle

====================================================================
GUARD 3: Terminal vs Non-Terminal Path Split
====================================================================
Location: _vc_progressive.py line ~1748
Parameters: _refresh_and_sync_metadata(..., terminal=False)

Why split?
- Terminal (on download completion) MUST do full sync, no throttle, no cap
- Non-terminal (periodic grows) use throttle + cap to batch updates
- Without split, terminal completions could be delayed if interval gate is active

Guard rule:
- All calls from completion handlers MUST pass terminal=True
- Check: _on_series_download_fully_complete_impl, load_series_on_demand
- If terminal=False is used at terminal paths, will delay completion by up to 700ms

Test: tests/viewer/test_fast_viewer_pipeline.py::TestProgressiveGrow::test_progressive_terminal_completes_immediately

====================================================================
GUARD 4: No Duplicate refresh_file_list Method
====================================================================
Location: modules/viewer/fast/lightweight_2d_pipeline.py
Expected: Only one definition (line 2706)

Why?
- Duplicate definitions cause confusion during maintenance
- Second definition would shadow first, causing unpredictable behavior
- Violates Python best practices

Guard rule:
- Run: grep -n "def refresh_file_list" modules/viewer/fast/lightweight_2d_pipeline.py
- Expected output: ONE match at line 2706
- If two matches: regression detected

Also check plugin mirror:
- builder/plugin package/.../modules/viewer/fast/lightweight_2d_pipeline.py
- Must have same single definition

Test: grep check in build pipeline / manual verification

====================================================================
GUARD 5: os.scandir Usage (not Path.iterdir)
====================================================================
Location: _vc_cache.py lines 495, 819
Pattern: with os.scandir(series_path) as entries:

Why?
- os.scandir is ~3x faster than Path.iterdir() for large directories
- Metadata scan reduced from ~15ms to ~2ms
- Uses single syscall per entry vs separate stat() calls

Guard rule:
- Check for os.scandir in _refresh_stored_metadata_instances and _count_series_files_on_disk
- If refactored to use Path.iterdir or glob, will regress latency by 6-8x
- Import os at top of file (already present)

Test: No specific test, but KPI will show if latency regresses

====================================================================
GUARD 6: Additive Grow Buffering and Terminal Force-Flush
====================================================================

Location: modules/viewer/fast/lightweight_2d_pipeline.py
Related files:
- modules/viewer/fast/qt_viewer_bridge.py
- PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py
- builder/plugin package/.../modules/viewer/fast/lightweight_2d_pipeline.py

Why?
- Same-series overlap should not mutate `_slices` on every small downloaded batch.
- Expensive work in the grow path is not file discovery itself; it is the
    structural mutation sequence: sort + cache remap + geometry invalidation +
    cache prune.
- Buffering reduces those mutations while terminal force-flush preserves exact
    completion behavior.

Guard rules:
- `_grow_batch_flush_threshold()` must preserve the size-aware policy:
    - `< 50`: `1`
    - `<= 100`: `10`
    - `<= 200`: `25`
    - `> 200`: `50`
- Scan submission must exclude both already-applied paths and
    `_pending_grow_entries` paths.
- Completed scan results must be filtered again before buffering so duplicate
    or stale paths do not enter the pending buffer.
- Terminal completion must continue to pass `force_flush=True` through the Qt
    bridge path.
- `close_series()` must clear `_pending_grow_entries` and attempt
    `_grow_future.cancel()` before dropping the future reference.

Tests:
- tests/viewer/test_fast_viewer_pipeline.py::test_lightweight_refresh_file_list_preserves_caches_by_slice_identity
- tests/viewer/test_fast_viewer_pipeline.py::test_lightweight_refresh_file_list_filters_duplicate_and_existing_entries
- tests/viewer/test_fast_viewer_pipeline.py::test_lightweight_close_series_cancels_pending_grow_and_clears_buffer
- tests/viewer/test_fast_viewer_pipeline.py::test_qt_bridge_grow_updates_count_without_calling_set_slice

====================================================================
REGRESSION DETECTION RULES (Quick checks)
====================================================================

RED FLAGS:
1. grow_p95_ms > 50 in fresh KPI parse → metadata changes leaked
2. Non-terminal sync happening every 150ms instead of every 700ms → interval gate removed
3. Duplicate method definitions in refresh_file_list → shadowing bug
4. Metadata scan > 10ms for 100-entry series → os.scandir replaced with slower path
5. Terminal completions delayed by 700ms intervals → terminal=True not passed
6. Repeated `FAST:additive_cache_grow` lines for tiny same-series download batches → buffering bypassed or force-flush leaked into non-terminal path
7. Duplicate slice paths in `_slices` or pending grow state after progressive download → stale/duplicate filter regressed
8. Growth appears after close/reopen without new files → pending buffer or stale future leaked across teardown

DETECTION:
- Parse viewer_diagnostics.log after each test run
- Check: progressive_grow_apply_ms_p95 < 10ms
- Check: DM rebuild count = 0 (R22 fix still in place)
- Check: metadata sync interval gaps ~700ms (not 150ms)

====================================================================
CODE REVIEW CHECKLIST
====================================================================

When modifying progressive grow code:
- [ ] Verify _FAST_PROGRESSIVE_METADATA_APPEND_CAP value (16)
- [ ] Verify _FAST_PROGRESSIVE_METADATA_SYNC_MIN_INTERVAL_MS value (700.0)
- [ ] Check max_new_entries passed to _refresh_and_sync_metadata (non-terminal only)
- [ ] Check terminal=True passed to sync path in completion handlers
- [ ] Grep for duplicate refresh_file_list definitions (should be 1)
- [ ] Verify os.scandir used in _count_series_files_on_disk and _refresh_stored_metadata_instances
- [ ] Verify `_grow_batch_flush_threshold()` still uses 1/10/25/50 policy
- [ ] Verify completed grow scan results are filtered against both `_slices` and `_pending_grow_entries`
- [ ] Verify `close_series()` clears pending grow state and attempts `_grow_future.cancel()`
- [ ] Run overlap regression (43 tests) — must all pass
- [ ] Run B34 tests (40 tests) — must all pass
- [ ] Parse KPI: grow_p95 < 10ms, DM rebuilds = 0

====================================================================
MONITORING DASHBOARD (Proposed)
====================================================================

Metrics to track per test session:
- progressive_grow_apply_ms_p95: target < 10ms
- progressive_grow_apply_ms_max: target < 50ms
- fast_drag_ui_lag_p95_ms: target < 500ms (separate from grow)
- dm_rebuild_count: target = 0 (R22 related)
- metadata_sync_count_per_session: should be ~1 per 700ms, not per 150ms
- os_scandir_latency_ms_per_100_entries: target ~2ms, warn > 5ms
- additive_cache_grow_flush_count_per_same_series_session: lower is better, expect major reduction on 200+ slice series

====================================================================
"""
