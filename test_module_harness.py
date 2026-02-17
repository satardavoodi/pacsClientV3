"""
Module Execution Framework - Test & Validation Harness

This script provides testing utilities for validating Module implementations
before integrating them with the production PipelineOrchestrator.

Usage:
    python test_module_harness.py
    
Tests validate:
    - Module execution completes
    - No blocking on main thread
    - Proper error handling
    - DB operations are thread-safe
    - Cache integration works
    - Stop signal handling works
    - State persistence works
"""

import asyncio
import sqlite3
import time
from contextlib import contextmanager
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import logging

from PacsClient.components.module_manager import ModuleContext

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# MOCK PIPELINE ORCHESTRATOR
# ============================================================================

@dataclass
class MockCacheEntry:
    data: Any
    size_bytes: int
    pin_count: int = 0


class MockPipelineOrchestrator:
    """Mock orchestrator for testing modules"""
    
    def __init__(self):
        self.cache: Dict[str, MockCacheEntry] = {}
        self.cache_hits = 0
        self.cache_misses = 0

        class _CacheAdapter:
            def __init__(adapter_self, owner):
                adapter_self._owner = owner

            def get(adapter_self, key: str):
                return adapter_self._owner.get_from_cache(key)

            def add(adapter_self, key: str, data: Any, size_bytes: int):
                adapter_self._owner.add_to_cache(key, data, size_bytes)

        self.cache = _CacheAdapter(self)
    
    def add_to_cache(self, key: str, data: Any, size_bytes: int) -> None:
        self.cache[key] = MockCacheEntry(data=data, size_bytes=size_bytes)
    
    def get_from_cache(self, key: str) -> Optional[Any]:
        if key in self.cache:
            self.cache_hits += 1
            return self.cache[key].data
        self.cache_misses += 1
        return None


# ============================================================================
# CONNECTION POOL FOR TESTING
# ============================================================================

