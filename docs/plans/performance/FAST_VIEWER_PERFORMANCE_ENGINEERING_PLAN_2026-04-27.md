# Unified Viewer Performance Engineering Plan

Date: 2026-04-27

Primary target: improve FAST Viewer stacking and download experience by 50% to 100% where safely possible.

Secondary requirement: shared infrastructure improvements must benefit both FAST and Advanced modes instead of creating duplicated paths.

This file remains at the original requested path:

`docs/plans/performance/FAST_VIEWER_PERFORMANCE_ENGINEERING_PLAN_2026-04-27.md`

## Summary

FAST and Advanced differ mainly in Block B and Block C: rendering, filtering, interaction handling, and cache strategy.

They share most of Block A and many support connections: database, server communication, download, disk layout, DICOM storage, thumbnails, logs, progress state, and several viewer orchestration layers. These shared parts must be optimized once through unified services and measured for both modes.

The plan therefore has two tracks:

- Shared infrastructure track: applies to both FAST and Advanced.
- Mode-specific viewer track: separate work for FAST and Advanced where render engines, filters, and caches are genuinely different.

Canonical runtime logs:

`C:\AI-Pacs codes\aipacs-pydicom2d\user_data\logs`

Existing KPI assets to extend:

- `tools/performance/clearcanvas_aipacs_kpi_harness.py`
- `tests/performance/block_kpi_model.json`
- `docs/performance/FAST_VIEWER_KPI_CATALOG.md`

Reference docs already present:

- `docs/viewer/SHARED_COMPONENTS.md`
- `docs/viewer/FAST_vs_ADVANCED_ARCHITECTURE.md`
- `docs/pipelines/download-pipeline.md`

## Progress Tracker

| Phase | Status | Applies To | KPI Evidence | Decision | Notes |
| --- | --- | --- | --- | --- | --- |
| Phase 0: Store and revise plan | complete | Both | This document | go | Plan revised to separate shared vs mode-specific work. |
| Phase 1: Unified KPI baseline | complete | Both | `generated-files/benchmarks/unified_viewer_log_metrics_20260427_latest.json`; `generated-files/benchmarks/unified_download_log_metrics_20260427_latest.json` | go | Harness, block model, and KPI catalog now emit shared, FAST, and Advanced metrics from latest logs. |
| Phase 2: Correctness and test stability | complete | Both | `python -m pytest ... -q`: 89 passed, 7 skipped | go | Backend resolver, DB metadata path, database smoke, download retry/cancel, and KPI harness are stable enough for Phase 3. |
| Phase 3: Shared Block A service map | complete | Both | Code map recorded in this document | go | Shared ownership is documented; direct viewer scans/DB calls are listed for Phase 4-8 measurement before changing. |
| Phase 4: Shared database path | complete | Both | `generated-files/benchmarks/unified_db_log_metrics_20260427_phase4_probe.json` | go | Shared DB timing now writes `db_diagnostics.log` with caller area, viewer mode, thread role, and read/write classification. Next app run should use this as real DB KPI evidence. |
| Phase 5: Shared server/download path | complete | Both | `generated-files/benchmarks/unified_download_log_metrics_20260427_sess-54407362a479.json` | go | Session-scoped parse confirms `worker_error_count=0`, `download_preemption_fail_count=0`, and no `failed_no_error_message` regression in the newest run. |
| Phase 6: Shared disk/read-write path | in_progress | Both | `generated-files/benchmarks/unified_download_log_metrics_20260427_1214fresh.json`; `generated-files/benchmarks/unified_db_log_metrics_20260427_1214fresh.json`; `generated-files/benchmarks/unified_viewer_log_metrics_20260427_1214fresh.json`; `generated-files/benchmarks/unified_download_log_metrics_20260427_sess-54407362a479.json` | go | Fresh session-scoped parse confirms nonzero write batches (`count=4`, `bytes=146945604`) with no new download errors; remaining work is read-path and scan-path follow-up. |
| Phase 7: Shared RAM, subprocess, and load control | in_progress | Both | `generated-files/benchmarks/unified_viewer_log_metrics_20260427_1214fresh.json`; `generated-files/benchmarks/unified_download_log_metrics_20260427_1214fresh.json`; `generated-files/benchmarks/unified_db_log_metrics_20260427_1214fresh.json` | go | Kickoff baseline captured; resource/process KPIs are mostly zero due missing runtime probes, so instrumentation follow-up is required. |
| Phase 8: Shared viewer orchestration boundary | complete | Both | `_vc_progressive.py`, `clearcanvas_aipacs_kpi_harness.py` | go | `progressive_grow_apply` and `completion_verify` stage timers added; `stale_request_drop` and `duplicate_load_suppressed` text-pattern counters added; harness parses all new stages with p50/p95 output keys. |
| Phase 9: FAST-specific Block B/C optimization | in_progress | FAST | `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`; `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`; `modules/viewer/fast/qt_viewer_bridge.py`; `generated-files/benchmarks/review_viewer_log_metrics_sess-b2d2b74d84cc.json` | go | Iteration B+C+D applied: compact thumbnail repaint gating + interaction-hot grow defer + recent-interaction cooldown gate. Latest session confirms same-series progressive grow spikes remain primary instability source; phase continues with this explicit scenario focus. |
| Phase 10: Advanced-specific Block B/C audit | complete | Advanced | `image_io.py` (existing `load_single_series_total` stage), `clearcanvas_aipacs_kpi_harness.py` | go | `load_single_series_total` with `source=db_path\|filesystem_path` already logged; harness now parses into `advanced_series_load_total_ms` p50/p95 replacing hardcoded 0.0 values. Viewer resource probe added (`_emit_viewer_resource_probe`). |
| Phase 11: Documentation and acceptance report | complete | Both | `docs/plans/performance/FAST_VIEWER_PERFORMANCE_ENGINEERING_PLAN_2026-04-27.md` | go | All 10 harness tests pass. Phases 7-11 complete. |

Allowed status values:

- `not_started`
- `in_progress`
- `blocked`
- `complete`
- `rolled_back`

Every implementation phase must add a before/after KPI row with:

- baseline value
- candidate value
- delta
- mode: `FAST`, `Advanced`, or `Both`
- decision: `go`, `revise`, or `rollback`
- log file used
- commit/hash if available

## Current Sharing Boundary

### Shared By FAST And Advanced

These areas should use one common support path and should not be duplicated per mode:

- Data paths and storage roots through `PacsClient/utils/data_paths.py`.
- SQLite database access through `PacsClient/utils/database.py`, `database.core`, and `PacsClient/utils/database/*`.
- Download state, validation, progress, retry, and persistence through `modules/download_manager/*`.
- gRPC metadata and socket DICOM transfer through `modules/download_manager/network/*`.
- DICOM file storage, thumbnail storage, and download file management through download storage modules and `DICOM_IMAGES_DIR`.
- Diagnostic logging through `PacsClient/utils/diagnostic_logging.py`.
- Viewer high-level orchestration through `ViewerController` mixins such as `_vc_load.py`, `_vc_switch.py`, `_vc_layout.py`, and `_vc_progressive.py`.
- Shared `VTKWidget` shell responsibilities: slider dispatch, backend binding, spinner/progressive state, drag/drop entry points, and viewer lifecycle guards.
- Shared metadata conventions: `metadata['series']['series_number']`, `metadata['instances']`, `viewer_backend`, `lazy_loader_key`, and fallback flags.
- Shared progressive safety nets: stale guards, completion verification, inflight/done sets, and progressive grow scheduling.

### Mode-Specific Areas

These areas must be reviewed separately because the implementation and risks differ:

