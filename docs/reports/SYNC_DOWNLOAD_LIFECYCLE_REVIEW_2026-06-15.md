# AI-PACS — Client/Server Sync + Download Lifecycle Architecture Review (2026-06-15)

Scope: the complete study **download → sync → open → preview → display** pipeline, treated as one
synchronization system. This is an architecture review, not a single bug fix. It maps the current
lifecycle, names the problems, records what was implemented now, and stages the larger structural work
behind explicit approval (rewriting a clinical sync pipeline in one pass would violate the project's
safety rules).

> **As-built (current state):** the consolidated, straightforward "how it works now +
> every flag + every issue handled" reference is
> `docs/pipelines/SYNC_DOWNLOAD_OPEN_PIPELINE_AS_BUILT.md`. This review remains the
> background + the phased plan. S1, download_only_missing, FIX-009/010/011/012/013/014
> and the disk-aware resync are **implemented**; S3 and S5 are staged enhancements.

Method: read-only code mapping (two subsystem audits), grounded in the existing as-built records
(`docs/pipelines/thumbnail-pipeline.md`, the Zeta download-manager review, the resync/45611 and
44113/44323 reports, the multi-study + cross-patient reports) and the live logs analysed this session
(patient 46370 slow open; pc2 crash set). Exact `file:line` anchors are given so each claim is checkable.

---

## 0. Executive summary

The pipeline is **more mature than a greenfield review would assume** — it already implements most of the
standard client/server patterns the brief asks for:

- **Disk is the source of truth** for "downloaded" status (`check_study_complete` /
  `get_study_download_status` count `.dcm` folders, not a DB flag).
- **Server-as-truth resync on reopen** exists, is **on by default**, **off-thread**, **throttled** (5-min
  TTL), detects new/grown series, and enqueues **only missing** series.
- **Download-only-missing** via a disk-count resume scan that excludes `.part` files.
- **Idempotent, atomic writes**: every `.dcm`/`.png` is written `*.part` then `os.replace()`.
- **5-layer task de-duplication** prevents duplicate study/series downloads and reuses the in-flight task
  when a downloading study is reopened.
- **Non-blocking open**: the tab is created immediately; downloads, server info, attachments, and resync
  all run off the UI thread.
- **Cross-patient isolation** + **multi-study completeness** guards on the persist/display paths.
- **Render coalescing** anti-flicker on the right panel.

The real gaps are narrower and specific (see §4): there is **no single local "manifest"** (state is spread
across the DM state store + `dicom.db` + `download_progress.db` + disk + several memory caches, with no one
place that says "here is this study's complete local truth"); the series **load** still briefly **blocks
the main thread** (improved this session, not eliminated); **stale detection is manual** (a Settings
button) rather than automatic on open; a **full re-download is queued even when the study is already
complete**; and **drag-drop of a not-yet-local series** does not itself trigger the needed download.

Implemented this session (all output-preserving, all in this pipeline): **FIX-009** (adaptive disk header
read — the 46370 slow open), **FIX-003/004/005/006** (storage clear consistency + a DB/disk consistency
validator+repair + the green-badge refresh wiring). This review adds a **read-only local-manifest /
local-vs-server comparison model** (§5.1) as the foundation for the staged sync work in §5.2.

---

## 1. Current-state lifecycle map

### 1.1 States — desired model vs as-built

The brief's 8 states are **mostly implicit** today, split across two levels:

| Brief state | As-built representation | Where it lives |
|---|---|---|
| NotDownloaded | `get_study_download_status()` → `'not_downloaded'` (no disk folder / 0 series) | derived from **disk** + `studies.number_of_series` |
| ThumbnailOnly | not a distinct state — thumbnails cached under `THUMBNAIL_PATH/<uid>/<n>.png` independent of DICOM presence | **disk** (`THUMBNAILS_DIR`) + `ThumbnailStore` (memory) |
| Downloading | `DownloadStatus.DOWNLOADING` (DM task) | **memory** `DownloadStateStore._states`; mirrored to `download_progress.status` |
| PartiallyDownloaded | `get_study_download_status()` → `'partial'` (some but `< number_of_series` folders) | derived from **disk** + DB |
| Downloaded | `'complete'` / `check_study_complete()==True` (`folder_count >= number_of_series`) | derived from **disk** + DB |
| Stale | **no explicit state** — only detectable by `validate_storage_consistency()` (Settings button, FIX-005) | computed on demand |
| Syncing | `_study_resync_check` in flight; `_patient_study_sync_inflight` set | **memory** (transient) |
| Failed | `DownloadStatus.FAILED` (DM task) | **memory** state store; `download_progress.status` |

