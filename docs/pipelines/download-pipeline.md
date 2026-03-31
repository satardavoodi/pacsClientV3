# Download Pipeline

> **Version:** v2.2.7+ | **Updated:** 2026-03-26

## Overview

The download pipeline handles fetching DICOM studies from the PACS server to local storage. It runs in a **separate subprocess** to avoid GIL contention with the viewer.

## Pipeline Stages

```
User Action (double-click study)
  │
  ▼
┌─────────────────────────────────────────┐
│ 1. INITIATION (main process)            │
│    HomePanelWidget._on_patient_double_  │
│    clicked_async()                       │
│    ├─ Create PatientWidget tab           │
│    └─ Start Zeta download with priority  │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ 2. VALIDATION (DownloadExecutor)        │
│    ├─ Rule engine validates task         │
│    ├─ Check download state (resume?)     │
│    └─ Create/update download state       │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ 3. METADATA FETCH (gRPC)                │
│    ├─ Fetch study structure from server  │
│    ├─ Validate study completeness        │
│    └─ Initialize DB hierarchy            │
│        (Patient→Study→Series→Instances)  │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ 4. DOWNLOAD (subprocess)                │
│    DownloadProcessWorker (own GIL)       │
│    ├─ Series downloaded via gRPC stream  │
│    ├─ DICOM files saved to disk          │
│    ├─ Progress signals → UI              │
│    └─ Instance records → DB              │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ 5. COMPLETION                            │
│    ├─ Download state → COMPLETED         │
│    ├─ Global download counter decremented│
│    ├─ ZetaBoost warmup lanes unblocked   │
│    └─ UI progress → 100%                 │
└─────────────────────────────────────────┘
```

## Key Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `HomePanelWidget` | `PacsClient/pacs/workstation_ui/home_ui/home_ui.py` | Download trigger, progress display |
| `DownloadManagerWidget` | `modules/download_manager/ui/main_widget.py` | Download queue UI, worker management |
| `DownloadExecutor` | `modules/download_manager/download/executor.py` | Orchestrate validation→fetch→download→complete |
| `SeriesDownloader` | `modules/download_manager/download/series_downloader.py` | Per-series download logic |
| `DownloadProcessWorker` | `modules/download_manager/download/worker.py` | Subprocess worker thread |
| `SocketService` | `modules/network/socket_service.py` | PACS protocol communication |
| `ResumableDicomSocketClient` | `modules/network/socket_client.py` | Resumable download support |
| `DicomDownloader` | `modules/network/dicom_downloader.py` | gRPC DICOM download |

## Data Flow

```
PACS Server
    │ (gRPC stream)
    ▼
DownloadProcessWorker (subprocess, own GIL, own priority)
    │ (signals)
    ▼
DownloadManagerWidget (main process)
    │ (Qt signals)
    ├─▶ Database (insert instances, update progress)
    ├─▶ Disk (DICOM files → user_data/patients/...)
    └─▶ UI (progress bars, status updates)
```

## ZetaBoost Interaction

During active downloads:
1. `ZetaBoostEngine.notify_global_download_start()` called → warmup/background lanes blocked
2. Download subprocess runs at IDLE priority → minimal CPU contention
3. On completion: `notify_global_download_stop()` → lanes unblocked → warmup begins

## Resumability

