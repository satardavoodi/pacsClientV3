"""
TTL Cache with LRU Eviction
Thread-safe cache implementation with time-to-live and size limits
"""
import time
import threading
from collections import OrderedDict
from typing import Optional, Any, Callable, TypeVar, Generic
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

K = TypeVar('K')
V = TypeVar('V')


@dataclass
class CacheEntry(Generic[V]):
    """Cache entry with value and timestamp"""
    value: V
    timestamp: float
    access_count: int = 0
    
    def is_expired(self, ttl_seconds: float) -> bool:
        """Check if entry has expired"""
        return (time.time() - self.timestamp) > ttl_seconds
    
    def age_seconds(self) -> float:
        """Get age of entry in seconds"""
        return time.time() - self.timestamp


class TTLCache(Generic[K, V]):
    """
    Thread-safe cache with TTL and LRU eviction
    
    Features:
    - Time-to-live (TTL) for automatic expiration
    - LRU eviction when max size reached
    - Thread-safe operations
    - Statistics tracking
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        ttl_seconds: float = 300,
        on_evict: Optional[Callable[[K, V], None]] = None
    ):
        """
        Args:
            max_size: Maximum number of entries
            ttl_seconds: Time-to-live in seconds
            on_evict: Optional callback when entry is evicted
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.on_evict = on_evict
        
        self._cache: OrderedDict[K, CacheEntry[V]] = OrderedDict()
        self._lock = threading.RLock()
        
        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
    
    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """
        Get value from cache
        
        Args:
            key: Cache key
            default: Default value if not found
        
        Returns:
            Cached value or default
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._misses += 1
                return default
            
            # Check if expired
            if entry.is_expired(self.ttl_seconds):
                self._invalidate(key, reason="expired")
                self._misses += 1
                self._expirations += 1
                return default
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.access_count += 1
            self._hits += 1
            
            return entry.value
    
    def set(self, key: K, value: V) -> None:
        """
        Set value in cache
        
        Args:
            key: Cache key
            value: Value to cache
        """
        with self._lock:
            # Update existing entry
            if key in self._cache:
                self._cache[key] = CacheEntry(
                    value=value,
                    timestamp=time.time(),
                    access_count=self._cache[key].access_count
                )
                self._cache.move_to_end(key)
                return
            
            # Evict oldest if at max size
            if len(self._cache) >= self.max_size:
                self._evict_lru()
            
            # Add new entry
            self._cache[key] = CacheEntry(
                value=value,
                timestamp=time.time()
            )
    
    def invalidate(self, key: K) -> bool:
        """
        Invalidate a specific key
        
        Args:
            key: Key to invalidate
        
        Returns:
            True if key existed, False otherwise
        """
        with self._lock:
            return self._invalidate(key, reason="manual")
    
    def _invalidate(self, key: K, reason: str = "unknown") -> bool:
        """Internal invalidation with reason"""
        entry = self._cache.pop(key, None)
        if entry is not None:
            if self.on_evict:
                try:
                    self.on_evict(key, entry.value)
                except Exception as e:
                    logger.error(f"Error in eviction callback: {e}")
            logger.debug(f"Invalidated cache key {key} (reason: {reason})")
            return True
        return False
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry"""
        if not self._cache:
            return
        
        # Pop from beginning (least recently used)
        key, entry = self._cache.popitem(last=False)
        self._evictions += 1
        
        if self.on_evict:
            try:
                self.on_evict(key, entry.value)
            except Exception as e:
                logger.error(f"Error in eviction callback: {e}")
        
        logger.debug(f"Evicted LRU cache entry: {key}")
    
    def clear(self) -> None:
        """Clear all cache entries"""
        with self._lock:
            if self.on_evict:
                for key, entry in self._cache.items():
                    try:
                        self.on_evict(key, entry.value)
                    except Exception as e:
                        logger.error(f"Error in eviction callback: {e}")
            
            self._cache.clear()
            logger.info("Cache cleared")
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries
        
        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired(self.ttl_seconds)
            ]
            
            for key in expired_keys:
                self._invalidate(key, reason="expired")
                self._expirations += 1
            
            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired entries")
            
            return len(expired_keys)
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate_percent': round(hit_rate, 2),
                'evictions': self._evictions,
                'expirations': self._expirations,
                'ttl_seconds': self.ttl_seconds
            }
    
    def reset_stats(self) -> None:
        """Reset statistics counters"""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._expirations = 0
    
    def __len__(self) -> int:
        """Get current cache size"""
        with self._lock:
            return len(self._cache)
    
    def __contains__(self, key: K) -> bool:
        """Check if key exists and is not expired"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired(self.ttl_seconds):
                self._invalidate(key, reason="expired")
                return False
            return True
    
    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"TTLCache(size={stats['size']}/{stats['max_size']}, "
            f"hit_rate={stats['hit_rate_percent']}%, "
            f"ttl={stats['ttl_seconds']}s)"
        )


class AutoCleanupCache(TTLCache[K, V]):
    """
    TTLCache with automatic background cleanup of expired entries
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        ttl_seconds: float = 300,
        cleanup_interval: float = 60,
        on_evict: Optional[Callable[[K, V], None]] = None
    ):
        """
        Args:
            max_size: Maximum number of entries
            ttl_seconds: Time-to-live in seconds
            cleanup_interval: Seconds between automatic cleanups
            on_evict: Optional callback when entry is evicted
        """
        super().__init__(max_size, ttl_seconds, on_evict)
        
        self.cleanup_interval = cleanup_interval
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_cleanup = threading.Event()
    
    def start_auto_cleanup(self) -> None:
        """Start background cleanup thread"""
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            logger.warning("Auto cleanup already running")
            return
        
        self._stop_cleanup.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="cache-cleanup"
        )
        self._cleanup_thread.start()
        logger.info("Started auto cleanup thread")
    
    def stop_auto_cleanup(self) -> None:
        """Stop background cleanup thread"""
        if not self._cleanup_thread or not self._cleanup_thread.is_alive():
            return
        
        self._stop_cleanup.set()
        self._cleanup_thread.join(timeout=5.0)
        logger.info("Stopped auto cleanup thread")
    
    def _cleanup_loop(self) -> None:
        """Background cleanup loop"""
        while not self._stop_cleanup.is_set():
            try:
                self.cleanup_expired()
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
            
            # Wait for next cleanup or stop signal
            self._stop_cleanup.wait(timeout=self.cleanup_interval)
    
    def __del__(self):
        """Cleanup on deletion"""
        self.stop_auto_cleanup()


