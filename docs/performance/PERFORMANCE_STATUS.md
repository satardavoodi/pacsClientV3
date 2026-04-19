# AIPacs Performance Status
**Version:** v2.3.4 | **Branch:** main | **Updated:** 2026-04-18

> **2026-04-18 current KPI extract (latest live-overlap artifact):**
> - Captured current artifact: `generated-files/benchmarks/aipacs_live_overlap_fresh.json`
> - Block summary artifact: `generated-files/benchmarks/aipacs_live_overlap_blocks_fresh.json`
> - Current overlap KPIs: `first_image_visible_ms=196.76`, `set_slice_present_p95_ms=155.48`, `set_slice_present_max_ms=385.82`, `decode_p95_ms=208.4`, `frame_render_p95_ms=187.49`, `cache_hit_ratio_pct=52.6`, `slow_frame_count_16ms=114`, `cpu_p95_pct=139.18`, `rss_peak_mb=221.42`, `thread_count_p95=36.0`.
> - Interpretation: startup is now fast enough to look healthy on the first image, but sustained heavy-stack interaction is still not healthy; the remaining bottleneck is no longer first-image startup but large-stack interaction under overlap.
> - Block diagnosis from the current summary: **Block 1** remains mostly healthy as a producer plane, **Block 2** still spikes when foreground decode/render is exposed, and **Block 3** remains the primary remaining bottleneck because cache/scroll/orchestration is still allowing large-stack interaction to fall into expensive paths.

> **2026-04-18 policy update (viewer interaction):**
> - Wheel scroll is now strict precision mode (**±1 slice only**, no adaptive skip).
> - Stack drag now follows a **shared slice-count-aware profile**: small stacks stay deliberate, medium stacks stay balanced, and large stacks allow faster bounded traversal without changing wheel precision.
> - Stack drag overflow is now **bounded, not queued**: capped drag events keep only a sub-threshold tail, and reversal clears stale pending drag immediately.
> - The same slice-count profile now also drives FAST drag-side Block C behavior (prefetch cap, surrogate window, decode relevance window) so stack speed and cache aggressiveness stay aligned instead of being tuned independently.
> - During progressive/download growth, the drag/cache profile now follows the **current interactive slice count**, so policy shifts only when the currently reachable stack changes.
> - FAST measurement tools now auto-return to default mode after completion (parity with Advanced lifecycle).

> **Quick-start:** Start here. For the planning-first KPI program, continue with `FAST_VIEWER_PERFORMANCE_ROADMAP.md` → `FAST_VIEWER_KPI_CATALOG.md` → `FAST_VIEWER_TEST_SCENARIOS.md` → `CONCURRENCY_ANALYSIS_v2.3.3.md`.

> **2026-04-15 runtime alignment update (scroll + download):**
> - Current logs show cache-hot FAST scroll is typically ~2-5ms with `decode_ms=0`.
> - Remaining spikes during concurrent download are orchestration/UI event pressure, not decode.
> - Progressive and thumbnail update paths now coalesce to a protected 2 Hz cadence during active interaction or heavy download.
> - Restart-after-DONE is fixed in the integrated progressive pipeline while stale terminal callbacks remain guarded.
> - `log 37` showed the next remaining storm source clearly: duplicate terminal completion/cache-warm activity for the same series before the definitive completion layer closed the cycle.
> - B4.x-i5 now blocks those duplicate late terminal callbacks before they can recreate tracking or re-fire one-shot grow; fresh runtime capture is still required to measure the live KPI delta.
> - B4.x-i6/i7 now route existing cadence and prefetch-cap decisions through a shared `SystemLoadController`, with a callback-gap-based `ui_event_loop_lag_ms` probe feeding protected-mode decisions.
> - B4.x-i8 now lets that same controller defer non-terminal progressive grow and post-completion cache warm during protected UI intervals; runtime recapture is still pending before claiming mixed-load lag is fixed.
> - 2026-04-17 follow-up: fast interaction now prefers an exact **filtered** cached frame over an exact unfiltered cache hit when both already exist, reducing the subtle scroll-stop image appearance pop without reintroducing decode/filter work.
> - 2026-04-17 follow-up: progressive slider range now stays anchored to the known total slice count while availability gating remains separate, eliminating the visible `200 → 20 → 40` scrollbar shrink/grow churn.
> - 2026-04-17 follow-up: slider max growth now explicitly preserves the current viewed position if the underlying slider implementation tries to snap to the new max during progressive range expansion.
> - 2026-04-17 follow-up: FAST stack drag for larger series is now materially more responsive (smaller per-step threshold + higher bounded per-event cap) so a full-height drag covers a much more useful span without reverting wheel precision or forcing every skipped slice through immediate render.
> - 2026-04-18 follow-up: FAST stack drag now uses a monotonic backlog-free standard — capped overflow no longer queues momentum, reversal clears stale pending drag immediately, and the active drag/cache profile rebases to the current interactive slice count during progressive growth.

