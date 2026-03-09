# Module Execution Framework - Design & Architecture

**Date:** February 13, 2026  
**Status:** Design Phase  
**Goal:** Enable concurrent module execution alongside pipeline operations

---

## Problem Statement

**Current situation:**
- Multi-pipeline architecture handles downloads, rendering, and DB sync
- New requirement: Multiple modules (MPR, Eagle Eye, Ecomind, toolbars, etc.) must execute concurrently
- **Challenge:** These modules need database access, UI updates, and state management without blocking pipelines

**Requirements:**
1. Smooth, fast invocation (no freezes, stutters, or blocking)
2. Efficient DB operations (modules don't stall pipelines)
3. Concurrent execution with ALL pipeline operations
4. Stable and responsive under concurrent stress
5. Reliable state/storage operations

---

## Architecture Overview

### Three-Layer Execution Model

```
┌─────────────────────────────────────────────────────┐
│           APPLICATION LAYER (Qt UI)                 │
│  ┌──────────────┬──────────────┬──────────────┐    │
│  │ Toolbars     │ Eagle Eye    │ Custom Mods  │    │
│  ├──────────────┼──────────────┼──────────────┤    │
│  │ MPR Modules  │ Ecomind      │ Viewers      │    │
│  └──────────────┴──────────────┴──────────────┘    │
└─────────────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────────────┐
│      MODULE EXECUTION FRAMEWORK (NEW)               │
│  ┌─────────────────────────────────────────────┐   │
│  │  ModuleManager (Orchestrator)               │   │
│  │  ├─ Module Registry & Lifecycle             │   │
│  │  ├─ Concurrent Execution Scheduler          │   │
│  │  ├─ Resource Management                     │   │
│  │  └─ State Persistence                       │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────────────┐
│    PIPELINE & CACHE FRAMEWORKS (EXISTING)           │
│  ┌────────────────┐      ┌──────────────┐          │
│  │ Pipeline       │      │ Cache        │          │
│  │ Orchestrator   │      │ Manager      │          │
│  └────────────────┘      └──────────────┘          │
└─────────────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────────────┐
│        DATABASE & STORAGE LAYER                     │
│  ┌────────────────┐      ┌──────────────┐          │
│  │ SQLite (WAL)   │      │ File System  │          │
│  │ Pool: 5 conn   │      │ DICOM files  │          │
│  └────────────────┘      └──────────────┘          │
└─────────────────────────────────────────────────────┘
```

---

## Module Execution Layer Design

### 1. Module Interface (Abstract Base Class)

```python
class BaseModule(ABC):
    """All modules implement this interface"""
    
    def __init__(self, module_id: str):
        self.module_id = module_id
        self.state = ModuleState.IDLE
        self._stop_event = threading.Event()
    
    @abstractmethod
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Execute module async (main work)"""
        pass
    
    @abstractmethod
    def on_ui_event(self, event: UIEvent) -> None:
        """Handle UI events (user interactions)"""
        pass
    
    @abstractmethod
    def save_state(self) -> Dict[str, Any]:
        """Serialize module state for storage"""
        pass
    
    @abstractmethod
    def load_state(self, state: Dict[str, Any]) -> None:
        """Deserialize module state from storage"""
        pass
    
    def request_stop(self) -> None:
        """Graceful shutdown signal"""
        self._stop_event.set()
    
    def should_stop(self) -> bool:
        """Check if stop requested"""
        return self._stop_event.is_set()
```

### 2. Module Manager (Orchestrator)

```python
class ModuleManager:
    """Orchestrates concurrent module execution"""
    
    def __init__(self, pipeline_orchestrator: PipelineOrchestrator, max_concurrent: int = 5):
        self.orchestrator = pipeline_orchestrator  # Ref to existing pipeline orchestrator
        self.max_concurrent = max_concurrent
        
        self._modules = {}  # { module_id: BaseModule }
        self._threads = {}  # { module_id: Thread }
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._db_connection_pool = ConnectionPool(max_size=5)
        
        logger.info(f"✅ ModuleManager initialized (max {max_concurrent} concurrent)")
    
    def register_module(self, module: BaseModule) -> bool:
        """Register a module"""
        with self._lock:
            if module.module_id in self._modules:
                logger.warning(f"Module {module.module_id} already registered")
                return False
            
            self._modules[module.module_id] = module
            logger.info(f"📝 Registered module: {module.module_id}")
            return True
    
    async def invoke_module(self, module_id: str, context: ModuleContext) -> ModuleResult:
        """Invoke module - spawns in thread pool, returns immediately"""
        with self._lock:
            if module_id not in self._modules:
                raise ValueError(f"Module not registered: {module_id}")
            
            module = self._modules[module_id]
        
        # Check concurrent limit
        active_count = sum(1 for t in self._threads.values() if t.is_alive())
        if active_count >= self.max_concurrent:
            logger.warning(f"⏸️  Module queue full ({active_count}/{self.max_concurrent})")
            # Queue for later execution or return pending status
        
        # Spawn in thread pool (non-blocking)
        future = self._executor.submit(self._run_module, module_id, context)
        
        logger.info(f"🚀 Invoked module: {module_id} (queued for execution)")
        return ModuleResult(status=ModuleStatus.QUEUED, future=future)
    
    def _run_module(self, module_id: str, context: ModuleContext) -> Any:
        """Run module in thread (called by executor)"""
        module = self._modules[module_id]
        module.state = ModuleState.RUNNING
        
        try:
            # DB connection from pool (doesn't block pipeline)
            with self._db_connection_pool.acquire() as db_conn:
                context.db_connection = db_conn
                
                # Run module async/await compatible
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(module.execute(context))
                
                module.state = ModuleState.COMPLETED
                logger.info(f"✅ Module completed: {module_id}")
                return result
        
        except Exception as e:
            module.state = ModuleState.ERROR
            logger.error(f"❌ Module error: {module_id} - {e}")
            return ModuleResult(status=ModuleStatus.ERROR, error=str(e))
    
    def pause_module(self, module_id: str) -> bool:
        """Gracefully pause a running module"""
        with self._lock:
            if module_id not in self._modules:
                return False
            
            module = self._modules[module_id]
            module.request_stop()
            module.state = ModuleState.PAUSED
            logger.info(f"⏸️  Paused module: {module_id}")
            return True
    
    def resume_module(self, module_id: str) -> bool:
        """Resume a paused module"""
        with self._lock:
            if module_id not in self._modules:
                return False
            
            module = self._modules[module_id]
            module.state = ModuleState.IDLE
            logger.info(f"▶️  Resumed module: {module_id}")
            return True
    
    def get_module_status(self, module_id: str) -> ModuleStatus:
        """Get current status of a module"""
        with self._lock:
            return self._modules.get(module_id, {}).state if module_id in self._modules else None
    
    def save_all_states(self, storage_path: str) -> Dict[str, Dict]:
        """Persist all module states to disk"""
        states = {}
        for module_id, module in self._modules.items():
            try:
                states[module_id] = module.save_state()
            except Exception as e:
                logger.error(f"❌ Failed to save state for {module_id}: {e}")
        
        # Write to JSON
        with open(storage_path, 'w') as f:
            json.dump(states, f)
        
        logger.info(f"💾 Saved {len(states)} module states")
        return states
    
    def load_all_states(self, storage_path: str) -> bool:
        """Restore all module states from disk"""
        if not os.path.exists(storage_path):
            logger.warning(f"State file not found: {storage_path}")
            return False
        
        try:
            with open(storage_path, 'r') as f:
                states = json.load(f)
            
            for module_id, state in states.items():
                if module_id in self._modules:
                    self._modules[module_id].load_state(state)
            
            logger.info(f"📖 Loaded {len(states)} module states")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to load states: {e}")
            return False
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get execution metrics"""
        active = sum(1 for m in self._modules.values() if m.state == ModuleState.RUNNING)
        return {
            'total_modules': len(self._modules),
            'active_modules': active,
            'queued_limit': self.max_concurrent,
            'db_connections_available': self._db_connection_pool.available_count()
        }
```

### 3. Module Context (Shared Resources)

```python
@dataclass
class ModuleContext:
    """Shared context passed to modules"""
    module_id: str
    pipeline_orchestrator: 'PipelineOrchestrator'  # Access to cache, state
    db_connection: sqlite3.Connection = None  # DB connection from pool
    cache_manager: 'MemoryCacheManager' = None  # Access to shared cache
    patient_uid: str = None  # Current patient (if applicable)
    series_uid: str = None  # Current series (if applicable)
    user_parameters: Dict[str, Any] = None  # Module-specific params
    
    def get_cached_series(self, series_uid: str) -> Optional[Any]:
        """Efficient cache read (no DB hit)"""
        return self.cache_manager.get(series_uid)
    
    def cache_result(self, key: str, data: Any, size_bytes: int) -> None:
        """Store module result in shared cache"""
        self.cache_manager.add(key, data, size_bytes)
    
    def execute_query(self, query: str, params: tuple = ()) -> List[tuple]:
        """Execute read query (non-blocking DB call)"""
        cursor = self.db_connection.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
    
    def execute_update(self, query: str, params: tuple = ()) -> None:
        """Execute write query (automatic WAL handling)"""
        cursor = self.db_connection.cursor()
        cursor.execute(query, params)
        self.db_connection.commit()
```

### 4. Module States

```python
class ModuleState(Enum):
    IDLE = "idle"              # Not running
    QUEUED = "queued"          # Waiting for execution
    RUNNING = "running"        # Currently executing
    PAUSED = "paused"          # Suspended (can resume)
    COMPLETED = "completed"    # Finished successfully
    ERROR = "error"            # Failed with error
    DISPOSED = "disposed"      # Cleaned up, no resume

class ModuleStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
```

---

## Resource Management Strategy

### 1. Database Connections

**Problem:** Each module needs DB access, but main pipeline also writes

**Solution:**
- Connection pool with 5 connections (separate from pipeline's 5)
- WAL mode allows concurrent readers
- Module writes use DEFERRED isolation (non-blocking)
- Automatic timeout on long transactions (30 seconds)

```python
class ConnectionPool:
    def __init__(self, max_size: int = 5):
        self.queue = queue.Queue(maxsize=max_size)
        for _ in range(max_size):
            conn = sqlite3.connect(DB_PATH)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.isolation_level = "DEFERRED"  # Non-blocking
            self.queue.put(conn)
    
    @contextmanager
    def acquire(self, timeout: float = 30.0):
        try:
            conn = self.queue.get(timeout=timeout)
            yield conn
        finally:
            self.queue.put(conn)
    
    def available_count(self) -> int:
        return self.queue.qsize()
```

### 2. Shared Cache Access

**Problem:** Modules need to read/write cache, but main pipeline also manages it

**Solution:**
- Modules can read cache (fast path, no DB hit)
- Modules can cache their results
- Cache manager handles eviction automatically
- Module data is unpinned after module completes (allows eviction)

```python
# In module.execute():
context = ModuleContext(...)

# Read from cache (sub-ms, no DB)
pixel_data = context.get_cached_series("series_123")

# Do computation...
result = expensive_processing(pixel_data)

# Store result in shared cache
context.cache_result("module_result_key", result, size_bytes=10*1024*1024)
```

### 3. Thread Pool Management

**Problem:** Too many threads causes thrashing, too few causes queueing

**Solution:**
- Configurable max concurrent (default: 5)
- Executor queues beyond max
- Monitor queue depth
- Auto-scale hint based on system resources

```python
# Hard limits
executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="module_")

# Soft monitoring
if queue_depth > max_workers * 2:
    logger.warning("Module queue backing up - consider increasing limit")
```

---

## Module Integration Examples

### Example 1: MPR Module (Heavy Computation)

```python
class MPRModule(BaseModule):
    """Multi-Planar Reformatting computation"""
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Compute MPR views in thread pool"""
        
        if context.should_stop():
            return ModuleResult(status=ModuleStatus.TIMEOUT, error="Stopped by user")
        
        # Read from cache (fast)
        series = context.get_cached_series(context.series_uid)
        if not series:
            # Fall back to DB
            result = context.execute_query(
                "SELECT pixel_data FROM series WHERE uid = ?",
                (context.series_uid,)
            )
            if not result:
                return ModuleResult(status=ModuleStatus.ERROR, error="Series not found")
        
        # Compute MPR (long-running, non-blocking)
        axial = await self._compute_axial(series)
        sagittal = await self._compute_sagittal(series)
        coronal = await self._compute_coronal(series)
        
        # Cache results
        mpr_result = {
            'axial': axial,
            'sagittal': sagittal,
            'coronal': coronal,
            'timestamp': time.time()
        }
        context.cache_result(f"mpr_{context.series_uid}", mpr_result, size_bytes=50*1024*1024)
        
        # Save to DB (non-blocking, WAL handles concurrency)
        context.execute_update(
            "INSERT INTO computed_mpr (series_uid, axial, sagittal, coronal) VALUES (?, ?, ?, ?)",
            (context.series_uid, axial, sagittal, coronal)
        )
        
        return ModuleResult(status=ModuleStatus.COMPLETED, data=mpr_result)
    
    async def _compute_axial(self, series):
        # VTK computation here (~500ms)
        await asyncio.sleep(0.5)  # Simulate
        return "axial_data"
    
    # ... etc
```

### Example 2: Eagle Eye Module (UI-Driven)

```python
class EagleEyeModule(BaseModule):
    """Thumbnail previewer with zoom/pan"""
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Prepare thumbnail data"""
        
        # Lightweight preparation (quick)
        series = context.get_cached_series(context.series_uid)
        
        # Create thumbnail from first slice
        thumb = create_thumbnail(series, size=(200, 200))
        
        # Cache for fast display
        context.cache_result(f"thumb_{context.series_uid}", thumb, size_bytes=1*1024*1024)
        
        return ModuleResult(status=ModuleStatus.COMPLETED, data=thumb)
    
    def on_ui_event(self, event: UIEvent) -> None:
        """Handle user interactions (zoom, pan, etc.)"""
        if event.type == "zoom":
            # Lightweight UI update, no blocking
            self.zoom_level = event.data['level']
        elif event.type == "pan":
            self.pan_offset = event.data['offset']
```

### Example 3: Toolbar Module (Quick Operations)

```python
class ToolbarModule(BaseModule):
    """Lightweight toolbar with quick actions"""
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """No heavy work, just UI preparation"""
        
        # Query available tools for current series
        tools = context.execute_query(
            "SELECT tool_id, tool_name FROM available_tools WHERE series_uid = ?",
            (context.series_uid,)
        )
        
        return ModuleResult(status=ModuleStatus.COMPLETED, data=tools)
    
    def on_ui_event(self, event: UIEvent) -> None:
        """Handle toolbar actions"""
        if event.type == "tool_selected":
            tool_id = event.data['tool_id']
            # Notify main UI - non-blocking signal
```

---

## Concurrent Execution Scenarios

### Scenario 1: Main Pipeline + 3 Modules Concurrent

```
Timeline:

T0:
  Main: [Download Study_1]
  Module 1: - (idle)
  Module 2: - (idle)
  Module 3: - (idle)

T1: (user clicks "Import Measurements")
  Main: [Download Study_1]      (continues, 50% complete)
  Module 1: [MeasurementTool]   (queued, waiting for thread)
  Module 2: - (idle)
  Module 3: - (idle)

T2: (MeasurementTool starts)
  Main: [Download Study_1]      (continues, 70% complete)
  Module 1: [MeasurementTool]   (running, accessing DB)
  Module 2: - (idle)
  Module 3: - (idle)

T3: (user opens MPR)
  Main: [Download Study_1]      (continues, 90% complete)
  Module 1: [MeasurementTool]   (running, 80% complete)
  Module 2: [MPR Module]        (queued)
  Module 3: - (idle)

T4: (MeasurementTool finishes, MPR starts)
  Main: [Download Study_1]      (continues, 95% complete)
  Module 1: -                   (saving state)
  Module 2: [MPR Module]        (running, computing)
  Module 3: - (idle)

T5: (Main pipeline completes download)
  Main: [✅ Render Study_1]      (fast, already cached)
  Module 1: [✅ Saved]           (completed)
  Module 2: [MPR Module]        (running, 60% complete)
  Module 3: - (idle)

T6: (all complete)
  Main: [✅ Complete]
  Module 1: [✅ Complete]
  Module 2: [✅ Complete - cached result]
  Module 3: -
```

**Key observations:**
- ✅ Main pipeline never blocks
- ✅ Module thread pool handles queuing
- ✅ DB WAL allows concurrent access
- ✅ Cache shared between all layers
- ✅ No UI freezes

### Scenario 2: User Switches Studies During Pipeline

```
T0: Study A downloading + Module running
  Main: [Downloading Study A]
  Module 1: [Processing]

T1: User switches to Study B
  Main: [Resume Study A OR cancel + start Study B] (user choice)
  Module 1: [Pause]  (graceful via request_stop())

T2: Study B pipeline starts
  Main: [Downloading Study B]
  Module 1: [Paused, can resume later]

T3: User returns to Study A
  Main: [Can resume saved progress]
  Module 1: [Resume]  (resume from saved state)
```

---

## Non-Blocking Guarantees

### Main Thread (Qt Event Loop)

**No blocking operations:**
- ✅ Module invocation: Queues to thread pool (non-blocking)
- ✅ State save/load: Happens in module threads
- ✅ DB queries: Each module has its own connection
- ✅ Cache access: RLock is fast (<1ms)

### Module Threads

**No blocking operations:**
- ✅ DB access: WAL mode + DEFERRED isolation
- ✅ Cache read: Direct dict lookup (~0.1ms)
- ✅ Cache write: RLock protected (~1ms)
- ✅ File I/O: Async-compatible

### Pipeline Threads

**No blocking operations:**
- ✅ Database writes: Batched + deferred (allows concurrent readers)
- ✅ Network: Async download manager
- ✅ Cache: Separate manager, doesn't block module cache access

---

## Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| Module invocation | <5ms | Thread pool queue |
| Module execution | Configurable | Depends on module |
| DB read (module) | <10ms | WAL concurrent reader |
| DB write (module) | <50ms | Batched transaction |
| Cache read | <1ms | Direct lookup |
| State save | <100ms | JSON serialization |
| Main thread latency | <100ms | Event loop responsive |

---

## Implementation Roadmap

### Phase 1: Framework (1 week)
1. Implement `ModuleManager` core
2. Implement `BaseModule` abstract class
3. Implement `ModuleContext` with resource access
4. Connection pool for module DB access
5. Thread pool orchestration

### Phase 2: Integration (1 week)
1. Adapt existing MPR module → ModuleManager
2. Adapt existing Eagle Eye → ModuleManager
3. Create lightweight toolbar module
4. Test concurrent with pipelines

### Phase 3: Optimization (1 week)
1. Performance profiling
2. Cache tuning
3. DB connection optimization
4. Thread pool sizing

### Phase 4: Hardening (1 week)
1. Error recovery
2. State persistence
3. Timeout handling
4. End-to-end testing

---

## Integration with Existing Pipeline

```python
# In main.py

from PacsClient.components.pipeline_orchestrator import PipelineOrchestrator
from PacsClient.components.module_manager import ModuleManager
from PacsClient.components.modules import MPRModule, EagleEyeModule, ToolbarModule

# Initialize orchestrators
pipeline_orchestrator = PipelineOrchestrator(max_cache_mb=500)
module_manager = ModuleManager(pipeline_orchestrator, max_concurrent=5)

# Register modules
module_manager.register_module(MPRModule("mpr_0"))
module_manager.register_module(EagleEyeModule("eagle_eye_0"))
module_manager.register_module(ToolbarModule("toolbar_0"))

# Call modules from UI
async def on_mpr_button_clicked():
    result = await module_manager.invoke_module(
        "mpr_0",
        ModuleContext(
            module_id="mpr_0",
            pipeline_orchestrator=pipeline_orchestrator,
            series_uid=current_series_uid
        )
    )
    # Result is Future - check status or await
    print(f"Module status: {result.status}")

# Save/load states
def on_application_shutdown():
    module_manager.save_all_states("modules_state.json")

def on_application_startup():
    module_manager.load_all_states("modules_state.json")
```

---

## Success Criteria

✅ **Smooth Invocation**
- Module opens in <100ms
- No UI freezes/stutters
- Responsive to user input

✅ **Efficient DB Operations**
- Module reads don't block pipeline writes
- Pipeline writes don't block module reads
- Concurrent transactions succeed

✅ **Concurrent Execution**
- 5+ modules can run simultaneously
- Each module gets exclusive thread
- Pipeline continues uninterrupted

✅ **Stability**
- No deadlocks under concurrent stress
- Graceful shutdown of modules
- State persisted reliably

---

## Files to Create

1. **module_manager.py** - ModuleManager class
2. **module_base.py** - BaseModule abstract class and enums
3. **connection_pool.py** - Database connection pool
4. **modules/mpr_module.py** - Example MPR implementation
5. **modules/eagle_eye_module.py** - Example Eagle Eye implementation
6. **modules/toolbar_module.py** - Example Toolbar implementation
7. **MODULE_EXECUTION_ARCHITECTURE.md** - Full design (this doc)

---

## Conclusion

This Module Execution Framework enables:

✅ Smooth, fast module invocation during active pipelines  
✅ Concurrent DB operations without blocking  
✅ Reliable state management and persistence  
✅ Stable and responsive UI under multi-module stress  
✅ Clean integration with existing pipeline architecture  

Ready for implementation.
