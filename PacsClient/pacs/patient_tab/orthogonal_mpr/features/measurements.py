"""
Measurements - Distance and angle measurement tools for MPR

Provides interactive measurement tools:
- Distance measurement between two points
- Angle measurement between three points
- Area measurement (polygon)

All measurements are in physical units (mm, degrees, mm^2).
"""

import logging
from typing import Optional, List, Tuple, Dict, Callable
from dataclasses import dataclass, field
from enum import Enum
import uuid

import numpy as np
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class MeasurementType(Enum):
    """Types of measurements."""
    DISTANCE = "distance"
    ANGLE = "angle"
    AREA = "area"


@dataclass
class DistanceMeasurement:
    """
    Distance measurement between two points.
    
    Attributes:
        id: Unique identifier
        point1: First point (x, y, z)
        point2: Second point (x, y, z)
        distance: Calculated distance in mm
        visible: Whether measurement is visible
    """
    point1: Tuple[float, float, float]
    point2: Tuple[float, float, float]
    distance: float = 0.0
    visible: bool = True
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    def __post_init__(self):
        """Calculate distance after initialization."""
        self.distance = self.calculate_distance()
    
    def calculate_distance(self) -> float:
        """Calculate Euclidean distance between points."""
        p1 = np.array(self.point1)
        p2 = np.array(self.point2)
        return float(np.linalg.norm(p2 - p1))
    
    def update_point(self, point_index: int, new_position: Tuple[float, float, float]):
        """Update a point position."""
        if point_index == 0:
            self.point1 = new_position
        else:
            self.point2 = new_position
        self.distance = self.calculate_distance()


@dataclass
class AngleMeasurement:
    """
    Angle measurement between three points.
    
    Attributes:
        id: Unique identifier
        vertex: Vertex point (angle measured here)
        point1: First arm endpoint
        point2: Second arm endpoint
        angle: Calculated angle in degrees
        visible: Whether measurement is visible
    """
    vertex: Tuple[float, float, float]
    point1: Tuple[float, float, float]
    point2: Tuple[float, float, float]
    angle: float = 0.0
    visible: bool = True
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    def __post_init__(self):
        """Calculate angle after initialization."""
        self.angle = self.calculate_angle()
    
    def calculate_angle(self) -> float:
        """Calculate angle at vertex in degrees."""
        v = np.array(self.vertex)
        p1 = np.array(self.point1)
        p2 = np.array(self.point2)
        
        # Vectors from vertex to points
        vec1 = p1 - v
        vec2 = p2 - v
        
        # Normalize
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 < 1e-10 or norm2 < 1e-10:
            return 0.0
        
        vec1 = vec1 / norm1
        vec2 = vec2 / norm2
        
        # Calculate angle
        cos_angle = np.clip(np.dot(vec1, vec2), -1.0, 1.0)
        angle_rad = np.arccos(cos_angle)
        
        return float(np.degrees(angle_rad))


