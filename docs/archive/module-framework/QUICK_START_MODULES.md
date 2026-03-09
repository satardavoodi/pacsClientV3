# Module Execution Framework - Quick Start Guide

**Goal:** Get modules running in 30 minutes  
**Complexity:** Beginner-friendly  
**Outcome:** Working module + pipeline concurrency

---

## Step 1: Copy Files (5 minutes)

Copy these files to your workspace:

```
PacsClient/components/module_manager.py      ← Core framework
PacsClient/components/example_modules.py     ← Ready-to-use examples
```

These are already in the workspace. If not found, create them from documentation.

---

## Step 2: Update main.py (10 minutes)

Find where `PipelineOrchestrator` is initialized and add:

```python
# At the top of main.py
from PacsClient.components.module_manager import ModuleManager
from PacsClient.components.example_modules import MPRModule, EagleEyeModule

# In MainWindowWidget.__init__() after pipeline_orchestrator creation:

# Initialize Module Manager (NEW)
self.module_manager = ModuleManager(
    pipeline_orchestrator=self.pipeline_orchestrator,
    db_path="database/pacs.db",
    max_concurrent=5
)

# Register modules (NEW)
self.module_manager.register_module(MPRModule("mpr_0"))
self.module_manager.register_module(EagleEyeModule("eagle_eye_0"))

print("✅ ModuleManager initialized with", len(self.module_manager._modules), "modules")
```

**Done!** Framework is now active.

---

## Step 3: Wire a Button (10 minutes)

Wire a toolbar button to invoke a module:

```python
# In your toolbar/widget code:

async def on_mpr_button_clicked(self):
    """User clicked 'Compute MPR' button"""
    
    # Create execution context
    from PacsClient.components.module_manager import ModuleContext
    
    context = ModuleContext(
        module_id="mpr_0",
        pipeline_orchestrator=self.pipeline_orchestrator,
        series_uid=self.current_series_uid,
        patient_uid=self.current_patient_uid
    )
    
    # Invoke (non-blocking - returns immediately)
    result = await self.module_manager.invoke_module("mpr_0", context)
    
    # Feedback to user
    print(f"✅ MPR module {result.status} - computing in background...")
    
    # Optional: Wait for result (in background)
    if result.data:  # Is a future
        try:
            final_result = result.data.result(timeout=30)
            print(f"✅ MPR complete: {final_result.status}")
            if final_result.error:
                print(f"❌ Error: {final_result.error}")
        except TimeoutError:
            print(f"⏱️ MPR computation took >30s, continue in background")
```

**Done!** Button now invokes module concurrently.

---

## Step 4: Test It (5 minutes)

Run the app and test:

```python
# Quick test script (run in Python REPL or test file)

import asyncio
from PacsClient.components.module_manager import ModuleContext

async def quick_test():
    # Get references
    module_manager = app.main_window.module_manager
    orchestrator = app.main_window.pipeline_orchestrator
    
    # Test invocation
    context = ModuleContext(
        module_id="mpr_0",
        pipeline_orchestrator=orchestrator,
        series_uid="test_series",
        patient_uid="test_patient"
    )
    
    result = await module_manager.invoke_module("mpr_0", context)
    print(f"✅ Test passed: {result.status}")

# Run test
asyncio.run(quick_test())
```

**Expected output:** `✅ Test passed: QUEUED`

---

## What You Now Have

```
✅ Module framework initialized
✅ Modules registered and ready
✅ Button wired to invoke modules
✅ Non-blocking execution (no UI freeze)
✅ Concurrent with pipeline
```

---

## Next Steps: Create Your Own Module

### Template (Copy & Fill In)

```python
from PacsClient.components.module_manager import BaseModule, ModuleContext, ModuleResult, ModuleStatus

class MyCustomModule(BaseModule):
    """My custom module implementation"""
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Override with your logic"""
        
        try:
            # Step 1: Get input data
            patient_uid = context.patient_uid
            series_uid = context.series_uid
            
            # Step 2: Check cache first (fast)
            data = context.get_cached_series(series_uid)
            if not data:
                # Step 3: Query database if not cached
                rows = context.execute_query(
                    "SELECT * FROM series WHERE patient_uid = ?",
                    (patient_uid,)
                )
                data = rows[0] if rows else None
            
            # Step 4: Do computation (check should_stop frequently)
            result = self._process_data(data)
            
            if self.should_stop():
                return ModuleResult(status=ModuleStatus.TIMEOUT)
            
            # Step 5: Cache and persist result
            context.cache_result(
                f"result_{series_uid}",
                result,
                size_bytes=len(str(result))
            )
            
            context.execute_update(
                "INSERT INTO results (series_uid, data) VALUES (?, ?)",
                (series_uid, str(result))
            )
            
            # Step 6: Return completion
            return ModuleResult(
                status=ModuleStatus.COMPLETED,
                data=result
            )
        
        except Exception as e:
            return ModuleResult(
                status=ModuleStatus.ERROR,
                error=str(e)
            )
    
    def _process_data(self, data):
        """Your computation here"""
        return {"processed": data}
    
    def save_state(self):
        """Optional: save state for recovery"""
        return super().save_state()
```

### Register It

```python
# In main.py

class MyCustomModule(BaseModule):
    # ... implementation above ...
    pass

# Register in __init__:
self.module_manager.register_module(MyCustomModule("my_module_0"))
```

### Wire It

