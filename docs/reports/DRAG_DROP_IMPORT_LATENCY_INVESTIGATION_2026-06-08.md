# Drag-drop import latency + cache pipeline — pre-test investigation (2026-06-08)

Investigation of the two performance areas requested before the manual
open→drag→download→scroll test. Conclusion up front: **the drag→image-visible
latency for a fully-downloaded large series is real (~1.8–2.4 s) and has a single
dominant cause — a sequential 428-file DICOM header re-scan on the load path that
should have used DB metadata. The cache/progressive pipeline (the second area) is
already clean; the cost lives in the *initial uncached series load*, not in the
progressive grow.**

Evidence is the real session for fresh CT **10352, Series 302** (428 slices, fully
downloaded this session), pid 166612, 13:25 — `viewer_diagnostics.log` +
`app.log`.

---

## 1. Measured drop→visible timeline (already-downloaded 428-slice series)

| t (13:25:..) | thread | event | Δ |
|---|---|---|---|
| 08.572 | main | `change_series_on_viewer series=302` start | — |
| 08.63 | main | `cache_lookup cache_hit=False` (1.9 ms) → not in memory cache | |
| 08.63 | main | `viewer_event_total = 61 ms` → **change_series returns (non-blocking, schedules bg load)** | 61 ms |
| 08.69 | bg | `[H7-P5] series=302 POST_DOWNLOAD` — background load begins | |
| **10.492** | **bg** | **`[FAST_LOAD_BREAKDOWN] series=302 headers_only_build=1424ms`** | **1424 ms** |
| 10.519 | bg | `[H7-P4] server=428 disk=428 metadata=428 backend=pydicom_qt` | |
| 10.551 | main | `[VIEWER_SWITCH] switch_start` (apply on UI thread) | |
| 10.94 | main | `series_switch_breakdown psso_total=398 ms` (widget_creation **363 ms**) | 398 ms |
| 10.941 | main | `FAST:first_image_visible slice=214 decode=6.3 render=25 ms` — **image on screen** | |

**Drop → first visible image ≈ 2.37 s wall** ( = ~61 ms schedule + ~1424 ms header
build + ~398 ms UI switch + thread-hop/queue overhead).

Important: the UI thread does **not** freeze — `change_series_on_viewer` returns in
61 ms and the heavy work is on a background thread. The user sees a **spinner for
~1.8–2.4 s**, then the image. The often-quoted "25 ms first image" is only the final
decode+render of the displayed slice; it excludes the 1.4 s load that precedes it.

---

## 2. Root cause #1 (dominant) — 1424 ms sequential header re-scan

The FAST `pydicom_qt` load (`image_io.load_single_series_by_number`) has two ways to
build series metadata:

1. **DB path** (fast): `find_series_pk_by_number` → `get_instances_by_series_pk` →
   `_get_cached_metadata`. One indexed query; ~tens of ms.
2. **Fallback** (`_build_metadata_headers_only`, `image_io.py:1638`): when the DB path
   yields nothing, **loop over every DICOM file and `_safe_dcmread(stop_before_pixels=True)`** — for 428 files this is the **1424 ms**.

For Series 302 the breakdown logged **only** `headers_only_build=1424ms` (no
`db_lookup`/`reconcile_disk` keys) — i.e. the DB path produced no metadata and the
code fell through to the disk scan. The study was opened from the **server**
(`FAST-OPEN-TRACE … is_local=False source=server`), so although the download
subprocess writes instances to `dicom.db`, the viewer's DB lookup returned nothing
usable at drop time and it re-derived all geometry from disk.

Why the fallback is slow:
- It is **single-threaded** — a sequential `for` over 428 files (`image_io.py:1645`).
  Header reads are I/O-bound and release the GIL, so they parallelize well, but the
  loop does them one at a time (~3.3 ms/file × 428).
- Each iteration does a `_safe_dcmread` **and** `_build_instance_header_stub`; if the
  stub re-opens the file that is a second read per slice.

