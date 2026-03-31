# AIPacs Copilot Instructions

**Current Stable Version:** v2.2.7.4 (2026-03-28)

## Architecture map (start here)
- App entry is `main.py` → `AppHandler` (login) → `MainWindowWidget` → `ControlPanelInterface` → `HomePanelWidget` for patient list and downloads.
- UI is PySide6 with qasync (`main.py` sets `QEventLoop`) and VTK; keep async UI work on the Qt event loop and offload heavy work to executor threads.
- Patient workflow lives in `PacsClient/pacs/workstation_ui/home_ui/home_ui.py` and opens `PacsClient/pacs/patient_tab` widgets for viewing.
- Download stack is Zeta-based: `PacsClient/zeta_download_manager/**` with adapter helpers in `PacsClient/components/zeta_adapter.py`. Legacy download helpers in `home_ui.py` are marked deprecated.
- Socket comms go through `PacsClient/components/socket_service.py` and config via `PacsClient/utils/socket_config.py` + `config/socket_config.json`.

## Critical rules (learned the hard way)
- **Do NOT re-sort metadata['instances'] by IPP.** VTK slices are in instance_number order (files are `Instance_NNNN.dcm` loaded via `natsort`). Metadata from DB is already in the correct order. Re-sorting by IPP broke reference lines in v1.09.5-v1.09.7.
- **The stored DirectionMatrix in field data has row 1 negated** (Y-flip compensation from `convert_itk2vtk`). Do not use it directly for DICOM normal comparisons without un-negating row 1 first.
- **Scroll fast-path (`_in_wheel_scroll` flag):** During wheelEvent-driven scroll, `set_slice()` skips camera zoom save/restore, interactor style update, and throttles Lock Sync to 100ms.  Do NOT add expensive per-frame operations inside `set_slice()` without guarding them with `if not _wheel:`. See v2.2.3.4.0.
- **DL_WARMUP subprocess runs at IDLE priority** (v2.2.3.4.0). It has its own GIL. Do not bump priority above IDLE — it causes memory-bus contention that spikes the viewer's SetSlice from 8→45ms.
- **GC is suppressed during scroll bursts** (`gc.disable()` in wheelEvent, re-enabled 2000ms after last render). Do not call `gc.collect()` during scroll. See v2.2.3.3.2.
- **Reference line repaint during scroll uses round-robin** (v2.2.3.3.7): trailing-edge timer paints ONE target viewer per tick. Do not change to paint-all-targets per tick — it blocks the event loop N×20ms.
- **Local backup of this stable version:** `backups/v2.2.7_2026-03-21/`
- **Download validation R17a allows resume for non-terminal states** (v2.2.7.1). PENDING/DOWNLOADING/PAUSED/FAILED downloads return `should_resume=True` instead of blocking. Only COMPLETED and CANCELLED are truly blocked. Do NOT revert R17a to unconditional blocking — it caused the "Download already exists" bug where incomplete downloads could never resume.
- **R17b verifies actual .dcm files on disk** (v2.2.7.1). Even if DB says "Completed", R17b counts `.dcm` files per series directory against `image_count`. Do NOT trust DB status alone for completeness checks.
- **Download retry has 3 layers** (v2.2.7.1): send_request wrapper (3 retries), connect_with_retry (exponential backoff+jitter), per-series retry loop (3 rounds, 3s→6s→12s). All constants in `modules/download_manager/core/constants.py`. Do NOT add retry to Login requests (fail-fast by design).
- **Progressive viewer has 250ms per-series throttle** (v2.2.7.1). `on_series_images_progress` debounces to prevent CPU spike from rapid signals. Do not remove the throttle or the `_progressive_display_inflight` guard.
- **R19b batch-skip on resume** (v2.2.7.2; hardened v2.2.7.3). `download_series()` advances `batch_start` past **verified** leading complete batches. Each batch is verified by checking that all sequential `Instance_NNNN.dcm` files exist — do NOT revert to count-based skip (it skips batches with gaps). Do NOT reset `batch_start` to 0 unconditionally — it wastes minutes re-transferring data.
- **Retry button keeps partial files** (v2.2.7.2). `_on_series_retry()` only deletes files when series is fully complete. Do NOT add unconditional `shutil.rmtree()` for incomplete series — it forces full re-download instead of incremental resume.
- **Per-patient retry deletes "complete" series files** (v2.2.7.3). `_on_per_patient_retry()` iterates all series and deletes series directories where `existing_count >= expected_count` — R20 would otherwise skip them. Incomplete series are kept for incremental resume. Do NOT remove the file deletion from `_on_per_patient_retry()` — without it, R20 sees the series as complete and the download never triggers.
- **skipped_count uses existing_files_set** (v2.2.7.3). Per-instance file-skip only increments `skipped_count` for files NOT in the initial scan set. Do NOT remove the `existing_files_set` check — it prevents double-counting that inflates progress and result values.
- **Retry methods are non-blocking** (v2.2.7.4). `_on_series_retry()` and `_on_per_patient_retry()` offload all file I/O (`shutil.rmtree`, `os.listdir`) and gRPC calls (`_reconstruct_task_from_database`) to `threading.Thread` background threads. Results are marshaled back via `QTimer.singleShot(0, callback)`. Do NOT add blocking I/O to the fast path of these methods — it freezes the entire application.
- **Worker preemption is non-blocking** (v2.2.7.4). `_pause_all_active_downloads()` uses `cancel_all_non_blocking()` (sets cancel flags only) instead of `stop_all()` (which waits 5s/worker). Do NOT revert to `stop_all()` in any main-thread code path — only use it for app shutdown.
- **Module independence rule** (v2.2.7.4). Each DICOM workstation module (viewer, download manager, thumbnails) must operate as an independent loop. No module may block the Qt event loop >16ms. All cross-module communication uses Qt signals (AutoConnection). Blocking I/O must be in background threads with `QTimer.singleShot(0, callback)` to marshal results back.

