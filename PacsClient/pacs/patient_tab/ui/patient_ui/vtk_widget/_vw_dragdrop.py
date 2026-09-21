"""
Drag-and-drop mixin for VTKWidget.
dragEnterEvent, dragMoveEvent, dragLeaveEvent, dropEvent.
"""
from __future__ import annotations
import json
import logging
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from PacsClient.utils.diagnostic_logging import now_ms
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._drop_hover_dwell import (
    _DropHoverDwellMixin,
)
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _DROP_HOVER_ARM_MS,
    _SERIES_DROP_MIME,
)

logger = logging.getLogger(__name__)


class _VWDragDropMixin(_DropHoverDwellMixin):
    """Drag-and-drop: series drop with dwell-timer visual feedback."""

    def _is_supported_drop_payload(self, mime_data) -> bool:
        if mime_data is None:
            return False

        if mime_data.hasFormat(_SERIES_DROP_MIME):
            return True

        if mime_data.hasText():
            text = str(mime_data.text() or "").strip()
            if text and text.lstrip("-").isdigit():
                return True

        # Keep URL support for external segmentation files.
        return bool(mime_data.hasUrls())

    def _is_internal_series_drop_payload(self, mime_data) -> bool:
        """True when payload is from in-app thumbnail drag source."""
        try:
            return bool(mime_data is not None and mime_data.hasFormat(_SERIES_DROP_MIME))
        except Exception:
            return False

    def _extract_dropped_series_number(self, mime_data):
        if mime_data is None:
            return None
        try:
            if mime_data.hasFormat(_SERIES_DROP_MIME):
                raw = bytes(mime_data.data(_SERIES_DROP_MIME)).decode("utf-8", errors="ignore").strip()
                if raw and raw.lstrip("-").isdigit():
                    return int(raw)
            if mime_data.hasText():
                text = str(mime_data.text() or "").strip()
                if text and text.lstrip("-").isdigit():
                    return int(text)
        except Exception:
            return None
        return None

    def dragEnterEvent(self, event):
        if not self._is_supported_drop_payload(event.mimeData()):
            self._reset_drop_hover_state()
            event.ignore()
            return

        self._begin_drop_hover(event)
        event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if not self._is_supported_drop_payload(event.mimeData()):
            event.ignore()
            return

        self._update_drop_hover(event)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._reset_drop_hover_state()
        super().dragLeaveEvent(event)

    def _show_drop_highlight(self, show: bool):
        if not hasattr(self, '_drop_overlay'):
            from PySide6.QtWidgets import QFrame
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
            if hasattr(self, '_update_empty_drop_hint_visibility'):
                self._update_empty_drop_hint_visibility()
        except RuntimeError:
            pass

    def dropEvent(self, event):
        mime_data = event.mimeData()
        self._show_drop_highlight(False)
        if not self._is_supported_drop_payload(mime_data):
            self._reset_drop_hover_state(hide_overlay=False)
            event.ignore()
            return

        elapsed_ms = now_ms() - float(self._drop_hover_started_ms or 0.0)
        is_internal_series_drop = self._is_internal_series_drop_payload(mime_data)
        if (
            _DROP_HOVER_ARM_MS > 0
            and (not is_internal_series_drop)
            and (not self._drop_hover_armed or elapsed_ms < _DROP_HOVER_ARM_MS)
        ):
            logger.debug(
                "drop ignored before arm viewer=%s elapsed_ms=%.1f required_ms=%d",
                str(getattr(self, "id_vtk_widget", None)),
                float(elapsed_ms),
                int(_DROP_HOVER_ARM_MS),
            )
            self._reset_drop_hover_state(hide_overlay=False)
            event.ignore()
            return

        data = self._extract_dropped_series_number(mime_data)
        if data is not None:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self._reset_drop_hover_state(hide_overlay=False)

        try:
            data = int(data)
        except Exception:
            # Dropped segmentation out of app (data is not an integer)
            if mime_data.hasUrls():
                event.setDropAction(Qt.CopyAction)
                event.accept()
                self._reset_drop_hover_state(hide_overlay=False)
                url_data = mime_data.urls()[0].toLocalFile()
                logger.debug(f'dropped file url: {url_data}\n')
                try:
                    from PacsClient.pacs.patient_tab.utils import read_segment_nifti
                    vtk_segmentation_img = read_segment_nifti(url_data)
                    self.overlay(vtk_segmentation_img, color=(0.0, 1.0, 0.0), opacity=0.35, is_label=True)
                    logger.debug('add segmentation successful.')
                except Exception as seg_err:
                    logger.warning(f"Segmentation load failed: {seg_err}")
                return
            self._reset_drop_hover_state(hide_overlay=False)
            event.ignore()
            return

        # --- Series drop ---
        # Change series with drag and drop - async for smooth UI
        # IMPORTANT: keep change_container_border isolated so its exceptions
        # never prevent the QTimer from being scheduled.
        try:
            self.change_container_border()
        except Exception as _cbe:
            logger.warning("change_container_border failed during drop (non-fatal): %s", _cbe)

        try:
            if self.patient_widget is not None:
                action_id = f"drag_drop-{data}-{int(time.time() * 1000)}-viewer-{getattr(self, 'id_vtk_widget', 'na')}"
                self.patient_widget._pending_action_id = action_id
                self.patient_widget._pending_action_series = str(data)
        except Exception:
            pass

        # Show loading spinner immediately when series is dropped
        # This provides instant visual feedback to the user
        self.viewport_spinner.show_loading("Switching series...")

        _method = self.method_change_series_on_viewer
        if _method is None:
            logger.error(
                "[DROP] method_change_series_on_viewer is None for viewer=%s — "
                "series=%s drop ignored. Was new_viewer() called?",
                getattr(self, 'id_vtk_widget', '?'), data,
            )
            self.viewport_spinner.hide_loading()
            return

        _slider = self.slider
        if _slider is None:
            logger.warning(
                "[DROP] slider is None for viewer=%s — series=%s drop may fail.",
                getattr(self, 'id_vtk_widget', '?'), data,
            )

        # Use QTimer to defer the call and avoid blocking during drop
        # This allows the spinner to display before the expensive series switch
        def _do_series_switch():
            try:
                # Manual drag-and-drop is an EXPLICIT user request: ALWAYS replace
                # the target viewport with the dropped series. force_reload=True
                # bypasses the same-series no-op and reloads from a clean
                # (cache-invalidated) state, so the drop wins even when the same
                # Study/Series is already open here or in another viewport.
                logger.info(
                    "[DROP] apply — series=%s target_viewer=%s force_reload=1",
                    data, getattr(self, 'id_vtk_widget', '?'),
                )
                _method(
                    series_index=int(data),
                    flag_change_selected_widget=False,
                    vtk_widget=self,
                    slider=_slider,
                    force_reload=True,
                )
            except Exception as _sw_err:
                logger.error(
                    "[DROP] series load FAILED — dropped series=%s target_viewer=%s: %s",
                    data, getattr(self, 'id_vtk_widget', '?'), _sw_err, exc_info=True,
                )

        QTimer.singleShot(0, _do_series_switch)
