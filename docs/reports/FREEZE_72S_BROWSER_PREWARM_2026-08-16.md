# 72-second GUI freeze — browser prewarm (IMP-4), 2026-08-16

**Report.** "Check the current running app, it freezes." Session pid 218252,
started 11:01:48.

## Finding 1 (fixed) — 72.1 s frozen GUI from the browser pre-warm

`user_data/logs/app.log`, this session:

```
11:03:06  browser prewarm: idle-gated (delay=20000ms, idle_gap=5000ms, ...)
11:05:47  browser prewarm: idle 12692ms >= 5000ms after first interaction -> warming now
11:06:04  browser prewarm: file warm read 152.1 MB in 4358 ms (off-thread)
11:07:16  browser prewarm: Chromium engine warmed (construct+setUrl 72122 ms on GUI thread)
```

Corroborated by the stall sampler — one contiguous block, growing gap, same stack:

```
11:07:10  gap=37220.6  ... notify > prewarm.py:360:_on_construct > prewarm.py:525:_construct_warm_view
11:07:15  gap=70841.1  ... (same)
11:07:16  gap=72137.8  ... (same)
```

**This is a regression from my own 2026-08-07 fix (IMP-3)** — not in the sense
that IMP-3 malfunctioned, but that it fixed the wrong half of the problem.

Every scheduling guard behaved *correctly*: the OPT-22 idle gate, the IMP-1
modal veto and the IMP-3 construct-time input-recency re-check all agreed the
user had genuinely been idle for 12.7 s, so the construct was allowed to run.
The unbounded thing was never *when* it fires — it is the construct's **cost**.
Four live incidents now:

| date | blocked | context |
|---|---|---|
| 2026-07-23 | ~17 s | landed on first patient clicks |
| 2026-08-05 | 39.7 s | landed mid import-copy (IMP-1) |
| 2026-08-07 | 19.0 s | landed on a patient double-click (IMP-3) |
| **2026-08-16** | **72.1 s** | landed after a legitimate 12.7 s idle gap |

`QWebEngineView` must be constructed on the GUI thread and that call is atomic,
so the block cannot be capped, chunked or interrupted. On 2026-08-07 the same
construct took 219–227 ms (warm); cold it took 72 s. No idle window is long
enough to be safe against that, because the user can always resume work inside
it. I documented "a click landing mid-construct still waits it out" as an
accepted residual risk on 2026-08-07 — at 72 s that judgement was wrong.

### Fix (IMP-4) — the pre-warm is now opt-in

`modules/web_browser/prewarm.py`, `should_prewarm()`: default flipped from
adaptive-on to **off**. The Chromium boot is now paid when the user actually
opens the Web Browser — an explicit action where a wait is expected and
attributable — instead of at a random idle moment mid-reporting, for a feature
that may not be used at all in a session.

