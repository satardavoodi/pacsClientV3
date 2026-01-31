"""
Orthogonal MPR Viewer Widget - Main widget for MPR visualization

Provides a complete MPR viewer with three synchronized orthogonal views
(Axial, Sagittal, Coronal), toolbar, and all advanced features.
"""

import logging
from typing import Optional, Dict, Tuple, List
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QFrame, QLabel, QSizePolicy
)
from PySide6.QtCore import Qt, Signal

import vtkmodules.all as vtk

from ..core.volume_loader import VolumeLoader
from ..core.mpr_calculator import MPRCalculator, PlaneType
from ..views.mpr_slice_view import MPRSliceView
from ..views.crosshair_manager import CrosshairManager
from ..features.window_level import WindowLevelManager, CT_PRESETS
from ..features.thick_slab import ThickSlabMPR, SlabMode, ThickSlabController
from .toolbar import MPRToolbar
from .slice_slider import SliceSlider

logger = logging.getLogger(__name__)


class MPRViewPanel(QFrame):
    """
    Panel containing a single MPR view with its slider and label.
    """
    
    def __init__(
        self,
        plane_type: PlaneType,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        
        self.plane_type = plane_type
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI."""
        self.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 1px solid #333;
                border-radius: 4px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        # Title label
        title = self.plane_type.value.capitalize()
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("""
            QLabel {
                color: #00aa00;
                font-weight: bold;
                font-size: 12px;
                padding: 2px 4px;
                background-color: rgba(0, 0, 0, 100);
                border-radius: 3px;
            }
        """)
        self._title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title_label)
        
        # View container
        view_container = QHBoxLayout()
        view_container.setContentsMargins(0, 0, 0, 0)
        view_container.setSpacing(2)
        
        # MPR view placeholder (will be set later)
        self._view_placeholder = QFrame()
        self._view_placeholder.setStyleSheet("background-color: black;")
        self._view_placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        view_container.addWidget(self._view_placeholder, stretch=1)
        
        # Slice slider
        self._slider = SliceSlider(Qt.Vertical)
        self._slider.setFixedWidth(50)
        view_container.addWidget(self._slider)
        
        layout.addLayout(view_container, stretch=1)
        
        # Public references
        self.view: Optional[MPRSliceView] = None
        self.slider = self._slider
    
    def set_view(self, view: MPRSliceView):
        """Set the MPR view."""
        self.view = view
        
        # Replace placeholder with actual view
        layout = self._view_placeholder.parent().layout()
        if layout:
            layout.replaceWidget(self._view_placeholder, view)
            self._view_placeholder.deleteLater()
            self._view_placeholder = view
        
        # Connect slider to view
        self._slider.slice_changed.connect(view.set_slice)
    
    def update_slider_range(self, min_val: int, max_val: int):
        """Update slider range."""
        self._slider.set_range(min_val, max_val)
        self._slider.set_value((min_val + max_val) // 2)
    
    def set_slider_spacing(self, spacing: float):
        """Set slider spacing for position display."""
        self._slider.set_spacing(spacing)


class OrthogonalMPRWidget(QWidget):
    """
    Main widget for orthogonal MPR visualization.
    
    Provides three synchronized MPR views (Axial, Sagittal, Coronal)
    with a toolbar for Window/Level presets, crosshairs, thick slab,
    and measurement tools.
    
    Example:
        >>> widget = OrthogonalMPRWidget()
        >>> widget.load_dicom_series("/path/to/dicom")
        >>> widget.show()
    
    Signals:
        data_loaded: Emitted when data is successfully loaded
        slice_changed(plane_type, index): Emitted when slice changes
        window_level_changed(window, level): Emitted when W/L changes
    """
    
    # Signals
    data_loaded = Signal()
    slice_changed = Signal(str, int)  # plane_type, index
    window_level_changed = Signal(float, float)
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize orthogonal MPR widget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Core components
        self._volume_loader = VolumeLoader()
        self._mpr_calculator: Optional[MPRCalculator] = None
        self._crosshair_manager = CrosshairManager()
        self._window_level_manager = WindowLevelManager()
        self._thick_slab_controller = ThickSlabController()
        
        # Views
        self._views: Dict[PlaneType, MPRSliceView] = {}
        self._panels: Dict[PlaneType, MPRViewPanel] = {}
        
        # State
        self._is_loaded = False
        
        # Initialize UI
        self._init_ui()
        
        # Connect signals
        self._connect_signals()
        
        logger.info("OrthogonalMPRWidget initialized")
    
    def _init_ui(self):
        """Initialize UI components."""
        self.setStyleSheet("""
            QWidget {
                background-color: #0d0d0d;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        # Toolbar
        self._toolbar = MPRToolbar()
        layout.addWidget(self._toolbar)
        
        # Views container - horizontal layout for 3 views
        views_container = QHBoxLayout()
        views_container.setContentsMargins(0, 0, 0, 0)
        views_container.setSpacing(4)
        
        # Create panels for each plane
        for plane_type in [PlaneType.AXIAL, PlaneType.SAGITTAL, PlaneType.CORONAL]:
            panel = MPRViewPanel(plane_type)
            self._panels[plane_type] = panel
            views_container.addWidget(panel, stretch=1)
        
        layout.addLayout(views_container, stretch=1)
    
    def _connect_signals(self):
        """Connect internal signals."""
        # Toolbar signals
        self._toolbar.preset_changed.connect(self._on_preset_changed)
        self._toolbar.crosshairs_toggled.connect(self._on_crosshairs_toggled)
        self._toolbar.thick_slab_changed.connect(self._on_thick_slab_changed)
        self._toolbar.tool_selected.connect(self._on_tool_selected)
        self._toolbar.reset_view.connect(self._on_reset_view)
        
        # Window/Level manager callback
        self._window_level_manager.add_callback(self._on_window_level_changed)
    
    def load_dicom_series(self, directory: str) -> bool:
        """
        Load DICOM series from directory.
        
        Args:
            directory: Path to DICOM directory
        
        Returns:
            True if loading successful
        """
        try:
            logger.info(f"Loading DICOM series from: {directory}")
            
            # Load volume
            self._volume_loader.load_dicom_series(directory)
            vtk_image = self._volume_loader.to_vtk_image()
            
            # Initialize MPR
            self._initialize_mpr(vtk_image)
            
            # Get metadata and set initial window/level
            ww, wl = self._volume_loader.get_window_level()
            self._window_level_manager.set_window_level(ww, wl)
            
            self._is_loaded = True
            self.data_loaded.emit()
            
            logger.info("DICOM series loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load DICOM series: {e}")
            return False
    
    def load_vtk_image(self, vtk_image: vtk.vtkImageData) -> bool:
        """
        Load from existing VTK image data.
        
        Args:
            vtk_image: vtkImageData to display
        
        Returns:
            True if loading successful
        """
        try:
            logger.info("Loading VTK image data")
            
            self._initialize_mpr(vtk_image)
            
            self._is_loaded = True
            self.data_loaded.emit()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load VTK image: {e}")
            return False
    
    def load_mhd(self, path: str) -> bool:
        """
        Load MHD/MHA file.
        
        Args:
            path: Path to MHD file
        
        Returns:
            True if loading successful
        """
        try:
            logger.info(f"Loading MHD file: {path}")
            
            self._volume_loader.load_mhd(path)
            vtk_image = self._volume_loader.to_vtk_image()
            
            self._initialize_mpr(vtk_image)
            
            self._is_loaded = True
            self.data_loaded.emit()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load MHD file: {e}")
            return False
    
    def _initialize_mpr(self, vtk_image: vtk.vtkImageData):
        """Initialize MPR components with loaded image."""
        # Create MPR calculator (shared between all views)
        self._mpr_calculator = MPRCalculator(vtk_image)
        
        # Store vtk_image reference
        self._vtk_image = vtk_image
        
        # Create views for each plane
        for plane_type in [PlaneType.AXIAL, PlaneType.SAGITTAL, PlaneType.CORONAL]:
            # Create view
            view = MPRSliceView(plane_type)
            
            # Set image data first
            view.set_image(vtk_image)
            
            # Then set shared calculator
            view.set_mpr_calculator(self._mpr_calculator)
            
            self._views[plane_type] = view
            
            # Add to panel
            panel = self._panels[plane_type]
            panel.set_view(view)
            
            # Update slider range
            min_s, max_s = self._mpr_calculator.get_slice_range(plane_type)
            panel.update_slider_range(min_s, max_s)
            
            # Set slider spacing
            spacing = self._mpr_calculator.spacing
            if plane_type == PlaneType.AXIAL:
                panel.set_slider_spacing(spacing[2])
            elif plane_type == PlaneType.SAGITTAL:
                panel.set_slider_spacing(spacing[0])
            elif plane_type == PlaneType.CORONAL:
                panel.set_slider_spacing(spacing[1])
            
            # Connect slice change signal
            view.add_slice_changed_callback(self._on_view_slice_changed)
            view.add_center_changed_callback(self._on_view_center_changed)
        
        # Update crosshair manager with calculator
        self._crosshair_manager.set_calculator(self._mpr_calculator)
        
        # Add views to crosshair manager
        for view in self._views.values():
            self._crosshair_manager.add_view(view)
        
        # Apply initial window/level
        window, level = self._window_level_manager.get_current()
        self._apply_window_level(window, level)
    
    def _on_view_slice_changed(self, plane_type: PlaneType, index: int):
        """Handle slice change from view."""
        # Update corresponding slider
        panel = self._panels.get(plane_type)
        if panel:
            panel.slider.set_value(index)
        
        # Update other views' crosshairs
        for pt, view in self._views.items():
            if pt != plane_type:
                view.update_from_calculator()
        
        self.slice_changed.emit(plane_type.value, index)
    
    def _on_view_center_changed(self, source_plane: PlaneType, new_center: list):
        """Handle center change from clicking in a view."""
        # Update the shared calculator
        if self._mpr_calculator:
            self._mpr_calculator.set_center(new_center)
        
        # Update all views including sliders
        for plane_type, view in self._views.items():
            if plane_type != source_plane:
                view.update_from_calculator()
                
            # Update slider to match current slice
            panel = self._panels.get(plane_type)
            if panel:
                current_slice = view.get_slice()
                panel.slider.set_value(current_slice)
    
    def _on_preset_changed(self, preset_name: str):
        """Handle preset change from toolbar."""
        self._window_level_manager.apply_preset(preset_name)
    
    def _on_window_level_changed(self, window: float, level: float):
        """Handle window/level change."""
        self._apply_window_level(window, level)
        self.window_level_changed.emit(window, level)
    
    def _apply_window_level(self, window: float, level: float):
        """Apply window/level to all views."""
        for view in self._views.values():
            view.set_window_level(window, level)
    
    def _on_crosshairs_toggled(self, visible: bool):
        """Handle crosshair toggle."""
        self._crosshair_manager.set_crosshairs_visible(visible)
    
    def _on_thick_slab_changed(self, mode: str, thickness: float):
        """Handle thick slab settings change."""
        if mode == "disabled":
            self._thick_slab_controller.set_enabled(False)
        else:
            self._thick_slab_controller.set_enabled(True)
            
            # Map mode string to SlabMode
            mode_map = {
                "mip": SlabMode.MIP,
                "minip": SlabMode.MINIP,
                "mean": SlabMode.MEAN,
            }
            slab_mode = mode_map.get(mode, SlabMode.MEAN)
            
            self._thick_slab_controller.set_mode_all(slab_mode)
            self._thick_slab_controller.set_thickness_all(thickness)
    
    def _on_tool_selected(self, tool: str):
        """Handle tool selection."""
        logger.debug(f"Tool selected: {tool}")
        # TODO: Implement tool switching for measurements
    
    def _on_reset_view(self):
        """Handle reset view request."""
        # Reset crosshairs to center
        self._crosshair_manager.reset_to_center()
        
        # Reset cameras
        for view in self._views.values():
            view.reset_camera()
        
        # Reset window/level
        self._window_level_manager.reset_to_default()
    
    def set_window_level(self, window: float, level: float):
        """
        Set window/level values.
        
        Args:
            window: Window width
            level: Window center/level
        """
        self._window_level_manager.set_window_level(window, level)
    
    def get_window_level(self) -> Tuple[float, float]:
        """Get current window/level."""
        return self._window_level_manager.get_current()
    
    def apply_preset(self, preset_name: str):
        """
        Apply a window/level preset.
        
        Args:
            preset_name: Name of preset (e.g., "lung", "bone")
        """
        self._window_level_manager.apply_preset(preset_name)
        self._toolbar.set_preset(preset_name)
    
    def set_crosshairs_visible(self, visible: bool):
        """Set crosshair visibility."""
        self._crosshair_manager.set_crosshairs_visible(visible)
        self._toolbar.set_crosshairs_visible(visible)
    
    def enable_thick_slab(self, thickness: float = 5.0, mode: str = "mean"):
        """
        Enable thick slab MPR.
        
        Args:
            thickness: Slab thickness in mm
            mode: Slab mode ("mip", "minip", "mean")
        """
        self._toolbar.set_thick_slab_enabled(True)
        self._on_thick_slab_changed(mode, thickness)
    
    def disable_thick_slab(self):
        """Disable thick slab MPR."""
        self._toolbar.set_thick_slab_enabled(False)
        self._on_thick_slab_changed("disabled", 0.0)
    
    def get_view(self, plane_type: PlaneType) -> Optional[MPRSliceView]:
        """Get view for a specific plane."""
        return self._views.get(plane_type)
    
    def get_mpr_calculator(self) -> Optional[MPRCalculator]:
        """Get MPR calculator."""
        return self._mpr_calculator
    
    def get_metadata(self) -> Dict:
        """Get loaded volume metadata."""
        return self._volume_loader.get_metadata()
    
    @property
    def is_loaded(self) -> bool:
        """Check if data is loaded."""
        return self._is_loaded
    
    def cleanup(self):
        """Clean up resources."""
        for view in self._views.values():
            view.cleanup()
        self._views.clear()
        
        logger.info("OrthogonalMPRWidget cleaned up")
    
    def closeEvent(self, event):
        """Handle close event."""
        self.cleanup()
        super().closeEvent(event)
