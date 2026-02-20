# Module Execution Framework - Developer Reference Card

**Quick API Reference for Module Development**

---

## Core Classes

### BaseModule (Abstract)

```python
from PacsClient.components.module_manager import BaseModule, ModuleContext, ModuleResult, ModuleStatus

class MyModule(BaseModule):
    def __init__(self, module_id: str):
        super().__init__(module_id)
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Main execution logic - OVERRIDE THIS"""
        # Implement your module logic here
        return ModuleResult(status=ModuleStatus.COMPLETED, data=...)
    
    def on_ui_event(self, event: UIEvent) -> None:
        """Handle user interactions"""
        pass
    
    def save_state(self) -> Dict:
        """Save module state for persistence"""
        return super().save_state()
    
    def load_state(self, state: Dict) -> None:
        """Restore saved state"""
        super().load_state(state)
```

---

## ModuleContext Methods

### Data Access

```python
# Read from shared cache (fast)
data = context.get_cached_series(series_uid: str) -> Optional[Any]

# Query database
rows = context.execute_query(
    sql: str,
    params: Tuple = ()
) -> List[Tuple]

# Update database (thread-safe, WAL-safe)
context.execute_update(
    sql: str,
    params: Tuple = ()
) -> int  # rows affected

# Cache result (auto-evicts LRU if needed)
context.cache_result(
    key: str,
    data: Any,
    size_bytes: int
) -> None
```

### Module Control

```python
# Check if stop requested (call frequently in loops)
if self.should_stop() -> bool:
    return ModuleResult(status=ModuleStatus.TIMEOUT)

# Get execution context info
patient_uid = context.patient_uid
series_uid = context.series_uid
parameters = context.user_parameters
```

---

## ModuleManager API

### Core Operations

```python
# Register module
manager.register_module(module: BaseModule) -> None

# Invoke (non-blocking)
result = await manager.invoke_module(
    module_id: str,
    context: ModuleContext
) -> ModuleResult

# Control running modules
manager.pause_module(module_id: str) -> bool
manager.resume_module(module_id: str) -> bool
manager.stop_module(module_id: str) -> bool
```

### State Management

```python
# Save all modules' states to file
states = manager.save_all_states(
    storage_path: str
) -> Dict[str, Dict]

# Load all modules' states from file
manager.load_all_states(storage_path: str) -> None

# Cleanup on shutdown
manager.shutdown() -> None
```

### Monitoring

```python
# Get module status
status = manager.get_module_status(module_id: str) -> Optional[ModuleState]

# Get last result
result = manager.get_module_result(module_id: str) -> Optional[ModuleResult]

# Get metrics
metrics = manager.get_metrics() -> Dict[str, Any]
# Returns:
# {
#   'running': int,
#   'max_concurrent': int,
#   'queued': int,
#   'completed': int,
#   'failed': int,
#   'db_connections_available': int,
#   'db_connections_total': int,
#   'cache_memory_mb': float
# }
```

---

## Common Patterns

### Pattern 1: Simple Computation

```python
async def execute(self, context: ModuleContext) -> ModuleResult:
    try:
        # Do computation
        result = self._compute(context.series_uid)
        
        # Cache for fast re-access
        context.cache_result(
            f"result_{context.series_uid}",
            result,
            size_bytes=len(str(result))
        )
        
        return ModuleResult(
            status=ModuleStatus.COMPLETED,
            data=result
        )
    except Exception as e:
        return ModuleResult(
            status=ModuleStatus.ERROR,
            error=str(e)
        )
```

### Pattern 2: Long-Running with Progress

```python
async def execute(self, context: ModuleContext) -> ModuleResult:
    try:
        results = []
        
        for i in range(N_STEPS):
            # Check stop signal frequently
            if self.should_stop():
                return ModuleResult(status=ModuleStatus.TIMEOUT)
            
            # Do one step
            step_result = await self._process_step(i)
            results.append(step_result)
            
            # Update progress
            self.progress = int((i / N_STEPS) * 100)
            
            # Allow other threads to run
            await asyncio.sleep(0)
        
        return ModuleResult(
            status=ModuleStatus.COMPLETED,
            data=results
        )
    except Exception as e:
        return ModuleResult(
            status=ModuleStatus.ERROR,
            error=str(e)
        )
```

### Pattern 3: Database Operations

```python
async def execute(self, context: ModuleContext) -> ModuleResult:
    try:
        # Read from database
        rows = context.execute_query(
            "SELECT * FROM series WHERE patient_uid = ?",
            (context.patient_uid,)
        )
        
        # Process results
        data = self._process_rows(rows)
        
        # Write back to database
        context.execute_update(
            "INSERT INTO results (series_uid, data) VALUES (?, ?)",
            (context.series_uid, str(data))
        )
        
        return ModuleResult(
            status=ModuleStatus.COMPLETED,
            data=data
        )
    except Exception as e:
        return ModuleResult(
            status=ModuleStatus.ERROR,
            error=str(e)
        )
```

### Pattern 4: UI-Driven Operations

```python
async def execute(self, context: ModuleContext) -> ModuleResult:
    initial_data = self._load_initial()
    return ModuleResult(
        status=ModuleStatus.COMPLETED,
        data=initial_data
    )

def on_ui_event(self, event: UIEvent) -> None:
    if event.type == UIEventType.BUTTON_CLICK:
        if event.data.get('action') == 'zoom_in':
            self.zoom_level *= 1.2
        elif event.data.get('action') == 'zoom_out':
            self.zoom_level /= 1.2
```

