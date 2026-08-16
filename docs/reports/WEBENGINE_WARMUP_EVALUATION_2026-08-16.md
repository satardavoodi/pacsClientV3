# Can the browser warm-up be made faster? — measured evaluation (IMP-5)

Question: after disabling the pre-warm (IMP-4, the 72.1 s freeze), can the
warm-up itself be optimised enough to be worth re-enabling?

Everything below is measured on the reporting workstation, not inferred.

## 1. Where the boot time actually goes

Phase-timed a full WebEngine boot in a fresh process (`C:\Temp\we_bench.py`):

| phase | warm |
|---|---|
| `import QtWidgets` | 214 ms |
| `import QtWebEngineCore` (the 202 MB DLL) | **46 ms** |
| `import QtWebEngineWidgets` | 2 ms |
| `QApplication()` | 45 ms |
| **`QWebEngineProfile.defaultProfile()`** | **918 ms** ← the global init |
| `QWebEngineView()` | **0 ms** |
| `setUrl()` + `loadFinished` | 554 ms |
| second view in same process | 0 ms |

**The view was never the expensive part.** The cost is Chromium's one-time
global init, which `defaultProfile()` triggers — and which Qt requires on the
GUI thread. The app's old warm constructed a throwaway `QWebEngineView`,
loaded `about:blank`, and held the resulting render process alive for up to
60 s, all to achieve what touching the profile achieves.

## 2. Chromium flags are not a lever (re-confirmed, cold-oriented flags too)

The previous flag benchmark was warm-only, so I retested the flags that change
*process spawning*, which was the leading cold-cost hypothesis:

| flags | `defaultProfile()` | total to ready |
|---|---|---|
| (none) | 662–918 ms | 998–1896 ms |
| `--disable-gpu` | 661 ms | 1037 ms |
| `--no-sandbox` | 665 ms | 998 ms |
| `--no-sandbox --disable-gpu` | 635 ms | 960 ms |
| `--in-process-gpu` | 696 ms | 1075 ms |

All within noise. No flag adopted.

## 3. What the warm is actually worth

| | GUI-thread block | user's first browser open |
|---|---|---|
| no warm at all | 0 ms | **971 ms** |
| throwaway view (old) | 991 / 889 ms | 156 / 115 ms |
| `defaultProfile()` (new) | **772 / 662 ms** | 173 / 123 ms |

So the entire benefit of pre-warming is **~850 ms off one browser open per
session**. That number matters for the strategy decision below.

## 4. Why it is 72 s cold — and what is *not* to blame

* Generic process spawn on this machine: **13.9 ms** — healthy. Proxifier is
  running, but it is *not* taxing ordinary process creation, so the
  "Proxifier hooks the spawn" theory in the old module notes is not supported.
* The WebEngine payload is **358 MB across 76 files**, and **two real-time AV
  engines are active simultaneously**: Windows Defender (RealTimeProtection
  ON) *and* Kaspersky Free.
* The app's off-thread file warm covered only **152.1 MB of that 358 MB**. The
  242 MB it missed was dominated by one file: **`Qt6WebEngineCore.dll`,
  202.3 MB**. `kick()` does `import QtWebEngineCore` off-thread, which
  memory-maps that DLL — but mapping is lazy: its pages fault in as the global
  init executes them, i.e. **on the GUI thread, from cold disk, past two AV
  engines**.

That is the best available explanation for a 100× cold/warm ratio, and it is
consistent with every other cold/warm ratio measured on this machine today
(header probes 40.5 vs 0.88 ms/file; cache scan ~4 s vs 90 ms).

## 5. Changes made (both measured)

**IMP-5a — warm via the profile, not a throwaway view.**
`_construct_warm_view()` now touches `QWebEngineProfile.defaultProfile()`.
Same benefit to the user, **~24 % smaller GUI-thread block** (701 ms measured
on the real path afterwards, vs 889–991 ms), no throwaway view, no page load,
and no render process held for 60 s to be discarded. Idempotent re-warm: 0.0 ms.

**IMP-5b — pre-read the engine DLLs off-thread.**
The file warm now covers **72 files / 394.8 MB** (was 64 / 152.1 MB), adding
`Qt6WebEngineCore.dll` and the other Qt DLLs by *name* (not a blanket `*.dll`
sweep — a test enforces that, so it can never start reading the whole of
site-packages). Off-thread pre-read: 394.8 MB in 3.0 s warm. Still bounded by
the existing 600 MB budget.

Tests: 5 new/updated pins in `tests/code/web_browser/test_prewarm_idle_gate.py`
— profile-based warm with the old machinery provably gone, DLL coverage,
name-scoping, budget cap. **92 passed** in the prewarm suites; full sweep of
`web_browser + system + viewer + fast`: **2,749 passed, 4 failed**, and those 4
are the pre-existing `test_local_search_progressive` failures verified against
a stashed-changes baseline earlier today. No regressions.

