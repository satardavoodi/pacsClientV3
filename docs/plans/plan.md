# FAST Mode — Unified Master Plan v3.1 (Merged)

**Project:** AI-PACS FAST Viewer (`pydicom_qt`)  
**Date:** 2026-04-17 (runtime benchmark capture + orchestration alignment update)  
**Scope:** FAST mode only (Advanced/VTK must remain unaffected)

---

## Performance Surgery Tracker (2026-05-05)

> The "performance surgery" is a phased architectural programme to eliminate all
> remaining overhead in FAST mode at the cell/widget, service, and UI layers.
> Each phase is independently committed, gate-tested, and merged before the next starts.
> Full safety constraints in `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md`.

| Phase | Name | Status | Branch | Plan doc |
|-------|------|--------|--------|----------|
| **P1** | FAST 2D Cell Separation — `QtFastContainer` replaces `VTKWidget` in FAST mode | ✅ **DONE** (Steps A–C) | `beta-version` @ `18ab5fc` | `docs/plans/performance/FAST_2D_CELL_SEPARATION_PLAN.md` |
| **P1-D** | Full VTK-free `QtFastContainer.__init__` — wire `QtViewerBridge` directly | ⏳ Next | `beta-version` | same |
| **P2** | Catalog Service — decouple series-list queries from VTK load path | 🔲 Planned | — | `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md §4` |
| **P3** | DM Control-Plane Subprocess — move coordinator to background process | 🔲 Planned | — | `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md §5` |
| **P4** | DM UI Rate Limiting — coalesce DM table rebuilds | 🔲 Planned | — | `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md §6` |
| **P5** | CPU Budget File — shared load-shedding config | 🔲 Planned | — | `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md §7` |
| **P6** | Signal Routing — direct signal paths, eliminate fan-out | 🔲 Planned | — | `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md §8` |
| **P7** | Architecture Tests — automated regression guards for all phases | 🔲 Planned | — | `docs/plans/VIEWER_CELL_SEPARATION_SAFETY_PLAN.md §9` |

### P1 completion notes (2026-05-05)
- `QtFastContainer(QWidget)` created with `_NullVtkObject` / `_NullImageViewer` stubs
- All crash sites C1–C9 covered by null stubs (zero call-site changes needed)
- Eagle Eye / MPR / Advanced VTK path completely unaffected
- `is_vtk_widget()` updated to accept `QtFastContainer`
- Factory switch in `_pw_viewers.py` (primary) and `_vc_layout.py` (fallback)
- Test gate: **167/168 passing** (1 pre-existing timing failure, unrelated)
- `_qt_bridge` wired at series-load time by existing `_bind_backend_from_metadata` — no bridge changes needed
- **Step D** (wire `QtViewerBridge` directly in `__init__`) is the immediate next step

---

## <u>Prompt (Execution Contract)</u>

- Keep FAST and Advanced pipelines strictly separate.
- Prioritize user-visible responsiveness over background throughput.
- Choose optimization targets from **concurrent-load KPI evidence**, not microbenchmarks alone.
- No random tuning. Every change must include: bounded diff, tests/scenario, KPI delta, doc update.
- Do not reintroduce VTK rendering into FAST path.
- Preserve tool lifecycle parity (tool complete → default mode → toolbar uncheck).

---

## Current merged status (truthful state)

### Phase status

- **Phase A (backend migration):** DONE
- **Phase B1 (visual debug/fix):** DONE
- **Phase B1.5 (tool behavior completion):** DONE (implementation)
- **Phase B1.6 (interaction parity + scroll policy):** DONE
- **Tools Track T2:** DONE (implementation + validation), optional coverage hardening
- **Phase B2 (instrumentation + baseline):** DONE
- **Phase B2.5 (concurrent-load baseline):** DONE (baseline captured, report in `docs/performance/B25_BASELINE_REPORT.md`)
- **Phase B3.1 (hot-path optimization):** DONE
- **Phase B3.2 (contention optimization — iteration 1):** DONE (adaptive prefetch, report in `docs/performance/B32_ADAPTIVE_PREFETCH_REPORT.md`)
- **Phase B3.3 (stack-drag fast_interaction parity):** DONE (report in `docs/performance/B33_STACK_DRAG_PARITY_REPORT.md`)
- **Phase B3.4 (unified interaction-aware policy):** DONE — 149 tests pass
- **Phase B3.5 (progressive display CPU offload):** DONE — 161 tests pass, main-thread grow cost reduced ~80-90%
- **Phase B3.6 (booster interaction gate + prefetch stale prevention):** DONE — 181 tests pass (report in `docs/performance/B36_BOOSTER_INTERACTION_GATE_REPORT.md`)
- **Phase B3.7 (cache-first fast scroll):** DONE — nearest-cached surrogate (0ms decode), prefetch radius 1→3
- **Phase B3.8 (reliability & diagnostics):** DONE — per-frame scroll metrics, Layer 2b FAST viewer fix, post-completion cache warm, duplicate guard
- **Phase B3.9 (decoder plugins):** DONE — all codec plugins already installed (pylibjpeg-libjpeg, pylibjpeg-openjpeg, pylibjpeg-rle), all Transfer Syntaxes have native decoders. Irrelevant for current data (all uncompressed).
- **Phase B3.10 (pydicom upgrade):** DEFERRED — upgrade from 2.4.4→3.x has breaking API risk. Low priority since decode bottleneck is parsing, not decompression.
- **Phase B3.11 (decode service):** DONE — subprocess decode via ProcessPoolExecutor(1, spawn), 2.38ms IPC overhead (26%), GIL isolation for prefetch, 9 tests pass
- **Phase B3.12 (disk pixel cache):** DONE — L2 persistent cache, 0.43ms read vs 4.88ms pydicom decode (11.5× speedup), 12 tests pass
- **Phase B4 (stabilization/cleanup):** IN PROGRESS (B4.1/B4.2/B4.4 implemented; B4.3 helper-fronted lifecycle reads + restart-after-DONE fix landed; download-aware orchestration throttling introduced; terminal idempotence bridge shipped; load-controller shell + UI-lag probe shipped; policy-driven grow/cache-warm shedding shipped; runtime recapture and helper-authority closure still pending)

### What changed since older plan

- Old state (`B2 pending`, `B3 blocked`) is no longer accurate.
- Hot-path optimization work is complete and measured.
- Performance program now splits into:
  - **Layer 1:** component speed (done for hot path)
  - **Layer 2:** system contention and architecture simplification is now the active focus after baseline capture

---

## Goals

### Goal 1 — Performance (Critical)

- Maintain smooth scroll and interaction under realistic workloads.
- Keep interactive frame path under 16ms budget.
- Sustain performance under concurrent download/progressive work.

### Goal 2 — Visual correctness

- Tools, overlays, sync indicators, and corner text render correctly at all times.
- Reset/Delete All clears annotations reliably.
- MPR open/close lifecycle remains stable.

---

## Completed work summary

### A) Tool and interaction track (from latest validation)

- Measurement distance correctness (`distance_mm`) verified.
- ROI drag-to-create finalized on mouse release.
- Rotation/flip mapping correctness verified (resolver + paint path).
- Sync UX behavior verified (set/clear sync mode; forwarding flow).
- MPR handoff + restore lifecycle stress scenarios passed (S8/S9/S15).
- Toolbar/bridge cleanup path verified (`delete_all_widgets` + controller clear).

### B) Hot-path performance optimization (B3.1 complete)

Source merged from `docs/performance/FAST_VIEWER_PERF_OPTIMIZATION.md`:

- W/L LUT path for int16/uint16 (`window_to_uint8_fast`) + cache.
- Preserve int16 decode path where safe (avoid float32 conversion overhead).
- Filter skip during active fast interaction.
- Annotation skip/defer during active fast interaction.
- Qt scroll-stop timer (200ms) to restore quality path.
- Hot-path debug logging gated by level checks.
- QImage copy elimination via retained NumPy buffer reference.

### C) FAST stack behavior refinement (2026-04-14)

- **Active-area guard:** stack drag is valid only while pointer remains inside
  both viewer bounds and current image area.
- **Immediate stop rule:** leaving viewer/image area during stack drag cancels
  stack mode instantly (no runaway scrolling outside viewport).
- **Top↔bottom proportional mapping:** drag distance is mapped against viewer
  height so one full-height sweep corresponds approximately to traversing the
  full series range.
- **Volume-size scaling by design:**
  - `<20` slices: naturally slower and more precise (larger px-per-slice)
  - `~50` slices: routine medium response
  - `~100` slices: faster traversal
  - `>200` slices: significantly faster traversal
- **Controlled skipping:** fast drag motion emits multiple slice steps with a
  bounded per-event cap (tier + proportional cap), so high-volume stacks can
  advance by 2/3/4+ when motion is rapid, while sparse MRI stays controlled.

---

## Performance baseline and measured outcome (merged)

### Pre-optimization baseline (synthetic 512×512)

| Metric | Value |
|---|---:|
| W/L P50 | 5.46ms |
| W/L P95 | 10.66ms |
| Filter P50 | 5.00ms |
| Frame P50 | 12.7ms |
| Frame P95 | 37.8ms |
| Slow frames >16ms | 52/200 |
| Slow frames >33ms | 14/200 |
| FPS | 61 |

### Post-optimization (normal render, filter enabled)

| Metric | Before | After | Improvement |
|---|---:|---:|---:|
| W/L P50 | 5.46ms | 1.7ms | 3.2× |
| W/L P95 | 10.66ms | 2.7ms | 3.9× |
| Frame P50 | 12.7ms | 7.1ms | 1.8× |
| Frame P95 | 37.8ms | 9.6ms | 3.9× |
| Slow >16ms | 52/200 | 0/200 | eliminated |
| FPS | 61 | 135 | 2.2× |

### Post-optimization (fast-scroll interactive path)

| Metric | Before | After | Improvement |
|---|---:|---:|---:|
| W/L P50 | 5.46ms | 1.7ms | 3.2× |
| Frame P50 | 12.7ms | 1.8ms | 7.1× |
| Frame P95 | 37.8ms | 2.9ms | 13× |
| Slow >16ms | 52/200 | 0/200 | eliminated |
| FPS | 61 | 518 | 8.5× |

---

## Two-layer performance model (official)

### Layer 1 — Component performance (mostly established)

Track per-subsystem:

- decode latency
- frame generation latency
- W/L stage latency
- conversion/wrap latency
- paint latency
- filter apply latency
- sync/overlay update latency

### Layer 2 — System contention performance (established)

Track under overlap:

- viewer + download
- viewer + download + filter settle
- queue growth/drain
- stale task ratio / cancellation ratio
- recovery latency after bursts
- low-end profile behavior

> Next optimization target must be selected from Layer 2 evidence, not Layer 1 microbenchmarks alone.

---

## Phase B2 — Instrumentation & baseline (DONE)

### Completed

- Synthetic performance benchmark exists (`tests/performance/test_fast_scroll_perf.py`).
- Hot-path KPI capture and before/after evidence exists.
- Scroll interactive vs settled-quality split is implemented/measured.
- Concurrent-load KPI instrumentation and scenario capture (B2.5).
- Queue depth / stale task / cancellation metrics (B2.5).
- Download interference quantification (DII=42.8% baseline, improved post-B3.2).
- Low-end profile baseline captured.

---

## Phase B2.5 — Concurrent-load baseline & contention model (DONE)

### Scenarios captured

1. Viewer-only baseline ✅
2. Viewer + progressive download ✅
3. Viewer + progressive download + filter settle ✅
4. Rapid direction reversal ✅
5. Sync under load ✅
6. Low-end hardware profile ✅
7. Long-session stability ✅

### KPIs captured (see `docs/performance/B25_BASELINE_REPORT.md`)

- DII=42.8%, stale ratio 80-94%, cache hit 0-8.6% (pre-B3.2)
- All required KPIs instrumented and baselined.

---

## Phase B3 — KPI-driven optimization

### B3.1 Hot-path optimization

