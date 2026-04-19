# Viewer KPI Comparison

- Left: `AI-PACS FAST`
- Right: `AI-PACS FAST`

## Findings

- AI-PACS FAST consumes materially more CPU under the same scripted steps, which points to control-plane overhead rather than pure rendering.
- AI-PACS FAST still misses the 16ms interactive frame budget in the compared run.

## Shared Metrics

| Metric | Left | Right | Delta (Left-Right) |
|---|---:|---:|---:|
| `cache_hit_ratio_pct` | 48.0 | 56.2 | -8.2 |
| `cpu_max_pct` | 166.7 | 140.5 | 26.2 |
| `cpu_p50_pct` | 160.5 | 92.4 | 68.1 |
| `cpu_p95_pct` | 166.08 | 132.2 | 33.88 |
| `decode_p95_ms` | 27.45 | 62.34 | -34.89 |
| `first_image_visible_ms` | 1382.48 | 327.72 | 1054.76 |
| `frame_render_p95_ms` | 29.93 | 46.82 | -16.89 |
| `longest_ui_gap_ms` | 0.0 | 0.0 | 0.0 |
| `read_mb_delta` | 451.22 | 28.8 | 422.42 |
| `rss_peak_mb` | 293.95 | 296.11 | -2.16 |
| `sample_count` | 3 | 5 | -2.0 |
| `set_slice_present_max_ms` | 60.04 | 191.09 | -131.05 |
| `set_slice_present_p50_ms` | 14.41 | 0.05 | 14.36 |
| `set_slice_present_p95_ms` | 30.04 | 24.85 | 5.19 |
| `slow_frame_count_16ms` | 124 | 63 | 61.0 |
| `stale_task_ratio` | 0.99 | 0.9537 | 0.04 |
| `steps` | {'rapid_burst': {'cpu_p95_pct': 166.7, 'rss_peak_mb': 292.5, 'thread_count_max': 33}, 'direction_reversal': {'cpu_p95_pct': 160.5, 'rss_peak_mb': 293.05, 'thread_count_max': 33}, 'idle_settle': {'cpu_p95_pct': 151.6, 'rss_peak_mb': 293.95, 'thread_count_max': 33}} | {'steady_forward': {'cpu_p95_pct': 99.0, 'rss_peak_mb': 281.27, 'thread_count_max': 31}, 'rapid_burst': {'cpu_p95_pct': 86.3, 'rss_peak_mb': 295.09, 'thread_count_max': 31}, 'direction_reversal': {'cpu_p95_pct': 140.5, 'rss_peak_mb': 296.11, 'thread_count_max': 31}, 'idle_settle': {'cpu_p95_pct': 1.2, 'rss_peak_mb': 295.84, 'thread_count_max': 30}, 'reopen_same_series': {'cpu_p95_pct': 92.4, 'rss_peak_mb': 220.77, 'thread_count_max': 28}} | None |
| `thread_count_max` | 33 | 31 | 2.0 |
| `thread_count_p95` | 33.0 | 31.0 | 2.0 |
| `write_mb_delta` | 0.0 | 25.0 | -25.0 |
