# Startup + First-Load + Warmup Evaluation and Cleanup Plan (2026-05-17)

## Scope
Evaluate and conservatively optimize the app startup, first screen load, and warmup behavior using the same workflow used for Download Manager cleanup:
1. Evaluation first (no behavior change).
2. Baseline metrics + static audit.
3. Small, reversible implementation slices.
4. Validation gates after each slice.

## Target startup path
1. `main.py`
2. `PacsClient/app_handler.py`
3. `PacsClient/pacs/workstation_ui/mainwindow_ui.py`
4. `PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py`
5. `modules/zeta_boost/warmup_subprocess.py`

## Architectural map (startup and warmup)
1. `main.py`
- Bootstraps frozen/runtime graphics env and diagnostic logging.
- Configures Qt application/event-loop integration via `QEventLoop`.
- Installs exception and optional event-loop attribution instrumentation.
- Creates `_AIPacsApplication`, then enters app lifecycle.

2. `AppHandler` login shell
- Login UI and auth socket flow in `PacsClient/app_handler.py`.
- Transitions to `MainWindowWidget` after auth.

3. `MainWindowWidget` first-load shell
- Initializes DB (`init_database`, migration fixups) and shell UI.
- Schedules optional startup import (`_schedule_startup_import_if_requested`).
- Creates home/control panel and viewer entry hooks.

4. `HomePanelWidget` first-load controller
- Uses service layer (`HomeDbService`, `HomeTabService`, `HomeDownloadService`, `HomeSearchService`).
- Uses lazy imports for heavy modules via `_ensure_patient_widget()` and `_ensure_ai_main_window()`.

5. Warmup subsystem
- `modules/zeta_boost/warmup_subprocess.py` performs GIL-isolated warmup work in a subprocess.
- Designed to avoid main-process GIL contention and keep UI interaction responsive.

## Baseline method
1. Static audit script:
- `tools/diagnostics/startup_warmup_evaluation_audit.py`
- Captures startup print usage, heavy imports, potential blocking patterns, `QTimer.singleShot` usage, lazy helper presence, and warmup isolation markers.

2. Runtime verification (existing gate):
- `tests/download_manager/run_dm_test.py` as stability checkpoint.
- Existing performance/event-loop instrumentation remains observation-only unless explicitly enabled by env vars.

## Risk categories for startup/first-load
1. Startup logging path still using direct `print` before full logger setup.
2. Potential heavyweight imports in startup-critical modules that can shift first-frame time.
3. Blocking patterns in startup UI paths (`subprocess.call`, `time.sleep`, `.join`, `.result`, `.wait`) if used on main thread.
4. Delayed startup tasks via `QTimer.singleShot` that may compete with first interaction.

## Conservative optimization phases
### Phase A - Evaluation and baseline (no behavior change)
1. Run startup/warmup static audit and store JSON baseline.
2. Produce findings report with file/line references.

### Phase B - Logging hygiene in startup path
1. Convert startup diagnostics from direct print to logger or controlled console emitter where safe.
2. Preserve user-visible CLI outputs where required.

### Phase C - First-load import and scheduling hygiene
1. Keep lazy import boundaries in `home_panel/widget.py` intact.
2. Eliminate accidental eager heavy imports in startup-critical files if found.
3. Keep startup delayed actions explicit and minimal.

### Phase D - Warmup guardrails
1. Verify warmup subprocess remains isolated (process marker + entrypoint marker).
2. Ensure no warmup-path change regresses interaction responsiveness.

## Validation gates (after each slice)
1. `tests/utils/test_structured_logging_lint.py`
2. `python tools/diagnostics/startup_warmup_evaluation_audit.py --json-out ...`
3. `python tests/download_manager/run_dm_test.py`

## Non-goals
1. No broad refactor of startup architecture in one pass.
2. No behavior-changing warmup scheduler redesign in this phase.
3. No uncontrolled logging volume increase.

## Deliverables
1. Baseline JSON audit report in `generated-files/benchmarks/`.
2. Incremental findings summary with measured deltas.
3. Conservative code improvements only after evaluation evidence confirms benefit.
