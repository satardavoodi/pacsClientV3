# AI-PACS Documentation — Index by Subsystem

When you're about to touch a subsystem, this index tells you which docs to read first. Most subsystems have an "as-built" plan that codifies invariants; the catalog row tells you which guard test enforces them at runtime.

---

## Master indexes

- **[Audit overview (2026-05-28)](AUDIT_2026-05-28_OVERVIEW.md)** — every stage report linked
- **[Regression catalog](plans/architecture/REGRESSION_CATALOG.md)** — every fix + its guard test (54 rows)
- **[Test inventory](../tests/INDEX_BY_GUARD.md)** — every guard test and what it protects
- **[For future agents](for-future-agents/README.md)** — onboarding for AI agents working in this repo
- **[Open findings (2026-08-16)](reports/OPEN_FINDINGS_2026-08-16.md)** — diagnosed but deliberately NOT fixed. §1 (pixel cache) has since been resolved; **§2, the ~4-5.5 s MPR activation stall, is still open** and is the app's largest remaining freeze. Read it before touching MPR activation.

---

## Subsystems

### EchoMind (reporting prompts, region gating, chat metadata)

| Doc | What's in it |
|---|---|
| **[`echomind/README.md`](echomind/README.md)** | **Start here.** Index, the one-page mental model, and the six invariants. |
| [`echomind/01-architecture.md`](echomind/01-architecture.md) | Module map, the three backends, and what every workflow calls. |
| [`echomind/02-prompt-architecture.md`](echomind/02-prompt-architecture.md) | The nine prompt slots, what is shared vs gated, the load-bearing rules. |
| [`echomind/03-region-gating.md`](echomind/03-region-gating.md) | What a gate is, what selects it, multi-region selection. |
| [`echomind/04-chat-metadata.md`](echomind/04-chat-metadata.md) | Where every field comes from, the three layers, storage, edits. |
| [`echomind/05-mobile-parity.md`](echomind/05-mobile-parity.md) | What Android and iOS must reproduce byte-for-byte. |
| [`echomind/06-extending.md`](echomind/06-extending.md) | Adding a modality, region, subtype, lexicon or rule. |
| [`pipelines/echomind-reporting-prompts.md`](pipelines/echomind-reporting-prompts.md) | Per-modality prompt bodies and the preservation rule. Partly superseded - see `echomind/README.md`. |

**Guard tests:**
- `tests/code/echomind/test_turbo_template.py` - 103 guards on the template, the region packages and the gate
- `tests/code/echomind/test_turbo_prompt_seam.py` - the Turbo/Send seam
- `tests/code/echomind/test_metadata_detection.py`, `test_metadata_card.py`, `test_reception_prefetch.py`

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

### Viewer cold-start cost (series load, pixel cache, import warm)

**The recurring lesson in this area: the cost is almost never parsing or thread count — it is FIRST TOUCH.** This machine runs two real-time AV engines, and cold/warm ratios of 7-100× on the *same bytes* have been measured repeatedly. Benchmark warm vs cold before attributing a slow load to the code.

| Doc | What's in it |
|---|---|
| **[`reports/SERIES_HEADER_SCAN_COLD_LOAD_2026-08-08.md`](reports/SERIES_HEADER_SCAN_COLD_LOAD_2026-08-08.md)** | Patient 53417, ~15.7 s to get series 202 on screen. The switch-time probe was already header-only (`stop_before_pixels` + `specific_tags`): 40.5 ms/file cold vs 0.88 ms/file warm, and more threads cap at ~2.3×. Fix = a budgeted read-only pre-read at patient open (WU-1). Full per-file verification is unchanged. |
| [`reports/WEBENGINE_WARMUP_EVALUATION_2026-08-16.md`](reports/WEBENGINE_WARMUP_EVALUATION_2026-08-16.md) | §8 documents the async pixel-cache init and the `viewer-import-warm` thread running off the GUI thread in a live run, plus the 7.6× cold/warm read on identical bytes. |
| **[`reports/PIXEL_CACHE_PERSISTENCE_2026-08-16.md`](reports/PIXEL_CACHE_PERSISTENCE_2026-08-16.md)** | The L2 pixel cache now **survives shutdown** (it never did before: 18 wipes / `0 entries` indexed, measured). `clear_on_exit()` vs `clear()`, why persistence is bounded, the 2 GB / PHI-at-rest trade, and the one residual risk (a reused SOP UID with different pixels). |
| **[`reports/OPEN_FINDINGS_2026-08-16.md`](reports/OPEN_FINDINGS_2026-08-16.md)** | §1 **resolved** (see above) — kept as the record of how the decision was reached. §2 still **OPEN**: MPR activation blocks the GUI thread ~4-5.5 s and the non-axial views are uninstrumented. |