> **2026-04-18 measured-state update (latest current artifact):**
> - First-image KPI is now materially stronger than the older overlap headless captures (`196.76ms` vs `1103.79-1382.48ms` class in older benchmark sets), so the old “overlap startup is the dominant pain” story is no longer sufficient on its own.
> - The remaining problem is sustained heavy-stack viewing quality: `set_slice_present_p95_ms=155.48`, `set_slice_present_max_ms=385.82`, `decode_p95_ms=208.4`, and `slow_frame_count_16ms=114` are still far from the interactive target.
> - `stale_task_ratio=0.0` is a meaningful control-plane improvement versus older headless captures, but `cache_hit_ratio_pct=52.6` shows the active series is still falling out of the cheap path too often during overlap.
> - Current execution priority should therefore remain conservative and heavy-stack-specific: protect the good `<200`-image behavior, stabilize Block 3 for large active stacks first, and only then broaden series-load refactoring.

> **2026-04-17 benchmark capture update (headless, real dataset):**
> - Captured AI-PACS FAST artifacts in `generated-files/benchmarks/run_001/` using dataset `user_data/patients/dicom/1.2.840.1.99.1.47.1.1772527236103.85188/202` (342 slices).
> - Common local baseline: `first_image_visible_ms=327.72`, `set_slice_present_p95_ms=24.85`, `cpu_p95_pct=132.2`, `stale_task_ratio=0.9537`.
> - AI-PACS overlap: `first_image_visible_ms=1382.48`, `set_slice_present_p95_ms=30.04`, `cpu_p95_pct=166.08`, `stale_task_ratio=0.99`.
> - Interpretation: overlap regression is primarily orchestration/admission pressure, not raw decode (`decode_p95_ms` improved from `62.34` to `27.45` while user-visible latency worsened).
> - Limitation: this headless run does **not** validate live Qt-event-loop lag or duplicate terminal log markers; those still require a runtime app log capture.

> **2026-04-15 stabilization pass recapture (headless, run_002):**
> - Landed a bounded control-plane pass: coalesced DM progress fan-out, single progressive terminal finalizer, shared admission gating for progress/prefetch.
> - Captured fresh artifacts in `generated-files/benchmarks/run_002/` on the same 342-slice dataset.
> - Common local baseline improved modestly: `first_image_visible_ms=227.61`, `set_slice_present_p95_ms=23.33`, `cpu_p95_pct=85.0`, `stale_task_ratio=0.9538`.
> - Overlap headless latency improved strongly: `first_image_visible_ms=1103.79`, `set_slice_present_p95_ms=6.45`, `slow_frame_count_16ms=0`.
> - But the primary orchestration targets are still open: `stale_task_ratio=0.9899` and overlap `cpu_p95_pct=189.4` remain unacceptable.
> - Interpretation: the admission hardening clearly helped the headless frame path, but the requested KPI gate is **not yet achieved** and still needs live app/runtime-log validation.

---

## 1. Architecture — Three Paths to Display

```
User double-clicks study
        │
        ▼
[HOME UI] opens patient tab immediately
        │
        ├─► [DOWNLOAD SUBPROCESS pid=N]  ← background, BELOW_NORMAL priority
        │        SeriesDownloader → socket → DICOM files on disk
        │        parallel pydicom header reads → DB insert (v2.2.3.2.0)
        │
        └─► [VIEWER — Qt main thread]
                 │
                 ├─ INTERACTIVE LOAD (user clicks series thumbnail)
                 │    image_io.load_single_series_by_number
                 │      ├─ DB query (38–88ms)
                 │      ├─ disk read (27–384ms)
                 │      ├─ ITK filter chain (150ms–3s, adaptive threads)
                 │      └─ ITK→VTK convert (2–45ms)
                 │
                 ├─ FIRST-SERIES DISPLAY (Mode B, asyncio.to_thread)
                 │    v2.2.3.2.4: max_itk_threads=2, max_pydicom_workers=2
                 │    (was unlimited → massive GIL contention with UI thread)
                 │
                 ├─ ZETA BOOST WARMUP (background, post-download)
                 │    lane=warmup, 2 workers, max_parallel_loads=2 (8GB+)
                 │    max_itk_threads=2, BELOW_NORMAL OS priority
                 │
                 └─► [DL_WARMUP SUBPROCESS pid=M] ← separate process (v2.2.3.2.3)
                      warmup_subprocess.py, own GIL, IDLE priority (v2.2.3.4.0)
                      max_itk_threads=1 (v2.2.3.3.9), results polled via QTimer (100ms)
                      queue_p95_ms dropped from 200-510ms → 0.00ms
```

---

## 2. Current Performance Numbers (v2.2.3.4.0, PC A)