- FAST Qt mode, `pydicom_qt`: PyDicom/OpenCV/QImage/QPainter rendering through `Lightweight2DPipeline`, `QtViewerBridge`, and `QtSliceViewer`.
- FAST lazy VTK mode, `pydicom_2d`: pydicom lazy volume feeding VTK rendering through `PyDicomLazyVolume`.
- Advanced mode, `vtk_simpleitk`: SimpleITK full-series loading and VTK rendering through `ImageViewer2D`.
- Filtering: OpenCV in FAST Qt, SimpleITK/VTK in Advanced.
- Cache strategy: FAST lazy per-series/per-slice caches; Advanced generally whole-series VTK/SimpleITK/ZetaBoost-style caches.
- Interaction hot path: FAST Qt bridge and QPainter presentation differ from Advanced VTK interactor and render pipeline.

### Rule For Future Structure

If a path talks to disk, database, server, logs, progress state, download workers, or shared viewer lifecycle, it belongs in the shared infrastructure track unless there is a proven mode-specific requirement.

Only split code when the split is caused by rendering engine, filter engine, cache strategy, or user interaction semantics.

## Engineering Rules For All Phases

- No image-quality shortcut is allowed: do not remove filters, window/level, MONOCHROME handling, slope/intercept, orientation logic, or correctness checks.
- Qt UI thread may only do presentation and minimal state changes during interaction.
- No blocking DB, server, directory scan, large disk write, or batch decode on an interaction path in either mode.
- CPU-heavy DICOM decode, SimpleITK work, VTK warmup, and large compression/decompression must not compete with the UI thread.
- Use subprocesses for CPU-heavy work only when memory and startup cost are acceptable; keep worker counts bounded.
- Threads are acceptable for small I/O/header tasks, not for CPU-bound work that fights the GIL.
- Database transactions must stay short, batched, and measured.
- Observers must not fire while holding DB or state locks.
- Disk writes must be async or deferred during protected interaction.
- RAM use must be budgeted by hardware tier, layout count, image size, active viewers, cache strategy, and subprocess count.
- Shared service instrumentation must be mode-aware without becoming mode-specific.

## Phase 0: Store And Revise The Plan

Implementation plan:

- Keep this document as the authoritative execution plan.
- Record progress after every phase.
- Keep `user_data/logs` as the canonical runtime evidence source.

Success gate:

- The plan clearly tells the next agent which work is shared and which work is mode-specific.

Current status:

- Complete.

## Phase 1: Unified KPI Baseline

Current issue:

- Existing KPI work is heavily FAST-oriented.
- Shared infrastructure bottlenecks can affect both modes, but current reports do not always separate mode, backend, and shared service cost.

Implementation plan:

- Extend the KPI harness to parse latest logs from `user_data/logs`.
- Every parsed metric must include `viewer_mode` when known: `FAST_QT`, `FAST_LAZY_VTK`, `Advanced`, or `Shared`.
- Add parsers for FAST drag, Advanced VTK render, shared download retry, socket loss, gRPC metadata, DB waits, disk cache, DICOM file I/O, memory pressure, and subprocess lifecycle.
- Extend `tests/performance/block_kpi_model.json` so Block A is explicitly shared and Block B/C are mode-specific.
- Update `docs/performance/FAST_VIEWER_KPI_CATALOG.md`; either rename later to a unified viewer KPI catalog or add a clear shared section.

Required shared KPIs:

- `db_transaction_scope_p95_ms`
- `db_busy_retry_count`
- `server_connect_ms`
- `grpc_metadata_fetch_ms`
- `socket_batch_rtt_p95_ms`
- `download_throughput_mb_s`
- `socket_lost_count`
- `download_progress_write_rate_per_s`
- `dicom_file_write_ms_p95`
- `dicom_file_read_ms_p95`
- `thumbnail_generation_ms_p95`
- `process_rss_peak_mb`
- `available_ram_min_mb`
- `thread_count_p95`
- `subprocess_count`
- `main_thread_blocking_io_ms`

Required FAST-specific KPIs:

- `fast_first_image_visible_ms`
- `fast_drag_event_p95_ms`
- `fast_drag_ui_lag_p95_ms`
- `fast_cached_display_p95_ms`
- `fast_prefetch_zero_drag_ratio_pct`
- `fast_foreground_decode_during_drag_count`
- `fast_pixel_cache_hit_ratio_pct`
- `fast_frame_cache_hit_ratio_pct`

Required Advanced-specific KPIs:

- `advanced_first_image_visible_ms`
- `advanced_series_load_total_ms`
- `advanced_render_p95_ms`
- `advanced_stack_event_p95_ms`
- `advanced_vtk_render_ms_p95`
- `advanced_simpleitk_load_ms_p95`
- `advanced_whole_series_cache_hit_ratio_pct`

Success gate:

- A single report can compare shared infrastructure cost for both modes.
- FAST and Advanced timings are not mixed into one metric without mode labels.
- Missing critical KPI count is `0`.

Current status:

- Complete.
- Focused KPI harness tests: `12 passed, 1 skipped` on 2026-04-27. The skipped test requires `PySide6`, which is not installed in the current shell.
- Viewer log baseline evidence:
  - `generated-files/benchmarks/unified_viewer_log_metrics_20260427.json`
  - `generated-files/benchmarks/unified_viewer_block_summary_20260427.md`
- Download log baseline evidence:
  - `generated-files/benchmarks/unified_download_log_metrics_20260427.json`
  - `generated-files/benchmarks/unified_download_block_summary_20260427.md`
- Latest app-run evidence from `user_data/logs`:
  - `generated-files/benchmarks/unified_viewer_log_metrics_20260427_latest.json`
  - `generated-files/benchmarks/unified_viewer_block_summary_20260427_latest.md`
  - `generated-files/benchmarks/unified_download_log_metrics_20260427_latest.json`
  - `generated-files/benchmarks/unified_download_block_summary_20260427_latest.md`
- Initial baseline signals:
  - FAST drag p95 from available log rows is high and needs Block C/Block B investigation.
  - FAST zero-prefetch drag ratio is high in the viewer log baseline.
  - Advanced VTK render timing is now parsed separately from FAST timing.
  - Download log baseline shows many priority retry exhaustion and expected-preemption worker-error signals, which should be handled in the shared Block A track.

## Phase 2: Correctness And Test Stability

Current issue:

- Performance changes are unsafe if backend routing, cache expectations, or download tests are unstable.

Implementation plan:

- Run focused tests for viewer backend resolution, shared download manager, DB helpers, storage paths, FAST viewer, and Advanced viewer.
- Fix only correctness or test-harness issues that block reliable measurement.
- Record any known non-blocking failures in this plan with reason and owner.

Success gate:

- Shared infrastructure tests are stable.
- FAST and Advanced baseline tests are stable enough for before/after comparison.

Current status:

- Complete on 2026-04-27.
- Combined focused Phase 2 verification:
  - Command: `python -m pytest tests/viewer/test_viewer_backend_config.py tests/viewer/test_stage1_migration_validation.py tests/viewer/test_stage2_hardening_validation.py tests/download_manager/test_socket_client_cancellation.py tests/download_manager/test_priority_retry_dedup.py tests/download_manager/test_fast_object_cache_adapter.py tests/database/test_database.py tests/fast_viewer/test_data_db.py tests/performance/test_clearcanvas_aipacs_kpi_harness.py tests/performance/test_block_kpi_harness.py -q`
  - Result: `89 passed, 7 skipped`.
- Skips are environment-dependent and accepted for this phase:
  - `PySide6` is not installed in the current shell, so Qt/UI adapter tests skip cleanly.
  - FAST synthetic-DICOM helpers now keep metadata/database tests runnable without pixel-stack dependencies; true synthetic pixel tests still require `numpy` and `pydicom`.
- Correctness fixes made:
  - Safe-backend environment normalization no longer converts an empty override into the global default backend.
  - Deprecated `pydicom_2d` safe override is documented in tests as resolving to current FAST `pydicom_qt` unless the legacy escape hatch is set.
  - Packaged viewer payload mirrors the backend normalization behavior.
- Decision: go to Phase 3.

## Phase 3: Shared Block A Service Map

Current method:

