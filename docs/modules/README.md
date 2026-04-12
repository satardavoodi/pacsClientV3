# Module Catalog

> **Version:** v2.3.1 | **Updated:** 2026-04-13

## Active Modules

| Module | Purpose | Primary Code | Notes |
| --- | --- | --- | --- |
| Workstation shell | Main PACS desktop shell, auth, settings, home tab | `PacsClient/app_handler.py`, `PacsClient/pacs/workstation_ui/` | Entry from `main.py` |
| Viewer, fast | Lightweight 2D viewing paths for responsiveness (`pydicom_qt`, `pydicom_2d`) | `modules/viewer/fast/` | Optimized for software rendering and active download/progressive scenarios |
| Viewer, advanced | Full viewer path with richer tools and overlays (`vtk_simpleitk`) | `modules/viewer/advanced/` | VTK/SimpleITK rendering path |
| Download Manager | Download queueing, resumability, priority, worker orchestration | `modules/download_manager/` | See `docs/pipelines/download-pipeline.md` |
| Zeta Download Adapter | Legacy Zeta أ¢â€ â€‌ DM bridge, UI helpers | `PacsClient/zeta_download_manager/` | Local guide: `ZETA_DOWNLOAD_MANAGER_IMPLEMENTATION_GUIDE.md` |
| Zeta MPR | Advanced MPR implementation | `PacsClient/pacs/patient_tab/zeta mpr/` | Local guide: `PacsClient/pacs/patient_tab/zeta mpr/README.md` |
| Orthogonal MPR | Focused orthogonal MPR widget and helpers | `PacsClient/pacs/patient_tab/orthogonal_mpr/` | Used alongside toolbar workflows |
| Advanced imaging and AI | Imaging tabs, service tabs, analysis workflows | `PacsClient/pacs/patient_tab/ui/ai_module_ui/` | Includes service-driven imaging workflows |
| Education | Course browsing and educational case workflows | `PacsClient/pacs/education/`, `Education/` | Static assets in `education_assets/` |
| Web viewing | Embedded browser or web tab | `modules/web_browser/` | Integrated into workstation UI through a compatibility shim |
| Printing | Film layout, DICOM rendering, print dispatch | `printing/` | Data layer restored under `printing/data/` |
| EchoMind | AI chat, assistant orchestration, secretary routing | `EchoMind/` | Secretary docs under `EchoMind/secretary/` |
| Advanced 3D Slicer | Custom 3D Slicer SuperBuild for advanced MPR/3D viewing | `modules/mpr/advanced_3d_slicer/` | Local docs: `slicer_custom_app/docs/DEPLOYMENT_GUIDE.md`. Runtime (842 MB) is git-ignored; deploy via shared storage or GitHub Releases. |

## Installer and Module Delivery Model

For `v2.3.1`, the Windows installer is the canonical way to prepare AIPacs for another PC.

- `Core` install always delivers the workstation shell plus the required basic modules.
- `Custom` install asks the user which optional modules should be copied for that specific PC.
- Selected optional packages are copied into `{app}\module_packages\<module_id>`.
- The installer writes `installation_profile.json` so the first launch knows which modules were chosen.
- `main.py` calls `bootstrap_installer_selected_module_packages()` before optional module imports, so setup-selected packages are activated on first launch.
- Users can still add or change optional packages later from `Settings -> Installation Module`.

## Update Delivery Model

The release builder now emits a second deployment surface under `builder/output/updates/`.

- `update_feed.json` is the top-level catalog for update checks.
- `core/` contains the versioned installer copies used for workstation updates.
- `modules/` contains optional-module update packages that can be installed without rebuilding the entire workstation.

The running workstation reads:

- `installation_profile.json` / `runtime_profile.json` for the currently installed core and module versions
- `config/update_sources.json` for the active update source
- `update_feed.json` from either a local folder or a hosted URL

Core/basic modules remain tied to the workstation installer, while optional modules can be updated from package artifacts.

Core modules delivered on every PC:

- Viewer
- Download Manager
- ZetaBoost
- Education Module
- Stitching Module
- Offline Cloud Server

Optional modules selectable during setup:

- Advanced MPR
- Printing
- Run CD
- Web Browser
- EchoMind

## Download Manager أ¢â‚¬â€‌ Internal Structure (v2.3.1)

The download manager is the most architecturally complex module. It uses a
**State Machine + Rule Engine + Thin Coordinator** pattern.

