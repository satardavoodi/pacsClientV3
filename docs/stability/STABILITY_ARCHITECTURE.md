# Stability Architecture

> **Version:** v2.2.3.4.0 | **Updated:** 2026-03-10

## Purpose

A DICOM workstation performs the same operations thousands of times per session: open patient, download series, view images, close, repeat. **Stability means every cycle completes cleanly, leaving no leaked resources that accumulate over time.** This document defines the patterns that guarantee this stability.

## Core Principle: The Clean Cycle

Every repeating operation in the workstation must satisfy:

```
ACQUIRE resources → USE resources → RELEASE resources → VERIFY clean state
```

If any step leaks, the leak multiplies with every cycle. After 1000 cycles, even a 100KB leak becomes 100MB.

---

## 1. Resource Lifecycle Management

### Pattern: Context-Managed Resources

All finite resources (database connections, file handles, thread pools) must use context managers or explicit lifecycle hooks.

```python
# CORRECT: Context manager guarantees cleanup
with get_db_connection() as conn:
    result = conn.execute(query)

# CORRECT: Explicit lifecycle in widget
class PatientWidget(QWidget):
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._timers = []
    
    def closeEvent(self, event):
        self._executor.shutdown(wait=False)
        for timer in self._timers:
            timer.stop()
        super().closeEvent(event)
```

### Resource Categories

| Resource | Lifecycle Pattern | Owner |
|----------|------------------|-------|
| DB connection | Context manager (`with`) | `database/core.py` pool |
| Socket connection | Singleton + explicit cleanup | `SocketService` |
| ThreadPoolExecutor | Create in init, shutdown in close | Component that creates it |
| QTimer | Parent-child (Qt auto-destroy) | Parent widget |
| VTK render window | Explicit cleanup before widget destroy | `VTKWidget` |
| File handles | Context manager (`with open(...)`) | Calling code |
| Subprocess | Graceful shutdown + force-kill timeout | `WarmupSubprocess` |

### Mandatory Cleanup Hooks

Every class that creates finite resources MUST implement cleanup:

| Widget Type | Required Hook | What to Clean |
|-------------|---------------|---------------|
| `QMainWindow` | `closeEvent()` | Socket, module manager, DB pool |
| `QWidget` (tab) | `closeEvent()` | VTK viewers, executors, timers |
| Service class | `cleanup()` / `shutdown()` | Connections, pools, threads |
| Cache class | `clear()` / `__del__()` | Memory entries, cleanup threads |

---

## 2. Connection Pool Management

### Database Connection Pool

```
Thread enters operation
  ├─ Acquire pool lock (brief)
  ├─ Check pool for reusable connection
  │   ├─ Found → Validate (SELECT 1) → Return
  │   └─ Empty → Create new connection
  ├─ Use connection (WAL mode, DEFERRED)
  └─ Return to pool (automatic via context manager)
```

**Rules:**
- Max 5 connections per thread
- Reuse validation prevents stale connections
- `cleanup_connection_pools()` called on app shutdown
- WAL mode enables concurrent read/write

### Socket Connection Pool

```
Operation needs socket
  ├─ Get singleton SocketService
  ├─ Check if connected
  │   ├─ Yes → Use existing connection
  │   └─ No → Connect with retry (3 attempts, backoff)
  ├─ Execute operation
  └─ Connection stays open (persistent session)
```

**Rules:**
- Singleton pattern (one service per app lifetime)
- Retry with exponential backoff + jitter
- Cleanup in MainWindow.closeEvent()

---

## 3. Cache Strategy

### Cache Hierarchy

```
L1: In-Memory (ZetaBoost)          ← Fastest, limited by RAM
  ├─ LRU eviction with pin/unpin
  └─ Cleared on tab close
  
L2: Disk Cache (ZetaBoost)         ← Fast, limited by disk
  ├─ SQLite manifest for tracking
  └─ Survives app restart

Thumbnail Cache (TTL-based)        ← Auto-cleanup thread
  ├─ 300s TTL per entry
  └─ Background cleanup every 60s

Metadata Cache (TTL-based)         ← Auto-cleanup thread  
  ├─ 300s TTL per entry
  └─ Cleared with thumbnails
```

### Cache Invariants