This is a **first-open, once-per-series** cost (the second open of 302 hit the memory
cache — `cache_result=hot_hit`). But in the user's workflow the dragged series is
always a first open, so it always pays it.

## 3. Root cause #2 — the "preview-first" mitigation isn't firing

The async load worker (`_vc_switch.py:588–634`) is *designed* to mask this: before the
full build it calls `load_series_preview(max_files=8)` to put the first slice on
screen in <100 ms, then swaps in the full stack when ready. For Series 302 **no
preview image appeared** — first-visible was slice 214 (the full-load middle), and
there are **zero `[PREVIEW]` traces** in the logs. The whole preview block is wrapped
in `try/except: pass`, so any failure (or a no-op apply in FAST mode) is swallowed
silently. Net effect: the user waits the full ~1.8 s instead of seeing an image at
~100 ms.

## 4. Secondary cost — 398 ms UI-thread switch/widget-creation

After the background load, `_perform_series_switch_optimized` runs on the **main
thread**: `psso_total=398 ms`, of which `widget_creation=363 ms`. This is a real
~0.4 s main-thread cost on every first switch into a series (FAST container/widget
build). Not a freeze, but it adds to the perceived delay and briefly blocks the UI.

---

## 5. Second requested area — cache / progressive pipeline: already clean

Re-confirmed (see `PROGRESSIVE_PIPELINE_BOTTLENECK_INVESTIGATION_2026-06-08.md`): the
batch→viewer grow is **incremental, not full-refresh** — `additive_cache_grow`
flushes cost **0.5–0.9 ms**, the directory/header scan is off-thread and
batch-buffered, the current slice is preserved by path across re-sorts, there is no
forced repaint, and grows are interaction-deferred so a batch never preempts a scroll.
Cache insert is non-blocking vs the download thread; indexing is path-preserved.

**So the latency the user feels is NOT the progressive cache** — it is the initial
uncached load (§2) plus the UI switch (§4). The progressive path only runs *after*
the first stack is up, and it is sub-millisecond.

---

## 6. Fix options (ranked; none applied yet — see note)

| # | Fix | Effect | Risk |
|---|---|---|---|
| **A** | **Parallelize `_build_metadata_headers_only`** (ThreadPool header reads, preserve order by index) | 1424 ms → ~250–400 ms | **Low** — pure read parallelism, header-only, order kept |
| **B** | **Repair preview-first in FAST mode** (instrument the swallowed `try/except`; ensure the ≤8-file preview actually applies for `pydicom_qt`) | First image ~100 ms regardless of full-build cost | Low–Med — touches the apply path; needs a guard test |
| **C** | **Prefer DB metadata for server-opened studies** (ensure series PK + instances are queryable at drop so the fast DB path is used, skipping the scan) | 1424 ms → ~tens of ms | Med — DB/download sync timing; fallback must stay for partial DB |
| **D** | **Drop the double header read** in `_build_instance_header_stub` if it re-opens the file | ~halve §2 | Low |
| **E** | Move/trim the 363 ms `widget_creation` off the first-switch critical path | −~0.3 s | Med — FAST container lifecycle |

Recommended combination: **A + B** (parallel scan *and* preview-first) takes
drop→visible from ~1.8–2.4 s to: preview at ~100 ms, full stack at ~400–600 ms —
a large, safe win without changing the DB/download contract. C is the deepest fix but
should stay behind the header fallback for active-download safety.

> **Note on sequencing:** no code changed yet. These touch the core series-load path,
> and the manual test is meant to capture a *baseline*. Recommend running the baseline
> test on the current build first, then applying A+B and re-measuring against the same
> KPIs (§7).

---

## 7. KPI / log review guide for the manual test

Workflow: double-click patient → open large-slice series → pick a not-yet-downloaded
series → drag into viewport → priority→critical → scroll while downloading.

