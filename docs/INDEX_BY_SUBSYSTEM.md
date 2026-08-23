# AI-PACS Documentation — Index by Subsystem

When you're about to touch a subsystem, this index tells you which docs to read first. Most subsystems have an "as-built" plan that codifies invariants; the catalog row tells you which guard test enforces them at runtime.

---

## Master indexes

- **[Audit overview (2026-05-28)](AUDIT_2026-05-28_OVERVIEW.md)** — every stage report linked
- **[Regression catalog](plans/architecture/REGRESSION_CATALOG.md)** — every fix + its guard test (56 rows)
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

### Medical Report Editor (Reception Data tab)

| Doc | What's in it |
|---|---|
| **[`reports/REPORT_IMAGE_INSERT_2026-08-18.md`](reports/REPORT_IMAGE_INSERT_2026-08-18.md)** | **Read before touching report content or the upload path.** How a captured viewer image gets into the report and survives `toHtml` -> normaliser -> `setHtml` -> render/print; why images are embedded and downscaled rather than linked; the measured payload numbers; and the reversed-cursor-selection bug that every AST guard missed. |
| [`reports/REPORT_SYNC_ECHOMIND_EDITOR_RECEPTION_AUDIT_2026-07-15.md`](reports/REPORT_SYNC_ECHOMIND_EDITOR_RECEPTION_AUDIT_2026-07-15.md) | How the editor, EchoMind and the reception server stay in sync, and what the server-side HTML actually keeps. |

**Invariants:**

- The editing surface is a **Qt rich-text `QTextEdit`**, not a web view. Only the HTML-4 subset Qt understands round-trips; anything that needs real CSS will be silently lost.
- **Styling must be inline.** `prepare_report_html_for_server()` strips `<style>`, `<script>` and document chrome on upload, so a class or a stylesheet rule does not reach the server. Image sizing therefore lives on the `QTextImageFormat` (Qt emits `<img width= height=>` attributes), never in CSS.
- **`<img>` must stay out of `_DIR_BLOCK_TAGS`.** If it is ever added, an embedded key image silently disappears from the copy the referring doctor opens while the author's copy still shows it.
- **Report images travel as bytes, not paths.** The report is uploaded as one JSON field; a `file:///` src renders only on the machine that wrote it.
- **Per-image size is capped** (~1000 px / JPEG q88, 1.5 MB hard ceiling). There is no per-report cap — a report with many images can still grow past what the endpoint likes.

**Guard tests:**
- `tests/code/reporting/test_report_image_insert.py` (47) — insert, resize, and the full save/upload/reopen round-trip
- `tests/code/reporting/test_server_report_html.py` (19) — the upload normaliser itself (RTL/LTR per block, inline-style preservation, idempotency)

### Viewer (multi-study, sidebar, drag-drop)

| Doc | What's in it |
|---|---|
| **[`MULTI_STUDY_SINGLE_TAB_PLAN.md`](MULTI_STUDY_SINGLE_TAB_PLAN.md)** | **Required reading before editing the viewer.** Offset-key invariants, `_render_multistudy_grouped` behavior, server-info dict shape. |
| [`AUDIT_STAGE_5_2026-05-28.md`](plans/architecture/AUDIT_STAGE_5_2026-05-28.md) | Read-only `ViewerAdapter` live verification. |
| [`AUDIT_STAGE_6_2026-05-28.md`](plans/architecture/AUDIT_STAGE_6_2026-05-28.md) | Multi-study live workflow audit (239 series across 5+ studies). |
| [`pipelines/thumbnail-pipeline.md`](pipelines/thumbnail-pipeline.md) | THUMBNAIL_PATH conventions, memory-first vs disk fallback. |
| **[`reports/REFERENCE_LINE_ACTIVE_VIEWPORT_2026-08-16.md`](reports/REFERENCE_LINE_ACTIVE_VIEWPORT_2026-08-16.md)** | **Read before touching reference lines.** Two modes ship: single-source (default — the ACTIVE viewport is the source and stays clean) and bidirectional all-pairs (`AIPACS_REFERENCE_LINES_ALL_PAIRS=1`). Explains why the source overlay must be *cleared*, not skipped. |
| **[`reports/TEXT_ANNOTATION_INPUT_2026-08-18.md`](reports/TEXT_ANNOTATION_INPUT_2026-08-18.md)** | **Read before touching the annotation tools.** Why `ToolController` is Qt-free and how the Qt layer injects behaviour into it (`_pixel_data_fn`, `_pixel_spacing_fn`, `_text_prompt_fn`); why a tool press returning `False` is the "place nothing, stay armed" contract; why text annotations are single-line. |

