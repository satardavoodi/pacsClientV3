# UI + Window + PySide + Button Evaluation Report (Phase A1)

Date: 2026-05-17

## Scope of this phase
Conservative evaluation-first baseline for:
1. UI widget code paths
2. Window/geometry operations
3. PySide signal/slot connection patterns
4. Button wiring patterns

No broad refactor and no behavior-changing cleanup in this phase except one tiny signal-wiring micro-change.

## New audit tool
1. `tools/diagnostics/ui_window_pyside_button_evaluation_audit.py`

Audit coverage:
1. UI file inventory
2. print() calls (AST-based)
3. blocking candidate calls (AST-based)
4. PySide connect/lambda/signal/slot usage
5. button instantiation and connect patterns
6. window operation markers
7. QTimer singleshot usage

## Baseline metrics (Phase A1 baseline)
Source:
`generated-files/benchmarks/ui_window_pyside_button_audit_baseline_2026-05-17.json`

1. `scanned_files = 135`
2. `print_calls = 1001`
3. `blocking_candidates = 5`
4. `pyside_connect_calls = 477`
5. `pyside_connect_lambda_calls = 83`
6. `pyside_signal_declarations = 72`
7. `pyside_slot_decorators = 10`
8. `qtimer_singleshot_calls = 157`
9. `button_instantiations = 190`
10. `button_clicked_connects = 249`
11. `button_other_connects = 8`
12. `window_ops = 89`
13. `todo_markers = 0`

## First conservative micro-change (Phase A step 1)
Changed file:
1. `modules/download_manager/ui/components/action_buttons.py`

Change:
1. Replaced no-arg lambda wrappers in button wiring with direct bound methods:
   - `clicked.connect(lambda: self._on_pause_clicked())` -> `clicked.connect(self._on_pause_clicked)`
   - Same for resume/cancel/retry buttons.

Why this is safe:
1. Same slot methods invoked.
2. No signal signature change.
3. Removes unnecessary lambda allocation/call overhead in hot UI rebuild path.

## Metrics after Phase A step 1
Source:
`generated-files/benchmarks/ui_window_pyside_button_audit_after_phaseA_step1_2026-05-17.json`

1. `pyside_connect_lambda_calls: 83 -> 79` (improved)
2. All other high-level counts unchanged (expected for a single-file micro-change).

## Second conservative micro-change batch (Phase A step 2)
Changed files:
1. `builder/plugin package/packages/download_manager/payload/python/modules/download_manager/ui/components/action_buttons.py`
2. `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py`
3. `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`

Changes:
1. Synced plugin-package mirror for `action_buttons.py` to preserve canonical/plugin parity.
2. Replaced additional no-arg lambda wrappers with direct bound methods:
   - `browse_btn.clicked.connect(lambda: self.browse_output_directory())` -> `browse_btn.clicked.connect(self.browse_output_directory)`
   - `mpr_btn.clicked.connect(lambda: self.toggle_zeta_mpr())` -> `mpr_btn.clicked.connect(self.toggle_zeta_mpr)`

## Metrics after Phase A step 2
Source:
`generated-files/benchmarks/ui_window_pyside_button_audit_after_phaseA_step2_2026-05-17.json`

1. `pyside_connect_lambda_calls: 83 -> 77` (net improvement)
2. `blocking_candidates` remained `5` (no regression)
3. `qtimer_singleshot_calls` remained `157` (no timer churn)

Note:
1. `print_calls` count shifted between runs due audit-scope evolution and parser precision work; this phase's intentional cleanup target was lambda-connection reduction, which improved monotonically.

## Validation gates
1. `pytest tests/utils/test_structured_logging_lint.py -q` -> PASS
2. `python tests/download_manager/run_dm_test.py` -> PASS (exit code 0)
3. No diagnostics errors in changed files.

## Impact assessment (current phase)
1. Functional risk: Low
2. Performance impact: Small but positive in DM action-button wiring path
3. Main value of this phase: objective baseline + measurable first reduction of lambda-based signal wiring

