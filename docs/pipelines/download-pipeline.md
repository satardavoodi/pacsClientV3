# Download Pipeline

> **Version:** v2.3.3 | **Updated:** 2026-04-27

## Overview

The download pipeline handles fetching DICOM studies from the PACS server to local storage. It runs in a **separate subprocess** to avoid GIL contention with the viewer.

In `v2.3.3`, the download manager remains part of the core workstation bundle, so every installed PC receives the same download engine even when optional modules differ.

## Pipeline Stages

```
User Action (double-click study)
  أ¢â€‌â€ڑ
  أ¢â€“آ¼
أ¢â€‌إ’أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع¯
أ¢â€‌â€ڑ 1. INITIATION (main process)            أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    HomePanelWidget._on_patient_double_  أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    clicked_async()                       أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ Create PatientWidget tab           أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌â€‌أ¢â€‌â‚¬ Start Zeta download with priority  أ¢â€‌â€ڑ
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌آ¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع©
                 أ¢â€‌â€ڑ
                 أ¢â€“آ¼
أ¢â€‌إ’أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع¯
أ¢â€‌â€ڑ 2. VALIDATION (DownloadExecutor)        أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ Rule engine validates task         أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ Check download state (resume?)     أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌â€‌أ¢â€‌â‚¬ Create/update download state       أ¢â€‌â€ڑ
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌آ¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع©
                 أ¢â€‌â€ڑ
                 أ¢â€“آ¼
أ¢â€‌إ’أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع¯
أ¢â€‌â€ڑ 3. METADATA FETCH (gRPC)                أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ Fetch study structure from server  أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ Validate study completeness        أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌â€‌أ¢â€‌â‚¬ Initialize DB hierarchy            أ¢â€‌â€ڑ
أ¢â€‌â€ڑ        (Patientأ¢â€ â€™Studyأ¢â€ â€™Seriesأ¢â€ â€™Instances)  أ¢â€‌â€ڑ
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌آ¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع©
                 أ¢â€‌â€ڑ
                 أ¢â€“آ¼
أ¢â€‌إ’أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع¯
أ¢â€‌â€ڑ 4. DOWNLOAD (subprocess)                أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    DownloadProcessWorker (own GIL)       أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ Series DICOM bytes downloaded via socket  أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ DICOM files saved to disk          أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ Progress signals أ¢â€ â€™ UI              أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌â€‌أ¢â€‌â‚¬ Instance records أ¢â€ â€™ DB              أ¢â€‌â€ڑ
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌آ¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع©
                 أ¢â€‌â€ڑ
                 أ¢â€“آ¼
أ¢â€‌إ’أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع¯
أ¢â€‌â€ڑ 5. COMPLETION                            أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ Download state أ¢â€ â€™ COMPLETED         أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ Global download counter decrementedأ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌إ“أ¢â€‌â‚¬ ZetaBoost warmup lanes unblocked   أ¢â€‌â€ڑ
أ¢â€‌â€ڑ    أ¢â€‌â€‌أ¢â€‌â‚¬ UI progress أ¢â€ â€™ 100%                 أ¢â€‌â€ڑ
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€‌ع©
```

## Key Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `HomePanelWidget` | `PacsClient/pacs/workstation_ui/home_ui/home_ui.py` | Download trigger, progress display |
| `DownloadManagerWidget` | `modules/download_manager/ui/main_widget.py` | Download queue UI, worker management |
| `DownloadExecutor` | `modules/download_manager/download/executor.py` | Orchestrate validationأ¢â€ â€™fetchأ¢â€ â€™downloadأ¢â€ â€™complete |
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
    أ¢â€‌â€ڑ (gRPC stream)
    أ¢â€“آ¼
DownloadProcessWorker (subprocess, own GIL, own priority)
    أ¢â€‌â€ڑ (signals)
    أ¢â€“آ¼
DownloadManagerWidget (main process)
    أ¢â€‌â€ڑ (Qt signals)
    أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€“آ¶ Database (insert instances, update progress)
    أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€“آ¶ Disk (DICOM files أ¢â€ â€™ user_data/patients/...)
    أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€“آ¶ UI (progress bars, status updates)
