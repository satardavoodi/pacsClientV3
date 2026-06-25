# -*- coding: utf-8 -*-
"""Dental Imaging shared core — volume binding + geometry.

Reuse, never duplicate: this layer turns the active series into a handle over the
SHARED ``vtk_image_data`` (single source of truth for the volume coordinate
system + geometry). Import-light and Qt/VTK-free — it operates on the existing
shared volume object rather than building its own.
"""
from .volume import DentalVolume
from .volume_binder import (
    bind_active_viewer_volume,
    get_active_image_data,
    materialize_lazy_volume,
)

__all__ = [
    "DentalVolume",
    "bind_active_viewer_volume",
    "get_active_image_data",
    "materialize_lazy_volume",
]
