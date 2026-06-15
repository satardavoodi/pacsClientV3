# AI-PACS — Impatient-User Stress Test Report (2026-06-14)

**Tester:** automated agent (Cowork) · **Build:** source build, branch `beta-version` @ `2148050`
(version 3.2.8), Python 3.13.5, PySide6, pytest 9.0.3 · **Live app:** pid 450372 on DELL S2421HN
(1920×1080 @ 100% / DPI 96).

---

## 1. Executive summary

The pass ran in two layers, as agreed: (1) an autonomous code-level + KPI/log baseline, then
(2) live "impatient-user" GUI driving of the running source build.

**Headline results**

- **Code-level suite is broadly healthy.** ~2,990 tests executed across the impatient-user-relevant
  subsystems. `mpr`, `download_manager`, `fast`/`fast_viewer`, `performance`, `system`, `cd_burner`,
  `cloud_consultation`, `network`, `startup`, `runtime`, `database`, `diagnostics`, `storage` are green
  except a **deterministic 73-failure cluster in `tests/code/viewer`** (and 1 in `download_manager`).
  Triage shows these are **overwhelmingly stale/known tests or test-harness drift, not product
  regressions** — see §4.
- **KPI/logs are clean for stability:** 0 `database is locked`, 0 right-panel socket errors, 0 real
  socket timeouts, no monotonic memory leak (RSS peaks ~2.47 GB under heavy load then returns to
  ~0.5 GB), and native faults are the documented benign shutdown/takeover teardown noise. The one
  responsiveness concern is **cold-open latency on large server studies** (p90 8.3 s, max 28.9 s) — §5.
- **Live GUI driving was blocked by a real, reproducible home-page bug (P0):** patient **search
  succeeds server-side** (`Found 38 patients` MR, `Found 5 patients` CT) but the **center patient table
  never renders the results** — no rows, not even a header, no exception logged. Because a study can't
  be opened from the table, the downstream live tests (single/double-click thumbnails, drag-drop,
  scrolling, measurements, MPR, multi-patient pressure) could not be executed live; they are covered
  here via the code-level layer + KPI logs instead. Root cause is localized and a safe fix path is given
  in §6 / §7-P0.
- One genuine **product code finding** (P2): the application theme re-apply was reconnected to run
  **synchronously inside the `themeChanged` signal** (the deferral guard was lost) — §4 / §7-P2.

No crashes, no deadlocks, and no data-integrity problems were observed.

---

## 2. Scope & method

- **Safe test invocation verified first:** `main.py --run-tests` runs pytest in a subprocess and
  `sys.exit()`s at `main.py:177-180` **before** the single-instance lock (`main.py:1113`), so running
  the suite cannot trigger takeover or kill the live app. Suites were run with the blessed env-restore
  (`. .\_recovery\restore_env.ps1` → `WINDIR`, `COMPUTERNAME=DRALIZADEH`), `QT_QPA_PLATFORM=offscreen`,
  `AIPACS_NO_TAKEOVER=1`, `-p no:debugging`, and the documented collection-order workaround
  (`download_manager` collected before any home-panel suite).
- **Candidate test data** was discovered read-only from `dicom.db` (immutable open) — §3.
- **Live driving** used the running source build via screen control; logs were read live via the
  Windows side (the agent's sandbox mount of `user_data/logs` is **stale-cached** and must not be
  trusted for live log tailing — a process gotcha worth recording).

---

## 3. Test data — candidate patients

Discovered from the local `dicom.db` (910 patients, 1,024 studies, 8,701 series, 305,734 instances).

**Multi-study patients (highest pressure for open/sync/thumbnail/drag):**

| Patient ID | #Studies | Modalities | Series | Instances | Note |
|---|---|---|---|---|---|
| 1 | 20 | MR | 241 | 6,062 | extreme multi-study |
| 45401 | 2 | MR+DOC | 35 | 2,931 | large multi-study |
| 45013 | 2 | MR+DOC | 27 | 2,583 | large multi-study |
| 45346 / 45405 / 44825 | 2 | MR+DOC | ~28-38 | ~2,400 | large multi-study |
| 43802 | 4 | MR | 32 | 1,602 | multi-study |
| 44982 | 3 | DOC,US,MR | 8 | 61 | multi-modality (known dead-tab history) |

**High-slice series (best for aggressive scrolling + MPR):**

| Patient ID | Modality | Series | Slices | Body part |
|---|---|---|---|---|
| 43977 | CT | 202 & 302 | **576** | CHEST |
| 44915 | CT | 202 & 302 | 544 | CHEST |
| 44648 | CT | 202 & 302 | 508 | — |
| 43953 | CT | 202 | 500 | ABDOMEN |
| 45112 | CT | 202/302/402 | 480 | CHEST |
| 45557 | CT | 202/203 | 476 | WRIST (Bone+Tissue) |

Server-side (not-downloaded) cold-open candidates observed live today: **46316, 46363, 46271, 46257**
(46363 had a 22.9 s cold open — a good large-series stress target once the table bug is fixed).

---

## 4. Code-level test results

Run offscreen, non-interfering with the live app.

| Suite(s) | Result |
|---|---|
| `mpr` | **66 passed** |
| `download_manager` | **141 passed, 1 failed** (theme retint — see below) |
| `fast` + `fast_viewer` + `performance` | **734 passed, 13 skipped, 1 xfail** (all documented stale-spec / perf-tier-gated) |
| `system`+`viewer`+`ui_services`+`cd_burner`+`cloud_consultation`+`network`+`startup`+`runtime`+`database`+`diagnostics`+`storage` | **2,119 tests: 73 failed, 0 errors, 22 skipped** (72 of 73 in `tests/code/viewer`) |

