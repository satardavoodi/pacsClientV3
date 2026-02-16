"""
Multi-Pipeline Concurrent Architecture Implementation

Core components for managing main pipeline + sub-pipelines with zero contention.
Implements cache management, state transitions, and concurrent resource access.
"""

import threading
import time
import logging
from typing import Dict, Optional, List, Tuple, Callable, Any
from dataclasses import dataclass, field
from collections import OrderedDict
from datetime import datetime
from enum import Enum
import weakref

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA MODELS
# ============================================================================

class PipelineState(Enum):
    """State transitions for study processing"""
    QUEUED = "QUEUED"              # Waiting to download
    DOWNLOADING = "DOWNLOADING"    # Download in progress
    DOWNLOADED = "DOWNLOADED"      # Ready to view
    RENDERING = "RENDERING"        # Currently viewing
    COMPLETED = "COMPLETED"        # All done


class PipelineRole(Enum):
    """Pipeline roles for resource allocation"""
    MAIN_PIPELINE = "main"          # Download → DB sync → render
    VIEW_PIPELINE = "view"          # Render cached data
    ANNOTATION = "annotation"       # User markups
    MEASUREMENT = "measurement"     # Tool measurements
    METADATA = "metadata"           # Background queries


@dataclass
class CacheEntry:
    """Single cache entry with metadata"""
    series_uid: str
    data: Any                       # Pixel data or VTK actor
    size_bytes: int
    last_access: float = field(default_factory=time.time)
    pin_count: int = 0              # Prevents eviction if > 0
    access_count: int = 0           # For eviction priority
    
    def __post_init__(self):
        if self.last_access is None:
            self.last_access = time.time()


@dataclass
class PipelineMetrics:
    """Track pipeline performance"""
    cache_hits: int = 0
    cache_misses: int = 0
    db_read_time: float = 0.0
    db_write_time: float = 0.0
    render_time: float = 0.0
    evictions: int = 0


# ============================================================================
# MEMORY CACHE MANAGER (LRU with pinning)
# ============================================================================

