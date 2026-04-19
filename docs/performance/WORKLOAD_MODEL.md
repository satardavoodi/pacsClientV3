# FAST Viewer Workload Model (B2.5)

**Date:** 2026-04-14  
**Scope:** FAST mode (`pydicom_qt`) only.  
**Source:** `CONCURRENCY_ANALYSIS_v2.3.3.md` formalized into code-path mapping.

## Workload classes

| Class | Definition | Frame budget impact | Scheduling intent |
|---|---|---|---|
| **Foreground hard-interactive** | In-frame work on the user-visible critical path | Must complete within 16ms frame budget | Highest priority; preempts all lower classes |
| **Foreground soft-interactive** | User-visible work that can lag without breaking scroll feel | May arrive 200ms after interaction stops | Preemptable by hard-interactive |
| **Background latency-sensitive** | Work needed for near-term UX continuity | Runs between frames; should yield under pressure | Budgeted; defer under sustained hard-interactive load |
| **Background deferrable** | Non-urgent work with no immediate UI value | No frame budget claim | Suspend first under any pressure |

**Policy rule:** A gain in background throughput NEVER justifies a regression in hard-interactive KPIs.

## Code-path mapping

### Foreground hard-interactive

| Code path | File | Trigger | GIL hold |
|---|---|---|---|
| `QtViewerBridge.set_slice()` | `qt_viewer_bridge.py` | wheelEvent | ~1.8ms (cache hit) to ~12ms (cache miss) |
| `pipeline.get_rendered_frame()` — cache hit | `lightweight_2d_pipeline.py` | set_slice | ~0.1ms (OrderedDict lookup only) |
| `pipeline.get_rendered_frame()` — cache miss | `lightweight_2d_pipeline.py` | set_slice | 3–8ms (pydicom.dcmread + W/L LUT) |
| `_window_level_to_uint8()` (LUT path) | `dicom_windowing.py` | get_rendered_frame | ~1.7ms (numpy fancy indexing, releases GIL during C-level) |
| `_numpy_to_qimage_gray()` | `lightweight_2d_pipeline.py` | get_rendered_frame | ~0.06ms |
| `QtSliceViewer.set_image()` + `update()` | `qt_slice_viewer.py` | set_slice | ~0.5ms |
| `wheelEvent` dispatch | `_vw_scroll.py` | user input | ~0.1ms |

### Foreground soft-interactive

| Code path | File | Trigger | GIL hold |
|---|---|---|---|
| `end_fast_interaction()` — filter re-render | `qt_viewer_bridge.py` | scroll-stop timer (200ms) | ~2.5ms |
| `_update_annotations()` | `qt_viewer_bridge.py` | scroll-stop | ~0.5ms |
| `_schedule_reference_line_update()` | `patient_widget.py` | scroll event | round-robin, one target per tick |
| `_do_lock_sync()` | `patient_widget.py` | scroll event (100ms throttle) | ~0.5ms |

### Background latency-sensitive

| Code path | File | Trigger | GIL hold |
|---|---|---|---|
| `_decode_into_cache()` — prefetch | `lightweight_2d_pipeline.py` | _prefetch_around after each frame | 3–8ms per pydicom.dcmread |
| `_render_into_cache()` — frame prefetch | `lightweight_2d_pipeline.py` | after decode completes | ~2ms (W/L + filter + QImage) |
| `_grow_progressive_fast()` | `viewer_controller.py` | 150ms timer during download | ~1–3ms (os.scandir + metadata) |
| Progressive grow signal processing | `viewer_controller.py` | DM 100ms batch timer | ~0.5ms signal dispatch |

### Background deferrable

| Code path | File | Trigger | GIL hold |
|---|---|---|---|
| ZetaBoost cache warmup | `cache_engine/_zb_workers.py` | Study download complete | Dormant during download (triple-gated) |
| DM bridge Queue polling | `download_process_worker.py` | 20ms timer | GIL released during wait |
| GC re-enable | `_vw_scroll.py` | 2000ms after last render | ~0.01ms |
| Completion sweep timer | `viewer_controller.py` | 3000ms interval | ~1ms (disk I/O) |
| Resource monitor | system | 2000ms | ~0.1ms |

## Contention hotspots

| Source A | Source B | Shared resource | Severity | Scenario |
|---|---|---|---|---|
| Main thread (set_slice cache miss) | LW2D decode workers | **GIL** | **HIGH** | Scroll into newly-downloaded area |
| Progressive grow timer | Scroll event processing | **Main thread time** | MEDIUM | Active download + scroll |
| LW2D decode worker N | LW2D decode worker M | **GIL** (pydicom.dcmread) | MEDIUM | Prefetch burst |
| DM progress signals | Scroll events | **Qt event queue** | LOW | Burst progress + scroll |

## Queue boundaries

| Queue | Producer | Consumer | Max depth | Backpressure? |
|---|---|---|---|---|
| Decode futures (ThreadPoolExecutor) | `_submit_prefetch` | `_decode_into_cache` workers | up to 2 × `prefetch_radius` (40) | No — tracked by `_prefetch_pending` set |
| Frame futures (ThreadPoolExecutor) | `_submit_frame_prefetch` | `_render_into_cache` workers | up to 2 × `prefetch_radius` (40) | No — tracked by `_frame_prefetch_pending` set |
| Qt event queue | Timers + signals | Main thread event loop | Unbounded | No explicit backpressure |
| DM multiprocessing.Queue | Download subprocess | DM bridge QThread | maxsize=1000 | Yes (blocks producer at 1000) |

## Timer collision model

During simultaneous scroll + download, these timers can fire in the same 16ms frame:

| Timer | Interval | Main-thread cost | Collision risk |
|---|---|---|---|
| Progressive grow | 150ms | 1–3ms (os.scandir + metadata) | MEDIUM with scroll |
| Progress debounce | 100ms | 0.5ms (signal dispatch) | LOW |
| Coordinator recheck | 50ms | 0.1ms | LOW |
| scroll-stop | 200ms (single-shot) | 2.5ms (filter + annotations) | N/A (only fires after scroll stops) |
| GC re-enable | 2000ms | 0.01ms | LOW |

Worst-case timer collision: progressive grow (3ms) fires immediately before a scroll event (1.8ms cache hit) = 4.8ms of main-thread work in one tick. Under 16ms budget but eats into margin.
