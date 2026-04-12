# Module Connections & Signal Map

> **Version:** v2.3.1 | **Updated:** 2026-04-13

## Purpose

This document maps every inter-module connection in AIPacs — how modules
communicate, what signals they exchange, and what the data flow looks like
end-to-end. Use this as a reference when modifying cross-module behavior.

---

## System-Level Connection Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AIPacs Desktop Application                        │
│                                                                             │
│  ┌─────────────┐     ┌──────────────────┐     ┌────────────────────────┐  │
│  │  main.py    │────▶│  AppHandler      │────▶│  MainWindowWidget      │  │
│  │  (entry)    │     │  (login)         │     │  (workstation shell)   │  │
│  └─────────────┘     └──────────────────┘     └───────────┬────────────┘  │
│                                                            │               │
│                    ┌───────────────────────────────────────┤               │
│                    │                                       │               │
│                    ▼                                       ▼               │
│  ┌──────────────────────┐             ┌───────────────────────────────┐   │
│  │   HomePanelWidget    │             │   Module Tabs                 │   │
│  │   (patient list)     │             │   (MPR, Education, Web, etc.) │   │
│  │                      │             └───────────────────────────────┘   │
│  │  ┌────────────────┐  │                                                 │
│  │  │ HomeDbService   │  │                                                │
│  │  │ HomeTabService  │  │                                                │
│  │  │ HomeDownload    │  │                                                │
│  │  │   Service       │  │                                                │
│  │  │ HomeSearch      │  │                                                │
│  │  │   Service       │  │                                                │
│  │  └────────────────┘  │                                                 │
│  └──────────┬───────────┘                                                 │
│             │ double-click study                                          │
│             ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                        PatientWidget Tab                              │ │
│  │                                                                       │ │
│  │  ┌────────────────┐  ┌────────────────────┐  ┌──────────────────┐   │ │
│  │  │ ViewerController│  │ ThumbnailManager   │  │ ZetaBoostEngine  │   │ │
│  │  │ (per-viewport) │  │ (sidebar)          │  │ (warmup cache)   │   │ │
│  │  └───────┬────────┘  └────────────────────┘  └──────────────────┘   │ │
│  │          │                                                            │ │
│  │          │ series switch / drag-drop                                  │ │
│  │          ▼                                                            │ │
│  │  ┌──────────────────────────────────────────────────────────────┐    │ │
│  │  │              VTK Widgets (2D / Fast / Advanced)               │    │ │
│  │  │  set_slice() │ wheelEvent │ window/level │ measurements      │    │ │
│  │  └──────────────────────────────────────────────────────────────┘    │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│             │                                                              │
│             │ Qt signals (series progress, priority change)                │
│             ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                    Download Manager Module                            │ │
│  │                                                                       │ │
│  │  ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐     │ │
│  │  │ StateStore     │  │ Coordinator      │  │ RuleEngine       │     │ │
│  │  │ (in-memory)    │◀─│ (intent mgr)     │  │ (R17a/R17b/R19) │     │ │
│  │  └────────┬───────┘  └──────────────────┘  └──────────────────┘     │ │
│  │           │                                                           │ │
│  │           ▼                                                           │ │
│  │  ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐     │ │
│  │  │ UIObserver     │  │ Workers          │  │ ProgressTracker  │     │ │
│  │  │ (state→UI)     │  │ (subprocess)     │  │ (signal emit)    │     │ │
│  │  └────────────────┘  └────────┬─────────┘  └──────────────────┘     │ │
│  │                                │                                      │ │
│  └────────────────────────────────┼──────────────────────────────────────┘ │
│                                   │                                        │
│             ┌─────────────────────┼────────────────────────┐              │
│             │                     │                        │              │
│             ▼                     ▼                        ▼              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │   Database        │  │   Network         │  │   Filesystem          │  │
│  │   (SQLite+WAL)    │  │   (Socket+gRPC)   │  │   (user_data/)        │  │
│  │                    │  │                    │  │                       │  │
│  │  core.py           │  │  SocketService    │  │  Instance_NNNN.dcm    │  │
│  │  manager.py        │  │  SocketDicomClient│  │  thumbnails/          │  │
│  │  get_db_connection  │  │  DicomGrpcClient  │  │  attachment/          │  │
│  └──────────────────┘  └────────┬─────────┘  └───────────────────────┘  │
│                                  │                                        │
└──────────────────────────────────┼────────────────────────────────────────┘
                                   │
                    ─── Network boundary ───
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │     AIPacs Server         │
                    │  Socket :50052            │
                    │  gRPC   :50051            │
                    │  DICOM Storage / PACS     │
                    └──────────────────────────┘
