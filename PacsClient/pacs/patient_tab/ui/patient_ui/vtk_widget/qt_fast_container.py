"""
QtFastContainer — VTK-free viewer cell widget for FAST mode (BACKEND_PYDICOM_QT).

Drop-in structural replacement for VTKWidget when the viewer backend is
BACKEND_PYDICOM_QT.  VTK objects (render_window, renderer, interactor) are
replaced by ``_NullVtkObject`` stubs that absorb every method call with a
no-op and evaluate as ``False`` in boolean context.  Image display is
delegated entirely to ``QtViewerBridge`` / ``QtSliceViewer`` children.

Design constraints (see docs/plans/performance/FAST_2D_CELL_SEPARATION_PLAN.md):
  - MUST NOT create a QVTKRenderWindowInteractor — no GPU context is allocated.
  - MUST expose the same duck-type surface as VTKWidget for all call sites that
    run in FAST mode (attributes listed in plan Section 3.2).
  - MUST remain entirely invisible to Advanced/MPR/Eagle Eye paths (those paths
    keep using the real VTKWidget via the ``BACKEND_VTK`` branch in the factory).
  - start_process_series / start_process_combine_series are no-ops because the
    FAST pipeline loads series via _load_single_series_on_demand + Qt bridge.
"""
from __future__ import annotations

import logging
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt

from modules.viewer.viewer_backend_config import BACKEND_PYDICOM_QT
from modules.viewer.widgets import ViewportSpinner

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Null-object helpers
# ---------------------------------------------------------------------------

class _NullVtkObject:
    """Null object for VTK render_window / renderer / interactor in FAST mode.

    Every attribute access returns a callable that ignores all arguments and
    returns ``None``.  Boolean evaluation is ``False`` so call sites that do::

        if vtk_widget.render_window:
            vtk_widget.render_window.Render()

    … skip the body entirely, which is the correct behaviour for FAST mode.
    """

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None

    def __bool__(self) -> bool:
        return False

    # Make the object itself callable, for any stray `self.render_window()` patterns.
    def __call__(self, *args, **kwargs):
        return None


