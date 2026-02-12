"""
Download State Store - Unified state management with observer pattern

Single source of truth for all download state.
Automatic synchronization to database, UI, and priority manager via observers.
Thread-safe operations with history tracking.
"""

import threading
import logging
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import replace

from ..core.models import DownloadTask, DownloadState, StateChange
from ..core.enums import DownloadStatus, DownloadPriority
from ..core.exceptions import StateError
from .state_machine import DownloadStateMachine

logger = logging.getLogger(__name__)


class DownloadStateStore:
    """
    Unified state management with observer pattern
    
    Features:
    - Thread-safe operations (RLock)
    - Observer pattern for automatic synchronization
    - State change history (last 1000 changes)
    - Query methods for filtering and searching
    
    Usage:
        store = DownloadStateStore()
        
        # Register observers
        store.register_observer(DatabaseObserver())
        store.register_observer(UIObserver())
        
        # Create state
        state = store.create(download_task)
        
        # Update state (observers auto-notified)
        store.update(study_uid, status=DownloadStatus.DOWNLOADING)
        store.update(study_uid, progress_percent=45.0, downloaded_count=100)
    """
    
    def __init__(self):
        self._states: Dict[str, DownloadState] = {}
        self._observers: List['StateObserver'] = []
        self._lock = threading.RLock()
        self._history: deque[StateChange] = deque(maxlen=1000)
        logger.info("✅ DownloadStateStore initialized")
    
    def create(self, task: DownloadTask) -> DownloadState:
        """
        Create new download state from task
        
        Args:
            task: Download task definition
            
        Returns:
            Created download state
            
        Raises:
            StateError: If state already exists for study_uid
        """
        with self._lock:
            if task.study_uid in self._states:
                raise StateError(f"State already exists for {task.study_uid}")
            
            # Create new state
            state = DownloadState(
                study_uid=task.study_uid,
                status=DownloadStatus.PENDING,
                priority=task.priority,
                total_count=task.total_image_count,
                patient_name=task.patient_name,
                study_description=task.description,
                start_time=datetime.now(),
                last_update=datetime.now()
            )
            
            self._states[task.study_uid] = state
            
            # Record in history
            change = StateChange(
                study_uid=task.study_uid,
                timestamp=datetime.now(),
                changes={'created': True},
                old_values={}
            )
            self._history.append(change)
            
            # Notify observers
            self._notify_observers('created', task.study_uid, state)
            
            logger.info(f"✅ Created state for {task.patient_name} ({task.study_uid[:40]}...)")
            
            return state
    
    def update(self, study_uid: str, **changes) -> None:
        """
        Update download state and auto-notify observers

        Implements:
        - R8: Valid state transitions enforced via StateMachine
        - R10: Auto-recovery from invalid states
        - R9: Prevent updates to terminal states

        Args:
            study_uid: Study UID to update
            **changes: Fields to update (status=..., progress_percent=..., etc.)

        Raises:
            StateError: If study_uid not found
        """
        with self._lock:
            state = self._states.get(study_uid)
            if not state:
                raise StateError(f"Unknown study_uid: {study_uid}")

            # R9: Check if current state is terminal before allowing any changes
            if DownloadStateMachine.is_terminal_state(state.status):
                # Only allow updates to non-status fields for terminal states
                non_status_changes = {k: v for k, v in changes.items() if k != 'status'}

                if len(changes) > len(non_status_changes):
                    # Status change attempted on terminal state
                    new_status = changes.get('status')
                    
                    # Only log warning if trying to change to a different status
                    # (don't warn if trying to set to same terminal status)
                    if new_status and new_status != state.status:
                        logger.warning(
                            f"⚠️ Cannot change terminal state {state.status.value} - ignoring status change to {new_status.value}"
                        )

                    # Remove status from changes to prevent invalid update
                    if 'status' in changes:
                        del changes['status']

                if not non_status_changes:
                    # No valid changes to make, return early
                    return

                # Only proceed with non-status changes
                changes = non_status_changes

            # Record old values for history
            old_values = {}
            for key in changes.keys():
                if hasattr(state, key):
                    old_values[key] = getattr(state, key)

            # R8: Validate state transition if status is being changed
            if 'status' in changes:
                new_status = changes['status']
                old_status = state.status

                if not DownloadStateMachine.is_valid_transition(old_status, new_status):
                    # R10: Attempt auto-recovery
                    logger.warning(
                        f"⚠️ Invalid transition: {old_status.value} → {new_status.value} "
                        f"for {study_uid[:40]}..."
                    )

                    # Check if we can auto-recovery
                    if DownloadStateMachine.is_terminal_state(old_status):
                        # Only log warning if trying to change to a different status
                        # (don't warn if trying to set to same terminal status)
                        new_status = changes.get('status')
                        if new_status and new_status != old_status:
                            logger.warning(
                                f"⚠️ Cannot change terminal state {old_status.value} - ignoring"
                            )
                        # Remove status from changes to prevent invalid update
                        del changes['status']
                        if 'status' in old_values:
                            del old_values['status']
                    else:
                        # Log but allow the transition (for flexibility)
                        logger.warning(
                            f"⚠️ Allowing unusual transition for recovery"
                        )

            # Apply changes
            for key, value in changes.items():
                if hasattr(state, key):
                    setattr(state, key, value)
                else:
                    logger.warning(f"⚠️ Unknown state field: {key}")

            # Update last_update timestamp
            state.last_update = datetime.now()

            # Record in history
            change = StateChange(
                study_uid=study_uid,
                timestamp=datetime.now(),
                changes=changes,
                old_values=old_values
            )
            self._history.append(change)

            # Notify observers for each field change
            for field_name, new_value in changes.items():
                old_value = old_values.get(field_name)
                self._notify_observers('updated', study_uid, state, field_name, old_value, new_value)

            logger.debug(f"Updated state for {study_uid[:40]}...: {changes}")
    
    def get(self, study_uid: str) -> Optional[DownloadState]:
        """
        Get current state (thread-safe)
        
        Args:
            study_uid: Study UID
            
        Returns:
            Download state or None if not found
        """
        with self._lock:
            return self._states.get(study_uid)
    
    def get_all(self) -> List[DownloadState]:
        """
        Get all states (thread-safe copy)
        
        Returns:
            List of all download states
        """
        with self._lock:
            return list(self._states.values())
    
    def exists(self, study_uid: str) -> bool:
        """
        Check if state exists
        
        Args:
            study_uid: Study UID to check
            
        Returns:
            True if exists, False otherwise
        """
        with self._lock:
            return study_uid in self._states
    
    def remove(self, study_uid: str) -> None:
        """
        Remove state from store
        
        Args:
            study_uid: Study UID to remove
        """
        with self._lock:
            if study_uid in self._states:
                state = self._states.pop(study_uid)
                self._notify_observers('removed', study_uid, state)
                logger.info(f"🗑️ Removed state for {study_uid[:40]}...")
    
    def reset(self, study_uid: str) -> None:
        """
        Force reset download state to PENDING with all progress cleared
        
        This bypasses terminal state checks and completely resets the download.
        Special method for Reset All button - overrides normal validation.
        
        Args:
            study_uid: Study UID to reset
            
        Raises:
            StateError: If study_uid not found
        """
        with self._lock:
            state = self._states.get(study_uid)
            if not state:
                raise StateError(f"Unknown study_uid: {study_uid}")
            
            # Record old values for history
            old_values = {
                'status': state.status,
                'progress_percent': state.progress_percent,
                'downloaded_count': state.downloaded_count,
                'current_series': state.current_series,
                'error_message': state.error_message,
                'retry_count': state.retry_count,
                'completed_series': state.completed_series.copy() if state.completed_series else [],
                'failed_series': state.failed_series.copy() if state.failed_series else [],
                'skipped_series': state.skipped_series.copy() if state.skipped_series else [],
            }
            
            # FORCE reset to PENDING state (bypass terminal state check)
            new_state = replace(
                state,
                status=DownloadStatus.PENDING,
                priority=DownloadPriority.NORMAL,
                progress_percent=0.0,
                downloaded_count=0,
                total_count=state.total_count,  # Keep total count
                current_series=None,
                current_series_number=None,
                current_series_downloaded=0,
                current_series_total=0,
                current_series_progress=0.0,
                error_message=None,
                retry_count=0,
                start_time=None,
                end_time=None,
                completed_series=[],
                failed_series=[],
                skipped_series=[],
                is_auto_paused=False,
                worker_id=None
            )
            
            # Update state in store
            self._states[study_uid] = new_state
            
            # Record change for history
            change = StateChange(
                study_uid=study_uid,
                timestamp=datetime.now(),
                changes={
                    'status': DownloadStatus.PENDING,
                    'progress_percent': 0.0,
                    'downloaded_count': 0,
                    'current_series': None,
                    'error_message': None,
                    'retry_count': 0,
                    'completed_series': [],
                    'failed_series': [],
                    'skipped_series': [],
                    'priority': DownloadPriority.NORMAL,
                    'is_auto_paused': False
                },
                old_values=old_values
            )
            self._history.append(change)
            
            # Notify observers for status change
            self._notify_observers('updated', study_uid, new_state, 'status', old_values['status'], DownloadStatus.PENDING)
            
            logger.info(f"✅ 🔄 FORCE RESET study {study_uid[:40]}... to PENDING (bypassed terminal state check)")
    
    def get_by_status(self, status: DownloadStatus) -> List[DownloadState]:
        """
        Get all states with specific status
        
        Args:
            status: Status to filter by
            
        Returns:
            List of states with matching status
        """
        with self._lock:
            return [s for s in self._states.values() if s.status == status]
    
    def get_by_priority(self, priority: DownloadPriority) -> List[DownloadState]:
        """
        Get all states with specific priority
        
        Args:
            priority: Priority to filter by
            
        Returns:
            List of states with matching priority
        """
        with self._lock:
            return [s for s in self._states.values() if s.priority == priority]
    
    def get_active_downloads(self) -> List[DownloadState]:
        """
        Get all active downloads (Pending, Downloading, Validating)
        
        Returns:
            List of active download states
        """
        with self._lock:
            return [s for s in self._states.values() if s.is_active]
    
    def get_downloading(self) -> List[DownloadState]:
        """
        Get all currently downloading
        
        Returns:
            List of downloading states
        """
        return self.get_by_status(DownloadStatus.DOWNLOADING)
    
    def get_all_downloads(self) -> List[DownloadState]:
        """
        Get all downloads regardless of status
        
        Returns:
            List of all download states
        """
        with self._lock:
            return list(self._states.values())
    
    def get_history(self, study_uid: Optional[str] = None, limit: int = 100) -> List[StateChange]:
        """
        Get state change history
        
        Args:
            study_uid: Optional filter by study UID
            limit: Max number of changes to return
            
        Returns:
            List of state changes (newest first)
        """
        with self._lock:
            if study_uid:
                filtered = [c for c in self._history if c.study_uid == study_uid]
                return list(reversed(filtered))[:limit]
            else:
                return list(reversed(self._history))[:limit]
    
    def register_observer(self, observer: 'StateObserver') -> None:
        """
        Register observer for state changes
        
        Args:
            observer: Observer to register
        """
        with self._lock:
            if observer not in self._observers:
                self._observers.append(observer)
                logger.info(f"✅ Registered observer: {observer.__class__.__name__}")
    
    def unregister_observer(self, observer: 'StateObserver') -> None:
        """
        Unregister observer
        
        Args:
            observer: Observer to unregister
        """
        with self._lock:
            if observer in self._observers:
                self._observers.remove(observer)
                logger.info(f"🗑️ Unregistered observer: {observer.__class__.__name__}")
    
    def _notify_observers(self, event: str, study_uid: str, state: DownloadState, *args):
        """
        Notify all observers of state change
        
        Args:
            event: Event type ('created', 'updated', 'removed')
            study_uid: Study UID
            state: Current state
            *args: Additional event-specific arguments
        """
        for observer in self._observers:
            try:
                observer.on_state_change(event, study_uid, state, *args)
            except Exception as e:
                logger.error(f"❌ Observer {observer.__class__.__name__} failed: {e}")
    
    def clear_completed(self) -> int:
        """
        Remove all completed downloads
        
        Returns:
            Number of states removed
        """
        with self._lock:
            completed = [uid for uid, state in self._states.items()
                        if state.status == DownloadStatus.COMPLETED]
            
            for uid in completed:
                self.remove(uid)
            
            logger.info(f"🧹 Cleared {len(completed)} completed downloads")
            return len(completed)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get state statistics
        
        Returns:
            Statistics dictionary
        """
        with self._lock:
            total = len(self._states)
            by_status = {}
            by_priority = {}
            
            for state in self._states.values():
                # Count by status
                status_name = state.status.value
                by_status[status_name] = by_status.get(status_name, 0) + 1
                
                # Count by priority
                priority_name = state.priority.display_name
                by_priority[priority_name] = by_priority.get(priority_name, 0) + 1
            
            active_count = len(self.get_active_downloads())
            downloading_count = len(self.get_downloading())
            
            return {
                'total': total,
                'active': active_count,
                'downloading': downloading_count,
                'by_status': by_status,
                'by_priority': by_priority,
            }


# Singleton instance
_state_store_instance: Optional[DownloadStateStore] = None
_instance_lock = threading.Lock()


def get_state_store() -> DownloadStateStore:
    """
    Get singleton instance of state store
    
    Returns:
        DownloadStateStore instance
    """
    global _state_store_instance
    
    if _state_store_instance is None:
        with _instance_lock:
            if _state_store_instance is None:
                _state_store_instance = DownloadStateStore()
    
    return _state_store_instance