```

---

## Inter-Module Signal Connections

### 1. Home Panel → Download Manager

```
HomePanelWidget._on_patient_double_clicked_async()
  │
  ├─ HomeTabService.add_patient_tab() → PatientWidget tab created
  │
  └─ HomeDownloadService.get_or_create_download_manager_tab()
      └─ DownloadManagerWidget.start_priority_download_immediately(task)
```

**Signal wiring** (done in `HomeDownloadService.connect_download_manager_to_widget()`):
```
DownloadManagerWidget.seriesProgressUpdated  ──▶  PatientWidget.series_images_progress
DownloadManagerWidget.downloadCompleted      ──▶  PatientWidget.on_download_completed
```

### 2. Viewer → Download Manager (Priority Change)

```
ViewerController.change_series_on_viewer(series_number)
  │
  └─ QTimer.singleShot(0, _notify_dm_viewed_series)   [deferred, non-blocking]
      │
      ├─ 500ms per-series cooldown (_dm_notify_last_ts)
      │
      └─ DownloadManagerWidget.set_viewed_series(study_uid, series_number)
          │
          └─ SeriesIntentCoordinator.request_critical_series(study_uid, series_number)
              │
              ├─ StateStore.update(priority=CRITICAL, viewed_series_number=series_number)
              │
              ├─ [if same study, different series] Cancel own worker (non-blocking)
              │   └─ StateStore.update(status=PENDING)  [not PAUSED — scheduler picks up]
              │
              ├─ negotiate_priority_change()
              │   ├─ Pause lower-priority peers (is_auto_paused=True)
              │   ├─ QTimer.singleShot(50, _start_next_pending)
              │   └─ schedule_priority_start_retry(200ms)  [backup poller]
              │
              └─ UIObserver.on_state_changed()
                  └─ QTimer.singleShot(0, refresh_table_order)
```

### 3. Download Manager → Viewer (Progressive Display)

```
DownloadProcessWorker (subprocess)
  │ gRPC download → files saved to disk
  │
  ├─ _progress_throttle_timer (100ms batching)
  │
  └─ seriesProgressUpdated.emit(series_number, downloaded, total)
      │
      └─ ViewerController.on_series_images_progress(sn, downloaded, total)
          │                                        [100ms per-series debounce]
          │
          ├─ First time (sn NOT in _progressive_display_done):
          │   └─ _start_progressive_display(sn)
          │       ├─ _ensure_import_folder_path()
          │       ├─ Load series from disk
          │       ├─ Display in viewer
          │       ├─ Activate progressive mode
          │       └─ _progressive_display_done.add(sn)  [on main thread ONLY]
          │
          └─ Subsequent (sn IN _progressive_display_done):
              └─ _grow_progressive_fast(sn)
                  └─ _progressive_grow_timer (150ms interval)
```

### 4. Download Manager → ZetaBoost

```
DownloadManagerWidget._on_worker_started()
  └─ ZetaBoostEngine.notify_global_download_start()
      └─ Warmup and background lanes blocked

DownloadManagerWidget._on_worker_completed()
  └─ ZetaBoostEngine.notify_global_download_stop()
      └─ Warmup lanes unblocked → prefetch begins
