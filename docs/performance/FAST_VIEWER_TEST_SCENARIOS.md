# FAST Viewer Performance Test Scenarios

**Date:** 2026-04-14  
**Purpose:** Standardized scenario set for KPI-driven performance iterations.

## 1) Scenario execution rules

- Run each scenario on the same build and logging configuration.
- Capture both component and system KPIs from `FAST_VIEWER_KPI_CATALOG.md`.
- Keep FAST mode isolated; do not mix Advanced mode behavior into measurements.
- Prefer repeatable scripted interactions where possible; otherwise use explicit manual protocol.

## 2) Scenario matrix

| ID | Scenario | Purpose | Setup | KPI focus | Pass/Fail signals |
|---|---|---|---|---|---|
| S1 | Viewer-only baseline | Establish clean baseline without download contention | Open large CT (200+), scroll steady + rapid | `set_slice_p50/p95`, `paint_p95`, `slow_frame_count`, `cache_hit_ratio` | Pass: baseline captured with no missing KPI fields |
| S2 | Viewer + progressive download | Measure overlap penalty and contention | Start download, open target series while download active | `download_interference_index`, `foreground_task_wait_ms`, `decode_queue_depth` | Pass: overlap KPI captured and reproducible trend |
| S3 | Viewer + progressive download + filter settle | Stress post-scroll recovery under overlap | same as S2 + force filter reapply after bursts | `recovery_after_scroll_ms`, `filter_apply_ms`, `scroll_jank_count` | Fail if recovery grows unbounded or jank spikes |
| S4 | Rapid scroll burst | Test hard-interactive stability under high input rate | 5-10s wheel burst over dense stack | `slow_frame_count`, `scroll_jank_count`, `set_slice_p95` | Fail if p95 tail explodes or visible freeze occurs |
| S5 | Rapid direction reversal | Expose stale work and cancellation weakness | alternate direction every 0.5-1s | `stale_task_ratio`, `canceled_task_ratio`, queue depths | Pass: stale ratio controlled, no queue runaway |
| S6 | Low-end profile simulation | Ensure survivability on constrained hardware | run with low profile knobs / lower worker limits and overlap load | hard-interactive KPIs + starvation metrics | Fail on starvation incidents or prolonged UI wait |
| S7 | Repeated open/close cycles | Detect leaks and lifecycle instability | repeat open/close 20-50 cycles | `rss_growth_mb`, recovery KPIs, error counts | Fail if monotonic RSS growth or degraded latency trend |
| S8 | Sync/reference under load | Validate lock-sync/refline impact during overlap | multi-view sync enabled + active download | `sync_update_ms`, `paint_p95`, `foreground_task_wait_ms` | Fail if sync updates cause hard jank |
| S9 | Cache warm vs cold | Quantify cache dependency and prefetch behavior | run S1 twice: cold then warm | `first_image_visible_ms`, decode KPIs, cache hit ratio | Pass: clear warm/cold distinction documented |
| S10 | Large CT stress (200+ slices) | Confirm high-volume behavior | 200+ slice stack with long scroll paths | tail latencies, queue depth, stale ratio | Fail if queue growth persists after user input stops |

## 3) Capture protocol per scenario

1. Record environment profile (CPU cores, RAM tier, GPU mode, FAST backend).
2. Start KPI capture.
3. Execute scenario script/manual protocol.
4. Stop capture and export KPI table.
5. Annotate anomalies (errors, stalls, visible artifacts).

## 4) Step-level test integration expectations

For each future optimization step:
- update or add at least one targeted automated test/helper for the affected bottleneck
- run the minimum scenario subset that can validate the change
- update KPI comparison table with before/after
- write a short interpretation note and decision

## 5) Suggested file evolution path

- Keep benchmark/runner helpers under `tests/performance/`.
- Add scenario-specific helpers (event generators, KPI parsers) as reusable modules.
- Preserve deterministic seeds and replay data where possible.
- Store sample output schemas in doc comments to avoid parser drift.

## 6) Manual review hooks

- Human confirms perceived smoothness in S2/S4/S8.
- Human confirms no visual correctness regressions while under load.
- Human confirms low-end profile remains usable.