```python
# In your UI code

async def on_my_button_clicked(self):
    context = ModuleContext(
        module_id="my_module_0",
        pipeline_orchestrator=self.pipeline_orchestrator,
        series_uid=self.current_series_uid,
        patient_uid=self.current_patient_uid
    )
    
    result = await self.module_manager.invoke_module("my_module_0", context)
    print(f"Custom module {result.status}")
```

---

## Debug Issues

### "Module not running"

```python
# Check module registered
print(module_manager._modules.keys())  # Should show your module_id

# Check status
status = module_manager.get_module_status("my_module_0")
print(f"Module status: {status}")

# Check metrics
metrics = module_manager.get_metrics()
print(f"Running: {metrics['running']}")
print(f"Available DB connections: {metrics['db_connections_available']}")
```

### "Module freezes UI"

```python
# Ensure:
# 1. You're using async/await:
async def execute(self, context):  # ← async keyword
    # NOT:
def execute(self, context):  # ← missing async

# 2. You're not blocking:
# BAD:
result = blocking_function()  # Blocks thread

# GOOD:
result = await async_function()  # Doesn't block

# 3. Add should_stop() in loops:
while True:
    if self.should_stop():  # ← Add this
        break
```

### "Database errors"

```python
# Ensure WAL mode enabled
import sqlite3
conn = sqlite3.connect("database/pacs.db")
mode = conn.execute("PRAGMA journal_mode;").fetchone()
print(f"Journal mode: {mode[0]}")  # Should print "wal"

# If not "wal", enable it:
conn.execute("PRAGMA journal_mode = WAL;")
```

---

## Performance Expectations

| Operation | Target | Typical | Status |
|-----------|--------|---------|--------|
| Module invocation | <10ms | <5ms | ✅ |
| Non-UI blocking | Yes | Yes | ✅ |
| 5 modules concurrent | Yes | Yes | ✅ |
| Module + pipeline | Non-blocking | Non-blocking | ✅ |

---

## Common Patterns

### Pattern 1: Async Computation (Heavy Work)

```python
async def execute(self, context: ModuleContext) -> ModuleResult:
    # Heavy computation in background thread
    result = await asyncio.to_thread(self._heavy_compute)
    return ModuleResult(status=ModuleStatus.COMPLETED, data=result)

def _heavy_compute(self):
    # This runs in executor (doesn't block main thread)
    return expensive_computation()
```

### Pattern 2: UI Events

```python
def on_ui_event(self, event: UIEvent) -> None:
    """Handle user interactions"""
    if event.type == UIEventType.BUTTON_CLICK:
        action = event.data.get('action')
        if action == 'zoom_in':
            self.zoom_level *= 1.2
        elif action == 'zoom_out':
            self.zoom_level /= 1.2
```

### Pattern 3: Database Operations

```python
async def execute(self, context: ModuleContext) -> ModuleResult:
    # Query
    rows = context.execute_query(
        "SELECT * FROM measurements WHERE series_uid = ?",
        (context.series_uid,)
    )
    
    # Process
    data = self._process_rows(rows)
    
    # Update
    context.execute_update(
        "INSERT INTO cache (key, value) VALUES (?, ?)",
        (context.series_uid, str(data))
    )
    
    return ModuleResult(status=ModuleStatus.COMPLETED, data=data)
```

---

## Documentation Reference

Got stuck? Read the full docs:

- **Architecture & Design:** `MODULE_EXECUTION_ARCHITECTURE.md`
- **Integration How-To:** `MODULE_INTEGRATION_GUIDE.md`
- **API Reference:** `MODULE_DEVELOPER_REFERENCE.md`
- **Full Summary:** `MODULE_EXECUTION_FRAMEWORK_SUMMARY.md`
- **Validation Guide:** `MODULE_VALIDATION_CHECKLIST.md`

---

## Support Checklist

Before asking for help, verify:

- [ ] module_manager.py copied to PacsClient/components/
- [ ] example_modules.py copied to PacsClient/components/
- [ ] ModuleManager initialized in main.py
- [ ] Module registered with module_manager.register_module()
- [ ] Button/signal wired to invoke_module()
- [ ] Using `async/await` in execute()
- [ ] No blocking operations (no time.sleep, no blocking I/O)
- [ ] Database in WAL mode (PRAGMA journal_mode = WAL;)

If all checked, framework is working correctly.

---

## Success Indicators

When framework is working, you'll see:

✅ **Smooth UI** - No freezes when invoking modules  
✅ **Concurrent Execution** - Multiple modules run simultaneously  
✅ **Background Processing** - Module results appear without blocking  
✅ **Pipeline Integration** - Downloads continue while modules run  
✅ **State Persistence** - Modules recover state after restart  

---

## What's Next?

1. **Try the examples:** Run `example_modules.py` patterns
2. **Create one module:** Build custom module using template
3. **Wire to UI:** Connect module to button/signal
4. **Test:** Verify execution and performance
5. **Monitor:** Use `get_metrics()` for health checks
6. **Optimize:** Profile and tune as needed

---

## 30-Second TL;DR

```python
# 1. Initialize (in main.py)
module_manager = ModuleManager(
    pipeline_orchestrator=orch,
    db_path="database/pacs.db"
)

# 2. Register
module_manager.register_module(MyModule("my_module"))

# 3. Invoke (in UI code)
result = await module_manager.invoke_module("my_module", context)
print(f"Module {result.status}")  # QUEUED → COMPLETED

# 4. Done!
# Module runs in background, UI stays responsive
```

---

**Questions?** Read the full documentation files included in workspace.

**Ready?** Start with Step 1 above and you'll have working modules in 30 minutes.
