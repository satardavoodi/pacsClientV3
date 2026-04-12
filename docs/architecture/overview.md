# Architecture Overview

> **Version:** v2.3.1 | **Updated:** 2026-04-13

## Purpose

AIPacs is a desktop DICOM workstation composed of a workstation shell plus several semi-independent modules:

- fast viewer
- advanced viewer
- download manager
- MPR and advanced imaging
- education
- web viewing
- printing
- EchoMind assistant

The current architecture is serviceable, but the repository had drifted away from a clean separation between runtime code, historical notes, and generated artifacts. This document describes the cleaned-up structure as it exists now.

## System Layers

### Presentation Layer

- `main.py`
- `PacsClient/app_handler.py`
- `PacsClient/pacs/workstation_ui/`
- `PacsClient/pacs/patient_tab/ui/`
- `printing/ui/`

This layer owns Qt widgets, tab management, user actions, and view composition.

As of v2.3.1, `HomePanelWidget` follows a **Thin Controller + Service Layer**
pattern.  See `docs/architecture/home-ui-services.md` for full details.

### Application and Orchestration Layer

- `PacsClient/components/`
- `PacsClient/zeta_download_manager/`
- `EchoMind/secretary/`
- `printing/data/`

This layer coordinates workflows, turns UI actions into tasks, and mediates access to database and filesystem resources.

### Imaging and Domain Layer

- `modules/viewer/`
- `PacsClient/pacs/patient_tab/orthogonal_mpr/`
- `PacsClient/pacs/patient_tab/zeta mpr/`
- `PacsClient/pacs/patient_tab/zeta_boost/`
- `PacsClient/pacs/patient_tab/zeta_sync/`
- `printing/render/`

This layer contains DICOM viewing, rendering, image transformation, sync, and printing logic.

### Network Layer

- `modules/network/` — socket clients, gRPC client, config, token management
- `modules/download_manager/network/` — download-path socket client, health monitor

This layer owns all server communication.  The `SocketService` singleton is the
single entry point for all socket calls.  See `docs/architecture/network-architecture.md`
for wire protocol, authentication, retry architecture, and TCP tuning details.

### Download Manager Layer

- `modules/download_manager/core/` — constants, enums, models, exceptions
- `modules/download_manager/state/` — StateStore, StateMachine, Observers
- `modules/download_manager/coordinator/` — SeriesIntentCoordinator (priority negotiation, series-interrupt)
- `modules/download_manager/rules/` — RuleEngine, ValidationRules (R17a/R17b), PriorityRules, ResumeRules
- `modules/download_manager/download/` — Executor, SeriesDownloader, BatchProcessor, ProgressTracker
- `modules/download_manager/ui/` — DownloadManagerWidget, components, dialogs, styles
- `modules/download_manager/workers/` — DownloadProcessWorker (subprocess)
- `modules/download_manager/network/` — SocketDicomClient, ConnectionHealthMonitor (R30-R34)
- `modules/download_manager/storage/` — file management, directory validation

This layer owns the entire download lifecycle from user intent to disk storage.
See `docs/pipelines/download-pipeline.md` for the full pipeline and `docs/architecture/module-connections.md`
for inter-module signal flow.

### Infrastructure Layer

- `PacsClient/utils/database.py`
- `PacsClient/utils/db_manager.py`
- `config/`
- `database/`
- `generated-files/`
- `logs/`

This layer handles persistence, configuration, diagnostics, migrations, and local runtime state.

As of v2.2.8.0, all database operations use `with get_db_connection() as conn:`
and commit explicitly.  See `docs/architecture/database-architecture.md` for
connection pool rules and commit safety.

## Module Catalog

### Viewer Modules

- Fast viewer: `modules/viewer/fast/` (`pydicom_qt`, `pydicom_2d`, bridge/pipeline)
- Advanced viewer: `modules/viewer/advanced/` (`viewer_2d.py`, tools, 3D helpers)
- Orthogonal MPR: `orthogonal_mpr/`
- Zeta MPR: `zeta mpr/`

The practical rule is:

- use the fast viewer for lightweight browsing and download-time interaction
- use the advanced viewer and MPR stack for richer tools, measurements, and reconstruction workflows

Canonical viewer architecture/debug docs: `docs/viewer/README.md`.

### Download and Cache Modules

