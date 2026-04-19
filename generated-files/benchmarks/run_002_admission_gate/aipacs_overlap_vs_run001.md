# Viewer KPI Comparison

- Left: `AI-PACS FAST`
- Right: `AI-PACS FAST`

## Findings

- No dominant regression signal was found in the overlapping metrics.

## Shared Metrics

| Metric | Left | Right | Delta (Left-Right) |
|---|---:|---:|---:|
| `cache_hit_ratio_pct` | 48.2 | 48.0 | 0.2 |
| `cpu_max_pct` | 181.6 | 166.7 | 14.9 |
| `cpu_p50_pct` | 181.1 | 160.5 | 20.6 |
| `cpu_p95_pct` | 181.55 | 166.08 | 15.47 |
| `decode_p95_ms` | 10.04 | 27.45 | -17.41 |
| `first_image_visible_ms` | 3116.67 | 1382.48 | 1734.19 |
| `frame_render_p95_ms` | 12.94 | 29.93 | -16.99 |
| `longest_ui_gap_ms` | 0.0 | 0.0 | 0.0 |
| `read_mb_delta` | 419.56 | 451.22 | -31.66 |
| `rss_peak_mb` | 293.71 | 293.95 | -0.24 |
| `sample_count` | 3 | 3 | 0.0 |
| `set_slice_present_max_ms` | 18.1 | 60.04 | -41.94 |
| `set_slice_present_p50_ms` | 5.89 | 14.41 | -8.52 |
| `set_slice_present_p95_ms` | 12.15 | 30.04 | -17.89 |
| `slow_frame_count_16ms` | 3 | 124 | -121.0 |
| `stale_task_ratio` | 0.0 | 0.99 | -0.99 |
| `steps` | {'rapid_burst': {'cpu_p95_pct': 181.1, 'rss_peak_mb': 292.08, 'thread_count_max': 32}, 'direction_reversal': {'cpu_p95_pct': 181.6, 'rss_peak_mb': 292.1, 'thread_count_max': 32}, 'idle_settle': {'cpu_p95_pct': 153.1, 'rss_peak_mb': 293.71, 'thread_count_max': 32}} | {'rapid_burst': {'cpu_p95_pct': 166.7, 'rss_peak_mb': 292.5, 'thread_count_max': 33}, 'direction_reversal': {'cpu_p95_pct': 160.5, 'rss_peak_mb': 293.05, 'thread_count_max': 33}, 'idle_settle': {'cpu_p95_pct': 151.6, 'rss_peak_mb': 293.95, 'thread_count_max': 33}} | None |
| `thread_count_max` | 32 | 33 | -1.0 |
| `thread_count_p95` | 32.0 | 33.0 | -1.0 |
| `write_mb_delta` | 0.0 | 0.0 | 0.0 |
