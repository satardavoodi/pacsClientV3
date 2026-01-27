"""
Curved MPR Widget - Interactive widget for curved MPR creation
Provides UI for defining centerline and generating curved MPR
"""
import logging
from typing import Optional, List, Tuple
import numpy as np

import vtkmodules.all as vtk
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSpinBox, QDoubleSpinBox, QGroupBox,
    QMessageBox, QComboBox, QCheckBox
)
from PySide6.QtCore import Signal, Qt

from .curved_mpr import CurvedMPRGenerator, InteractiveCurvedMPR

logger = logging.getLogger(__name__)


class CurvedMPRWidget(QWidget):
    """
    Widget for interactive Curved MPR creation
    
    Workflow:
    1. User clicks on 3D view to define path points
    2. System connects points to form centerline
    3. User adjusts parameters (width, height, samples)
    4. Generate curved MPR
    5. Display result
    """
    
    # Signals
    curved_mpr_generated = Signal(object)  # vtkImageData
    centerline_changed = Signal(list)  # List of points
    
    def __init__(
        self,
        image_data: vtk.vtkImageData,
        parent: Optional[QWidget] = None
    ):
        """
        Initialize Curved MPR widget
        
        Args:
            image_data: Input 3D volume
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.image_data = image_data
        self.generator = CurvedMPRGenerator(image_data)
        self.centerline_points = []
        
        # UI setup
        self._create_ui()
        
        logger.info("Created Curved MPR widget")
    
    def _create_ui(self):
        """Create user interface"""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("Curved MPR Generator")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # Instructions
        instructions = QLabel(
            "1. Click on 3D view to define centerline points\n"
            "2. Adjust parameters below\n"
            "3. Click 'Generate Curved MPR'"
        )
        instructions.setStyleSheet("color: gray;")
        layout.addWidget(instructions)
        
        # Centerline section
        centerline_group = self._create_centerline_section()
        layout.addWidget(centerline_group)
        
        # Parameters section
        params_group = self._create_parameters_section()
        layout.addWidget(params_group)
        
        # Generation section
        generation_group = self._create_generation_section()
        layout.addWidget(generation_group)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: green;")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
    
    def _create_centerline_section(self) -> QGroupBox:
        """Create centerline controls"""
        group = QGroupBox("Centerline")
        layout = QVBoxLayout(group)
        
        # Point count label
        self.point_count_label = QLabel("Points: 0")
        layout.addWidget(self.point_count_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.add_point_btn = QPushButton("Add Point (Click on View)")
        self.add_point_btn.setCheckable(True)
        self.add_point_btn.clicked.connect(self._on_add_point_mode)
        button_layout.addWidget(self.add_point_btn)
        
        self.clear_points_btn = QPushButton("Clear Points")
        self.clear_points_btn.clicked.connect(self._on_clear_points)
        button_layout.addWidget(self.clear_points_btn)
        
        layout.addLayout(button_layout)
        
        # Auto-extract option (for future VMTK integration)
        self.auto_extract_cb = QCheckBox("Auto-extract centerline (requires VMTK)")
        self.auto_extract_cb.setEnabled(False)
        self.auto_extract_cb.setToolTip("Automatic centerline extraction using VMTK (coming soon)")
        layout.addWidget(self.auto_extract_cb)
        
        return group
    
    def _create_parameters_section(self) -> QGroupBox:
        """Create parameter controls"""
        group = QGroupBox("Parameters")
        layout = QVBoxLayout(group)
        
        # Number of slices
        slices_layout = QHBoxLayout()
        slices_layout.addWidget(QLabel("Number of Slices:"))
        self.num_slices_spin = QSpinBox()
        self.num_slices_spin.setRange(10, 500)
        self.num_slices_spin.setValue(100)
        self.num_slices_spin.setToolTip("Number of perpendicular slices to extract")
        slices_layout.addWidget(self.num_slices_spin)
        slices_layout.addStretch()
        layout.addLayout(slices_layout)
        
        # Slice width
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("Slice Width (mm):"))
        self.slice_width_spin = QDoubleSpinBox()
        self.slice_width_spin.setRange(5.0, 200.0)
        self.slice_width_spin.setValue(50.0)
        self.slice_width_spin.setSingleStep(5.0)
        self.slice_width_spin.setToolTip("Width of each perpendicular slice")
        width_layout.addWidget(self.slice_width_spin)
        width_layout.addStretch()
        layout.addLayout(width_layout)
        
        # Slice height
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("Slice Height (mm):"))
        self.slice_height_spin = QDoubleSpinBox()
        self.slice_height_spin.setRange(5.0, 200.0)
        self.slice_height_spin.setValue(50.0)
        self.slice_height_spin.setSingleStep(5.0)
        self.slice_height_spin.setToolTip("Height of each perpendicular slice")
        height_layout.addWidget(self.slice_height_spin)
        height_layout.addStretch()
        layout.addLayout(height_layout)
        
        # Interpolation method
        interp_layout = QHBoxLayout()
        interp_layout.addWidget(QLabel("Interpolation:"))
        self.interpolation_combo = QComboBox()
        self.interpolation_combo.addItems(["Linear", "Cubic", "Lanczos (Best Quality)"])
        self.interpolation_combo.setCurrentIndex(2)  # Default to Lanczos
        self.interpolation_combo.setToolTip("Interpolation method for reslicing")
        interp_layout.addWidget(self.interpolation_combo)
        interp_layout.addStretch()
        layout.addLayout(interp_layout)
        
        return group
    
    def _create_generation_section(self) -> QGroupBox:
        """Create generation controls"""
        group = QGroupBox("Generation")
        layout = QVBoxLayout(group)
        
        # Preview button
        self.preview_btn = QPushButton("Preview (Low Resolution)")
        self.preview_btn.clicked.connect(self._on_preview)
        self.preview_btn.setEnabled(False)
        layout.addWidget(self.preview_btn)
        
        # Generate button
        self.generate_btn = QPushButton("Generate Curved MPR")
        self.generate_btn.clicked.connect(self._on_generate)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 8px; }"
            "QPushButton:disabled { background-color: #cccccc; }"
        )
        layout.addWidget(self.generate_btn)
        
        # Save button
        self.save_btn = QPushButton("Save to File")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setEnabled(False)
        layout.addWidget(self.save_btn)
        
        return group
    
    def add_centerline_point(self, point: Tuple[float, float, float]):
        """
        Add point to centerline
        
        Args:
            point: 3D point coordinates (x, y, z)
        """
        self.centerline_points.append(point)
        self.point_count_label.setText(f"Points: {len(self.centerline_points)}")
        
        # Enable generation if we have enough points
        if len(self.centerline_points) >= 2:
            self.preview_btn.setEnabled(True)
            self.generate_btn.setEnabled(True)
            self.status_label.setText("Ready to generate")
            self.status_label.setStyleSheet("color: green;")
        
        # Emit signal
        self.centerline_changed.emit(self.centerline_points)
        
        logger.info(f"Added centerline point: {point}, total: {len(self.centerline_points)}")
    
    def _on_add_point_mode(self, checked: bool):
        """Toggle add point mode"""
        if checked:
            self.add_point_btn.setText("Adding Points... (Click to Stop)")
            self.status_label.setText("Click on 3D view to add points")
            self.status_label.setStyleSheet("color: blue;")
        else:
            self.add_point_btn.setText("Add Point (Click on View)")
            self.status_label.setText("Ready")
            self.status_label.setStyleSheet("color: green;")
    
    def _on_clear_points(self):
        """Clear all centerline points"""
        if not self.centerline_points:
            return
        
        reply = QMessageBox.question(
            self,
            "Clear Points",
            "Are you sure you want to clear all centerline points?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.centerline_points.clear()
            self.point_count_label.setText("Points: 0")
            self.preview_btn.setEnabled(False)
            self.generate_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            self.centerline_changed.emit([])
            self.status_label.setText("Points cleared")
            logger.info("Cleared all centerline points")
    
    def _on_preview(self):
        """Generate low-resolution preview"""
        try:
            self.status_label.setText("Generating preview...")
            self.status_label.setStyleSheet("color: orange;")
            
            # Use fewer slices for preview
            preview_slices = min(50, len(self.centerline_points))
            
            self.generator.set_centerline(self.centerline_points)
            curved_mpr = self.generator.generate_curved_mpr(
                slice_width=self.slice_width_spin.value(),
                slice_height=self.slice_height_spin.value(),
                num_slices=preview_slices
            )
            
            self.curved_mpr_generated.emit(curved_mpr)
            self.status_label.setText("Preview generated")
            self.status_label.setStyleSheet("color: green;")
            
            logger.info("Generated preview curved MPR")
            
        except Exception as e:
            logger.error(f"Error generating preview: {e}")
            self.status_label.setText(f"Error: {str(e)}")
            self.status_label.setStyleSheet("color: red;")
            QMessageBox.warning(self, "Error", f"Failed to generate preview:\n{str(e)}")
    
    def _on_generate(self):
        """Generate full-resolution curved MPR"""
        try:
            self.status_label.setText("Generating curved MPR...")
            self.status_label.setStyleSheet("color: orange;")
            
            # Set centerline
            self.generator.set_centerline(self.centerline_points)
            
            # Generate curved MPR
            curved_mpr = self.generator.generate_curved_mpr(
                slice_width=self.slice_width_spin.value(),
                slice_height=self.slice_height_spin.value(),
                num_slices=self.num_slices_spin.value()
            )
            
            # Emit signal
            self.curved_mpr_generated.emit(curved_mpr)
            
            # Enable save button
            self.save_btn.setEnabled(True)
            
            self.status_label.setText("Curved MPR generated successfully")
            self.status_label.setStyleSheet("color: green;")
            
            logger.info(
                f"Generated curved MPR: "
                f"{self.num_slices_spin.value()} slices, "
                f"{self.slice_width_spin.value()}x{self.slice_height_spin.value()}mm"
            )
            
        except Exception as e:
            logger.error(f"Error generating curved MPR: {e}")
            self.status_label.setText(f"Error: {str(e)}")
            self.status_label.setStyleSheet("color: red;")
            QMessageBox.warning(self, "Error", f"Failed to generate curved MPR:\n{str(e)}")
    
    def _on_save(self):
        """Save curved MPR to file"""
        # TODO: Implement file save dialog
        QMessageBox.information(
            self,
            "Save",
            "Save functionality will be implemented in the next version."
        )
        logger.info("Save button clicked (not yet implemented)")
    
    def get_interpolation_mode(self) -> str:
        """Get selected interpolation mode"""
        text = self.interpolation_combo.currentText()
        if "Linear" in text:
            return "linear"
        elif "Cubic" in text:
            return "cubic"
        else:
            return "lanczos"


class CurvedMPRDialog(QWidget):
    """
    Standalone dialog for curved MPR creation
    Can be opened from MPR toolbar
    """
    
    def __init__(
        self,
        image_data: vtk.vtkImageData,
        parent: Optional[QWidget] = None
    ):
        """
        Initialize dialog
        
        Args:
            image_data: Input 3D volume
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Set window flags for proper dialog behavior
        self.setWindowFlags(Qt.Window)
        
        self.setWindowTitle("Curved MPR Generator")
        self.setMinimumSize(400, 600)
        
        # Main layout
        layout = QVBoxLayout(self)
        
        # Add curved MPR widget
        self.curved_mpr_widget = CurvedMPRWidget(image_data, self)
        layout.addWidget(self.curved_mpr_widget)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        logger.info("Created Curved MPR dialog")

