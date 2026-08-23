# Open findings — diagnosed, not fixed

**Date:** 2026-08-16
**Status:** §1 is **RESOLVED** (2026-08-16, later the same day — see
[`PIXEL_CACHE_PERSISTENCE_2026-08-16.md`](PIXEL_CACHE_PERSISTENCE_2026-08-16.md)).
**§2 is still OPEN.**
**Why they are here and not in the regression catalog:** each one needs a
decision that is not mine to make — one is a privacy/policy call, the other
needs measurement I do not yet have. Writing them down beats silently
"fixing" the wrong thing.

---

## 1. The L2 disk pixel cache is wiped on every shutdown — RESOLVED

> **Outcome (2026-08-16).** The owner chose persistence by default. Implemented
> as `DiskPixelCache.clear_on_exit()` with the kill switch
> `AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT=1`, guarded by
> `tests/code/viewer/test_disk_pixel_cache_persistence.py` (20 tests, 13 of
> which fail on the pre-fix codebase). Full write-up:
> [`PIXEL_CACHE_PERSISTENCE_2026-08-16.md`](PIXEL_CACHE_PERSISTENCE_2026-08-16.md).
> The analysis below is kept as the record of how the decision was reached.

### The finding

`PacsClient/pacs/workstation_ui/mainwindow_ui.py:1521`, inside the
`cache.auto_cleanup_threads` shutdown step:

```python
def _shutdown_caches():
    ...
    for cache in (_thumbnail_cache, _metadata_cache, _image_cache):
        ...            # in-memory caches — clearing these is correct
    clear_study_cache()
    get_disk_pixel_cache().clear()      # <-- this one is on disk
```

`DiskPixelCache.clear()` (`modules/viewer/fast/disk_pixel_cache.py:306-321`)
does not just drop the in-memory index — it calls `shutil.rmtree(self._root)`
and recreates an empty directory. Every decoded slice on disk is deleted.

### Why that is a contradiction

The module's own docstring states its purpose:

> **L2 persistent cache** for decoded DICOM pixel arrays. Eliminates the need
> to re-decode slices when reopening a previously-viewed series.

It is built for persistence: a 2 GB size cap (`_DEFAULT_MAX_SIZE_MB = 2048`),
LRU eviction by last-access time, a corruption-safe binary header, an on-disk
index scan at startup. All of that machinery only pays off across sessions —
and the cache never survives one.

### Evidence

Every `clear` and every `indexed` line in `viewer_diagnostics.log*`:

```
2026-08-08 15:21:56  [B3.12] Disk pixel cache cleared
2026-08-08 16:14:41  [B3.12] Disk pixel cache cleared
2026-08-08 17:37:18  [B3.12] Disk pixel cache cleared
2026-08-08 20:22:06  [B3.12] Disk pixel cache cleared
2026-08-09 12:26:14  [B3.12] Disk pixel cache cleared
2026-08-09 15:21:19  ... (7 more on 08-09)
2026-08-10 15:31:22  [B3.12] Disk pixel cache cleared
2026-08-10 21:30:41  [B3.12] Disk pixel cache cleared
2026-08-11 14:08:29  [B3.12] Disk pixel cache cleared
2026-08-16 12:49:04  [B3.12] Disk pixel cache cleared
2026-08-16 13:25:44  [B3.12] Disk pixel cache cleared

2026-08-16 13:07:13  [B3.12] Disk pixel cache indexed: 0 entries (+0 new, 0.0 MB) in 1 ms
2026-08-16 13:26:59  [B3.12] Disk pixel cache indexed: 0 entries (+0 new, 0.0 MB) in 1 ms
```

18 clears in nine days. **Both** index scans found **0 entries**. The L2 cache
has never once served a hit across a restart on this machine. The async-init
work done on 2026-08-16 made the startup scan free — but it is scanning an
empty directory, so it saves nothing real either.

### Why I did not change it

There is a plausible, deliberate reason for this line, and it is not
performance: **decoded pixel arrays are patient image data at rest.** They sit
in `user_data/cache/pixel_cache/`, unencrypted, keyed by a SOP-UID hash. On a
shared or portable workstation, wiping them at exit is a defensible privacy
posture, and removing that behaviour to win a few hundred milliseconds would be
a bad trade made without asking.

The counter-argument is equally real: **the source DICOM files are already
stored unencrypted on the same disk** under `SOURCE_PATH`. The pixel cache is
therefore a second copy of data that is already there, in a different format —
not a new class of exposure. If that reasoning holds for this deployment, the
clear is pure cost.

I cannot decide that from the code. It is a site policy question.

