"""PyDicom fast-viewer subpackage.

Contains the pydicom-based lazy 2-D backend, shared lazy volume, lightweight
Qt pipeline, and supporting utilities (registry, contracts, stale-frame guard).
"""

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
