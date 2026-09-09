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

## Overall Progress Contract

- `Overall Progress` means all images in the selected study/queue row; it is not the current-series percentage and is not a global total across every queued study.
- Per-series counters may restart at zero, but study-level downloaded images are monotonic within one download generation.
- The accumulator is an O(1), integer-only main-process ledger keyed by `SeriesInstanceUID`; no disk, database, network, decode, or VTK work is allowed in this UI path.
- Before the first series starts, the download subprocess publishes one reliable aggregate-only `study_manifest` event. Its total comes from the server metadata actually used by the downloader and replaces an unknown or stale queue/search-payload total without resetting an already-observed numerator.
- The subprocess progress envelope carries both immutable `SeriesInstanceUID` and display `SeriesNumber`. Duplicate numbers must never be used as the authoritative identity.
- A complete-on-disk/resumed series emits one `series_accounted` message for aggregate state only. It must not create per-instance or viewer-progress fan-out.

### Live verification record

- On 2026-09-01, a human-controlled source-build run confirmed that both Overall Progress surfaces behaved cumulatively after a fresh restart.
- The PHI-safe diagnostic sequence showed an initially unknown queue total (`0`) replaced by the authoritative downloader manifest (`319` images across `6` series). All six terminal series totals summed exactly to `319` (`2 + 45 + 135 + 135 + 1 + 1`).
- No timestamped `ERROR` or `CRITICAL` event appeared in the application, download, viewer, or database logs during the verification window. This is source-build live verification, not installer or release readiness.

## Tests
```bash
# DM tests (27 scenarios, 129 assertions)
.venv\Scripts\python.exe tests/download_manager/run_dm_test.py

# Smoke tests
.venv\Scripts\python.exe -m pytest tests/smoke/test_import_smoke.py -v

# Connection tests
.venv\Scripts\python.exe -m pytest tests/connection_between_modules/ -v
```