### Mode A — No download active

| What | Metric | Value | Target |
|---|---|---|---|
| Scroll response (typical) | `set_slice_p50_ms` | ~17–42ms | <20ms |
| Scroll response (95th pct) | `set_slice_p95_ms` | ~45–83ms | <35ms |
| Scroll response (worst) | `set_slice_max_ms` | ~60–98ms | <80ms |
| Event queue delay | `queue_p95_ms` | **0.00ms** (Mode A, no DL) | <5ms ✅ |
| Scroll frame interval | frame-to-frame | ~85–116ms (~10fps sw GL) | — |
| Series load, cold (MR 20sl) | `load_single_series_total` | 1.2–1.9s (cold) | <1000ms |
| Series load, ZetaBoost hit | `load_single_series_total` | ~200ms | <300ms ✅ |
| ITK filter, MR ~20sl | `apply_filters duration_ms` | 150–500ms (interactive, 6t) | <500ms |
| Sub-timing: SetSlice | VTK `SetSlice()` | 20–35ms | — |
| Sub-timing: Render | VTK `Render()` | 7–14ms | — |

### Mode B — Download active (DL_WARMUP running in subprocess)

| What | Metric | Value | Target |
|---|---|---|---|
| Scroll response (typical) | `set_slice_p50_ms` | ~35ms (expected v2.2.3.4.0, was ~45ms) | <25ms |
| Scroll response (95th pct) | `set_slice_p95_ms` | ~45ms (expected, was ~61ms) | <50ms |
| Queue delay during DL (scroll) | `queue_p95_ms` | **0.00ms** (subprocess DL_WARMUP, v2.2.3.2.3) | <30ms ✅ |
| Queue delay during DL (signals) | `queue_p95_ms` | 620–5437ms → **<200ms** (v2.2.3.2.6 coalescing) | <30ms — **mitigated** |
| Stale-event drain (v2.2.3.2.1) | `stale_drain_complete skipped=N` | N events skipped, 1 render | eliminates 4s+ backlog ✅ |
| DL_WARMUP per-series (large MR) | `[DL_WARMUP_SUB] ✓ Cached` | ~402ms (subprocess, v2.2.3.2.3) | <2000ms ✅ |
| DL_WARMUP per-series (small MR) | `[DL_WARMUP_SUB] ✓ Cached` | ~200–500ms | <1200ms ✅ |
| DB insert (download subprocess) | `batch_insert_instances_total` | 6–455ms (was 2217ms) | <500ms ✅ |
| First-series GIL pressure | ITK threads + pydicom workers | **2+2** (v2.2.3.2.4, was N+8) | low contention ✅ |
| Series switch (VTK data mapping) | `switch_series()` | ~718ms (once, not per-scroll) | — |
| Subprocess warmup priority | OS priority class | **IDLE** (v2.2.3.4.0, was BELOW_NORMAL) | minimal contention ✅ |
| Camera save/restore on scroll | per-frame overhead | **0ms** (v2.2.3.4.0, skipped) | was ~3-5ms |
| Lock Sync during scroll | callback rate | **≤10/sec** (v2.2.3.4.0, 100ms throttle) | was every frame |

---

## 3. What Was Fixed (Most Recent First)