- Download state persists in DB across app restarts
- `ResumableDicomSocketClient` supports partial file recovery
- Series-level granularity (resume from last incomplete series)
- **Incomplete download detection (v2.2.7+):** When a patient is re-opened and a download already exists in StateStore or DB, the system no longer unconditionally blocks it. Non-terminal download states (PENDING, DOWNLOADING, PAUSED, FAILED) trigger a **resume path** instead of rejection.
- **Filesystem verification (v2.2.7+):** Even if the DB marks a study as COMPLETED, R17b now counts actual `.dcm` files in each series directory and compares against the expected `image_count`. If any series is incomplete, the system allows re-download.
- **State reset on resume (v2.2.7+):** When resuming an incomplete download, `start_priority_download_immediately` resets `completed_series`, `skipped_series`, `failed_series`, `downloaded_count`, and `progress_percent` to zero for a fresh attempt.
- **Batch-skip optimization (R19b, v2.2.7.2; hardened v2.2.7.3):** When resuming a partially-downloaded series, `download_series()` advances `batch_start` past leading complete batches instead of always starting at batch 0. Since v2.2.7.3, R19b **verifies actual sequential file existence** (`Instance_0001.dcm` through `Instance_{batch_end}.dcm`) instead of relying on a simple file count. This prevents skipping batches that have gaps when files are non-sequential. Individual files within the first re-downloaded batch are still checked via R19 file-skip.
- **Retry button incremental resume (v2.2.7.2):** The per-series retry button (`_on_series_retry`) no longer deletes existing files when a series is incomplete. It keeps partial files on disk so the downloader can resume using batch-skip (R19b) + file-skip (R19). Only deletes files when the series appears fully complete (to handle corruption).
- **Per-patient retry file cleanup (v2.2.7.3):** The Retry button calls `_on_per_patient_retry()` which now deletes series directories where `existing_count >= expected_count` before starting the download worker. This prevents R20 from falsely skipping "complete" series when files exist on disk but may be corrupt or the user explicitly wants a re-download. Incomplete series are kept for incremental resume.

## Retry Architecture (v2.2.7+)

All retry constants live in `modules/download_manager/core/constants.py`:

| Constant | Value | Purpose |
|----------|-------|---------|
| `RECONNECT_MAX_RETRIES` | 5 | Max socket reconnection attempts |
| `RECONNECT_BASE_DELAY` | 1.0s | Initial reconnect delay |
| `RECONNECT_MAX_DELAY` | 30.0s | Maximum reconnect delay (cap) |
| `RECONNECT_BACKOFF_FACTOR` | 2.0 | Exponential multiplier per retry |
| `RECONNECT_JITTER_MAX` | 1.0s | Random jitter added to prevent thundering herd |
| `MAX_SERIES_RETRIES` | 3 | Per-series retry rounds after initial failure |
| `SERIES_RETRY_BASE_DELAY` | 3.0s | Initial delay between series retry rounds |
| `REQUEST_MAX_RETRIES` | 3 | Retries per send_request call |
| `REQUEST_RETRY_BASE_DELAY` | 1.0s | Initial delay between request retries |

### Retry layers

```
Layer 1: send_request() retry wrapper
  └─ Retries individual socket requests up to REQUEST_MAX_RETRIES
  └─ Exponential backoff + reconnect between retries
  └─ Login requests are NOT retried (fail-fast)

Layer 2: connect_with_retry() (socket level)
  └─ Exponential backoff with jitter, capped at RECONNECT_MAX_DELAY
  └─ Formula: delay = min(base * factor^attempt, max_delay) + random(0, jitter)

Layer 3: Per-series retry loop (series_downloader.py)
  └─ After main download loop completes, retries ALL failed series
  └─ Up to MAX_SERIES_RETRIES rounds (3 by default)
  └─ Exponential backoff between rounds: 3s → 6s → 12s
  └─ Reconnects socket between retry rounds via connect_with_retry()
```

## Validation Rules (R17) — Duplicate/Resume Detection

Located in `modules/download_manager/rules/validation_rules.py`:

### R17a — In-Memory StateStore Check

Checks if a download already exists in the active StateStore:
- **Terminal states** (COMPLETED, CANCELLED): Block with `"Download already exists"` — no re-download.
- **Non-terminal states** (PENDING, DOWNLOADING, PAUSED, FAILED): Return `should_resume=True` so the caller can resume instead of rejecting.

### R17b — Persistent Database Check

