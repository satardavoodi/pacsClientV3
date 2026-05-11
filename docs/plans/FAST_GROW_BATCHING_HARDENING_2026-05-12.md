FAST Grow Batching Hardening
May 12, 2026

Problem

- FAST same-series stack interaction was still paying too many additive grow mutations while the same series was downloading.
- Even after metadata stabilization work, the grow path could still trigger repeated sort/remap/prune cycles on small downloaded batches.
- The user-visible result was avoidable drag interference: more chances for lag, more cache churn, and more main-thread work than necessary.

Goal

- Keep additive growth in FAST mode.
- Reduce the frequency of expensive structural mutations to the slice list and index-keyed caches.
- Preserve correctness and reliability: no duplicate slice admission, no stale grow results after close/reopen, no growth loops, no cache identity corruption, and no delayed terminal completion.

Files Changed

- modules/viewer/fast/lightweight_2d_pipeline.py
- builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/lightweight_2d_pipeline.py
- modules/viewer/fast/qt_viewer_bridge.py
- builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/qt_viewer_bridge.py
- PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py
- tests/viewer/test_fast_viewer_pipeline.py

Method

1. Split discovery from apply

- Background grow scanning still uses the single-worker `_grow_executor`.
- Completed `DicomHeaderEntry` scan results are first buffered in `_pending_grow_entries`.
- `_slices` is mutated only when the pending buffer reaches a threshold, or when terminal completion explicitly forces a flush.

2. Make batch size depend on series scale

- `_grow_batch_flush_threshold()` chooses the minimum buffered-entry count required before a flush:
  - `< 50 slices`: `1`
  - `<= 100 slices`: `10`
  - `<= 200 slices`: `25`
  - `> 200 slices`: `50`
- The threshold uses `max(len(_slices), _interaction_slice_count_hint)` so a large announced stack behaves like a large stack from the start, even before all files are present on disk.

3. Keep terminal completion exact

- `QtViewerBridge.grow(force_flush=False)` now accepts a terminal override.
- `_vc_progressive.py` passes `force_flush=terminal` in the regular grow path and `force_flush=True` in the final completion path.
- This preserves the responsiveness win during download while keeping the completion contract exact: terminal grow applies all buffered slices immediately.

4. Defend against duplicate and stale admission

- New `_filter_pending_grow_entries()` removes any completed scan results whose paths are already present in `_slices`, already present in `_pending_grow_entries`, or duplicated within the same scan result.
- The next submitted scan already excludes both applied and pending paths; the new filter is a second defensive boundary in case a stale or repeated result still comes back.

5. Tear down safely

- `close_series()` now clears `_pending_grow_entries` and attempts `cancel()` on any queued `_grow_future` before dropping the reference.
- This avoids stale grow results leaking into a close/reopen sequence and prevents unnecessary queued work from surviving teardown.

Core Logic

Hot path in `refresh_file_list(force_flush=False)`:

1. If `_grow_future` is done, read its results.
2. Filter those results through `_filter_pending_grow_entries()`.
3. Append accepted entries to `_pending_grow_entries`.
4. If `force_flush=True` or pending-count >= batch threshold, then:
   - materialize `SliceMeta`
   - extend `_slices`
   - sort once
   - remap index-keyed caches by path identity once
   - invalidate geometry cache once
   - prune caches once
5. If no scan is in flight, submit the next background scan excluding both applied and pending paths.

Why this is safer

- Single writer: `_slices`, `_pixel_cache`, `_frame_cache`, and geometry state are still mutated only on the caller side of `refresh_file_list()`, not inside the worker thread.
- No duplicate rows: path filtering happens both before scan submission and after scan completion.
- No stale reopen carry-over: pending buffer is cleared and queued grow work is cancelled on close.
- No data loss on completion: terminal flush bypasses batching and applies all buffered slices.
- Cache correctness preserved: `_remap_indexed_caches_after_resort()` still maps old cache entries by path, not old index.

Expected Performance Effect

- For a 300-slice series downloaded in small batches, structural grow work drops from roughly one flush per small batch to roughly one flush per 50 accepted slices.
- Practical expectation from the design discussed during implementation:
  - previous pattern: about 33 sort/remap/prune cycles for a 300-slice additive load
  - new pattern: about 6 such cycles
- That reduces the amount of main-thread work competing with drag handling while preserving additive growth.

KPI Impact

Primary KPIs expected to improve or remain protected

- `same_series_progressive_grow_apply_ms_p95`
- `same_series_progressive_drag_ui_lag_p95_ms`
- `same_series_progressive_drag_event_p95_ms`

Supporting indicators expected to improve

- lower count of `FAST:additive_cache_grow` flush events per download session
- lower repeated sort/remap/prune work during same-series overlap
- less unnecessary cache churn during progressive stack growth

Measured validation completed in this change set

- Focused FAST grow regression tests: passed
- Broader FAST viewer regression pack: `211 passed, 20 warnings in 6.16s`
- Earlier broader pack before the two new tests: `209 passed, 20 warnings in 7.21s`

Important KPI note

- This change set did not include a fresh live overlap-log capture from a real download-and-stack session.
- So the engineering expectation is strong and test validation is green, but a new session-scoped KPI parse is still required before claiming a measured p95 delta in production-like runtime logs.

Reliability Rules Introduced

- Completed grow scan results must be filtered against both live and pending slice paths before buffering.
- `close_series()` must clear pending grow state and attempt to cancel queued grow scan work.
- Terminal completion must continue to force-flush the pending grow buffer.
- Plugin mirror must remain behavior-identical to the canonical FAST pipeline file.

Regression Tests Added or Updated

- `test_lightweight_refresh_file_list_preserves_caches_by_slice_identity`
- `test_lightweight_refresh_file_list_filters_duplicate_and_existing_entries`
- `test_lightweight_close_series_cancels_pending_grow_and_clears_buffer`
- `test_qt_bridge_grow_updates_count_without_calling_set_slice`

Review Checklist

- Verify `_grow_batch_flush_threshold()` still uses the 1/10/25/50 policy unless re-measured.
- Verify scan submission excludes both `_slices` and `_pending_grow_entries` paths.
- Verify completed scan results are filtered again before buffering.
- Verify terminal completion paths still pass `force_flush=True`.
- Verify `close_series()` clears pending grow state and attempts to cancel `_grow_future`.
- Verify canonical and plugin mirror files remain in sync.

Next Validation Step

- Run a fresh same-series overlap session and parse session-scoped KPIs from logs, with special attention to:
  - `same_series_progressive_grow_apply_ms_p95`
  - `same_series_progressive_drag_ui_lag_p95_ms`
  - count of `FAST:additive_cache_grow` events