Plus a **visit status** orthogonal axis on the home table: `'opened'` / `'synced'` (name colour), persisted
via `update_visited_status` / `get_visit_status`.

Key point: the **download-task** state (`DownloadStatus` enum, `modules/download_manager/core/enums.py:35`)
is rich and explicit, but the **study-as-seen-on-the-home-page** state is a derived string computed from
disk+DB each time. There is no single study-level state object that unifies "downloaded?", "downloading?",
"stale?", "syncing?", "thumbnails present?".

### 1.2 Where each state is stored (storage matrix)

| Aspect | Memory | Database | Disk | UI model |
|---|---|---|---|---|
| Download task status | `DownloadStateStore._states[uid]` (`state/state_store.py:50`) | `download_progress.status` (`database/download_progress_db.py:45`) | — | DM table rows |
| Progress %, counts | `DownloadState.progress_percent/downloaded_count` | `download_progress.downloaded_count/total_instances` | implicit (file count) | DM progress bar |
| Expected series count | — | `studies.number_of_series` (`database/dicom_db.py:78`) | — | — |
| Per-series instance count | — | `series.image_count` (`dicom_db.py:99`) | `count .dcm in series folder` | — |
| Downloaded files (truth) | — | — | `SOURCE_PATH/<uid>/<series_number>/<n>.dcm` | — |
| Thumbnails | `ThumbnailStore` | `series.thumbnail_path` (hint only) | `THUMBNAIL_PATH/<uid>/<series_number>.png` | right panel / sidebar |
| Completion decision | `_download_status_cache` (table widget) | (inputs) | (inputs) | status cell colour |
| Resync recency | `_study_resync_check_ts[uid]` (TTL 300s) | — | — | — |
| Server series count (last seen) | `_server_series_count_by_study[uid]`, `_thumbs_server_refreshed_uids` (keyed `uid@count`) | — | — | — |

### 1.3 Component map (authoritative anchors)

- **Status (disk-first):** `PacsClient/pacs/patient_tab/utils/utils.py` — `check_study_complete()` :1409,
  `get_study_download_status()` :1453.
- **DM state machine:** `modules/download_manager/core/enums.py:35` (`DownloadStatus`),
  `core/models.py:100` (`DownloadTask`, series de-dup `__post_init__` :127), `state/state_store.py:50`.
- **De-dup layers:** queue existence `ui/widget/_dm_queue.py:61`; worker-pool guard
  `workers/worker_pool.py:87`; task series de-dup `core/models.py:127`; series resume skip
  `rules/resume_rules.py:186` (`check_series_complete`); in-flight reuse `ui/widget/_dm_workers.py:195`.
- **Atomic writes / resume:** `download/executor.py:458` (`.part`→`os.replace`),
  `rules/resume_rules.py:206` (counts only `.dcm`).
- **Single-click:** `home_ui/patient_table_widget.py` click debounce :866/:1742/:1905/:1933;
  `home_panel/_hp_series.py` `click_single_entry` :139, `series_info_entry` :651.
- **Double-click open:** `home_panel/_hp_patient_open.py` `_on_patient_double_clicked_async` :546 (phases
  :567 open_request → :725 tab_created → :754 waiting_for_first_series_signal → download wiring :758-922 →
  resync :680).
- **Resync / server check:** `home_panel/_hp_series.py` `_resync_patient_studies_from_server` :276,
  `_detect_study_growth` :240, `_local_series_counts` :257, gate flag :41 (`AIPACS_RESYNC_ON_REOPEN`, default
  on), TTL :44 (300s).
