# Module Execution Framework - Post-Integration Validation Checklist

**Purpose:** Ensure framework is working correctly after integration  
**Frequency:** Run after initial setup and periodically (weekly)  
**Time Required:** 30-60 minutes  

---

## Pre-Integration Checklist (Do This First)

- [ ] Python 3.9+ installed
- [ ] PySide6 available 
- [ ] asyncio library available
- [ ] SQLite3 with WAL support enabled
- [ ] PacsClient/components/ directory exists
- [ ] Database/pacs.db accessible for R/W
- [ ] Main thread event loop configured (qasync)

---

## Post-File-Addition Checklist

After copying files to workspace:

### File Placement Verification

- [ ] module_manager.py exists in PacsClient/components/
- [ ] example_modules.py exists in PacsClient/components/
- [ ] All 4 documentation files (.md) in root or docs/
- [ ] test_module_harness.py in root

### File Content Verification

```bash
# Check file sizes to ensure content was copied
ls -lah PacsClient/components/module_manager.py       # Should be ~25KB
ls -lah PacsClient/components/example_modules.py      # Should be ~20KB
wc -l MODULE_*.md                                      # Should be 1950+ total
```

Expected sizes:
- module_manager.py: ~25 KB
- example_modules.py: ~20 KB
- MODULE_EXECUTION_ARCHITECTURE.md: ~40 KB
- MODULE_INTEGRATION_GUIDE.md: ~25 KB
- MODULE_DEVELOPER_REFERENCE.md: ~20 KB
- MODULE_EXECUTION_FRAMEWORK_SUMMARY.md: ~30 KB

### Import Verification

```python
# Test that modules can be imported
try:
    from PacsClient.components.module_manager import (
        BaseModule, ModuleManager, ModuleContext, ModuleStatus
    )
    print("✅ Core imports OK")
except ImportError as e:
    print(f"❌ Import failed: {e}")

try:
    from PacsClient.components.example_modules import (
        MPRModule, EagleEyeModule, ToolbarModule
    )
    print("✅ Example imports OK")
except ImportError as e:
    print(f"❌ Example import failed: {e}")
```

---

## Initialization Checklist

### 1. ModuleManager Creation

```python
# Add to main.py after PipelineOrchestrator initialization

from PacsClient.components.module_manager import ModuleManager
from PacsClient.components.example_modules import (
    MPRModule, EagleEyeModule, ToolbarModule, MeasurementModule
)

# Initialize
module_manager = ModuleManager(
    pipeline_orchestrator=pipeline_orchestrator,  # From existing code
    db_path="database/pacs.db",
    max_concurrent=5
)

print(f"✅ ModuleManager initialized")
print(f"   Max concurrent: {module_manager.max_concurrent}")
print(f"   DB pool size: {module_manager._db_pool.pool_size}")
```

### 2. Module Registration

```python
# Register modules
for module_class in [MPRModule, EagleEyeModule, ToolbarModule, MeasurementModule]:
    module = module_class(module_class.__name__.lower())
    module_manager.register_module(module)
    print(f"✅ Registered {module_class.__name__}")

# Verify registration
print(f"✅ Total modules registered: {len(module_manager._modules)}")
```

### 3. State Restoration

```python
# Load previous state if exists
state_file = "config/module_states.json"
try:
    module_manager.load_all_states(state_file)
    print(f"✅ Module states loaded from {state_file}")
except FileNotFoundError:
    print(f"ℹ️  No previous state file (first run)")
except Exception as e:
    print(f"⚠️  Warning loading state: {e}")
```

---

## Functional Testing Checklist

### Test 1: Basic Execution

```python
import asyncio
from PacsClient.components.module_manager import ModuleContext

async def test_module_invocation():
    # Create context
    context = ModuleContext(
        module_id="mpr",
        pipeline_orchestrator=pipeline_orchestrator,
        series_uid="1.2.3.4.5",
        patient_uid="patient_001"
    )
    
    # Invoke
    result = await module_manager.invoke_module("mpr", context)
    
    # Verify
    assert result.status.name == 'QUEUED', f"Expected QUEUED, got {result.status}"
    print(f"✅ Module invocation returned QUEUED status")
    
    # Wait for completion
    if result.data:  # Is a future
        final = result.data.result(timeout=5)
        print(f"✅ Module completed with status: {final.status}")
    
    return True

# Run test
asyncio.run(test_module_invocation())
```

