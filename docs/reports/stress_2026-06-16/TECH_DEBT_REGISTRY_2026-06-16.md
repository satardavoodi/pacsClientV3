# AI-PACS — Tech-Debt / Suspected-Issues Registry (2026-06-16)

Two parts: **Part A** = issues found by *direct live evidence* this session. **Part B** = issues surfaced by auditing the project's own docs + regression-guard notes (status is doc-derived and should be **re-verified against current code** before any change — several may already be fixed). Nothing in Part B was modified.

Guiding rule honored: no clinically-verified geometry / slice order / orientation / rendering was changed. Suspicious-but-physician-verified areas are recorded here, not edited.

---

## Part A — Found by live evidence this session

### A1 — Report-status poll holds the shared socket lock ~30 s  ✅ FIXED
- **Where:** `modules/network/socket_report_status_service.py::get_report_status` → shared `PatientListSocketClient` via `_get_client()`; lock at `modules/network/socket_client.py:165`; 30 s timeout `socket_config.py:50`. Callers: `_hp_download.py:288` (loops per study UID), `patient_table_widget.py:3781`.
- **Observation:** server never answers `GetReportStatus`; each call holds the GUI-shared client's `RLock` until the 30 s timeout → GUI-thread patient/thumbnail calls block → 1.3–1.7 s main-thread stalls + 36 timeouts/114 ERRORs per day. Multi-study patients loop it (20× for Patient 1).
- **Risk:** HIGH (GUI responsiveness + log noise; worst on multi-study).
- **Resolution:** circuit breaker (this session). Test `tests/code/network/test_report_status_circuit_breaker.py`. **Activate live by restarting the app.**
- **Related case:** Patient 1 (20 studies); any server-study open cluster.

### A2 — Disk > DB instance index drift  ⛔ OPEN (registry — not a blind fix)
- **Where:** downloader instance-insert path (`modules/download_manager/.../series_downloader*` + `database/dicom_db.py` `batch_insert_instances`).
- **Observation:** downloaded `.dcm` files exist on disk that have no `instances` row — 4/54 sampled studies (pt 43977: disk 2418 vs DB 2414; another +19; +2; +4). Direction is safe (no missing images; viewer reads disk) but DB undercount can make a complete study look incomplete and feed completion/"downloaded N/M" logic incorrectly.
- **Risk:** MED. **Defer reason:** touches the downloader DB-write/index path under DB-lock retry — not "isolated/clearly-safe"; needs a dedicated fix + reconciliation test and a backfill decision.
- **Related case:** pt 43977 (`…8618…`), and 3 other sampled studies; relates to the known downloader write-gap (slice_thickness/spacing NULLs, 12% zero-instance series).

### A3 — Main-thread stalls during background (non-interactive) work  ⛔ PARTIALLY OPEN
- **Where:** broad; instrumented by `main.py:942–1051` watchdog. Contributors include A1 (lock contention), thumbnail/render, possibly GC.
- **Observation:** 1688 stalls, p95 1.5 s, p99 ~10 s, 100 >1 s; 96 % `interaction_active=False`; `stall_correlation_report.py` attributes 1437 as `UNKNOWN_REMAINING` (no nearby instrumented event).
- **Risk:** HIGH in aggregate. **Defer reason:** A1 removes one major contributor; the rest need finer instrumentation (the correlation buckets are mostly empty) before safe targeted fixes. Recommend adding event markers around the suspected background tasks so the existing `stall_correlation_report.py` can attribute them.
- **Related:** re-measure after A1 ships (restart) to quantify A1's share.

### A4 — Extreme stall outliers (10–95 s)  📝 DOCUMENTED (not an interactive freeze)
- **Observation:** ~32 stalls ≥ 8 s, up to 95.8 s, all `interaction=False`, `nearest=none`. Pattern matches shutdown/teardown or OS suspension (laptop sleep / process suspend), not user-facing freezes. The native_fault `0x8001010d` hits are the known benign shutdown-teardown signature.
- **Action:** none beyond awareness; exclude from interactive-responsiveness KPIs (tag teardown explicitly if cheap).

---

## Part B — Doc-audited latent / known-open items (verify against current code first)

> Severity and "status" below are derived from `docs/` + CLAUDE.md regression guards. Many guards exist *because* the area is fragile; some entries may already be resolved. Re-check before acting.