- **Right-panel cache gate:** `home_panel/_hp_search.py` `show_patient_studies` :1301, gate :1389-1413
  (`right_panel_cache_gate`, key `uid@server_series`).
- **Drag-drop:** `patient_tab/ui/patient_ui/vtk_widget/_vw_dragdrop.py` `dropEvent` :198, `force_reload=True`
  :307; switch inflight guard `_vc_switch.py:237`.
- **Series load (disk):** `image_io.py` `load_single_series_by_number` :2476, `_build_metadata_headers_only`
  :1742 (now via adaptive `_read_header_stubs`, FIX-009); on-demand entry `_vc_load.py:271`.
- **Consistency validator (FIX-005):** `modules/storage/local_storage_cleanup_manager.py`
  `validate_storage_consistency` / `repair_storage_consistency`.
- **KPI logs:** `_hp_patient_open.py:54-87` (`_log_open_trace` → `FAST-OPEN-TRACE`), `FAST_LOAD_BREAKDOWN`
  (`image_io.py`), `NET_TIMING` / `VIEWER_SWITCH` / `PERF series_switch_breakdown` / `MAIN_THREAD_STALL`.

---

## 2. How the six core scenarios behave today

1. **Not-downloaded, single-click** — debounced (≥ `doubleClickInterval`), loads thumbnails only (server
   thumbnails via the right-panel cache gate); **no full download**. Responsive. ✔ matches intent.
2. **Not-downloaded, double-click** — tab created immediately; CRITICAL-priority download started; server
   series-info fetched off-thread; thumbnail stubs + progressive series appear; UI usable. ✔ matches intent.
3. **Currently downloading, reopen / switch / drag / return** — reopening reuses the in-flight worker/task
   (no duplicate); viewer-drag can preempt the single download slot for the dragged study; state is
   centralised in the DM state store. ✔ mostly matches; partial-series **drag** is the weak spot (§4.7).
4. **Already downloaded, reopen** — fast local render (disk), **plus** a throttled off-thread resync that
   compares local vs server counts and pulls only new series. ✔ matches — **except** it still **queues a
   full priority download of the complete study** (§4.4) and the local **load can block** (§4.2).
5. **Cleared locally** — disk is the truth so a cleared study computes as not-downloaded; FIX-003/004/005/006
   made the clear path consistent (files+DB+thumbnails+memory+UI) and added a validator+repair. ✔ — but the
   stale check is **manual** (Settings), not automatic on open (§4.6).
6. **New server-side content** — the resync detects new/grown series and enqueues only the missing ones; the
   right-panel gate refetches thumbnails once per new server count; de-dup prevents duplicate series. ✔
   matches — limited to *new series* and *grown series counts*; **per-instance** drift inside an
   unchanged-count series is not compared (§4.5).

---

## 3. Standard-pattern conformance scorecard

| Standard pattern | Status | Evidence / gap |
|---|---|---|
| Manifest-based sync | **Partial** | No single manifest; equivalent data is spread across DB+disk+memory (§4.1) |
| Server metadata = source of truth | **Yes** | resync compares server series-info; pulls missing |
| Local data = cache | **Yes** | disk-first status; DB `thumbnail_path` is "hint only" |
| Idempotent downloads | **Yes** | disk-count resume; `.part`→replace; series/file skip |
| Atomic state updates | **Partial** | file writes atomic; **DB+disk+memory not updated in one transaction** (§4.1) |
| Background refresh | **Yes** | resync off-thread, fire-and-forget, throttled |
| Avoid stale-cache trust | **Mostly** | disk-first; but no **on-open** file-existence validation (§4.6) |
| Avoid duplicate background work | **Yes** | 5-layer de-dup |
| Keep UI responsive | **Mostly** | open orchestration off-thread; **series load still blocks** (§4.2) |

---

## 4. Problems / gaps found