## Prioritized next conservative targets
1. Additional no-arg lambda wrappers in UI button wiring where direct method binding is equivalent.
2. Investigate 5 blocking candidates with call-site safety review before edits.
3. Add a UI evaluation bundle runner (same pattern as startup bundle) for repeatable cross-PC benchmarking.

## Phase A2 step 1 (UI evaluation bundle runner)
Changed file:
1. `tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py`

What changed:
1. Added one-command UI bundle runner for repeatable evaluation.
2. Bundle supports optional validation gates:
   - `--run-logging-lint`
   - `--run-dm-tests`
3. Added compact run mode:
   - `--summary-only`
4. Added gateable UI KPI regression checks:
   - `--fail-on-ui-kpi-regression`
   - `--expected-pyside-connect-lambda-calls`
   - `--expected-blocking-candidates`
5. Added optional baseline delta support:
   - `--baseline-bundle-json`

Validation and generated artifacts:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step1 --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 77 --expected-blocking-candidates 5`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step1.json`
3. Summary output confirmed:
   - `lambda_connects=77`
   - `blocking_candidates=5`
   - `ui_kpi_passed=True`
   - `lint_passed=True`
   - `dm_passed=True`

## Phase A2 step 2 (high-frequency sidebar wiring cleanup)
Changed files:
1. `PacsClient/pacs/patient_tab/ui/patient_ui/sidebar_widget.py`
2. `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py`

Changes:
1. Replaced repeated lambda click handlers in sidebar/panel navigation with direct method slots.
2. Added dedicated handler methods for each panel target to preserve behavior while removing lambda wrappers.

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step2_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 69 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step1.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step2_post.json`

Measured impact:
1. `lambda_connects: 77 -> 69` (delta `-8`)
2. `blocking_candidates: 5 -> 5` (no regression)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 3 (custom tab close wiring cleanup)
Changed file:
1. `PacsClient/pacs/patient_tab/ui/patient_ui/custom_tab_manager.py`

Changes:
1. Replaced static-index `close_requested` lambda wrappers with `functools.partial` callbacks.
2. Added `from functools import partial` import.
3. Scope limited to close-tab callbacks where lambda only forwarded a fixed tab index.

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step3_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 62 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step2_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step3_post.json`