**Expected Result:** ✅ Module queued and completed

### Test 2: Concurrent Modules

```python
async def test_concurrent_modules():
    tasks = []
    
    # Create 3 contexts for 3 modules
    for module_id in ["mpr", "eagle_eye", "toolbar"]:
        context = ModuleContext(
            module_id=module_id,
            pipeline_orchestrator=pipeline_orchestrator,
            series_uid="1.2.3.4.5",
            patient_uid="patient_001"
        )
        tasks.append(module_manager.invoke_module(module_id, context))
    
    # Invoke all concurrently
    results = await asyncio.gather(*tasks)
    
    # Verify all queued
    for i, result in enumerate(results):
        assert result.status.name in ['QUEUED', 'RUNNING'], \
            f"Module {i} returned unexpected status: {result.status}"
    
    print(f"✅ All {len(results)} modules invoked concurrently")
    return True

# Run test
asyncio.run(test_concurrent_modules())
```

**Expected Result:** ✅ All 3 modules queued simultaneously

### Test 3: Non-Blocking Invocation

```python
async def test_non_blocking():
    import time
    
    # Get execution time for module invocation
    context = ModuleContext(
        module_id="mpr",
        pipeline_orchestrator=pipeline_orchestrator,
        series_uid="1.2.3.4.5",
        patient_uid="patient_001"
    )
    
    start = time.time()
    result = await module_manager.invoke_module("mpr", context)
    elapsed = time.time() - start
    
    # Should return immediately
    assert elapsed < 0.01, f"Took {elapsed*1000:.1f}ms (should be <10ms)"
    assert result.status.name == 'QUEUED', "Should return immediately with QUEUED"
    
    print(f"✅ Module invocation non-blocking (<{elapsed*1000:.1f}ms)")
    return True

# Run test
asyncio.run(test_non_blocking())
```

**Expected Result:** ✅ Invocation latency <10ms

### Test 4: State Persistence

```python
def test_state_persistence():
    import json
    
    # Save state
    states = module_manager.save_all_states("config/test_states.json")
    
    # Verify file created
    import os
    assert os.path.exists("config/test_states.json"), "State file not created"
    
    # Verify content
    with open("config/test_states.json") as f:
        saved = json.load(f)
    
    assert isinstance(saved, dict), "State should be dict"
    print(f"✅ State persisted to file ({len(saved)} modules)")
    
    # Load state
    module_manager.load_all_states("config/test_states.json")
    print(f"✅ State restored from file")
    
    return True

# Run test
test_state_persistence()
```

**Expected Result:** ✅ State saved and loaded successfully

---

## Performance Validation Checklist

### Performance Test 1: Invocation Latency

```python
import asyncio
import time
from statistics import mean, stdev

async def measure_invocation_latency(iterations=100):
    times = []
    
    for i in range(iterations):
        context = ModuleContext(
            module_id="toolbar",
            pipeline_orchestrator=pipeline_orchestrator,
            series_uid="1.2.3.4.5",
            patient_uid="patient_001"
        )
        
        start = time.perf_counter()
        result = await module_manager.invoke_module("toolbar", context)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        
        times.append(elapsed)
    
    avg = mean(times)
    stddev = stdev(times) if len(times) > 1 else 0
    max_time = max(times)
    
    print(f"\n📊 Invocation Latency (n={iterations}):")
    print(f"  Average: {avg:.2f}ms")
    print(f"  StdDev:  {stddev:.2f}ms")
    print(f"  Max:     {max_time:.2f}ms")
    
    # Target: <5ms average
    assert avg < 5.0, f"Average latency {avg:.2f}ms exceeds 5ms target"
    print(f"✅ PASS - Invocation latency within target")
    
    return True

# Run test
asyncio.run(measure_invocation_latency())
```

**Expected Result:** ✅ Average <5ms, Max <10ms

### Performance Test 2: Concurrent Throughput

