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
| `test_credential_obfuscation.py` | EchoMind center access codes and provider credentials never ship as plaintext; access-code-derived AES-GCM envelopes open only the selected center; tampering and missing Company Server 3 entitlement fail closed |

**Subtotal: 13 unit-test files.**

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

## 2026-08 additions — startup, warm-up and thumbnail guards

These live outside `tests/code/system/`, so they are easy to miss from the
system table above. Each pairs with a 2026-08 row in the regression catalog.

| Test file | Guards | What it protects |
|---|---|---|
| `code/web_browser/test_prewarm_recency_veto.py` | **13** | The input filter SURVIVES the warm (`_finish_watch(warm=True)` must not remove it) and `_on_construct` re-checks input recency before blocking the GUI thread. Removing these re-introduces the 19 s double-click freeze. |
| `code/system/test_browser_prewarm_idle_gate.py` | +3 | The pre-warm is **opt-in**: only a literal `AIPACS_BROWSER_PREWARM="1"` enables it, and the adaptive used-marker still gates on top. Removing these re-introduces the 72 s freeze. |
| `code/web_browser/test_prewarm_idle_gate.py` | +4 | Warm the **default profile**, never a throwaway `QWebEngineView` + `setUrl`; the DLL file warm stays **name-scoped** and budget-capped. |
| `code/viewer/test_series_file_warm.py` | **12** | The patient-open file warm stays read-only, daemon-threaded, budget-capped, kill-switchable, and refuses blank/duplicate work. It must never become the thing that verifies series files — the switch-time scan still does that. |
| `code/viewer/test_disk_pixel_cache_async_init.py` | **10** | `initialize()` stays synchronous for direct callers; only the singleton goes background. Includes a threaded writer-vs-scan race and the LRU-order-after-merge invariant (the index's ORDER is the eviction order). |
| `code/viewer/test_viewer_import_warm.py` | **8** | The import warm creates **no Qt object** (it runs off the GUI thread) and fails loudly if the windowing path stops using the numpy calls it warms. |
| `code/viewer/test_dicom_import_preview.py` | **5** | Import groups by immutable study/series UID, assigns duplicate raw numbers through the shared collision resolver, and distinguishes copied DICOM object count from pixel-bearing image count. Metadata-only SR/vendor objects remain importable but must report zero displayable images. |
| `code/viewer/test_disk_pixel_cache_persistence.py` | **20** | The L2 cache SURVIVES shutdown (before this it was `rmtree`'d every exit and had never served a cross-session hit). Pins: persistence is the default; `AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT=1` really restores the wipe; **`clear()` itself stays unconditional** so an explicit user clear always clears; the shutdown path calls `clear_on_exit()` not `clear()` (AST pin — a comment naming `.clear()` cannot fool it); and eviction still bounds a *persisted* cache, with LRU order surviving a restart. |
| `code/ui_services/test_thumbnail_active_state_and_strip.py` | **20** | **Behavioural, on real Qt widgets.** The download bar is not buried by the re-parenting `addWidget`; the red active line is stacked above it; A→B→A returns a series to the active state. A source-string pin cannot see a z-order bug — that is exactly how the buried bar survived `test_thumbnail_panel_ui_fixes.py`. |
| `code/ui_services/test_main_footer_bar_removed.py` | **6** | The empty main-page footer stays hidden and its widgets stay alive (so `apply_theme` keeps working); fails if anyone starts writing to its labels or introduces a real `QSizeGrip`. |
| `code/ui_services/test_clear_table_crash_guard.py` | **16** | Patient-table item and widget teardown stays outside Qt model mutation: each order cell is created once, safe row/full clears use `takeItem` before `removeRow`/`setRowCount(0)`, producers respect the rebuild guard, and Local Server search does not pump a nested event loop. Includes a real offscreen Qt/Shiboken ownership check. |
| `code/ui_services/test_local_offline_contract.py` | **20** | LocalDatabase defaults to no remote resync; single-click reconcile, right-panel cache miss, grouped preview, viewer thumbnail cache miss, existing-tab focus, and local patient open return through DB/disk paths before any PACS socket access. Multi-study Local open must aggregate every study's SQLite/disk series metadata. Duplicate-SeriesNumber imports preserve exact `series_path`/`folder_key` but use a digit-only UI handle; missing PNGs rebuild from the exact folder off the GUI thread; metadata-only DICOM groups are excluded; cine cards show total frames without changing file-completeness counts; and count persistence targets `SeriesInstanceUID`. Local startup must not render collision storage stems as drag handles before authoritative projection, and the FAST parser must reject them rather than reinterpret underscores as numeric separators. |
| `code/ui_services/test_patient_study_set.py` | **27** | Pure patient/study/series authority, including deterministic digit-only display aliases for duplicate raw SeriesNumber values while preserving the raw number and collision folder. |
| `code/viewer/test_dicom_color_decode.py` | **12** | DICOM colour conversion plus the FAST metadata-recovery regression: an RGB/YBR single frame remains `Rows x Columns x 3` when DB metadata omits colour facts. |
| `code/viewer/test_fast_multiframe.py` | **20** | Multi-frame decode, cache, geometry and metadata expansion, including several cine DICOM objects whose DB rows omit NumberOfFrames. |
| `code/viewer/test_series_ref_authority.py` | **29** | Immutable display/study/series authority; a numeric collision alias retains the original DICOM number but loads the exact suffixed storage folder. |
| `code/ui_services/test_advanced_search_routing.py` + `code/database/test_local_advanced_search.py` | **8 + 3** | Advanced Search follows the active source and preserves bounded multi-ID, normalized acquisition/import date, multi-valued modality, body part, DICOM age, and persisted physician filters in Local SQLite. Valid online physician hydration is persisted for later offline reuse; the database tests use an isolated patched `DATABASE_FILE` and cleared pool. |
| `code/ui_services/test_local_incremental_and_import_date.py` | **13** | Imported Date means the immutable first entry into this computer's Local SQLite, never acquisition date or last refresh. Single-day/preset/range queries use full-day boundaries, NULL legacy timestamps do not match, import-date queries stay Local, and reversed custom ranges are normalized in both the dialog and repository. Also retains the incremental Local-list guards. |
| `code/viewer/test_reference_line_active_viewport.py` | **17** | The ACTIVE viewport carries no reference line — it is the source and stays clean; the line goes only on the series being cross-referenced. Load-bearing pin: the source overlay is **cleared**, not merely skipped, so a line drawn while a viewport was inactive vanishes the instant it becomes active. Also pins that `AIPACS_REFERENCE_LINES_ALL_PAIRS=1` restores bidirectional lines end-to-end. |
| `code/viewer/test_text_annotation_input.py` | **25** | The Text tool ASKS what to write. Before this it stamped the literal word "Text" — the whole chain was wired except the input step. Pins: the typed string is what reaches the `TextModel`; cancel / whitespace / a raising prompt all place **nothing** and return `False`, so the tool stays armed; a bare `ToolController` still places the legacy `"Text"` (every headless tool test and the EchoMind adapter build one that way); only the TEXT tool may prompt; `controller.py` stays **Qt-free**; the Qt bridge really wires `_text_prompt_fn` (AST pin — the controller change is inert without it); the dialog is re-entrancy-guarded and releases its flag even when it raises; and both backends word the prompt identically. |
| `code/reporting/test_report_image_insert.py` | **68** | Captured viewer images can be inserted into the Medical Report Editor and survive the whole trip. Also pins study RESOLUTION: a report opened from the Reception Data tab carries a reception record with no `studyUID`, so the study is found by joining `patients.patient_id -> patient_pk -> studies.patient_fk` — `patient_fk` is a FK to `patient_pk`, NOT the DICOM PatientID, and a direct comparison returns zero rows silently. Identifiers are tried in order and the FIRST match wins; `test_resolution_stops_at_the_first_identifier_that_matches` exists because unioning them could mix another patient's key images into the report. Load-bearing: **`test_the_upload_normaliser_keeps_the_image`** — the normaliser already strips `<style>`/`<script>`/chrome, and adding `img` to `_DIR_BLOCK_TAGS` would lose the key image for the referring doctor while the author's copy still shows it, the worst failure mode there is. Also pins: the picker's file list matches the viewer's "Captured Images" dropdown exactly; the encoder refuses rather than embedding over the byte ceiling (a report that will not upload is worse than a refused insert); and the resize actually changes the stored width — **behavioural, because the AST guards did not catch a reversed-cursor-selection bug where every button was wired, every handler ran, and nothing moved**. `test_a_document_can_render_a_data_uri` pins behaviour, not mechanism, so it holds on any Qt. |
| `code/mpr/test_mpr_lifecycle_release.py` | **28** | MPR teardown runs on EVERY destruction path, not just the toolbar toggle. Before this: 14 MPR opens vs 6 `cleanup()` completions across the logged sessions. **The load-bearing pair is `test_layout_teardown_releases_before_orphaning` + `test_patient_close_releases_the_mpr_child`** — they pin the two paths that actually leaked *and their ordering*, because a `closeEvent` hook alone does NOT fix this (Qt never calls `closeEvent` when a parent is destroyed or a widget is re-parented away). Anyone who "simplifies" the fix down to the closeEvent comes back green on the closeEvent tests and is caught here. Also pins: release must happen BEFORE `setParent(None)` or the GL context is gone and the VRAM cannot be freed; the 3D mapper is really re-pointed on an in-MPR series switch (behavioural, on real VTK); and teardown survives an already-deleted C++ object. |
| `code/viewer/test_mpr_step_instrumentation.py` | **20** | Every MPR view creator emits `[MPR-STEP]` under its OWN view name. Before this all 17 call sites passed `'axial'`, so sagittal/coronal/3D cost was invisible and an 8.7 s activation freeze could not be attributed. AST-based, so a renamed-but-still-hardcoded creator fails. |
| `code/network/test_ino_state_batch_write.py` | **28** | The assignment snapshot is written ONCE per refresh batch, not once per reception. Each write rewrites the whole file under a lock the GUI thread takes per patient-list row — the per-row version froze the UI for 10.79 s. Pins: one `_save` + one lock acquisition per batch; `set_state`/`set_many` cannot drift (shared `_entry`); `_load` happens inside the save's lock so a concurrent single write is not rolled back; the fsync is opt-in; and the refresh contracts that must NOT change (per-row `on_row`, summary shape, a failed fetch never wipes, an interrupted refresh still persists). |

Run them all with:

```
.venv\Scripts\python.exe -m pytest tests/code/web_browser tests/code/viewer/test_series_file_warm.py tests/code/viewer/test_disk_pixel_cache_async_init.py tests/code/viewer/test_disk_pixel_cache_persistence.py tests/code/viewer/test_viewer_import_warm.py tests/code/ui_services/test_thumbnail_active_state_and_strip.py tests/code/ui_services/test_main_footer_bar_removed.py tests/code/network/test_ino_state_batch_write.py tests/code/network/test_ino_server_state_concurrency.py tests/code/system/test_browser_prewarm_idle_gate.py -q
```

Last verified green: **2026-08-16, 196 passed**. The wider viewer regression
run was green again on **2026-08-18**:

```
pytest tests/code/viewer      -> 2265 passed, 28 skipped, 37 deselected,
                                 54 xfailed, 2 xpassed
pytest tests/code/fast        ->  176 passed
pytest tests/code/fast_viewer ->  416 passed, 12 skipped   (needs -p no:debugging)
pytest tests/code/reporting
       tests/code/ai_imaging  ->  297 passed, 8 xfailed
```

**2026-08-19** — `tests/code/mpr + viewer + ui_services` → **3091 passed**,
29 skipped, 54 xfailed, 5 xpassed. The 2 failures in that run
(`test_login_carries_the_user_identity_ids`,
`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute`) are
pre-existing source-string pins on the login/JWT path and the patient-list
status renderer; confirmed unrelated by running them in isolation.

**2026-08-21** — `tests/code/viewer + fast_viewer + ui_services + system +
dicom_media` → **3814 passed**, 41 skipped, 38 deselected, 55 xfailed,
5 xpassed. **6 failures, all pre-existing and all proved to fail at HEAD:**
`test_login_carries_the_user_identity_ids` and
`test_status_flags_are_stashed_on_the_widget_to_avoid_recompute` (carried over
from 2026-08-19), plus four in
`tests/code/system/test_local_search_progressive.py` — three assert first-batch
sizes of 100/40 that a June change to `_PROGRESSIVE_INITIAL_BATCH` (now 20) made
stale, and one pins a renamed constant (`_LOCAL_SEARCH_BATCH` →
`_LOCAL_PROGRESSIVE_MIN`). Proved with
`tools/analysis/oneoff/prove_progressive_test_prefails_2026_08_21.py`, which runs
that file's own exec-the-source harness against a `git show HEAD:` copy and gets
20 rows either way. Left alone as unrelated to the 2026-08-21 fixes.

New this day: `tests/code/viewer/test_ybr_color_decode.py` (23 guards, 19 fail at
HEAD) and `tests/code/ui_services/test_list_stream_backpressure.py` (17 guards,
15 fail at HEAD). Both pre-fix checks swap `git show HEAD:` copies into the tree
and restore them in a `finally`.

**2026-08-22** — same five folders, same order → **3841 passed**, 41 skipped,
38 deselected, 55 xfailed, 5 xpassed, **6 failed — the same six as 2026-08-21 and
nothing new**. New guard file:
`tests/code/ui_services/test_gui_thread_disk_paths.py` (27 guards, **19 fail at
HEAD** via `tools/analysis/oneoff/verify_gui_disk_guard_fails_prefix_2026_08_22.py`).

**2026-08-23** — `tests/code/system + runtime + utils + builder` → **580 passed**,
5 deselected, 1 xfailed, **11 failed, 0 of them ours**. New guard files:
`tests/code/system/test_close_path_hang_visibility.py` (14) and
`tests/code/runtime/test_seed_config_once.py` (12) — **all 26 fail pre-fix.**

> **The pre-fix check could not use `git show HEAD:` this time, and that is the
> point.** This working tree carries **389 lines of unrelated uncommitted work in
> `aipacs_runtime.py`** and 17 in `_pw_lifecycle.py` (3.6.1/3.6.2 were built from
> the working tree, not from a commit). Restoring those files from HEAD would
> have reverted far more than the A0 change, and the guards would have "failed"
> for the wrong reason — a green result that proves nothing. So
> `tools/analysis/oneoff/verify_close_path_guard_fails_prefix_2026_08_23.py`
> removes **exactly** the A0 additions instead: anchor-based, every anchor
> asserted present before anything is written, restored in a `finally`. Check
> this before reaching for `git show HEAD:` in any future pre-fix script.

The 11 failures were **measured**, not argued, by
`tools/analysis/oneoff/check_a0_regression_delta_2026_08_23.py`, which runs the
same file set with and without the A0 additions and diffs the failure sets:
identical both ways, **caused by A0: 0**. They are

* 6 × `tests/code/builder/test_nuitka_arm64_parity.py`
* 4 × `tests/code/system/test_local_search_progressive.py` — the same four
  carried since 2026-08-21 (stale batch-size pins)
* 1 × `tests/code/builder/test_release_parity_guards.py::test_plugin_mirrors_are_fresh`

The arm64 six and the plugin-mirror one are **new to this index and unexplained**
— they were not in the 08-21/08-22 folder set, so this is the first run that
covered `tests/code/builder`. Worth their own look; they are not A0.

**2026-08-23 (second run, MPR surface)** — `tests/code/mpr + viewer + system +
architecture + fast` → **2 919 passed**, 28 skipped, 37 deselected, 56 xfailed,
2 xpassed, **4 failed — the four `test_local_search_progressive.py` pins carried
since 2026-08-21, nothing new**. This is the **baseline for the MPR geometry
surface**: it is currently fully green apart from those four, so any red in
`tests/code/mpr` or `tests/code/viewer` after a geometry change is a regression.

Run because A1 (oblique MPR) was about to be changed. **It was not changed** —
reading the prior documentation showed the proposed fix would have reverted
v1.09.Fix-E. See `docs/plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`.
Only docs and one stale docstring were edited, hence the clean sweep.

> **Before editing any MPR source file, read the fixed-character-window table in
> that brief.** Eleven MPR-adjacent guard tests still slice their source at a
> fixed character count from a `def`; the 600-char window at
> `_capture_baseline_camera_state` and the 2200/2600-char windows at the two
> wheel handlers are the ones that will bite an oblique-camera change. The
> 2600-char ones hold **negative** assertions, so growth silently *weakens* them
> instead of failing — a worse failure mode than a red test.

> **Folder order changes the result — watch for it.** Running the same folders as
> `ui_services → system → viewer → fast_viewer` instead adds four
> `test_fast_viewer_pipeline.py::test_b41_*` failures. They are **run-order
> pollution, not a regression**: the file passes in isolation (`170 passed`), and
> `tools/analysis/oneoff/check_b41_order_pollution_2026_08_22.py` runs that order
> twice — once with the working tree, once with the three changed files swapped
> for their HEAD copies — and gets the **same four failures both times**.
> Whatever leaks between those folders predates this work and is still unfixed.

> **The fixed-window trap bit again — third file, fourth time.**
> `test_status_refresh_dicom_only.py::test_storage_clear_still_full_recomputes`
> searched a FIXED 1,800-character window from
> `def refresh_download_statuses_local_only`. Moving that method off the GUI
> thread added an explanatory paragraph, which pushed
> `self._local_status_cache.clear()` out of the window — the assertion was still
> TRUE in the code. Re-bounded at the next `def`, assertion untouched, exactly as
> `test_mpr_defer_3d_view.py` was on 2026-08-18 and 2026-08-19. **If you are
> writing a source-pin guard, bound it at the next `def` — never at a character
> count.**

(`tests/code/fast` and `tests/code/fast_viewer` are two different folders —
15 and 17 files. Running only one of them is a common way to miss a break.)

The xfail/xpass set is the pre-existing quarantine, unchanged.

> **`tests/code/fast_viewer` needs `-p no:debugging`.** Without it pytest dies
> with an INTERNALERROR before collection: `_pytest.debugging.pytest_configure`
> does `import pdb`, `pdb` does `import code`, and once `tests/` is on
> `sys.path` that resolves to this repo's `tests/code` package —
> `AttributeError: module 'code' has no attribute 'InteractiveConsole'`.
> `tests/code/viewer` is unaffected because it has no `__init__.py`.
> Pre-existing; the real fix is renaming `tests/code` or putting
> `-p no:debugging` in the pytest config, both wider than any one bug fix.

---

**2026-08-23 (third run, CPU budget)** — `tests/code/system + runtime + utils +
builder` → **593 passed**, 5 deselected, 1 xfailed, **11 failed — the same 11 as
the A0 run above, byte for byte**. 580 + the 13 new guards = 593, so **0
regressions**. New guard file:
`tests/code/system/test_cpu_budget_priority_boost.py` (13) — **5 fail pre-fix**
(`tools/analysis/oneoff/verify_cpu_budget_guard_fails_prefix_2026_08_23.py`).

> **This pre-fix script DOES use `git show HEAD:` — and proves it is allowed
> to.** The A0 note above says not to reach for it blindly; the discriminator is
> `git diff --numstat -- <file>`. For `main.py` that is exactly `18  0  main.py`
> — the fix hunk and nothing else — so HEAD really is the pre-fix state. The
> script asserts this and **refuses to run** if it stops being true. Check the
> numstat before deciding which technique a pre-fix script needs.

Only 5 of the 13 fail pre-fix, and that is correct rather than weak: the other 8
are either preservation guards (the block, the log lines, the `AIPACS_PRIORITY`
kill switch — they must pass on BOTH sides, that is their job) or the two
behavioural Win32 probes, which test Windows' pseudo-handle semantics rather
than our source and therefore pass on both sides by construction. The five that
flip are the three ctypes declarations and the two ORDERING pins.

---

**2026-08-23 (fourth run, HIGH on deployed workstations)** — `tests/code/system +
runtime + utils` → **519 passed**, 1 xfailed, **4 failed — the same four
`test_local_search_progressive` pins carried since 2026-08-21**. 0 regressions.
`test_cpu_budget_priority_boost.py` grew 13 → **23 guards**, of which **16 fail
pre-fix**.

> **`tests/code/builder` was NOT in this run, and that is a measurement gap, not
> a pass.** `test_release_parity_guards.py` calls
> `builder/release_gate.check_source_freshness()`, which shells out to
> `git fetch` with a 90 s timeout — the fetch hung on this network and took the
> whole pytest process with it. Environmental, not ours: the same folder ran 90
> minutes earlier in this session. **Re-run `tests/code/builder` with network
> access before a release build.**

Two new techniques in this file worth copying:

> **Behavioural guards over inline `__main__` code.** The priority resolution
> lives inside `if __name__ == "__main__":` and cannot be imported. Rather than
> settle for source pins, `_resolution_source()` lifts the resolution lines out
> of `main.py` **by anchor** and `exec`s them against a stubbed `_pri_frozen`
> and a stubbed `os.environ`. The guards then assert what the shipped code
> actually DECIDES, not merely that certain characters are present. Extract from
> the **start of the anchor's line**, or `textwrap.dedent` finds no common
> prefix and the exec raises `IndentationError`.

> **A pre-fix script can EARN the right to use `git show HEAD:`.** The A0 note
> above says not to reach for it blindly. The discriminator is whether the
> working diff touches anything outside the block being fixed.
> `verify_cpu_budget_guard_fails_prefix_2026_08_23.py` now parses
> `git diff -U0` hunk headers and requires every hunk to fall inside the CPU
> BUDGET block's line range at HEAD — and **refuses to run** otherwise. That is
> strictly better than the literal numstat check it replaced, which broke the
> moment the fix grew a second landing.

Two guards were **re-pinned, not deleted**, and both record why in the file:
`test_normal_escape_hatch_preserved` (spelling moved) and
`test_high_priority_class_is_not_the_default` →
`test_high_is_the_default_only_for_installed_builds` (**the policy changed by
owner request** — the guard now pins the new rule so a later edit that quietly
makes HIGH the default for source runs too is still caught).

---

**2026-08-24 (completion pass)** — the measurement gap left open on 08-23 is now
closed and one piece of tooling was repaired.

`tests/code/builder` finally ran: **85 passed, 6 failed** — the six
`test_nuitka_arm64_parity` pins, unchanged and unrelated. The seventh failure
carried since 08-23, `test_release_parity_guards::test_plugin_mirrors_are_fresh`,
now **passes** (the v3.6.3 release re-synced the plugin mirrors), and the
`git fetch` inside `check_source_freshness()` no longer hangs. Full picture for
the CPU-budget work: `system+runtime+utils` 519 passed / 4 failed +
`builder` 85 passed / 6 failed = **604 passed, 10 failed, none of them ours**.

> **A pre-fix verification script dies the moment its fix is committed — fix that
> when you write it, not after.** `verify_cpu_budget_guard_fails_prefix_2026_08_23.py`
> asserted `HEAD:main.py` lacks the fix. The fix shipped in
> `5deb8ee7 release(v3.6.3)`, so from that commit onward the script aborted with
> "HEAD already has fix" and the guard's pre-fix proof was **un-runnable**. It now
> resolves a base ref: HEAD when HEAD still lacks the fix, otherwise it walks
> `git log` for the newest commit whose `main.py` lacks it (here `c2f79e63`,
> v3.6.0) and prints which ref it chose; `--base <ref>` overrides. Re-run
> confirmed: **16 fail at `c2f79e63`, 23 pass after restore, `main.py` clean.**

---

**2026-08-26 (overlay re-entrancy crash)** — `tests/code/{viewer,system,ui_services,
fast_viewer}` + `test_loading_overlay_liveness_guard.py` → **3,862 passed**, 41
skipped, 55 xfailed, 5 xpassed, **6 failed — 0 of them ours**. New guard file:
`tests/code/system/test_overlay_reentrancy_crash.py` (13 guards, **11 fail pre-fix**).

Four of the six are the `test_local_search_progressive` pins carried since 08-21.
The other two are in `tests/code/ui_services`, a folder new to this index, and were
**measured rather than argued**: `check_overlay_fix_delta_2026_08_26.py` runs them
with and without the two changed files and gets the identical failure set.

> **A source pin over a file with several same-named methods must carry a CLASS
> scope.** `loading_overlay.py` defines three `__init__`s; a bare `ast.walk()`
> returns `_LogoSpinner.__init__` first, so the first draft of
> `test_overlay_init_refuses_a_destroyed_anchor` was reading the wrong function
> and would have guarded nothing. `_func_src(path, name, cls=...)` now takes the
> class. This is the AST-shaped cousin of the fixed-character-window trap above
> — same failure mode, different mechanism: the guard is bound to the wrong text
> and still goes green.

> **Binding a real method to a stub beats constructing the real object.**
> `QtFastContainer` is a QWidget subclass, so `object.__new__` is refused and a
> real instance needs a QApplication and a live viewport — neither of which the
> re-entrancy guard is about. `QtFastContainer.switch_series.__get__(stub, Stub)`
> runs the SHIPPED method against a plain object, which is how
> `test_a_nested_switch_is_refused` reproduces a native crash with no Qt at all.

---

**2026-08-26 (Eagle Eye lumbar — wrong series in the panes)** — `tests/code/ai_imaging`
→ **385 passed**, 8 pre-existing xfail; `tests/code/viewer` green;
`verify_plugin_mirrors.py` 456/456. Three guards added to
`test_eagle_eye_protocol_resolution.py`:
`test_the_tab_does_not_pre_wait_on_the_thumbnail_list`,
`test_the_controller_asks_by_series_key_never_by_list_position`,
`test_the_controller_still_refuses_when_the_series_never_arrive`.
The 10 `tests/code/ui_services` failures seen in the same run were **measured**
pre-existing: stashing this work reproduces the identical set (a qtawesome
font-directory `TypeError` plus two stale source pins).

> **A parameter name is not a contract — read the first line of the callee.**
> `change_series_on_viewer(series_index, …)` opens with
> `series_number = str(series_index)`: the argument is a series KEY, not a
> position. Passing a `lst_thumbnails_data` index loaded whichever series was
> *numbered* "1" and "2" (the localizer and a coronal myelogram) while every
> log line upstream said the mapping was correct — the defect was invisible
> from the resolver's side and only the viewport's own metadata revealed it.

> **Waiting for a precondition that your own call would satisfy is a deadlock
> with a timeout.** The tab polled `lst_thumbnails_data` (LOADED series only)
> before assigning, but assignment is what triggers the decode. For a study
> whose other series had never been requested the entries never appeared, so a
> correct mapping still burned the full 90 s budget. Readiness moved to the
> layer that can observe the real end state: the viewport.

---

**2026-08-26 (Eagle Eye v1.1.0 — protocol-driven engine + reference-line policy)** —
`tests/code/ai_imaging` → **426 passed**, `tests/code/viewer` → **2,288 passed**
(2,714 together), `verify_plugin_mirrors.py` 456/456. Eighteen guards added in two
new sections of `test_eagle_eye_lumbar_pipeline.py`: §8b the reference-line policy
(real behaviour against fake viewers) and §8c the protocol architecture.

> **A guard that says "the engine must not know about X" belongs on the AST, not
> the text.** `test_the_engine_names_no_body_part` first failed on the module
> docstring — which deliberately explains the lumbar history — and on the
> back-compat class alias. Parsing instead, and excluding docstring constants,
> makes it test the values the engine COMPUTES with rather than what it SAYS.
> The text version would have forced the comments to be worse.

> **Write the guard for the requirement, not for the code you just wrote.** Two
> of these failed on the first run and were right to: `restore()` on the
> reference-line policy was never wired into `_finish`/`_fail`, and the engine
> still carried `"lumbar_mri"` string defaults. Both were real gaps found by
> guards written from the requirement rather than from the implementation.

> **Derive a rule instead of declaring it where you can.**
> `hide_reference_lines_on` defaults to `primary + synced` and `sync_groups` is
> computed from the sessions. Declared copies of a rule drift from the code that
> enforces it; derived ones cannot. Both still allow an explicit override, so
> the default is a default rather than a law.

---

**2026-08-27 (Eagle Eye LLM pipeline 3.3.0 — explicit stenosis grades and
provider-specific stage sampling)** — `tests/code/ai_imaging` → **499 passed**,
8 pre-existing xfail. Five guards were added to
`test_eagle_eye_llm_analysis.py`; all five failed before the implementation and
passed afterward. They protect the immutable/versioned central-canal, neural-
foraminal and lateral-recess grading catalog; identical grading semantics in
both passes; ordinal grading fields in the screening contract; temperature in
stored provenance; and actual forwarding of each stage's temperature across
the Eagle Eye → EchoMind boundary.

> **Two readers may have opposite dispositions without having different
> dictionaries.** Screening remains inclusive and verification remains
> conservative, but both now use one catalog for the meaning of mild, moderate
> and severe. The transport also no longer applies its shared 0.2 default to
> Gemini 3 screening: screening requests 1.0, while GPT verification remains
> at 0.2. This slice deliberately does not change image selection, candidate
> routing, or final-report rendering, so its effect can be evaluated separately.

---

**2026-08-27 (Eagle Eye — patient-free GapGPT capability matrix)** —
`tests/code/ai_imaging` → **504 passed**, 8 pre-existing xfail;
Eagle Eye/GapGPT/EchoMind cross-boundary selection → **94 passed**;
`verify_plugin_mirrors.py` → **456/456**. New guard file:
`tests/code/ai_imaging/test_eagle_eye_gapgpt_capability.py` (5 guards; all five
failed before the pure contract and adapter existed).

The probe sends only deterministic in-memory PNG tiles through the existing
GapGPT URL, key and HTTP authorities. It pins the two production model ids and
their stage temperatures; text, high-detail vision, multi-image ordering,
strict-schema and Responses scenarios; semantic schema evaluation; credential
redaction; and the absence of any direct OpenAI endpoint or key path.

> **HTTP 200 is not capability success.** Gemini returned an empty JSON object
> for a strict schema and therefore failed semantically; GPT-5.6 Sol returned
> the exact required object. Also, `google/<model>` and `openai/<model>` are
> GapGPT canonical names, not model substitution. The first evaluator used raw
> string inequality, incorrectly marked every live response as substituted,
> and the namespace guard failed before that defect was fixed.

---

**2026-08-28 (Eagle Eye workflow/UI boundary)** — New guard file:
`tests/code/ai_imaging/test_eagle_eye_ui_boundary.py` (4 guards). The architecture
guard failed before implementation because the coordinator did not exist and all
capture, analysis, result, and teardown methods were still members of
`ImagingToolsTab`. The extracted
`modules/ai_imaging/eagle_eye_lumbar/workflow_coordinator.py` now owns those
lifecycles. Two behavioral guards protect the validated series-identity handoff and
close-while-running abort/detach sequence. Focused boundary/resolution gate:
**56 passed**; capture/resolution/LLM gate: **267 passed**; complete AI Imaging
gate: **518 passed, 8 pre-existing xfailed**.

> **A UI callback is not the feature boundary.** Moving only the button callback
> would leave state, error handling, worker ownership, and teardown coupled to the
> oversized tab. The coordinator owns the entire lifecycle; the tab constructs it,
> schedules it, displays status, and tears it down.

---

**2026-08-28 (Eagle Eye pipeline 4.0.0 — parallel clinical context)** —
`tests/code/ai_imaging/test_eagle_eye_llm_analysis.py` now contains 77 guards,
including four new guards that all failed before implementation. They protect:
the versioned Gemini clinical-context stage and GPT fusion input; bounded,
supported, path-redacted attachment packaging; concurrent Gemini MRI screening
and document extraction before GPT verification; and graceful continuation when
the document branch is absent or fails. Complete AI Imaging gate: **522 passed,
8 pre-existing xfailed**.

> Clinical context is an untrusted prior, never current-MRI evidence. The final
> adapter allowlists the extraction schema, and GPT verification must re-check
> every historical claim against the MRI. No document means no extra Gemini
> request; context failure does not discard a successful MRI read.

---

**2026-08-28 (Eagle Eye pipeline 4.1.0 — multi-source context)** — The parallel
Gemini context branch now reads allowlisted reception facts and prior reports,
a sanitized full-or-limited PACS series catalogue, DICOMized clinical history
series `100000`, supported attachment documents, and a bounded MRI overview.
New guards prove that collection itself overlaps MRI screening; the capture
boundary snapshots the full catalogue without UIDs; DICOM clinical pages are
rendered to derived PNGs; and `locally_available_series_only` can never create a
missing-sequence, absent-postcontrast, or protocol-limitation claim. Focused LLM
file: **83 passed**; LLM plus lumbar pipeline: **222 passed**; complete AI
Imaging gate: **529 passed, 8 pre-existing xfailed**; EchoMind scoping plus the
patient-free GapGPT capability gate: **21 passed**.

> Only `pacs_series_catalog` may support an absence claim. Reception history is
> a prior, series inventory is protocol metadata, and MRI overview is incomplete
> context; the final GPT must still establish findings from the full MRI package.

---

**2026-08-29 (Eagle Eye original-tab context handoff repair)** — Three new
guards failed before the fix and protect the live-discovered loss of patient ID
and complete series inventory between the original patient tab and the reduced
Eagle Eye widget. `test_preflight_handoff_snapshots_patient_id_and_the_complete_catalog`
pins the bounded, UID/path-free snapshot at the source;
`test_capture_context_uses_complete_handoff_when_the_ai_widget_is_reduced`
pins patient-ID recovery and six-series full-catalogue authority at capture;
and `test_original_patient_context_crosses_the_existing_one_shot_handoff`
pins coordinator threading without returning feature logic to the oversized UI
tab. Focused lumbar/UI gate: **146 passed**; complete AI Imaging gate:
**546 passed, 8 pre-existing xfailed**; plugin mirrors: **456 matched**.

> The handoff is application context, not model input. Identity enables the
> existing reception/prior-report authorities locally and is removed before the
> model package; the series snapshot contains descriptive protocol metadata but
> no series UID or path. Live source-build confirmation remains pending.

The same repair is now pinned into every default build path by
`tests/code/builder/test_eagle_eye_default_build_inclusion.py` (3 guards). The
Nuitka inclusion guard failed before the builder change; both monolithic and
staged full-core Nuitka now force-include `modules.ai_imaging`, while
PyInstaller's existing non-optional `modules` collection remains the third
path. The guards also inspect the generated staged command, prove there is no
feature-flag gate, and require the canonical Viewer file to match its package
payload exactly. Focused builder guard: **3 passed**; module/plugin readiness
and cross-build coherence: **passed**;
plugin mirrors: **456 matched**. The broader builder baseline remains red for
six unrelated ARM64 parity guards, one stale staged-config guard, and one
network source-freshness timeout; no full-build pass is claimed.

**2026-08-30 (Eagle Eye pipeline 4.2.0 — disc hydration specificity and
provider-neutral popup)** — Two behavioral guards failed before the fix and
pass afterward. The LLM guard requires both image-reading stages to treat
preserved central nucleus-pulposus T2 hyperintensity on adjacent mid-sagittal
slices as evidence against desiccation, and forbids axial-only or dark-annulus
calls. The UI guard renders a synthetic stored record and proves that the popup
shows `AI-PACS AI Lumbar Analysis` without Gemini/GPT/provider identifiers,
while preserving prompt version, pass/image counts, date, and token metadata.
Raw model provenance remains stored for audit. Focused proof: **2 passed**;
changed-boundary files: **90 passed**; complete AI Imaging gate: **559 passed,
8 pre-existing xfailed**; default-build inclusion guard: **3 passed**. Live
radiologist validation of pipeline 4.2.0 remains pending.

**2026-08-30 (Eagle Eye pipeline 4.3.0 — pathology-focus differential
adjudication)** — Four new prompt-contract guards failed before the fix. They
pin screening as a sensitivity-oriented attention map, a shared multi-plane
disc-displacement nomenclature, separate authorities for screening/context/MRI,
and mandatory differential reclassification at every positive focus. A wrong
screening label with a supported alternative pathology must be
`RECLASSIFIED`, not `REJECTED`; normal and non-pathological variants remain
valid rejection outcomes. Two older guards were intentionally re-pinned from
the former deletion-filter/axial-veto policy to the clarified owner contract.
Focused LLM file: **88 passed**. Live radiologist validation of pipeline 4.3.0
remains pending. Complete AI Imaging gate: **563 passed, 8 pre-existing
xfailed**; default-build inclusion guard: **3 passed**.

**2026-08-30 (Eagle Eye pipeline 4.4.0 — paired sagittal context and focal
attention)** — Four behavioral guards failed before the fix. They require the
context branch to select paired sagittal T2/T1 captures nearest the measured
midline instead of sagittal/axial sweep endpoints; extract bounded general,
regional, and level-specific `context_attention_foci`; preserve only allowlisted
fields and evidence sources when forwarding context; and retain safe
session-local sagittal context when an invalid study UID disables external
lookups. The final verifier must audit every non-global context focus against
the complete MRI and may add, reject, or mark it indeterminate. Focused LLM
file: **92 passed**; complete AI Imaging gate: **567 passed, 8 pre-existing
xfailed**; default-build inclusion guard: **3 passed**; combined gate:
**570 passed**. Live radiologist validation remains pending.

**2026-08-30 (Eagle Eye pipeline 4.5.0 — patient laterality and same-lesion
multiplanar morphology)** — Two prompt-contract guards failed before the fix.
They require both image readers to derive patient side from visible `R/L`
markers or trusted DICOM patient coordinates, never screen position, and to
return indeterminate laterality when orientation evidence is unavailable or
conflicting. They also require sagittal and axial observations to be correlated
to the same level and displaced component before morphology is fused. A
sagittal extrusion-defining neck/base-to-dome relationship cannot be outvoted
by a partial axial slice that looks protrusion-like. Focused LLM file: **94
passed**; complete AI Imaging gate: **569 passed, 8 pre-existing xfailed**;
default-build inclusion guard: **3 passed**; combined gate: **572 passed**.
Live radiologist validation remains pending.

**2026-08-31 (OPT-55 — opt-in bilateral sagittal supplements; root scorer 1.1.0)** —
`test_eagle_eye_parasagittal.py`: **18 passed**, covering LPS sampling under
reversed/oblique geometry, short/invalid coverage, exact V3 image/caption
preservation, screening-side independence, image/pixel/byte caps, optional
failure retention, no-focus overviews, and verification-only mocked dispatch.
Initial feature guards failed in **11 cases** before implementation. Root
negation guards reproduced **6 failures / 7 passes** before the scorer repair;
`test_eagle_eye_bench_scoring.py` now passes **25 tests**. Contact with negated
deviation is `under` against compression, not a total miss. Complete AI Imaging:
**675 passed, 8 existing xfailed**; core-build inclusion **3 passed**; **458
mirror pairs** matched. Offline replay preserved 57 original files and all four
baseline images/captions, then added two supplements within unchanged caps.
No model call, default promotion, or diagnostic improvement claim. Remaining
Phase 0 scorer/reference defects are documented, not silently declared fixed.

**2026-08-31 (OPT-55 — focused V2/V3 bounded axial-window coverage)** —
`tests/code/ai_imaging/test_eagle_eye_focused_v2.py` adds **41 synthetic cases**
covering short/long slabs, every anchor, both boundaries, interior windows,
gap/orientation isolation, reversed source ordinals, unchanged shared sagittal
selection, preserved projection anchors, original capture bytes, and audited
manifest/budget behavior in both render modes. Before the fix: **20 failed,
21 passed**, exit code 1. Afterward: focused V2/V3 **63 passed**; complete AI
Imaging **643 passed, 8 existing xfailed**; default-build inclusion **3 passed**;
**458 plugin mirror pairs** matched, all with exit code 0. A fresh private
offline replay restored available five-slice focus coverage without changing
original artifacts or sagittal sampling. No model call or clinical accuracy
claim. Manifest schema 1.3.0 records policy `same-slab-backfill-v1`; live
source-build/radiologist validation remains pending.

**2026-08-30 (Eagle Eye pipeline 4.6.0 — candidate-directed focused-v2 DICOM
evidence)** — `tests/code/ai_imaging/test_eagle_eye_focused_v2.py` adds seven
behavioral guards. They pin the versioned allowlisted focus plan; decisive-frame
sanitization and level-map fallback; patient-LPS mapping from stored capture
geometry into the immutable axial volume; DICOM-derived patient orientation;
five-slice axial and three-slice
sagittal sequence sheets; no-upscale rendering, uniform-image rejection, and
image/pixel/byte caps; local-only series-path provenance; layout evidence for
parallel Gemini screening; focused evidence only for GPT verification; and
deterministic fallback to the original stored layout when DICOM provenance or
composition is unavailable. The shared headless volume primitives now serve
both Legion Consult and Eagle Eye. Focused changed-boundary gate: **262 passed**;
complete AI Imaging gate: **576 passed, 8 pre-existing xfailed**. `layout`
remains the runtime default pending paired radiologist validation.

**2026-08-30 (Eagle Eye pipeline 4.6.1 — focused-v2 capture-frame
authority)** — Four additional behavioral guards cover the live reversed-level
map defect. They require raw inferior-to-superior DICOM order to remain distinct
from original superior-to-inferior capture-frame identity, prevent adjacent
focus ribbons from crossing independently angled slab boundaries, calculate the
cross-plane point from the physical image center rather than Image Position
Patient alone, and require verification to use only `AX frame n/N` labels for
the final level map. The numbering guard failed pre-fix with no
`axial_capture_frames` authority. The focused file now contains **11 guards**.
The changed-boundary set passed **134 tests**, complete AI Imaging passed **580
tests with 8 pre-existing xfails**, default-build inclusion passed **3 tests**,
and **458 plugin mirror pairs** matched. Live source-build model and radiologist
validation remain pending.

**2026-08-28 (Eagle Eye — Legion Consult foundation)** — New guard files:
`tests/code/ai_imaging/test_legion_consult_foundation.py` and
`tests/code/ai_imaging/test_legion_consult_ui_contract.py` (**14 focused guards**).
They protect the native/Legion function picker, MRI-only availability, mandatory
source/T1/T2 roles, role de-duplication, optional/select-all cost control,
non-diagnostic-series exclusion, deterministic four-corner LPS mapping, atomic
local-only request persistence, source identity matching, and toolbar routing.
The UI gate also proves that disarming an unfinished ROI returns the coordinator
to idle. No capture, provider dispatch, or model-analysis behavior is claimed
by this foundation gate.

**2026-08-29 (Eagle Eye — Legion Consult post-ROI completion)** —
`tests/code/ai_imaging/test_legion_consult_analysis.py` adds 10 focused guards,
with one additional retry-lifecycle guard in
`tests/code/ai_imaging/test_legion_consult_ui_contract.py`.
They pin the exact user-supplied Step 1 prompt fingerprint; Gemini screening and
GPT-5.6 Sol verification routing; clipped ±5 focus slices; exact complete-stack
overview coverage; LPS-to-series projection; 3D-volume validation; anonymous,
UID/path-free derived evidence and retry reconstruction; sequential transfer
of the Step 1 answer into Step 2; the workflow transition from a persisted ROI
request into analysis; and retention of source candidates when evidence
preparation fails before its manifest exists. The post-ROI transition guard
failed before the fix. The foundation persistence guard also verifies atomic
request-state advancement without changing the saved ROI geometry.

---

## Cumulative count (2026-08-18)

Counted directly by `tools/analysis/oneoff/count_test_files_2026_08_18.py`,
not from the dashboard:

- **Test files under `tests/code/`: 691** (`test_*.py`, recursive) across
  **41** domain folders, plus 16 sitting directly under `tests/code/`
- **Regression catalog rows: 59**

Note: the 08-16 block below recorded *688 files / 44 folders*. The file delta
is the three guards added on 08-18 (`test_mpr_step_instrumentation.py`,
`test_text_annotation_input.py`, `test_report_image_insert.py`); the folder
count differs because this script counts only folders that actually contain a
`test_*.py`, so it is the number to trust going forward. Re-run
`tools/analysis/oneoff/count_test_files_2026_08_18.py` to refresh both numbers.

---

## Cumulative count (2026-08-16)

Counted directly, not from the dashboard:

- **Test files under `tests/code/`: 688** across **44** domain folders
- **Regression catalog rows: 56**

---

## Cumulative count (post-audit 2026-05-29)

- **Total test files: 194** (code = 183, bus-driven = 7, pywinauto = 4)
- **Sandbox-runnable code tests: 121 / 0 / 0**
- **Structural system guards: 46 across 7 files**
- **Regression catalog rows: 37**
- **KPI registered keys: 42 across 13 workflows**

These numbers come from `python tools/kpi_dashboard.py` and `pytest tests/code/echomind tests/code/system`. They are the long-term measurement surface — every PR that lands a fix should make the catalog and test counts grow together.
