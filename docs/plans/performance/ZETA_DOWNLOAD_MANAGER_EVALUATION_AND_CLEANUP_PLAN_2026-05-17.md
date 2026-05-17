# Zeta Download Manager Evaluation and Cleanup Plan (2026-05-17)

## Goal
Establish a safe, evaluation-first implementation path for Zeta download manager cleanup and optimization across both stacks:
- modules/download_manager (canonical runtime authority)
- PacsClient/zeta_download_manager (legacy/parallel surface)

This phase is intentionally non-invasive. No runtime behavior changes are introduced here.

## Scope
1. Code structure and ownership boundaries.
2. Method relationships and pipeline path integrity.
3. Duplication and dead/unreachable code risks.
4. Logging and observability hygiene risks.
5. Test and documentation parity before cleanup.

## Current Architectural Authority
1. Canonical download pipeline execution and state handling is in modules/download_manager.
2. UI integration and workflow wiring to home/patient flows passes through:
- modules/network/zeta_adapter.py
- PacsClient/pacs/workstation_ui/home_ui/home_download_service.py
3. Legacy or parallel pieces under PacsClient/zeta_download_manager require explicit boundary checks before unification.

## Risk-ranked Findings Summary
1. High: split authority risk between canonical and legacy stacks can cause drift.
2. High: observer/UI coupling and table refresh paths need lifecycle-safe hardening.
3. Medium: logging noise and potential silent-drop patterns reduce diagnostics quality.
4. Medium: nested retry/loop flow in series download path increases maintenance cost.
5. Medium: structural duplication exists in nearby code domains; DM-specific audits should run before each cleanup phase.

## Phase Plan (Implementation Order)

### Phase A: Baseline and Safety Gates
Run and store baseline results before any cleanup:
1. tests/download_manager/run_dm_test.py
2. tests/download_manager/test_dm_stress.py
3. tests/load/run_load_test.py
4. tests/performance/test_dm_rebuild_kpi_parser.py
5. tests/performance/test_priority_handoff_kpi_parser.py

Gate: proceed only when baseline passes and artifacts are captured.

### Phase B: No-behavior-change Structural Cleanup
1. Remove dead/unreachable code blocks where execution is already delegated.
2. Eliminate duplicate/shadowed method definitions in DM scope.
3. Standardize method placement by ownership layer (UI mixin vs coordinator vs worker).

Gate: run focused regressions after each file-level edit.

### Phase C: Observability Hygiene
1. Reduce non-essential log spam in hot paths.
2. Preserve required KPI/instrumentation tags and contracts.
3. Prevent silent-drop patterns for component=download emissions.

Gate: structured logging lint and KPI parser tests stay green.

### Phase D: Relationship Hardening (Minimal-risk Refactors)
1. Coalesce rebuild triggers where duplicate refresh work exists.
2. Tighten observer lifecycle cleanup on widget close/disconnect.
3. Keep behavior stable with small, test-gated changes.

Gate: DM stress + load suites pass on same commit.

### Phase E: Documentation Alignment
Update only after code is validated:
1. docs/pipelines/download-pipeline.md
2. docs/architecture/network-architecture.md
3. docs/architecture/home-ui-services.md

## New Audit Tool (Phase 0)
A static audit helper was added:
- tools/diagnostics/zeta_dm_evaluation_audit.py

It reports:
1. File inventory in DM-related roots.
2. Duplicate class/module definitions in same file.
3. print() usage in runtime paths.
4. TODO/FIXME/HACK markers.
5. Potential silent-drop logger.info(... component=download) candidates.

Usage:
- python tools/diagnostics/zeta_dm_evaluation_audit.py
- python tools/diagnostics/zeta_dm_evaluation_audit.py --json-out generated-files/benchmarks/zeta_dm_audit_2026-05-17.json

## Acceptance Criteria Before Functional Cleanup
1. Baseline suite artifacts captured.
2. Audit report generated and reviewed.
3. Target file list approved for Phase B edits.
4. Per-file rollback strategy documented.

## Notes
- This plan follows strict minimal-change policy.
- Cleanup starts with structural clarity before any algorithmic or policy modifications.
- No destructive consolidation of legacy stack occurs without explicit approval and parity validation.
