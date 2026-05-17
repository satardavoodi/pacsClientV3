# Startup + First-Load + Warmup Evaluation Report (Phase B1)

Date: 2026-05-17

## Scope of this phase
Conservative startup-path logging hygiene only.
No functional flow changes to login, startup import, graphics mode selection, or warmup execution policy.

Changed files:
1. `main.py`
2. `PacsClient/app_handler.py`
3. `PacsClient/pacs/workstation_ui/mainwindow_ui.py`

## What changed
1. Replaced direct startup-path `print(...)` diagnostics with controlled emitters/logger calls.
2. Preserved user-visible startup/CLI output semantics in `main.py` via `_emit_console(...)`.
3. Moved login/window/startup warnings and info in AppHandler/MainWindow to logger calls.

## Baseline metrics (before)
Source: `generated-files/benchmarks/startup_warmup_audit_baseline_2026-05-17.json`

1. `print_calls_startup = 40`
2. `blocking_candidates_startup = 1`
3. `qtimer_singleshot_startup = 11`
4. `lazy_import_helpers = 2`
5. `warmup_isolation markers = all true`

## Metrics after Phase B1
Source: `generated-files/benchmarks/startup_warmup_audit_after_phaseB_step1_2026-05-17.json`

1. `print_calls_startup = 0` (40 -> 0)
2. `blocking_candidates_startup = 1` (unchanged)
3. `qtimer_singleshot_startup = 11` (unchanged)
4. `lazy_import_helpers = 2` (unchanged; good)
5. `warmup_isolation markers = all true` (unchanged; good)

## Validation gates
1. `tests/utils/test_structured_logging_lint.py` -> PASS
2. `tests/download_manager/run_dm_test.py` -> PASS (exit code 0)
3. No file diagnostics errors in changed startup files.

## Impact assessment
1. Functional impact: Low (logging/console emission path only).
2. Startup observability: Improved consistency (logger + explicit emitter).
3. Warmup behavior: No change.
4. First-load latency: No direct timing optimization yet (this phase is hygiene/evaluation).

## Remaining prioritized findings
1. `main.py` still has one startup test-mode blocking call candidate:
   - `subprocess.call(...)` in `--run-tests` path.
   - Risk to regular startup: Low (debug/test-only code path).
2. `QTimer.singleShot` startup callbacks remain at 11 and need classification by criticality.

## Next conservative phase (Phase C)
1. Classify each startup `QTimer.singleShot` call as:
   - Must-run-before-first-interaction
   - Deferrable
   - Shutdown-only / not startup critical
2. Do not change timings yet.
3. Add a static classifier report artifact first, then propose micro-edits.

## Phase C1 update (classification completed)
Source: `generated-files/benchmarks/startup_qtimer_classification_2026-05-17.json`

1. `total = 11`
2. `window_geometry = 5`
3. `ui_deferred_polish = 2`
4. `startup_deferred = 1`
5. `login_flow = 1`
6. `shutdown_path = 2`
7. `unknown_review = 0` (resolved)

Resolved unknown callsites:
1. `PacsClient/app_handler.py:489` -> `ui_deferred_polish`
2. `PacsClient/pacs/workstation_ui/mainwindow_ui.py:318` -> `window_geometry`

Conservative interpretation:
1. `window_geometry` timers are event-loop handoff primitives for frameless/native movement and should remain immediate (`0`/`10 ms`) unless there is direct regression evidence.
2. `shutdown_path` timers are outside first-load critical path.
3. `startup_deferred` (`900 ms` startup import) is the only startup-delay timer worth considering for a micro-adjustment benchmark in the next phase.
4. `ui_deferred_polish` timers are first-paint smoothing aids; keep as-is unless startup jitter measurement points to them.

## Phase C2 step 1 (default-preserving tunable delay)
Changed file:
1. `PacsClient/pacs/workstation_ui/mainwindow_ui.py`

