"""Backward-compat shim — actual code is in vtk_widget/ package.

All external imports of ``widget_viewer.VTKWidget`` or
``widget_viewer.grow_vtk_inplace`` continue to work unchanged.

Set env var  AIPACS_VTK_LEGACY=1  before launch to use the monolithic
v2.3.0 VTKWidget for A/B comparison testing.
"""
import os as _os

if _os.environ.get("AIPACS_VTK_LEGACY") == "1":
    # ── legacy monolithic class (v2.3.0 backup) ──
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._legacy_widget import *  # noqa: F401,F403
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._legacy_widget import (  # noqa: F401
        VTKWidget,
        grow_vtk_inplace,
        register_download_subprocess,
        unregister_download_subprocess,
        _create_qt_viewer_bridge,
        _throttle_background_threads,
        _nt_suspend_download_subprocesses,
        _nt_resume_download_subprocesses,
        _active_download_pids,
        _RENDER_THROTTLE_MS,
        _SPINNER_HIDE_DELAY_MS,
        _SYNC_MOVE_THROTTLE_MS,
        _DROP_HOVER_ARM_MS,
        _DROP_DWELL_MOVE_TOLERANCE_PX,
        _SERIES_DROP_MIME,
    )
    print("[A/B] VTKWidget: LEGACY monolithic (v2.3.0)")
else:
    # ── refactored mixin-based class ──
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import *  # noqa: F401,F403
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import (  # noqa: F401
        VTKWidget,
        grow_vtk_inplace,
        register_download_subprocess,
        unregister_download_subprocess,
        _create_qt_viewer_bridge,
    )
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (  # noqa: F401
        _throttle_background_threads,
        _nt_suspend_download_subprocesses,
        _nt_resume_download_subprocesses,
        _active_download_pids,
        _RENDER_THROTTLE_MS,
        _SPINNER_HIDE_DELAY_MS,
        _SYNC_MOVE_THROTTLE_MS,
        _DROP_HOVER_ARM_MS,
        _DROP_DWELL_MOVE_TOLERANCE_PX,
        _SERIES_DROP_MIME,
    )
    print("[A/B] VTKWidget: MIXIN refactored (current)")