Logs: `user_data/logs/viewer_diagnostics.log` (viewer timeline) + `app.log`
(load breakdown, switch perf, resource) + `download_diagnostics.log` (DM/priority).

What to grep, and the number that matters:

| Question | Log line | Read |
|---|---|---|
| Drop→first image (the headline) | `viewer-event start change_series_on_viewer series=N` … `FAST:first_image_visible series=N` | wall-clock delta between the two timestamps |
| Was it the header re-scan? | `[FAST_LOAD_BREAKDOWN] series=N …` (app.log) | `headers_only_build=NNNNms` present = the slow path; `db_lookup=`/`cached_metadata=` present = fast path |
| Was the UI blocked or just spinning? | `change_series_on_viewer stage=viewer_event_total duration_ms=` | should be ~60 ms (non-blocking). If seconds → a real UI-thread stall |
| UI switch cost | `[PERF] series_switch_breakdown series=N psso_total=` (app.log) | watch `widget_creation_ms` (~363 ms seen) |
| Did a preview show first? | `[PREVIEW]` / `preview_only` | absent = no fast first-image (current behavior) |
| Priority → critical on drag | `download_diagnostics.log`: `add_downloads`, viewed-series/critical markers | drag should escalate the dragged series |
| Progressive stack growth | `[PROGRESSIVE_GROW_SPLIT] … repaint_request_ms=0.000`, `FAST:additive_cache_grow` | flush cost should stay <1 ms; `repaint_request_ms=0` |
| Scroll smoothness while downloading | `FAST_EVENT_PACING`, `MAIN_THREAD_STALL` | no `MAIN_THREAD_STALL` > ~150 ms during scroll |
| Server-opened vs local | `[FAST-OPEN-TRACE] … is_local= source=` | `is_local=False source=server` correlates with the §2 slow path |

Hand me the session timestamp + patient/series after the test and I'll pull these and
produce the PASS/WARN/FAIL + before/after table (and apply A+B if you want the fix).

---

## 8. Fixes applied (2026-06-08)

Baseline confirmed live on patient 45525 (series 201, fully downloaded, first
open): `headers_only_build=712ms` for 303 files; a re-drop of the already-cached
series 202 was `~31ms`. Same root cause as 10352/302 (1424 ms / 428 files).

**Fix A — de-duplicated + tag-scoped header scan** (`image_io.py`
`_build_metadata_headers_only` + `_build_instance_header_stub`).

> **Correction (live re-measure on 45557).** The first attempt parallelized the
> scan with a `ThreadPoolExecutor` on the (wrong) assumption that header reads
> are I/O-bound. The live re-run showed series 202 (476 files) still at
> `headers_only_build=1284 ms`, and a micro-benchmark
> (`_recovery/bench_header_scan.py`) proved why: pydicom header **parsing is
> GIL-bound (CPU), not I/O-bound**, so the pool ran **~2× *slower*** than
> sequential (476 files: sequential 472 ms vs ThreadPool-8 937 ms). The pool was
> a regression and has been **reverted**.

The two changes that actually help, both safe and single-threaded:
1. **One header read per file.** The old loop did a *second*, throwaway
   `_safe_dcmread` on every file just to capture series-level metadata; that is
   removed (the series header is read once, after the stubs build).
2. **`specific_tags`.** `_build_instance_header_stub` now parses only the ~16
   tags it needs (`_HEADER_STUB_TAGS`) instead of the whole header — the
   GIL-bound parse cost is what that trims.

**Measured on the real 476-file series 202** (warm cache, `bench_header_scan.py`):
the actual function went **OLD 921 ms → NEW 635 ms ≈ 1.45×**, and ~1.5× faster
than the reverted threadpool. Slice order, metadata shape, and the DB/download
fallback are all unchanged.