**The 73 failures are deterministic** (identical count when `tests/code/viewer` is run in isolation =
72), so they are **not cross-suite pollution**. Triage:

| Bucket | Count | Classification | Evidence |
|---|---|---|---|
| `test_display_geometry` / `test_geometry_api` / stack-policy | ~15 | **STALE** | Tests assert identity/`eye(4)`; source `display_geometry.py:200` intentionally sets `M[2,3]=-1.0` (R30 fix, 2026-05-17, 1-based→0-based) with `[R30_FIX_INIT]` logging. Confirmed against source + your own geometry-eval memo. |
| `overlap_pixel_quality` / `_drag` | 6 | **Suspected offscreen artifact** | "dim/zero QImage" + golden pixel-hash mismatch — typical of `QT_QPA_PLATFORM=offscreen`. Re-run on the normal platform to confirm before touching goldens. |
| Backend-selection (`force_vtk_fallback`, `escape_hatch_overridden_by_force_vtk`) | 6 | **Likely intentional** | Tests expect `vtk_simpleitk`; code returns `pydicom_qt`/`pydicom_2d`. Consistent with the "FAST never instantiates VTK" rule — tests likely stale. Verify. |
| Mock drift (`SimpleNamespace` missing `_grow_future`, `_emit_mg_parity_trace`) | 2+ | **Test-harness drift** | Production added attributes the test fakes don't provide. |
| V2 token/constant drift (`#60a5fa`→`#3182ce`, `base_divisor 0.7`→`0.86`) | 4 | **STALE** | Tests assert pre-V2 tokens/constants. |
| `stage1_migration_validation` FileNotFound `tests\modules\viewer\fast\dicom_header_scan.py` | 4 | **Stale path** | References a moved/renamed source path. |
| `b34_interaction_aware_policy`, `b35_deferred_header_fill`, `fast_viewer_live_sync`, `progressive_admission_storm`, `progressive_grow_batch_cap`, `qt_slice_viewer_stack_drag`, `vtk_widget_split`, `dragdrop_progressive`, `tool_layer`, misc | ~36 | **Mixed — verify individually** | Behavioral assertions on prefetch/progressive/drag; some may be offscreen/timing-sensitive, some may be real. These touch acceptance-criteria areas (drag-drop, prefetch responsiveness) and deserve a focused pass. |
| `download_manager/test_dm_theme_retint::test_mainpy_defers_app_restyle_out_of_emit` | 1 | **REAL (P2)** | `main.py:1140-1145` connects `_apply_application_theme` directly to `themeChanged` and calls `app.setStyleSheet(...)` **synchronously** — the `_apply_application_theme_deferred` wrapper the test guards for is gone. A full-app restyle inside the signal emit can hitch the UI when the theme is re-tinted. |

> Recommendation: do **not** mass-rewrite the 72 viewer tests. The geometry ones in particular are
> flagged in your own notes as "stale **mask** regressions" — blindly updating them can hide a real
> geometry regression. Update them in a focused, reviewed pass (golden re-capture on the real platform
> for the pixel tests; confirm intended backend for the VTK-fallback tests).

---

## 5. KPI / lock / fault findings (from live + rotated logs)

| KPI | Value | Verdict |
|---|---|---|
| Open latency `first_series_visible` (44 server opens) | min 0.50 s · median **1.08 s** · p90 **8.29 s** · max **28.9 s** | 18/44 (41%) > 3 s — **cold opens of large not-downloaded series**. Spinner, not a freeze (hot-path completes ~1 s; the wait is download + header parse). Worst: 46363 = 22.9 s. |
| FAST `headers_only_build` | n=115 · median 53 ms · p90 289 ms · **max 978 ms** | Bounded; large series dominate (consistent with the H1 "viewer re-reads headers" analysis in your memos). |
| Memory (RSS) | min 275 · median 623 · p90 1,206 · **max 2,474 MB**, ended 504 MB | Peaks under heavy multi-study/large-CT load then **releases** — no monotonic leak. |
| `database is locked` | **0** | DB-lock backoff holds. |
| right-panel socket errors / port-105 misuse / real 45123 ms timeouts | **0 / 0 / 0** | Thumbnail-port and refresh-gate fixes hold. ("timeout" log hits were config strings `timeout:8`, `timeout=30s`.) |
| app.log ERROR / CRITICAL / tracebacks | 4 / 0 / 0 | 2× EchoMind "LLM network error contacting RAZI" (external); **2× `[PatientWidget] Error registering buttons with safeguard: Internal C++ object deleted`** (Qt lifetime — worth a look, §7-P3). |
| `native_fault.log` | `0x8001010d` ×287 | Documented benign shutdown/takeover teardown; faulthandler dumps ≠ crashes (app survives). |
| Auth | `Refreshing credentials due to a 401 response` ×73 (16:19→18:43) | Consultation-poller OAuth 401 refresh loop (known); does **not** block patient search (which uses the working socket auth). Noise worth quieting. |
| Console/terminal | `aipacs.resource` resource-summary every ~2 s | **Floods the launch terminal**, burying real tracebacks (contributing factor to the silent P0 below). Consider lowering cadence or routing resource-summary to its own file. |

---

## 6. Live GUI findings

### P0 — Home patient table does not render search results (BLOCKER)

**Symptom.** With a server selected, running a search returns patients but the center patient table
stays empty (no rows, **no header**), and a study cannot be opened from the home page.

