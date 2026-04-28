# Unified Viewer KPI Catalog

Date: 2026-04-27

Scope: shared viewer infrastructure plus FAST and Advanced mode-specific metrics.

This file keeps its historical path for compatibility with existing tools and references, but it now covers:

- Shared Block A infrastructure used by both modes.
- FAST mode Block B/C behavior.
- Advanced mode Block B/C behavior.

Canonical runtime logs:

`C:\AI-Pacs codes\aipacs-pydicom2d\user_data\logs`

## KPI Classes

- Shared KPIs: database, server, socket/gRPC, download, disk, logs, RAM, subprocesses, and shared viewer orchestration.
- FAST KPIs: PyDicom/OpenCV/QImage/QPainter rendering, lazy slice caching, stacking, and prefetch.
- Advanced KPIs: SimpleITK/VTK loading, rendering, whole-series cache behavior, and VTK interaction.
- System KPIs: behavior under concurrent download, progressive viewing, and user interaction.

## Shared Block A KPIs

| KPI | Definition | Unit | Collection point | Target style |
|---|---|---:|---|---|
| `db_transaction_scope_p95_ms` | p95 DB stage/transaction timing | ms | diagnostic stage timing, component=db | lower |
| `db_read_transaction_p95_ms` | p95 DB timing for read-classified calls | ms | `db_diagnostics.log` stage timing | <10 |
| `db_write_transaction_p95_ms` | p95 DB timing for write-classified calls | ms | `db_diagnostics.log` stage timing | <50 |
| `db_busy_retry_count` | SQLite busy/retry events | count | DB logs | 0 during interaction |
| `main_thread_db_ms_during_fast_drag` | main-thread DB timing classified as FAST interaction | ms | `db_diagnostics.log` caller labels | 0 |
| `main_thread_db_ms_during_advanced_stack` | main-thread DB timing classified as Advanced interaction | ms | `db_diagnostics.log` caller labels | 0 |
| `server_connect_ms` | server/socket connect timing | ms | network stage timing | lower |
| `grpc_metadata_fetch_ms` | gRPC metadata fetch timing | ms | gRPC client stage timing | lower |
| `socket_batch_rtt_p95_ms` | p95 socket request timing | ms | socket request stage timing | lower |
| `download_throughput_mb_s` | DICOM transfer throughput | MB/s | download telemetry | higher, bounded by UI impact |
| `socket_lost_count` | socket disconnect/lost events | count | download logs | classify expected vs true failure |
| `priority_retry_exhausted_count` | priority-start retries exhausted | count | download intent logs | 0 for expected preemption |
| `preemption_worker_error_count` | expected preemption surfaced as worker error | count | download worker logs | 0 |
| `thumbnail_generation_ms_p95` | p95 thumbnail pipeline lifecycle duration (`start_series_download` to `complete_series_download`) | ms | thumbnail logs (`FAST:thumbnail_pipeline event=end`) | lower (interpret as end-to-end thumbnail readiness latency, not pure image-generation CPU) |
| `dicom_file_write_ms_p95` | DICOM file write p95 | ms | download storage stage timing | lower |
| `dicom_file_write_batch_count` | DICOM write batch timing samples | count | download storage stage timing | nonzero during fresh download |
| `dicom_file_write_bytes_total` | DICOM bytes written through shared download path | bytes | download storage stage timing | trend with dataset size |
| `dicom_file_read_ms_p95` | DICOM file/header read p95 | ms | viewer/storage/header telemetry | lower |
| `dicom_file_read_batch_count` | DICOM read/header batch timing samples | count | header persistence stage timing | nonzero during metadata persistence |
| `main_thread_disk_scan_ms` | main-thread path/group scan timing total | ms | viewer-data path/group stages | track and reduce |
| `main_thread_disk_scan_ms_during_fast_drag` | main-thread disk scan while FAST drag is active | ms | viewer-data stages inside drag windows | 0 |
| `main_thread_disk_scan_ms_during_advanced_stack` | main-thread disk scan while Advanced stack is active | ms | viewer-data stages inside stack windows | 0 |
| `main_thread_blocking_io_ms` | main-thread shared I/O timing total | ms | diagnostic stage timing | 0 during interaction |
| `process_rss_peak_mb` | process peak RSS | MB | process monitor | profile bounded |
| `available_ram_min_mb` | minimum available RAM | MB | resource monitor | >=1200 when possible |
| `thread_count_p95` | p95 thread count | count | process monitor | stable |
| `subprocess_count` | active subprocess count | count | resource monitor | <= profile limit |

