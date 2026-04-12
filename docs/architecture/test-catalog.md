# Test Catalog

> **Version:** v2.2.8.7 | **Updated:** 2026-04-02

## Overview

All tests are under the `tests/` directory. No single test runner is configured —
each suite has its own entry point. Tests use mocks/fakes and require no live
server or DICOM data.

Quick suite navigation: [`tests/README.md`](../../tests/README.md)

## Quick Reference

| Suite | Command | Scenarios | Assertions | Status |
|-------|---------|-----------|------------|--------|
| Download Manager | `python tests/download_manager/run_dm_test.py` | 27 | 129 | All pass |
| DM Stress | `python tests/download_manager/test_dm_stress.py` | 10 | 32 | 31 pass, 1 expected |
| Viewer Pipeline | `python -m pytest tests/viewer/test_fast_viewer_pipeline.py -v` | 18 | 18 | All pass |
| Drag-Drop Progressive | `python -m pytest tests/viewer/test_dragdrop_progressive.py -v` | 16 | 48 | All pass |
| Network | `python tests/network/test_network.py` | 8 | ~40 | All pass |
| Database | `python tests/database/run_db_test.py` | 7 | ~35 | All pass |
| UI Services | `python tests/ui_services/test_ui_services.py` | 5+ | — | Import OK |
| Smoke (imports) | `python -m pytest tests/smoke/test_import_smoke.py -v` | 26+ | — | All pass |
| Connection | `python -m pytest tests/connection_between_modules/ -v` | 5+ | — | All pass |
| Builder | `python -m pytest tests/builder/ -v` | 4 | — | All pass |
| CD Burner | `python -m pytest tests/cd_burner/ -v` | 1 | — | All pass |
| Runtime | `python -m pytest tests/runtime/ -v` | 2 | — | All pass |
| Module System | `python -m pytest tests/module_system/ -v` | 1 | — | All pass |
| Printing | `python -m pytest tests/printing/ -v` | 1 | — | All pass |
| Web Browser | `python -m pytest tests/web_browser/ -v` | 1 | — | All pass |

---

## Test Suite Details

### 1. Download Manager (`tests/download_manager/`)

**Files:**
- `test_download_manager.py` — 27 scenarios (S1–S27), 129 assertions with KPI report
- `test_dm_stress.py` — 10 heavy-load scenarios (H1–H10)
- `run_dm_test.py` — wrapper that captures output to `dm_results.txt`
- `dm_results.txt` — latest test output with KPI table

**What it covers:**

| Area | Scenarios |
|------|-----------|
| State machine transitions | S1: PENDING→DOWNLOADING→COMPLETED, FAILED→PENDING, PAUSED→PENDING |
| Priority preemption | S2: HIGH pauses NORMAL, CRITICAL pauses all, resume order |
| Disconnect/reconnect | S3: socket failure → state preserved → resume |
| File cleanup (R20) | S4: skip logic, per-patient retry deletion |
| Batch-skip (R19b) | S5: sequential file verification, gap detection |
| Thread safety | S6: 8 threads × 12 ops concurrency |
| Observer fan-out | S7: state changes propagate to all observers |
| Rule engine (R17a/R17b) | S8: duplicate detection, resume detection |
| Skip-count accuracy | S9: existing_files_set prevents double-counting |
| Priority ordering | S10: CRITICAL > HIGH > NORMAL sorting |
| State reset on resume | S11: progress counters cleared |
| Coordinator latency | S22: negotiate_priority_change completes <5ms |
| Observer chain | S23: state→priority→UI refresh sequence |
| Critical roundtrip | S24: request_critical_series end-to-end |
| Rapid toggle stress | S25: 100 NORMAL↔CRITICAL toggles |
| Auto-resume | S26: peers resume after critical done |
| Series-interrupt | S27: same-study worker cancel + PENDING state |

**Stress scenarios (H1–H10):**

| Scenario | Load | KPI Target |
|----------|------|-----------|
| H1 | 50 concurrent patients | StateStore handles in <100ms |
| H2 | 500 rapid series switches | Coordinator <5s total |
| H3 | 16 threads × 500 ops | P99 lock wait <5ms |
| H4 | 10,000 progress updates | No dropped signals |
| H5 | 200 studies × 20 series | Memory bounded |
| H6 | All studies CRITICAL | Deterministic resolution |
| H7 | 100 full lifecycle cycles | No state corruption |
| H8 | 10K files I/O | All created/verified |
| H9 | 1000 get_next_download | >1000/s throughput |
| H10 | Combined pipeline | <10ms/op end-to-end |

