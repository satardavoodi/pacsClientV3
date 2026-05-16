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
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt, QTimer

from modules.viewer.viewer_backend_config import BACKEND_PYDICOM_QT
from modules.viewer.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import _SERIES_DROP_MIME
from PacsClient.utils.runtime_correlation import (
    now_mono_ms as _corr_now_mono_ms,
    record_event as _corr_record_event,
    session_id as _corr_session_id,
    set_active_viewer_state as _corr_set_active_viewer_state,
)

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

    # Drop hint message (mirrors VTKWidget._VWOverlayMixin)
    _EMPTY_DROP_HINT_HTML = (
        "<div style='text-align:center;'>"
        "<span style='font-size:14px; font-weight:600;'>"
        "Drop a series here or select one from the thumbnail panel."
        "</span>"
        "</div>"
    )

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

        # Accept series drops from the thumbnail sidebar.
        self.setAcceptDrops(True)
        
        # ── Container layout for QtSliceViewer ──────────────────────────────
        # Initialize with an empty VBoxLayout so the viewer can be added later
        self._container_layout = QVBoxLayout(self)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(0)

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

        # ── Progressive-display state (mirror VTKWidget._vw_progressive) ────
        # _find_progressive_viewers() and related helpers access these directly.
        # In FAST mode the actual grow is driven by QtViewerBridge, but the
        # flag and series-number must exist so the controller can locate
        # which viewer cell is tracking a given progressive series.
        self._progressive_mode: bool = False
        self._progressive_series_number = None

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
        self._qt_viewer_widget = None  # The actual QtSliceViewer widget

        # ── Viewport spinner (reuses the same class as VTKWidget) ────────────
        try:
            self.viewport_spinner = ViewportSpinner(self)
        except Exception:
            self.viewport_spinner = None
        
        # ── Visual feedback for drag-drop (empty state) ──────────────────────
        self._empty_drop_hint_label = None  # Lazy-created
        self._drop_overlay = None  # Lazy-created
        
        # ── Update drop hint visibility when container becomes empty ────────
        self._update_empty_drop_hint_visibility()

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

    # ── Progressive-display protocol (mirror _vw_progressive.py) ─────────
    # _vc_progressive calls these on whatever viewer cell is showing a
    # partially-downloaded series.  In FAST mode the actual grow is done
    # via QtViewerBridge.grow(); here we only maintain the flag/series-number
    # so that _find_progressive_viewers() can locate this container.

    def enter_progressive_mode(self, total_expected_slices: int, series_number: str) -> None:
        self._progressive_mode = True
        self._progressive_series_number = str(series_number)
        logger.debug(
            "[QtFastContainer] enter_progressive_mode series=%s total=%d",
            series_number, total_expected_slices,
        )

    def exit_progressive_mode(self) -> None:
        self._progressive_mode = False
        self._progressive_series_number = None
        logger.debug("[QtFastContainer] exit_progressive_mode")

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

    def _ensure_qt_bridge(self, metadata=None, metadata_fixed=None):
        """Initialize QtViewerBridge if not already created.
        
        Called lazily from switch_series() / reset_image() when the bridge
        is first needed. This matches the VTKWidget pattern where _start_qt_viewer()
        creates the bridge on demand.
        """
        if self._qt_bridge is not None and self._qt_bridge_active:
            return  # Already initialized
        
        if metadata is None or not isinstance(metadata, dict):
            logger.warning("[FAST] _ensure_qt_bridge called with invalid metadata")
            return
        
        try:
            from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
                _create_qt_viewer_bridge,
            )
            
            # Use provided metadata_fixed or fall back to empty dict
            _mf = metadata_fixed or {}
            
            logger.info("[FAST] Creating QtViewerBridge (lazy init)")
            bridge, qt_viewer = _create_qt_viewer_bridge(self, metadata, _mf)
            
            self._qt_bridge = bridge
            self._qt_viewer_widget = qt_viewer
            self._qt_bridge_active = True
            self.image_viewer = bridge  # Update the stub to the real bridge
            
            # ── Add QtSliceViewer to container layout ────────────────────────
            # Remove any existing widgets from layout
            while self._container_layout.count() > 0:
                item = self._container_layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            
            # Add the QtSliceViewer to the layout
            qt_viewer.setParent(self)  # Ensure proper parent
            self._container_layout.addWidget(qt_viewer, stretch=1)
            qt_viewer.show()
            
            # ── Update drop hint visibility (hide hint now that series is loaded) ──
            self._update_empty_drop_hint_visibility()
            
            logger.info("[FAST] QtViewerBridge initialized successfully")
        except Exception as e:
            logger.error(f"[FAST] Failed to initialize QtViewerBridge: {e}", exc_info=True)

    def set_slice(self, value: int) -> None:
        if self._qt_bridge:
            self._qt_bridge.set_slice(value)

    def begin_slider_drag_session(self) -> None:
        """Begin a protected FAST drag session from slider thumb-press."""
        if self._qt_bridge is not None:
            try:
                self._qt_bridge.begin_slider_drag()
            except Exception:
                pass

    def end_slider_drag_session(self) -> None:
        """End the protected FAST drag session on slider thumb-release."""
        if self._qt_bridge is not None:
            try:
                self._qt_bridge.end_slider_drag()
            except Exception:
                pass

    def set_slice_during_drag(self, value: int) -> None:
        """Fast-path slice setter for active slider thumb drag.
        Routes through _on_stack_drag_target for surrogate/metrics/render-clock path."""
        if self._qt_bridge is not None:
            try:
                self._qt_bridge.handle_slider_drag_target(int(value))
                return
            except Exception:
                pass
            # Fallback: direct set_slice if drag-target path fails
            try:
                self._qt_bridge.set_slice(value)
            except Exception:
                pass

    # ── Core image-display methods ────────────────────────────────────────

    def _start_qt_viewer(self, metadata, metadata_fixed):
        """Create and wire QtViewerBridge, then render the first slice.

        Mirrors _legacy_widget.py::_start_qt_viewer so QtFastContainer follows
        the same Qt fast path as VTKWidget.  Called by switch_series() and
        reset_image().
        """
        from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
            _create_qt_viewer_bridge,
        )

        # Clean up any existing bridge before creating a new one
        switch_id = str(getattr(self, '_corr_switch_id', '') or '')
        series_number = str((metadata or {}).get('series', {}).get('series_number', '') or '')
        series_uid = str((metadata or {}).get('series', {}).get('series_uid', '') or '')
        create_start_ms = _corr_now_mono_ms()
        _corr_set_active_viewer_state(
            viewer_state="qt_bridge_create_start",
            series_uid=series_uid,
            series_number=series_number,
            interaction_active=False,
        )
        _corr_record_event(
            "VIEWER_SWITCH",
            phase="widget_create_start",
            switch_id=switch_id,
            series_number=series_number,
            series_uid=series_uid,
        )
        if self._qt_bridge is not None:
            try:
                self._qt_bridge.cleanup()
            except Exception:
                pass
            self._qt_bridge = None
            self._qt_viewer_widget = None
            self._qt_bridge_active = False

        # Create bridge + pipeline (pipeline.open_series is called inside)
        bridge, qt_viewer = _create_qt_viewer_bridge(self, metadata, metadata_fixed or {})
        create_end_ms = _corr_now_mono_ms()
        widget_create_ms = max(0.0, create_end_ms - create_start_ms)
        try:
            setattr(bridge, '_corr_switch_id', switch_id)
        except Exception:
            pass
        create_event = _corr_record_event(
            "VIEWER_SWITCH",
            phase="widget_created",
            switch_id=switch_id,
            series_number=series_number,
            series_uid=series_uid,
            widget_create_ms=float(widget_create_ms),
        )
        logger.info(
            "[VIEWER_SWITCH] phase=widget_created switch_id=%s series=%s series_uid=%s "
            "widget_creation_ms=%.1f corr_session=%s corr_mono_ms=%.3f",
            switch_id,
            series_number,
            series_uid,
            widget_create_ms,
            _corr_session_id(),
            float(create_event.get('mono_ms', create_end_ms)),
        )

        self._qt_bridge = bridge
        self._qt_viewer_widget = qt_viewer
        self._qt_bridge_active = True
        self.image_viewer = bridge

        # Remove any previous widgets from the container layout
        while self._container_layout.count() > 0:
            item = self._container_layout.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)

        # Embed QtSliceViewer in the layout so it fills the cell
        qt_viewer.setParent(self)
        self._container_layout.addWidget(qt_viewer, stretch=1)
        qt_viewer.show()
        qt_viewer.raise_()

        if self.slider is not None:
            try:
                self.slider.raise_()
            except Exception:
                pass

        # Render the middle slice — this is what actually paints the first image
        mid_slice = bridge.get_count_of_slices() // 2
        render_req_event = _corr_record_event(
            "VIEWER_SWITCH",
            phase="first_render_request",
            switch_id=switch_id,
            series_number=series_number,
            series_uid=series_uid,
            requested_slice=int(mid_slice),
        )
        logger.info(
            "[VIEWER_SWITCH] phase=first_render_request switch_id=%s series=%s series_uid=%s "
            "slice=%d corr_session=%s corr_mono_ms=%.3f",
            switch_id,
            series_number,
            series_uid,
            int(mid_slice),
            _corr_session_id(),
            float(render_req_event.get('mono_ms', _corr_now_mono_ms())),
        )
        bridge.set_slice(mid_slice)
        bridge.apply_default_window_level(mid_slice)
        _corr_set_active_viewer_state(
            viewer_state="qt_bridge_active",
            series_uid=series_uid,
            series_number=series_number,
            interaction_active=False,
        )

        # Hide the empty-drop hint now that a series is loaded
        self._update_empty_drop_hint_visibility()

        logger.info(
            "[QtFastContainer] _start_qt_viewer: slices=%d mid=%d",
            bridge.get_count_of_slices(), mid_slice,
        )

    def switch_series(self, vtk_image_data, metadata, series_index,
                      vtk_image_data_2=None, metadata_2=None,
                      metadata_fixed=None, progressive_total: int = 0):
        """Switch series on the FAST viewer.

        Mirrors the Qt fast path in VTKWidget.switch_series() from
        _legacy_widget.py.  Ignores vtk_image_data / vtk_image_data_2 because
        FAST mode loads pixels directly from DICOM files via the pipeline.
        """
        series_number = (metadata or {}).get('series', {}).get('series_number', 'N/A')

        # Same-series no-op: skip if already showing this series index
        if self.last_series_show == series_index and self._qt_bridge is not None:
            logger.debug(
                "[QtFastContainer] switch_series: already showing series=%s idx=%s, skip",
                series_number, series_index,
            )
            return False

        if self.viewport_spinner:
            try:
                self.viewport_spinner.show_loading("Switching series...")
            except Exception:
                pass

        try:
            self._start_qt_viewer(metadata, metadata_fixed or {})
            self.last_series_show = series_index
            logger.info(
                "[QtFastContainer] switch_series: complete series=%s slices=%d",
                series_number, self.get_count_of_slices(),
            )
        except Exception as e:
            logger.error("[QtFastContainer] switch_series failed: %s", e, exc_info=True)
            if self.viewport_spinner:
                try:
                    self.viewport_spinner.hide_loading()
                except Exception:
                    pass
            return False

        QTimer.singleShot(180, self._safe_hide_spinner)
        return True

    def _safe_hide_spinner(self):
        """Hide viewport spinner safely (QTimer target — must not raise)."""
        try:
            if self.viewport_spinner:
                self.viewport_spinner.hide_loading()
        except Exception:
            pass

    def reset_image(self, vtk_image_data, metadata) -> None:
        """Reset image display — recreates the Qt bridge with fresh metadata."""
        try:
            self._start_qt_viewer(metadata, {})
        except Exception as e:
            logger.error("[QtFastContainer] reset_image failed: %s", e, exc_info=True)

    # ── Slice / count delegation ──────────────────────────────────────────

    def get_count_of_slices(self) -> int:
        """Return the number of slices available in the current series."""
        if self._qt_bridge_active and self._qt_bridge is not None:
            try:
                return int(self._qt_bridge.get_count_of_slices())
            except Exception:
                pass
        return 0

    def update_available_slice_count(self, count: int) -> None:
        """Update available slice count for progressive display."""
        if self._qt_bridge_active and self._qt_bridge is not None:
            try:
                if hasattr(self._qt_bridge, 'update_available_slice_count'):
                    self._qt_bridge.update_available_slice_count(count)
            except Exception:
                pass

    # ── Presentation sync (mirrors _vw_series._sync_qt_viewer_presentation) ──

    def _sync_qt_viewer_presentation(self, *, refit_view: bool = False) -> None:
        """Keep the Qt child viewer aligned with the host widget.

        Since QtSliceViewer is embedded in a QVBoxLayout, geometry is managed
        by Qt's layout engine.  We only apply zoom-to-fit on explicit request.
        """
        if not self._qt_bridge_active or self._qt_bridge is None:
            return

        if refit_view:
            try:
                new_scale = self._qt_bridge.zoom_to_fit()
                if new_scale:
                    self._protected_parallel_scale = float(new_scale)
            except Exception as exc:
                logger.debug("[QtFastContainer] _sync_qt_viewer_presentation zoom failed: %s", exc)

    def set_slider(self, slider) -> None:
        """Store slider reference for drag-drop / series switching."""
        self.slider = slider

    # ── Empty drop hint label (mirrors VTKWidget._VWOverlayMixin) ────────

    def _ensure_empty_drop_hint_label(self):
        """Create empty drop hint label if not already created."""
        label = self._empty_drop_hint_label
        if label is not None:
            return label

        label = QLabel(self)
        label.setObjectName("emptyDropHint")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setText(self._EMPTY_DROP_HINT_HTML)
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        label.setStyleSheet(
            "QLabel#emptyDropHint {"
            "background-color: rgba(0, 0, 0, 210);"
            "color: #f8fafc;"
            "border: 1px dashed rgba(148, 163, 184, 170);"
            "border-radius: 12px;"
            "padding: 14px 18px;"
            "}"
        )
        label.hide()
        self._empty_drop_hint_label = label
        return label

    def _layout_empty_drop_hint_label(self):
        """Position and size the empty drop hint label."""
        label = self._ensure_empty_drop_hint_label()
        available_width = max(180, int(self.width()) - 48)
        target_width = max(180, min(available_width, 340))
        label.setFixedWidth(target_width)
        label.adjustSize()

        x = max(12, (self.width() - label.width()) // 2)
        y = max(48, (self.height() - label.height()) // 2)
        label.move(x, y)

    def _should_show_empty_drop_hint(self) -> bool:
        """Return True if drop hint should be visible (no series loaded yet)."""
        return self._qt_bridge is None

    def _update_empty_drop_hint_visibility(self):
        """Show/hide drop hint based on whether series is loaded."""
        if self._should_show_empty_drop_hint():
            label = self._ensure_empty_drop_hint_label()
            self._layout_empty_drop_hint_label()
            label.show()
        else:
            if self._empty_drop_hint_label is not None:
                self._empty_drop_hint_label.hide()

    # ── Drop highlight overlay (blue border on drag-over) ────────────────

    def _show_drop_highlight(self, show: bool):
        """Show/hide blue border overlay during drag-over (mirrors VTKWidget)."""
        if not hasattr(self, '_drop_overlay') or self._drop_overlay is None:
            overlay = QFrame(self)
            overlay.setObjectName("dropOverlay")
            overlay.setStyleSheet(
                """
                QFrame#dropOverlay {
                    border: 3px solid rgba(59, 130, 246, 200);
                    border-radius: 6px;
                    background: rgba(59, 130, 246, 25);
                }
                """
            )
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            overlay.hide()
            self._drop_overlay = overlay

        try:
            self._drop_overlay.setGeometry(self.rect())
            if show:
                self._drop_overlay.raise_()
                self._drop_overlay.show()
            else:
                self._drop_overlay.hide()
            # Update drop hint visibility
            if hasattr(self, '_update_empty_drop_hint_visibility'):
                self._update_empty_drop_hint_visibility()
        except RuntimeError:
            pass

    def _is_series_drop(self, mime_data) -> bool:
        if mime_data is None:
            return False
        if mime_data.hasFormat(_SERIES_DROP_MIME):
            return True
        if mime_data.hasText():
            text = (mime_data.text() or "").strip()
            return bool(text and text.lstrip("-").isdigit())
        return False

    def _extract_series_number(self, mime_data):
        if mime_data is None:
            return None
        try:
            if mime_data.hasFormat(_SERIES_DROP_MIME):
                raw = bytes(mime_data.data(_SERIES_DROP_MIME)).decode("utf-8", errors="ignore").strip()
                return int(raw)
            if mime_data.hasText():
                text = (mime_data.text() or "").strip()
                if text.lstrip("-").isdigit():
                    return int(text)
        except (ValueError, TypeError):
            pass
        return None

    def dragEnterEvent(self, event):
        if self._is_series_drop(event.mimeData()):
            # Show blue border highlight during drag-over
            self._show_drop_highlight(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._is_series_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        # Hide blue border highlight when leaving
        self._show_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        series_number = self._extract_series_number(event.mimeData())
        if series_number is None:
            event.ignore()
            return

        event.setDropAction(Qt.CopyAction)
        event.accept()
        
        # Hide drop highlight after drop
        self._show_drop_highlight(False)

        if self.viewport_spinner:
            try:
                self.viewport_spinner.show_loading(f"Loading series {series_number}…")
            except Exception:
                pass

        _method = self.method_change_series_on_viewer
        if _method is None:
            logger.error(
                "[QtFastContainer DROP] method_change_series_on_viewer is None "
                "for viewer=%s series=%s — drop ignored.",
                self.id_vtk_widget, series_number,
            )
            if self.viewport_spinner:
                try:
                    self.viewport_spinner.hide_loading()
                except Exception:
                    pass
            return

        _slider = self.slider

        def _do_switch():
            try:
                _method(
                    series_index=int(series_number),
                    flag_change_selected_widget=False,
                    vtk_widget=self,
                    slider=_slider,
                )
            except Exception as _err:
                logger.error("[QtFastContainer DROP] series switch raised: %s", _err, exc_info=True)

        QTimer.singleShot(0, _do_switch)

    # ── Resize handling for drop hint label positioning ───────────────────

    def resizeEvent(self, event):
        """Reposition drop hint label on resize."""
        super().resizeEvent(event)
        if self._empty_drop_hint_label is not None and self._empty_drop_hint_label.isVisible():
            self._layout_empty_drop_hint_label()
        if self._drop_overlay is not None:
            self._drop_overlay.setGeometry(self.rect())

    # ── Lifecycle ─────────────────────────────────────────────────────────
    def cleanup(self) -> None:
        try:
            if self._qt_bridge and hasattr(self._qt_bridge, 'cleanup'):
                self._qt_bridge.cleanup()
        except Exception:
            pass