**P1 — No unified local manifest; state is fragmented (architectural).** Truth is split across the DM
state store (memory), `dicom.db` (studies/series/instances), `download_progress.db`, disk folders, the
thumbnail store, and ≥6 home-page memory caches. There is no single read-model that answers "what does this
study look like locally, and how does that compare to the server?" Consequences: the same comparison logic
is re-implemented in `check_study_complete`, `_detect_study_growth`, the right-panel gate, and
`validate_storage_consistency`; and updates are **not atomic across layers** (a clear or a download can
leave DB/disk/memory transiently disagreeing — the class FIX-003/004/006 patched for the clear path).

**P2 — Series load still blocks the UI thread (responsiveness).** Open *orchestration* is off-thread, but
the actual first-series **load** (`_build_metadata_headers_only` → render) runs synchronously on the main
thread. FIX-009 cut the slow-disk case from ~42s to ~9s (adaptive parallel header read), but a large series
on a slow disk can still block for seconds. Full fix = preview-first (show first slice after a few headers)
+ off-thread scan; preview-first currently **silently fails** (`load_series_preview`, 0 `[PREVIEW]` traces).

**P3 — `is_local=False` for fully-downloaded server studies (H1).** A study opened from a server search is
tagged `is_local=False source=server` even when all series are on disk, so it takes the server load branch
and re-reads headers instead of trusting local files. Root of P2's worst case (46370). The proper fix
(use downloader-written DB metadata) is gated on closing the downloader's slice-spacing write-gap (clinical
geometry) — deferred.

**P4 — Full re-download queued on an already-complete study (wasteful).** On double-click open, the open
path unconditionally starts a CRITICAL-priority download of the whole study
(`start_priority_download_immediately`) even when `check_study_complete()==True`. The DM resume scan then
finds every file present and downloads nothing — but it still spawns the worker/subprocess, writes a
`download_progress` row, and contends I/O at exactly the moment the viewer is reading the same files
(observed on 46370: `[FAST-SERIES-DOWNLOAD-QUEUE] series_count=62` on a complete study). It should
short-circuit to a metadata-only check when complete.

**P5 — Sync granularity stops at series count.** The resync compares **series numbers** and **per-series
image_count**; it does not compare **SOPInstanceUID lists** or detect a series whose server count is
unchanged but whose instances differ. For most PACS this is fine; it is a known boundary, not a silent bug.

**P6 — Stale detection is manual, not on-open (cache trust).** `validate_storage_consistency` (FIX-005)
detects "DB says downloaded but files gone" and "thumbnail points at a deleted file", but only when the user
clicks the Settings button. The brief wants an automatic lightweight file-existence check before showing
"downloaded" / on open. Disk-first status already avoids most stale trust, but a study whose folder exists
with **partial** leftover files after a botched clear can still read as `'partial'`/`'complete'` wrongly.

**P7 — Drag-drop does not trigger download for a not-yet-local series.** `dropEvent` always
`force_reload=True` and loads from disk; if the dropped series isn't fully local it renders what's present
(or fails) and does **not** attach to / start the needed download. Scenario 8 wants a partial/remote drop to
trigger the load path + attach to the existing task. (Duplicate-download is *not* a risk here — the de-dup
layers prevent it — but the *missing* download is.)

**P8 — No single "Syncing/Stale/Failed" surface in the home UI.** The user sees green/orange/gray + a name
colour, but "checking server", "syncing", "stale", "failed/retry" are not distinct, progressive UI states.

---

## 5. Improvements

### 5.1 Implemented now (safe, output-preserving)

- **FIX-009 — adaptive disk header read** (`image_io.py::_read_header_stubs`). Sequential on a fast SSD (no
  regression), thread-overlapped on a slow/I-O-bound disk (4.6× in a 30 ms/file sim, byte-identical). Turns
  46370's ~42s scan into ~9s. Gated `AIPACS_HEADER_SCAN_PARALLEL=auto`.
- **FIX-003/004/005/006 — clear-path consistency + consistency model** (this session). The clear path now
  updates files+DB+thumbnails(disk+memory)+status+UI together; `validate_storage_consistency()` /
  `repair_storage_consistency()` give a DB↔disk read-model + files-safe repair; the green badge refreshes
  from disk after a clear.
