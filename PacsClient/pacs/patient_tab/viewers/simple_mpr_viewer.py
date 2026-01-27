"""
Simple MPR Viewer for Viewport Integration
Displays 3 MPR views without external toolbar
"""
import logging
from typing import Optional

import vtkmodules.all as vtk
from PySide6.QtWidgets import QWidget, QGridLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, QTimer

logger = logging.getLogger(__name__)


class SimpleMPRViewer(QWidget):
    """
    Simple MPR viewer that shows 3 views in a grid
    Perfect for replacing a single viewport
    """
    
    def __init__(self, vtk_image_data: vtk.vtkImageData, parent: Optional[QWidget] = None):
        """
        Args:
            vtk_image_data: VTK image data to display
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.image_data = vtk_image_data
        self.viewers = {}
        
        # Auto-rotation state
        self.auto_rotation_active = False
        self.auto_rotation_timer = None
        
        # Setup UI
        self._setup_ui()
        
        # Create viewers
        self._create_viewers()
        
        logger.info("Simple MPR viewer created")
    
    def _setup_ui(self):
        """Setup the UI layout"""
        layout = QGridLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        self.setLayout(layout)
        
        # Set dark background
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
            }
            QLabel {
                color: #ffffff;
                background-color: #2a2a2a;
                padding: 4px;
                font-weight: bold;
                border-bottom: 1px solid #3a3a3a;
            }
        """)
    
    def _create_viewers(self):
        """Create 4 views: 3 MPR + 1 3D"""
        from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
        
        layout = self.layout()
        
        # Get image dimensions
        dims = self.image_data.GetDimensions()
        
        # Define views - matching the image layout
        views = [
            {
                'name': 'Axial',
                'orientation': 2,  # Z axis
                'row': 0,
                'col': 0,
                'slice': dims[2] // 2,
                'is_3d': False
            },
            {
                'name': '3D',
                'orientation': None,
                'row': 0,
                'col': 1,
                'slice': None,
                'is_3d': True
            },
            {
                'name': 'Sagittal',
                'orientation': 0,  # X axis
                'row': 1,
                'col': 0,
                'slice': dims[0] // 2,
                'is_3d': False
            },
            {
                'name': 'Coronal',
                'orientation': 1,  # Y axis
                'row': 1,
                'col': 1,
                'slice': dims[1] // 2,
                'is_3d': False
            }
        ]
        
        for view_config in views:
            # Create container
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(0)
            
            # Add label
            label = QLabel(view_config['name'])
            label.setAlignment(Qt.AlignCenter)
            container_layout.addWidget(label)
            
            # Create VTK widget
            vtk_widget = QVTKRenderWindowInteractor(container)
            container_layout.addWidget(vtk_widget)
            
            # Create renderer
            renderer = vtk.vtkRenderer()
            renderer.SetBackground(0.0, 0.0, 0.0)  # Black background like image
            
            vtk_widget.GetRenderWindow().AddRenderer(renderer)
            
            # Create 3D or 2D view
            if view_config['is_3d']:
                # Create 3D volume rendering
                self._create_3d_view(renderer)
                
                # Setup 3D interactor style for rotation
                style = vtk.vtkInteractorStyleTrackballCamera()
                vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(style)
                
                # Get camera reference
                camera = renderer.GetActiveCamera()
                
                self.viewers[view_config['name'].lower()] = {
                    'widget': vtk_widget,
                    'renderer': renderer,
                    'interactor_style': style,
                    'camera': camera,
                    'is_3d': True
                }
                
                # Install event filter to detect user interaction
                vtk_widget.installEventFilter(self)
            else:
                # Create 2D slice
                image_slice = self._create_image_slice(
                    view_config['orientation'],
                    view_config['slice']
                )
                
                # Set proper window/level
                scalar_range = self.image_data.GetScalarRange()
                window = scalar_range[1] - scalar_range[0]
                level = (scalar_range[0] + scalar_range[1]) / 2.0
                
                # Create mapper and actor
                image_mapper = vtk.vtkImageSliceMapper()
                image_mapper.SetInputData(image_slice.GetOutput())
                
                image_actor = vtk.vtkImageSlice()
                image_actor.SetMapper(image_mapper)
                
                # Set window/level
                property = image_actor.GetProperty()
                property.SetColorWindow(window)
                property.SetColorLevel(level)
                
                renderer.AddViewProp(image_actor)
                
                # Add crosshair
                crosshair_actors = self._create_crosshair(view_config['orientation'], dims)
                for ch_actor in crosshair_actors:
                    renderer.AddActor(ch_actor)
                
                # Fit to view
                renderer.ResetCamera()
                camera = renderer.GetActiveCamera()
                camera.ParallelProjectionOn()
                
                # Store info
                self.viewers[view_config['name'].lower()] = {
                    'widget': vtk_widget,
                    'renderer': renderer,
                    'orientation': view_config['orientation'],
                    'actor': image_actor,
                    'slicer': image_slice,
                    'crosshair_actors': crosshair_actors,
                    'current_slice': view_config['slice'],
                    'max_slice': dims[view_config['orientation']],
                    'is_3d': False
                }
            
            # Add to layout
            layout.addWidget(container, view_config['row'], view_config['col'])
            
            # Initialize
            vtk_widget.Initialize()
            vtk_widget.Start()
        
        # Setup auto-rotation for 3D view after all views are created
        self.setup_auto_rotation()
        
        logger.info("Created 4 views (3 MPR + 1 3D)")
    
    def _create_image_slice(self, orientation: int, slice_number: int) -> vtk.vtkImageReslice:
        """
        Create image slice for specific orientation
        
        Args:
            orientation: 0=sagittal, 1=coronal, 2=axial
            slice_number: Slice index
            
        Returns:
            vtkImageReslice object
        """
        reslice = vtk.vtkImageReslice()
        reslice.SetInputData(self.image_data)
        reslice.SetOutputDimensionality(2)
        
        # Get image info
        dims = self.image_data.GetDimensions()
        spacing = self.image_data.GetSpacing()
        origin = self.image_data.GetOrigin()
        
        # Set reslice axes based on orientation
        axes = vtk.vtkMatrix4x4()
        
        if orientation == 0:  # Sagittal (YZ plane)
            axes.SetElement(0, 0, 0)
            axes.SetElement(0, 1, 0)
            axes.SetElement(0, 2, -1)
            axes.SetElement(0, 3, origin[2] + slice_number * spacing[2])
            
            axes.SetElement(1, 0, 1)
            axes.SetElement(1, 1, 0)
            axes.SetElement(1, 2, 0)
            axes.SetElement(1, 3, origin[1])
            
            axes.SetElement(2, 0, 0)
            axes.SetElement(2, 1, 1)
            axes.SetElement(2, 2, 0)
            axes.SetElement(2, 3, origin[0])
            
        elif orientation == 1:  # Coronal (XZ plane)
            axes.SetElement(0, 0, 1)
            axes.SetElement(0, 1, 0)
            axes.SetElement(0, 2, 0)
            axes.SetElement(0, 3, origin[0])
            
            axes.SetElement(1, 0, 0)
            axes.SetElement(1, 1, 0)
            axes.SetElement(1, 2, -1)
            axes.SetElement(1, 3, origin[2] + dims[2] * spacing[2])
            
            axes.SetElement(2, 0, 0)
            axes.SetElement(2, 1, 1)
            axes.SetElement(2, 2, 0)
            axes.SetElement(2, 3, origin[1] + slice_number * spacing[1])
            
        else:  # Axial (XY plane)
            axes.SetElement(0, 0, 1)
            axes.SetElement(0, 1, 0)
            axes.SetElement(0, 2, 0)
            axes.SetElement(0, 3, origin[0])
            
            axes.SetElement(1, 0, 0)
            axes.SetElement(1, 1, 1)
            axes.SetElement(1, 2, 0)
            axes.SetElement(1, 3, origin[1])
            
            axes.SetElement(2, 0, 0)
            axes.SetElement(2, 1, 0)
            axes.SetElement(2, 2, 1)
            axes.SetElement(2, 3, origin[2] + slice_number * spacing[2])
        
        reslice.SetResliceAxes(axes)
        reslice.SetInterpolationModeToLinear()
        reslice.Update()
        
        return reslice
    
    def _create_crosshair(self, orientation: int, dims: tuple) -> list:
        """
        Create crosshair lines for MPR view
        
        Args:
            orientation: View orientation (0=sagittal, 1=coronal, 2=axial)
            dims: Image dimensions
            
        Returns:
            List of vtkActor2D objects for crosshair lines
        """
        actors = []
        
        # Get image center in world coordinates
        spacing = self.image_data.GetSpacing()
        origin = self.image_data.GetOrigin()
        
        center_x = origin[0] + (dims[0] / 2) * spacing[0]
        center_y = origin[1] + (dims[1] / 2) * spacing[1]
        center_z = origin[2] + (dims[2] / 2) * spacing[2]
        
        # Create two perpendicular lines
        for i in range(2):
            line_source = vtk.vtkLineSource()
            
            if orientation == 2:  # Axial
                if i == 0:  # Horizontal (red in image)
                    line_source.SetPoint1(origin[0], center_y, center_z)
                    line_source.SetPoint2(origin[0] + dims[0] * spacing[0], center_y, center_z)
                    color = (1.0, 0.0, 0.0)  # Red
                else:  # Vertical (green in image)
                    line_source.SetPoint1(center_x, origin[1], center_z)
                    line_source.SetPoint2(center_x, origin[1] + dims[1] * spacing[1], center_z)
                    color = (0.0, 1.0, 0.0)  # Green
                    
            elif orientation == 0:  # Sagittal
                if i == 0:  # Horizontal (green)
                    line_source.SetPoint1(center_x, origin[1], origin[2])
                    line_source.SetPoint2(center_x, origin[1], origin[2] + dims[2] * spacing[2])
                    color = (0.0, 1.0, 0.0)  # Green
                else:  # Vertical (blue)
                    line_source.SetPoint1(center_x, origin[1], center_z)
                    line_source.SetPoint2(center_x, origin[1] + dims[1] * spacing[1], center_z)
                    color = (0.0, 0.0, 1.0)  # Blue
                    
            else:  # Coronal
                if i == 0:  # Horizontal (red)
                    line_source.SetPoint1(origin[0], center_y, center_z)
                    line_source.SetPoint2(origin[0] + dims[0] * spacing[0], center_y, center_z)
                    color = (1.0, 0.0, 0.0)  # Red
                else:  # Vertical (blue)
                    line_source.SetPoint1(center_x, center_y, origin[2])
                    line_source.SetPoint2(center_x, center_y, origin[2] + dims[2] * spacing[2])
                    color = (0.0, 0.0, 1.0)  # Blue
            
            # Create mapper and actor
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(line_source.GetOutputPort())
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(color)
            actor.GetProperty().SetLineWidth(2)
            
            actors.append(actor)
        
        return actors
    
    def _create_3d_view(self, renderer: vtk.vtkRenderer):
        """
        Create 3D volume rendering view
        
        Args:
            renderer: VTK renderer to add volume to
        """
        # Create volume mapper
        volume_mapper = vtk.vtkGPUVolumeRayCastMapper()
        volume_mapper.SetInputData(self.image_data)
        
        # Create volume property
        volume_property = vtk.vtkVolumeProperty()
        volume_property.ShadeOn()
        volume_property.SetInterpolationTypeToLinear()
        
        # Create color transfer function (brown/tan for bone)
        color_func = vtk.vtkColorTransferFunction()
        color_func.AddRGBPoint(-3024, 0.0, 0.0, 0.0)
        color_func.AddRGBPoint(-1000, 0.62, 0.36, 0.18)
        color_func.AddRGBPoint(-500, 0.88, 0.60, 0.29)
        color_func.AddRGBPoint(0, 0.90, 0.82, 0.56)
        color_func.AddRGBPoint(500, 1.0, 0.95, 0.75)
        color_func.AddRGBPoint(1000, 1.0, 1.0, 1.0)
        color_func.AddRGBPoint(3071, 1.0, 1.0, 1.0)
        
        # Create opacity transfer function
        opacity_func = vtk.vtkPiecewiseFunction()
        opacity_func.AddPoint(-3024, 0.0)
        opacity_func.AddPoint(-1000, 0.0)
        opacity_func.AddPoint(-500, 0.0)
        opacity_func.AddPoint(200, 0.0)
        opacity_func.AddPoint(400, 0.3)
        opacity_func.AddPoint(1000, 0.8)
        opacity_func.AddPoint(3071, 0.9)
        
        # Create gradient opacity function
        gradient_func = vtk.vtkPiecewiseFunction()
        gradient_func.AddPoint(0, 0.0)
        gradient_func.AddPoint(90, 0.5)
        gradient_func.AddPoint(100, 1.0)
        
        # Set properties
        volume_property.SetColor(color_func)
        volume_property.SetScalarOpacity(opacity_func)
        volume_property.SetGradientOpacity(gradient_func)
        
        # Create volume
        volume = vtk.vtkVolume()
        volume.SetMapper(volume_mapper)
        volume.SetProperty(volume_property)
        
        # Add to renderer
        renderer.AddVolume(volume)
        
        # Setup camera for better initial view
        camera = renderer.GetActiveCamera()
        
        # Reset camera first to fit volume in view
        renderer.ResetCamera()
        
        # Position camera behind the volume (looking from back to front)
        # Z axis is typically up in medical images
        camera.SetViewUp(0, 0, 1)  # Z is up
        
        # Get volume bounds to calculate proper distance
        bounds = self.image_data.GetBounds()
        center_x = (bounds[0] + bounds[1]) / 2.0
        center_y = (bounds[2] + bounds[3]) / 2.0
        center_z = (bounds[4] + bounds[5]) / 2.0
        distance = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]) * 2.5
        
        camera.SetPosition(
            center_x,           # Center X
            center_y + distance,  # Behind (positive Y)
            center_z + distance * 0.5  # Elevated for better view
        )
        camera.SetFocalPoint(center_x, center_y, center_z)
        
        # Adjust camera for nice viewing angle
        camera.Elevation(15)  # Tilt up slightly for better perspective
        camera.Zoom(1.3)      # Zoom in to see details better
        
        logger.info("Created 3D volume rendering view")
    
    def setup_auto_rotation(self):
        """Setup auto-rotation timer for 3D view"""
        if '3d' not in self.viewers:
            return
        
        # Create auto-rotation timer
        self.auto_rotation_timer = QTimer(self)
        self.auto_rotation_timer.timeout.connect(self.auto_rotate_step)
        self.auto_rotation_timer.setInterval(30)  # ~30 FPS
        
        # Start auto-rotation by default
        self.auto_rotation_active = True
        self.auto_rotation_timer.start()
        
        logger.info("Auto-rotation enabled for 3D view - will stop on user interaction")
    
    def auto_rotate_step(self):
        """Perform one step of automatic rotation"""
        if not self.auto_rotation_active or '3d' not in self.viewers:
            return
        
        try:
            # Get camera from 3D view
            camera = self.viewers['3d']['camera']
            
            # Rotate slowly around Y axis (azimuth)
            camera.Azimuth(0.5)
            
            # Render
            renderer = self.viewers['3d']['renderer']
            renderer.GetRenderWindow().Render()
        except Exception as e:
            logger.debug(f"Auto-rotation step error: {e}")
    
    def stop_auto_rotation(self):
        """Stop the automatic rotation"""
        if self.auto_rotation_timer and self.auto_rotation_active:
            self.auto_rotation_active = False
            self.auto_rotation_timer.stop()
            logger.info("Auto-rotation stopped due to user interaction")
    
    def eventFilter(self, obj, event):
        """Event filter to detect user interaction with VTK widget"""
        # Stop auto-rotation on mouse press or wheel event
        if event.type() in [event.Type.MouseButtonPress, event.Type.Wheel]:
            self.stop_auto_rotation()
        return super().eventFilter(obj, event)
    
    def cleanup(self):
        """Cleanup VTK resources"""
        # Stop auto-rotation timer
        if hasattr(self, 'auto_rotation_timer') and self.auto_rotation_timer:
            self.auto_rotation_timer.stop()
            self.auto_rotation_timer = None
        
        try:
            for viewer in self.viewers.values():
                if 'widget' in viewer:
                    viewer['widget'].Finalize()
        except Exception as e:
            logger.error(f"Error cleaning up MPR viewer: {e}")
    
    def closeEvent(self, event):
        """Handle close event"""
        self.cleanup()
        super().closeEvent(event)