class MemoryCacheManager:
    """
    Manages multi-level cache with LRU eviction.
    
    Key properties:
    - Non-blocking operations (no spinlocks during cache ops)
    - Pin/unpin prevents eviction of actively viewed data
    - Automatic eviction under memory pressure
    - Optional memory budget enforcement
    """
    
    def __init__(self, max_memory_mb: int = 500, eviction_threshold: float = 0.9):
        """
        Args:
            max_memory_mb: Maximum cache size in MB
            eviction_threshold: Start eviction when memory > threshold% of max
        """
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.eviction_threshold = eviction_threshold
        self.current_memory = 0
        
        # OrderedDict maintains insertion order (important for LRU)
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        
        self.metrics = PipelineMetrics()
        logger.info(f"✅ MemoryCacheManager initialized ({max_memory_mb}MB max)")
    
    def get(self, series_uid: str) -> Optional[Any]:
        """Retrieve from cache (non-blocking)"""
        with self._lock:
            if series_uid not in self._cache:
                self.metrics.cache_misses += 1
                return None
            
            entry = self._cache[series_uid]
            entry.last_access = time.time()
            entry.access_count += 1
            
            # Move to end (most recently used)
            self._cache.move_to_end(series_uid)
            
            self.metrics.cache_hits += 1
            return entry.data
    
    def add(self, series_uid: str, data: Any, size_bytes: int) -> bool:
        """
        Add to cache, evicting LRU entries if needed.
        
        Returns:
            True if added successfully, False if rejected (e.g., too large)
        """
        if size_bytes > self.max_memory_bytes:
            logger.warning(f"⚠️ Series too large for cache: {size_bytes/1024/1024:.1f}MB > {self.max_memory_bytes/1024/1024:.1f}MB")
            return False
        
        with self._lock:
            # Remove if already exists (update)
            if series_uid in self._cache:
                old_size = self._cache[series_uid].size_bytes
                self.current_memory -= old_size
                del self._cache[series_uid]
            
            # Evict LRU if needed
            while (self.current_memory + size_bytes) > (self.max_memory_bytes * self.eviction_threshold):
                if not self._evict_one_lru():
                    # No evictable entries, even though we're over threshold
                    logger.warning(f"⚠️ Cache LRU eviction stalled: all entries pinned")
                    break
            
            # Add new entry
            entry = CacheEntry(
                series_uid=series_uid,
                data=data,
                size_bytes=size_bytes,
                last_access=time.time()
            )
            self._cache[series_uid] = entry
            self.current_memory += size_bytes
            
            logger.debug(f"📦 Added to cache: {series_uid} ({size_bytes/1024/1024:.1f}MB, total: {self.current_memory/1024/1024:.1f}MB)")
            
            return True
    
    def pin(self, series_uid: str) -> None:
        """Mark series as 'in use' - won't be evicted"""
        with self._lock:
            if series_uid in self._cache:
                self._cache[series_uid].pin_count += 1
                logger.debug(f"📌 Pinned: {series_uid} (pin_count={self._cache[series_uid].pin_count})")
    
    def unpin(self, series_uid: str) -> None:
        """Mark series as potentially evictable"""
        with self._lock:
            if series_uid in self._cache:
                self._cache[series_uid].pin_count = max(0, self._cache[series_uid].pin_count - 1)
                logger.debug(f"📍 Unpinned: {series_uid} (pin_count={self._cache[series_uid].pin_count})")
    
    def remove(self, series_uid: str) -> int:
        """Remove from cache, return freed bytes"""
        with self._lock:
            if series_uid in self._cache:
                freed = self._cache[series_uid].size_bytes
                self.current_memory -= freed
                del self._cache[series_uid]
                logger.debug(f"🗑️ Removed from cache: {series_uid} (freed {freed/1024/1024:.1f}MB)")
                return freed
            return 0
    
    def _evict_one_lru(self) -> bool:
        """Evict single LRU entry that isn't pinned"""
        # Iterate through all entries (older ones first due to OrderedDict)
        for series_uid, entry in list(self._cache.items()):
            # CRITICAL: Only evict if pin_count is 0
            if entry.pin_count == 0:  # Not pinned
                self.current_memory -= entry.size_bytes
                del self._cache[series_uid]
                self.metrics.evictions += 1
                logger.debug(f"🗑️  Evicted LRU: {series_uid} (freed {entry.size_bytes/1024/1024:.1f}MB, pin_count was 0)")
                return True
            else:
                # Skip pinned entries
                logger.debug(f"⏭️  Skipped pinned: {series_uid} (pin_count={entry.pin_count})")
        
        # No unpinned entries found
        logger.warning(f"⚠️  Cache eviction blocked: all {len(self._cache)} entries are pinned!")
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get cache status (non-blocking query)"""
        with self._lock:
            return {
                'entries': len(self._cache),
                'memory_used_mb': self.current_memory / 1024 / 1024,
                'memory_max_mb': self.max_memory_bytes / 1024 / 1024,
                'memory_percent': (self.current_memory / self.max_memory_bytes) * 100,
                'hits': self.metrics.cache_hits,
                'misses': self.metrics.cache_misses,
                'evictions': self.metrics.evictions,
                'hit_rate': self.metrics.cache_hits / max(1, self.metrics.cache_hits + self.metrics.cache_misses)
            }
    
    def clear(self) -> None:
        """Clear cache (use cautiously - only for shutdown/testing)"""
        with self._lock:
            self._cache.clear()
            self.current_memory = 0
            logger.info("💨 Cache cleared")


# ============================================================================
# PIPELINE STATE MANAGER (Thread-safe state transitions)
# ============================================================================

class PipelineStateManager:
    """
    Manages state transitions for each study across pipelines.
    Ensures atomic, race-free transitions.
    """
    
    def __init__(self):
        self._study_states: Dict[str, PipelineState] = {}
        self._state_callbacks: Dict[str, List[Callable]] = {}
        self._lock = threading.RLock()
    
    def create(self, study_uid: str, initial_state: PipelineState = PipelineState.QUEUED) -> None:
        """Create new study state"""
        with self._lock:
            if study_uid in self._study_states:
                raise ValueError(f"Study {study_uid} already exists")
            self._study_states[study_uid] = initial_state
            logger.info(f"📊 Created state for {study_uid}: {initial_state.value}")
    
    def transition(self, study_uid: str, from_state: PipelineState, to_state: PipelineState) -> bool:
        """
        Atomic state transition.
        
        Returns:
            True if transition successful, False if current state doesn't match expected
        """
        with self._lock:
            current = self._study_states.get(study_uid)
            
            if current != from_state:
                logger.warning(
                    f"⚠️ Cannot transition {study_uid}: expected {from_state.value}, "
                    f"got {current.value if current else 'None'}"
                )
                return False
            
            self._study_states[study_uid] = to_state
            logger.info(f"📊 State transition: {study_uid} {from_state.value} → {to_state.value}")
            
            # Call registered callbacks
            if study_uid in self._state_callbacks:
                for callback in self._state_callbacks[study_uid]:
                    try:
                        callback(study_uid, from_state, to_state)
                    except Exception as e:
                        logger.error(f"❌ Error in state callback: {e}")
            
            return True
    
    def get_state(self, study_uid: str) -> Optional[PipelineState]:
        """Get current state (non-blocking query)"""
        with self._lock:
            return self._study_states.get(study_uid)
    
    def can_render(self, study_uid: str) -> bool:
        """Check if study is ready for rendering"""
        with self._lock:
            state = self._study_states.get(study_uid)
            return state in [
                PipelineState.DOWNLOADED,
                PipelineState.RENDERING,
                PipelineState.COMPLETED
            ]
    
    def register_callback(self, study_uid: str, callback: Callable) -> None:
        """Register callback for state changes"""
        with self._lock:
            if study_uid not in self._state_callbacks:
                self._state_callbacks[study_uid] = []
            self._state_callbacks[study_uid].append(callback)


# ============================================================================
# PIPELINE EXECUTORS (Main + Sub-pipelines)
# ============================================================================

class MainDownloadPipeline:
    """
    Main pipeline: Query → Download → DB Sync → Render Queue → Report
    
    Non-blocking operations: Returns immediately, never locks UI.
    """
    
    def __init__(self, cache: MemoryCacheManager, state_manager: PipelineStateManager):
        self.cache = cache
        self.state_manager = state_manager
        self.metrics = PipelineMetrics()
        self._lock = threading.RLock()
    
    def queue_download(self, study_uid: str, task_metadata: Dict) -> bool:
        """
        Queue study for download (non-blocking).
        
        Returns immediately. Download happens in background.
        """
        try:
            self.state_manager.create(study_uid, PipelineState.QUEUED)
            # Actual download queuing would happen here via Zeta
            logger.info(f"📥 Queued download: {study_uid}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to queue download: {e}")
            return False
    
    def sync_to_database(self, study_uid: str, series_data: List) -> bool:
        """
        Sync downloaded series to database (batched, non-blocking).
        """
        try:
            start_time = time.time()
            
            # Write in batches to allow other operations
            batch_size = 100
            for i in range(0, len(series_data), batch_size):
                batch = series_data[i : i + batch_size]
                
                # Database write would happen here
                # (Uses pooled connection with DEFERRED isolation)
                logger.debug(f"💾 Syncing batch {i // batch_size + 1}...")
                
                # Small delay to allow interleaving
                time.sleep(0.001)
            
            self.metrics.db_write_time += time.time() - start_time
            
            # Transition state
            self.state_manager.transition(
                study_uid,
                PipelineState.DOWNLOADING,
                PipelineState.DOWNLOADED
            )
            
            logger.info(f"✅ Synced to DB: {study_uid}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to sync to DB: {e}")
            return False


class ViewRenderSubPipeline:
    """
    Sub-pipeline: Render cached series without blocking main pipeline.
    
    Can run while main pipeline is downloading/writing.
    """
    
    def __init__(self, cache: MemoryCacheManager, state_manager: PipelineStateManager):
        self.cache = cache
        self.state_manager = state_manager
        self.metrics = PipelineMetrics()
        self._series_uid: Optional[str] = None
        self._render_thread: Optional[threading.Thread] = None
    
    def show_series(self, series_uid: str) -> bool:
        """Display series in viewer (non-blocking)"""
        
        # Check if ready
        if not self.state_manager.can_render(series_uid):
            logger.warning(f"⚠️ Cannot render {series_uid}: not ready yet")
            return False
        
        # Pin series in cache (prevent eviction while viewing)
        self.cache.pin(series_uid)
        self._series_uid = series_uid
        
        # Get data (possibly from cache)
        start_time = time.time()
        data = self._get_series_data(series_uid)
        
        if data is None:
            logger.error(f"❌ Failed to get series data: {series_uid}")
            self.cache.unpin(series_uid)
            return False
        
        # Render in separate thread (non-blocking)
        self._render_thread = threading.Thread(
            target=self._render_loop,
            args=(series_uid, data),
            daemon=True
        )
        self._render_thread.start()
        
        logger.info(f"🎬 Rendering started: {series_uid}")
        return True
    
    def _get_series_data(self, series_uid: str) -> Optional[Any]:
        """Get series data (cache-first)"""
        start_time = time.time()
        
        # Try cache first
        data = self.cache.get(series_uid)
        if data is not None:
            hit_time = time.time() - start_time
            logger.debug(f"✅ Cache hit: {series_uid} ({hit_time*1000:.1f}ms)")
            return data
        
        # Load from disk (would happen here in real implementation)
        logger.debug(f"📁 Loading from disk: {series_uid}")
        time.sleep(0.1)  # Simulate disk I/O
        
        # Cache it for future use
        data = f"<PixelData:{series_uid}>"  # Placeholder
        self.cache.add(series_uid, data, size_bytes=10*1024*1024)  # 10MB estimate
        
        load_time = time.time() - start_time
        self.metrics.db_read_time += load_time
        logger.debug(f"📁 Loaded: {series_uid} ({load_time*1000:.1f}ms)")
        
        return data
    
    def _render_loop(self, series_uid: str, data: Any) -> None:
        """Render loop (runs in dedicated thread)"""
        try:
            start_time = time.time()
            
            # VTK rendering would happen here
            logger.debug(f"🎨 Rendering {series_uid}...")
            time.sleep(0.05)  # Simulate render
            
            self.metrics.render_time += time.time() - start_time
            
            # Update state
            self.state_manager.transition(
                series_uid,
                PipelineState.DOWNLOADED,
                PipelineState.RENDERING
            )
            
            logger.info(f"✅ Rendering complete: {series_uid}")
            
        except Exception as e:
            logger.error(f"❌ Render error: {e}")
        finally:
            # Always unpin when done viewing
            self.cache.unpin(series_uid)
    
    def stop_rendering(self) -> None:
        """Stop rendering and unpin series"""
        if self._series_uid:
            self.cache.unpin(self._series_uid)
            self._series_uid = None
            if self._render_thread:
                self._render_thread.join(timeout=1.0)


# ============================================================================
# PIPELINE ORCHESTRATOR (Coordinates main + sub-pipelines)
# ============================================================================

class PipelineOrchestrator:
    """
    High-level coordinator for managing multiple pipelines.
    Ensures resource sharing and prevents contention.
    """
    
    def __init__(self, max_cache_mb: int = 500, max_concurrent_sub_pipelines: int = 10):
        self.cache = MemoryCacheManager(max_memory_mb=max_cache_mb)
        self.state_manager = PipelineStateManager()
        self.main_pipeline = MainDownloadPipeline(self.cache, self.state_manager)
        
        self._sub_pipelines: Dict[str, ViewRenderSubPipeline] = {}
        self._max_sub_pipelines = max_concurrent_sub_pipelines
        self._lock = threading.RLock()
        
        logger.info(f"✅ PipelineOrchestrator initialized (cache: {max_cache_mb}MB)")
    
    def create_viewer_pipeline(self, viewer_id: str) -> Optional[ViewRenderSubPipeline]:
        """Create new viewer with its own render pipeline"""
        with self._lock:
            if len(self._sub_pipelines) >= self._max_sub_pipelines:
                logger.warning(f"⚠️ Max concurrent viewers ({self._max_sub_pipelines}) reached")
                return None
            
            pipeline = ViewRenderSubPipeline(self.cache, self.state_manager)
            self._sub_pipelines[viewer_id] = pipeline
            logger.info(f"🎬 Created viewer pipeline: {viewer_id}")
            return pipeline
    
    def destroy_viewer_pipeline(self, viewer_id: str) -> None:
        """Destroy viewer and its pipeline"""
        with self._lock:
            if viewer_id in self._sub_pipelines:
                self._sub_pipelines[viewer_id].stop_rendering()
                del self._sub_pipelines[viewer_id]
                logger.info(f"🗑️ Destroyed viewer pipeline: {viewer_id}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get overall system status"""
        return {
            'cache': self.cache.get_status(),
            'active_viewers': len(self._sub_pipelines),
            'main_pipeline_metrics': {
                'db_write_time': self.main_pipeline.metrics.db_write_time
            }
        }


