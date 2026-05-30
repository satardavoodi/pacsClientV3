# AI-PACS Documentation — Index by Subsystem

When you're about to touch a subsystem, this index tells you which docs to read first. Most subsystems have an "as-built" plan that codifies invariants; the catalog row tells you which guard test enforces them at runtime.

---

## Master indexes

- **[Audit overview (2026-05-28)](AUDIT_2026-05-28_OVERVIEW.md)** — every stage report linked
- **[Regression catalog](plans/architecture/REGRESSION_CATALOG.md)** — every fix + its guard test (37 rows)
- **[Test inventory](../tests/INDEX_BY_GUARD.md)** — every guard test and what it protects
- **[For future agents](for-future-agents/README.md)** — onboarding for AI agents working in this repo

---

## Subsystems

### Viewer (multi-study, sidebar, drag-drop)

| Doc | What's in it |
|---|---|
| **[`MULTI_STUDY_SINGLE_TAB_PLAN.md`](MULTI_STUDY_SINGLE_TAB_PLAN.md)** | **Required reading before editing the viewer.** Offset-key invariants, `_render_multistudy_grouped` behavior, server-info dict shape. |
| [`AUDIT_STAGE_5_2026-05-28.md`](plans/architecture/AUDIT_STAGE_5_2026-05-28.md) | Read-only `ViewerAdapter` live verification. |
| [`AUDIT_STAGE_6_2026-05-28.md`](plans/architecture/AUDIT_STAGE_6_2026-05-28.md) | Multi-study live workflow audit (239 series across 5+ studies). |
| [`pipelines/thumbnail-pipeline.md`](pipelines/thumbnail-pipeline.md) | THUMBNAIL_PATH conventions, memory-first vs disk fallback. |

**Guard tests:**
- `tests/code/echomind/test_viewer_adapter.py` — 11 read-only adapter contract guards
- `tests/code/system/test_2026_05_27_regression_guards.py::test_change_series_signature_matches_base`

---

### Download Manager (Zeta) + bulk download

| Doc | What's in it |
|---|---|
| **[`plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`](plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md)** | As-built review and fix plan; §13 = applied vs outstanding; §14 = patient-open stall; §15 = socket/gRPC path map. |
| [`AUDIT_STAGE_4_2026-05-28.md`](plans/architecture/AUDIT_STAGE_4_2026-05-28.md) | Live bulk-download audit (35 patients in 8 s). |
| [`AUDIT_STAGE_4b_2026-05-28.md`](plans/architecture/AUDIT_STAGE_4b_2026-05-28.md) | DM controls (Pause / Cancel / Retry / Reset / priority dropdown). |

**Guard tests (in `tests/code/system/test_2026_05_27_regression_guards.py`):**
- `test_probe_uses_raw_send_request_not_helper` — GetStudyInfo 6.8 s stall guard
- `test_probe_lock_is_module_level`, `test_probe_lock_is_used_in_get_series_info_from_server`
- `test_prefetch_uses_threadpool_executor`, `test_prefetch_has_no_sequential_loop`, `test_parallel_prefetch_is_faster_than_sequential`

---

### UI / Design system (V2, flag-gated) + viewer interaction

| Doc | What's in it |
|---|---|
| **[`design/V2_DESIGN_SYSTEM_AS_BUILT.md`](design/V2_DESIGN_SYSTEM_AS_BUILT.md)** | **Required reading before editing `v2_style.py`, `ui_variant.py`, toolbar/home styling.** Flag gating, apply-at-source rule, where each V2 style is applied, design-language invariants, how to extend. |
| [`design/DROPDOWN_SUBMENU_REVIEW.md`](design/DROPDOWN_SUBMENU_REVIEW.md) | Original dropdown/submenu review (rollout now complete). |
| [`design/VIEWER_TOOLBAR_INTERACTION_REVIEW.md`](design/VIEWER_TOOLBAR_INTERACTION_REVIEW.md) | Toolbar hover / dropdown attach / menu layout review. |
| **[`plans/performance/FAST_STACK_DRAG_PRESSURE_FIX_2026-05-30.md`](plans/performance/FAST_STACK_DRAG_PRESSURE_FIX_2026-05-30.md)** | Stack-drag main-thread stall fix: drag-pressure psutil sampler gated off by default (`AIPACS_FAST_STACK_PRESSURE`). Don't call psutil on the drag hot path. |

**Guard tests:**
- `tests/code/test_v2_style_scaffold.py` — pure-function QSS builder + gate guards
- `tests/code/test_ui_variant_scaffold.py` — flag resolution never raises

---

### Patient search + patient list

| Doc | What's in it |
|---|---|
| [`AUDIT_STAGE_2_2026-05-28.md`](plans/architecture/AUDIT_STAGE_2_2026-05-28.md) | Search workflow audit, `_hp_search.py` print-to-logger fixes. |

**Guard test:** `tests/code/system/test_hp_search_logging_guard.py` (5 guards)

---

### Patient open + tab management