Opt back in with `AIPACS_BROWSER_PREWARM=1` (the adaptive "browser used at
least once" marker still gates it on top). Only a literal `"1"` enables it.

All the scheduling machinery (idle gate, modal veto, recency veto, off-thread
file warm) is untouched and still applies when enabled.

**Tests:** `tests/code/system/test_browser_prewarm_idle_gate.py` gains
`test_prewarm_is_opt_in_by_default`, `test_marker_gate_applies_on_top_of_the_opt_in`
and a 7-case parametrised pin that only `"1"` enables it. The three
`tests/code/web_browser/` fixtures that exercise the scheduling machinery now
opt in explicitly. **88 passed**, `py_compile` clean.

Takes effect on the next app restart. This session's warm already completed
(it is once-per-process), so it will not recur before then.

## Finding 2 (NOT fixed — needs your call) — ~9.1 s freeze on series open

A second, independent contiguous block at 11:05:41–11:05:47, from the sampler's
growing gap and shifting stack:

| gap | where |
|---|---|
| 3.0 → 6.0 s | `disk_pixel_cache.initialize` → `Path.iterdir` / `Path.stat` |
| 7.1 s | `dicom_windowing.auto_window_level_from_array` → numpy `percentile`/`unique` |
| 8.1 s | `qt_viewer_bridge._build_annotation_metadata` |
| 9.1 s | `qt_slice_viewer.paintEvent` → `_paint_image` |

The dominant chunk (~4 s) is **`DiskPixelCache.initialize()` running on the GUI
thread** during the first series switch. It is called lazily from
`get_disk_pixel_cache()` and walks the whole cache: measured on this machine
**44 study dirs, 1,593 `.apc` files, ~1.97 GB** — an `iterdir` per dir plus a
`stat()` per file, on cold/AV-scanned disk.

Proposed minimal fix (not applied): run `initialize()` once in a daemon thread
at startup (same pattern as the existing warmers) and have `get`/`put` treat an
un-initialised index as a cache miss until it is ready. Needs care around the
existing `self._lock` and the LRU byte accounting, so I would rather you okay it
than have me change cache semantics unasked.

## Note on WU-1 (my 2026-08-09 series-file warm)

`[SERIES_FILE_WARM] files=0 bytes=0.0MB elapsed=6ms studies=1` this session —
the warmer found nothing to warm. That is expected for a patient opened from the
server whose files have not been downloaded yet (there are no `<study>/<series>/`
dirs on disk at open time); it only helps already-downloaded studies, which was
the 53417 case it was built for. Worth knowing it is a no-op on the fresh-server
path rather than assuming it always helps.

## Current state

App is responsive as of 11:11 (Responding=True, only 100–330 ms stalls).

---

# Follow-up: the ~9.1 s series-open freeze, fixed (same day)

"Fix all in best way." Both remaining causes of the 9.1 s block are now fixed.

## Fix 2 — disk pixel cache index scan off the GUI thread

`modules/viewer/fast/disk_pixel_cache.py`.

`initialize()` walked the cache (an `iterdir` per study dir + a `stat` per
file) on whichever thread first touched the module singleton — in practice the
GUI thread, inside the first series switch.

**Design: `initialize()` stays SYNCHRONOUS for every direct caller** (so no
existing user or test changes behaviour); only `get_disk_pixel_cache()` — the
singleton created on the GUI thread — passes `background=True` and indexes on a
daemon thread. Deferring is safe because an unindexed lookup is simply a cache
**miss**: the caller decodes from DICOM exactly as on a cold cache.

Two things could have gone wrong in the merge, and both are pinned by tests:

* **double counting** — a key registered by a concurrent `put()` already had
  its bytes added, so the merge skips it (`_total_bytes` must equal the sum of
  entries; a threaded writer-vs-scan stress test asserts this);
* **LRU inversion** — the index's *order* is the LRU order
  (`_evict_if_needed` pops the front), so appending old scanned entries after
  freshly written ones would have made the newest slices the first eviction
  candidates. The merge re-sorts by access time.

Measured on the real cache (1,700 `.apc` files): GUI-thread cost
**90 ms → 0.33 ms**. Note the honest caveat — 90 ms is the *warm* figure; the
live 4 s was the cold/AV-scanned first touch, the same 10–20× cold/warm ratio
seen everywhere else on this machine (40.5 vs 0.88 ms/file header probes;
72 s vs 219 ms Chromium boot). The fix matters precisely in the cold case that
actually froze. Kill switch: `AIPACS_PIXEL_CACHE_ASYNC_INIT=0`.

Tests: `tests/code/viewer/test_disk_pixel_cache_async_init.py` (10 pins) — all
19 pre-existing disk-cache tests still pass unchanged.

## Fix 3 — heavy viewer imports warmed off the GUI thread (VS-2)

`PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py`.

The rest of the stall was **one-time module imports**, caught mid-import by the
sampler:

```
cv2/__init__.py:181 <module> -> :153 bootstrap -> :88 import_module     (~2 s)
auto_window_level_from_array -> np.percentile -> np.unique
    -> numpy/__init__.py:737 __getattr__                                (~1 s)
```

The numpy frame is the giveaway that this is *import* cost, not arithmetic:
`numpy/__init__.py:__getattr__` is numpy resolving a lazy submodule.

Added a `viewer-import-warm` daemon thread to the EXISTING first-search warm
hook (which already warms the download manager and the viewer linecache):
imports `cv2`, forces the numpy percentile/unique lazy path on a 3-element
array, and imports `opencv_filter_pipeline`. Pure imports — no Qt object is
created — so a background thread is safe, the same pattern the QtWebEngine
prewarm and linecache warm already use. Worst case the user reaches a series
first and pays the cost exactly where they do today: never worse.

Measured with the PacsClient package already loaded (as in the running app):
cv2 82 ms + numpy 103 ms + filter pipeline 2 ms = **187 ms warm**, vs the ~3 s
seen cold in the live trace. Kill switch: `AIPACS_VIEWER_IMPORT_WARM=0`.

(An earlier measurement of mine said 1.6 s for `opencv_filter_pipeline`; that
was wrong — it was the first-ever `PacsClient` package import in a fresh
process, which the app already pays at startup. Corrected above.)

Tests: `tests/code/viewer/test_viewer_import_warm.py` (8 pins), including one
that fails if the warm ever starts touching Qt objects, and one that fails if
the windowing path stops using `np.percentile` (i.e. if the warm starts warming
the wrong thing).

## Verification

`tests/code/{viewer,fast,web_browser,system,ui_services}`:
**3,469 passed, 14 failed** — and all 14 are the pre-existing failures verified
earlier by a stashed-changes baseline run (`test_field_icon_chip` ×5,
`test_local_incremental_and_import_date` ×3, `test_local_search_progressive`
×4, `test_report_assign_rendering`, `test_status_report_sorting`).
**Zero regressions.** `py_compile` clean on all three edited modules.

## Expected effect on the next restart

| cause | was | now |
|---|---|---|
| browser prewarm Chromium construct | **72.1 s** GUI block | not run (opt-in) |
| disk pixel cache index scan | ~4 s cold GUI block | 0.33 ms (off-thread) |
| cv2 + numpy lazy imports | ~3 s cold GUI block | off-thread at first search |

What is left of the original 9.1 s is the genuinely per-series work —
`_build_annotation_metadata` and the first `paintEvent` (~1 s each cold). Those
are real rendering work rather than deferrable startup cost, so I have left
them alone; if they still bite after a restart they are the next thing to look
at, with numbers from a fresh trace rather than from today's mixed one.

Verify live after restart: `[IMPORT-WARM] viewer imports warmed in ... ms`,
`[B3.12] Disk pixel cache indexed: ... in ... ms`, and no
`browser prewarm: ... warming now` line at all.
