# AI-PACS Test Inventory — Index by Guard

Every guard test in `tests/code/system/` is paired with one row of `docs/plans/architecture/REGRESSION_CATALOG.md`. This index tells you, for each test file: **what it protects, what bug it would re-introduce if removed, and where to read the audit report**.

For an alphabetical layout map (where tests live), see [`README.md`](README.md). For the 5-minute onboarding, see [`QUICKSTART.md`](QUICKSTART.md).

---

## How to use this index

When you touch a subsystem:

1. Look up the subsystem in [`../docs/INDEX_BY_SUBSYSTEM.md`](../docs/INDEX_BY_SUBSYSTEM.md).
2. Identify which guard tests cover it.
3. Run them BEFORE your change so you have a green baseline.
4. Run them AFTER your change so any regression is loud.

When you ship a fix:

1. Add a row to `docs/plans/architecture/REGRESSION_CATALOG.md`.
2. Add a guard test to `tests/code/system/test_<scope>_guard.py`.
3. Add a row to this index.
4. Update the cumulative count in `docs/AUDIT_2026-05-28_OVERVIEW.md`.

---

## System-level structural guards (`tests/code/system/`)

| Test file | Guards | What it protects |
|---|---|---|
| `test_2026_05_27_regression_guards.py` | **15** | GetStudyInfo 6.8 s stall (4 probe guards), Eagle Eye COM 0x8001010d (3 mg-mirror QTimer guards), bulk-download UI freeze (5 ThreadPool prefetch guards), compile gates (3) |
| `test_kpi_schema.py` | KPI registry integrity | Each KPI key registered + threshold ordering correct |
| `test_diagnostic_logging_catchall.py` | **7** | `app.log` catch-all handler (download/viewer/db component routing + 4th catch-all for everything else); without this, UI/home events vanish |
| `test_hp_search_logging_guard.py` | **5** | Error paths in `_hp_search.py` use `_logger.error`, not `print()` |
| `test_hp_patient_open_logging_guard.py` | **4** | Error paths in `_hp_patient_open.py` bypass the `print → _logger.debug` rebind; success traces stay at debug |
| `test_responsive_layout_qscrollarea_guard.py` | **4** | `wrap_in_horizontal_scroll` uses `setSingleStep` not the bogus `setHorizontalScrollMode`; `QAbstractScrollArea` not re-imported |
| `test_titlebar_userinfo_clamp_guard.py` | **7** | TitleBar QFrame + user_info_container both have `setMaximumHeight` + Fixed vertical size policy; 84 / 70 px floors preserved |
| `test_thumbnail_card_height_guard.py` | **6** | Right-panel card height 215 px so server-desc + image-count labels coexist; progress overlay y-center recomputed for new height |
| `test_ui_polish_2026_05_29_guard.py` | **4** | Title bar maxHeight 110, right-panel grid vert spacing 14 + right margin 22, patient table `setShowGrid(False)` |
| `test_patient_tab_strip_width_guard.py` | **6** | tab_area carries stretch=1 (claims ~2/3 title bar); chip strip max_height ≥ 80 (10 px buffer); no outer trailing addStretch; **inner title_bar_tabs_layout has trailing addStretch(1) so chips left-pack inside QScrollArea (round-4)**; `_add_title_bar_tab_widget` uses `count()-1` to insert before the stretch |
| `test_max_patient_tabs_message_guard.py` | **3** | "Maximum Patient Tabs Reached" message in `_hp_modules.py` interpolates `MAX_PATIENT_TABS` (no hardcoded digit); constant is imported; `add_patient_tab` docstring doesn't pin a stale numeric literal |
| `test_right_panel_reserved_height_guard.py` | **2** | `RightPanelWidget.THUMBNAIL_BOX_HEIGHT` is coupled to `ThumbnailManager.create_thumbnail_widget`'s real card height (215) by source-parse; constant has a comment pointing at thumbnail_manager.py as source-of-truth |
| `test_patient_click_double_click_guard.py` | **4** | `_on_patient_clicked` does NOT call the redundant `highlight_selected_row(row)` that broke double-click detection; `itemClicked` + `itemDoubleClicked` signals stay wired to their handlers; table keeps `SelectRows` behaviour so Qt's native selection still fires |
| `test_right_panel_min_width_guard.py` | **2** | `RightPanelWidget.setMinimumWidth(N)` is large enough that at the floor there's ≥22 px gap between the 190 px card right edge and the AlwaysOn 12 px vertical scrollbar (so the dotted border can't visually clip into the scrollbar); constant has a geometry comment so future agents don't lower it |
| `test_system_stress.py` | (env-gated) | Multi-process stress patterns (skips in sandbox) |

**Subtotal: 73 system-level guards across 14 active files.**

---

## EchoMind / Command Layer (`tests/code/echomind/`)

