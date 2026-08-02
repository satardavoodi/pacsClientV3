# "MPR on a large study crashes the app" — triage against the latest crash log (2026-08-01)

**Report:** pressing MPR on a study with many slices makes the layout collapse → expand → the
application crashes and closes.
**Verdict from the logs: the current dev build did NOT crash on any MPR open today.** Three MPR
opens on large studies all succeeded, and every session ended with a clean shutdown. The single
access violation in `native_fault.log` today belongs to a **download subprocess**, not the app.
The most probable explanation for what was observed is stated in §5.

---

## 1. What the latest crash log actually contains

`native_fault.log` last entries (2026-08-01):

| Time | pid | Fault | Verdict |
|---|---|---|---|
| 14:14:12 | **50588** | **access violation** | **NOT the app** — `app.log` proves it: `[PREWARM] spawned idle download subprocess pid=50588`. This is a download-subprocess prewarm spare (known **OPT-05**, "download subprocess spawn access violation"), unrelated to MPR |
| 14:59:29 | 47964 | `0x8001010d` | **Benign** — `RPC_E_CANTCALLOUT_ININPUTSYNCCALL`, a COM re-entrancy warning faulthandler catches; NOT fatal (this session kept running for another 19 minutes and opened MPR successfully at 15:17) |
| 15:44:21 | 46140 | `0x8001010d` | Benign, same class |
| 15:47:51 / 15:47:58 | 48340 / 55032 | (session markers only) | No fault |

The 14:14 crash thread had **no Python frame** — a pure native fault, consistent with the
subprocess-spawn issue, and its stack contains no VTK/MPR/Qt-widget frames at all.

## 2. Every MPR open today SUCCEEDED — with the OPT-48 fixes active

| Time | pid | Slices | `standard_mpr_construct_ms` | VRT |
|---|---|---|---|---|
| 11:34 | 40900 | 672 | **17 944** (pre-fix baseline) | auto-built (~9 s extra freeze) |
| 12:58 | 48500 | **716** | **1 784** | `vrt_on_demand=True` |
| 14:09 | 42072 | 400 | **1 355** | `vrt_on_demand=True` |
| 15:17 | 47964 | **716** | **2 147** | `vrt_on_demand=True` |

**OPT-48 is confirmed working on live data: 17.9 s → ~2 s on an even LARGER study (716 vs 672
slices), with `warm_scalar_range=1` and `vrt_on_demand=True` both engaged.** No crash, no
truncated log, no fault marker at any of those timestamps.

## 3. How those sessions ended (the decisive check)

A crash cannot produce the orderly shutdown markers. All three MPR sessions have them:

- pid=42072 → `Application shutdown: instance lock released`
- pid=48500 → `Released single-instance lock (PID 48500)` + `Application shutdown: instance lock released`
- pid=47964 → full sequence at 15:18:19, **74 s after** the MPR open, while the app sat idle at
  2.3 % CPU with a stable 2 232 MB RSS:
  ```
  [SHUTDOWN-INITIATOR] mainwindow.closeEvent spontaneous=False (code called close())
  [SHUTDOWN-INITIATOR] QApplication.quit() called
  [SHUTDOWN-INITIATOR] aboutToQuit reason=mainwindow_close_programmatic visible_windows=[]
  Released single-instance lock (PID 47964)
  Application shutdown: instance lock released
  ```

## 4. Checklist the report asked for — answered from evidence

| Item | Finding |
|---|---|
| MPR button activation | `toggle_zeta_mpr called` present, followed by a complete, successful open ✅ |
| Layout destruction/resizing → MPR start race | **Not observed.** The volume load is off-thread and *completes* (`async off-thread load complete`) before `StandardMPRViewer` is constructed; the construction is synchronous on the GUI thread, so it cannot interleave with a layout pass |
| VTK renderer / render-window init | `[MPR-STEP]` ladder completes through `interactor_start end` on every open ✅ |
| Volume creation / DICOM→volume | `[MPR VTK LOAD] ✓ dims=(512,512,716)` ✅ |
| Initial axial/coronal/sagittal reconstruction | All three panes built; VRT deferred on-demand (OPT-48 #4) ✅ |
| Memory allocation | Peak RSS today **3 999 MB** (pid=48500, 12:56) — high but survived; the MPR open at 12:58 succeeded |
| GPU allocation | OPT-47 budget path active; no `[MPR-VRT-BUDGET]` failure, no GPU fault |
| Thread creation | Loader + flip workers created and joined normally |
| Widget destruction/recreation during transition | No `RuntimeError: already deleted` and no teardown-race log today |
| Use-after-free of VTK/Qt object | None in evidence |
| Renderer accessed after widget destroyed | None in evidence |
| **Multiple simultaneous / double MPR init** | **Only ONE `toggle_zeta_mpr called` per open** — no double-trigger today |
| Heavy volume creation on the UI thread | Load is off-thread; scalar range + X-flip now off-thread too (OPT-48). Residual GUI-thread work = VTK render-window creation, which is unavoidable |
| Temporary duplication of the full volume | Still 2 copies (source + flipped ≈ 375 MB each at 716 slices) — the known, deliberately-deferred item |
| Race: layout reconstruction vs MPR init | No evidence in today's logs |

## 5. Most likely explanation for the observed crash — ranked

1. **The crash predates the fixes / is on a build that lacks them.** The v3.4.7 installer was built
   **2026-07-08 18:50**; today's OPT-48 Phase 1+2 and jitter fixes are **NOT in it**. On the
   pre-fix path (still what that installer ships) the same 672-slice study took **17.9 s to build
   with the GUI blocked ~30 s** and peaked near 4 GB — a window that is unresponsive for half a
   minute during a visible layout change is exactly what gets reported as "it collapsed, expanded,
   then crashed", and is also the window in which Windows may show "not responding" or a user/OS
   force-close occurs. **Re-test with a build containing today's changes before treating this as
   an open crash.**
2. **The `spontaneous=False` programmatic close.** One session closed itself 74 s after MPR while
   idle. That is not a crash (clean lock release), but it *looks* like one to the user. The
   `quit()` stack showed no Python caller, i.e. it came from Qt C++ — consistent with
   `quitOnLastWindowClosed` after something called `mainwindow.close()`. **Instrumentation gap
   closed today**: `closeEvent` now logs the full call stack whenever `spontaneous=False`, so the
   next occurrence names its caller.
3. Memory pressure at ~4 GB peak with the double volume copy — plausible on a smaller machine,
   not the cause here (the 4 GB peak session opened MPR fine two minutes later).
4. The download-subprocess access violation (OPT-05) — real, but a *subprocess*; it does not close
   the main window.

## 6. What to do next

1. **Rebuild** (`python builder\build_release.py`) so the installed build actually contains OPT-48
   — the 17.9 s → 2 s improvement alone removes the whole unresponsive window being described.
2. Reproduce on that build. If it still closes, the new `[SHUTDOWN-INITIATOR] programmatic close()
   call stack` line will name the caller, or `native_fault.log` will carry a real access violation
   **with VTK frames** (today's has none).
3. Report back with: the `[MPR-OPEN-KPI]` line, whether `Application shutdown: instance lock
   released` is present, and any `[SHUTDOWN-INITIATOR]` block.

**Bottom line: this is not currently reproducible as a crash in the dev build — it is a
layout-lifecycle/threading question that the evidence does not support, plus one unattributed
programmatic close that is now instrumented.** No speculative fix was applied to the MPR pipeline,
because the logs give no defect to fix there.