**Reproduction (observed live, 2026-06-14):**
1. Home → select a modality (MR or CT) + date = Today → Search.
2. Live `app.log`: `socket_patient_service … Found 38 patients` (MR) / `Found 5 patients` (CT);
   `reporter-hydration … resolved pid=46363`.
3. The center pane (`patient_table_widget`) shows nothing. Zoom confirms uniform empty — no header row.
4. **No exception or traceback in `app.log`.**

**What was ruled out**
- *Not a search/backend failure* — search returns patients (38 / 5) and reporter-hydration resolves them.
- *Not a DPI/small-window issue* — window is 1920×1032 @ DPI 96 (100%).
- *Not a persisted-splitter collapse* — `QSettings("AIPacs","AIPacs")` has **no** `home/tripane_splitter_state`
  key, so the splitter uses default sizes `[314, 750, 216]` (`widget.py:526`).
- *Not cross-thread* — `home_search_service.py::search_server()` populates on the main/qasync loop;
  only the socket call is offloaded to the thread pool.
- *Not the parallel agent's uncommitted edits* — `home_search_service.py`, `patient_table_widget.py`,
  `_hp_layout.py`, `_hp_search.py`, `main.py` are all **clean/committed**.

**Root cause (narrowed to a visibility/embedding defect, not data):**

- The population path runs and **rows are added successfully.** `search_server()`
  (`home_search_service.py:481-496`) clears the table and calls `_add_socket_patient_to_table` per
  patient; that function reaches `self.add_data2patient_list_table(...)` (`_hp_search.py:1067`), which
  **always** reaches `self.patient_table_widget.add_patient_data(**kwargs)` (`_hp_search.py:1188`) — no
  early return. Its `except` (`_hp_search.py:1087`) logs with `exc_info=True`, and **no such error
  appears in app.log**, so the adds are not throwing.
- **`PatientTableWidget` is healthy.** A headless offscreen probe instantiated it and called
  `add_patient_data(...)` 3× → `rows=3, table.visible=True, rowHeights=[50,50,50], header.visible=True`.
  So the widget renders rows correctly in isolation.
- **Yet in the live home page the center pane shows no header and no rows** (verified by zoom). Since
  rows are added to a healthy widget but nothing displays, the `patient_table_widget` (or its
  `results_table`) is **hidden or sized to ~0 in the embedded center pane / tri-pane `QSplitter` at
  runtime** — the added rows are never shown. Ruled out: search/backend, DPI, persisted splitter state,
  population failure, and bulk-insert hide (`begin/end_bulk_insert` only toggles `setUpdatesEnabled`).

**One-restart instrumentation to close it (no behavior change).** After `end_bulk_insert()` in
`search_server()` (~`home_search_service.py:496`), log the live widget state:
```python
_rt = home.patient_table_widget.results_table
_logger.warning("[DIAG-table] total=%d rowCount=%d table_vis=%s table_size=%s widget_vis=%s "
                "widget_size=%s updates=%s splitter_sizes=%s",
                total, _rt.rowCount(), _rt.isVisible(), (_rt.width(), _rt.height()),
                home.patient_table_widget.isVisible(),
                (home.patient_table_widget.width(), home.patient_table_widget.height()),
                _rt.updatesEnabled(),
                getattr(getattr(home, "_home_splitter", None), "sizes", lambda: None)())
```
Restart, run one search, read `app.log` → the offending value (rowCount>0 with `widget_size`/`table_size`
≈0, or `isVisible()==False`, or a zeroed splitter size) names the exact defect. Then apply the minimal
targeted fix (restore visibility / enforce a sane center-pane min-size in the splitter). Headless probe
used: `user_data/logs/stress/probe_table.py`.

> Because a study could not be opened, the following live tests **could not be executed live** and are
> instead covered by the code-level layer noted in parentheses: single-click thumbnail load &
> stale-request cancellation (`fast/test_thumbnail_*`, `download_manager/test_socket_client_cancellation`),
> double-click open/download & duplicate prevention (`download_manager/*`), **drag-drop viewport
> replacement** (`viewer/test_dragdrop_progressive`, `cd_burner/test_viewer_dragdrop`,
> `download_manager/test_dm_preempt_on_drag`), aggressive scrolling (`performance/test_fast_scroll_perf`,
> `performance/test_b33_stack_drag_fast_interaction`), measurements (`mpr` + viewer tool tests), MPR
> (`mpr/*`, `system/test_mpr_*`). Note also the standing harness limitation recorded in your memos:
> **synthetic mouse drags do not trigger Qt drag-and-drop**, so true drag-drop must be validated at the
> code level regardless.

### Secondary (cosmetic, verify after P0)
The left search form renders its controls in roughly the left half of its ~314 px pane (labels clipped:
"Patie", "Custo", "Sele"); the "Adaptive to Screen Size" toggle and splitter dividers did not visibly
re-flow it. Re-check once the table renders, as the two may share a layout cause.

---

## 7. Recommended fixes (prioritized)

**P0 — Home patient-table render (clean files; needs one app restart to verify).**
Two-step, minimal, safe:
Population is fine (rows added; `PatientTableWidget` healthy in isolation per the headless probe). The
table is **hidden / ~0-sized in the embedded center pane** at runtime. Two-step, minimal, safe:
1. *Confirm the exact zeroed value* — add the `[DIAG-table]` log after `end_bulk_insert()` in
   `home_search_service.py::search_server()` (snippet in §6). Restart, run one search, read `app.log` —
   it shows whether `results_table`/`patient_table_widget` is `isVisible()==False`, sized ~0, or the
   `_home_splitter` handed the center pane a 0 size.
