# -*- coding: utf-8 -*-
"""
Curved MPR Panoramic View - Dual Panel Display

نمایش دوگانه:
1. نمای پانورامیک (Panoramic/Straightened): تصویر صاف شده از مسیر منحنی
2. نمای مقطعی (Cross-Section): مقطع عمود بر مسیر با reference line

این ساختار مشابه نرم‌افزارهای دندانپزشکی (Panoramic CBCT) است.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSlider, QPushButton, QSplitter, QFrame
)
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QMouseEvent
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor


class ImageViewerWrapper:
    """
    Wrapper around vtkImageViewer2 to provide ImageViewer2D-like interface.
    This allows InteractorStyles to work with Curved MPR viewers.
    """
    def __init__(self, vtk_image_viewer, vtk_widget):
        self._viewer = vtk_image_viewer
        self.vtk_widget = vtk_widget
        
        # Shared widgets storage that persists across interactor style changes
        # This is crucial for maintaining widget visibility when switching tools
        self.widgets_by_slice = {}
        self.skip_slices = 0  # For compatibility with ImageViewer2D
        
    @property
    def image_interactor(self):
        """Get the interactor from the render window"""
        return self._viewer.GetRenderWindow().GetInteractor()
    
    @property
    def renderer(self):
        """Get the renderer"""
        return self._viewer.GetRenderer()
    
    @property
    def image_render_window(self):
        """Get the render window"""
        return self._viewer.GetRenderWindow()
    
    def GetSlice(self):
        """Get current slice index"""
        return self._viewer.GetSlice()
    
    def SetSlice(self, slice_idx):
        """Set slice index"""
        self._viewer.SetSlice(slice_idx)
    
    def set_slice(self, slice_idx):
        """
        Set slice index (VTKWidget-compatible method).
        This method also notifies the interactor style to update widget visibility.
        """
        self._viewer.SetSlice(slice_idx)
        
        # Notify interactor style to update widget visibility (like VTKWidget does)
        try:
            interactor = self._viewer.GetRenderWindow().GetInteractor()
            style = interactor.GetInteractorStyle()
            if hasattr(style, 'update_slice'):
                style.update_slice()
                print(f"[VIEWER WRAPPER] Called update_slice() after setting slice to {slice_idx}")
        except Exception as e:
            print(f"[VIEWER WRAPPER] Error calling update_slice: {e}")
    
    def GetRenderer(self):
        """Get the renderer"""
        return self._viewer.GetRenderer()
    
    def GetRenderWindow(self):
        """Get the render window"""
        return self._viewer.GetRenderWindow()
    
    def GetInteractor(self):
        """Get the interactor"""
        return self._viewer.GetRenderWindow().GetInteractor()
    
    def Render(self):
        """Render the scene"""
        self._viewer.Render()
    
    def get_count_of_slices(self):
        """Get total number of slices"""
        input_data = self._viewer.GetInput()
        if input_data:
            dims = input_data.GetDimensions()
            return dims[2]
        return 1
    
    def get_window_level(self):
        """Get window/level"""
        return self._viewer.GetColorWindow(), self._viewer.GetColorLevel()
    
    def set_window_level(self, window, level, flag_default=False):
        """Set window/level"""
        self._viewer.SetColorWindow(window)
        self._viewer.SetColorLevel(level)
    
    def update_corners_actors(self, update_just_zoom=False):
        """Mock method - Curved MPR doesn't have corner actors"""
        pass
    
    def zoom_to_fit(self):
        """Reset camera to fit the image"""
        renderer = self._viewer.GetRenderer()
        renderer.ResetCamera()
        renderer.ResetCameraClippingRange()
        self._viewer.Render()
    
    # Mock attributes for compatibility
    skip_slices = 0
    flag_set_custom_window_level = False


