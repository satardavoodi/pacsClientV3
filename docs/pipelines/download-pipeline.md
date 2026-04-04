# Download Pipeline

> **Version:** v2.3.0 | **Updated:** 2026-04-04

## Overview

The download pipeline handles fetching DICOM studies from the PACS server to local storage. It runs in a **separate subprocess** to avoid GIL contention with the viewer.

In `v2.3.0`, the download manager remains part of the core workstation bundle, so every installed PC receives the same download engine even when optional modules differ.

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
| `SocketService` | `modules/network/socket_service.py` | PACS protocol communication (singleton facade) |
| `PatientListSocketClient` | `modules/network/socket_client.py` | Patient list/report socket queries |
| `ResumableDicomSocketClient` | `modules/download_manager/network/socket_client.py` | Resumable download with retry/health |
| `DicomGrpcClient` | `modules/network/grpc_client.py` | gRPC thumbnail + DICOM streaming |
| `DicomDownloader` | `modules/network/dicom_downloader.py` | gRPC DICOM download |
| `ConnectionHealthMonitor` | `modules/download_manager/network/health_monitor.py` | R30-R34 adaptive health tracking |
| `SocketConfig` | `modules/network/socket_config.py` | Server host/port/timeout config |
| `SocketTokenManager` | `modules/network/socket_token_manager.py` | JWT token management (singleton) |

## Install and Runtime Contract

The download manager is always installed as a core module:

- The Windows installer does not let users remove it, because study open, resumable fetch, and progressive viewing depend on it.
- The install profile written during setup keeps the download manager enabled on the target PC.
- Optional modules selected during setup are bootstrapped on first launch without changing the download manager contract.
- Cross-PC installs therefore keep a consistent download path while still allowing per-PC optional module choices.

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

## Progressive Viewer Loading (v2.2.8.1)

When a patient tab is opened, the viewer progressively loads images as series download:

| Guard | Purpose |
|-------|---------|
| 100ms per-series throttle | Prevents CPU spike from rapid download progress signals (was 250ms pre-v2.2.8.1) |
| `_progressive_display_inflight` set | Prevents spawning duplicate concurrent load tasks for the same series |
| `_progressive_display_done` set | Marks series that completed initial display — routes to grow path |
| Done-guard recovery | Re-activates progressive mode if guard says done but no progressive viewer exists |
| `finally` block cleanup | Ensures inflight guard is always cleared even on error |

**v2.2.8.1 Changes:**
- Progressive grow timer reduced: 500ms → 150ms
- Progress debounce reduced: 250ms → 100ms
- Done-guard ordering fixed: `done.add(sn)` now runs AFTER display+activation on main thread
- Stale guard: show-then-refresh (display immediately, background reload at +150ms)
- DM notify deferred: `QTimer.singleShot(0)` with 500ms cooldown per series
- Loading spinner: shown on target viewer for empty series drag-drop

Located in `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`.

## Series-Interrupt (v2.2.8.1)

When user drag-drops a different series within the same study that's actively downloading:

1. `request_critical_series()` detects `current_series_number != requested_series`
2. Own worker is cancelled non-blocking (sets cancel flag, doesn't wait)
3. State overridden to PENDING (not PAUSED) — so `_start_next_pending` picks it up
4. `negotiate_priority_change()` defers `_start_next_pending` + schedules retry backup
5. Result: ~batch RTT + 250ms to switch (was: wait for entire series to finish)

Located in `modules/download_manager/coordinator/series_intent_coordinator.py`.

## Critical Series Intent (FAST Viewer Drag/Drop) — 2026-04-01 Hardening

### Why this matters

In FAST mode, users may drag/drop any series while a study is already downloading in routine order. The pipeline must treat this as immediate clinical intent, not as a best-effort hint.

### Required behavior

1. Patient open from server enters **High** priority study flow.
2. User drag/drop of an undownloaded series creates **Critical** series intent.
3. Active lower-priority worker is preempted/cancelled non-blocking.
4. Requested series is fetched first.
5. After requested series is available, study returns to **High** and normal order continues.

### Failure modes that were hardened

- DM init crash due to `_tasks` initialization order before coordinator wiring.
- Repeated same-series drag/drop treated as no-op despite incomplete files.
- Same-study critical retry accepted in UI but not enforced as immediate preemption.
- Preemption relying only on state flags (which can lag) instead of active worker truth.
- Cancel responsiveness too slow during long in-flight socket responses.

### Implementation rules now enforced

- Coordinator-backed critical intent path in DM (`request_critical_series_download` + viewed-series intent).
- Same-series drag/drop re-triggers download when on-disk data is still incomplete.
- `_on_series_retry()` avoids false skip when requested series differs from active same-study series.
- `_pause_all_active_downloads()` first cancels by active worker pool, then normalizes state to `PAUSED`.
- Socket receive/retry loops check cancellation early to shorten preemption latency.

### Operational note

Priority orchestration is now designed as:

- **Rules + state machine** for validation/transitions,
- **Thin intent coordinator** for atomic viewer-to-DM decisions,
- **Worker pool truth** for runtime preemption decisions.

This avoids a heavyweight monolithic orchestrator while preserving deterministic behavior under repeated user actions.

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
16. **sendall() for all socket writes (v2.2.8.0)**: `PatientListSocketClient.send_request()` uses `sendall()` instead of `send()` — prevents partial writes from corrupting framing on large payloads
17. **Exact-length recv (v2.2.8.0)**: `_recv_exact(size)` accumulates partial reads until the exact byte count is received — prevents framing corruption on slow/congested networks
18. **Response size validation (v2.2.8.0)**: 50 MB limit on response allocation — prevents unbounded memory growth from server bugs or corrupted length headers
19. **Lazy connection pool (v2.2.8.0)**: `SocketConnectionPool` creates connections on demand instead of eagerly at init — validates `is_connected()` before returning pooled clients
20. **gRPC auto-reconnect (v2.2.8.0)**: `DicomGrpcClient._ensure_stub()` reconnects if channel/stub is `None` — subsequent thumbnail calls succeed after transient failure
21. **No hardcoded server IPs (v2.2.8.0)**: `constants.py` defaults to `localhost` with `AIPACS_SOCKET_HOST` env var override — production IPs come from config only

## Network Architecture Reference

For full details on wire protocol, authentication, connection pools, TCP tuning,
and the complete file map, see `docs/architecture/network-architecture.md`.

## Test Coverage

### Download Manager Tests (`tests/download_manager/test_download_manager.py`)

27 scenarios, 129 assertions. Run: `python tests/download_manager/run_dm_test.py`

| Scenario | What it tests |
|----------|---------------|
| S1 | State machine transitions: PENDING→DOWNLOADING→COMPLETED, FAILED→PENDING, PAUSED→PENDING |
| S2 | Priority preemption: HIGH pauses NORMAL, CRITICAL pauses all, resume order HIGH→NORMAL |
| S3 | Disconnect/reconnect resume: socket failure → state preserved → resume path |
| S4 | R20 skip & retry file cleanup: series skip logic, per-patient retry file deletion |
| S5 | R19b verified batch-skip: sequential file verification, gap detection |
| S6 | State store thread safety: 8 threads × 12 ops, no corruption |
| S7 | Observer fan-out: state changes propagate to all registered observers |
| S8 | Rule engine validation: R17a/R17b duplicate detection, resume detection |
| S9 | Skipped-count accuracy: existing_files_set prevents double-counting |
| S10 | Priority ordering: CRITICAL > HIGH > NORMAL sorting |
| S11 | State reset on resume: progress counters cleared on re-download |
| S12–S21 | Additional state machine, retry, and error handling edge cases |
| S22 | Coordinator negotiate latency: priority change completes in <5ms |
| S23 | Observer priority chain: state change → priority change → UI refresh in sequence |
| S24 | Critical series roundtrip: request_critical_series → state=CRITICAL, viewed_series set |
| S25 | Rapid toggle stress: 100 rapid NORMAL↔CRITICAL toggles, state remains consistent |
| S26 | Auto-resume after critical done: peers resume when critical study completes |
| S27 | Series-interrupt: same-study worker cancelled, state=PENDING, viewed_series updated |

### Stress Tests (`tests/download_manager/test_dm_stress.py`)

10 heavy-load scenarios, 31 pass / 1 expected fail. Run: `python tests/download_manager/test_dm_stress.py`

| Scenario | What it tests | KPI |
|----------|---------------|-----|
| H1 | 50 concurrent patient downloads | State store handles 50 entries in <100ms |
| H2 | 500 rapid series switches | Coordinator handles 500 priority changes in <5s |
| H3 | 16-thread × 500 ops contention | P99 lock wait <5ms (expected fail: GIL contention) |
| H4 | 10,000 progress updates with observer fan-out | No dropped signals |
| H5 | 200 studies × 20 series memory pressure | Memory stays bounded |
| H6 | Priority negotiation storm (all CRITICAL) | Coordinator resolves deterministically |
| H7 | 100 create/promote/complete/resume cycles | No state corruption |
| H8 | 10 studies × 10 series × 100 files I/O stress | All files created/verified |
| H9 | 1000 get_next_download under full store | Rule engine throughput >1000/s |
| H10 | Combined pipeline (priority + observer + coordinator + I/O) | End-to-end <10ms/op |
