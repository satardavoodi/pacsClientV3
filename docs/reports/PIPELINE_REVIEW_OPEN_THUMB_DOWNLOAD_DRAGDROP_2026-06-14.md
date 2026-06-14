# Pipeline review — patient open / thumbnails / download / sync / drag-and-drop (2026-06-14)

Scope: review the full workflow after the two recent changes (manual drag-and-drop
"always replaces the viewport" via `force_reload`, and server resync-on-reopen for
newly-added series). Confirm the pipeline is clean, find redundant/conflicting logic,
add logging at the gap stages, and provide a manual QA checklist. Per the agreed scope
this pass makes **only low-risk logging additions**; larger simplifications are written
up as proposals (not applied).

Verdict: the pipeline is **sound and already heavily instrumented**. Drag-and-drop now
has a single consistent rule and no remaining no-op can swallow a drop. The main genuine
findings are (1) a partially-downloaded series can re-download in full (instance-level
resume filter not on the hot path), (2) thumbnails don't auto-refresh in the UI the
moment a background download completes, and (3) two independent per-modality enumeration
paths. None are regressions from the recent changes; all are pre-existing and flagged
below as proposals.

---

## 1. As-built flow (the 10-step workflow)

### 1.1 Single-click a not-yet-downloaded patient → thumbnail preview
`patient_table_widget._on_patient_clicked` debounces behind `QApplication.doubleClickInterval()`
(`click_timer`) → on timeout emits `patientClicked` + `thumbnailRequested` →
`_hp_series._on_patient_single_clicked` (logs `click_single_entry`) →
`_load_and_display_series_info` → `_reconcile_patient_studies_on_click` (per-modality
enumeration for multi-modality patients) and a **fire-and-forget** resync →
`_hp_search.show_patient_studies` **cache gate** (`_hp_search.py:~1410`,
`right_panel_cache_gate grew= local_thumbs= server_series=`).

- Cache hit (no growth + local thumbs present) → render local PNGs, **no server call**
  (`right_panel_cache_hit`).
- Cache miss / grew → `right_panel_socket_start` → `GetStudyThumbnails` →
  `right_panel_display_done`.
- **No full image download is triggered on single-click** — thumbnails only. ✔ matches spec.

### 1.2 Double-click → open + download
`_hp_patient_open._on_patient_double_clicked_async` (`_hp_patient_open.py:546`): cancels the
pending single-click, resolves all study UIDs via `_resolve_patient_study_uids_async`
(adds `_enumerate_studies_for_row` per-modality discovery, logs
`study_enumerated_by_modality`), creates the tab immediately (`tab_created`), then **STEP
3.5** fetches per-study series info (`force_refresh=True`), applies the cross-patient owner
guard (`download_queue_cross_patient_skip`), and enqueues each study with
`download_manager.start_priority_download_immediately(... priority="High")`
(`[FAST-SERIES-DOWNLOAD-QUEUE]`, `download_manager_wired`). Non-critical UI work
(right-panel, series-info, attachments) is deferred until first image is visible
(`ui_tasks_deferred` → replayed by `_on_first_series_loaded`). ✔ UI stays responsive.

### 1.3 Server sync / newly-added series
Three complementary mechanisms:

| Mechanism | Where | Trigger | Detects | Guard |
|---|---|---|---|---|
| Right-panel **cache gate** | `_hp_search.py` `show_patient_studies` | single-click | study **thumbnail/series count** grew vs local | single-study only (`_server_series_count_by_study`, `total_studies<=1`) |
| Per-modality **enumeration** | `_hp_patient_open._enumerate_studies_for_row` | open / reconcile | **new studies** of other modalities | only when `len(modalities)>1` |
| **Resync-on-reopen** | `_hp_series._resync_patient_studies_from_server` (cd7162e) | reselect / right-click "Refresh" | **new/grown series within a study** | per-study series numbers (44534-safe), 5-min TTL, cross-patient owner check |

Resync compares each study's **own** `series_number → image_count` map
(`_detect_study_growth`), enqueues via `dm.add_downloads(..., start_immediately=True)`
(resume scan dedups), and reveals with `_show_grouped_patient_studies(force_server_merge=True)`.
Env gate `AIPACS_RESYNC_ON_REOPEN`; manual path `force=True` ignores throttle+gate. ✔

### 1.4 Drag-and-drop → viewport replace
Two **separate** drop handlers: `_vw_dragdrop.dropEvent` (Advanced VTK) and
`qt_fast_container.dropEvent` (FAST). Both defer via `QTimer.singleShot(0, …)` and call
`method_change_series_on_viewer(..., force_reload=True)` →
`_pw_series.change_series_on_viewer` (forwards `force_reload`) →
`_vc_switch.change_series_on_viewer` → `_perform_series_switch_optimized` →
`switch_series` on the FAST/VTK widget → `_vc_load` load.