class CurvedMPRInteractorStyle(vtk.vtkInteractorStyleImage):
    """
    Custom interactor style for Curved MPR viewports.
    Mimics behavior of 2D viewer:
    - Left-click + Drag: Window/Level
    - Right-click + Drag: Window/Level (alternative)
    - Middle-click + Drag: Pan
    - Scroll: Navigate slices (for cross-section) or Zoom (for panoramic)
    """
    
    def __init__(self, viewer, viewport_id=None):
        super().__init__()
        self.viewer = viewer
        self.viewport_id = viewport_id  # Unique ID for this viewport
        self.windowLevel_start = None
        
    def OnLeftButtonDown(self):
        """Start window/level adjustment"""
        self.windowLevel_start = self.GetInteractor().GetEventPosition()
        self.StartWindowLevel()
        
    def OnLeftButtonUp(self):
        """End window/level adjustment"""
        self.EndWindowLevel()
        self.windowLevel_start = None
        
    def OnMouseMove(self):
        """Handle mouse move for window/level"""
        if self.windowLevel_start is not None:
            # Window/Level mode
            self.WindowLevel()
        else:
            # Default behavior
            super().OnMouseMove()
            
    def OnRightButtonDown(self):
        """Right-click also starts window/level"""
        self.windowLevel_start = self.GetInteractor().GetEventPosition()
        self.StartWindowLevel()
        
    def OnRightButtonUp(self):
        """End window/level adjustment"""
        self.EndWindowLevel()
        self.windowLevel_start = None
        
    def OnMiddleButtonDown(self):
        """Start panning"""
        self.StartPan()
        
    def OnMiddleButtonUp(self):
        """End panning"""
        self.EndPan()
    
    # Mock methods for toolbar compatibility
    def activate(self, tool=None):
        """Mock activate method - not needed for Curved MPR"""
        pass
    
    def deactivate(self, tool=None):
        """Mock deactivate method"""
        pass


