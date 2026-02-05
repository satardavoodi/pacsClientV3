#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Connection Health Monitor for Download Manager
Monitors network quality and adapts download behavior
"""

import time
import logging
import random
from typing import List, Dict, Tuple
from collections import deque

logger = logging.getLogger(__name__)


class ConnectionHealthMonitor:
    """
    Monitor connection health and provide adaptive recommendations
    
    Features:
    - Tracks download speeds over rolling window
    - Tracks error rates
    - Recommends batch size adjustments
    - Provides connection health status
    """
    
    def __init__(self, window_size: int = 10):
        """
        Initialize connection health monitor
        
        Args:
            window_size: Number of recent samples to track
        """
        self.window_size = window_size
        self.recent_speeds = deque(maxlen=window_size)  # Bytes per second
        self.error_count = 0
        self.success_count = 0
        self.total_downloads = 0
        self.total_bytes = 0
        self.total_time = 0.0
        
        # Health thresholds
        self.min_healthy_speed = 1024  # 1 KB/s minimum
        self.max_error_rate = 0.3  # 30% error rate threshold
        self.error_decay_rate = 0.5  # Decay errors over time
        
        logger.info("📊 Connection health monitor initialized")
    
    def record_download(self, bytes_downloaded: int, duration: float):
        """
        Record successful download
        
        Args:
            bytes_downloaded: Number of bytes downloaded
            duration: Time taken in seconds
        """
        if duration <= 0:
            duration = 0.001  # Avoid division by zero
        
        speed = bytes_downloaded / duration
        self.recent_speeds.append(speed)
        self.success_count += 1
        self.total_downloads += 1
        self.total_bytes += bytes_downloaded
        self.total_time += duration
        
        # Decay error count on success
        self.error_count = max(0, self.error_count - self.error_decay_rate)
        
        logger.debug(f"✅ Download recorded: {bytes_downloaded} bytes in {duration:.2f}s ({speed/1024:.1f} KB/s)")
    
    def record_error(self, severity: int = 3):
        """
        Record download error
        
        Args:
            severity: Error severity (1-5, higher = more severe)
        """
        self.error_count += severity
        self.total_downloads += 1
        
        logger.debug(f"❌ Error recorded (severity: {severity}, total errors: {self.error_count:.1f})")
    
    def get_average_speed(self) -> float:
        """
        Get average download speed from recent samples
        
        Returns:
            Average speed in bytes per second
        """
        if not self.recent_speeds:
            return 0.0
        
        return sum(self.recent_speeds) / len(self.recent_speeds)
    
    def get_error_rate(self) -> float:
        """
        Get current error rate
        
        Returns:
            Error rate (0.0 to 1.0)
        """
        if self.total_downloads == 0:
            return 0.0
        
        # Weighted error rate (recent errors count more)
        effective_errors = min(self.error_count, self.total_downloads)
        return effective_errors / self.total_downloads
    
    def is_healthy(self) -> bool:
        """
        Check if connection is healthy
        
        Returns:
            True if connection is healthy
        """
        # Not enough data yet - assume healthy
        if len(self.recent_speeds) < 3:
            return True
        
        # Check error rate
        error_rate = self.get_error_rate()
        if error_rate > self.max_error_rate:
            logger.debug(f"⚠️ Unhealthy: High error rate ({error_rate:.1%})")
            return False
        
        # Check average speed
        avg_speed = self.get_average_speed()
        if avg_speed < self.min_healthy_speed:
            logger.debug(f"⚠️ Unhealthy: Low speed ({avg_speed/1024:.1f} KB/s)")
            return False
        
        return True
    
    def should_throttle(self) -> bool:
        """
        Check if downloads should be throttled
        
        Returns:
            True if throttling recommended
        """
        error_rate = self.get_error_rate()
        return error_rate > (self.max_error_rate / 2)  # Throttle at 15% error rate
    
    def get_recommended_batch_size(self, current_size: int, min_size: int = 1, max_size: int = 50) -> int:
        """
        Get recommended batch size based on connection health
        
        Args:
            current_size: Current batch size
            min_size: Minimum batch size
            max_size: Maximum batch size
            
        Returns:
            Recommended batch size
        """
        if not self.is_healthy():
            # Poor connection - reduce batch size aggressively
            new_size = max(min_size, current_size // 2)
            logger.info(f"📉 Reducing batch size: {current_size} → {new_size} (unhealthy connection)")
            return new_size
        
        if self.should_throttle():
            # Moderate issues - maintain current size
            return current_size
        
        # Healthy connection - can increase batch size gradually
        avg_speed = self.get_average_speed()
        if avg_speed > self.min_healthy_speed * 10:  # >10 KB/s
            new_size = min(max_size, current_size + 1)
            if new_size > current_size:
                logger.info(f"📈 Increasing batch size: {current_size} → {new_size} (healthy connection)")
            return new_size
        
        return current_size
    
    def get_statistics(self) -> Dict:
        """
        Get statistics about connection health
        
        Returns:
            Dict with statistics
        """
        avg_speed = self.get_average_speed()
        error_rate = self.get_error_rate()
        
        return {
            'average_speed_bps': avg_speed,
            'average_speed_kbps': avg_speed / 1024,
            'error_rate': error_rate,
            'error_count': self.error_count,
            'success_count': self.success_count,
            'total_downloads': self.total_downloads,
            'total_bytes': self.total_bytes,
            'total_time': self.total_time,
            'is_healthy': self.is_healthy(),
            'should_throttle': self.should_throttle(),
            'samples_count': len(self.recent_speeds)
        }
    
    def reset(self):
        """Reset all statistics"""
        self.recent_speeds.clear()
        self.error_count = 0
        self.success_count = 0
        self.total_downloads = 0
        self.total_bytes = 0
        self.total_time = 0.0
        logger.info("🔄 Connection health monitor reset")


class AdaptiveBatchSizer:
    """
    Adaptive batch sizer that adjusts batch size based on connection health
    """
    
    def __init__(self, initial_size: int = 10, min_size: int = 1, max_size: int = 50):
        """
        Initialize adaptive batch sizer
        
        Args:
            initial_size: Initial batch size
            min_size: Minimum batch size
            max_size: Maximum batch size
        """
        self.batch_size = initial_size
        self.min_size = min_size
        self.max_size = max_size
        self.health_monitor = ConnectionHealthMonitor()
        
        logger.info(f"📏 Adaptive batch sizer initialized (size: {initial_size}, range: {min_size}-{max_size})")
    
    def get_batch_size(self) -> int:
        """
        Get current recommended batch size
        
        Returns:
            Recommended batch size
        """
        self.batch_size = self.health_monitor.get_recommended_batch_size(
            self.batch_size, self.min_size, self.max_size
        )
        return self.batch_size
    
    def record_download(self, bytes_downloaded: int, duration: float):
        """Record successful download"""
        self.health_monitor.record_download(bytes_downloaded, duration)
    
    def record_error(self, severity: int = 3):
        """Record download error"""
        self.health_monitor.record_error(severity)
    
    def get_statistics(self) -> Dict:
        """Get statistics"""
        stats = self.health_monitor.get_statistics()
        stats['current_batch_size'] = self.batch_size
        stats['min_batch_size'] = self.min_size
        stats['max_batch_size'] = self.max_size
        return stats


def calculate_retry_delay(attempt: int, base_delay: float = 2.0, max_delay: float = 60.0) -> float:
    """
    Calculate retry delay with exponential backoff and jitter
    
    Args:
        attempt: Retry attempt number (0-based)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        
    Returns:
        Delay in seconds
    """
    # Exponential backoff: 2s, 4s, 8s, 16s, 32s, 60s (capped)
    delay = min(base_delay * (2 ** attempt), max_delay)
    
    # Add jitter (±20%) to prevent thundering herd
    jitter = delay * 0.2 * (random.random() * 2 - 1)
    final_delay = max(0.1, delay + jitter)  # Never less than 0.1s
    
    logger.debug(f"⏱️ Retry delay calculated: attempt {attempt} → {final_delay:.2f}s")
    return final_delay