---

### 2. Viewer Pipeline (`tests/viewer/`)

**Files:**
- `test_fast_viewer_pipeline.py` — 18 pytest tests
- `test_dragdrop_progressive.py` — 16 pytest tests (drag-drop + progressive display regression suite)

#### `test_fast_viewer_pipeline.py` — 18 tests

| Test | Purpose |
|------|---------|
| `test_apply_loaded_series_data_rehydrates_parent_cache_without_refresh` | Cache rehydration without triggering viewer refresh |
| `test_get_series_by_number_fast_rehydrates_from_full_cache` | Fast-path cache hit returns correct data |
| `test_progressive_display_done_set` | Done-guard prevents duplicate initial loads |
| `test_progressive_display_inflight_guard` | Inflight set blocks concurrent loads for same series |
| `test_ensure_import_folder_path` | Study path resolution works during active download |
| `test_disk_count_cache_ttl` | `os.scandir` TTL cache expires after 1 second |
| `test_dm_notify_cooldown` | 500ms per-series cooldown enforced |
| `test_done_guard_recovery` | Recovery re-activates progressive mode if lost |
| `test_threaded_done_add_ordering` | Background thread done.add races are prevented |

#### `test_dragdrop_progressive.py` — 16 tests, 48 KPI assertions

Covers three bugs fixed in v2.2.8.1 where drag-dropping a not-yet-downloaded series left the viewer frozen on the old image, never showed the first batch, and never grew the second batch.

| # | Test | Bug / Area |
|---|------|------------|
| S1 | `test_awaiting_series_number_set_when_async_load_fails` | Bug C: spinner kept, marker set |
| S2 | `test_awaiting_series_number_cleared_on_new_dragdrop` | Bug C: new switch clears old marker |
| S3 | `test_repeated_dragdrop_overwrites_awaiting_marker` | Bug C: latest drop wins |
| S4 | `test_progress_scan_finds_awaiting_viewer` | Bug A: scan locates waiting viewer |
| S5 | `test_two_layouts_track_different_awaiting_series` | Bug A: independent per-layout markers |
| S6 | `test_apply_progressive_to_target_viewer_happy_path` | Bug A: display + progressive mode + spinner hide |
| S7 | `test_apply_progressive_to_target_viewer_cache_miss_hides_spinner` | Bug A: cleanup on cache miss |
| S8 | `test_inflight_guard_blocks_start_when_awaiting_viewer_present` | Guard correctness |
| S9 | `test_done_guard_blocks_restart_when_awaiting_viewer_present` | Guard correctness |
| S10 | `test_awaiting_scan_over_10_nodes_is_fast` | Perf: < 1ms avg over 10 nodes |
| S11 | `test_end_to_end_10series_patient_drag_drop_flow` | End-to-end A+B+C |
| S12 | `test_bug_a_first_batch_triggers_display_on_awaiting_viewer` | Bug A regression |
| S13 | `test_bug_b_second_batch_grows_not_restarts` | Bug B regression |
| S14 | `test_bug_c_dragdrop_replaces_image_and_escalates_priority` | Bug C regression |
| S15 | `test_stability_10_batches_one_start_nine_grows` | Stability: 10-batch state machine × 3 reps |
| S16 | `test_repeatability_full_dragdrop_plus_10_batches` | Repeatability: full lifecycle × 5, < 5ms/rep |

**Run both files together:**
```
.venv\Scripts\python.exe -m pytest tests/viewer/test_fast_viewer_pipeline.py tests/viewer/test_dragdrop_progressive.py -v
```
Expected: **34 passed**.

**Direct execution (with KPI report):**
```
.venv\Scripts\python.exe tests/viewer/test_dragdrop_progressive.py
```

**Other viewer tests:**
- `test_dicom_import_preview.py` — DICOM folder import preview dialog
- `test_flat_folder_import.py` — flat folder DICOM import
- `test_pooyan_opencv_filter.py` — OpenCV filter pipeline
- `tests/viewer/test_pydicom_backend_geometry.py` — geometry calculation correctness
- `test_viewer_backend_config.py` — backend selection logic
- `test_viewer_gpu_boost.py` — GPU acceleration configuration