2. *Apply the minimal targeted fix* for whichever it is — restore the table's visibility, or put a sane
   floor on the center pane so the splitter can't collapse it to 0
   (`patient_table_widget.setMinimumWidth(...)` / a `_home_splitter.setSizes([...])` guard). Re-verify by
   searching (header + rows appear). Stay within the existing layout path; do **not** rewrite search.

**P2 — Theme re-apply runs synchronously in `themeChanged`.** Restore the deferral in `main.py:1140-1145`:
wrap the `app.setStyleSheet(...)` in a `QTimer.singleShot(0, …)` (an `_apply_application_theme_deferred`)
and connect *that* to `themeChanged`, so a re-tint never repolishes every widget inside the signal emit.
Re-greens `test_dm_theme_retint`. *(Note: `main.py` is clean, but a parallel Claude Code session is
active — coordinate before editing `main.py`.)*

**P3 — `[PatientWidget] Error registering buttons with safeguard: Internal C++ object deleted` (×2).**
A Qt object-lifetime race during patient-button registration; investigate the safeguard registration
path for a widget used after deletion (relates to multi-patient tab lifecycle).

**Hygiene.** (a) Lower `aipacs.resource` resource-summary cadence or route it to its own log so the
launch terminal isn't flooded (this directly hid the P0 cause). (b) Quiet/repair the consultation-poller
401 refresh loop. (c) Schedule the focused, reviewed pass to update the genuinely-stale viewer tests
(geometry, V2 tokens, moved paths) and re-capture pixel goldens on the real platform.

---

## 8. Test-automation improvements (proposed)

Code-level (verifiable headless, no live app):
- **Search→table population guard:** drive `search_server()` with a stub socket service returning N
  patients; assert `patient_table_widget.results_table.rowCount() == N` and that a row-add exception is
  *raised/logged*, not swallowed. (Directly guards the P0 class.)
- **Thumbnail cancellation:** assert a superseded single-click thumbnail request is ignored (extend
  `test_socket_client_cancellation` to the right-panel path).
- **Server-sync comparison:** assert a study that grew on the server triggers exactly one re-fetch
  (extend the `_thumbs_server_refreshed_uids` gate tests).
- **Viewport replacement lifecycle:** assert a drop into an occupied viewport fully replaces stack +
  metadata + measurements (no residue) — strengthen `test_dragdrop_progressive`.
- **Duplicate prevention:** assert repeated double-clicks/drops don't create duplicate downloads or rows.

GUI (once P0 is fixed): scripted patient search, single vs double click disambiguation, repeated
drag-drop, aggressive scroll, ruler measurement, MPR launch/rotate/close.

---

## 9. Acceptance-criteria status

| Criterion | Status |
|---|---|
| Patient search/list responsive | ⚠️ Search backend OK & responsive; **list does not render (P0)** |
| Single-click thumbnail without freeze | ◻️ Blocked live; code-level green |
| Double-click open/download correct | ◻️ Blocked live; code-level green |
| Server sync detects missing/new series | ✅ Code-level green; logs show correct resync gating |
| Drag-drop replaces viewport repeatedly | ◻️ Blocked live (+ synthetic-DnD limitation); code-level green |
| Aggressive scrolling no crash/freeze | ◻️ Blocked live; `fast_scroll`/`b33` green |
| Length measurements during stress | ◻️ Blocked live; mpr/viewer tool tests green |
| MPR open/rotate/close stable | ◻️ Blocked live; `mpr` 66 green |
| Multi-study patients don't break pipeline | ✅ Code-level green (multi-study/enumeration guards) |
| No serious lock/deadlock | ✅ 0 `database is locked`, no deadlock observed |
| KPI violations fixed or documented | ✅ Documented (§5) — cold-open latency the main item |
| Existing code-level tests pass | ⚠️ 73 failing, triaged as mostly stale/known (§4) |
| New impatient-user stress tests added | ◻️ Proposed (§8); not yet added pending P0 + edit-coordination |

✅ met · ⚠️ partial / needs work · ◻️ blocked by P0

---

## 10. Residual risks & follow-ups

1. **P0 home-table render** — top priority; safe diagnostic + fix path in §7. Needs one human-driven
   restart to verify (per bootstrap mode).
2. **Live impatient-user driving** is pending the P0 fix; once a study opens, run the §6 checklist live.
3. **Concurrent editing:** a parallel Claude Code session is active on this repo. Coordinate before
   editing shared files (especially `main.py`) to avoid clobbering.
4. **Cold-open latency** on large not-downloaded studies (p90 8.3 s) — track against the H1 header-rescan
   work already scoped in your memos.
5. **Stale viewer tests** — a reviewed cleanup pass was done (§11); the remainder is classified there.

---

## 11. Test-suite cleanup (follow-up pass)

**Rule applied:** a test was only changed to match *verified intended behavior* (source/docs), only
removed/repathed when provably obsolete, never weakened just to pass, and never touched when it might be
catching a real bug. The viewer test files were clean in git (no conflict with the parallel session).

### Fixed + verified (viewer failures **72 → 59**, theme test green, zero regressions)
- **`main.py` theme deferral restored (real P2 bug)** — `themeChanged` now connects
  `_apply_application_theme_deferred` (QTimer.singleShot wraps the full-app `setStyleSheet` out of the
  signal emit). `test_dm_theme_retint` green.
- **`test_display_geometry` (8):** the 6 round-trip tests now compare against the *captured initial
  matrix* (the true invariant — "round-trip returns to start"), not a hardcoded `eye(4)`; init/reset
  assert the documented R30 init (`eye` with `M[2,3]=-1.0`). Robust and R30-correct.