**MPR lifecycle invariant (2026-08-19):** `_MprLayoutMixin.cleanup()` is the
only thing that releases an MPR viewer's volume, render windows and GPU
texture — and **a `closeEvent` hook cannot be relied on to reach it.** Qt does
not call `closeEvent` when a parent is destroyed or a widget is re-parented
away, which is how patient-tab close and layout rebuilds leaked (14 opens vs
6 teardowns across the logged sessions). Any code that drops, orphans or
replaces a widget which may host an MPR must call
`modules.mpr.zeta_mpr.mpr_viewer._mpr_lifecycle.release_mpr_children(widget,
reason=...)` **before** `setParent(None)` / `deleteLater()` — after that the
GL context is gone and `ReleaseGraphicsResources()` cannot free the VRAM.
See [`reports/MPR_LIFECYCLE_RELEASE_2026-08-19.md`](reports/MPR_LIFECYCLE_RELEASE_2026-08-19.md).

**Oblique-MPR camera invariant (2026-08-23):** *in oblique mode the camera does
not select the displayed plane — an explicit `vtkPlane` on the mapper does.*
`_set_oblique_camera` runs `SliceFacesCameraOff()` + `SliceAtFocalPointOff()` and
sets `plane.SetOrigin(self.current_position)` (the crosshair centre) +
`plane.SetNormal(oblique_normal)`, **leaving the camera untouched** — this is
**v1.09.Fix-E**, and repositioning the camera is what it deliberately reverted,
because it made the image pan under the cursor during rotation. **Do NOT "fix"
the camera focal point onto the crosshair.** The displayed oblique plane passes
through the crosshair by construction. Two corollaries that read like bugs and
are not: `_update_slice_positions` moves the camera along the **look axis only**
in *both* modes; and `mpr_diagnostic_validator.py` (header `Version: 2026-02-17`)
still measures the *camera's* plane, so its `focal_at_crosshair`,
`plane_containment` and `parallel_scale` checks fire on every oblique update
without anything being wrong. Until 2026-08-23 Fix-E was recorded only in a
source docstring, and a stability review recommended reverting it. See
[`plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`](plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md)
and `pipelines/mpr-geometry-pipeline.md` §10.9, §10g, §10h.

**Colour-decode invariant (2026-08-21):** any code path that reaches
`ds.pixel_array` for display must call
`modules.viewer.fast.dicom_color.normalize_ybr_subsampling(ds)` **before** the
decode and `ybr_samples_to_rgb(ds, arr)` **after** it. Order is the mechanism,
not a style choice: pydicom caches the decoded array, and for an uncompressed
dataset that claims `YBR_FULL_422` while shipping full-rate samples it truncates
the frame to two thirds and then resamples it, producing coloured static — this
cannot be repaired after the fact. Equally, multi-sample YBR data painted
straight into `Format_RGB888` renders with a heavy cyan cast. Both corrections
are needed; either alone leaves the image unreadable. See
[`plans/architecture/IMPORT_FREEZE_AND_YBR_COLOR_2026-08-21.md`](plans/architecture/IMPORT_FREEZE_AND_YBR_COLOR_2026-08-21.md).