---

## Error Handling

### Graceful Failure

```python
async def execute(self, context: ModuleContext) -> ModuleResult:
    try:
        # Attempt operation
        data = await self._risky_operation()
        return ModuleResult(status=ModuleStatus.COMPLETED, data=data)
    
    except TimeoutError:
        return ModuleResult(
            status=ModuleStatus.ERROR,
            error="Operation timed out"
        )
    
    except IOError as e:
        return ModuleResult(
            status=ModuleStatus.ERROR,
            error=f"Device error: {str(e)}"
        )
    
    except Exception as e:
        logger.exception("Unexpected error in module")
        return ModuleResult(
            status=ModuleStatus.ERROR,
            error=f"Unexpected error: {str(e)}"
        )
```

---

## Testing Module

```python
import asyncio
from PacsClient.components.module_manager import ModuleManager, ModuleContext

# Test module execution
async def test_my_module():
    # Create manager
    manager = ModuleManager(
        pipeline_orchestrator=mock_orchestrator,
        db_path=":memory:",  # In-memory DB for testing
        max_concurrent=5
    )
    
    # Register module
    my_module = MyModule("test_module")
    manager.register_module(my_module)
    
    # Create context
    context = ModuleContext(
        module_id="test_module",
        pipeline_orchestrator=mock_orchestrator,
        series_uid="1.2.3.4.5",
        patient_uid="patient_123"
    )
    
    # Invoke
    result = await manager.invoke_module("test_module", context)
    assert result.status == ModuleStatus.QUEUED
    
    # Wait for completion
    future = result.data
    final_result = future.result(timeout=30)
    
    assert final_result.status == ModuleStatus.COMPLETED
    print(f"Test passed: {final_result.data}")
    
    # Cleanup
    manager.shutdown()

# Run test
if __name__ == "__main__":
    asyncio.run(test_my_module())
```

---

## Configuration

### Environment Variables

```bash
# Maximum concurrent modules (default: 5)
set PACS_MODULE_MAX_CONCURRENT=8

# Database pool size (default: 5)
set PACS_MODULE_DB_POOL_SIZE=10

# Debug logging
set PACS_MODULE_DEBUG=1
```

### Initialization Parameters

```python
ModuleManager(
    pipeline_orchestrator=orchestrator,  # REQUIRED
    db_path="database/pacs.db",           # REQUIRED
    max_concurrent=5,                     # OPTIONAL (default: 5)
    db_pool_size=5,                       # OPTIONAL (default: 5)
    state_file="config/modules.json"      # OPTIONAL
)
```

---

## Performance Tips

| Tip | Benefit | Implementation |
|-----|---------|-----------------|
| Cache results | 10-100x faster re-access | context.cache_result() |
| Check should_stop() | Responsive pause/stop | if self.should_stop(): return |
| Use await asyncio.sleep(0) | Prevent thread starvation | In loops |
| Batch DB updates | 5-10x faster writes | Execute multiple SQLs together |
| Monitor max_concurrent | Prevent resource exhaustion | Keep ≤ 10 |

---

## Debugging

### Enable Logging

```python
import logging

# Set debug level
logging.getLogger('PacsClient.components.module_manager').setLevel(logging.DEBUG)

# See output like:
# DEBUG: Module 'mpr_0' queued
# DEBUG: Module 'mpr_0' started in thread worker-1
# DEBUG: Module 'mpr_0' completed with status COMPLETED
```

### Check Module State

```python
# During execution
status = manager.get_module_status("mpr_0")
if status:
    print(f"Module is {status.value} (progress: {module.progress}%)")

# After execution
result = manager.get_module_result("mpr_0")
if result and result.status == ModuleStatus.ERROR:
    print(f"Error: {result.error}")
```

### Monitor Resources

```python
metrics = manager.get_metrics()
print(f"Running: {metrics['running']}/{metrics['max_concurrent']}")
print(f"DB connections: {metrics['db_connections_available']}/{metrics['db_connections_total']}")
print(f"Cache: {metrics['cache_memory_mb']:.1f} MB")
```

---

## Quick Checklist for New Module

- [ ] Inherit from BaseModule
- [ ] Implement async execute()
- [ ] Add should_stop() checks in loops
- [ ] Handle exceptions gracefully
- [ ] Cache results when appropriate
- [ ] Implement save_state() if stateful
- [ ] Test in isolation with mock orchestrator
- [ ] Test with real orchestrator
- [ ] Test concurrent with other modules
- [ ] Verify no main thread blocking

---

## Common Mistakes & Fixes

| Mistake | Effect | Fix |
|---------|--------|-----|
| No should_stop() checks | Can't be paused/stopped | Add checks in loops |
| Blocking I/O | Freezes all modules | Use async/await |
| Huge cache_result() | Memory exhaustion | Pass accurate size_bytes |
| Same DB query twice | Slower execution | Cache results |
| No error handling | Crashes thread | Use try/except |
| Holding DB connection | Resource leak | Use context manager |

---

## API Version

**Module Manager API v1.0**  
**Python 3.9+**  
**PySide6 + asyncio compatible**