`force_reload=True` bypasses **every** same-series no-op in the chain:

| No-op gate | File:approx | Bypassed by force_reload? |
|---|---|---|
| dispatcher same-series | `_vc_switch.py:~257` | ✔ |
| FAST container same-series | `qt_fast_container.py:~582` | ✔ |
| VTK same-series identity | `_vw_series.py:~882` | ✔ |
| load "already visible" | `_vc_load.py:~414` | ✔ |
| full-series cache bypass | `_vc_load.py:~439` | ✔ |
| existing-series load skip | `_vc_load.py:~471` | ✔ |

No remaining gate can swallow a manual drop. ✔ This is the consistent rule the spec asked
for; it is implemented by a flag, **not** by weakening the identity checks (automatic /
cache / progressive callers keep the cheap no-op). Drop of A→empty, B→occupied (replaces),
A→same pane (reloads), same currently-loaded series (reloads), and series already open
elsewhere (loads into target too) are all satisfied by the single rule.

### 1.5 Resource lifecycle on replace
`_vw_series.cleanup_image_viewer` removes the old renderer
(`render_window.RemoveRenderer`), calls `image_viewer.cleanup()`, drops the reference, and
releases the bound lazy loader (`_release_bound_lazy_loader`); the FAST path goes through
`QtViewerBridge.cleanup()`. **Race handling:** each request gets an `expected_token`
(`_next_request_token` / `_is_request_current`); a stale (superseded) load is discarded at
apply time, and `_viewer_switch_inflight` + `_series_load_lock`/`_loading_series_numbers`
serialize concurrent loads (a main-thread drop returns and retries rather than blocking).
Last drop wins. Pixel-buffer and VTK-observer teardown are delegated to the viewer/bridge
`cleanup()` (not in the switch layer).

### 1.6 Download manager + thumbnails
Dedup is solid: `StateStore.get(study_uid)` + on-disk completeness
(`resume_rules.check_series_complete`, `_is_study_complete_on_disk`) — an already-complete
study is marked `COMPLETED` and returns success without re-download; instance writes are
atomic (`*.part` → `os.replace`). Downloads run in `DownloadWorker(QThread)` / subprocess;
thumbnails persist to `THUMBNAIL_PATH/<study_uid>/<series_number>.png`, populate
`ThumbnailStore`, and decode on the GUI thread (`make_pixmap_from_bytes`); a placeholder
pixmap exists for misses. ✔ No network/decode on the GUI thread observed.

---

## 2. Logging added in this pass (low-risk)

All additions are one-liners that change no control flow:

- **Drag-drop replacement decision** — `qt_fast_container._do_switch` and
  `_vw_dragdrop._do_series_switch` now log `[QtFastContainer DROP] apply …` /
  `[DROP] apply — series=… target_viewer=… force_reload=1` *before* the switch (previously
  only the failure path logged). This brackets every drop: `apply …` then either the
  switch-complete logs or the existing `… FAILED` line.
- **Series unload lifecycle** — `_vw_series.cleanup_image_viewer` now logs
  `[SERIES UNLOAD] viewer=… backend=… qt_active=… had_image_viewer=… preserve_backend=…`
  so the old series teardown is visible alongside the existing `[SERIES SWITCH] COMPLETE`
  bind log.
- **Server sync bracket** — `_hp_series._resync_patient_studies_from_server` now logs
  `resync_start` (study_count, forced) and `resync_complete` (changed, rerendered) around
  the existing per-study `study_resync_check`.

Existing markers already cover the rest: `click_single_entry`, `right_panel_cache_gate` /
`right_panel_cache_hit` / `right_panel_socket_*`, `study_enumerated_by_modality`,
`[FAST-SERIES-DOWNLOAD-QUEUE]`, `study_resync_check`, `FAST:thumbnail_pipeline` /
`[FAST-THUMB-STATE]`, `[SERIES SWITCH] COMPLETE`, `[NET_TIMING]`, `[SPAWN-TIMING]`.

Verification: 4 files compile; `tests/code/viewer/test_viewport_drop_replacement.py` +
`tests/code/ui_services/test_resync_on_reopen.py` = 30 passed.

---

## 3. Findings — redundant / conflicting logic (not changed)

1. **Two per-modality enumeration paths.** Single-click (`_reconcile_patient_studies_on_click`)
   and double-click (`_resolve_patient_study_uids_async`) each enumerate studies
   independently with no shared result/cache. Harmless (both verify patient ownership) but
   duplicated work on a patient that is clicked then opened.
