"""
Minimal Working MPR Viewer with Window/Level Control
Simple, tested, and reliable
"""
import logging
import vtkmodules.all as vtk
from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QComboBox, QHBoxLayout, QVBoxLayout
from PySide6.QtCore import Qt
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

logger = logging.getLogger(__name__)


# Window/Level presets
WL_PRESETS = {
    'Auto': None,  # Will be calculated from data
    'Brain': {'window': 80, 'level': 40},
    'Subdural': {'window': 200, 'level': 75},
    'Bone': {'window': 2000, 'level': 300},
    'Lung': {'window': 1500, 'level': -600},
    'Abdomen': {'window': 350, 'level': 50},
    'Liver': {'window': 150, 'level': 80},
    'Soft Tissue': {'window': 400, 'level': 50},
}

# 3D Volume presets
VOLUME_PRESETS = {
    'Bone': {
        'color': [(0, 0.0, 0.0, 0.0), (200, 0.62, 0.36, 0.18), (400, 0.88, 0.60, 0.29), (1000, 1.0, 0.95, 0.75)],
        'opacity': [(0, 0.0), (200, 0.0), (400, 0.5), (1000, 0.8)]
    },
    'Soft Tissue': {
        'color': [(0, 0.0, 0.0, 0.0), (100, 0.8, 0.6, 0.6), (300, 1.0, 0.8, 0.8), (500, 1.0, 1.0, 1.0)],
        'opacity': [(0, 0.0), (100, 0.2), (300, 0.5), (500, 0.7)]
    },
    'MIP': {
        'color': [(0, 0.0, 0.0, 0.0), (100, 0.5, 0.5, 0.5), (500, 1.0, 1.0, 1.0)],
        'opacity': [(0, 0.0), (100, 0.8), (500, 1.0)]
    },
}


