# Progressive download/view/cache pipeline — bottleneck investigation (2026-06-08)

Prompted by the updated max-pressure stress strategy. Because the live
multi-patient impatient-drag-during-download test is **not faithfully
executable by the agent** (reasons below), this is a **code + telemetry
investigation** of the five suspected hesitation sources the user named.
Conclusion up front: **the four most-suspected paths are already engineered
against the feared anti-pattern; none does a full refresh per batch, and each
hot-path operation is sub-millisecond.**

## Why the live test couldn't be run by the agent (honest scope)
- **Synthetic mouse-drag does not trigger Qt drag-and-drop** — it registers as
  a thumbnail click, not a drop. Confirmed repeatedly (44982, fresh-CT). So the
  "drag Series 3 from A, immediately Series 5 from B…" gesture is not agent-
  performable; a human hand does it instantly.
- **The LAN server finishes a full multi-series CT in seconds**, so the
  "while 10–30% downloaded" window closes before screen automation can react.
- **No GPU/FPS telemetry** — inferred from FAST paint/event-pacing logs only.
→ The live impatient-drag-during-download is best run by a human, with the
agent harvesting KPIs from logs. A test-only download throttle would re-open
the observation window (task #161).

## Suspect #1 — "every arriving batch triggers a FULL viewport refresh" → **NOT TRUE**
The FAST batch→viewer path (`QtViewerBridge.grow` →
`Lightweight2DPipeline.refresh_file_list`) is **incremental**:
- Only **new** files get header-read (`existing_paths` + pending excluded);
  existing `SliceMeta` and cached pixels are **preserved** — no re-decode.
- The directory scan + header reads run **off the main thread**
  (`_grow_executor`, ≤16 headers/tick); the main-thread tick is ~2 ms
  (`os.scandir`).
- New entries are **batch-buffered** in `_pending_grow_entries` and only
  flushed (sort/remap/prune) once `_grow_batch_flush_threshold()` accumulates
  — "~5–8× fewer" sorts for 200+ slice series.
- The current slice is preserved **by path** across the re-sort
  (`new_index_by_path`) → no index mismatch / no jump.
- **No forced repaint**: bridge grow logs `repaint_request_ms=0.000`; it
  updates the slice count + slider range, not the displayed frame.

**Measured (real logs):** `FAST:additive_cache_grow` flushes cost
**0.54–0.89 ms total** (slice_list_extend 0.1–0.4 ms + cache_index_update
0.4–0.5 ms). Imperceptible.

## Suspect #2 — cache-insert path blocking the download thread → **NOT BLOCKING**
The cache grow is on the **viewer/main side** (additive flush above), not the
download thread. The download subprocess writes `*.part`→`os.replace` atomically
and is decoupled from the viewer's `refresh_file_list` (which reads the
directory independently). The viewer never waits on the download thread for a
cache op, and vice-versa.

## Suspect #3 — progressive stack indexing recalculation → **CHEAP, PRESERVED**
Partial-stack navigation does **not** recompute the whole index. Geometry cache
is invalidated only on a flush (`_invalidate_geometry_cache`), the current
index is remapped by path once per flush (not per scroll), and `set_slice`
clamps to the live `_slice_count`. `cache_index_update_ms` ≈ 0.4 ms per flush.

## Suspect #4 — thumbnail pipeline competing with image downloads → **DE-PRIORITIZED**
Thumbnails fetch via a separate lightweight endpoint at open and then
**cache-hit** on revisit (`right_panel_cache_hit`, observed 10352). Progressive
grow uses `_MAX_PROGRESSIVE_GROW_ENTRIES_HEAVY` (fewer header reads/tick) when
`is_heavy_download_active()` — i.e. it backs off the scan rate while the image
download is heavy, yielding to it.

## Suspect #5 — priority transition when a new series is dragged → **NON-BLOCKING + GUARDED**
`_notify_dm_viewed_series` (drag/click → CRITICAL, demote others) is:
- **Deferred** via `QTimer.singleShot(0)` — never blocks the drag/switch fast path.
- **Per-series cooldown** (`_DM_VIEWED_NOTIFY_COOLDOWN_MS`) — rapid repeat drags
  don't flood the DM → directly prevents duplicate downloads / thrash.
- The DM retry/cleanup I/O that this can trigger now runs on the shared
  pre-warmed worker (yesterday's `7be93a7`), not a GUI-thread `Thread.start()`.

## The grow loop itself is interaction-aware (the real anti-hesitation guard)
`_vc_progressive.py` defers grows during a hot scroll/drag
(`_should_defer_progressive_grow`), adapts the grow interval to the last grow
cost (back-pressure), and coalesces multiple pending grows. So an arriving
batch **never preempts an in-progress scroll**.

## One minor efficiency note (LOW priority — not a hesitation source)
69 grows logged `added=6 force_flush=True threshold=50`. `force_flush=True`
(set when `terminal OR _stale_retry_count>0`) bypasses the 50-entry batch
buffer, so under **stale-retry** the sort/remap/prune runs per ~6 slices
instead of per ~50. At ~0.5 ms/flush this is imperceptible, but it does defeat
the batching design when stale-retry is active. If stale-retry is firing often
on heavy series, capping force-flush frequency (or only forcing on the *final*
stale retry) would restore the intended batching. Worth a look only if a
profiler shows flush frequency mattering.

## Verdict
The progressive download/view/cache pipeline does **not** exhibit the suspected
bottlenecks. Batch→viewer is incremental (~0.5 ms), scanning is off-thread,
flushing is batch-buffered + interaction-deferred, indexing is path-preserved,
priority escalation is non-blocking + cooldown-guarded, and thumbnails yield to
heavy downloads. Any residual "hesitation" on a fast LAN is most plausibly
(a) inherent decode cost on the first scroll through an **uncached** region
(`FAST_FG_DISK source=direct_dicom_read decode_wait_ms`), already mitigated by
prefetch, and (b) machine/IO load — not a full-refresh-per-batch defect.

## To actually measure the impatient-drag-during-download KPIs (task #161)
Add a test-only socket/download throttle (env-gated) so the 10–30% window stays
open; then a human performs the multi-patient drags while the agent harvests
`FAST_DRAG_KPI` / `FAST_EVENT_PACING` / `PROGRESSIVE_GROW_SPLIT` /
`MAIN_THREAD_STALL`. This is the only way to capture true mid-download
escalation + scroll-FPS numbers, since the agent cannot perform Qt drags and
the LAN is too fast to observe otherwise.
