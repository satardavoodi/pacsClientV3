# Module Catalog

> **Version:** v2.3.0 | **Updated:** 2026-04-04

## Active Modules

| Module | Purpose | Primary Code | Notes |
| --- | --- | --- | --- |
| Workstation shell | Main PACS desktop shell, auth, settings, home tab | `PacsClient/app_handler.py`, `PacsClient/pacs/workstation_ui/` | Entry from `main.py` |
| Viewer, fast | Lightweight 2D viewing path for responsiveness | `PacsClient/pacs/patient_tab/viewers/lightweight_2d_pipeline.py` | Optimized for software rendering and active download cases |
| Viewer, advanced | Full viewer path with richer tools and overlays | `PacsClient/pacs/patient_tab/viewers/viewer_2d.py` | Backed by `viewers/backends/` |
| Download Manager | Download queueing, resumability, priority, worker orchestration | `modules/download_manager/` | See `docs/pipelines/download-pipeline.md` |
| Zeta Download Adapter | Legacy Zeta ↔ DM bridge, UI helpers | `PacsClient/zeta_download_manager/` | Local guide: `ZETA_DOWNLOAD_MANAGER_IMPLEMENTATION_GUIDE.md` |
| Zeta MPR | Advanced MPR implementation | `PacsClient/pacs/patient_tab/zeta mpr/` | Local guide: `PacsClient/pacs/patient_tab/zeta mpr/README.md` |
| Orthogonal MPR | Focused orthogonal MPR widget and helpers | `PacsClient/pacs/patient_tab/orthogonal_mpr/` | Used alongside toolbar workflows |
| Advanced imaging and AI | Imaging tabs, service tabs, analysis workflows | `PacsClient/pacs/patient_tab/ui/ai_module_ui/` | Includes service-driven imaging workflows |
| Education | Course browsing and educational case workflows | `PacsClient/pacs/education/`, `Education/` | Static assets in `education_assets/` |
| Web viewing | Embedded browser or web tab | `modules/web_browser/` | Integrated into workstation UI through a compatibility shim |
| Printing | Film layout, DICOM rendering, print dispatch | `printing/` | Data layer restored under `printing/data/` |
| EchoMind | AI chat, assistant orchestration, secretary routing | `EchoMind/` | Secretary docs under `EchoMind/secretary/` |
| Advanced 3D Slicer | Custom 3D Slicer SuperBuild for advanced MPR/3D viewing | `modules/mpr/advanced_3d_slicer/` | Local docs: `slicer_custom_app/docs/DEPLOYMENT_GUIDE.md`. Runtime (842 MB) is git-ignored; deploy via shared storage or GitHub Releases. |

## Installer and Module Delivery Model

For `v2.3.0`, the Windows installer is the canonical way to prepare AIPacs for another PC.

- `Core` install always delivers the workstation shell plus the required basic modules.
- `Custom` install asks the user which optional modules should be copied for that specific PC.
- Selected optional packages are copied into `{app}\module_packages\<module_id>`.
- The installer writes `installation_profile.json` so the first launch knows which modules were chosen.
- `main.py` calls `bootstrap_installer_selected_module_packages()` before optional module imports, so setup-selected packages are activated on first launch.
- Users can still add or change optional packages later from `Settings -> Installation Module`.

Core modules delivered on every PC:

- Viewer
- Download Manager
- ZetaBoost
- Education Module
- Stitching Module

Optional modules selectable during setup:

- Advanced MPR
- Printing
- Run CD
- Web Browser
- EchoMind

## Download Manager — Internal Structure (v2.3.0)

The download manager is the most architecturally complex module. It uses a
**State Machine + Rule Engine + Thin Coordinator** pattern.