---

### 3. Network (`tests/network/`)

**Files:**
- `test_network.py` — 8 scenarios with KPI report

**What it covers:**

| Scenario | Purpose |
|----------|---------|
| N1 | SocketConfig loading and defaults |
| N2 | Wire protocol: sendall, recv_exact, 4-byte framing |
| N3 | Response size limit (50 MB cap) |
| N4 | PatientListSocketClient pool (lazy creation, health check) |
| N5 | gRPC client auto-reconnect (`_ensure_stub`) |
| N6 | Token manager singleton thread safety |
| N7 | No hardcoded server IPs in constants |
| N8 | Connection pooling and reuse |

---

### 4. Database (`tests/database/`)

**Files:**
- `test_database.py` — 7 scenarios
- `run_db_test.py` — wrapper, output to `db_results.txt`

**What it covers:**

| Scenario | Purpose |
|----------|---------|
| D1 | Connection pool: lazy creation, validation, return |
| D2 | Context manager safety: auto-rollback, commit discipline |
| D3 | FK indexes existence verification |
| D4 | CRUD: patients, studies, series, instances |
| D5 | Search correctness: patient lookup |
| D6 | Thread safety: concurrent writes from multiple threads |
| D7 | Log throttle: min_ms suppression |

---

### 5. UI Services (`tests/ui_services/`)

**Files:**
- `test_ui_services.py` — service layer integration tests

**What it covers:**

| Area | Purpose |
|------|---------|
| HomeTabService | Tab lookup, activate, register, cache |
| HomeDownloadService | DM tab factory, signal wiring idempotency |
| home_widget_utils | `is_widget_alive()` across None/deleted/visible states |
| home_module_tabs | `activate_or_create_module_tab()` deduplication |
| HomeSearchService | Import viability |

---

### 6. Smoke Tests (`tests/smoke/`)

**Files:**
- `test_import_smoke.py` — parametrized module import validation
- `_simple_test.py` — basic sanity check

**What it covers:**
- 26+ module imports verified build-safe (no circular imports, no missing deps)
- Includes all v2.2.8.0 service layer modules, network modules, validation rules
- `PatientWidget` and `AiMainWindow` lazy export resolution
- `WebBrowserWidget` package export

---

### 7. Connection Between Modules (`tests/connection_between_modules/`)

**Files:**
- `test_connection_between_modules.py` — cross-module integration

**What it covers:**
- Download Manager ↔ State Store interaction with validation rules
- Rule engine + state store combined workflow
- Cross-module import chains

---

### 8. Builder Tests (`tests/builder/`)

**Files:**
- `test_build_gpu_profile.py` — GPU profile detection for build
- `test_materialize_plugin_packages.py` — plugin package materialization
- `test_plugin_package_builder.py` — plugin package build pipeline
- `test_plugin_package_registry.py` — package registry integrity

---

### 9. Peripheral Module Tests

| File | Module | Purpose |
|------|--------|---------|
| `tests/cd_burner/test_cd_burner_portability.py` | CD Burner | Cross-platform build portability |
| `tests/runtime/test_aipacs_runtime_graphics.py` | Runtime | Graphics fallback config validation |
| `tests/runtime/test_aipacs_runtime_modules.py` | Runtime | Module loading at startup |
| `tests/module_system/test_module_installation_packages.py` | Module System | Module install/uninstall packaging |
| `tests/printing/test_printing_series_repository.py` | Printing | Series data repository correctness |
| `tests/web_browser/test_web_browser_state_store.py` | Web Browser | Browser state persistence |

---

## KPI Thresholds

These are the performance KPIs enforced by the test suites:

| KPI | Target | Source |
|-----|--------|--------|
| State store create latency | <1ms | S1 (info metric) |
| Negotiate priority change | <5ms | S22 |
| Observer chain propagation | <2ms | S23 |
| Critical series roundtrip | <5ms | S24 |
| 100 rapid toggles | no corruption | S25 |
| Series-interrupt + state update | <5ms | S27 |
| 50 concurrent patients | <100ms total | H1 |
| 500 series switches | <5s total | H2 |
| 16-thread P99 lock wait | <5ms | H3 (expected fail) |
| 10K progress updates | 0 drops | H4 |
| Rule engine throughput | >1000 ops/s | H9 |
| Combined pipeline per-op | <10ms | H10 |
| Viewer frame time | <16ms (60 Hz) | Scroll performance target |
| progressive display first-batch→visible | <350ms | Pipeline latency budget |

## Running All Tests

```powershell
# Run all test suites sequentially
cd "c:\AI-Pacs codes\aipacs-pydicom2d"

# Core suites (custom runners)
.\.venv\Scripts\python.exe tests/download_manager/run_dm_test.py
.\.venv\Scripts\python.exe tests/download_manager/test_dm_stress.py
.\.venv\Scripts\python.exe tests/network/test_network.py
.\.venv\Scripts\python.exe tests/database/run_db_test.py

# Pytest suites
.\.venv\Scripts\python.exe -m pytest tests/viewer/test_fast_viewer_pipeline.py -v
.\.venv\Scripts\python.exe -m pytest tests/smoke/test_import_smoke.py -v
.\.venv\Scripts\python.exe -m pytest tests/connection_between_modules/ -v
.\.venv\Scripts\python.exe -m pytest tests/builder/ -v
.\.venv\Scripts\python.exe -m pytest tests/cd_burner/ -v
.\.venv\Scripts\python.exe -m pytest tests/runtime/ -v
.\.venv\Scripts\python.exe -m pytest tests/module_system/ -v
.\.venv\Scripts\python.exe -m pytest tests/printing/ -v
.\.venv\Scripts\python.exe -m pytest tests/web_browser/ -v
```

---

## Test Gap Analysis

The following areas do NOT have dedicated test coverage yet:

| Area | Risk | Recommended test type |
|------|------|-----------------------|
| Login authentication flow | Medium | Integration (mock socket) |
| Theme switching | Low | Smoke test (import + apply) |
| Patient table sorting/filtering | Medium | Unit test (SortableItem logic) |
| Image filter pipeline (ITK/VTK) | High | Unit test with synthetic DICOM |
| Window/Level presets | Medium | Unit test (calculation correctness) |
| Reference line computation | High | Unit test (geometry math) |
| ZetaBoost L1/L2 cache eviction | Medium | Unit test (cache size limits) |
| Shutdown sequence (LifecycleManager) | High | Integration (mock registrations) |
| CD burner full pipeline | Low | Integration (requires CD drive) |
| Upload/attachment flow | Low | Integration (mock server) |

---

## Test Files by Module (quick index)

```
tests/
├── download_manager/
│   ├── test_download_manager.py   ← S1–S27 (129 assertions)
│   ├── test_dm_stress.py          ← H1–H10 (heavy load)
│   ├── run_dm_test.py             ← runner wrapper
│   └── dm_results.txt             ← latest output
├── viewer/
│   ├── test_fast_viewer_pipeline.py ← 11 progressive display tests
│   ├── test_pydicom_backend_geometry.py
│   ├── test_viewer_backend_config.py
│   ├── test_viewer_gpu_boost.py
│   ├── test_dicom_import_preview.py
│   ├── test_flat_folder_import.py
│   └── test_pooyan_opencv_filter.py
├── network/
│   └── test_network.py            ← N1–N8 (socket/gRPC)
├── database/
│   ├── test_database.py           ← D1–D7
│   └── run_db_test.py
├── ui_services/
│   └── test_ui_services.py        ← service layer imports
├── smoke/
│   └── test_import_smoke.py       ← 26+ module imports
├── connection_between_modules/
│   └── test_connection_between_modules.py
├── builder/
│   ├── test_build_gpu_profile.py
│   ├── test_materialize_plugin_packages.py
│   ├── test_plugin_package_builder.py
│   └── test_plugin_package_registry.py
├── cd_burner/
│   └── test_cd_burner_portability.py
├── runtime/
│   ├── test_aipacs_runtime_graphics.py
│   └── test_aipacs_runtime_modules.py
├── module_system/
│   └── test_module_installation_packages.py
├── printing/
│   └── test_printing_series_repository.py
└── web_browser/
    └── test_web_browser_state_store.py
```