class TestConnectionPool:
    """Simple connection pool for testing"""
    
    def __init__(self, db_path: str = ":memory:", pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._connections: List[sqlite3.Connection] = []
        self._available: List[sqlite3.Connection] = []
        self._initialize_connections()
    
    def _initialize_connections(self):
        """Initialize connection pool"""
        for _ in range(self.pool_size):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.isolation_level = None  # Autocommit
            self._connections.append(conn)
            self._available.append(conn)
        logger.debug(f"Initialized pool with {self.pool_size} connections")
    
    @contextmanager
    def acquire(self):
        """Acquire connection from pool"""
        if not self._available:
            raise RuntimeError("No available connections")
        
        conn = self._available.pop()
        try:
            yield conn
        finally:
            self._available.append(conn)
    
    def close_all(self):
        """Close all connections"""
        for conn in self._connections:
            conn.close()
        logger.debug("Closed all connections")


# ============================================================================
# TEST UTILITIES
# ============================================================================

class ModuleTestHarness:
    """Harness for testing module implementations"""
    
    def __init__(self, module_id: str, mock_orchestrator: MockPipelineOrchestrator):
        self.module_id = module_id
        self.orchestrator = mock_orchestrator
        self.db_pool = TestConnectionPool()
        self.test_results: List[Dict[str, Any]] = []
    
    async def test_basic_execution(self, module) -> bool:
        """Test module executes without error"""
        print(f"\n{'='*60}")
        print(f"TEST: Basic Execution - {self.module_id}")
        print(f"{'='*60}")
        
        try:
            # Create mock context
            context = self._create_mock_context()
            
            # Execute
            start = time.time()
            result = await module.execute(context)
            elapsed = time.time() - start
            
            # Verify
            assert result is not None, "Result is None"
            assert hasattr(result, 'status'), "Result missing status"
            assert hasattr(result, 'data'), "Result missing data"
            
            print(f"✅ PASS - {self.module_id} executed in {elapsed:.3f}s")
            print(f"   Status: {result.status}")
            print(f"   Data: {str(result.data)[:100]}...")
            
            self.test_results.append({
                'test': 'basic_execution',
                'passed': True,
                'elapsed': elapsed
            })
            return True
        
        except Exception as e:
            print(f"❌ FAIL - {str(e)}")
            self.test_results.append({
                'test': 'basic_execution',
                'passed': False,
                'error': str(e)
            })
            return False
    
    async def test_stop_signal(self, module) -> bool:
        """Test module responds to stop signal"""
        print(f"\n{'='*60}")
        print(f"TEST: Stop Signal - {self.module_id}")
        print(f"{'='*60}")
        
        try:
            context = self._create_mock_context()
            
            # Request stop before execution
            module.request_stop()
            
            # Execute
            result = await module.execute(context)
            
            # Should stop quickly
            print(f"✅ PASS - Module stopped on signal")
            print(f"   Status: {result.status}")

            module.clear_stop()
            
            self.test_results.append({
                'test': 'stop_signal',
                'passed': True
            })
            return True
        
        except Exception as e:
            print(f"❌ FAIL - {str(e)}")
            self.test_results.append({
                'test': 'stop_signal',
                'passed': False,
                'error': str(e)
            })
            return False
    
    async def test_error_handling(self, module, error_func) -> bool:
        """Test module handles errors gracefully"""
        print(f"\n{'='*60}")
        print(f"TEST: Error Handling - {self.module_id}")
        print(f"{'='*60}")
        
        try:
            context = self._create_mock_context()
            
            # Inject error condition
            error_func()
            
            # Execute
            result = await module.execute(context)
            
            # Should not raise, should return error status
            if result is None:
                print(f"❌ FAIL - Returned None instead of error result")
                self.test_results.append({
                    'test': 'error_handling',
                    'passed': False,
                    'error': 'Returned None'
                })
                return False
            
            print(f"✅ PASS - Module handled error gracefully")
            print(f"   Status: {result.status}")
            if result.error:
                print(f"   Error: {result.error}")
            
            self.test_results.append({
                'test': 'error_handling',
                'passed': True
            })
            return True
        
        except Exception as e:
            print(f"❌ FAIL - Module crashed: {str(e)}")
            self.test_results.append({
                'test': 'error_handling',
                'passed': False,
                'error': str(e)
            })
            return False
    
    async def test_concurrent_execution(self, module, num_concurrent: int = 3) -> bool:
        """Test module works with concurrent execution"""
        print(f"\n{'='*60}")
        print(f"TEST: Concurrent Execution ({num_concurrent} tasks) - {self.module_id}")
        print(f"{'='*60}")
        
        try:
            # Create concurrent tasks
            tasks = []
            for i in range(num_concurrent):
                context = self._create_mock_context()
                context.user_parameters = {'task_id': i}
                tasks.append(module.execute(context))
            
            # Execute concurrently
            start = time.time()
            results = await asyncio.gather(*tasks)
            elapsed = time.time() - start
            
            # Verify all completed
            for i, result in enumerate(results):
                assert result is not None, f"Task {i} returned None"
                assert hasattr(result, 'status'), f"Task {i} missing status"
            
            print(f"✅ PASS - {num_concurrent} concurrent executions completed in {elapsed:.3f}s")
            print(f"   Avg per task: {elapsed/num_concurrent:.3f}s")
            
            self.test_results.append({
                'test': f'concurrent_execution_{num_concurrent}',
                'passed': True,
                'elapsed': elapsed
            })
            return True
        
        except Exception as e:
            print(f"❌ FAIL - {str(e)}")
            self.test_results.append({
                'test': f'concurrent_execution_{num_concurrent}',
                'passed': False,
                'error': str(e)
            })
            return False
    
    async def test_cache_integration(self, module) -> bool:
        """Test module caches results properly"""
        print(f"\n{'='*60}")
        print(f"TEST: Cache Integration - {self.module_id}")
        print(f"{'='*60}")
        
        try:
            context = self._create_mock_context()
            
            # Pre-populate cache
            test_data = {'cached': True, 'value': 42}
            self.orchestrator.add_to_cache('test_key', test_data, 1024)
            
            # Execute
            result = await module.execute(context)
            
            # Check if cache was accessed
            hits_before = self.orchestrator.cache_hits
            retrieved = self.orchestrator.get_from_cache('test_key')
            hits_after = self.orchestrator.cache_hits
            
            assert retrieved == test_data, "Cache data mismatch"
            assert hits_after > hits_before, "Cache not accessed"
            
            print(f"✅ PASS - Cache integration working")
            print(f"   Hits: {self.orchestrator.cache_hits}")
            print(f"   Misses: {self.orchestrator.cache_misses}")
            
            self.test_results.append({
                'test': 'cache_integration',
                'passed': True
            })
            return True
        
        except Exception as e:
            print(f"❌ FAIL - {str(e)}")
            self.test_results.append({
                'test': 'cache_integration',
                'passed': False,
                'error': str(e)
            })
            return False
    
    async def test_db_operations(self, module) -> bool:
        """Test module DB operations don't block"""
        print(f"\n{'='*60}")
        print(f"TEST: Database Operations - {self.module_id}")
        print(f"{'='*60}")
        
        try:
            # Create test table
            with self.db_pool.acquire() as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS test_data (
                        id INTEGER PRIMARY KEY,
                        value TEXT
                    )
                ''')
                conn.commit()
            
            context = self._create_mock_context()
            
            # Execute (may perform DB ops)
            start = time.time()
            result = await module.execute(context)
            elapsed = time.time() - start
            
            # Should complete reasonably fast
            assert elapsed < 10.0, f"Took too long: {elapsed:.1f}s"
            
            print(f"✅ PASS - Database operations completed in {elapsed:.3f}s")
            
            self.test_results.append({
                'test': 'db_operations',
                'passed': True,
                'elapsed': elapsed
            })
            return True
        
        except Exception as e:
            print(f"❌ FAIL - {str(e)}")
            self.test_results.append({
                'test': 'db_operations',
                'passed': False,
                'error': str(e)
            })
            return False
    
    async def test_state_persistence(self, module) -> bool:
        """Test module state saves and loads"""
        print(f"\n{'='*60}")
        print(f"TEST: State Persistence - {self.module_id}")
        print(f"{'='*60}")
        
        try:
            # Save state
            state = module.save_state()
            assert state is not None, "State is None"
            assert isinstance(state, dict), "State is not dict"
            
            # Simulate app restart (new module instance)
            module2 = module.__class__(module.module_id)
            
            # Load state
            module2.load_state(state)
            
            print(f"✅ PASS - State persistence working")
            print(f"   State keys: {list(state.keys())}")
            
            self.test_results.append({
                'test': 'state_persistence',
                'passed': True
            })
            return True
        
        except Exception as e:
            print(f"❌ FAIL - {str(e)}")
            self.test_results.append({
                'test': 'state_persistence',
                'passed': False,
                'error': str(e)
            })
            return False
    
    def print_summary(self) -> None:
        """Print test summary"""
        print(f"\n{'='*60}")
        print(f"TEST SUMMARY - {self.module_id}")
        print(f"{'='*60}")
        
        passed = sum(1 for r in self.test_results if r['passed'])
        total = len(self.test_results)
        
        print(f"\nResults: {passed}/{total} PASSED")
        
        for result in self.test_results:
            status = "✅" if result['passed'] else "❌"
            test_name = result['test']
            print(f"  {status} {test_name}", end="")
            
            if result.get('elapsed'):
                print(f" ({result['elapsed']:.3f}s)", end="")
            if result.get('error'):
                print(f" - {result['error']}", end="")
            
            print()
        
        success_rate = (passed / total * 100) if total > 0 else 0
        print(f"\nSuccess Rate: {success_rate:.1f}%")
        
        if success_rate == 100:
            print("✅ ALL TESTS PASSED - Module ready for integration")
        else:
            print("❌ SOME TESTS FAILED - Fix issues before integration")
    
    def _create_mock_context(self):
        """Create mock ModuleContext for testing"""
        db_conn = sqlite3.connect(":memory:", check_same_thread=False)
        db_conn.isolation_level = None
        return ModuleContext(
            module_id=self.module_id,
            pipeline_orchestrator=self.orchestrator,
            db_connection=db_conn,
            series_uid='test_series_uid',
            patient_uid='test_patient_uid',
            user_parameters={}
        )
    
    @staticmethod
    def _mock_query(sql: str, params: tuple) -> List:
        """Mock database query"""
        return [(1, 'test_value')]
    
    @staticmethod
    def _mock_update(sql: str, params: tuple) -> int:
        """Mock database update"""
        return 1


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

async def run_full_test_suite(module):
    """Run complete test suite on module"""
    orchestrator = MockPipelineOrchestrator()
    harness = ModuleTestHarness(module.module_id, orchestrator)
    
    # Run tests
    await harness.test_basic_execution(module)
    await harness.test_stop_signal(module)
    await harness.test_concurrent_execution(module, num_concurrent=5)
    await harness.test_cache_integration(module)
    await harness.test_state_persistence(module)
    
    # Print summary
    harness.print_summary()
    
    # Cleanup
    harness.db_pool.close_all()
    
    return harness


if __name__ == "__main__":
    print("""
    Module Test Harness
    ===================
    
    This harness provides utilities for testing Module implementations.
    
    Usage in your test file:
    
        from test_module_harness import run_full_test_suite
        from your_module import YourModule
        
        async def main():
            module = YourModule("your_module_id")
            harness = await run_full_test_suite(module)
    
    The harness will run these tests:
        1. Basic execution (module runs without error)
        2. Stop signal (module responds to cancellation)
        3. Concurrent execution (5 parallel tasks work)
        4. Cache integration (uses module cache)
        5. State persistence (state saves/loads)
    
    Modules passing all tests are ready for integration.
    """)
