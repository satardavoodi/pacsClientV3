# Performance Decision Log — 2026-02-24

## Scope
- Goal: keep diagnostics traceable, avoid log overfill, decide whether to measure more or implement now.
- Conditions:
  - Plan A = no active download
  - Plan B = active download while viewer scrolling

## New Data Points Captured

### Plan A (baseline)
- `VTKWidget.set_slice_total`: repeatedly ~45–60 ms, spikes up to ~91 ms.
- `VTKWidget.set_slice.slice_apply`: often ~35–55 ms, spikes ~70 ms.
- `image_io.load_single_series_by_number.itk_filter_chain`: repeatedly ~1.64–2.17 s.
- `image_io.load_single_series_total`: repeatedly ~1.85–2.34 s.
- `image_io.disk_read`: ~70–222 ms.
- DB timings (`pool_lock_wait`, `reuse_validate`, viewer db read): low, typically sub-ms to few ms.

### Plan B (download active)
- ZetaBoost warmup correctly blocked:
  - `WORKER_BLOCKED ... reason=global_download_active(1)` observed repeatedly.
- Viewer improved vs Plan A:
  - `set_slice_total` mostly ~22–45 ms, occasional spikes ~52–72 ms.
  - `slice_apply` mostly ~18–40 ms, occasional spikes ~55–60 ms.
- Download subprocess path:
  - `SocketDicomClient.send_request.request_total` usually ~0.8–0.9 s, worst observed ~3.2 s.
  - `response_header_recv` often 50–190 ms.
  - `response_parse` usually ~18–44 ms, one spike ~186 ms.
  - `save_series_instances_total` ~0.4–0.58 s per save block.
- Reliability issue observed:
  - `Download process ... exited unexpectedly`.

## Steps Taken Today

1. Stopped active Plan B run manually to prevent further log flooding and keep current evidence readable.
2. Added rotating diagnostic logs to prevent unbounded file growth:
   - `PacsClient/utils/diagnostic_logging.py`
   - Uses `RotatingFileHandler` for viewer/download diagnostics.
   - New env controls:
     - `AIPACS_LOG_MAX_BYTES` (default 20 MB)
     - `AIPACS_LOG_BACKUP_COUNT` (default 3)
3. Reduced high-frequency viewer timing spam while preserving slow-event evidence:
   - `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py`
   - Added `_should_log_timing()`:
     - always log slow timings (default >=35 ms)
     - sample normal timings every N events (default every 25)
   - New env controls:
     - `AIPACS_VIEWER_TIMING_MIN_MS` (default 35)
     - `AIPACS_VIEWER_TIMING_SAMPLE_EVERY` (default 25)
4. Verified edits with diagnostics/syntax checks (no editor-reported errors in modified files).

## Performance Improvements Observed

- Relative to Plan A, Plan B shows meaningful viewer latency reduction once warmup blocking is active.
- Main remaining viewer jitter is now intermittent, not sustained.
- Bottleneck shifted from main-process warmup ITK contention to download subprocess/network-request latency and occasional DB-save blocks.

## Decision (Option 2: Implement Changes Now)

### Decision
Proceed with implementation now (selected changes), while continuing incremental measurement.

### Why
- Evidence is sufficient for the current root cause transition:
  - Warmup contention in Plan A is confirmed.
  - Global download blocking works in Plan B and improves viewer behavior.
  - New dominant constraints are visible (request_total / save_series_instances_total / subprocess unexpected exit).
- Log volume itself became a blocker; anti-flood/rotation changes are necessary operational improvements.

### What was implemented immediately
- Log rotation + viewer timing sampling/thresholding (see “Steps Taken Today”).

## Improvement Opinions

### Plan A improvements (also relevant to Plan B viewer path)
1. Keep warmup bounded and defer heavy ITK work from interactive windows.
2. Keep per-slice event telemetry sampled by default; only elevate slow slices.
3. Reduce repeated uncached `load_single_series_*` work during active interaction.
4. Prioritize robust handling for malformed/mixed-size series to avoid expensive fallback loops.

### Plan B improvements
1. Keep `global_download_active` blocking behavior as default policy during active downloads.
2. Investigate subprocess unexpected exits first (stability before micro-optimization).
3. Profile `SocketDicomClient.send_request.request_total` outliers (0.8s typical, multi-second worst).
4. Profile and potentially chunk/yield `save_series_instances_total` path to reduce burst latency.

## Next Incremental Steps

1. Add explicit subprocess exit diagnostics (exit code + last stage marker + last request context).
2. Run one short Plan B re-test with new anti-flood settings.
3. Generate updated A/B bottleneck table and compare against this baseline.
4. If subprocess stability issue reproduces, prioritize fix before further performance tuning.

## Change Tracking

- Updated code:
  - `PacsClient/utils/diagnostic_logging.py`
  - `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py`
  - `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`
  - `PacsClient/zeta_download_manager/network/socket_client.py`