class CurvedMPRViewport(QWidget):
    """
    Single viewport wrapper that can be selected and work with toolbar.
    Acts similar to VTKWidget for toolbar compatibility.
    """
    viewport_clicked = Signal(object)  # Emit self when clicked
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        # Create VTK widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.vtk_widget.setStyleSheet("background: #000000;")
        layout.addWidget(self.vtk_widget)
        
        # Mock properties for toolbar compatibility
        self.image_viewer = None
        self.current_style = None  # Will be set when viewer is created
        self.is_selected = False
        
        # Mouse tracking
        self.setMouseTracking(True)
        self.vtk_widget.setMouseTracking(True)
        
        # Install event filter to catch mouse clicks on VTK widget
        self.vtk_widget.installEventFilter(self)
        
    def set_new_interactorstyle(self, style_class):
        """
        Set new interactor style from toolbar tools.
        
        Args:
            style_class: The interactor style class (not instance)
        """
        if self.image_viewer is None:
            print(f"[CURVED MPR VIEWPORT] Cannot set interactor style - viewer not initialized")
            return
        
        try:
            # Create instance of the style
            new_style = style_class(self.image_viewer)
            
            # Set functional slider if style needs it (for AbstractInteractorStyle-based tools)
            if hasattr(new_style, 'set_slider_from_ui'):
                # Create a functional slider for slice navigation
                class FunctionalSlider:
                    def __init__(self, viewer_wrapper, parent_viewport):
                        self.viewer = viewer_wrapper
                        self.parent = parent_viewport
                    
                    def setValue(self, value):
                        """Actually change the slice when stack tool is used"""
                        # Clamp value to valid range
                        max_slice = self.viewer.get_count_of_slices() - 1
                        value = max(0, min(value, max_slice))
                        
                        # Use set_slice() instead of SetSlice() to trigger update_slice()
                        # This is critical for updating widget visibility!
                        self.viewer.set_slice(value)
                        self.viewer.Render()
                        
                        # Update reference line if this is cross-section viewport
                        if hasattr(self.parent, 'parent') and self.parent.parent():
                            parent_widget = self.parent.parent()
                            if hasattr(parent_widget, '_update_reference_line'):
                                parent_widget._update_reference_line(value)
                
                new_style.set_slider_from_ui(FunctionalSlider(self.image_viewer, self))
            
            # Set it on the interactor
            interactor = self.vtk_widget.GetRenderWindow().GetInteractor()
            interactor.SetInteractorStyle(new_style)
            
            # Update current_style reference
            self.current_style = new_style
            
            print(f"[CURVED MPR VIEWPORT] ✓ Interactor style set to: {style_class.__name__}")
            
        except Exception as e:
            print(f"[CURVED MPR VIEWPORT] ❌ Error setting interactor style: {e}")
            import traceback
            traceback.print_exc()
        
    def restore_default_interactorstyle(self):
        """Restore default CurvedMPRInteractorStyle"""
        if self.image_viewer is None:
            print(f"[CURVED MPR VIEWPORT] Cannot restore interactor style - viewer not initialized")
            return
        
        try:
            # Restore the default Curved MPR style
            # image_viewer is already a wrapper, so use it directly
            default_style = CurvedMPRInteractorStyle(self.image_viewer)
            
            interactor = self.vtk_widget.GetRenderWindow().GetInteractor()
            interactor.SetInteractorStyle(default_style)
            
            # Update current_style reference
            self.current_style = default_style
            
            print(f"[CURVED MPR VIEWPORT] ✓ Default interactor style restored")
            
        except Exception as e:
            print(f"[CURVED MPR VIEWPORT] ❌ Error restoring interactor style: {e}")
            import traceback
            traceback.print_exc()
        
    def eventFilter(self, obj, event):
        """Filter events from VTK widget to detect clicks"""
        if obj == self.vtk_widget:
            if event.type() == QEvent.Type.MouseButtonPress:
                # Emit viewport clicked signal when VTK widget is clicked
                self.viewport_clicked.emit(self)
        return super().eventFilter(obj, event)
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press to mark as selected"""
        self.viewport_clicked.emit(self)
        super().mousePressEvent(event)
        
    def set_selected(self, selected: bool):
        """Mark this viewport as selected/active"""
        self.is_selected = selected
        if selected:
            self.setStyleSheet("""
                CurvedMPRViewport {
                    background: #1e40af;
                    border: 2px solid #3b82f6;
                }
            """)
        else:
            self.setStyleSheet("""
                CurvedMPRViewport {
                    background: transparent;
                    border: none;
                }
            """)


class CurvedMPRPanoramicView(QWidget):
    """
    Dual-panel viewer for Curved MPR:
    - Left: Panoramic (straightened) view - Maximum Intensity Projection
    - Right: Cross-section (perpendicular) view with reference line
    
    Compatible with toolbar and supports viewport selection.
    """
    
    def __init__(self, curved_mpr_image: vtk.vtkImageData, num_points: int = 0, panoramic_image: vtk.vtkImageData = None, parent=None):
        super().__init__(parent)
        
        self.curved_mpr_image = curved_mpr_image
        self.num_points = num_points
        self.current_slice = 0
        self.panoramic_image = panoramic_image  # TRUE panoramic from new algorithm
        
        # Active viewport (for toolbar)
        self.active_viewport = None
        
        self._setup_ui()
        self._setup_viewers()
    
    def _create_mip_image(self, input_image):
        """
        Create Maximum Intensity Projection along X axis with SLAB thickness
        This creates a true panoramic view (like dental OPG/Panorex)
        
        Uses a thick slab (not just 1 pixel) to get better visualization
        """
        import numpy as np
        from vtkmodules.util import numpy_support
        
        print("\n" + "="*80)
        print("DEBUG: Starting MIP Creation")
        print("="*80)
        
        try:
            from scipy import ndimage
            has_scipy = True
            print("[MIP] ✓ scipy available for high-quality upsampling")
        except ImportError:
            has_scipy = False
            print("[MIP] ⚠ scipy NOT available, using simple upsampling")
        
        dims = input_image.GetDimensions()
        spacing = input_image.GetSpacing()
        print(f"[MIP] Input volume:")
        print(f"      Dimensions: {dims[0]}×{dims[1]}×{dims[2]} (X×Y×Z)")
        print(f"      Spacing: {spacing[0]:.3f}×{spacing[1]:.3f}×{spacing[2]:.3f} mm")
        print(f"      Physical size: {dims[0]*spacing[0]:.1f}×{dims[1]*spacing[1]:.1f}×{dims[2]*spacing[2]:.1f} mm")
        
        # Get scalar data as numpy array
        scalars = input_image.GetPointData().GetScalars()
        np_array = numpy_support.vtk_to_numpy(scalars)
        print(f"[MIP] Numpy array: shape={np_array.shape}, dtype={np_array.dtype}")
        print(f"      Value range: [{np_array.min():.1f}, {np_array.max():.1f}]")
        
        # Reshape to 3D: (Z, Y, X) in VTK memory layout
        volume_3d = np_array.reshape(dims[2], dims[1], dims[0])
        print(f"[MIP] Reshaped to 3D: {volume_3d.shape} (Z, Y, X)")
        
        # THICK SLAB PROJECTION:
        # Instead of taking max of ALL X pixels, use a thick central slab
        # This gives better visualization, similar to dental panoramic
        slab_thickness_ratio = 0.6  # Use central 60% of volume
        x_center = dims[0] // 2
        x_half_slab = int((dims[0] * slab_thickness_ratio) / 2)
        x_start = max(0, x_center - x_half_slab)
        x_end = min(dims[0], x_center + x_half_slab)
        
        print(f"[MIP] Slab selection:")
        print(f"      X center: {x_center}")
        print(f"      Thickness ratio: {slab_thickness_ratio*100:.0f}%")
        print(f"      X range: {x_start} to {x_end} (thickness: {x_end - x_start} pixels)")
        
        # Take maximum in the slab region
        slab_volume = volume_3d[:, :, x_start:x_end]
        print(f"[MIP] Slab volume shape: {slab_volume.shape} (Z, Y, X_slab)")
        
        mip_2d = np.max(slab_volume, axis=2)  # Result: (Z, Y)
        print(f"[MIP] MIP 2D created: {mip_2d.shape} (Z, Y)")
        print(f"      Value range: [{mip_2d.min():.1f}, {mip_2d.max():.1f}]")
        
        # TRANSPOSE for proper orientation: (Y, Z) instead of (Z, Y)
        # numpy array: (Z, Y) = (60, 810)
        # We want: Wide=810, Tall=upsampled(60)
        print(f"\n[MIP] TRANSPOSE step:")
        print(f"      Before: {mip_2d.shape} (Z, Y)")
        mip_2d = mip_2d.T  # Now: (Y, Z) = (810, 60)
        print(f"      After: {mip_2d.shape} (Y, Z)")
        
        # UPSAMPLE in BOTH directions for better panoramic view
        # Dental panoramic should be WIDE and TALL with good resolution
        scale_factor_y = 2.0  # Make width 2x larger (810 → 1620 pixels)
        scale_factor_z = 10.0  # Make height 10x taller (60 → 600 pixels)
        
        print(f"\n[MIP] UPSAMPLING step:")
        print(f"      Input shape: {mip_2d.shape} (Y, Z)")
        print(f"      Scale factors: Y×{scale_factor_y}, Z×{scale_factor_z}")
        print(f"      Expected output: {int(mip_2d.shape[0]*scale_factor_y)}×{int(mip_2d.shape[1]*scale_factor_z)}")
        
        if has_scipy:
            # (Y, Z) = (810, 60) → zoom (2.0, 10.0) → (1620, 600)
            zoom_factors = (scale_factor_y, scale_factor_z)
            print(f"      Using scipy.ndimage.zoom with order=1 (bilinear)")
            mip_2d_upsampled = ndimage.zoom(mip_2d, zoom_factors, order=1)  # Bilinear
            print(f"      ✓ Upsampled with scipy zoom: {zoom_factors}")
        else:
            # Fallback: simple repeat
            print(f"      Using np.repeat (nearest neighbor)")
            mip_2d_upsampled = np.repeat(mip_2d, int(scale_factor_y), axis=0)
            mip_2d_upsampled = np.repeat(mip_2d_upsampled, int(scale_factor_z), axis=1)
            print(f"      ✓ Upsampled with repeat: Y×{scale_factor_y}, Z×{scale_factor_z}")
        
        # Now we have: (Y, Z) = (1620, 600)
        # For VTK: Width=X=1620, Height=Y=600
        
        final_width = mip_2d_upsampled.shape[0]   # 1620 (Y becomes Width)
        final_height = mip_2d_upsampled.shape[1]  # 600 (Z becomes Height)
        
        print(f"\n[MIP] UPSAMPLING result:")
        print(f"      Final numpy shape: {mip_2d_upsampled.shape} (Y, Z)")
        print(f"      Width: {final_width} pixels")
        print(f"      Height: {final_height} pixels")
        print(f"      Value range: [{mip_2d_upsampled.min():.1f}, {mip_2d_upsampled.max():.1f}]")
        print(f"      Aspect ratio: {final_width/final_height:.2f}:1")
        
        # Create vtkImageData for the MIP
        # VTK SetDimensions(X, Y, Z) where X=width, Y=height
        print(f"\n[MIP] Creating VTK image:")
        mip_image = vtk.vtkImageData()
        print(f"      SetDimensions({final_width}, {final_height}, 1)")
        mip_image.SetDimensions(final_width, final_height, 1)
        
        # Adjust spacing based on upsampling factors
        orig_spacing = input_image.GetSpacing()
        new_spacing_x = orig_spacing[1] / scale_factor_y  # Y spacing / Y scale
        new_spacing_y = orig_spacing[2] / scale_factor_z  # Z spacing / Z scale
        
        print(f"      Original spacing: {orig_spacing[0]:.3f}×{orig_spacing[1]:.3f}×{orig_spacing[2]:.3f}")
        print(f"      New spacing: {new_spacing_x:.3f}×{new_spacing_y:.3f}×1.0 mm")
        mip_image.SetSpacing(new_spacing_x, new_spacing_y, 1.0)
        mip_image.SetOrigin(0, 0, 0)
        
        # Convert numpy array to VTK array
        # Numpy: (Y, Z) = (1620, 600)
        # VTK needs: data for (X, Y) = (1620, 600) in row-major order
        # Flatten: transpose to (Z, Y) then flatten C-style
        print(f"\n[MIP] Converting to VTK array:")
        print(f"      Numpy shape before transpose: {mip_2d_upsampled.shape}")
        transposed = mip_2d_upsampled.T
        print(f"      After transpose: {transposed.shape}")
        flat_array = np.ascontiguousarray(transposed).flatten()
        print(f"      Flattened array: length={len(flat_array)}, expected={final_width*final_height}")
        
        vtk_array = numpy_support.numpy_to_vtk(flat_array, deep=True)
        vtk_array.SetNumberOfComponents(1)
        
        mip_image.GetPointData().SetScalars(vtk_array)
        
        final_dims = mip_image.GetDimensions()
        final_range = mip_image.GetScalarRange()
        print(f"\n[MIP] ✓ VTK image created successfully:")
        print(f"      Dimensions: {final_dims[0]}×{final_dims[1]}×{final_dims[2]}")
        print(f"      Scalar range: [{final_range[0]:.1f}, {final_range[1]:.1f}]")
        print(f"      Total pixels: {final_dims[0]*final_dims[1]*final_dims[2]}")
        print("="*80 + "\n")
        
        return mip_image
        
    def _setup_ui(self):
        """Setup the dual-panel UI"""
        # Set widget properties (no window title since it's not a dialog)
        self.setStyleSheet("""
            QWidget {
                background: #1a1a1a;
            }
            QLabel {
                color: #f3f4f6;
                font-size: 13px;
            }
            QPushButton {
                background: #374151;
                color: #f3f4f6;
                border: 1px solid #4b5563;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #4b5563;
            }
            QSlider::groove:horizontal {
                background: #374151;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #8b5cf6;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
        """)
        
        # Main layout - only splitter, no header/footer
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Splitter for dual panels (full screen)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("QSplitter::handle { background: #4b5563; width: 3px; }")
        
        # LEFT PANEL: Panoramic view
        self.panoramic_panel = self._create_panoramic_panel()
        self.splitter.addWidget(self.panoramic_panel)
        
        # RIGHT PANEL: Cross-section view
        self.crosssection_panel = self._create_crosssection_panel()
        self.splitter.addWidget(self.crosssection_panel)
        
        # Set initial sizes (60% panoramic, 40% cross-section)
        self.splitter.setSizes([600, 400])
        
        main_layout.addWidget(self.splitter)
        
    def _create_panoramic_panel(self):
        """Create the left panel for panoramic (straightened) view"""
        # Create viewport wrapper
        self.panoramic_viewport = CurvedMPRViewport(self)
        self.panoramic_viewport.viewport_clicked.connect(self._on_viewport_clicked)
        
        # Store reference to VTK widget for compatibility
        self.panoramic_vtk_widget = self.panoramic_viewport.vtk_widget
        
        # Reference line actor (will be created after viewer setup)
        self.reference_line_actor = None
        
        return self.panoramic_viewport
    
    def _create_crosssection_panel(self):
        """Create the right panel for cross-section view"""
        # Create viewport wrapper
        self.crosssection_viewport = CurvedMPRViewport(self)
        self.crosssection_viewport.viewport_clicked.connect(self._on_viewport_clicked)
        
        # Store reference to VTK widget for compatibility
        self.crosssection_vtk_widget = self.crosssection_viewport.vtk_widget
        
        return self.crosssection_viewport
    
    def _on_viewport_clicked(self, viewport):
        """Handle viewport selection"""
        # Deselect all
        self.panoramic_viewport.set_selected(False)
        self.crosssection_viewport.set_selected(False)
        
        # Select clicked viewport
        viewport.set_selected(True)
        self.active_viewport = viewport
        
        # Determine which viewport was clicked
        viewport_name = "Panoramic" if viewport == self.panoramic_viewport else "Cross-section"
        print(f"[CURVED MPR] Active viewport: {viewport_name}")
        
        # Update patient_widget's selected_widget for toolbar
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'selected_widget'):
                parent.selected_widget = viewport
                break
            parent = parent.parent()
        
        print(f"[CURVED MPR] Viewport selected: {'Panoramic' if viewport == self.panoramic_viewport else 'Cross-section'}")
    
    
    def _setup_viewers(self):
        """Setup both VTK viewers"""
        dims = self.curved_mpr_image.GetDimensions()
        scalar_range = self.curved_mpr_image.GetScalarRange()
        
        # Calculate universal window/level
        if scalar_range[0] == 0 and scalar_range[1] == 0:
            window, level = 1, 0
        else:
            window = max(scalar_range[1] - scalar_range[0], 1)
            level = (scalar_range[1] + scalar_range[0]) / 2
        
        print(f"[Panoramic View] Auto W/L: {window:.0f}/{level:.0f}")
        
        # === PANORAMIC VIEWER ===
        # Use TRUE panoramic image if provided, otherwise create MIP
        
        print("\n" + "="*80)
        print("PANORAMIC VIEWER SETUP")
        print("="*80)
        
        if self.panoramic_image is not None:
            # Use the TRUE panoramic image generated by new algorithm
            print("[Panoramic] Using TRUE panoramic image from generator!")
            mip_image = self.panoramic_image
            pano_dims = mip_image.GetDimensions()
            pano_range = mip_image.GetScalarRange()
            print(f"[Panoramic] Panoramic dimensions: {pano_dims}")
            print(f"[Panoramic] Panoramic range: {pano_range}")
        else:
            # Fallback: Create MIP from curved volume
            print("[Panoramic] Creating Maximum Intensity Projection (fallback)...")
            try:
                mip_image = self._create_mip_image(self.curved_mpr_image)
            except Exception as e:
                print(f"[Panoramic] ❌ ERROR creating MIP: {e}")
                import traceback
                traceback.print_exc()
                # Fallback: use simple YZ slice
                print("[Panoramic] Fallback: using simple YZ slice")
                mip_image = self.curved_mpr_image
        
        # Create the viewer with MIP image
        print(f"\n[Panoramic] Setting up vtkImageViewer2...")
        self.panoramic_viewer = vtk.vtkImageViewer2()
        self.panoramic_viewer.SetInputData(mip_image)
        self.panoramic_viewer.SetRenderWindow(self.panoramic_vtk_widget.GetRenderWindow())
        self.panoramic_viewer.SetupInteractor(self.panoramic_vtk_widget.GetRenderWindow().GetInteractor())
        
        # Show as 2D image
        print(f"      SetSliceOrientationToXY()")
        self.panoramic_viewer.SetSliceOrientationToXY()
        self.panoramic_viewer.SetSlice(0)
        
        # Set window/level
        mip_range = mip_image.GetScalarRange()
        mip_dims = mip_image.GetDimensions()
        print(f"\n[Panoramic] MIP image info:")
        print(f"      Dimensions: {mip_dims[0]}×{mip_dims[1]}×{mip_dims[2]}")
        print(f"      Scalar range: [{mip_range[0]:.0f}, {mip_range[1]:.0f}]")
        print(f"      Window/Level: {window:.0f}/{level:.0f}")
        
        if mip_range[0] != mip_range[1]:
            self.panoramic_viewer.SetColorWindow(window)
            self.panoramic_viewer.SetColorLevel(level)
            print(f"      ✓ Window/Level set")
        else:
            print("[Panoramic] ⚠ WARNING: MIP has constant value!")
        
        # Rotate 90 degrees counter-clockwise for proper dental arch orientation
        # This makes it look like a traditional panoramic radiograph
        print(f"\n[Panoramic] Setting up camera and rendering...")
        pano_renderer = self.panoramic_viewer.GetRenderer()
        pano_renderer.SetBackground(0.1, 0.1, 0.1)  # Dark gray background
        
        # Zoom to fit: Reset camera to fit image properly
        print(f"      Resetting camera to fit image...")
        pano_renderer.ResetCamera()
        
        pano_camera = pano_renderer.GetActiveCamera()
        
        # Zoom 3x for better visibility
        pano_camera.Zoom(3.0)
        
        # Reset clipping range
        pano_renderer.ResetCameraClippingRange()
        
        # Interactive style - Custom style for 2D viewer-like behavior
        pano_interactor = self.panoramic_vtk_widget.GetRenderWindow().GetInteractor()
        pano_style = CurvedMPRInteractorStyle(self.panoramic_viewer)
        pano_interactor.SetInteractorStyle(pano_style)
        
        # Store style reference for toolbar compatibility
        self.panoramic_style = pano_style
        
        print(f"      ✓ Interactive style set (CurvedMPRInteractorStyle)")
        
        print(f"\n[Panoramic] ✓ Viewer configured successfully!")
        print("="*80 + "\n")
        
        # === CROSS-SECTION VIEWER (XY plane - perpendicular slices) ===
        print("\n" + "="*80)
        print("CROSS-SECTION VIEWER SETUP")
        print("="*80)
        
        print(f"[Cross-section] Setting up vtkImageViewer2...")
        self.crosssection_viewer = vtk.vtkImageViewer2()
        self.crosssection_viewer.SetInputData(self.curved_mpr_image)
        self.crosssection_viewer.SetRenderWindow(self.crosssection_vtk_widget.GetRenderWindow())
        self.crosssection_viewer.SetupInteractor(self.crosssection_vtk_widget.GetRenderWindow().GetInteractor())
        
        # Show XY plane (cross-sections)
        print(f"      SetSliceOrientationToXY()")
        self.crosssection_viewer.SetSliceOrientationToXY()
        self.current_slice = dims[2] // 2
        self.crosssection_viewer.SetSlice(self.current_slice)
        print(f"      Initial slice: {self.current_slice} / {dims[2]}")
        
        self.crosssection_viewer.SetColorWindow(window)
        self.crosssection_viewer.SetColorLevel(level)
        print(f"      Window/Level: {window:.0f}/{level:.0f}")
        
        # Setup camera for cross-section
        print(f"\n[Cross-section] Setting up camera...")
        cross_renderer = self.crosssection_viewer.GetRenderer()
        
        # Zoom to fit: Reset camera
        print(f"      Resetting camera to fit image...")
        cross_renderer.ResetCamera()
        
        cross_camera = cross_renderer.GetActiveCamera()
        
        # Rotate 180 degrees counter-clockwise for correct orientation
        cross_camera.Roll(-180)
        print(f"      ✓ Rotated 180° counter-clockwise")
        
        # Small zoom for better fit (images are auto-cropped)
        cross_camera.Zoom(1.1)
        
        # Reset clipping range
        cross_renderer.ResetCameraClippingRange()
        
        # Interactive style - Custom style for 2D viewer-like behavior
        cross_interactor = self.crosssection_vtk_widget.GetRenderWindow().GetInteractor()
        cross_style = CurvedMPRInteractorStyle(self.crosssection_viewer)
        cross_interactor.SetInteractorStyle(cross_style)
        
        # Store style reference for toolbar compatibility
        self.crosssection_style = cross_style
        
        print(f"      ✓ Interactive style set (CurvedMPRInteractorStyle)")
        
        print(f"\n[Cross-section] ✓ Viewer configured successfully!")
        print("="*80 + "\n")
        
        # Initialize and render
        print("\n" + "="*80)
        print("INITIALIZING AND RENDERING")
        print("="*80)
        
        print("[Panoramic] Initializing panoramic viewer...")
        self.panoramic_vtk_widget.Initialize()
        print("[Panoramic] Rendering...")
        self.panoramic_viewer.Render()
        print("[Panoramic] Starting interactor...")
        self.panoramic_vtk_widget.Start()
        print("[Panoramic] ✓ Panoramic viewer initialized and rendered!")
        
        print("\n[Cross-section] Initializing cross-section viewer...")
        self.crosssection_vtk_widget.Initialize()
        print("[Cross-section] Rendering...")
        self.crosssection_viewer.Render()
        print("[Cross-section] Starting interactor...")
        self.crosssection_vtk_widget.Start()
        print("[Cross-section] ✓ Cross-section viewer initialized and rendered!")
        
        print("\n" + "="*80)
        print("✓ BOTH VIEWERS READY!")
        print("="*80 + "\n")
    
        # Setup image_viewer and current_style references for toolbar compatibility
        # Wrap vtkImageViewer2 to provide ImageViewer2D-like interface
        pano_wrapper = ImageViewerWrapper(
            self.panoramic_viewer, 
            self.panoramic_vtk_widget
        )
        
        cross_wrapper = ImageViewerWrapper(
            self.crosssection_viewer,
            self.crosssection_vtk_widget
        )
        
        # Rebuild styles with wrapped viewers for proper compatibility
        # CRITICAL: Each viewport MUST have its own interactor style instance
        # so they have separate widgets_by_slice dictionaries
        pano_interactor = self.panoramic_vtk_widget.GetRenderWindow().GetInteractor()
        self.panoramic_style = CurvedMPRInteractorStyle(pano_wrapper, viewport_id='panoramic')
        pano_interactor.SetInteractorStyle(self.panoramic_style)
        
        cross_interactor = self.crosssection_vtk_widget.GetRenderWindow().GetInteractor()
        self.crosssection_style = CurvedMPRInteractorStyle(cross_wrapper, viewport_id='crosssection')
        cross_interactor.SetInteractorStyle(self.crosssection_style)
        
        # Re-apply zoom after style rebuild
        pano_camera = self.panoramic_viewer.GetRenderer().GetActiveCamera()
        pano_camera.Zoom(3.0)
        print("[CURVED MPR] ✓ Panoramic zoom re-applied: 3.0x")
        
        # Set wrapped viewers and styles on viewports
        self.panoramic_viewport.image_viewer = pano_wrapper
        self.panoramic_viewport.current_style = self.panoramic_style
        
        self.crosssection_viewport.image_viewer = cross_wrapper
        self.crosssection_viewport.current_style = self.crosssection_style
        
        # Select panoramic viewport as default
        self.panoramic_viewport.set_selected(True)
        self.active_viewport = self.panoramic_viewport
        
        # Setup reference line on panoramic view
        self._setup_reference_line()
        
        # Store current cross-section slice for tracking changes
        self._last_cross_slice = self.crosssection_viewer.GetSlice()
        
        # Add timer to check for slice changes (more reliable than observer)
        from PySide6.QtCore import QTimer
        self._reference_line_timer = QTimer()
        self._reference_line_timer.timeout.connect(self._check_slice_change)
        self._reference_line_timer.start(100)  # Check every 100ms
        
        print("[CURVED MPR] Default viewport: Panoramic (left)")
        print("[CURVED MPR] Viewport image_viewer and current_style set for toolbar compatibility")
        print("[CURVED MPR] ✓ Reference line setup complete")
    
    def _setup_reference_line(self):
        """Create initial reference line on panoramic view"""
        self.reference_line_actor = None
        # Initialize at current slice (which was set during setup)
        current_slice = self.crosssection_viewer.GetSlice()
        self._update_reference_line(current_slice)
        print(f"[CURVED MPR] Reference line initialized at slice {current_slice}")
    
    def _check_slice_change(self):
        """Check if cross-section slice has changed and update reference line"""
        try:
            current_slice = self.crosssection_viewer.GetSlice()
            if current_slice != self._last_cross_slice:
                self._last_cross_slice = current_slice
                self._update_reference_line(current_slice)
        except Exception as e:
            pass  # Ignore errors during cleanup
    
    def _update_reference_line(self, slice_index):
        """Update reference line position on panoramic view to show current cross-section slice"""
        try:
            # Get panoramic image dimensions
            pano_input = self.panoramic_viewer.GetInput()
            if not pano_input:
                return
            
            dims = pano_input.GetDimensions()
            pano_width = dims[0]
            pano_height = dims[1]
            
            # Get cross-section total slices
            cross_input = self.crosssection_viewer.GetInput()
            if not cross_input:
                return
            
            cross_dims = cross_input.GetDimensions()
            total_slices = cross_dims[2]
            
            if total_slices <= 1:
                return
            
            # Calculate line position (normalized 0-1 across panoramic width)
            position_ratio = slice_index / (total_slices - 1)
            line_x = position_ratio * (pano_width - 1)
            
            print(f"[REF LINE] Slice {slice_index}/{total_slices-1}, Position: {line_x:.1f}/{pano_width-1}")
            
            # Remove old line if exists
            if self.reference_line_actor is not None:
                self.panoramic_viewer.GetRenderer().RemoveActor(self.reference_line_actor)
            
            # Create line using vtkLineWidget2 approach - more visible in 2D
            # Convert image coordinates to world coordinates
            pano_renderer = self.panoramic_viewer.GetRenderer()
            
            # Get image actor position and bounds
            image_actor = self.panoramic_viewer.GetImageActor()
            bounds = image_actor.GetBounds()
            # bounds = [xmin, xmax, ymin, ymax, zmin, zmax]
            
            # Calculate world coordinates for the line
            x_world = bounds[0] + line_x * (bounds[1] - bounds[0]) / (pano_width - 1)
            y_min_world = bounds[2]
            y_max_world = bounds[3]
            
            # Create vertical line in world coordinates
            line_source = vtk.vtkLineSource()
            line_source.SetPoint1(x_world, y_min_world, 0)
            line_source.SetPoint2(x_world, y_max_world, 0)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(line_source.GetOutputPort())
            
            self.reference_line_actor = vtk.vtkActor()
            self.reference_line_actor.SetMapper(mapper)
            self.reference_line_actor.GetProperty().SetColor(1.0, 0.0, 0.0)  # Red (most visible)
            self.reference_line_actor.GetProperty().SetLineWidth(5.0)  # Very thick
            self.reference_line_actor.GetProperty().SetOpacity(1.0)
            
            # Make sure it's on top
            self.reference_line_actor.GetProperty().SetRenderLinesAsTubes(True)
            
            pano_renderer.AddActor(self.reference_line_actor)
            self.panoramic_viewer.Render()
            
            print(f"[REF LINE] Line drawn at x_world={x_world:.1f}, y_range=[{y_min_world:.1f}, {y_max_world:.1f}]")
            
        except Exception as e:
            print(f"[CURVED MPR] Error updating reference line: {e}")
    