What changed:
1. Startup auto-import delay is now configurable by env var `AIPACS_STARTUP_IMPORT_DELAY_MS`.
2. Default remains `900 ms` (`_DEFAULT_STARTUP_IMPORT_DELAY_MS = 900`) to preserve existing behavior.
3. Invalid env values are ignored with a warning and fallback to default.

Validation and impact:
1. Startup audit unchanged on all key metrics:
   - Source: `generated-files/benchmarks/startup_warmup_audit_after_phaseC2_step1_2026-05-17.json`
   - `print_calls_startup = 0`
   - `blocking_candidates_startup = 1`
   - `qtimer_singleshot_startup = 11`
2. QTimer classification remains stable with no unknowns:
   - Source: `generated-files/benchmarks/startup_qtimer_classification_after_phaseC2_step1_2026-05-17.json`
   - `startup_deferred = 1` (now `QTimer.singleShot(delay_ms, _run_startup_import)`)
3. Regression gates:
   - `tests/utils/test_structured_logging_lint.py` -> PASS
   - `tests/download_manager/run_dm_test.py` -> PASS

## Phase C2 step 2 (audit visibility for delay source)
Changed file:
1. `tools/diagnostics/startup_warmup_evaluation_audit.py`

What changed:
1. Added a new audit block `startup_import_delay` with fields:
   - `env_var_present`
   - `default_delay_ms`
   - `uses_delay_variable`
2. Summary output now prints the new startup delay status line.
3. JSON output now includes `startup_import_delay` for cross-PC comparisons.

Validation and impact:
1. Source: `generated-files/benchmarks/startup_warmup_audit_after_phaseC2_step2_2026-05-17.json`
2. New line confirms expected state:
   - `startup_import_delay=env_var_present:True,default_delay_ms:900,uses_delay_variable:True`
3. Startup baseline metrics remain stable (`print_calls_startup=0`, `qtimer_singleshot_startup=11`, `blocking_candidates_startup=1`).

## Phase C2 step 3 (classifier visibility for delay timer mode)
Changed file:
1. `tools/diagnostics/startup_qtimer_classifier.py`

What changed:
1. Added startup import timer metadata block: `startup_import_delay_timer`.
2. Metadata fields:
   - `found`
   - `mode` (`variable|literal|unknown|absent`)
   - `path`, `line`, `call`
3. Summary output now includes `startup_import_delay_timer=...`.

Validation and impact:
1. Source: `generated-files/benchmarks/startup_qtimer_classification_after_phaseC2_step3_2026-05-17.json`
2. Current detected state:
   - `found=True`
   - `mode=variable`
   - `path=PacsClient/pacs/workstation_ui/mainwindow_ui.py`
   - `line=141`
3. Class distribution remains stable (`total=11`; no `unknown_review`).

## Phase C2 step 4 (one-command bundle runner)
Changed file:
1. `tools/diagnostics/run_startup_evaluation_bundle.py`

What changed:
1. Added an evaluation-only wrapper that runs both diagnostics in sequence:
   - `startup_warmup_evaluation_audit.py`
   - `startup_qtimer_classifier.py`
2. Wrapper writes three outputs per run:
   - startup warmup audit JSON
   - startup QTimer classification JSON
   - aggregate bundle JSON with key summary fields for cross-PC comparison
3. Wrapper keeps source read-only and does not alter runtime behavior.

Validation and generated artifacts:
1. Run command:
   - `python tools/diagnostics/run_startup_evaluation_bundle.py --tag 2026-05-17_phaseC2_step4`
2. Generated files:
   - `generated-files/benchmarks/startup_warmup_audit_bundle_2026-05-17_phaseC2_step4.json`
   - `generated-files/benchmarks/startup_qtimer_classification_bundle_2026-05-17_phaseC2_step4.json`
   - `generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step4.json`