1. **Every cache entry has a TTL or size limit** — no unbounded caches
2. **Eviction is automatic** — LRU for memory caches, TTL for time-based caches
3. **Pin/unpin prevents eviction of active entries** — unpinned entries can be evicted any time
4. **Cache clear on component close** — tab close clears associated L1 cache
5. **Disk cache survives restart** — but has maximum size limit

### Cache Cleanup Timeline

```
Continuous:
  └─ TTL expiry removes stale entries (every 60s check)

On tab close:
  └─ L1 cache cleared for that study

On app shutdown:
  └─ Thumbnail cleanup thread stopped
  └─ DB pool connections closed
  └─ (L2 disk cache survives for next session)

On manual action:
  └─ Storage cleanup dialog for disk cache management
```

---

## 4. Thread Safety Patterns

### Qt Thread Safety

```
Background thread                    Main (UI) thread
  │                                    │
  ├─ Heavy computation                 ├─ Widget updates
  │   (image loading, ITK)             │   (only from main thread!)
  │                                    │
  └─ Signal.emit(result) ──────────▶  └─ Slot receives result
                                          └─ Update UI safely
```

**Rules:**
- **Never update Qt widgets from background threads** — always use signals
- `asyncio.to_thread()` for async I/O operations
- `ThreadPoolExecutor` for CPU-bound work
- Single-threaded VTK render calls

### Lock Hierarchy

To prevent deadlocks, locks must be acquired in a consistent order:

```
1. Database pool lock (_pool_lock)      ← Always first
2. Cache lock (RLock)                   ← Second
3. UI state lock                        ← Third
4. ZetaBoost engine lock                ← Fourth
```

**Rule:** Never acquire a higher-numbered lock while holding a lower-numbered one in reverse order.

### Error Isolation

```python
# CORRECT: Catch-and-continue in background operations
def _background_worker(self):
    try:
        result = self._do_work()
        self.result_ready.emit(result)
    except Exception as e:
        logger.error(f"Background work failed: {e}")
        self.error_occurred.emit(str(e))
    # Worker continues to next task — never crashes the loop

# INCORRECT: Unhandled exception kills the thread
def _background_worker(self):
    result = self._do_work()  # If this throws, thread dies silently
    self.result_ready.emit(result)
```

---

## 5. Memory Management

### GC Strategy

```
Normal operation:
  └─ GC enabled (default Python behavior)

Scroll burst (wheelEvent):
  ├─ gc.disable()               ← Prevent GC pauses during scroll
  ├─ ... scroll frames ...
  └─ GC re-enable timer (2000ms after last render)
      └─ gc.enable()            ← Resume normal GC
```

**Rules:**
- GC suppression ONLY during scroll bursts
- Re-enable timer is mandatory — never leave GC disabled permanently
- Do NOT call `gc.collect()` during scroll
- Do NOT add expensive per-frame operations inside `set_slice()` without `_in_wheel_scroll` guard

### WeakRef Usage

Use `weakref.ref()` for:
- Callbacks to parent widgets (prevent circular references)
- Observer patterns where the observed may outlive the observer
- Cache entries that should not prevent garbage collection

---

## 6. Error Recovery

### Retry Pattern (Network Operations)

```python
@retry(max_attempts=3, initial_delay=1.0, backoff_multiplier=2.0, jitter=True)
def network_operation():
    """Retries with exponential backoff: 1s, 2s, 4s (+ random jitter)"""
    return socket_client.fetch_data()
```

### Fallback Pattern (Viewer Operations)

```python
def load_series(self, series_number):
    try:
        # Primary path
        volume = self._load_from_cache(series_number)
    except CacheMiss:
        try:
            # Fallback: load from disk
            volume = self._load_from_disk(series_number)
        except Exception:
            # Last resort: show error state in UI
            self._show_load_error(series_number)
            return
    self._display_volume(volume)
```

### Recovery Categories

| Error Type | Strategy | Max Retries |
|------------|----------|-------------|
| Network timeout | Exponential backoff + jitter | 3 |
| DB connection failure | Reconnect from pool | 1 (pool creates new) |
| File I/O error | Log + skip/retry | 1 |
| VTK render error | Log + fallback UI state | 0 (graceful degrade) |
| Cache corruption | Clear cache + reload | 1 |
| Subprocess crash | Restart subprocess | 1 |

