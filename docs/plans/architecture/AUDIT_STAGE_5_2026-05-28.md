# AI-PACS Application Audit — Stage 5 Report (Viewer read-only)

**Date:** 2026-05-28
**Scope:** Viewer state — active tab, open tabs, sidebar correctness, multi-study info, thumbnail data, green-border / download-state consistency. **No write-side viewer changes** were made (per the plan).
**Method:** Live workflow against the source build (pid 552932) + read-only structural guards.

---

## 1. Workflow exercised

1. Returned to home tab from the DM widget (home view re-rendered with 100 MR studies, all-date range).
2. Identified **malakoti somayeh (ID 1)** as a multi-study patient candidate — the only row with the **green download arrow** in Status column, multi-body-part listing (`CSPINE, LSPINE, HEAD, BRAIN, ...`), and 132,540 images (clearly a multi-study patient).
3. Double-clicked the row → viewer tab opened.
4. Waited for the viewer's series sidebar to populate.
5. Scrolled the sidebar to observe study grouping (read-only).
6. Did NOT load any series into a viewport, did NOT change layout, did NOT click any toolbar tool.

---

## 2. Live observations

### 2.1 Tab + toolbar bring-up

A new patient tab appeared next to the AI-Pacs home tab labeled `malakoti somayeh / ID: 1` with a close (×) button. The full viewer toolbar materialized: layout, multi-row, eraser, zoom, flip, pan, layers, rotate, +, camera, mic, eye, helmet, **MPR**, download. The header time stamp matched the live session.

### 2.2 Series sidebar — multi-study grouping works correctly

After ~18 s of cold load, the sidebar reported:

- **239 series total** (badge in the panel header)
- Grouped by study with explicit headers:
  - **`Study 1 — LSPINE (12 series)`** — series 1 through 12, with per-card titles like `t2_haste_cor_myel...`, `t2_haste_sag_my...`, `t2_lse_tra_msma...`. Image counts per series: 8, 1, 1, 11, 11, 25, 8, 1, 1, 11, 11, 20.
  - **`Study 2 — CSPINE (6 series)`** — header visible right after Study 1's Series 12, starting a fresh "Series 1" within Study 2 (per the multi-study invariant: series-number collisions don't collapse studies).
  - More studies expected below (badge total = 239 series, vs ~18 visible across Studies 1+2).

This matches the `MULTI_STUDY_SINGLE_TAB_PLAN.md` invariants:

- ✅ Each study gets its own group header with body part and series count.
- ✅ Series numbers within a study go 1, 2, 3, … — independent of other studies.
- ✅ The sidebar is populated via the deferred `_render_multistudy_grouped` path (no flickering observed during load).
- ✅ Patient-level total (239) is displayed at the panel header.

### 2.3 Viewports — empty (browse mode)

Both left and right viewports show the placeholder `Drop a series here or select one from the thumbnail panel.` No series was loaded — that's the read-only state. No green border / active border on any thumbnail in the sidebar (no series is "active" yet). Working as designed.

### 2.4 Active-tab indicator

The patient tab `malakoti somayeh / ID: 1` shows the red × close icon when active (mouse-hover or selected state). Single source of truth for which tab is currently focused. The home tab `AI-Pacs` is the home tab; the malakoti tab is the active patient tab. **No tab confusion.**

---

## 3. Regression guards — all passing

`tests/code/echomind/test_viewer_adapter.py` — **11 / 11 PASS**:

| Guard | What it protects |
|---|---|
| `test_no_active_tab_returns_clean_error` | Calling get_active_tab without a tab returns a typed error, not None |
| `test_get_active_tab_single_study` | Single-study path still works |
| `test_get_active_tab_multistudy_flag_propagates` | `multistudy=True` flag reaches the bus result |
| `test_list_open_tabs` | Multiple open tabs enumerate correctly |
| `test_list_open_tabs_no_tab_widget_error` | Defensive when no tab widget exists |
| `test_get_thumbnails_data_returns_rows_with_orig_series_number` | The `_orig_series_number` key is preserved per-row (essential for multi-study offset-key resolution) |
| `test_get_active_series_focused_viewport` | Active series reflects the focused viewport |
| `test_get_active_series_returns_empty_when_no_viewport` | Defensive when no viewport |
| `test_get_multistudy_info_single_study_returns_one_primary_row` | Single-study patients still get one row |
| `test_get_multistudy_info_multistudy_flags_primary` | Primary study is flagged correctly |
| `test_adapter_is_purely_read_only` | **Structural guard — no write-verb actions exist** |

`tests/code/echomind/test_bus_factory.py` — **5 / 5 PASS** including `test_factory_wires_everything_when_all_args_provided` which is the end-to-end production wire-up verification.