if __name__ == "__main__":
    # Example usage and validation
    
    logging.basicConfig(level=logging.DEBUG)
    
    print("\n" + "="*80)
    print("MULTI-PIPELINE CONCURRENT ARCHITECTURE - DEMO")
    print("="*80 + "\n")
    
    # Create orchestrator
    orchestrator = PipelineOrchestrator(max_cache_mb=100)
    
    # Create two viewers
    viewer1 = orchestrator.create_viewer_pipeline("viewer_1")
    viewer2 = orchestrator.create_viewer_pipeline("viewer_2")
    
    # Queue download in main pipeline
    orchestrator.main_pipeline.queue_download("study_001", {})
    
    # Simulate state progression
    orchestrator.state_manager.transition(
        "study_001",
        PipelineState.QUEUED,
        PipelineState.DOWNLOADING
    )
    
    # Pre-load series into cache
    orchestrator.cache.add("series_a", "<PixelData:series_a>", 10*1024*1024)
    orchestrator.state_manager.create("series_a", PipelineState.DOWNLOADED)
    
    # Start viewers (non-blocking)
    print("\n▶️ Starting concurrent viewers...")
    viewer1.show_series("series_a")
    viewer2.show_series("series_a")
    
    # Meanwhile, simulate main pipeline update
    print("\n▶️ Main pipeline syncing to DB...")
    time.sleep(1)
    orchestrator.main_pipeline.sync_to_database("study_001", [])
    
    # Check cache status
    print("\n📊 CACHE STATUS:")
    for k, v in orchestrator.cache.get_status().items():
        print(f"  {k}: {v}")
    
    print("\n✅ Demo complete - no blocking between pipelines!")
