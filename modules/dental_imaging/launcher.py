# -*- coding: utf-8 -*-
"""Singleton launcher for the Dental Imaging workspace.

Mirrors ``modules/stitching/stitching_widget.py::get_stitching_widget`` — one
re-used top-level window per session. Qt/VTK-light: the workspace class (which
imports PySide6) is only imported when this is actually called.
"""
from __future__ import annotations

from typing import Optional

from .context import DentalSeriesContext

_workspace_instance = None  # type: ignore[var-annotated]


def _is_alive(widget) -> bool:
    """True if the Python ref still wraps a live Qt object."""
    if widget is None:
        return False
    try:
        # Touching a deleted QWidget raises RuntimeError ("already deleted").
        widget.isVisible()
        return True
    except RuntimeError:
        return False


def get_dental_imaging_workspace(parent=None):
    """Return the singleton workspace window, creating it if needed."""
    global _workspace_instance
    from .workspace import DentalImagingWorkspace

    if not _is_alive(_workspace_instance):
        _workspace_instance = DentalImagingWorkspace(parent)
    return _workspace_instance


def open_dental_imaging_workspace(parent=None, context: Optional[DentalSeriesContext] = None,
                                  volume=None, resolver=None):
    """Create/raise the workspace pop-up and load ``context`` (+ bound ``volume``).

    ``volume`` is a ``core.DentalVolume`` handle over the shared ``vtk_image_data``
    (reused from the active viewer); passing ``None`` simply shows the shell.
    ``resolver(series_number)`` (optional) lets the workspace re-resolve + reload a
    series dropped onto it, reusing the Patient-Viewer series pipeline.
    """
    ws = get_dental_imaging_workspace(parent)
    if resolver is not None:
        ws.set_series_resolver(resolver)
    ws.load_series(context, volume)
    ws.show()
    ws.raise_()
    ws.activateWindow()
    return ws
