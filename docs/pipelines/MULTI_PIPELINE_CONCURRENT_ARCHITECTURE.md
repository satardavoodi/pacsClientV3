# Multi-Pipeline Concurrent Architecture for PACS Workstation
## Main Loop + Sub-Loops with Zero Contention Design

**Current Date:** February 13, 2026  
**Architecture Version:** 2.0 - Concurrent Multi-Pipeline  
**Status:** DESIGN & IMPLEMENTATION

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    PACS Application                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────────┐      ┌──────────────────────────┐  │
│  │   MAIN PIPELINE      │      │   SUB-PIPELINES (N)      │  │
│  │  (Download Loop)     │      │  (View/Render Loops)     │  │
│  │                      │      │                          │  │
│  │ 1. Select           │      │ • View cached series     │  │
│  │ 2. Download         │◄────►│ • Re-render with tools   │  │
│  │ 3. DB Sync          │      │ • Metadata lookup        │  │
│  │ 4. Render           │      │ • Measurement cache      │  │
│  │ 5. Report/Upload    │      │ • Annotation read        │  │
│  │                      │      │                          │  │
│  └──────────────────────┘      └──────────────────────────┘  │
│           │                             │                    │
│           ▼                             ▼                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │        SHARED RESOURCE LAYER (Protected)               │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │                                                         │ │
│  │ • Database (WAL mode + pool)  [Read/Write with locks] │ │
│  │ • File System (series files)  [Concurrent read-safe]  │ │
│  │ • VTK Cache (renderer state)  [Actor-level locking]   │ │
│  │ • Viewer State (widgets)      [Per-viewer thread]     │ │
│  │ • Memory Cache (hot data)     [LRU eviction]          │ │
│  │                                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Design Principles

### 1. **Pipeline Independence**
- Each pipeline (main + sub-loops) runs in its **own thread/executor**
- Minimal synchronization points
- **No blocking waits** between pipelines

### 2. **Resource Separation**
```
Main Pipeline Resources:          Sub-Pipeline Resources:
├─ Download queue                 ├─ Viewer widgets (per-window)
├─ Download workers               ├─ Cached series data
├─ DB write locks (sequential)    ├─ VTK render cache
├─ Reporting/upload               ├─ UI update signals
└─ File write locks               └─ Local measurements

SHARED (Protected):
├─ Database reads (concurrent)
├─ File reads (concurrent)
├─ Metadata cache (LRU)
└─ Memory budget tracker
```

### 3. **Concurrency Strategy**
- **Readers**: Multiple sub-pipelines read DB/files simultaneously
- **Writers**: Main pipeline writes DB (with deferred transactions)
- **Rendering**: Per-viewer rendering thread (no UI thread blocks)
- **Memory**: LRU cache limits + smart eviction during main pipeline updates

### 4. **Cache Hierarchy** (Hot → Cold)
```
Level 1 (L1): Viewer-local cache       [In memory, fast access]
  └─ Currently viewed series pixels/vtk actors
  └─ Recent measurements & annotations
  └─ Slide stack for current series

Level 2 (L2): Application-shared cache [In memory, managed LRU]
  └─ Last 5 viewed series (preloaded)
  └─ Metadata for studies in download queue
  └─ Recently computed field-of-views

Level 3 (L3): Disk cache              [Fast SSD, on-demand load]
  └─ Downloaded DICOM series (.dcm files)
  └─ Generated thumbnails
  └─ Rendering cache artifacts

DB: Persistent state                   [SQLite with WAL]
  └─ Series metadata, instance paths
  └─ Download progress, state machine
  └─ User annotations, measurements
```

---

## Implementation Strategy

### Phase 1: Pipeline Separation (TODAY)

Create two distinct execution contexts:

#### **Main Pipeline**
```python
class MainDownloadPipeline:
    """
    Orchestrates: Select → Download → DB Sync → Queue for rendering
    
    Runs: In main Qt event loop OR dedicated main thread
    Frequency: User-triggered (select study)
    Operations:
    - Query server for study metadata
    - Queue download task in Zeta
    - (Wait for completion)
    - Sync results to DB
    - Signal render queue
    - Upload/report back to server
    """
    
    def execute_main_loop(self, study_uid):
        # 1. Query metadata (non-blocking)
        task = await self.prepare_download_task(study_uid)
        
        # 2. Queue download (non-blocking, returns immediately)
        self.queue_download(task)
        
        # 3. Wait for completion (async, doesn't block rendering)
        # Sub-pipelines can render while this waits
        await self.wait_download_completion(study_uid)
        
        # 4. DB sync (fast, WAL allows concurrent reads)
        self.sync_to_database(study_uid)
        
        # 5. Signal render queue
        self.queue_render(study_uid)
        
        # 6. Report (can be async)
        await self.report_completion(study_uid)
```

#### **Sub-Pipelines (Render/View Loops)**
```python
class ViewRenderSubPipeline:
    """
    Runs concurrently with main pipeline.
    Never waits for downloads or DB writes.
    
    Operations (non-blocking):
    - Load cached series (if available)
    - Render with current tools/measurements
    - Handle user interactions (zoom, pan, measure)
    - Update annotations
    """
    
    def render_view_loop(self, viewer_widget):
        # This runs in viewer's own thread, never blocks main
        while viewer_active:
            # 1. Try to load cached series (fail-fast if not ready)
            if cached_series.available():
                pixels = self.load_from_cache(series_uid)
            else:
                # Load from disk (already downloaded) non-blocking
                pixels = self.load_from_disk_async(series_uid)
            
            # 2. Render to VTK (no DB locks)
            self.render_vtk(pixels)
            
            # 3. Apply measurements from separate measurement cache
            self.apply_cached_measurements(series_uid)
            
            # 4. Update UI
            viewer_widget.update()
            
            # 5. Handle user input
            self.process_user_input()
```

### Phase 2: Smart Caching

#### **Memory Cache Manager** (Controls memory usage without stalling)
```python
class MemoryCacheManager:
    """
    Manages L1 + L2 cache with LRU eviction.
    Key: Doesn't block main pipeline, doesn't throw away hot data.
    """
    
    def __init__(self, max_memory_mb=500):
        self.max_memory = max_memory_mb
        self.current_memory = 0
        self.cache = {}  # series_uid -> (data, last_access, size)
        self.lock = threading.RLock()
    
    def add_to_cache(self, series_uid, pixel_data):
        """Add series to cache, evict LRU if needed (non-blocking)"""
        with self.lock:
            size = len(pixel_data) / 1024 / 1024  # MB
            
            # If we need space, evict oldest NOT CURRENTLY VIEWING
            if (self.current_memory + size) > self.max_memory:
                self._evict_lru(size)
            
            self.cache[series_uid] = {
                'data': pixel_data,
                'last_access': time.time(),
                'size': size,
                'pin_count': 0  # Prevents eviction while viewing
            }
            self.current_memory += size
    
    def pin(self, series_uid):
        """Mark series as 'in use' (won't be evicted)"""
        with self.lock:
            if series_uid in self.cache:
                self.cache[series_uid]['pin_count'] += 1
    
    def unpin(self, series_uid):
        """Mark series as potentially evictable"""
        with self.lock:
            if series_uid in self.cache:
                self.cache[series_uid]['pin_count'] = max(0, self.cache[series_uid]['pin_count'] - 1)
    
    def _evict_lru(self, needed_space):
        """Evict oldest not-pinned entries until space available"""
        candidates = [
            (uid, entry) for uid, entry in self.cache.items()
            if entry['pin_count'] == 0
        ]
        
        # Sort by last_access (oldest first)
        candidates.sort(key=lambda x: x[1]['last_access'])
        
        freed = 0
        for uid, entry in candidates:
            if freed >= needed_space:
                break
            self.current_memory -= entry['size']
            del self.cache[uid]
            freed += entry['size']
```

### Phase 3: Database Concurrency (Already in Place, Enhanced)