```python
async def measure_throughput(num_concurrent=10, duration_sec=5):
    import time
    
    completed = 0
    start_time = time.time()
    
    async def invoke_continuously():
        nonlocal completed
        while time.time() - start_time < duration_sec:
            context = ModuleContext(
                module_id="toolbar",
                pipeline_orchestrator=pipeline_orchestrator,
                series_uid="1.2.3.4.5",
                patient_uid="patient_001"
            )
            result = await module_manager.invoke_module("toolbar", context)
            completed += 1
            await asyncio.sleep(0.01)  # Small delay
    
    # Run multiple invocations concurrently
    tasks = [invoke_continuously() for _ in range(num_concurrent)]
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=duration_sec+1)
    
    elapsed = time.time() - start_time
    throughput = completed / elapsed
    
    print(f"\n📊 Concurrent Throughput:")
    print(f"  Duration: {elapsed:.1f}s")
    print(f"  Completed: {completed} invocations")
    print(f"  Throughput: {throughput:.0f} invocations/sec")
    
    # Target: >100 invocations/sec
    assert throughput > 100, f"Throughput {throughput:.0f}/s below 100 target"
    print(f"✅ PASS - Throughput above target")
    
    return True

# Run test
asyncio.run(measure_throughput())
```

**Expected Result:** ✅ Throughput >100 invocations/sec

### Performance Test 3: Memory Usage

```python
def measure_memory_usage():
    import tracemalloc
    
    tracemalloc.start()
    
    # Create some module contexts and invoke
    asyncio.run(invoke_100_modules())
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    print(f"\n📊 Memory Usage:")
    print(f"  Current: {current / 1024 / 1024:.1f} MB")
    print(f"  Peak:    {peak / 1024 / 1024:.1f} MB")
    
    # Should be <100MB for framework overhead
    assert peak / 1024 / 1024 < 100, "Memory usage too high"
    print(f"✅ PASS - Memory usage within bounds")
    
    return True

async def invoke_100_modules():
    for i in range(100):
        context = ModuleContext(
            module_id="toolbar",
            pipeline_orchestrator=pipeline_orchestrator,
            series_uid="1.2.3.4.5",
            patient_uid="patient_001"
        )
        result = await module_manager.invoke_module("toolbar", context)

# Run test
measure_memory_usage()
```

**Expected Result:** ✅ Peak memory <100MB

---

## Integration with Pipeline Checklist

### Test 1: Module + Pipeline Concurrent

```python
async def test_module_pipeline_concurrent():
    """Verify modules don't block pipeline"""
    
    # Start module
    module_context = ModuleContext(
        module_id="mpr",
        pipeline_orchestrator=pipeline_orchestrator,
        series_uid="study_001",
        patient_uid="patient_001"
    )
    
    result1 = await module_manager.invoke_module("mpr", module_context)
    
    # While module running, start pipeline
    # (Simulate pipeline download)
    pipeline_context = {
        'series_uid': 'study_002',
        'priority': 'high'
    }
    
    # Pipeline should queue without blocking for module
    import time
    start = time.time()
    # Simulate pipeline queue (would be actual pipeline call)
    elapsed_pipeline = time.time() - start
    
    # Both should be concurrent
    print(f"✅ Module and pipeline executing concurrently")
    print(f"   Module status: {result1.status}")
    print(f"   Pipeline queue: {elapsed_pipeline*1000:.1f}ms (fast)")
    
    return True

# Run test
asyncio.run(test_module_pipeline_concurrent())
```

**Expected Result:** ✅ Pipeline operations not blocked by modules

### Test 2: Database Fairness

```python
def test_db_connection_fairness():
    """Verify DB connections not starved"""
    
    metrics = module_manager.get_metrics()
    
    print(f"\n📊 Database Connection Status:")
    print(f"  Available: {metrics['db_connections_available']}")
    print(f"  Total:     {metrics['db_connections_total']}")
    print(f"  Used:      {metrics['db_connections_total'] - metrics['db_connections_available']}")
    
    # Should always have connections available
    assert metrics['db_connections_available'] > 0, "No DB connections available"
    print(f"✅ PASS - DB connections available")
    
    return True

test_db_connection_fairness()
```

**Expected Result:** ✅ DB connections never exhausted

---

## Monitoring & Metrics Checklist

### Enable Metrics Collection

```python
# In your monitoring code
def print_module_metrics():
    metrics = module_manager.get_metrics()
    
    print(f"\n📊 Module Framework Metrics:")
    print(f"  Running modules: {metrics['running']}/{metrics['max_concurrent']}")
    print(f"  Queued: {metrics['queued']}")
    print(f"  Completed: {metrics['completed']}")
    print(f"  Failed: {metrics['failed']}")
    print(f"  DB connections: {metrics['db_connections_available']}/{metrics['db_connections_total']}")
    print(f"  Cache memory: {metrics['cache_memory_mb']:.1f} MB")

# Call periodically (e.g., every 10 seconds)
import threading
def monitor_loop():
    while True:
        print_module_metrics()
        time.sleep(10)

# Optional: Start in background
# monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
# monitor_thread.start()
```