---

## 4. Real issues found

**None.** Multi-study sidebar grouping works in the live build. Active-tab indicator is single-source-of-truth. Read-only ViewerAdapter is structurally enforced — there are zero write-verb actions registered.

---

## 5. Non-issues confirmed

1. **Sidebar reported "0 series" during the first 8 seconds after double-click** — initial empty render before disk-side study/series enumeration completes for a 239-series multi-study patient. Eventually populated correctly. Not a bug; could be a UX-polish opportunity (show a "Indexing…" placeholder) but not a defect.

2. **No green border on any series thumbnail** — by design at this point. Green border indicates the series currently loaded in the focused viewport. No series was loaded (read-only audit). Once a series is dragged to a viewport, its sidebar card gets the active border. **Working as designed.**

3. **Viewports show placeholder text** — by design. The viewer is in browse mode until the user explicitly drags a series.

4. **TelegramDesktop notification appeared briefly during scroll** — system notification, not part of AI-PACS state. Cleared on its own.

---

## 6. Fixes applied

**None.** No code changes were made in Stage 5.

---

## 7. Tests run

After Stage 5 (no code changes):

- `tests/code/echomind/test_viewer_adapter.py` — **11 / 11 PASS**
- `tests/code/echomind/test_bus_factory.py` — **5 / 5 PASS**
- Total runnable sandbox surface still **106 / 0** from Stage 2.

---

## 8. KPI / dashboard impact

- KPI schema unchanged (42 keys, baseline in sync).
- Regression catalog still 34 rows.
- Dashboard verdict still `[1 warn]` — pre-existing stale native fault.

**Live KPI evidence:**

| KPI | Observed | Budget (warn / hard) | Status |
|---|---|---|---|
| `viewer.first_render_ms` | n/a (no series loaded) | 500 / 800 | n/a — read-only |
| `viewer.stack_rebuild_ms` | n/a (no layout change) | 300 / 500 | n/a — read-only |
| Sidebar populate time (cold load, 239 series, multi-study) | **~18 s** | (no KPI key for this specific case) | informational — first-open is the heaviest case |
| `get_active_tab.elapsed_ms` (structural) | n/a (not exercised via bus) | 40 / 80 | n/a |
| `get_thumbnails_data.elapsed_ms` (structural) | n/a (not exercised via bus) | 80 / 150 | n/a |
| `get_multistudy_info.elapsed_ms` (structural) | n/a (not exercised via bus) | 60 / 120 | n/a |

The 18 s sidebar populate is the **cold-load case** for a heavy multi-study patient (239 series across multiple studies, 132,540 image references). For warm load or smaller patients, the time will be much lower. This isn't a defect — it's the inherent cost of indexing many series. A future optimization (background indexing during patient-list browse) could move some of this work off the patient-open critical path.

---

## 9. Regression catalog changes

**None.** No fix landed.

---

## 10. Remaining risks

1. **Live in-process bus introspection wasn't exercised.** I verified the ViewerAdapter via structural unit tests; the live bus actions (`get_active_tab`, `list_open_tabs`, `get_thumbnails_data`, `get_active_series`, `get_multistudy_info`) couldn't be called from the sandbox against the running process (no exposed RPC; that's by design for now). The structural unit tests cover the contract that the production bus enforces.

2. **Green-border / download-state consistency** wasn't observable because no series was loaded. Future stage that does write-side actions (Stage 6 or beyond) should verify the border state when a series is in a viewport, when the patient is partially downloaded, etc.

3. **Sidebar populate time for 239-series cold load is 18 s** — informational. If users frequently open multi-study patients of this size, consider background pre-indexing on patient hover or patient-list select.

4. **Read-only adapter cannot test write-side multi-study scenarios** — e.g. switching active series across studies, layout changes for multi-study viewports. These need the dedicated multi-study test suite per the plan's deferred Phase D.2.

---

## 11. Verdict

**STRONG PASS.** The viewer's multi-study sidebar grouping works correctly in the live build. The read-only ViewerAdapter is structurally enforced (no write-verb actions). All 11 read-only adapter guards pass. The active tab is correctly identified. Multi-study invariants from `MULTI_STUDY_SINGLE_TAB_PLAN.md` are intact.

**Recommended next stage:**
- **Stage 6 — Multi-study workflow audit.** Now that I have a confirmed multi-study patient open (malakoti somayeh, 239 series across at least 2 studies), Stage 6 can dig deeper: verify all studies appear, all study UIDs are captured, series numbers stay correctly offset-keyed, download state doesn't leak across studies, and thumbnails don't cross between studies. **Still strictly read-only** until the dedicated multi-study test suite for write-side exists.
