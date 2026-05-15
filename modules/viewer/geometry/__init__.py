"""Viewer-wide geometry contract: DICOM → SimpleITK → VTK → patient LPS.

This package provides the authoritative geometry objects that every medical
feature (markers, sync, reference lines, MPR/NPR, rotate, 3D) must use.

Submodules
----------
source_geometry   — SourceGeometry: DICOM-derived raw IJK→LPS affine authority
display_geometry  — DisplayGeometry: per-viewport display-index transforms
geometry_api      — Canonical API functions (index↔LPS, screen vectors, planes)
vtk_bridge        — Mirror geometry into VTK; log orientation bridge status
"""

from modules.viewer.geometry.source_geometry import SourceGeometry
from modules.viewer.geometry.display_geometry import DisplayGeometry
from modules.viewer.geometry.geometry_api import GeometryAPI, ViewportGeometryRegistry

__all__ = [
    "SourceGeometry",
    "DisplayGeometry",
    "GeometryAPI",
    "ViewportGeometryRegistry",
]
