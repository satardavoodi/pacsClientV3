"""
Download State Machine - Valid state transitions (R8, R9, R10)

Enforces valid state transitions and prevents invalid state changes.
"""

import logging
from typing import Set, Dict, Optional
from dataclasses import dataclass

from ..core.enums import DownloadStatus
from ..core.exceptions import StateError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StateTransition:
    """
    Represents a state transition
    """
    from_state: DownloadStatus
    to_state: DownloadStatus
    reason: str = ""
    
    def is_valid(self) -> bool:
        """Check if transition is valid"""
        return DownloadStateMachine.is_valid_transition(self.from_state, self.to_state)


class DownloadStateMachine:
    """
    State machine for download status transitions
    
    Enforces rules:
    - R8: Valid state transitions enforced
    - R9: Cancelled is terminal state
    - R10: Invalid state auto-recovery
    
    Valid Transitions:
        PENDING → DOWNLOADING, PAUSED, CANCELLED, VALIDATING
        DOWNLOADING → PAUSED, COMPLETED, FAILED, CANCELLED
        PAUSED → DOWNLOADING, CANCELLED
        FAILED → DOWNLOADING (retry), CANCELLED
        VALIDATING → PENDING, DOWNLOADING, CANCELLED
        COMPLETED → (terminal)
        CANCELLED → (terminal)
    """
    
    # Define valid state transitions
    # IMPORTANT: All states MUST be able to progress forward to COMPLETED
    # or transition to a state that allows retry/resume
    VALID_TRANSITIONS: Dict[DownloadStatus, Set[DownloadStatus]] = {
        DownloadStatus.PENDING: {
            DownloadStatus.DOWNLOADING,   # Normal start
            DownloadStatus.VALIDATING,    # Validation before download
            DownloadStatus.COMPLETED,     # Already complete on disk (R17b skip)
            DownloadStatus.PAUSED,        # Paused before starting
            DownloadStatus.FAILED,        # Failed before starting (e.g., no auth)
            DownloadStatus.CANCELLED,     # User cancelled
        },
        DownloadStatus.VALIDATING: {
            DownloadStatus.PENDING,       # Needs re-queue
            DownloadStatus.DOWNLOADING,   # Validation passed, start download
            DownloadStatus.PAUSED,        # Preempted by higher-priority series request
            DownloadStatus.FAILED,        # Validation failed
            DownloadStatus.CANCELLED,     # User cancelled
        },
        DownloadStatus.DOWNLOADING: {
            DownloadStatus.VALIDATING,    # Re-validation (executor workflow)
            DownloadStatus.PAUSED,        # User paused or preemption
            DownloadStatus.COMPLETED,     # Successfully completed
            DownloadStatus.FAILED,        # Download failed
            DownloadStatus.CANCELLED,     # User cancelled
        },
        DownloadStatus.PAUSED: {
            DownloadStatus.PENDING,       # Re-queue for auto-resume
            DownloadStatus.DOWNLOADING,   # Manual resume
            DownloadStatus.CANCELLED,     # User cancelled
        },
        DownloadStatus.FAILED: {
            DownloadStatus.PENDING,       # Re-queue for retry
            DownloadStatus.DOWNLOADING,   # Direct retry
            DownloadStatus.CANCELLED,     # User gave up
        },
        DownloadStatus.COMPLETED: set(),  # Terminal state - SUCCESS
        DownloadStatus.CANCELLED: set(),  # Terminal state - USER STOPPED (R9)
    }
    
    @classmethod
    def is_valid_transition(cls, from_state: DownloadStatus, to_state: DownloadStatus) -> bool:
        """
        Check if state transition is valid
        
        Args:
            from_state: Current state
            to_state: Target state
            
        Returns:
            True if transition is valid, False otherwise
        """
        if from_state == to_state:
            # Same state is always valid
            return True
        
        valid_next_states = cls.VALID_TRANSITIONS.get(from_state, set())
        return to_state in valid_next_states
    
    @classmethod
    def validate_transition(
        cls,
        from_state: DownloadStatus,
        to_state: DownloadStatus,
        study_uid: str = ""
    ) -> StateTransition:
        """
        Validate state transition and return transition object
        
        Args:
            from_state: Current state
            to_state: Target state
            study_uid: Study UID (for logging)
            
        Returns:
            StateTransition object
            
        Raises:
            StateError: If transition is invalid
        """
        if not cls.is_valid_transition(from_state, to_state):
            error_msg = (
                f"Invalid state transition: {from_state.value} → {to_state.value}"
                f" (Study: {study_uid[:40]}...)" if study_uid else ""
            )
            logger.error(f"❌ {error_msg}")
            raise StateError(error_msg)
        
        transition = StateTransition(
            from_state=from_state,
            to_state=to_state,
            reason=f"Valid transition"
        )
        
        logger.debug(
            f"✅ Valid transition: {from_state.value} → {to_state.value} "
            f"({study_uid[:40]}...)" if study_uid else ""
        )
        
        return transition
    
    @classmethod
    def get_valid_next_states(cls, current_state: DownloadStatus) -> Set[DownloadStatus]:
        """
        Get all valid next states from current state
        
        Args:
            current_state: Current download status
            
        Returns:
            Set of valid next states
        """
        return cls.VALID_TRANSITIONS.get(current_state, set())
    
    @classmethod
    def is_terminal_state(cls, state: DownloadStatus) -> bool:
        """
        Check if state is terminal (cannot transition further)
        
        Args:
            state: Download status
            
        Returns:
            True if terminal, False otherwise
        """
        return len(cls.VALID_TRANSITIONS.get(state, set())) == 0
    
    @classmethod
    def auto_recover(cls, invalid_state: DownloadStatus, context: str = "") -> DownloadStatus:
        """
        Auto-recovery from invalid state (R10)
        
        Args:
            invalid_state: Current invalid state
            context: Context information for logging
            
        Returns:
            Recovered state
        """
        logger.warning(
            f"⚠️ Auto-recovering from invalid state: {invalid_state.value} "
            f"(Context: {context})"
        )
        
        # Recovery strategies
        if invalid_state == DownloadStatus.DOWNLOADING:
            # If stuck in downloading, move to failed for retry
            recovered = DownloadStatus.FAILED
        elif invalid_state == DownloadStatus.PAUSED:
            # If stuck in paused, move to pending
            recovered = DownloadStatus.PENDING
        else:
            # Default recovery: move to failed
            recovered = DownloadStatus.FAILED
        
        logger.info(f"✅ Auto-recovered: {invalid_state.value} → {recovered.value}")
        
        return recovered
    
    @classmethod
    def get_transition_description(cls, from_state: DownloadStatus, to_state: DownloadStatus) -> str:
        """
        Get human-readable description of transition
        
        Args:
            from_state: Current state
            to_state: Target state
            
        Returns:
            Description string
        """
        descriptions = {
            (DownloadStatus.PENDING, DownloadStatus.DOWNLOADING): "Download started",
            (DownloadStatus.PENDING, DownloadStatus.VALIDATING): "Validating with server",
            (DownloadStatus.VALIDATING, DownloadStatus.DOWNLOADING): "Validation complete, starting download",
            (DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED): "Download paused",
            (DownloadStatus.DOWNLOADING, DownloadStatus.COMPLETED): "Download completed successfully",
            (DownloadStatus.DOWNLOADING, DownloadStatus.FAILED): "Download failed",
            (DownloadStatus.PAUSED, DownloadStatus.DOWNLOADING): "Download resumed",
            (DownloadStatus.FAILED, DownloadStatus.DOWNLOADING): "Retrying download",
            (DownloadStatus.PENDING, DownloadStatus.CANCELLED): "Download cancelled before start",
            (DownloadStatus.DOWNLOADING, DownloadStatus.CANCELLED): "Download cancelled",
            (DownloadStatus.PAUSED, DownloadStatus.CANCELLED): "Paused download cancelled",
        }
        
        return descriptions.get(
            (from_state, to_state),
            f"{from_state.value} → {to_state.value}"
        )