```
modules/download_manager/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ core/                           # Foundation types
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ constants.py                # Retry delays, batch sizes, timeouts
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ enums.py                    # DownloadStatus, DownloadPriority
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ models.py                   # DownloadTask, SeriesInfo dataclasses
أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ exceptions.py               # Custom exception hierarchy
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ state/                          # State management (thread-safe)
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ state_store.py              # DownloadStateStore أ¢â‚¬â€‌ in-memory dict + Lock
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ state_machine.py            # Status transition rules & guards
أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ observers.py                # UIObserver أ¢â‚¬â€‌ stateأ¢â€ â€™UI refresh bridge
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ coordinator/                    # Intent management
أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ series_intent_coordinator.py # Priority negotiation, series-interrupt,
أ¢â€‌â€ڑ                                    # viewed-series tracking, retry scheduling
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ rules/                          # Business rules (pure functions)
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ rule_engine.py              # DownloadRuleEngine أ¢â‚¬â€‌ orchestrates rules
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ validation_rules.py         # R17a (StateStore), R17b (DB+filesystem)
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ priority_rules.py           # Priority ordering, preemption logic
أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ resume_rules.py             # Resume eligibility, batch-skip (R19b)
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ download/                       # Execution layer
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ executor.py                 # DownloadExecutor أ¢â‚¬â€‌ validateأ¢â€ â€™fetchأ¢â€ â€™download
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ series_downloader.py        # Per-series download with retry rounds
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ batch_processor.py          # Batch-level I/O, file-skip (R19)
أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ progress_tracker.py         # Progress aggregation and signal emission
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ network/                        # Server communication (download path)
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ socket_client.py            # SocketDicomClient أ¢â‚¬â€‌ resumable download
أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ health_monitor.py           # ConnectionHealthMonitor (R30-R34)
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ workers/                        # Subprocess workers
أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ worker.py                   # DownloadProcessWorker (own GIL, IDLE priority)
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ storage/                        # File management
أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ ...                         # Directory creation, validation, cleanup
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ ui/                             # Qt widgets
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ main_widget.py              # DownloadManagerWidget أ¢â‚¬â€‌ worker pool, timers
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ components/                 # Table rows, progress bars, buttons
أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ dialogs/                    # Confirmation dialogs
أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ styles/                     # QSS stylesheets
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ utils/                          # Shared helpers
```

### DM Signal Flow

```
User opens study (HomePanelWidget)
  أ¢â€‌â€ڑ
  أ¢â€“آ¼
HomeDownloadService.get_or_create_download_manager_tab()
  أ¢â€‌â€ڑ
  أ¢â€“آ¼
DownloadManagerWidget.start_priority_download_immediately()
  أ¢â€‌إ“أ¢â€‌â‚¬ RuleEngine.validate() أ¢â€ â€™ R17a/R17b
  أ¢â€‌إ“أ¢â€‌â‚¬ gRPC metadata fetch
  أ¢â€‌إ“أ¢â€‌â‚¬ StateStore.create() أ¢â€ â€™ state=PENDING
  أ¢â€‌â€‌أ¢â€‌â‚¬ Worker pool أ¢â€ â€™ start DownloadProcessWorker (subprocess)
      أ¢â€‌â€ڑ
      أ¢â€‌إ“أ¢â€‌â‚¬ seriesProgressUpdated signal أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€“آ¶ ViewerController.on_series_images_progress()
      أ¢â€‌â€ڑ                                        أ¢â€‌â€ڑ
      أ¢â€‌â€ڑ                                        أ¢â€‌إ“أ¢â€‌â‚¬ First batch: _start_progressive_display()
      أ¢â€‌â€ڑ                                        أ¢â€‌â€‌أ¢â€‌â‚¬ Subsequent: _grow_progressive_fast()
      أ¢â€‌â€ڑ
      أ¢â€‌إ“أ¢â€‌â‚¬ Worker completed أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€“آ¶ _on_worker_completed()
      أ¢â€‌â€ڑ                            أ¢â€‌â€‌أ¢â€‌â‚¬ QTimer.singleShot(0, _start_next_pending)
      أ¢â€‌â€ڑ
      أ¢â€‌â€‌أ¢â€‌â‚¬ Worker error أ¢â€‌â‚¬أ¢â€‌â‚¬أ¢â€“آ¶ _on_worker_error()
                              أ¢â€‌â€‌أ¢â€‌â‚¬ QTimer.singleShot(0, _start_next_pending)
```

### Priority & Series-Interrupt Flow (v2.2.8.1)

