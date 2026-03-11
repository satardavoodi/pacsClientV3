# Download Pipeline

> **Version:** v2.2.3.4.0 | **Updated:** 2026-03-10

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

## Error Handling

| Error Type | Recovery |
|------------|----------|
| Network timeout | Exponential backoff retry (3 attempts, jitter) |
| Partial download | Resume from last complete series |
| Disk full | Error state + user notification |
| Server unavailable | Queued for retry with backoff |
| Corrupt DICOM file | Skip file, log warning, continue series |

## Stability Considerations

1. **Subprocess isolation**: Download runs in separate process with own GIL — cannot block viewer
2. **Global counter**: Prevents ZetaBoost from competing for CPU during downloads
3. **Connection pool**: gRPC connections are pooled and reused
4. **State persistence**: Download progress survives app restart
5. **Priority management**: Subprocess runs at IDLE OS priority
