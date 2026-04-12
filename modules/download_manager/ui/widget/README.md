# Download Manager Widget — Split Reference

## Purpose
The `DownloadManagerWidget` (originally 5,534 lines in `main_widget.py`) has been split into 9 focused mixin files + 1 core widget, following the same pattern used for `patient_widget_core/` (Phase 1).

## File Map

| File | Class | Methods | Lines | Responsibility |
|------|-------|---------|-------|----------------|
| `widget.py` | `DownloadManagerWidget` | 2 + signals | ~320 | Core class: `__init__`, `study_downloads` property, signals, mixin assembly |
| `_dm_ui_setup.py` | `_DMUISetupMixin` | 6 | ~812 | UI setup: header, toolbar, download queue, details panel |
| `_dm_queue.py` | `_DMQueueMixin` | 20 | ~630 | Queue management: add/update/remove rows, progress bars, badges |
| `_dm_controls.py` | `_DMControlsMixin` | 10 | ~571 | Button handlers: play, pause, clear, start, cancel, retry, reset, priority |
| `_dm_workers.py` | `_DMWorkersMixin` | 11 | ~855 | Worker lifecycle: start, progress, complete, error, auto-management, health |
| `_dm_retry.py` | `_DMRetryMixin` | 5 | ~587 | Per-patient/series retry: non-blocking pause, resume, cancel, retry |
| `_dm_details.py` | `_DMDetailsMixin` | 15 | ~887 | Table & details: selection, details rendering, table ordering, row building |
| `_dm_priority.py` | `_DMPriorityMixin` | 8 | ~427 | Priority & coordination: critical series, viewed series, preemption |
| `_dm_reception.py` | `_DMReceptionMixin` | 4 | ~299 | Reception data: load, receive, error, apply |
| `_dm_theming.py` | `_DMThemingMixin` | 4 | ~206 | Theming: theme changes, v106 styling, speed display, logging |
| `__init__.py` | — | — | 3 | Re-exports `DownloadManagerWidget` |

## MRO (Method Resolution Order)
```python
class DownloadManagerWidget(
    _DMUISetupMixin,
    _DMQueueMixin,
    _DMControlsMixin,
    _DMWorkersMixin,
    _DMRetryMixin,
    _DMDetailsMixin,
    _DMPriorityMixin,
    _DMReceptionMixin,
    _DMThemingMixin,
    QWidget,
):
```

## Module-Level Helpers
Three module-level functions live in `widget.py` (not in any mixin):
- `_dm_theme_color_map(theme)` — Maps legacy hex colors to semantic theme colors
- `_dm_retint_stylesheet(css, theme)` — Replaces CSS hex colors with theme values
- `_dm_retint_widget_tree(root, theme)` — Recursively retints all widgets in tree

## Backward Compatibility
`modules/download_manager/ui/main_widget.py` is now a thin shim that re-exports:
- `DownloadManagerWidget`
- `_dm_theme_color_map`
- `_dm_retint_stylesheet`
- `_dm_retint_widget_tree`

All existing import paths continue to work unchanged.

## Signals (defined in widget.py)
| Signal | Parameters | Purpose |
|--------|-----------|---------|
| `download_completed` | `str` | study_uid on completion |
| `download_failed` | `str, str` | study_uid, error_message |
| `priority_changed` | `str, int` | study_uid, new_priority |
| `studyProgressUpdated` | `str, int, int, float` | study_uid, downloaded, total, percent |
| `seriesDownloadStarted` | `str, str, str` | study_uid, series_uid, series_desc |
| `seriesProgressUpdated` | `str, str, int, int` | study_uid, series_uid, downloaded, total |
| `seriesDownloadCompleted` | `str, str` | study_uid, series_uid |

## Critical Rules
- **Retry methods are non-blocking** — `_on_series_retry()` and `_on_per_patient_retry()` use `threading.Thread` + `QTimer.singleShot(0, callback)`.
- **Worker preemption uses `cancel_all_non_blocking()`** — NOT `stop_all()`.
- **Observer priority→refresh is 0ms** — `QTimer.singleShot(0, refresh_table_order)`.
- **Worker completion timer is 0ms** — `QTimer.singleShot(0, _start_next_pending)`.
- **Progress throttle is 100ms** — `_progress_throttle_timer` batches per-image signals.

## Tests
```bash
# DM tests (27 scenarios, 129 assertions)
.venv\Scripts\python.exe tests/download_manager/run_dm_test.py

# Smoke tests
.venv\Scripts\python.exe -m pytest tests/smoke/test_import_smoke.py -v

# Connection tests
.venv\Scripts\python.exe -m pytest tests/connection_between_modules/ -v
```