```
modules/download_manager/
├── core/                           # Foundation types
│   ├── constants.py                # Retry delays, batch sizes, timeouts
│   ├── enums.py                    # DownloadStatus, DownloadPriority
│   ├── models.py                   # DownloadTask, SeriesInfo dataclasses
│   └── exceptions.py               # Custom exception hierarchy
├── state/                          # State management (thread-safe)
│   ├── state_store.py              # DownloadStateStore — in-memory dict + Lock
│   ├── state_machine.py            # Status transition rules & guards
│   └── observers.py                # UIObserver — state→UI refresh bridge
├── coordinator/                    # Intent management
│   └── series_intent_coordinator.py # Priority negotiation, series-interrupt,
│                                    # viewed-series tracking, retry scheduling
├── rules/                          # Business rules (pure functions)
│   ├── rule_engine.py              # DownloadRuleEngine — orchestrates rules
│   ├── validation_rules.py         # R17a (StateStore), R17b (DB+filesystem)
│   ├── priority_rules.py           # Priority ordering, preemption logic
│   └── resume_rules.py             # Resume eligibility, batch-skip (R19b)
├── download/                       # Execution layer
│   ├── executor.py                 # DownloadExecutor — validate→fetch→download
│   ├── series_downloader.py        # Per-series download with retry rounds
│   ├── batch_processor.py          # Batch-level I/O, file-skip (R19)
│   └── progress_tracker.py         # Progress aggregation and signal emission
├── network/                        # Server communication (download path)
│   ├── socket_client.py            # SocketDicomClient — resumable download
│   └── health_monitor.py           # ConnectionHealthMonitor (R30-R34)
├── workers/                        # Subprocess workers
│   └── worker.py                   # DownloadProcessWorker (own GIL, IDLE priority)
├── storage/                        # File management
│   └── ...                         # Directory creation, validation, cleanup
├── ui/                             # Qt widgets
│   ├── main_widget.py              # DownloadManagerWidget — worker pool, timers
│   ├── components/                 # Table rows, progress bars, buttons
│   ├── dialogs/                    # Confirmation dialogs
│   └── styles/                     # QSS stylesheets
└── utils/                          # Shared helpers
```

### DM Signal Flow

```
User opens study (HomePanelWidget)
  │
  ▼
HomeDownloadService.get_or_create_download_manager_tab()
  │
  ▼
DownloadManagerWidget.start_priority_download_immediately()
  ├─ RuleEngine.validate() → R17a/R17b
  ├─ gRPC metadata fetch
  ├─ StateStore.create() → state=PENDING
  └─ Worker pool → start DownloadProcessWorker (subprocess)
      │
      ├─ seriesProgressUpdated signal ──▶ ViewerController.on_series_images_progress()
      │                                        │
      │                                        ├─ First batch: _start_progressive_display()
      │                                        └─ Subsequent: _grow_progressive_fast()
      │
      ├─ Worker completed ──▶ _on_worker_completed()
      │                            └─ QTimer.singleShot(0, _start_next_pending)
      │
      └─ Worker error ──▶ _on_worker_error()
                              └─ QTimer.singleShot(0, _start_next_pending)
```

### Priority & Series-Interrupt Flow (v2.2.8.1)

