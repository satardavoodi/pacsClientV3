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

## Overlap log tag `[OVERLAP_SCENARIO]` (F2.1, 2026-04-28; F2.1b extension 2026-04-29)

To make the "download same series + stack same series" KPIs observable from a normal production run without enabling DEBUG, `Lightweight2DPipeline.get_rendered_frame()` emits a structured INFO line at all three return paths (cached frame / surrogate / synchronous decode) when both:

- `is_heavy_download_active()` returns `True`, AND
- `is_viewed_series_complete(self._series_number)` returns `False`.

Sampled 1-in-N (default 5) via env var `AIPACS_OVERLAP_LOG_SAMPLE`. Sampling protects log volume; default ≈ 20 % of overlap frames produce a tag.

**F2.1b sentinel-emit bypass (2026-04-29).** Live-run capture on 2026-04-28 23:01 produced exactly 2 overlap samples — both surrogate, zero decode — over a real drag burst, while the same drag's `[FAST_DRAG_KPI]` summary reported `event_p95=607.9 ms` / `ui_lag_max=363.9 ms`. The 1-in-N sampler is too sparse to capture decode-cache misses (the only path > 1 ms). `_maybe_emit_overlap_tag` now bypasses the sampler when:

- `cache=decode` — every foreground decode emits unconditionally (still gated by min-gap, see below).
- `_overlap_force_emit_next` is set — armed at drag-begin (`set_fast_interaction(False → True)`) and drag-end (`set_fast_interaction(True → False)`) so each drag burst contributes ≥1 sample even on cache-warm rides.

A 50 ms min-gap (`_OVERLAP_FORCE_EMIT_MIN_GAP_MS`) prevents log storm if many decode misses fire back-to-back. Sampled (non-forced) emits are unaffected by the gap.

**Format (verbatim, must remain stable for the harness regex):**

```
[OVERLAP_SCENARIO] frame idx=<int> cache=<hit|surrogate|decode> decode_ms=<float> wl_ms=<float> total_ms=<float> settled=<True|False> sentinel=<reason>
```

The trailing `sentinel=<reason>` field was added in F2.1b. `<reason>` is one of `decode`, `drag_begin`, `drag_end`, or `-` (for sampled / non-boundary frames). Old logs without this field are still accepted by the parser regex (the field is optional). `settled=True` means the user is NOT in fast-interaction (drag/wheel) at emission time — i.e. either the overlap-coalesce settle frame after release, or a non-interactive call.