class _NullImageViewer:
    """Minimal stub for ``vtk_widget.image_viewer`` in FAST mode.

    Only the subset of ``ImageViewer2D`` attributes referenced by code paths
    that run regardless of backend needs to be stubbed.  Methods that are
    genuinely FAST-mode-only dead-code are no-ops.
    """

    def __getattr__(self, name: str):
        # Property-style objects (e.g. image_viewer.renderer) should also be
        # falsy so guards like ``if self.image_viewer.renderer:`` skip the block.
        return _NullVtkObject()

    def GetSlice(self) -> int:
        return 0

    def apply_default_window_level(self, slice_index: int = 0):
        pass

    def update_corners_actors(self):
        pass

    def load_bottom_left_actors(self, *args, **kwargs):
        pass

    @property
    def metadata(self) -> dict:
        return {}


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class QtFastContainer(QWidget):
    """VTK-free viewer cell widget for FAST mode.

    Instantiated by the factory helpers in ``_pw_viewers.py`` /
    ``_vc_layout.py`` when ``_get_requested_viewer_backend()`` returns
    ``BACKEND_PYDICOM_QT``.  The real Qt bridge (``QtViewerBridge``) is wired
    in by ``_bind_backend_from_metadata`` at series-load time — this class only
    provides the lightweight container and the null-object surface until then.
    """

    def __init__(
        self,
        parent=None,
        height_viewer: int = 480,
        patient_widget=None,
    ):
        super().__init__(parent)

        # ── Geometry ────────────────────────────────────────────────────────
        self.height_viewer = height_viewer
        self.setMinimumHeight(height_viewer)

        # Dark background to match the VTK placeholder appearance while empty.
        self.setStyleSheet("background-color: #1a1a2e;")

        # ── Patient context ─────────────────────────────────────────────────
        self.patient_widget = patient_widget

        # ── VTK null stubs (crash-site register C1–C9) ──────────────────────
        # These provide the same attribute names as VTKWidget so existing
        # call sites that already have hasattr() guards satisfy their condition
        # but every method call is silently absorbed.
        self.render_window = _NullVtkObject()
        self.renderer = _NullVtkObject()    # accessed in _create_lightweight_vtk_placeholder
        self.interactor = _NullVtkObject()

        # current_style = None (not _NullVtkObject) so that:
        #   - Eagle Eye guard "if not vtk_widget.current_style:" evaluates True → skipped
        #   - isinstance checks for AbstractInteractorStyle are not confused
        self.current_style = None
        self.style = None                   # legacy attribute on VTKWidget

        # ── Series / viewer state (mirror VTKWidget) ─────────────────────────
        self.last_series_show = None
        self.id_vtk_widget = None
        self.image_viewer = _NullImageViewer()
        self.slider = None
        self.apply_default_filter = True
        self.method_change_series_on_viewer = None
        self.method_change_container_border = None

        # ── Overlay / drag-drop state ─────────────────────────────────────────
        self._overlay = {}
        self._prev_interactor_render = None
        self.initial_view_up_camera = None

        # ── Render throttle state (mirror VTKWidget) ─────────────────────────
        self._render_pending = False
        self._last_render_time = 0
        self._render_timer = None

        # ── Camera / zoom state ──────────────────────────────────────────────
        self._protected_parallel_scale = None
        self._wheel_event_count = 0
        self._camera_restore_generation = 0

        # ── FAST-mode-specific flags ─────────────────────────────────────────
        self._active_backend: str = BACKEND_PYDICOM_QT
        self._qt_bridge_active: bool = False   # True once QtViewerBridge is wired
        self._is_fast_mode: bool = True
        self._is_placeholder: bool = False      # set by _create_lightweight_vtk_placeholder

        # ── Lazy-loader placeholders (FAST mode never uses these) ────────────
        self._lazy_loader = None
        self._lazy_loader_key = None

        # ── Qt bridge reference (wired by _bind_backend_from_metadata) ───────
        self._qt_bridge = None

        # ── Viewport spinner (reuses the same class as VTKWidget) ────────────
        try:
            self.viewport_spinner = ViewportSpinner(self)
        except Exception:
            self.viewport_spinner = None

    # ── VTK compatibility shims ────────────────────────────────────────────

    def GetRenderWindow(self) -> _NullVtkObject:
        """Null stub — satisfies GetRenderWindow().Render() call sites (C7, C9)."""
        return _NullVtkObject()

    def Render(self) -> None:
        """Null stub — no-op in FAST mode."""
        pass

    def Initialize(self) -> None:
        """Null stub — QVTKRenderWindowInteractor.Initialize() analogue."""
        pass

    # ── Drag-drop method wiring ────────────────────────────────────────────

    def set_method_change_series_on_drop(self, fn) -> None:
        self.method_change_series_on_viewer = fn
        if self._qt_bridge and hasattr(self._qt_bridge, 'set_method_change_series_on_drop'):
            self._qt_bridge.set_method_change_series_on_drop(fn)

    def set_method_change_container_border(self, fn) -> None:
        self.method_change_container_border = fn

    # ── Series processing entry points (no-ops in FAST mode) ──────────────
    # The FAST pipeline loads series via _load_single_series_on_demand + the
    # Qt bridge, not through start_process_series.

    def start_process_series(self, *args, **kwargs) -> None:
        logger.debug("[QtFastContainer] start_process_series called (no-op in FAST mode)")

    def start_process_combine_series(self, *args, **kwargs) -> None:
        logger.debug("[QtFastContainer] start_process_combine_series called (no-op in FAST mode)")

    # ── Interactor-style stubs (called by Eagle Eye / toolbar) ────────────

    def set_new_interactorstyle(self, style) -> None:
        """No-op — FAST mode has no VTK interactor to switch."""
        pass

    def restore_default_interactorstyle(self) -> None:
        """No-op — FAST mode has no VTK interactor to restore."""
        pass

    # ── Slice / view delegation to Qt bridge ──────────────────────────────

    def set_slice(self, value: int) -> None:
        if self._qt_bridge:
            self._qt_bridge.set_slice(value)

    def switch_series(self, *args, **kwargs):
        if self._qt_bridge:
            return self._qt_bridge.switch_series(*args, **kwargs)

    def reset_image(self, vtk_image_data, metadata) -> None:
        if self._qt_bridge:
            self._qt_bridge.reset_image(vtk_image_data, metadata)

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        try:
            if self._qt_bridge and hasattr(self._qt_bridge, 'cleanup'):
                self._qt_bridge.cleanup()
        except Exception:
            pass
