# Viewer KPI Comparison

- Left: `AI-PACS FAST`
- Right: `AI-PACS FAST`

## Findings

- AI-PACS FAST consumes materially more CPU under the same scripted steps, which points to control-plane overhead rather than pure rendering.

## Shared Metrics

| Metric | Left | Right | Delta (Left-Right) |
|---|---:|---:|---:|
| `cache_hit_ratio_pct` | 48.2 | 56.1 | -7.9 |
| `cpu_max_pct` | 181.6 | 99.5 | 82.1 |
| `cpu_p50_pct` | 181.1 | 70.3 | 110.8 |
| `cpu_p95_pct` | 181.55 | 97.94 | 83.61 |
| `decode_p95_ms` | 10.04 | 6.6 | 3.44 |
| `first_image_visible_ms` | 3116.67 | 819.47 | 2297.2 |
| `frame_render_p95_ms` | 12.94 | 11.89 | 1.05 |
| `longest_ui_gap_ms` | 0.0 | 0.0 | 0.0 |
| `read_mb_delta` | 419.56 | 30.17 | 389.39 |
| `rss_peak_mb` | 293.71 | 291.45 | 2.26 |
| `sample_count` | 3 | 5 | -2.0 |
| `set_slice_present_max_ms` | 18.1 | 46.59 | -28.49 |
| `set_slice_present_p50_ms` | 5.89 | 0.04 | 5.85 |
| `set_slice_present_p95_ms` | 12.15 | 11.36 | 0.79 |
| `slow_frame_count_16ms` | 3 | 4 | -1.0 |
| `stale_task_ratio` | 0.0 | 0.0 | 0.0 |
| `steps` | {'rapid_burst': {'cpu_p95_pct': 181.1, 'rss_peak_mb': 292.08, 'thread_count_max': 32}, 'direction_reversal': {'cpu_p95_pct': 181.6, 'rss_peak_mb': 292.1, 'thread_count_max': 32}, 'idle_settle': {'cpu_p95_pct': 153.1, 'rss_peak_mb': 293.71, 'thread_count_max': 32}} | {'steady_forward': {'cpu_p95_pct': 99.5, 'rss_peak_mb': 277.07, 'thread_count_max': 29}, 'rapid_burst': {'cpu_p95_pct': 70.3, 'rss_peak_mb': 289.13, 'thread_count_max': 29}, 'direction_reversal': {'cpu_p95_pct': 53.8, 'rss_peak_mb': 289.14, 'thread_count_max': 29}, 'idle_settle': {'cpu_p95_pct': 0.6, 'rss_peak_mb': 291.45, 'thread_count_max': 29}, 'reopen_same_series': {'cpu_p95_pct': 91.7, 'rss_peak_mb': 220.74, 'thread_count_max': 27}} | None |
| `thread_count_max` | 32 | 29 | 3.0 |
| `thread_count_p95` | 32.0 | 29.0 | 3.0 |
| `write_mb_delta` | 0.0 | 0.0 | 0.0 |
