# FAST Viewer — Optimization State of the System (2026-04-29)

> **Read this first** before opening any other FAST-viewer / overlap performance plan.
> This document is the canonical reference for "where we are, what's already
> optimized, what's the real bottleneck, what to do next." It collapses ten
> phases (F0–F11) plus the post-pivot G-series instrumentation into a single
> view so the next session does not restart from zero.
>
> **Companion docs:**
> - Master plan with per-step actions: `plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md`
> - KPI definitions and parser: `tools/performance/clearcanvas_aipacs_kpi_harness.py`
> - Per-frame log catalog: `docs/performance/FAST_VIEWER_KPI_CATALOG.md`
> - Stable-version invariants (R1–R20): `.github/copilot-instructions.md`

---

## 1 — One-paragraph status

After ten committed phases (F0 baseline & tooling → F11 stack sampler) the
**FAST pipeline per-frame compute path is no longer the bottleneck** under
real download-overlap drag. Live `[FAST_DRAG_KPI]` summaries on PC A show
`handler_p95_ms` at 3–22 ms (within the 16 ms budget for almost every burst)
while `event_p95_ms` peaks at 559–608 ms and `ui_lag_max_ms` hits
**1842–2496 ms** — the user-visible freeze is the Qt event loop being
blocked, not pipeline work. Two observation phases (F7 paint percentiles,
F8 main-thread stall probe) confirm `prefetch_per_s ≈ 0` and
`bg_decode_count ≈ 0` during the worst freezes. Two defer phases
(F9 Layer 2b body, F10 terminal `_grow_progressive_fast`) shipped and **fire
correctly**, but **a 1201 ms drag-active stall remains** with **558 ms of
pure log silence** — proof that something *outside* the layers we have
instrumented holds the GIL. F11 (main-thread stack sampler) was just
shipped and is the next-log diagnostic. Until F11 names the silent blocker,
all further code-path optimizations are speculative.

---

## 2 — What we believe vs what we have proved (post-pivot)

| Belief that drove F0–F6 | Status after F7–F11 evidence | Action |
|---|---|---|
| The per-frame decode/render path is the user-visible bottleneck. | **Falsified** for real drag. Synthetic harsh shows `decode_only_p95=75 ms` for 4.74 % of frames; real drag shows `handler_p95=3–22 ms`. | Synthetic decode KPIs remain useful gating signals but do **not** correlate with user pain. |
| Cache hit ratio < 85 % is a target. | **Already 95.3 %**. F7 (adaptive surrogate radius) deferred indefinitely. | Don't spend more effort on cache widening. |
| Foreground decode contention with prefetch is the cause of long frames. | **Falsified.** Foreground is already inline; prefetch lane has its own executor. F4/F5 deferred. | Don't separate or coalesce decode lanes. |
| The 27 s priority-handoff stall (3 production sessions × N exhausts/day) was the dominant DM-side bug. | **Confirmed** (759 lifetime exhausts on PC A pre-fix). F3.5.1/F3.5.2/F3.5.3 shipped — synthetic post baseline shows 0 exhausts on the 25 s peer-hold scenario. | F3.5.4 default-on flip blocked only on installed-build refresh + 1 day soak. |
| Frame prefetch during drag (W/L on background) was a high-leverage win. | **Plausible but not yet measurable** in synthetic; relies on `is_protected_drag_active()` which the synthetic stub does not enter. | Re-measure on next live log; if `handler_p95` drops in `bg_decode=0` bursts, the win is real. |
| Layer 2b / terminal grow during drag is a top-3 user-visible spike. | **Confirmed** then **mitigated** in F9/F10. Both gates fire in the latest log. But the residual 1201 ms stall is **NOT** Layer 2b or terminal grow (they were deferred at the time of the stall). | Find the *next* silent blocker — which is what F11 is for. |
| The drag-active main-thread freezes are a single-cause problem. | **Falsified.** F9 + F10 covered two causes (large progressive grow, large Layer 2b body) and the freeze did not vanish — there is at least a third cause. | Treat each remaining stall as an independent investigation. |