**Invariants:**
- `DiskPixelCache.initialize()` stays **synchronous** for every direct caller; only `get_disk_pixel_cache()` passes `background=True`. An unindexed lookup is simply a cache miss, which is why this is safe.
- The index's **order is the LRU order** (`_evict_if_needed` pops the front). A background scan must re-sort by access time on merge, or the newest slices become the first evicted. This is also what makes persistence safe — without it the slice viewed last before closing would be first evicted next session.
- The shutdown path calls **`clear_on_exit()`, never `clear()`**. `clear()` must stay unconditional so an explicit user-initiated "clear cache" always clears; only the shutdown *policy* is configurable (`AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT=1`).
- The import warm creates **no Qt objects** — it is pure imports on a daemon thread.
- FAST viewer mode must **never** instantiate VTK render windows. Anything added to warm or cache the MPR path must not be reachable from FAST.

**Guard tests:**
- `tests/code/viewer/test_series_file_warm.py` (12) — budget caps, kill switch, blank-path refusal, no duplicate concurrent warm
- `tests/code/viewer/test_disk_pixel_cache_async_init.py` (10) — incl. a threaded writer-vs-scan race and LRU order after merge
- `tests/code/viewer/test_viewer_import_warm.py` (8) — fails if the warm ever touches a Qt object, or if the windowing path stops using `np.percentile`
- `tests/code/viewer/test_disk_pixel_cache_persistence.py` (20) — the cache survives shutdown, the kill switch really wipes, `clear()` stays unconditional, and eviction still bounds a persisted cache

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

### Web browser module + startup / engine warm-up

**Read this before touching `modules/web_browser/prewarm.py`.** Four live freezes came out of this one file (~17 s 2026-07-23, 39.7 s 2026-08-05, 19 s 2026-08-07, **72 s 2026-08-16**) and the lesson took all four to learn: *when* the Chromium construct runs was never the problem — its **cost is unbounded and cannot be capped**, because Qt requires it on the GUI thread and the call is atomic. Do not "improve the scheduling" here again.

| Doc | What's in it |
|---|---|
| **[`reports/FREEZE_72S_BROWSER_PREWARM_2026-08-16.md`](reports/FREEZE_72S_BROWSER_PREWARM_2026-08-16.md)** | **Start here.** The 72 s incident, why every scheduling guard behaved correctly, and why the answer was to make the pre-warm opt-in (IMP-4). |
| [`reports/PREWARM_DBLCLICK_FREEZE_2026-08-07.md`](reports/PREWARM_DBLCLICK_FREEZE_2026-08-07.md) | The 19 s double-click freeze → the input-recency veto (IMP-3). Explains why `_finish_watch` must keep the input filter installed. |
| [`reports/WEBENGINE_WARMUP_EVALUATION_2026-08-16.md`](reports/WEBENGINE_WARMUP_EVALUATION_2026-08-16.md) | Phase-by-phase cost of the engine boot (IMP-5): `defaultProfile()` is the 918 ms global init, `QWebEngineView()` is 0 ms. §8 is the confirmed live run — 208 ms GUI block, 884 ms total. Chromium flags are measured and are NOT a lever. |
| [`reports/WEB_BROWSER_MODULE_FIXES_2026-06-27.md`](reports/WEB_BROWSER_MODULE_FIXES_2026-06-27.md) | Earlier module fixes. |