```
User drag-drops series S5 (while S3 is downloading)
  أ¢â€‌â€ڑ
  أ¢â€“آ¼
ViewerController._notify_dm_viewed_series()  [deferred via QTimer.singleShot(0)]
  أ¢â€‌â€ڑ                                           [500ms per-series cooldown]
  أ¢â€“آ¼
DownloadManagerWidget.set_viewed_series()
  أ¢â€‌â€ڑ
  أ¢â€“آ¼
SeriesIntentCoordinator.request_critical_series()
  أ¢â€‌إ“أ¢â€‌â‚¬ StateStore.update(priority=CRITICAL, viewed_series='5')
  أ¢â€‌إ“أ¢â€‌â‚¬ Same study, different series? أ¢â€ â€™ Cancel own worker (non-blocking)
  أ¢â€‌â€ڑ                                  Set state=PENDING (not PAUSED)
  أ¢â€‌إ“أ¢â€‌â‚¬ negotiate_priority_change()
  أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬ Pause lower-priority peers (is_auto_paused=True)
  أ¢â€‌â€ڑ   أ¢â€‌إ“أ¢â€‌â‚¬ defer _start_next_pending via QTimer.singleShot(50)
  أ¢â€‌â€ڑ   أ¢â€‌â€‌أ¢â€‌â‚¬ schedule_priority_start_retry(200ms) as backup
  أ¢â€‌â€‌أ¢â€‌â‚¬ UIObserver أ¢â€ â€™ refresh_table_order() [0ms, next tick]
```

## Supporting Layers

### Database

- connection pool and schema management: `database/core.py`
- query helpers and CRUD: `database/manager.py`
- migrations: `database/migrations/`
- context manager: `get_db_connection()` with explicit commit required
- See `docs/architecture/database-architecture.md`

### Network

- socket facade: `modules/network/socket_service.py` (singleton)
- patient list client: `modules/network/socket_client.py` (pooled)
- download client: `modules/download_manager/network/socket_client.py`
- gRPC client: `modules/network/grpc_client.py` (auto-reconnect)
- config: `modules/network/socket_config.py` + `config/socket_config.json`
- token: `modules/network/socket_token_manager.py` (JWT singleton)
- See `docs/architecture/network-architecture.md`

### Cache and Storage

- thumbnails: `thumbnails/`
- attachments and filming pages: `attachment/`
- generated performance output: `generated-files/`
- boosted viewer cache logic: `PacsClient/pacs/patient_tab/zeta_boost/`

### Home UI Service Layer

- thin controller: `PacsClient/pacs/workstation_ui/home_ui/home_ui.py`
- DB service: `home_db_service.py`
- tab service: `home_tab_service.py`
- download service: `home_download_service.py`
- search service: `home_search_service.py`
- See `docs/architecture/home-ui-services.md`

## Viewer Module أ¢â‚¬â€‌ Internal Structure

The viewer has three rendering paths:

### Fast Viewer (primary for download-time browsing)
```
modules/viewer/fast/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ contracts.py                 # IViewer2DBackend (Protocol), FrameData, GeometryData
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ lightweight_2d_pipeline.py   # Lightweight2DPipeline أ¢â‚¬â€‌ main fast render
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ pydicom_2d_backend.py        # PyDicom2DBackend أ¢â‚¬â€‌ slice extraction from pydicom
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ pydicom_lazy_volume.py       # PyDicomLazyVolume أ¢â‚¬â€‌ progressive loading (grows on signal)
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ qt_slice_viewer.py           # QtSliceViewer أ¢â‚¬â€‌ Qt widget, no VTK dependency
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ qt_viewer_bridge.py          # QtViewerBridge أ¢â‚¬â€‌ adapts Qt viewer to VTK API
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ stale_frame_guard.py         # Detects stale cached frames vs disk
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ lazy_volume_registry.py      # Registry of loaded volumes
```

### Advanced Viewer (measurement tools, 3D)
```
modules/viewer/advanced/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ viewer_2d.py                 # Base advanced 2D viewer
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ viewer_2d_optimized.py       # Optimized variant
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ viewer_2d_with_tools.py      # Viewer2DWithTools أ¢â‚¬â€‌ adds ruler/angle/ROI
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ viewer_3d.py                 # Viewer3DWidget أ¢â‚¬â€‌ 3D volume rendering
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ vtk_3d_presets.py            # VolumePresetConfig أ¢â‚¬â€‌ bone, soft tissue, etc.
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ filter_config_widget.py      # FilterConfigWidget UI
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ image_filter_sidebar.py      # Filter sidebar
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ preset_manager.py            # User preset management
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ advanced_tools_panel.py      # Toolbar for advanced features
```