```

### 5. State Store → UIObserver → DM Table

```
StateStore.update(field, value)
  │
  └─ _notify_observers(study_uid, field, old_value, new_value)
      │
      └─ UIObserver.on_state_changed(study_uid, field, old, new)
          │
          ├─ status change → update_row_status(study_uid)
          ├─ progress change → update_row_progress(study_uid)
          └─ priority change → QTimer.singleShot(0, refresh_table_order)
```

### 6. Home Search → Network → Database

```
HomeSearchService.search_patients_server()  [async]
  │
  └─ SocketService.send_request("GetPatientList", params)
      │
      └─ PatientListSocketClient.send_request()
          ├─ SocketTokenManager.get_token() → JWT
          ├─ 4-byte length-prefixed JSON envelope
          └─ _recv_exact() → parse response
              │
              └─ HomeDbService.save_patient_and_study_on_db()
                  └─ get_db_connection() → INSERT/UPDATE + commit
```

### 7. Thumbnail Fetch → gRPC

```
PatientWidget._load_thumbnails()
  │
  └─ DicomGrpcClient.get_thumbnail(study_uid, series_uid)
      ├─ _ensure_stub()  [auto-reconnect if stub is None]
      └─ gRPC stub.GetThumbnail(request)
```

---

## Cross-Module Communication Rules (v2.3.1)

| Rule | Description |
|------|-------------|
| No module may block Qt event loop >16ms | All I/O must be in background threads |
| Cross-module communication uses Qt signals | AutoConnection (same-thread=direct, cross-thread=queued) |
| Background thread results use `QTimer.singleShot(0, callback)` | Marshals back to main thread safely |
| No direct cross-module state mutation | Use signals/slots, not shared mutable state |
| Each module is an independent loop | Viewer, DM, thumbnails operate independently |
| Socket writes use `sendall()` | Never `send()` — prevents partial writes |
| Socket reads use `_recv_exact(size)` | Never bare `recv(4)` — prevents partial reads |
| DB operations use `with get_db_connection()` | Never bare `get_connection_database()` |
| DML inside `with` block must `conn.commit()` | Context manager does NOT auto-commit |

---

## Module Dependency Matrix

```
                Home  Patient  Viewer  DM   Network  Database  ZetaBoost  EchoMind  Printing
HomePanelWidget  ──    uses     ──     uses  uses     uses      ──         ──        ──
PatientWidget    ──    ──       uses   uses  ──       uses      uses       ──        ──
ViewerController ──    ──       ──     uses  ──       ──        ──         ──        ──
DownloadManager  ──    ──       ──     ──    uses     uses      notify     ──        ──
SocketService    ──    ──       ──     ──    ──       ──        ──         ──        ──
Database         ──    ──       ──     ──    ──       ──        ──         ──        ──
ZetaBoostEngine  ──    ──       ──     ──    ──       uses      ──         ──        ──
EchoMind         ──    ──       ──     ──    uses     uses      ──         ──        ──
Printing         ──    ──       ──     ──    ──       uses      ──         ──        ──
```

**Legend:** `uses` = calls methods/signals, `notify` = sends notifications, `──` = no dependency

---

## Thread Model Summary

| Thread | Owner | Responsibility |
|--------|-------|----------------|
| Main (Qt) | QApplication | All UI, widget manipulation, signal dispatch |
| qasync event loop | main.py | Async patient search, login flow |
| Download subprocess | DownloadProcessWorker | DICOM download (own GIL, IDLE priority) |
| DL_WARMUP subprocess | warmup_subprocess.py | Cache warmup (own GIL, IDLE priority) |
| Background I/O threads | `threading.Thread` | File cleanup, retry, gRPC reconnect |
| DB thread pool | connection pool | Per-thread SQLite connections (WAL mode) |
| ZetaBoost workers | ThreadPoolExecutor | L1/L2 cache fill, IDLE priority |

---

## Timer Inventory (v2.3.1)

All timers that affect cross-module latency:

| Timer | Value | Location | Purpose |
|-------|-------|----------|---------|
| `_progress_throttle_timer` | 100ms | DM main_widget.py | Batch per-image progress signals |
| `on_series_images_progress` debounce | 100ms | viewer_controller.py | Per-series progress throttle |
| `_progressive_grow_timer` | 150ms | viewer_controller.py | Batch image growth cadence |
| `negotiate_priority_change` defer | 50ms | series_intent_coordinator.py | Queue recheck delay |
| `schedule_priority_start_retry` | 200ms | series_intent_coordinator.py | Priority retry polling |
| UIObserver priority refresh | 0ms | observers.py | Next event loop tick |
| Worker completion → next | 0ms | main_widget.py | Next event loop tick |
| DM notify cooldown | 500ms | viewer_controller.py | Per-series drag-drop dedup |
| Stale guard refresh | 150ms | viewer_controller.py | Background cache refresh |
| GC re-enable | 2000ms | vtk_widget.py | After scroll burst ends |
| Lock Sync throttle | 100ms | vtk_widget.py | During scroll only |
| Reference line round-robin | ~20ms | patient_widget.py | 1 target per tick |

---

## Additional Module Connections

### 8. Viewer → ZetaBoost (Cache Warmup)

```
PatientWidget opens study
  │
  └─ ZetaBoostEngine.start_warmup(study_uid, series_list)
      ├─ L1 cache (memory) — hot slices around current position
      ├─ L2 cache (disk via disk_cache.py) — prefetched slices
      └─ WarmupSubprocessManager — dedicated subprocess at IDLE priority
          └─ Communicates via IPC, own GIL so no contention with main process
