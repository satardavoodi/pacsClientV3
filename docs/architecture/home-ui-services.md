# Home UI — Service Layer Architecture

> **Version:** v2.3.3 | **Updated:** 2026-04-14

## Purpose

`HomePanelWidget` is the main patient-list screen and the hub for opening
studies, launching downloads, and navigating to module tabs.  As of v2.3.3
it follows a **Thin Controller + Service Layer** pattern: the widget class
handles only UI composition and signal wiring, while domain logic lives in
dedicated service modules.

## File Map

```
PacsClient/pacs/workstation_ui/home_ui/
├── home_ui.py                 # Thin controller — widget init, signal wiring, layout
├── home_db_service.py         # Service: all DB read/write operations
├── home_tab_service.py        # Service: tab lifecycle (find, create, activate, close)
├── home_download_service.py   # Service: DM tab factory, signal wiring, flag refresh
├── home_search_service.py     # Service: local + server async patient search
├── home_module_tabs.py        # Helper: generic module tab activate-or-create
├── home_widget_utils.py       # Helper: is_widget_alive() — unified widget validity
├── patient_table_widget.py    # Sub-widget: patient list QTableWidget
├── patient_search_widget.py   # Sub-widget: search bar + filters
├── right_panel_widget.py      # Sub-widget: right-side study/series info panel
├── data_access_panel.py       # Sub-widget: data-access button strip
├── import_preview_dialog.py   # Dialog: DICOM folder import preview
├── secretary_button_widget.py # Sub-widget: EchoMind secretary launcher
├── report_status_dialog.py    # Dialog: report status indicator
└── __init__.py                # Public API exports
```

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                     HomePanelWidget                          │
│  (thin controller — layout, signal wiring, event dispatch)   │
├──────────┬──────────┬──────────────┬─────────────────────────┤
│          │          │              │                          │
│  HomeDb  │ HomeTab  │ HomeDownload │    HomeSearch            │
│  Service │ Service  │ Service      │    Service               │
│          │          │              │                          │
│ save_*   │ find_*   │ get_or_      │ search_patients_local()  │
│ get_*    │ add_*    │ create_dm()  │ search_patients_server() │
│ insert_* │ close_*  │ connect_dm() │ _convert_params()        │
│ update_* │          │ refresh_     │                          │
│          │          │ flag()       │                          │
└──────────┴──────────┴──────────────┴─────────────────────────┘
         │             │               │                │
         ▼             ▼               ▼                ▼
    database/      QTabWidget     DownloadManager    socket/
    core.py        (MainWindow)   Widget             grpc
