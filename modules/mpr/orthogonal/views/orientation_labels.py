"""
Orientation Labels - Anatomical direction indicators for MPR views

Displays anatomical direction labels (R/L, A/P, S/I) around the edges
of MPR views to help users understand the orientation of the displayed slice.

Labels follow the DICOM LPS convention:
- L/R: Left/Right (X axis)
- A/P: Anterior/Posterior (Y axis)
- S/I: Superior/Inferior (Z axis)
"""

import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import vtkmodules.all as vtk

from ..core.mpr_calculator import PlaneType

logger = logging.getLogger(__name__)


class LabelPosition(Enum):
    """Position of orientation label around the view."""
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


@dataclass
class LabelStyle:
    """Style configuration for orientation labels."""
    font_size: int = 16
    color: Tuple[float, float, float] = (0.9, 0.9, 0.0)  # Yellow
    bold: bool = True
    shadow: bool = True
    font_family: str = "Arial"


# Standard orientation labels for each plane in LPS convention
PLANE_LABELS: Dict[PlaneType, Dict[LabelPosition, str]] = {
    PlaneType.AXIAL: {
        LabelPosition.LEFT: "R",    # Right side of patient
        LabelPosition.RIGHT: "L",   # Left side of patient
        LabelPosition.TOP: "A",     # Anterior
        LabelPosition.BOTTOM: "P",  # Posterior
    },
    PlaneType.SAGITTAL: {
        LabelPosition.LEFT: "A",    # Anterior
        LabelPosition.RIGHT: "P",   # Posterior
        LabelPosition.TOP: "S",     # Superior
        LabelPosition.BOTTOM: "I",  # Inferior
    },
    PlaneType.CORONAL: {
        LabelPosition.LEFT: "R",    # Right
        LabelPosition.RIGHT: "L",   # Left
        LabelPosition.TOP: "S",     # Superior
        LabelPosition.BOTTOM: "I",  # Inferior
    },
}

# Viewport positions for labels (normalized coordinates)
LABEL_POSITIONS: Dict[LabelPosition, Tuple[float, float]] = {
    LabelPosition.LEFT: (0.02, 0.5),
    LabelPosition.RIGHT: (0.95, 0.5),
    LabelPosition.TOP: (0.5, 0.92),
    LabelPosition.BOTTOM: (0.5, 0.05),
}


class OrientationLabels:
    """
    Manages orientation labels for an MPR view.
    
    Creates and manages VTK text actors that display anatomical
    direction labels around the edges of the view.
    
    Example:
        >>> labels = OrientationLabels(PlaneType.AXIAL)
        >>> labels.add_to_renderer(renderer)
        >>> labels.set_visible(True)
    """
    
    def __init__(
        self,
        plane_type: PlaneType,
        style: Optional[LabelStyle] = None
    ):
        """
        Initialize orientation labels.
        
        Args:
            plane_type: Type of anatomical plane
            style: Optional label style configuration
        """
        self.plane_type = plane_type
        self.style = style or LabelStyle()
        
        # VTK text actors for each label
        self._actors: Dict[LabelPosition, vtk.vtkTextActor] = {}
        self._visible = True
        
        # Create label actors
        self._create_actors()
        
        logger.debug(f"OrientationLabels created for {plane_type.value}")
    
    def _create_actors(self):
        """Create VTK text actors for all label positions."""
        labels = PLANE_LABELS.get(self.plane_type, {})
        
        for position in LabelPosition:
            label_text = labels.get(position, "")
            viewport_pos = LABEL_POSITIONS[position]
            
            actor = self._create_text_actor(label_text, viewport_pos)
            self._actors[position] = actor
    
    def _create_text_actor(
        self,
        text: str,
        position: Tuple[float, float]
    ) -> vtk.vtkTextActor:
        """
        Create a single text actor.
        
        Args:
            text: Label text
            position: Normalized viewport position (x, y)
        
        Returns:
            Configured vtkTextActor
        """
        actor = vtk.vtkTextActor()
        actor.SetInput(text)
        
        # Position in normalized viewport coordinates
        actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        actor.GetPositionCoordinate().SetValue(position[0], position[1])
        
        # Text properties
        prop = actor.GetTextProperty()
        prop.SetFontSize(self.style.font_size)
        prop.SetColor(*self.style.color)
        prop.SetBold(self.style.bold)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        
        if self.style.shadow:
            prop.SetShadow(1)
        
        # Set font family
        if self.style.font_family.lower() == "arial":
            prop.SetFontFamilyToArial()
        elif self.style.font_family.lower() == "courier":
            prop.SetFontFamilyToCourier()
        elif self.style.font_family.lower() == "times":
            prop.SetFontFamilyToTimes()
        
        return actor
    
    def add_to_renderer(self, renderer: vtk.vtkRenderer):
        """
        Add all label actors to a renderer.
        
        Args:
            renderer: VTK renderer to add labels to
        """
        for actor in self._actors.values():
            renderer.AddActor(actor)
    
    def remove_from_renderer(self, renderer: vtk.vtkRenderer):
        """
        Remove all label actors from a renderer.
        
        Args:
            renderer: VTK renderer to remove labels from
        """
        for actor in self._actors.values():
            renderer.RemoveActor(actor)
    
    def set_visible(self, visible: bool):
        """
        Set visibility of all labels.
        
        Args:
            visible: Whether labels should be visible
        """
        self._visible = visible
        
        for actor in self._actors.values():
            if visible:
                actor.VisibilityOn()
            else:
                actor.VisibilityOff()
    
    def get_visible(self) -> bool:
        """Get current visibility state."""
        return self._visible
    
    def set_style(self, style: LabelStyle):
        """
        Update label style.
        
        Args:
            style: New label style
        """
        self.style = style
        
        for actor in self._actors.values():
            prop = actor.GetTextProperty()
            prop.SetFontSize(style.font_size)
            prop.SetColor(*style.color)
            prop.SetBold(style.bold)
            prop.SetShadow(1 if style.shadow else 0)
    
    def set_color(self, color: Tuple[float, float, float]):
        """
        Set label color.
        
        Args:
            color: RGB color tuple (0-1 range)
        """
        self.style.color = color
        
        for actor in self._actors.values():
            actor.GetTextProperty().SetColor(*color)
    
    def get_actor(self, position: LabelPosition) -> Optional[vtk.vtkTextActor]:
        """
        Get actor for a specific label position.
        
        Args:
            position: Label position
        
        Returns:
            VTK text actor or None
        """
        return self._actors.get(position)
    
    @property
    def actors(self) -> Dict[LabelPosition, vtk.vtkTextActor]:
        """Get all label actors."""
        return self._actors.copy()


def get_orientation_string(plane_type: PlaneType) -> str:
    """
    Get a human-readable orientation string.
    
    Args:
        plane_type: Type of plane
    
    Returns:
        String like "Axial (L-R, A-P)"
    """
    labels = PLANE_LABELS.get(plane_type, {})
    
    horizontal = f"{labels.get(LabelPosition.LEFT, '')}←→{labels.get(LabelPosition.RIGHT, '')}"
    vertical = f"{labels.get(LabelPosition.TOP, '')}↑↓{labels.get(LabelPosition.BOTTOM, '')}"
    
    return f"{plane_type.value.capitalize()} ({horizontal}, {vertical})"