```

### 9. Module System → Dynamic Loading

```
config/installation_profile.json
  │
  └─ ModuleManager.load_modules()
      ├─ Check module state: IDLE → QUEUED → RUNNING
      ├─ ThreadPoolExecutor for concurrent init
      └─ pipeline_orchestrator.py — dependency-ordered execution
```

### 10. Storage Cleanup Flow

```
StorageCleanupPanelWidget (settings UI)
  │
  └─ local_storage_cleanup_manager.py
      ├─ storage_calculator.py — scan disk usage
      ├─ patient_cleanup_manager.py — per-patient file removal
      └─ disk_alert_service.py — low-space warnings
```

### 11. Stitching Pipeline

```
StitchingWidget (UI)
  ├─ StitchController (QObject) — orchestration
  │   ├─ LandmarkStore — stores alignment landmarks
  │   └─ StitchEngine — image composition
  └─ stitch_worker.py — background processing
```

### 12. Printing Pipeline

```
PrintingWidget (UI)
  ├─ PrintToolManager — tool selection
  ├─ GridLayoutEngine — paper layout computation
  ├─ FilmPreviewWidget — preview rendering
  └─ printers/ — printer driver abstraction
```

---

## Error Propagation Paths

| Error Source | Signal/Mechanism | Handler |
|-------------|-----------------|---------|
| Socket timeout | `send_request` retry (3×) | Exponential backoff + jitter |
| gRPC disconnect | `_ensure_stub()` returns None | Auto-reconnect on next call |
| Worker crash | `DownloadProcessWorker.finished` signal | `_on_worker_error` → FAILED state |
| DB lock timeout | `BUSY_TIMEOUT_MS = 120000` | Retry via connection pool |
| Disk full | `FileManager` IO error | State → FAILED, user notification |
| Series not found | DM rule engine R17b | `RuleResult(should_block=True)` |
| Progressive display failure | Background thread exception | `QTimer.singleShot(0, error_callback)` |

---

## Shutdown Sequence

```
MainWindow.closeEvent()
  │
  └─ LifecycleManager.shutdown_all()  [LIFO order]
      ├─ 1. DM workers: cancel_all_non_blocking() + stop_all(timeout=5s)
      ├─ 2. ZetaBoost: WarmupSubprocessManager.stop()
      ├─ 3. gRPC channel: close()
      ├─ 4. Socket pools: close all connections
      ├─ 5. DB pool: close all connections
      ├─ 6. Thread pools: shutdown(wait=True)
      └─ 7. Temp file cleanup (DM UI state file only — DB preserved)
```
