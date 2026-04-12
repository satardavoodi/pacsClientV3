"""
vtk_widget package — split from widget_viewer.py (Phase 5D).

Public API:
    VTKWidget             — the main viewer widget class
    grow_vtk_inplace      — standalone VTK image grow helper
    register_download_subprocess / unregister_download_subprocess
    _create_qt_viewer_bridge
"""
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.widget import VTKWidget  # noqa: F401
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (  # noqa: F401
    grow_vtk_inplace,
    register_download_subprocess,
    unregister_download_subprocess,
    _create_qt_viewer_bridge,
)