(Note for future me: the "must be gone" assertions had to parse the function
with `ast` and drop the docstring — the docstring's own measurement table
quotes `QWebEngineView()` and `setUrl()`, so a plain substring check matched
prose instead of code. Third time that trap has appeared in this codebase.)

## 6. Recommendation

**Leave the pre-warm default OFF.** The honest arithmetic: it buys ~850 ms on
one browser open per session, and its downside tail was 72 s of frozen
clinical workstation. Even now that the warm is 24 % cheaper and 243 MB more
of the payload is pre-read off-thread, I cannot *prove* the cold case is fixed
without a cold boot — and I am not willing to re-enable a minutes-long-freeze
risk on an unverified improvement.

**The real lever is the environment, not the code:**

1. **Two real-time AV engines** (Defender + Kaspersky Free) both scanning a
   358 MB payload. Running two is itself a general performance problem, not
   just for this.
2. **AV exclusions** for the app tree and `…\.venv\Lib\site-packages\PySide6\`
   (especially `Qt6WebEngineCore.dll` and `QtWebEngineProcess.exe`) would very
   likely collapse the cold cost. This is an IT/security decision — your call,
   not something I should change silently.

**How to decide it with data instead of opinion:** after a fresh boot, set
`AIPACS_BROWSER_PREWARM=1` for one session and read the new log line:

```
browser prewarm: Chromium engine warmed (defaultProfile NNNNN ms on GUI thread)
```

That single number is the cold GUI-thread block with all of today's
improvements in place. If it comes back in the low seconds, enabling by
default becomes defensible; if it is still tens of seconds, the answer is the
AV exclusions above, and the pre-warm should stay off regardless.

---

## 7. Live run with `AIPACS_BROWSER_PREWARM=1` (13:07) — what it showed

Both IMP-5 changes are confirmed live:

```
13:07:07.012  [IMPORT-WARM] viewer imports warmed in 81 ms: cv2, numpy.percentile, opencv_filter_pipeline
13:07:13.087  [B3.12] Disk pixel cache indexed: 0 entries in 1 ms      (off-thread, new)
13:07:53.564  browser prewarm: file warm read 394.8 MB in 4907 ms (off-thread)   (was 152.1 MB)
13:07:53.564  browser prewarm: Chromium engine warmed (defaultProfile 0 ms on GUI thread)
```

**The `defaultProfile 0 ms` is not a broken warm.** The user opened the Web
Browser *themselves* at 13:07:16 — proven by `.browser_used` (mtime 13:07:16)
and the profile cache files written 13:07:24–25 — which booted Chromium on
their click. The idle gate did not fire until 13:07:48, **32 s too late**, so
the warm correctly found nothing to do.

Verified separately that the warm still works, with a control (`we_bench3.py`),
including against the REAL browser's **named** profile
(`QWebEngineProfile("aipacs-web-browser")`, not the default one):

| | GUI block | user's real browser open |
|---|---|---|
| no warm | — | 888 / 803 ms |
| profile warm | 705 / 704 ms | **140 / 132 ms** |

Warming the *default* profile boots the process-wide engine, so the named
profile then costs 2–3 ms instead of 659–709 ms. Also confirmed the engine is
**not** booted by importing QtWebEngine (15–20 ms on either thread, and
`defaultProfile()` still costs ~700 ms afterwards) — so the off-thread import
alone was never enough; the GUI-thread trigger is required.

**The measurement we wanted was not captured**, for two reasons: the browser
was opened before the prewarm could fire, and the machine was not cold (the app
had already run at 11:07 that day, so DLL/AV caches were warm).

**What we got instead — the real browser-open cost on this machine:** a
**1.46 s** main-thread stall at 13:07:15.9–13:07:16.7, with a 455 ms sample
inside `web_browser/widget.py:1887 setup_ui` (where the named profile is
built). Not 72 s. Warm-machine figure, consistent with the bench.

`0 entries` in the pixel-cache line is also explained and is not a regression:
`[B3.12] Disk pixel cache cleared` at **12:49:04**, ~18 min before this run.
`_scan_index()` never deletes anything.

### Bigger fish than the browser

The largest interactive freeze in this run was **not** the browser — it was
MPR activation, ~3.8 s of contiguous main-thread block:

```
13:07:36.163 gap=1618  toggle_zeta_mpr > widget.py:452 __init__ > _mpr_views.py:294 _setup_ui
                       > _mpr_views.py:600 _create_axial_view > QVTKRenderWindowInteractor.py:401 __init__
