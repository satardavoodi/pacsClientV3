"""
Thumbnail Cache - In-memory thumbnail caching for fast access

Caches thumbnails to avoid repeated file I/O operations.
"""

import logging
import threading
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class ThumbnailCache:
    """
    In-memory cache for thumbnails
    
    Features:
    - LRU eviction policy
    - Size-based limits
    - Thread-safe operations
    - Automatic cleanup
    """
    
    def __init__(self, max_size_mb: int = 50):
        """
        Initialize thumbnail cache
        
        Args:
            max_size_mb: Maximum cache size in megabytes
        """
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.cache: Dict[str, tuple[bytes, datetime]] = {}  # path -> (data, timestamp)
        self.current_size_bytes = 0
        self.lock = threading.Lock()
        
        logger.info(f"✅ ThumbnailCache initialized (max: {max_size_mb} MB)")
    
    def get(self, thumbnail_path: Path) -> Optional[bytes]:
        """
        Get thumbnail from cache
        
        Args:
            thumbnail_path: Path to thumbnail
            
        Returns:
            Thumbnail bytes or None if not cached
        """
        with self.lock:
            path_str = str(thumbnail_path)
            if path_str in self.cache:
                data, timestamp = self.cache[path_str]
                # Update timestamp (LRU)
                self.cache[path_str] = (data, datetime.now())
                logger.debug(f"📋 Cache hit: {thumbnail_path.name}")
                return data
            
            logger.debug(f"❌ Cache miss: {thumbnail_path.name}")
            return None
    
    def put(self, thumbnail_path: Path, data: bytes) -> None:
        """
        Add thumbnail to cache
        
        Args:
            thumbnail_path: Path to thumbnail
            data: Thumbnail bytes
        """
        with self.lock:
            path_str = str(thumbnail_path)
            data_size = len(data)
            
            # Check if need to evict
            while self.current_size_bytes + data_size > self.max_size_bytes and self.cache:
                self._evict_oldest()
            
            # Add to cache
            self.cache[path_str] = (data, datetime.now())
            self.current_size_bytes += data_size
            
            logger.debug(
                f"💾 Cached: {thumbnail_path.name} "
                f"({data_size / 1024:.1f} KB, total: {self.current_size_bytes / 1024 / 1024:.1f} MB)"
            )
    
    def _evict_oldest(self) -> None:
        """Evict oldest cache entry (LRU)"""
        if not self.cache:
            return
        
        # Find oldest entry
        oldest_path = min(self.cache.keys(), key=lambda k: self.cache[k][1])
        data, timestamp = self.cache.pop(oldest_path)
        self.current_size_bytes -= len(data)
        
        logger.debug(f"🗑️ Evicted: {Path(oldest_path).name}")
    
    def clear(self) -> None:
        """Clear all cache"""
        with self.lock:
            self.cache.clear()
            self.current_size_bytes = 0
            logger.info("🧹 Cache cleared")
    
    def get_stats(self) -> Dict[str, any]:
        """
        Get cache statistics
        
        Returns:
            Statistics dictionary
        """
        with self.lock:
            return {
                'cached_count': len(self.cache),
                'current_size_mb': self.current_size_bytes / 1024 / 1024,
                'max_size_mb': self.max_size_bytes / 1024 / 1024,
                'utilization_percent': (self.current_size_bytes / self.max_size_bytes * 100) if self.max_size_bytes > 0 else 0
            }