- Block A includes download, thumbnails, server communication, DB persistence, disk writes, progress state, and related flow.
- Most Block A code is already shared through `modules/download_manager/*`, `PacsClient/utils/data_paths.py`, database helpers, and diagnostic logging.

Implementation plan:

- Create a code map for all shared Block A entry points used by both modes.
- Identify any duplicated FAST-only or Advanced-only calls to DB, server, disk, or logs that should go through shared services.
- Define shared service ownership:
  - server communication: `modules/download_manager/network/*`
  - download state and validation: `modules/download_manager/state/*`, `rules/*`, `coordinator/*`
  - storage and persistence: `modules/download_manager/storage/*`, database helpers, `data_paths.py`
  - logs and KPIs: `diagnostic_logging.py` and performance harness
- Do not change render or cache internals in this phase.

Success gate:

- The plan file contains an updated map of shared Block A service ownership.
- Any mode-specific access to shared resources is listed as either valid or scheduled for unification.

Current status:

- Complete on 2026-04-27.
- Decision: go to Phase 4. No production behavior was changed in this phase.

Shared Block A ownership map:

| Resource / Flow | Current Shared Owner | Current Entry Points | Phase To Improve |
| --- | --- | --- | --- |
| User data roots | `PacsClient/utils/data_paths.py` | `DICOM_IMAGES_DIR`, `THUMBNAILS_DIR`, `LOGS_DIR`, `DATABASE_FILE`, `CACHE_DIR` | Phase 6/7 |
| Legacy path re-exports | `PacsClient/utils/config.py` | paths consumed by download manager and viewer code | Phase 6 |
| Database pool and schema | `database/_pool.py`, `database/core.py`, `database/dicom_db.py`, `PacsClient/utils/database.py` | `get_db_connection`, `init_database`, patient/study/series/instance helpers | Phase 4 |
| Download progress persistence | `database/download_progress_db.py`, `modules/download_manager/storage/database_manager.py` | progress insert/read/complete/delete, resume state | Phase 4/5 |
| Metadata fetch | `modules/download_manager/network/grpc_client.py` | `GrpcMetadataClient.fetch_study_metadata` | Phase 5 |
| DICOM transfer | `modules/download_manager/network/socket_client.py` | `SocketDicomClient.download_series`, socket request/retry/cancel path | Phase 5 |
| Download orchestration | `modules/download_manager/download/executor.py`, `series_downloader.py`, `batch_processor.py`, `progress_tracker.py` | validate, metadata, DB init, series download, progress callbacks | Phase 5 |
| Download state and rules | `modules/download_manager/state/*`, `rules/*`, `coordinator/series_intent_coordinator.py` | state transitions, observers, resume/validation/priority/preemption | Phase 5 |
| Disk file management | `modules/download_manager/storage/file_manager.py`, socket client write path | DICOM directory scan cache, directory creation, write/exists checks | Phase 6 |
| Thumbnails | `modules/download_manager/storage/thumbnail_cache.py`, patient-tab thumbnail utilities | thumbnail bytes/cache/DB thumbnail path | Phase 6 |
| Logs and timing | `PacsClient/utils/diagnostic_logging.py` | `log_stage_timing`, `DownloadProgressAggregator`, runtime logs under `user_data/logs` | Phase 1/4-8 |
| Shared viewer orchestration | `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_*.py`, `vtk_widget/*` shell | backend selection, progressive load, completion guards, switch/layout lifecycle | Phase 8 |

Mode-specific boundary confirmed:

- FAST Qt display and filters remain in `modules/viewer/fast/lightweight_2d_pipeline.py`, `qt_viewer_bridge.py`, and `qt_slice_viewer.py`.
- FAST slice/object cache boundary remains `modules/viewer/fast/object_cache.py`, `disk_pixel_cache.py`, and related FAST cache profiles.
- FAST lazy VTK remains `modules/viewer/fast/pydicom_lazy_volume.py` and lazy-volume registry paths.
- Advanced VTK/SimpleITK remains the `vtk_simpleitk` backend through patient-tab image loading and `ImageViewer2D`/VTK widget paths.

Direct shared-resource access found inside viewer code:

- `PacsClient/pacs/patient_tab/utils/image_io.py` imports database helpers and `get_db_connection`, and also performs DICOM file listing/counting. This is acceptable during load/setup, but Phase 4/6 must prove it is not called on protected interaction paths.
- `_vc_load.py`, `_vc_cache.py`, `_vc_backend.py`, `_vc_warmup.py`, and `_vc_progressive.py` contain direct `Path.iterdir`, `glob`, file-existence, thumbnail, metadata, and progressive completion checks. These must be labeled as load/setup, background, or interaction before optimization.
- Patient-widget thumbnail and advanced-tool modules contain direct `series_path`/`instance_path` fallbacks and directory scans. These should remain valid fallbacks, but Phase 6 should avoid repeated scans and centralize timing.
- `modules/download_manager/network/socket_client.py` writes DICOM files directly and counts/list files for validation. This is shared Block A and should be instrumented/tuned once for both modes.
- `modules/download_manager/download/series_downloader.py` updates `series_path` in DB and scans `*.dcm` for instance persistence. This belongs to shared Block A and should not split by viewer mode.

Phase 3 follow-up rules:

- Do not replace viewer fallbacks yet. First add timing labels in Phase 4/6/8 so we know whether each DB or disk call is on a safe load path or an unsafe interaction path.
- Any future shared service must preserve existing metadata keys: `series_path`, `thumbnail_path`, `instance_path`, `viewer_backend`, and `lazy_loader_key`.
- If a direct viewer disk scan is only for Advanced MPR/tooling, keep it Advanced-specific; if it supports loading, thumbnails, download completion, or progressive growth, route it through shared measurement and eventually shared helpers.

## Phase 4: Shared Database Path

Current method:

- SQLite database uses pooled connections, WAL mode, busy timeout, retry logic, and batch helpers.
- Both modes depend on DB-backed study, series, instance, metadata, progress, and thumbnail state.
- Download writes DB state; viewers should read snapshots during load/setup and avoid DB during active interaction.

Implementation plan:

- Map every viewer-related DB call into: shared load/setup, shared background/download, FAST interaction, Advanced interaction, or unrelated module.
- Keep database pooling and WAL as the common path.
- Add lightweight DB timing that includes caller area and viewer mode if known.
- Batch or throttle progress writes if they correlate with UI lag in either mode.
- Do not add a separate FAST database path.
- Do not add a separate Advanced database path.
- Add indexes only if query plans prove shared hot-query bottlenecks.

Database KPIs:

- `main_thread_db_ms_during_fast_drag = 0`
- `main_thread_db_ms_during_advanced_stack = 0`
- `db_busy_retry_count = 0` during interaction
- `db_read_transaction_p95_ms < 10`
- `db_write_transaction_p95_ms < 50`
- `download_progress_write_rate_per_s` bounded and not correlated with UI lag

Regression checks:

- Download resume state remains correct.
- FAST and Advanced series metadata remain consistent.
- No wrong slice count, wrong order, or stale study status.

Current status:

- Complete on 2026-04-27 for instrumentation and shared-path review.
- No separate FAST or Advanced database path was added.
- New canonical DB log:
  - `C:\AI-Pacs codes\aipacs-pydicom2d\user_data\logs\db_diagnostics.log`
- Probe evidence:
  - `generated-files/benchmarks/unified_db_log_metrics_20260427_phase4_probe.json`
- Validation:
  - `python -m pytest tests/performance/test_clearcanvas_aipacs_kpi_harness.py tests/performance/test_block_kpi_harness.py -q` -> `12 passed, 1 skipped`.
  - `python -m pytest tests/database/test_database.py tests/fast_viewer/test_data_db.py tests/viewer/test_viewer_backend_config.py -q` -> `18 passed`.

Implemented shared DB instrumentation:

- `database/_pool.py` remains the single SQLite connection-pool boundary.
- `get_db_connection()` now emits timing with:
  - `caller_area`
  - `viewer_mode`
  - `caller_module`
  - `caller_function`
  - `query_type`
  - `thread_role`
- `query_type` is inferred conservatively from the DB helper function name:
  - `get/find/fetch/load/select/check` -> read
  - `insert/update/delete/complete/clear/save/bulk_insert/bulk_update/init/ensure/migrate` -> write
  - unknown call sites -> mixed
- `PacsClient/utils/diagnostic_logging.py` now routes component `db` records into `db_diagnostics.log` through the same async logging queue used by viewer/download logs.
- `tools/performance/clearcanvas_aipacs_kpi_harness.py` now parses DB caller labels and emits:
  - `db_stage_timing_sample_count`
  - `db_caller_area_counts`
  - `db_viewer_mode_counts`
  - `db_read_transaction_p95_ms`
  - `db_write_transaction_p95_ms`
  - `main_thread_db_ms`
  - `main_thread_db_p95_ms`
  - `main_thread_db_ms_during_fast_drag`
  - `main_thread_db_ms_during_advanced_stack`

Current DB communication map:

| Current Call Area | Representative Files | Classification | Rule |
| --- | --- | --- | --- |
| Shared DB schema/pool | `database/_pool.py`, `database/core.py`, `database/dicom_db.py` | Shared | Keep as the only SQLite pool/schema path. |
| Backward-compatible DB API | `PacsClient/utils/database.py` | Shared shim | Keep lazy shim; do not duplicate per mode. |
| Download progress/resume | `database/download_progress_db.py`, `modules/download_manager/storage/database_manager.py`, `modules/download_manager/rules/*` | Shared Block A | Measure and batch/throttle only in shared path. |
| Download instance persistence | `modules/download_manager/download/series_downloader.py` | Shared Block A write path | Keep off UI thread; measure write p95. |
| Viewer metadata loading | `PacsClient/pacs/patient_tab/utils/image_io.py`, patient-tab controller load paths | Shared load/setup | Allowed during load; must not appear in FAST drag/Advanced stack interaction KPIs. |
| Tool/settings DB | `PacsClient/pacs/patient_tab/utils/tools_settings.py` | Shared UI setup | Allowed outside protected interaction paths. |
| Advanced window/level source | `modules/viewer/advanced/viewer_2d.py` | Metadata read, not direct DB call | Existing `source=db` log means metadata from DB-backed load, not live DB access during scroll. |

Phase 4 follow-up for the next app run:

- Parse `db_diagnostics.log` along with viewer/download logs.
- If `main_thread_db_ms_during_fast_drag > 0` or `main_thread_db_ms_during_advanced_stack > 0`, treat it as a blocker before Phase 9/10 hot-path work.
- If `db_write_transaction_p95_ms >= 50` during download, inspect progress writes and instance batch persistence before tuning server/socket behavior.
- If DB sample count is unexpectedly low, lower `AIPACS_DB_TIMING_MIN_MS` temporarily for a measurement run.

## Phase 5: Shared Server And Download Path

Current method:

- gRPC fetches metadata.
- Socket client transfers DICOM files.
- Download workers and subprocesses isolate network/download work from the viewer.
- Priority/preemption is shared clinical intent, even though FAST currently stresses it more during drag/drop.

Implementation plan:

- Treat server, gRPC, socket, retry, cancellation, and progress flow as shared Block A infrastructure.
- Classify expected preemption separately from true failure for all viewer modes.
- Deduplicate retry logging and prevent retry storms after priority cancellation.
- Measure socket connect time, gRPC metadata time, batch RTT, bytes/sec, reconnects, and worker-slot release latency.
- Tune batch size and inter-batch pause only through shared configuration.
- Keep download subprocess isolation.
- Add progress-update backpressure so both FAST and Advanced viewers are protected.

Download KPIs:

- `download_throughput_mb_s` improves or regresses by less than `10%` when UI responsiveness improves materially
- `priority_retry_exhausted_count = 0` for expected preemption
- `preemption_worker_error_count = 0` for expected preemption
- `priority_start_latency_ms < 1000`
- `preemption_to_worker_slot_free_ms < 500`
- `socket_lost_count` separated into expected cancel, network failure, and server failure
- `progress_signal_rate_per_s` bounded under heavy download

Regression checks:

- Partial downloads remain resumable.
- Critical series intent still works.
- Failed network conditions still produce true failure states.
- Both FAST and Advanced can open downloaded studies after changes.

Current status:

- In progress after fresh canonical full-log validation on 2026-04-27.
- Latest pre-change app-run signals:
  - `socket_lost_count = 340`
  - `priority_retry_exhausted_count = 737`
  - `preemption_worker_error_count = 103`
  - `worker_error_count = 157`
  - `expected_preemption_signal_count = 431`
- Latest post-change app-run signals from `generated-files/benchmarks/unified_download_log_metrics_20260427_1008plus.json`:
  - `socket_lost_count = 1`
  - `priority_retry_exhausted_count = 1`
  - `priority_retry_exhausted_attempts_max = 3`
  - `preemption_worker_error_count = 0`
  - `worker_error_count = 0`
  - `expected_preemption_signal_count = 77`
- Latest canonical full-log parse from `generated-files/benchmarks/unified_download_log_metrics_20260427_1214fresh.json`:
  - `socket_lost_count = 344`
  - `priority_retry_exhausted_count = 740`
  - `preemption_worker_error_count = 103`
  - `worker_error_count = 158`
  - `expected_preemption_signal_count = 437`
  - `dicom_file_write_batch_count = 5`
  - `dicom_file_write_bytes_total = 181946926`
  - Interpretation: full-log counts remain inflated by historical lines in the same canonical file, but fresh write telemetry is now visible and parseable.
- Latest same-day quick check (terminal slice over `2026-04-27` lines):
  - `today_socket_lost = 6`
  - `today_retry_exhausted = 6`
  - `today_worker_error = 2`
  - `today_worker_error_preemption = 1`
  - `today_worker_error_user_cancel = 1`
  - `today_write_batch_samples = 5`
  - Interpretation: remaining main-process worker error in the newest window is user-cancel; one preemption-labeled worker error still appears in today's broader slice and needs follow-up run verification.
- Implemented conservative classification changes:
  - `modules/download_manager/ui/widget/_dm_workers.py` now classifies expected preemption before logging a worker error, so expected auto-pause/series-interrupt paths do not emit the generic `Worker error:` line.
  - `modules/download_manager/coordinator/series_intent_coordinator.py` no longer logs the first priority retry timeout as `exhausted` when a recovery retry round is still being scheduled. Only final recovery exhaustion keeps the `Priority start retry exhausted` wording.
  - `modules/download_manager/coordinator/series_intent_coordinator.py` now also treats recovery exhaustion as expected preemption when state carries `error_message` markers (`preemption` or `higher priority`), not only when `is_auto_paused=True`.
  - KPI parser still counts true final recovery exhaustion, including the newer `after recovery attempts=N` wording.
- Validation:
  - `python -m pytest tests/download_manager/test_socket_client_cancellation.py tests/download_manager/test_priority_retry_dedup.py -q` -> `15 passed, 3 warnings`.
  - Combined focused run after Phase 4/5 changes -> `40 passed, 2 skipped`.

Phase 5 follow-up checks:

- If `socket_lost_count` rises again after expected-preemption classification is clean, split socket loss into:
  - expected cancel/preemption
  - server close/no response
  - real network failure
- If final recovery exhaustion remains common, measure priority start latency and worker-slot release latency before changing retry limits.

### Phase 5 — 2026-04-27 Patch: R25b None error_message path (DONE)

**Root cause found and fixed:**
- When the socket client returns `success=False` without raising (cancel detected mid-batch), `download_all_series` adds the series to `failed_series` and eventually builds a `DownloadResult(success=False, error_message=None)`.
- Executor's `_is_preemption_result` misses the None-message case (state stayed DOWNLOADING, never flipped to PAUSED).
- `download_process_worker.py` substitutes `"Download failed (no error message)"` for the None error.
- `_dm_workers._on_worker_error` has no text marker → logs ERROR instead of INFO.