## FAST Mode KPIs

| KPI | Definition | Unit | Collection point | Target style |
|---|---|---:|---|---|
| `fast_first_image_visible_ms` | first visible FAST image | ms | FAST first-image log | lower |
| `fast_drag_event_p95_ms` | p95 FAST drag event interval | ms | `FAST_DRAG_KPI` | <120 |
| `fast_drag_ui_lag_p95_ms` | p95 FAST drag UI lag | ms | `FAST_DRAG_KPI` | <200 |
| `fast_cached_display_p95_ms` | p95 cached QImage/QPixmap display time | ms | `FAST_SET_SLICE_STAGE` | <15 |
| `fast_foreground_decode_during_drag_count` | foreground decodes while drag is active | count | FAST scroll logs | reduce by >=50% |
| `fast_prefetch_zero_drag_ratio_pct` | drag KPI rows with zero prefetch | % | `FAST_DRAG_KPI` | <25 |
| `fast_pixel_cache_hit_ratio_pct` | FAST pixel/cache hit ratio proxy | % | scroll source counters | higher |
| `fast_frame_cache_hit_ratio_pct` | FAST frame cache hit ratio proxy | % | scroll source counters | higher |
| `stack_drag_decode_hitch_count` | drag hitches caused by decode | count | FAST scroll logs | 0 preferred |
| `stack_drag_nondecode_hitch_count` | drag hitches not caused by decode | count | FAST bridge logs | 0 preferred |
| `same_series_progressive_drag_event_p95_ms` | p95 drag event interval while viewed series is still downloading (`available < total`) | ms | session-scoped `FAST_DRAG_KPI` + progressive state logs | lower |
| `same_series_progressive_drag_ui_lag_p95_ms` | p95 drag UI lag while viewed series is still downloading | ms | session-scoped `FAST_DRAG_KPI` + progressive state logs | lower |
| `same_series_progressive_grow_apply_ms_p95` | p95 `progressive_grow_apply` while viewed series is still downloading | ms | stage timing logs | lower |
| `same_series_progressive_prefetch_zero_ratio_pct` | percent of same-series progressive drag KPI rows with `prefetch_per_s=0` | % | session-scoped `FAST_DRAG_KPI` | lower |
| `same_series_progressive_targets_per_drag_session_p50` | p50 accepted drag targets per session under same-series progressive load | count | `FAST_DRAG_KPI` | higher without UI-lag regression |

## Advanced Mode KPIs

| KPI | Definition | Unit | Collection point | Target style |
|---|---|---:|---|---|
| `advanced_first_image_visible_ms` | first visible Advanced image | ms | Advanced load/render logs | lower |
| `advanced_series_load_total_ms` | Advanced full-series load timing | ms | load stage timing | lower |
| `advanced_stack_event_p95_ms` | p95 Advanced stack event total | ms | `viewer-scroll sub-timing` | lower |
| `advanced_vtk_render_ms_p95` | p95 VTK render stage | ms | `ImageViewer2D.set_slice` sub-timing | lower |
| `advanced_simpleitk_load_ms_p95` | p95 SimpleITK load stage | ms | load stage timing | lower |
| `advanced_whole_series_cache_hit_ratio_pct` | whole-series cache hit ratio | % | Advanced cache telemetry | higher |

## Derived KPI Formulas

- `download_interference_index = ((interactive_p95_with_download - interactive_p95_viewer_only) / interactive_p95_viewer_only) * 100`
- `stale_task_ratio = stale_task_count / total_submitted_task_count`
- `canceled_task_ratio = canceled_task_count / total_submitted_task_count`
- `fast_prefetch_zero_drag_ratio_pct = zero_prefetch_drag_rows / fast_drag_kpi_rows * 100`
- `same_series_progressive_prefetch_zero_ratio_pct = zero_prefetch_rows_same_series_progressive / drag_rows_same_series_progressive * 100`
- `preemption_false_error_count = preemption_worker_error_count + priority_retry_exhausted_count for expected-preemption windows`

