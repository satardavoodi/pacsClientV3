"""
Download Priority Manager - Global coordinator for download priorities

Priority Levels (Highest to Lowest):
- CRITICAL: Series currently displayed in active viewer layouts
- HIGH: Other series of patients with open tabs (not in viewer)
- NORMAL: Selected patients in Download Manager (not opened)  
- LOW: Closed patient tabs (remaining downloads continue in background)

This manager ensures downloads happen in the order that provides
the best user experience - what the user is looking at downloads first.
"""

import logging
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Set, Callable, Any
from collections import OrderedDict
import time

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class DownloadPriority(IntEnum):
    """Download priority levels - higher value = higher priority"""
    LOW = 0       # Closed tabs, background downloads
    NORMAL = 1    # Selected but not opened
    HIGH = 2      # Open patient tab (not in viewer)
    CRITICAL = 3  # Currently displayed in viewer


@dataclass
class SeriesDownloadInfo:
    """Information about a series download"""
    series_uid: str
    series_number: str
    study_uid: str
    patient_id: str
    priority: DownloadPriority = DownloadPriority.NORMAL
    is_downloading: bool = False
    is_completed: bool = False
    progress_percent: float = 0.0
    added_time: float = field(default_factory=time.time)
    priority_order: int = 0  # Order within same priority level
    viewer_layout_position: int = -1  # Position in viewer (-1 = not in viewer)
    tab_open_order: int = -1  # Order in which patient tab was opened


@dataclass
class PatientDownloadInfo:
    """Information about a patient's download status"""
    patient_id: str
    study_uid: str
    patient_name: str = ""
    series: Dict[str, SeriesDownloadInfo] = field(default_factory=dict)
    tab_open_order: int = -1  # -1 means tab not open
    is_tab_open: bool = False
    added_time: float = field(default_factory=time.time)