**Summary lesson:** The original "100 %-improvement" framing assumed a single
hot path. The actual evidence after F7/F8 is that the freeze surface is
**multiple competing main-thread events** — each individually 200–600 ms —
that compose into multi-second freezes when they line up. We will not
unblock the user by optimizing one path; we have to enumerate and defer
each one. The remaining work is *enumeration*, not *clever rewrites*.

---

## 3 — Phase ledger (F0–F11 + G-series)

Each row: phase id → what it tested/changed → committed (commit short SHA)
→ outcome category → keep / deprecate. Status as of `8325add0` (HEAD).

### F-series (master plan: overlap KPI lane + targeted code wins)

| ID | Title | Commit | Outcome | Keep? |
|---|---|---|---|---|
| F0.2 | Overlap KPI parser + `parse_overlap_log_text` | `bb8294fa` | DONE — parser stable | ✅ keep |
| F0.4 | Synthetic overlap runner (headless) | `ddb773cf` | DONE — useful for regression gating; **does not exercise protected-drag latch** | ✅ keep, but never trust as a real-world signal |
| F0.5 | Real-world v0 anchor | (not committed; superseded by F0.5b) | Replaced by harsh synthetic + live-log Tier-2 | — |
| F0.6 | Harsh-preset CLI flag in synthetic runner | `2489af61` | DONE — `preset=harsh` is the canonical synthetic anchor | ✅ keep |
| F1.1 | Settled-frame pixel-hash gate | `f3118ad4` | DONE — golden hashes locked | ✅ keep (regression gate) |
| F1.2 | Drag-mode pixel-hash gate (surrogate ≥ 99 %, settle exact) | `4bdb422f` | DONE | ✅ keep |
| F1.3 | CI wiring `tools/dev/run_overlap_regression.ps1` (43 tests, ~12 s) | `fbb9d105` | DONE — must stay green | ✅ keep — **mandatory before every FAST-pipeline commit** |
| F2.1 | `[OVERLAP_SCENARIO]` emit at 3 return paths | `9f180262` | DONE | ✅ keep |
| F2.1b | Sentinel emits (decode + drag-begin/end) bypass 1-in-N | `f2031f9f` | DONE — captures the 4.7 % decode tail under live load | ✅ keep |
| F2.2 | Manual re-baseline | — | DEFERRED indefinitely (superseded by F2.4) | ❌ drop |
| F2.3 | Wall-clock fps parser fix | `2489af61` | DONE | ✅ keep |
| F2.4 | Cache-source-split KPIs (decode_only / settled / hit / surrogate) | `fea7f9b1` | DONE — current canonical KPI block | ✅ keep |
| F2.4b | Real-world `[FAST_DRAG_KPI]` parser (Tier-2) | `f2031f9f` | DONE — Tier-2 north stars | ✅ keep |
| F3.1 | Pre-queue prefetch cancellation guards | `feb7f2f7` | DONE — synthetic `cancelled_task_ratio` improved | ✅ keep (R18) |
| F3.2 | Direction-flip prefetch invalidation | `a293b1d8` | DONE | ✅ keep (R18) |
| F3.3 | Cross-PC verification baseline v2 | — | PENDING (PC B unavailable) | ⏸ defer |
| F3.5.1 | DM priority-handoff instrumentation `[INTENT_PRIORITY]` | `0bdf4fae` | DONE — KPI parser + 22 tests | ✅ keep (R19) |
| F3.5.2 | V2 wall-clock retry + reclamation-race CAS (env-gated default-off) | `30365119` | DONE — synthetic post = 0 exhausts | ✅ keep (R20) |
| F3.5.3 | Priority-handoff toast (default-on) | `e3ceaaaf` | DONE — additive observer signal | ✅ keep |
| F3.5.4 | `AIPACS_INTENT_HANDOFF_V2=1` default-on flip | — | BLOCKED on PC A installed-build refresh + 1 day soak | ⏸ ready to ship after install |
| F4 | Foreground decode lane separation | — | **DEFERRED** — falsified by live-log evidence (`handler_p95=3–22 ms`) | ❌ skip unless decode share > 5 % in real log |
| F5 | In-flight decode coalescing | — | **DEFERRED** — same rationale as F4 | ❌ skip same trigger |
| F6 | Frame prefetch during protected drag (W/L on background) | `bd89386d` | DONE in code; **synthetic flat** (synthetic doesn't enter protected-drag latch); needs live-log validation | ⏳ pending live-log win signature |
| F7 | Adaptive surrogate radius for overlap | — | **DEFERRED** — cache_hit=95.3 % already; widening risks R1 surrogate-staleness break | ❌ skip |
| F8 | Header pre-warm via DM completion hook | — | NOT STARTED — low risk, addresses cold-cache decode share | ⏸ candidate after F11 names the silent blocker |
| F9 (master plan) | DM disk-flush backpressure (opt-in) | — | NOT STARTED | ⏸ low priority |
| F10 (master plan) | Acceptance / docs / release | — | BLOCKED on Tier-2 KPI targets | ⏸ |
| F11 (master plan) | Defer terminal progressive grow during active drag | (renamed → ad-hoc F10) | RENAMED — see G-series mapping below | — |

### G-series (post-pivot ad-hoc instrumentation & defers, 2026-04-29)

> These commits used "F7–F11" labels in their messages, which **collides** with
> the master plan F-series above. Going forward they are referred to as
> **G1–G5** to keep the namespace clean. The git tags in the commit messages
> remain unchanged (history is immutable); only the planning docs use the new
> names.

| ID | Commit tag | Commit | What it does | Status |
|---|---|---|---|---|
| **G1** | `[F7]` | `8c9a9157` | Paint observability — `paint_count`/`paint_p50_ms`/`paint_p95_ms` in `[FAST_DRAG_KPI]` (observation-only). | ✅ shipped, must stay |
| **G2** | `[F8]` | `9f075e34` | Main-thread stall probe — 50 ms QTimer, logs `[MAIN_THREAD_STALL] gap_ms=X drag_active=BOOL` whenever interval > 100 ms. | ✅ shipped, must stay |
| **G3** | `[F9]` | `4eeba717` | Defer Layer 2b body (`_on_series_download_fully_complete_impl`) up to 6 retries (~1.35 s window) during FAST hot drag. R4 honored via force-run after max retries. | ✅ shipped, fires correctly |
| **G4** | `[F10]` | `d2fa9131` | Defer terminal `_grow_progressive_fast` (`_flush_progressive_grow_impl`) up to 6 retries during FAST hot drag. R4 honored via force-run after max retries. **This is what the master plan called "F11 — Defer terminal progressive grow during active drag" — same intent, shipped earlier.** | ✅ shipped, fires correctly |
| **G5** | `[F11]` | `8325add0` | Main-thread stack sampler — daemon thread samples `sys._current_frames()` and dumps the top 15 frames as `[MAIN_THREAD_STALL_TRACE]` whenever the F8 probe detects a > 400 ms stall. Rate-limited to 1 dump/sec. | ✅ shipped, **next log will identify the residual silent blocker** |

**Numbering rule going forward:**
- The master plan F-series (`plan-fastViewerOverlap*.md`) owns the F-namespace.
- Any new ad-hoc instrumentation/defer work uses the **G-series** in this
  document. When new work matches a master-plan F-step, use the F-id and
  cross-reference here.

---

## 4 — Current KPI snapshot (where we are)

### Synthetic (harsh anchor, `generated-files/benchmarks/post_f6_harsh.json`, 2026-04-29 PM)

| KPI | Value | Tier-1 target | Tier-1 status |
|---|---|---|---|
| `overlap_decode_only_p95_ms` | 81.98 | ≤ 7.0 | ❌ far off — but irrelevant to real drag (see Tier-2) |
| `overlap_decode_only_max_ms` | 162.84 | ≤ 40.0 | ❌ same |
| `overlap_decode_sample_share_pct` | 5.33 | ≤ 2.5 | close |
| `overlap_slow_frame_count_16ms` | 72 / 30 s | ≤ 1 / 30 s | ❌ — but 100 % are decode-source, addressable only by avoiding decode (more cache hits, which is already at 95 %) |
| `overlap_cache_hit_ratio_pct` | 94.67 | ≥ 85 | ✅ 11 pts above target |
| `overlap_effective_fps` | 50.24 | ≥ 30 | ✅ |

### Real-world (`[FAST_DRAG_KPI]` end-of-burst summaries, 2026-04-29 PM live log)

| Burst | duration_s | event_p95_ms | handler_p95_ms | ui_lag_max_ms | prefetch_per_s | bg_decode |
|---|---|---|---|---|---|---|
| 1 | 0.91 | 141.9 | 60.7 | 162.8 | 11.0 | 10 |
| **2** | **3.99** | 337.7 | 6.4 | **2496.2** | 0.0 | 0 |
| 6 | 1.88 | 222.4 | 9.7 | 356.9 | 6.9 | 13 |
| 9 | 0.92 | 168.2 | 21.5 | 153.8 | 12.0 | 11 |
| 11 | 1.43 | 199.9 | 11.0 | 245.4 | 13.3 | 19 |
| **12** | **3.83** | **559.1** | 5.8 | **1842.8** | 0.3 | 1 |

| Tier-2 KPI | Worst observed | Target | Status |
|---|---|---|---|
| `overlap_drag_event_p95_max_ms` | 607.9 (earlier) / 559.1 (latest) | ≤ 300 | ❌ |
| `overlap_drag_ui_lag_max_max_ms` | **2496.2** | ≤ 180 | ❌ — **primary north star, ~14× over budget** |
| `overlap_drag_handler_p95_max_ms` | 60.7 (Burst 1, with `bg_decode=10`); 3–22 ms otherwise | ≤ 16 | ⚠️ one outlier; otherwise within budget |
| `overlap_drag_background_decode_count_total` | 0 in worst freezes | hold at 0 (R3) | ✅ R3 invariant intact |

**Reading:** Bursts 2 and 12 are the user-visible freezes. Both have
`handler_p95 ≤ 6.4 ms` and `prefetch_per_s ≈ 0` — the FAST pipeline is
**idle** during these freezes. The main thread is being held by something
the pipeline does not see.

### Latest residual stall (post-G3 + G4, pre-G5 log)

- 1201.9 ms `[MAIN_THREAD_STALL] drag_active=True` at 15:47:38.435.
- **558 ms log silence** between the F9 retry=2 emit (15:47:37.876) and the
  next probe tick (15:47:38.435).
- F9 (Layer 2b) and F10 (terminal grow) both deferred during this window —
  so the blocker is **neither** of them.
- G5 (stack sampler, just shipped at `8325add0`) will name it on next live log.

---

## 5 — Bottleneck map (what is and isn't optimized)

### Already optimized — do NOT spend more time here

| Area | Why it's done | Evidence |
|---|---|---|
| **Per-frame compute (`Lightweight2DPipeline.get_rendered_frame`)** | `handler_p95_ms` 3–22 ms in real drag (under the 16 ms budget except under prefetch saturation). Surrogate path is ~0 ms. Decode-cache miss is ~13–82 ms but covers ≤ 5 % of frames. | Live `[FAST_DRAG_KPI]` |
| **Cache hit ratio** | 94.7–95.6 % on the harsh synthetic anchor; widening risks R1 surrogate-staleness break. | Synthetic harsh; F7 deferred |
| **Decode lanes (foreground vs prefetch isolation)** | Foreground is inline (no executor); prefetch has its own thread pool; they don't compete on the main thread. | F4 falsified; live `bg_decode=0` in worst freezes |
| **Prefetch admission shell (R1, R3, R12, R18)** | Surrogate-staleness break + protected-drag CACHE_WARM denial + P1 admission + pre-queue cancellation. | F3.1/F3.2 shipped; tests in `test_b34_interaction_aware_policy.py` (21/21 GREEN), `test_prefetch_pre_queue_cancel.py` (9/9 GREEN) |
| **Disk pixel cache (B3.12)** | 11.5× speedup on series re-open; async writes; LRU; binary `.apc` format. | `test_disk_pixel_cache.py` |
| **Decode service subprocess (B3.11)** | GIL-isolated background decode for prefetch; foreground stays inline (avoids 2.4 ms IPC overhead). | `test_decode_service.py` |
| **DM priority-handoff (F3.5.1/F3.5.2/F3.5.3)** | Wall-clock retry budget eliminates 27 s exhaust failure mode (env-gated default-off, ready to flip). | `test_priority_handoff_v2.py`, synthetic pre/post baselines |
| **Layer 2b body during drag (G3)** | Bounded-retry defer of `_on_series_download_fully_complete_impl`. Honored R4 via force-run after max retries. | Live log shows G3 fires + force-runs correctly |
| **Terminal `_grow_progressive_fast` during drag (G4)** | Bounded-retry defer of `_flush_progressive_grow_impl` terminal path. | Live log shows G4 fires + force-runs correctly |
| **Stack-drag smoothness rules (R1–R18, v2.3.6/2.3.7/2.3.8)** | Surrogate-staleness break, protected-drag latch + keepalive, async logging, GC-suppress, P1 prefetch, FAST↔Advanced unified latch, OpenCV filter `preserve_dimensions=True`. | `.github/copilot-instructions.md` Critical rules |
| **Worker subprocess priority (BELOW_NORMAL on launch)** | Reduces viewer↔download priority inversion; R13 throttle infrastructure preserved but default-off after IPC mutex inversion regression. | R13 docs |

### Probably optimized — keep monitoring but don't re-engineer

| Area | Confidence | Why |
|---|---|---|
| Frame prefetch (G3 / F6) on protected drag P1 lane | Medium-high | Code is correct and admission tests green; synthetic doesn't exercise the latch so we can't measure win; needs one live-log confirmation that `handler_p95` drops in cache-hit drags |
| `[FAST_DRAG_KPI]` paint observability (G1) | High | Adds fields, no behavior change |
| Main-thread stall probe (G2) | High | 50 ms QTimer, ~0.1 % CPU |

### **NOT optimized — this is where the user freeze lives**

| Suspect | Evidence | Status |
|---|---|---|
| **Unknown silent main-thread blocker (the 558 ms gap)** | F9/F10 both deferred at the time of the 1201 ms stall, yet drag-active stall persisted with zero log emissions. Something in the Qt slot/signal graph is running synchronously and emits no log. | **G5 (stack sampler) will name it on next log — top priority** |
| `thumbnail_manager.complete_series_download` (or its peers) | Earlier session saw 731 ms `start_series_download` stall; finalization may also block | Suspect candidate; awaiting G5 trace |
| ZetaBoost lazy-volume promotion / `set_study_download_complete` | Architecturally empty in FAST mode (R-rule); but `notify_global_download_stop` may fan out to multiple subscribers synchronously | Suspect candidate; awaiting G5 trace |
| Garbage collection (gen-2) | GC is suppressed during stack drag (R6) and re-enabled 1500 ms after end; but a forced `gc.collect()` from elsewhere (e.g. external lib) would still run | Lower probability given R6 |
| `_finalize_progressive_series` defer side path | Routed through `_cleanup_progressive_lifecycle_state`; could be slow if guard sets are large | Suspect candidate |
| Qt signal fan-out from `series_downloaded` / `seriesDownloadCompleted` | Multiple slots registered (DM widget, viewer, thumbnail, home); synchronous emit could cascade | Suspect candidate |
| OS-level disk flush / fsync from DM subprocess | Not on viewer's main thread, but contention on file handles / NTFS mft locks could spill | Lower probability |
| Log queue listener back-pressure | R7 mandates async logging; but if the queue listener itself stalls the Qt thread waits on `Logger.handle()`'s implicit lock | Verify queue depth in next G5 dump |

---

## 6 — What to focus on next (priority order)

### Immediate (block on current evidence)

1. **G5 live log** — user runs the app with HEAD = `8325add0`, reproduces the
   freeze, and ships `user_data/logs/viewer_diagnostics.log`. The
   `[MAIN_THREAD_STALL_TRACE]` lines will name the silent blocker.
2. **G6** (next) — bounded defer of whatever G5 names. Pattern is identical
   to G3/G4: 200 ms × 6 retries, force-run after max, mirror to plugin
   package, regression bundle green, ship.

### Near-term (after G5 names the blocker)

3. **F3.5.4** — flip `AIPACS_INTENT_HANDOFF_V2=1` default. Blocked only on
   "PC A installed build = `30365119`+ AND ≥ 1 day soak with `[INTENT_PRIORITY]`
   in production logs."
4. **Live-log validation of F6 / G3 / G4 win signatures** — collect a fresh
   `[FAST_DRAG_KPI]` series, confirm `handler_p95` drops on cache-hit drags
   (F6) and that no `[MAIN_THREAD_STALL]` lines correlate with deferred
   Layer 2b / terminal grow windows (G3 / G4).

### Mid-term (after G6)

5. **Continue the G-series** until `overlap_drag_ui_lag_max_max_ms ≤ 180 ms`
   (the Tier-2 north star). Each remaining stall ≥ 200 ms is a candidate
   G-step. Expected count from current evidence: 2–4 more (the silent
   blocker, possibly `complete_series_download`, possibly a Qt signal fan-out,
   possibly progressive lifecycle cleanup).
6. **F8 (master plan)** — header pre-warm via DM completion hook. Low risk,
   reduces cold-cache decode share. Only valuable if a future log shows
   `decode_sample_share > 5 %` *and* slow frames correlate with that share.

### Do NOT pursue

7. **F4 / F5** — falsified by live-log evidence; pipeline compute is not
   the bottleneck.
8. **F7** — cache hit ratio already past target.
9. **Speculative master-plan optimizations beyond F8** — every remaining
   master-plan F-step is gated on real-world KPIs that are already at
   target. Don't burn budget on them until G-series has driven `ui_lag_max`
   under 200 ms.

---

## 7 — Where everything is (file map for future sessions)

### KPI lane
- Synthetic runner: `tools/performance/synthetic_overlap_runner.py`
- Live-log parser: `tools/performance/clearcanvas_aipacs_kpi_harness.py`
  - `parse_overlap_log_text` — per-frame `[OVERLAP_SCENARIO]`
  - `parse_drag_kpi_log_text` — end-of-burst `[FAST_DRAG_KPI]` (Tier-2)
  - `parse_priority_handoff_log_text` — `[INTENT_PRIORITY]` (F3.5)
- Regression bundle: `tools/dev/run_overlap_regression.ps1` (43 tests, ~12 s)
- Anchors:
  - `generated-files/benchmarks/overlap_baseline_v0_synthetic_harsh.json` (canonical synthetic)
  - `generated-files/benchmarks/post_f6_harsh.json` (post-F6 synthetic)
  - `generated-files/benchmarks/priority_handoff_v2_pre.json` / `_post.json`

### Code (FAST pipeline only)
- Per-frame: `modules/viewer/fast/lightweight_2d_pipeline.py` (+ plugin mirror under `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/`)
- Admission: `modules/viewer/fast/ui_throttle.py` + `system_load_controller.py`
- Backend: `modules/viewer/fast/qt_slice_viewer.py`, `qt_viewer_bridge.py`
- Decoder: `modules/viewer/fast/decode_service.py`, `disk_pixel_cache.py`
- Progressive lifecycle (G3 / G4 live here): `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py`
- DM coordinator (F3.5): `modules/download_manager/coordinator/series_intent_coordinator.py`

### Probes (G-series)
- `main.py` lines ~482–630 — F8/G2 stall probe + F11/G5 stack sampler
- `[FAST_DRAG_KPI]` emit: `qt_viewer_bridge.py::_log_drag_metrics_summary`
- `[OVERLAP_SCENARIO]` emit: `lightweight_2d_pipeline.py::_maybe_emit_overlap_tag`
- `[INTENT_PRIORITY]` emit: `series_intent_coordinator.py::_emit_intent_priority`

### Tests (must stay green)
- `tools/dev/run_overlap_regression.ps1` — bundled gate
- `tests/viewer/test_fast_viewer_pipeline.py` — 61 tests (158 with mixins)
- `tests/viewer/test_b34_interaction_aware_policy.py` — 21+ admission tests
- `tests/viewer/test_overlap_pixel_quality.py` — F1 hash gate
- `tests/performance/test_overlap_kpi_parser.py` — parser contract
- `tests/performance/test_priority_handoff_kpi_parser.py` — F3.5 parser contract
- `tests/download_manager/test_priority_handoff_v2.py` + `_instrumentation.py`

### Stable-version invariants (R-rules — DO NOT regress)
- `.github/copilot-instructions.md` § Critical rules
- R1 (surrogate-staleness break), R2 (protected-drag latch + keepalive),
  R3 (PREFETCH+CACHE_WARM denial during drag), R4 (terminal completion
  always fires — relaxed in G3/G4 to "force-run after bounded defer"),
  R5 (DM `_apply_throttled_progress` skip during drag), R6 (GC disable
  during stack drag), R7 (async logging), R12 (P1 prefetch admission),
  R15 (FAST↔Advanced unified latch), R16 (VTK `FirstRender` consume order),
  R17 (FAST `preserve_dimensions=True`), R18 (pre-queue cancellation +
  direction-flip target invalidation), R19 (`[INTENT_PRIORITY]` instrumentation),
  R20 (V2 wall-clock retry).

---

## 8 — Disk / RAM / database / network — what's already optimized

| Layer | Optimization | Doc |
|---|---|---|
| **Disk pixel cache** | L2 binary `.apc` format with sha256 key, async writes, LRU 2 GB cap, atomic tmp→rename | B3.12 / `disk_pixel_cache.py` |
| **DICOM decode** | `pydicom` foreground inline + subprocess background (decode_service); bypassed for surrogate path | B3.11 |
| **RAM frame cache** | Per-pipeline `_frame_cache` keyed by (idx, W/L); exact-filtered match outranks unfiltered during fast interaction | 2026-04-17 rule |
| **RAM pixel cache** | Per-pipeline `_pixel_cache`; nearest-cached surrogate ±10 (±20 during overlap or fast drag) | B3.7 / `_find_nearest_cached_pixel` |
| **Database** | WAL mode; FK indexes on `studies.patient_fk`, `series.study_fk`, `instances.series_fk`, `instances(series_fk, group_id)`; lazy connection pool; commit-required context manager; sub-5 ms log throttle | `database/core.py` / v2.2.8.0 rules |
| **Sockets** | `sendall()` only (no partial writes); `_recv_exact()` only; 50 MB response cap; lazy connection pool; structured retry layers (3+5+3); health monitor (R30–R34); login fail-fast (no retry) | `modules/network/socket_*.py` |
| **gRPC** | `_ensure_stub()` auto-reconnect; thumbnail-only (not on download hot path) | `modules/network/grpc_client.py` |
| **Logging** | QueueHandler/QueueListener async pipeline; file handlers on listener thread; console sync; `AIPACS_LOG_SYNC=1` escape hatch | R7 |
| **GC** | `gc.disable()` during stack drag burst; re-enabled 1500 ms after end via QTimer | R6 |
| **CPU priority** | Main process `ABOVE_NORMAL_PRIORITY_CLASS` (default; opt-in via `AIPACS_PRIORITY`); subprocess `BELOW_NORMAL` at start | R8, R13 |
| **Decode workers** | `AIPACS_DECODE_WORKERS=1` (default), capped at 4 (more = IPC contention) | R9 |
| **Download retries** | 3 layers: send_request (3 retries), connect_with_retry (5 exp+jitter), per-series (3 rounds 3s/6s/12s) | v2.2.7.1 rules |
| **Download validation** | R17a (resume non-terminal), R17b (verify .dcm files on disk), R19b (batch-skip with file verification), R20 (file deletion on per-patient retry) | v2.2.7.x rules |

**Conclusion:** Disk, RAM, DB, network, and OS-level concerns are
**well-tuned**. The remaining bottleneck is **Qt main-thread scheduling**,
not throughput.

---

## 9 — Mental model for future optimizers

When the user reports a freeze in the FAST viewer during download overlap:

1. **First**, check `[FAST_DRAG_KPI]` for the burst. If `handler_p95 ≤ 16 ms`,
   the pipeline is fine — look elsewhere.
2. **Second**, check `[MAIN_THREAD_STALL]` lines around the same timestamp.
   `gap_ms` tells you how long Qt was blocked.
3. **Third** (post-G5), check `[MAIN_THREAD_STALL_TRACE]` lines. They name
   the slot/function that holds the GIL.
4. **Fourth**, identify whether the named function is gated by
   `is_protected_drag_active()`. If not, it's a candidate G-step
   (bounded-retry defer during drag).
5. **Fifth**, write the smallest possible defer (mirror the G3/G4 pattern),
   ship behind a force-run cap, mirror to plugin package, run the F1
   regression bundle, request a fresh log.

**The wrong things to do:**

- Optimize the per-frame compute path further. It's already under budget.
- Add new admission classes / thread pools. R3/R12/R18 already cover
  prefetch and cache-warm.
- Touch surrogate or cache logic. R1 + B3.7 are the load-bearing wins;
  changes risk visible regressions caught only by the F1 hash gate.
- Skip the F1 regression bundle. It is the only proof that pixels are
  byte-identical. Use `tools/dev/run_overlap_regression.ps1`.

---

## 10 — Glossary of phase IDs (for cross-document searches)

| ID | Master plan? | Commit subject prefix | What |
|---|---|---|---|
| F0–F2.4b | Yes | `[F0.x]` / `[F2.x]` | Tooling and KPI lane |
| F3.x | Yes | `[F3.x]` | Pre-queue cancellation |
| F3.5.x | Yes | `[F3.5.x]` | DM priority-handoff |
| F4 / F5 | Yes | — (deferred) | Decode lane separation / coalescing — **DEFERRED, do not implement without trigger** |
| F6 | Yes | `[F6]` | Frame prefetch on protected drag |
| F7 / F8 / F9 (master plan) | Yes | — | Adaptive radius / header pre-warm / DM disk-flush — **F7 deferred; F8/F9 not started** |
| F10 (master plan) | Yes | — | Acceptance + release — **blocked on Tier-2 KPI** |
| **G1** | This doc only | `[F7]` | Paint observability |
| **G2** | This doc only | `[F8]` | Main-thread stall probe |
| **G3** | This doc only | `[F9]` | Layer 2b defer during drag |
| **G4** | This doc only | `[F10]` | Terminal `_grow_progressive_fast` defer during drag (= master plan's optional "F11") |
| **G5** | This doc only | `[F11]` | Main-thread stack sampler |
| **G6+** | This doc only | `[G6]` etc. (going forward) | Whatever G5 names |

**Naming rule going forward:** all new ad-hoc instrumentation/defer work
uses `[Gn]` commit prefix (not `[Fn]`) to avoid the namespace collision
that occurred in 2026-04-29.

---

*Last updated: 2026-04-29 PM after `8325add0` (G5 stack sampler shipped).
Next checkpoint: live-log run with G5 active.*