**Parsed by:** [tools/performance/clearcanvas_aipacs_kpi_harness.py](tools/performance/clearcanvas_aipacs_kpi_harness.py) → `parse_overlap_log_text` / `parse_overlap_log_file`. CLI:

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py parse-overlap-log --log <path-to-viewer_diagnostics.log>
```

**F2.4b — `[FAST_DRAG_KPI]` aggregation (2026-04-29).** The same parser also ingests end-of-burst summaries emitted by `qt_viewer_bridge._log_drag_metrics_summary`. These are 100% sampled (one per drag) and carry the real-world Qt event-loop / UI-lag KPIs the per-frame `[OVERLAP_SCENARIO]` tag cannot measure. New keys in the parser payload:

| Key | Meaning |
|---|---|
| `overlap_drag_burst_count` | Number of `[FAST_DRAG_KPI]` lines parsed. |
| `overlap_drag_event_p95_max_ms` | Max `event_p95_ms` across bursts. **Tier-2 north star.** |
| `overlap_drag_event_p95_p95_ms` | p95 of the per-burst `event_p95_ms` list. |
| `overlap_drag_handler_p95_max_ms` | Max `handler_p95_ms` across bursts. |
| `overlap_drag_ui_lag_max_max_ms` | Max `ui_lag_max_ms` across bursts. **Tier-2 north star.** |
| `overlap_drag_ui_lag_max_p95_ms` | p95 of per-burst `ui_lag_max_ms`. |
| `overlap_drag_prefetch_per_s_avg` | Mean `prefetch_per_s` across bursts. |
| `overlap_drag_background_decode_count_total` | Sum of `background_decode_count`. R3 invariant: must stay 0. |

And new sentinel-visibility keys (F2.1b):

| Key | Meaning |
|---|---|
| `overlap_sentinel_emit_count` | Total forced (non-`-`) sentinel emits. |
| `overlap_sentinel_breakdown.decode` | Forced emits at decode-cache miss. |
| `overlap_sentinel_breakdown.drag_begin` | Forced emits at `set_fast_interaction(True)`. |
| `overlap_sentinel_breakdown.drag_end` | Forced emits at `set_fast_interaction(False)`. |
| `overlap_sentinel_breakdown.other` | Catch-all for future reasons. |

**Contract tests:** `tests/performance/test_overlap_kpi_parser.py` — 25 tests total. Production-format round-trip is now covered by both `test_parse_overlap_log_text_matches_production_emit_format` (legacy emit) and `test_parse_overlap_log_text_matches_production_emit_format_with_sentinel` (current emit with `sentinel=` field). If you change the emit format string in `Lightweight2DPipeline._maybe_emit_overlap_tag`, both contract tests must be reconciled.

**Plan reference:** `plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md` Phase F2.1 / F2.1b / F2.4 / F2.4b.

### Retargeted KPI tier (post-2026-04-29 live run)

The overlap analysis tracks two layers:

**Tier-1 — synthetic, harsh-preset anchor (`overlap_baseline_v0_synthetic_harsh.json`)** — canonical for F3–F10 commit gating:

| KPI | Harsh v0 | Target | Source |
|---|---|---|---|
| `overlap_decode_only_p95_ms` | 13.94 | ≤7.0 | `cache=decode` `total_ms` p95 |
| `overlap_decode_only_max_ms` | 77.67 | ≤40.0 | `cache=decode` `total_ms` max |
| `overlap_decode_sample_share_pct` | 4.45 | ≤2.5 | `decode / total × 100` |
| `overlap_slow_frame_count_16ms` | 3 / 30 s | ≤1 / 30 s | frames > 16 ms |

**Tier-2 — real-world (mandatory for "Final target" claim)**:

| KPI | Live 2026-04-28 | Target |
|---|---|---|
| `overlap_drag_event_p95_max_ms` | 607.9 | ≤300 |
| `overlap_drag_ui_lag_max_max_ms` | 363.9 | ≤180 |
| `overlap_drag_handler_p95_max_ms` | 3.7 | ≤16 (no regression) |
| `overlap_drag_background_decode_count_total` | 0 | 0 (R3 invariant) |
| `overlap_settled_present_p95_ms` | 1 sample (TBD) | populate to ≥30 samples |
| `overlap_sentinel_breakdown.decode` | 0 (pre-F2.1b) | ≥1 per drag-with-decode |

Demoted (kept in payload for compat, NOT a target): `overlap_set_slice_present_p95_ms`, `overlap_decode_p95_ms` (all-samples), `overlap_effective_fps`, `overlap_cache_hit_ratio_pct`.

---

## Headless overlap reproducer (F0.4, 2026-04-28)

A no-Qt, no-DM synthetic runner that produces ``[OVERLAP_SCENARIO]`` log
samples on any developer machine without requiring a live download or human
stack-drag input. Used to smoke-validate F2.1 instrumentation, parser
regression, and to seed ``overlap_baseline_v0_synthetic.json`` between
human-captured baselines.

**Script:** `tools/performance/synthetic_overlap_runner.py`

**CLI:**

```powershell
.venv\Scripts\python.exe tools\performance\synthetic_overlap_runner.py `
    --duration 5 --output overlap_baseline_v0_synthetic.json
```

**What it does:**

1. Materialises a deterministic 60-slice 256x256 MONOCHROME2 series under
   a temp dir (slope=1, intercept=-1024, fixed per-slice RNG seed).
2. Sets ``AIPACS_OVERLAP_LOG_SAMPLE=1`` (every overlap return path emits a
   tag) and reloads ``Lightweight2DPipeline`` so the new sample rate is
   picked up by the module constant.
3. Activates the heavy_download gate via
   ``modules.zeta_boost.cache_engine._zb_globals.set_global_download_active(True)``.
4. Runs a ``set_fast_interaction(True, "drag")`` burst at 30 Hz for the
   requested duration, sweeping the slice index 0 -> N -> 0.
5. Settles via ``set_fast_interaction(False)`` and renders one final frame.
6. Parses the captured log via ``parse_overlap_log_file`` from the KPI
   harness and writes JSON.

**Determinism caveat (per plan):** pixel data is byte-identical run to run,
but ``decode_ms`` / ``wl_ms`` / ``total_ms`` and the exact
hit/surrogate/decode breakdown depend on host CPU and prefetch worker
scheduling. Treat the synthetic baseline as a smoke-level signal that
should land within ~30% of human-captured baselines on the same machine.
The runner does NOT simulate real network arrival ordering or disk-flush
timing - the entire series is on disk before the drag loop starts.

**Smoke test:**
`tests/performance/test_synthetic_overlap_runner.py::test_synthetic_overlap_runner_smoke`
runs a 1.0s burst over 20 slices at 128x128 and asserts:

* Total runtime < 60s (plan F0.4 success criterion).
* JSON file matches the in-memory return payload.
* ``overlap_sample_count >= 5``.
* ``sum(cache_breakdown.values()) == overlap_sample_count``.
* ``sum(settled_breakdown.values()) == overlap_sample_count``.

**Plan reference:** `plan-fastViewerOverlap100PercentImprovement.prompt.prompt.md` Phase F0.4.
