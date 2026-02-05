"""
Priority Rules - Enforcement of priority-based rules (R1-R7, R24-R26)

Handles priority determination, preemption logic, and priority change effects.
"""

import logging
from typing import Optional, List
from dataclasses import dataclass

from ..core.models import DownloadTask, DownloadState, RuleResult
from ..core.enums import DownloadPriority, DownloadStatus, PreemptionAction
from ..core.constants import (
    MAX_PARALLEL_SERIES_CRITICAL,
    MAX_PARALLEL_SERIES_HIGH,
    MAX_PARALLEL_SERIES_NORMAL,
    MAX_PARALLEL_SERIES_LOW,
)

# Import database functions for persistent state check
try:
    from PacsClient.utils.database import get_download_progress
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreemptionResult:
    """Result of preemption evaluation"""
    action: PreemptionAction
    reason: str
    affected_downloads: List[str] = None  # List of study UIDs to pause
    
    def __post_init__(self):
        if self.affected_downloads is None:
            object.__setattr__(self, 'affected_downloads', [])


class PriorityRules:
    """
    Priority-based rule enforcement
    
    Rules enforced:
    - R1: Sequential execution (1 study at a time)
    - R2: Critical pauses all other downloads
    - R3: High preempts Normal/Low
    - R4: Priority order: CRITICAL > HIGH > NORMAL > LOW
    - R5: Auto-resume auto-paused downloads
    - R6: Manual pause requires manual resume
    - R7: LIFO within same priority
    - R24: Priority interrupt mechanism
    - R25: Preemption check between batches
    - R26: Preemption action by priority level
    """
    
    def __init__(self, state_store, config: dict):
        """
        Initialize priority rules
        
        Args:
            state_store: DownloadStateStore instance
            config: Configuration dictionary
        """
        self.state = state_store
        self.config = config
        logger.info("✅ PriorityRules initialized")
    
    def evaluate_preemption(
        self,
        new_task: DownloadTask,
        current_downloads: List[DownloadState]
    ) -> PreemptionResult:
        """
        Determine preemption action when new download is added
        
        Args:
            new_task: New download task being added
            current_downloads: List of currently active downloads
            
        Returns:
            PreemptionResult with action and affected downloads
        """
        new_priority = new_task.priority
        
        if not current_downloads:
            # No active downloads - no preemption needed
            return PreemptionResult(
                action=PreemptionAction.QUEUE,
                reason="No active downloads"
            )
        
        # R2: Critical pauses ALL other downloads
        if new_priority == DownloadPriority.CRITICAL:
            affected = [d.study_uid for d in current_downloads 
                       if d.status == DownloadStatus.DOWNLOADING]
            
            return PreemptionResult(
                action=PreemptionAction.PAUSE_ALL,
                reason="CRITICAL priority pauses all other downloads",
                affected_downloads=affected
            )
        
        # R3: High preempts Normal/Low
        if new_priority == DownloadPriority.HIGH:
            affected = [d.study_uid for d in current_downloads
                       if d.priority in [DownloadPriority.NORMAL, DownloadPriority.LOW]
                       and d.status == DownloadStatus.DOWNLOADING]
            
            if affected:
                return PreemptionResult(
                    action=PreemptionAction.PREEMPT_LOWER,
                    reason="HIGH priority preempts NORMAL and LOW",
                    affected_downloads=affected
                )
        
        # R4: Normal preempts Low
        if new_priority == DownloadPriority.NORMAL:
            affected = [d.study_uid for d in current_downloads
                       if d.priority == DownloadPriority.LOW
                       and d.status == DownloadStatus.DOWNLOADING]
            
            if affected:
                return PreemptionResult(
                    action=PreemptionAction.PREEMPT_LOWER,
                    reason="NORMAL priority preempts LOW",
                    affected_downloads=affected
                )
        
        # No preemption - add to queue
        return PreemptionResult(
            action=PreemptionAction.QUEUE,
            reason="No preemption needed"
        )
    
    def should_auto_resume(self, state: DownloadState) -> bool:
        """
        Check if download should auto-resume (R5, R6)
        
        Args:
            state: Download state
            
        Returns:
            True if should auto-resume, False otherwise
        """
        # R6: Manual pause requires manual resume
        if state.status == DownloadStatus.PAUSED and not state.is_auto_paused:
            logger.debug(f"Manual pause - no auto-resume for {state.study_uid[:40]}...")
            return False
        
        # R5: Auto-resume auto-paused downloads
        if state.status == DownloadStatus.PAUSED and state.is_auto_paused:
            logger.debug(f"Auto-paused - can auto-resume {state.study_uid[:40]}...")
            return True
        
        return False
    
    def get_series_parallelism(self, priority: DownloadPriority) -> int:
        """
        Get max parallel series for priority level (R12, R13, R14)
        
        Args:
            priority: Download priority
            
        Returns:
            Max number of parallel series
        """
        parallelism_map = {
            DownloadPriority.CRITICAL: MAX_PARALLEL_SERIES_CRITICAL,  # 1 (sequential)
            DownloadPriority.HIGH: MAX_PARALLEL_SERIES_HIGH,          # 1 (sequential)
            DownloadPriority.NORMAL: MAX_PARALLEL_SERIES_NORMAL,      # 2 (parallel)
            DownloadPriority.LOW: MAX_PARALLEL_SERIES_LOW,            # 3 (parallel)
        }
        
        return parallelism_map.get(priority, 1)
    
    def can_use_parallel_series(self, priority: DownloadPriority) -> bool:
        """
        Check if parallel series download allowed (R13)
        
        Args:
            priority: Download priority
            
        Returns:
            True if parallel allowed, False otherwise
        """
        # R13: Parallel only for Low/Normal priority
        return priority in [DownloadPriority.LOW, DownloadPriority.NORMAL]
    
    def get_next_download_by_priority(self, pending_states: List[DownloadState]) -> Optional[DownloadState]:
        """
        Get next download to execute based on priority order (R4, R7)
        
        Enhanced: Filters database-completed studies before priority sorting
        
        Args:
            pending_states: List of pending downloads
            
        Returns:
            Next download to execute or None
        """
        if not pending_states:
            return None
        
        # R17: Filter out database-completed studies (if database available)
        if DATABASE_AVAILABLE:
            filtered_pending = []
            for state in pending_states:
                try:
                    db_progress = get_download_progress(state.study_uid)
                    if db_progress and db_progress.get('status') == 'Completed':
                        logger.info(
                            f"⏭️ [Priority Queue] Skipping database-completed: "
                            f"{state.patient_name}"
                        )
                        continue
                except Exception as e:
                    logger.debug(f"Database check failed: {e}")
                
                filtered_pending.append(state)
            
            pending_states = filtered_pending
            
            if not pending_states:
                return None
        
        # R4: Priority order: CRITICAL > HIGH > NORMAL > LOW
        # R7: LIFO within same priority (newest first)
        
        # Sort by priority (descending) then by created_at (descending for LIFO)
        sorted_downloads = sorted(
            pending_states,
            key=lambda s: (
                -s.priority,  # Higher priority first
                -(s.start_time.timestamp() if s.start_time else 0)  # LIFO (newest first)
            )
        )
        
        return sorted_downloads[0]
    
    def check_priority_interrupt(
        self,
        current_download: DownloadState,
        waiting_downloads: List[DownloadState]
    ) -> bool:
        """
        Check if current download should be interrupted for higher priority (R24, R25)
        
        Args:
            current_download: Currently downloading state
            waiting_downloads: List of waiting downloads
            
        Returns:
            True if should interrupt, False otherwise
        """
        if not waiting_downloads:
            return False
        
        current_priority = current_download.priority
        
        # Check if any waiting download has higher priority
        for waiting in waiting_downloads:
            if waiting.priority > current_priority:
                logger.info(
                    f"⚡ Priority interrupt: {waiting.priority.name} "
                    f"waiting while {current_priority.name} downloading"
                )
                return True
        
        return False
    
    def get_preemption_action_for_priority(self, priority: DownloadPriority) -> PreemptionAction:
        """
        Get preemption action for priority level (R26)
        
        Args:
            priority: Priority level
            
        Returns:
            Preemption action to take
        """
        action_map = {
            DownloadPriority.CRITICAL: PreemptionAction.PAUSE_ALL,
            DownloadPriority.HIGH: PreemptionAction.PREEMPT_LOWER,
            DownloadPriority.NORMAL: PreemptionAction.PREEMPT_LOWER,
            DownloadPriority.LOW: PreemptionAction.QUEUE,
        }
        
        return action_map.get(priority, PreemptionAction.QUEUE)
    
    def validate_priority_change(
        self,
        state: DownloadState,
        new_priority: DownloadPriority
    ) -> RuleResult:
        """
        Validate if priority change is allowed
        
        Args:
            state: Current download state
            new_priority: New priority to set
            
        Returns:
            RuleResult indicating if change is allowed
        """
        # Check if there's already a CRITICAL download
        if new_priority == DownloadPriority.CRITICAL:
            critical_downloads = self.state.get_by_priority(DownloadPriority.CRITICAL)
            
            # Allow only if no other CRITICAL downloads exist
            if critical_downloads and state.study_uid not in [d.study_uid for d in critical_downloads]:
                return RuleResult(
                    allowed=False,
                    reason="Only ONE download can be CRITICAL at a time",
                    action="reject"
                )
        
        return RuleResult(
            allowed=True,
            reason="Priority change allowed",
            action="update"
        )