```python
# Current state: WAL mode + connection pooling
# Additional: Separate read/write transactions

class DatabasePipelineAdapter:
    """
    Bridge between pipelines and database with optimal locking.
    """
    
    def read_series_metadata(self, study_uid):
        """Non-blocking read (multiple pipelines can do this)"""
        # Uses thread-local pooled connection
        with get_db_connection() as conn:
            conn.isolation_level = "DEFERRED"  # Let reads share locks
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM series WHERE study_uid = ?",
                (study_uid,)
            )
            return cursor.fetchall()
    
    def write_download_state(self, study_uid, state):
        """Serialized write (main pipeline only, or queued)"""
        # Main pipeline's write doesn't block reads
        with get_db_connection() as conn:
            conn.isolation_level = "IMMEDIATE"  # Get write lock early
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE studies SET download_state = ? WHERE study_uid = ?",
                (state, study_uid)
            )
            conn.commit()
    
    def streaming_instance_write(self, study_uid, instance_list):
        """Write instances as they arrive (batched)
        
        Doesn't block readers due to WAL mode.
        """
        batch_size = 100
        for i in range(0, len(instance_list), batch_size):
            batch = instance_list[i : i + batch_size]
            
            with get_db_connection() as conn:
                conn.isolation_level = "DEFERRED"
                cursor = conn.cursor()
                
                # Multi-row insert
                cursor.executemany(
                    """INSERT INTO instances 
                       (sop_uid, series_fk, instance_path, instance_number)
                       VALUES (?, ?, ?, ?)""",
                    batch
                )
                conn.commit()
            
            # Allow other operations between batches
            time.sleep(0.01)
```

### Phase 4: Thread-Safe State Machine

```python
class PipelineStateManager:
    """
    Ensures race-free transitions between pipeline stages.
    """
    
    def __init__(self):
        self._study_states = {}  # study_uid -> state
        self._lock = threading.RLock()
    
    def transition(self, study_uid, from_state, to_state):
        """Atomic state transition (no race conditions)"""
        with self._lock:
            current = self._study_states.get(study_uid, None)
            
            if current != from_state:
                raise StateTransitionError(
                    f"Cannot transition {study_uid}: expecting {from_state}, "
                    f"got {current}"
                )
            
            self._study_states[study_uid] = to_state
            logger.info(f"📊 State transition: {study_uid} {from_state}→{to_state}")
    
    def can_render(self, study_uid):
        """Check if sub-pipeline can safely render (non-blocking query)"""
        with self._lock:
            state = self._study_states.get(study_uid)
            # Can render if DOWNLOADED or RENDERING or beyond
            return state in ['DOWNLOADED', 'RENDERING', 'COMPLETED']
```

---

## Contention Prevention Checklist

| Conflict Point | Issue | Prevention | Status |
|---|---|---|---|
| **DB writes** | Multiple threads writing instances | WAL mode allows concurrent reads while writes happen | ✅ Active |
| **File reads** | Sub-pipelines + main reading series | OS handles (no locks on reads) | ✅ Safe |
| **Viewer state** | Sub-pipelines concurrently rendering | Per-widget rendering thread + local pinning | 🔨 Implement |
| **Memory cache** | Eviction while rendering | Pin/unpin prevents eviction of viewing series | 🔨 Implement |
| **VTK actors** | Concurrent render state changes | Actor-level thread safety (VTK is thread-safe for read-only actors) | ✅ VTK Design |
| **Download queue** | Main pipeline + UI adding tasks | Qasync signals (thread-safe), queue is concurrent | ✅ qasync design |

---

## Implementation Roadmap

### Week 1: Core Pipeline Separation
- [ ] Create separate `MainPipeline` class
- [ ] Create `ViewRenderPipeline` class per viewer
- [ ] Thread-safe state machine for transitions
- [ ] Async/await for non-blocking main loop

### Week 2: Memory Management
- [ ] MemoryCacheManager with LRU eviction
- [ ] Pin/unpin system for viewers
- [ ] Memory budget tracking
- [ ] Test with 1000+ cache cycles

### Week 3: Concurrency Testing
- [ ] Simulate main pipeline + 5 sub-pipelines
- [ ] Verify no DB locks during rendering
- [ ] Measure UI responsiveness
- [ ] Test cache eviction under memory pressure

