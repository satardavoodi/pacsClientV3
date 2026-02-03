"""
MPR Slice View - Individual slice visualization with VTK

Provides a single MPR view (Axial, Sagittal, or Coronal) with:
- VTK-based rendering integrated with Qt
- Mouse wheel scrolling through slices
- Window/Level adjustment with right-click drag
- Crosshair display
- Orientation labels

Uses vtkImageReslice for proper orthogonal plane extraction.
"""

import logging
from typing import Optional, Callable, List, Tuple

import numpy as np
import vtkmodules.all as vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from ..core.mpr_calculator import MPRCalculator, PlaneType, STANDARD_PLANES

logger = logging.getLogger(__name__)


class MPRSliceView(QVTKRenderWindowInteractor):
    """
    VTK-based view for displaying a single MPR slice.
    
    Uses vtkImageReslice for proper orthogonal plane visualization.
    """
    
    def __init__(
        self,
        plane_type: PlaneType,
        parent=None
    ):
        """
        Initialize the MPR slice view.
        
        Args:
            plane_type: Type of anatomical plane (AXIAL, SAGITTAL, CORONAL)
            parent: Parent Qt widget
        """
        super().__init__(parent)
        
        self.plane_type = plane_type
        self._vtk_image: Optional[vtk.vtkImageData] = None
        self._mpr_calculator: Optional[MPRCalculator] = None
        
        # Current state
        self._current_slice = 0
        self._window = 400.0
        self._level = 40.0
        self._min_slice = 0
        self._max_slice = 0
        
        # Callbacks
        self._slice_changed_callbacks: List[Callable] = []
        self._center_changed_callbacks: List[Callable] = []
        
        # Initialize VTK pipeline
        self._init_vtk_pipeline()
        
        # Initialize interactor
        self._init_interactor()
        
        logger.debug(f"MPRSliceView initialized: {plane_type.value}")
    
    def _init_vtk_pipeline(self):
        """Initialize VTK rendering pipeline using vtkImageReslice."""
        render_window = self.GetRenderWindow()
        render_window.SetMultiSamples(0)
        render_window.SetNumberOfLayers(2)
        
        # Layer 0: Image renderer
        self._renderer = vtk.vtkRenderer()
        self._renderer.SetBackground(0.0, 0.0, 0.0)
        self._renderer.SetLayer(0)
        render_window.AddRenderer(self._renderer)
        
        # Layer 1: Overlay renderer (for crosshairs and text)
        self._overlay_renderer = vtk.vtkRenderer()
        self._overlay_renderer.SetBackground(0, 0, 0)
        self._overlay_renderer.SetBackgroundAlpha(0)
        self._overlay_renderer.SetLayer(1)
        self._overlay_renderer.InteractiveOff()
        render_window.AddRenderer(self._overlay_renderer)
        
        # Create reslice filter for extracting slices
        self._reslice = vtk.vtkImageReslice()
        self._reslice.SetOutputDimensionality(2)
        self._reslice.SetInterpolationModeToLinear()
        self._reslice.AutoCropOutputOn()
        
        # Create reslice axes matrix
        self._reslice_axes = vtk.vtkMatrix4x4()
        
        # Window/Level filter
        self._window_level = vtk.vtkImageMapToWindowLevelColors()
        self._window_level.SetWindow(self._window)
        self._window_level.SetLevel(self._level)
        self._window_level.SetInputConnection(self._reslice.GetOutputPort())
        
        # Image actor for display
        self._image_actor = vtk.vtkImageActor()
        self._image_actor.InterpolateOn()
        self._image_actor.GetMapper().SetInputConnection(self._window_level.GetOutputPort())
        
        # Add to renderer
        self._renderer.AddActor(self._image_actor)
        
        # Create orientation labels
        self._orientation_actors = {}
        self._create_orientation_labels()
        
        # Slice info text actor
        self._slice_info_actor = vtk.vtkTextActor()
        self._slice_info_actor.SetPosition(10, 10)
        self._slice_info_actor.GetTextProperty().SetFontSize(14)
        self._slice_info_actor.GetTextProperty().SetColor(1, 1, 0)
        self._overlay_renderer.AddActor(self._slice_info_actor)
        
        # Crosshair lines
        self._crosshair_h = self._create_line_actor((0, 1, 0))
        self._crosshair_v = self._create_line_actor((0, 1, 0))
        self._overlay_renderer.AddActor(self._crosshair_h)
        self._overlay_renderer.AddActor(self._crosshair_v)
    
    def _create_line_actor(self, color: Tuple[float, float, float]) -> vtk.vtkActor:
        """Create a line actor for crosshairs."""
        line_source = vtk.vtkLineSource()
        line_source.SetPoint1(0, 0, 0)
        line_source.SetPoint2(1, 1, 0)
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(line_source.GetOutputPort())
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetLineWidth(1.5)
        actor.VisibilityOff()
        
        actor._line_source = line_source
        return actor
    
    def _create_orientation_labels(self):
        """Create orientation label text actors."""
        labels = self._get_orientation_labels()
        
        positions = {
            "left": (0.02, 0.5),
            "right": (0.95, 0.5),
            "top": (0.5, 0.92),
            "bottom": (0.5, 0.05)
        }
        
        for position_name, (x, y) in positions.items():
            label = labels.get(position_name, "")
            
            actor = vtk.vtkTextActor()
            actor.SetInput(label)
            actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            actor.GetPositionCoordinate().SetValue(x, y)
            actor.GetTextProperty().SetFontSize(16)
            actor.GetTextProperty().SetColor(0.9, 0.9, 0.0)
            actor.GetTextProperty().SetBold(True)
            actor.GetTextProperty().SetJustificationToCentered()
            actor.GetTextProperty().SetVerticalJustificationToCentered()
            
            self._overlay_renderer.AddActor(actor)
            self._orientation_actors[position_name] = actor
    
    def _get_orientation_labels(self) -> dict:
        """Get orientation labels for current plane."""
        if self.plane_type == PlaneType.AXIAL:
            # Looking from feet toward head (standard radiological)
            return {
                "left": "R",
                "right": "L",
                "top": "A",
                "bottom": "P"
            }
        elif self.plane_type == PlaneType.SAGITTAL:
            # Looking from patient's left side
            return {
                "left": "A",
                "right": "P",
                "top": "S",
                "bottom": "I"
            }
        elif self.plane_type == PlaneType.CORONAL:
            # Looking from posterior (back)
            return {
                "left": "L",
                "right": "R",
                "top": "S",
                "bottom": "I"
            }
        return {}
    
    def _init_interactor(self):
        """Initialize interactor style and events."""
        style = vtk.vtkInteractorStyleImage()
        
        interactor = self.GetRenderWindow().GetInteractor()
        interactor.SetInteractorStyle(style)
        
        # Add observers
        interactor.AddObserver("MouseWheelForwardEvent", self._on_mouse_wheel_forward)
        interactor.AddObserver("MouseWheelBackwardEvent", self._on_mouse_wheel_backward)
        interactor.AddObserver("LeftButtonPressEvent", self._on_left_click)
    
    def _on_mouse_wheel_forward(self, obj, event):
        """Handle mouse wheel forward (scroll up)."""
        self.set_slice(self._current_slice + 1)
    
    def _on_mouse_wheel_backward(self, obj, event):
        """Handle mouse wheel backward (scroll down)."""
        self.set_slice(self._current_slice - 1)
    
    def _on_left_click(self, obj, event):
        """Handle left click to move crosshair."""
        if self._mpr_calculator is None:
            return
        
        interactor = self.GetRenderWindow().GetInteractor()
        click_pos = interactor.GetEventPosition()
        
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.005)
        
        if picker.Pick(click_pos[0], click_pos[1], 0, self._renderer):
            world_pos = picker.GetPickPosition()
            if world_pos != (0, 0, 0):
                self._update_center_from_click(world_pos)
    
    def _update_center_from_click(self, world_pos: Tuple[float, float, float]):
        """Update center based on click position."""
        if self._mpr_calculator is None:
            return
        
        current_center = list(self._mpr_calculator.center)
        
        # Update axes based on plane type
        if self.plane_type == PlaneType.AXIAL:
            current_center[0] = world_pos[0]
            current_center[1] = world_pos[1]
        elif self.plane_type == PlaneType.SAGITTAL:
            current_center[1] = world_pos[0]
            current_center[2] = world_pos[1]
        elif self.plane_type == PlaneType.CORONAL:
            current_center[0] = world_pos[0]
            current_center[2] = world_pos[1]
        
        self._mpr_calculator.set_center(current_center)
        
        for callback in self._center_changed_callbacks:
            callback(self.plane_type, current_center)
    
    def set_image(self, vtk_image: vtk.vtkImageData):
        """
        Set the volume image to display.
        
        Args:
            vtk_image: 3D vtkImageData
        """
        self._vtk_image = vtk_image
        
        # Create MPR calculator
        self._mpr_calculator = MPRCalculator(vtk_image)
        
        # Update slice range
        self._min_slice, self._max_slice = self._mpr_calculator.get_slice_range(self.plane_type)
        self._current_slice = (self._min_slice + self._max_slice) // 2
        
        # Setup reslice pipeline
        self._reslice.SetInputData(vtk_image)
        
        # Setup reslice axes for this plane type
        self._setup_reslice_axes()
        
        # Update display
        self._update_slice()
        
        # Setup camera
        self._setup_camera()
        
        logger.info(f"Image set: slice range [{self._min_slice}, {self._max_slice}]")
    
    def _setup_reslice_axes(self):
        """Setup reslice axes matrix for current plane type."""
        if self._vtk_image is None:
            return
        
        # Get image properties
        spacing = self._vtk_image.GetSpacing()
        origin = self._vtk_image.GetOrigin()
        dims = self._vtk_image.GetDimensions()
        
        # Calculate center of volume
        center = [
            origin[0] + spacing[0] * dims[0] / 2,
            origin[1] + spacing[1] * dims[1] / 2,
            origin[2] + spacing[2] * dims[2] / 2
        ]
        
        # Reset matrix to identity
        self._reslice_axes.Identity()
        
        if self.plane_type == PlaneType.AXIAL:
            # XY plane - standard orientation
            # Row 0: X axis direction
            self._reslice_axes.SetElement(0, 0, 1)
            self._reslice_axes.SetElement(1, 0, 0)
            self._reslice_axes.SetElement(2, 0, 0)
            # Row 1: Y axis direction
            self._reslice_axes.SetElement(0, 1, 0)
            self._reslice_axes.SetElement(1, 1, 1)
            self._reslice_axes.SetElement(2, 1, 0)
            # Row 2: Z axis direction (normal)
            self._reslice_axes.SetElement(0, 2, 0)
            self._reslice_axes.SetElement(1, 2, 0)
            self._reslice_axes.SetElement(2, 2, 1)
            
        elif self.plane_type == PlaneType.SAGITTAL:
            # YZ plane
            # Row 0: Y axis direction
            self._reslice_axes.SetElement(0, 0, 0)
            self._reslice_axes.SetElement(1, 0, 1)
            self._reslice_axes.SetElement(2, 0, 0)
            # Row 1: Z axis direction
            self._reslice_axes.SetElement(0, 1, 0)
            self._reslice_axes.SetElement(1, 1, 0)
            self._reslice_axes.SetElement(2, 1, 1)
            # Row 2: X axis direction (normal)
            self._reslice_axes.SetElement(0, 2, 1)
            self._reslice_axes.SetElement(1, 2, 0)
            self._reslice_axes.SetElement(2, 2, 0)
            
        elif self.plane_type == PlaneType.CORONAL:
            # XZ plane
            # Row 0: X axis direction
            self._reslice_axes.SetElement(0, 0, 1)
            self._reslice_axes.SetElement(1, 0, 0)
            self._reslice_axes.SetElement(2, 0, 0)
            # Row 1: Z axis direction
            self._reslice_axes.SetElement(0, 1, 0)
            self._reslice_axes.SetElement(1, 1, 0)
            self._reslice_axes.SetElement(2, 1, 1)
            # Row 2: Y axis direction (normal)
            self._reslice_axes.SetElement(0, 2, 0)
            self._reslice_axes.SetElement(1, 2, 1)
            self._reslice_axes.SetElement(2, 2, 0)
        
        # Set origin (will be updated for each slice)
        self._reslice_axes.SetElement(0, 3, center[0])
        self._reslice_axes.SetElement(1, 3, center[1])
        self._reslice_axes.SetElement(2, 3, center[2])
        
        self._reslice.SetResliceAxes(self._reslice_axes)
    
    def _update_reslice_origin(self):
        """Update reslice origin based on current slice."""
        if self._vtk_image is None or self._mpr_calculator is None:
            return
        
        origin = self._vtk_image.GetOrigin()
        spacing = self._vtk_image.GetSpacing()
        dims = self._vtk_image.GetDimensions()
        
        # Calculate center for non-slice axes
        center_x = origin[0] + spacing[0] * dims[0] / 2
        center_y = origin[1] + spacing[1] * dims[1] / 2
        center_z = origin[2] + spacing[2] * dims[2] / 2
        
        # Calculate slice position
        if self.plane_type == PlaneType.AXIAL:
            slice_pos = origin[2] + self._current_slice * spacing[2]
            self._reslice_axes.SetElement(0, 3, center_x)
            self._reslice_axes.SetElement(1, 3, center_y)
            self._reslice_axes.SetElement(2, 3, slice_pos)
        elif self.plane_type == PlaneType.SAGITTAL:
            slice_pos = origin[0] + self._current_slice * spacing[0]
            self._reslice_axes.SetElement(0, 3, slice_pos)
            self._reslice_axes.SetElement(1, 3, center_y)
            self._reslice_axes.SetElement(2, 3, center_z)
        elif self.plane_type == PlaneType.CORONAL:
            slice_pos = origin[1] + self._current_slice * spacing[1]
            self._reslice_axes.SetElement(0, 3, center_x)
            self._reslice_axes.SetElement(1, 3, slice_pos)
            self._reslice_axes.SetElement(2, 3, center_z)
        
        self._reslice.SetResliceAxes(self._reslice_axes)
    
    def _setup_camera(self):
        """Setup camera for 2D image viewing."""
        self._renderer.ResetCamera()
        
        camera = self._renderer.GetActiveCamera()
        camera.ParallelProjectionOn()
        
        # Get image bounds for proper view
        self._reslice.Update()
        output = self._reslice.GetOutput()
        if output:
            bounds = output.GetBounds()
            if bounds[1] > bounds[0] and bounds[3] > bounds[2]:
                x_size = bounds[1] - bounds[0]
                y_size = bounds[3] - bounds[2]
                camera.SetParallelScale(max(x_size, y_size) / 2 * 1.1)
        
        # Share camera with overlay renderer
        self._overlay_renderer.SetActiveCamera(camera)
    
    def _update_slice(self):
        """Update the displayed slice."""
        if self._vtk_image is None:
            return
        
        # Update reslice origin for current slice
        self._update_reslice_origin()
        
        # Update pipeline
        self._reslice.Update()
        self._window_level.Update()
        
        # Update slice info text
        self._update_slice_info()
        
        # Update crosshairs
        self._update_crosshairs()
        
        # Render
        self.GetRenderWindow().Render()
    
    def _update_slice_info(self):
        """Update slice information text."""
        text = f"Slice: {self._current_slice + 1}/{self._max_slice + 1}"
        if self._mpr_calculator:
            pos = self._mpr_calculator.get_slice_position(self.plane_type)
            text += f" ({pos:.1f} mm)"
        
        self._slice_info_actor.SetInput(text)
    
    def _update_crosshairs(self):
        """Update crosshair positions."""
        if self._mpr_calculator is None:
            return
        
        # Get output bounds from reslice
        self._reslice.Update()
        output = self._reslice.GetOutput()
        if output is None:
            return
        
        bounds = output.GetBounds()
        center_x = (bounds[0] + bounds[1]) / 2
        center_y = (bounds[2] + bounds[3]) / 2
        
        # Horizontal line
        self._crosshair_h._line_source.SetPoint1(bounds[0], center_y, 0)
        self._crosshair_h._line_source.SetPoint2(bounds[1], center_y, 0)
        self._crosshair_h._line_source.Update()
        
        # Vertical line
        self._crosshair_v._line_source.SetPoint1(center_x, bounds[2], 0)
        self._crosshair_v._line_source.SetPoint2(center_x, bounds[3], 0)
        self._crosshair_v._line_source.Update()
    
    def set_slice(self, index: int):
        """Set the current slice index."""
        index = max(self._min_slice, min(index, self._max_slice))
        
        if index != self._current_slice:
            self._current_slice = index
            
            # Update calculator center
            if self._mpr_calculator:
                self._mpr_calculator.set_slice_index(self.plane_type, index)
            
            self._update_slice()
            
            for callback in self._slice_changed_callbacks:
                callback(self.plane_type, index)
    
    def get_slice(self) -> int:
        """Get current slice index."""
        return self._current_slice
    
    def get_slice_range(self) -> Tuple[int, int]:
        """Get valid slice range."""
        return (self._min_slice, self._max_slice)
    
    def set_window_level(self, window: float, level: float):
        """Set window/level for display."""
        self._window = window
        self._level = level
        
        self._window_level.SetWindow(window)
        self._window_level.SetLevel(level)
        self._window_level.Update()
        
        self.GetRenderWindow().Render()
    
    def get_window_level(self) -> Tuple[float, float]:
        """Get current window/level."""
        return (self._window, self._level)
    
    def set_crosshair_visible(self, visible: bool):
        """Show or hide crosshairs."""
        if visible:
            self._crosshair_h.VisibilityOn()
            self._crosshair_v.VisibilityOn()
        else:
            self._crosshair_h.VisibilityOff()
            self._crosshair_v.VisibilityOff()
        
        self.GetRenderWindow().Render()
    
    def set_mpr_calculator(self, calculator: MPRCalculator):
        """Set shared MPR calculator for synchronized views."""
        self._mpr_calculator = calculator
        
        # Get vtk_image from calculator if not already set
        if self._vtk_image is None and hasattr(calculator, 'vtk_image'):
            self._vtk_image = calculator.vtk_image
            self._reslice.SetInputData(self._vtk_image)
            self._setup_reslice_axes()
        
        self._min_slice, self._max_slice = calculator.get_slice_range(self.plane_type)
        self._current_slice = calculator.get_slice_index(self.plane_type)
        
        # Update display
        if self._vtk_image is not None:
            self._update_slice()
            self._setup_camera()
    
    def add_slice_changed_callback(self, callback: Callable):
        """Add callback for slice change events."""
        self._slice_changed_callbacks.append(callback)
    
    def add_center_changed_callback(self, callback: Callable):
        """Add callback for center change events."""
        self._center_changed_callbacks.append(callback)
    
    def update_from_calculator(self):
        """Update view based on current calculator state."""
        if self._mpr_calculator is None:
            return
        
        # Get current slice index from calculator
        new_slice = self._mpr_calculator.get_slice_index(self.plane_type)
        
        if new_slice != self._current_slice:
            self._current_slice = new_slice
            self._update_slice()
        else:
            # Just update crosshairs
            self._update_crosshairs()
            self.GetRenderWindow().Render()
    
    def reset_camera(self):
        """Reset camera to fit the slice."""
        self._setup_camera()
        self.GetRenderWindow().Render()
    
    def cleanup(self):
        """Clean up VTK resources."""
        try:
            self.GetRenderWindow().Finalize()
            self.close()
        except Exception as e:
            logger.warning(f"Error during cleanup: {e}")