Measured impact:
1. `lambda_connects: 69 -> 62` (delta `-7`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 4 (workstation/home UI connection cleanup)
Changed files:
1. `PacsClient/pacs/workstation_ui/AIPacs_ui.py`
2. `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py`
3. `PacsClient/pacs/workstation_ui/home_ui/import_preview_dialog.py`

Changes:
1. Replaced fixed-target lambda wrappers in left/center menu and navigation wiring with explicit handler methods.
2. Replaced container-hide lambdas with direct bound methods.
3. Replaced font-size and series select/clear fixed-argument lambda wrappers with dedicated click-handler methods.

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step4_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 51 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step3_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step4_post.json`

Measured impact:
1. `lambda_connects: 62 -> 51` (delta `-11`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 5 (workstation settings signal-wrapper cleanup)
Changed files:
1. `PacsClient/pacs/workstation_ui/AIPacs_ui.py`
2. `PacsClient/pacs/workstation_ui/theme_ui.py`
3. `PacsClient/pacs/workstation_ui/settings_ui/servers_config.py`
4. `PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py`

Changes:
1. Replaced fixed-argument `clicked.connect(lambda ...)` wrappers with `partial(...)` + dedicated bridge handlers that explicitly absorb `clicked(bool)` payload.
2. Scope limited to argument-forwarding wrappers only (no behavior changes).

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step5_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 46 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step4_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step5_post.json`

Measured impact:
1. `lambda_connects: 51 -> 46` (delta `-5`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 6 (workstation settings follow-up cleanup)
Changed files:
1. `PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py`
2. `PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py`

Changes:
1. Replaced fixed-argument/no-arg `clicked.connect(lambda ...)` wrappers with explicit handlers and `partial(...)` where argument forwarding is required.
2. Preserved the same async launch behavior for external PACS Echo and the same force-refresh/cleanup routing in storage settings.

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step6_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 42 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step5_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step6_post.json`

Measured impact:
1. `lambda_connects: 46 -> 42` (delta `-4`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 7 (home download panel final workstation lambda cleanup)
Changed file:
1. `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py`

Changes:
1. Replaced remaining argument-forwarding lambda wrappers with bridge handlers and `partial(...)` in start/resume wiring and progress-signal forwarding.
2. Confirmed workstation scope now has zero `connect(lambda` callsites.

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step7_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 39 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step6_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step7_post.json`

Measured impact:
1. `lambda_connects: 42 -> 39` (delta `-3`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 8 (custom tab activation lambda cleanup)
Changed file:
1. `PacsClient/pacs/patient_tab/ui/patient_ui/custom_tab_manager.py`

Changes:
1. Replaced remaining static-index activation lambda wrappers with `partial(...)` callbacks.
2. Scope limited to click handlers that only forwarded fixed tab indices.

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step8_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 37 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step7_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step8_post.json`

Measured impact:
1. `lambda_connects: 39 -> 37` (delta `-2`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 9 (patient toolbar forwarding-lambda cleanup)
Changed file:
1. `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`

Changes:
1. Replaced a large safe subset of forwarding-only lambda connections in the toolbar section with explicit bridge handlers and `partial(...)`.
2. Preserved clicked-signal compatibility by absorbing optional `checked` payload in bridge methods where needed.
3. Intentionally left complex multi-action lambda blocks untouched in this step.

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step9_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 18 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step8_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step9_post.json`

Measured impact:
1. `lambda_connects: 37 -> 18` (delta `-19`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 10 (patient toolbar final simple-lambda sweep)
Changed file:
1. `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`

Changes:
1. Replaced remaining simple toolbar lambdas in this area (`prev/next` slice buttons and MPR menu open) with `partial(...)` and bridge-handler wiring.
2. Left only the intentionally deferred complex multi-action lambda group in the earlier toolbar section.

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step10_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 15 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step9_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step10_post.json`

Measured impact:
1. `lambda_connects: 18 -> 15` (delta `-3`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 11 (patient toolbar complex-lambda decomposition)
Changed file:
1. `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`

Changes:
1. Replaced the remaining complex multi-action toolbar lambda connections (Lock Sync dropdown, MPR dropdown actions, rotation/flip dropdown actions) with explicit bridge handlers plus `partial(...)` wiring.
2. Preserved execution order exactly: action first, then dropdown close.
3. Post-change inventory confirms zero `connect(lambda` callsites in the toolbar module.

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step11_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 5 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step10_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step11_post.json`

Measured impact:
1. `lambda_connects: 15 -> 5` (delta `-10`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`

## Phase A2 step 12 (final patient UI lambda cleanup to zero)
Changed files:
1. `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown.py`
2. `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py`
3. `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py`
4. `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_viewers.py`
5. `PacsClient/pacs/patient_tab/utils/series_layout_matrix.py`

Changes:
1. Replaced remaining forwarding lambda connect patterns in patient UI with explicit handlers and `partial(...)` forwarding.
2. Kept behavior identical (argument flow and target method calls preserved).
3. Active `connect(lambda...)` inventory in patient tab scope reduced to zero (only one commented example remains in `series_layout_matrix.py`).

Validation and generated artifact:
1. Run command:
   - `python tools/diagnostics/run_ui_window_pyside_button_evaluation_bundle.py --tag 2026-05-17_phaseA2_step12_post --run-logging-lint --run-dm-tests --summary-only --fail-on-ui-kpi-regression --expected-pyside-connect-lambda-calls 0 --expected-blocking-candidates 5 --baseline-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step11_post.json`
2. Generated file:
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step12_post.json`

Measured impact:
1. `lambda_connects: 5 -> 0` (delta `-5`)
2. `blocking_candidates: 5 -> 5` (stable)
3. `qtimer_singleshot_calls: 157 -> 157` (stable)
4. Gates: `lint_passed=True`, `dm_passed=True`, `ui_kpi_passed=True`