### Week 4: Integration & Optimization
- [ ] Integrate with existing Zeta download manager
- [ ] Performance profiling
- [ ] Auto-tuning of cache sizes
- [ ] Production readiness

---

## Key Invariants (Must Always Hold)

1. **Sub-pipelines never block main pipeline**
   - Rendering doesn't wait for downloads
   - Rendering doesn't wait for DB writes
   
2. **Main pipeline never blocks sub-pipelines**
   - DB writes don't prevent rendering reads
   - Download completion doesn't stall viewing
   
3. **Memory is bounded**
   - L1+L2 cache never exceeds configured limit
   - Eviction respects current viewing (pinned data)
   
4. **Data is always consistent**
   - Reads see committed data
   - Writes maintain ACID properties
   - No dirty reads from concurrent operations
   
5. **Performance is predictable**
   - UI response time <100ms regardless of download state
   - Cache hits available for recently viewed series
   - No "GC pauses" from memory management

---

## Testing Strategy

### Concurrent Scenario 1: Main + View
```python
def test_main_download_with_concurrent_view():
    """Main pipeline downloading study while sub-pipeline views cached series"""
    
    # 1. Pre-cache series A
    cache_manager.add_to_cache('series_a', pixel_data_a)
    
    # 2. Start viewing series A (pins it in cache)
    viewer.pin('series_a')
    
    # 3. Meanwhile, main pipeline starts downloading series B
    main_pipeline.queue_download('study_b')
    
    # 4. While download happens, viewer continuously renders series A
    for i in range(100):
        viewer.render('series_a')
        assert viewer.is_responsive(), "UI should stay responsive"
    
    # 5. When series B arrives, eviction should NOT touch series A
    time.sleep(5)  # Wait for download
    assert 'series_a' in cache_manager.cache, "Pinned series should survive eviction"
```

### Concurrent Scenario 2: Multiple Views
```python
def test_two_viewers_concurrent_rendering():
    """Two viewers rendering different series simultaneously"""
    
    viewer1.show_series('series_a')
    viewer1.pin('series_a')
    
    viewer2.show_series('series_b')
    viewer2.pin('series_b')
    
    # Both viewers render concurrently
    for i in range(100):
        viewer1.render()
        viewer2.render()
        
        # Neither should block the other
        assert viewer1.render_time < 50ms
        assert viewer2.render_time < 50ms
```

### Concurrent Scenario 3: Cache Under Pressure
```python
def test_cache_eviction_under_main_pipeline_load():
    """Main pipeline loading 10 new series while viewers active"""
    
    # Fill cache with series A,B,C (viewers active on these)
    for s in ['a', 'b', 'c']:
        cache.add(f'series_{s}', large_pixel_data)
        viewer.pin(f'series_{s}')
    
    # Main pipeline starts loading 20 new series
    for i in range(20):
        new_data = download_next_series()
        cache.add(new_data)  # Should evict non-pinned old data
    
    # Original pinned series should still be accessible
    assert cache.get('series_a') is not None
    assert cache.get('series_b') is not None
    assert cache.get('series_c') is not None
```

---

## Performance Targets

| Metric | Target | Method |
|--------|--------|--------|
| **UI Response Time** | <100ms | Per-widget render thread |
| **Download doesn't freeze rendering** | 0% freeze | Non-blocking queuing |
| **Cache hit rate** | >80% for recent series | LRU with pinning |
| **Memory footprint** | <1GB (configurable) | Automatic eviction |
| **Concurrent pipelines** | 10+ without blocking | Separate thread pool |
| **DB lock contention** | <5% wait time | WAL + connection pool |

---

## Success Criteria

✅ User can **view cached series while download is running**  
✅ No **UI freezes** during main pipeline operations  
✅ **Multiple concurrent viewers** render smoothly  
✅ **Memory usage stays bounded** over 1000+ cycles  
✅ **DB maintains consistency** under concurrent access  
✅ **Performance is predictable** (no random lag spikes)

---

## References

- Database: `PacsClient/utils/database.py` (WAL mode, connection pooling)
- Download: `PacsClient/zeta_download_manager/`
- Viewer: `PacsClient/pacs/patient_tab/`
- Async: `main.py` (qasync QEventLoop)

