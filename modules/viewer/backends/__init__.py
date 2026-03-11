"""Backward-compatibility shim — backends moved to ``viewers.pydicom``."""

from modules.viewer.fast.contracts import (
    FrameData,
    GeometryData,
    IViewer2DBackend,
)
from modules.viewer.fast.pydicom_2d_backend import (
    PyDicom2DBackend,
)

__all__ = [
    "FrameData",
    "GeometryData",
    "IViewer2DBackend",
    "PyDicom2DBackend",
]