- Updated documentation:
  - `docs/PERFORMANCE_DECISION_LOG_2026-02-24.md`

## Implementation Wave 2 (Reversible Plan A-first controls)

### Change A: Viewer-first warmup deferral (low-risk, reversible)
- File: `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`
- Added interaction-aware gating so deferred heavy warmup waits for an idle viewer window.
- Added `notify_viewer_interaction(reason=...)` and connected active interactions:
  - series switch path (`change_series_on_viewer`)
  - wheel scrolling path (`vtk_widget.py` calls controller notifier)
- During active interaction, Zeta external interactive-busy state remains true; it auto-releases after idle debounce.

New env toggles:
- `AIPACS_PLAN_A_VIEWER_FIRST` (default `1`)
- `AIPACS_HEAVY_WARMUP_IDLE_SEC` (default `2.5`)
- `AIPACS_VIEWER_INTERACTION_PAUSE_MS` (default `350`)

Rollback:
- Set `AIPACS_PLAN_A_VIEWER_FIRST=0` to disable this behavior immediately.

### Change B: Download load shaping for weak hardware (reversible)
- File: `PacsClient/zeta_download_manager/network/socket_client.py`
- Added configurable burst shaping:
  - adaptive batch cap (instead of hard-coded cap)
  - small inter-batch pause
  - configurable post-request yield
- Objective: reduce burst CPU/network pressure while preserving steady throughput.

New env toggles:
- `AIPACS_DOWNLOAD_BATCH_SIZE_CAP` (default `10`)
- `AIPACS_DOWNLOAD_INTER_BATCH_PAUSE_MS` (default `3`)
- `AIPACS_DOWNLOAD_POST_REQUEST_YIELD_MS` (default `5`)

Rollback:
- Set `AIPACS_DOWNLOAD_INTER_BATCH_PAUSE_MS=0` and `AIPACS_DOWNLOAD_POST_REQUEST_YIELD_MS=0` to disable pacing.
- Restore previous batch cap behavior with `AIPACS_DOWNLOAD_BATCH_SIZE_CAP=10`.

### Expected effect on constrained systems
- Lower UI contention during active scroll/series-switch windows.
- Fewer short CPU bursts in download loop under sustained transfer.
- Smoother viewer interaction at slight cost to peak download aggressiveness.

## Implementation Wave 3 (Reliability-first root-cause fixes)

### Change C: Deterministic ITK mixed-size fallback (no repeated failing loops)
- Files:
  - `PacsClient/pacs/patient_tab/utils/image_io.py`
  - `PacsClient/pacs/patient_tab/utils/utils.py`
- Problem addressed:
  - Repeated SimpleITK region mismatch failures (`Requested region ... outside the largest possible region`) caused expensive retry/fallback chains.
- What changed:
  - Added explicit error-pattern detection for ITK region-mismatch exceptions.
  - On mismatch, group DICOM files by `Rows x Columns`, keep dominant cohort, preserve input order, and execute one deterministic reader fallback.
  - Simplified `get_itk_image_optimized()` to delegate to the stable `get_itk_image()` path instead of re-running multiple reader attempts.
  - Updated fast-first path to use `get_itk_image()` directly on large-series path.
- Expected impact:
  - Prevent repeated failure loops and reduce first-load stall spikes on mixed-size/problematic series.
  - Improve predictability of first-series load under malformed input.

### Change D: Subprocess exit handling hardened against queue/process race
- File: `PacsClient/zeta_download_manager/workers/download_process_worker.py`
- Problem addressed:
  - Parent bridge could report “process exited unexpectedly” before final queue messages arrived.
- What changed:
  - Removed fragile `Queue.empty()`-based unexpected-exit decision.
  - Added short grace window after child death before concluding failure.
  - Unexpected-exit message now includes subprocess exit code for diagnosis.
- Expected impact:
  - Fewer false/ambiguous unexpected-exit reports.
  - Better triage quality when real subprocess crashes occur.

### Change E: DB save smoothing via chunked inserts (reversible)
- File: `PacsClient/zeta_download_manager/download/series_downloader.py`
- Problem addressed:
  - Large one-shot `batch_insert_instances` calls produced occasional long `save_series_instances_total` spikes.
- What changed:
  - Split instance inserts into configurable chunks.
  - Yield briefly between chunks to keep UI scheduling smooth during active download.
  - Added per-chunk and total insert timing metadata.

New env toggles:
- `AIPACS_DB_INSERT_CHUNK_SIZE` (default `120`, minimum `25`)
- `AIPACS_DB_INSERT_CHUNK_YIELD_MS` (default `5`)

Rollback:
- Set `AIPACS_DB_INSERT_CHUNK_SIZE` high (e.g., larger than typical series instance count) and `AIPACS_DB_INSERT_CHUNK_YIELD_MS=0` to approximate previous one-shot insert behavior.

### Validation status
- Editor diagnostics for modified files: no errors reported.