2. **Sync asymmetry.** Single-click is gated (cache gate decides whether to hit the server);
   double-click STEP 3.5 always `force_refresh=True` per study (no gate). Reasonable (open is
   a stronger intent), but it means "open" never consults the cheap gate.
3. **Multiple stale-response guards** (`_active_thumb_*`, `_is_active_patient_selection`,
   `_opening_studies`, per-request `expected_token`). Each guards a real race; together they
   are correct but spread across files — a single source of "current selection/token" would
   be easier to reason about.
4. **Layered same-series no-ops (6).** Defensive and all now uniformly `force_reload`-aware,
   but four of them re-check series identity at different stages with slightly different
   conditions. Consolidation is possible but risky (see proposals).

None of these conflict with the new drag-and-drop rule; the `force_reload` flag already
isolates the manual path from every duplicate-skip check.

---

## 4. Proposals (NOT implemented — need approval / verification)

- **P1 — Instance-level resume for partial series (download).** Review indicates
  `resume_rules.filter_existing_files` (instance-level "download only missing") is **not on
  the partial-series hot path**: a series that is partially present can be re-fetched in
  full (series-level `check_series_complete` is all-or-nothing). Fix = filter the instance
  list to missing-only before `download_series`. *Risk:* download_manager is a guarded
  subsystem (ZETA review doc); verify against `tests/code/download_manager` and the resume
  contract first. Highest-value optimization here.
- **P2 — Thumbnail auto-refresh on download completion.** When a background series download
  finishes, there is no completion→UI signal, so a sidebar thumbnail can stay in the
  "downloading" state until the next sync/reopen. Fix = emit a thumbnail-ready signal from
  the worker completion to `ThumbnailManager` for the affected `study_uid/series`.
- **P3 — Unify the two enumeration paths** (Finding 1) behind one cached resolver shared by
  single- and double-click.
- **P4 — Placeholder-on-failure log.** Add a debug log where `ThumbnailImageSourceService`
  returns a null/placeholder pixmap so thumbnail-fetch misses are traceable (kept out of
  this pass to avoid per-thumbnail log noise during normal initial load).

Recommend P1 then P2 as separate, test-gated changes.

---

## 5. Manual QA checklist (run on the SOURCE build)

Pick a **multi-study, not-yet-downloaded** patient (ideally MR + a DOC/attachment study).
Tail `user_data/logs/download_diagnostics.log` + `viewer_diagnostics.log` while testing.

Open / thumbnails / sync:
- [ ] Single-click a non-downloaded patient → thumbnails/preview appear; UI does not freeze.
      Log: `click_single_entry` → `right_panel_cache_gate` → `right_panel_socket_done` (or
      `right_panel_cache_hit`). No download queued on single-click.
- [ ] Double-click → tab opens immediately; download starts. Log: `tab_created`,
      `[FAST-SERIES-DOWNLOAD-QUEUE]`, `download_manager_wired`; UI stays responsive.
- [ ] Newly-added server series are detected on reselect / right-click "Refresh from
      server". Log: `resync_start` → `study_resync_check result=grew new_series=…` →
      `resync_complete changed=1`; the new series appears (grouped merge).
- [ ] Series list + thumbnails reflect latest local+server state after sync; missing
      thumbnails fill in.
- [ ] No duplicate downloads (resume scan skips complete series); no duplicate series rows.

Drag-and-drop (watch for `[DROP] apply …` / `[QtFastContainer DROP] apply …` then
`[SERIES UNLOAD] …` then `[SERIES SWITCH] COMPLETE …`):
- [ ] Drag series A into an empty viewport → A loads.
- [ ] Drag series B into that viewport → B replaces A (A unloaded; `[SERIES UNLOAD]`).
- [ ] Drag series A again into the same viewport → A reloads cleanly.
- [ ] Drag the **same currently-loaded** series onto its own pane → it reloads (not a no-op).
- [ ] Drag a series already open in another viewport into a new pane → it loads there too.
- [ ] Repeat drops quickly 8–10× across panes → no freeze/crash; last drop wins; no stale
      image left in any pane.

Resilience:
- [ ] Thumbnail fetch failure → placeholder shown, reason logged; app does not freeze.
- [ ] Sync failure → existing local data still usable; no crash.
- [ ] Series load failure → viewport stays in a safe empty state (FAST spinner hidden);
      log `… FAILED …`.

Note: the other clinic PC runs the **frozen installed build** — it needs a rebuilt
installer to pick up these logging changes and the earlier drag-drop fix.

---

## 6. Deeper validation — KPIs, conflicts, test baseline (2026-06-14)

