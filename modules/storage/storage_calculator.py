"""
Storage Calculator Module

Provides functions to calculate disk usage, directory sizes, and storage metrics
for the PACS client application.
"""

import os
import shutil
import time
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple, Optional
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class StorageMetrics:
    """Storage metrics data class"""
    drive_total: int  # bytes
    drive_used: int   # bytes
    drive_free: int   # bytes
    source_size: int  # bytes (DICOM files)
    thumbnails_size: int  # bytes
    attachments_size: int  # bytes
    free_percent: float  # percentage
    used_percent: float  # percentage
    
    def format_size(self, size_bytes: int) -> str:
        """Format bytes to human-readable string"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    
    @property
    def total_pacs_size(self) -> int:
        """Total size of all PACS data"""
        return self.source_size + self.thumbnails_size + self.attachments_size


# Cache for storage calculations
_storage_cache: Optional[StorageMetrics] = None
_cache_timestamp: float = 0
_cache_ttl: int = 300  # 5 minutes
_cache_lock = Lock()


def get_drive_info(path: Path) -> Tuple[int, int, int]:
    """
    Get drive statistics for the drive containing the specified path.
    
    Args:
        path: Path to check (can be file or directory)
        
    Returns:
        Tuple of (total, used, free) in bytes
        
    Raises:
        OSError: If path doesn't exist or stats cannot be retrieved
    """
    try:
        stat = shutil.disk_usage(str(path))
        return stat.total, stat.used, stat.free
    except Exception as e:
        logger.error(f"Failed to get drive info for {path}: {e}")
        raise


def calculate_directory_size(path: Path, progress_callback=None) -> int:
    """
    Recursively calculate directory size in bytes.
    
    Args:
        path: Directory path to calculate
        progress_callback: Optional callback function(current_file: str) for progress updates
        
    Returns:
        Total size in bytes
    """
    if not path.exists():
        logger.warning(f"Directory does not exist: {path}")
        return 0
    
    if not path.is_dir():
        logger.warning(f"Path is not a directory: {path}")
        return 0
    
    total = 0
    file_count = 0
    
    try:
        for entry in path.rglob('*'):
            try:
                if entry.is_file():
                    size = entry.stat().st_size
                    total += size
                    file_count += 1
                    
                    if progress_callback and file_count % 100 == 0:
                        progress_callback(str(entry))
                        
            except (PermissionError, OSError) as e:
                logger.debug(f"Skipping file {entry}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Error calculating directory size for {path}: {e}")
    
    logger.debug(f"Calculated size for {path}: {total} bytes ({file_count} files)")
    return total


def get_source_folder_size(progress_callback=None) -> int:
    """
    Calculate size of the source folder (DICOM files).
    
    Args:
        progress_callback: Optional progress callback
        
    Returns:
        Size in bytes
    """
    try:
        from PacsClient.utils.config import SOURCE_PATH
        return calculate_directory_size(SOURCE_PATH, progress_callback)
    except Exception as e:
        logger.error(f"Failed to calculate source folder size: {e}")
        return 0


def get_thumbnails_folder_size(progress_callback=None) -> int:
    """
    Calculate size of the thumbnails folder.
    
    Args:
        progress_callback: Optional progress callback
        
    Returns:
        Size in bytes
    """
    try:
        from PacsClient.utils.config import THUMBNAIL_PATH
        return calculate_directory_size(THUMBNAIL_PATH, progress_callback)
    except Exception as e:
        logger.error(f"Failed to calculate thumbnails folder size: {e}")
        return 0


def get_attachments_folder_size(progress_callback=None) -> int:
    """
    Calculate size of the attachments folder.
    
    Args:
        progress_callback: Optional progress callback
        
    Returns:
        Size in bytes
    """
    try:
        from PacsClient.utils.config import ATTACHMENT_PATH
        if ATTACHMENT_PATH.exists():
            return calculate_directory_size(ATTACHMENT_PATH, progress_callback)
        return 0
    except Exception as e:
        logger.error(f"Failed to calculate attachments folder size: {e}")
        return 0


def get_total_storage_metrics(use_cache: bool = True, progress_callback=None) -> StorageMetrics:
    """
    Calculate and return comprehensive storage metrics.
    
    Args:
        use_cache: If True, return cached metrics if available and not expired
        progress_callback: Optional progress callback for directory scanning
        
    Returns:
        StorageMetrics object with all calculated metrics
    """
    global _storage_cache, _cache_timestamp
    
    # Check cache
    if use_cache:
        with _cache_lock:
            if _storage_cache and (time.time() - _cache_timestamp) < _cache_ttl:
                logger.debug("Returning cached storage metrics")
                return _storage_cache
    
    logger.info("Calculating storage metrics...")
    
    try:
        from PacsClient.utils.config import SOURCE_PATH
        
        # Get drive info
        total, used, free = get_drive_info(SOURCE_PATH)
        free_percent = (free / total * 100) if total > 0 else 0
        used_percent = (used / total * 100) if total > 0 else 0
        
        logger.info(f"Drive stats: {total / (1024**3):.2f} GB total, {free / (1024**3):.2f} GB free ({free_percent:.1f}%)")
        
        # Calculate directory sizes
        logger.info("Calculating DICOM files size...")
        source_size = get_source_folder_size(progress_callback)
        
        logger.info("Calculating thumbnails size...")
        thumbnails_size = get_thumbnails_folder_size(progress_callback)
        
        logger.info("Calculating attachments size...")
        attachments_size = get_attachments_folder_size(progress_callback)
        
        metrics = StorageMetrics(
            drive_total=total,
            drive_used=used,
            drive_free=free,
            source_size=source_size,
            thumbnails_size=thumbnails_size,
            attachments_size=attachments_size,
            free_percent=free_percent,
            used_percent=used_percent
        )
        
        # Update cache
        with _cache_lock:
            _storage_cache = metrics
            _cache_timestamp = time.time()
        
        logger.info(f"Storage metrics calculated: DICOM={metrics.format_size(source_size)}, "
                   f"Thumbnails={metrics.format_size(thumbnails_size)}, "
                   f"Attachments={metrics.format_size(attachments_size)}, "
                   f"Total PACS={metrics.format_size(metrics.total_pacs_size)}")
        
        return metrics
        
    except Exception as e:
        logger.error(f"Failed to calculate storage metrics: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Return empty metrics on error
        return StorageMetrics(
            drive_total=0,
            drive_used=0,
            drive_free=0,
            source_size=0,
            thumbnails_size=0,
            attachments_size=0,
            free_percent=0,
            used_percent=0
        )


def clear_storage_cache():
    """Clear the storage metrics cache to force recalculation on next call"""
    global _storage_cache, _cache_timestamp
    with _cache_lock:
        _storage_cache = None
        _cache_timestamp = 0
    logger.debug("Storage cache cleared")


def set_cache_ttl(seconds: int):
    """
    Set the cache TTL (time-to-live) in seconds.
    
    Args:
        seconds: TTL in seconds (default is 300 = 5 minutes)
    """
    global _cache_ttl
    _cache_ttl = max(0, seconds)
    logger.debug(f"Cache TTL set to {_cache_ttl} seconds")