3. Bundle run confirms stable baseline and startup-delay governance fields:
   - `print_calls_startup=0`
   - `blocking_candidates_startup=1`
   - `qtimer_singleshot_startup=11`
   - startup delay mode remains `variable` with default delay `900`.

## Phase C2 step 5 (optional lint gate in bundle)
Changed file:
1. `tools/diagnostics/run_startup_evaluation_bundle.py`

What changed:
1. Added optional flag `--run-logging-lint` to execute `tests/utils/test_structured_logging_lint.py -q` inside the bundle run.
2. Bundle JSON now includes `validation.structured_logging_lint` with:
   - `enabled`
   - `returncode`
   - `passed`
3. If lint is enabled and fails, wrapper exits non-zero to preserve gate semantics.

Validation and generated artifacts:
1. Run command:
   - `python tools/diagnostics/run_startup_evaluation_bundle.py --tag 2026-05-17_phaseC2_step5 --run-logging-lint`
2. Generated files:
   - `generated-files/benchmarks/startup_warmup_audit_bundle_2026-05-17_phaseC2_step5.json`
   - `generated-files/benchmarks/startup_qtimer_classification_bundle_2026-05-17_phaseC2_step5.json`
   - `generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step5.json`
3. Lint status in bundle JSON:
   - `enabled=true`
   - `returncode=0`
   - `passed=true`

## Phase C2 step 6 (optional DM regression gate in bundle)
Changed file:
1. `tools/diagnostics/run_startup_evaluation_bundle.py`

What changed:
1. Added optional flag `--run-dm-tests` to execute `tests/download_manager/run_dm_test.py` inside the bundle run.
2. Bundle JSON `validation` now includes `dm_test_suite` with:
   - `enabled`
   - `returncode`
   - `passed`
3. If DM suite is enabled and fails, wrapper exits non-zero (gate semantics preserved).

Validation and generated artifacts:
1. Run command:
   - `python tools/diagnostics/run_startup_evaluation_bundle.py --tag 2026-05-17_phaseC2_step6 --run-logging-lint --run-dm-tests`
2. Generated files:
   - `generated-files/benchmarks/startup_warmup_audit_bundle_2026-05-17_phaseC2_step6.json`
   - `generated-files/benchmarks/startup_qtimer_classification_bundle_2026-05-17_phaseC2_step6.json`
   - `generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step6.json`
3. Gate statuses in bundle JSON:
   - `structured_logging_lint: enabled=true, returncode=0, passed=true`
   - `dm_test_suite: enabled=true, returncode=0, passed=true`

## Phase C2 step 7 (optional startup syntax gate in bundle)
Changed file:
1. `tools/diagnostics/run_startup_evaluation_bundle.py`

What changed:
1. Added optional flag `--run-startup-syntax-check`.
2. Gate runs `python -m py_compile` on startup-critical files:
   - `main.py`
   - `PacsClient/app_handler.py`
   - `PacsClient/pacs/workstation_ui/mainwindow_ui.py`
   - `PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py`
3. Bundle JSON `validation` now includes `startup_syntax_check` with:
   - `enabled`
   - `returncode`
   - `passed`
4. Non-zero exit is preserved when this gate is enabled and fails.

Validation and generated artifacts:
1. Run command:
   - `python tools/diagnostics/run_startup_evaluation_bundle.py --tag 2026-05-17_phaseC2_step7 --run-logging-lint --run-dm-tests --run-startup-syntax-check`
2. Generated files:
   - `generated-files/benchmarks/startup_warmup_audit_bundle_2026-05-17_phaseC2_step7.json`
   - `generated-files/benchmarks/startup_qtimer_classification_bundle_2026-05-17_phaseC2_step7.json`
   - `generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step7.json`
3. Gate statuses in bundle JSON:
   - `structured_logging_lint: enabled=true, returncode=0, passed=true`
   - `dm_test_suite: enabled=true, returncode=0, passed=true`
   - `startup_syntax_check: enabled=true, returncode=0, passed=true`

