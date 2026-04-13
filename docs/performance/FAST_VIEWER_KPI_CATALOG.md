# FAST Viewer KPI Catalog

**Date:** 2026-04-14  
**Scope:** FAST mode (`pydicom_qt`) only.  
**Use:** Single source of KPI definitions for baseline and iteration deltas.

## 1) KPI classes

- **Component KPIs**: measure one subsystem in isolation or near-isolation.
- **System KPIs**: measure behavior under concurrent overlap and contention.

## 2) Component KPI Catalog

| KPI | Definition | Unit | Collection point | Why it matters | Target style |
|---|---|---:|---|---|---|
| `first_image_visible_ms` | Time from series-switch request to first visible image | ms | viewer controller / bridge log marker | initial responsiveness | lower is better |
| `set_slice_latency_p50_ms` | median `set_slice` duration in scenario window | ms | bridge timing | core scroll smoothness | lower |
| `set_slice_latency_p95_ms` | p95 `set_slice` duration | ms | bridge timing | tail latency/jank risk | lower |
| `decode_latency_p50_ms` | median per-slice decode time | ms | decode path probe | decode efficiency | lower |
| `decode_latency_p95_ms` | p95 decode latency | ms | decode path probe | hotspot pressure | lower |
| `frame_ready_latency_ms` | decode-to-frame-ready latency | ms | pipeline stage timing | end-to-end frame preparation | lower |
| `qimage_convert_ms` | numpy/frame → QImage conversion time | ms | pipeline conversion marker | UI image transfer cost | lower |
| `paint_time_p95_ms` | p95 paint event cost | ms | viewer paint timing | redraw pressure | lower |
| `cache_hit_ratio` | hits / (hits + misses) over scenario | ratio (%) | pipeline counters | miss-induced latency control | higher |
| `slow_frame_count` | frame count above threshold (16ms default) | count | scenario runner parser | jank indicator | lower |
| `scroll_jank_count` | number of scroll intervals above jank threshold | count | scenario harness | user-perceived stutter | lower |
| `filter_apply_ms` | filter apply cost in refine path | ms | filter timing | post-scroll settle cost | lower |
| `sync_update_ms` | lock-sync/refline update cost per event | ms | sync markers | multi-view interaction cost | lower |
| `overlay_paint_ms` | overlay/tool paint time per frame | ms | paint-layer instrumentation | tool/overlay impact | lower |
| `progressive_grow_latency_ms` | grow signal to displayed slice extension | ms | progressive path markers | download-viewing responsiveness | lower |

## 3) System / Contention KPI Catalog

| KPI | Definition | Unit | Collection point | Why it matters | Target style |
|---|---|---:|---|---|---|
| `foreground_task_wait_ms` | wait time before hard-interactive task starts | ms | scheduler/load-signal marker | direct UI responsiveness | lower |
| `decode_queue_depth` | pending decode jobs over time (max/p95) | count | decode queue probe | decode contention pressure | lower |
| `frame_queue_depth` | pending frame jobs over time (max/p95) | count | frame queue probe | render pipeline pressure | lower |
| `stale_task_ratio` | stale tasks / submitted tasks | ratio (%) | task lifecycle counters | wasted work and lag propagation | lower |
| `canceled_task_ratio` | canceled tasks / submitted tasks | ratio (%) | cancellation counters | cancellation efficiency + churn | bounded optimum |
| `download_interference_index` | delta in hard-interactive latency with vs without download | % | scenario comparison | overlap penalty | lower |
| `cpu_scroll_only_pct` | CPU usage during viewer-only scenario | % | process monitor | baseline CPU pressure | profile baseline |
| `cpu_scroll_plus_download_pct` | CPU usage with download overlap | % | process monitor | overlap pressure | bounded |
| `cpu_scroll_plus_download_plus_filter_pct` | CPU usage with full overlap | % | process monitor | worst-case pressure | bounded |
| `rss_growth_mb` | RSS delta across scenario | MB | process monitor | memory stability | lower |
| `recovery_after_scroll_ms` | time from scroll-stop to stable refined state | ms | scroll-stop + settle marker | post-interaction quality recovery | lower |
| `recovery_after_download_burst_ms` | time to recover after burst progress events | ms | download/progressive markers | robustness under bursty I/O | lower |
| `starvation_incidents` | count of deferred class tasks exceeding starvation budget | count | scheduler audit log | fairness guardrail | near-zero |
| `queue_drop_count` | dropped/expired tasks due to queue pressure policy | count | queue manager | backpressure behavior | controlled |

## 4) Derived KPI formulas

- `download_interference_index = ((set_slice_p95_with_download - set_slice_p95_viewer_only) / set_slice_p95_viewer_only) * 100`
- `stale_task_ratio = stale_task_count / total_submitted_task_count`
- `canceled_task_ratio = canceled_task_count / total_submitted_task_count`

## 5) KPI capture requirements per optimization step

Every step must include:
1. Baseline row (pre-change)
2. Candidate row (post-change)
3. Delta column
4. Interpretation note
5. Go/Revise/Stop decision

## 6) Minimum KPI set for phase gates

### Gate P1 (baseline complete)
- `first_image_visible_ms`
- `set_slice_latency_p50_ms`
- `set_slice_latency_p95_ms`
- `paint_time_p95_ms`
- `cache_hit_ratio`
- `slow_frame_count`
- `download_interference_index`
- `decode_queue_depth`
- `stale_task_ratio`
- `rss_growth_mb`

### Gate P2+ (each optimization iteration)
- Must include the KPI most directly tied to that bottleneck + all hard-interactive guardrail KPIs.

## 7) Notes

- KPI thresholds should be profile-aware (low/mid/high hardware) rather than one universal absolute number.
- Do not accept “faster background throughput” if hard-interactive KPIs regress.