```

## ZetaBoost Interaction

During active downloads:
1. `ZetaBoostEngine.notify_global_download_start()` called أ¢â€ â€™ warmup/background lanes blocked
2. Download subprocess runs at IDLE priority أ¢â€ â€™ minimal CPU contention
3. On completion: `notify_global_download_stop()` أ¢â€ â€™ lanes unblocked أ¢â€ â€™ warmup begins

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
  أ¢â€‌â€‌أ¢â€‌â‚¬ Retries individual socket requests up to REQUEST_MAX_RETRIES
  أ¢â€‌â€‌أ¢â€‌â‚¬ Exponential backoff + reconnect between retries
  أ¢â€‌â€‌أ¢â€‌â‚¬ Backoff wait is cancellation-aware so preemption can abort before the next retry/reconnect
  أ¢â€‌â€‌أ¢â€‌â‚¬ Login requests are NOT retried (fail-fast)

Layer 2: connect_with_retry() (socket level)
  أ¢â€‌â€‌أ¢â€‌â‚¬ Exponential backoff with jitter, capped at RECONNECT_MAX_DELAY
  أ¢â€‌â€‌أ¢â€‌â‚¬ Formula: delay = min(base * factor^attempt, max_delay) + random(0, jitter)
  أ¢â€‌â€‌أ¢â€‌â‚¬ Reconnect backoff wait is cancellation-aware so a preempted worker does not keep the pool slot occupied through the full retry ladder

Layer 3: Per-series retry loop (series_downloader.py)
  أ¢â€‌â€‌أ¢â€‌â‚¬ After main download loop completes, retries ALL failed series
  أ¢â€‌â€‌أ¢â€‌â‚¬ Up to MAX_SERIES_RETRIES rounds (3 by default)
  أ¢â€‌â€‌أ¢â€‌â‚¬ Exponential backoff between rounds: 3s أ¢â€ â€™ 6s أ¢â€ â€™ 12s
  أ¢â€‌â€‌أ¢â€‌â‚¬ Reconnects socket between retry rounds via connect_with_retry()
  أ¢â€‌â€‌أ¢â€‌â‚¬ If reconnect fails because cancellation/preemption was requested, the round exits as auto-pause/preemption instead of being counted as a hard failure
```

## 2026-04-27 Operational Notes (Phase 5/6)

- `SocketDicomClient.download_series` emits per-series `stage=dicom_file_write_batch` at WARNING level with `files`, `bytes`, and `disk_write_ms` so canonical `download_diagnostics.log` always carries write telemetry.
- KPI fields now expected from canonical parse: `dicom_file_write_batch_count`, `dicom_file_write_bytes_total`, and `dicom_file_write_ms_p95`.
- `SeriesIntentCoordinator.schedule_priority_start_retry` classifies recovery exhaustion as expected preemption when either `is_auto_paused` is true or state `error_message` contains `preemption`/`higher priority` markers.
- `_dm_workers._on_worker_error` keeps preemption-marker completions on the expected path (non-failure), while explicit user-cancel errors remain failure-visible.

### Priority-handoff diagnostic tag (F3.5.1, v2.4.7)

`SeriesIntentCoordinator._emit_intent_priority` produces a stable `[INTENT_PRIORITY]` log line at six points in the priority retry chain. Format:

```
[INTENT_PRIORITY] tag=<TAG> study=<UID> series=<SN> attempt=<N>/<M> recovery=<BOOL>
                  pool_busy=<BOOL> pool_capacity=<U>/<T> state=<S>
                  auto_paused=<BOOL> elapsed_ms=<INT> token=<INT> [branch=<B>]
```

Tags:

- `begin` — first chain entry, immediately after `_begin_priority_retry` reserves the token.
- `tick` — continuation entry within an active chain (verbose; gated by `AIPACS_INTENT_PRIORITY_TRACE=1`).
- `defer` — handoff has rescheduled itself because the worker pool is full or a reclamation race rejected the start (verbose; gated).
- `recover branch=primary` — primary 90×200ms chain expired, transitioning to recovery 3×3000ms chain.
- `exhaust branch=primary|recovery` — chain attempts hit the cap; emitted before classifying as auto-pause/preemption-expected.
- `started` — `start_download_worker` returned `True`; carries cumulative `elapsed_ms` from the `begin` event.