### The options, if you want it changed

| | Change | Effect |
|---|---|---|
| **A** | Leave it exactly as is | Status quo. No PHI in the pixel cache between sessions. Cost: re-decode on every reopen; the whole B3.12 module is dead weight. |
| **B** | Drop `get_disk_pixel_cache().clear()` from `_shutdown_caches()` | The cache does what it was built to do. LRU + the 2 GB cap still bound it. Decoded pixels persist between sessions. |
| **C** | Gate it: `AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT`, default `1` | Nothing changes for anyone by default; a single-user workstation can opt into persistence. Matches this project's convention for every other behavioural change. |
| **D** | Clear on logout / user switch instead of on process exit | Keeps the privacy boundary at the point that actually matters (a different clinician sitting down) while allowing same-user reopen to be fast. More code than B or C. |

**My recommendation is C**, on the grounds that it changes nothing by default
and makes the trade-off explicit and per-site. If you tell me the answer, the
edit is three lines plus a guard test.

**Not yet measured:** what B or C would actually buy. The correct benchmark is
"reopen a previously-viewed series, cold process, cache populated vs empty" —
worth running before committing to any option, and I have not run it.

---

## 2. MPR activation blocks the GUI thread for seconds

### The finding

Opening the MPR view is now the **largest user-visible freeze in the app** —
larger than the browser prewarm problem that occupied most of this week.

From the 13:26 run (pid 239928, `corr_session=sess-f71c084178dd`), the user
toggled MPR twice. The main-thread stall probe recorded, between 13:27:08.9 and
13:27:20.8, **seven stalls of ≥100 ms totalling ~5.5 s**, the largest a single
**2014 ms** block:

| Time | Stall |
|---|---|
| 13:27:10.225 | 1345.1 ms |
| 13:27:10.523 | 298.1 ms |
| 13:27:12.537 | **2014.0 ms** |
| 13:27:12.902 | 364.9 ms |
| 13:27:13.049 | 146.8 ms |
| 13:27:20.408 | 1138.3 ms |
| 13:27:20.609 | 200.8 ms |

This reproduces. The 13:07 run of the same day showed ~3.8 s of contiguous
block on a single MPR activation.

### What the sampler caught inside those stalls

```
13:27:09.286 gap=402  toggle_zeta_mpr > mpr_viewer/widget.py:378 get_preset_manager
                      > preset_manager.py:52 custom_presets_dir.mkdir()
13:27:12.443 gap=575  _mpr_views.py:1147 _build_deferred_3d_view
                      > _mpr_views.py:869 _create_3d_view > vtk.vtkGPUVolumeRayCastMapper()
13:27:19.716 gap=424  mpr_viewer/widget.py:452 _setup_ui > _mpr_views.py:294 _setup_ui
                      > _mpr_views.py:600 _create_axial_view
                      > QVTKRenderWindowInteractor.py:362 vtkRenderWindow()
```

Every one of them is **VTK render-window / GPU mapper construction on the GUI
thread**.

### The honest limit of this evidence — do not skip this

Those three traces are *samples*, not accounting. They tell you what the GUI
thread was doing at one instant inside a multi-second block; they do **not**
prove that line cost the whole block.

The only part of the MPR open that is properly instrumented is the axial view.
`_mpr_step()` in `_mpr_views.py` emits `[MPR-STEP]` begin/end pairs, and for
these two activations it accounts for:

| Activation | `_create_axial_view` total | Dominant sub-step |
|---|---|---|
| 13:27:09.286 → 09.710 | **424 ms** | `interactor_initialize` 240 ms, `qvtk_interactor_ctor` 101 ms |
| 13:27:19.641 → 19.858 | **217 ms** | `qvtk_interactor_ctor` 86 ms, `interactor_initialize` 78 ms |

So the one instrumented step explains **641 ms of ~5.5 s**. The other ~4.9 s —
coronal and sagittal view construction, the deferred 3D view, the GPU volume
mapper, `get_preset_manager()`, the volume build — is **unattributed**. There
are no `[MPR-STEP]` lines for `_create_coronal_view`, `_create_sagittal_view`
or `_create_3d_view`.

I am not going to propose a fix on sampled evidence. That is how the browser
prewarm work went wrong the first time: I fixed the *scheduling* of an
unbounded cost instead of bounding the cost, because I had not measured where
the cost actually was.

### Recommended next step — measure first, in one cheap change

