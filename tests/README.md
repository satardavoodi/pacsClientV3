# Test Suite Hub

This folder contains the project test suites organized by subsystem.

> Scope: this index covers `tests/` only. There are additional module-local tests (for example under `modules/EchoMind/secretary/tests/`).

---

## Quick start

Run from repository root:

- `.venv\Scripts\python.exe tests\download_manager\run_dm_test.py`
- `.venv\Scripts\python.exe tests\download_manager\test_dm_stress.py`
- `.venv\Scripts\python.exe tests\load\run_load_test.py`
- `.venv\Scripts\python.exe tests\database\run_db_test.py`
- `.venv\Scripts\python.exe -m pytest tests\viewer\test_fast_viewer_pipeline.py -v`
- `.venv\Scripts\python.exe -m pytest tests\smoke\test_import_smoke.py -v`
- `.venv\Scripts\python.exe -m pytest tests\connection_between_modules\ -v`

There is no single universal test runner for all suites; run suites separately.

---

## Suite map

| Suite | Purpose | Key files | Typical entrypoint |
|---|---|---|---|
| `download_manager/` | DM state machine, coordinator, rules, retries, stress | `test_download_manager.py`, `test_dm_stress.py` | `run_dm_test.py` |
| `performance/` | KPI scenario runners, comparison harness tests, FAST synthetic benchmarks, Block 1/2/3 KPI summaries, and anti-orphan job inventories | `test_b25_scenarios.py`, `test_clearcanvas_aipacs_kpi_harness.py`, `test_block_kpi_harness.py`, `test_pipeline_job_block_model.py` | `pytest tests/performance/ -v` |
| `load/` | multi-patient/multi-series load scenarios | `run_load_test.py` | `run_load_test.py` |
| `viewer/` | FAST/ADV viewer pipeline, backend config, geometry, drag-drop, tool layer | `test_fast_viewer_pipeline.py`, `test_fast_viewer_live_sync.py`, `test_viewer_backend_config.py` | `pytest tests/viewer/...` |
| `fast/` | FAST sync geometry and FAST download/UI behavior | `test_sync_sparse_stack.py`, `test_sync_validity_classification.py` | `pytest tests/fast/ -v` |
| `fast_viewer/` | FAST viewer functional/tool/perf slices | `test_tools_*.py`, `test_sync.py`, `test_performance.py` | `pytest tests/fast_viewer/ -v` |
| `network/` | socket/gRPC protocol and behavior checks | `test_network.py` | direct python run |
| `database/` | DB pool, CRUD, context-manager behavior | `test_database.py` | `run_db_test.py` |
| `ui_services/` | home UI service layer checks | `test_ui_services.py` | direct python run |
| `smoke/` | import smoke and basic sanity | `test_import_smoke.py` | `pytest tests/smoke/ -v` |
| `connection_between_modules/` | cross-module contract checks | `test_connection_between_modules.py` | `pytest tests/connection_between_modules/ -v` |
| `builder/` | packaging/build and plugin package tests | `test_plugin_package_*.py` | `pytest tests/builder/ -v` |
| `runtime/` | runtime graphics + module loading behavior | `test_aipacs_runtime_*.py` | `pytest tests/runtime/ -v` |
| `module_system/` | installation package behavior | `test_module_installation_packages.py` | `pytest tests/module_system/ -v` |
| `printing/` | printing data/repository checks | `test_printing_series_repository.py` | `pytest tests/printing/ -v` |
| `web_browser/` | browser state store behavior | `test_web_browser_state_store.py` | `pytest tests/web_browser/ -v` |
| `offline_cloud_server/` | offline cloud server tests | `test_offline_cloud_server.py` | `run_offline_cloud_server_test.py` |
| `system/` | stress/system-level scenarios | `test_system_stress.py` | `pytest tests/system/ -v` |
| `diagnostics/` | scenario harness + KPI/failure detectors | `run_diagnostic.py`, `scenarios/s*.py` | `run_diagnostic.py` |
| `cd_burner/` | cd burner portability checks | `test_cd_burner_portability.py` | `pytest tests/cd_burner/ -v` |
| `manual_archive/` | relocated one-off scripts kept for historical context, not canonical regression coverage | `root_ad_hoc/*.py` | manual run only |

---

## Recommended run order by intent

### Fast confidence pass (developer loop)
1. `tests/smoke/`
2. `tests/viewer/test_fast_viewer_pipeline.py`
3. `tests/download_manager/run_dm_test.py`
4. `tests/network/test_network.py`

### ClearCanvas benchmark workflow validation
1. `pytest tests/performance/test_clearcanvas_aipacs_kpi_harness.py -v`
2. review `tests/performance/clearcanvas_aipacs_scenarios.json`
3. review `tests/performance/clearcanvas_aipacs_benchmark_model.json`
4. follow `docs/analysis/CLEARCANVAS_BENCHMARK_EXECUTION.md`

### Release confidence pass
1. DM + DM stress
2. Load suite
3. Viewer + FAST + FAST_VIEWER suites
4. Database + network + runtime
5. Connection/system/builder suites

---

## Naming and placement conventions

- Use `test_<feature>.py` for pytest files.
- Keep scenario runners as `run_<suite>_test.py` when a custom runner exists.
- Place helper fixtures in suite-local `conftest.py` when practical.
- Put long-running scenario scripts under the closest subsystem suite (`load/`, `diagnostics/`, `system/`) instead of `viewer/`.
- Keep ad-hoc one-off validation scripts under `tests/manual_archive/`, not in repository root.

---

## Notes for AI agents

When asked to "run tests", first determine if user wants:
- **targeted suite** (preferred during debugging), or
- **broad confidence pass** (slower).

Use this folder map to route quickly to the smallest suite covering the issue.

For ClearCanvas comparison work, start with:

1. `docs/analysis/CLEARCANVAS_BENCHMARK_EXECUTION.md`
2. `tests/performance/clearcanvas_aipacs_scenarios.json`
3. `tests/performance/clearcanvas_aipacs_benchmark_model.json`
4. `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`

For the new block-based performance model, also read:

5. `docs/plans/FAST_BLOCK_PERFORMANCE_ARCHITECTURE.md`
6. `tests/performance/block_kpi_model.json`
7. `tests/performance/test_block_kpi_harness.py`
8. `docs/plans/FAST_PIPELINE_JOB_BLOCK_INVENTORY.md`
9. `tests/performance/pipeline_job_block_model.json`
