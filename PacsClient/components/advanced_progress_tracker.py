# -*- coding: utf-8 -*-

"""
Advanced Progress Tracker inspired by pySmartDL
ردیاب پیشرفت پیشرفته الهام گرفته از pySmartDL
"""

import time
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from collections import deque
import logging

logger = logging.getLogger(__name__)

@dataclass
class DownloadStats:
    """Statistics for download progress"""
    total_size: int = 0
    downloaded_size: int = 0
    start_time: float = 0
    current_speed: float = 0
    average_speed: float = 0
    eta_seconds: float = 0
    progress_percent: float = 0
    active_connections: int = 0
    failed_connections: int = 0

class AdvancedProgressTracker:
    """
    Advanced progress tracker with pySmartDL-style features
    """
    
    def __init__(self, update_interval: float = 0.5):
        self.update_interval = update_interval
        self.stats = DownloadStats()
        self.speed_history = deque(maxlen=10)  # Last 10 speed measurements
        self.callbacks: List[Callable] = []
        self.lock = threading.Lock()
        self.running = False
        self.update_thread = None
        
    def add_callback(self, callback: Callable[[DownloadStats], None]):
        """Add progress callback"""
        with self.lock:
            self.callbacks.append(callback)
    
    def remove_callback(self, callback: Callable):
        """Remove progress callback"""
        with self.lock:
            if callback in self.callbacks:
                self.callbacks.remove(callback)
    
    def start_tracking(self, total_size: int):
        """Start progress tracking"""
        with self.lock:
            self.stats = DownloadStats(
                total_size=total_size,
                start_time=time.time()
            )
            self.speed_history.clear()
            self.running = True
            
        # Start update thread
        if not self.update_thread or not self.update_thread.is_alive():
            self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
            self.update_thread.start()
    
    def stop_tracking(self):
        """Stop progress tracking"""
        with self.lock:
            self.running = False
    
    def update_progress(self, downloaded_size: int, active_connections: int = 0, failed_connections: int = 0):
        """Update download progress"""
        with self.lock:
            current_time = time.time()
            elapsed_time = current_time - self.stats.start_time
            
            # Update basic stats
            self.stats.downloaded_size = downloaded_size
            self.stats.active_connections = active_connections
            self.stats.failed_connections = failed_connections
            
            if self.stats.total_size > 0:
                self.stats.progress_percent = (downloaded_size / self.stats.total_size) * 100
            
            # Calculate speeds
            if elapsed_time > 0:
                current_speed = downloaded_size / elapsed_time
                self.stats.current_speed = current_speed
                
                # Add to speed history for average calculation
                self.speed_history.append(current_speed)
                self.stats.average_speed = sum(self.speed_history) / len(self.speed_history)
                
                # Calculate ETA
                remaining_size = self.stats.total_size - downloaded_size
                if self.stats.average_speed > 0:
                    self.stats.eta_seconds = remaining_size / self.stats.average_speed
    
    def _update_loop(self):
        """Background update loop"""
        while self.running:
            try:
                with self.lock:
                    # Notify callbacks
                    for callback in self.callbacks:
                        try:
                            callback(self.stats)
                        except Exception as e:
                            logger.warning(f"⚠️ Progress callback error: {e}")
                
                time.sleep(self.update_interval)
            except Exception as e:
                logger.error(f"❌ Progress tracker update error: {e}")
    
    def get_stats(self) -> DownloadStats:
        """Get current download statistics"""
        with self.lock:
            return self.stats
    
    def format_speed(self, speed_bps: float) -> str:
        """Format speed in human readable format"""
        if speed_bps < 1024:
            return f"{speed_bps:.1f} B/s"
        elif speed_bps < 1024 * 1024:
            return f"{speed_bps / 1024:.1f} KB/s"
        elif speed_bps < 1024 * 1024 * 1024:
            return f"{speed_bps / (1024 * 1024):.1f} MB/s"
        else:
            return f"{speed_bps / (1024 * 1024 * 1024):.1f} GB/s"
    
    def format_size(self, size_bytes: int) -> str:
        """Format size in human readable format"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    def format_time(self, seconds: float) -> str:
        """Format time in human readable format"""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds // 60:.0f}m {seconds % 60:.0f}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours:.0f}h {minutes:.0f}m"
    
    def get_progress_string(self) -> str:
        """Get formatted progress string"""
        stats = self.get_stats()
        
        progress_bar = self._create_progress_bar(stats.progress_percent)
        speed_str = self.format_speed(stats.current_speed)
        size_str = f"{self.format_size(stats.downloaded_size)}/{self.format_size(stats.total_size)}"
        eta_str = self.format_time(stats.eta_seconds) if stats.eta_seconds > 0 else "∞"
        
        return f"{progress_bar} {stats.progress_percent:.1f}% | {size_str} | {speed_str} | ETA: {eta_str}"
    
    def _create_progress_bar(self, percent: float, width: int = 30) -> str:
        """Create ASCII progress bar"""
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}]"


class MultiConnectionProgressTracker(AdvancedProgressTracker):
    """
    Progress tracker for multiple connections (pySmartDL style)
    """
    
    def __init__(self, update_interval: float = 0.5):
        super().__init__(update_interval)
        self.connection_stats: Dict[int, Dict[str, Any]] = {}
    
    def update_connection_progress(self, connection_id: int, downloaded_size: int, 
                                 connection_speed: float, status: str = "active"):
        """Update progress for specific connection"""
        with self.lock:
            self.connection_stats[connection_id] = {
                "downloaded_size": downloaded_size,
                "speed": connection_speed,
                "status": status,
                "last_update": time.time()
            }
            
            # Calculate total progress
            total_downloaded = sum(conn["downloaded_size"] for conn in self.connection_stats.values())
            active_connections = sum(1 for conn in self.connection_stats.values() if conn["status"] == "active")
            failed_connections = sum(1 for conn in self.connection_stats.values() if conn["status"] == "failed")
            
            self.update_progress(total_downloaded, active_connections, failed_connections)
    
    def get_connection_stats(self) -> Dict[int, Dict[str, Any]]:
        """Get statistics for all connections"""
        with self.lock:
            return self.connection_stats.copy()
    
    def get_detailed_progress_string(self) -> str:
        """Get detailed progress string with connection info"""
        base_progress = self.get_progress_string()
        stats = self.get_stats()
        
        connection_info = f"Connections: {stats.active_connections} active, {stats.failed_connections} failed"
        
        return f"{base_progress} | {connection_info}"