**Invariants:**
- The pre-warm is **opt-in**: `AIPACS_BROWSER_PREWARM=1` (a literal `"1"`), *and* the adaptive used-marker still gates on top.
- Warm the **default profile**, never a throwaway `QWebEngineView` + `setUrl` — same benefit, ~24 % less GUI block, no render process held to be discarded.
- The off-thread file warm is **name-scoped** (`_WARM_DLL_HINTS`), not a blanket DLL sweep, and stays budget-capped.

**Guard tests:**
- `tests/code/web_browser/test_prewarm_recency_veto.py` (13) — input filter survives the warm; construct re-checks recency
- `tests/code/web_browser/test_prewarm_idle_gate.py` — default-profile warm + the DLL-name-scoped file warm
- `tests/code/system/test_browser_prewarm_idle_gate.py` — opt-in default, marker gate on top, only a literal `"1"` enables it
- `tests/code/web_browser/test_prewarm_busy_veto.py`

---

### UI / Design system (V2, flag-gated) + viewer interaction

| Doc | What's in it |
|---|---|
| **[`design/V2_DESIGN_SYSTEM_AS_BUILT.md`](design/V2_DESIGN_SYSTEM_AS_BUILT.md)** | **Required reading before editing `v2_style.py`, `ui_variant.py`, toolbar/home styling.** Flag gating, apply-at-source rule, where each V2 style is applied, design-language invariants, how to extend. |
| [`design/DROPDOWN_SUBMENU_REVIEW.md`](design/DROPDOWN_SUBMENU_REVIEW.md) | Original dropdown/submenu review (rollout now complete). |
| [`design/VIEWER_TOOLBAR_INTERACTION_REVIEW.md`](design/VIEWER_TOOLBAR_INTERACTION_REVIEW.md) | Toolbar hover / dropdown attach / menu layout review. |
| **[`plans/performance/FAST_STACK_DRAG_PRESSURE_FIX_2026-05-30.md`](plans/performance/FAST_STACK_DRAG_PRESSURE_FIX_2026-05-30.md)** | Stack-drag main-thread stall fix: drag-pressure psutil sampler gated off by default (`AIPACS_FAST_STACK_PRESSURE`). Don't call psutil on the drag hot path. |
| **[`reports/THUMBNAIL_STRIP_AND_ACTIVE_STATE_2026-08-09.md`](reports/THUMBNAIL_STRIP_AND_ACTIVE_STATE_2026-08-09.md)** | **Required reading before touching the series thumbnail card.** The download bar / red active line share one bottom strip; `QLayout.addWidget()` RE-PARENTS and moves a widget to the TOP of the sibling stack, which is what buried the bar. Also the A→B→A active-state bug and `set_active_series()` as the single entry point. |
| [`reports/MAIN_FOOTER_BAR_REMOVAL_2026-08-10.md`](reports/MAIN_FOOTER_BAR_REMOVAL_2026-08-10.md) | The stray bar at the bottom of the main page — an empty Designer footer whose only visible output was its own chrome. Hidden, not deleted (`apply_theme` still styles it). Restore with `AIPACS_MAIN_FOOTER=1`. |

**Guard tests:**
- `tests/code/test_v2_style_scaffold.py` — pure-function QSS builder + gate guards
- `tests/code/test_ui_variant_scaffold.py` — flag resolution never raises
- `tests/code/ui_services/test_thumbnail_active_state_and_strip.py` (20) — **behavioural**, on real Qt widgets. A source-string pin cannot see a z-order bug; that is exactly how the buried download bar survived `test_thumbnail_panel_ui_fixes.py`.
- `tests/code/ui_services/test_main_footer_bar_removed.py` (6) — footer stays hidden, its widgets stay alive, and it fails loudly if anyone starts writing to its labels

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