| ID | Area (file/function) | Observation / failure mode | Sev | Status (doc-derived) | Family |
|----|----------------------|----------------------------|-----|----------------------|--------|
| B1 | Open path / disk header scan (`_vc_load.py`, `image_io.load_single_series_by_number` `headers_only_build`) | **H1**: FAST viewer re-reads all N DICOM headers off disk (~0.8–1.4 s) for metadata the downloader already wrote to `dicom.db`; cold-open p90 ~8 s on large server studies → looks like a freeze | HIGH | known-open (DB-completeness blocked; see memory `h1_header_rescan_dependencies`) | high-slice, download |
| B2 | DM preemption (`series_intent_coordinator`) | **DM-H3**: a study in `VALIDATING` holds the single download slot; a CRITICAL drag-to-load can wait out the ~30–60 s handoff | MED | known-open (test `test_dm_preempt_on_drag`) | download, drag-drop |
| B3 | Socket recv (`download_manager/network/socket_client.py::_safe_recv`) | **DM-H1**: timeout == EOF == reset all return `b""` → transient stall triggers full reconnect instead of cheap retry | MED | known-open | download |
| B4 | Cross-patient persist (`_hp_patient_open.py` STEP 3.5, `_hp_series.py`, `_hp_modules.py`) | fresh (not-yet-downloaded) study with unknown local owner can persist under wrong patient before server `patient_id` re-check | HIGH | guarded 2026-06-02 but safety-net hole noted | multi-study, isolation |
| B5 | Multi-study enumeration (`_resolve_patient_study_uids_async`, `_enumerate_studies_for_row`) | server returns only latest study UID per patient; non-latest-modality studies invisible unless per-modality enumeration runs | HIGH | guarded 2026-06-02; fragile | multi-study |
| B6 | Right-panel cache gate (`_hp_search.py`, `_hp_series.py` `_thumbs_server_refreshed_uids`) | must key on `uid@server_series`; bare-UID keying mis-attributes aggregate counts → false cache hit, stale thumbnails | MED | latent invariant (thumbnail-pipeline §8) | multi-study, thumbnails |
| B7 | MPR widget lifecycle (`modules/mpr/…`, VTK widget) | no explicit test/monitor for MPR VTK cleanup on patient close → potential memory growth over many MPR opens | MED | latent (untested) | MPR |
| B8 | Duplicate DM enqueue (coordinator/models dedup) | 5 dedup layers rely on in-memory `_tasks` sync; rapid double-click before first task spawns is untested under concurrency | LOW | latent | download |
| B9 | Thumbnail path authority (`THUMBNAIL_PATH` vs legacy `BASE_PATH/thumbnails`) | dual canonical paths; a consumer using the wrong root misses cache → slow DICOM re-decode on main thread | MED | latent (print path fixed; confusion remains) | thumbnails |
| B10 | Theme re-apply (`main.py` `_apply_application_theme` in `themeChanged`) | synchronous full-app `setStyleSheet` inside signal emit → UI hitch on theme change | MED | doc says a guard test was failing — **verify** | GUI responsiveness |
| B11 | Single-click debounce (`patient_table_widget.py` `click_timer`) | debounce must be ≥ `doubleClickInterval` (≥250 ms) or slow double-clicks break the open | MED | guarded; fragile invariant | GUI responsiveness |
| B12 | Slice-order geometry (`display_geometry.apply_k_flip_for_stack_order`) | docstring vs test disagree on 1-based→0-based; **live CT renders correctly** | LOW | SUSPECT — do **not** change without author intent + real-series check | viewer (clinical) |

### KPI thresholds already defined in code/docs (reuse for gating)
stall threshold 100 ms (`AIPACS_STALL_THRESHOLD_MS`) · stall stack-trace 400 ms · socket timeout 30 s (`socket_config.py:50`) · download batch soft-cap 64 MB · resync TTL 300 s · single-click debounce ≥250 ms · right-panel cache poll 150 ms→700 ms · thumbnail LRU 300 entries/50 MB · stack-drag render p95 target 27–65 ms, event p95 target ≤16 ms.

---

## Recommended next actions (priority order)
1. **Restart the app** to activate A1; re-run `stall_correlation_report.py` to quantify A1's share of the stalls.
2. Fix **A2** (disk>DB drift) with a reconciliation pass + test (deliberate, not blind).
3. Add instrumentation markers so **A3** stalls become attributable, then target the largest bucket.
4. Verify **B10** (theme hitch test) and **B1/B5** completeness against current code before scheduling.
5. Run the **live runbook** for drag/scroll/MPR/mammography/X-ray once idle (no concurrent build).


---

## Part A (cont.) — Found during live session (post-restart)