| Version | Symptom Fixed | How |
|---|---|---|
| **Unreleased (2026-04-19)** | FAST stack drag still treated 20/100/200-slice series too similarly, so drag speed, skip allowance, and Block C cache behavior could fall out of sync | Added a shared slice-count-aware policy (`stack_cache_profile`) used by both `QtSliceViewer` and `Lightweight2DPipeline`: drag threshold/fullscreen span/max-step cap now scale by slice count, while drag-side prefetch radius, surrogate search distance, and decode relevance window scale from the same profile. Heavy-download admission caps remain the final authority, so Block C stays protected under overlap. |
| **Unreleased (2026-04-16)** | Fast internal-network download bursts could still land in the viewer as one large progressive jump even after signal coalescing; concern remained that a gate might only move complexity into the background | Added a non-terminal **progressive admission gate**: backend may know all downloaded files, but viewer-visible `available_slice_count` now advances in bounded batches via `_progressive_admit_batch_size`; terminal completion remains uncapped. After one-knob sweep results on series `202`, tuned the default admission batch **10 → 8** because it improved overlap P95/max, kept >16ms slow frames at zero, and beat both `5` and `12` on the balance score across overlap + common-path KPIs. Added `test_progressive_admission_storm.py` to prove lower burst shock, bounded drain complexity, and a CPU-pressure storm harness so the stress test is genuinely hot rather than just callback-dense |
| **Unreleased (2026-04-16)** | Even with the admission gate, protected UI could still wake the progressive grow retry loop every **150ms** while non-terminal viewer admission was being deferred, adding avoidable control-plane churn during download overlap | Added a protected-mode **progressive grow retry cadence**: non-terminal viewer admission now re-arms at **500ms** during active download and **750ms** during active download + fast interaction, while terminal completion remains immediate/uncapped. This makes the visible viewer behave like it currently has only the admitted slice count while the background continues preparing later batches. |
| **v2.3.3-stability B4.x (2026-04-15)** | Scroll+download spikes with `decode_ms=0`; thumbnail/progressive/log event bursts; integrated restart-after-completion rejected new same-series cycles | Added shared UI throttle/download activity helper; progressive callbacks and thumbnail progress/log updates coalesce to 2 Hz during scroll/heavy download; `set_slice()` marks viewer interaction so thumbnail repaints defer; `Lightweight2DPipeline` reads the live download-active flag; lifecycle re-entry from `DONE` can clear completed-series guard for verified new partial cycles |
| **v2.3.3-perf B3.7** | 100% foreground pydicom decode (17-45ms) during fast scroll; CPU 150-220%; P95 set_slice 35-50ms | Cache-first fast scroll: `_find_nearest_cached_pixel(±10)` returns surrogate from pixel_cache (0ms decode, ~2ms W/L). Falls through to sync decode only on first frame of new region. During heavy-download overlap on an incomplete viewed series, drag navigation may widen the surrogate window to **±20** and still re-arm the existing prefetch path; admission policy and radius caps remain in force so overlap cache fill stays tiny instead of fully suppressed. Separately, very high-speed drag may also widen to **±20** for completed viewed series so transient cache gaps resolve to surrogate instead of a 15–20ms foreground decode spike. Follow-up: drag now probes the **nearest cached rendered frame** before rerendering a nearby cached pixel, removing remaining `decode_ms=0 / wl_ms≈10–16ms` spikes caused by UI-thread W/L recomputation on surrogate frames. Prefetch radius raised 1→3 during fast interaction. Expected: set_slice P95 <5ms during fast scroll, CPU ~50-70% |
| **v2.3.3 (2026-04-14)** | Wheel felt jumpy due to adaptive skipping; stack/wheel intent mixed; FAST tools could stay latched after completion | Enforced wheel ±1 policy in `_vw_scroll.py`; added adaptive stack profiles in `qt_slice_viewer.py` and `abstract_interactorstyle.py`; wired FAST auto-deactivate callback chain to restore default mode and clear toolbar selection |
| **v2.2.3.4.0** | 5-15ms per-frame overhead in set_slice during wheel scroll (camera save/restore, style update, Lock Sync) + subprocess warmup memory-bus contention | Wheel-scroll fast-path: skip camera zoom save/restore (~3-5ms), skip interactor style update (~1ms), throttle Lock Sync to 100ms; subprocess priority BELOW_NORMAL→IDLE |
| **v2.2.3.3.9** | Mode B scroll lag from warmup subprocess contention (ITK 2 threads + unthrottled result poll + frequent notify) | Subprocess ITK threads 2→1; defer poll during scroll (idle<300ms); max 1 result/tick; notify throttle 500→250ms |
| **v2.2.3.3.8** | Size-mismatch false positives during active downloads triggering warmup retries | Compare against DB expected count, not just cached data |
| **v2.2.3.3.7** | Reference line repaint blocking scroll loop (N×20ms per tick) | Round-robin: paint ONE target viewer per tick; scroll-end repaints ALL targets |
| **v2.2.3.3.6** | Ref-line Render() called during scroll loop blocking main thread | Trailing-edge uses geometry-only update (repaint=False); actual Render deferred to scroll-end |
| **v2.2.3.3.5** | Reference lines lagging behind scroll (only updating on trailing edge) | Dual-timer: leading-edge immediate geometry-only + trailing-edge 50ms with repaint |
| **v2.2.3.3.4** | Reference lines stale during lock sync drag | Ref-line update fires after lock sync completes; debounced at 80ms |
| **v2.2.3.3.3** | _update_reference_lines() Render on every scroll frame (~20-40ms) | Debounced via `_schedule_reference_line_update()` with 80ms trailing-edge QTimer |
| **v2.2.3.3.2** | 660ms periodic lag on PC B (500ms GC timer + 150ms GC collection) | GC re-enable timer 500→2000ms; keep elevated thresholds on re-enable; save originals only once |
| **v2.2.3.3.1** | 100-300ms stalls from event-loop congestion between download signals | Cache `os.getenv` in `__init__` (was 3-5ms/call ×2/frame); bypass coalesce timer when gap expired |
| **v2.2.3.3.0** | Sporadic 400-660ms GC stalls on PC B during heavy volume scroll | Strengthened GC suppression: longer timer, elevated thresholds kept on re-enable |
| **v2.2.3.2.9** | Sporadic ~100–400ms freezes during smooth scrolling (Python GC pauses) | GC suppressed during scroll bursts (`gc.disable()`), re-enabled 300ms after last render with soft gen-0 collect; ImageSliceBooster `on_slice_changed` throttled to once per 200ms (was every render) |
| **v2.2.3.2.8** | Scroll debounce added 16ms latency to EVERY frame, ~5–8fps on sw GL | Adaptive THROTTLE replaces debounce: immediate render on first scroll, paced subsequent renders with adaptive gap (25% of frame time); skip redundant per-event ruler/border/camera checks; throttle `notify_viewer_interaction` to once per 500ms |
| **v2.2.3.2.7** | Infinite stale-drain re-arm loop froze UI for 44s+; gRPC on main thread; viewer creation starvation | Fixed re-arm loop in `_flush_pending_wheel_slice` (reset `_last_scroll_event_ms` on each flush); `processEvents()` yield between viewer creations; gRPC offloaded to `asyncio.to_thread` |
| **v2.2.3.2.6** | SERIES_DOWNLOAD_COMPLETE signals fire back-to-back, blocking Qt event loop 620–5437ms | Coalesced `on_series_completed` handler in `home_ui.py`: first series immediate, rest batched with 100ms debounce + processEvents yield every 2 series; added `processEvents()` yield after first-series viewer init in controller |
| **v2.2.3.2.5** | VTK render overhead on software OpenGL: FXAA +20-50ms/frame, MSAA 8x, redundant `color_mapper.Update()` on scroll | FXAA off (`renderer.UseFXAAOff()`); `SetMultiSamples(0)`; skip `color_mapper.Update()` on default-WL scroll path (Render() auto-updates); sub-timing instrumentation in `set_slice` |
| **v2.2.3.2.4** | First-series load floods GIL (unlimited ITK threads + 8 pydicom workers in viewer process) | `max_itk_threads=2, max_pydicom_workers=2` for in-process first-series load; `process_series_groups` yields 50ms→5ms |
| **v2.2.3.2.3** | DL_WARMUP thread in viewer process causes 200–510ms `queue_p95_ms` during scroll | Moved DL_WARMUP to `multiprocessing.Process` (own GIL); results polled via QTimer 100ms; `queue_p95_ms` → **0.00ms** |
| **v2.2.3.2.2** | DL_WARMUP taking 4s per large MR series | `max_itk_threads=1→2`, delay 3.0→1.5s, max_parallel_loads 1→2 |
| **v2.2.3.2.1** | Scroll backlog: 84 events × 50ms = 4s freeze after any main-thread block | Stale-event drain guard: skip render when queue_delay>500ms, 1 render at final pos |
| **v2.2.3.2.0** | Download DB insert 2217ms (serial pydicom); ITK scroll spikes during filter | Parallel asyncio pydicom; adaptive threads + BELOW_NORMAL OS priority |
| **v2.2.3.1.9** | Viewer-side instance creation 4.3s (330-file CT) | Parallel pydicom via ThreadPoolExecutor on viewer path |
| **v2.2.3.1.8** | Series switch 1.4s overhead | Skip redundant `SetInputData` when reslice output already connected |
| **v2.2.3.1.8p1** | Download subprocess competing with VTK render | Download subprocess → BELOW_NORMAL Windows priority |
| **v2.2.3.1.6** | `apply_filters` 423ms due to repeated int16↔float32 casts | Cast-once to float32 before all stages; cast back once at end |
| **v2.2.3.0.8** | MR mild_mode filter 29s on first load | 2 threads + 2 sigmas + skip adaptive sharpening on thick slices |
| **v2.2.3.0.5** | 14–17s event_queue_delay after series switch | Clear stale `_last_scroll_event_ms` on `switch_series` |

