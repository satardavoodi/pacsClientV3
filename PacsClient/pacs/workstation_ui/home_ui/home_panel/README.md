# Home Panel Widget — Split Reference

## Purpose
The `HomePanelWidget` (originally 5,410 lines in `home_ui.py`) has been split into 10 focused mixin files + 1 core widget, following the same mixin pattern used for `patient_widget_core/` (Phase 1) and `download_manager/ui/widget/` (Phase 2).

## File Map

| File | Class | Methods | Lines | Responsibility |
|------|-------|---------|-------|----------------|
| `widget.py` | `HomePanelWidget` | 1 + signals | ~209 | Core class: `__init__`, signals, module-level helpers, mixin assembly |
| `_hp_layout.py` | `_HPLayoutMixin` | 17 | ~803 | UI layout: left/center/right panels, theme, loading overlays, connection status |
| `_hp_patient_open.py` | `_HPPatientOpenMixin` | 11 | ~495 | Patient double-click: tab open, loading states, close/cleanup |
| `_hp_search.py` | `_HPSearchMixin` | 31 | ~497 | Search & table population: local/server search, patient table delegates |
| `_hp_import.py` | `_HPImportMixin` | 6 | ~390 | Import pipeline: folder import with preview, auto-import from startup |
| `_hp_download.py` | `_HPDownloadMixin` | 19 | ~614 | Download coordination: start, complete, fail, resume, progress dialog |
| `_hp_series.py` | `_HPSeriesMixin` | 18 | ~424 | Series info, thumbnails, right panel display |
| `_hp_priority.py` | `_HPPriorityMixin` | 12 | ~668 | Priority download: thumbnail-click priority, single series immediate download |
| `_hp_modules.py` | `_HPModulesMixin` | 22 | ~575 | Module launchers: DM, web browser, education, printing, NPR, CD burn, tabs |
| `_hp_offline.py` | `_HPOfflineMixin` | 12 | ~451 | Offline cloud operations: sync, export, import, server validation |
| `_hp_study_save.py` | `_HPStudySaveMixin` | 4 | ~321 | Study/series save: save complete study info, series info DB/server |
| `__init__.py` | — | — | 3 | Re-exports `HomePanelWidget`, `SourceOfPatientLoad`, `get_home_widget` |

## MRO (Method Resolution Order)
```python
class HomePanelWidget(
    _HPLayoutMixin,
    _HPPatientOpenMixin,
    _HPSearchMixin,
    _HPImportMixin,
    _HPDownloadMixin,
    _HPSeriesMixin,
    _HPPriorityMixin,
    _HPModulesMixin,
    _HPOfflineMixin,
    _HPStudySaveMixin,
    QWidget,
):
```

## Module-Level Names (in widget.py)
- `SourceOfPatientLoad` — Enum-like class (DB, SERVER, IMPORT, OFFLINE_CLOUD)
- `get_home_widget()` — Returns singleton `HomePanelWidget` instance
- `_ensure_patient_widget()` — Lazy-loads `PatientWidget` on first use
- `_ensure_ai_main_window()` — Lazy-loads `AiMainWindow` on first use
- `PRIORITY_MANAGER_AVAILABLE` — Legacy constant (always False)

## Backward Compatibility
`home_ui.py` is now a thin shim re-exporting:
- `HomePanelWidget`
- `SourceOfPatientLoad`
- `get_home_widget`
- `_ensure_patient_widget`, `_ensure_ai_main_window`, `PRIORITY_MANAGER_AVAILABLE`

All existing import paths continue to work unchanged.

## Critical Rules
- **Lazy imports**: `PatientWidget` and `AiMainWindow` loaded via `_ensure_patient_widget()` / `_ensure_ai_main_window()` on first use. Do NOT import them at module level.
- **DB context manager**: All DB ops MUST use `with get_db_connection() as conn:` with explicit `conn.commit()`.
- **`is_widget_alive()`**: Use instead of inline `sip.isdeleted()`.
- **Non-blocking patterns**: File I/O and gRPC calls in background threads with `QTimer.singleShot(0, callback)`.

## Tests
```bash
# Smoke tests
.venv\Scripts\python.exe -m pytest tests/smoke/test_import_smoke.py -v

# UI services tests
.venv\Scripts\python.exe tests/ui_services/test_ui_services.py

# Connection tests
.venv\Scripts\python.exe -m pytest tests/connection_between_modules/ -v
```
