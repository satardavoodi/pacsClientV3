"""
2D Viewer with Advanced Tools Panel
====================================

This module provides a QWidget wrapper for ImageViewer2D with integrated
advanced medical imaging tools panel.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter
)
from PySide6.QtCore import Qt
import vtkmodules.all as vtk

from .advanced_tools_panel import AdvancedToolsPanel


class Viewer2DWithTools(QWidget):
    """
    2D Viewer with integrated advanced tools panel
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Store references
        self.image_viewer = None
        self.vtk_image_data = None
        self.renderer = None
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI layout"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side: VTK viewer placeholder
        # (Will be populated when viewer is set)
        self.viewer_container = QWidget()
        viewer_layout = QVBoxLayout(self.viewer_container)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        
        # Right side: Advanced tools panel
        self.tools_panel = AdvancedToolsPanel()
        self.tools_panel.setMaximumWidth(350)
        self.tools_panel.setMinimumWidth(280)
        
        # Add to splitter
        splitter.addWidget(self.viewer_container)
        splitter.addWidget(self.tools_panel)
        
        # Set initial sizes (viewer takes most space)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(splitter)
        
        # Connect signals
        self.tools_panel.tool_applied.connect(self._on_tool_applied)
        self.tools_panel.processing_started.connect(self._on_processing_started)
        self.tools_panel.processing_finished.connect(self._on_processing_finished)
    
    def set_image_viewer(self, image_viewer):
        """
        Set the 2D image viewer
        
        Args:
            image_viewer: ImageViewer2D instance
        """
        self.image_viewer = image_viewer
        
        # Add viewer widget to container if it has one
        if hasattr(image_viewer, 'GetRenderWindow'):
            # This is a VTK viewer - we need the Qt widget
            pass
    
    def set_image_data(self, image_data: vtk.vtkImageData):
        """
        Set image data for tools
        
        Args:
            image_data: VTK image data
        """
        self.vtk_image_data = image_data
        self.tools_panel.set_image_data(image_data)
    
    def set_renderer(self, renderer: vtk.vtkRenderer):
        """
        Set VTK renderer
        
        Args:
            renderer: VTK renderer
        """
        self.renderer = renderer
        self.tools_panel.set_renderer(renderer)
    
    def _on_tool_applied(self, tool_name: str, result):
        """
        Handle tool application
        
        Args:
            tool_name: Name of the tool
            result: Result object (volume, actor, etc.)
        """
        print(f"Tool applied: {tool_name}")
        
        # Handle different result types
        if isinstance(result, vtk.vtkVolume):
            # Volume rendering result
            if self.renderer:
                self.renderer.AddVolume(result)
                self.renderer.ResetCamera()
                self.renderer.GetRenderWindow().Render()
        
        elif isinstance(result, vtk.vtkActor):
            # Surface actor result
            if self.renderer:
                self.renderer.AddActor(result)
                self.renderer.ResetCamera()
                self.renderer.GetRenderWindow().Render()
        
        elif isinstance(result, list):
            # Multiple actors
            if self.renderer:
                for item in result:
                    if isinstance(item, vtk.vtkActor):
                        self.renderer.AddActor(item)
                    elif isinstance(item, vtk.vtkVolume):
                        self.renderer.AddVolume(item)
                self.renderer.ResetCamera()
                self.renderer.GetRenderWindow().Render()
        
        elif isinstance(result, dict):
            # Dictionary of actors (multi-tissue)
            if self.renderer:
                for name, actor in result.items():
                    if isinstance(actor, vtk.vtkActor):
                        self.renderer.AddActor(actor)
                    elif isinstance(actor, vtk.vtkVolume):
                        self.renderer.AddVolume(actor)
                self.renderer.ResetCamera()
                self.renderer.GetRenderWindow().Render()
        
        elif isinstance(result, vtk.vtkImageData):
            # Image data result (masks, slabs)
            # Could display as overlay
            if self.image_viewer and hasattr(self.image_viewer, 'overlay'):
                # Create temporary file for overlay
                import tempfile
                import nibabel as nib
                import numpy as np
                from vtkmodules.util import numpy_support
                
                try:
                    # Convert vtkImageData to numpy
                    vtk_array = result.GetPointData().GetScalars()
                    numpy_array = numpy_support.vtk_to_numpy(vtk_array)
                    dims = result.GetDimensions()
                    numpy_array = numpy_array.reshape(dims[2], dims[1], dims[0])
                    
                    # Create NIfTI and save temporarily
                    nifti_img = nib.Nifti1Image(numpy_array, np.eye(4))
                    temp_file = tempfile.NamedTemporaryFile(suffix='.nii.gz', delete=False)
                    nib.save(nifti_img, temp_file.name)
                    
                    # Overlay on viewer
                    self.image_viewer.overlay(
                        temp_file.name,
                        color=(1.0, 1.0, 0.0),
                        opacity=0.4,
                        is_label=True
                    )
                except Exception as e:
                    print(f"Error creating overlay: {e}")
    
    def _on_processing_started(self, message: str):
        """Handle processing start"""
        print(f"Processing started: {message}")
        # Could show spinner or disable UI
    
    def _on_processing_finished(self, message: str):
        """Handle processing finish"""
        print(f"Processing finished")
        # Could hide spinner or re-enable UI

