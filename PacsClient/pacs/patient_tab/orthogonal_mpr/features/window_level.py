"""
Window/Level Manager - Preset management and adjustment for MPR

Provides:
- Standard CT and MR window/level presets
- Interactive window/level adjustment
- Preset management and customization
"""

import logging
from typing import Dict, Optional, Tuple, List, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WindowLevelPreset:
    """
    Window/Level preset configuration.
    
    Attributes:
        name: Display name of preset
        window: Window width (contrast)
        level: Window center/level (brightness)
        description: Optional description
    """
    name: str
    window: float
    level: float
    description: str = ""


# Standard CT Window/Level Presets
CT_PRESETS: Dict[str, WindowLevelPreset] = {
    "default": WindowLevelPreset("Default", 400, 40, "Default soft tissue"),
    "lung": WindowLevelPreset("Lung", 1500, -600, "Lung parenchyma"),
    "bone": WindowLevelPreset("Bone", 2000, 500, "Bone windows"),
    "brain": WindowLevelPreset("Brain", 80, 40, "Brain parenchyma"),
    "soft_tissue": WindowLevelPreset("Soft Tissue", 400, 40, "Soft tissue"),
    "liver": WindowLevelPreset("Liver", 150, 30, "Liver"),
    "mediastinum": WindowLevelPreset("Mediastinum", 350, 50, "Mediastinal structures"),
    "abdomen": WindowLevelPreset("Abdomen", 400, 50, "Abdominal organs"),
    "spine": WindowLevelPreset("Spine", 250, 50, "Spine soft tissue"),
    "pe": WindowLevelPreset("PE Study", 700, 100, "Pulmonary embolism"),
    "stroke": WindowLevelPreset("Stroke", 40, 40, "Acute stroke"),
    "subdural": WindowLevelPreset("Subdural", 200, 75, "Subdural hematoma"),
}

# Standard MR Window/Level Presets
MR_PRESETS: Dict[str, WindowLevelPreset] = {
    "default": WindowLevelPreset("Default", 1000, 500, "Default MR"),
    "t1": WindowLevelPreset("T1", 800, 400, "T1 weighted"),
    "t2": WindowLevelPreset("T2", 1200, 600, "T2 weighted"),
    "flair": WindowLevelPreset("FLAIR", 1000, 500, "FLAIR sequence"),
    "dwi": WindowLevelPreset("DWI", 1500, 750, "Diffusion weighted"),
}


