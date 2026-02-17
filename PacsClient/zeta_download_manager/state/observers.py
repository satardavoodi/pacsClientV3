"""
State Observers - Automatic synchronization via observer pattern

Observers react to state changes and synchronize with:
- Database (persist download progress)
- UI (update widgets)
- Priority Manager (track priorities)
- Logging (audit trail)
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional
from datetime import datetime

from ..core.models import DownloadState
from ..core.enums import DownloadStatus
from ..core.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class StateObserver(ABC):
    """
    Abstract base class for state observers
    
    Observers are notified of all state changes and can react accordingly.
    """
    
    @abstractmethod
    def on_state_change(
        self,
        event: str,
        study_uid: str,
        state: DownloadState,
        *args
    ) -> None:
        """
        Called when state changes
        
        Args:
            event: Event type ('created', 'updated', 'removed')
            study_uid: Study UID
            state: Current state
            *args: Additional event-specific arguments
                For 'updated': field_name, old_value, new_value
        """
        pass


class DatabaseObserver(StateObserver):
    """
    Automatically synchronize state to database
    
    Persists download progress for resume functionality.
    """
    
    def __init__(self, database_manager):
        """
        Initialize database observer
        
        Args:
            database_manager: DatabaseManager instance
        """
        self.db = database_manager
        logger.info("✅ DatabaseObserver initialized")
    
    def on_state_change(
        self,
        event: str,
        study_uid: str,
        state: DownloadState,
        *args
    ) -> None:
        """Sync state to database"""
        try:
            if event == 'created':
                # Insert new download progress record
                self.db.insert_download_progress(
                    study_uid=study_uid,
                    downloaded_count=state.downloaded_count,
                    total_instances=state.total_count,
                    progress_percent=state.progress_percent,
                    status=state.status.value
                )
                logger.debug(f"💾 DB: Created progress record for {study_uid[:40]}...")
            
            elif event == 'updated':
                # Handle case where args may be empty (direct state modification)
                if len(args) < 3:
                    # Fallback: update key fields without field-level granularity
                    self.db.update_download_progress(
                        study_uid=study_uid,
                        status=state.status.value,
                        progress_percent=state.progress_percent,
                        downloaded_count=state.downloaded_count
                    )
                    logger.debug(f"💾 DB: Bulk update for {study_uid[:40]}... (no field details)")
                    return

                field_name, old_value, new_value = args

                # Only update database for relevant fields
                if field_name in ['status', 'progress_percent', 'downloaded_count', 'error_message']:
                    self.db.update_download_progress(
                        study_uid=study_uid,
                        **{field_name: new_value}
                    )
                    logger.debug(f"💾 DB: Updated {field_name} for {study_uid[:40]}...")

                # Mark as completed if status changed to COMPLETED
                if field_name == 'status' and new_value == DownloadStatus.COMPLETED:
                    self.db.complete_download_progress(study_uid)
                    logger.info(f"✅ DB: Marked as completed: {study_uid[:40]}...")
            
            elif event == 'removed':
                # Delete from database
                self.db.delete_download_progress(study_uid)
                logger.debug(f"🗑️ DB: Deleted progress for {study_uid[:40]}...")
        
        except Exception as e:
            logger.error(f"❌ DatabaseObserver error: {e}")
            # Don't raise - database errors shouldn't break state management


class UIObserver(StateObserver):
    """
    Automatically update UI when state changes
    
    Updates download table rows incrementally without full refresh.
    """
    
    def __init__(self, ui_widget):
        """
        Initialize UI observer
        
        Args:
            ui_widget: DownloadManagerWidget instance
        """
        self.ui = ui_widget
        logger.info("✅ UIObserver initialized")
    
    def on_state_change(
        self,
        event: str,
        study_uid: str,
        state: DownloadState,
        *args
    ) -> None:
        """Update UI based on state change"""
        try:
            if event == 'created':
                # Add new row to table
                self.ui.add_download_row(study_uid, state)
                logger.debug(f"🎨 UI: Added row for {study_uid[:40]}...")
            
            elif event == 'updated':
                # Handle case where args may be empty (direct state modification)
                if len(args) < 3:
                    # Full refresh when field-level details not available
                    self.ui.refresh_table_order()
                    logger.debug(f"🎨 UI: Full refresh for {study_uid[:40]}... (no field details)")
                    return

                field_name, old_value, new_value = args

                # Update specific UI elements based on field changed
                if field_name == 'progress_percent':
                    self.ui.update_progress_bar(study_uid, new_value)
                elif field_name == 'status':
                    self.ui.update_status_badge(study_uid, new_value)
                elif field_name == 'priority':
                    self.ui.update_priority_badge(study_uid, new_value)
                    # DEFER table reordering through QTimer (not directly!)
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, self.ui.refresh_table_order)
                elif field_name in {
                    'current_series',
                    'current_series_number',
                    'current_series_downloaded',
                    'current_series_total',
                    'current_series_progress'
                }:
                    self.ui.update_current_series(study_uid)

                logger.debug(f"🎨 UI: Updated {field_name} for {study_uid[:40]}...")
            
            elif event == 'removed':
                # Remove row from table
                self.ui.remove_download_row(study_uid)
                logger.debug(f"🎨 UI: Removed row for {study_uid[:40]}...")
        
        except Exception as e:
            logger.error(f"❌ UIObserver error: {e}")
            # Don't raise - UI errors shouldn't break state management


class PriorityObserver(StateObserver):
    """
    Synchronize with priority manager
    
    Tracks priority changes and coordinates with download priority manager.
    """
    
    def __init__(self, priority_manager):
        """
        Initialize priority observer
        
        Args:
            priority_manager: DownloadPriorityManager instance
        """
        self.priority_mgr = priority_manager
        logger.info("✅ PriorityObserver initialized")
    
    def on_state_change(
        self,
        event: str,
        study_uid: str,
        state: DownloadState,
        *args
    ) -> None:
        """Sync with priority manager"""
        try:
            if event == 'created':
                # Register study with priority manager
                self.priority_mgr.register_study(study_uid, state.priority)
                logger.debug(f"🎯 Priority: Registered {study_uid[:40]}...")
            
            elif event == 'updated':
                # Handle case where args may be empty (direct state modification)
                if len(args) < 3:
                    # Fallback: sync key fields without field-level granularity
                    self.priority_mgr.update_study_priority(study_uid, state.priority)
                    logger.debug(f"🎯 Priority: Bulk sync for {study_uid[:40]}... (no field details)")
                    return

                field_name, old_value, new_value = args

                if field_name == 'priority':
                    # Update priority tracking
                    self.priority_mgr.update_study_priority(study_uid, new_value)
                    logger.debug(f"🎯 Priority: Updated to {new_value.name} for {study_uid[:40]}...")
                
                elif field_name == 'status':
                    # Notify priority manager of status changes
                    if new_value == DownloadStatus.COMPLETED:
                        self.priority_mgr.unregister_study(study_uid)
                        logger.debug(f"🎯 Priority: Unregistered {study_uid[:40]}...")
            
            elif event == 'removed':
                # Unregister from priority manager
                self.priority_mgr.unregister_study(study_uid)
                logger.debug(f"🎯 Priority: Unregistered {study_uid[:40]}...")
        
        except Exception as e:
            logger.error(f"❌ PriorityObserver error: {e}")
            # Don't raise


class LoggingObserver(StateObserver):
    """
    Log all state changes for audit trail and debugging
    
    Creates detailed log of all state transitions.
    """
    
    def __init__(self, log_level: int = logging.INFO):
        """
        Initialize logging observer
        
        Args:
            log_level: Logging level for state changes
        """
        self.log_level = log_level
        self.audit_logger = logging.getLogger('zeta.state.audit')
        logger.info("✅ LoggingObserver initialized")
    
    def on_state_change(
        self,
        event: str,
        study_uid: str,
        state: DownloadState,
        *args
    ) -> None:
        """Log state change"""
        try:
            if event == 'created':
                self.audit_logger.log(
                    self.log_level,
                    f"📝 [CREATED] {state.patient_name} - {study_uid[:40]}... "
                    f"(Priority: {state.priority.name}, Total: {state.total_count} images)"
                )
            
            elif event == 'updated':
                # Handle case where args may be empty (direct state modification)
                if len(args) < 3:
                    # Log generic update without field-level details
                    self.audit_logger.log(
                        self.log_level,
                        f"📝 [UPDATED] {study_uid[:40]}... (bulk update)"
                    )
                    return

                field_name, old_value, new_value = args

                # Log important field changes
                if field_name in ['status', 'priority', 'progress_percent']:
                    self.audit_logger.log(
                        self.log_level,
                        f"📝 [UPDATED] {study_uid[:40]}... • {field_name}: {old_value} → {new_value}"
                    )
            
            elif event == 'removed':
                self.audit_logger.log(
                    self.log_level,
                    f"📝 [REMOVED] {study_uid[:40]}... (Status: {state.status.value})"
                )
        
        except Exception as e:
            logger.error(f"❌ LoggingObserver error: {e}")


class ValidationObserver(StateObserver):
    """
    Validate state consistency (for testing and debugging)
    
    Checks for invalid states and logs inconsistencies.
    """
    
    def __init__(self, strict_mode: bool = False):
        """
        Initialize validation observer
        
        Args:
            strict_mode: If True, raise exceptions on validation errors
        """
        self.strict_mode = strict_mode
        self.validation_errors = []
        logger.info("✅ ValidationObserver initialized (strict={})".format(strict_mode))
    
    def on_state_change(
        self,
        event: str,
        study_uid: str,
        state: DownloadState,
        *args
    ) -> None:
        """Validate state consistency"""
        try:
            errors = []
            
            # Validate progress consistency
            if state.downloaded_count > state.total_count:
                errors.append(f"Downloaded count ({state.downloaded_count}) > Total ({state.total_count})")
            
            if state.progress_percent < 0 or state.progress_percent > 100:
                errors.append(f"Invalid progress: {state.progress_percent}%")
            
            # Validate status transitions
            if event == 'updated' and len(args) >= 3:
                field_name, old_value, new_value = args
                if field_name == 'status':
                    if old_value == DownloadStatus.CANCELLED:
                        errors.append(f"Invalid transition from CANCELLED to {new_value}")
            
            # Log errors
            if errors:
                for error in errors:
                    logger.warning(f"⚠️ Validation: {study_uid[:40]}... - {error}")
                    self.validation_errors.append({
                        'study_uid': study_uid,
                        'timestamp': datetime.now(),
                        'error': error
                    })
                
                if self.strict_mode:
                    raise ValidationError(f"State validation failed: {errors}")
        
        except Exception as e:
            logger.error(f"❌ ValidationObserver error: {e}")
            if self.strict_mode:
                raise