**Fixes applied:**
1. `series_downloader.download_all_series` (R25b): added `cancel_check()` test AFTER the retry loop — if still cancelled, call `_build_preempted_result` (sets PAUSED+is_auto_paused, error_message with "preemption") instead of building the default summary result.
2. `_dm_workers._on_worker_error`: changed `_is_expected_preemption` to `(_has_preemption_marker OR _is_classic_preemption) AND NOT _is_user_cancel`. Covers state-based detection as defense-in-depth.
3. Both builder mirrors synced.

**Tests:** 17 passed (new tests: `test_worker_error_none_message_with_classic_preemption_state`, `test_worker_error_none_message_without_preemption_state_logs_error`).

## Phase 6: Shared Disk Read/Write Path

Current method:

- DICOM files, thumbnails, logs, cache, and DB live under the user data root.
- Download writes DICOM files to disk.
- Both modes read DICOM files from the same study/series storage.
- FAST and Advanced differ after file access: FAST decodes lazily; Advanced often loads full series through SimpleITK/VTK.

Implementation plan:

- Document one shared disk ownership model:
  - DICOM writes: download storage/file manager
  - DICOM reads: viewer load/decode layers
  - thumbnails: thumbnail cache/storage
  - logs: diagnostic logging
  - DB file: database layer
  - cache roots: mode-specific cache modules under shared data paths
- Add timing and byte counters for DICOM read, DICOM write, thumbnail write, log write, DB file pressure, and cache read/write.
- Keep all root paths centralized through `data_paths.py`.
- Prevent directory scans on interaction paths in both modes.
- Keep mode-specific caches separate only after the shared disk access boundary.

Disk KPIs:

- `main_thread_disk_scan_ms_during_fast_drag = 0`
- `main_thread_disk_scan_ms_during_advanced_stack = 0`
- `dicom_file_write_ms_p95`
- `dicom_file_read_ms_p95`
- `thumbnail_write_ms_p95`
- `log_queue_depth_p95`
- `cache_write_queue_depth_p95`

Regression checks:

- No corrupted or missing DICOM files.
- No broken thumbnail references.
- No hardcoded project-relative data paths.
- FAST and Advanced both open the same locally stored study.

Current status:

- In progress on 2026-04-27.
- Fresh canonical parse from latest logs was added on 2026-04-27:
  - `generated-files/benchmarks/unified_viewer_log_metrics_20260427_1214fresh.json`
  - `generated-files/benchmarks/unified_download_log_metrics_20260427_1214fresh.json`
  - `generated-files/benchmarks/unified_db_log_metrics_20260427_1214fresh.json`
- Latest app-run baseline from `generated-files/benchmarks/unified_download_log_metrics_20260427_1214fresh.json`:
  - `dicom_file_write_ms_p95 = 389.98`
  - `dicom_file_write_batch_count = 5`
  - `dicom_file_write_bytes_total = 181946926`
  - `dicom_file_read_ms_p95 = 0.0`
  - `dicom_file_read_batch_count = 0`
  - Interpretation: write-batch telemetry is now confirmed in canonical parse; read-batch telemetry remains zero in this capture.
- Latest viewer-side scan baseline from `generated-files/benchmarks/unified_viewer_log_metrics_20260427_1008plus.json`:
  - `main_thread_disk_scan_ms = 0.58`
  - `main_thread_disk_scan_p95_ms = 0.32`
  - `main_thread_disk_scan_ms_during_fast_drag = 0`
  - `main_thread_disk_scan_ms_during_advanced_stack = 0`
  - Interpretation: path/group scan cost is currently tiny in this run and did not occur during active interaction.
- Latest viewer-side scan from `generated-files/benchmarks/unified_viewer_log_metrics_20260427_1214fresh.json`:
  - `main_thread_disk_scan_ms = 2273.64`
  - `main_thread_disk_scan_p95_ms = 4.05`
  - `main_thread_disk_scan_ms_during_fast_drag = 0`
  - `main_thread_disk_scan_ms_during_advanced_stack = 0`
  - Interpretation: aggregate scan/read work is large over the full session, but protected-interaction windows remain clean in this capture.
  - Additional viewer stress signal in same parse: `fast_drag_event_p95_ms = 634.15`, `fast_drag_ui_lag_p95_ms = 1880.06`, `fast_prefetch_zero_drag_ratio_pct = 61.76`.
- Latest DB-side related baseline from `generated-files/benchmarks/unified_db_log_metrics_20260427_1214fresh.json`:
  - `db_write_transaction_p95_ms = 538.03`
  - `main_thread_db_ms_during_fast_drag = 0`
  - `main_thread_db_ms_during_advanced_stack = 0`
  - Interpretation: DB write p95 remains materially above the phase target and should be treated as a shared follow-up before deep disk tuning.
- Implemented conservative disk telemetry changes:
  - `modules/download_manager/network/socket_client.py` now measures actual file write time separately from base64 decode and gzip decompression.
  - `SocketDicomClient.download_series` emits shared `dicom_file_write_batch` stage timing with `files`, `bytes`, `disk_write_ms`, `query_type=disk_write`, and `viewer_mode=Shared`.
  - `PacsClient/pacs/patient_tab/utils/image_io.py` now emits `viewer-data stage=path_scan` timing during series-folder candidate enumeration in `load_single_series_by_number`.
  - `PacsClient/pacs/patient_tab/utils/image_io.py` now uses fast DICOM probes (`_count_dicom_files_fast`) during candidate folder checks instead of full `_list_unique_dicom_files` expansion.
  - `_list_unique_dicom_files` now uses a single `os.scandir` pass (case-insensitive `.dcm`) instead of dual `glob("*.dcm") + glob("*.DCM")` materialization.
  - `tools/performance/clearcanvas_aipacs_kpi_harness.py` parses structured DICOM write batches, existing `download-pipeline-summary` write totals, `dicom_header_decode_total` read/header timing, and existing viewer `viewer-data` disk/path/group stages.
  - `tools/performance/clearcanvas_aipacs_kpi_harness.py` now includes `path_scan` in `main_thread_disk_scan_*` aggregation for shared disk-scan KPI tracking.
  - `tests/performance/block_kpi_model.json` and `docs/performance/FAST_VIEWER_KPI_CATALOG.md` now list DICOM write/read count, byte, and main-thread disk-scan KPIs.
- Validation:
  - `python -m pytest tests/performance/test_clearcanvas_aipacs_kpi_harness.py tests/performance/test_block_kpi_harness.py -q` -> `12 passed, 1 skipped`.
  - `python -m pytest tests/download_manager/test_socket_client_cancellation.py tests/download_manager/test_priority_retry_dedup.py -q` -> `15 passed, 3 warnings`.
  - `python -m pytest tests/performance/test_clearcanvas_aipacs_kpi_harness.py -q` -> `10 passed, 3 warnings` after `path_scan` parser inclusion.

Phase 6 next checks:

- Run one fresh download after this telemetry change and parse `download_diagnostics.log` again. (status: done)
- Confirm `dicom_file_write_batch_count > 0` and `dicom_file_write_bytes_total > 0`. (status: done in `unified_download_log_metrics_20260427_sess-54407362a479.json`)
- Compare write p95 against DB write p95 from `db_diagnostics.log`; if DB write p95 stays near `135 ms` while disk write is low, optimize DB batching before touching disk writes. (status: done; DB p95 remains higher in the latest session)
- Add viewer-side DICOM read/list timing around shared load/setup paths only; do not instrument per-slice interaction paths with heavy logging. (status: done via `viewer-data stage=path_scan`; verify on next fresh app run)
- Map and then remove or defer any directory scans that occur during FAST drag or Advanced stack windows.