`tick` and `defer` are suppressed unless the env flag `AIPACS_INTENT_PRIORITY_TRACE=1` is set, so production logs stay quiet by default while still capturing all state transitions (`begin`, `recover`, `exhaust`, `started`). The KPI harness (`tools/performance/clearcanvas_aipacs_kpi_harness.py parse-priority-handoff-log`) consumes this format and produces `overlap_priority_handoff_latency_p50_ms`, `overlap_priority_handoff_latency_p95_ms`, `overlap_priority_handoff_pool_busy_ratio_pct`, and primary/recovery exhaust counts. Format is contract-tested by `tests/performance/test_priority_handoff_kpi_parser.py`; instrumentation behavior (begin → started, exhaust clears `_priority_retry_started_ms`, dedup) is verified by `tests/download_manager/test_priority_handoff_instrumentation.py`.

### V2 wall-clock priority-handoff retry (F3.5.2, v2.4.7 — default-off)

The legacy chain (90×200 ms primary + 5 s gap + 3×3000 ms recovery, total ~33 s) hard-exits as `recovery_exhaust` if the peer worker holds its slot longer than the budget. A second failure mode is the **reclamation race**: `WorkerPool.can_add_worker()` reports `True` while `_start_download_worker()` returns `False` because the rule engine has not yet finished freeing the prior worker — the legacy path silently treats this as a normal retry.

The V2 path replaces both with:

- A **wall-clock budget** (`INTENT_HANDOFF_HARD_TIMEOUT_MS = 60_000` ms) instead of an attempt cap.
- A **fixed tick cadence** (`INTENT_HANDOFF_V2_INTERVAL_MS = 250` ms) — no primary/recovery split, no 5 s deferred recovery gap.
- **Reclamation-race detection**: when `can_add_worker()=True` but `start_download_worker()=False`, the tick emits `tag=defer pool_busy=False branch=v2 reason=reclaimed`, sets `next_branch="reclaimed"`, AND nudges the central scheduler via `_defer(0, _start_next_pending)`.
- **CAS state promotion**: PAUSED→PENDING flips through the new `DownloadStateStore.update_if_status` helper, eliminating the read-modify-write race against concurrent state writers.
- **Four exhaust reasons**: `pool_busy` (budget elapsed while pool full), `reclaimed` (race never resolved), `state_lost` (state row vanished mid-chain), `timeout` (default fallback).

Activation gate: `AIPACS_INTENT_HANDOFF_V2=1` (default `0`). The fork is decided at chain start (`_token is None and _intent_handoff_v2_enabled()`), so legacy in-flight chains are not yanked mid-flight if the env flips.

KPI harness adds: `v2_begin_count`, `v2_started_count`, `v2_defer_reclaimed_count`, `v2_exhaust_pool_busy_count`, `v2_exhaust_reclaimed_count`, `v2_exhaust_state_lost_count`, `v2_exhaust_timeout_count`, `overlap_priority_handoff_v2_total_exhaust_count`. All zero on the legacy path.

Synthetic baselines (no Qt window, no real socket): `tools/performance/synthetic_priority_handoff_runner.py` drives 20 simulated CRITICAL promotions with a peer-held slot for 25 s and a 3-of-20 reclamation-race overlay. Output: `generated-files/benchmarks/priority_handoff_v2_pre.json` (env=0) and `priority_handoff_v2_post.json` (env=1). Pre baseline shows 20 `primary_exhaust` events (legacy 18 s primary cap is hit on every handoff before the 25 s peer release); post baseline shows 0 primary/recovery exhausts and 12 `v2_defer_reclaimed_count` (3 race-flagged handoffs × 4 ticks each in their 1 s reclamation window).

V2 path tests: `tests/download_manager/test_priority_handoff_v2.py` (9 tests). `update_if_status` CAS helper test: `tests/download_manager/test_priority_handoff_v2.py::test_update_if_status_cas_helper`. KPI parser V2 round-trips: `tests/performance/test_priority_handoff_kpi_parser.py` (10 V2 tests).

## Validation Rules (R17) أ¢â‚¬â€‌ Duplicate/Resume Detection

Located in `modules/download_manager/rules/validation_rules.py`:

### R17a أ¢â‚¬â€‌ In-Memory StateStore Check

Checks if a download already exists in the active StateStore:
- **Terminal states** (COMPLETED, CANCELLED): Block with `"Download already exists"` أ¢â‚¬â€‌ no re-download.
- **Non-terminal states** (PENDING, DOWNLOADING, PAUSED, FAILED): Return `should_resume=True` so the caller can resume instead of rejecting.