## Key flows to preserve
- Opening a study: `HomePanelWidget._on_patient_double_clicked_async` opens tab immediately, then starts Zeta download with priority and wires progress signals.
- Download UI: always use `DownloadManagerWidget` from `PacsClient/zeta_download_manager/ui/main_widget.py` (created via `_get_or_create_download_manager_tab`).
- Shutdown behavior: `main.py` clears only the Download Manager UI state file but keeps DB download history; do not delete DB progress in shutdown.

## Project-specific conventions
- Resource paths must go through `PacsClient/utils/config.py` (`BASE_PATH`, `ICON_PATH`, `IMAGES_LOGIN_PATH`) to work for both dev and PyInstaller.
- For sockets, update settings via `update_socket_server_settings()` before querying server-side lists.
- Prefer signals/slots for UI updates; download progress is emitted from background threads via Qt signals.

## Build/run/test workflows
- Run app: `python main.py` (Windows uses software OpenGL flags set in `main.py`).
- Build executable: `build.bat` → `build.py` (PyInstaller spec `AIPacs.spec`).
- Tests are ad-hoc scripts like `test_*.py`; there is no single test runner configured.

## Where to look for feature work
- Patient UI and tabs: `PacsClient/pacs/patient_tab/**`.
- MPR modules: `PacsClient/pacs/patient_tab/zeta mpr/**` and `advance_mpr_3d_slicer/**`.
- Download engine + state: `PacsClient/zeta_download_manager/{core,download,network,storage,state,ui}`.
- Download manager (modular): `modules/download_manager/{core,download,network,rules,state,ui}` — retry constants, validation rules (R17), series downloader, socket client.
- Download validation rules: `modules/download_manager/rules/validation_rules.py` (R17a/R17b duplicate/resume detection).
- Progressive viewer loading: `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` (throttle, inflight guard).
- Scroll performance: `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py` (set_slice, wheelEvent, adaptive throttle, GC suppression).
- DL_WARMUP subprocess: `PacsClient/pacs/patient_tab/zeta_boost/warmup_subprocess.py`.
- Image pipeline / ITK filters: `PacsClient/pacs/patient_tab/utils/image_filters.py` and `image_io.py`.
- Reference lines during scroll: `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget.py` (`_schedule_reference_line_update`, `_do_lock_sync`).

## Documentation rules for AI
- When changing image pipeline or sync mapping, update `docs/IMAGE_PIPELINE_REFERENCE.md`.
- When changing Zeta MPR internals, update `PacsClient/pacs/patient_tab/zeta mpr/ZETA_MPR_PIPELINE_REFERENCE.md`.
- When bumping versions, update `VERSION_*.md` with date, tag, and commit.
- When changing scroll performance, update `docs/PERFORMANCE_STATUS.md`, `docs/METRICS_TRACKING_v2.2.3.x.md`, and `docs/PERFORMANCE_DECISION_LOG_2026-02-27.md`.
- When adding new per-frame overhead to `set_slice()`, guard it with `_in_wheel_scroll` check and document in `PERFORMANCE_STATUS.md`.
- When changing download retry/reconnection/validation logic, update `docs/pipelines/download-pipeline.md` and `docs/releases/RELEASE_NOTES.md`.
- When changing R17 validation rules, update the "Validation Rules (R17)" section in `docs/pipelines/download-pipeline.md`.

## Cross-PC improvement cycle (mandatory)
- **PC roles:** treat the current development machine as **PC A (Developer PC)**. Other machines (e.g., PC B) are validation targets.
- **Standard cycle for every optimization/debugging change:**
	1. Apply code changes locally on **PC A**.
	2. Validate locally on **PC A** (focused run/log check for the changed flow).
	3. Push updated code from **PC A** to GitHub.
	4. Pull the same commit on **PC B**.
	5. Re-run the same scenario on **PC B** and compare behavior/logs.
	6. Decide next iteration based on **PC A vs PC B** deltas, then repeat.
- **Scope:** use this cycle for all future cross-PC performance, stability, and debugging work.
- **Reference:** `docs/CROSS_PC_IMPROVEMENT_WORKFLOW.md`.