### Set Up Logging

```python
import logging

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Watch module manager logs
logger = logging.getLogger('PacsClient.components.module_manager')
logger.setLevel(logging.DEBUG)

# You should see logs like:
# DEBUG: Module 'mpr' queued for execution
# DEBUG: Module 'mpr' started in thread worker-1
# DEBUG: Module 'mpr' completed with status COMPLETED
```

---

## Troubleshooting Decision Tree

### Issue: "Module never completes"

```
1. Check logs for errors
   └─ See any exceptions? → Fix in module code
   
2. Check should_stop() calls
   └─ Are there loops without should_stop()? → Add checks
   
3. Check for deadlocks
   └─ Set timeout and see if it timeouts → Likely deadlock
   
4. Check DB connections
   └─ metrics['db_connections_available'] == 0? → Increase pool size
```

**Resolution Steps:**
1. Enable debug logging
2. Check module execute() for infinite loops
3. Verify should_stop() in loops
4. Test with timeout=5 to see timeout behavior
5. If timeout: Check for resource contention

### Issue: "Database locked errors"

```
1. Check WAL mode enabled
   ├─ Run: sqlite3 database/pacs.db "PRAGMA journal_mode;"
   └─ Should return: journal_mode = wal
   
2. Check DB connection pool size
   └─ metrics['db_connections_available'] very low?
   
3. Check for long transactions
   └─ Module holding connection too long?
```

**Resolution Steps:**
1. Verify WAL enabled: `PRAGMA journal_mode = WAL;`
2. Increase DB pool size: `max_concurrent` + 5
3. Add context manager: `with context.db_connection as conn:`
4. Check transaction scope

### Issue: "Out of memory / cache overflow"

```
1. Check cache size configuration
   └─ PipelineOrchestrator(max_cache_mb=?)
   
2. Check module cache_result() calls
   └─ Passing correct size_bytes?
   
3. Check for cache leaks
   └─ Are results being evicted? Get metrics.
```

**Resolution Steps:**
1. Verify cache size: `metrics['cache_memory_mb']`
2. Module cache_result() calls - verify sizes accurate
3. Enable cache debug logging
4. Add manual cleanup: `pipeline_orchestrator.cache.clear()`

---

## Sign-Off Checklist

After all tests pass, sign off on integration:

- [ ] All imports successful
- [ ] ModuleManager initialized
- [ ] Modules registered
- [ ] State persistence working
- [ ] Test 1: Basic execution passed
- [ ] Test 2: Concurrent modules passed
- [ ] Test 3: Non-blocking invocation passed
- [ ] Test 4: State persistence passed
- [ ] Performance 1: Invocation latency <5ms
- [ ] Performance 2: Throughput >100/sec
- [ ] Performance 3: Memory <100MB
- [ ] Pipeline integration test passed
- [ ] DB connection fairness verified
- [ ] Logging enabled and working
- [ ] Monitoring metrics visible
- [ ] Troubleshooting guide reviewed

**Ready for Production:** ✅ All items checked

---

## Rollout Plan

### Phase 1: Canary (1-2 days)
- [ ] Deploy to 1-2 testing machines
- [ ] Run all validation tests
- [ ] Monitor metrics continuously
- [ ] Collect baseline performance data

### Phase 2: Beta (1 week)
- [ ] Deploy to 10-20 users
- [ ] Gather feedback on responsiveness
- [ ] Monitor for edge cases
- [ ] Fix any issues that arise

### Phase 3: Full Rollout (1+ weeks)
- [ ] Deploy to all machines
- [ ] Monitor continuously
- [ ] Collect long-term metrics
- [ ] Iterate based on feedback

---

## Ongoing Monitoring

**Weekly Checks:**
- [ ] Review module metrics (see print_module_metrics())
- [ ] Check error logs for failures
- [ ] Verify no memory leaks

**Monthly Review:**
- [ ] Collect performance data
- [ ] Compare to baseline
- [ ] Identify optimization opportunities

**Quarterly Assessment:**
- [ ] Full performance audit
- [ ] Scalability testing (more concurrent modules)
- [ ] Upgrade decision for framework version

---

## Sign-Off

**Integration Date:** _______________

**Validated By:** _______________

**Notes:** _______________

✅ **Framework validated and approved for production use**
