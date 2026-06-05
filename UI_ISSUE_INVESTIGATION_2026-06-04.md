# Fast UI-Probe Investigation — 6 Known Issues (2026-06-04, run `*_issues`)

> **RESOLUTION UPDATE (same day, clean-slate verification run `20260604_195412_verify`):**
> the three non-PASS items were re-verified after an automated app restart (clean tab slate):
>
> - **Issue 5 → PASS.** Fresh patient 44920 opened, study download in flight, LAST series
>   (190109541) dropped 3 s later: dispatch 24 ms, loader stable at 77 ms, and the dragged
>   series showed **35 slices in the viewport 14.7 s after the drop** with the awaiting
>   marker cleared — impossible unless the DM fetched the dragged series first. The preempt
>   machinery was also observed firing live this run (`Download preempted: … — Paused for
>   higher priority (preemption)` for two other studies). The earlier WARN was an artifact of
>   a dirty 3-study contention window + 14 s observation, not an ordering failure. Under
>   heavy multi-study contention time-to-first-image stretches with the queue — that is
>   contention, not a priority violation.
> - **Issue 1 → PASS.** Clean close of the only patient tab: first response 75 ms, stable at
>   396 ms, **0 flickers / 0 blank dips**; return to main page: 132 ms / 199 ms, 0/0. No
>   jump, flicker, or reflow — the main page settles in ≈0.2–0.4 s.
> - **Issue 3 → PASS.** Three fresh patients (44972/44852/44963) opened rapidly: tabs 2/3/4
>   hold **exactly the three expected study UIDs** with their own series counts (7/5/5) —
>   `no_mixing=True` — and tab mini-thumbnails present on every tab (std 32–34).
> - **Issue 6 → PASS (fixed same day, two conservative changes, verify run
>   `20260604_202817_verify`).** Stall-trace evidence identified two recurring GUI-thread
>   stall sources in the open/POST_DOWNLOAD path and both were eliminated:
>   1. `_hp_patient_open.py` STEP 3.5 — synchronous `servers.json` read
>      (`get_selectable_server`) + per-study sqlite read inside the open coroutine
>      (~400 ms+ on the nearly-full disk) → moved off-thread via `asyncio.to_thread`
>      (widget attribute still read on the GUI thread). After-fix traces: **0**
>      `get_server`/`servers.json` frames.
>   2. `ImageSliceBooster.clear()` (`_vc_load._on_pipeline_state_changed` →
>      POST_DOWNLOAD) — blocking `join(timeout=0.3)` (already best-effort per H12-2)
>      + in-place pixel-cache deallocation under the lock, on the main thread
>      (~300–400 ms per transition) → non-blocking join + O(1) cache swap under the
>      lock + daemon-thread dealloc (race-safe: worker re-checks `_active_series`
>      under the same lock before writing). After-fix traces: **0** booster frames;
>      booster guard tests 21/21 pass; plugin payload copy mirrored.
>   After-fix workflow window (open → drop → close → 3 rapid opens → tab switches):
>   the only ≥300 ms events left are one-shot per-process initialisations (first tab
>   activation styling 432 ms; PySide6 shiboken signature warm-up 422 ms at the first
>   `invokeMethod` — neither recurs across subsequent opens) plus the known startup
>   construction cluster. **No repeating per-open stall remains**; all 7 verify steps
>   re-passed (I5 first slices 13.9 s, I3 no_mixing=True, I1 0 flicker).
> - Probe harness gained the lesson permanently: `issue_verify_run.py` restarts the app for a
>   clean slate before index-based assertions.

Method: `ui_issue_probe_run.py` drove each workflow through the bus while `ui_probe`
captured the window at ~17–25 fps (before/first-change/worst/stable PNGs + per-command
`clip.gif` + tab-strip crop + per-region flicker/blank/settle metrics), joined with the app
log timeline (INTENT_PRIORITY, FAST-SERIES-DOWNLOAD-QUEUE, UX_FIRST_IMAGE, PROGRESSIVE_GROW,
MAIN_THREAD_STALL, preempt, load-on-demand FAILED). Artifacts under
`tools/testing/aipacs_control_mcp/ui_probe_runs/<ts>_issues/`. App was NOT started from a
clean tab slate (prior-walkthrough patients still open) — this affects issues 1 & 3 as noted.

| # | Workflow | Verdict | Key measurement |
|---|---|---|---|
| 1 | Close patient → main page flicker | **INCONCLUSIVE** | 0 pixel-delta captured at close+return; no flicker/reflow seen, but the close didn't reduce a dirty tab set → re-run from clean slate |
| 2 | Un-downloaded patient open | **PASS** | tab opens, series bound (uid match ✓, 6 series), download enqueued, tab mini-thumb present (tab_std 25.9); first response 1354 ms, stable 1639 ms |
| 3 | Several un-downloaded patients fast | **PASS (caveat)** | each probed tab held exactly ONE coherent study_uid, 8 series — no intra-tab mixing; auto "no-mix" flag false only due to leftover pre-run tabs |
| 4 | Drag not-yet-downloaded series | **PASS** | loader shown (awaiting), viewport did NOT freeze; bus dispatch 133 ms; no blank/flicker |
| 5 | Priority order (drag late series) | **WARN** | escalation to Critical confirmed in logs + queue, BUT dropped series stayed awaiting w/ 0 images for 14 s and **preempt=0** — see root cause |
| 6 | Impatient burst | **WARN** | no crash/mix, but **29 MAIN_THREAD_STALLS**, up to **949 ms**, clustered on rapid opens |