### A5 — Home patient-list layout: dark panel overlaps the table  ⛔ OPEN (UI/usability)
- **Where:** home-page workstation UI (`PacsClient/pacs/workstation_ui/home_ui/` — patient table + filter panel + the "Adaptive to Screen Size" control).
- **Observation:** live on monitor A (DELL S2421HN), the home page rendered with a large dark (empty study-preview) panel overlapping the center of the patient-list table; the left filter column was clipped — the Local/Server toggle and Patient ID/Name fields were only partly visible, and search defaulted to **server** mode. `Escape` and toggling "Adaptive to Screen Size" did not clear it. The patient list was readable only as a thin strip + the bottom rows.
- **Failure mode (impatient user):** hard to read the result list / select a specific patient; effectively blocks reaching a known local patient by ID. Not a crash — search and open still worked when a visible row was double-clicked.
- **Risk:** MED. **Defer reason:** layout/responsive issue needing a UI review at this resolution/DPI/window state; verify whether it reproduces maximized vs restored and at other resolutions before editing — not a clearly-safe blind change.
- **Related:** observed 2026-06-16 ~10:21–10:28 live; blocked live runbook S1/S2/S7 (multi-study Patient 1, CT 562346, MPR) this session.

> **Live F1 confirmation:** after restart the breaker is loaded; a real `GetReportStatus: Invalid response length header` occurred (server gap ongoing) with the breaker correctly dormant at 1 failure. Open + drag-drop load + scroll burst produced no freeze (2 stalls >1 s since restart, one = 3.96 s startup; p50 160 ms).


### A6 — Heavy multi-study open → multi-second main-thread freeze  ⛔ OPEN (reproduced live)
- **Where:** open path / first-series load — `PacsClient/pacs/patient_tab/utils/image_io` `headers_only_build` + multi-study grouped render (`_vc_load.py`/`_vc_switch.py`). Same root as **B1 / H1**.
- **Observation (live, 2026-06-16 10:58):** opening **Patient 1 (ID 1, 30 studies — 27 MR + 2 OTHER + 1 CT)** produced a single **9.4 s main-thread stall** and **~8.8 s** from `open_hot_path_complete` (10:58:17.075) → `first_series_visible` (10:58:25.921). The hot path itself was ~3 ms; the freeze is in the first-series header-scan/decode/render. No crash; the patient tab opened. Server **answered** report-status for all 30 studies, so F1/A1 is **not** the cause here.
- **Failure mode (impatient user):** ~8–9 s apparent freeze when opening a heavy multi-study patient; user may click again / assume a hang.
- **Risk:** HIGH (responsiveness). **Defer reason:** this is H1 (FAST viewer re-reads DICOM headers off disk for metadata the downloader already wrote to `dicom.db`) plus multi-study enumeration cost — a **staged** effort gated on DB-metadata completeness (see memory `h1_header_rescan_dependencies`, `architecture_review_2026-06-08`). Not a clearly-safe blind edit; needs the DB-metadata load path + golden-compare. **Highest-value perf item after A1.**
- **Related:** B1; reproduced on Patient 1; re-measure first-series-visible after the H1 Phase-0 DB write-gap fix.


### A7 — Viewer series-thumbnail panel empty for multi-study + mammography  ⛔ OPEN (functional, confirm at normal resolution)
- **Where:** viewer left "Series Thumbnails" panel — multi-study grouped sidebar (`_render_multistudy_grouped`, `_vc_load.py`) and/or MG series-thumbnail rendering in the patient-tab thumbnail panel.
- **Observation (live, 2026-06-16):** the viewer's left series-thumbnail panel rendered **no thumbnails** for (a) **multi-study Patient 1** (ID 1, 30 studies / **239 series**) and (b) **mammography 42552** (5 MG series). It rendered **correctly** for single-study **US** (Heydari), **CT** (562346, 5 thumbs), and **DX** (44876, 4 thumbs) — same monitor, same session. With an empty panel the user can't select/drag a series → stuck at "Drop a series here" (no images load).
- **Important corroboration:** the **home-page right panel DID show Patient 1's series thumbnails** (Series 0–3, "239 series") — so the thumbnails/data exist on disk; the gap is the **viewer sidebar population**, not missing data.
- **Failure mode:** can't open images for a heavy multi-study patient or a mammography study from the viewer thumbnail panel.
- **Risk:** HIGH (functional) — **caveat:** observed on monitor A under the A5 cramped layout; **confirm at a normal/maximized resolution** and identify whether it's the multi-study grouped render (239 series), the MG thumbnail path, or layout-clipping before fixing. Not a blind edit; relates to the CLAUDE.md multi-study `_render_multistudy_grouped` invariant.
- **Related:** A5, A6; reproduced on Patient 1 + 42552. **Recommended:** re-test maximized + check `THUMBNAIL_PATH/<study_uid>/<series_number>.png` existence for these series.
