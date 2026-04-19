# FAST Block KPI Summary

- Viewer: `AI-PACS FAST overlap`
- Source mode: `headless-aipacs-fast`
- Scenario: `aipacs_live_download_overlap` AI-PACS Live Download Overlap

## Scenario block focus

- Primary blocks: `block_1_data_services, block_2_viewer_hot_path, block_3_cache_scroll_orchestration`
- Intent: Full overlap scenario where all three blocks compete and must be scheduled by the orchestrator.

## Block 1 - Data services

- Role: Download, thumbnail/right-panel projection, DICOM/header persistence, DB/storage writes, and deferred external metadata.
- Position: Upstream producer feeding data/state into Block 2 through Block 3 scheduling.
- Coverage: 57.14%

| Metric | Value | Goal | Source | Status |
|---|---:|---|---|---|
| `CPU p95` | 139.18 | <80 primary overlap target; <50 stretch | `process_summary` | `existing` |
| `Thread count p95` | 36.0 | Stable; detect worker explosion during overlap | `process_summary` | `existing` |
| `Read MB delta` | 52.27 | Track storage/network pressure by scenario | `process_summary` | `existing` |
| `Write MB delta` | 0.03 | Track persistence churn by scenario | `process_summary` | `existing` |
| `Download preemption fail count` | _missing_ | 0 | `planned log/process metric` | `planned` |
| `Thumbnail start transitions` | _missing_ | 1 per series | `planned UI projection metric` | `planned` |
| `Thumbnail complete transitions` | _missing_ | 1 per series | `planned UI projection metric` | `planned` |

## Block 2 - Viewer hot path

- Role: Decode, filter, render, and present the FAST viewer image.
- Position: Latency-critical visible path consuming the smallest possible image-ready payload.
- Coverage: 85.71%

| Metric | Value | Goal | Source | Status |
|---|---:|---|---|---|
| `First image visible` | 196.76 | <800ms overlap target | `kpis/log_metrics` | `existing` |
| `set_slice present p95` | 155.48 | <16ms ideal; <24ms local; <30ms overlap | `kpis/log_metrics` | `existing` |
| `set_slice present max` | 385.82 | Track visible hitch spikes | `kpis/log_metrics` | `existing` |
| `Decode p95` | 208.4 | Trend downward without harming correctness | `kpis` | `existing` |
| `Frame render p95` | 187.49 | <15ms warm path target | `kpis` | `existing` |
| `Slow frame count >16ms` | 114 | Approach 0 in controlled scenarios | `kpis` | `existing` |
| `Stack-drag decode hitch count` | _missing_ | 0 preferred | `log_metrics` | `existing` |

## Block 3 - Cache, scroll, orchestration

- Role: Admission control, progressive lifecycle, cache/scroll policy, redraw ordering, and inter-block scheduling.
- Position: Control plane between Block 1 and Block 2.
- Coverage: 42.86%

| Metric | Value | Goal | Source | Status |
|---|---:|---|---|---|
| `Stale task ratio` | 0.0 | <0.50 first; <0.35 strong target | `kpis` | `existing` |
| `Cache hit ratio` | 52.6 | High enough to suppress foreground decode during interaction | `kpis` | `existing` |
| `Longest UI gap` | 0.0 | Trend toward <20ms p95 equivalent | `kpis` | `existing` |
| `Terminal completion duplicate count` | _missing_ | 0 | `log_metrics` | `existing` |
| `Cache warm duplicate count` | _missing_ | 0 | `log_metrics` | `existing` |
| `Stack-drag non-decode hitch count` | _missing_ | 0 preferred | `log_metrics` | `existing` |
| `UI event loop lag p95` | _missing_ | <20ms | `planned controller metric` | `planned` |