## Phase C2 step 8 (summary-only mode for fast cross-PC runs)
Changed file:
1. `tools/diagnostics/run_startup_evaluation_bundle.py`

What changed:
1. Added optional flag `--summary-only`.
2. In summary-only mode, verbose stdout/stderr from internal tool runs is suppressed unless there is stderr.
3. Wrapper prints compact KPI/gate lines:
   - startup KPI line (`print_calls_startup`, `blocking_candidates_startup`, `qtimer_singleshot_startup`)
   - timer governance line (`qtimer_total`, `startup_import_delay_mode`)
   - validation gate line (`lint_passed`, `dm_passed`, `syntax_passed`)

Validation and generated artifacts:
1. Run command:
   - `python tools/diagnostics/run_startup_evaluation_bundle.py --tag 2026-05-17_phaseC2_step8 --run-logging-lint --run-dm-tests --run-startup-syntax-check --summary-only`
2. Generated file:
   - `generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step8.json`
3. Console summary output confirmed:
   - `print_calls_startup=0`
   - `blocking_candidates_startup=1`
   - `qtimer_singleshot_startup=11`
   - `startup_import_delay_mode=variable`
   - all enabled gates passed (`lint`, `dm`, `syntax`).

## Phase C2 step 9 (startup KPI regression guard)
Changed file:
1. `tools/diagnostics/run_startup_evaluation_bundle.py`

What changed:
1. Added optional flag `--fail-on-startup-kpi-regression`.
2. Added optional threshold argument `--expected-qtimer-singleshot-startup` (default `11`).
3. Guard evaluates startup KPI checks:
   - `print_calls_startup == 0`
   - `qtimer_singleshot_startup == expected`
4. Bundle JSON `validation` now includes `startup_kpi_regression` with:
   - `enabled`
   - `expected`
   - `actual`
   - `passed`
   - `failed_checks`
5. When enabled and failing, wrapper exits non-zero (`2`).

Validation and generated artifacts:
1. Run command:
   - `python tools/diagnostics/run_startup_evaluation_bundle.py --tag 2026-05-17_phaseC2_step9 --run-logging-lint --run-dm-tests --run-startup-syntax-check --summary-only --fail-on-startup-kpi-regression`
2. Generated file:
   - `generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step9.json`
3. Summary output confirmed:
   - `startup_kpi_passed=True`
   - `failed_checks=[]`
4. Bundle JSON validation confirms guard pass with expected/actual values.

## Phase C2 step 10 (baseline bundle comparison for PC A vs PC B)
Changed file:
1. `tools/diagnostics/run_startup_evaluation_bundle.py`

What changed:
1. Added optional `--baseline-bundle-json <path>` argument.
2. Wrapper now emits `baseline_comparison` in bundle JSON:
   - `enabled`
   - `baseline_path`
   - `loaded`
   - `delta` (key KPI differences)
3. Delta fields include:
   - `print_calls_startup_delta`
   - `blocking_candidates_startup_delta`
   - `qtimer_singleshot_startup_delta`
   - `qtimer_total_delta`
   - startup import delay mode changed/current/baseline
4. `--summary-only` now prints compact baseline delta line when a baseline is provided.

Validation and generated artifacts:
1. Run command:
   - `python tools/diagnostics/run_startup_evaluation_bundle.py --tag 2026-05-17_phaseC2_step10 --run-logging-lint --run-dm-tests --run-startup-syntax-check --summary-only --fail-on-startup-kpi-regression --baseline-bundle-json generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step9.json`
2. Generated file:
   - `generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step10.json`
3. Summary output confirmed baseline equality in this run:
   - `vs_baseline(print=0, blocking=0, qtimer=0, mode_changed=False)`
4. Bundle JSON confirms `baseline_comparison.loaded=true` and zero deltas vs step9 baseline.
