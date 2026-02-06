"""
Zeta Sync module

Centralized synchronization utilities for linking cursor/position between viewers
(e.g., MPR↔MPR, MPR↔2D, 2D↔2D) without embedding sync logic in viewers themselves.
"""

from .sync_manager import SyncManager
from .sync_context import SyncContext
from .sync_types import SyncMode, SyncTarget
from .geometry_utils import (
    map_ijk_between_vtk_images,
    build_ijk_to_world_matrix,
    world_to_ijk,
    ijk_to_world,
    is_ijk_in_bounds,
    log_image_orientation,
)

__all__ = [
    "SyncManager",
    "SyncContext",
    "SyncMode",
    "SyncTarget",
    "map_ijk_between_vtk_images",
    "build_ijk_to_world_matrix",
    "world_to_ijk",
    "ijk_to_world",
    "is_ijk_in_bounds",
    "log_image_orientation",
]