This is a real but modest win — the per-file pydicom parse is the floor. The
large perceived-latency lever remains **Fix B (preview-first)**: show the first
slice after ~1 header instead of waiting for all N. That needs the
`[PREVIEW_FIRST]` trace from an *interactive drag* of an uncached series (the
45557 loads were progressive/download-driven, so the preview hook wasn't
exercised and no trace was emitted).

**Fix B — preview-first made observable** (`_vc_switch.py`
`_schedule_async_load_and_switch._worker`). The preview-first path (show ≤8-file
first slice in <100 ms while the full build runs) was wrapped in a silent
`try/except: pass`, so a non-firing preview left no trace. Added `[PREVIEW_FIRST]`
logging for the decision (`use_preview`/`exp_slices`/`backend`), the
`load_series_preview` outcome, the apply, and — critically — the previously
swallowed exception. **No render-path behaviour change.** This is deliberately
the safe step: the next live drag will show in the logs exactly why the preview
doesn't surface in FAST `pydicom_qt` mode (suspected: the preview builds a
`BACKEND_VTK` payload + VTK volume that the file-rendering FAST viewer ignores),
so the full preview enablement can be done with evidence rather than blind on the
clinical render path.

**Verification:** both files `py_compile` clean; guard
`tests/code/viewer/test_headers_only_parallel_scan.py` (7 tests: order/dedup,
skipped-file ordering, tiny-series, empty/all-unreadable → None, `specific_tags`
usage, tag-coverage) passes; existing real-DICOM tests `test_fast_viewer_pipeline`
+ `test_flat_folder_import` (185) still pass — **192 total green**. Both files are
under `PacsClient/` — not plugin-mirrored.

**Needs another restart:** the live 45557 run still had the *threadpool* build;
the corrected sequential+tags build is on disk but not yet in the running process.

**Next:** restart, then drag a fully-downloaded-but-uncached series and read
`[FAST_LOAD_BREAKDOWN]` (expect roughly 1.45× lower than the 712 ms/303 ·
1424 ms/428 baseline) and the new `[PREVIEW_FIRST]` lines — the latter only fire
on an *interactive drag* (not a progressive/download-driven load), and are what's
needed to finish Fix B's FAST preview enablement (task #168).

### Live re-measure (45557 → corrected Fix A, then 45486)
- **45557 caught a regression.** The first Fix A used a `ThreadPoolExecutor`; live
  series 202 (476 files) still showed `headers_only_build=1284 ms`. A micro-bench
  (`_recovery/bench_header_scan.py`) proved pydicom parse is GIL-bound → the pool
  was ~2× *slower*. **Reverted** to sequential + de-dup + `specific_tags`.
- **45486 confirmed the corrected build live:** series 201 (450 files, fully
  downloaded) `headers_only_build=800 ms` = **1.78 ms/file — the fastest per-file
  of every run** (v0 original 2.35–3.33, v1 broken pool 2.70, **v2 1.78**). No crash.

## 9. Fix B v2 — FAST-native preview on the shared load path (flag-gated, default OFF)

The 45486 trace showed `[PREVIEW_FIRST]` never fires in normal use: large series
load via the **progressive/auto-display path** (`_apply_progressive_to_target_viewer`
→ `_load_single_series_on_demand`), not the interactive `_schedule_async_load_and_switch`
path where the original preview hook lives. So the preview was moved **down into the
shared loader** (`image_io.load_single_series_by_number`, FAST `pydicom_qt` path):

- New `max_files` cap on `_build_metadata_headers_only` → build metadata for the first
  N files only (~tens of ms).
- When the full header scan is needed (DB metadata empty), the loader now **yields a
  small `preview_only` first-batch payload first**, then continues to the full scan and
  yields the full stack. The caller's apply loop (`_load_single_series_on_demand`)
  applies each yielded item, and caches **only the last (full)** item — so the preview
  shows a first slice fast but never pins the series at N slices. Unlike the old
  `load_series_preview` (which built a `BACKEND_VTK` payload the FAST file-renderer
  ignored), this preview is annotated `pydicom_qt` and renders from the 8 files.

