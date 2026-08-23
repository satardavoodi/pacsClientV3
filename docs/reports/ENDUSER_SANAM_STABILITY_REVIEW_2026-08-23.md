# End-user stability review — workstation "sanam" — 2026-08-23

226 MB of application logs (2026-08-03 → 2026-08-23 10:33) plus two Windows
Event Log exports (System, 487 records; Application, 22 059 records back to
2026-05-02). Every finding below is bucketed by the app version that was
actually installed at the time, so a bug that only ever happened on an old build
is never presented as a live one.

**Read this first.** The Windows Application log arrived after the first pass and
**changed three conclusions**. Where the two sources disagree, Windows is
authoritative and this report has been corrected:

1. The post-update failure the user reported is a **hang at 00:47:02 on 3.6.2
   during patient-tab teardown** (issue **A0**, Critical) — *not* the 06:00
   disappearance, which was a workstation power loss.
2. **Three sessions I first called "clean" or "abrupt" were native crashes.**
   All three are 3.5.9, so no conclusion about the current build changes.
3. The true crash history is **47 crashes and 12 hangs since May**, not the 3 the
   app's own `native_fault.log` recorded — and the trend across versions is
   strongly downward, ending at **zero crashes on 3.6.1/3.6.2**.

The single most useful thing in this report is not any individual bug: it is that
**a 17-second hang left no trace in our own diagnostics**, because the stall probe
is a Python thread and cannot see a main thread blocked in native code holding the
GIL. Until that is fixed, absence of evidence in our logs is not evidence of
absence.

## Version timeline (from `auto_update.log`)

| when | version |
|---|---|
| 2026-07-19 20:49 | 2.4.8c → 3.5.4 |
| 2026-07-25 22:44 | 3.5.5 |
| 2026-07-27 14:46 | 3.5.6 |
| 2026-08-02 21:46 | 3.5.7 |
| 2026-08-10 10:57 | **3.5.9** — the build that covers 08-10 … 08-22 21:56 |
| 2026-08-22 21:56 | **3.6.1** |
| **2026-08-23 00:08:54** | **3.6.2 — CURRENT** |

Everything timestamped **≥ 2026-08-23 00:08:54 is the current build**. The
current build has ~6.2 hours of runtime in these logs, across two sessions.

**What is in 3.6.2.** The last commit is v3.6.0 (2026-08-16); 3.6.1 and 3.6.2
were built from the working tree (`builder nuitka/output/build_state.json`
written 2026-08-22 22:28, `builder/spec/appA_version_info.txt` → `3.6.2`). File
mtimes confirm the following fixes are **in** 3.6.2:

* MPR lifecycle release / GPU teardown (2026-08-19)
* YBR_FULL_422 colour decode (2026-08-21, `dicom_color.py` 08-21 14:25)
* Patient-list streamer back-pressure + path memo (2026-08-21 14:29)
* Download-badge off-thread, `count_subfolders_with_dicom` scandir, storage
  cleanup on a worker (2026-08-22 16:20)

So these logs are the **first field data** on all four.

## Session inventory

| pid | window | ver | lines | peak RSS | ended |
|---|---|---|---:|---:|---|
| 7084 | 08-19 12:20 → 08-22 09:24 (69 h) | 3.5.9 | 138 866 | **5 700 MB** | **crash**² |
| 26332 | 08-22 09:24 → 17:14 | 3.5.9 | 14 007 | **3 983 MB** | abrupt |
| 14684 | 08-22 15:41 → 16:05 | 3.5.9 | 2 182 | 1 370 MB | **crash**² |
| 24936 | 08-22 16:31 → 21:41 | 3.5.9 | 9 968 | 507 MB | **crash**² |
| 19540 | 08-22 21:55 → 22:11 | 3.5.9 | 868 | 810 MB | clean |
| 3584 | 08-22 22:13 → 08-23 00:06 | 3.6.1 | 3 453 | 417 MB | clean (update restart) |
| **24696** | **08-23 00:08 → 00:46** | **3.6.2** | 4 065 | 2 378 MB | **HUNG**¹ |
| **1120** | **08-23 00:47 → 06:00** | **3.6.2** | 14 642 | 2 799 MB | **host power loss** |
| 2940 | 08-23 09:34 → 10:33 | 3.6.2 | 2 406 | 814 MB | clean |

¹ **Corrected by the Windows Application log.** I first bucketed 24696 as 3.6.1
and called its ending "the 3.6.2 update restart". Both were wrong. Windows
records `Application Hang 1002` for **`AIPacs.exe 3.6.2.0`, pid 0x6078 = 24696,
at 00:47:02** — so 24696 was already running the new build (installed 00:08:54,
which is what restarted 3584) and it **stopped responding**. The
`module_install.log` bootstrap at 00:47:05 is the *recovery* launch after the
hung process was killed, not an update. This is the one real post-update
failure; see **A0** below.

² Windows `Application Error 1000` — see "The Windows Application log rewrites
part of this". All three are 3.5.9; my clean/abrupt heuristic missed them
because a `__fastfail` writes no faulthandler record.

---

## The reported post-update failure — there were TWO events, not one

The user reported that after the update the application "still crashed once and
closed unexpectedly". The logs contain **two** distinct post-update endings,
seven hours apart, with completely different causes:

| # | when | session | what actually happened |
|---|---|---|---|
| **1** | **08-23 00:47:02** | pid 24696, 3.6.2 | **The application hung** during patient-tab teardown; Windows recorded `Application Hang 1002` and the process was killed. **A real defect — see A0.** |
| 2 | 08-23 06:00:27 | pid 1120, 3.6.2 | **The workstation lost power.** The application did not crash. Not a software defect. |

Event 1 is almost certainly the one the user noticed: it happened while they
were working, right after closing a patient. Event 2 happened at 6 a.m. with the
app idle and nobody at the machine — it would only have been discovered later.

