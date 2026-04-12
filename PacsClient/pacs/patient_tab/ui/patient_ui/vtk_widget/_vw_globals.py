import ctypes
import time
import logging
import os
import threading
import sys

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from modules.viewer.interactor_styles import AbstractInteractorStyle
from modules.viewer.advanced.viewer_2d import ImageViewer2D, CustomCombineImageViewers
from modules.viewer.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.ui.patient_ui.viewer_isolation_guard import ViewerIsolationGuard
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor, QPainter, QPixmap, QColor
import gc  # For manual garbage collection
from PacsClient.pacs.patient_tab.utils import read_segment_nifti
import vtkmodules.all as vtk
from PySide6.QtWidgets import QApplication, QLabel
from modules.viewer.fast.lazy_volume_registry import (
    acquire_loader,
    release_loader,
)
from modules.viewer.fast.stale_frame_guard import (
    should_render_ready_slice,
)
from modules.viewer.viewer_backend_config import (
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    BACKEND_VTK,
    load_viewer_backend,
    resolve_viewer_backend,
)
from modules.viewer.gpu_boost import resolve_gpu_boost_plan
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing

# ظ¤ظ¤ Qt-based 2D viewer (lazy import to avoid circular/startup overhead) ظ¤ظ¤
def _create_qt_viewer_bridge(vtk_widget, metadata, metadata_fixed):
    """Factory: create QtViewerBridge + pipeline + viewer for Qt backend."""
    from modules.viewer.fast.lightweight_2d_pipeline import (
        Lightweight2DPipeline,
        PipelineConfig,
    )
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    config = PipelineConfig()
    pipeline = Lightweight2DPipeline(config=config)

    # Open series from metadata
    series_path = ""
    if metadata and metadata.get("instances"):
        instances = metadata["instances"]
        if instances:
            from pathlib import Path
            first_path = str(instances[0].get("instance_path", ""))
            if first_path:
                series_path = str(Path(first_path).parent)
    pipeline.open_series(series_path, metadata=metadata)

    # Create the Qt viewer widget as a child of the VTK widget
    qt_viewer = QtSliceViewer(parent=vtk_widget)
    qt_viewer.setGeometry(vtk_widget.rect())

    bridge = QtViewerBridge(
        qt_viewer=qt_viewer,
        pipeline=pipeline,
        metadata=metadata,
        metadata_fixed=metadata_fixed,
        vtk_widget=vtk_widget,
    )

    return bridge, qt_viewer

logger = logging.getLogger(__name__)

# =====================================================
# ANTI-FLICKER CONSTANTS
# =====================================================
# v2.2.3.8.0: Background-thread priority throttle during scroll.
_THROTTLE_KEYWORDS = (
    'download', 'zeta', 'filter', 'prefetch', 'warmup',
    'network', 'socket', 'deferredfilter', 'imgboost', 'asyncswitchload',
)


def _throttle_background_threads(throttle: bool) -> None:
    if sys.platform != 'win32':
        return
    priority = -15 if throttle else 0
    main_tid = threading.main_thread().ident
    desired = 0x0020 | 0x0040
    for t in threading.enumerate():
        tid = t.ident
        if tid is None or tid == main_tid:
            continue
        name = (t.name or '').lower()
        if not any(kw in name for kw in _THROTTLE_KEYWORDS):
            continue
        try:
            handle = ctypes.windll.kernel32.OpenThread(desired, False, tid)
            if handle:
                ctypes.windll.kernel32.SetThreadPriority(handle, priority)
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


_active_download_pids: set = set()


def register_download_subprocess(pid: int) -> None:
    _active_download_pids.add(pid)


def unregister_download_subprocess(pid: int) -> None:
    _active_download_pids.discard(pid)


def _nt_suspend_download_subprocesses() -> None:
    if sys.platform != 'win32' or not _active_download_pids:
        return
    desired = 0x0800
    for pid in list(_active_download_pids):
        try:
            handle = ctypes.windll.kernel32.OpenProcess(desired, False, pid)
            if handle:
                ctypes.windll.ntdll.NtSuspendProcess(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


def _nt_resume_download_subprocesses() -> None:
    if sys.platform != 'win32' or not _active_download_pids:
        return
    desired = 0x0800
    for pid in list(_active_download_pids):
        try:
            handle = ctypes.windll.kernel32.OpenProcess(desired, False, pid)
            if handle:
                ctypes.windll.ntdll.NtResumeProcess(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass

_RENDER_THROTTLE_MS = 16  # ~60fps max render rate
_SPINNER_HIDE_DELAY_MS = 50  # Delay before hiding spinner to allow final render
_SYNC_MOVE_THROTTLE_MS = 16  # min interval between sync mouse move processing (~60fps)

_DROP_HOVER_ARM_MS = max(0, int(os.getenv("AIPACS_DROP_HOVER_ARM_MS", "120") or "120"))
_DROP_DWELL_MOVE_TOLERANCE_PX = max(1, int(os.getenv("AIPACS_DROP_DWELL_MOVE_TOLERANCE_PX", "8") or "8"))
_SERIES_DROP_MIME = "application/x-aipacs-series-number"


def grow_vtk_inplace(old_input, new_vtk_image_data):
    # Old/new dimensions
    ox, oy, oz = old_input.GetDimensions()
    nx, ny, nz = new_vtk_image_data.GetDimensions()

    # If nothing was added, just mark as Modified
    if (nx <= ox and ny <= oy and nz <= oz):
        old_input.Modified()
        return False

    # 2) XY must remain unchanged; otherwise avoid memory corruption
    if (ox, oy) != (nx, ny):
        # If XY changed, reject for now to avoid crashes/heavy memory use
        # (A safer path can be implemented if needed)
        return False

    # 3) Update spacing/origin only when changed
    if old_input.GetSpacing() != new_vtk_image_data.GetSpacing():
        old_input.SetSpacing(new_vtk_image_data.GetSpacing())
    if old_input.GetOrigin() != new_vtk_image_data.GetOrigin():
        old_input.SetOrigin(new_vtk_image_data.GetOrigin())

    # 4) New dimensions/extent
    old_input.SetDimensions(nx, ny, nz)
    old_input.SetExtent(0, nx - 1, 0, ny - 1, 0, nz - 1)

    # 5) Lowest-cost scalar update: use SetScalars instead of DeepCopy (pointer swap)
    new_scalars = new_vtk_image_data.GetPointData().GetScalars()
    old_input.GetPointData().SetScalars(new_scalars)

    # 7) Mark as modified; no immediate Render/Update
    old_input.GetPointData().Modified()
    old_input.Modified()

    # self.image_reslice.Modified()
    # self.image_reslice.Update()      # intentionally removed
    # self.UpdateDisplayExtent()       # intentionally removed
    # self.update_corners_actors()     # intentionally removed (caller can trigger after throttle)
    # self.Render()                    # intentionally removed

    ################################################################
    # # 3) Change signal
    # old_vtk.GetPointData().Modified()
    # old_vtk.Modified()
    return True