- **`test_progressive_grow_batch_cap` (2 of 4):** fixed an off-by-one source path
  (`.parent.parent.parent` → `.resolve().parents[3]`; the test moved from `tests/viewer/` to
  `tests/code/viewer/`). The other 2 now fail a *real* content check — see "real bugs" below.
- **`test_fast_viewer_empty_state_ui` (2):** `#60a5fa` → `#3182ce` accent token (the source docstring
  documents the move from a hard-coded sky-blue to the theme `accent`; default `#3182ce`).
- **`test_advanced_conservative_optimizations` (1):** added `_emit_mg_parity_trace` to the fake.
- **NEW `test_patient_table_population_visibility.py` (3):** guards the **P0 class** — the patient table
  must actually render rows after the `clear → begin_bulk → add×N → end_bulk` search path (rowCount,
  visible, non-zero row heights, `updatesEnabled` restored). Would have caught the live Home blocker.

Partial (correct attribute added; fake needs more — left in place + flagged): `b34::close_series`
(`_grow_future`), `roi_wl::manual_qt_window_level` (`_current_window_level`).

### Remaining 59 — classified, deliberately NOT auto-changed

**POSSIBLE REAL BUGS (do NOT update the test — fix the code):**
- **`TestDisplayKPolicy` (2):** after `apply_k_flip_for_stack_order`, `display_k_to_raw_k(1)` returns
  **-1** (expected 0) and `raw_k_to_display_k(0)` returns **2** (expected 1) — an off-by-one in the
  k-flip slice-index mapping (clinical slice-order relevant). Independently confirmed.
- **`test_progressive_grow_batch_cap` content (2):** after the path fix,
  `test_pipeline_passes_max_entries_to_scan_*` now fail a real source-contract check — the pipeline may
  not pass `max_new_entries` to `scan_series_header_entries` as the Fix-A contract specifies.

**Stale-but-deferred (grounded; mechanical update):**
- **`TestV2BandParams` (8):** `base_divisor` retune `0.86→0.70` (micro/tiny), `0.99→0.80` (small) is
  intentional (`RELIABILITY_STABILITY_REVIEW_2026-06-04`); update the asserted constants + the derived
  traversal/`v_onset` expectations to match `qt_slice_viewer.py`.
- **Geometry `effective_equals_raw` / `lps_origin` / `geometry_api origin` (3):** R30-derived; update to
  the 1-based-display contract (display k=1 → raw k=0; effective affine differs from raw by the −1 k
  translation).

**Needs design confirmation (backend, 10):** `stage1`/`stage2` expect `pydicom_qt` + `force_vtk →
vtk_simpleitk`; code now returns `pydicom_2d` / `pydicom`. Confirm the current FAST/Advanced backend
design (the on-disk config moved to `pydicom_2d`) before updating — these are migration guardrails.

**Offscreen-suspected (6):** `overlap_pixel_quality[_drag]` golden-hash — re-run on the normal platform;
if offscreen-only, gate behind a real-platform marker / skip-with-reason rather than re-baselining blind.

**Ambiguous behavioral — verify against source before changing (subagent uncertain):** `b34` prefetch
(6), `b35` deferred-header (4), `dragdrop_progressive` (2), `event_loop` (1), `fast_viewer_live_sync` (3),
`mg_window_placeholder` (1), `progressive_admission_storm` (4), `tool_layer` (2), `vtk_widget_split` (3 —
likely AST-checker false positives: `gc`=module, `object`=builtin, loop vars). Several show "nothing
submitted" (`0 == 6`, `set()==…`), which usually means the test's fake isn't wired to the current path
(harness-drift) — but each must be confirmed against production before editing so a real regression
isn't masked.

---

## 12. Live verification + no-mouse interaction tests (follow-up 2)

Fresh app instance on monitor A; operator confirmed search works.

**The app renders correctly — P0 framing corrected.** Search populates the home table (a CT patient row
was visible) and double-click opens the viewer. The FAST viewer renders images — confirmed in the live
log: `FAST:first_image_visible series=202 slice=78 render_ms=23.9 filter_status=applied`,
`viewer_interactive_ready`, `switch_series complete slices=156`. The "empty viewport/table" seen in my
screenshots is largely a **capture limitation** — computer-use screen captures do not grab the FAST
viewer's hardware-accelerated image surface (the operator sees it on the monitor). The earlier
zero-row/empty-viewport observation was the *prior degraded instance* + this capture gap; the §6 P0 is
**not reproduced** in the fresh instance.