class Measurements:
    """
    Manager for all measurements in an MPR view.
    
    Handles creation, deletion, and visualization of measurements.
    
    Example:
        >>> meas = Measurements(renderer)
        >>> dist = meas.add_distance((0, 0, 0), (10, 0, 0))
        >>> print(f"Distance: {dist.distance} mm")
    """
    
    def __init__(self, renderer: vtk.vtkRenderer):
        """
        Initialize measurements manager.
        
        Args:
            renderer: VTK renderer to add measurement visuals to
        """
        self._renderer = renderer
        
        # Storage for measurements
        self._distances: Dict[str, DistanceMeasurement] = {}
        self._angles: Dict[str, AngleMeasurement] = {}
        
        # VTK actors for visualization
        self._actors: Dict[str, List[vtk.vtkActor]] = {}
        
        # Style configuration
        self._line_color = (1.0, 1.0, 0.0)  # Yellow
        self._line_width = 2.0
        self._text_color = (1.0, 1.0, 0.0)
        self._font_size = 14
        
        # Callbacks
        self._measurement_callbacks: List[Callable] = []
        
        logger.debug("Measurements manager initialized")
    
    def add_distance(
        self,
        point1: Tuple[float, float, float],
        point2: Tuple[float, float, float]
    ) -> DistanceMeasurement:
        """
        Add a distance measurement.
        
        Args:
            point1: First point
            point2: Second point
        
        Returns:
            Created DistanceMeasurement
        """
        measurement = DistanceMeasurement(point1, point2)
        self._distances[measurement.id] = measurement
        
        # Create visualization
        self._create_distance_visual(measurement)
        
        # Notify callbacks
        self._notify_callbacks("add", measurement)
        
        logger.info(f"Distance added: {measurement.distance:.2f} mm")
        
        return measurement
    
    def add_angle(
        self,
        vertex: Tuple[float, float, float],
        point1: Tuple[float, float, float],
        point2: Tuple[float, float, float]
    ) -> AngleMeasurement:
        """
        Add an angle measurement.
        
        Args:
            vertex: Vertex point (angle measured here)
            point1: First arm endpoint
            point2: Second arm endpoint
        
        Returns:
            Created AngleMeasurement
        """
        measurement = AngleMeasurement(vertex, point1, point2)
        self._angles[measurement.id] = measurement
        
        # Create visualization
        self._create_angle_visual(measurement)
        
        # Notify callbacks
        self._notify_callbacks("add", measurement)
        
        logger.info(f"Angle added: {measurement.angle:.1f}°")
        
        return measurement
    
    def _create_distance_visual(self, measurement: DistanceMeasurement):
        """Create VTK actors for distance measurement."""
        actors = []
        
        # Create line
        line = vtk.vtkLineSource()
        line.SetPoint1(measurement.point1)
        line.SetPoint2(measurement.point2)
        
        line_mapper = vtk.vtkPolyDataMapper()
        line_mapper.SetInputConnection(line.GetOutputPort())
        
        line_actor = vtk.vtkActor()
        line_actor.SetMapper(line_mapper)
        line_actor.GetProperty().SetColor(*self._line_color)
        line_actor.GetProperty().SetLineWidth(self._line_width)
        
        self._renderer.AddActor(line_actor)
        actors.append(line_actor)
        
        # Create endpoint markers (small spheres)
        for point in [measurement.point1, measurement.point2]:
            sphere = vtk.vtkSphereSource()
            sphere.SetCenter(point)
            sphere.SetRadius(1.0)
            
            sphere_mapper = vtk.vtkPolyDataMapper()
            sphere_mapper.SetInputConnection(sphere.GetOutputPort())
            
            sphere_actor = vtk.vtkActor()
            sphere_actor.SetMapper(sphere_mapper)
            sphere_actor.GetProperty().SetColor(*self._line_color)
            
            self._renderer.AddActor(sphere_actor)
            actors.append(sphere_actor)
        
        # Create text label
        midpoint = [
            (measurement.point1[i] + measurement.point2[i]) / 2
            for i in range(3)
        ]
        
        text_actor = vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(f"{measurement.distance:.1f} mm")
        text_actor.SetPosition(*midpoint)
        text_actor.GetTextProperty().SetFontSize(self._font_size)
        text_actor.GetTextProperty().SetColor(*self._text_color)
        text_actor.GetTextProperty().SetBold(True)
        
        self._renderer.AddActor(text_actor)
        actors.append(text_actor)
        
        self._actors[measurement.id] = actors
    
    def _create_angle_visual(self, measurement: AngleMeasurement):
        """Create VTK actors for angle measurement."""
        actors = []
        
        # Create two lines from vertex to points
        for point in [measurement.point1, measurement.point2]:
            line = vtk.vtkLineSource()
            line.SetPoint1(measurement.vertex)
            line.SetPoint2(point)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(line.GetOutputPort())
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*self._line_color)
            actor.GetProperty().SetLineWidth(self._line_width)
            
            self._renderer.AddActor(actor)
            actors.append(actor)
        
        # Create arc to show angle
        arc = self._create_angle_arc(measurement)
        if arc:
            arc_mapper = vtk.vtkPolyDataMapper()
            arc_mapper.SetInputConnection(arc.GetOutputPort())
            
            arc_actor = vtk.vtkActor()
            arc_actor.SetMapper(arc_mapper)
            arc_actor.GetProperty().SetColor(*self._line_color)
            
            self._renderer.AddActor(arc_actor)
            actors.append(arc_actor)
        
        # Create text label
        text_actor = vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(f"{measurement.angle:.1f}°")
        text_actor.SetPosition(*measurement.vertex)
        text_actor.GetTextProperty().SetFontSize(self._font_size)
        text_actor.GetTextProperty().SetColor(*self._text_color)
        text_actor.GetTextProperty().SetBold(True)
        
        self._renderer.AddActor(text_actor)
        actors.append(text_actor)
        
        self._actors[measurement.id] = actors
    
    def _create_angle_arc(
        self,
        measurement: AngleMeasurement
    ) -> Optional[vtk.vtkArcSource]:
        """Create arc source for angle visualization."""
        try:
            arc = vtk.vtkArcSource()
            arc.SetCenter(measurement.vertex)
            arc.SetPoint1(measurement.point1)
            arc.SetPoint2(measurement.point2)
            arc.SetResolution(32)
            arc.Update()
            return arc
        except Exception as e:
            logger.warning(f"Could not create angle arc: {e}")
            return None
    
    def remove_measurement(self, measurement_id: str):
        """
        Remove a measurement by ID.
        
        Args:
            measurement_id: ID of measurement to remove
        """
        # Remove from storage
        if measurement_id in self._distances:
            measurement = self._distances.pop(measurement_id)
        elif measurement_id in self._angles:
            measurement = self._angles.pop(measurement_id)
        else:
            logger.warning(f"Measurement not found: {measurement_id}")
            return
        
        # Remove actors
        if measurement_id in self._actors:
            for actor in self._actors[measurement_id]:
                self._renderer.RemoveActor(actor)
            del self._actors[measurement_id]
        
        # Notify callbacks
        self._notify_callbacks("remove", measurement)
        
        logger.info(f"Measurement removed: {measurement_id}")
    
    def clear_all(self):
        """Remove all measurements."""
        # Get all IDs
        all_ids = list(self._distances.keys()) + list(self._angles.keys())
        
        # Remove each
        for mid in all_ids:
            self.remove_measurement(mid)
        
        logger.info("All measurements cleared")
    
    def set_visible(self, visible: bool):
        """
        Set visibility of all measurements.
        
        Args:
            visible: Whether measurements should be visible
        """
        for actors in self._actors.values():
            for actor in actors:
                if visible:
                    actor.VisibilityOn()
                else:
                    actor.VisibilityOff()
    
    def get_all_distances(self) -> List[DistanceMeasurement]:
        """Get all distance measurements."""
        return list(self._distances.values())
    
    def get_all_angles(self) -> List[AngleMeasurement]:
        """Get all angle measurements."""
        return list(self._angles.values())
    
    def add_callback(self, callback: Callable):
        """
        Add callback for measurement events.
        
        Args:
            callback: Function(action: str, measurement) to call
        """
        self._measurement_callbacks.append(callback)
    
    def _notify_callbacks(self, action: str, measurement):
        """Notify all callbacks."""
        for callback in self._measurement_callbacks:
            try:
                callback(action, measurement)
            except Exception as e:
                logger.warning(f"Callback error: {e}")
    
    def set_style(
        self,
        line_color: Optional[Tuple[float, float, float]] = None,
        line_width: Optional[float] = None,
        text_color: Optional[Tuple[float, float, float]] = None,
        font_size: Optional[int] = None
    ):
        """
        Set visual style for measurements.
        
        Args:
            line_color: RGB color for lines (0-1)
            line_width: Width of lines
            text_color: RGB color for text
            font_size: Font size for labels
        """
        if line_color:
            self._line_color = line_color
        if line_width:
            self._line_width = line_width
        if text_color:
            self._text_color = text_color
        if font_size:
            self._font_size = font_size
