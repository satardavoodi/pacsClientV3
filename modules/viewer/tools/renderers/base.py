"""Abstract base for tool renderers.

Defines the protocol that any concrete renderer (QPainter, VTK, etc.)
must implement.  Also provides ``RenderContext`` — a lightweight
snapshot of the viewer state needed for coordinate conversion during
rendering.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from ..coord_resolver import CoordinateResolver
from ..enums import ToolType
from ..models import ToolModel


@dataclass(frozen=True)
class RenderContext:
    """Immutable snapshot passed to every render call.

    Parameters
    ----------
    coord : CoordinateResolver
        Widget ↔ image conversion (rotation/flip aware).
    slice_index : int
        Currently displayed slice.
    backend : optional
        Backend reference for patient-space lookups (distance_mm, etc.).
    """

    coord: CoordinateResolver
    slice_index: int
    backend: Any = None
    hovered_model: Any = None  # ToolModel currently hovered (for highlight rendering)
    hovered_handle_idx: int = -2  # Hovered handle code for active interaction rendering


class AbstractToolRenderer(ABC):
    """Protocol for rendering tool overlays."""

    @abstractmethod
    def render_tool(
        self,
        ctx: RenderContext,
        painter: Any,
        model: ToolModel,
    ) -> None:
        """Draw a completed or in-progress tool annotation.

        Parameters
        ----------
        ctx : RenderContext
            Coordinate conversion + slice info.
        painter : Any
            Backend-specific drawing surface (QPainter, vtkRenderer, etc.).
        model : ToolModel
            The annotation to draw.
        """

    @abstractmethod
    def render_preview(
        self,
        ctx: RenderContext,
        painter: Any,
        tool_type: ToolType,
        points_image: List[Tuple[float, float]],
        cursor_image: Tuple[float, float],
    ) -> None:
        """Draw a rubber-band preview for an in-progress tool.

        Parameters
        ----------
        ctx : RenderContext
            Coordinate conversion + slice info.
        painter : Any
            Drawing surface.
        tool_type : ToolType
            Which tool is being placed.
        points_image : list of (x, y)
            Already-placed points in image coordinates.
        cursor_image : (x, y)
            Current cursor position in image coordinates.
        """