**GUI-thread disk invariant (2026-08-22):** nothing on the patient-list or
settings path may walk the filesystem on the GUI thread. Three separate scanners
were found doing it the day after the streaming fix, and the pattern behind all
three is worth recognising: *chunking a blocking call does not make it
non-blocking*. The download-badge refresh was already split into 2-study chunks
and still froze the UI for 13.1 s per chunk, because the per-study cost was
seconds. Verdicts are now computed on a worker
(`patient_table_widget._compute_study_download_status`, dispatched via
`downloadStatusReady`) and applied on the GUI thread; `_peek_download_status`
reads the cache and **never computes**. Storage cleanup runs on a `QThread`
behind a busy dialog (`storage_cleanup_panel._CleanupWorker`). And
`count_subfolders_with_dicom` uses an early-exit `os.scandir` walk instead of
`Path.rglob('*')` — measured **682.5 ms → 1.45 ms per study** cold, same verdict.
Prefer the two worker patterns already in `patient_table_widget`
(`statusFlagsReady`) and `storage_cleanup_panel` (`_FolderUsageWorker`) over a
new mechanism. See
[`plans/architecture/GUI_THREAD_DISK_PATHS_2026-08-22.md`](plans/architecture/GUI_THREAD_DISK_PATHS_2026-08-22.md).

**Hang-visibility invariant (2026-08-23):** *our stall probes cannot see a hang.
Do not read their silence as health.* Both are blind, for different reasons.
**F8 `[MAIN_THREAD_STALL]`** is a `QTimer` on the main thread — it measures the
gap when it *next fires*, so it only ever reports a stall that **ended**; a block
that runs until the process is killed leaves no record at all. **F11
`[MAIN_THREAD_STALL_TRACE]`** samples an in-progress block, but it is a **Python**
thread and needs the GIL for a single bytecode, so it cannot run while the main
thread sits inside a long C call — `gc.collect()`, a VTK destructor, a driver
call. On 2026-08-23 a workstation hung for 17 s during a patient close
(Windows `Application Hang 1002`) and the worst stall either probe recorded for
that session was 1 188 ms. Therefore: **any GUI-thread section that can block in
native code must be wrapped in
`PacsClient.utils.native_fault_log.hang_watchdog(label)`** — it arms
`faulthandler.dump_traceback_later`, whose timer runs on a **native** thread and
fires while the GIL is held — **and must log a breadcrumb BEFORE it runs**, not
only after, so a step the process dies inside is identifiable by having a start
and no done (`_pw_lifecycle._close_step`). The watchdog keeps exactly one timer
process-wide and is deliberately non-reentrant; arm it at the outermost point
that matters. Related: the deferred patient-close `gc.collect()` was made
*later* in 2026-06-27, not *shorter* — it still runs on the GUI thread by design.
See
[`plans/architecture/CLOSE_PATH_HANG_VISIBILITY_2026-08-23.md`](plans/architecture/CLOSE_PATH_HANG_VISIBILITY_2026-08-23.md).

**Patient-list streaming invariant (2026-08-21):** the progressive patient-table
streamer must never resolve a row's on-disk path on the GUI thread. Rows are
resolved on a worker (`_resolve_display_paths`), and
`load_progressive(..., ready=)` makes the streamer *wait* for that worker rather
than fall back to an inline `stat`/`opendir`. The previous "the worker
comfortably outruns the streamer" assumption held warm (4,500–6,000 rows/s vs
800) and failed catastrophically during an import (~325 ms/row → a 13.0 s
freeze). Anything that adds per-row work to the render path must be
`ready`-gated or budgeted the same way.

**Annotation-tool invariant:** `modules/viewer/tools/controller.py` must stay
**Qt-free** — it holds the tool state machine and is imported by every headless
tool test. Anything needing a widget (a dialog, a colour picker, a font) is
INJECTED by `qt_viewer_bridge._init_tool_controller`, never imported here. A
press handler returns `True` only when it actually placed or changed something;
`False` means the caller must not repaint or deactivate the tool.