If R17a passes (no active state), checks the DB for completed records:
- Queries DB status for the study_uid.
- If DB says "Completed", **verifies actual .dcm file counts on disk** per series directory against `image_count` from metadata.
- If any series directory has fewer `.dcm` files than expected, the download is allowed to proceed (overrides DB "Completed" status).
- This catches the scenario where DB marks a study complete but one or more series was only partially downloaded.

### Resume flow in main_widget.py

```
start_priority_download_immediately()
  ├─ STEP 1: Build task
  ├─ STEP 2: Validate (R17a/R17b)
  │     ├─ should_resume=True? → Fall through to STEP 3+ (resume)
  │     └─ blocked? → Return False (truly duplicate/completed)
  ├─ STEP 3: gRPC metadata fetch
  ├─ STEP 4: State update (reset progress counters for resume)
  └─ STEP 5: Start worker
```

## Progressive Viewer Loading (v2.2.7+)

When a patient tab is opened, the viewer progressively loads images as series download:

| Guard | Purpose |
|-------|---------|
| 250ms per-series throttle | Prevents CPU spike from rapid download progress signals |
| `_progressive_display_inflight` set | Prevents spawning duplicate concurrent load tasks for the same series |
| `finally` block cleanup | Ensures inflight guard is always cleared even on error |

Located in `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`.

## Error Handling

| Error Type | Recovery |
|------------|----------|
| Network timeout | Exponential backoff retry (3 attempts, jitter) via `send_request` wrapper |
| Socket disconnect mid-download | `connect_with_retry()` with exponential backoff + jitter |
| Series download failure | Per-series retry loop: 3 rounds with backoff (3s→6s→12s) |
| Partial download (app restart) | R17a detects non-terminal state → resume path |
| Partial download (retry button) | Per-patient: deletes complete series, keeps incomplete + R19b/R19 resume |
| DB says Complete but files missing | R17b filesystem verification → allows re-download |
| Disk full | Error state + user notification |
| Server unavailable | Queued for retry with backoff |
| Corrupt DICOM file | Skip file, log warning, continue series |
| Login failure | Fail-fast (no retry) |

## Stability Considerations

1. **Subprocess isolation**: Download runs in separate process with own GIL — cannot block viewer
2. **Global counter**: Prevents ZetaBoost from competing for CPU during downloads
3. **Connection pool**: gRPC connections are pooled and reused
4. **State persistence**: Download progress survives app restart
5. **Priority management**: Subprocess runs at IDLE OS priority
6. **Progressive viewer throttle (v2.2.7+)**: 250ms debounce prevents CPU spike from rapid progress signals
7. **Retry jitter (v2.2.7+)**: Random jitter on reconnect delays prevents thundering herd on server recovery
8. **Filesystem truth (v2.2.7+)**: R17b verifies actual files on disk, not just DB state — catches silent partial downloads
9. **Batch-skip on resume (v2.2.7.2; hardened v2.2.7.3)**: `download_series()` skips leading complete batches on partial resume — now verifies actual sequential files instead of trusting file count alone
10. **Retry button preserves files (v2.2.7.2)**: Incomplete series are not deleted on retry — the downloader resumes incrementally via R19b + R19
11. **Per-patient retry cleans complete series (v2.2.7.3)**: `_on_per_patient_retry()` deletes series directories where file count ≥ expected count — prevents R20 from skipping series that the user wants re-downloaded
12. **Accurate skip counting (v2.2.7.3)**: Per-instance file-skip no longer double-counts pre-existing files — progress and result counts are correct
13. **Non-blocking retry (v2.2.7.4)**: `_on_series_retry()` and `_on_per_patient_retry()` offload file I/O and gRPC calls to background threads — the Qt event loop is never blocked by retry operations
14. **Non-blocking worker preemption (v2.2.7.4)**: `_pause_all_active_downloads()` uses `cancel_all_non_blocking()` instead of `stop_all()` — avoids 5s/worker blocking on the main thread
15. **Module independence (v2.2.7.4)**: Download manager operations cannot freeze the viewer, thumbnails, or other modules — all cross-thread marshaling uses `QTimer.singleShot(0, callback)`