- `modules/download_manager/` — modular download engine (state, coordinator, rules, workers)
- `PacsClient/zeta_download_manager/` — legacy Zeta adapter and UI helpers
- `PacsClient/pacs/patient_tab/zeta_boost/` — warmup cache and boost engine
- thumbnail and study caches under `generated-files/`, `thumbnails/`, and database-backed state

Download orchestration, progress tracking, resumability, priority management, and warmup caching are concentrated here.
The download manager follows a **state machine + rule engine + thin coordinator** architecture (v2.3.1).

### Education Module

- UI integration under `PacsClient/pacs/education/`
- persistent course content under `Education/`
- static assets under `education_assets/`

### Web Viewing Module

- `modules/web_browser/`

The workstation shell imports this as a standalone module package.

### Printing Module

- `printing/ui/`
- `printing/render/`
- `printing/printers/`
- `printing/data/`

The missing data-access layer has now been restored so the printing UI does not depend on absent imports.

### EchoMind and Secretary

- `EchoMind/`
- `EchoMind/secretary/`

This module owns conversational AI, routing, module selection, and assistant execution plans.

## Database and Cache Responsibilities

### Database

- Primary local database: `dicom.db`
- schema and low-level connection logic: `PacsClient/utils/database.py`
- query helpers and migration-style helpers: `PacsClient/utils/db_manager.py`
- operational scripts: `database/`

The database stores the DICOM hierarchy, download state, filming metadata, reception reports, and AI-related session data.

### Cache and Local Storage

- image thumbnails: `thumbnails/`
- attachments and filming output: `attachment/`
- generated logs and temp outputs: `generated-files/`
- viewer warmup and boosted image caching: `PacsClient/pacs/patient_tab/zeta_boost/`

The repository previously mixed cache discussions across many notes; these responsibilities are now documented centrally here.

## Current Integration Path

The standard module-to-data path should be:

1. UI widget triggers an action.
2. Application layer validates state and selects the correct service or repository.
3. Repository or service talks to the database or filesystem.
4. Domain layer renders or processes DICOM data.
5. UI updates through the owning widget, not through direct cross-module state mutation.

## Active Architectural Risks

- `PacsClient.utils` is still acting as a broad re-export hub. That makes imports convenient but increases coupling and import-order risk.
- `PacsClient/pacs/patient_tab/zeta mpr/` still uses a space in the directory name, forcing dynamic import workarounds.
- Several very large UI/controller files still carry too many responsibilities.
- Historical notes inside packages are inconsistent in encoding and freshness.

## Current KPI Snapshot (v2.2.8.1 — 2026-04-02)

### Test Suites

| Suite | File | Scenarios | Assertions | Pass | Fail |
|-------|------|-----------|------------|------|------|
| Download Manager | `tests/download_manager/test_download_manager.py` | 27 (S1–S27) | 129 | 129 | 0 |
| DM Stress | `tests/download_manager/test_dm_stress.py` | 10 (H1–H10) | 32 | 31 | 1 (expected) |
| Viewer Pipeline | `tests/viewer/test_fast_viewer_pipeline.py` | 11 | 11 | 11 | 0 |
| Network | `tests/network/test_network.py` | 8 | ~40 | all | 0 |
| Database | `tests/database/test_database.py` | 7 | ~35 | all | 0 |
| UI Services | `tests/ui_services/test_ui_services.py` | — | — | import-ok | — |
| Smoke (imports) | `tests/smoke/test_import_smoke.py` | 26+ modules | — | all | 0 |
| Connection | `tests/connection_between_modules/test_connection_between_modules.py` | — | — | all | 0 |

### Pipeline Latency Budget

| Layer | Timer | Purpose |
|---|---|---|
| DM progress batch | 100 ms | `_progress_throttle_timer` — batches per-image signals |
| Viewer progress debounce | 100 ms | `on_series_images_progress` per-series throttle |
| Progressive grow timer | 150 ms | `_progressive_grow_timer` — batch growth cadence |
| Coordinator queue recheck | 50 ms | `negotiate_priority_change` delay |
| Coordinator retry | 200 ms | `schedule_priority_start_retry` polling |
| Observer refresh | 0 ms | UIObserver priority→`refresh_table_order` |
| Worker completion→next | 0 ms | `_on_worker_completed`→`_start_next_pending` |
| DM notify cooldown | 500 ms | per-series dedup for drag-drop |

**Worst-case perceived latency** (image downloaded → visible): **~350 ms**

### Scroll Performance