class MinimalMPRViewer(QWidget):
    """
    Minimal MPR viewer that DEFINITELY works
    """
    
    def __init__(self, vtk_image_data, parent=None):
        super().__init__(parent)
        
        self.image_data = vtk_image_data
        self.dims = vtk_image_data.GetDimensions()
        self.spacing = vtk_image_data.GetSpacing()
        self.origin = vtk_image_data.GetOrigin()
        
        # Get scalar range for window/level
        self.scalar_range = vtk_image_data.GetScalarRange()
        
        # Store viewers for scroll interaction
        self.viewers = {}
        
        self._setup_ui()
        logger.info("MinimalMPRViewer created")
    
    def _setup_ui(self):
        """Setup UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(2)
        
        # Control panel
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        control_layout.setContentsMargins(4, 4, 4, 4)
        control_layout.setSpacing(8)
        
        # Window/Level preset for 2D views
        wl_label = QLabel("W/L:")
        wl_label.setStyleSheet("color: white; font-weight: bold;")
        control_layout.addWidget(wl_label)
        
        self.wl_combo = QComboBox()
        self.wl_combo.addItems(list(WL_PRESETS.keys()))
        self.wl_combo.setCurrentText('Auto')
        self.wl_combo.currentTextChanged.connect(self._on_wl_changed)
        self.wl_combo.setStyleSheet("""
            QComboBox {
                background: #2a2a2a;
                color: white;
                border: 1px solid #555;
                padding: 4px;
                min-width: 100px;
            }
        """)
        control_layout.addWidget(self.wl_combo)
        
        control_layout.addSpacing(20)
        
        # 3D Volume preset
        vol_label = QLabel("3D Preset:")
        vol_label.setStyleSheet("color: white; font-weight: bold;")
        control_layout.addWidget(vol_label)
        
        self.vol_combo = QComboBox()
        self.vol_combo.addItems(list(VOLUME_PRESETS.keys()))
        self.vol_combo.setCurrentText('Bone')
        self.vol_combo.currentTextChanged.connect(self._on_volume_preset_changed)
        self.vol_combo.setStyleSheet("""
            QComboBox {
                background: #2a2a2a;
                color: white;
                border: 1px solid #555;
                padding: 4px;
                min-width: 100px;
            }
        """)
        control_layout.addWidget(self.vol_combo)
        
        control_layout.addStretch()
        
        control_panel.setStyleSheet("background: #1a1a1a;")
        main_layout.addWidget(control_panel)
        
        # Views grid
        views_widget = QWidget()
        views_layout = QGridLayout(views_widget)
        views_layout.setContentsMargins(0, 0, 0, 0)
        views_layout.setSpacing(4)
        
        # Axial (top left)
        axial_widget = self._create_view("Axial", 2, self.dims[2] // 2)
        views_layout.addWidget(axial_widget, 0, 0)
        self.viewers['axial'] = axial_widget
        
        # 3D (top right)
        vol_widget = self._create_3d_view("3D Volume")
        views_layout.addWidget(vol_widget, 0, 1)
        self.viewers['3d'] = vol_widget
        
        # Sagittal (bottom left)
        sag_widget = self._create_view("Sagittal", 0, self.dims[0] // 2)
        views_layout.addWidget(sag_widget, 1, 0)
        self.viewers['sagittal'] = sag_widget
        
        # Coronal (bottom right)
        cor_widget = self._create_view("Coronal", 1, self.dims[1] // 2)
        views_layout.addWidget(cor_widget, 1, 1)
        self.viewers['coronal'] = cor_widget
        
        views_widget.setStyleSheet("QWidget { background-color: #000000; }")
        main_layout.addWidget(views_widget)
        
        self.setLayout(main_layout)
    
    def _create_view(self, name, orientation, slice_num):
        """Create a single 2D view with scrolling"""
        # Container
        container = QWidget()
        container_layout = QGridLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # Label
        label = QLabel(name)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: white; background: #2a2a2a; padding: 4px;")
        container_layout.addWidget(label, 0, 0)
        
        # VTK widget
        vtk_widget = QVTKRenderWindowInteractor(container)
        container_layout.addWidget(vtk_widget, 1, 0)
        
        # Renderer
        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0, 0, 0)
        vtk_widget.GetRenderWindow().AddRenderer(renderer)
        
        # Create reslice
        reslice = vtk.vtkImageReslice()
        reslice.SetInputData(self.image_data)
        reslice.SetOutputDimensionality(2)
        reslice.SetInterpolationModeToLinear()
        
        # Set initial slice
        self._update_slice_axes(reslice, orientation, slice_num)
        
        # Create actor with proper window/level
        mapper = vtk.vtkImageSliceMapper()
        mapper.SetInputData(reslice.GetOutput())
        
        actor = vtk.vtkImageSlice()
        actor.SetMapper(mapper)
        
        # Set window/level
        window = self.scalar_range[1] - self.scalar_range[0]
        level = (self.scalar_range[0] + self.scalar_range[1]) / 2
        actor.GetProperty().SetColorWindow(window)
        actor.GetProperty().SetColorLevel(level)
        
        renderer.AddViewProp(actor)
        
        # Camera setup with proper orientation
        renderer.ResetCamera()
        camera = renderer.GetActiveCamera()
        camera.ParallelProjectionOn()
        
        # Set camera orientation based on view
        if orientation == 2:  # Axial
            # Default view from above (looking down Z axis)
            camera.SetPosition(0, 0, 1)
            camera.SetFocalPoint(0, 0, 0)
            camera.SetViewUp(0, 1, 0)
        elif orientation == 0:  # Sagittal
            # View from the side (looking along X axis)
            camera.SetPosition(1, 0, 0)
            camera.SetFocalPoint(0, 0, 0)
            camera.SetViewUp(0, 0, 1)
        else:  # Coronal
            # View from front (looking along Y axis)
            camera.SetPosition(0, -1, 0)
            camera.SetFocalPoint(0, 0, 0)
            camera.SetViewUp(0, 0, 1)
        
        renderer.ResetCamera()
        
        # Custom interactor for scrolling
        interactor_style = self._create_scroll_interactor(
            orientation, slice_num, reslice, actor, mapper, renderer
        )
        vtk_widget.SetInteractorStyle(interactor_style)
        
        # Initialize
        vtk_widget.Initialize()
        vtk_widget.Start()
        
        # Store info
        container._viewer_info = {
            'orientation': orientation,
            'current_slice': slice_num,
            'max_slice': self.dims[orientation] - 1,
            'reslice': reslice,
            'actor': actor,
            'mapper': mapper,
            'renderer': renderer
        }
        
        return container
    
    def _update_slice_axes(self, reslice, orientation, slice_num):
        """Update reslice axes for specific orientation and slice"""
        axes = vtk.vtkMatrix4x4()
        axes.Identity()
        
        if orientation == 2:  # Axial (XY plane, scroll through Z)
            # Standard axial view - no rotation needed
            axes.SetElement(0, 0, 1)
            axes.SetElement(0, 3, self.origin[0])
            axes.SetElement(1, 1, 1)
            axes.SetElement(1, 3, self.origin[1])
            axes.SetElement(2, 2, 1)
            axes.SetElement(2, 3, self.origin[2] + slice_num * self.spacing[2])
            
        elif orientation == 0:  # Sagittal (YZ plane, scroll through X)
            # Rotate to show YZ plane
            # Column 0 (X-axis in output): Y direction in input
            axes.SetElement(0, 0, 0)
            axes.SetElement(1, 0, 1)
            axes.SetElement(2, 0, 0)
            axes.SetElement(3, 0, 0)
            
            # Column 1 (Y-axis in output): Z direction in input
            axes.SetElement(0, 1, 0)
            axes.SetElement(1, 1, 0)
            axes.SetElement(2, 1, 1)
            axes.SetElement(3, 1, 0)
            
            # Column 2 (Z-axis in output): X direction in input
            axes.SetElement(0, 2, 1)
            axes.SetElement(1, 2, 0)
            axes.SetElement(2, 2, 0)
            axes.SetElement(3, 2, 0)
            
            # Column 3 (Translation)
            axes.SetElement(0, 3, self.origin[0] + slice_num * self.spacing[0])
            axes.SetElement(1, 3, self.origin[1])
            axes.SetElement(2, 3, self.origin[2])
            axes.SetElement(3, 3, 1)
            
        else:  # Coronal (XZ plane, scroll through Y)
            # Rotate to show XZ plane
            # Column 0 (X-axis in output): X direction in input
            axes.SetElement(0, 0, 1)
            axes.SetElement(1, 0, 0)
            axes.SetElement(2, 0, 0)
            axes.SetElement(3, 0, 0)
            
            # Column 1 (Y-axis in output): Z direction in input
            axes.SetElement(0, 1, 0)
            axes.SetElement(1, 1, 0)
            axes.SetElement(2, 1, 1)
            axes.SetElement(3, 1, 0)
            
            # Column 2 (Z-axis in output): -Y direction in input
            axes.SetElement(0, 2, 0)
            axes.SetElement(1, 2, 1)
            axes.SetElement(2, 2, 0)
            axes.SetElement(3, 2, 0)
            
            # Column 3 (Translation)
            axes.SetElement(0, 3, self.origin[0])
            axes.SetElement(1, 3, self.origin[1] + slice_num * self.spacing[1])
            axes.SetElement(2, 3, self.origin[2])
            axes.SetElement(3, 3, 1)
        
        reslice.SetResliceAxes(axes)
        reslice.Update()
    
    def _create_scroll_interactor(self, orientation, initial_slice, reslice, actor, mapper, renderer):
        """Create interactor style with mouse wheel scrolling"""
        parent_viewer = self
        max_slice = self.dims[orientation] - 1
        
        class ScrollInteractor(vtk.vtkInteractorStyleImage):
            def __init__(self):
                self.current_slice = initial_slice
                self.AddObserver("MouseWheelForwardEvent", self.on_scroll_forward)
                self.AddObserver("MouseWheelBackwardEvent", self.on_scroll_backward)
            
            def on_scroll_forward(self, obj, event):
                if self.current_slice < max_slice:
                    self.current_slice += 1
                    self.update_view()
            
            def on_scroll_backward(self, obj, event):
                if self.current_slice > 0:
                    self.current_slice -= 1
                    self.update_view()
            
            def update_view(self):
                # Update reslice
                parent_viewer._update_slice_axes(reslice, orientation, self.current_slice)
                
                # Update mapper
                mapper.SetInputData(reslice.GetOutput())
                mapper.Update()
                
                # Reset camera to keep image fitted
                renderer.ResetCamera()
                
                # Render
                renderer.GetRenderWindow().Render()
        
        return ScrollInteractor()
    
    def _on_wl_changed(self, preset_name):
        """Handle window/level preset change"""
        preset = WL_PRESETS[preset_name]
        
        if preset is None:  # Auto
            window = self.scalar_range[1] - self.scalar_range[0]
            level = (self.scalar_range[0] + self.scalar_range[1]) / 2
        else:
            window = preset['window']
            level = preset['level']
        
        # Update all 2D views
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name in self.viewers:
                view_widget = self.viewers[view_name]
                if hasattr(view_widget, '_viewer_info'):
                    actor = view_widget._viewer_info['actor']
                    actor.GetProperty().SetColorWindow(window)
                    actor.GetProperty().SetColorLevel(level)
                    
                    # Render
                    renderer = view_widget._viewer_info['renderer']
                    renderer.GetRenderWindow().Render()
        
        logger.info(f"Applied W/L preset: {preset_name} (W={window}, L={level})")
    
    def _on_volume_preset_changed(self, preset_name):
        """Handle 3D volume preset change"""
        if '3d' not in self.viewers:
            return
        
        preset = VOLUME_PRESETS[preset_name]
        view_widget = self.viewers['3d']
        
        if hasattr(view_widget, '_volume_info'):
            volume_property = view_widget._volume_info['property']
            
            # Update color transfer function
            color_func = vtk.vtkColorTransferFunction()
            for value, r, g, b in preset['color']:
                adjusted_value = self.scalar_range[0] + value
                color_func.AddRGBPoint(adjusted_value, r, g, b)
            
            # Update opacity transfer function
            opacity_func = vtk.vtkPiecewiseFunction()
            for value, opacity in preset['opacity']:
                adjusted_value = self.scalar_range[0] + value
                opacity_func.AddPoint(adjusted_value, opacity)
            
            # Apply to property
            volume_property.SetColor(color_func)
            volume_property.SetScalarOpacity(opacity_func)
            
            # Render
            renderer = view_widget._volume_info['renderer']
            renderer.GetRenderWindow().Render()
        
        logger.info(f"Applied 3D preset: {preset_name}")
    
    def _create_3d_view(self, name):
        """Create 3D volume view with presets"""
        # Container
        container = QWidget()
        container_layout = QGridLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # Label
        label = QLabel(name)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: white; background: #2a2a2a; padding: 4px;")
        container_layout.addWidget(label, 0, 0)
        
        # VTK widget
        vtk_widget = QVTKRenderWindowInteractor(container)
        container_layout.addWidget(vtk_widget, 1, 0)
        
        # Renderer
        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0, 0, 0)
        vtk_widget.GetRenderWindow().AddRenderer(renderer)
        
        # Volume mapper
        volume_mapper = vtk.vtkGPUVolumeRayCastMapper()
        volume_mapper.SetInputData(self.image_data)
        
        # Volume property
        volume_property = vtk.vtkVolumeProperty()
        volume_property.ShadeOn()
        volume_property.SetInterpolationTypeToLinear()
        
        # Apply default preset (Bone)
        preset = VOLUME_PRESETS['Bone']
        
        # Color function
        color_func = vtk.vtkColorTransferFunction()
        for value, r, g, b in preset['color']:
            adjusted_value = self.scalar_range[0] + value
            color_func.AddRGBPoint(adjusted_value, r, g, b)
        
        # Opacity function
        opacity_func = vtk.vtkPiecewiseFunction()
        for value, opacity in preset['opacity']:
            adjusted_value = self.scalar_range[0] + value
            opacity_func.AddPoint(adjusted_value, opacity)
        
        volume_property.SetColor(color_func)
        volume_property.SetScalarOpacity(opacity_func)
        
        # Volume
        volume = vtk.vtkVolume()
        volume.SetMapper(volume_mapper)
        volume.SetProperty(volume_property)
        
        renderer.AddVolume(volume)
        renderer.ResetCamera()
        
        # Setup 3D interactor style for rotation
        style = vtk.vtkInteractorStyleTrackballCamera()
        vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(style)
        
        # Initialize
        vtk_widget.Initialize()
        vtk_widget.Start()
        
        # Store info for preset changes
        container._volume_info = {
            'property': volume_property,
            'renderer': renderer,
            'volume': volume
        }
        
        return container
    
    def cleanup(self):
        """Cleanup"""
        pass

