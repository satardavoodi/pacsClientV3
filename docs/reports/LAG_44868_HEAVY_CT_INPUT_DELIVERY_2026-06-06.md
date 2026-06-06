# 44868 Heavy-CT Lag — Log/KPI Analysis (2026-06-06, 16:31–16:37 session)

User report: stacking + dropping series into the viewport "not smooth" for
patient 44868 (heavy CT, multi-study). Logs analyzed live during the session
(pid 64744, source build).

## TL;DR

**The viewer pipeline is healthy — the lag is in INPUT DELIVERY.** Every
scrolled frame hit the memory cache and rendered in ≤21ms end-to-end, but
wheel/slider events reached the app **150–385ms apart (p95)** during the
late-session drags. The pacing instrumentation itself classifies it:
`queue_wait_classification=INPUT_DELIVERY_GAP`. Per-event overhead **grows
through the session** (p95 ~40–110ms at 16:31 → 150–385ms by 16:36), pointing
at an accumulating cost in the event-delivery path (the `main.py notify`
layer family — the same U4 family that is production's #1 stall source),
not at the FAST pipeline, downloads, disk, or DB.

## What the KPIs prove (drag `drag-b24b90…`, 16:37:04)

| Stage | p95 | Verdict |
|---|---|---|
| cache/disk/decode/sqlite wait | 0 ms (`cache_hit=True`, hot cache — morning download finished) | ✅ |
| request → execute | 0.1 ms | ✅ |
| set_slice → image | 9.9 ms (max 21) | ✅ |
| frame-ready → paint | 7.0 ms | ✅ |
| paint → present | 2.7 ms (one 52 ms spike) | ✅ |
| **input event gap** | **151 ms (max 287; other drags up to p95 385 / max 1743)** | ❌ the lag |

`main_thread_stall_during_drag=False`, `dm_rebuild_during_drag=False`,
`foreground_disk_reads=0`, `cache_grow_overlap=False` — every previously-known
smoothness suspect (admitted-edge wait, foreground disk loads, DM table
rebuilds, progressive growth, SQLite overlap) is **ruled out by data**.

## Session-degradation timeline (all FAST_EVENT_PACING summaries)

| Time | gap p95 | classification |
|---|---|---|
| 16:31:44–16:32:02 | 17–110 ms | mixed |
| 16:32:54 | **663 ms** (max 1743) | INPUT_DELIVERY_GAP |
| 16:33:01–16:33:20 | 33–104 ms | mixed |
| 16:35:43–16:37:04 | **151–385 ms** consistently | INPUT_DELIVERY_GAP |

App-process CPU 1.5–3.1% (multicore average), RSS stable ~1.03 GB — not
compute- or memory-bound; the cost sits in short (~100–300 ms) main-thread
occupations between input events, **below every armed tracer's threshold**
(`AIPACS_STALL_TRACE_THRESHOLD_MS` default 400 → zero [F11] stack dumps;
that's why nothing was attributed automatically).

## Series-drop ("import into viewport") verdict

Drops themselves dispatched cleanly (drag stamps + async load; no errors, no
re-fetches; hot cache). The perceived "import lag" is the same input-delivery
phenomenon during the immediately-following stack scroll, plus one 52 ms
paint spike — there is no drop-pipeline defect in this session.

## Prime suspects for the growing per-event overhead (ranked)

1. **`main.py notify` layer work per event** — every Qt event traverses it;
   matches the U4 notify/styling family (production's #1: 305 of 498 stalls,
   median 462 ms on the other PC's logs).
2. **ThemeManager listener accumulation** (known deferred P1 leak —
   per-widget connections grow during a session; iterating them is per-event
   adjacent work).
3. Qt-internal timer/event congestion from the live diagnostics cadence
   (~1 MB/min viewer log) — least likely (queued handlers), checked last.

## Recommended next step (no code change needed to attribute)

Relaunch with the existing tracer armed BELOW the observed gaps:

```
AIPACS_STALL_TRACE_THRESHOLD_MS=120
AIPACS_STALL_TRACE_COOLDOWN_MS=400
```

then stack-scroll 44868 for ~30 s. Every 120 ms+ occupation dumps the exact
main-thread stack to `native_fault.log`/app log — that names the function
family directly, after which the fix is one targeted change (and if it's the
notify/styling family, it finally justifies the long-deferred U4 pass with
hard evidence). I can drive the scroll reproducibly via the control MCP
(`AIPACS_TEST_SERVER=1`, `scroll_slices`) so the capture is clean.

*Method: FAST_FG_DISK per-frame KPIs, FAST_DRAG_KPI / FAST_EVENT_PACING
summaries, ADVANCED_CACHE_READ probes, app.log resource/throttle lines,
F11/stall tracer config — session 16:31–16:37, patient 44868 (studies
…86285 / …86299).*
