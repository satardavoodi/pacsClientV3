"""
File Manager - File system operations with caching (R38)

Handles file operations with filesystem caching to avoid repeated scans.
"""

import logging
import os
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
import threading
import time

from ..core.constants import DICOM_FILE_EXTENSION

logger = logging.getLogger(__name__)


class FileManager:
    """
    File system operations manager
    
    Features:
    - Filesystem caching (R38: scan once per series) with TTL eviction
    - Thread-safe operations
    - Automatic directory creation
    - File validation
    """
    
    def __init__(self, cache_ttl_seconds: int = 3600):
        """
        Initialize file manager
        
        Args:
            cache_ttl_seconds: Cache time-to-live in seconds (default: 1 hour)
        """
        # CRITICAL FIX: Add TTL to cache to prevent unbounded growth in high-frequency loops
        self._cache: Dict[str, Set[str]] = {}  # dir_path -> set of filenames
        self._cache_timestamps: Dict[str, float] = {}  # dir_path -> timestamp
        self._cache_ttl = cache_ttl_seconds
        self._cache_lock = threading.Lock()
        logger.info(f"✅ FileManager initialized (cache TTL: {cache_ttl_seconds}s)")
    
    def scan_directory(
        self,
        directory: Path,
        use_cache: bool = True
    ) -> List[str]:
        """
        Scan directory for DICOM files with caching (R38)
        
        Args:
            directory: Directory to scan
            use_cache: Whether to use cached results
            
        Returns:
            List of DICOM filenames
        """
        dir_str = str(directory)
        current_time = time.time()
        
        # Check cache (with TTL expiration)
        if use_cache:
            with self._cache_lock:
                if dir_str in self._cache:
                    cache_age = current_time - self._cache_timestamps.get(dir_str, 0)
                    if cache_age < self._cache_ttl:
                        logger.debug(f"📋 Cache hit: {directory.name} (age: {cache_age:.1f}s)")
                        return list(self._cache[dir_str])
                    else:
                        # Cache expired, remove it
                        logger.debug(f"🗑️ Cache expired for {directory.name} (age: {cache_age:.1f}s > {self._cache_ttl}s)")
                        del self._cache[dir_str]
                        del self._cache_timestamps[dir_str]
        
        # Scan directory
        if not directory.exists():
            return []
        
        try:
            files = [
                f for f in os.listdir(directory)
                if f.endswith(DICOM_FILE_EXTENSION)
            ]
            
            # Cache results with timestamp for TTL tracking
            with self._cache_lock:
                self._cache[dir_str] = set(files)
                self._cache_timestamps[dir_str] = time.time()
            
            logger.debug(f"📁 Scanned: {directory.name} ({len(files)} files)")
            
            return files
        
        except Exception as e:
            logger.error(f"❌ Directory scan failed: {e}")
            return []
    
    def invalidate_cache(self, directory: Optional[Path] = None) -> None:
        """
        Invalidate filesystem cache
        
        Args:
            directory: Specific directory to invalidate, or None for all
        """
        with self._cache_lock:
            if directory:
                dir_str = str(directory)
                if dir_str in self._cache:
                    del self._cache[dir_str]
                    logger.debug(f"🔄 Cache invalidated: {directory.name}")
            else:
                self._cache.clear()
                logger.info("🔄 All cache invalidated")
    
    def ensure_directory(self, directory: Path) -> bool:
        """
        Ensure directory exists (create if needed)
        
        Args:
            directory: Directory path
            
        Returns:
            True if successful, False otherwise
        """
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"❌ Could not create directory: {e}")
            return False
    
    def count_existing_files(self, directory: Path) -> int:
        """
        Count existing DICOM files in directory
        
        Args:
            directory: Directory to count
            
        Returns:
            Number of DICOM files
        """
        return len(self.scan_directory(directory, use_cache=True))
    
    def file_exists(self, file_path: Path) -> bool:
        """
        Check if file exists and is valid
        
        Args:
            file_path: File path to check
            
        Returns:
            True if exists and valid, False otherwise
        """
        if not file_path.exists():
            return False
        
        # Validate file size (min 128 bytes for valid DICOM)
        try:
            return file_path.stat().st_size >= 128
        except:
            return False
