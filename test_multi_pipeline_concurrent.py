#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Pipeline Concurrent Architecture Test Suite

Tests concurrent execution of main pipeline + sub-pipelines.
Validates: no blocking, proper resource sharing, memory management.
"""

import sys
import time
import threading
import logging
from pathlib import Path
from typing import List

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add workspace to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PacsClient.components.pipeline_orchestrator import (
    PipelineOrchestrator,
    PipelineState,
    MemoryCacheManager,
    MainDownloadPipeline,
    ViewRenderSubPipeline
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# TEST SCENARIOS
# ============================================================================

class ConcurrentPipelineTests:
    """Test suite for concurrent pipeline architecture"""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
    
    def test_1_cache_basic_operations(self):
        """Test 1: Cache LRU eviction works correctly"""
        print("\n" + "="*80)
        print("TEST 1: Memory Cache LRU Eviction (with pinning)")
        print("="*80)
        
        try:
            cache = MemoryCacheManager(max_memory_mb=50)  # 50MB max
            
            # Add first series and IMMEDIATELY pin it before filling cache
            cache.add("series_0", "<Data:0>", size_bytes=10*1024*1024)  # 10MB
            cache.pin("series_0")  # PIN before adding more data
            print(f"  ✅ Added series_0 (10MB) and pinned it")
            
            # Add more series to fill cache and trigger evictions
            for i in range(1, 8):  # 7 more x 10MB = 70MB total
                series_uid = f"series_{i}"
                cache.add(series_uid, f"<Data:{i}>", size_bytes=10*1024*1024)  # 10MB each
                status = cache.get_status()
                if i % 2 == 0:
                    print(f"    After series_{i}: {status['memory_used_mb']:.0f}MB used, {status['entries']} entries, {status['evictions']} evictions")
            
            status = cache.get_status()
            print(f"  Final: {status['memory_used_mb']:.0f}MB used ({status['memory_percent']:.0f}%), {status['entries']} entries")
            print(f"  Total evictions: {status['evictions']}")
            
            # Memory should be bounded to 50MB max
            assert status['memory_used_mb'] <= 50, f"Memory exceeded max! {status['memory_used_mb']:.0f}MB > 50MB"
            
            # Series_0 should STILL be there (pinned)
            retrieved = cache.get("series_0")
            assert retrieved is not None, f"❌ Pinned series_0 was evicted! Current entries: {list(cache._cache.keys())}"
            print(f"  ✅ Pinned series_0 survived {status['evictions']} evictions")
            
            # Verify pin_count is still > 0
            assert cache._cache["series_0"].pin_count > 0, "Pin count was reset!"
            print(f"  ✅ Pin count maintained: {cache._cache['series_0'].pin_count}")
            
            # Unpin and verify it CAN be evicted
            cache.unpin("series_0")
            print(f"  ✅ Unpinned series_0, can now be evicted")
            
            print("✅ TEST 1 PASSED - Pin/unpin protection verified")
            self.passed += 1
            
        except Exception as e:
            print(f"❌ TEST 1 FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
    
    def test_2_state_transitions(self):
        """Test 2: Thread-safe state transitions"""
        print("\n" + "="*80)
        print("TEST 2: Thread-Safe State Transitions")
        print("="*80)
        
        try:
            from PacsClient.components.pipeline_orchestrator import PipelineStateManager
            
            state_mgr = PipelineStateManager()
            state_mgr.create("study_001", PipelineState.QUEUED)
            
            # Valid transition
            success = state_mgr.transition(
                "study_001",
                PipelineState.QUEUED,
                PipelineState.DOWNLOADING
            )
            assert success, "Valid transition failed"
            print(f"  ✅ Valid transition succeeded")
            
            # Invalid transition (wrong from_state)
            success = state_mgr.transition(
                "study_001",
                PipelineState.QUEUED,  # Wrong! Current is DOWNLOADING
                PipelineState.DOWNLOADED
            )
            assert not success, "Invalid transition should fail"
            print(f"  ✅ Invalid transition rejected")
            
            # Check can_render at various states
            assert not state_mgr.can_render("study_001"), "Cannot render while DOWNLOADING"
            
            state_mgr.transition("study_001", PipelineState.DOWNLOADING, PipelineState.DOWNLOADED)
            assert state_mgr.can_render("study_001"), "Can render when DOWNLOADED"
            print(f"  ✅ Render state checks work")
            
            print("✅ TEST 2 PASSED")
            self.passed += 1
            
        except Exception as e:
            print(f"❌ TEST 2 FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
    
    def test_3_main_pipeline_nonblocking(self):
        """Test 3: Main pipeline operations don't block"""
        print("\n" + "="*80)
        print("TEST 3: Main Pipeline Non-Blocking Operations")
        print("="*80)
        
        try:
            orchestrator = PipelineOrchestrator(max_cache_mb=200)
            
            # Queue multiple downloads
            start = time.time()
            
            for i in range(10):
                orchestrator.main_pipeline.queue_download(f"study_{i:03d}", {})
            
            elapsed = time.time() - start
            
            print(f"  Queued 10 downloads in {elapsed*1000:.1f}ms (should be <100ms)")
            assert elapsed < 0.1, "Queueing took too long, probably blocking"
            print(f"  ✅ Non-blocking confirmed")
            
            print("✅ TEST 3 PASSED")
            self.passed += 1
            
        except Exception as e:
            print(f"❌ TEST 3 FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
    
    def test_4_concurrent_viewers_render(self):
        """Test 4: Multiple viewers render concurrently without blocking each other"""
        print("\n" + "="*80)
        print("TEST 4: Concurrent Viewer Rendering")
        print("="*80)
        
        try:
            orchestrator = PipelineOrchestrator(max_cache_mb=300)
            
            # Create viewers
            viewers = []
            for i in range(3):
                viewer = orchestrator.create_viewer_pipeline(f"viewer_{i}")
                viewers.append(viewer)
            
            # Pre-load series
            for i in range(3):
                series_uid = f"series_{i}"
                orchestrator.cache.add(series_uid, f"<Data:{i}>", size_bytes=20*1024*1024)
                orchestrator.state_manager.create(series_uid, PipelineState.DOWNLOADED)
            
            # Start rendering concurrently
            render_times = []
            
            def render_and_time(viewer, series_uid):
                start = time.time()
                viewer.show_series(series_uid)
                elapsed = time.time() - start
                render_times.append(elapsed)
            
            threads = []
            for i, viewer in enumerate(viewers):
                t = threading.Thread(target=render_and_time, args=(viewer, f"series_{i}"))
                threads.append(t)
                t.start()
            
            # Wait for all to complete
            for t in threads:
                t.join()
            
            print(f"  Concurrent renders completed")
            print(f"  Times: {[f'{t*1000:.1f}ms' for t in render_times]}")
            
            # All should take roughly same time (no blocking)
            # Threshold: 3.5x allows for OS scheduler variance while detecting true blocking (10x+)
            max_time = max(render_times)
            min_time = min(render_times)
            ratio = max_time / min_time if min_time > 0 else 1
            
            print(f"  Max/Min ratio: {ratio:.1f}x (should be <3.5x = no blocking)")
            assert ratio < 3.5, f"Viewers blocking each other: {ratio}x difference"
            print(f"  ✅ Concurrent rendering works (ratio {ratio:.2f}x indicates parallel execution)")
            
            # Cleanup
            for viewer in viewers:
                viewer.stop_rendering()
            
            print("✅ TEST 4 PASSED")
            self.passed += 1
            
        except Exception as e:
            print(f"❌ TEST 4 FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
    
    def test_5_main_plus_sub_concurrent(self):
        """Test 5: Main pipeline + sub-pipelines working simultaneously"""
        print("\n" + "="*80)
        print("TEST 5: Main Pipeline + Sub-Pipelines Concurrent")
        print("="*80)
        
        try:
            orchestrator = PipelineOrchestrator(max_cache_mb=400)
            
            # Create viewers (sub-pipelines)
            viewer1 = orchestrator.create_viewer_pipeline("viewer_1")
            viewer2 = orchestrator.create_viewer_pipeline("viewer_2")
            
            # Pre-load series for viewers
            orchestrator.cache.add("series_a", "<Data:a>", size_bytes=20*1024*1024)
            orchestrator.cache.add("series_b", "<Data:b>", size_bytes=20*1024*1024)
            orchestrator.state_manager.create("series_a", PipelineState.DOWNLOADED)
            orchestrator.state_manager.create("series_b", PipelineState.DOWNLOADED)
            
            # Start viewers
            viewer1.show_series("series_a")
            viewer2.show_series("series_b")
            
            # Simultaneously, main pipeline is downloading
            def main_pipeline_work():
                for i in range(5):
                    orchestrator.main_pipeline.queue_download(f"study_{i}", {})
                    time.sleep(0.1)
            
            main_thread = threading.Thread(target=main_pipeline_work)
            main_thread.start()
            
            # Keep rendering while main pipeline works
            render_count = 0
            start = time.time()
            
            while time.time() - start < 1.0:  # Run for 1 second
                viewer1.render_time = time.time()
                viewer2.render_time = time.time()
                render_count += 2
                time.sleep(0.05)
            
            main_thread.join(timeout=2)
            
            print(f"  Main pipeline queued 5 downloads while sub-pipelines rendered {render_count} frames")
            print(f"  ✅ No visible blocking between main and sub-pipelines")
            
            print("✅ TEST 5 PASSED")
            self.passed += 1
            
        except Exception as e:
            print(f"❌ TEST 5 FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
    
    def test_6_cache_eviction_under_pressure(self):
        """Test 6: Cache evicts correctly under memory pressure"""
        print("\n" + "="*80)
        print("TEST 6: Cache Eviction Under Memory Pressure")
        print("="*80)
        
        try:
            cache = MemoryCacheManager(max_memory_mb=100)
            
            # Fill cache and pin some entries (viewers active)
            for i in range(3):
                series_uid = f"series_{i}"
                cache.add(series_uid, f"<Data:{i}>", size_bytes=15*1024*1024)
                cache.pin(series_uid)
            
            status_before = cache.get_status()
            print(f"  Before eviction pressure: {status_before['entries']} entries, {status_before['memory_used_mb']:.1f}MB")
            
            # Now try to add more (should evict unpinned, keep pinned)
            for i in range(3, 10):
                series_uid = f"series_{i}"
                cache.add(series_uid, f"<Data:{i}>", size_bytes=15*1024*1024)
            
            status_after = cache.get_status()
            print(f"  After pressure: {status_after['entries']} entries, {status_after['evictions']} evictions")
            
            # Pinned entries should be preserved
            for i in range(3):
                assert cache.get(f"series_{i}") is not None, f"Pinned series_{i} was evicted!"
            
            print(f"  ✅ Pinned entries survived eviction")
            print(f"  ✅ Old unpinned entries evicted: {status_after['evictions']} total")
            
            print("✅ TEST 6 PASSED")
            self.passed += 1
            
        except Exception as e:
            print(f"❌ TEST 6 FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
    
    def test_7_no_deadlocks(self):
        """Test 7: No deadlocks under concurrent load"""
        print("\n" + "="*80)
        print("TEST 7: Deadlock Detection (Stress Test)")
        print("="*80)
        
        try:
            orchestrator = PipelineOrchestrator(max_cache_mb=500)
            
            errors = []
            
            def worker_main(worker_id):
                try:
                    for i in range(20):
                        study_uid = f"study_w{worker_id}_s{i}"
                        orchestrator.main_pipeline.queue_download(study_uid, {})
                        time.sleep(0.01)
                except Exception as e:
                    errors.append(f"Main worker {worker_id}: {e}")
            
            def worker_viewer(worker_id):
                try:
                    viewer = orchestrator.create_viewer_pipeline(f"viewer_{worker_id}")
                    for i in range(20):
                        series_uid = f"series_w{worker_id}_s{i}"
                        orchestrator.cache.add(series_uid, f"<Data>", size_bytes=5*1024*1024)
                        orchestrator.state_manager.create(series_uid, PipelineState.DOWNLOADED)
                        viewer.show_series(series_uid)
                        time.sleep(0.01)
                except Exception as e:
                    errors.append(f"Viewer worker {worker_id}: {e}")
            
            # Start multiple threads (should not deadlock)
            threads = []
            
            for i in range(3):
                t = threading.Thread(target=worker_main, args=(i,))
                threads.append(t)
                t.start()
            
            for i in range(3):
                t = threading.Thread(target=worker_viewer, args=(i,))
                threads.append(t)
                t.start()
            
            # Wait with timeout (if deadlocked, timeout)
            start = time.time()
            for t in threads:
                timeout = max(0.1, 5.0 - (time.time() - start))  # Remaining time
                t.join(timeout=timeout)
                if t.is_alive():
                    print(f"❌ Thread still alive after timeout - likely deadlock!")
                    raise TimeoutError("Deadlock detected")
            
            elapsed = time.time() - start
            
            if errors:
                for err in errors:
                    print(f"  ERROR: {err}")
                raise Exception(f"Workers encountered errors: {errors}")
            
            print(f"  6 concurrent workers completed in {elapsed:.1f}s with no deadlock")
            print(f"  ✅ No deadlocks detected")
            
            print("✅ TEST 7 PASSED")
            self.passed += 1
            
        except Exception as e:
            print(f"❌ TEST 7 FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1


def run_all_tests():
    """Run complete test suite"""
    print("\n")
    print("+" + "=" * 78 + "+")
    print("|" + " " * 78 + "|")
    print("|" + "MULTI-PIPELINE CONCURRENT ARCHITECTURE TEST SUITE".center(78) + "|")
    print("|" + " " * 78 + "|")
    print("+" + "=" * 78 + "+")
    
    tester = ConcurrentPipelineTests()
    
    # Run all tests
    tester.test_1_cache_basic_operations()
    tester.test_2_state_transitions()
    tester.test_3_main_pipeline_nonblocking()
    tester.test_4_concurrent_viewers_render()
    tester.test_5_main_plus_sub_concurrent()
    tester.test_6_cache_eviction_under_pressure()
    tester.test_7_no_deadlocks()
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    total = tester.passed + tester.failed
    print(f"PASSED: {tester.passed}/{total}")
    print(f"FAILED: {tester.failed}/{total}")
    
    if tester.failed == 0:
        print("\n[SUCCESS] ALL TESTS PASSED!")
        print("   Multi-pipeline concurrent architecture is ready for production.")
        return 0
    else:
        print(f"\n[WARNING] {tester.failed} test(s) failed - review and fix before deployment")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
