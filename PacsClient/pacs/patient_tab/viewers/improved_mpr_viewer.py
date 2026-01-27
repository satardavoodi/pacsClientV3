"""
Improved MPR Viewer with Separate RenderWindows
Based on VTK discourse solution - prevents crosshair overlap
"""
import logging
from typing import Optional

import vtkmodules.all as vtk
from PySide6.QtWidgets import QWidget, QGridLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class ImprovedMPRViewer(QWidget):
    """
    MPR viewer with separate render windows to prevent crosshair overlap
    Based on: https://discourse.vtk.org/t/create-mpr-view-with-independent-cross-sectional-hairs-cursor-between-views/8714
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
        
        # Setup UI
        self._setup_ui()
        
        # Create viewers with separate render windows
        self._create_viewers()
        
        logger.info("Improved MPR viewer created with separate render windows")
    
    def _setup_ui(self):
        """Setup the UI layout"""
        layout = QGridLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)  # Add spacing between views
        
        self.setLayout(layout)
        
        # Set dark background
        self.setStyleSheet("""
            QWidget {
                background-color: #000000;
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
        """Create 4 views with independent interactions"""
        from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
        
        layout = self.layout()
        
        # Get image dimensions
        dims = self.image_data.GetDimensions()
        
        # Define views - matching the reference image layout
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
                'name': '3D Volume',
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
            
            # Create SEPARATE VTK widget for each view
            vtk_widget = QVTKRenderWindowInteractor(container)
            container_layout.addWidget(vtk_widget)
            
            # Each widget gets its OWN render window and interactor
            render_window = vtk_widget.GetRenderWindow()
            
            # Create renderer
            renderer = vtk.vtkRenderer()
            renderer.SetBackground(0.0, 0.0, 0.0)  # Black background
            
            render_window.AddRenderer(renderer)
            
            # Create 3D or 2D view
            if view_config['is_3d']:
                # Create 3D volume rendering
                self._create_3d_view(renderer)
                
                # Setup 3D interactor style for rotation
                style = vtk.vtkInteractorStyleTrackballCamera()
                vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(style)
            else:
                # Create 2D slice with crosshair
                image_slice = self._create_image_slice(
                    view_config['orientation'],
                    view_config['slice']
                )
                
                # Create actor
                actor = vtk.vtkImageActor()
                actor.SetInputData(image_slice.GetOutput())
                renderer.AddActor(actor)
                
                # Set proper window/level for visibility
                scalar_range = self.image_data.GetScalarRange()
                window = scalar_range[1] - scalar_range[0]
                level = (scalar_range[0] + scalar_range[1]) / 2.0
                
                # Create image mapper with window/level
                image_mapper = vtk.vtkImageSliceMapper()
                image_mapper.SetInputData(image_slice.GetOutput())
                
                # Create image slice actor (better than vtkImageActor for 2D)
                image_actor = vtk.vtkImageSlice()
                image_actor.SetMapper(image_mapper)
                
                # Set window/level
                property = image_actor.GetProperty()
                property.SetColorWindow(window)
                property.SetColorLevel(level)
                
                renderer.AddViewProp(image_actor)
                
                # Add crosshair lines (constrained to this view only)
                crosshair_actors = self._create_crosshair_lines(
                    view_config['orientation'], 
                    dims,
                    view_config['slice']
                )
                for ch_actor in crosshair_actors:
                    renderer.AddActor(ch_actor)
                
                # Reset camera to fit the image
                renderer.ResetCamera()
                
                # Adjust camera for better fit
                camera = renderer.GetActiveCamera()
                camera.ParallelProjectionOn()
                
                # Set up custom interactor style for scrolling through slices
                interactor_style = self._create_slice_interactor_style(
                    view_config['orientation'],
                    view_config['slice'],
                    renderer,
                    image_actor,
                    image_slice,
                    crosshair_actors
                )
                vtk_widget.SetInteractorStyle(interactor_style)
                
                # Store slice info for scrolling
                view_info = {
                    'widget': vtk_widget,
                    'renderer': renderer,
                    'orientation': view_config['orientation'],
                    'is_3d': False,
                    'container': container,
                    'actor': image_actor,
                    'slicer': image_slice,
                    'crosshair_actors': crosshair_actors,
                    'current_slice': view_config['slice'],
                    'max_slice': dims[view_config['orientation']],
                    'window': window,
                    'level': level
                }
                
                self.viewers[view_config['name'].lower()] = view_info
            
            renderer.ResetCamera()
            
            # Add to layout (not duplicating storage)
            if view_config['is_3d']:
                # Store 3D view info
                self.viewers[view_config['name'].lower()] = {
                    'widget': vtk_widget,
                    'renderer': renderer,
                    'orientation': view_config['orientation'],
                    'is_3d': True,
                    'container': container
                }
            
            # Add to layout
            layout.addWidget(container, view_config['row'], view_config['col'])
            
            # Initialize
            vtk_widget.Initialize()
            vtk_widget.Start()
        
        logger.info("Created 4 independent views (3 MPR + 1 3D)")
    
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
            axes.SetElement(0, 3, origin[2] + dims[2] * spacing[2])
            
            axes.SetElement(1, 0, 1)
            axes.SetElement(1, 1, 0)
            axes.SetElement(1, 2, 0)
            axes.SetElement(1, 3, origin[1])
            
            axes.SetElement(2, 0, 0)
            axes.SetElement(2, 1, 1)
            axes.SetElement(2, 2, 0)
            axes.SetElement(2, 3, origin[0] + slice_number * spacing[0])
            
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
    
    def _create_slice_interactor_style(self, orientation: int, initial_slice: int, 
                                      renderer, actor, slicer, crosshair_actors):
        """
        Create custom interactor style for scrolling through slices
        
        Args:
            orientation: View orientation
            initial_slice: Initial slice number
            renderer: VTK renderer
            actor: Image actor
            slicer: vtkImageReslice
            crosshair_actors: List of crosshair actors
            
        Returns:
            Custom interactor style
        """
        dims = self.image_data.GetDimensions()
        max_slice = dims[orientation] - 1
        
        class SliceScrollInteractor(vtk.vtkInteractorStyleImage):
            def __init__(self, parent_viewer, orientation, initial_slice, renderer, 
                        actor, slicer, crosshair_actors, max_slice):
                self.parent_viewer = parent_viewer
                self.orientation = orientation
                self.current_slice = initial_slice
                self.renderer = renderer
                self.actor = actor
                self.slicer = slicer
                self.crosshair_actors = crosshair_actors
                self.max_slice = max_slice
                self.AddObserver("MouseWheelForwardEvent", self.on_mouse_wheel_forward)
                self.AddObserver("MouseWheelBackwardEvent", self.on_mouse_wheel_backward)
            
            def on_mouse_wheel_forward(self, obj, event):
                # Scroll forward (increase slice)
                if self.current_slice < self.max_slice:
                    self.current_slice += 1
                    self.update_slice()
                return
            
            def on_mouse_wheel_backward(self, obj, event):
                # Scroll backward (decrease slice)
                if self.current_slice > 0:
                    self.current_slice -= 1
                    self.update_slice()
                return
            
            def update_slice(self):
                # Update the reslice to show new slice
                spacing = self.parent_viewer.image_data.GetSpacing()
                origin = self.parent_viewer.image_data.GetOrigin()
                dims = self.parent_viewer.image_data.GetDimensions()
                
                axes = vtk.vtkMatrix4x4()
                
                if self.orientation == 0:  # Sagittal
                    axes.SetElement(0, 0, 0)
                    axes.SetElement(0, 1, 0)
                    axes.SetElement(0, 2, -1)
                    axes.SetElement(0, 3, origin[2] + dims[2] * spacing[2])
                    
                    axes.SetElement(1, 0, 1)
                    axes.SetElement(1, 1, 0)
                    axes.SetElement(1, 2, 0)
                    axes.SetElement(1, 3, origin[1])
                    
                    axes.SetElement(2, 0, 0)
                    axes.SetElement(2, 1, 1)
                    axes.SetElement(2, 2, 0)
                    axes.SetElement(2, 3, origin[0] + self.current_slice * spacing[0])
                    
                elif self.orientation == 1:  # Coronal
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
                    axes.SetElement(2, 3, origin[1] + self.current_slice * spacing[1])
                    
                else:  # Axial
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
                    axes.SetElement(2, 3, origin[2] + self.current_slice * spacing[2])
                
                # Update the slicer
                self.slicer.SetResliceAxes(axes)
                self.slicer.Update()
                
                # Update the mapper input (این خط مهم است!)
                self.actor.GetMapper().SetInputData(self.slicer.GetOutput())
                self.actor.GetMapper().Update()
                
                # Update crosshair position
                self.parent_viewer._update_crosshair_position(
                    self.crosshair_actors,
                    self.orientation,
                    self.current_slice
                )
                
                # Reset camera to ensure proper view
                self.renderer.ResetCamera()
                
                # Re-render
                self.renderer.GetRenderWindow().Render()
        
        return SliceScrollInteractor(
            self, orientation, initial_slice, renderer, 
            actor, slicer, crosshair_actors, max_slice
        )
    
    def _update_crosshair_position(self, crosshair_actors, orientation: int, slice_num: int):
        """
        Update crosshair position for new slice
        
        Args:
            crosshair_actors: List of crosshair actors
            orientation: View orientation
            slice_num: Current slice number
        """
        dims = self.image_data.GetDimensions()
        spacing = self.image_data.GetSpacing()
        origin = self.image_data.GetOrigin()
        
        # Calculate bounds
        bounds_x = [origin[0], origin[0] + dims[0] * spacing[0]]
        bounds_y = [origin[1], origin[1] + dims[1] * spacing[1]]
        bounds_z = [origin[2], origin[2] + dims[2] * spacing[2]]
        
        center_x = (bounds_x[0] + bounds_x[1]) / 2
        center_y = (bounds_y[0] + bounds_y[1]) / 2
        center_z = (bounds_z[0] + bounds_z[1]) / 2
        
        # Update line positions
        for i, actor in enumerate(crosshair_actors):
            mapper = actor.GetMapper()
            line_source = mapper.GetInputConnection(0, 0).GetProducer()
            
            if orientation == 2:  # Axial
                z_pos = origin[2] + slice_num * spacing[2]
                if i == 0:  # Horizontal
                    line_source.SetPoint1(bounds_x[0], center_y, z_pos)
                    line_source.SetPoint2(bounds_x[1], center_y, z_pos)
                else:  # Vertical
                    line_source.SetPoint1(center_x, bounds_y[0], z_pos)
                    line_source.SetPoint2(center_x, bounds_y[1], z_pos)
                    
            elif orientation == 0:  # Sagittal
                x_pos = origin[0] + slice_num * spacing[0]
                if i == 0:  # Horizontal
                    line_source.SetPoint1(x_pos, bounds_y[0], center_z)
                    line_source.SetPoint2(x_pos, bounds_y[1], center_z)
                else:  # Vertical
                    line_source.SetPoint1(x_pos, center_y, bounds_z[0])
                    line_source.SetPoint2(x_pos, center_y, bounds_z[1])
                    
            else:  # Coronal
                y_pos = origin[1] + slice_num * spacing[1]
                if i == 0:  # Horizontal
                    line_source.SetPoint1(bounds_x[0], y_pos, center_z)
                    line_source.SetPoint2(bounds_x[1], y_pos, center_z)
                else:  # Vertical
                    line_source.SetPoint1(center_x, y_pos, bounds_z[0])
                    line_source.SetPoint2(center_x, y_pos, bounds_z[1])
            
            line_source.Update()
    
    def _create_crosshair_lines(self, orientation: int, dims: tuple, slice_num: int) -> list:
        """
        Create crosshair lines that are properly positioned on the image
        
        Args:
            orientation: View orientation (0=sagittal, 1=coronal, 2=axial)
            dims: Image dimensions
            slice_num: Current slice number
            
        Returns:
            List of vtkActor objects for crosshair lines
        """
        actors = []
        
        # Get image info
        spacing = self.image_data.GetSpacing()
        origin = self.image_data.GetOrigin()
        
        # Calculate bounds
        bounds_x = [origin[0], origin[0] + dims[0] * spacing[0]]
        bounds_y = [origin[1], origin[1] + dims[1] * spacing[1]]
        bounds_z = [origin[2], origin[2] + dims[2] * spacing[2]]
        
        center_x = (bounds_x[0] + bounds_x[1]) / 2
        center_y = (bounds_y[0] + bounds_y[1]) / 2
        center_z = (bounds_z[0] + bounds_z[1]) / 2
        
        # Create two perpendicular lines at the current slice position
        for i in range(2):
            line_source = vtk.vtkLineSource()
            
            if orientation == 2:  # Axial (XY plane)
                z_pos = origin[2] + slice_num * spacing[2]
                if i == 0:  # Horizontal (red - X direction)
                    line_source.SetPoint1(bounds_x[0], center_y, z_pos)
                    line_source.SetPoint2(bounds_x[1], center_y, z_pos)
                    color = (1.0, 0.0, 0.0)  # Red
                else:  # Vertical (green - Y direction)
                    line_source.SetPoint1(center_x, bounds_y[0], z_pos)
                    line_source.SetPoint2(center_x, bounds_y[1], z_pos)
                    color = (0.0, 1.0, 0.0)  # Green
                    
            elif orientation == 0:  # Sagittal (YZ plane)
                x_pos = origin[0] + slice_num * spacing[0]
                if i == 0:  # Horizontal (green - Y direction)
                    line_source.SetPoint1(x_pos, bounds_y[0], center_z)
                    line_source.SetPoint2(x_pos, bounds_y[1], center_z)
                    color = (0.0, 1.0, 0.0)  # Green
                else:  # Vertical (blue - Z direction)
                    line_source.SetPoint1(x_pos, center_y, bounds_z[0])
                    line_source.SetPoint2(x_pos, center_y, bounds_z[1])
                    color = (0.0, 0.5, 1.0)  # Blue
                    
            else:  # Coronal (XZ plane)
                y_pos = origin[1] + slice_num * spacing[1]
                if i == 0:  # Horizontal (red - X direction)
                    line_source.SetPoint1(bounds_x[0], y_pos, center_z)
                    line_source.SetPoint2(bounds_x[1], y_pos, center_z)
                    color = (1.0, 0.0, 0.0)  # Red
                else:  # Vertical (blue - Z direction)
                    line_source.SetPoint1(center_x, y_pos, bounds_z[0])
                    line_source.SetPoint2(center_x, y_pos, bounds_z[1])
                    color = (0.0, 0.5, 1.0)  # Blue
            
            # Create mapper and actor
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(line_source.GetOutputPort())
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(color)
            actor.GetProperty().SetLineWidth(2)
            actor.GetProperty().SetOpacity(0.8)
            actor.PickableOff()  # Prevent interaction with crosshair
            
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
        volume_mapper.SetBlendModeToComposite()
        
        # Create volume property
        volume_property = vtk.vtkVolumeProperty()
        volume_property.ShadeOn()
        volume_property.SetInterpolationTypeToLinear()
        
        # Get scalar range
        scalar_range = self.image_data.GetScalarRange()
        
        # Create color transfer function (brown/tan for bone like reference image)
        color_func = vtk.vtkColorTransferFunction()
        color_func.AddRGBPoint(scalar_range[0], 0.0, 0.0, 0.0)
        color_func.AddRGBPoint(scalar_range[0] + 150, 0.55, 0.25, 0.15)
        color_func.AddRGBPoint(scalar_range[0] + 320, 0.88, 0.60, 0.29)
        color_func.AddRGBPoint(scalar_range[0] + 440, 1.0, 0.94, 0.95)
        color_func.AddRGBPoint(scalar_range[1], 0.83, 0.66, 1.0)
        
        # Create opacity transfer function
        opacity_func = vtk.vtkPiecewiseFunction()
        opacity_func.AddPoint(scalar_range[0], 0.0)
        opacity_func.AddPoint(scalar_range[0] + 150, 0.0)
        opacity_func.AddPoint(scalar_range[0] + 320, 0.45)
        opacity_func.AddPoint(scalar_range[0] + 440, 0.63)
        opacity_func.AddPoint(scalar_range[1], 0.63)
        
        # Set properties
        volume_property.SetColor(color_func)
        volume_property.SetScalarOpacity(opacity_func)
        volume_property.SetAmbient(0.20)
        volume_property.SetDiffuse(1.00)
        volume_property.SetSpecular(0.00)
        
        # Create volume
        volume = vtk.vtkVolume()
        volume.SetMapper(volume_mapper)
        volume.SetProperty(volume_property)
        
        # Add to renderer
        renderer.AddVolume(volume)
        
        # Reset camera to show full volume
        renderer.ResetCamera()
        
        # Set camera for nice view (similar to reference image)
        camera = renderer.GetActiveCamera()
        camera.SetViewUp(0, 0, -1)
        camera.SetPosition(1, -1, 0.5)
        camera.SetFocalPoint(0, 0, 0)
        renderer.ResetCamera()
        
        logger.info("Created 3D volume rendering view")
    
    def cleanup(self):
        """Cleanup VTK resources"""
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

