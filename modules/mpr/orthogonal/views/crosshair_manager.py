"""
Crosshair Manager - Synchronized crosshairs between MPR views

Manages the coordination of crosshairs across multiple MPR views,
ensuring that clicking in one view updates all other views.
"""

import logging
from typing import Dict, List, Optional, Callable, Tuple

import numpy as np
import vtkmodules.all as vtk

from ..core.mpr_calculator import MPRCalculator, PlaneType
from .mpr_slice_view import MPRSliceView

logger = logging.getLogger(__name__)


class CrosshairManager:
    """
    Manages synchronized crosshairs across multiple MPR views.
    
    When the user clicks in one view, all views are updated to
    reflect the new center position. This provides intuitive
    navigation through the volume.
    
    Example:
        >>> manager = CrosshairManager(mpr_calculator)
        >>> manager.add_view(axial_view)
        >>> manager.add_view(sagittal_view)
        >>> manager.add_view(coronal_view)
        >>> manager.set_crosshairs_visible(True)
    """
    
    def __init__(
        self,
        mpr_calculator: Optional[MPRCalculator] = None
    ):
        """
        Initialize crosshair manager.
        
        Args:
            mpr_calculator: Shared MPR calculator for all views
        """
        self._calculator = mpr_calculator
        self._views: Dict[PlaneType, MPRSliceView] = {}
        self._crosshairs_visible = True
        self._is_updating = False  # Prevent recursive updates
        
        # Callbacks for external notification
        self._center_changed_callbacks: List[Callable] = []
        
        logger.debug("CrosshairManager initialized")
    
    def set_calculator(self, calculator: MPRCalculator):
        """
        Set or update the MPR calculator.
        
        Args:
            calculator: MPR calculator to use
        """
        self._calculator = calculator
        
        # Update all views with new calculator
        for view in self._views.values():
            view.set_mpr_calculator(calculator)
    
    def add_view(self, view: MPRSliceView):
        """
        Add a view to be managed.
        
        Args:
            view: MPR slice view to add
        """
        plane_type = view.plane_type
        self._views[plane_type] = view
        
        # Set shared calculator
        if self._calculator:
            view.set_mpr_calculator(self._calculator)
        
        # Register callbacks
        view.add_center_changed_callback(self._on_center_changed)
        view.add_slice_changed_callback(self._on_slice_changed)
        
        # Set crosshair visibility
        view.set_crosshair_visible(self._crosshairs_visible)
        
        logger.debug(f"Added view: {plane_type.value}")
    
    def remove_view(self, plane_type: PlaneType):
        """
        Remove a view from management.
        
        Args:
            plane_type: Type of plane to remove
        """
        if plane_type in self._views:
            del self._views[plane_type]
            logger.debug(f"Removed view: {plane_type.value}")
    
    def _on_center_changed(
        self,
        source_plane: PlaneType,
        new_center: List[float]
    ):
        """Handle center change from a view."""
        if self._is_updating:
            return
        
        self._is_updating = True
        
        try:
            # Update calculator
            if self._calculator:
                self._calculator.set_center(new_center)
            
            # Update all other views
            for plane_type, view in self._views.items():
                if plane_type != source_plane:
                    view.update_from_calculator()
            
            # Notify external callbacks
            for callback in self._center_changed_callbacks:
                callback(new_center)
        
        finally:
            self._is_updating = False
    
    def _on_slice_changed(
        self,
        source_plane: PlaneType,
        slice_index: int
    ):
        """Handle slice change from a view."""
        if self._is_updating:
            return
        
        self._is_updating = True
        
        try:
            # Update calculator with new slice
            if self._calculator:
                self._calculator.set_slice_index(source_plane, slice_index)
            
            # Update crosshairs in all views
            for plane_type, view in self._views.items():
                if plane_type != source_plane:
                    view.update_from_calculator()
        
        finally:
            self._is_updating = False
    
    def set_center(self, center: List[float]):
        """
        Set center position for all views.
        
        Args:
            center: New center position [x, y, z]
        """
        if self._calculator:
            self._calculator.set_center(center)
        
        # Update all views
        for view in self._views.values():
            view.update_from_calculator()
    
    def get_center(self) -> Optional[List[float]]:
        """Get current center position."""
        if self._calculator:
            return list(self._calculator.center)
        return None
    
    def set_crosshairs_visible(self, visible: bool):
        """
        Show or hide crosshairs in all views.
        
        Args:
            visible: Whether crosshairs should be visible
        """
        self._crosshairs_visible = visible
        
        for view in self._views.values():
            view.set_crosshair_visible(visible)
    
    def get_crosshairs_visible(self) -> bool:
        """Get crosshair visibility state."""
        return self._crosshairs_visible
    
    def toggle_crosshairs(self) -> bool:
        """
        Toggle crosshair visibility.
        
        Returns:
            New visibility state
        """
        self.set_crosshairs_visible(not self._crosshairs_visible)
        return self._crosshairs_visible
    
    def reset_to_center(self):
        """Reset crosshairs to volume center."""
        if self._calculator:
            bounds = self._calculator.bounds
            center = [
                (bounds[0] + bounds[1]) / 2,
                (bounds[2] + bounds[3]) / 2,
                (bounds[4] + bounds[5]) / 2
            ]
            self.set_center(center)
    
    def add_center_changed_callback(self, callback: Callable):
        """
        Add callback for center change events.
        
        Args:
            callback: Function that takes [x, y, z] center position
        """
        self._center_changed_callbacks.append(callback)
    
    def update_all_views(self):
        """Force update of all views."""
        for view in self._views.values():
            view.update_from_calculator()
    
    def get_view(self, plane_type: PlaneType) -> Optional[MPRSliceView]:
        """
        Get view for a specific plane.
        
        Args:
            plane_type: Type of plane
        
        Returns:
            View if registered, None otherwise
        """
        return self._views.get(plane_type)
    
    @property
    def views(self) -> Dict[PlaneType, MPRSliceView]:
        """Get all managed views."""
        return self._views.copy()


class CrosshairStyle:
    """
    Configuration for crosshair appearance.
    """
    
    def __init__(
        self,
        color: Tuple[float, float, float] = (0.0, 1.0, 0.0),
        line_width: float = 1.5,
        dashed: bool = False,
        gap_size: float = 10.0
    ):
        """
        Initialize crosshair style.
        
        Args:
            color: RGB color tuple (0-1 range)
            line_width: Width of crosshair lines
            dashed: Whether to use dashed lines
            gap_size: Size of gap at intersection (0 for no gap)
        """
        self.color = color
        self.line_width = line_width
        self.dashed = dashed
        self.gap_size = gap_size
    
    @classmethod
    def default(cls) -> "CrosshairStyle":
        """Get default crosshair style."""
        return cls(
            color=(0.0, 1.0, 0.0),
            line_width=1.5,
            dashed=False,
            gap_size=0.0
        )
    
    @classmethod
    def radiology(cls) -> "CrosshairStyle":
        """Get radiology-style crosshairs (yellow, thin)."""
        return cls(
            color=(1.0, 1.0, 0.0),
            line_width=1.0,
            dashed=False,
            gap_size=5.0
        )