### R17b أ¢â‚¬â€‌ Persistent Database Check

If R17a passes (no active state), checks the DB for completed records:
- Queries DB status for the study_uid.
- If DB says "Completed", **verifies actual .dcm file counts on disk** per series directory against `image_count` from metadata.
- If any series directory has fewer `.dcm` files than expected, the download is allowed to proceed (overrides DB "Completed" status).
- This catches the scenario where DB marks a study complete but one or more series was only partially downloaded.

### Resume flow in main_widget.py

```
start_priority_download_immediately()
  أ¢â€‌إ“أ¢â€‌â‚¬ STEP 1: Build task
  أ¢â€‌إ“أ¢â€‌â‚¬ STEP 2: Validate (R17a/R17b)
  أ¢â€‌â€ڑ     أ¢â€‌إ“أ¢â€‌â‚¬ should_resume=True? أ¢â€ â€™ Fall through to STEP 3+ (resume)
  أ¢â€‌â€ڑ     أ¢â€‌â€‌أ¢â€‌â‚¬ blocked? أ¢â€ â€™ Return False (truly duplicate/completed)
  أ¢â€‌إ“أ¢â€‌â‚¬ STEP 3: gRPC metadata fetch
  أ¢â€‌إ“أ¢â€‌â‚¬ STEP 4: State update (reset progress counters for resume)
  أ¢â€‌â€‌أ¢â€‌â‚¬ STEP 5: Start worker
```

## Progressive Viewer Loading (v2.2.8.1)

When a patient tab is opened, the viewer progressively loads images as series download:

| Guard | Purpose |
|-------|---------|
| 100ms per-series throttle | Prevents CPU spike from rapid download progress signals (was 250ms pre-v2.2.8.1) |
| `_progressive_display_inflight` set | Prevents spawning duplicate concurrent load tasks for the same series |
| `_progressive_display_done` set | Marks series that completed initial display أ¢â‚¬â€‌ routes to grow path |
| Done-guard recovery | Re-activates progressive mode if guard says done but no progressive viewer exists |
| `finally` block cleanup | Ensures inflight guard is always cleared even on error |

**v2.2.8.1 Changes:**
- Progressive grow timer reduced: 500ms أ¢â€ â€™ 150ms
- Progress debounce reduced: 250ms أ¢â€ â€™ 100ms
- Done-guard ordering fixed: `done.add(sn)` now runs AFTER display+activation on main thread
- Stale guard: show-then-refresh (display immediately, background reload at +150ms)
- DM notify deferred: `QTimer.singleShot(0)` with 500ms cooldown per series
- Loading spinner: shown on target viewer for empty series drag-drop

Located in `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py`.

## Series-Interrupt (v2.2.8.1)

When user drag-drops a different series within the same study that's actively downloading:

1. `request_critical_series()` detects `current_series_number != requested_series`
2. Own worker is cancelled non-blocking (sets cancel flag, doesn't wait)
3. State overridden to PENDING (not PAUSED) أ¢â‚¬â€‌ so `_start_next_pending` picks it up
4. `negotiate_priority_change()` defers `_start_next_pending` + schedules retry backup
5. Result: ~batch RTT + 250ms to switch (was: wait for entire series to finish)

Located in `modules/download_manager/coordinator/series_intent_coordinator.py`.

## Critical Series Intent (FAST Viewer Drag/Drop) أ¢â‚¬â€‌ 2026-04-01 Hardening

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
- Reconnect and retry backoff sleeps are also cancellation-aware, so preempted workers stop waiting inside retry ladders and free slots sooner.

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
| Preemption during retry/reconnect backoff | Abort wait early, classify as auto-pause/preemption, and release worker path sooner |
| Series download failure | Per-series retry loop: 3 rounds with backoff (3sأ¢â€ â€™6sأ¢â€ â€™12s) |
| Partial download (app restart) | R17a detects non-terminal state أ¢â€ â€™ resume path |
| Partial download (retry button) | Per-patient: deletes complete series, keeps incomplete + R19b/R19 resume |
| DB says Complete but files missing | R17b filesystem verification أ¢â€ â€™ allows re-download |
| Disk full | Error state + user notification |
| Server unavailable | Queued for retry with backoff |
| Corrupt DICOM file | Skip file, log warning, continue series |
| Login failure | Fail-fast (no retry) |

## Stability Considerations

1. **Subprocess isolation**: Download runs in separate process with own GIL أ¢â‚¬â€‌ cannot block viewer
2. **Global counter**: Prevents ZetaBoost from competing for CPU during downloads
3. **Connection pool**: gRPC connections are pooled and reused
4. **State persistence**: Download progress survives app restart
5. **Priority management**: Subprocess runs at IDLE OS priority
6. **Progressive viewer throttle (v2.2.7+)**: 250ms debounce prevents CPU spike from rapid progress signals
7. **Retry jitter (v2.2.7+)**: Random jitter on reconnect delays prevents thundering herd on server recovery
8. **Filesystem truth (v2.2.7+)**: R17b verifies actual files on disk, not just DB state أ¢â‚¬â€‌ catches silent partial downloads
9. **Batch-skip on resume (v2.2.7.2; hardened v2.2.7.3)**: `download_series()` skips leading complete batches on partial resume أ¢â‚¬â€‌ now verifies actual sequential files instead of trusting file count alone
10. **Retry button preserves files (v2.2.7.2)**: Incomplete series are not deleted on retry أ¢â‚¬â€‌ the downloader resumes incrementally via R19b + R19
11. **Per-patient retry cleans complete series (v2.2.7.3)**: `_on_per_patient_retry()` deletes series directories where file count أ¢â€°آ¥ expected count أ¢â‚¬â€‌ prevents R20 from skipping series that the user wants re-downloaded
12. **Accurate skip counting (v2.2.7.3)**: Per-instance file-skip no longer double-counts pre-existing files أ¢â‚¬â€‌ progress and result counts are correct
13. **Non-blocking retry (v2.2.7.4)**: `_on_series_retry()` and `_on_per_patient_retry()` offload file I/O and gRPC calls to background threads أ¢â‚¬â€‌ the Qt event loop is never blocked by retry operations
14. **Non-blocking worker preemption (v2.2.7.4)**: `_pause_all_active_downloads()` uses `cancel_all_non_blocking()` instead of `stop_all()` أ¢â‚¬â€‌ avoids 5s/worker blocking on the main thread
15. **Module independence (v2.2.7.4)**: Download manager operations cannot freeze the viewer, thumbnails, or other modules أ¢â‚¬â€‌ all cross-thread marshaling uses `QTimer.singleShot(0, callback)`
16. **sendall() for all socket writes (v2.2.8.0)**: `PatientListSocketClient.send_request()` uses `sendall()` instead of `send()` أ¢â‚¬â€‌ prevents partial writes from corrupting framing on large payloads
17. **Exact-length recv (v2.2.8.0)**: `_recv_exact(size)` accumulates partial reads until the exact byte count is received أ¢â‚¬â€‌ prevents framing corruption on slow/congested networks
18. **Response size validation (v2.2.8.0)**: 50 MB limit on response allocation أ¢â‚¬â€‌ prevents unbounded memory growth from server bugs or corrupted length headers
19. **Lazy connection pool (v2.2.8.0)**: `SocketConnectionPool` creates connections on demand instead of eagerly at init أ¢â‚¬â€‌ validates `is_connected()` before returning pooled clients
20. **gRPC auto-reconnect (v2.2.8.0)**: `DicomGrpcClient._ensure_stub()` reconnects if channel/stub is `None` أ¢â‚¬â€‌ subsequent thumbnail calls succeed after transient failure
21. **No hardcoded server IPs (v2.2.8.0)**: `constants.py` defaults to `localhost` with `AIPACS_SOCKET_HOST` env var override أ¢â‚¬â€‌ production IPs come from config only
22. **Cancellation-aware retry backoff (2026-04-18)**: socket request, reconnect, and per-batch retry sleeps are sliced so cancel/preemption can break out before the next retry attempt; reconnect failures caused by cancellation now preserve the auto-paused/preemption path instead of being recorded as ordinary series failure

## Network Architecture Reference

For full details on wire protocol, authentication, connection pools, TCP tuning,
and the complete file map, see `docs/architecture/network-architecture.md`.

## Test Coverage

### Download Manager Tests (`tests/download_manager/test_download_manager.py`)

27 scenarios, 129 assertions. Run: `python tests/download_manager/run_dm_test.py`

| Scenario | What it tests |
|----------|---------------|
| S1 | State machine transitions: PENDINGأ¢â€ â€™DOWNLOADINGأ¢â€ â€™COMPLETED, FAILEDأ¢â€ â€™PENDING, PAUSEDأ¢â€ â€™PENDING |
| S2 | Priority preemption: HIGH pauses NORMAL, CRITICAL pauses all, resume order HIGHأ¢â€ â€™NORMAL |
| S3 | Disconnect/reconnect resume: socket failure أ¢â€ â€™ state preserved أ¢â€ â€™ resume path |
| S4 | R20 skip & retry file cleanup: series skip logic, per-patient retry file deletion |
| S5 | R19b verified batch-skip: sequential file verification, gap detection |
| S6 | State store thread safety: 8 threads ط£â€” 12 ops, no corruption |
| S7 | Observer fan-out: state changes propagate to all registered observers |
| S8 | Rule engine validation: R17a/R17b duplicate detection, resume detection |
| S9 | Skipped-count accuracy: existing_files_set prevents double-counting |
| S10 | Priority ordering: CRITICAL > HIGH > NORMAL sorting |
| S11 | State reset on resume: progress counters cleared on re-download |
| S12أ¢â‚¬â€œS21 | Additional state machine, retry, and error handling edge cases |
| S22 | Coordinator negotiate latency: priority change completes in <5ms |
| S23 | Observer priority chain: state change أ¢â€ â€™ priority change أ¢â€ â€™ UI refresh in sequence |
| S24 | Critical series roundtrip: request_critical_series أ¢â€ â€™ state=CRITICAL, viewed_series set |
| S25 | Rapid toggle stress: 100 rapid NORMALأ¢â€ â€‌CRITICAL toggles, state remains consistent |
| S26 | Auto-resume after critical done: peers resume when critical study completes |
| S27 | Series-interrupt: same-study worker cancelled, state=PENDING, viewed_series updated |

### Focused regression additions (2026-04-18)

- `tests/download_manager/test_socket_client_cancellation.py`
  - `test_connect_with_retry_stops_when_cancelled_during_backoff`
  - `test_send_request_stops_retry_when_cancelled_during_backoff`
  - `test_series_downloader_reconnect_cancel_returns_preempted_result`

### Stress Tests (`tests/download_manager/test_dm_stress.py`)

10 heavy-load scenarios, 31 pass / 1 expected fail. Run: `python tests/download_manager/test_dm_stress.py`

| Scenario | What it tests | KPI |
|----------|---------------|-----|
| H1 | 50 concurrent patient downloads | State store handles 50 entries in <100ms |
| H2 | 500 rapid series switches | Coordinator handles 500 priority changes in <5s |
| H3 | 16-thread ط£â€” 500 ops contention | P99 lock wait <5ms (expected fail: GIL contention) |
| H4 | 10,000 progress updates with observer fan-out | No dropped signals |
| H5 | 200 studies ط£â€” 20 series memory pressure | Memory stays bounded |
| H6 | Priority negotiation storm (all CRITICAL) | Coordinator resolves deterministically |
| H7 | 100 create/promote/complete/resume cycles | No state corruption |
| H8 | 10 studies ط£â€” 10 series ط£â€” 100 files I/O stress | All files created/verified |
| H9 | 1000 get_next_download under full store | Rule engine throughput >1000/s |
| H10 | Combined pipeline (priority + observer + coordinator + I/O) | End-to-end <10ms/op |

## 2026-05-24 Review & Fixes

A full review of the Zeta Download Manager was done on 2026-05-24. The as-built
review, fix plan, and implementation-progress record is
`docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`
(its §13 tracks applied vs outstanding work).

Applied this session: atomic `.part` + `os.replace()` DICOM/thumbnail writes;
resume-scan integrity check; final progress flush; DB lock-retry wrappers on
`initialize_study` / `batch_insert_instances`; dead-code quarantine; and a
`GetStudyInfo`-probe fix that cut patient-open → download-start from ~9 s to ~3 s.

**Transport note:** gRPC is **retired** — the active transport is socket
end-to-end. `GrpcMetadataClient` is socket-backed despite its name. See review
doc §15 for the full active-vs-retired path map.

Deferred / outstanding: review-doc steps S2.3, S2.5, S3.2–S3.5, Phase 4, and the
subprocess-spawn pre-warm.
