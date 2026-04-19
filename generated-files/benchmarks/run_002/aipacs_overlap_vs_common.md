# Viewer KPI Comparison

- Left: `AI-PACS FAST`
- Right: `AI-PACS FAST`

## Findings

- AI-PACS FAST consumes materially more CPU under the same scripted steps, which points to control-plane overhead rather than pure rendering.

## Shared Metrics

| Metric | Left | Right | Delta (Left-Right) |
|---|---:|---:|---:|
| `cache_hit_ratio_pct` | 48.2 | 56.2 | -8.0 |
| `cpu_max_pct` | 192.7 | 100.7 | 92.0 |
| `cpu_p50_pct` | 159.7 | 18.1 | 141.6 |
| `cpu_p95_pct` | 189.4 | 85.0 | 104.4 |
| `decode_p95_ms` | 4.52 | 23.12 | -18.6 |
| `first_image_visible_ms` | 1103.79 | 227.61 | 876.18 |
| `frame_render_p95_ms` | 6.3 | 23.94 | -17.64 |
| `longest_ui_gap_ms` | 0.0 | 0.0 | 0.0 |
| `read_mb_delta` | 605.0 | 29.67 | 575.33 |
| `rss_peak_mb` | 293.36 | 291.55 | 1.81 |
| `sample_count` | 3 | 5 | -2.0 |
| `set_slice_present_max_ms` | 8.98 | 28.69 | -19.71 |
| `set_slice_present_p50_ms` | 2.99 | 0.03 | 2.96 |
| `set_slice_present_p95_ms` | 6.45 | 23.33 | -16.88 |
| `slow_frame_count_16ms` | 0 | 109 | -109.0 |
| `stale_task_ratio` | 0.9899 | 0.9538 | 0.04 |
| `steps` | {'rapid_burst': {'cpu_p95_pct': 192.7, 'rss_peak_mb': 290.91, 'thread_count_max': 33}, 'direction_reversal': {'cpu_p95_pct': 119.9, 'rss_peak_mb': 291.43, 'thread_count_max': 33}, 'idle_settle': {'cpu_p95_pct': 159.7, 'rss_peak_mb': 293.36, 'thread_count_max': 33}} | {'steady_forward': {'cpu_p95_pct': 22.2, 'rss_peak_mb': 276.95, 'thread_count_max': 29}, 'rapid_burst': {'cpu_p95_pct': 10.2, 'rss_peak_mb': 289.28, 'thread_count_max': 29}, 'direction_reversal': {'cpu_p95_pct': 18.1, 'rss_peak_mb': 289.3, 'thread_count_max': 29}, 'idle_settle': {'cpu_p95_pct': 0.0, 'rss_peak_mb': 291.55, 'thread_count_max': 29}, 'reopen_same_series': {'cpu_p95_pct': 100.7, 'rss_peak_mb': 221.38, 'thread_count_max': 26}} | None |
| `thread_count_max` | 33 | 29 | 4.0 |
| `thread_count_p95` | 33.0 | 29.0 | 4.0 |
| `write_mb_delta` | 0.0 | 0.0 | 0.0 |
