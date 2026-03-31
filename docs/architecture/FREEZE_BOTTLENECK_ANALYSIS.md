# Freeze Bottleneck Analysis — v2.2.7.3 (2026-03-27)

## Executive Summary

The software freezes because **blocking I/O and blocking thread-wait operations run on the main Qt event loop thread**. The Qt event loop is the single thread that processes all UI events (mouse clicks, scroll, render, paint). When ANY operation blocks this thread, the entire application becomes unresponsive.

Three distinct freeze paths were identified, all triggered from the UI thread:

| Freeze Point | Operation | Duration | Trigger |
|---|---|---|---|
| **F1** | `worker.wait(5000)` per active worker | 5-15s | Series retry → `_pause_all_active_downloads()` → `stop_all()` |
| **F2** | `shutil.rmtree()` per series directory | 2-30s | Series/patient retry file cleanup |
| **F3** | `grpc_client.fetch_study_metadata_sync()` | 1-30s+ (or hang) | `_reconstruct_task_from_database()` when task not in memory |

Combined worst case: **30-120+ seconds of total UI freeze** from a single retry button click.

---

## Architecture Principle: Independent Loops

A DICOM Workstation is a set of **independent loops** (modules) that must not block each other:

```
┌─────────────────────────────────────────────────────┐
│                    Qt Event Loop                      │
│  (mouse, keyboard, paint, scroll, timer, signals)     │
├─────────────────────────────────────────────────────┤
│                                                       │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Viewer   │  │  Download    │  │  Thumbnail   │   │
│  │  Module   │  │  Manager     │  │  Manager     │   │
│  │           │  │              │  │              │   │
│  │ • scroll  │  │ • download   │  │ • load thumbs│   │
│  │ • DnD     │  │ • retry      │  │ • update     │   │
│  │ • tools   │  │ • preempt    │  │ • retry btn  │   │
│  │ • render  │  │ • progress   │  │              │   │
│  └──────────┘  └──────────────┘  └──────────────┘   │
│       ▲               ▲               ▲               │
│       │    SIGNALS     │    SIGNALS    │               │
│       └───────────────┴───────────────┘               │
└─────────────────────────────────────────────────────┘
```

**Rule:** No signal handler or slot may block the event loop for more than ~16ms (one frame at 60fps). Any operation longer than that MUST be offloaded to a background thread or scheduled asynchronously.

---

## Freeze Path F1: Worker Wait in stop_all()

### Call chain
```
User clicks 🔄 refresh button
  → thumbnail_manager.retry_download_requested.emit()
  → patient_widget._on_retry_series_download()
  → download_manager._on_series_retry()        [MAIN THREAD]
    → _pause_all_active_downloads()             [MAIN THREAD]
      → worker_pool.stop_all()                  [MAIN THREAD]
        → worker.request_cancel()               [fast]
        → worker.quit()                         [fast]
        → worker.wait(5000)                     [BLOCKS 5 SECONDS PER WORKER]
```

### Why it blocks
`QThread.wait(5000)` is a **synchronous blocking call** that waits up to 5 seconds for each worker thread to finish. If there's 1 active download, that's 5 seconds of freeze. If there are 3 (MAX_CONCURRENT_STUDIES), that's 15 seconds.

The worker thread may be in the middle of a socket read, a file write, or waiting for server response — it cannot respond instantly to the cancel flag.

### Fix
Replace `stop_all()` with a non-blocking cancellation:
1. Set cancel flag on all workers (fast)
2. Return immediately
3. Worker cleanup happens via the `worker.finished` signal (already connected)

---

## Freeze Path F2: File Deletion on Main Thread

### Call chain
```
_on_series_retry() or _on_per_patient_retry()  [MAIN THREAD]
  → os.listdir(series_path)                    [BLOCKS: disk I/O]
  → shutil.rmtree(series_path)                 [BLOCKS: deletes hundreds of files]
```

### Why it blocks
`shutil.rmtree()` deleting 500+ DICOM files (each 0.5-2MB) from an SSD takes 2-10 seconds. On an HDD, 10-30+ seconds. This runs synchronously on the main Qt thread.

### Fix
Offload file deletion to a background thread (QThread or asyncio.to_thread), then start the download worker only after deletion completes — via a callback/signal.

---

## Freeze Path F3: Synchronous gRPC on Main Thread

### Call chain
```
_start_download_worker()                       [MAIN THREAD]
  → _reconstruct_task_from_database()           [MAIN THREAD]
    → grpc_client.fetch_study_metadata_sync()   [BLOCKS: network I/O, 1-30s+]
```

### Why it blocks
This is a synchronous network call to the PACS server. If the server is slow or the network congested, it can block for 30+ seconds or hang indefinitely (no timeout configured).

### Fix
1. Add a timeout to the gRPC call (e.g., 10 seconds)
2. Offload the call to a background thread
3. If task reconstruction fails, proceed without it (degrade gracefully)

---

## Secondary Issues

### S1: Progressive viewer signal cascade
When downloads are active, `seriesProgressUpdated` fires ~10 times/second. Each signal cascades through `on_series_progress` → `update_series_progress()` → `on_series_images_progress()` → `_find_progressive_viewers()` (O(n) scan). This compounds to 50-200ms of event loop work per second, causing scroll stutter.

### S2: Series 202 specific bug
The R20 check (`check_series_complete`) counts files on disk and skips the series if all files exist. The `_on_per_patient_retry` now deletes "complete" series (v2.2.7.3 fix), but `_on_series_retry` (called by the refresh button) has the SAME problem — it also does a file-count check and may keep files that R20 considers "complete".

### S3: Active download guard prevents retry
`_on_series_retry()` at line ~3137 checks if the study is currently DOWNLOADING with active workers, and if so, returns without doing anything. This means the refresh button does NOTHING for series that are part of an active download — even if that specific series failed within the download.

---

## Recommended Fix Priority

| Priority | Fix | Impact | Complexity |
|----------|-----|--------|------------|
| **P0** | Make `_on_series_retry` non-blocking (offload I/O) | Eliminates UI freeze | Medium |
| **P0** | Make `_on_per_patient_retry` non-blocking (offload I/O) | Eliminates UI freeze | Medium |
| **P0** | Replace `stop_all()` with async cancel (no wait) | Eliminates 5-15s freeze | Low |
| **P1** | Add timeout to gRPC sync call | Prevents infinite hang | Low |
| **P1** | Fix Series 202 R20 skip in `_on_series_retry` | Enables actual re-download | Low |
| **P2** | Throttle progressive viewer signal cascade | Reduces scroll stutter | Medium |

---

## Design Principle: The Orchestrator Question

> Is an orchestrator required?

**No, a centralized orchestrator is not required.** What IS required is enforcing the **non-blocking rule** at each module boundary:

1. **Viewer → Download Manager:** Communication via Qt signals only. No synchronous method calls. If the viewer needs to retry a download, it emits a signal and returns immediately. The download manager processes the signal asynchronously.

2. **Download Manager → Viewer:** Communication via Qt signals only. Progress updates, completion notifications — all via signals with throttling.

3. **Within Download Manager:** All I/O operations (file deletion, network calls, thread wait) must run off the main thread. Use `QTimer.singleShot(0, ...)` or `asyncio.ensure_future()` to defer heavy work.

The existing Qt signal/slot architecture is the correct pattern. The problem is not missing an orchestrator — it's that **some slots perform blocking operations directly on the main thread** instead of deferring them.
