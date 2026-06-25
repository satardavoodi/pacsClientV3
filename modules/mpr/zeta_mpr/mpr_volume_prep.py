"""Shared MPR volume preparation — first extracted piece of the unified MPR/3D
foundation (2026-06-22).

Replicates the radiological left-right X-flip that ``StandardMPRViewer`` applies to its
input volume (``vtkImageFlip`` on axis 0, ``FlipAboutOrigin`` off, field data preserved),
so other MPR-family modules — starting with Dental Curve MPR — can reslice the *same*
prepared volume standard MPR uses and stay in the same patient orientation (L/R).

Design:
* ``volume_center_x`` / ``mirror_point_x`` are pure (stdlib only) and unit-testable
  WITHOUT VTK.
* ``prepare_radiological_volume`` imports VTK lazily, so importing this module never
  pulls in VTK or a render window (same discipline as ``_mpr_canonicalize.py``).

Why the point mirror works: ``vtkImageFlip(SetFilteredAxis(0))`` with ``FlipAboutOrigin``
off flips the pixels but PRESERVES origin/spacing/extent (the volume occupies the same
physical bounds). So a point picked on the *unflipped* volume lands on the same anatomy
in the flipped volume after mirroring its world X about the volume's X center:
``X' = 2*center_x - X`` (Y, Z unchanged), where
``center_x = origin[0] + (dims[0]-1)*spacing[0]*0.5`` — identical to
``StandardMPRViewer.center[0]``.

NOTE: standard MPR is intentionally NOT rewired to call this yet — it stays
byte-identical (it is the working reference). This module currently serves the Dental
Curve MPR geometry-contract path (flag ``AIPACS_CURVED_MPR_GEOMETRY_CONTRACT``). A later
step can refactor ``StandardMPRViewer`` onto it to prove equivalence. See
``docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md`` and
``docs/reports/DENTAL_CURVE_MPR_VS_STANDARD_MPR_ALIGNMENT_2026-06-22.md``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def volume_center_x(vtk_image_data):
    """World-space X center of the volume.

    Equals ``origin[0] + (dims[0]-1)*spacing[0]*0.5`` — the same value
    ``StandardMPRViewer`` computes as ``center[0]``. The radiological X-flip mirrors
    world X about this value. Pure: reads geometry off the image, imports no VTK.
    """
    origin = vtk_image_data.GetOrigin()
    dims = vtk_image_data.GetDimensions()
    spacing = vtk_image_data.GetSpacing()
    return origin[0] + (dims[0] - 1) * spacing[0] * 0.5


def mirror_point_x(point, center_x):
    """Mirror a world point's X about ``center_x``: ``X' = 2*center_x - X``.

    Y and Z are unchanged. This is the world-coordinate effect of
    ``vtkImageFlip(axis=0, FlipAboutOrigin off)`` (which preserves origin/spacing/
    extent), so a point picked on the unflipped volume maps to the same anatomy in the
    flipped volume. Pure stdlib; no VTK. Self-inverse (mirroring twice returns the
    original point).
    """
    return (2.0 * center_x - point[0], point[1], point[2])


def prepare_radiological_volume(vtk_image_data):
    """Return a NEW ``vtkImageData`` with the radiological X-flip standard MPR applies.

    Replicates ``StandardMPRViewer.__init__`` exactly: ``vtkImageFlip`` with
    ``SetFilteredAxis(0)`` (left-right), then copies every field-data array
    (``DirectionMatrix`` / ``ZetaAnatA`` …) onto the flipped image so downstream
    geometry stays intact. VTK is imported lazily here (never at module import).

    Pair every call with ``mirror_point_x`` on any world points (e.g. curve control
    points) that were picked on the unflipped volume.
    """
    import vtkmodules.all as vtk  # lazy: importing this module must not pull VTK

    flip = vtk.vtkImageFlip()
    flip.SetInputData(vtk_image_data)
    flip.SetFilteredAxis(0)  # X (left-right); FlipAboutOrigin off → bounds preserved
    flip.Update()
    out = flip.GetOutput()

    field_data = vtk_image_data.GetFieldData()
    if field_data:
        for i in range(field_data.GetNumberOfArrays()):
            arr = field_data.GetArray(i)
            if arr:
                out.GetFieldData().AddArray(arr)
    return out
