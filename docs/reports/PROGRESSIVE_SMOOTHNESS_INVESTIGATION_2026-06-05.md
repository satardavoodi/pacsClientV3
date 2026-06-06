# Scroll-During-Download Smoothness Investigation (2026-06-05 evening)

Question: while a dragged series is still downloading and batches are being merged
into the viewer, scrolling feels hesitant — find the cost and optimize safely.

Method: PC-USE live run on the user's workstation (real mouse: double-click open of
fresh patient 40366 TARABI, 12 series / ~1,700 images; drag of series 202 into a
viewport; ~160 wheel clicks of scrolling across 2.5 minutes while the rest of the
study downloaded), joined with the always-on KPI instrumentation
(`[OVERLAP_SCENARIO]` F2.1 frame samples, `PROGRESSIVE_GROW` budget telemetry,
`MAIN_THREAD_STALL_TRACE`), plus code review of the merge path.

## 1. Blocking bug found and FIXED first (it masqueraded as "slowness")

While reproducing the scenario, fresh opens on this build came up with a dead
sidebar — **"0 series", no thumbnails, nothing to drag** — whenever the user had
single-clicked a DIFFERENT patient earlier (trace: `series_info_inactive_skip` +
`right_panel_inactive_skip_pre_fetch` at open). Root cause: the stale-response
guard added 2026-06-01 (`_is_active_patient_selection`) compares against the LAST
SINGLE-CLICKED row, and the double-click open path never updated that marker — so
the open's own series-info/right-panel work was discarded as stale. Fix: the open
now calls `_mark_active_patient_selection(patient_id, study_uid)` at
`open_request` (one guarded call in `_hp_patient_open.py`; the guard's protection
against genuinely stale earlier clicks is unchanged).

**Live-verified on this run:** the exact previously-broken sequence (user's click
on another patient → double-click 40366) produced a fully populated 12-series
sidebar with thumbnails and live progress counts.

## 2. Smoothness measurements — the merge pipeline is clean on this build

| Metric (during the live scroll-while-downloading window) | Result |
|---|---|
| Main-thread stall traces during 2.5 min of scrolling + ~1,300 background image downloads | **0** (the only stall in the window was the known one-shot tab-construction 426 ms BEFORE the drop) |
| `[OVERLAP_SCENARIO]` frame samples today (scroll/drag during active download) | 78 samples — **100% cache=hit, total_ms=0.0, source_dist=0**; zero surrogate frames, zero on-demand decodes, zero frames >50 ms |
| Progressive grow budget violations (`GROW_BUDGET_APPLY` skips) | none in the window (8 ms budget machinery never tripped) |
| Drop → image on screen (series already on disk) | ~1 s |
| Download throughput while scrolling | ~19–25 images/s sustained, unaffected by interaction |

Code review agreed with the measurements: the merge path is already heavily
shaped — 8 ms grow budget, deferred + throttled metadata sync (caps per tick,
separate retroactive throttle), interaction-hot detection that defers grows during
drags, DM table refresh coalescing, render-signature coalescing, and the
off-main-thread decode/disk-cache workers.

## 3. So where does the "hesitation" feeling come from?

Three contributors, none of them an unbounded client-side defect:

1. **The admitted-edge wait (dominant, physics + UX).** While a series is still
   downloading, the scroll range is capped at the admitted slice count. A user
   scrolling at 30+ slices/s outruns a ~20–25 images/s download, hits the edge,
   and waits for the next admission burst (~10 instances / ~350 ms batch). That
   reads as "hesitation" even though every rendered frame is instant. No merge
   optimization changes this — it is network-bound. (Optional UX polish, NOT
   applied: a subtle "loading edge" indicator at the last admitted slice, and/or
   per-file admission to make the edge advance in 1-slice steps instead of ~10.)
2. **Machine load, not app load.** Earlier today the box was at 100% CPU (two
   agent sessions + Proxifier intercepting every socket call + the v3.2.0
   installer build). Under that, paint/decode of ANY app stutters. Tonight, with
   the machine quiet, the same workflow measures clean.
3. **The dead-sidebar bug (§1)** made fresh opens feel broken/slow before any
   scrolling even started — fixed.

## 4. Recommendations

- Applied: the sidebar/active-selection fix (§1) — highest UX value of the day.
- Not applied (candidates, each small but touching guarded subsystems — do
  individually with a soak if desired): per-file admission at the progressive
  edge; an explicit edge-loading indicator; pre-spawning the per-pipeline decode
  threads off the first click (one-shot 410 ms observed yesterday).
- Keep Proxifier closed during clinical use; it both intercepts the PACS socket
  traffic and burns CPU.

## 5. Evidence
- Logs 19:27–19:32: `Downloading series …` ladder (101→…→214217738), 1 stall
  trace total, 0 grow-budget trips.
- `[OVERLAP_SCENARIO]` aggregate: 78/78 hit @ 0.0 ms (no decode misses today).
- Open trace for 40351 (18:31): `series_info_inactive_skip` → the §1 root cause.
- Fix: `_hp_patient_open.py` (open marks active selection), compiled, echomind
  suite 81/81.