### Pipeline Orchestration
```
modules/viewer/pipeline/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ orchestrator.py              # PipelineOrchestrator, PipelineState enum
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ load_coordinator.py          # LoadCoordinator أ¢â‚¬â€‌ dedup in-flight loads
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ preview_engine.py            # PreviewEngine أ¢â‚¬â€‌ quick preview before full load
```

### Widget Helpers
```
modules/viewer/widgets/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ loading_spinner.py           # LoadingSpinner, ViewportSpinner
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ medical_loading_overlay.py   # MedicalLoadingOverlay
```

### Interactor Styles (Measurement Tools)
```
modules/viewer/interactor_styles/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ abstract_interactorstyle.py     # AbstractInteractorStyle أ¢â‚¬â€‌ base class
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ ruler_interactorstyle.py        # Distance measurement
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ angle_interactorstyle.py        # Angle measurement
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ two_line_angle_interactorstyle.py # Cobb angle
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ arrow_interactorstyle.py        # Arrow annotation
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ text_interactorstyle.py         # Text annotation
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ roi_interactorstyle.py          # Region of interest with statistics
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ roi_with_segment.py             # ROI with AI segmentation overlay
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ eraser_interactorstyle.py       # Annotation eraser
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ default_interaction_interactorstyle.py # Default pan/zoom/scroll
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ rotate_interactorstyles.py      # Image rotation
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ ai_chat_interactorstyle.py      # AI click-on-image integration
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ tools_object_manager.py         # All tool data objects (RulerObject, etc.)
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ interactor_utils/               # Shared math helpers
```

## ZetaSync Module

Cross-viewer synchronization (linked scroll, W/L sync):

```
modules/zeta_sync/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ sync_manager.py    # SyncManager أ¢â‚¬â€‌ orchestrates cross-viewer sync
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ sync_context.py    # Sync state context (active groups, modes)
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ sync_types.py      # Type definitions for sync messages
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ geometry_utils.py  # IPP-based position calculation
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ adapters.md        # Integration guide for new viewer types
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ README.md          # Module documentation
```

## Storage Module

Disk management and cleanup:

```
modules/storage/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ disk_alert_service.py                # Low disk space warnings
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ local_storage_cleanup_manager.py     # Automated DICOM cleanup
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ patient_cleanup_manager.py           # Per-patient file removal
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ storage_calculator.py                # Disk usage scanning
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ thumbnail_store.py                   # Thumbnail storage management
```

## Stitching Module

Long-bone / panorama image stitching:

```
modules/stitching/
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ stitching_widget.py           # StitchingWidget أ¢â‚¬â€‌ main UI
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ stitch_controller.py          # StitchController أ¢â‚¬â€‌ orchestration
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ stitch_engine.py              # StitchEngine أ¢â‚¬â€‌ image composition
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ stitch_worker.py              # Background processing thread
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ blend_engine.py               # Multi-image blending
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ canvas_builder.py             # Output canvas construction
أ¢â€‌إ“أ¢â€‌â‚¬أ¢â€‌â‚¬ landmark_store.py             # LandmarkStore أ¢â‚¬â€‌ alignment points
أ¢â€‌â€‌أ¢â€‌â‚¬أ¢â€‌â‚¬ landmark_interactor_style.py  # VTK interaction for placing landmarks
```

## Module-to-Database Contract

The expected dependency direction is:

1. module UI
2. module application service or repository
3. database or filesystem
4. render or business logic output back to UI

Direct UI-to-database code still exists in older areas, but new work should prefer repository-style modules like `printing/data/`.

## Module Configuration Reference

Each module reads config from `config/` JSON files:

| Module | Config file | Key settings |
|--------|------------|-------------|
| Viewer | `viewer_backend_settings.json` | Backend selection (fast vs advanced) |
| ZetaBoost | `boostviewer_settings.json` | Cache sizes, thread counts, prefetch |
| Grid layout | `modality_grid.json` | Default grid per modality (CT=1ط£â€”1, MR=2ط£â€”2) |
| Filters | `filter_presets.json`, `filter_settings.json` | Filter chains and defaults |
| Network | `socket_config.json` | Server host/port/timeout |
| Printing | `printing_config.json` | Paper size, DPI, layout |
| Module system | `installation_profile.json` | Enabled/disabled modules |
| External PACS | `external_pacs_servers.json` | External PACS server list |
| Patient table | `patient_table_columns.json`, `patient_table_font.json`, `patient_table_sort.json` | Table display config |

## Local Documentation Policy

- Keep package-local docs only when they explain a package that is independently complex.
- Prefer linking local docs from this catalog instead of duplicating architecture notes in multiple places.
- Archive time-bound investigation notes under `docs/archive/` when they stop being operationally useful.