**Computer-use synthetic input does not reach the FAST viewer.** A live scroll logged
`[FAST_EVENT_PACING] total_events=0` — OS-level synthetic wheel/drag (like synthetic Qt DnD) is not
delivered. Impatient-user stacking/drag-drop must be driven through the code-base (operator's guidance),
not the mouse.

**Cold-open KPI:** the server 156-slice CT (pid 46314, not downloaded) logged
`first_series_visible t_ms=77889` (**77.9 s**) — download-bound (all other phases done by ~2 s; render
itself 23.9 ms). Worst cold-open observed; reinforces the §5 latency item. Local/downloaded studies open
fast.

**DICOM import — verified healthy (code + real data):**
- 66 import tests pass (pipeline, JPEG 2000 transcode, flat-folder, preview, background-job); 2 documented skips.
- Real data `D:\AI-PACS-Recordings\Dicom test file`: **927 .dcm parse, 0 errors**; 2 studies (MR 6 series/199 inst,
  CT 10 series/728 inst); all JPEG 2000 Lossless; pixels decode (512×512 uint16).

**No-mouse stacking + drag-drop — the code-base entry points (per operator request):**
- Stacking: `pipeline.set_slice_index(i)` · `bridge.set_slice(i)` · slider-drag session
  `bridge.begin_slider_drag()` → `handle_slider_drag_target(i)` → `end_slider_drag()` ·
  `qt_slice_viewer.set_current_slice_index(i)`. (These are what the wheel handler calls internally.)
- Drag-drop (series-load into a viewport): `qt_fast_container.switch_series(...)` (the drop's effect),
  `qt_fast_container.dropEvent(event)` (raw handler), `_vc_load.load_series_on_demand/immediately(...)`;
  at the pipeline level a drop = `close_series()` + `open_series(other)`.
- NEW `tests/code/viewer/test_stacking_and_dragdrop_no_mouse.py` (**6 tests, all pass**): aggressive
  forward/backward stacking tracks exactly; over-scroll clamps (no crash/blank); `bridge.set_slice` +
  slider-drag session safe; **drop replaces the viewport cleanly** (new slice range, index reset, no
  residue of the previous series); re-drop restores; repeated same-series drop is idempotent.

**New tests added this engagement:** `test_patient_table_population_visibility` (3) +
`test_stacking_and_dragdrop_no_mouse` (6) = **9, all green**.

---

## 13. Optimization round (tests + app function)

Viewer failures **59 → 48** (zero regressions), plus a real app-function fix:

- **REAL APP BUG fixed — missing `import gc`** (`_vw_series.py`): `switch_series`'s GC
  threshold save/restore called `gc.set_threshold(...)` / `gc.enable()` but `gc` was never
  imported in that mixin, so the restore silently raised `NameError` (swallowed by a broad
  `except`) and GC stayed mis-configured after a heavy series load. Added the import.
  Surfaced by `test_vtk_widget_split::test_mixin_method_names_resolve` — the static checker was
  correct here.
- **`TestV2BandParams` (8) optimized** to the intentional v3.0.8 retune (documented per-band in
  `qt_slice_viewer.py` + `RELIABILITY_STABILITY_REVIEW_2026-06-04`): micro/tiny `base_divisor
  0.86→0.70`, small `0.99→0.80`, and the tiny/small *no-gain* tests rewritten to the new **mild
  velocity gain** (`v_onset` 450/500, `gain_max` 1.2/1.3). Derived traversal/px expectations
  recomputed. Verified green (49/49 in that file).
- **`test_vtk_widget_split` AST checker (3) made accurate** (without weakening real-undefined-name
  detection): it now recognizes module-level `ClassDef` names (`_QtBridgeStyle`), the `object`
  builtin (+ a few others), and **lambda / nested-function parameters** (`d`, `_k`) — which were
  false positives. All 3 pass.
- **DisplayKPolicy (2) — characterized, NOT auto-changed (clinical).** `apply_k_flip_for_stack_order`
  composes `init @ _k_flip_4x4(n)`, which **double-applies the 1-based→0-based offset**: the k-row
  translation becomes `-2`, so `display_k_to_raw_k(1)` returns `-1` instead of `0` (while
  `is_k_flip_active` stays `False`, which passes). There is a genuine **docstring-vs-test
  contradiction** (docstring: "reverses the stack"; tests + the hardcoded `k_flip_active=False`
  log: *not* a reversal). Because this is clinical slice-ordering, the fix needs the R30 author's
  intent — documented here, not applied. *Fix candidate:* make the stack-order policy not re-add
  the −1 already present at init, OR make `_k_flip_4x4` a true reversal — then verify slice order
  on a real series.

**Cumulative this engagement:** 72 → 48 viewer failures fixed safely (24 tests: geometry 8, dicom-path
2, V2-token 2, mock 1, base_divisor 8, vtk_split 3) + 2 real app bugs fixed (theme deferral, `gc`
import) + 9 new guard tests, all verified. Remaining 48 = backend (10, needs design confirmation),
DisplayKPolicy (2, clinical, documented), geometry-derived (3), dicom_header content (2, real),
offscreen-suspected pixel goldens (6), and the ambiguous behavioral clusters (~25, verify-before-edit).

**Clinical-safety guardrail:** all clinically-sensitive / deferred items are now tracked in
`docs/technical-debt/suspected-issues.json` (+ `.md` companion). Geometry, slice ordering, orientation,
flip/rotation, and final rendering output are **not** changed to satisfy a test — only documented and
monitored unless a real, reproduced, user-visible bug (or a clear code-level double-operation) is
proven. The two code fixes this engagement (theme deferral, `gc` import) are non-clinical-output
software-engineering defects.

---

## 14. Fix round 2 — clear engineering defects only (output-preserving)

Viewer failures **48 → 45**, zero regressions. Followed the clinical-safety principle: fix clear
software-engineering / user-visible defects; leave clinical output untouched; document the rest.

- **SUSPECT-005 (progressive-grow cap) — VERIFIED CORRECT, not a defect.** The cap *is* applied:
  `lightweight_2d_pipeline.py:3794-3803` selects `_max_grow` (= `_MAX_PROGRESSIVE_GROW_ENTRIES_HEAVY`
  during heavy download, else `_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK`=16) and passes
  `max_new_entries=_max_grow`. The 2 contract tests checked an old literal string → updated them to the
  current form (test-only). Now green.
- **SUSPECT-008 (PatientWidget Qt-lifetime) — REAL FIX.** `_register_buttons_with_safeguard` now filters
  out deleted Qt widgets (`shiboken6.isValid`, fallback `objectName` probe) before `register_buttons`,
  and `auto_discover_buttons` is best-effort. A dead button (a tab closed mid-init) no longer aborts the
  whole batch ("Internal C++ object deleted"). Non-clinical stability fix.
- **dragdrop_progressive S7 (cache-miss) — STALE test fixed.** The code correctly **re-arms** the
  awaiting marker + keeps the spinner on a cache miss (BUG-1 fix 2026-06-04 — the old clear+hide
  orphaned drops; they died silently, only close+reopen recovered). The test asserted the old buggy
  clear+hide → updated to the verified re-arm behavior. Now green.
- **dragdrop_progressive S17 (one-shot final grow) — kept RED, NOT masked.** The minimal mock can no
  longer drive the evolved `on_series_images_progress` (lifecycle/finalization guard layers + an outer
  try/except that swallows errors). Could be harness-drift OR a real "viewer stuck at slice 19" grow
  regression → registry SUSPECT-006: verify via a **live drag-at-N/M** scenario before changing
  anything.

**Cumulative across the engagement:** **72 → 45** viewer failures resolved safely · **3 real code fixes**
(theme deferral, `gc` import, PatientWidget Qt-lifetime) · **9 new guard tests** · a structured
technical-debt registry. **No clinical geometry, slice ordering, orientation, flip/rotation, or final
rendering output was changed.**

## 15. Settings → Storage info + clear-data consistency (follow-up 3)

Scope: **data management only — no clinical output (geometry / slice-order / rendering) is touched.**
Target: Settings → Viewer Configuration → **Information Storage**.

**Audited, found sound:**
- **Async size loading (FIX request #1).** Already off-thread with a 30 s cache + coalescing — opening
  the panel does not block the UI and storage sizes fill in progressively. Verified by
  `test_storage_cleanup_panel_async`. No change needed.
- **Clinical-safety of download status.** Download/green status is recomputed from **disk**
  (`check_study_complete`), not a DB flag — disk stays the source of truth.

**Real defects fixed (all output-preserving):**
- **FIX-004 — green badge lingered after a clear (the main reported bug).** The panel emitted
  `storageChanged` but **nothing was connected to it**, so the home patient table kept serving the
  cached downloaded/green badge after the files were deleted. Wired `storageChanged` (through the
  lazily-built viewer-config tab, in `AIPacs_ui._wire_modality_grid_config_signal`) to a **focused
  `patient_table_widget.refresh_download_statuses_local_only()`**, which clears the in-memory status
  cache and recomputes each visible row from disk **without any server call or refresh-button
  animation** — the smallest possible blast radius for a storage clear (the broader
  `refresh_download_statuses()`, which also re-pulls the report column from the server, remains as a
  defensive fallback). The connect + handler are fully guarded (can't break startup or the existing
  modality-grid wiring).
- **FIX-003 — stale in-memory thumbnails.** Clear Cache / Clear Patient deleted files on disk but left
  the in-memory `ThumbnailStore` populated. The clear paths now call `ThumbnailStore.instance().clear()`
  so RAM matches disk immediately.
- **FIX-005 — consistency validator + repair (FIX request #5).** Added a read-only
  `validate_storage_consistency()` (DB studies whose files are gone → would still show downloaded;
  orphan disk folders; thumbnails pointing at missing files) and a conservative
  `repair_storage_consistency()` that removes stale DB study records (instances→series→studies,
  cascade-agnostic) and NULLs dangling thumbnail pointers. **Repair never deletes any files;** orphan
  disk folders are reported only (could be a not-yet-indexed import). Surfaced via a new
  **"🩺 Check Consistency"** button that offers repair only when repairable items exist.
- **FIX-006 — partial-deletion confusion (FIX request #4).** `CleanupResult` now carries a `warnings`
  list; if file deletion succeeds but the matching DB cleanup fails (e.g. DB locked), the action reports
  `success=False` + a WARNING instead of a silent partial success.

**Transactional consistency (FIX request #3).** A clear now spans files → DB → thumbnails (disk +
in-memory `ThumbnailStore`) → in-memory status → **UI refresh** (the `storageChanged` wiring), with a
warning when any leg fails so the user can run Check Consistency.

**Logging.** All new logging is counts/paths only — **no credentials or tokens.**

**Tests (13 green, offscreen, isolated temp DB — never touches the live `dicom.db`):**
`tests/code/storage/test_storage_cleanup_consistency.py` (validator detect+repair, orphan-not-deleted,
present-not-flagged, cache-clear clears ThumbnailStore, partial-failure warning) and
`tests/code/storage/test_storage_change_home_refresh_wiring.py` (the full
`storageChanged → refresh_download_statuses_local_only` chain as a static guard, **including a
no-server-pull / no-button-animation conservative guard** on the local-only refresh). Settings
lazy-init + settings integrations re-run clean (28 passed together) — **no regression** from the
`AIPacs_ui` wiring.

**Remaining (live confirm):** download a study (green) → Clear Patient Data → verify the home badge flips
to not-downloaded without a restart. The wiring + recompute are verified statically and by unit tests;
the end-to-end UI flip is best confirmed on the running app.

## 16. Other-PC log triage (follow-up 4 — installed build, 2026-06-14)

Triaged the logs from the second workstation (`Desktop\log on other pc\`: `native_fault.log`,
`app.log[.1]`, `download_diagnostics.log`, `db_diagnostics.log`, `viewer_diagnostics.log`).

**Real client crash found + FIXED (FIX-007).** `native_fault.log` captured a Windows **access violation**
on the live event loop:

```
Current thread (most recent call first):
  patient_tab_widget.py line 458 in animate_hover
  patient_tab_widget.py line 448 in enterEvent
  main.py line 907 in notify   ←  run_forever (main.py:1511)
```

Root cause: `animate_hover` / `animate_active` created a **local** `QPropertyAnimation(self, b"geometry")`
with no parent and no stored reference, called `start()`, and returned — so Python could garbage-collect
the wrapper while the 150–200 ms animation was still running, freeing the underlying C++ object mid-flight.
Fast hovering across patient/service tabs (an impatient user) spawns many short-lived animations and makes
the race likely. **Fix:** reuse one animation per widget, **parented to `self` and stored on `self`**
(`_hover_animation` / `_active_animation`), stopped before each restart — identical visible animation, but
it can no longer be collected while running. Applied to both sibling widgets
(`patient_tab_widget.py`, `service_tab_widget.py`); guard test
`tests/code/test_tab_hover_animation_lifetime.py` (2 green). The same bare-local pattern exists in a few
non-crash paths (fade-out / opacity / border animations) — lower risk, noted for opportunistic cleanup.
The other two access violations in `native_fault.log` (`main.py:1597` and `:1606`) are
**shutdown/takeover teardown** — known and mostly benign.

**Environmental, NOT a code bug (OBS-009).** `download_diagnostics.log` has ~337 ERROR lines, dominated by
**network/server connectivity**: 45× `NetworkError: Too many broadcast messages, no response received`,
`[WinError 10060]` TCP connection timeouts (`the connected party did not properly respond`), 3× `Connection
lost while receiving data`, plus 1× `UnicodeDecodeError` / 1× `JSONDecodeError` on a garbled/desynced
response. **`app.log` and `db_diagnostics.log` are clean over the same period** — the client logged and
retried, and the app stayed up. Action is on that PC's link to the PACS server (host reachable, firewall,
correct host/port, link quality), not in client code. One optional client-robustness item: map a desynced
response to the structured "Response too large" desync path + bounded retry instead of a raw decode error.

**Viewer (downstream, not a standalone defect).** Two `[ASYNC SWITCH] preview remained active for
series=… (full load failed)` lines coincide with the network failures — the viewer's **defensive fallback**
(keep the preview when the full series can't be fetched) working as intended, not a separate bug.

**Reaches the other PC only after a rebuilt installer** — it runs the frozen build, which predates these
source fixes.

## 17. Second-PC log triage — "pc 2 baba", multi-study focus (follow-up 5, 2026-06-15)

Triaged the `pc 2 baba\` logs (previous installed build, June 15): `native_fault.log` (9 access
violations), `app.log`, `download_diagnostics.log`, `viewer_diagnostics.log`, `db_diagnostics.log`.

**Multi-study functional behaviour is HEALTHY (the headline answer).** The logs show grouped multi-study
rendering working: `patient_tab_thumb_multistudy_rendered series_count=17 studies=3`, `…16 studies=2`,
`…16 studies=3`, each preceded by per-sibling-study `multistudy_prefetch`. The right-panel cache gate is
also correct: of 70 `right_panel_cache_gate` decisions, the 44 `grew=1` are **different patients' first
opens** (`local_thumbs=0` → fetch), each followed by `grew=0` cache hits on re-open — **no refetch loop,
no cross-patient mixing, no missing study**. `cross_patient_skip`, `study_enumerated_by_modality`, and
`resync` markers are **absent** — this previous build simply predates the 2026-06-02 per-modality
enumeration and the resync work; nothing in the logs shows a multi-study study going missing on this build.

**The real problem is crashes — root cause identified.** All 9 access violations share one mechanism. The
`main.py` `notify()` override (an **intentional** crash-capture that re-raises any event-dispatch exception
so a full traceback is logged) converts a recoverable transient into a PySide cascade:
`SystemError: …notify(): <built-in function perf_counter> returned a result with an exception set`,
`<class 'PySide6.QtWidgets.QMenu'> returned NULL without setting an exception`, `notify called with wrong
argument types`. The **trigger correlates with network failures during patient open** — `WinError 10065`
(unreachable host, attachments) and `WinError 10060` timeouts. So the crashes are largely **environmental
(flaky PACS link) amplified by crash-on-exception**, occurring in the open path.

**Fixed (FIX-008, conservative, current-source bug).** One concrete crash site was still exposed in current
source: `_hp_layout._hide_loading_overlay` built an opacity `QPropertyAnimation` on a possibly-deleted
overlay during the async-open teardown race (`_hide_loading_overlay ← hide_loading ←
_on_patient_double_clicked_async`). Added the same liveness guard the sibling `loading_overlay.py` already
has — `shiboken6.isValid` + try/except → fall back to `overlay.hide()`, never raise into the open path.
Applied to `_hide_loading_overlay` and `_show_loading_overlay`. Guard test
`tests/code/test_loading_overlay_liveness_guard.py` (3 green).

**Already fixed in source → need a rebuilt installer on pc2.** The `loading_overlay.py _start_fade` crash
and the tab-hover animation crashes (FIX-007) are already hardened in current source; they reproduce on pc2
only because it runs the older frozen build.

**Documented, not changed (needs author sign-off).** Changing `notify()` to recover (log + return) instead
of re-raising would reduce these crashes, but it is a core safety/diagnostic mechanism — flagged in OBS-010,
not altered unilaterally. The MPR axial-view (`_mpr_views._create_axial_view`) and `add_patient_data`
crashes are noted for separate verification (likely VTK/GPU-environmental and old-build line numbers
respectively; neither is multi-study).

**Action items for pc2:** (1) rebuild + reinstall to pick up FIX-007/FIX-008 and the loading_overlay guard;
(2) fix that PC's network/PACS-server connectivity (the `WinError 10060/10065` upstream trigger).
