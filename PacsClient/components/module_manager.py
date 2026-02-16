"""
Module Execution Framework

Enables smooth, concurrent module/widget execution alongside pipeline operations.
Handles database access, resource management, and state persistence.
"""

import threading
import queue
import sqlite3
import json
import os
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA MODELS
# ============================================================================

class ModuleState(Enum):
    """Module lifecycle states"""
    IDLE = "idle"              # Not running
    QUEUED = "queued"          # Waiting for execution
    RUNNING = "running"        # Currently executing
    PAUSED = "paused"          # Suspended (can resume)
    COMPLETED = "completed"    # Finished successfully
    ERROR = "error"            # Failed with error
    DISPOSED = "disposed"      # Cleaned up, no resume


class ModuleStatus(Enum):
    """Execution result status"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"


class UIEventType(Enum):
    """Types of UI events modules can receive"""
    USER_INPUT = "user_input"
    PARAMETER_CHANGE = "parameter_change"
    PAUSE_REQUEST = "pause_request"
    RESUME_REQUEST = "resume_request"
    CANCEL_REQUEST = "cancel_request"


@dataclass
class UIEvent:
    """Event from UI to module"""
    event_type: UIEventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class ModuleResult:
    """Result from module execution"""
    status: ModuleStatus
    data: Any = None
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ModuleContext:
    """Shared context passed to modules"""
    module_id: str
    pipeline_orchestrator: Any  # PipelineOrchestrator reference
    db_connection: Optional[sqlite3.Connection] = None
    patient_uid: Optional[str] = None
    series_uid: Optional[str] = None
    user_parameters: Dict[str, Any] = field(default_factory=dict)
    
    def get_cached_series(self, series_uid: str) -> Optional[Any]:
        """Get series from shared cache (fast path)"""
        if not self.pipeline_orchestrator:
            return None
        return self.pipeline_orchestrator.cache.get(series_uid)
    
    def cache_result(self, key: str, data: Any, size_bytes: int) -> None:
        """Store result in shared cache"""
        if self.pipeline_orchestrator:
            self.pipeline_orchestrator.cache.add(key, data, size_bytes)
    
    def execute_query(self, query: str, params: tuple = ()) -> List[tuple]:
        """Execute SELECT query (read-only)"""
        if not self.db_connection:
            return []
        cursor = self.db_connection.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
    
    def execute_update(self, query: str, params: tuple = ()) -> None:
        """Execute INSERT/UPDATE/DELETE query"""
        if not self.db_connection:
            return
        cursor = self.db_connection.cursor()
        cursor.execute(query, params)
        self.db_connection.commit()


# ============================================================================
# DATABASE CONNECTION POOL
# ============================================================================

class ConnectionPool:
    """
    Thread-safe pool of database connections for modules.
    Separate from main pipeline DB pool to avoid contention.
    """
    
    def __init__(self, db_path: str, max_size: int = 5, timeout: float = 30.0):
        self.db_path = db_path
        self.max_size = max_size
        self.timeout = timeout
        self.pool = queue.Queue(maxsize=max_size)
        self._all_connections: List[sqlite3.Connection] = []
        self._closed = False
        
        # Create connections
        for _ in range(max_size):
            try:
                conn = sqlite3.connect(db_path, timeout=timeout, check_same_thread=False)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.isolation_level = "DEFERRED"  # Non-blocking
                self._all_connections.append(conn)
                self.pool.put(conn)
            except Exception as e:
                logger.error(f"Failed to create DB connection: {e}")
        
        logger.info(f"✅ ConnectionPool initialized ({max_size} connections, WAL mode)")
    
    @contextmanager
    def acquire(self, timeout: Optional[float] = None):
        """Acquire a connection from the pool"""
        if timeout is None:
            timeout = self.timeout

        if self._closed:
            raise RuntimeError("Connection pool is closed")
        
        try:
            conn = self.pool.get(timeout=timeout)
            try:
                yield conn
            finally:
                if not self._closed:
                    self.pool.put(conn)
        except queue.Empty:
            logger.warning(f"⚠️  Connection pool exhausted (timeout: {timeout}s)")
            raise RuntimeError("No database connections available")
    
    def available_count(self) -> int:
        """Get number of available connections"""
        return self.pool.qsize()
    
    def close_all(self) -> None:
        """Close all connections (shutdown)"""
        self._closed = True
        for conn in self._all_connections:
            try:
                conn.close()
            except Exception:
                pass

        while not self.pool.empty():
            try:
                self.pool.get_nowait()
            except queue.Empty:
                break

        logger.info("✅ ConnectionPool closed")


# ============================================================================
# MODULE BASE CLASS (ABSTRACT)
# ============================================================================

class BaseModule(ABC):
    """
    Abstract base class for all modules.
    
    All modules (MPR, Eagle Eye, Ecomind, toolbars, etc.) inherit from this
    and implement required methods.
    """
    
    def __init__(self, module_id: str, display_name: str = ""):
        self.module_id = module_id
        self.display_name = display_name or module_id
        self.state = ModuleState.IDLE
        self._stop_event = threading.Event()
        self._last_result = None
        
        logger.info(f"📝 Module initialized: {module_id}")
    
    @abstractmethod
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """
        Main execution method (runs in thread pool).
        
        Must be async-compatible. Call self.should_stop() periodically
        to check for cancellation.
        """
        pass
    
    def on_ui_event(self, event: UIEvent) -> None:
        """
        Handle UI events (optional, override if needed).
        
        Called from main thread for user interactions.
        """
        if event.event_type == UIEventType.PAUSE_REQUEST:
            self.request_stop()
        elif event.event_type == UIEventType.CANCEL_REQUEST:
            self.request_stop()
    
    def save_state(self) -> Dict[str, Any]:
        """
        Serialize module state for persistence.
        Override to save state between sessions.
        """
        return {
            'module_id': self.module_id,
            'state': self.state.value,
            'timestamp': time.time()
        }
    
    def load_state(self, state: Dict[str, Any]) -> None:
        """Load serialized module state (optional)"""
        pass
    
    def request_stop(self) -> None:
        """Signal gradual shutdown (called from UI thread)"""
        self._stop_event.set()
        logger.debug(f"⏹️  Stop requested for module: {self.module_id}")
    
    def should_stop(self) -> bool:
        """Check if stop was requested (call from execute())"""
        return self._stop_event.is_set()
    
    def clear_stop(self) -> None:
        """Clear stop flag (for resume)"""
        self._stop_event.clear()


# ============================================================================
# MODULE MANAGER (ORCHESTRATOR)
# ============================================================================

class ModuleManager:
    """
    Orchestrates concurrent execution of modules alongside pipelines.
    
    Manages:
    - Module registration and lifecycle
    - Thread pool execution
    - Database connection pooling
    - Resource access and sharing
    - State persistence
    """
    
    def __init__(self, 
                 pipeline_orchestrator: Any,
                 db_path: str,
                 max_concurrent: int = 5):
        """
        Args:
            pipeline_orchestrator: Reference to PipelineOrchestrator (for cache, state)
            db_path: Path to SQLite database
            max_concurrent: Maximum concurrent module executions
        """
        self.orchestrator = pipeline_orchestrator
        self.db_path = db_path
        self.max_concurrent = max_concurrent
        
        self._modules: Dict[str, BaseModule] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent,
            thread_name_prefix="module_executor_"
        )
        self._db_pool = ConnectionPool(db_path, max_size=5)
        
        logger.info(f"✅ ModuleManager initialized (max {max_concurrent} concurrent)")
    
    def register_module(self, module: BaseModule) -> bool:
        """Register a module for management"""
        with self._lock:
            if module.module_id in self._modules:
                logger.warning(f"⚠️  Module already registered: {module.module_id}")
                return False
            
            self._modules[module.module_id] = module
            logger.info(f"📝 Registered module: {module.module_id}")
            return True
    
    def unregister_module(self, module_id: str) -> bool:
        """Unregister a module"""
        with self._lock:
            if module_id not in self._modules:
                return False
            
            # Gracefully stop if running
            module = self._modules[module_id]
            if module.state == ModuleState.RUNNING:
                logger.info(f"⏹️  Stopping module before unregister: {module_id}")
                module.request_stop()
            
            del self._modules[module_id]
            logger.info(f"❌ Unregistered module: {module_id}")
            return True
    
    async def invoke_module(self, module_id: str, context: ModuleContext) -> ModuleResult:
        """
        Invoke a module for execution.
        
        Returns immediately with status QUEUED.
        Check status periodically or await result.
        """
        with self._lock:
            if module_id not in self._modules:
                error = f"Module not registered: {module_id}"
                logger.error(f"❌ {error}")
                return ModuleResult(status=ModuleStatus.ERROR, error=error)
            
            module = self._modules[module_id]
            module.state = ModuleState.QUEUED
        
        # Check concurrent limit
        active_count = sum(
            1 for m in self._modules.values()
            if m.state == ModuleState.RUNNING
        )
        
        if active_count >= self.max_concurrent:
            logger.warning(
                f"⏸️  Module queue full ({active_count}/{self.max_concurrent}), "
                f"module {module_id} will wait"
            )
        
        # Spawn in thread pool (non-blocking)
        future = self._executor.submit(
            self._run_module_impl,
            module_id,
            context
        )
        
        logger.info(f"🚀 Invoked module: {module_id}")
        
        return ModuleResult(status=ModuleStatus.QUEUED, data=future)
    
    def _run_module_impl(self, module_id: str, context: ModuleContext) -> ModuleResult:
        """
        Internal: Execute module in thread pool.
        
        This method runs in a worker thread, not on main thread.
        """
        with self._lock:
            if module_id not in self._modules:
                return ModuleResult(
                    status=ModuleStatus.ERROR,
                    error=f"Module disappeared: {module_id}"
                )
            module = self._modules[module_id]

            # Respect terminal state set by stop/unregister before execution starts
            if module.state == ModuleState.DISPOSED:
                return ModuleResult(
                    status=ModuleStatus.TIMEOUT,
                    error="Module disposed before execution"
                )

            module.state = ModuleState.RUNNING
        
        try:
            # Get DB connection from pool
            with self._db_pool.acquire() as db_conn:
                context.db_connection = db_conn
                context.pipeline_orchestrator = self.orchestrator
                
                # Run module async/await
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(module.execute(context))
                loop.close()

                with self._lock:
                    # Never override explicit terminal states from control path
                    if module.state not in (ModuleState.DISPOSED, ModuleState.PAUSED):
                        if result.status == ModuleStatus.COMPLETED:
                            module.state = ModuleState.COMPLETED
                        elif result.status == ModuleStatus.TIMEOUT:
                            module.state = ModuleState.PAUSED if module.should_stop() else ModuleState.ERROR
                        else:
                            module.state = ModuleState.ERROR

                    module._last_result = result

                if result.status == ModuleStatus.COMPLETED:
                    logger.info(f"✅ Module completed: {module_id}")
                else:
                    logger.warning(f"⚠️  Module returned status: {result.status}")
                
                return result
        
        except Exception as e:
            error_msg = str(e)
            with self._lock:
                if module.state not in (ModuleState.DISPOSED, ModuleState.PAUSED):
                    module.state = ModuleState.ERROR
            logger.error(f"❌ Module error: {module_id} - {error_msg}")
            return ModuleResult(
                status=ModuleStatus.ERROR,
                error=error_msg
            )
    
    def pause_module(self, module_id: str) -> bool:
        """Gracefully pause a running module"""
        with self._lock:
            if module_id not in self._modules:
                return False
            
            module = self._modules[module_id]
            if module.state != ModuleState.RUNNING:
                logger.warning(f"⚠️  Cannot pause non-running module: {module_id}")
                return False
            
            module.request_stop()
            module.state = ModuleState.PAUSED
            logger.info(f"⏸️  Paused module: {module_id}")
            return True
    
    def resume_module(self, module_id: str, context: ModuleContext) -> bool:
        """Resume a paused module"""
        with self._lock:
            if module_id not in self._modules:
                return False
            
            module = self._modules[module_id]
            if module.state != ModuleState.PAUSED:
                logger.warning(f"⚠️  Cannot resume non-paused module: {module_id}")
                return False
            
            module.clear_stop()
            module.state = ModuleState.IDLE

        # Re-invoke safely from current context
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.invoke_module(module_id, context))
        except RuntimeError:
            threading.Thread(
                target=lambda: asyncio.run(self.invoke_module(module_id, context)),
                daemon=True,
                name=f"module_resume_{module_id}"
            ).start()

        logger.info(f"▶️  Resumed module: {module_id}")
        return True
    
    def stop_module(self, module_id: str) -> bool:
        """Forcefully stop a module"""
        with self._lock:
            if module_id not in self._modules:
                return False
            
            module = self._modules[module_id]
            module.request_stop()
            module.state = ModuleState.DISPOSED
            logger.info(f"🛑 Stopped module: {module_id}")
            return True
    
    def get_module_status(self, module_id: str) -> Optional[ModuleState]:
        """Get current state of a module"""
        with self._lock:
            if module_id not in self._modules:
                return None
            return self._modules[module_id].state
    
    def get_module_result(self, module_id: str) -> Optional[ModuleResult]:
        """Get last result from a module"""
        with self._lock:
            if module_id not in self._modules:
                return None
            return self._modules[module_id]._last_result
    
    def save_all_states(self, storage_path: str) -> Dict[str, Dict]:
        """Persist all module states to disk"""
        states = {}
        
        with self._lock:
            for module_id, module in self._modules.items():
                try:
                    states[module_id] = module.save_state()
                except Exception as e:
                    logger.error(f"❌ Failed to save state for {module_id}: {e}")
        
        # Write to JSON
        try:
            with open(storage_path, 'w') as f:
                json.dump(states, f, indent=2)
            
            logger.info(f"💾 Saved {len(states)} module states to {storage_path}")
            return states
        
        except Exception as e:
            logger.error(f"❌ Failed to write state file: {e}")
            return states
    
    def load_all_states(self, storage_path: str) -> bool:
        """Restore all module states from disk"""
        if not os.path.exists(storage_path):
            logger.warning(f"⚠️  State file not found: {storage_path}")
            return False
        
        try:
            with open(storage_path, 'r') as f:
                states = json.load(f)
            
            with self._lock:
                for module_id, state_data in states.items():
                    if module_id in self._modules:
                        self._modules[module_id].load_state(state_data)
            
            logger.info(f"📖 Loaded {len(states)} module states from {storage_path}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to load states: {e}")
            return False
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        with self._lock:
            total = len(self._modules)
            running = sum(1 for m in self._modules.values() if m.state == ModuleState.RUNNING)
            idle = sum(1 for m in self._modules.values() if m.state == ModuleState.IDLE)
            paused = sum(1 for m in self._modules.values() if m.state == ModuleState.PAUSED)
        
        return {
            'total_modules': total,
            'running': running,
            'idle': idle,
            'paused': paused,
            'max_concurrent': self.max_concurrent,
            'db_connections_available': self._db_pool.available_count(),
            'db_connections_max': self._db_pool.max_size
        }
    
    def shutdown(self) -> None:
        """Gracefully shutdown all modules and resources"""
        logger.info("🛑 Shutting down ModuleManager...")
        
        # Stop all running modules
        with self._lock:
            for module in self._modules.values():
                if module.state == ModuleState.RUNNING:
                    module.request_stop()
        
        # Close executor
        self._executor.shutdown(wait=True)
        
        # Close DB pool
        self._db_pool.close_all()
        
        logger.info("✅ ModuleManager shutdown complete")


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Mock pipeline orchestrator
    class MockOrchestrator:
        def __init__(self):
            self.cache = type('obj', (object,), {
                'get': lambda x: None,
                'add': lambda k, d, s: None
            })()
    
    # Create manager
    mock_orchestrator = MockOrchestrator()
    manager = ModuleManager(mock_orchestrator, ":memory:", max_concurrent=3)
    
    # Create a simple test module
    class TestModule(BaseModule):
        async def execute(self, context: ModuleContext) -> ModuleResult:
            logger.info(f"  Executing test module...")
            await asyncio.sleep(0.5)  # Simulate work
            
            if self.should_stop():
                logger.info(f"  Module stop requested")
                return ModuleResult(status=ModuleStatus.TIMEOUT)
            
            return ModuleResult(status=ModuleStatus.COMPLETED, data="success")
    
    # Register and invoke
    test_module = TestModule("test_module_1")
    manager.register_module(test_module)
    
    # Invoke
    result = asyncio.run(manager.invoke_module("test_module_1", ModuleContext(
        module_id="test_module_1",
        pipeline_orchestrator=mock_orchestrator
    )))
    
    logger.info(f"Result: {result.status}")
    logger.info(f"Metrics: {manager.get_metrics()}")
    
    # Shutdown
    manager.shutdown()