## Phase Gate Requirements

Every optimization step must include:

1. Baseline row.
2. Candidate row.
3. Delta column.
4. Viewer mode: `FAST_QT`, `FAST_LAZY_VTK`, `Advanced`, or `Shared`.
5. Interpretation note.
6. Decision: `go`, `revise`, or `rollback`.

## Gate P1: Baseline Complete

Required shared metrics:

- `db_transaction_scope_p95_ms`
- `db_read_transaction_p95_ms`
- `db_write_transaction_p95_ms`
- `main_thread_db_ms_during_fast_drag`
- `main_thread_db_ms_during_advanced_stack`
- `socket_lost_count`
- `priority_retry_exhausted_count`
- `preemption_worker_error_count`
- `thumbnail_generation_ms_p95`
- `main_thread_blocking_io_ms`
- `thread_count_p95`
- `process_rss_peak_mb`

Required FAST metrics:

- `fast_first_image_visible_ms`
- `fast_drag_event_p95_ms`
- `fast_drag_ui_lag_p95_ms`
- `fast_cached_display_p95_ms`
- `fast_prefetch_zero_drag_ratio_pct`
- `fast_foreground_decode_during_drag_count`
- `same_series_progressive_drag_event_p95_ms`
- `same_series_progressive_drag_ui_lag_p95_ms`
- `same_series_progressive_grow_apply_ms_p95`

Required Advanced metrics:

- `advanced_stack_event_p95_ms`
- `advanced_vtk_render_ms_p95`
- `advanced_series_load_total_ms`

## Notes

- KPI thresholds should be profile-aware for low, mid, and high hardware.
- Do not accept faster background throughput if hard-interactive KPIs regress.
- Shared-service changes must be measured for both FAST and Advanced.
- Rendering and filter metrics must stay mode-specific.

## Overlap pixel-quality gate (F1.3, 2026-04-28)

Any performance work targeting the "downloading same series + stacking same series" overlap scenario must not regress image quality. The gate is enforced by a deterministic pixel-hash regression bundle that runs offscreen Qt + synthetic DICOM (no UI required, ~12 s).

**Run the bundle locally before commit:**

```powershell
.\tools\dev\run_overlap_regression.ps1
```

**Tests in the bundle (25 total):**

| Path | Purpose |
|------|---------|
| [tests/viewer/test_overlap_pixel_quality.py](tests/viewer/test_overlap_pixel_quality.py) | F1.1 — settled rendering byte-equal to golden across 4 cases (filter on/off × MONOCHROME1/2). |
| [tests/viewer/test_overlap_pixel_quality_drag.py](tests/viewer/test_overlap_pixel_quality_drag.py) | F1.2 — drag-mode validity (every served frame is the rendering of *some* slice), surrogate proximity (≤±10), settle exactness on release. |
| [tests/performance/test_overlap_kpi_parser.py](tests/performance/test_overlap_kpi_parser.py) | F0.2 — `parse_overlap_log_text` shape, malformed-line tolerance, file round-trip. |
| [tests/performance/test_clearcanvas_aipacs_kpi_harness.py](tests/performance/test_clearcanvas_aipacs_kpi_harness.py) | KPI harness regression (existing). |

**Gate scope (must run before merging changes to):**

- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/qt_viewer_bridge.py`
- `modules/viewer/fast/qt_slice_viewer.py`
- Their plugin-package mirrors under `builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/`

**Re-capturing goldens:** only with `.\tools\dev\run_overlap_regression.ps1 -Capture` AND a deliberate human review of the JSON diff under `tests/viewer/golden/`. A hash change is by definition a user-visible image change.

**Red-team verification:** to confirm the gate detects breakage, temporarily change the FAST W/L LUT or filter dimensions and re-run — settled hashes must drift. Revert and re-run — bundle must return green.

**Plan reference:** `plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md` Phase F1.