### Event 2 — the 06:00 disappearance — verdict: NOT an application crash

`pid=1120` (3.6.2) stopped at **06:00:27.016**. The evidence:

* last `app.log` line 06:00:27.016; last main-thread probe tick 06:00:26.865 —
  the event loop was alive and ticking one second before the end;
* **zero log lines in any of the four logs between 06:00:28 and 09:34:33** —
  3 h 34 min of total silence;
* **no `native_fault.log` record** for it — and faulthandler *is* working on
  this machine (it captured three faults on older builds);
* no `[SHUTDOWN-INITIATOR]` / `aboutToQuit` / instance-lock-release sequence,
  which a Windows logoff or shutdown would have produced;
* memory flat at 1 677 MB for the previous four hours, CPU 5.8 % — no OOM, no
  runaway;
* the app had been **idle since 02:11:46** (last user action).

An in-process crash leaves a faulthandler record; a Windows shutdown leaves a
close sequence. Neither is present. The pattern fits the **host suspending or
losing power at 06:00** while the app sat idle overnight.

### CONFIRMED by the Windows System log (exported 2026-08-23)

The workstation's System log (`DESKTOP-5I5KJCQ`, 487 records, 08-22 12:27 →
08-23 12:17 local; evtx stores UTC, this PC is Iran Standard Time = UTC+3:30):