**Default OFF** (`AIPACS_FAST_FIRST_PREVIEW`, with `_FILES`=8, `_MIN`=32). Rationale: it
adds a *second* viewer apply per load, and the in-loader preview was historically
"disabled by design" to avoid flicker — so this must be **flicker-validated on real
hardware before becoming default**. With the flag off, behaviour is byte-identical.

To try it: launch with `AIPACS_FAST_FIRST_PREVIEW=1`, drag/open a large
fully-downloaded series, and check for (a) `[FAST_FIRST_PREVIEW] series=… preview_slices=8`
in `app.log`, (b) first image in ~100 ms, (c) the full stack replacing it with **no
flicker**. If clean on the real workstation, flip the default in `image_io.py`.

### Outcome — preview tested, then REMOVED (final state)

Live test with `AIPACS_FAST_FIRST_PREVIEW=1` (45369 series 204, 288 slices,
downloading): the preview fired (`[FAST_FIRST_PREVIEW] series=204 preview_slices=8`)
then the full `headers_only_build=275 ms` ran anyway, so the viewer went
**8 → 40 → grow** — an extra apply plus a slider-range jump that reads as jank. And
because the series was **downloading**, the progressive path was already streaming
images in, making the preview redundant. The user confirmed the no-preview build
feels faster.

**Decision: the preview code was removed entirely** (constants, the `max_files`
param on `_build_metadata_headers_only`, the FAST-path yield, and the `[PREVIEW_FIRST]`
logging in `_vc_switch.py`). The pre-existing interactive preview machinery is
untouched. **Only Fix A remains** (sequential + de-dup + `specific_tags`), which is
flag-independent and is the real, clean win. Lesson: a second viewer apply + a
slider-range jump outweighs a ~270 ms first-frame gain, and you should never preview
a series the progressive pipeline is already streaming.

**Verification (final):** `image_io.py` + `_vc_switch.py` compile; guards back to 7
tests (preview tests removed) — **192 total green** with `test_fast_viewer_pipeline` +
`test_flat_folder_import`. `PacsClient/` — not plugin-mirrored.

## 10. First-patient vs second-patient cold start (investigated; no code change kept)

Separately, the user observed the **second** patient opening faster than the **first**
after launch. Confirmed from logs (pid 172584): patient 1 `tab_created` 469 ms /
first-image 758 ms vs patient 2 305 ms / 586 ms — a ~165 ms one-time cold cost.

**Attribution.** Patient 1's trace shows the gap is between `ButtonSafeguard` init and
`AdapterRegistry.register` — i.e. **first-time `PatientWidget` Qt construction** (toolbars,
FAST container, viewer controller) plus the once-per-process EchoMind adapter registration
and first-time code-path JIT. Patient 2 reuses all of it.

**Attempted fix → reverted (no-op).** I extended the existing first-search background
warmup (`_hp_search.py::_warmup_download_manager_once`) to pre-import the four heavy
first-tab modules (`PatientWidget`, viewer controller, FAST container, EchoMind
`bus_factory`). Live re-measure (pid 162036) logged
**`[DM-WARMUP] pre-imported 4/4 first-tab modules in 0ms`** — i.e. those modules are
**already imported during app startup**, well before the first search, so the import was
never on the open critical path. The pre-import bought nothing and was **removed** to keep
the warmup clean. (The first open that session was 388 ms / 735 ms, but with the change
contributing 0 ms that is run-to-run variance, not the edit.)

**Conclusion.** The remaining ~150 ms first-open cost is inherent first-time **Qt widget
construction**, which import pre-warming cannot address. Eliminating it would require
constructing a throwaway `PatientWidget` at startup — a real side-effect/leak risk on
clinical software for a one-time, sub-second, per-session cost — so it was **deliberately
not pursued**. First-patient open (<800 ms to first image) is acceptable as-is. The
existing DM + linecache warmups (and Fix A) remain the active, effective optimizations.