class WindowLevelManager:
    """
    Manager for window/level adjustment and presets.
    
    Handles window/level settings for MPR views, including
    preset management and interactive adjustment.
    
    Example:
        >>> manager = WindowLevelManager(modality="CT")
        >>> manager.apply_preset("lung")
        >>> window, level = manager.get_current()
    """
    
    def __init__(
        self,
        modality: str = "CT",
        initial_window: float = 400.0,
        initial_level: float = 40.0
    ):
        """
        Initialize window/level manager.
        
        Args:
            modality: Image modality ("CT" or "MR")
            initial_window: Initial window width
            initial_level: Initial window center/level
        """
        self._modality = modality.upper()
        self._window = initial_window
        self._level = initial_level
        
        # Select appropriate presets
        if self._modality == "CT":
            self._presets = CT_PRESETS.copy()
        elif self._modality in ("MR", "MRI"):
            self._presets = MR_PRESETS.copy()
        else:
            self._presets = CT_PRESETS.copy()  # Default to CT
        
        # Custom user presets
        self._custom_presets: Dict[str, WindowLevelPreset] = {}
        
        # Callbacks for value changes
        self._callbacks: List[Callable] = []
        
        # Current preset name (if any)
        self._current_preset: Optional[str] = None
        
        logger.debug(f"WindowLevelManager initialized: modality={modality}")
    
    @property
    def window(self) -> float:
        """Get current window width."""
        return self._window
    
    @window.setter
    def window(self, value: float):
        """Set window width."""
        self._window = max(1.0, value)  # Minimum window of 1
        self._current_preset = None  # Clear preset when manually changing
        self._notify_callbacks()
    
    @property
    def level(self) -> float:
        """Get current window level/center."""
        return self._level
    
    @level.setter
    def level(self, value: float):
        """Set window level/center."""
        self._level = value
        self._current_preset = None
        self._notify_callbacks()
    
    def set_window_level(self, window: float, level: float):
        """
        Set both window and level.
        
        Args:
            window: Window width
            level: Window center/level
        """
        self._window = max(1.0, window)
        self._level = level
        self._current_preset = None
        self._notify_callbacks()
    
    def get_current(self) -> Tuple[float, float]:
        """
        Get current window/level.
        
        Returns:
            (window, level) tuple
        """
        return (self._window, self._level)
    
    def apply_preset(self, preset_name: str) -> bool:
        """
        Apply a named preset.
        
        Args:
            preset_name: Name of preset to apply (case-insensitive)
        
        Returns:
            True if preset was found and applied
        """
        preset_name = preset_name.lower()
        
        # Check standard presets
        if preset_name in self._presets:
            preset = self._presets[preset_name]
        elif preset_name in self._custom_presets:
            preset = self._custom_presets[preset_name]
        else:
            logger.warning(f"Preset not found: {preset_name}")
            return False
        
        self._window = preset.window
        self._level = preset.level
        self._current_preset = preset_name
        self._notify_callbacks()
        
        logger.info(f"Applied preset '{preset.name}': W={preset.window}, L={preset.level}")
        
        return True
    
    def get_preset_names(self) -> List[str]:
        """
        Get list of available preset names.
        
        Returns:
            List of preset names
        """
        return list(self._presets.keys()) + list(self._custom_presets.keys())
    
    def get_preset(self, name: str) -> Optional[WindowLevelPreset]:
        """
        Get preset by name.
        
        Args:
            name: Preset name
        
        Returns:
            Preset if found, None otherwise
        """
        name = name.lower()
        return self._presets.get(name) or self._custom_presets.get(name)
    
    def add_custom_preset(
        self,
        name: str,
        window: float,
        level: float,
        description: str = ""
    ):
        """
        Add a custom preset.
        
        Args:
            name: Preset name
            window: Window width
            level: Window level
            description: Optional description
        """
        preset = WindowLevelPreset(name, window, level, description)
        self._custom_presets[name.lower()] = preset
        logger.info(f"Added custom preset: {name}")
    
    def remove_custom_preset(self, name: str) -> bool:
        """
        Remove a custom preset.
        
        Args:
            name: Name of preset to remove
        
        Returns:
            True if preset was found and removed
        """
        name = name.lower()
        if name in self._custom_presets:
            del self._custom_presets[name]
            logger.info(f"Removed custom preset: {name}")
            return True
        return False
    
    def save_current_as_preset(self, name: str, description: str = ""):
        """
        Save current window/level as a custom preset.
        
        Args:
            name: Name for new preset
            description: Optional description
        """
        self.add_custom_preset(name, self._window, self._level, description)
    
    def adjust_window(self, delta: float):
        """
        Adjust window by delta amount.
        
        Args:
            delta: Amount to add to window (can be negative)
        """
        self.window = self._window + delta
    
    def adjust_level(self, delta: float):
        """
        Adjust level by delta amount.
        
        Args:
            delta: Amount to add to level (can be negative)
        """
        self.level = self._level + delta
    
    def adjust_interactive(self, dx: float, dy: float, sensitivity: float = 1.0):
        """
        Adjust window/level based on mouse movement.
        
        Standard convention: horizontal = window, vertical = level
        
        Args:
            dx: Horizontal mouse movement (pixels)
            dy: Vertical mouse movement (pixels)
            sensitivity: Adjustment sensitivity multiplier
        """
        # Window adjusts with horizontal movement
        # Level adjusts with vertical movement (inverted)
        window_delta = dx * sensitivity
        level_delta = -dy * sensitivity
        
        self._window = max(1.0, self._window + window_delta)
        self._level = self._level + level_delta
        self._current_preset = None
        self._notify_callbacks()
    
    def reset_to_default(self):
        """Reset to default preset."""
        self.apply_preset("default")
    
    def auto_window_level(
        self,
        min_value: float,
        max_value: float,
        percentile_low: float = 0.01,
        percentile_high: float = 0.99
    ):
        """
        Automatically set window/level based on image statistics.
        
        Args:
            min_value: Minimum voxel value
            max_value: Maximum voxel value
            percentile_low: Low percentile for level calculation
            percentile_high: High percentile for window calculation
        """
        # Simple auto-windowing based on range
        value_range = max_value - min_value
        
        self._window = value_range * (percentile_high - percentile_low)
        self._level = min_value + value_range * 0.5
        self._current_preset = None
        self._notify_callbacks()
        
        logger.info(f"Auto window/level: W={self._window:.1f}, L={self._level:.1f}")
    
    def add_callback(self, callback: Callable):
        """
        Add callback for window/level changes.
        
        Args:
            callback: Function(window, level) to call on changes
        """
        self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable):
        """Remove a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def _notify_callbacks(self):
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(self._window, self._level)
            except Exception as e:
                logger.warning(f"Callback error: {e}")
    
    @property
    def current_preset_name(self) -> Optional[str]:
        """Get name of currently applied preset (if any)."""
        return self._current_preset
    
    def get_all_presets(self) -> Dict[str, WindowLevelPreset]:
        """Get all available presets (standard + custom)."""
        all_presets = self._presets.copy()
        all_presets.update(self._custom_presets)
        return all_presets