| local time | event | detail |
|---|---|---|
| 04:26:39 | last System event before the silence | — |
| **05:45:00** | *(Windows' last checkpoint)* | — |
| **06:00:27** | app's last log line | — |
| — | **304 minutes with no System event at all** | — |
| 09:30:19 | `Kernel-General 12` **OS started** | LastBootId=43→44 |
| 09:30:19 | `Kernel-Boot 20` | **LastShutdownGood = false** |
| 09:30:20 | `Kernel-Power 41` **CRITICAL** | "rebooted without cleanly shutting down"; **BugcheckCode = 0** |
| 09:30:27 | `EventLog 6008` **ERROR** | "The previous system shutdown at **5:45:00 AM on 8/23/2026** was **unexpected**" |

**Verdict: the workstation lost power. The application did not crash.**

* **Not sleep.** There is no `Kernel-Power 42` and no `Power-Troubleshooter 1`
  anywhere near 06:00. The only sleep/resume pair in the entire 24-hour export is
  08-22 12:56:54 → 12:56:57, a three-second transition.
* **Not a blue screen.** `Kernel-Power 41` carries `BugcheckCode = 0`, so no
  bugcheck occurred and no memory dump was written.
* **Not a Windows shutdown.** No `Kernel-General 13`, no `User32 1074`, no
  `EventLog 6006`.
* **Not a hardware fault we can see.** In the whole 24 hours the System log holds
  exactly **1 CRITICAL, 1 ERROR and 28 WARNINGs** — and the warnings are 25 ×
  `DistributedCOM 10016` (benign permission noise), 2 × `BTHUSB 34` and 1 ×
  `Kernel-PnP 219` (a HID device). No disk timeouts, no NTFS corruption, no
  storage or thermal events.

The 15-minute gap between Windows' "5:45:00 AM" and the app's last line at
06:00:27 is expected: 6008 reports the last periodically-flushed "system alive"
timestamp, not the instant of the loss. **06:00:27 is the accurate moment** — the
application was still writing its 2-second heartbeat until then.

**Close this item.** Then, operationally: an unexpected power loss on a reading
workstation is worth chasing on its own — check whether that PC is on a UPS, on a
switched power strip someone turns off at night, or has a failing PSU. Nothing was
being written at 06:00 (the app had been idle since 02:11), so no data was at
risk this time; a loss mid-import would not be so forgiving.

---

## The Windows Application log rewrites part of this — read it

The Application log export (22 059 records, 2026-05-02 → 2026-08-23) contains
**47 `Application Error 1000` crashes of AIPacs.exe** and **12
`Application Hang 1002`** — far more than the app's own `native_fault.log` knew
about, because a `__fastfail`/abort never reaches faulthandler.

### Crash trend by version — this is the good news

| version | window | crashes | hangs |
|---|---|---:|---:|
| pre-3.5.4 | May 2 – Jul 19 (~11 weeks) | **31** | 8 |
| 3.5.6 | Jul 27 – Aug 2 (~6 days) | **10** | 2 |
| 3.5.7 | Aug 2 – Aug 10 | 2 | 1 |
| 3.5.9 | Aug 10 – Aug 22 | 4 | 1 |
| **3.6.1 / 3.6.2** | Aug 22 21:56 → Aug 23 12:08 | **0** | **1** |

3.5.6 was the worst build on this machine — 8 of its 10 crashes fell between
07-31 and 08-02. 3.5.7 fixed most of that. **The current build has crashed zero
times.**

### Faulting-module signature — one bug dominates

| n | module | exception | meaning |
|---:|---|---|---|
| 19 | `Qt6Core.dll` | `c0000409` | STATUS_STACK_BUFFER_OVERRUN — a `__fastfail`, i.e. `qFatal`/abort/`std::terminate` |
| 18 | `pyside6.abi3.dll` | `c0000005` | access violation, **almost all at the same offset `0x1bbd8`** |
| 3 | `vtkCommonCore-9.6.1.dll` | `c0000005` | access violation at `0x1de9770` — the MPR/3D path |
| 2 | `shiboken6.abi3.dll` | `c0000005` | |
| 2 | `Qt6Core.dll` | `c0000005` | |
| 1 each | `ucrtbase.dll`, `Qt6Widgets.dll`, `ntdll.dll` | | |

An access violation recurring at a **constant offset in pyside6.abi3.dll from May
through August** is one bug, not eighteen: the classic PySide6 failure of
invoking a Python slot on a C++ object that has already been deleted, inside a Qt
event dispatch where the exception cannot propagate. The `vtkCommonCore` three
(2026-08-03, 08-08 and **08-11 on 3.5.9**) are the VTK teardown class that the
2026-08-19 MPR lifecycle release targets — and none have recurred since.

### Windows' own leak detector has been flagging us

`Windows Error Reporting 1001 / RADAR_PRE_LEAK_64` fired for AIPacs six times —
versions 3.1.3.0, 3.4.1.0, **3.5.6.0 (2026-07-30, the last one)** and the legacy
`AI PACS Viewer.exe 1.0.79.0`. That is Windows independently detecting runaway
memory growth, and it corroborates P1. No RADAR event on 3.5.7, 3.5.9 or 3.6.x.

### Correction: three sessions I called "clean" actually crashed

My clean/abrupt call was a heuristic — "does the tail hold a shutdown marker" —
and for these it was **wrong**. Windows is authoritative:

| session | I said | Windows says |
|---|---|---|
| pid 7084, ended 08-22 09:24:05 (69 h, 5 700 MB) | clean | **crash** 09:24:06 `Qt6Core c0000409` |
| pid 14684, ended 08-22 16:05:38 | abrupt | **crash** 16:05:39 `pyside6 c0000005` ✔ |
| pid 24936, ended 08-22 21:41:42 | clean | **crash** 21:41:42 `Qt6Core c0000409` |

All three are 3.5.9. It does not change any conclusion about the current build,
but the session table above should be read with this correction.

---

## The stall numbers are a trap — read this before acting on them

Raw counts say 3.6.2 stalls 100× more than 3.5.9. That is **wrong**, and here is
why. Stall threshold is identical (100 ms) on every version, so the comparison is
fair — but the exposure is not:

| pid | ver | total | startup | steady | steady/h | median | worst |
|---|---|---:|---:|---:|---:|---:|---:|
| 26332 | 3.5.9 | 321 | 9 | 312 | 40.1 | 168 | 1 707 |
| 14684 | 3.5.9 | 64 | 33 | 31 | 88.9 | 210 | 1 883 |
| 24936 | 3.5.9 | 117 | 8 | 109 | 21.3 | 373 | 1 532 |
| 24696 | 3.6.2¹ | 85 | 11 | 74 | 126.1 | 168 | 1 188 |
| **1120** | **3.6.2** | 1 638 | 11 | 1 627 | **314.7** | 395 | 1 703 |
| **2940** | **3.6.2** | 24 | 11 | 13 | **14.0** | 215 | 5 417 |

¹ Corrected from 3.6.1 — Windows records this session as `AIPacs.exe 3.6.2.0`.
**And note what this row does not show:** pid 24696's worst recorded stall is
1 188 ms, yet this is the session that hung for 17 seconds (A0). The probe
missed it entirely.

`pid=1120` hour by hour:

| hour | stalls | stalled ms | app activity | CPU |
|---|---:|---:|---|---:|
| 00 | 33 | 9 518 | startup | 23.3 % |
| 01 | 86 | 17 938 | real work (MPR, reports) | 20.2 % |
| 02 | 9 | 3 239 | last user action 02:11:46 | 6.8 % |
| **03** | **425** | **159 862** | **nothing but heartbeats** | 5.8 % |
| **04** | **556** | **211 696** | **nothing** | 5.9 % |
| **05** | **526** | **199 713** | **nothing** | 5.9 % |
| 06 | 3 | 1 223 | dies 06:00:27 | 5.8 % |

**1 507 of the 1 638 stalls happened between 03:00 and 05:59, with the
application doing nothing at all.** An idle Qt app cannot block itself for
200 seconds an hour while executing no code. 303 of the 331 steady-state
sampled stacks show nothing below `qasync run_forever`. The duration histogram
is a spike of **1 475 samples in the 200–500 ms band and zero above 3 s**.

An idle application executes no code, so it cannot block itself: whatever the
mechanism, these are **not** the app blocking the GUI thread. It is a
**diagnostics defect, not a performance defect**.

**Honest caveat on the mechanism.** I first attributed this to OS
descheduling / power management. The Windows System log does **not** support
that: the only `Kernel-Processor-Power 55` records are the twelve boot-time
processor enumerations at 09:30:22, not throttling, and there are no thermal or
power-limit events at all in the overnight window. The one suggestive record is
`Kernel-Power 566` at **03:11:57** (a power-session transition) — the storm
begins in that same hour. So the exact cause is **unproven**.

**And a hypothesis worth watching.** The storm ran 03:00–05:59 and the machine
suffered an unexpected power loss at ~06:00. Those may be independent, or the
storm may have been an early symptom of the same failure. **If the stall storm
recurs on that PC and is again followed by a power loss, treat it as hardware,
not software** — that is a cheap and decisive test.

The honest comparison is the daytime, actually-used 3.6.2 session: **`pid=2940`
at 14.0 steady stalls/hour — the best session in the entire dataset**, against
21–89/h on 3.5.9. On real usage 3.6.2 is measurably better, which is consistent
with the four fixes landing.

(The only 3.6.1 session, pid 3584, produced no retained stall data; the 126/h row
belongs to 3.6.2, not 3.6.1, so there is no 3.6.1-vs-3.6.2 comparison to draw.)

---

## Classification

### Still reproducible / active — fix these

| # | issue | severity |
|---|---|---|
| **A0** | **Patient-tab teardown hangs the GUI thread — took the app down on 3.6.2** | **Critical** |
| ~~**A1**~~ | ~~Oblique MPR geometry~~ → **RECLASSIFIED: no geometry defect.** The MPR diagnostic validator is stale (written 2026-02-17, never updated for v1.09.Fix-E) and measures the camera's plane instead of the mapper's. Fix the validator. | Medium (diagnostics) |
| **A2** | Login blocks the GUI thread on a socket read — up to 5.4 s every launch | **High** |
| **A3** | Attachment fetch: 15 s hang per study open when the server refuses | **High** |
| **A4** | Report save posts to the API on the GUI thread — 1.4 s freeze | Medium |
| **A5** | Stall probe: noisy (~500×/h on an idle app) **and blind — it cannot see a native GIL-held block, which is how A0 left no trace** | **High** |
| **A6** | `_run_deferred_close_gc` runs GC on the GUI thread on patient close — **now folded into A0** | Medium |
| **A7** | MPR construction still costs 0.5–0.6 s on the GUI thread | Medium |
| **A8** | `notify() skipped malformed dispatch` — a QEvent passed where a QObject belongs | Medium |

### Possibly active — needs one more data point

| # | issue | why uncertain |
|---|---|---|
| **P1** | Long-session memory growth (5 700 MB peak on a 69 h 3.5.9 session) | 3.6.2's longest session is 5 h and ended flat at 1 677 MB. The MPR lifecycle fix is in 3.6.2 but has not seen a multi-day session yet. **Windows corroborates the history**: `RADAR_PRE_LEAK_64` fired 6× for AIPacs, last on 3.5.6 (2026-07-30), none on 3.5.7 or later. **But pid 24696 hit 2 378 MB in 38 minutes on 3.6.2** and then hung — so the ramp is not gone, and P1 now feeds A0. |
| **P2** | `❌ Search returned None` (6× on 3.6.2) | Correlates with the same window as the network refusals; may be the same root cause. |

### Likely fixed by 3.6.x — do not spend time here

* **Native crashes.** The app's own `native_fault.log` knew of 3; the Windows
  Application log knows of **47 crashes and 12 hangs** since May. The trend is
  what matters: 31 pre-3.5.4 → 10 on 3.5.6 → 2 on 3.5.7 → 4 on 3.5.9 →
  **0 crashes on 3.6.1/3.6.2**. The dominant signature —
  `pyside6.abi3.dll c0000005` at a constant offset, 18 times from May to August
  — has not recurred since 3.5.9. Do not chase these blind; if one recurs on
  3.6.x that is new information and worth a crash dump. **The one 3.6.x
  exception is the hang, which is A0 — not a crash.**
* **`WinError 10054` (connection reset by peer)** — 204 / 220 / 37 on
  3.5.6 / 3.5.7 / 3.5.9 → **14** on 3.6.2.
* **`reconnect` churn** — 813 on 3.5.9 → **21** on 3.6.2.
* **`Traceback` occurrences** — 404 / 381 / 293 on the 3.5.x line → **21** on 3.6.2.
* **GUI-thread patient-list disk scanning** — the 3.5.9 stall stacks are full of
  `toggle_zeta_mpr` / `build_or_get_mpr_volume` / `_load_full_vtk_for_mpr`
  (7–8 samples each); on 3.6.2 those drop to 2 and the list-render paths fixed on
  08-21/08-22 do not appear at all.

### Historical / no longer relevant

* Everything before 3.5.9 (2026-08-10). The retained `viewer_diagnostics` files
  only cover 08-22 onward anyway, so pre-3.5.9 stall data does not exist here.
* The two 2026-07 native faults (one at 2026-07-18 19:10, pre-3.5.4).

---

## Active issues in detail

### A0 — Patient-tab teardown hangs the GUI thread (the real post-update failure)

**Severity: Critical.** This is the only defect in this dataset that actually
took the current build down, and it is invisible to every diagnostic we have.

**Evidence.** Windows Application log:

```
Application Hang 1002 — AIPacs.exe 3.6.2.0 — pid 0x6078 (24696)
2026-08-23 00:47:02 — hang type 41 (top-level window stopped responding)
```

The app's own logs stop **17 seconds earlier, at 00:46:45**. In the 2 698 lines
covering 00:45:00–00:47:30, the last thing the application does is **close a
patient tab**:

| time | line |
|---|---|
| 00:46:44 | `[VOICE-DELETE-GUARD] kept saved voice on non-user teardown` |
| 00:46:44 | `[B3.4_DIAG] BRIDGE_CLEANUP bridge=bfb250 viewer=q14680 slice=68` |
| 00:46:44 | `[B3.4_DIAG] BRIDGE_CLEANUP bridge=bfa5d0 viewer=q27f80 slice=134` |
| 00:46:44 | `[ZetaBoost] INACTIVE clear_cache=True` |
| 00:46:44 | `[ZetaBoostDisk] CLEAR_TAB` |
| 00:46:44–45 | **`[SEED_CONFIG]` × 8 in one second** |
| 00:46:45 | `[Socket] pooled connection has 1+ unread byte(s) (stream desync) — discarding` |
| 00:46:45 | `[ino-approval] reception=55359` |
| — | **nothing further; process killed** |

Then `module_install.log` bootstraps at 00:47:05 and pid 1120 starts at 00:47:13
— i.e. the process was killed and relaunched, which is what the user saw.

**Why our diagnostics missed it — both of them, structurally.** In that same
window the probe recorded only **100 ms and 202 ms**. Reading `main.py` explains
why, and it is worse than "the probe is noisy":

* **F8 `[MAIN_THREAD_STALL]`** is a `QTimer` **on the main thread**. It computes
  `now - last_fire_ms` *when it next fires*, so it can only ever report a stall
  that **ended**. A block that runs until the process is killed is never
  reported at all. pid 24696's worst recorded stall is 1 188 ms — for a session
  that hung for 17 seconds.
* **F11 `[MAIN_THREAD_STALL_TRACE]`** is the one that *should* have caught it: a
  daemon thread that samples the main thread's stack once the gap exceeds
  400 ms, without waiting for the block to end. But it is a **Python** thread,
  so it cannot execute at all while the main thread holds the GIL inside a long
  C call. `gc.collect()` over a multi-GB heap, a VTK render-window destructor, a
  GPU driver call — no bytecode boundary, no GIL release, no sample.

**The silence is itself the evidence: the block was native and held the GIL.**

**Root cause — now grounded in the source, not inferred from log order.** I read
the close path. It has exactly **one** step that is unlogged, unbounded and
GIL-holding, and it is not the one I first guessed:

```python
# _pw_lifecycle.py
def _run_deferred_close_gc():
    _CLOSE_GC_PENDING[0] = False
    try:
        gc.collect()          # <- no log line, no bound, holds the GIL throughout
    except Exception:
        pass
```

**The 2026-06-27 "patient-close GUI-freeze fix" moved this freeze; it never
shortened it.** Its own comment says so: a synchronous `gc.collect()` on the GUI
thread cost "up to ~3.7 s freeze on EVERY patient close", and the fix was to run
the *same* collect 150 ms later via `QTimer.singleShot` so the close *returns*
instantly. The collect still runs on the GUI thread — deliberately, because VTK
render windows can only be destroyed there — it just runs a moment afterwards.
150 ms after closing a patient the user is still sitting in front of the screen.
pid 24696's heap was **2 378 MB** of volumes and VTK wrappers when it collected.

Everything else on that path is either logged or bounded:

| step | logs? | verdict |
|---|---|---|
| `qt_viewer_bridge.cleanup` | yes — but the `BRIDGE_CLEANUP` line is emitted **first**, before `pipeline.shutdown()` and `qt_viewer.clear()` | still a candidate; the log proves entry, not completion |
| `ZetaBoostDisk.clear_tab` | yes — `CLEAR_TAB tab=… removed=N` is emitted **last** | **it completed.** Not the blocker this time, though it is still sqlite + up to 2 `unlink()` per cached slice on the GUI thread |
| `seed_user_config_defaults` | yes, 8× | each one completed; a directory walk per call, not a 17 s block |
| **deferred `gc.collect()`** | **no** | **only step that can vanish silently** |

The three `vtkCommonCore-9.6.1.dll c0000005` crashes at offset `0x1de9770`
(08-03, 08-08, 08-11) belong to the same teardown family: a crash and a deadlock
are the two failure modes of the same unsafe VTK destruction, and a GC is what
triggers that destruction. **A6 is not a separate Medium item — it is A0.**

**Contributing factor.** pid 24696 reached **2 378 MB in 38 minutes** — the
fastest memory ramp in the dataset. A large heap makes both the GC pause and the
VTK teardown longer, so this may be why the window that is normally survivable
became a hang here.

**How to reproduce.** Open a patient with **two or more viewer bridges** and MPR
active, let memory build (large series, several series switches), then close the
patient tab. Repeat. The 3.6.2 log shows the same teardown sequence completing
successfully many times before this one hung, so expect it to be intermittent
and load-dependent — script the loop rather than trying by hand.

**What has landed (2026-08-23).** Observation first — the next field log has to
be able to name the blocking step instead of stopping mid-sentence.

| change | file | kill switch |
|---|---|---|
| `hang_watchdog` — arms `faulthandler.dump_traceback_later`, whose timer runs on a **native** thread, so it dumps every thread's stack *while the GIL is held*. `exit=False`: it observes, it never aborts. | `PacsClient/utils/native_fault_log.py` | `AIPACS_HANG_WATCHDOG` (+`_SECONDS`, default 5) |
| `_close_step()` — breadcrumb **before** each close step and elapsed-ms after, with the watchdog armed around it. The `start` line is the load-bearing half: a step the process dies inside is now identifiable by having a start and no done. | `_pw_lifecycle.py` | `AIPACS_CLOSE_PATH_TIMING` (+`_WARN_MS`, default 250) |
| The deferred `gc.collect()` and the whole synchronous `exit_patient_widget` teardown now run inside `_close_step`. | `_pw_lifecycle.py` | same |
| `seed_user_config_defaults` memoised per resolved `(src, dst)` — eight callers, one directory walk. Five `_config_root()` helpers were calling it on **every** feature-flag read. | `aipacs_runtime.py` | `AIPACS_SEED_CONFIG_ONCE` |

The watchdog is not a heuristic: `tests/code/system/test_close_path_hang_visibility.py`
asserts behaviourally that a 1.2 s block under a 0.2 s watchdog **writes a real
stack dump to `native_fault.log`**, and that a block which completes writes
nothing. 26 guards, **all 26 fail on the pre-fix tree** (proved by
`tools/analysis/oneoff/verify_close_path_guard_fails_prefix_2026_08_23.py`, which
removes only the A0 additions — a blanket `git show HEAD:` would have reverted
389 lines of unrelated uncommitted work in `aipacs_runtime.py` and "passed" for
the wrong reason).

**Deliberately NOT changed yet, and why.**

* **`ZetaBoostDisk.clear_tab` stays on the GUI thread.** I had recommended
  moving it; reading it changed my mind for now. Its log line is emitted *last*,
  so it demonstrably completed during the incident, and moving it off-thread
  introduces a real race — a tab reopened under the same key could have its
  fresh entries deleted by a late clear. It also has a plugin-payload mirror
  that would have to move with it. Instrument, then decide.
* **The GC itself is untouched.** Making the collect cheaper (generational
  instead of full, or budgeted) is a behavioural change to a path that exists
  precisely to destroy VTK render windows on the GUI thread. That deserves the
  measurement first.

**Next, once a field log comes back with `[CLOSE_PATH]` lines.** If the
watchdog's dump lands inside `gc.collect()`, the fix is to stop doing a *full*
collect on the close path. If it lands in `pipeline.shutdown()` or a VTK
destructor, the fix is to re-enter the event loop between bridge teardowns
rather than destroying both inside one slot.

**How to verify the eventual fix.** A 200-iteration open/close loop on a
two-bridge MPR patient: no `[CLOSE_PATH] … done` line above the warn threshold,
no watchdog dump in `native_fault.log`, and no growth in peak RSS across the
loop.

**Honest caveat.** That `gc.collect()` is the *only* silent unbounded GIL-holding
step on the close path is now established from the source. That it is what
actually hung pid 24696 is still **inference** — the watchdog exists so the next
occurrence answers it instead of me guessing.

### A1 — Oblique MPR: the coronal/sagittal camera is not on the crosshair

**Evidence.** 1 175 `[MPR_DIAG] … FAILED` detail lines on 3.6.2, **zero on
3.5.9**:

| n | check | measured | threshold | meaning |
|---:|---|---:|---:|---|
| 557 | `sagittal.focal_at_crosshair` | **52.58 mm** | 2.00 mm | camera looks 52.6 mm away from the crosshair |
| 489 | `coronal.focal_at_crosshair` | **39.80 mm** | 2.00 mm | camera looks 39.8 mm away |
| 101 | `coronal.parallel_scale` | **64.36 %** | 1.00 % | unexpected zoom jump |
| 24 | `sagittal.plane_containment` | **17.51 mm** | 0.50 mm | crosshair centre is off the displayed plane |
| 4 | `coronal.plane_containment` | **27.98 mm** | 0.50 mm | same, coronal |

Triggers are `oblique:coronal` and `oblique:sagittal` — this fires when the
crosshair is rotated into an oblique orientation.

> ## ⚠️ SUPERSEDED — read this box before acting on anything in A1
>
> I wrote the "probable root cause" and "recommended fix" below from the log
> alone. **Then I read the code and the prior documentation, and both were
> wrong.** The corrected analysis is
> `docs/plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`.
>
> **1. The recommended fix would have caused a regression.** "Re-set
> `camera.SetFocalPoint(crosshair_world_centre)`" is exactly what v1.09 did, and
> it was deliberately reverted by **v1.09.Fix-E**, which switched the oblique
> path from repositioning the camera to setting an explicit `vtkPlane` on the
> mapper — *"the camera stays in its original orthogonal position, so the
> viewport is perfectly stable"*. Re-implementing it re-introduces the
> image-pans-while-you-rotate defect and breaks at least six guard tests.
>
> **2. There is no clinical defect.** In oblique mode the mapper runs
> `SliceFacesCameraOff()` + `SliceAtFocalPointOff()` and takes its plane from
> `plane.SetOrigin(self.current_position)` — the crosshair centre. **The
> displayed plane passes through the crosshair by construction.**
>
> **3. The 1 147 failures are a stale validator.** `validate_after_oblique`
> builds its snapshots from `renderer.GetActiveCamera()` and measures the
> *camera's* plane. Since Fix-E the camera no longer defines the displayed
> slice. The validator header reads `Version: 2026-02-17` — it encodes the
> pre-Fix-E design and was never updated.
>
> Every count below is explained without any geometry being wrong:
> `focal_at_crosshair` (1 046) is Fix-E working as designed; `plane_containment`
> (28) is the camera focal being one frame stale on `rotate`, which skips
> `_update_slice_positions`; `parallel_scale` (101) is the user's own zoom
> against a baseline captured at view creation and never refreshed.
>
> **A1 is a diagnostics defect. Fix the validator, not the geometry.**

**Root cause (as first written — see the box above, this is wrong).** The oblique
rotation path updates the reslice axes but does not re-derive the camera focal
point / parallel scale from the new crosshair centre, so the coronal and sagittal
panes render a plane that is up to 28 mm away from where the crosshair says it
is, at a 64 % different zoom.

**Module.** `modules/mpr/zeta_mpr/` — the crosshair-rotation → camera-sync path.
The validator itself is `mpr_diagnostic_validator.py`.

**Is this a 3.6.x regression? MEASURED: no — the comparison was
exposure-confounded.** I said "probably not" on the strength of an empty
`git diff`; that was the right instinct for the wrong reason, and the numbers
now settle it
(`tools/analysis/oneoff/enduser_sanam_mpr_exposure_2026_08_23.py`):

| build | log lines | MPR opens | lines mentioning `oblique` | `MPR_DIAG` PASS | `MPR_DIAG` FAILED |
|---|---:|---:|---:|---:|---:|
| 3.5.9 | 253 921 | 8 | **7** | 0 | **0** |
| 3.6.1 | 4 505 | 0 | 0 | 0 | 0 |
| 3.6.2 | 82 383 | 7 | **1 152** | 0 | **1 147** |

**3.5.9 opened MPR just as often (8 vs 7) and produced almost no oblique
activity at all — 7 lines against 1 152, a 165× difference.** The validator did
not run and pass on 3.5.9; it had essentially nothing to validate. "Zero
failures on 3.5.9" is an **absence of measurement**, not a clean bill of health,
and comparing it to 3.6.2 was comparing a build that was used obliquely against
one that was not.

Two corrections that follow from reading the validator source:

* **"0 passes" is not alarming.** `mpr_diagnostic_validator.py` logs violations
  at WARNING always but logs passes only under `ZETA_MPR_DIAG=1`. A silent run
  is a clean run.
* **The git-diff argument was also weaker than I stated.** The zeta_mpr delta
  between 3.5.9 and 3.6.2 is not empty in the *working tree* — it is +147 lines
  across `_mpr_layout`, `_mpr_series`, `_mpr_views` (3.6.1/3.6.2 were built from
  the working tree, not from a commit). I read that diff: it is `_mpr_step`
  brackets, an `[MPR-MEM]` probe, and re-pointing the 3D volume mapper on series
  switch. **None of it touches camera or crosshair geometry** — so the
  conclusion stands, but now on evidence rather than on a diff that was
  measured against the wrong baseline.

**Severity: re-ranked, and the headline number was the wrong one to lead with.**
Reading the checks, the 1 046 `focal_at_crosshair` failures and the 28
`plane_containment` failures are **not the same kind of problem**:

* `focal_at_crosshair` measures the full 3-D distance from the camera's focal
  point to the crosshair. A pure **in-plane pan** produces a large value while
  the displayed slice is still the correct plane — visible as off-centre framing,
  not as the wrong anatomy.
* `plane_containment` measures `dot(crosshair − focal, view_direction)` — the
  component **perpendicular to the slice**. A non-zero value means the pane is
  showing a plane that is *not* the one the crosshair marks. **That is the
  clinical defect**, and it fired **28 times** (24 sagittal at 17.51 mm, 4
  coronal at 27.98 mm), not 1 175.
* `coronal.parallel_scale` (101 × 64.36 %) is a zoom jump: distracting, not
  unsafe.

So: **High severity for the 28 `plane_containment` events; Medium for the rest.**
Chasing 1 175 as one number would have put the effort in the wrong place.

**Recommended fix.** In the oblique-rotation handler, after the reslice axes are
set, re-set `camera.SetFocalPoint(crosshair_world_centre)` and recompute
`ParallelScale` from the new plane extent, for every non-primary view — then let
the validator confirm.

**How to verify.** Run with `ZETA_MPR_DIAG=1` so passes are logged too — without
it the validator is silent on success and you cannot tell a fixed run from a run
that never exercised the path, which is exactly the trap that made 3.5.9 look
clean. Then open an MPR, rotate the crosshair obliquely, and confirm
`[MPR_DIAG] oblique:coronal` / `oblique:sagittal` report `ALL PASSED (12 checks)`.
**Verify `plane_containment` first** — it is the check that maps to the clinical
defect; `focal_at_crosshair` can stay non-zero for a benign in-plane pan.

No 3.5.9 comparison run is needed: the regression question is already settled
above by exposure counts.

**Still open, and worth its own look.** Why did oblique activity jump from 7
lines on 3.5.9 to 1 152 on 3.6.2 across a near-identical number of MPR opens?
Either the user's workflow changed on 08-23, or something in 3.6.x makes the
oblique path engage (or log) far more readily. That is a different question from
the geometry, and answering it first would tell us how much this defect is
actually being hit in the field.

---

### A2 — Login blocks the GUI thread on a blocking socket read

**Evidence.** The worst stall in the whole dataset, on the current build:

```
2026-08-23 09:34:54  gap = 5 417 ms   (also 4 465 / 3 458 / 2 451 / 1 444 ms)
  app_handler.py:923  <lambda>
  app_handler.py:950  _complete_login
  app_handler.py:994  _authenticate_with_socket
  socket_client.py:475  login
  socket_client.py:610  send_request
  socket_client.py:744  _send_request_once
  socket_client.py:959  _safe_recv
  socket.py             readinto
```

**Root cause.** `_authenticate_with_socket` performs a synchronous
request/response on the GUI thread; the freeze is exactly the server's round-trip
time, unbounded.

**Module.** `PacsClient/app_handler.py` + `modules/download_manager/network/socket_client.py`.

**Trigger.** Every application launch. It is the first thing the user sees.

**Severity: High** — reproducible on demand, worst measured 5.4 s.

**Recommended fix.** Run `login()` on a worker and deliver the result to the GUI
thread by signal — the same pattern already used for `statusFlagsReady` in
`patient_table_widget`. Show a determinate "Signing in…" state while it runs.
Add a socket timeout so an unreachable server fails in seconds, not indefinitely.

**How to verify.** Launch with the server unreachable; the window must stay
responsive and the stall probe must record no gap > 300 ms in the login window.

---

### A3 — Attachment fetch hangs a study open for 15 seconds

**Evidence.** On 3.6.2, `phase=attachments_*` duration:

| version | n | median | p90 | max |
|---|---:|---:|---:|---:|
| 3.5.9 | 150 | 444 ms | 1 634 ms | 5 474 ms |
| **3.6.2** | 44 | 494 ms | **13 292 ms** | **15 468 ms** |

with, every time:

```
[FAST-OPEN-TRACE] phase=attachments_error t_ms=15370.1
  error=[WinError 10061] No connection could be made because the target machine actively refused it
[THREAD] Error downloading attachments: [WinError 10061] …
```

`WinError 10061` count: 12 on 3.5.9 → **161 on 3.6.2**.

**Root cause.** Two parts. (a) The attachment endpoint is refusing connections
from this workstation — a server or configuration problem, not application code.
(b) The client waits ~15 s before giving up, where 3.5.9 gave up inside 5.5 s.
A refused connection (10061) is an *immediate* TCP RST — a 15 s wall means
retries or a long connect timeout stacked on top.

**Module.** `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`
(`_worker`), plus whatever sets the attachment client's timeout/retry policy.

**Trigger.** Every study open on that workstation.

**Severity: High** — it is on a background thread so the UI survives, but the
open flow waits on it.

**Recommended fix.** First, check the attachment server host/port that 3.6.x
resolves on this PC against 3.5.9 — a config change is the most likely reason the
count went 12 → 161. Then cap the attachment fetch: connection refused should
fail immediately and the study should open without attachments, with a single
warning rather than three ERRORs per open.

**How to verify.** Point at an unreachable attachment host; the study must open
in under 1 s with one warning.

---

### A4 — Report save posts to the API on the GUI thread

```
2026-08-23 02:11:04  gap = 1 425 ms
  reception_data_tab.py:1365  <lambda>
  reception_data_tab.py:1648  _on_report_saved
  reception_data_tab.py:1722  _save_report_to_api
  requests/api.py post → urllib3 → http/client.py:1430 getresponse → socket readinto
```

**Module.** `modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py`.
**Trigger.** Saving a report. **Severity: Medium** — freeze length is the
server's response time, unbounded.
**Fix.** Move `_save_report_to_api` to a worker; report success/failure by
signal. **Verify.** Save a report against a slow endpoint; no stall > 300 ms.

---

### A5 — The stall probe reports ~500 false stalls per hour on an idle app

**Evidence.** Section above: 1 507 stalls in three hours with zero application
activity, 200–500 ms each, no frame below `run_forever`. It also drives log
volume — `viewer_diagnostics.log.1` holds **31 341 lines in 44 minutes**, and the
file rotated four times in one day.

**Module.** `main.py` `_f11_sampler` / `aipacs.main_thread_probe`.
**Severity: Medium** — no user impact, but it makes every future log review
harder and it is what made this build look 100× worse than it is.
**Fix.** Suppress stall reporting when no Qt event has been dispatched since the
previous tick (a genuinely idle loop), or require two consecutive over-threshold
samples with a non-empty application stack. Keep raw counts in a periodic
summary line instead of one record per event.
**Verify.** Leave the app idle for one hour: expect a handful of records, not 500.

---

### A6 — `_run_deferred_close_gc` on the GUI thread

`_pw_lifecycle.py:40` — 3 steady-state stalls up to 541 ms on 3.6.2; it was the
second most common innermost frame on 3.5.9 (15 samples). Explicit garbage
collection on the GUI thread when a patient tab closes.
**Severity: Medium.** **Fix:** run the collection from an idle callback with a
time budget, or drop the explicit `gc.collect()` and rely on the now-explicit
MPR/VTK release added on 2026-08-19. **Verify:** close a patient with an MPR
open; no stall > 200 ms.

---

### A7 — MPR construction cost

`_create_sagittal_view` 593 ms, `_build_full_vtk` / `_load_vtk_paths_responsive`
530 ms, `QVTKRenderWindowInteractor.__init__` — all on 3.6.2, all on the GUI
thread. Much reduced from 3.5.9 (7–8 samples per frame there, 2 now) but not
gone. **Severity: Medium.** Known work, already instrumented by `[MPR-STEP]`.

---

### A8 — `notify() skipped malformed dispatch`

```
aipacs.crash.notify: notify() skipped malformed dispatch:
  receiver=QEvent event=QEvent  ('PySide6.QtWidgets.QApplication.notify' called with wrong argument types)
```

5 occurrences on 3.6.2, **none on any earlier build in these logs**. A `QEvent`
is being passed where a `QObject` receiver belongs. The guard is doing its job —
it skips the dispatch instead of crashing — but this is precisely the shape of
call that produces an access violation when unguarded. **Severity: Medium.**
**Fix:** log the full stack on the first occurrence per process so the caller can
be identified. **Verify:** the message stops appearing.

---

## Other observations

* **`[VOICE-DELETE-GUARD] kept saved voice on non-user teardown`** — 44 on 3.5.9,
  14 on 3.6.2. The guard is working; the frequency suggests voice recordings are
  routinely being torn down non-interactively.
* **`[KPI] TTSSD … ttssd_ms=-1.0 widget_creation_ms=-1.0`** — 138 times on 3.6.2.
  The series-switch KPI is recording sentinel values; that instrumentation is
  currently blind.
* **`[CPU_BUDGET] SetPriorityClass failed (err=6)`** — `ERROR_INVALID_HANDLE`,
  twice per launch. Harmless but the call is wrong.
* **`[MULTI-STUDY LOAD] key=N slot=N out of range (ordered_studies=1)`** — twice;
  the loader falls back to the primary path.
* The user runs the app for **days at a time** (one 69-hour session). Any leak
  compounds; worth a deliberate 48-hour soak on 3.6.2 before closing P1.

## Suggested order of work

1. **A0** — it is the only defect that took the current build down, and step one
   is reading the close path, which is cheap. Its two independent sub-fixes (stop
   seeding config 8× on close; move `CLEAR_TAB` off the GUI thread) can land
   immediately regardless of what the instrumentation later shows.
2. **A5 + the A0 watchdog together** — right now a GIL-held block is invisible to
   us, which is how a 17-second hang left no trace. Fixing this once makes every
   future field log trustworthy, including the verification of everything below.
3. **A3** — 15 s per study open is the biggest thing the user actually feels.
4. **A2** — 5.4 s on every launch, and the fix is a known pattern.
5. **A1 (validator only)** — cheap, and it stops 1 147 false WARNINGs per session
   from masking a real one. **Do not touch MPR geometry**; see
   `docs/plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`.
6. **A4**, **A8**, then **A7**. (**A6** is folded into A0.)

Do **not** open work on: native crashes, socket resets, reconnect churn, the
3.5.9 patient-list freezes, or the 06:00 disappearance — the evidence says all of
those are either fixed in 3.6.x or not application defects. **The post-update
failure worth working is the 00:47 hang, not the 06:00 power loss.**

## Diagnostics used (all read-only, `tools/analysis/oneoff/`)

`enduser_sanam_review_2026_08_23.py` (versions, sessions, error sources) ·
`enduser_sanam_faults_2026_08_23.py` (native faults, endings, stalls) ·
`enduser_sanam_deep_2026_08_23.py` (the vanished session, memory, network) ·
`enduser_sanam_stallshape_2026_08_23.py` (stall coverage, startup vs steady) ·
`enduser_sanam_pid1120_2026_08_23.py` (the overnight hour-by-hour profile) ·
`enduser_sanam_warnings_2026_08_23.py` (warning/error inventory) ·
`enduser_sanam_mprdiag_2026_08_23.py` and
`enduser_sanam_mprfail_detail_2026_08_23.py` (the MPR validator failures) ·
`enduser_sanam_hang24696_2026_08_23.py` (the 00:47 hang window, line by line).

**Windows Event Log exports** (read with the `evtx` Rust reader, not
`python-evtx`, whose `hexdump` dependency fails to build on this machine):

* `sanam pc log.evtx` — System log, 487 records, 08-22 12:27 → 08-23 12:17.
  Proved the 06:00 power loss.
* `app log.evtx` — Application log, 22 059 records, 2026-05-02 → 08-23 12:08.
  Proved the 47 crashes / 12 hangs, the version trend, the faulting-module
  signature, and the 00:47 hang that is A0.

Both are UTC; this workstation is Iran Standard Time (UTC+3:30) and every local
time in this report has been converted.
