# Impatient-User Stress Test — 2026-06-04 (01:15–01:29)

Agent-driven GUI stress test of the **source build** (python PID 174976, started 01:11:18,
includes the 2026-06-03 disk_pixel_cache copy-at-enqueue fix). Proxifier off. Baseline
`native_fault.log` = 528,733 bytes.

## 1. Tests performed (all agent-driven via computer control)

1. **Thumbnail churn (Home):** 7 rapid single-clicks across 5 patients, 0.3–0.5 s apart,
   clicking new patients before the previous right-panel load finished.
2. **Open under churn:** double-click 44868 (2,197 img CT) while the right panel was mid-load.
3. **Drag before download:** dropped Series 201/202 into both viewports while the study was
   still downloading; re-dropped the in-flight 424-image series onto an occupied viewport;
   stack-dragged through slices during active download.
4. **Second patient under load:** opened 44915 (2,453 img) while 44868 still downloading;
   dropped 2 series before series-info had loaded.
5. **Tab churn:** 4 rapid tab switches mid-load; **closed 44868's tab while its downloads and
   cache writes were in flight** (the teardown the B1 fix targets); reopened later.
6. **Sidebar flicking:** rapid scroll up/down through 18 series during active loads.
7. **Controlled no-touch drops** (to separate interaction-cancel from self-failure).
8. **Close + reopen** of a degraded tab; drop + **MPR open/close** on the fresh tab.

## 2. Crashes / stability verdict

**ZERO crashes. ZERO native faults.** `native_fault.log` byte-identical to baseline
(528,733 → 528,733): no `0x8001010d`, no access violations, no Qt fail-fast through OLE drags
under download load, preemptions, tab close mid-flight, MPR open/close. App responsive
throughout — **0 main-thread stalls** ≥100 ms (probe armed, none fired). No Qt event-dispatch
cascade. Cross-patient isolation: **0 leak events**; no thumbnail mixing observed.

**B1 soak (disk_pixel_cache UAF fix): PASSED** — tab-close-under-load (its historical trigger)
exercised with no recurrence. (Crash A is intermittent; one clean run ≠ proof, but the exact
trigger workflow was driven hard.)

## 3. What broke (functional bugs found)

### BUG-1 — Dropped series silently never loads; viewport reverts to empty (HIGH)
Every drop in 44915's first tab failed: `change_series_on_viewer: async load-on-demand FAILED`
within **25–324 ms** (6× in window; series 201, 202, 203, 301). Spinner shows, then hides;
viewport returns to "Drop a series here". No error shown, no retry. **Re-drag fails again —
even after the series was fully downloaded (S301 @ 136/136 still FAILED in ~50 ms).** Failure
is too fast to be a real read → the tab had no file mapping.

**Root cause (high confidence): the series-info push never bound to the patient widget.**
`background_series_info_pushed … series_count=18` arrived 1.7 s after open, but every sidebar
card stayed "No series info" for the tab's entire life — the loader resolves 0 files for any
series → instant FAIL. The download/intent layer keeps its own copy (downloads completed fine),
so only the *viewer* is blind. The open trace shows a `series_info_inactive_skip` gate in
`_hp_patient_open` — prime suspect: the apply was skipped (tab judged inactive mid-open, two
tabs + churn) and there is **no re-apply on tab activation**. **Close + reopen fully recovers**
(fresh tab: labels correct, same drop loads in **680 ms**, MPR works).
Corroborating: `[ASYNC SWITCH] preview remained active for series=301 (full load failed)`.

### BUG-2 — Second UnboundLocalError stalls progressive growth (HIGH)
`progressive: _grow_progressive_fast failed series=202: cannot access local variable
'admitted_count'` — 5× under load, each tick logging
`[PROGRESSIVE_GROW_BUDGET_APPLY] applied_count=0 … skipped_reason=budget_exhausted_pre_loop`,
ending in `grow retry exhausted series=202 after 5 failures, stopping timer re-arm`.
Same defect class as the fixed `new_count` bug: when the 8 ms grow budget is exhausted
**pre-loop**, the loop is skipped and `admitted_count` is referenced unbound → every tick
throws → growth stops → **viewport pinned at 220/424** (observed live) until manual re-drag.
Fix: bind `admitted_count = 0` before the loop in `_vc_progressive.py::_grow_progressive_fast`.

### BUG-3 — Rapid single-clicks swallowed (MEDIUM)
During Phase-1 churn the last two selections (0.3 s apart, during a heavy 18-series right-panel
load) never moved the table highlight; selection stuck on the prior patient. Coincides with
`GetStudyInfo: timed out` (01:17:35) on the reconcile worker. Needs a focused look at the
click-debounce + reconcile path under concurrent load.

### Minor observations
- Drag-priority **preemption churn**: each drop preempts the in-flight series of the *same*
  study (`Download cancelled (preemption)` ×2) — by design, but repeated re-drags thrash the
  single download slot.
- MPR open has a ~3 s **transitional overlap** (MPR panes composite over the old viewport,
  placeholder text bleeds through) before settling into a correct 4-panel layout. Cosmetic.
- `[DIAG]` yellow MPR overlay tags were visible — check `ZETA_MPR_DIAG` isn't enabled in this
  environment (default should be off).
- 1× `GetStudyInfo timed out` under churn (known server non-answer; single-probe design ok).

## 4. KPIs (from logs)

| Metric | Value |
|---|---|
| Native faults during run | **0** (baseline unchanged) |
| Main-thread stalls ≥100 ms | **0** |
| Open → first series visible (44868, under churn) | 754 ms |
| Open → first series visible (44915, under load) | 2,380 ms |
| Drop → loaded, healthy tab, downloaded series (136 img) | **680 ms** |
| Drop → silent fail, degraded tab | 25–324 ms (6/6 drops) |
| Cross-patient isolation events | 0 |
| Progressive partial-stack stall | 220/424 (BUG-2), recovered only by re-drag |

## 5. Recommended fix order

1. **BUG-2** (`admitted_count`) — one-line bind, same as the verified `new_count` fix; removes
   the stuck-partial-stack under load. Lowest risk, do first.
2. **BUG-1** — make the series-info apply un-skippable for a freshly opened tab (or re-apply on
   tab activation), and make a FAILED drop-load re-arm when series files/info arrive. Read
   `_hp_patient_open` `series_info_inactive_skip` gate + `_load_and_display_series_info` first.
3. **BUG-3** — instrument the reconcile worker under churn before changing the debounce.

Crash A (0x8001010d) plan unchanged: A2 protected-drag latch ready (report §9), apply as its
own iteration now that the B1 soak is clean.
