# Module Catalog

> **Version:** v2.3.3 | **Updated:** 2026-04-14

## Active Modules

| Module | Purpose | Primary Code | Notes |
| --- | --- | --- | --- |
| Workstation shell | Main PACS desktop shell, auth, settings, home tab | `PacsClient/app_handler.py`, `PacsClient/pacs/workstation_ui/` | Entry from `main.py` |
| Viewer, fast | Lightweight 2D viewing paths for responsiveness (`pydicom_qt`, `pydicom_2d`) | `modules/viewer/fast/` | Optimized for software rendering and active download/progressive scenarios |
| Viewer, advanced | Full viewer path with richer tools and overlays (`vtk_simpleitk`) | `modules/viewer/advanced/` | VTK/SimpleITK rendering path |
| Download Manager | Download queueing, resumability, priority, worker orchestration | `modules/download_manager/` | See `docs/pipelines/download-pipeline.md` |
| Zeta Download Adapter | Legacy Zeta ط£آ¢أ¢â‚¬آ أ¢â‚¬â€Œ DM bridge, UI helpers | `PacsClient/zeta_download_manager/` | Local guide: `ZETA_DOWNLOAD_MANAGER_IMPLEMENTATION_GUIDE.md` |
| Zeta MPR | Advanced MPR implementation | `PacsClient/pacs/patient_tab/zeta mpr/` | Local guide: `PacsClient/pacs/patient_tab/zeta mpr/README.md` |
| Orthogonal MPR | Focused orthogonal MPR widget and helpers | `PacsClient/pacs/patient_tab/orthogonal_mpr/` | Used alongside toolbar workflows |
| Advanced imaging and AI | Imaging tabs, service tabs, analysis workflows | `PacsClient/pacs/patient_tab/ui/ai_module_ui/` | Includes service-driven imaging workflows |
| Education | Course browsing and educational case workflows | `PacsClient/pacs/education/`, `Education/` | Static assets in `education_assets/` |
| Web viewing | Embedded browser or web tab | `modules/web_browser/` | Integrated into workstation UI through a compatibility shim |
| Printing | Film layout, DICOM rendering, print dispatch | `printing/` | Data layer restored under `printing/data/` |
| EchoMind | AI chat, assistant orchestration, secretary routing | `EchoMind/` | Secretary docs under `EchoMind/secretary/` |
| Advanced 3D Slicer | Custom 3D Slicer SuperBuild for advanced MPR/3D viewing | `modules/mpr/advanced_3d_slicer/` | Local docs: `slicer_custom_app/docs/DEPLOYMENT_GUIDE.md`. Runtime (842 MB) is git-ignored; deploy via shared storage or GitHub Releases. |

## Installer and Module Delivery Model

For `v2.3.3`, the Windows installer is the canonical way to prepare AIPacs for another PC.

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

## Download Manager ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ Internal Structure (v2.3.3)

The download manager is the most architecturally complex module. It uses a
**State Machine + Rule Engine + Thin Coordinator** pattern.

```
modules/download_manager/
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ core/                           # Foundation types
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ constants.py                # Retry delays, batch sizes, timeouts
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ enums.py                    # DownloadStatus, DownloadPriority
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ models.py                   # DownloadTask, SeriesInfo dataclasses
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ exceptions.py               # Custom exception hierarchy
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ state/                          # State management (thread-safe)
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ state_store.py              # DownloadStateStore ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ in-memory dict + Lock
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ state_machine.py            # Status transition rules & guards
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ observers.py                # UIObserver ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ stateط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢UI refresh bridge
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ coordinator/                    # Intent management
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ series_intent_coordinator.py # Priority negotiation, series-interrupt,
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘                                    # viewed-series tracking, retry scheduling
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ rules/                          # Business rules (pure functions)
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ rule_engine.py              # DownloadRuleEngine ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ orchestrates rules
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ validation_rules.py         # R17a (StateStore), R17b (DB+filesystem)
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ priority_rules.py           # Priority ordering, preemption logic
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ resume_rules.py             # Resume eligibility, batch-skip (R19b)
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ download/                       # Execution layer
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ executor.py                 # DownloadExecutor ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ validateط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢fetchط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢download
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ series_downloader.py        # Per-series download with retry rounds
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ batch_processor.py          # Batch-level I/O, file-skip (R19)
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ progress_tracker.py         # Progress aggregation and signal emission
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ network/                        # Server communication (download path)
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ socket_client.py            # SocketDicomClient ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ resumable download
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ health_monitor.py           # ConnectionHealthMonitor (R30-R34)
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ workers/                        # Subprocess workers
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ worker.py                   # DownloadProcessWorker (own GIL, IDLE priority)
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ storage/                        # File management
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ...                         # Directory creation, validation, cleanup
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ui/                             # Qt widgets
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ main_widget.py              # DownloadManagerWidget ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ worker pool, timers
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ components/                 # Table rows, progress bars, buttons
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ dialogs/                    # Confirmation dialogs
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ styles/                     # QSS stylesheets
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ utils/                          # Shared helpers
```

