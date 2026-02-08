"""
Unified Viewer State Controller

This module provides a single source of truth for viewer updates.
NO OTHER CODE should directly update VTK viewers - all updates must go through this controller.

This prevents flickering caused by multiple concurrent updates from different functions.
"""

import threading
import logging
from typing import Optional, List, Tuple, Dict, Any
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication


class ViewerStateController(QObject):
    """
    SINGLE UNIFIED CONTROLLER for all viewer updates.
    
    Responsibilities:
    1. Maintain viewer state (what's currently displayed)
    2. Prevent concurrent updates (locking)
    3. Eliminate redundant updates (state checking)
    4. Provide flicker-free updates (single repaint per state change)
    
    Rules:
    - Only this class may call vtk_widget.start_process_series()
    - All other code must use display_series_in_viewers()
    - Updates are serialized via lock to prevent race conditions
    """
    
    # Signal emitted when display state changes
    display_state_changed = Signal(str, list)  # (series_number, viewer_indices)
    
    def __init__(self, patient_widget):
        super().__init__()
        self.patient_widget = patient_widget
        self.logger = logging.getLogger(f"{__name__}.ViewerStateController")
        
        # Thread-safe lock prevents concurrent updates
        self._update_lock = threading.Lock()
        
        # Track current state: {viewer_index: series_number}
        self._current_display_state: Dict[int, Optional[str]] = {}
        
        # Track loading state: {viewer_index: is_loading}
        self._loading_state: Dict[int, bool] = {}
        
        # Flag: have viewers been initialized?
        self._viewers_initialized = False
        
        # Pending series to display (when viewers are created)
        self._pending_first_series = None
        
        self.logger.info("ViewerStateController initialized")
    
    def are_viewers_initialized(self) -> bool:
        """Check if viewers have been created"""
        return self._viewers_initialized and len(self.patient_widget.lst_nodes_viewer) > 0
    
    def mark_viewers_initialized(self):
        """Mark viewers as initialized and ready for updates"""
        self._viewers_initialized = True
        self.logger.info(f"Viewers marked as initialized: {len(self.patient_widget.lst_nodes_viewer)} viewers")
    
    def get_current_series_in_viewer(self, viewer_index: int) -> Optional[str]:
        """Get currently displayed series in a specific viewer"""
        return self._current_display_state.get(viewer_index)
    
    def is_series_already_displayed(self, series_number: str, viewer_index: int) -> bool:
        """Check if series is already displayed in viewer (prevents redundant updates)"""
        current = self._current_display_state.get(viewer_index)
        return current == series_number
    
    def display_series_in_viewers(
        self,
        series_number: Optional[str],
        viewer_indices: Optional[List[int]] = None,
        force_update: bool = False
    ) -> bool:
        """
        UNIFIED DISPLAY FUNCTION - Only place where viewer updates happen
        
        This function is the SINGLE SOURCE OF TRUTH for all viewer updates.
        
        Args:
            series_number: Series to display (None = loading state)
            viewer_indices: Which viewers to update (None = all viewers)
            force_update: Force update even if already displayed
        
        Returns:
            bool: True if update was performed, False if skipped
        """
        # Acquire lock to prevent concurrent updates (flicker prevention)
        with self._update_lock:
            self.logger.info(f"🎬 [UNIFIED] Display request: series={series_number}, viewers={viewer_indices}, force={force_update}")
            
            # Check if viewers are ready
            if not self.are_viewers_initialized():
                self.logger.warning("⚠️ [UNIFIED] Viewers not initialized yet, storing as pending")
                self._pending_first_series = series_number
                return False
            
            # Determine which viewers to update
            if viewer_indices is None:
                # Update ALL viewers
                viewer_indices = list(range(len(self.patient_widget.lst_nodes_viewer)))
            
            # Find series data
            series_data = self._find_series_data(series_number)
            if series_number is not None and series_data is None:
                self.logger.error(f"❌ [UNIFIED] Series {series_number} not found in lst_thumbnails_data")
                return False
            
            # Perform update for each viewer
            updates_performed = 0
            for viewer_idx in viewer_indices:
                if viewer_idx >= len(self.patient_widget.lst_nodes_viewer):
                    self.logger.warning(f"⚠️ [UNIFIED] Viewer index {viewer_idx} out of range")
                    continue
                
                # Skip if already displayed (prevents flicker)
                if not force_update and self.is_series_already_displayed(series_number, viewer_idx):
                    self.logger.debug(f"⏭️ [UNIFIED] Skipping viewer {viewer_idx} - already showing {series_number}")
                    continue
                
                # Perform actual update
                success = self._update_single_viewer(viewer_idx, series_number, series_data)
                if success:
                    updates_performed += 1
                    # Update state tracking
                    self._current_display_state[viewer_idx] = series_number
                    self._loading_state[viewer_idx] = (series_number is None)
            
            if updates_performed > 0:
                self.logger.info(f"✅ [UNIFIED] Updated {updates_performed} viewers with series {series_number}")
                self.display_state_changed.emit(series_number or "loading", viewer_indices)
                return True
            else:
                self.logger.debug(f"⏭️ [UNIFIED] No updates needed")
                return False
    
    def _find_series_data(self, series_number: Optional[str]) -> Optional[Dict[str, Any]]:
        """Find series data in lst_thumbnails_data"""
        if series_number is None:
            return None
        
        # Search in lst_thumbnails_data
        for item in self.patient_widget.lst_thumbnails_data:
            metadata = item.get('metadata', {})
            series_info = metadata.get('series', {})
            if str(series_info.get('series_number')) == str(series_number):
                return item
        
        return None
    
    def _update_single_viewer(
        self,
        viewer_index: int,
        series_number: Optional[str],
        series_data: Optional[Dict[str, Any]]
    ) -> bool:
        """
        Actually update a single viewer (low-level function)
        
        This is the ONLY place where vtk_widget.start_process_series() is called
        """
        try:
            node_viewer = self.patient_widget.lst_nodes_viewer[viewer_index]
            vtk_widget = node_viewer.vtk_widget
            slider = node_viewer.slider
            
            if series_number is None or series_data is None:
                # Show loading state
                self.logger.debug(f"📺 [UNIFIED] Setting viewer {viewer_index} to loading state")
                # Keep viewer empty with "Loading medical images..." message
                # The VTKWidget should already have this from initialization
                return True
            
            # Extract data
            vtk_image_data = series_data['vtk_image_data']
            metadata = series_data['metadata']
            
            self.logger.info(f"📺 [UNIFIED] Updating viewer {viewer_index} with series {series_number}")
            
            # Single update - no flicker
            vtk_widget.start_process_series(
                vtk_image_data,
                metadata,
                series_data.get('thumbnail_index', viewer_index),
                viewer_index
            )
            
            # Update slider
            count_slices = vtk_widget.get_count_of_slices()
            slider.setMinimum(0)
            slider.setMaximum(count_slices - 1)
            slider.setValue(0)
            
            # Process events once (not multiple times)
            QApplication.processEvents()
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ [UNIFIED] Failed to update viewer {viewer_index}: {e}", exc_info=True)
            return False
    
    def initialize_viewers_with_loading_state(self, layout: Tuple[int, int] = (1, 2)):
        """
        Create viewers in loading state showing 'Loading medical images...'
        
        This is called once during initialization.
        """
        with self._update_lock:
            self.logger.info(f"🎬 [UNIFIED] Initializing {layout[0]}x{layout[1]} viewers in loading state")
            
            # Clear existing viewers
            self.patient_widget.cleanup_all_viewers()
            
            # Create viewers in grid layout
            rows, cols = layout
            for row in range(rows):
                for col in range(cols):
                    viewer_index = row * cols + col
                    
                    # Create viewer (will show "Loading medical images..." by default)
                    node_viewer = self.patient_widget.new_viewer(default_thumb_index=0)
                    
                    # Add to grid (NodeViewer has 'widget' attribute, not 'container')
                    self.patient_widget.vtk_layout.addWidget(
                        node_viewer.widget,
                        row, col
                    )
                    
                    # Mark as loading
                    self._loading_state[viewer_index] = True
                    self._current_display_state[viewer_index] = None
                    
                    self.logger.debug(f"📺 [UNIFIED] Created viewer {viewer_index} at ({row}, {col})")
            
            # Mark as initialized
            self.mark_viewers_initialized()
            
            # If there's a pending series, display it now
            if self._pending_first_series is not None:
                self.logger.info(f"🎬 [UNIFIED] Displaying pending series: {self._pending_first_series}")
                QTimer.singleShot(100, lambda: self.display_series_in_viewers(self._pending_first_series))
    
    def display_first_series_when_ready(self, series_number: str):
        """
        Display first downloaded series in all viewers
        
        This is called when the first series finishes downloading.
        If viewers aren't ready yet, it will be stored as pending.
        """
        self.logger.info(f"🎯 [UNIFIED] First series ready: {series_number}")
        
        if not self.are_viewers_initialized():
            self.logger.info(f"⏳ [UNIFIED] Viewers not ready, storing as pending")
            self._pending_first_series = series_number
            return
        
        # Display in all viewers
        self.display_series_in_viewers(
            series_number=series_number,
            viewer_indices=None,  # All viewers
            force_update=True
        )
    
    def reset_state(self):
        """Reset controller state (used when switching patients)"""
        with self._update_lock:
            self._current_display_state.clear()
            self._loading_state.clear()
            self._viewers_initialized = False
            self._pending_first_series = None
            self.logger.info("🔄 [UNIFIED] Controller state reset")