### 6.1 Test baseline (proves the changes are isolated)
Ran `tests/code/viewer + download_manager + system + ui_services`. Result with the changes:
**73 failed, 1731 passed, 20 skipped**. To prove the 73 are not mine, the 4 logging-only
files were reverted to their pre-change state and the viewer+DM suites re-run: **73 failed,
1459 passed** — the **identical 73-failure set** (the extra passes at HEAD are only because
the HEAD run also included system+ui_services). So **the logging additions introduce zero
new failures.** Targeted suites for the changed surface stay green:
`test_viewport_drop_replacement.py` + `test_resync_on_reopen.py` = **30 passed**.

The 73 failures are **pre-existing**, from other in-flight work, not this pipeline:
geometry `[R30_FIX] matrix[2,3]=-1.0` (`test_display_geometry`), B34/B35 prefetch &
deferred-header-fill, FAST backend stage1/2 migration, theme retint (`test_dm_theme_retint`
asserts a `main.py` string), and the AST-resolver false-positive in
`test_vtk_widget_split::test_mixin_method_names_resolve` (fails identically for
`_vw_backend` / `_vw_interactor`, which this work never touched). **Recommend addressing the
viewer-suite red backlog separately — it is unrelated to open/thumbnail/download/drag-drop.**

### 6.2 KPIs (from real session logs)
| KPI (log marker) | n | p50 | p95 | max | read |
|---|---|---|---|---|---|
| `GetStudyThumbnails` total_ms (`NET_TIMING`) | 778 | 45 | 105 | 241 | thumbnails are cheap ✔ |
| `GetPatientList` total_ms (`NET_TIMING`) | 496 | 349 | 2642 | 29583 | slow tail, but **off-thread** ⚠ |
| FAST `headers_only_build` ms | 509 | 60 | 249 | 6761 | dominant load cost (server studies) |
| `MAIN_THREAD_STALL` duration ms | 5528 | 153 | 1396 | 122194 | tagged cause: table_refresh 562 > viewer_switch 222 > fast_drag 45 |
| right-panel `cache_gate` | 1565 | — | — | — | **grew=0 (cache hit) 1191 / grew=1 (fetch) 374 → ~76% no server call** ✔ |
| `study_resync_check` | 18 | — | — | — | grew 8 / current 10 → fires modestly, not hammering ✔ |

Reads: single-click thumbnail preview is fast and mostly served from local cache (76% hits);
`GetPatientList`'s slow tail (used by per-modality enumeration) is the main server-side cost
but runs off the GUI thread; the dominant main-thread stalls are **home table refresh**, not
the viewer drop path; resync fires modestly.

### 6.3 Cross-subsystem conflict analysis (no conflicts found)
- **force_reload × cache / progressive / ZetaBoost:** `force_reload` defaults **False**
  everywhere, so automatic / click / scroll / progressive / cache loads are byte-identical
  and keep the cheap no-op. It only invalidates the full-series cache on a **manual drop**.
  Cost of a forced re-drop of the same large series ≈ one `headers_only_build`
  (p50 60 ms / p95 249 ms) — acceptable for a user-initiated action; not a hot loop.
- **force_reload × multi-study isolation:** force_reload gates only the *same-series no-ops*;
  it does **not** touch the cross-patient owner guards (STEP 3.5 / reconcile / resync). No
  isolation bypass.
- **force_reload × token race:** the drop still allocates `expected_token` and honors
  `_is_request_current`; force_reload does not bypass the race guard, so **last drop wins**
  on fast repeated drops (covered by the 16 drop tests).
- **resync × consultation poller / GUI thread:** resync does all server I/O via
  `asyncio.to_thread` with a 45 s timeout — **no network on the GUI thread** (honors the
  poller-stall rule). Throttled 5 min/study so rapid reselect can't hammer the server.
- **resync × download-manager dedup:** resync enqueues via `add_downloads(start_immediately
  =True)`; the DM StateStore + on-disk resume scan dedup means a study already
  downloading/complete is **not** re-fetched, even though STEP 3.5 may also enqueue it.
  No duplicate downloads / no duplicate series rows.
- **logging cost:** `[SERIES UNLOAD]` fires once per series switch (same cadence as the
  existing `[SERIES SWITCH] COMPLETE`); `[DROP] apply` once per user drop; resync bracket
  once per (throttled) resync. None are per-frame/per-slice/per-batch. Negligible.

### 6.4 Reliability verdict
The open / thumbnail / download / sync / drag-drop pipeline is **stable and internally
consistent**; the two recent changes are correctly isolated behind a default-False flag and a
throttled, off-thread, owner-guarded resync, with no detected conflict against caching,
progressive loading, multi-study isolation, the race guard, the download manager, or the
consultation poller. Residual items are the pre-existing **viewer test backlog** (§6.1, other
teams' work) and proposals **P1/P2** (§4). One thing the headless tests cannot cover — a real
Qt drag on a fast LAN — still wants the manual QA pass in §5 on the source build.