Extend the existing `_mpr_step()` instrumentation to the three uninstrumented
view creators and to the volume build, exactly mirroring the axial pattern
already in `_create_axial_view` (`_mpr_views.py:576`, whose 17 `_mpr_step()`
calls run from line 591 to line 660). Verified: **every one of the 17 call
sites in the file passes `'axial'`** — `_create_sagittal_view` (:662),
`_create_coronal_view` (:740), `_create_3d_view` (:815) and
`_build_deferred_3d_view` (:1058) emit nothing at all. That is:

- purely additive log lines, no behavioural change;
- uses machinery that already exists and is already proven in this module;
- turns one MPR open into a complete per-step cost table.

Only then decide what to do with the result. The plausible fixes, in the order
I would consider them, are all conditional on what that table says:

1. **Reuse instead of rebuild.** Two activations 10 s apart both paid full
   render-window construction. If the MPR widget is being destroyed and rebuilt
   on every toggle, caching the widget is the whole fix and touches no VTK code.
2. **Defer the 3D view further.** `_build_deferred_3d_view` is already
   deferred, yet still lands inside the visible stall. Deferring it past the
   first paint of the 2D views would make MPR *appear* immediately.
3. **Warm the VTK/OpenGL stack off the critical path**, the way
   `AIPACS_BROWSER_PREWARM` warms Chromium — but only if the table shows
   first-touch driver cost rather than per-open work.

### Constraint that must be respected in any fix

Per the project rules: **FAST viewer mode must never instantiate VTK render
windows.** Any warming or caching added here must stay strictly inside the MPR
path and must not be triggered from the FAST viewer. Whatever is chosen needs a
guard test asserting exactly that.

---

## 3. `os.stat` per series folder, on the GUI thread, per search result

### The finding

The second offender inside the 17:19 freeze (2 of 12 sampled traces, worst
sample **1,454 ms**), distinct from the assignment-snapshot cause that was
fixed:

```
home_search_service.py:925  search_server
  -> _hp_search.py:1452 _add_socket_patient_to_table
  -> _hp_search.py:1553 add_data2patient_list_table
       download_status = get_study_download_status(study_uid, ...)
  -> utils.py:1618 get_study_download_status
  -> utils.py:923  count_subfolders_with_dicom
       if sub.is_dir():
  -> pathlib/_local.py:515 stat  ->  os.stat
```

Every row of a server search result walks the study's folder on disk and
`stat`s each series subfolder, **on the GUI thread, while the table is being
populated**. Same disease as the two already fixed today — filesystem work on
the paint path — and the same first-touch AV cost applies (this machine runs
two real-time engines).

### Why I did not fix it in the same pass

Because the obvious fix is a cache, and a cache here has a **clinical display**
consequence: `get_study_download_status` drives the download-status indicator
the user reads to decide whether a study is complete. A stale cache would show
"downloaded" for a study still arriving. That is not a trade I should make
silently, and it is a different module from the freeze I was asked to fix.

### What I would do

1. **Measure first**, as with the MPR item: how many rows, how many subfolders
   per study, what a cold vs warm `count_subfolders_with_dicom` costs. The
   whole-freeze attribution is 1,454 ms from *one sample* — that is a lower
   bound, not a total.
2. Then choose between: (a) computing the status **off the GUI thread** and
   filling the cell asynchronously — the pattern the Status column already uses
   (`OPT-50`, 2026-08-02); (b) a short-TTL cache keyed by
   `(study_uid, dir mtime)`, which self-invalidates as files land; (c) deriving
   the count from the download manager's own progress state instead of the
   filesystem.

(a) is most consistent with what this codebase already does elsewhere and does
not risk staleness.

---

## Summary

| # | Finding | Blocked on | Cost of doing nothing |
|---|---|---|---|
| 1 | ~~Disk pixel cache wiped every shutdown~~ | **RESOLVED 2026-08-16** — owner chose persistence by default (a variant of option C with the default inverted) | — |
| 2 | MPR activation blocks the GUI thread ~4-5.5 s | Measurement — the non-axial views are uninstrumented | The app's largest remaining freeze, on a frequently-pressed button |
| 3 | `os.stat` per series folder on the GUI thread, per search-result row | Measurement, then a staleness decision on the download-status indicator | ~1.5 s+ of GUI block on a large server search |

Related: [`WEBENGINE_WARMUP_EVALUATION_2026-08-16.md`](WEBENGINE_WARMUP_EVALUATION_2026-08-16.md) §8,
[`FREEZE_72S_BROWSER_PREWARM_2026-08-16.md`](FREEZE_72S_BROWSER_PREWARM_2026-08-16.md),
[`MPR_VTK_LIFECYCLE_REVIEW_2026-08-01.md`](MPR_VTK_LIFECYCLE_REVIEW_2026-08-01.md).