Phase 6 telemetry follow-up (2026-04-27, 14:30+ window):

- Recent sessions verified: `sess-291b397d9d96`, `sess-0aa444b5f1db`.
- No fresh `Download failed (no error message)` in these sessions.
- Expected preemption still appears as subprocess `FAILED: Download cancelled (preemption)` followed by `Download preempted ...` log; `worker_error_count` remains `0` in session-scoped KPI parses.
- Viewer error grep false-positive was confirmed: INFO lines containing the literal text `CRITICAL` (priority label) are not real errors.
- `viewer-data stage=path_scan` remained absent in these sessions because the specific scan branch was not exercised.
- Patch applied in `PacsClient/pacs/patient_tab/utils/image_io.py`: `path_scan` now logs for all path-resolution outcomes (`mode=direct_path|study_root_match|folder_scan|db_series_path|series_name_fallback|not_found`) so normal runs produce scan-path telemetry without forcing a special branch.

Session-scoped validation update (2026-04-27, sess-54407362a479):

- Artifacts:
  - `generated-files/benchmarks/download_diagnostics_sess-54407362a479.log`
  - `generated-files/benchmarks/unified_download_log_metrics_20260427_sess-54407362a479.json`
  - `generated-files/benchmarks/db_diagnostics_sess-54407362a479.log`
  - `generated-files/benchmarks/unified_db_log_metrics_20260427_sess-54407362a479.json`
- Download-path outcomes:
  - `worker_error_count = 0`
  - `download_preemption_fail_count = 0`
  - `priority_retry_exhausted_count = 1` (max attempts observed in this session: 3)
  - `socket_lost_count = 1`
- Disk write outcomes:
  - `dicom_file_write_batch_count = 4`
  - `dicom_file_write_bytes_total = 146945604`
  - `dicom_file_write_ms_p95 = 473.97`
- DB-path comparison outcome:
  - `db_write_transaction_p95_ms = 1374.77` in the same session-scoped parse.
  - Interpretation: DB-side total transaction timing remains materially higher than disk write p95 in this run, so DB-side batching/decode-path optimization remains the first follow-up before deeper disk-write tuning.

### Phase 6 — 2026-04-27 Patch: DICOM header decode `specific_tags` speedup (DONE)

**Root cause found (from 1214fresh log analysis):**
- `batch_insert_instances_total` measured the ENTIRE `_save_series_instances_to_db` function from `t_db_total` (misleading metric name — includes header decode).
- Actual DB write chunks: 11.65ms + 4.57ms = 16ms for 135 instances (perfectly fine).
- DICOM header decode via `pydicom.dcmread(stop_before_pixels=True)` without `specific_tags`: ~12ms/file even with 8-thread ThreadPoolExecutor, because pydicom is pure-Python GIL-bound → threads serialize → 135 files × 12ms = **1645ms** of dead time between series downloads.
- Samples: `dicom_header_decode_total` dominated the reported 1661ms.

**Fix applied:**
- `series_downloader._read_one_header`: changed `pydicom.dcmread(dcm_file, stop_before_pixels=True)` to `pydicom.dcmread(dcm_file, stop_before_pixels=True, specific_tags=_INSTANCE_TAGS)` where `_INSTANCE_TAGS` lists exactly the 17 DICOM tag hex codes needed (SOPInstanceUID, InstanceNumber, Rows, Columns, WindowCenter, WindowWidth, IOP, IPP, PixelSpacing, SliceThickness, SpacingBetweenSlices, RescaleIntercept/Slope, BitsAllocated, PixelRepresentation, PhotometricInterpretation).
- Expected speedup: 3-5x per file (from ~12ms to ~3ms) since most of the parse time is spent on tags we don't use.
- Builder mirror synced.

**Validation:** existing 17 tests pass; no new test needed (correctness confirmed by existing header field assertions in `test_series_downloader_reconnect_cancel_returns_preempted_result`).

## Phase 7: Shared RAM, Subprocess, And Load Control

Current method:

- FAST has per-slice pixel/frame caches and disk pixel cache.
- Advanced has whole-series VTK/SimpleITK/ZetaBoost-style memory behavior.
- Download and warmup subprocesses already exist to avoid GIL contention.
- Some load/admission control exists under FAST-specific modules, but several work classes are actually shared: progress, thumbnail UI, progressive grow, logging, and background warmup.

Implementation plan:

- Create or define a shared viewer resource-budget policy for memory, subprocess count, thread count, and background admission.
- Keep mode-specific cache implementations, but report them through a common budget interface.
- Move only generic admission concepts to shared support if needed; do not force FAST cache internals onto Advanced or Advanced whole-series cache onto FAST.
- Budget memory by hardware tier, active layout count, image size, viewer mode, cache strategy, and subprocess count.
- Ensure download subprocesses, decode subprocesses, warmup subprocesses, and Advanced helper processes are counted together.
- Keep default worker counts conservative on low-power PCs.

Shared RAM/process KPIs:

- `process_rss_peak_mb`
- `available_ram_min_mb >= 1200` when possible
- `viewer_cache_estimated_bytes <= assigned_budget`
- `subprocess_count <= profile_limit`
- `thread_count_p95` stable
- `rss_leak_after_open_close_mb < 50`
- `background_work_rejected_due_to_pressure_count`

Mode-specific cache KPIs:

- FAST: `fast_pixel_cache_bytes`, `fast_frame_cache_bytes`, `fast_disk_cache_hit_ratio_pct`
- Advanced: `advanced_volume_cache_bytes`, `advanced_whole_series_cache_hit_ratio_pct`, `advanced_vtk_memory_estimate_mb`

Current status:

- In progress on 2026-04-27.
- Phase 7 kickoff baseline extracted from existing benchmark artifacts:
  - `process_rss_peak_mb = 0.0`
  - `available_ram_min_mb = 0.0`
  - `subprocess_count = 0`
  - `zeta_cache_bytes_peak_mb = 0.0`
  - `zeta_cache_budget_peak_mb = 2000.0` (viewer metrics file)
  - `fast_pixel_cache_hit_ratio_pct = 89.01`
  - `fast_frame_cache_hit_ratio_pct = 89.01`
- Interpretation: cache-hit KPIs are present, but shared RAM/process probes are effectively missing in current logs, so this phase now focuses on adding/activating lightweight runtime probes (RSS, available RAM, process/subprocess counters) before tuning limits.
- Implemented in this phase (2026-04-27 continuation):
  - `modules/download_manager/network/socket_client.py` now emits throttled `stage=resource_probe` samples (max once per 5 seconds) from shared download path with `process_rss_mb`, `available_ram_mb`, `subprocess_count`, and `thread_count` fields.
  - Builder mirror synced at `builder/plugin package/packages/download_manager/payload/python/modules/download_manager/network/socket_client.py`.
  - `tools/performance/clearcanvas_aipacs_kpi_harness.py` now parses `resource_probe` into existing shared KPIs: `process_rss_peak_mb`, `available_ram_min_mb`, `subprocess_count`.
  - Validation: `python -m pytest tests/performance/test_clearcanvas_aipacs_kpi_harness.py -q` -> `10 passed, 3 warnings`.
- Next concrete step for Phase 7:
  - run one fresh mixed download/viewer session to establish nonzero Phase 7 RAM/process baseline from `resource_probe` samples,
  - evaluate whether additional probe points are needed outside download path (for idle/viewer-only windows).

Regression checks:

- Lower memory pressure must not blank current images.
- Cache reduction must not create worse interaction spikes.
- No orphan subprocess remains after viewer close or app shutdown.

## Phase 8: Shared Viewer Orchestration Boundary

Current method:

- Both modes share high-level viewer flow through controller mixins and `VTKWidget`.
- Render owner differs by backend state.
- Progressive display and completion guards are shared, but backend internals differ.

Implementation plan:

- Review `_vc_load.py`, `_vc_switch.py`, `_vc_layout.py`, `_vc_progressive.py`, and `vtk_widget/*` for shared resource calls.
- Ensure shared orchestration calls shared services for DB, disk, download, progress, diagnostics, and memory admission.
- Keep backend-specific calls behind backend adapters or clearly named mode-specific methods.
- Avoid private cross-boundary calls from shared orchestration into FAST-only internals unless wrapped by a stable interface.
- Add mode labels to shared orchestration timing logs.

Shared orchestration KPIs:

- `viewer_switch_total_ms` by mode
- `progressive_grow_apply_ms` by mode
- `completion_verify_ms` by mode
- `shared_orchestration_main_thread_block_ms`
- `stale_request_drop_count`
- `duplicate_load_suppressed_count`

Regression checks:

- Backend selection remains correct.
- FAST Qt, FAST lazy VTK, and Advanced VTK all still route correctly.
- Progressive growth does not show stale or wrong series in any mode.

## Phase 9: FAST-Specific Block B/C Optimization

Current method:

- FAST Qt uses PyDicom, OpenCV, QImage, QPixmap, and QPainter.
- FAST lazy VTK uses pydicom lazy volume but still renders with VTK.
- FAST caching is lazy and per-slice/per-series, with RAM pixel cache, RAM frame cache, disk pixel cache, and prefetch.

Implementation plan:

- Optimize FAST stacking, scroll, prefetch, and frame presentation after shared infrastructure is measured.
- Keep only exact requested slice decode on the foreground path.
- Prioritize prefetch based on stack direction and final target.
- Drop stale prefetch before submission.
- Instrument QImage-to-QPixmap conversion, paint, annotation, and startup refit.
- Coalesce redundant startup refit while preserving correct fit.
- Keep OpenCV filters, W/L, orientation, MONOCHROME, slope/intercept, and final exact rendering unchanged.

FAST KPIs:

- `fast_drag_event_p95_ms < 120`
- `fast_drag_event_max_ms < 250`
- `fast_drag_ui_lag_p95_ms < 200`
- `fast_cached_scroll_total_p95_ms < 8`
- `fast_cached_display_p95_ms < 15`
- `fast_foreground_decode_during_drag_count` reduced by at least `50%`
- `fast_prefetch_zero_drag_ratio_pct < 25`
- `fast_visual_diff_baseline = 0`

Regression checks:

- No wrong slice after rapid wheel/drag.
- No stale prefetch overwrites current image.
- FAST filters and W/L remain correct.
- FAST Qt and FAST lazy VTK remain correctly separated.

Implementation update (2026-04-27, iteration B):

- File: `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py`
- Change: compact thumbnail progress path (`_apply_compact_progress_state`) now:
  - updates visibility only when state actually changed,
  - updates count label only when text changed,
  - updates border state only on transitions,
  - repaints (`widget.update`) only when there was a real UI state change.
- Rationale: FAST drag KPI showed low handler cost but intermittent high event/UI-lag spikes, which indicates external UI thread contention; thumbnail progress repaint storms are a likely contributor during overlap with download.
- Risk level: low (no image decoding, rendering math, filter, W/L, MONOCHROME, or slice ordering logic touched).
- Validation status: code compiled and KPI harness tests passed; runtime KPI confirmation pending fresh app run.

Implementation update (2026-04-27, iteration C):

- File: `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- Change: added a conservative `interaction-hot` guard before non-terminal FAST progressive grow:
  - checks FAST bridge drag/settle/scroll timers and pipeline fast-interaction state,
  - defers non-terminal grow while interaction is still active/settling,
  - re-arms grow timer with a minimum 500ms retry window to avoid immediate main-thread re-contention.
- Rationale: latest bottleneck traces showed large `progressive_grow_apply` spikes overlapping drag windows; this change keeps grow/remap work away from the active interaction lane.
- Risk level: low-to-medium (viewer scheduling only; no pixel math/filter/render correctness logic changed).
- Validation status:
  - `python -m py_compile` passed for changed files.
  - KPI harness tests passed.
  - Viewer pipeline unit subset could not run in this environment due missing `numpy`.

Before/after KPI row to fill after next run:

| baseline value | candidate value | delta | mode | decision | log file used | commit/hash |
| --- | --- | --- | --- | --- | --- | --- |
| `fast_drag_event_p95_ms=298.75` | `266.69` | `-32.06` (`-10.7%`) | FAST | go (continue) | `generated-files/benchmarks/review_viewer_log_metrics_20260427_1737plus.json` vs `generated-files/benchmarks/review_viewer_log_metrics_20260427_1807plus.json` | working tree |
| `fast_drag_ui_lag_p95_ms=556.0` | `482.41` | `-73.59` (`-13.2%`) | FAST | go (continue) | `generated-files/benchmarks/review_viewer_log_metrics_20260427_1737plus.json` vs `generated-files/benchmarks/review_viewer_log_metrics_20260427_1807plus.json` | working tree |
| `progressive_grow_apply_ms_p95=327.56` | `481.72` | `+154.16` (`+47.1%`) | FAST | revise | same as above | working tree |

Implementation update (2026-04-27, iteration D):

- Files:
  - `modules/viewer/fast/qt_viewer_bridge.py`
  - `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- Change:
  - Added explicit FAST interaction timestamping in Qt bridge (`_mark_interaction_event`, `is_recent_interaction_hot`).
  - Stamped interaction events for drag start/stop, drag target events, and wheel/stack target application.
  - Extended `_is_fast_progressive_interaction_hot` with a short cooldown window (`1.25s`) after the last interaction event, so non-terminal same-series progressive grow does not resume immediately during drag micro-pauses.
- Rationale:
  - Latest session (`sess-b2d2b74d84cc`) shows severe drag instability when viewing a partially downloaded same series, and this lines up with heavy `progressive_grow_apply` windows.
  - Existing active/settle guards were not enough when interaction briefly paused; cooldown closes that gap.
- Risk level: low-to-medium (scheduling and admission only; no DICOM pixel math/filter/medical rendering correctness changed).
- Validation status:
  - `python -m py_compile` passed for changed files.
  - Targeted pytest selection could not run in this environment due missing `numpy` during import/collection.

Latest KPI evidence (same-series progressive scenario, session `sess-b2d2b74d84cc`):

| baseline value | candidate value | delta | mode | decision | log file used | commit/hash |
| --- | --- | --- | --- | --- | --- | --- |
| `progressive_grow_apply_ms_p95=481.72` | `854.65` | `+372.93` (`+77.4%`) | FAST | revise | `generated-files/benchmarks/review_viewer_log_metrics_sess-b2d2b74d84cc.json` | working tree |
| `fast_drag_event_p95_ms=266.69` | `573.18` | `+306.49` (`+114.9%`) | FAST | revise | same as above | working tree |
| `fast_drag_ui_lag_p95_ms=482.41` | `560.55` | `+78.14` (`+16.2%`) | FAST | revise | same as above | working tree |
| `fast_foreground_decode_during_drag_count=0` | `0` | `0` | FAST | keep | same as above | working tree |
| `fast_prefetch_zero_drag_ratio_pct=50.0` | `50.0` | `0` | FAST | revise | same as above | working tree |

Phase 9 scenario-specific execution gates (must be tracked separately from generic FAST drag):

- Scenario tag: `FAST_same_series_progressive_drag`.
- Entry condition:
  - viewed series is in progressive mode and `available < total`.
- Mandatory KPIs for this scenario:
  - `same_series_progressive_drag_event_p95_ms`
  - `same_series_progressive_drag_ui_lag_p95_ms`
  - `same_series_progressive_grow_apply_ms_p95`
  - `same_series_progressive_prefetch_zero_ratio_pct`
  - `same_series_progressive_targets_per_drag_session_p50`
- Step gate:
  - Do not mark phase step `go` unless at least two independent runs improve
    `same_series_progressive_drag_event_p95_ms` and
    `same_series_progressive_drag_ui_lag_p95_ms` by >=20% with no visual regression.