**Reference-line invariant:** the active viewport draws **no** line, and its overlay is explicitly cleared when it becomes active — skipping it silently leaves a stale line and looks like the fix never landed.

**Guard tests:**
- `tests/code/viewer/test_ybr_color_decode.py` (23) — a mislabelled `YBR_FULL_422` frame is corrected before decode and converted to RGB after it; genuinely subsampled, compressed, 16-bit, RGB and monochrome data are all left byte-identical
- `tests/code/ui_services/test_list_stream_backpressure.py` (17) — the list streamer waits for the path resolver instead of touching the disk, loses no rows, respects a per-batch time budget, and still makes progress if the resolver dies
- `tests/code/ui_services/test_gui_thread_disk_paths.py` (27) — the download-badge refresh dispatches instead of walking, the DICOM scan never calls `rglob` yet returns the same verdict, and storage cleanup runs on a QThread
- `tests/code/viewer/test_text_annotation_input.py` (25) — the Text tool asks what to write, cancel places nothing and leaves the tool armed, a bare controller keeps the legacy placeholder, and `controller.py` stays Qt-free
- `tests/code/viewer/test_reference_line_active_viewport.py` (17) — the active viewport stays clean, the clean one follows the selection, and the env flag restores bidirectional
- `tests/code/viewer/test_reference_lines_all_pairs.py` — the all-pairs engine itself (still fully covered; the flag default is pinned in both directions)
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

### CPU contention & process priority (Windows)

**The recurring lesson in this area: before optimising a path, check whether the main thread was RUNNING.** A stall sample that bottoms out in `run_forever` with nothing below it means the thread was inside the Qt event loop waiting to be scheduled — no amount of work removed from our handler changes that number.

| Doc | What's in it |
|---|---|
| **[`reports/STACKING_LAG_55387_2026-08-23.md`](reports/STACKING_LAG_55387_2026-08-23.md)** | Patient 55387 stacking lag (pid 90364). The stacking path is exonerated by its own instrumentation — `frame_total_ms` median **1.6 ms**, disk/decode/cache waits **0.0 at median and p90** — while `ui_lag_max_ms` is 300 ms per drag. The decisive pair is **`event_p95_ms` 84.5 ms vs `handler_p95_ms` 9.0 ms**, and **45 of 66** sampled stall stacks bottom out in `run_forever`. Root cause on our side: the `[CPU_BUDGET]` priority boost had **never applied** (ctypes pseudo-handle truncation → `ERROR_INVALID_HANDLE`, 19 launches / 19 failures). |

**Invariants:**
- `GetCurrentProcess()` returns the pseudo-handle `(HANDLE)-1` == `0xFFFFFFFFFFFFFFFF`. **Any ctypes call that passes a Win32 HANDLE must declare `restype`/`argtypes` as `c_void_p`**, and must declare them **BEFORE** the handle is taken — a `restype` set after the call is a no-op. The default `c_int` silently truncates and the API fails with err 6. **There is a second, still-unfixed instance of this exact defect** at `modules/download_manager/workers/download_process_entry.py:149` — see the open item below.
- **The default priority class is build-type dependent** (2026-08-23, by owner request): frozen/installed build → **HIGH** (deployed clinical workstation), source run → **ABOVE_NORMAL** (developer box also running an IDE/VM/compiler). Detected with `aipacs_runtime.is_frozen()`, never a bare `sys.frozen` check — that would report False on every Nuitka build, i.e. on exactly the machines the rule is for. `AIPACS_PRIORITY=normal|above_normal|high` overrides; `normal` is the kill switch.
- An unrecognised `AIPACS_PRIORITY` must fall back to **the machine's own default**, never a hard-coded class — otherwise a typo silently demotes a clinical workstation.
- A failing `is_frozen()` probe degrades to the **source** default. Never promote a machine to HIGH because a probe raised.