---

## 4. Open Issues (Ranked)

### 🟡 P1 — First-series in-process load still ~2.4s
- v2.2.3.2.4 caps threads+workers to 2+2, reducing GIL contention during the load
- But the load itself still runs in the viewer process via `asyncio.to_thread()`
- **Ideal fix:** Route first-series through the warmup subprocess too (eliminates ALL in-process GIL contention during Mode B first-series load)
- **Complexity:** Subprocess must load → serialize result → QTimer polls → `_display_first_series_in_all_viewers()` — requires refactoring display path

### 🟡 P2 — `update_corners_actors()` runs 6+ VTK text updates per scroll
- Currently does metadata dict lookups + string formatting + 6 `change_actor_text()` calls on every scroll frame
- Only `im_slice_actor` and `im_series_window_level` actually change per-scroll; others (date, series name, thickness, size) are constant within a series
- **Next step:** Split into `_update_scroll_varying_actors()` (slice count + WL only) and `_update_series_constant_actors()` (called once on series switch)
- **Expected savings:** ~5-10ms per scroll frame on software-GL renderer

### 🟡 P3 — `viewer_db_read` (38–88ms) on every series load
- DB query runs on worker thread so it doesn't block scroll, but adds to perceived load time
- **Next step:** After study download, cache series_pk and instance paths in a simple dict — eliminates DB query on repeated open

