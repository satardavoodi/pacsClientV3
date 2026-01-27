"""
MPR Toolbar - Simplified toolbar for MPR viewer
Only includes plane selection
"""
import logging
from typing import Optional
from enum import Enum

from PySide6.QtWidgets import (
    QToolBar, QWidget, QLabel, QPushButton, QButtonGroup,
    QMenu, QToolButton
)
from PySide6.QtCore import Signal, QSize, QTimer

logger = logging.getLogger(__name__)


class MPRToolbarAction(Enum):
    """MPR toolbar action types"""
    AXIAL = "axial"
    SAGITTAL = "sagittal"
    CORONAL = "coronal"
    OBLIQUE = "oblique"
    CURVED = "curved"


class MPRToolbar(QToolBar):
    """
    Simplified MPR Toolbar with plane selection only
    """
    
    # Signals
    action_triggered = Signal(str, object)  # (action_name, value)
    plane_changed = Signal(str)  # plane name
    curved_mpr_requested = Signal()  # Signal for curved MPR tool
    curved_mpr_toggle = Signal(bool)  # Signal for toggle mode (on/off)
    curved_mpr_generate = Signal()  # Signal for generate CPR
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Args:
            parent: Parent widget
        """
        super().__init__("MPR Tools", parent)
        
        self.setMovable(True)
        self.setFloatable(True)
        self.setIconSize(QSize(24, 24))
        
        # State
        self.current_plane = "axial"
        self.vtk_widget = None  # Will be set later
        
        # Timer for checking point count
        self.point_check_timer = QTimer(self)
        self.point_check_timer.timeout.connect(self._update_generate_button)
        
        # Create toolbar
        self._create_plane_section()
        self.addSeparator()
        self._create_tools_section()
        
        logger.info("Created MPR toolbar with plane selection and tools")
    
    def _create_plane_section(self):
        """Create plane selection buttons"""
        # Plane selection label
        label = QLabel(" View: ")
        label.setStyleSheet("font-weight: bold;")
        self.addWidget(label)
        
        # Create button group for exclusive selection
        self.plane_group = QButtonGroup(self)
        self.plane_group.setExclusive(True)
        
        # Axial button
        self.axial_btn = QPushButton("Axial")
        self.axial_btn.setCheckable(True)
        self.axial_btn.setChecked(True)
        self.axial_btn.setToolTip("Switch to Axial view (XY plane)")
        self.axial_btn.clicked.connect(lambda: self._on_plane_selected("axial"))
        self.plane_group.addButton(self.axial_btn)
        self.addWidget(self.axial_btn)
        
        # Sagittal button
        self.sagittal_btn = QPushButton("Sagittal")
        self.sagittal_btn.setCheckable(True)
        self.sagittal_btn.setToolTip("Switch to Sagittal view (YZ plane)")
        self.sagittal_btn.clicked.connect(lambda: self._on_plane_selected("sagittal"))
        self.plane_group.addButton(self.sagittal_btn)
        self.addWidget(self.sagittal_btn)
        
        # Coronal button
        self.coronal_btn = QPushButton("Coronal")
        self.coronal_btn.setCheckable(True)
        self.coronal_btn.setToolTip("Switch to Coronal view (XZ plane)")
        self.coronal_btn.clicked.connect(lambda: self._on_plane_selected("coronal"))
        self.plane_group.addButton(self.coronal_btn)
        self.addWidget(self.coronal_btn)
        
        # Oblique button
        self.oblique_btn = QPushButton("Oblique")
        self.oblique_btn.setCheckable(True)
        self.oblique_btn.setToolTip("Switch to Oblique view (custom angle)")
        self.oblique_btn.clicked.connect(lambda: self._on_plane_selected("oblique"))
        self.plane_group.addButton(self.oblique_btn)
        self.addWidget(self.oblique_btn)
        
        self.addSeparator()
        
        # Curved MPR Toggle button
        self.curved_mpr_toggle_btn = QPushButton("▶ Start Curved MPR")
        self.curved_mpr_toggle_btn.setCheckable(True)
        self.curved_mpr_toggle_btn.setToolTip("Enable Curved MPR mode - Click to pick points on the view")
        self.curved_mpr_toggle_btn.clicked.connect(self._on_curved_mpr_toggled)
        self.curved_mpr_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #64748b;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #475569;
            }
            QPushButton:checked {
                background-color: #10b981;
                border: 2px solid #fbbf24;
            }
        """)
        self.addWidget(self.curved_mpr_toggle_btn)
        
        # Curved MPR Generate button
        self.curved_mpr_generate_btn = QPushButton("🎯 Generate CPR")
        self.curved_mpr_generate_btn.setEnabled(False)
        self.curved_mpr_generate_btn.setToolTip("Generate and view the curved reformation image (need at least 2 points)")
        self.curved_mpr_generate_btn.clicked.connect(self._on_curved_mpr_generate)
        self.curved_mpr_generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
            QPushButton:disabled {
                background-color: #424242;
                color: #888888;
            }
        """)
        self.addWidget(self.curved_mpr_generate_btn)
    
    def _on_plane_selected(self, plane: str):
        """Handle plane selection"""
        self.current_plane = plane
        self.plane_changed.emit(plane)
        self.action_triggered.emit("plane_changed", plane)
        logger.info(f"Plane changed to: {plane}")
    
    def _create_tools_section(self):
        """Create MPR tools dropdown menu"""
        # Tools label
        tools_label = QLabel(" Tools: ")
        tools_label.setStyleSheet("font-weight: bold;")
        self.addWidget(tools_label)
        
        # Create tools dropdown button
        tools_button = QToolButton()
        tools_button.setText("MPR Tools")
        tools_button.setPopupMode(QToolButton.InstantPopup)
        tools_button.setToolTip("Advanced MPR Tools")
        
        # Create dropdown menu
        tools_menu = QMenu(tools_button)
        
        # Add Curved MPR action
        curved_mpr_action = tools_menu.addAction("Curved MPR")
        curved_mpr_action.setToolTip("Create curved multi-planar reconstruction along a path")
        curved_mpr_action.triggered.connect(self._on_curved_mpr_clicked)
        
        # Add Maximum Intensity Projection action
        mip_action = tools_menu.addAction("Maximum Intensity Projection (MIP)")
        mip_action.setToolTip("Create maximum intensity projection")
        mip_action.triggered.connect(lambda: self._on_tool_clicked("mip"))
        
        # Add Minimum Intensity Projection action
        minip_action = tools_menu.addAction("Minimum Intensity Projection (MinIP)")
        minip_action.setToolTip("Create minimum intensity projection")
        minip_action.triggered.connect(lambda: self._on_tool_clicked("minip"))
        
        # Add Volume Rendering action
        volume_action = tools_menu.addAction("Volume Rendering")
        volume_action.setToolTip("Enable volume rendering mode")
        volume_action.triggered.connect(lambda: self._on_tool_clicked("volume_rendering"))
        
        tools_button.setMenu(tools_menu)
        self.addWidget(tools_button)
        
        logger.info("Added MPR tools dropdown menu")
    
    def _on_curved_mpr_toggled(self, checked):
        """Handle Curved MPR toggle button"""
        logger.info(f"Curved MPR mode {'activated' if checked else 'deactivated'}")
        
        # Update button text
        if checked:
            self.curved_mpr_toggle_btn.setText("⬛ Stop Curved MPR")
            # Start timer to check point count
            self.point_check_timer.start(500)  # Check every 500ms
        else:
            self.curved_mpr_toggle_btn.setText("▶ Start Curved MPR")
            # Stop timer
            self.point_check_timer.stop()
            # Disable generate button
            self.curved_mpr_generate_btn.setEnabled(False)
            self.curved_mpr_generate_btn.setText("🎯 Generate CPR")
        
        # Emit signals
        self.curved_mpr_toggle.emit(checked)
        self.curved_mpr_requested.emit()
        self.action_triggered.emit("curved_mpr_toggle", checked)
    
    def _on_curved_mpr_generate(self):
        """Handle Curved MPR generate button"""
        logger.info("Curved MPR generation requested")
        self.curved_mpr_generate.emit()
        self.action_triggered.emit("curved_mpr_generate", None)
    
    def _update_generate_button(self):
        """Update generate button state based on point count"""
        if self.vtk_widget is None:
            return
        
        try:
            viewer = self.vtk_widget.image_viewer
            if viewer is None:
                return
            
            # Check if curved MPR mode is active
            if not viewer.curved_mpr_module.is_active():
                return
            
            # Get point count
            point_count = viewer.curved_mpr_module.get_point_count()
            
            # Enable/disable generate button
            self.curved_mpr_generate_btn.setEnabled(point_count >= 2)
            
            # Update button text
            if point_count >= 2:
                self.curved_mpr_generate_btn.setText(f"🎯 Generate CPR ({point_count} points)")
            else:
                needed = 2 - point_count
                self.curved_mpr_generate_btn.setText(f"🎯 Generate CPR (need {needed} more)")
                
        except Exception as e:
            logger.error(f"Error updating generate button: {e}")
    
    def set_vtk_widget(self, vtk_widget):
        """
        Set the VTK widget for accessing viewer state.
        
        Args:
            vtk_widget: VTKWidget instance
        """
        self.vtk_widget = vtk_widget
        logger.info("VTK widget set for Curved MPR toolbar")
    
    def _on_curved_mpr_clicked(self):
        """Handle Curved MPR menu item click (from dropdown)"""
        logger.info("Curved MPR tool requested from menu")
        # Toggle the button state
        self.curved_mpr_toggle_btn.setChecked(not self.curved_mpr_toggle_btn.isChecked())
        self.curved_mpr_requested.emit()
        self.action_triggered.emit("curved_mpr", self.curved_mpr_toggle_btn.isChecked())
    
    def _on_tool_clicked(self, tool_name: str):
        """Handle tool button click"""
        logger.info(f"MPR tool requested: {tool_name}")
        self.action_triggered.emit(tool_name, None)
    
    def set_plane(self, plane: str):
        """
        Programmatically set plane
        
        Args:
            plane: Plane name (axial, sagittal, coronal, oblique)
        """
        plane = plane.lower()
        if plane == "axial":
            self.axial_btn.setChecked(True)
        elif plane == "sagittal":
            self.sagittal_btn.setChecked(True)
        elif plane == "coronal":
            self.coronal_btn.setChecked(True)
        elif plane == "oblique":
            self.oblique_btn.setChecked(True)
        
        self.current_plane = plane


class MPRToolbarManager:
    """
    Manager for MPR toolbar
    Handles toolbar creation and integration with MPR viewer
    """
    
    def __init__(self, mpr_widget):
        """
        Args:
            mpr_widget: MPR widget to control
        """
        self.mpr_widget = mpr_widget
        self.toolbar = MPRToolbar()
        
        # Connect toolbar signals to MPR widget
        self._connect_signals()
        
        logger.info("Created MPR toolbar manager")
    
    def _connect_signals(self):
        """Connect toolbar signals to MPR widget handlers"""
        self.toolbar.action_triggered.connect(self._handle_action)
        self.toolbar.plane_changed.connect(self._handle_plane_change)
    
    def _handle_action(self, action: str, value):
        """Handle toolbar action"""
        try:
            if action == "plane_changed":
                self._handle_plane_change(value)
        except Exception as e:
            logger.error(f"Error handling action {action}: {e}")
    
    def _handle_plane_change(self, plane: str):
        """Handle plane change"""
        logger.info(f"Plane changed to: {plane}")
    
    def get_toolbar(self) -> MPRToolbar:
        """Get toolbar widget"""
        return self.toolbar