### DM Signal Flow

```
User opens study (HomePanelWidget)
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘
  ط£آ¢أ¢â‚¬â€œط¢آ¼
HomeDownloadService.get_or_create_download_manager_tab()
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘
  ط£آ¢أ¢â‚¬â€œط¢آ¼
DownloadManagerWidget.start_priority_download_immediately()
  ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ RuleEngine.validate() ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ R17a/R17b
  ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ gRPC metadata fetch
  ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ StateStore.create() ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ state=PENDING
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ Worker pool ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ start DownloadProcessWorker (subprocess)
      ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘
      ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ seriesProgressUpdated signal ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€œط¢آ¶ ViewerController.on_series_images_progress()
      ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘                                        ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘
      ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘                                        ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ First batch: _start_progressive_display()
      ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘                                        ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ Subsequent: _grow_progressive_fast()
      ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘
      ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ Worker completed ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€œط¢آ¶ _on_worker_completed()
      ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘                            ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ QTimer.singleShot(0, _start_next_pending)
      ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘
      ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ Worker error ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€œط¢آ¶ _on_worker_error()
                              ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ QTimer.singleShot(0, _start_next_pending)
```

### Priority & Series-Interrupt Flow (v2.2.8.1)

```
User drag-drops series S5 (while S3 is downloading)
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘
  ط£آ¢أ¢â‚¬â€œط¢آ¼
ViewerController._notify_dm_viewed_series()  [deferred via QTimer.singleShot(0)]
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘                                           [500ms per-series cooldown]
  ط£آ¢أ¢â‚¬â€œط¢آ¼
DownloadManagerWidget.set_viewed_series()
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘
  ط£آ¢أ¢â‚¬â€œط¢آ¼
SeriesIntentCoordinator.request_critical_series()
  ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ StateStore.update(priority=CRITICAL, viewed_series='5')
  ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ Same study, different series? ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ Cancel own worker (non-blocking)
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘                                  Set state=PENDING (not PAUSED)
  ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ negotiate_priority_change()
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ Pause lower-priority peers (is_auto_paused=True)
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ defer _start_next_pending via QTimer.singleShot(50)
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬ع‘   ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ schedule_priority_start_retry(200ms) as backup
  ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ UIObserver ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ refresh_table_order() [0ms, next tick]
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

## Viewer Module ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ Internal Structure

The viewer has three rendering paths:

### Fast Viewer (primary for download-time browsing)
```
modules/viewer/fast/
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ contracts.py                 # IViewer2DBackend (Protocol), FrameData, GeometryData
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ lightweight_2d_pipeline.py   # Lightweight2DPipeline ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ main fast render
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ pydicom_2d_backend.py        # PyDicom2DBackend ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ slice extraction from pydicom
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ pydicom_lazy_volume.py       # PyDicomLazyVolume ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ progressive loading (grows on signal)
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ qt_slice_viewer.py           # QtSliceViewer ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ Qt widget, no VTK dependency
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ qt_viewer_bridge.py          # QtViewerBridge ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ adapts Qt viewer to VTK API
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ stale_frame_guard.py         # Detects stale cached frames vs disk
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ lazy_volume_registry.py      # Registry of loaded volumes
```

### Advanced Viewer (measurement tools, 3D)
```
modules/viewer/advanced/
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ viewer_2d.py                 # Base advanced 2D viewer
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ viewer_2d_optimized.py       # Optimized variant
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ viewer_2d_with_tools.py      # Viewer2DWithTools ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ adds ruler/angle/ROI
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ viewer_3d.py                 # Viewer3DWidget ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ 3D volume rendering
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ vtk_3d_presets.py            # VolumePresetConfig ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ bone, soft tissue, etc.
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ filter_config_widget.py      # FilterConfigWidget UI
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ image_filter_sidebar.py      # Filter sidebar
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ preset_manager.py            # User preset management
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ advanced_tools_panel.py      # Toolbar for advanced features
```

### Pipeline Orchestration
```
modules/viewer/pipeline/
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ orchestrator.py              # PipelineOrchestrator, PipelineState enum
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ load_coordinator.py          # LoadCoordinator ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ dedup in-flight loads
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ preview_engine.py            # PreviewEngine ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ quick preview before full load
```

### Widget Helpers
```
modules/viewer/widgets/
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ loading_spinner.py           # LoadingSpinner, ViewportSpinner
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ medical_loading_overlay.py   # MedicalLoadingOverlay
```

### Interactor Styles (Measurement Tools)
```
modules/viewer/interactor_styles/
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ abstract_interactorstyle.py     # AbstractInteractorStyle ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ base class
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ruler_interactorstyle.py        # Distance measurement
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ angle_interactorstyle.py        # Angle measurement
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ two_line_angle_interactorstyle.py # Cobb angle
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ arrow_interactorstyle.py        # Arrow annotation
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ text_interactorstyle.py         # Text annotation
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ roi_interactorstyle.py          # Region of interest with statistics
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ roi_with_segment.py             # ROI with AI segmentation overlay
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ eraser_interactorstyle.py       # Annotation eraser
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ default_interaction_interactorstyle.py # Default pan/zoom/scroll
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ rotate_interactorstyles.py      # Image rotation
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ai_chat_interactorstyle.py      # AI click-on-image integration
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ tools_object_manager.py         # All tool data objects (RulerObject, etc.)
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ interactor_utils/               # Shared math helpers
```

## ZetaSync Module

Cross-viewer synchronization (linked scroll, W/L sync):

```
modules/zeta_sync/
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ sync_manager.py    # SyncManager ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ orchestrates cross-viewer sync
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ sync_context.py    # Sync state context (active groups, modes)
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ sync_types.py      # Type definitions for sync messages
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ geometry_utils.py  # IPP-based position calculation
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ adapters.md        # Integration guide for new viewer types
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ README.md          # Module documentation
```

## Storage Module

Disk management and cleanup:

```
modules/storage/
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ disk_alert_service.py                # Low disk space warnings
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ local_storage_cleanup_manager.py     # Automated DICOM cleanup
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ patient_cleanup_manager.py           # Per-patient file removal
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ storage_calculator.py                # Disk usage scanning
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ thumbnail_store.py                   # Thumbnail storage management
```

## Stitching Module

Long-bone / panorama image stitching:

```
modules/stitching/
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ stitching_widget.py           # StitchingWidget ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ main UI
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ stitch_controller.py          # StitchController ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ orchestration
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ stitch_engine.py              # StitchEngine ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ image composition
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ stitch_worker.py              # Background processing thread
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ blend_engine.py               # Multi-image blending
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ canvas_builder.py             # Output canvas construction
ط£آ¢أ¢â‚¬â€Œط¥â€œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ landmark_store.py             # LandmarkStore ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ alignment points
ط£آ¢أ¢â‚¬â€Œأ¢â‚¬â€Œط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ landmark_interactor_style.py  # VTK interaction for placing landmarks
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
| Grid layout | `modality_grid.json` | Default grid per modality (CT=1ط·آ£أ¢â‚¬â€‌1, MR=2ط·آ£أ¢â‚¬â€‌2) |
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