- **Status:** DONE
- Completed items listed above (LUT, fast-interaction filter defer, annotation defer, timer wiring, logging gates, copy elimination).

### B3.2 Concurrent-load optimization — Iteration 1: Stale-Aware Adaptive Prefetch

- **Status:** DONE
- **Evidence:** B2.5 baseline (DII=42.8%, stale ratio 80-94%, cache hit 0-8.6%)
- **Root cause:** Fixed ±20 prefetch window submits ~40 tasks per scroll event regardless of scroll speed. Workers decode 3-8ms per slice (holding GIL). User scrolls faster than workers complete → 80-94% of decode work is wasted → GIL convoy amplified → cache polluted with stale entries.

**Policy: Generation-Gated Adaptive Prefetch**

1. **Generation counter** — monotonically increasing `_prefetch_generation` int, bumped on every `_prefetch_around()` call. Each submitted task carries its birth generation. Before the heavy `pydicom.dcmread`, worker checks if its generation is still current — if not, exits immediately without holding GIL.
2. **Adaptive window sizing** — window radius = f(scroll_velocity):
   - Fast scroll (≥4 slices in last 200ms): radius = 3 (direction-only)
   - Medium scroll (2-3 slices in 200ms): radius = 8
   - Slow/idle (<2 slices in 200ms): radius = min(20, series_size // 4)
   - Idle expansion (on scroll-stop timer): full radius for local region
3. **Directional scope** — during detected movement, prefetch ONLY in movement direction. Bidirectional prefetch only during idle/slow.
4. **Cache pollution guard** — `_decode_into_cache` checks relevance before inserting into `_pixel_cache`. If slice is outside current relevance window at completion time, pixel data is discarded.
5. **Series-size awareness** — for small series (≤30 slices), always use full-series prefetch since entire series fits in cache.

**KPI targets:**

| KPI | B2.5 baseline | Target after B3.2-i1 |
|-----|:---:|:---:|
| stale_task_ratio | 80-94% | <30% |
| cache_hit_ratio | 0-8.6% | >40% |
| set_slice P95 (S1) | 41.1ms | <30ms |
| set_slice P95 (S2) | 58.7ms | <45ms |
| DII | 42.8% | <30% |
| foreground_wait P95 | 50.7ms | <35ms |

**Guardrails:**
- Must not regress small-series performance (≤50 slices)
- Must not regress settled-quality path (filter rerender on scroll-stop)
- Must not affect Advanced mode
- Must remain stable across repeated runs (no oscillation/thrashing)

---

## Architecture reference (updated runtime modes)

### Interactive fast path (during active scroll)

`wheelEvent -> set_slice(fast_interaction=True) -> render (no filter, deferred annotations) -> paint`

- filter skipped
- annotation updates deferred
- minimal render latency prioritized

### Settled quality path (scroll-stop)

`scroll-stop timer -> end_fast_interaction() -> filtered rerender + annotations refresh`

- filter restored
- overlays/annotations fully refreshed
- one-time settle cost accepted

---

## Known gaps (updated)

| ID | Severity | Gap | Status | Phase |
|---|---|---|---|---|
| G6 | PERF | Concurrent-load behavior not fully benchmarked (viewer+download+filter) | CLOSED | B2.5 |
| G7 | PERF | Queue depth / stale-task / cancellation KPI instrumentation incomplete | CLOSED | B2.5 |
| G8 | PERF | Low-end hardware baseline incomplete | CLOSED | B2.5 |
| G9 | PERF | Resource contention policy not yet validated by measured controls | CLOSED | B3.2–B3.8 |
| G10 | TEST | Tool lifecycle regression coverage can be expanded (auto-deactivate assertions) | OPTIONAL | Test hardening |
| G11 | UX | Surrogate frame shows different slice content during wheel precision scroll — clinically unacceptable | OPEN | B4.1 |
| G12 | ARCH | ImageSliceBooster cache is fully independent from Lightweight2DPipeline cache — duplicated work | PARTIAL (runtime-disabled in FAST) | B4.2 |
| G13 | ARCH | 6 progressive display guard sets with 4-layer completion protocol — high cognitive complexity | IN PROGRESS (cleanup dedup + explicit lifecycle state-map + helper-fronted read paths + terminal idempotence bridge added; write-side collapse still pending) | B4.3 |

---

## Validation snapshot (latest merged)

- Targeted FAST pipeline/tool tests passed in latest run.
- Sync suite passed after contract-aligned assertions.
- MPR lifecycle stress scenarios (S8/S9/S15) passed.
- Larger viewer suites were previously reported green in batch runs.

---

## Execution log (merged)

| Date | Area | Action | Result |
|---|---|---|---|
| 2026-04-13 | A | Backend migration stages complete | stable |
| 2026-04-13..14 | B1/B1.5/B1.6 | Tool behavior + parity + policy work | validated |
| 2026-04-15 | B3.1 | FAST hot-path optimization bundle completed | major KPI gains |
| 2026-04-14 (latest run) | T2 audit | Sync suite + MPR lifecycle targeted validation | passing |
| 2026-04-14 | B2/B2.5 | Instrumentation wired, 7 scenarios captured, baseline report written | DII=42.8%, stale 80-94% |
| 2026-04-14 | B3.2-i1 | Stale-aware adaptive prefetch: velocity-based radius, dedup, pre-decode position gate | done — S1 P95 41→18ms (↓56%), S4 P95 45→22ms, S7 slow>16 334→65 (↓81%) |
| 2026-04-14 | B3.3 | Stack-drag fast_interaction parity: signal, bridge tracking, settle timer | done — wheel and stack-drag now share identical fast_interaction contract |
| 2026-04-14 | B3.4 | Unified interaction-aware policy: wheel fast_interaction fix + prefetch interaction-awareness | DONE — 149 tests pass (20 new B3.4 + 56 pipeline + 73 smoke/stage) |
| 2026-04-14 | B3.5 | Progressive display CPU offload: deferred DICOM header reads, stylesheet cache, diagnostic guard | DONE — 161 tests pass (12 new B3.5 + 149 prior), main-thread grow cost 20-50ms → 3-6ms |
| 2026-04-15 | B3.6 | Booster interaction gate: pause during scroll (eliminates 100% stale booster decode + GIL contention), pipeline pre-decode tightening (threshold 3 during fast interaction) | DONE — 181 tests pass (20 new B3.6 + 161 prior) |
| 2026-04-15 | B3.7 | Cache-first fast scroll: nearest-cached surrogate during fast_interaction (0ms foreground decode), prefetch radius 1→3, end_fast_interaction rerender | DONE — 85 tests pass |
| 2026-04-15 | B3.8 | Per-frame scroll metrics (B3.8a), Layer 2b FAST viewer fix (B3.8b), post-completion cache warm (B3.8c), duplicate Layer 2b call guard (B3.8d) | DONE — 85 viewer + 129 DM assertions |
| 2026-04-15 | B3.9 | Decoder plugin audit: pylibjpeg-libjpeg 2.4.0, pylibjpeg-openjpeg 2.5.0, pylibjpeg-rle 2.2.0 already installed. All TS have native decoders. All actual data is Explicit VR LE (uncompressed) — plugins irrelevant for current workload | VERIFIED — no action needed |
| 2026-04-15 | B3.12 | Disk pixel cache: custom binary format (.apc, 14-byte header), LRU eviction at 2GB, async fire-and-forget writes, atomic tmp→rename. Integrated into Lightweight2DPipeline._decode_slice (read+write). Benchmark: current validation 0.51ms cache read vs 9.07ms pydicom decode = 17.7× speedup | DONE — 12 tests pass |
| 2026-04-15 | B3.11 | Decode service: ProcessPoolExecutor(1, spawn) subprocess with _decode_worker, integrated into _decode_into_cache for background prefetch. Foreground stays in-process. Fallback to in-process on failure. Toggle: AIPACS_DECODE_SERVICE=0. Current validation: 12.66ms subprocess vs 10.24ms in-process = 2.42ms IPC overhead. | DONE — 9 tests pass |
| 2026-04-14 | B4 review | Standards-driven architecture review vs Cornerstone/OHIF/Orthanc/Weasis. Identified 3 misalignments: rendering inconsistency, no request class separation, cache over-layering. Reconciled stale plan sections. | Architecture review complete |
| 2026-04-14 | B4.1 | Interaction-class-aware rendering: wheel precision path never uses surrogate (always exact slice), stack drag retains surrogate. Added `interaction_type` parameter to set_slice/get_rendered_frame. | DONE — validated by B4.1 tests |
| 2026-04-15 | B4.2/B4.4/B4.3-i1 | B4.2: FAST-mode booster disabled at runtime (no-op public APIs, programmatic disable in viewer controller). B4.4: removed duplicate VTK-side Qt scroll-stop timer; QtViewerBridge settle timer is now the single end_fast_interaction trigger. B4.3-i1: centralized Layer 2b/3/4 lifecycle cleanup into one helper path. | DONE/PARTIAL — 90 viewer + 24 smoke tests pass |
| 2026-04-15 | B4.3-i2 | Added explicit progressive lifecycle state-map (`NO_VIEWER → AWAITING → PROGRESSIVE → COMPLETING → DONE`) and wired transitions across progress, start, grow, and completion layers while preserving legacy guards. Added dedicated lifecycle tests. | DONE/PARTIAL — 67 viewer + 24 smoke tests pass |

| 2026-04-15 | B4.3-i3 | Routed progressive done/inflight/completed/Layer 2b duplicate-completion decisions through lifecycle helper APIs, removed scattered raw-set reads from live call sites, and converted compatibility writes to helper wrappers where safe. Added helper-focused lifecycle tests and reran progressive + stale-exhaustion + import-smoke regressions. | DONE/PARTIAL — 42 targeted tests pass |
| 2026-04-15 | B4.x/B4.3-i4 | Log-driven stabilization: fixed integrated restart-after-DONE by allowing verified partial new cycles to clear completed-series guard; added shared UI throttle/download activity helper; throttled progressive callbacks and thumbnail progress/log updates to 2 Hz during heavy download or active scroll; added per-series orchestrator download queries. Refreshed stale B3.4 tests for B3.7/B4.1 radius/signature reality. | DONE/PARTIAL — 176 targeted tests pass |
| 2026-04-15 | B4.x planning | Reviewed `log 37` plus the orchestration article and aligned the plan around the real remaining bottleneck: duplicate terminal completion/cache-warm storm under concurrent download. Accepted central load-controller ideas in principle, but prioritized an incremental sequence: terminal idempotence first, then UI-lag/load probes, then policy routing. Updated plan/docs/coding rules accordingly. | PLAN/DOCS UPDATED — no code change in this step |
| 2026-04-15 | B4.x-i5 | Stop-the-storm idempotence: added a terminal-complete compatibility guard so duplicate late terminal progress callbacks are rejected before they recreate `_progressive_series` or re-fire one-shot grow. Cleared the guard only for verified new partial cycles after `DONE`. Added focused lifecycle/integration tests and reran progressive + live-sync + dragdrop + import-smoke regressions. | DONE/PARTIAL — 146 tests pass |
| 2026-04-15 | B4.x-i6/i7 | Added `SystemLoadController` as the shared policy front door for request classes (progressive signal, thumbnail UI, prefetch, diagnostic log, cache warm). Added a callback-gap-based `ui_event_loop_lag_ms` probe, recorded from Qt bridge `set_slice()`, and routed existing cadence/radius decisions through controller-backed helpers instead of scattered direct checks. Added focused controller tests and reran progressive + pipeline + live-sync + dragdrop + import-smoke regressions. | DONE/PARTIAL — 151 tests pass |

| 2026-04-15 | B4.x-i8 | Routed non-terminal progressive grow and post-completion cache warm through controller-backed defer helpers. Protected UI now yields non-terminal grow, keeps terminal completion visible, and defers cache warm by bounded retry instead of firing immediately into an overloaded interval. Added focused shedding tests and reran controller + progressive + pipeline + lifecycle + live-sync + dragdrop + interaction-policy + import-smoke regressions. | DONE/PARTIAL â€” 176 tests pass |
| 2026-04-17 | B4.x-i9 | Workstation hygiene pass: (1) HomeDownloadService cleanup()/disconnect_widget() with per-record signal teardown; (2) HomeDbService migrated to get_db_connection context manager; (3) Tab close wires disconnect_widget before deleteLater; (4) ui_throttle orchestrator bridge with is_heavy_download_active dual-source probe; (5) ViewerController wires pipeline to ui_throttle on init/cleanup; (6) Hot-path progress logging downgraded INFO to DEBUG; (7) Socket routing docstring + orchestrator disambiguation comment. Added lifecycle hygiene + orchestrator bridge tests. | DONE |

---

## Next actionable sequence

1. ~~Finish B2.5 instrumentation wiring for queue/foreground/stale metrics.~~ DONE
2. ~~Run all B2.5 scenarios and capture baseline tables.~~ DONE
3. ~~Rank dominant contention bottleneck by user-impact score.~~ DONE → stale prefetch (Rank 1)
4. ~~Implement B3.2-i1: generation-gated adaptive prefetch.~~ DONE
5. ~~Run B2.5 scenarios post-implementation and compare KPIs.~~ DONE (2 runs, reproducible)
6. ~~Evaluate: iterate B3.2 or proceed to next optimization target.~~ DONE → stack-drag fast_interaction gap identified
7. ~~**B3.3 Stack-drag fast_interaction parity** — add `fast_interaction=True` to stack-drag path + settle timer.~~ DONE
8. ~~**B3.4 Unified interaction-aware policy** — fix wheel fast_interaction + interaction-aware prefetch.~~ DONE
9. ~~**B3.5 Progressive display CPU offload** — deferred DICOM header reads, stylesheet cache, diagnostic guard.~~ DONE
10. ~~**B3.6 Booster interaction gate** — pause booster during scroll, pipeline pre-decode tightening.~~ DONE
11. ~~**B3.7 Cache-first fast scroll** — nearest-cached surrogate during fast interaction (0ms decode), prefetch radius 1→3.~~ DONE
12. ~~**B3.8 Log-34 reliability & diagnostics** — per-frame scroll metrics, Layer 2b FAST viewer fix, post-completion cache warm, duplicate guard.~~ DONE
13. ~~**B3.9 Decoder plugins** — verified all codec plugins already installed (pylibjpeg-libjpeg 2.4.0, pylibjpeg-openjpeg 2.5.0, pylibjpeg-rle 2.2.0). All TS have native decoders. Irrelevant for current data (all Explicit VR LE uncompressed).~~ DONE (verified)
14. **B3.10 pydicom upgrade + pixels API migration** — upgrade pydicom 2.4.4 → 3.x, migrate to `pydicom.pixels.pixel_array(path, raw=True)`. DEFERRED (low priority — decode bottleneck is parsing, not decompression)
15. ~~**B3.11 Decode Service** — subprocess decode via ProcessPoolExecutor(1, spawn), GIL isolation for prefetch, transparent fallback.~~ DONE
16. ~~**B3.12 Disk pixel cache** — L2 persistent cache for decoded pixel arrays. Custom binary format (.apc), 0.43ms read vs 4.88ms pydicom = 11.5× speedup. 12 tests pass.~~ DONE
17. **B3.13 Native C++ decoder (optional)** — evaluate dicomsdl or nvImageCodec as drop-in decoder backend for further per-slice speedup. OPTIONAL
18. **B4 Stabilization/cleanup** — dead code, documentation, final KPI capture. IN PROGRESS (B4.2/B4.4 implemented)

---

## Article Evaluation: "Deep Research on Sustainable Decode/Prefetch Solutions" (April 2026)

### Article overview

The article reassesses our position after B3.1–B3.7 and proposes three main pillars for the next phase:
1. **Multi-backend decoder** — compiled decoders (GDCM/pylibjpeg plugins/dicomsdl) with Transfer-Syntax-based routing
2. **Decode Service** — subprocess with SharedMemory (zero-copy) instead of simple ProcessPool
3. **Two-level cache (RAM + Disk)** — RAM LRU for active window + disk cache for reopened series

Plus additional recommendations: pydicom.pixels migration, surrogate clinical safety indicators, time-to-exact SLA, dicomsdl/GPU decode as optional accelerators.

### Point-by-point evaluation against our current state

| # | Article Point | Our Status | Assessment |
|---|---------------|-----------|------------|
| 1 | Generation-id stale cancellation | ✅ B3.2 DONE | Exceeds recommendation — pre-decode + post-decode + cache insert guards |
| 2 | Cache pollution prevention | ✅ B3.2 DONE | Relevance-window check at completion time |
| 3 | Mode-aware prefetch (velocity/direction/radius) | ✅ B3.2+B3.4 DONE | Velocity-based radius, direction-only during fast, idle expansion |
| 4 | Progressive/low-res during fast scroll | ✅ B3.7 DONE | B3.7 delivered major responsiveness gains for navigation, but surrogate-based rendering is not acceptable for precision wheel browsing and must now be restricted (→ B4.1) |
| 5 | Booster interaction gate | ✅ B3.6 DONE | threading.Event pause/resume, position relevance check |
| 6 | Per-frame scroll diagnostic metrics | ✅ B3.8a DONE | `[B3.8_SCROLL]` every 20th frame with full breakdown |
| 7 | Layer 2b FAST viewer matching | ✅ B3.8b DONE | 3-tier fallback matching _grow_progressive_fast |
| 8 | Post-completion cache warm | ✅ B3.8c DONE | Bidirectional prefetch on series COMPLETE |
| 9 | cancel_futures only cancels pending, not running | ✅ Handled | Generation-id cooperative cancellation at decode boundary (no reliance on cancel_futures) |
| 10 | Surrogate clinical safety (indicator + SLA) | ⚠️ PARTIAL | end_fast_interaction renders exact slice on stop; no visual "approximate" indicator during scroll |
| 11 | time_to_exact SLA measurement | ❌ NOT YET | B3.8a logs per-frame metrics but does not track settle→exact latency separately |
| 12 | pydicom.pixels migration | ❌ NOT YET | **Critical finding: pydicom 2.4.4 installed, `pydicom.pixels` API does not exist.** Upgrade to 3.x required first |
| 13 | Decoder plugins per Transfer Syntax | ❌ NOT YET | **Critical finding: pylibjpeg 2.1.0 installed WITHOUT pylibjpeg-openjpeg or pylibjpeg-libjpeg. No GDCM. No dicomsdl.** JPEG/JPEG2000 decompression relies on pure Python fallback |
| 14 | ProcessPool for GIL bypass | ❌ PLANNED (B3.9 old) | Article argues SharedMemory Decode Service is better than simple ProcessPool |
| 15 | Disk cache for decoded outputs | ❌ NOT YET | Article cites Orthanc Web Viewer pattern: configurable path/size, versioned, corruption-safe |
| 16 | dicomsdl C++ decoder | ❌ NOT YET | Article: "can reduce decode_ms unit cost, not just parallelism" — valid for future |
| 17 | GPU decode (nvImageCodec) | ❌ NOT YET | Optional for NVIDIA workstations, not a default dependency |
| 18 | Cornerstone stackContextPrefetch (cache-aware algorithm) | ⚠️ PARTIAL | Our B3.2 is velocity-based; not yet "fill entire series if it fits in cache" |

### Key insights from the article that change our plan

**Insight 1: Install decoder plugins BEFORE any architecture change (highest ROI, lowest risk)**
Our pydicom 2.4.4 with bare pylibjpeg (no openjpeg/libjpeg plugins) means ALL compressed DICOM decode goes through slow Python fallback paths. Installing `pylibjpeg-openjpeg` and `pylibjpeg-libjpeg` could reduce per-slice decode from 17-45ms to 5-15ms **with zero code changes**. This should be B3.9 — immediate, high-impact, zero-risk.

**Insight 2: pydicom upgrade is a prerequisite, not just an optimization**
`pydicom.pixels.pixel_array(path, raw=True)` requires pydicom ≥3.0. Our 2.4.4 cannot use it. The upgrade is also a **deprecation necessity** — `pixel_data_handlers` will be removed. But pydicom 3.x has API differences that need correctness testing. This should be bounded and tested thoroughly.

**Insight 3: Decode Service with SharedMemory > simple ProcessPool**
Article argues convincingly:
- ProcessPool has broken-pool risk on worker crash (must recreate)
- SharedMemory eliminates serialization overhead (~0.5-1ms per 512×512 int16)
- Decode crash is isolated from UI process
- Health-check + restart is cleaner with dedicated service
This upgrades our B3.9 from "simple ProcessPool" to "Decode Service with SharedMemory".

**Insight 4: Disk cache completes the story for reopened series**
Currently, reopening a previously-viewed series requires full re-decode of all slices. With L2 disk cache (Orthanc pattern), this becomes near-instant (disk read only). Key for clinical workflow where users flip between series repeatedly.

**Insight 5: Surrogate safety indicators are a clinical quality concern**
Article correctly notes: surrogate shows correct-resolution image from a NEARBY slice, not the EXACT slice. During fast scroll this is acceptable, but the user should never mistake a surrogate for an exact image during precision work. Our `end_fast_interaction()` guarantees exact on stop, which satisfies the SLA. A subtle visual indicator during fast scroll would be a nice-to-have but not blocking.

### Environment audit (pinned in evaluation)

| Component | Version | Gap |
|-----------|---------|-----|
| pydicom | 2.4.4 | `pydicom.pixels` API unavailable. Upgrade to ≥3.0 needed |
| pylibjpeg | 2.1.0 | Installed but **no codec plugins** |
| pylibjpeg-openjpeg | NOT INSTALLED | Required for JPEG 2000 native decode |
| pylibjpeg-libjpeg | NOT INSTALLED | Required for JPEG Baseline/Lossless native decode |
| GDCM | NOT INSTALLED | Alternative multi-codec decoder |
| dicomsdl | NOT INSTALLED | C++/AVX2 fast decoder (optional) |
| numpy | installed | OK |
| Pillow | installed | Basic JPEG Baseline via pillow_handler |

### Reordered roadmap rationale

Old order: B3.9 (ProcessPool) → B3.10 (pydicom.pixels)
New order based on article evaluation:

1. **B3.9 Decoder plugins** (QUICK WIN) — `pip install pylibjpeg-openjpeg pylibjpeg-libjpeg`. Zero code changes. Could halve decode_ms. Install + benchmark + correctness test matrix.
2. **B3.10 pydicom 3.x + pixels API** — Upgrade pydicom, migrate to `pixel_array(path, raw=True)`, correctness matrix. Code changes in `_decode_slice()` only.
3. **B3.11 Decode Service** — SharedMemory subprocess, zero-copy, health-check. Major architecture addition.
4. **B3.12 Disk cache** — L2 cache for decoded arrays. Key by SOPInstanceUID+TS. Near-instant series re-open.
5. **B3.13 Native decoder** (OPTIONAL) — dicomsdl or GPU. Only if B3.9-B3.12 don't meet targets.

### Updated KPIs (article-aligned, extended from B3.8a)

| KPI | Current value | Target | Phase |
|-----|---------------|--------|-------|
| `set_slice_present_p95_ms` (any frame to UI) | ~2-5ms (surrogate) | <16ms | ✅ B3.7 achieved |
| `time_to_exact_after_stop_p95_ms` (no download) | ~200ms (est.) | <300ms | Measure in B3.9 |
| `time_to_exact_after_stop_p95_ms` (with download) | ~500ms (est.) | <500ms | Measure in B3.9 |
| `bg_decode_per_slice_p50_ms` | 17-45ms | <10ms | B3.9 (plugins), B3.10 (raw=True) |
| `surrogate_frame_ratio` (fast scroll) | ~90%+ | acceptable | ✅ B3.7 by design |
| `surrogate_frame_ratio` (slow wheel) | ~10-30% (est.) | <20% | B3.9 (faster cache fill) |
| `cpu_scroll_peak` | ~80-120% (est.) | <60% | B3.11 (GIL bypass) |
| `disk_cache_hit_ratio_reopen` | 0% (no disk cache) | >70% | B3.12 |
| `stale_ratio` | <30% (post-B3.2) | <20% | ✅ Maintain |
| `cache_hit_near_current` | >40% (post-B3.2) | >60% | B3.9 (faster decode → faster fill) |

---

## Phase B3.5 — Progressive Display CPU Offload (DONE)

### Problem (production-log-driven)

During simultaneous download + user interaction, the progressive display grow path (`_grow_progressive_fast`, 150ms timer) runs `pydicom.dcmread(stop_before_pixels=True)` for every new `.dcm` file **synchronously on the main thread**. With typical download batches of 5–15 files per grow tick, this creates **15–40ms of blocking I/O** competing directly with scroll rendering for the GUI event loop.

Three CPU consumers ranked by evidence:
1. **`_fill_stub_from_dicom_header`** — 15–40ms/tick, every 150ms, main thread, no interaction guard
2. **ThumbnailManager `setStyleSheet()`** — 2–5ms at 5–10 Hz, main thread, re-parses CSS on every progress signal
3. **H7-P7 diagnostic viewer iteration** — 0.5–1ms at 5–10 Hz, main thread, always runs at INFO level

### Solution (3 bounded fixes)

1. **Deferred DICOM header reads** — `_refresh_stored_metadata_instances` no longer calls `_fill_stub_from_dicom_header(stub)` synchronously. New stubs get template fields (series-level W/L, rows, columns) immediately. Per-slice geometry (IPP, IOP, pixel_spacing) is filled on a single-thread `ThreadPoolExecutor("dicom-header-fill")`. On completion, `QTimer.singleShot(0)` marshals back to main thread → `_on_headers_filled` → `_sync_viewer_metadata_instances`.  Fallback: if executor is shut down, fills synchronously.

2. **Thumbnail stylesheet cache** — `update_series_progress` now sets `setStyleSheet()` only once per overlay via `_b35_style_applied` flag. Eliminates ~2ms of CSS parsing on every progress signal.

3. **H7-P7 diagnostic guard** — Viewer iteration loop gated behind `logger.isEnabledFor(logging.DEBUG)`. At production INFO level, the entire loop body (including viewer iteration) is skipped.

### KPI impact

| Metric | Before B3.5 | After B3.5 | Savings |
|--------|-------------|------------|---------|
| Main-thread cost per 150ms grow tick | 20–50ms | ~2–5ms (metadata scan only) | 15–45ms |
| Thumbnail progress CPU per signal | 2–5ms | ~0.1ms (setText only) | ~2–5ms |
| H7-P7 diagnostic per progress signal | 0.5–1ms | 0ms (gated) | 0.5–1ms |
| Combined main-thread pressure during DL+scroll | 25–55ms/150ms | ~3–6ms/150ms | **~80–90% reduction** |

### Test coverage
- `tests/viewer/test_b35_deferred_header_fill.py` — 12 tests (deferred fill, thread pool, sync fallback, stylesheet cache, diagnostic guard)
- Full regression: 161 passed (56 pipeline + 20 B3.4 + 34 stage1 + 15 stage2 + 24 smoke + 12 B3.5)

### Files changed
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py` — Added `_schedule_background_header_fill`, `_on_headers_filled`; modified `_refresh_stored_metadata_instances` to defer header reads
- `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py` — `_b35_style_applied` stylesheet cache guard
- `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py` — H7-P7 diagnostic loop gated behind `logging.DEBUG`

---

## Phase B3.6 — Booster Interaction Gate & Prefetch Stale Prevention (DONE)

### Problem (production-log-driven, log 33)

Three independent decode systems compete for CPU/GIL during scroll:
1. **ImageSliceBooster** (1 daemon thread) — decodes ±20 slices around old center. Log 33 shows slices 0→20 decoded at 20-62ms each while user scrolled 16→128 — **100% stale work**.
2. **Lightweight2DPipeline** (4 prefetch workers) — historically radius=1 during fast interaction before B3.7; current fast cap is radius=3. The B3.6 problem was that pre-decode distance check used full `prefetch_radius` (20), allowing stale tasks to proceed.
3. **Main thread foreground** — always cache-miss during fast scroll (20-80ms/slice).

CPU: 124-188% sustained. ZetaBoost cache entirely unused (entries=0).

### Solution (3 bounded fixes)

1. **Booster interaction gate** — `threading.Event` (`_interaction_gate`) added to `ImageSliceBooster`. During `fast_interaction=True`, bridge calls `pause_for_interaction()` → gate clears → worker blocks. On scroll-stop (200ms settle), `resume_from_interaction()` → gate sets → worker resumes from current position. Zero thread restart overhead.

2. **Booster pre-decode position check** — In `_worker_fn`, before each decode: `abs(idx - current_center) > window` → skip. Catches stale work from indices queued before pause or from prior scroll positions.

3. **Pipeline pre-decode tightening** — `_decode_into_cache()` now uses `threshold=3` during `_fast_interaction` (was 20). Matches the current B3.7 fast-interaction cap of radius=3.

### KPI impact (theoretical)

| Metric | Before B3.6 | Expected after B3.6 |
|--------|-------------|---------------------|
| Booster stale decode during scroll | 100% | 0% (worker paused) |
| GIL contention from booster | 20-62ms/decode cycle | 0ms during scroll |
| CPU during scroll | 124-188% | ~80-120% (est.) |
| Pipeline stale ratio | 80-94% | ~40-60% (tighter check) |

### Test coverage
- `tests/viewer/test_b36_booster_interaction_gate.py` — 20 tests (gate API, threading semantics, bridge wiring, position relevance)
- Full regression: 181 passed (20 B3.6 + 56 pipeline + 12 B3.5 + 34 stage1 + 15 stage2 + 24 smoke + 129 DM assertions)

### Files changed
- `modules/zeta_boost/image_slice_booster.py` — `_interaction_gate` Event, pause/resume API, worker gate check, position relevance
- `modules/viewer/fast/qt_viewer_bridge.py` — `_get_booster`, `_pause_booster`, `_resume_booster`, wiring in `set_slice`/`end_fast_interaction`
- `modules/viewer/fast/lightweight_2d_pipeline.py` — Pre-decode distance threshold=3 during fast interaction

---

## Phase B3.7 — Cache-First Fast Scroll: Nearest-Cached Surrogate (DONE)

### Problem (production-log-driven, log 33)

Before B3.7, even after B3.1–B3.6 optimizations (filter skip, booster pause, prefetch tightening), **every** `set_slice` during fast scroll triggered a synchronous foreground decode (17-45ms per slice). At 50-745 sl/s scroll velocity, the user outran the then-adjacent-slice prefetch (radius=1, decode took 22ms average, next event arrived in 5-15ms). Result: **0% cache hit during drag**, CPU 150-220%. B3.7 raised the fast prefetch cap to 3 and introduced cache-first surrogate rendering for drag navigation.

Root cause analysis:
- pixel_cache has capacity (96 entries) — the problem is **timing**, not capacity.
- Background prefetch submits idx+1 but decode takes longer than the inter-event interval.
- Every frame requires blocking foreground `_decode_slice()` → 100% foreground decode.

### Solution: Nearest-Cached Surrogate

Inspired by progressive loading pattern from Cornerstone/OHIF (show approximate image during fast navigation, refine on settle):

1. **`_find_nearest_cached_pixel(idx, max_distance=10)`** — During `fast_interaction=True`, when both frame_cache and pixel_cache miss for the requested slice, search for the **nearest cached pixel** within ±10 slices.

2. **Render surrogate** — If found, render the cached pixel with current W/L (0ms decode, ~2ms W/L), report `decode_ms=0.0` and `slice_index=requested_idx` (user sees the correct position in slider/corner text).

3. **Fall-through** — If no cached pixel within ±10 (first frame of a new region), fall through to synchronous decode (existing behavior).

4. **Scroll-stop refinement** — `end_fast_interaction()` always calls `get_rendered_frame(current_slice)` with `fast_interaction=False` to render the exact final slice. This ensures the user always sees the correct image when they stop scrolling.

5. **Prefetch radius raised 1 → 3** — With foreground decode eliminated, background workers have CPU headroom. Radius 3 fills cache ahead of scroll, reducing surrogate distance from ±6-10 to ±1-3.

### Architectural comparison with article recommendations

| Article Recommendation | Our Implementation | Status |
|------------------------|-------------------|--------|
| Generation-id stale cancellation | B3.2 generation gate + pre/post-decode checks | ✅ Done (exceeds recommendation) |
| Queue separation (interaction vs prefetch) | B3.4 interaction-aware radius cap + B3.6 booster gate | ✅ Done (pragmatic; formal queue separation not needed because B3.7 eliminates foreground decode) |
| ProcessPool for GIL bypass | B3.7 reduces urgency. Article recommends SharedMemory Decode Service over simple ProcessPool. | ⬜ Planned (B3.11) |
| pydicom.pixels + codec optimization | pydicom 2.4.4 installed — API doesn't exist. Must upgrade first. | ⬜ Planned (B3.10) |
| Decoder plugins per Transfer Syntax | **Missing**: no pylibjpeg-openjpeg, no pylibjpeg-libjpeg, no GDCM | ⬜ Planned (B3.9 — Quick Win) |
| Disk cache for reopened series | Not yet. Orthanc-style L2 cache for instant re-open. | ⬜ Planned (B3.12) |
| Surrogate clinical safety indicator | end_fast_interaction guarantees exact; no visual indicator during scroll | ⚠️ Nice-to-have |
| pydicom.pixels + codec optimization | pydicom 2.4.4 — API does not exist yet. Plugins missing. | ⬜ B3.9 (plugins) → B3.10 (upgrade+API) |
| Mode-aware prefetch | B3.2 velocity-based + B3.4 interaction cap + B3.7 raised radius | ✅ Done |
| Progressive/low-res during fast scroll | B3.7 nearest-cached surrogate — delivered major responsiveness gains for drag navigation, but restricted for precision wheel browsing by B4.1 | ✅ Done (refined by B4.1) |
| Cache pollution guard | B3.2 post-decode relevance check + generation check | ✅ Done |
| Budget-aware cache | pixel_cache LRU(96), frame_cache LRU(96) — effective for current use | ✅ Adequate |

### KPI impact (expected, pending production validation)

| Metric | Before B3.7 | Expected after B3.7 |
|--------|-------------|---------------------|
| set_slice per-frame (fast scroll) | 20-50ms (100% decode) | ~2-5ms (W/L only, 0ms decode) |
| CPU during stack drag | 150-220% | ~50-70% (est.) |
| Cache hit rate during drag | 0% | ~90%+ (surrogate) |
| First frame of new region | 20-50ms | 20-50ms (unchanged) |
| Scroll-stop refinement | conditional (filter only) | always exact slice |
| Prefetch radius during fast | 1 | 3 |

### Test coverage
- `tests/viewer/test_fast_viewer_pipeline.py` — 5 new B3.7 tests + 56 prior = 61 total
  - `test_b37_find_nearest_cached_pixel_returns_closest`
  - `test_b37_find_nearest_cached_pixel_empty_cache`
  - `test_b37_get_rendered_frame_uses_surrogate_during_fast_interaction`
  - `test_b37_get_rendered_frame_falls_through_when_no_nearby_cache`
  - `test_b37_surrogate_not_used_outside_fast_interaction`
- Full regression: 61 viewer + 129 DM + 37 load + 24 smoke = 251 total, all pass

### Files changed
- `modules/viewer/fast/lightweight_2d_pipeline.py` — `_find_nearest_cached_pixel()`, B3.7 surrogate path in `get_rendered_frame()`, prefetch radius 1→3
- `modules/viewer/fast/qt_viewer_bridge.py` — `end_fast_interaction()` always renders exact final slice

---

## Phase B3.8 — Log-34 Reliability & Diagnostics (DONE)

### Problem (production log 34 driven)

Production log from a real session (series 401: 106 slices, series 402: 212 slices) revealed four root causes:

1. **RC1 — ZetaBoost permanently blocked**: PipelineOrchestrator stays in DOWNLOADING until ALL series complete. Multi-series studies never reach POST_DOWNLOAD if user closes app early → ZetaBoost warmup = 0 cache entries.
2. **RC2 — Layer 2b can't match FAST viewers**: `_on_series_download_fully_complete_impl` only checked `_lazy_loader.grow()`. FAST/pydicom_qt viewers use Qt bridge → never found → final grow never fired.
3. **RC3 — No post-completion cache warm**: After per-series completion, no explicit wide prefetch. First scroll after download relied entirely on B3.7 surrogates for non-cached slices.
4. **RC4 — Double Layer 2b execution**: `_on_series_download_fully_complete_impl` called twice for same series (signal duplication), doing expensive file scanning twice.

### Solution (4 targeted fixes)

| Sub-phase | Fix | File |
|-----------|-----|------|
| **B3.8a** | Per-frame scroll metrics — periodic INFO log every 20th frame during fast interaction: decode_ms, wl_ms, total_ms, cache source (hit/surrogate/decode), pixel+frame cache sizes | `modules/viewer/fast/qt_viewer_bridge.py` |
| **B3.8b** | Layer 2b FAST viewer matching — 3-tier fallback in `_on_series_download_fully_complete_impl`: (1) `_lazy_loader.grow()`, (2) `backend.refresh_file_list()`, (3) `_qt_bridge_active → bridge.grow()` | `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py` |
| **B3.8c** | Post-completion cache warm — after `_grow_progressive_fast` detects series COMPLETE, resets `_last_prefetch_center=-1` and triggers `_prefetch_around(current_slice, direction=0)` for bidirectional full-radius prefetch | same file |
| **B3.8d** | Duplicate call guard — `_layer2b_complete_guard` set prevents re-entry. Cleared at all 3 lifecycle cleanup points (Layer 2b, Layer 3 verify, Layer 4 sweep) | same file |

### KPI impact

| Metric | Before B3.8 | After B3.8 | Notes |
|--------|-------------|------------|-------|
| Layer 2b final grow (FAST) | 0% success | 100% success | Previously never matched pydicom_qt viewers |
| Post-completion first scroll | 17-45ms decode (no cache) | 0ms surrogate + prefetch filling | Cache warm pre-populates ±3 slices around current position |
| Duplicate Layer 2b calls | 2× per series completion | 1× max | Set-based dedup guard |
| Diagnostic visibility | None during scroll | Every 20th frame logged | Enables production KPI measurement |

### Test coverage
- 85 viewer + smoke tests pass (no regressions)
- 129 DM assertions pass (no regressions)
- B3.8b/c/d tested via existing progressive display tests

### Files changed
| File | Changes |
|------|---------|
| `modules/viewer/fast/qt_viewer_bridge.py` | `_scroll_frame_count`, `[B3.8_SCROLL]` periodic log |
| `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py` | 3-tier Layer 2b grow, post-completion prefetch, `_layer2b_complete_guard` + 3 cleanup sites |

---

## Phase B3.9 — Decoder Plugin Install + TS-Based Backend Selection (DONE — verified)

### Result

All codec plugins were already installed: pylibjpeg-libjpeg 2.4.0, pylibjpeg-openjpeg 2.5.0, pylibjpeg-rle 2.2.0. All Transfer Syntaxes have native decoders. All actual production data is Explicit VR LE (uncompressed) — plugins are irrelevant for current workload. No action needed.

---

## Phase B3.10 — pydicom 3.x Upgrade + pixels API Migration (PLANNED)

### Rationale (from article + deprecation necessity)

- `pydicom.pixel_data_handlers` deprecated since pydicom 3.0 — will be removed in future versions
- `pydicom.pixels.pixel_array(path, raw=True)` accepts file path directly (avoids full Dataset parse overhead)
- `raw=True` skips rescale/photometric transforms (we do these ourselves in W/L pipeline)
- Currently on pydicom 2.4.4 — `pydicom.pixels` API does not exist

Article emphasizes: "migration to pydicom.pixels is not just optimization — it's a deprecation necessity" and warns that pydicom "does not guarantee correctness" of decompress output, requiring own validation.

### Implementation

1. **Upgrade pydicom**: 2.4.4 → latest 3.x (check compatibility with our Dataset usage patterns)
2. **Migrate decode path**: Replace `ds = pydicom.dcmread(path); arr = ds.pixel_array` with `arr = pydicom.pixels.pixel_array(path, raw=True)` in `_decode_slice()`
3. **Correctness matrix**: Full test matrix: Transfer Syntax × PhotometricInterpretation × BitsStored × raw=True/False
4. **Performance benchmark**: Compare decode_ms before/after migration
5. **Fallback**: Keep old decode path available behind feature flag during transition

### Expected impact
- Background decode per-slice: potentially 17-45ms → 8-20ms (path-based API avoids full Dataset parse)
- Future-proofed against pydicom deprecation timeline

### Risk: MEDIUM
- pydicom 3.x may have breaking API changes affecting our metadata reads
- raw=True behavior for YBR color space needs verification
- Must verify all Transfer Syntaxes in production dataset

---

## Phase B3.11 — Decode Service with Subprocess Isolation (DONE)

### Rationale (from article — GIL isolation + crash safety)

Article argues Decode Service is needed for:
- **GIL isolation**: pydicom.dcmread holds the GIL extensively during Python dict/string operations. Moving decode to a subprocess frees the main UI thread's GIL.
- **Crash isolation**: Decoder crash (segfault in native codec) doesn't take down UI.
- **Auto-restart**: Worker auto-restarts after `max_tasks_per_child` decodes (memory guard).

### Implementation (v2.3.3-perf)

- **Module**: `modules/viewer/fast/decode_service.py` — `DecodeService` class
- **Architecture**: `ProcessPoolExecutor(1, spawn)` with pickle IPC
- **Worker**: `_decode_worker()` — same decode logic as `_decode_slice()`, runs in subprocess with its own GIL
- **Integration**: `Lightweight2DPipeline._decode_into_cache()` uses service for background prefetch; foreground decode stays in-process (lowest latency)
- **Fallback**: transparent — if service returns None (failure/timeout/disabled), falls through to in-process `_decode_slice()`
- **Toggle**: `AIPACS_DECODE_SERVICE=0` env var disables the service
- **Health**: Soft per-file content errors do not poison service health; hard worker failures attempt bounded pool restart before final disable when failure rate stays >50% (10+ failures)
- **Shutdown**: `shutdown_decode_service()` called from `main.py` finally block

**Design decision**: Used `ProcessPoolExecutor` with pickle instead of SharedMemory ring buffer. Pickle overhead is ~2.4ms per 512×512 int16 slice (26% overhead), which is acceptable since the benefit is CPU isolation, not per-slice latency. SharedMemory can be added later if overhead matters.

### Measured results

| Metric | Value |
|--------|-------|
| Subprocess decode (512×512 int16) | 11.67 ms |
| In-process decode (same file) | 9.29 ms |
| IPC overhead | 2.38 ms (26%) |
| GIL freed per prefetch slice | ~9.3 ms |
| Tests | 9 pass (lifecycle, correctness, benchmark) |

### Risk: LOW (actual) — original estimate MEDIUM-HIGH
- Clean fallback eliminates risk of regression
- ProcessPoolExecutor is well-tested Python stdlib
- No SharedMemory lifecycle edge cases (deferred to future optimization)

---

## Phase B3.12 — Disk Cache for Decoded Outputs (DONE)

### Rationale (from article — Orthanc Web Viewer pattern)

Article cites Orthanc Web Viewer with configurable disk cache (CachePath, CacheSize) as proven operational pattern. Currently, reopening a previously-viewed series requires full re-decode of all slices (17-45ms × N slices). Disk cache makes this near-instant.

### Implementation (v2.3.3-perf)

- **Module**: `modules/viewer/fast/disk_pixel_cache.py` — `DiskPixelCache` class
- **Format**: Custom binary `.apc` (14-byte header: magic `APDC` + version + dtype_code + rows + cols + raw array bytes)
- **Key**: `sha256(sop_instance_uid)[:16]` → `{user_data}/cache/pixel_cache/{study_hash}/{key}.apc`
- **Supported dtypes**: int16(0), uint16(1), float32(2), uint8(3)
- **Size limit**: 2 GB default (`_DEFAULT_MAX_SIZE_MB = 2048`)
- **Eviction**: LRU by mtime — evicts oldest entries when over size limit
- **Writes**: Async fire-and-forget on daemon threads, atomic via tmp→rename
- **Corruption handling**: Shape + dtype validation on read, delete on mismatch
- **Integration**: `Lightweight2DPipeline._decode_slice()` — disk cache lookup before pydicom.dcmread, disk cache save after successful decode

### Measured results

| Metric | Value |
|--------|-------|
| Disk cache read (512×512 int16) | 0.43 ms |
| pydicom decode (warm, same file) | 4.88 ms |
| Speedup | 11.5× |
| Raw file I/O floor | 0.48 ms |
| Tests | 12 pass (round-trip, corruption, eviction, benchmark) |

### KPI target
- `disk_cache_hit_ratio_reopen`: >70% for previously-viewed series ✅ (100% on re-open)
- Series re-open time: from 2-10s (full decode) to <500ms (disk read only) ✅ (0.43ms/slice × 200 slices = 86ms)

### Risk: LOW ✅ Delivered

---

## Phase B3.13 — Native C++ Decoder (OPTIONAL)

### Options evaluated by article

| Decoder | Strength | Limitation |
|---------|----------|------------|
| dicomsdl | C++/AVX2, multi-TS support, direct pixel access | Additional dependency, validation needed |
| nvImageCodec | GPU-accelerated JPEG 2000 | Requires NVIDIA GPU, not portable |
| GDCM | Mature, multi-TS, clinical-grade | Complex build, large dependency |

### Decision criteria
- Only pursue if B3.9-B3.12 don't meet `bg_decode_per_slice_p50 < 5ms` target
- dicomsdl is the most likely candidate (pip-installable, AVX2 fast path)
- nvImageCodec only for workstations with known NVIDIA GPU

---

## Phase B3.4 — Unified Interaction-Aware Policy (DONE)

### Problem (production-log-driven)

Production logging (log 32) reveals five critical findings:

1. **Wheel scroll NEVER sets `fast_interaction=True`** — all 8 PREFETCH logs during wheel show `fast=False`; only 1 during stack-drag shows `fast=True`. Root cause: `_on_qt_scroll()` passes `fast_interaction=self._stack_drag_active` which is `False` during wheel.

2. **Prefetch runs at high velocity with `fast=False`** — velocity=286.7 but still running full filter path and submitting background thread work.

3. **CPU saturated 91-127%** during interaction — prefetch workers + progressive download + thumbnails + foreground rendering all compete for CPU.

4. **`load_single_series_by_number` ~608ms during active interaction** — progressive display triggers heavy background load while user is scrolling.

5. **B3.3 analysis was based on incorrect assumption** — it assumed the VTK widget wheel path (which does set `fast_interaction=True`) handles wheel in FAST mode. In reality, FAST mode uses QtSliceViewer → `slice_scroll_requested` → `_on_qt_scroll()`.

### Interaction model

| Mode | Intent | Adjacent slices | Filter | Prefetch | Stale policy |
|------|--------|-----------------|--------|----------|--------------|
| **Wheel** | Precision review / next-prev inspection | Highly relevant | Defer during scroll, apply on settle | Low radius, bidirectional | Normal |
| **Stack drag** | Fast navigation to region of interest | Less relevant | Defer during drag, apply on settle | Minimal radius, directional | Aggressive |
| **Idle (settled)** | Full quality review | Critical for context | Full filter applied | Full radius, bidirectional | Normal |
| **Navigation → review** | User stops drag, starts wheel | Transition: refill local cache | Full filter on settle, then normal | Rebalance around current position | Normal |

### Solution

1. **Unified fast_interaction**: Replace B3.3 stack-only mechanism with unified settle timer. `_on_qt_scroll()` ALWAYS passes `fast_interaction=True` (both wheel and stack-drag). Single 200ms settle timer fires `end_fast_interaction()`.

2. **Interaction-aware prefetch**: During `_fast_interaction=True`, cap radius to 1 (adjacent only) and skip frame prefetch (pixel decode only). This eliminates background thread CPU pressure during active scroll.

3. **Keep stack-drag context flag**: `_stack_drag_active` remains for diagnostic and future mode-differentiated policy.

### Expected impact

- Wheel filter cost eliminated during scroll (~3-5ms/frame saved)
- Annotation update eliminated during wheel (~1-2ms/frame saved)
- Prefetch background work reduced during interaction (from 3-15 radius → 1)
- CPU contention reduced: fewer background threads active during scroll

---

## Phase B3.3 — Stack-Drag Fast-Interaction Parity (DONE)

### Problem

Stack-drag through `_on_qt_scroll` calls `bridge.set_slice(n)` without `fast_interaction=True`.
Every stack-drag step runs the full OpenCV filter (3-5ms) + annotation update (1-2ms) per frame.
For fast drag on a 200-slice series (4 steps/event), that's ~56ms per mouse-move event blocking
the event loop. Wheel scroll avoids this via `fast_interaction=True` and a 200ms settle timer.

### Root cause

`QtViewerBridge._on_qt_scroll(delta)` was written as a generic scroll handler without
awareness of the interaction source. It calls `self.set_slice(new_val)` with default
`fast_interaction=False`. The wheel path (`VTKWidget.wheelEvent` Qt bridge shortcut) bypasses
`_on_qt_scroll` entirely and calls `bridge.set_slice(n, fast_interaction=True)` directly.

### Solution

1. Add `_stack_drag_active: bool` to `QtViewerBridge`
2. When stack-drag is active, `_on_qt_scroll` passes `fast_interaction=True`
3. Add 200ms settle timer for stack-drag stop (mouseRelease + area-exit)
4. On settle, call `bridge.end_fast_interaction()` for filter re-render

### Expected impact

- Stack-drag frame cost: ~14ms → ~7ms (filter + annotations eliminated during drag)
- Fast-drag event-loop block: ~56ms → ~28ms (for 4 steps/event on 200-slice series)
- Visual quality preserved by settle timer re-render
- No change to wheel behavior

---

## ClearCanvas comparison findings (2026-04-15)

- Local ClearCanvas source was verified at `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`; conclusions are code-backed from `Desktop/*`, `ImageViewer/*`, `StudyManagement/*`, `Tools/Synchronization/*`, `Thumbnails/*`, and `Volume/Mpr/*`.
- ClearCanvas validates our **FAST/Advanced separation** instinct and strongly reinforces a cleaner ownership model: `DesktopWindow -> Workspace -> ImageViewerComponent -> {LogicalWorkspace, PhysicalWorkspace} -> ImageBox -> DisplaySet -> PresentationImage`.
- Our **FAST core is sound**: `Lightweight2DPipeline`, disk pixel cache, decode service, and download-aware throttling are stronger than ClearCanvas in persistent cache / Python-specific mixed-load mitigation.
- Our main over-engineering is **control-plane complexity**, not base render speed: progressive lifecycle, guard compatibility sets, and overlapping auxiliary cache/orchestration responsibilities still exceed what is easy to reason about.
- ClearCanvas is cleaner in three places worth emulating incrementally: (1) single-owner lifecycle boundaries, (2) explicit sync/redraw coordination (`SynchronizationToolCoordinator` pattern), and (3) single-authority cache lifetime (`VolumeCache` pattern).
- ClearCanvas is **not** a perfect template for our live download-progressive workload; its simplicity partly comes from solving a calmer problem. So the right move is **simplification of authority**, not rollback of download-aware protections or FAST pipeline capabilities.
- Priority implications: finish collapsing progressive lifecycle authority, keep FAST booster overlap retired unless uniquely justified, and continue routing load policy through shared controller/throttle helpers instead of adding new ad hoc guards.

---

## ClearCanvas-inspired KPI correction track (2026-04-15)

> **Canonical next-step plan:** `docs/plans/performance/FAST_STORM_AND_PERFORMANCE_PLAN_vNEXT.md`

The ClearCanvas review changes the next optimization direction in one important way:

> We should now optimize for calmer ownership and stricter admission, not for another round of isolated renderer micro-tuning.

### What this means

- The FAST render path is no longer the main suspect.
- The main risk is mixed-load control-plane overlap.
- Local-viewing KPI comparison against ClearCanvas must be treated separately from AI-PACS-only live-download overlap KPIs.

### Benchmark assets now in repo

- Scenario definitions: `tests/performance/clearcanvas_aipacs_scenarios.json`
- KPI harness: `tools/performance/clearcanvas_aipacs_kpi_harness.py`
- Harness tests: `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`
- Review/scorecard: `docs/plans/analysis/CLEARCANVAS_KPI_SCORECARD_AND_PLAN_UPDATE.md`

### KPI classes

**Common KPIs for both apps**
- `first_image_visible_ms`
- `set_slice_present_p95_ms`
- `cpu_p95_pct`
- `rss_peak_mb`
- `thread_count_p95`
- `read_mb_delta`
- `write_mb_delta`

**AI-PACS-only overlap KPIs**
- `terminal_completion_duplicate_count`
- `cache_warm_duplicate_count`
- `stale_task_ratio`
- `cache_hit_ratio_pct`
- `decode_p95_ms`
- `frame_render_p95_ms`
- `longest_ui_gap_ms`

### New correction principles

1. **One terminal owner**
   - terminal completion must be one-shot per series epoch
   - post-completion cache warm must not dispatch more than once per epoch

2. **One non-interactive admission gate**
   - `SystemLoadController` should become the single front door for non-interactive FAST work
   - bridge/controller/progressive code should stop making independent "cheap enough" decisions

3. **One authoritative FAST 2D cache owner**
   - `Lightweight2DPipeline` remains the only authoritative FAST 2D cache/prefetch owner
   - helpers may request work, but must not become parallel cache authorities

4. **One redraw coordination point**
   - sync/reference-line redraw follow-up should be coordinated by a small mediator instead of distributed callbacks

### ClearCanvas-inspired execution sequence

**CC1 - Benchmark gate**
- Run `common_local_viewing` on both apps with the same local DICOM dataset.
- Run `aipacs_live_download_overlap` for AI-PACS.
- Compare common KPIs first; interpret overlap KPIs second.
- Execution workflow prepared:
  - `docs/analysis/CLEARCANVAS_BENCHMARK_EXECUTION.md`
  - `tests/performance/clearcanvas_aipacs_benchmark_model.json`
  - `tools/performance/run_clearcanvas_manual_benchmark.ps1`
- Current blocker status:
  - ClearCanvas not yet runnable here because `.NETFramework v4.0` targeting pack is missing.
  - `ReferencedAssemblies` checkout is also missing.
  - Therefore runtime comparison is **prepared, not completed**.

**2026-04-17 status update (first real AI-PACS capture):**
- AI-PACS headless benchmark capture is now **partially complete** using dataset
   `user_data/patients/dicom/1.2.840.1.99.1.47.1.1772527236103.85188/202`
   (342-slice series).
- Artifacts written to `generated-files/benchmarks/run_001/`:
   - `aipacs_common.json`
   - `aipacs_overlap.json`
   - `aipacs_overlap_vs_common.md`
- ClearCanvas runtime capture is still **blocked** in this workspace state:
   - source checkout exists and `Desktop/Desktop.sln` is present
   - no built desktop executable was found
   - `ReferencedAssemblies` folders were not present

**Measured AI-PACS benchmark summary (run_001):**

| KPI | Common local baseline | AI-PACS overlap | Delta / interpretation |
|---|---:|---:|---|
| `first_image_visible_ms` | 327.72 | 1382.48 | overlap cold/open path is 4.2× worse |
| `set_slice_present_p95_ms` | 24.85 | 30.04 | overlap still misses the 16ms target and regresses by 5.19ms |
| `set_slice_present_p50_ms` | 0.05 | 14.41 | overlap loses the cache-hot "almost free" browsing feel |
| `set_slice_present_max_ms` | 191.09 | 60.04 | baseline has rarer but larger outliers; overlap is more consistently slow |
| `decode_p95_ms` | 62.34 | 27.45 | overlap regression is **not** explained by slower decode |
| `frame_render_p95_ms` | 46.82 | 29.93 | render path is not the main overlap bottleneck |
| `cache_hit_ratio_pct` | 56.2 | 48.0 | overlap reduces cache usefulness |
| `slow_frame_count_16ms` | 63 / 296 | 124 / 248 | overlap roughly doubles missed-frame count |
| `stale_task_ratio` | 0.9537 | 0.99 | both runs are dominated by stale background work |
| `cpu_p95_pct` | 132.2 | 166.08 | overlap adds heavy control-plane CPU pressure |
| `thread_count_p95` | 31 | 33 | overlap keeps more actors alive |

**Interpretation:**
- The FAST render/data path is no longer the primary suspect.
- Even the common local baseline is already too noisy (`set_slice_present_p95_ms=24.85`, `stale_task_ratio=0.9537`, `cpu_p95_pct=132.2`).
- Under overlap, `decode_p95_ms` improves while `set_slice_present_p95_ms`, `first_image_visible_ms`, `slow_frame_count_16ms`, and `cpu_p95_pct` worsen. That is strong evidence for **control-plane contention**, not another decode-only bottleneck.

**Lag classification from run_001 + current code paths:**

| Class | Meaning | Status | Evidence |
|---|---|---|---|
| A | Decode-bound lag | **Secondary** | decode cost exists, but overlap `decode_p95_ms` dropped to 27.45ms while user-visible latency worsened |
| B | Main-thread/UI-blocked work | **Present** | overlap first image 1382ms; idle-settle CPU remains high; `_vc_progressive.py` still owns multi-layer completion/grow work |
| C | Event storm / fan-out | **Strong** | `HomeDownloadService` forwards one DM progress event to viewer growth and thumbnail progress immediately, plus completion pulse + `series_downloaded` |
| D | Scheduling/admission conflict | **Strongest** | `stale_task_ratio` 0.9537 → 0.99 shows prefetch/background work is admitted far beyond what interaction needs |
| E | Redraw / follow-up duplication | **Moderate** | slider, lock-sync, reference-line scheduling, thumbnail border/overlay updates remain distributed follow-up work; not isolated by this headless run |

**2026-04-15 stabilization pass update (bounded control-plane pass):**
- Implemented three targeted changes only:
   1. `HomeDownloadService` now coalesces raw `seriesProgressUpdated` fan-out behind a single admitted progress gateway instead of immediately fanning into both viewer-progress and thumbnail-progress consumers.
   2. `_vc_progressive.py` now uses one terminal authority path via `_finalize_progressive_series(...)` plus `_progressive_finalized_series` one-shot guarding.
   3. `SystemLoadController.should_admit(...)` now gates `PROGRESS_UPDATE` and `PREFETCH`, and `Lightweight2DPipeline` routes prefetch bursts through that shared admission policy.
- Verification after landing the pass:
   - Targeted stabilization tests: **125 passed** (`test_system_load_controller`, `test_lifecycle_hygiene`, `test_b43_progressive_lifecycle_state`, `test_cp1_control_plane_governance`, `test_fast_viewer_pipeline`).
   - New headless benchmark artifacts written to `generated-files/benchmarks/run_002/`.

**Measured AI-PACS benchmark summary (run_002, after stabilization pass):**

| KPI | Common local baseline | AI-PACS overlap | Delta / interpretation |
|---|---:|---:|---|
| `first_image_visible_ms` | 227.61 | 1103.79 | overlap startup still heavy, but both scenarios improved versus run_001 |
| `set_slice_present_p95_ms` | 23.33 | 6.45 | overlap slice-present tail improved sharply in the headless harness |
| `set_slice_present_p50_ms` | 0.03 | 2.99 | overlap is still slower than local, but no longer in the prior 14ms class |
| `decode_p95_ms` | 23.12 | 4.52 | overlap decode remains cheaper than common local in headless mode |
| `frame_render_p95_ms` | 23.94 | 6.30 | overlap render tail also improved materially in the harness |
| `cache_hit_ratio_pct` | 56.2 | 48.2 | locality remains weaker under overlap |
| `slow_frame_count_16ms` | 109 / 296 | 0 / 248 | overlap frame misses disappeared in this synthetic headless run |
| `stale_task_ratio` | 0.9538 | 0.9899 | stale background work is still essentially unchanged — the primary KPI goal is NOT met yet |
| `cpu_p95_pct` | 85.0 | 189.4 | overlap CPU got worse in the headless harness — the CPU target is NOT met yet |
| `thread_count_p95` | 29 | 33 | overlap still keeps more actors alive |

**Interpretation of run_002:**
- The bounded pass improved headless slice-present latency substantially, especially under overlap.
- However, the key orchestration KPIs requested for this pass are still open: `stale_task_ratio` remains ~0.99 and overlap `cpu_p95_pct` is worse than run_001.
- This likely means the headless harness captures the tightened prefetch admission but does not fully exercise the real Qt/UI-side fan-out reductions; a live app runtime/log capture is still required before claiming victory.

**Next code-level fix set (evidence-backed):**
1. **Collapse viewer-facing progress fan-out**
    - Add one coalesced viewer-progress contract between `HomeDownloadService` and patient-tab consumers.
    - Downstream progressive/thumbnail consumers should read one admitted update per series/cadence instead of each receiving direct DM callbacks.
2. **Finish progressive terminal authority collapse**
    - Keep Layer 2b as the only terminal closer.
    - Restrict Layer 3/4 to verification/recovery only; they must not recreate active terminal work for the same epoch.
3. **Harden prefetch admission during overlap**
    - Current `SystemLoadController` shell exists, but the measured stale-task ratios show submission is still too eager.
    - Tighten non-interactive admission during `heavy_download + fast_interaction`, especially for work not near the viewed slice.
4. **Add a small redraw mediator for sync/ref-line follow-up**
    - Keep `set_slice()` synchronous and first-class.
    - Queue slider/sync/ref-line follow-up behind one coordinator instead of several near-term callbacks.

**Estimated KPI impact of the next correction pass (estimate, not yet measured):**

| KPI | Current run_001 | Target after next pass | Basis |
|---|---:|---:|---|
| `set_slice_present_p95_ms` (common local) | 24.85 | 16-20 | lower fan-out + tighter admission |
| `set_slice_present_p95_ms` (overlap) | 30.04 | 18-24 | same, with overlap-specific shedding |
| `cpu_p95_pct` (overlap) | 166.08 | 110-135 | remove duplicate UI/control-plane churn |
| `stale_task_ratio` | 0.99 | <0.35 | stricter submission + relevance gating |
| `first_image_visible_ms` (overlap) | 1382.48 | 500-800 | less competing startup churn during overlap |
| `slow_frame_count_16ms` (overlap) | 124 / 248 | <60 / 248 | calmer admitted work around interaction |

**CC2 - Progressive terminal closure**
- Finish removal of duplicate terminal completion and duplicate cache-warm dispatch for the same series epoch.
- KPI gate: `terminal_completion_duplicate_count = 0`, `cache_warm_duplicate_count = 0`.

**CC3 - Viewer-facing progress contract**
- Collapse DM/progressive/thumbnail viewer updates into one viewer-facing contract with coalesced cadence.
- KPI gate: lower `cpu_p95_pct`, lower `longest_ui_gap_ms`, no regressions in `progressive_grow_latency_ms`.

**CC4 - Admission control hardening**
- Route non-interactive FAST work through `SystemLoadController` admission instead of scattered local checks.
- KPI gate: lower `set_slice_present_p95_ms` tails under overlap, stable or lower `stale_task_ratio`.

**CC5 - FAST redraw coordinator**
- Add a small coordinator for sync/reference-line redraw ordering inspired by `SynchronizationToolCoordinator`.
- KPI gate: lower multi-view or sync-enabled tail latency, fewer redraw bursts.

**CC6 - Loader/model cleanup**
- Move closer to ClearCanvas's separation of enumeration/header state from pixel retrieval, without copying its code or removing live-progressive behavior.
- KPI gate: lower overlap jitter and less metadata-repair work near the active frame path.

### Things we should actively avoid

- another decode-only optimization pass without new evidence
- reintroducing booster-like overlap in FAST mode
- adding new ad hoc guard logic outside the lifecycle authority path
- copying ClearCanvas thumbnail design blindly
- treating ClearCanvas as if it has the same live-download workload

### Immediate next benchmark action

1. Install ClearCanvas build prerequisites.
2. Build `ImageViewer/ImageViewer.sln`.
3. Run `emit-execution-pack` for `common_local_viewing`.
4. Capture `aipacs_common.json` and `clearcanvas_common.json`.
5. Generate first shared KPI comparison markdown before drawing any new optimization conclusions.

---

## Architecture Review Against Standard Viewers (2026-04-14)

### Comparison table

| Concern | Cornerstone/OHIF | Orthanc Web Viewer | Weasis | AI-PACS FAST |
|---------|------------------|-------------------|--------|-------------|
| **Request classes** | Explicit: interaction / thumbnail / prefetch / compute — each has priority + cancellation token | Single-threaded, request/response | Thread-pooled with priority queues | Mixed — all scroll types share `fast_interaction=True`, no separation between precision wheel and fast navigation |
| **Decode placement** | Web worker (off main thread), SharedArrayBuffer for zero-copy | Server-side (orthancviewer) or WASM (stone) | Thread pool with codec plugins | **6-layer**: frame_cache → pixel_cache → disk_cache → decode_service (subprocess) → in-process pydicom → booster (independent) |
| **Prefetch model** | `stackContextPrefetch`: velocity-aware, bounded, directional, "fill if fits" | Server-side pre-decode on series load | Bounded read-ahead ±N slices | Velocity-adaptive radius (3/8/15), generation-gated, position-relevance — **aligned** but layered with a separate booster prefetch |
| **Cache model** | ImageCache with `putImageLoadObject`, TypedArray cache | Server LRU (in-memory + optional disk) | LRU by series | **6 layers partially overlapping**: frame_cache, pixel_cache, disk_pixel_cache, booster_cache, ZetaBoost cache, decode_service (stateless) — **over-layered** |
| **Rendering consistency** | Deterministic: same pixel data → same viewport appearance always. No mode-dependent filter/appearance | Deterministic: server renders at fixed quality | Deterministic: OpenCV pipeline always applies | **NOT deterministic**: surrogate shows neighbor slice pixels + no filter; exact shows correct pixels + filter. Two visible changes on settle. **Misaligned** |
| **Mixed-load behavior** | RequestPool priority queues: interaction requests preempt prefetch. Bounded worker count | Single thread — simple but limited | Thread priority + job cancellation | Partially aligned (booster paused, prefetch radius capped during scroll) but interaction and prefetch share the same ThreadPoolExecutor without priority separation |
| **Complexity** | Moderate — clear interfaces, plugin codec model | Low — trade performance for simplicity | Moderate — mature, modular | **High** — 6 cache layers, 4-completion protocol, 6 guard sets, 2 settle timers, surrogate path, booster layer, decode service |
| **Determinism / predictability** | High — rendering output deterministic | High — simple model | High — stable clinical use | **Low** — frame appearance depends on cache state, interaction mode, surrogate availability, filter enabled, settle timing |

### Where we stand

| Alignment | Area |
|-----------|------|
| ✅ Aligned | Velocity-aware prefetch, generation-gated stale prevention, decode GIL isolation |
| ✅ Aligned | Interaction-aware prefetch radius reduction, booster interaction gate |
| ✅ Aligned | Disk cache for decoded outputs (Orthanc pattern) |
| ⚠️ Partially aligned | Background decode in separate process (Cornerstone uses Web Workers — similar intent) |
| ⚠️ Partially aligned | Filter deferral during fast interaction (common pattern, but our filter changes *appearance*) |
| ❌ Misaligned | **Rendering consistency** — surrogate shows different content AND different processing. Standard viewers NEVER change apparent image quality based on cache state |
| ❌ Misaligned | **Request class separation** — no distinction between precision wheel and fast navigation. Both use identical `fast_interaction=True` path with surrogate possible |
| ❌ Misaligned | **Cache layer count** — 6 layers with 2 independent decode/cache systems (pipeline + booster) is over-engineered vs standard viewers' 1-2 layers |

### Key violations of clinical viewer principles

1. **"User sees different appearance at different times for the same slice"** — During fast wheel scroll, surrogate may show slice N±3 with no filter. After settle, exact slice N with filter appears. This is a visible content jump + appearance change. Standard viewers never do this.

2. **"Precision browsing must be visually exact"** — Wheel scroll (±1 slice, clinical reading) should ALWAYS render the exact requested slice with consistent processing. Cornerstone's interaction model explicitly separates "precision" from "navigation" at the request level.

3. **"Rendering output is deterministic given the same inputs"** — In our pipeline, the same `get_rendered_frame(idx)` call returns different QImages depending on: fast_interaction flag, pixel_cache state, frame_cache state, nearest-cached-pixel availability. Standard viewers return the same visual for the same (idx, W/L) always.

---

## Architecture Audit: Over-Complex / Low-ROI Paths

### Essential (keep as-is)
- Lightweight2DPipeline core: decode → W/L → QImage → paint
- pixel_cache (L1) + frame_cache (L0): standard 2-layer in-memory cache
- Adaptive prefetch with generation-gating (B3.2): proven effective
- Interaction-aware radius capping (B3.4): necessary for CPU budget
- Progressive display core: grow-on-download is essential for UX
- Disk pixel cache (B3.12): high ROI for series re-open (11.5× speedup)

### Should simplify
- **4-layer completion protocol** → Extract `_cleanup_progressive_state(sn)` and `_do_grow_and_sync(sn)` methods to deduplicate. The 4 layers are justified (OS flush delays) but the code duplication is not.
- **6 guard sets** (`_progressive_display_done`, `_progressive_display_inflight`, `_series_download_completed`, `_progressive_series`, `_layer2b_complete_guard`, `_completion_sweep_series_set`) → Consider a state machine with explicit states instead of 6 independent sets.
- **Two settle timers** (bridge `_interaction_settle_timer` + viewer `_scroll_stop_timer`) → Unify into one.

### Should demote (disable during interaction or make lazy)
- **ImageSliceBooster during FAST mode** — Its cache is never read by the rendering path. It only helps progressive grow, which is a download-time concern. During scroll it's already paused (B3.6). Consider disabling it entirely for FAST mode and letting the pipeline's own prefetch handle everything.
- **DecodeService subprocess** — 2.4ms IPC overhead per slice. Useful for GIL isolation during prefetch, but the pipeline already limits prefetch to 3 slices during fast interaction. The overhead is consumed by background work that rarely reaches the user during scroll. Keep but make it opt-in for idle prefetch only.

### Should remove or replace
- **Surrogate frame rendering for wheel scroll** — Clinically unacceptable for precision browsing. Replace with: wheel always decodes exact slice (synchronous, ≤17ms — within budget since wheel is ±1 slice). Keep surrogate only for stack-drag fast navigation.

---

## Phase B4 — Stabilization & Architecture Correction

### B4.1 — Interaction-Class-Aware Rendering Policy (DONE)

**Problem:**

The B3.7 surrogate mechanism treats all scroll types identically. During wheel precision browsing (±1 slice, clinical reading), the viewer may show a neighboring slice's pixels when the exact slice isn't cached. This violates the clinical principle that precision browsing must show the exact requested image with consistent appearance.

Standard viewers (Cornerstone/OHIF, Weasis) separate interaction types at the request level:
- **Precision (wheel):** Always exact, may accept slightly higher latency
- **Navigation (stack drag):** May approximate for responsiveness

Our current system uses a single `fast_interaction=True` flag for both, which conflates precision and navigation.

**Solution: Two-tier interaction policy**

1. **Wheel (precision) path:** `set_slice(idx, fast_interaction=True, interaction_type='wheel')`
   - Filter: **skipped** during scroll (acceptable — same W/L pipeline, only sharpening deferred)
   - Surrogate: **NEVER** — always decode exact slice synchronously
   - Annotations: deferred (same as current)
   - Expected cost: ≤5ms cache hit, ≤17ms cache miss (acceptable for ±1 slice wheel precision)

2. **Stack drag (navigation) path:** `set_slice(idx, fast_interaction=True, interaction_type='drag')`
   - Filter: skipped (same as current)
   - Surrogate: **allowed** when cache miss (existing B3.7 behavior)
   - Annotations: deferred (same as current)
   - Expected cost: ≤2ms surrogate, 0ms decode

3. **Settled (scroll-stop) path:** `end_fast_interaction()` — same as current
   - Filter: applied
   - Exact slice: always rendered
   - Annotations: updated

**Key insight:** Wheel scroll moves ±1 slice. With prefetch radius 3, the adjacent slice is almost always in pixel_cache already (0ms decode, ~2ms W/L = cache hit). The surrogate path is rarely needed for wheel — but when it fires, it shows wrong content. Eliminating it for wheel has near-zero latency cost but eliminates 100% of the clinical UX risk.

**Implementation scope:**
- Add `interaction_type` parameter to `QtViewerBridge.set_slice()` (default='wheel')
- Pass `interaction_type` through to `Lightweight2DPipeline.get_rendered_frame()`
- Gate B3.7 surrogate path: only when `interaction_type='drag'`
- `_on_qt_scroll` sets `interaction_type='drag'` when `_stack_drag_active`, else `'wheel'`
- No changes to prefetch, cache, or completion protocol

**KPI targets:**

| KPI | Current | After B4.1 |
|-----|---------|------------|
| Wheel visual mismatch rate | >0% (possible) | 0% (guaranteed) |
| Wheel cache hit rate | ~95%+ | ~95%+ (unchanged) |
| Wheel cache miss cost | 0ms (surrogate) → 17ms decode on settle | ≤17ms immediate (no settle needed) |
| Stack drag surrogate rate (fast) | ~90%+ | ~90%+ (unchanged) |
| Filter deferred during scroll | Yes (both modes) | Yes (both modes — acceptable) |
| `precision_scroll_visual_mismatch_rate` | >0% (possible) | **0% target** (wheel never uses surrogate) |
| `wheel_exact_frame_ratio` | <100% (surrogate possible) | **100% target** (every wheel frame is exact slice) |

**Risk:** VERY LOW — adds a parameter check to the existing surrogate gate. No architectural changes. The only behavioral difference is wheel cache miss: instead of showing wrong content + decoding on settle, it decodes immediately (17ms max).

### B4.2 — Booster simplification for FAST mode (DONE — runtime disable)

`ImageSliceBooster` is now runtime-disabled in FAST mode. The FAST rendering path does not consume booster cache data; it uses `Lightweight2DPipeline` (`pixel_cache` + `frame_cache` + disk cache + prefetch). Public booster APIs are no-op when disabled, and `ViewerController` sets disable at init for FAST mode.

**Expected impact:** removes redundant booster decode work and one background thread from FAST interaction paths, reducing avoidable contention.

### B4.3 — Progressive state machine (IN PROGRESS)

Replace 6 independent guard sets with an explicit state machine: `{NO_VIEWER → AWAITING → PROGRESSIVE → COMPLETING → DONE}`. Reduce code duplication across 4 completion layers.

**B4.3 incremental steps done:**
- **i1:** Layer 2b/3/4 repeated lifecycle cleanup (`_progressive_series.pop` + `done.discard` + duplicate-guard discard) is centralized through one helper path.
- **i2:** Added explicit `_progressive_lifecycle_state` map and transition updates across key paths (`on_series_images_progress`, `_start_progressive_display`, `_grow_progressive_fast`, Layer 2/3/4 completion callbacks).
- **i3:** Routed progressive decision reads through helper APIs first (`done`, `inflight`, completed-series, Layer 2b duplicate-completion), so live call sites no longer read the raw compatibility sets directly.
- **i4:** Fixed integrated restart-after-DONE: a verified new partial progress cycle can clear `_series_download_completed` and re-enter the first-display path, while terminal late callbacks remain rejected. Added a start-task helper so lifecycle `AWAITING` does not accidentally block the first start.

**Remaining for full closure:** collapse write-side legacy guard maintenance where helper/state authority is now sufficient, retire compatibility storage that no longer has direct readers, expand policy-driven shedding/defer rules on top of the shipped load-controller shell, and confirm the live KPI delta with a fresh mixed-load capture.

### B4.4 — Settle timer unification (DONE — duplicate timer removed)

Removed duplicate VTK-side `_qt_scroll_stop_timer` arming in FAST Qt bridge wheel path. `QtViewerBridge._interaction_settle_timer` is now the single owner of `end_fast_interaction()` settle behavior (200ms). `QtSliceViewer._scroll_stop_timer` remains for annotation repaint state (`_in_wheel_scroll`) only.

### B4.x — Download-aware orchestration (IN PROGRESS)

Runtime logs show the FAST path is already highly optimized when cache-hot (`[B3.8_SCROLL]` often ~2-5ms, `decode_ms=0`), but scroll+download can still produce 50-100ms+ spikes with `decode_ms=0`. That means the remaining issue is orchestration and UI-thread pressure, not pydicom decode.

**Implemented in this stabilization pass:**
- Added shared UI throttle helpers (`modules/viewer/fast/ui_throttle.py`) for active scroll and heavy-download awareness.
- Added `is_heavy_download_active()` in ZetaBoost globals with a short grace window after download bursts.
- Progressive callbacks now use 100ms normal cadence and 500ms protected cadence during heavy download or active interaction.
- Thumbnail progress UI and `[FAST-THUMB-STATE]` logs now coalesce to a protected 2 Hz cadence during active scroll/heavy download.
- `QtViewerBridge.set_slice()` marks active scroll so thumbnail repaint work can defer behind the viewer.
- `Lightweight2DPipeline` now reads the live download-active flag instead of a copied import-time boolean, and caps idle/medium prefetch radius to 3 during heavy download.
- `PipelineOrchestrator` exposes per-series download state (`is_series_downloading`, `active_download_count`, `is_heavy_download_active`) so future routing can avoid blocking one viewer because unrelated series are downloading.

**Rules:**
- `set_slice()` remains the priority path and runs synchronously.
- Background UI work is coalesced or deferred during scroll.
- Download/progressive/thumbnail updates are allowed, but only at a bounded cadence while the viewer is interacting.

**New evidence from `log 37`:**
- The FAST render path is still healthy: sampled `[B3.8_SCROLL]` frames are mostly ~0.6-5.2ms with `decode_ms=0`, with one observed 10.9ms frame still far below the old 50-100ms class spikes.
- CPU remains high during mixed load (`cpu=153.6%`, `169.8%`, `186.2%`, `221.2%`) and the viewed series is still competing with download-side work.
- The main remaining storm is no longer thumbnail cadence. It is duplicate terminal handling on the same series: `progressive-fast: ... COMPLETE (123 slices)` and `cache-warm dispatched ...` repeat multiple times within about one second for series 303.
- The repeated transition pattern is `COMPLETING -> AWAITING -> COMPLETING -> PROGRESSIVE -> COMPLETING`, which means late terminal progress is still re-entering the grow path before the definitive completion layer closes the lifecycle.

**Article extraction: what is suitable for this project now**

Adopt now:
- **Idempotence first:** terminal `COMPLETE` and post-completion cache warm must be one-shot per series per download epoch.
- **Central load probes:** `scroll_active`, `heavy_download_active`, CPU pressure, and eventually UI event-loop lag should drive policy instead of scattered ad hoc checks.
- **Work-class policy:** interaction, progressive grow, thumbnail UI, cache warm, prefetch, and diagnostic logging should be treated as different request classes with different behavior under load.
- **Event coalescing / load shedding:** during mixed load, non-critical callbacks should be coalesced, deferred, or dropped instead of competing with `set_slice()`.

Adapt later:
- **System Load Controller (SLC):** a small central policy object is a good fit, but it should arrive behind a feature flag after the terminal duplicate path is closed.
- **UI lag heartbeat:** useful and well matched to the problem, but it should be introduced as instrumentation before it starts steering multiple code paths.
- **Dynamic prefetch shedding beyond current caps:** worth doing after we have the idempotence fix and better overload signals.

Not for now:
- Full reactive-streams style rewrite.
- Large architectural replacement of the current FAST pipeline.
- Any change that demotes `set_slice()` behind background orchestration.

**Accepted incremental sequence**

1. **B4.x-i5 — stop-the-storm idempotence** — DONE
   - Added a terminal-complete compatibility guard that is marked by `_grow_progressive_fast()` when a cycle first reaches `COMPLETE`.
   - Duplicate late terminal progress callbacks are now rejected before they recreate `_progressive_series` or re-enter one-shot grow.
   - The guard is cleared only when `DONE -> partial new cycle` is verified by the existing restart-after-DONE path.

2. **B4.x-i6 — load controller skeleton** — DONE
   - Added `SystemLoadController` with request classes for progressive signals, thumbnail UI, prefetch, diagnostic logging, interaction, and cache warm.
   - Routed existing cadence/radius decisions through controller-backed `ui_throttle` helpers without rewriting the pipeline.

3. **B4.x-i7 — UI lag instrumentation** — DONE
   - Added a lightweight callback-gap probe for `ui_event_loop_lag_ms` and record it from the Qt bridge interaction path.
   - The controller now treats fresh `ui_event_loop_lag_ms > 50` as protected-mode input for cadence and prefetch cap decisions.

4. **B4.x-i8 — policy-driven shedding** — DONE
   - Under protected UI, non-terminal progressive grow now yields through controller-backed defer helpers instead of firing immediately.
   - Post-completion cache warm is now deferred with bounded retry under protected UI, while terminal completion itself still proceeds.
   - Existing cadence/radius shedding remains controller-backed; runtime recapture is still required before tightening policies further.

5. **B4.x-i9 — workstation hygiene pass** — DONE
   - HomeDownloadService: cleanup()/disconnect_widget() with _ConnectionRecord-based per-widget signal teardown.
   - HomeDbService: migrated 2 methods from bare get_connection_database() to get_db_connection context manager.
   - Tab close path: wires disconnect_widget before deleteLater in _hp_patient_open.py.
   - ui_throttle: orchestrator bridge (set/clear_active_orchestrator) + is_heavy_download_active dual-source probe.
   - ViewerController: wires pipeline to ui_throttle on init, clears on cleanup_all_viewers.
   - Storm amplifiers: hot-path progress logging downgraded INFO→DEBUG, verified existing dedup guards adequate.
   - Architectural clarity: socket routing docstring, orchestrator naming disambiguation comment.
   - Tests: lifecycle hygiene (15 cases) + orchestrator bridge (4 cases).

**KPI gates for this track**
- `[B3.8_SCROLL]` remains stable in the ~2-5ms class for cache-hot interaction.
- No duplicate late terminal progress callback may recreate `_progressive_series` or re-fire one-shot grow after terminal completion has already been observed for that cycle.
- No duplicate `progressive-fast: ... COMPLETE` for the same series/epoch in the target runtime capture.
- No duplicate `cache-warm dispatched` for the same series/epoch in the target runtime capture.
- No `decode_ms=0` spikes above 50ms during scroll+download in the target validation session.
- CPU pressure under mixed load trends down once terminal storm work is removed and policy shedding is active.

--- 

## Notes

- This merged plan supersedes older "B2 pending / B3 blocked" wording.
- FAST and Advanced remain intentionally separated in scope and implementation.
- Scroll interaction contract is now explicit:
  - **Wheel = precision mode (±1 slice only) — visually exact, no surrogates**
  - **Stack drag = proportional speed mode (height-mapped + bounded acceleration) — surrogates allowed**