```

## Service Responsibilities

### HomeDbService (`home_db_service.py`)

All database persistence for the home screen.  Every method uses
`with get_db_connection() as conn:` and commits inside the block.

| Method | Purpose |
|--------|---------|
| `save_patient_and_study_on_db()` | Upsert patient + study + series + instances |
| `get_patient_study()` | Load study record by study_uid |
| `save_study_details()` | Write study-level metadata |
| `get_series_info_from_database()` | Load series list for a study |
| `save_series_info_to_database()` | Persist series metadata |

### HomeTabService (`home_tab_service.py`)

Tab lifecycle management — finding existing tabs, adding new ones, closing.

| Method | Purpose |
|--------|---------|
| `find_widget_by_study_uid()` | Search open tabs for a given study |
| `add_patient_tab()` | Create a new PatientWidget tab |
| `close_tab()` | Close tab by index |

### HomeDownloadService (`home_download_service.py`)

Download-manager tab creation and signal wiring.

| Method | Purpose |
|--------|---------|
| `get_or_create_download_manager_tab()` | Find or create the DM tab |
| `connect_download_manager_to_widget()` | Wire DM progress signals to a viewer |
| `refresh_global_download_flag()` | Update the "downloads active" indicator |

### HomeSearchService (`home_search_service.py`)

Async patient search — both local-DB and server-side (via socket/gRPC).

| Method | Purpose |
|--------|---------|
| `search_patients_local()` | `async` — query local DB, populate table |
| `search_patients_server()` | `async` — query remote PACS, populate table |
| `_convert_search_data_to_socket_params()` | Map UI filter dict → socket request params |

### home_module_tabs.py (helper)

| Function | Purpose |
|----------|---------|
| `activate_or_create_module_tab()` | Generic tab pattern: find existing → activate, or create + add |
| `find_existing_module_tab()` | Scan tabs by widget type |

### home_widget_utils.py (helper)

| Function | Purpose |
|----------|---------|
| `is_widget_alive(widget)` | Safe check combining `None`, `sip.isdeleted`, `isVisible`, `RuntimeError` |

## Public API

External code accesses the home panel via:

```python
from PacsClient.pacs.workstation_ui.home_ui import HomePanelWidget
# or
from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
widget = get_home_widget()
```

All service instances are attributes of `HomePanelWidget`:

```python
widget._db_service       # HomeDbService
widget._tab_service      # HomeTabService
widget._download_service # HomeDownloadService
widget._search_service   # HomeSearchService
```

Services are internal — external callers use `HomePanelWidget` methods which
delegate to services.

## Threading Model

| Layer | Thread | Pattern |
|-------|--------|---------|
| UI composition | Main (Qt) thread | Direct widget manipulation |
| Search (local) | Main thread, async | `async def` on qasync event loop |
| Search (server) | Main thread, async | `async def` on qasync event loop |
| DB writes | Main thread | Synchronous, fast (<5ms) |
| Heavy imports | Deferred | `PatientWidget`, `AiMainWindow` lazy-loaded on first use |
| Anti-aliasing | Deferred | `QTimer.singleShot(0, ...)` after first paint |
| Background jobs | Thread pool | `_run_background_job_with_progress()` via `QEventLoop` |

## Performance Optimizations (v2.3.3)

1. **Lazy imports**: `PatientWidget` and `AiMainWindow` are loaded on first
   patient double-click, not at module import time.  This saves ~200ms on
   startup.
2. **Anti-aliasing deferred**: `apply_anti_aliasing_to_all_widgets()` runs via
   `QTimer.singleShot(0)` so the UI paints before iterating children.
3. **Loading overlay reactivated**: `show_loading()`/`hide_loading()` now dim
   the panel during long operations instead of being no-ops.
4. **No event-loop blocking**: `_run_background_job_with_progress()` replaced
   `while not done: processEvents(); sleep(0.05)` with signal-driven
   `QEventLoop` + done callback.

## Rules for Future Development

### MUST follow

- **All new DB operations** go in `home_db_service.py`, not in `home_ui.py`.
- **All new tab operations** go in `home_tab_service.py`.
- **All new search logic** goes in `home_search_service.py`.
- **All new download-manager wiring** goes in `home_download_service.py`.
- **Never add blocking I/O** (DB, filesystem, network) directly in
  `home_ui.py` methods — delegate to a service.
- **Never use `QApplication.processEvents()` + `time.sleep()`** in new code.
  Use `QEventLoop`, `QTimer`, or async/await.
- **Widget validity**: use `is_widget_alive(w)` from `home_widget_utils.py`
  instead of inline `sip.isdeleted()` / `try-except RuntimeError` blocks.
- **Module tab pattern**: use `activate_or_create_module_tab()` from
  `home_module_tabs.py` instead of duplicating find-or-create logic.

### SHOULD follow

- Keep `home_ui.py` under 4000 lines.  If it grows, extract more into
  services.
- Each service class should stay under 500 lines.
- Add type hints to new service methods.
- Prefer `QTimer.singleShot(0, callback)` over direct method calls when
  marshaling from background threads.

### MUST NOT do

- Do not import `PatientWidget` or `AiMainWindow` at module level — use the
  lazy accessors `_get_patient_widget_class()` and `_get_ai_mainwindow_class()`.
- Do not merge services back into `home_ui.py`.
- Do not add `time.sleep()` in any UI-thread code path.
- Do not bypass `is_widget_alive()` with raw `sip.isdeleted()` checks.
