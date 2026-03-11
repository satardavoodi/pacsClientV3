# Workstation Lifecycle

> **Version:** v2.2.3.4.0 | **Updated:** 2026-03-10

This document describes the complete lifecycle of the AIPacs DICOM Workstation — from startup through repeated operation cycles to shutdown. Understanding this lifecycle is essential for maintaining stability across long sessions.

## Application Startup

```
main.py
  ├─ 1. Multiprocessing freeze_support()
  ├─ 2. Graphics fallback config (WARP, Mesa, software OpenGL)
  ├─ 3. Qt attributes (AA_UseSoftwareOpenGL, etc.)
  ├─ 4. QApplication + QEventLoop (qasync)
  ├─ 5. Font loading + stylesheet
  ├─ 6. Diagnostic logging init (role="main")
  ├─ 7. Legacy data migration (flat → user_data/)
  ├─ 8. AppHandler (login dialog)
  │     ├─ Socket connection + authentication
  │     └─ On success → MainWindowWidget
  └─ 9. Event loop runs until exit
```

### Startup Invariants
- Graphics config environment variables MUST be set before any Qt/VTK imports
- Database is initialized in `MainWindowWidget.__init__()` (WAL mode, connection pool)
- Socket service is a singleton — first connection persists across the session

## Session Phases

### Phase 1: Home Panel (Patient List)
```
MainWindowWidget
  └─ HomePanelWidget
       ├─ Socket query → patient/study list
       ├─ Display in table
       └─ Wait for user interaction
```

### Phase 2: Study Operations (Repeating Cycle)
```
User double-clicks study
  ├─ PatientWidget tab created
  ├─ Zeta download initiated (if not cached)
  │     ├─ DownloadExecutor validates + fetches metadata
  │     ├─ Series downloaded via gRPC (subprocess)
  │     ├─ Progress signals → UI updates
  │     └─ DB records created (patient→study→series→instances)
  ├─ Series viewing
  │     ├─ image_io loads from disk/DB
  │     ├─ ITK filters applied
  │     ├─ VTK display
  │     └─ Scroll, zoom, measure (user interaction loop)
  ├─ ZetaBoost prefetch (warmup lane)
  │     ├─ L1 cache (in-memory) filled
  │     └─ L2 cache (disk) manifest updated
  └─ Tab closed → resources released
```

### Phase 3: Module Operations
```
Module activated (MPR, AI, Education, Printing, etc.)
  ├─ Module resources allocated
  ├─ Module work performed
  └─ Module closed → resources released
```

## Repeating Operation Cycles

The workstation constantly repeats these cycles during normal use:

| Cycle | Frequency | Resources Involved |
|-------|-----------|-------------------|
| **Patient open/close** | Every few minutes | VTK viewers, DB queries, file I/O |
| **Series scroll** | Continuous (60 Hz) | VTK render, GC suppression, timers |
| **Download** | Per study | gRPC subprocess, DB writes, disk I/O |
| **Cache fill/evict** | Continuous | L1 memory, L2 disk, thumbnail TTL |
| **DB connection cycle** | Per operation | Connection pool acquire/release |
| **Reference line sync** | During scroll | Round-robin repaint across viewers |

## Application Shutdown

```
MainWindowWidget.closeEvent()
  ├─ 1. Socket service cleanup (disconnect)
  ├─ 2. Download Manager UI state cleared (DB history preserved)
  ├─ 3. Module manager shutdown (if active)
  ├─ 4. Database connection pool cleanup
  ├─ 5. ThreadPoolExecutor shutdown
  ├─ 6. Qt widget destruction cascade
  └─ 7. Event loop exit
```

### Shutdown Rules
- Download Manager clears only UI state file — DB history is preserved
- Database pool connections are closed explicitly
- VTK render windows must be cleaned up before Qt widgets are destroyed

## Resource Ownership

| Resource | Owner | Created | Destroyed |
|----------|-------|---------|-----------|
| Database pool | `database/core.py` | First DB operation | `cleanup_connection_pools()` |
| Socket connection | `SocketService` (singleton) | Login | `cleanup()` in closeEvent |
| ThreadPoolExecutor | Various | Component init | Component shutdown |
| VTK render window | `VTKWidget` | Tab creation | Tab close / cleanup |
| QTimer instances | Parent widget | Widget init | Qt parent destruction |
| ZetaBoost engine | Per-PatientWidget | Study load | Tab close |
| Download subprocess | DownloadProcessWorker | Download start | Download complete |
| L1 cache (memory) | ZetaBoost engine | Warmup | Engine dispose |
| L2 cache (disk) | ZetaBoost engine | Warmup | Manual / app restart |
| Thumbnail cache | AutoCleanupCache | Thumbnail gen | TTL expiry (300s) |

## Critical Invariants

1. **No resource may outlive its owner.** If a tab closes, all VTK viewers, timers, and threads owned by that tab must be released.
2. **Database connections must return to pool.** Every `get_db_connection()` call must be in a `with` block or explicitly closed.
3. **GC is suppressed only during scroll bursts.** Re-enable timer fires 2000ms after last render. Never suppress GC for longer.
4. **Download subprocess has its own GIL.** Do not share objects with the download process — use signals only.
5. **ZetaBoost warmup runs at IDLE priority.** Do not escalate priority — causes memory-bus contention.