# Global cache instances for common use cases
_thumbnail_cache: Optional[TTLCache] = None
_metadata_cache: Optional[TTLCache] = None
_image_cache: Optional[TTLCache] = None


def get_thumbnail_cache() -> TTLCache:
    """Get global thumbnail cache"""
    global _thumbnail_cache
    if _thumbnail_cache is None:
        _thumbnail_cache = AutoCleanupCache(
            max_size=1000,
            ttl_seconds=300,  # 5 minutes
            cleanup_interval=60
        )
        _thumbnail_cache.start_auto_cleanup()
    return _thumbnail_cache


def get_metadata_cache() -> TTLCache:
    """Get global metadata cache"""
    global _metadata_cache
    if _metadata_cache is None:
        _metadata_cache = AutoCleanupCache(
            max_size=500,
            ttl_seconds=600,  # 10 minutes
            cleanup_interval=120
        )
        _metadata_cache.start_auto_cleanup()
    return _metadata_cache


def get_image_cache() -> TTLCache:
    """Get global image cache"""
    global _image_cache
    if _image_cache is None:
        _image_cache = AutoCleanupCache(
            max_size=100,  # Smaller because images are large
            ttl_seconds=1800,  # 30 minutes
            cleanup_interval=300
        )
        _image_cache.start_auto_cleanup()
    return _image_cache