### 🟡 P4 — Lock Sync callback runs coordinate math on every scroll
- `_do_lock_sync()` in patient_widget.py does IPP interpolation + applies to target viewers on every slice change when Lock Sync is enabled
- Consider debouncing to every 2nd or 3rd scroll event (user won't notice 1-frame delay in synced viewer)

### 🟢 P5 — ITK→VTK convert 11–44ms on large series
- `itk_to_vtk_convert` duration grows with size (500×640×24 ≈ 44ms)
- ITK stores as `[Z, Y, X]` C array → VTK needs `[X, Y, Z]` Fortran; currently always copies
- **Next step:** Check if `vtk.util.numpy_support.numpy_to_vtk(ravel_order='F')` avoids copy

### ✅ Resolved — Mode B queue delay (was P1)
- v2.2.3.2.6 coalesces `SERIES_DOWNLOAD_COMPLETE` signals (100ms debounce, processEvents yield)
- Measured `queue_p95_ms` = **0.00ms** in v2.2.3.2.8 logs — fully resolved

### ✅ Resolved — Sporadic GC stutters (was P0 in v2.2.3.2.8)
- ~338ms gaps observed with zero main-thread activity → Python GC gen-1/gen-2 pauses
- v2.2.3.2.9 suppresses GC during scroll bursts, re-enables 300ms after last render

### ✅ Resolved — Infinite stale-drain loop (was P0 in v2.2.3.2.6)
- `_flush_pending_wheel_slice` re-armed indefinitely because `_last_scroll_event_ms` wasn't reset
- v2.2.3.2.7 resets timestamp on each flush, breaking the loop

### ✅ Resolved — Debounce latency (was P0 in v2.2.3.2.7)
- Every wheel event restarted 16ms timer → added 16ms latency to every frame
- v2.2.3.2.8 replaced with adaptive throttle: 0ms first-scroll, paced subsequent renders
---

## 4.1 Concurrent Download Behavior

Runtime evidence from `log 36 .txt` and `log 37 .txt` now shows three simultaneous truths:
- The FAST frame path is cache-hot and fast (`[B3.8_SCROLL]` commonly ~0.6-5.2ms with `decode_ms=0`; one sampled frame in `log 37` reached 10.9ms but not the old 50-100ms class).
- CPU still climbs hard during mixed load (`cpu=153.6%`, `169.8%`, `186.2%`, `221.2%` in `log 37`).
- The remaining storm is not mainly decode and not mainly thumbnail cadence. The clearest repeated waste is duplicate terminal progressive work on the same series before the final completion layer closes the lifecycle.

`log 37` specifically shows series 303 hitting:
- repeated `progressive-fast: ... COMPLETE (123 slices)`
- repeated `cache-warm dispatched ...`
- repeated lifecycle bounce `COMPLETING -> AWAITING -> COMPLETING -> PROGRESSIVE`

That pattern means late terminal progress callbacks are still able to re-enter the grow path after `_grow_progressive_fast()` has already reached the full count, but before Layer 2b/cleanup writes the final `DONE` state and closes the cycle.

The current stabilization already does the following:
- Viewer priority: `set_slice()` stays synchronous and marks fast interaction immediately.
- UI protection: thumbnail progress/border work defers while scrolling and coalesces to max 2 Hz under scroll/heavy download.
- Progressive signal control: progressive callbacks remain normal 10 Hz when idle, but widen to 2 Hz during heavy download or active interaction.
- Download awareness: `is_heavy_download_active()` uses the live global download flag plus a short grace window after bursts.
- Prefetch pressure: idle/medium prefetch radius is capped more aggressively while heavy download is active.
- Per-series state: `PipelineOrchestrator` now exposes active-series download queries so future routing can distinguish unrelated downloads from the viewed series.

What has now been shipped on top of that diagnosis:
- **Terminal idempotence bridge:** once `_grow_progressive_fast()` observes terminal completion for a cycle, a compatibility guard blocks duplicate late terminal progress callbacks before they recreate `_progressive_series` or re-fire one-shot grow.
- **Restart compatibility preserved:** a verified `DONE -> partial new cycle` still clears the completed-series and terminal-complete guards so restart-after-DONE remains functional.
- **Shared policy point:** cadence/radius decisions now flow through `SystemLoadController` instead of scattered direct timing checks.
- **UI lag probe:** the Qt bridge records a lightweight callback-gap estimate for `ui_event_loop_lag_ms`; fresh lag above 50ms now activates the same protected cadence path used by heavy download / active interaction.
- **Policy-driven shedding:** that controller now also front-doors defer decisions for non-terminal progressive grow and post-completion cache warm, so those background actions step aside during protected UI windows instead of contributing more burst pressure.
- **Viewer admission gate:** non-terminal progressive growth no longer exposes the full `pending_downloaded` count in one tick. The backend can know all files are present, but the viewer admits them in bounded steps via `_progressive_admit_batch_size`. This targets the remaining LAN-speed “burst jump” problem without slowing the downloader or delaying terminal completion.
- **Storm proof harness:** `tests/viewer/test_progressive_admission_storm.py` now compares ungated vs gated burst shock, verifies bounded extra grow ticks, and includes a CPU-saturation proxy storm so the harness reflects a real hot-path stress class rather than a toy event-count model.

### 4.1.1 Stack path vs gating vs other solutions

The current direction is intentionally split by work class:

- **Stack/wheel/drag path** stays direct and low-latency. That is the user’s sacred path; adding gating there would trade one kind of jank for another.
- **Progressive growth** now uses a bounded admission gate because it is background, viewer-facing, and burst-sensitive.
- **Other non-interactive work** (prefetch, cache warm, thumbnail/progress fan-out, refresh/apply after load) is still handled by coalescing, protected-mode deferral, and terminal-idempotence guards.

So the strategy is not “gate everything.” It is:

1. keep the stack path immediate,
2. gate only non-interactive viewer admission,
3. keep terminal completion visible,
4. continue reducing duplicate/background follow-up work elsewhere.

What still needs to happen next:
- **Runtime recapture:** the live mixed-load session must be rerun to confirm that duplicate `COMPLETE` / cache-warm bursts disappear in production logs and that `[B3.8_SCROLL]` stays in the target class under mixed load.
- **Helper-authority closure:** once runtime behavior is confirmed, the next cleanup step is retiring compatibility writes/reads that are now shadowed by helper-driven lifecycle and controller policy paths.

This status does not claim the storm is fully solved yet. The specific duplicate terminal re-entry path is now guarded in code and tests, and the shared policy shell is in place, while the broader mixed-load orchestration work remains open.

### 4.1.2 Headless benchmark recapture (`run_001`, 2026-04-17)

Dataset used:
- `user_data/patients/dicom/1.2.840.1.99.1.47.1.1772527236103.85188/202`
- 342-slice series from local patient data

Artifacts:
- `generated-files/benchmarks/run_001/aipacs_common.json`
- `generated-files/benchmarks/run_001/aipacs_overlap.json`
- `generated-files/benchmarks/run_001/aipacs_overlap_vs_common.md`

Measured results:

| KPI | Common local baseline | AI-PACS overlap | Interpretation |
|---|---:|---:|---|
| `first_image_visible_ms` | 327.72 | 1382.48 | overlap open path is 4.2× slower |
| `set_slice_present_p50_ms` | 0.05 | 14.41 | overlap loses the near-free cache-hot feel |
| `set_slice_present_p95_ms` | 24.85 | 30.04 | both runs still miss the 16ms target |
| `decode_p95_ms` | 62.34 | 27.45 | overlap regression is not decode-dominated |
| `frame_render_p95_ms` | 46.82 | 29.93 | render path is not the main offender |
| `cache_hit_ratio_pct` | 56.2 | 48.0 | overlap reduces useful cache locality |
| `slow_frame_count_16ms` | 63 / 296 | 124 / 248 | overlap roughly doubles missed frames |
| `stale_task_ratio` | 0.9537 | 0.99 | background admission is still extremely noisy |
| `cpu_p95_pct` | 132.2 | 166.08 | overlap adds substantial control-plane load |
| `thread_count_p95` | 31 | 33 | overlap keeps more workers/actors alive |

What this run proves:
- The FAST path is **not** healthy enough yet even in common local viewing; the baseline still has too much stale work and too many missed frames.
- The overlap regression is **not** explained by slower decode. The decode path got cheaper while the UX KPIs got worse.
- The best current explanation remains: admitted non-interactive work is still too eager, and one DM progress event still fans out into too many UI-side consumers.

What this run does **not** prove:
- It does not measure live Qt event-loop callback gaps in the real app.
- It does not confirm whether duplicate terminal `COMPLETE` / cache-warm log markers are gone in production runtime.
- It does not isolate multi-view redraw/sync tails; those require live runtime capture, not headless harness only.

### 4.1.2 Headless stabilization recapture (`run_002`, 2026-04-15)

Artifacts:
- `generated-files/benchmarks/run_002/aipacs_common.json`
- `generated-files/benchmarks/run_002/aipacs_overlap.json`
- `generated-files/benchmarks/run_002/aipacs_overlap_vs_common.md`

Measured results:

| KPI | `run_001` common | `run_002` common | `run_001` overlap | `run_002` overlap |
|---|---:|---:|---:|---:|
| `first_image_visible_ms` | 327.72 | 227.61 | 1382.48 | 1103.79 |
| `set_slice_present_p95_ms` | 24.85 | 23.33 | 30.04 | 6.45 |
| `slow_frame_count_16ms` | 63 / 296 | 109 / 296 | 124 / 248 | 0 / 248 |
| `stale_task_ratio` | 0.9537 | 0.9538 | 0.99 | 0.9899 |
| `cpu_p95_pct` | 132.2 | 85.0 | 166.08 | 189.4 |

What `run_002` shows:
- The shared admission changes helped headless slice-present latency materially under overlap.
- The control-plane goals that motivated this pass are still NOT achieved in benchmark terms:
        - `stale_task_ratio` did not move meaningfully.
        - overlap `cpu_p95_pct` regressed further.
- Therefore this pass should be treated as a **partial stabilization** rather than a completed KPI fix.

Why the mismatch is believable:
- `run-aipacs-headless` strongly exercises `Lightweight2DPipeline` and simulated mixed-load decode pressure.
- It does **not** fully exercise live Qt/UI fan-out, `HomeDownloadService` signal cadence, or real-app terminal duplicate logs.
- So the code changes are real and the tests are green, but the remaining KPI question now depends on a live runtime capture, not headless-only evidence.

---

## 5. Key Files

| File | Purpose |
|---|---|
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py` | VTK viewer widget, scroll events, stale-drain guard, series switch |
| `PacsClient/pacs/patient_tab/utils/image_filters.py` | ITK filter chain, adaptive threads, BELOW_NORMAL priority |
| `PacsClient/pacs/patient_tab/utils/image_io.py` | Series load pipeline: DB path, disk read, ITK, VTK conversion |
| `PacsClient/pacs/patient_tab/utils/utils.py` | `get_or_create_instance` — parallel pydicom reads (viewer side) |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_viewer_controller.py` | ZetaBoost engine, DL_WARMUP subprocess integration, RAM tier config |
| `PacsClient/pacs/patient_tab/zeta_boost/warmup_subprocess.py` | **NEW v2.2.3.2.3** — GIL-free DL_WARMUP in separate process (`multiprocessing.Process`) |
| `PacsClient/zeta_download_manager/download/series_downloader.py` | Download pydicom reads, DB batch insert (download subprocess) |
| `PacsClient/zeta_download_manager/network/socket_client.py` | DICOM server communication |

---

## 6. Environment Tuning Knobs

| Variable | Default | Effect |
|---|---|---|
| `AIPACS_DL_WARMUP_MAX_CACHED` | `4` | Max series DL_WARMUP pre-caches per download session |
| `AIPACS_DL_WARMUP_MAX_SLICES` | `200` | Skip series with more slices than this |
| `AIPACS_DL_WARMUP_INTER_DELAY` | `1.5` | Seconds between DL_WARMUP jobs (v2.2.3.2.2: was 3.0) |
| `AIPACS_DL_WARMUP_SUBPROCESS` | `1` | Enable subprocess-based DL_WARMUP (v2.2.3.2.3; set 0 to fall back to in-process thread) |
| `AIPACS_SCROLL_COALESCE_MS` | `16` | Scroll coalesce timer interval (ms); adaptive throttle overrides during burst |
| `AIPACS_SCROLL_LAG_PROBE_ENABLED` | `1` | Enable/disable scroll performance probe |
| `AIPACS_SCROLL_LAG_PROBE_WINDOW_SEC` | `12` | Scroll probe measurement window (seconds) |
| `AIPACS_VIEWER_TIMING_MIN_MS` | `35` | Only log scroll timings ≥ this threshold |
| `AIPACS_VIEWER_TIMING_SAMPLE_EVERY` | `25` | Sample normal-speed scroll events 1-in-N |
| `AIPACS_LOG_MAX_BYTES` | `20971520` | Rotating log file max size (20MB) |
| `AIPACS_LOG_BACKUP_COUNT` | `3` | Number of log file backups to keep |

---

## 7. Test Sequence (Quick Validation)

```
1. Pull latest DR.vahid on both PC A and PC B
2. python main.py → log in → select a new study (not yet downloaded)
3. Observe: first series opens in < 3s, subsequent series < 2s (DL_WARMUP pre-caching)
4. Scroll series — check no freeze during download (stale drain guard active)
5. Wait for download to complete → open ZetaBoost warmup phase
6. Switch between all series — each should load in < 300ms (ZetaBoost L1 hit)
7. Grab log file → run extract commands from METRICS_TRACKING_v2.2.3.x.md §13
8. Fill in PC A / PC B columns and compare
```

---

## 8. Cross-PC Improvement Cycle

See `docs/CROSS_PC_IMPROVEMENT_WORKFLOW.md` for the full PC A → GitHub → PC B → compare cycle.

**Stable backup:** `backups/v2.2.2_2026-02-19/` (pre-optimization baseline; safe rollback point)