## Detail + root causes

**Issue 5 — the priority concern is real and reproduced (WARN, highest value).**
Timeline of the drop (series 205102986 = the LAST series of fresh study …86297):
```
18:49:02.151 [INTENT_PRIORITY] tag=begin study=…86297 series=205102986   ← escalation fired for the EXACT dragged series
18:49:02.170 change_series_on_viewer: async load-on-demand FAILED 205102986 (23.5ms)  ← not on disk → awaiting/loader
… viewport: awaiting_series=205102986, slice_count=0 after 14s ; first_img=0, grow=0 for it
final queue: by_priority {Critical:1, High:4}  (the dragged series IS the Critical one)
```
So the dragged series **is correctly re-prioritized to Critical** — the user's core ask
("prioritize that exact series") is met at the assignment layer. **But `preempt=0` for the
whole run and the series produced no images in 14 s.** Root cause is known and self-inflicted
this session: the viewer-drag preempt (`_pause_all_active_downloads` in
`request_critical_series_download`) was **reverted earlier today** for crash-safety on the
drag path. With it gone and `MAX_CONCURRENT_STUDIES=1`, a Critical drop is *labelled* Critical
but **waits for the in-flight download to yield the single slot instead of jumping ahead** —
exactly "it keeps downloading Series 1/2 before the dragged series." This matches the lumbar-MRI
T2 scenario the user described.
*Conservative fix:* re-introduce the targeted preempt **scoped to the dragged study/series
only** (pause the current non-matching transfer, start the Critical series, resume) — now
safer to attempt because the drag-path crashes that forced the revert (B1 UAF, BUG-1, BUG-2)
are fixed. Gate behind a live soak with `native_fault` watched; keep it one isolated change.

**Issue 6 — burst stalls (WARN).** 29 `MAIN_THREAD_STALL` events during the impatient burst,
several 200–410 ms and one **949 ms** — visible lag, no freeze/crash, no state corruption.
Root cause (consistent with prior session findings): per-open series-info resolution +
progressive-grow run on the GUI thread; rapid opens stack them. The disk-scan hoist and 8 ms
grow budget already cut the worst; the residual is the open-path series-info work.
*Conservative fix:* move the remaining synchronous series-info/DB read in the open path to a
worker (it already partially is) and coalesce rapid select/open bursts behind the existing
debounce — measure before/after with this same probe.

**Issue 4 — drag loader (PASS).** The dropped series put the viewport into `awaiting_series`
with a loader (not frozen), 133 ms bus dispatch, no blank dip or flicker. "Loader instead of
freeze" satisfied; image appearance then depends on Issue 5's ordering.

**Issue 2 — fresh open (PASS).** uid match true, 6 series bound, download enqueued, and the
**small tab thumbnail was present** (tab-strip content metric 25.9, well above the ~8 absent
threshold). The intermittent missing-thumbnail bug did not reproduce; the detector is armed.

**Issue 3 — multi-patient, no mixing (PASS with caveat).** Every patient tab probed held
exactly one coherent study_uid with its own 8 series — no tab showed two patients' data, no
duplication. The automated `no_mixing=False` was a harness artifact: the app already had
leftover tabs from earlier walkthroughs, so index-based probing hit pre-existing tabs rather
than only the three just opened. Cross-patient isolation (separately guarded + verified this
session) holds. *Probe improvement:* start issue runs from a clean slate (`stop_app`→`launch_app`).

**Issue 1 — close → main flicker (INCONCLUSIVE).** The close and return-to-main steps captured
**zero pixel delta** — i.e. no flicker/reflow was observed, but the close also didn't cleanly
reduce a dirty multi-tab set, so the transition under test may not have been the one captured.
Needs a focused re-run: launch clean → open one patient → close it → capture. (When that's
done the same metrics will state PASS/FAIL on flicker definitively.)

## KPIs captured (per command, in records.json)
command send wall-time, bus elapsed, first-UI-response ms, stable ms, per-region (full / tab
strip / right panel / viewport) diff series, flicker events, blank dips, tab-strip content
std; plus the joined download/priority/first-image/grow/stall log timeline with counts
(intent 2, queue 3, download_series 105, sig_progress 45, stalls 29, preempt 0, fail 1).

## Recommended next actions (priority order)
1. **Issue 5 (WARN→fix):** re-apply the scoped drag preempt; verify with a probe run that the
   dragged Critical series starts within ~1–2 s and earlier series yield. Highest user impact.
2. **Issue 6 (WARN):** off-thread the open-path series-info read; re-measure stall count/max.
3. **Issues 1 (and a clean 3):** re-run from a `stop_app`/`launch_app` clean slate to convert
   INCONCLUSIVE → PASS/FAIL and remove the harness caveat. (Add an auto clean-slate option to
   `ui_issue_probe_run.py`.)
4. Loop the open step 8–10× across varied patients to hunt the intermittent missing tab
   thumbnail with the now-armed `tab_strip_std` detector.