```
User drag-drops series S5 (while S3 is downloading)
  │
  ▼
ViewerController._notify_dm_viewed_series()  [deferred via QTimer.singleShot(0)]
  │                                           [500ms per-series cooldown]
  ▼
DownloadManagerWidget.set_viewed_series()
  │
  ▼
SeriesIntentCoordinator.request_critical_series()
  ├─ StateStore.update(priority=CRITICAL, viewed_series='5')
  ├─ Same study, different series? → Cancel own worker (non-blocking)
  │                                  Set state=PENDING (not PAUSED)
  ├─ negotiate_priority_change()
  │   ├─ Pause lower-priority peers (is_auto_paused=True)
  │   ├─ defer _start_next_pending via QTimer.singleShot(50)
  │   └─ schedule_priority_start_retry(200ms) as backup
  └─ UIObserver → refresh_table_order() [0ms, next tick]
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

## Viewer Module — Internal Structure

The viewer has three rendering paths:

### Fast Viewer (primary for download-time browsing)
```
modules/viewer/fast/
├── contracts.py                 # IViewer2DBackend (Protocol), FrameData, GeometryData
├── lightweight_2d_pipeline.py   # Lightweight2DPipeline — main fast render
├── pydicom_2d_backend.py        # PyDicom2DBackend — slice extraction from pydicom
├── pydicom_lazy_volume.py       # PyDicomLazyVolume — progressive loading (grows on signal)
├── qt_slice_viewer.py           # QtSliceViewer — Qt widget, no VTK dependency
├── qt_viewer_bridge.py          # QtViewerBridge — adapts Qt viewer to VTK API
├── stale_frame_guard.py         # Detects stale cached frames vs disk
└── lazy_volume_registry.py      # Registry of loaded volumes
```

### Advanced Viewer (measurement tools, 3D)
```
modules/viewer/advanced/
├── viewer_2d.py                 # Base advanced 2D viewer
├── viewer_2d_optimized.py       # Optimized variant
├── viewer_2d_with_tools.py      # Viewer2DWithTools — adds ruler/angle/ROI
├── viewer_3d.py                 # Viewer3DWidget — 3D volume rendering
├── vtk_3d_presets.py            # VolumePresetConfig — bone, soft tissue, etc.
├── filter_config_widget.py      # FilterConfigWidget UI
├── image_filter_sidebar.py      # Filter sidebar
├── preset_manager.py            # User preset management
└── advanced_tools_panel.py      # Toolbar for advanced features
```

### Pipeline Orchestration
```
modules/viewer/pipeline/
├── orchestrator.py              # PipelineOrchestrator, PipelineState enum
├── load_coordinator.py          # LoadCoordinator — dedup in-flight loads
└── preview_engine.py            # PreviewEngine — quick preview before full load
```

### Widget Helpers
```
modules/viewer/widgets/
├── loading_spinner.py           # LoadingSpinner, ViewportSpinner
└── medical_loading_overlay.py   # MedicalLoadingOverlay
```

### Interactor Styles (Measurement Tools)
```
modules/viewer/interactor_styles/
├── abstract_interactorstyle.py     # AbstractInteractorStyle — base class
├── ruler_interactorstyle.py        # Distance measurement
├── angle_interactorstyle.py        # Angle measurement
├── two_line_angle_interactorstyle.py # Cobb angle
├── arrow_interactorstyle.py        # Arrow annotation
├── text_interactorstyle.py         # Text annotation
├── roi_interactorstyle.py          # Region of interest with statistics
├── roi_with_segment.py             # ROI with AI segmentation overlay
├── eraser_interactorstyle.py       # Annotation eraser
├── default_interaction_interactorstyle.py # Default pan/zoom/scroll
├── rotate_interactorstyles.py      # Image rotation
├── ai_chat_interactorstyle.py      # AI click-on-image integration
├── tools_object_manager.py         # All tool data objects (RulerObject, etc.)
└── interactor_utils/               # Shared math helpers
```

## ZetaSync Module

Cross-viewer synchronization (linked scroll, W/L sync):

```
modules/zeta_sync/
├── sync_manager.py    # SyncManager — orchestrates cross-viewer sync
├── sync_context.py    # Sync state context (active groups, modes)
├── sync_types.py      # Type definitions for sync messages
├── geometry_utils.py  # IPP-based position calculation
├── adapters.md        # Integration guide for new viewer types
└── README.md          # Module documentation
```

## Storage Module

Disk management and cleanup:

```
modules/storage/
├── disk_alert_service.py                # Low disk space warnings
├── local_storage_cleanup_manager.py     # Automated DICOM cleanup
├── patient_cleanup_manager.py           # Per-patient file removal
├── storage_calculator.py                # Disk usage scanning
└── thumbnail_store.py                   # Thumbnail storage management
```

## Stitching Module

Long-bone / panorama image stitching:

```
modules/stitching/
├── stitching_widget.py           # StitchingWidget — main UI
├── stitch_controller.py          # StitchController — orchestration
├── stitch_engine.py              # StitchEngine — image composition
├── stitch_worker.py              # Background processing thread
├── blend_engine.py               # Multi-image blending
├── canvas_builder.py             # Output canvas construction
├── landmark_store.py             # LandmarkStore — alignment points
└── landmark_interactor_style.py  # VTK interaction for placing landmarks
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
| Grid layout | `modality_grid.json` | Default grid per modality (CT=1×1, MR=2×2) |
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
