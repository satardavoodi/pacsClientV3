"""Unified viewport capture — one Screenshot action across viewer modules.

``capture_active_viewport()`` is the single routing point ("CaptureActiveViewport"):
the active module determines which rendering surface is actually visible and the
capture is taken from that surface, so the user always gets exactly what is on
screen.

Routing today:
  - Zeta MPR / Curve MPR replacing a 2D viewport  -> OpenGL-safe screen grab of
    the visible MPR widget (all panes: axial/sagittal/coronal/VRT, crosshairs,
    captions — exactly as displayed).
  - Plain 2D viewing (Advanced VTK or FAST Qt)    -> returns ``None`` so the
    caller keeps its legacy capture path BYTE-IDENTICAL (vtkWindowToImageFilter
    for Advanced, QWidget.grab for FAST). No regression to the existing 2D
    screenshot workflow.
  - EagleEye / future modules call ``capture_widget_to_attachments()`` (or
    ``grab_widget_pixmap()`` for clipboard / save-as flows) directly on their
    visible viewer surface.

Implementation notes:
  - The screen grab uses ``QScreen.grabWindow`` on the TOP-LEVEL window handle
    restricted to the target widget's rect — the same OpenGL-safe technique
    already proven by the toolbar's "Total Layouts" capture — so VTK GL panes
    are captured as rendered. ``QWidget.grab()`` (software paint) is only a
    fallback.
  - This module never instantiates VTK objects or render windows (FAST-safe).
  - PacsClient imports are deferred to call time to avoid import cycles and to
    keep the plugin payload import-light.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Attributes a 2D viewport widget may carry when an MPR surface has visibly
# replaced it (kept in sync with ToolbarManager.get_mpr_widget / is_mpr_viewer).
_MPR_HOST_ATTRS = (
    '_zeta_mpr_widget',
    '_new_mpr_zeta_widget',
    '_curve_mpr_widget',
    '_mpr_widget',
)


def _is_alive_and_visible(widget) -> bool:
    """True if the Qt widget is a live (non-deleted) object currently visible."""
    if widget is None:
        return False
    try:
        import shiboken6
        if not shiboken6.isValid(widget):
            return False
    except Exception:
        pass  # shiboken unavailable — fall through to duck checks
    try:
        return bool(widget.isVisible())
    except Exception:
        return False


def resolve_active_mpr_widget(selected_widget, patient_widget=None):
    """Return the visible MPR widget that replaced a 2D viewport, else ``None``.

    Checks the selected widget (and its ``vtk_widget``) for the known MPR host
    attributes first; if the selection does not carry one, scans the viewer
    grid nodes — an open MPR occupies the viewport, so the user is looking at
    it even when the logical selection still points at the hidden 2D widget.
    """
    candidates = []

    hosts = [selected_widget]
    inner = getattr(selected_widget, 'vtk_widget', None)
    if inner is not None and inner is not selected_widget:
        hosts.append(inner)

    for host in hosts:
        if host is None:
            continue
        # The selection may BE the MPR widget itself (it carries _original_widget).
        if getattr(host, '_original_widget', None) is not None:
            candidates.append(host)
        for attr in _MPR_HOST_ATTRS:
            w = getattr(host, attr, None)
            if w is not None:
                candidates.append(w)

    if not candidates and patient_widget is not None:
        try:
            nodes = list(getattr(patient_widget, 'lst_nodes_viewer', []) or [])
        except Exception:
            nodes = []
        for node in nodes:
            host = getattr(node, 'vtk_widget', None)
            if host is None:
                continue
            for attr in _MPR_HOST_ATTRS:
                w = getattr(host, attr, None)
                if w is not None:
                    candidates.append(w)

    for widget in candidates:
        if _is_alive_and_visible(widget):
            return widget
    return None


def grab_widget_pixmap(widget):
    """OpenGL-safe grab of exactly what ``widget`` currently shows on screen.

    Grabs the screen region through the widget's TOP-LEVEL window handle (no
    native-handle forcing on the target itself), so VTK/OpenGL child panes are
    captured as displayed. Falls back to ``QWidget.grab()`` if the screen grab
    fails. Returns a ``QPixmap`` or ``None``.
    """
    if widget is None:
        return None

    pixmap = None
    try:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication

        window = widget.window()
        handle = window.windowHandle() if window is not None else None
        screen = handle.screen() if handle is not None else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None and window is not None:
            top_left = widget.mapTo(window, QPoint(0, 0))
            pixmap = screen.grabWindow(
                int(window.winId()),
                int(top_left.x()), int(top_left.y()),
                int(widget.width()), int(widget.height()),
            )
    except Exception as exc:
        logger.warning(
            "viewport_capture: screen grab failed (%s); falling back to widget.grab()", exc
        )
        pixmap = None

    if pixmap is None or pixmap.isNull():
        try:
            pixmap = widget.grab()
        except Exception:
            return None
    if pixmap is None or pixmap.isNull():
        return None
    return pixmap


def save_pixmap_to_attachments(pixmap, study_uid=None):
    """Save a pixmap as PNG into the study's attachment folder.

    Same destination as every other capture path (interactor-style capture,
    FAST capture, Total Layouts), so captures appear in the existing
    "View Captured Images" gallery. Returns the file path or ``None``.
    """
    if pixmap is None or pixmap.isNull():
        return None
    try:
        from PacsClient.pacs.patient_tab.utils import (
            create_attachment_folder,
            create_random_string,
        )
        if not study_uid:
            import random
            study_uid = str(random.randint(10000, 100000))
        folder_path = create_attachment_folder(study_uid)
        file_path = f'{folder_path}/{create_random_string()}.png'
        if pixmap.save(file_path, 'PNG'):
            return file_path
    except Exception as exc:
        logger.error("viewport_capture: failed to save capture: %s", exc)
    return None


def capture_widget_to_attachments(widget, study_uid=None):
    """Grab ``widget`` as shown on screen and save it to the attachment folder."""
    if widget is None:
        return None
    try:
        widget.repaint()  # flush pending Qt paints before reading the screen
    except Exception:
        pass
    return save_pixmap_to_attachments(grab_widget_pixmap(widget), study_uid)


def capture_active_viewport(patient_widget, selected_widget=None):
    """CaptureActiveViewport(): route Screenshot to the visible rendering surface.

    Returns the saved file path when an advanced surface (Zeta/Curve MPR) was
    visibly replacing the 2D viewport and was captured. Returns ``None`` when
    plain 2D viewing is active — the caller must then run its legacy 2D capture
    path unchanged (Advanced vtkWindowToImageFilter / FAST QWidget.grab).
    """
    if selected_widget is None:
        selected_widget = getattr(patient_widget, 'selected_widget', None)

    mpr_widget = resolve_active_mpr_widget(selected_widget, patient_widget)
    if mpr_widget is None:
        return None

    study_uid = getattr(patient_widget, 'study_uid', None)
    path = capture_widget_to_attachments(mpr_widget, study_uid)
    if path:
        logger.info("viewport_capture: MPR viewport captured -> %s", path)
    else:
        logger.warning("viewport_capture: MPR surface found but capture failed")
    return path