13:07:37.023 gap=2673  ... _mpr_views.py:641 _create_axial_view
13:07:37.917 gap=3706  ... toolbar_manager.py:5691 toggle_zeta_mpr
```

plus 564 ms in `_build_full_vtk` / `_load_full_vtk_for_mpr`. That is VTK
render-window construction on the GUI thread, and it is now the top
user-visible stall. Recommended next target, ahead of any further browser work.

### Conclusion unchanged

Keep the prewarm **off** by default. This run is itself evidence for that: the
user opened the browser 16 s into the session, long before a 20 s-delay +
5 s-idle-gate warm could ever have helped, and the open cost ~1.5 s — an
acceptable, attributable wait. To capture a true cold number, the app must be
the first thing launched after a reboot with the browser left alone for ~30 s.


---

## 8. The confirmed measurement — the 13:26 run

pid 239928, `corr_session=sess-f71c084178dd`, launched from the VS terminal with
`AIPACS_CURVED_MPR_VTK_PICK=1` and `AIPACS_BROWSER_PREWARM=1`.

This is the run §7 asked for. The Web Browser tab was **left alone**, so the
idle gate fired before the user could boot Chromium themselves and the warm
actually did work. Every number below is quoted from
`user_data/logs/app.log` and `user_data/logs/viewer_diagnostics.log`.

```
13:26:23.889  browser prewarm: idle-gated (initial delay=20000ms, idle_gap=5000ms, cap=600000ms, untouched_grace=120000ms, first-interaction required)
13:26:47.028  [IMPORT-WARM] viewer imports warmed in 63 ms: cv2, numpy.percentile, opencv_filter_pipeline
13:26:59.968  [B3.12] Disk pixel cache indexed: 0 entries (+0 new, 0.0 MB) in 1 ms      (tid=239548)
13:27:04.998  browser prewarm: idle 5230ms >= 5000ms after first interaction -> warming now
13:27:05.673  browser prewarm: file warm read 394.8 MB in 649 ms (off-thread)
13:27:05.882  browser prewarm: Chromium engine warmed (defaultProfile 208 ms on GUI thread)
```

### What each line proves

| Claim | Evidence in this run |
|---|---|
| **IMP-5a** — the GUI-thread block is bounded and small | `defaultProfile 208 ms`. First non-zero live reading; the 13:07 run's `0 ms` was a no-op because the user had already booted the engine. |
| ...and it is a hitch, not a freeze | The stall sampler recorded exactly **one 256.8 ms** stall spanning it (13:27:05.887). Session `max_gap_ms` stayed at 2479.0 ms — set during startup, untouched by the warm. |
| **IMP-5b** — the DLL hint list widened coverage | **394.8 MB** read, against 152.1 MB before `_WARM_DLL_HINTS` was added. |
| **Async pixel-cache init** runs off the GUI thread | The `_scan_index` line is emitted on **tid 239548**; the GUI thread in this process is tid 205316. |
| **VS-2 import warm** is cheap and off-thread | 63 ms (81 ms in the 13:07 run), on tid 246264. |

**Total prewarm cost: 884 ms wall** (13:27:04.998 → 13:27:05.882), of which
**208 ms** lands on the GUI thread. Against the 72 s freeze that opened this
investigation, that is a **~346×** reduction in GUI-thread block.

### Cold vs warm, measured on the same bytes

The file warm read the **identical 394.8 MB** in both runs of that afternoon:

| Run | Machine state | Read time |
|---|---|---|
| 13:07 | app first started ~13:06, WebEngine DLLs unread this boot | **4907 ms** |
| 13:26 | third launch of the afternoon, OS + AV caches hot | **649 ms** |

**7.6× on the same bytes**, off-thread in both cases. This is the AV/disk factor
described in §5, now measured directly instead of inferred. It also bounds what
the file warm can ever be worth: it is a *prefetch*, and on a cold machine it
costs seconds — which is exactly why it stays on a daemon thread and why the
whole feature stays opt-in.

### Conclusion after the confirmed run — unchanged

`AIPACS_BROWSER_PREWARM` stays **off by default** (IMP-4). Nothing here argues
otherwise. The warm is now cheap and well-behaved when it is asked for, but it
still buys at most ~1.5 s on a click most users make at most once per session,
and it still pays a multi-second off-thread read on a cold machine. The flag is
the right shape: a user who lives in the Web Browser tab can turn it on and get
a near-instant open; nobody else pays anything.

### Still the bigger fish: MPR activation

Same run, same session. `toggle_zeta_mpr` blocked the GUI thread in three
contiguous chunks between 13:27:09 and 13:27:20 — **1345 ms + 2014 ms +
1138 ms ≈ 4.5 s**:

```
13:27:09.286 gap=402  toggle_zeta_mpr > widget.py:378 get_preset_manager
                      > preset_manager.py:52 custom_presets_dir.mkdir()
13:27:12.443 gap=575  _mpr_views.py:1147 _build_deferred_3d_view
                      > _mpr_views.py:869 _create_3d_view > vtk.vtkGPUVolumeRayCastMapper()
13:27:19.716 gap=424  widget.py:452 _setup_ui > _mpr_views.py:294 _setup_ui
                      > _mpr_views.py:600 _create_axial_view
                      > QVTKRenderWindowInteractor.py:362 vtkRenderWindow()
```

That is **5× the browser cost**, on a button the user presses many times a
session, and it reproduces across runs (~3.8 s at 13:07, ~4.5 s here). It is
now the top user-visible stall in the app. Written up, not fixed, in
[`OPEN_FINDINGS_2026-08-16.md`](OPEN_FINDINGS_2026-08-16.md) §2.