---

## 7. Shutdown Sequence

Proper shutdown must happen in reverse dependency order:

```
1. Stop accepting new operations
   ├─ Block new downloads
   ├─ Block new viewer loads
   └─ Block new module starts

2. Stop background workers
   ├─ ZetaBoost engines → shutdown()
   ├─ ThreadPoolExecutors → shutdown(wait=False)
   ├─ Warmup subprocess → graceful stop + force-kill timeout
   └─ Auto-cleanup cache threads → stop

3. Cleanup open resources
   ├─ VTK render windows → cleanup
   ├─ Socket connections → disconnect
   └─ Module managers → shutdown

4. Persist final state
   ├─ Download state → DB (preserved)
   ├─ UI state → cleared (not preserved)
   └─ Cache manifests → flushed

5. Release infrastructure
   ├─ Database pool → cleanup_connection_pools()
   └─ Qt widget cascade → deleteLater / destroy
```

---

## 8. Monitoring & Diagnostics

### Diagnostic Logging

```python
# Per-component timing
log_stage_timing(component="db", stage="pool_lock_wait", duration_ms=2.1)
log_stage_timing(component="viewer", stage="itk_filters", duration_ms=150.3)
```

### Health Indicators

| Indicator | Healthy | Warning | Critical |
|-----------|---------|---------|----------|
| DB pool size | ≤5/thread | 6-8 | >8 (leak) |
| Memory usage | <2GB | 2-3GB | >3GB |
| Event queue delay | <16ms | 16-50ms | >50ms |
| Cache hit rate | >80% | 50-80% | <50% |
| Thread count | <20 | 20-40 | >40 (leak) |

---

## 9. Implemented Stability Components

### LifecycleManager (`PacsClient/components/lifecycle_manager.py`)

Centralized registry that coordinates orderly shutdown of all long-lived subsystems.

- **Registration:** Each subsystem registers a name, shutdown callback, and timeout via `lifecycle_manager.register()`.
- **Shutdown order:** Resources are drained in **LIFO** (last-in-first-out) order so high-level consumers stop before low-level infrastructure.
- **Health checks:** Optional health-check callbacks can be attached for runtime diagnostics (`health_snapshot()`).
- **Integration point:** `MainWindowWidget.__init__()` calls `_register_lifecycle_resources()` which wires DB pool, cache threads, HomePanelWidget, patient tabs, and socket service. `closeEvent()` calls `lifecycle_manager.shutdown_all()`.

Registered resources (in registration / LIFO drain order):

| Order | Name | Timeout | What it cleans |
|-------|------|---------|----------------|
| 5 (first drain) | `socket_service` | 5s | Socket connection |
| 4 | `patient_tabs.exit_all` | 10s | VTK viewers, ZetaBoost engines |
| 3 | `HomePanelWidget.cleanup` | 5s | ThreadPoolExecutor, async tasks |
| 2 | `cache.auto_cleanup_threads` | 3s | TTL cache background threads |
| 1 (last drain) | `database.connection_pools` | 5s | SQLite WAL connections |

### CircuitBreaker (`PacsClient/pacs/patient_tab/utils/circuit_breaker.py`)

Prevents cascading failures when network endpoints (socket, gRPC, HTTP) become unavailable.

- **States:** `CLOSED` (normal) → `OPEN` (fail-fast) → `HALF_OPEN` (probe).
- **Thresholds:** configurable `failure_threshold` (default 5) and `cooldown` (default 30s).
- **Usage:** `breaker.call(fn, *args)` or `@breaker.protect` decorator.
- **Thread-safe:** All state transitions are protected by `threading.Lock`.
- **Integration:** Available for wrapping socket/gRPC calls in `socket_service.py` and download network calls.

### ZetaBoost Thread Joins (`modules/zeta_boost/engine.py`)

`deactivate()` now joins worker threads with a 3-second timeout after setting the stop event. This ensures in-progress cache writes and DB updates complete cleanly before the engine is destroyed, preventing silent data corruption on tab close.

### HomePanelWidget Cleanup (`home_ui.py`)

`cleanup()` shuts down `self.thread_pool` (`ThreadPoolExecutor`) and cancels outstanding `_background_tasks`, preventing thread-pool leak on repeated app sessions.