| Doc | What's in it |
|---|---|
| [`AUDIT_STAGE_3_2026-05-28.md`](plans/architecture/AUDIT_STAGE_3_2026-05-28.md) | Click-to-open audit, cross-patient isolation verification. |
| [`AUDIT_STAGE_10_2026-05-28.md`](plans/architecture/AUDIT_STAGE_10_2026-05-28.md) | Print-rebind → debug-silencing fix (13 error paths now visible in `app.log`). |

**Guard test:** `tests/code/system/test_hp_patient_open_logging_guard.py` (4 guards)

---

### Database (`dicom.db`) + test isolation

| Doc | What's in it |
|---|---|
| **`COPILOT_REPORT_db_cleanup.md`** (top-level) | 2026-05-24 pollution cleanup record. Patch `PacsClient.utils.data_paths.DATABASE_FILE` for tests, NOT `database.core._DB_PATH`. |

**Guard test:** `tests/code/database/conftest.py` (PRAGMA `database_list` invariant — loud-fail if a test connects to the live DB).

---

### Eagle Eye / AI module

| Doc | What's in it |
|---|---|
| [`AUDIT_STAGE_7_2026-05-28.md`](plans/architecture/AUDIT_STAGE_7_2026-05-28.md) | Three-layer defense map (structural + canonical pywinauto + modality gate). |

**Guard tests:**
- `tests/code/system/test_2026_05_27_regression_guards.py::test_mg_mirror_is_deferred_via_qtimer` (structural)
- `tests/gui/pywinauto/test_eagle_eye_dragdrop.py` (canonical Win32 OLE drag-drop)

---

### Module launchers (Eagle Eye / MPR / Printing / Education / Advanced Analysis)

| Doc | What's in it |
|---|---|
| [`AUDIT_STAGE_8_2026-05-28.md`](plans/architecture/AUDIT_STAGE_8_2026-05-28.md) | **Adapter-readiness map per module.** Lists where each launcher lives and what refactor it needs before CommandBus integration. |

**Guard tests:**
- `tests/code/echomind/test_module_adapter.py`
- `tests/code/echomind/test_module_catalog_coverage.py` (drift reporter — currently 4 / 15 wired = 27 %)
- `tests/code/echomind/test_bus_factory.py`

---

### Unified Command Layer (EchoMind / CommandBus / Adapters)

| Doc | What's in it |
|---|---|
| **[`plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md`](plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md)** | Architecture design. |
| [`plans/architecture/IMPLEMENTATION_PLAN_2026-05-27.md`](plans/architecture/IMPLEMENTATION_PLAN_2026-05-27.md) | Phase-by-phase spec. |

**Guard tests:** every file under `tests/code/echomind/` (12 files).

---

### Layout & responsive UI

| Doc | What's in it |
|---|---|
| **[`conventions/RESPONSIVE_UI_CONVENTION.md`](conventions/RESPONSIVE_UI_CONVENTION.md)** | The seven archetypes (horizontal scroll wrap, wrapping label, elided label, splitter, min-height form fields, table column policy, empty-state). |
| [`plans/RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md`](plans/RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md) | Background + decision tree. |
| [`AUDIT_STAGE_9_2026-05-28.md`](plans/architecture/AUDIT_STAGE_9_2026-05-28.md) | `QScrollArea.setHorizontalScrollMode` regression fix. |

**Guard tests:**
- `tests/code/system/test_responsive_layout_qscrollarea_guard.py` (4 guards)
- `tests/code/system/test_titlebar_userinfo_clamp_guard.py` (7 guards)

---

### Logging & observability

| Doc | What's in it |
|---|---|
| [`AUDIT_STAGE_10_2026-05-28.md`](plans/architecture/AUDIT_STAGE_10_2026-05-28.md) | `app.log` catch-all handler + `_hp_patient_open` print-rebind fix. |

**Guard tests:**
- `tests/code/system/test_diagnostic_logging_catchall.py` (7 structural guards)
- `tests/code/system/test_hp_patient_open_logging_guard.py` (4 guards)
- `tests/code/system/test_hp_search_logging_guard.py` (5 guards)

---

### KPI machinery

| Doc | What's in it |
|---|---|
| **[`tests/_kpi/README.md`](../tests/_kpi/README.md)** | How to add a new KPI, how the collector hooks the bus, how the reporter CLI works. |
| [`plans/architecture/SCENARIO_KPIS_2026-05-28.md`](plans/architecture/SCENARIO_KPIS_2026-05-28.md) | KPI taxonomy — 42 keys across 13 workflows. |

**Guard test:** `tests/code/system/test_kpi_schema.py` (registered-keys integrity).

**Tools:**
- `tools/kpi_dashboard.py` — framework health snapshot (exit 0 / 1 / 2)
- `tools/kpi_html_report.py` — trend report from the JSONL sink
- `tools/kpi_build_compare.py` — cross-build divergence detector

---

### Testing architecture

| Doc | What's in it |
|---|---|
| **[`plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`](plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md)** | The full design — goals, taxonomy, test discipline, regression-catalog rules. |
| [`tests/QUICKSTART.md`](../tests/QUICKSTART.md) | 5-minute onboarding — how to run, where to add tests, the hard rules. |
| [`AUDIT_2026-05-28_OVERVIEW.md`](AUDIT_2026-05-28_OVERVIEW.md) | What the audit produced and the cumulative numbers. |