- **NEW — local-manifest / local-vs-server read-model** (`modules/storage/sync_manifest.py`, this review).
  A **read-only** consolidation that, for a study, builds the local manifest from DB+disk
  (series list, per-series DB `image_count` vs on-disk `.dcm` count, thumbnail presence, folder/file
  existence, disk-derived completeness) and, given a server series-info list, returns a **pure sync
  decision** — `missing_series`, `partial_series` (server_count > disk_count), `missing_thumbnails`, and an
  overall `state` in the brief's vocabulary (NotDownloaded/ThumbnailOnly/PartiallyDownloaded/Downloaded/
  Stale). It performs **no I/O writes and no downloads** — it is the single place the scattered comparisons
  can converge on, and the foundation for §5.2. Fully unit-tested; not yet wired into the live open path
  (that wiring is a staged step so it can't change clinical behaviour unreviewed).

### 5.2 Staged proposal (approval-gated — each phase flag-gated + golden-compared)

> Rationale for staging: every item below touches the clinical open/render or download-trigger path. Per
> the project rules (minimal safe edits, explain root cause before large modifications, never alter
> clinically-verified output) these ship one at a time, behind an env flag, with the legacy path as the
> default fallback until each is validated live.

- **S1 + S6(scenario-6) — Download ONLY what is missing (P4 + the 46640 "all of them start downloading"
  case). ✅ IMPLEMENTED (flag-gated, default on).** In the double-click open, after the existing fresh server
  series-info fetch, the open asks `sync_manifest.evaluate_sync(uid, server_series=<fresh server list>)` and:
  (a) if the server confirms **no missing and no partial series**, `start_priority_download_immediately` is
  **skipped** entirely (`download_skipped_complete`) — no subprocess, no I/O contention; (b) if **some**
  series are missing/partial, it **filters the download queue to ONLY those series** (`download_only_missing`)
  instead of queueing the whole study. So a study that grew on the server from 1→11 series now queues the
  **10 new** ones, not all 11 — the already-local series no longer appears to "re-download" (verified against
  46640's log: open logged `[FAST-SERIES-DOWNLOAD-QUEUE] series_count=11` for a 1-local/11-server study; now
  it queues 10). The DM resume still skips complete files as a second layer; any error/unreachable-server
  falls through to the full list; the background resync (which already enqueues only-missing) stays the
  safety net. Server-accurate (fresh list, not the stale local `number_of_series`). Flag
  `AIPACS_OPEN_SKIP_DOWNLOAD_WHEN_COMPLETE` (`0` = legacy always-download-full). Guard tests:
  `tests/code/storage/test_open_skip_download_when_complete.py`. **Live confirm: reopen a complete study →
  `download_skipped_complete`, no queue; open a grown study → `download_only_missing` with `missing=<new
  count>` and `[FAST-SERIES-DOWNLOAD-QUEUE] series_count=<new count>` (NOT the full count).**
- **S2 — Wire the manifest read-model into the open path as the completeness/stale gate (P1/P6).** Note: the
  **functional** stale requirement (scenario 5 — a cleared study must not show as downloaded and must
  re-sync on open) is **already met** by the disk-first status + FIX-004 (badge recompute) + the validator
  (FIX-005). S2 is therefore narrowed to (a) auto-repairing the lingering stale DB *row* on open (currently
  manual via the Settings validator) and (b) unifying the duplicated comparison logic
  (`check_study_complete` / `_detect_study_growth` / right-panel gate) onto the one `sync_manifest` model.
  Both are flag-gated + golden-compared. Lower urgency now that S1 + FIX-004/005 landed.
- **S3 — Off-thread / preview-first series load (P2/P3).** Move `_build_metadata_headers_only` off the main
  thread and repair preview-first so the first slice paints after a few headers; keep the full scan in the
  background. The single largest responsiveness win; also the highest care (render must stay on the main
  thread, slice ordering must be byte-identical). Golden-image gated.
- **S4 — Drag-drop triggers download for a not-local series (P7).** Note: the **common** cases are already
  handled — dropping a *partial* or *currently-downloading* series of the opened study loads what's on disk
  and the progressive-grow pipeline feeds new slices into the viewport as they arrive, and the 5-layer
  de-dup prevents a duplicate task. The remaining gap is dropping a series whose study was **never**
  downloaded; closing it needs viewer→DownloadManager wiring (the drop handler in `_vw_dragdrop.py` has no DM
  reference today) and a real Qt drag to verify (synthetic drags don't trigger Qt DnD), so it is **staged**
  rather than implemented blind. When done: in `_do_series_switch`, if `evaluate_sync` shows the dropped
  series missing/partial, request the priority download (reusing the in-flight task via de-dup) alongside the
  load; preserve `force_reload` for local series. Flag-gated.
- **S5 — Unified study-level state + progressive UI surface (P8).** Expose
  Checking→Downloading→Generating→Ready→Stale/Failed from the manifest model in the home status cell.
  Largest UI change; lowest clinical risk; do last.
- **S6 — Per-instance / SOP-level sync option (P5).** Only if a real PACS scenario needs it; opt-in
  (`AIPACS_SYNC_SOP_LEVEL`) because it costs a heavier server query.

---

## 6. KPI review

**Already instrumented** (good coverage): `FAST-OPEN-TRACE` (click_single_entry, thumbnail_task_start,
open_request, study_path_ready, tab_created, waiting_for_first_series_signal, first_series_visible,
download_manager_wired, attachments_start/done, resync_start, study_resync_check, resync_complete,
right_panel_cache_gate/hit), `FAST_LOAD_BREAKDOWN` (headers_only_build, now header_scan_parallel),
`NET_TIMING` (endpoint, server_wait_ms), `VIEWER_SWITCH` / `PERF series_switch_breakdown`,
`MAIN_THREAD_STALL`, resource-summary (cpu/rss/io).

**Targets (suggested, to drive S1–S3):** single-click→thumbnails < 1.5s; double-click→tab < 0.3s;
double-click→first image (local complete) < 2s; server metadata check < 0.5s; download-start latency <
0.5s; UI-thread blocked per open < 100ms (today: seconds — the gap S2/S3 close).

**Gaps:** no explicit KPI for "UI-thread blocked time per open" (derivable from MAIN_THREAD_STALL but not
aggregated); no counter for "duplicate-download avoided" or "resync pulled N missing series" (would prove
the de-dup/sync are working in the field).

---

## 7. Validation checklist (current status)

| # | Check | Status |
|---|---|---|
| 1 | Not-downloaded single-click loads thumbnails fast | ✔ (debounced, thumbnail-only) |
| 2 | Not-downloaded double-click opens + downloads | ✔ (tab instant, CRITICAL download, progressive) |
| 3 | Downloading study → no duplicate download | ✔ (5-layer de-dup; in-flight reuse) |
| 4 | Downloaded study opens fast + still checks server | ◑ server check ✔; **fast** blocked by P2/P4 (S1/S3) |
| 5 | New server series detected + downloaded | ✔ (resync; only-missing) — count-level (P5) |
| 6 | Cleared study no longer shows downloaded | ✔ (disk-first + FIX-003/004/005/006) — on-open auto-stale = S2 |
| 7 | Drag-drop works local / partial / remote | ◑ local ✔; partial/remote download trigger = S4 |
| 8 | UI responsive during sync/download | ◑ orchestration ✔; series load blocks (S3) |
| 9 | DB / files / cache / UI stay consistent | ✔ clear path (FIX); on-open validation = S2 |
| 10 | No duplicate series entries / files | ✔ (task series de-dup; file resume skip) |

Legend: ✔ in place · ◑ partially in place, closed by the staged item noted.

---

## 8. Recommendation

The architecture is sound and already conforms to most standard sync patterns; it does **not** need a
rewrite. The highest-value, lowest-risk next step is **S1** (stop the wasteful re-download of a complete
study) followed by wiring the new **manifest read-model (S2)** in as the single completeness/stale gate, and
then **S3** (off-thread/preview-first load) as the big responsiveness win. Each is flag-gated and
golden-compared so clinical output cannot change unreviewed. The manifest read-model added in §5.1 is the
shared foundation those phases build on.