| Metric | Target | Actual |
|--------|--------|--------|
| Frame time | <16 ms (60 Hz) | 8–12 ms typical |
| GC suppression window | 2000 ms | 2000 ms |
| Reference line repaint | 1 target/tick | round-robin confirmed |
| Lock Sync throttle | 100 ms | 100 ms |

See `docs/performance/PERFORMANCE_STATUS.md` for detailed metrics and `docs/architecture/test-catalog.md` for full test documentation.

## User-Data Directory Tree

All user-writable data lives under `user_data/` (dev) or `%LOCALAPPDATA%\AIPacs\user_data` (production).

```
user_data/
├── patients/
│   ├── dicom/           ← DICOM files by study_uid/series_number/
│   ├── attachments/     ← voice recordings, AI results, filming output
│   └── thumbnails/      ← series thumbnail images (JPEG)
├── education/
│   ├── courses/
│   │   └── MyCourse/
│   │       └── CaseOfTheDay/
│   └── assets/
├── ai/
│   ├── segments/        ← AI segmentation masks
│   └── clinical_notes.csv
├── echomind/
│   ├── memory/
│   └── logs/
├── cache/
│   └── zeta_boost/      ← L2 disk cache for viewer
├── reports/
│   └── reception/
├── logs/
└── dicom.db             ← SQLite database (WAL mode)
```

Path definitions: `PacsClient/utils/data_paths.py` (canonical) re-exported by `PacsClient/utils/config.py`.

## Interactor Styles (measurement tools)

All interactor styles inherit from `AbstractInteractorStyle` at `modules/viewer/interactor_styles/abstract_interactorstyle.py`.

| Style | File | Tool |
|-------|------|------|
| `RulerInteractorStyle` | `ruler_interactorstyle.py` | Distance measurement |
| `AngleInteractorStyle` | `angle_interactorstyle.py` | Angle measurement |
| `TwoLineAngleInteractorStyle` | `two_line_angle_interactorstyle.py` | Cobb angle |
| `ArrowInteractorStyle` | `arrow_interactorstyle.py` | Arrow annotation |
| `TextInteractorStyle` | `text_interactorstyle.py` | Text annotation |
| `RoiInteractorStyle` | `roi_interactorstyle.py` | Region of interest |
| `EraserInteractorStyle` | `eraser_interactorstyle.py` | Eraser tool |
| `DefaultInteractionInteractorStyle` | `default_interaction_interactorstyle.py` | Pan/zoom/scroll |
| `RotateInteractorStyle` | `rotate_interactorstyles.py` | Image rotation |
| `AIChatInteractorStyle` | `ai_chat_interactorstyle.py` | AI click integration |

Tool objects: `tools_object_manager.py` defines `RulerObject`, `AngleObject`, `TwoLineAngleObject`, `ArrowObject`, `TextObject`, `RoiObject`, `CircleRoiObject`, `TriangleObject`.

## Module System Architecture

Dynamic module loading is managed by `modules/module_system/module_manager.py`:

```
ModuleManager
  ├─ ModuleState enum: IDLE → QUEUED → RUNNING → COMPLETED/ERROR → DISPOSED
  ├─ Uses ThreadPoolExecutor for concurrent module execution
  ├─ Config from config/installation_profile.json
  └─ pipeline_orchestrator.py — orchestrates execution order
```

Modules are enabled/disabled via `config/installation_profile.json`. The `InstallationModuleSettingsWidget` provides the UI.

## EchoMind Architecture

```
modules/EchoMind/
  ├── echomind_main.py       — Module entry point
  ├── api_manager.py         — API endpoint management
  ├── llm_client.py          — LLM API client
  ├── ai_chat_config.py      — Configuration
  ├── settings_store.py      — Persistent settings
  ├── secretary_bridge.py    — Bridge to secretary module
  ├── secretary/             — AI secretary (auto-routing, module selection)
  └── viewer_chat/
      ├── ai_chat_api.py     — ChatController (QObject)
      ├── ai_chat_viewer.py  — AIChatViewer (QWidget)
      ├── ai_chat_pages.py   — ModePickerPage, OneChatPage
      └── ai_chat_widgets.py — MessageBubble, ChatHistory, UnifiedComposer
```

## Recommended Next Refactors

1. Split large UI controllers into presentation, services, and repositories.
2. Replace broad `PacsClient.utils` imports with direct module imports over time.
3. Rename `zeta mpr/` to `zeta_mpr/` only when imports and packaging can be migrated safely.
4. Expand targeted tests around printing, database repositories, and module orchestration.
