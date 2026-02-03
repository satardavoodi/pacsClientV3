"""
Progress Throttler Module
Prevents UI overload by throttling high-frequency progress updates.
"""

import time
from typing import Dict, Callable, Any, Optional
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class ProgressThrottler:
    """
    Throttles progress updates to prevent UI overload.
    
    Instead of updating UI 100+ times per second (one per image),
    this limits updates to a reasonable frequency (e.g., 10 Hz).
    
    Benefits:
    - Reduces UI lag
    - Lower CPU usage
    - Smoother visual updates
    - Better battery life (for laptops)
    """
    
    def __init__(self, max_updates_per_second: int = 10):
        """
        Initialize throttler
        
        Args:
            max_updates_per_second: Maximum update frequency (default 10 Hz)
        """
        self.interval = 1.0 / max_updates_per_second
        self.last_update: Dict[str, float] = {}
        self.pending_updates: Dict[str, dict] = {}
        self.force_next_update: set = set()
        
        logger.debug(f"ProgressThrottler initialized: max {max_updates_per_second} updates/sec")
    
    def should_update(self, key: str, force: bool = False) -> bool:
        """
        Check if an update should be sent
        
        Args:
            key: Unique identifier for this update stream (e.g., study_uid)
            force: Force update regardless of throttling
        
        Returns:
            True if update should be sent, False to skip
        """
        if force or key in self.force_next_update:
            self.last_update[key] = time.time()
            self.force_next_update.discard(key)
            return True
        
        now = time.time()
        last = self.last_update.get(key, 0)
        
        if now - last >= self.interval:
            self.last_update[key] = now
            return True
        
        return False
    
    def queue_update(self, key: str, update_data: dict):
        """
        Queue an update for later delivery
        
        Args:
            key: Unique identifier
            update_data: Data to send when update fires
        """
        self.pending_updates[key] = update_data
    
    def get_pending_update(self, key: str) -> Optional[dict]:
        """
        Get and clear pending update
        
        Args:
            key: Unique identifier
        
        Returns:
            Pending update data or None
        """
        return self.pending_updates.pop(key, None)
    
    def force_update(self, key: str):
        """
        Force next update to go through regardless of throttling
        
        Args:
            key: Unique identifier
        """
        self.force_next_update.add(key)
    
    def reset(self, key: Optional[str] = None):
        """
        Reset throttling state
        
        Args:
            key: If provided, reset only this key. Otherwise reset all.
        """
        if key:
            self.last_update.pop(key, None)
            self.pending_updates.pop(key, None)
            self.force_next_update.discard(key)
        else:
            self.last_update.clear()
            self.pending_updates.clear()
            self.force_next_update.clear()
    
    def get_stats(self) -> dict:
        """Get throttler statistics"""
        return {
            'tracked_keys': len(self.last_update),
            'pending_updates': len(self.pending_updates),
            'forced_updates': len(self.force_next_update),
            'update_interval': self.interval
        }


class BatchProgressAggregator:
    """
    Aggregates progress from multiple series into study-level progress.
    Works with throttler to provide smooth, batched updates.
    """
    
    def __init__(self, throttler: Optional[ProgressThrottler] = None):
        """
        Initialize aggregator
        
        Args:
            throttler: Optional ProgressThrottler instance
        """
        self.throttler = throttler or ProgressThrottler()
        self.series_progress: Dict[str, Dict[str, int]] = defaultdict(dict)
        self.series_totals: Dict[str, Dict[str, int]] = defaultdict(dict)
        
    def update_series_progress(self, study_uid: str, series_uid: str, 
                               current: int, total: int) -> Optional[dict]:
        """
        Update progress for a series
        
        Args:
            study_uid: Study identifier
            series_uid: Series identifier
            current: Current downloaded count
            total: Total count
        
        Returns:
            Aggregated study progress if update should be sent, None otherwise
        """
        # Store series progress
        self.series_progress[study_uid][series_uid] = current
        self.series_totals[study_uid][series_uid] = total
        
        # Calculate study-level progress
        study_current = sum(self.series_progress[study_uid].values())
        study_total = sum(self.series_totals[study_uid].values())
        study_percent = (study_current / study_total * 100) if study_total > 0 else 0
        
        # Check if we should send update
        if self.throttler.should_update(study_uid):
            return {
                'study_uid': study_uid,
                'current': study_current,
                'total': study_total,
                'percent': study_percent,
                'series_progress': dict(self.series_progress[study_uid])
            }
        else:
            # Queue for later
            self.throttler.queue_update(study_uid, {
                'study_uid': study_uid,
                'current': study_current,
                'total': study_total,
                'percent': study_percent,
                'series_progress': dict(self.series_progress[study_uid])
            })
            return None
    
    def force_update(self, study_uid: str) -> dict:
        """
        Force an immediate update for a study
        
        Args:
            study_uid: Study identifier
        
        Returns:
            Current aggregated progress
        """
        self.throttler.force_update(study_uid)
        
        study_current = sum(self.series_progress[study_uid].values())
        study_total = sum(self.series_totals[study_uid].values())
        study_percent = (study_current / study_total * 100) if study_total > 0 else 0
        
        return {
            'study_uid': study_uid,
            'current': study_current,
            'total': study_total,
            'percent': study_percent,
            'series_progress': dict(self.series_progress[study_uid])
        }
    
    def reset_study(self, study_uid: str):
        """Reset progress tracking for a study"""
        self.series_progress.pop(study_uid, None)
        self.series_totals.pop(study_uid, None)
        self.throttler.reset(study_uid)


# Global throttler instance for convenience
_global_throttler = None

def get_global_progress_throttler() -> ProgressThrottler:
    """Get or create global progress throttler instance"""
    global _global_throttler
    if _global_throttler is None:
        from .priority_config import PriorityRules
        _global_throttler = ProgressThrottler(
            max_updates_per_second=PriorityRules.PROGRESS_UPDATE_MAX_HZ
        )
    return _global_throttler