| Test file | What it protects |
|---|---|
| `test_command_envelope.py` | Pydantic `CommandRequest` / `CommandPlan` / `CommandResult` round-trip with the legacy TypedDict |
| `test_adapter_registry.py` | `AdapterRegistry` dispatch, action mapping, scalar-payload normalization |
| `test_command_bus_unit.py` | `CommandBus.parse / execute / dispatch / dispatch_async` |
| `test_system_adapter.py` | `SystemAdapter` psutil probes (resources, process count, native faults, idle CPU) |
| `test_download_adapter.py` | `DownloadAdapter` pause / cancel / list / statistics |
| `test_module_adapter.py` | `ModuleAdapter` open_module / convenience aliases / launcher-failure handling |
| `test_viewer_adapter.py` | **Structural read-only enforcement** — no write-verb actions exist; multi-study flag propagation; offset-key preservation |
| `test_bus_factory.py` | `build_command_bus()` wires adapters correctly given different launcher dicts |
| `test_kpi_auto_record.py` | `hook_bus(bus)` auto-records `<action>.elapsed_ms` to the sink |
| `test_module_catalog_coverage.py` | Catalog vs CommandBus drift reporter; INFRASTRUCTURE_ACTIONS ⊥ catalog actions invariant |

**Subtotal: 12 unit-test files.**

---

## GUI tests (`tests/gui/`)

### `pywinauto/` — Windows UI Automation

| Test file | What it protects |
|---|---|
| `test_eagle_eye_dragdrop.py` | **The canonical 0x8001010d COM crash test** — only test that fires real Win32 OLE drag-drop messages. Requires source build + `_verify_source_build()`. |
| `test_close_no_zombie.py` | App fully exits — no orphan process in Task Manager after close |
| `test_open_close_cycles.py` | N-launch restart-to-ready KPI + zombie process leak (env-gated `AIPACS_CYCLE_LAUNCH_CMD`) |
| `test_thumbnail_pixel_isolation.py` | Pixel-diff: cross-patient thumbnail leak at the rendered-output level |

**Subtotal: 4 pywinauto tests.**

### `echomind_driven/` — CommandBus-driven scenarios

| Test file | What it protects |
|---|---|
| `test_command_bus_smoke.py` | Bus fixture works end-to-end with a `FakeHomeAdapter` |
| `test_scenario_1_patient_open.py` | Click-to-thumbnail latency KPI (`patient_open.elapsed_ms`) |
| `test_scenario_3_bulk_download.py` | 20+ patient enqueue speed |
| `test_idle_resource_budget.py` | `proc.idle_cpu_pct` + `crash.native_fault_count` budgets |
| `test_dm_status_workflow.py` | Status → list → cancel via `bus.execute` |
| `test_cross_patient_thumbnail_isolation.py` | Typed regression: patient A's thumbnails must not appear on B |
| `test_long_session_workload.py` | RSS-growth + leak KPI across hours (env-gated) |

**Subtotal: 7 bus-driven scenarios.**

### `live_walkthroughs/` — one-off agentic scripts

- `_verify_source_build.py` — pre-flight: refuses to run against the frozen exe
- `extract_2026_05_27_kpis.py` — log → PASS / CHECK extractor

---

## KPI machinery (`tests/_kpi/`)

| File | Purpose |
|---|---|
| `schema.py` | 42 registered KPI keys across 13 workflows |
| `collector.py` | `KpiCollector` + `kpi` pytest fixture + `hook_bus(bus)` auto-recording |
| `reporter.py` | CLI: `last` / `trend` / `diff` / `summary` over `user_data/test_kpis/<run>.jsonl` |
| `baseline.json` | Last-known-good values per key |
| [`README.md`](_kpi/README.md) | How to add a new KPI |

**Tools that consume this sink:**
- `tools/kpi_dashboard.py` — framework health snapshot
- `tools/kpi_html_report.py` — self-contained trend report
- `tools/kpi_build_compare.py` — cross-build divergence detector

---

## Domain-specific code tests (`tests/code/<domain>/`)

The `tests/code/` directory has 26 domain folders; **183 files total**. Highlights:

| Domain | What it covers |
|---|---|
| `architecture/` | Module boundary contracts (DM widget responsibilities, etc.) |
| `database/` | Connection pool, schema migration, test isolation |
| `download_manager/` | DM widget init contract, network paths, queue ordering |
| `fast/` | FAST viewer mode primitives (pydicom backend) |
| `fast_viewer/` | FAST viewer integration |
| `viewer/` | Standard viewer pipeline, multi-study state |
| `network/` | Socket / gRPC client behavior |
| `ui_services/` | Patient table, search-sort, sidebar rendering |
| `runtime/` | Runtime profile (FAST vs Advanced), GPU detection |
| `startup/` | Boot ordering, env-var contracts |
| `utils/` | Path resolvers, structured logging helpers |
| `system/` | **Cross-cutting structural guards listed above** |
| `echomind/` | **Command Layer unit tests listed above** |

For each domain, the matching docs live under `docs/` — start at [`../docs/INDEX_BY_SUBSYSTEM.md`](../docs/INDEX_BY_SUBSYSTEM.md).

---

## Cumulative count (post-audit 2026-05-29)

- **Total test files: 194** (code = 183, bus-driven = 7, pywinauto = 4)
- **Sandbox-runnable code tests: 121 / 0 / 0**
- **Structural system guards: 46 across 7 files**
- **Regression catalog rows: 37**
- **KPI registered keys: 42 across 13 workflows**

These numbers come from `python tools/kpi_dashboard.py` and `pytest tests/code/echomind tests/code/system`. They are the long-term measurement surface — every PR that lands a fix should make the catalog and test counts grow together.
