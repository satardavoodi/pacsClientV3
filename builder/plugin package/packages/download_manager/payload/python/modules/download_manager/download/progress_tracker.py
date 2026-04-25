"""
Progress Tracker - Progress tracking and throttling (R35)

Manages progress updates with throttling to prevent UI freezing.
"""

import logging
import time
import threading
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from ..core.constants import PROGRESS_UPDATE_INTERVAL_MS

logger = logging.getLogger(__name__)


def _is_expected_cancellation_exception(exc: Exception) -> bool:
    text = str(exc or "").lower()
    name = type(exc).__name__.lower()
    return (
        name == "downloadcancelled"
        or "cancelled via process cancel event" in text
        or "download cancelled" in text
        or "preemption" in text
    )


@dataclass
class ProgressUpdate:
    """Progress update data"""
    study_uid: str
    series_number: str
    progress_percent: float
    downloaded_count: int
    total_count: int
    timestamp: datetime
    event_type: str = "progress"
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            object.__setattr__(self, 'metadata', {})


class ProgressTracker:
    """
    Progress tracking with throttling
    
    Features:
    - Progress update throttling (R35: 10 Hz max)
    - Accumulated updates between throttle intervals
    - Thread-safe operations
    - Event-based callbacks
    """
    
    def __init__(
        self,
        update_interval_ms: int = None,
        callback: Optional[Callable] = None
    ):
        """
        Initialize progress tracker
        
        Args:
            update_interval_ms: Update interval (default: 100ms = 10 Hz)
            callback: Progress callback function
        """
        self.update_interval_ms = update_interval_ms or PROGRESS_UPDATE_INTERVAL_MS
        self.callback = callback
        
        self.last_update_time = 0
        self.pending_updates: Dict[str, ProgressUpdate] = {}
        self.lock = threading.Lock()
        
        # Statistics
        self.total_updates_sent = 0
        self.total_updates_throttled = 0
        
        logger.info(f"✅ ProgressTracker initialized (interval: {self.update_interval_ms}ms)")
    
    def report_progress(
        self,
        study_uid: str,
        series_number: str,
        progress_percent: float,
        downloaded_count: int,
        total_count: int,
        **metadata
    ) -> None:
        """
        Report progress update (with throttling)
        
        Args:
            study_uid: Study UID
            series_number: Series number
            progress_percent: Progress percentage
            downloaded_count: Downloaded count
            total_count: Total count
            **metadata: Additional metadata
        """
        with self.lock:
            # Create update object
            update = ProgressUpdate(
                study_uid=study_uid,
                series_number=series_number,
                progress_percent=progress_percent,
                downloaded_count=downloaded_count,
                total_count=total_count,
                timestamp=datetime.now(),
                metadata=metadata
            )
            
            # Store as pending
            self.pending_updates[study_uid] = update
            
            # Check if should send update (throttling - R35)
            if self._should_send_update():
                self._flush_pending_updates()
    
    def _should_send_update(self) -> bool:
        """
        Check if enough time has passed since last update (R35)
        
        Returns:
            True if should send, False otherwise
        """
        current_time = time.time() * 1000  # milliseconds
        time_since_last = current_time - self.last_update_time
        
        return time_since_last >= self.update_interval_ms
    
    def _flush_pending_updates(self) -> None:
        """Flush all pending updates to callback"""
        if not self.callback or not self.pending_updates:
            return
        
        # Send all pending updates
        for update in self.pending_updates.values():
            try:
                self.callback(
                    update.event_type,
                    update.series_number,
                    update.progress_percent,
                    update.downloaded_count,
                    update.total_count,
                    study_uid=update.study_uid,
                    **update.metadata
                )
                self.total_updates_sent += 1
            
            except Exception as e:
                if _is_expected_cancellation_exception(e):
                    logger.info(f"⏸️ Progress callback cancelled: {e}")
                else:
                    logger.error(f"❌ Progress callback error: {e}")
        
        # Clear pending
        self.pending_updates.clear()
        self.last_update_time = time.time() * 1000
    
    def force_update(self, study_uid: Optional[str] = None) -> None:
        """
        Force immediate update (bypass throttling)
        
        Args:
            study_uid: Specific study UID to update, or None for all
        """
        with self.lock:
            if study_uid and study_uid in self.pending_updates:
                update = self.pending_updates[study_uid]
                if self.callback:
                    try:
                        self.callback(
                            update.event_type,
                            update.series_number,
                            update.progress_percent,
                            update.downloaded_count,
                            update.total_count,
                            study_uid=update.study_uid,
                            **update.metadata
                        )
                    except Exception as e:
                        if _is_expected_cancellation_exception(e):
                            logger.info(f"⏸️ Progress callback cancelled: {e}")
                        else:
                            logger.error(f"❌ Progress callback error: {e}")
                del self.pending_updates[study_uid]
            else:
                # Flush all pending
                self._flush_pending_updates()
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get tracker statistics
        
        Returns:
            Statistics dictionary
        """
        with self.lock:
            throttle_rate = 0.0
            if self.total_updates_sent + self.total_updates_throttled > 0:
                throttle_rate = (
                    self.total_updates_throttled /
                    (self.total_updates_sent + self.total_updates_throttled) * 100
                )
            
            return {
                'total_updates_sent': self.total_updates_sent,
                'total_updates_throttled': self.total_updates_throttled,
                'throttle_rate': throttle_rate,
                'pending_updates': len(self.pending_updates),
                'update_interval_ms': self.update_interval_ms,
            }