**Open item — the DM subprocess demotion has never applied.** `download_process_entry.py:149` calls `SetPriorityClass(GetCurrentProcess(), BELOW_NORMAL)` with no `restype`/`argtypes` **and does not check the return**, so it has always silently failed. That demotion is the codebase's stated mitigation for "HIGH starves disk I/O", and the same file's v2.3.7 comment reasons from the premise "the viewer (ABOVE_NORMAL) blocks waiting on a lock held by an IDLE-scheduled thread" — a premise that was false, because the viewer was at Normal too. **The intended priority separation has never existed at runtime.** Not fixed yet: the repo has MEASURED harm from widening this gap (`ui_lag_max` 412 ms vs 229 ms), and HIGH-vs-BELOW_NORMAL is wider still, so it needs its own measurement. Until then `high` is untested against heavy concurrent downloading.
- **Never delete the `[CPU_BUDGET] SetPriorityClass failed (err=%d)` warning.** That line, ignored for months, is the only reason the defect was ever found.
- The stall probe writes to **`viewer_diagnostics.log`, not `app.log`.** Searching only `app.log` returns ~2 lines per session and the wrong conclusion.
- Logging is **not** a GUI-thread cost: `diagnostic_logging.py` routes every file handler behind a `QueueHandler`/`QueueListener`. Rule it out by reading that file, not by assuming.

**Guard tests:**
- `tests/code/system/test_cpu_budget_priority_boost.py` (13) — the three ctypes declarations, both ORDERING pins, the preserved diagnostics and kill switch, plus two behavioural Win32 probes that reproduce the truncation read-only via `GetPriorityClass`

**Analysis scripts:** `tools/analysis/oneoff/stack_lag_55387{,_detail}_2026_08_23.py`, `stall_trace_frames_90364_2026_08_23.py`

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

### Internal assignment (INO) — server-state snapshot

**The snapshot file is written under a process-global lock that the GUI thread also takes.** `get_state` is called per patient-list row while painting; anything that holds `_LOCK` for long freezes the worklist. Never add a per-row write to this store.

| Doc | What's in it |
|---|---|
| **[`reports/ASSIGNMENT_SNAPSHOT_BATCH_WRITE_2026-08-16.md`](reports/ASSIGNMENT_SNAPSHOT_BATCH_WRITE_2026-08-16.md)** | **Read before touching `ino_assignment_server_state` or `ino_assignment_refresh`.** The 10.79 s freeze: one full-file rewrite per reception, serialised against the GUI thread's per-row read. Measured write costs, why the fsync is now opt-in, and the four contracts that deliberately did NOT change. |
| [`reports/INTERNAL_ASSIGN_FALSE_ASSIGNED_REGRESSION_2026-07-15.md`](reports/INTERNAL_ASSIGN_FALSE_ASSIGNED_REGRESSION_2026-07-15.md) | Earlier assignment-state regression. |

**Invariants:**
- Writes are **batched**: `set_many()` for anything loop-shaped, `set_state()` only for a single user action. The write is O(all receptions), so a per-row write is O(N²) over a refresh.
- `_merge_and_save` must `_load` **inside the same lock acquisition** as the save, or a concurrent single write is silently rolled back.
- `_load` must stay **lock-free** — the writer already holds `_LOCK`, and `threading.Lock` is not reentrant.
- `get_state` must **keep** taking `_LOCK` (the 2026-07-31 WinError-5 fix); the answer to contention is fewer writes, not an unlocked read.
- A failed fetch must never wipe a known assignment.

**Guard tests:**
- `tests/code/network/test_ino_state_batch_write.py` (28) — one write per batch, the two write paths cannot drift, the fsync gate, and the refresh contracts that must not change
- `tests/code/network/test_ino_server_state_concurrency.py` — the reader/writer `os.replace` failure and the per-writer temp name

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
