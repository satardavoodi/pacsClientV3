# -*- coding: utf-8 -*-
"""Dental Imaging — full professional dental CBCT workspace (Advanced Analysis level).

This package is the **PROFESSIONAL** level of the two-level dental architecture:

  • Patient-Tab **"Dental Curve MPR"** (opened from the MPR dropdown inside the
    2D viewer) = the **lightweight** viewer mode (simple panoramic-style view +
    simple ruler). It lives under ``modules/mpr/...`` and is a *separate* thing —
    this package must NEVER be imported into it, and must not bloat it.

  • **This module** = the **full** dental workspace, opened as a dedicated pop-up
    from the Patient Viewer's **Advanced Analysis** area (beside Advanced MPR /
    Stitching). Home for the future professional dental workflow: panoramic
    reconstruction, curved MPR, cross-sections, arch-curve editing, nerve tracing,
    measurements, segmentation, AI tools, case planning.

Architecture rules (see README.md):
  • Reuse the SHARED volume / geometry / MPR infrastructure — never duplicate
    geometry or fork a separate volume pipeline. The active series arrives as a
    pure ``DentalSeriesContext`` handle; later milestones build the volume via the
    shared ``modules/viewer/fast/pydicom_lazy_volume.py::PyDicomLazyVolume`` + the
    standard-MPR geometry contract.
  • Flag-gated (``AIPACS_DENTAL_IMAGING``, default on) so it is purely additive and
    trivially reversible.

Import-light by design: importing this package pulls in only stdlib + the pure
``DentalSeriesContext``. Qt / VTK are imported lazily (only when the workspace is
actually opened), so the Patient Viewer can check the flag and build the context
cheaply at startup.
"""
from __future__ import annotations

import os

from .context import DentalSeriesContext

__all__ = [
    "DentalSeriesContext",
    "dental_imaging_enabled",
    "open_dental_imaging_workspace",
    "FLAG_ENV",
]

#: Environment kill-switch. Default ON; set to "0" to hide the Advanced-Analysis
#: entry and disable the launcher (purely additive — disabling leaves every
#: existing flow byte-identical).
FLAG_ENV = "AIPACS_DENTAL_IMAGING"


def dental_imaging_enabled() -> bool:
    """Whether the Advanced-Analysis 'Dental Imaging' entry/module is available."""
    return os.environ.get(FLAG_ENV, "1") != "0"


def open_dental_imaging_workspace(parent=None, context: "DentalSeriesContext | None" = None,
                                  volume=None, resolver=None):
    """Open (or re-use) the Dental Imaging workspace pop-up and load ``context``.

    ``volume`` is an optional ``core.DentalVolume`` handle over the shared
    ``vtk_image_data`` bound from the active viewer. ``resolver(series_number)`` lets
    the workspace re-resolve + reload a dropped series via the existing pipeline.
    Lazy wrapper so importing this package does NOT pull in Qt/VTK. Returns the
    workspace window, or ``None`` if the module is disabled by its flag.
    """
    if not dental_imaging_enabled():
        return None
    from .launcher import open_dental_imaging_workspace as _open
    return _open(parent=parent, context=context, volume=volume, resolver=resolver)
