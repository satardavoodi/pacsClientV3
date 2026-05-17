# Cross-Part Harmony Evaluation (Startup + UI/UX/Button + Download Manager)

Date: 2026-05-17

## Goal
Provide an up-level integration verdict for the three streams and ensure they are aligned in behavior and gating:
1. Startup / warmup
2. UI/UX + button signal wiring
3. Download Manager integration and regression gates

## New evaluator
1. `tools/diagnostics/run_cross_part_harmony_bundle.py`

Inputs consumed:
1. Startup bundle JSON (latest stable):
   - `generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step10.json`
2. UI bundle JSON (latest stable):
   - `generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step12_post.json`

Output generated:
1. `generated-files/benchmarks/cross_part_harmony_bundle_2026-05-17_phaseH1.json`

## Run command
1. `python tools/diagnostics/run_cross_part_harmony_bundle.py --tag 2026-05-17_phaseH1 --startup-bundle-json generated-files/benchmarks/startup_evaluation_bundle_2026-05-17_phaseC2_step10.json --ui-bundle-json generated-files/benchmarks/ui_window_pyside_button_evaluation_bundle_2026-05-17_phaseA2_step12_post.json --summary-only`

## Harmony checks (all passed)
1. Startup lint gate passed
2. Startup DM test gate passed
3. Startup syntax gate passed
4. Startup KPI regression gate passed
5. UI lint gate passed
6. UI DM test gate passed
7. UI KPI regression gate passed
8. Startup print calls remain zero
9. UI lambda connect count remains zero
10. Blocking candidate alignment is acceptable
11. Startup timer topology remains at expected value (11)

## Key metrics snapshot
1. `startup_print_calls = 0`
2. `startup_qtimer_singleshot = 11`
3. `ui_lambda_connects = 0`
4. `ui_blocking_candidates = 5` (stable)
5. `ui_qtimer_singleshot = 157` (stable)

## Verdict
1. `harmony_passed = True`
2. `checks_passed = 11/11`
3. No cross-part regression signal detected.

## Notes
1. The evaluator is read-only with respect to runtime behavior; it only consumes existing benchmark bundles and enforces integration-level consistency checks.
2. Timestamp generation in the evaluator is timezone-aware UTC (Python 3.13 clean, no deprecation warning).