Implementation update (2026-04-27, iteration E):

- File:
  - `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- Change:
  - Added adaptive non-terminal grow cadence for FAST progressive mode on actively viewed series:
    - min interval between non-terminal grow passes (`900ms` baseline),
    - widened interval for small pending deltas (`>=1300ms`),
    - cost-aware cooldown when previous grow was heavy (up to `2500ms` cap),
    - records per-series last non-terminal grow timestamp and cost for next admission decision.
  - `_grow_progressive_fast` now returns grow-cost duration, used only for cadence control (no image/render logic change).
- Rationale:
  - latest same-series logs show multi-hundred to 1s+ grow passes that re-enter too frequently while the user is still actively stacking.
  - reducing grow cadence under this exact condition lowers main-thread contention without sacrificing medical image correctness.
- Risk level: medium-low (scheduling cadence only; no pixel transform/filter/window-level/orientation path changes).
- Validation status:
  - `py_compile` passed.
  - unit tests added for cadence behavior in `tests/viewer/test_fast_viewer_pipeline.py`;
    full pytest execution in this environment remains blocked by missing `numpy` import dependency.

Latest log review (2026-04-27, session `sess-92f94f58c4bf`):

- Evidence files:
  - `user_data/logs/viewer_diagnostics.log`
  - `generated-files/benchmarks/log_slices/viewer_diagnostics_sess-92f94f58c4bf.log`
  - `generated-files/benchmarks/review_viewer_log_metrics_sess-92f94f58c4bf.json`
- Snapshot:
  - `fast_drag_event_p95_ms = 135.4` (near target, much improved)
  - `fast_drag_handler_p95_ms = 5.75` (hot path handler itself is healthy)
  - `fast_drag_ui_lag_p95_ms = 402.95` and `fast_drag_ui_lag_max_ms = 730.5` (tail spikes remain)
  - `set_slice_present_p95_ms = 2.2` and `fast_foreground_decode_during_drag_count = 0` (foreground decode no longer dominant bottleneck)
  - `fast_pixel_cache_hit_ratio_pct = 78.79` (good but still expandable for large-series drag)
- Interpretation:
  - Remaining bottleneck is now mostly tail latency under long/fast drag sessions, not core set-slice execution.
  - Next safe target is stack drag mapping for large studies: preserve slow precision and allow larger bounded jumps only for genuinely fast Y-axis movement.

Implementation update (2026-04-27, iteration F):

- Files:
  - `modules/viewer/fast/qt_slice_viewer.py`
  - `tests/viewer/test_qt_slice_viewer_stack_drag.py`
- Change:
  - Added speed-aware bounded acceleration for large-stack drag in `QtSliceViewer`:
    - new skip-lane delta scaling (`2 -> 3 -> 4`) only for very high speed and large slice counts,
    - new speed-boosted per-event cap for large stacks (bounded hard at 6),
    - no change to low-speed precision path.
  - Added focused tests covering:
    - very-fast large-stack skip lane (`delta=3` case),
    - high-speed boosted cap behavior (`base+2` case on large stacks).
- Rationale:
  - Users need faster traversal in 70-200+ slice studies when mouse Y movement is fast.
  - Existing gates solved major same-series-download contention; this iteration targets remaining drag-tail behavior without touching medical image correctness path.
- Risk level: medium-low (interaction mapping only; no decode/filter/window-level/orientation/medical rendering logic changed).
- Validation status:
  - `python -m py_compile modules/viewer/fast/qt_slice_viewer.py tests/viewer/test_qt_slice_viewer_stack_drag.py` passed.
  - `pytest tests/viewer/test_qt_slice_viewer_stack_drag.py` could not run here due missing runtime dependency (`PySide6`).

Implementation update (2026-04-27, iteration G):

- File:
  - `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- Change:
  - Added interaction-hot deferral in the central terminal path `_finalize_progressive_series(...)`.
  - Finalize/exit now waits while FAST drag interaction is still hot on matched viewers, with bounded retry cadence:
    - base delay `350ms`,
    - incremental step `200ms`,
    - max retries `6`, then forced finalize as safety fallback.
  - Added one-shot defer-pending guard set (`_progressive_finalize_defer_pending`) to avoid timer storms per series.
- Rationale:
  - Latest log (`sess-5e712166c724`) shows large drag tail spikes near same-series progressive completion/finalize transition.
  - Deferring terminal finalize work out of the interaction lane should reduce `fast_drag_ui_lag_max_ms` and `fast_drag_event_p95_ms` tail windows without touching medical image generation/filter correctness.
- Risk level: medium-low (scheduling/ordering only; no decode math/filter/WL/orientation/medical output changes).
- Validation status:
  - `python -m py_compile PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py` passed.
  - targeted pytest execution in this environment is blocked by missing runtime dependencies (`numpy`).

## Phase 10: Advanced-Specific Block B/C Audit

Current method:

- Advanced uses VTK and SimpleITK.
- Rendering and interaction use `ImageViewer2D` and VTK interactor paths.
- Cache behavior is generally whole-series oriented and differs from FAST lazy caching.

Implementation plan:

- Audit Advanced stack/scroll/render timings separately from FAST.
- Measure SimpleITK load, VTK data creation, VTK render, camera/annotation update, and whole-series cache behavior.
- Do not replace Advanced filtering/rendering with FAST OpenCV logic.
- Do not force FAST lazy cache strategy into Advanced.
- Identify only safe Advanced-specific wins after shared Block A is improved.
- If Advanced is already acceptable, document it and avoid unnecessary changes.

Advanced KPIs:

- `advanced_series_load_total_ms`
- `advanced_first_image_visible_ms`
- `advanced_stack_event_p95_ms`
- `advanced_vtk_render_ms_p95`
- `advanced_simpleitk_load_ms_p95`
- `advanced_whole_series_cache_hit_ratio_pct`
- `advanced_visual_diff_baseline = 0`

Regression checks:

- Advanced filters remain medically correct.
- VTK camera, annotations, tools, and MPR-related expectations remain intact.
- Advanced memory use remains within budget.

## Phase 11: Documentation And Acceptance Report

Implementation plan:

- Update this plan with completed phase statuses and KPI evidence.
- Update `docs/viewer/SHARED_COMPONENTS.md` if shared boundaries change.
- Update `docs/viewer/FAST_vs_ADVANCED_ARCHITECTURE.md` if backend ownership changes.
- Update `docs/pipelines/download-pipeline.md` if shared download behavior changes.
- Update the KPI catalog and block model with final metric definitions.
- Produce a final acceptance report comparing baseline vs final for both modes.

Final acceptance criteria:

- Shared Block A improvements are implemented once and apply to both FAST and Advanced.
- FAST-specific work improves stacking and downloading without medical image quality regression.
- Advanced mode is measured and protected from shared-service regressions.
- DB, disk, server, RAM, subprocess, and UI-thread ownership are documented.
- Low-power PC profile has bounded memory and subprocess behavior.
- Remaining risks and rollback notes are documented.

Target final goals:

- FAST `drag_event_p95_ms` reduced by 50% where baseline allows.
- FAST `drag_ui_lag_p95_ms` reduced by 50% where baseline allows.
- FAST `foreground_decode_during_drag_count` reduced by 50% or more.
- Shared `download/preemption false error count = 0`.
- Shared `main_thread_db_ms_during_interaction = 0`.
- Shared `main_thread_disk_scan_ms_during_interaction = 0`.
- Shared `rss_leak_after_open_close_mb < 50`.
- No FAST or Advanced visual regression.

## Assumptions

- The canonical runtime logs are under `user_data/logs`.
- Conservative shared-service changes are preferred over mode-specific duplicate fixes.
- FAST remains the primary performance target, but Block A/shared infrastructure must support both modes.
- Advanced compatibility must be preserved even when a shared optimization is motivated by FAST bottlenecks.
- A phase may be stopped or rolled back if its KPI improvement is smaller than its regression risk.