class DownloadPriorityManager(QObject):
    """
    Singleton manager for coordinating download priorities across the application.
    
    Tracks:
    - Which patients are being downloaded
    - Which patient tabs are open (and in what order)
    - Which series are displayed in viewers
    - Dynamic priority updates
    """
    
    # Signals for priority changes
    priority_changed = Signal(str, str, int)  # study_uid, series_uid, new_priority
    download_order_changed = Signal()  # Emitted when download order needs to be recalculated
    study_priority_changed = Signal(str, int)  # study_uid, new_priority (for Download Manager UI)
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        super().__init__()
        self._initialized = True
        
        # Core data structures
        self._patients: Dict[str, PatientDownloadInfo] = {}  # study_uid -> PatientDownloadInfo
        self._series: Dict[str, SeriesDownloadInfo] = {}  # series_uid -> SeriesDownloadInfo
        
        # Tab tracking (ordered by open time)
        self._open_tabs: OrderedDict[str, int] = OrderedDict()  # study_uid -> open_order
        self._next_tab_order = 0
        
        # Viewer tracking
        self._viewer_series: Dict[str, Dict[int, str]] = {}  # study_uid -> {layout_position: series_uid}
        self._active_study_uid: Optional[str] = None  # Currently active/focused patient tab
        
        # Download queue callbacks
        self._priority_update_callbacks: List[Callable] = []
        
        # Thread safety
        self._data_lock = threading.RLock()
        
        logger.info("DownloadPriorityManager initialized")
    
    # =========================================================================
    # PATIENT MANAGEMENT
    # =========================================================================
    
    def register_patient_download(self, study_uid: str, patient_id: str, 
                                  patient_name: str = "", series_list: List[Dict] = None) -> None:
        """
        Register a patient for download (e.g., when added to Download Manager).
        Initial priority is NORMAL.
        """
        with self._data_lock:
            if study_uid not in self._patients:
                patient_info = PatientDownloadInfo(
                    patient_id=patient_id,
                    study_uid=study_uid,
                    patient_name=patient_name,
                )
                self._patients[study_uid] = patient_info
                logger.debug(f"Registered patient for download: {patient_name} ({study_uid[:20]}...)")
            
            # Register series if provided
            if series_list:
                for series in series_list:
                    self._register_series(study_uid, patient_id, series)
    
    def _register_series(self, study_uid: str, patient_id: str, series_info: Dict) -> None:
        """Register a series for download"""
        series_uid = series_info.get('series_uid', '')
        series_number = str(series_info.get('series_number', ''))
        
        if not series_uid:
            return
        
        if series_uid not in self._series:
            series_download_info = SeriesDownloadInfo(
                series_uid=series_uid,
                series_number=series_number,
                study_uid=study_uid,
                patient_id=patient_id,
                priority=DownloadPriority.NORMAL,
            )
            self._series[series_uid] = series_download_info
            
            # Add to patient's series list
            if study_uid in self._patients:
                self._patients[study_uid].series[series_uid] = series_download_info
    
    def unregister_patient_download(self, study_uid: str) -> None:
        """Remove a patient from download tracking (e.g., download completed or cancelled)"""
        with self._data_lock:
            if study_uid in self._patients:
                patient = self._patients[study_uid]
                # Remove all series
                for series_uid in list(patient.series.keys()):
                    if series_uid in self._series:
                        del self._series[series_uid]
                del self._patients[study_uid]
                logger.debug(f"Unregistered patient download: {study_uid[:20]}...")
    
    # =========================================================================
    # TAB LIFECYCLE MANAGEMENT
    # =========================================================================
    
    def on_patient_tab_opened(self, study_uid: str, patient_id: str = "", patient_name: str = "") -> None:
        """
        Called when a patient tab is opened (double-click).
        Promotes the newly opened patient to CRITICAL priority to ensure immediate download.
        
        CRITICAL FIX: Use CRITICAL (not HIGH) to ensure the newly opened patient
        preempts other HIGH priority patients that may be downloading.
        """
        print(f"📢 [PRIORITY-MGR] on_patient_tab_opened called: {patient_name} ({study_uid[:30]}...)")
        with self._data_lock:
            # Track tab open order
            if study_uid not in self._open_tabs:
                self._open_tabs[study_uid] = self._next_tab_order
                self._next_tab_order += 1
                logger.info(f"Patient tab opened: {patient_name} (order: {self._open_tabs[study_uid]})")
            
            # Register patient if not already registered
            if study_uid not in self._patients:
                self.register_patient_download(study_uid, patient_id, patient_name)
            
            # Update patient info
            patient = self._patients.get(study_uid)
            if patient:
                patient.is_tab_open = True
                patient.tab_open_order = self._open_tabs[study_uid]
                
                # Promote all series to HIGH priority (series-level)
                for series_uid, series_info in patient.series.items():
                    if series_info.priority < DownloadPriority.HIGH:
                        old_priority = series_info.priority
                        series_info.priority = DownloadPriority.HIGH
                        series_info.tab_open_order = patient.tab_open_order
                        self.priority_changed.emit(study_uid, series_uid, DownloadPriority.HIGH)
                        logger.debug(f"Series {series_info.series_number} promoted: {old_priority.name} -> HIGH")
            
            self._set_active_study(study_uid)
            self.download_order_changed.emit()
            
            # CRITICAL: Emit CRITICAL priority for study-level to ensure preemption
            # This ensures the newly opened patient preempts any other HIGH priority patients
            print(f"📢 [PRIORITY-MGR] Emitting CRITICAL priority signal for {study_uid[:30]}...")
            self.study_priority_changed.emit(study_uid, DownloadPriority.CRITICAL)
            print(f"📢 [PRIORITY-MGR] Signal emitted!")
    
    def on_patient_tab_closed(self, study_uid: str) -> None:
        """
        Called when a patient tab is closed.
        Demotes remaining incomplete series to LOW priority.
        """
        print(f"📢 [PRIORITY-MGR] on_patient_tab_closed called: {study_uid[:30]}...")
        with self._data_lock:
            if study_uid in self._open_tabs:
                del self._open_tabs[study_uid]
                logger.info(f"Patient tab closed: {study_uid[:20]}...")
            
            # Clear viewer tracking for this study
            if study_uid in self._viewer_series:
                del self._viewer_series[study_uid]
            
            # Demote series to LOW
            patient = self._patients.get(study_uid)
            if patient:
                patient.is_tab_open = False
                patient.tab_open_order = -1
                
                for series_uid, series_info in patient.series.items():
                    if not series_info.is_completed:
                        old_priority = series_info.priority
                        series_info.priority = DownloadPriority.LOW
                        series_info.viewer_layout_position = -1
                        series_info.tab_open_order = -1
                        self.priority_changed.emit(study_uid, series_uid, DownloadPriority.LOW)
                        logger.debug(f"Series {series_info.series_number} demoted: {old_priority.name} -> LOW")
            
            self.download_order_changed.emit()
            
            # Emit study-level priority change for Download Manager UI
            print(f"📢 [PRIORITY-MGR] Emitting LOW priority signal for {study_uid[:30]}...")
            self.study_priority_changed.emit(study_uid, DownloadPriority.LOW)
    
    def on_patient_tab_activated(self, study_uid: str) -> None:
        """
        Called when a patient tab becomes the active/focused tab.
        Updates active study tracking for CRITICAL priority ordering.
        """
        with self._data_lock:
            self._set_active_study(study_uid)
            self.download_order_changed.emit()
    
    def _set_active_study(self, study_uid: str) -> None:
        """Set the currently active study"""
        if self._active_study_uid != study_uid:
            self._active_study_uid = study_uid
            logger.debug(f"Active study changed to: {study_uid[:20]}...")
    
    def get_tab_open_order(self, study_uid: str) -> int:
        """
        Get the tab open order for a study.
        
        Higher values = more recently opened (LIFO).
        Returns -1 if the study has no tab open.
        """
        with self._data_lock:
            return self._open_tabs.get(study_uid, -1)
    
    # =========================================================================
    # VIEWER MANAGEMENT
    # =========================================================================
    
    def on_series_loaded_in_viewer(self, study_uid: str, series_uid: str, 
                                   layout_position: int = 0) -> None:
        """
        Called when a series is loaded into a viewer layout.
        Promotes the series to CRITICAL priority.
        
        Args:
            study_uid: Study instance UID
            series_uid: Series instance UID
            layout_position: Position in the viewer layout (0, 1, 2, etc.)
        """
        with self._data_lock:
            # Initialize viewer tracking for this study
            if study_uid not in self._viewer_series:
                self._viewer_series[study_uid] = {}
            
            # Track which series is in which layout position
            self._viewer_series[study_uid][layout_position] = series_uid
            
            # Promote series to CRITICAL
            series_info = self._series.get(series_uid)
            if series_info:
                old_priority = series_info.priority
                series_info.priority = DownloadPriority.CRITICAL
                series_info.viewer_layout_position = layout_position
                self.priority_changed.emit(study_uid, series_uid, DownloadPriority.CRITICAL)
                logger.info(f"Series {series_info.series_number} promoted to CRITICAL (layout: {layout_position})")
            
            self.download_order_changed.emit()
            
            # Emit study-level priority change for Download Manager UI
            self.study_priority_changed.emit(study_uid, DownloadPriority.CRITICAL)
    
    def on_series_removed_from_viewer(self, study_uid: str, series_uid: str) -> None:
        """
        Called when a series is removed from a viewer layout.
        Demotes from CRITICAL to HIGH (if tab still open) or LOW (if tab closed).
        """
        with self._data_lock:
            # Remove from viewer tracking
            if study_uid in self._viewer_series:
                for pos, uid in list(self._viewer_series[study_uid].items()):
                    if uid == series_uid:
                        del self._viewer_series[study_uid][pos]
                        break
            
            # Demote series
            series_info = self._series.get(series_uid)
            if series_info and series_info.priority == DownloadPriority.CRITICAL:
                patient = self._patients.get(study_uid)
                if patient and patient.is_tab_open:
                    series_info.priority = DownloadPriority.HIGH
                    new_priority = DownloadPriority.HIGH
                else:
                    series_info.priority = DownloadPriority.LOW
                    new_priority = DownloadPriority.LOW
                
                series_info.viewer_layout_position = -1
                self.priority_changed.emit(study_uid, series_uid, new_priority)
                logger.debug(f"Series {series_info.series_number} demoted from CRITICAL to {new_priority.name}")
            
            self.download_order_changed.emit()
    
    # =========================================================================
    # PRIORITY QUERIES
    # =========================================================================
    
    def get_series_priority(self, series_uid: str) -> DownloadPriority:
        """Get the current priority of a series"""
        with self._data_lock:
            series_info = self._series.get(series_uid)
            if series_info:
                return series_info.priority
            return DownloadPriority.NORMAL
    
    def get_ordered_download_queue(self) -> List[SeriesDownloadInfo]:
        """
        Get all pending series ordered by priority.
        
        Order:
        1. CRITICAL series (ordered by: active study first, then layout position)
        2. HIGH series (ordered by: tab open order)
        3. NORMAL series (ordered by: added time)
        4. LOW series (ordered by: added time)
        """
        with self._data_lock:
            pending = [s for s in self._series.values() 
                      if not s.is_completed and not s.is_downloading]
            
            def sort_key(series: SeriesDownloadInfo):
                priority_value = -series.priority  # Negative for descending
                
                if series.priority == DownloadPriority.CRITICAL:
                    # Active study first, then by layout position
                    is_active = 0 if series.study_uid == self._active_study_uid else 1
                    layout_pos = series.viewer_layout_position if series.viewer_layout_position >= 0 else 999
                    return (priority_value, is_active, layout_pos, series.added_time)
                
                elif series.priority == DownloadPriority.HIGH:
                    # By tab open order
                    tab_order = series.tab_open_order if series.tab_open_order >= 0 else 999
                    return (priority_value, tab_order, series.added_time)
                
                else:
                    # By added time
                    return (priority_value, series.added_time)
            
            return sorted(pending, key=sort_key)
    
    def get_next_series_to_download(self) -> Optional[SeriesDownloadInfo]:
        """Get the highest priority series that should be downloaded next"""
        queue = self.get_ordered_download_queue()
        return queue[0] if queue else None
    
    def get_priority_stats(self) -> Dict[str, int]:
        """Get count of series at each priority level"""
        with self._data_lock:
            stats = {
                'critical': 0,
                'high': 0,
                'normal': 0,
                'low': 0,
                'total': len(self._series),
                'completed': 0,
                'downloading': 0,
            }
            
            for series in self._series.values():
                if series.is_completed:
                    stats['completed'] += 1
                elif series.is_downloading:
                    stats['downloading'] += 1
                else:
                    if series.priority == DownloadPriority.CRITICAL:
                        stats['critical'] += 1
                    elif series.priority == DownloadPriority.HIGH:
                        stats['high'] += 1
                    elif series.priority == DownloadPriority.NORMAL:
                        stats['normal'] += 1
                    else:
                        stats['low'] += 1
            
            return stats
    
    # =========================================================================
    # DOWNLOAD STATUS UPDATES
    # =========================================================================
    
    def mark_series_downloading(self, series_uid: str) -> None:
        """Mark a series as currently downloading"""
        with self._data_lock:
            series_info = self._series.get(series_uid)
            if series_info:
                series_info.is_downloading = True
    
    def mark_series_completed(self, series_uid: str) -> None:
        """Mark a series as completed"""
        with self._data_lock:
            series_info = self._series.get(series_uid)
            if series_info:
                series_info.is_downloading = False
                series_info.is_completed = True
                series_info.progress_percent = 100.0
                logger.debug(f"Series {series_info.series_number} marked as completed")
    
    def update_series_progress(self, series_uid: str, progress_percent: float) -> None:
        """Update download progress for a series"""
        with self._data_lock:
            series_info = self._series.get(series_uid)
            if series_info:
                series_info.progress_percent = progress_percent
    
    # =========================================================================
    # CALLBACK MANAGEMENT
    # =========================================================================
    
    def register_priority_callback(self, callback: Callable) -> None:
        """Register a callback to be notified when priorities change"""
        with self._data_lock:
            if callback not in self._priority_update_callbacks:
                self._priority_update_callbacks.append(callback)
    
    def unregister_priority_callback(self, callback: Callable) -> None:
        """Unregister a priority callback"""
        with self._data_lock:
            if callback in self._priority_update_callbacks:
                self._priority_update_callbacks.remove(callback)
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def get_open_tabs_count(self) -> int:
        """Get number of open patient tabs"""
        with self._data_lock:
            return len(self._open_tabs)
    
    def get_open_tabs(self) -> List[str]:
        """Get list of open patient tab study UIDs in order"""
        with self._data_lock:
            return list(self._open_tabs.keys())
    
    def is_tab_open(self, study_uid: str) -> bool:
        """Check if a patient tab is open"""
        with self._data_lock:
            return study_uid in self._open_tabs
    
    def clear_all(self) -> None:
        """Clear all tracking data (for testing/reset)"""
        with self._data_lock:
            self._patients.clear()
            self._series.clear()
            self._open_tabs.clear()
            self._viewer_series.clear()
            self._active_study_uid = None
            self._next_tab_order = 0
            logger.info("DownloadPriorityManager cleared")


# Singleton accessor
_priority_manager_instance: Optional[DownloadPriorityManager] = None

def get_download_priority_manager() -> DownloadPriorityManager:
    """Get the global DownloadPriorityManager instance"""
    global _priority_manager_instance
    if _priority_manager_instance is None:
        _priority_manager_instance = DownloadPriorityManager()
    return _priority_manager_instance
