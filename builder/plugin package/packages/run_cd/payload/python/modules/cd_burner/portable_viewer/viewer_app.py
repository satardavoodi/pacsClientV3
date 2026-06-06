"""AI-PACS Lite Viewer — main window and application entry.

A deliberately small, dependency-light 2D DICOM viewer for patient CD/DVD
media. Features: open study folder, series list, slice scrolling, zoom,
pan, window/level, basic toolbar. Nothing else (no MPR / AI / reporting),
and it must stay that way — this ships on read-only media.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QPoint, QPointF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

try:  # package-relative (dev run inside AI-PACS repo)
    from .viewer_meta import VIEWER_DISPLAY_NAME, VIEWER_VERSION
    from .media_scan import ScanResult, SeriesRecord, discover_media_root, scan_media
    from .render import SliceData, load_slice, peek_frame_count, slice_to_qimage
except ImportError:  # standalone build / direct script execution
    from viewer_meta import VIEWER_DISPLAY_NAME, VIEWER_VERSION  # type: ignore
    from media_scan import ScanResult, SeriesRecord, discover_media_root, scan_media  # type: ignore
    from render import SliceData, load_slice, peek_frame_count, slice_to_qimage  # type: ignore

logger = logging.getLogger(__name__)

_SLICE_CACHE_MAX = 96          # decoded slices kept in memory (LRU)
_PREFETCH_RADIUS = 3           # neighbour slices loaded in the background

_DARK_QSS = """
QMainWindow, QWidget { background-color: #14181d; color: #d7dde3; }
QToolBar { background-color: #1b2128; border: none; spacing: 4px; padding: 4px; }
QToolBar QToolButton { color: #d7dde3; padding: 6px 10px; border-radius: 6px; }
QToolBar QToolButton:hover { background-color: #2a323c; }
QToolBar QToolButton:checked { background-color: #2f5d9e; color: #ffffff; }
QListWidget { background-color: #10141a; border: 1px solid #242c35;
              border-radius: 6px; font-size: 12px; }
QListWidget::item { padding: 6px 8px; }
QListWidget::item:selected { background-color: #2f5d9e; color: #ffffff; }
QSlider::groove:horizontal { height: 5px; background: #2a323c; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; background: #5b8ad6;
                             margin: -5px 0; border-radius: 7px; }
QStatusBar { background-color: #1b2128; color: #9aa6b2; }
QLabel#sliceLabel { color: #9aa6b2; font-size: 12px; padding: 0 8px; }
"""


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _Bridge(QObject):
    scan_done = Signal(object)                 # ScanResult
    slice_loaded = Signal(str, int, object)    # path, frame, SliceData


class _ScanTask(QRunnable):
    def __init__(self, bridge: _Bridge, root: str):
        super().__init__()
        self._bridge = bridge
        self._root = root

    def run(self):  # pragma: no cover — thin thread wrapper
        result = scan_media(self._root)
        self._bridge.scan_done.emit(result)


class _SliceLoadTask(QRunnable):
    def __init__(self, bridge: _Bridge, path: str, frame: int):
        super().__init__()
        self._bridge = bridge
        self._path = path
        self._frame = frame

    def run(self):  # pragma: no cover — thin thread wrapper
        data = load_slice(self._path, self._frame)
        self._bridge.slice_loaded.emit(self._path, self._frame, data)


# ---------------------------------------------------------------------------
# Image canvas
# ---------------------------------------------------------------------------

class ImageCanvas(QWidget):
    """Paints the current slice with zoom/pan and overlay text.

    Interaction (delegated back to the window through callables):
      wheel = scroll slices · Ctrl+wheel = zoom · left-drag = active tool
      middle-drag = pan · right-drag = zoom · double-click = fit
    """

    TOOL_WL = "wl"
    TOOL_PAN = "pan"
    TOOL_ZOOM = "zoom"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setMouseTracking(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._image: Optional[QImage] = None
        self._zoom: float = 1.0
        self._pan: QPointF = QPointF(0.0, 0.0)
        self._fit_pending = True

        self.active_tool: str = self.TOOL_WL
        self.overlay_lines: Dict[str, List[str]] = {"tl": [], "tr": [], "bl": [], "br": []}
        self.empty_text: str = "Loading…"

        # Callbacks wired by the window
        self.on_scroll = lambda delta: None
        self.on_wl_drag = lambda dx, dy: None
        self.on_interaction_changed = lambda: None

        self._drag_button: Optional[Qt.MouseButton] = None
        self._drag_last: QPoint = QPoint()

    # -- public API ---------------------------------------------------------

    def set_image(self, image: Optional[QImage], keep_view: bool = True):
        size_changed = (
            self._image is None
            or image is None
            or self._image.size() != image.size()
        )
        self._image = image
        if image is None or not keep_view or size_changed:
            self._fit_pending = True
        self.update()

    def fit(self):
        self._fit_pending = True
        self.update()

    def actual_size(self):
        self._fit_pending = False
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def zoom_by(self, factor: float):
        self._fit_pending = False
        self._zoom = max(0.05, min(40.0, self._zoom * factor))
        self.update()
        self.on_interaction_changed()

    @property
    def zoom(self) -> float:
        return self._zoom

    # -- painting -----------------------------------------------------------

    def _apply_fit(self):
        if self._image is None or self._image.width() == 0:
            return
        scale_w = self.width() / self._image.width()
        scale_h = self.height() / self._image.height()
        self._zoom = max(0.01, min(scale_w, scale_h))
        self._pan = QPointF(0.0, 0.0)
        self._fit_pending = False

    def paintEvent(self, event):  # noqa: N802 — Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))

        if self._image is None:
            painter.setPen(QPen(QColor("#7f8b97")))
            font = QFont(self.font())
            font.setPointSize(11)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
            painter.end()
            return

        if self._fit_pending:
            self._apply_fit()

        target_w = self._image.width() * self._zoom
        target_h = self._image.height() * self._zoom
        x = (self.width() - target_w) / 2.0 + self._pan.x()
        y = (self.height() - target_h) / 2.0 + self._pan.y()

        painter.setRenderHint(QPainter.SmoothPixmapTransform, self._zoom < 4.0)
        painter.save()
        painter.translate(x, y)
        painter.scale(self._zoom, self._zoom)
        painter.drawImage(0, 0, self._image)
        painter.restore()

        self._paint_overlay(painter)
        painter.end()

    def _paint_overlay(self, painter: QPainter):
        font = QFont(self.font())
        font.setPointSize(9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        line_h = metrics.height()
        margin = 8

        def draw(lines: List[str], top: bool, left: bool):
            if not lines:
                return
            y = margin + metrics.ascent() if top else (
                self.height() - margin - line_h * (len(lines) - 1) - metrics.descent()
            )
            for line in lines:
                if not line:
                    y += line_h
                    continue
                w = metrics.horizontalAdvance(line)
                x = margin if left else self.width() - margin - w
                painter.setPen(QPen(QColor(0, 0, 0, 180)))
                painter.drawText(int(x) + 1, int(y) + 1, line)
                painter.setPen(QPen(QColor("#e8eef4")))
                painter.drawText(int(x), int(y), line)
                y += line_h

        draw(self.overlay_lines.get("tl", []), True, True)
        draw(self.overlay_lines.get("tr", []), True, False)
        draw(self.overlay_lines.get("bl", []), False, True)
        draw(self.overlay_lines.get("br", []), False, False)

    # -- interaction ---------------------------------------------------------

    def wheelEvent(self, event):  # noqa: N802 — Qt override
        delta = event.angleDelta().y()
        if delta == 0:
            return
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_by(1.15 if delta > 0 else 1.0 / 1.15)
        else:
            self.on_scroll(-1 if delta > 0 else 1)
        event.accept()

    def mouseDoubleClickEvent(self, event):  # noqa: N802 — Qt override
        self.fit()
        self.on_interaction_changed()

    def mousePressEvent(self, event):  # noqa: N802 — Qt override
        self._drag_button = event.button()
        self._drag_last = event.position().toPoint()
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 — Qt override
        self._drag_button = None
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 — Qt override
        if self._drag_button is None:
            return
        pos = event.position().toPoint()
        dx = pos.x() - self._drag_last.x()
        dy = pos.y() - self._drag_last.y()
        self._drag_last = pos

        button = self._drag_button
        tool = self.active_tool
        if button == Qt.MiddleButton:
            tool = self.TOOL_PAN
        elif button == Qt.RightButton:
            tool = self.TOOL_ZOOM

        if tool == self.TOOL_PAN:
            self._fit_pending = False
            self._pan += QPointF(dx, dy)
            self.update()
        elif tool == self.TOOL_ZOOM:
            self.zoom_by(1.0 + (-dy) * 0.01)
        else:  # window/level
            self.on_wl_drag(dx, dy)
        self.on_interaction_changed()
        event.accept()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class LiteViewerWindow(QMainWindow):
    def __init__(self, media_root: Optional[str] = None):
        super().__init__()
        self.setWindowTitle(f"{VIEWER_DISPLAY_NAME} {VIEWER_VERSION}")
        self.resize(1180, 760)

        self._bridge = _Bridge()
        self._bridge.scan_done.connect(self._on_scan_done)
        self._bridge.slice_loaded.connect(self._on_slice_loaded)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)

        self._media_root: Optional[str] = media_root
        self._scan: Optional[ScanResult] = None
        self._series: List[SeriesRecord] = []
        self._series_index: int = -1
        self._slice_index: int = 0
        self._slice_keys: List[Tuple[str, int]] = []   # (path, frame) per slice
        self._cache: "OrderedDict[Tuple[str, int], SliceData]" = OrderedDict()
        self._pending_loads: set = set()
        self._wl_by_series: Dict[str, Tuple[float, float]] = {}
        self._current_wl: Tuple[float, float] = (0.0, 1.0)

        self._build_ui()
        if media_root:
            self._start_scan(media_root)
        else:
            self.canvas.empty_text = (
                "No DICOM media detected.\n\nUse  File ▸ Open Folder…  to select a "
                "folder that contains DICOM images or a DICOMDIR."
            )
            self.canvas.update()

    # -- UI construction -----------------------------------------------------

    def _build_ui(self):
        self.setStyleSheet(_DARK_QSS)

        # Central widgets are created FIRST — toolbar actions connect to them.
        self.series_list = QListWidget(self)
        self.series_list.setMinimumWidth(230)
        self.series_list.setMaximumWidth(420)
        self.series_list.currentItemChanged.connect(self._on_series_item_changed)

        self.canvas = ImageCanvas(self)
        self.canvas.on_scroll = self._step_slice
        self.canvas.on_wl_drag = self._adjust_wl
        self.canvas.on_interaction_changed = self._refresh_overlay

        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(toolbar)

        open_action = QAction("Open Folder…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_folder_dialog)
        toolbar.addAction(open_action)
        toolbar.addSeparator()

        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_actions = {}
        for key, label, tip in (
            (ImageCanvas.TOOL_WL, "W/L", "Left-drag adjusts window/level"),
            (ImageCanvas.TOOL_PAN, "Pan", "Left-drag pans the image"),
            (ImageCanvas.TOOL_ZOOM, "Zoom", "Left-drag zooms the image"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setToolTip(tip)
            action.triggered.connect(lambda _=False, k=key: self._set_tool(k))
            self._tool_group.addAction(action)
            toolbar.addAction(action)
            self._tool_actions[key] = action
        self._tool_actions[ImageCanvas.TOOL_WL].setChecked(True)
        toolbar.addSeparator()

        zoom_in = QAction("Zoom +", self)
        zoom_in.setShortcut(QKeySequence.ZoomIn)
        zoom_in.triggered.connect(lambda: self.canvas.zoom_by(1.25))
        toolbar.addAction(zoom_in)

        zoom_out = QAction("Zoom −", self)
        zoom_out.setShortcut(QKeySequence.ZoomOut)
        zoom_out.triggered.connect(lambda: self.canvas.zoom_by(0.8))
        toolbar.addAction(zoom_out)

        fit_action = QAction("Fit", self)
        fit_action.setShortcut("F")
        fit_action.triggered.connect(self.canvas.fit)
        toolbar.addAction(fit_action)

        actual_action = QAction("1:1", self)
        actual_action.setShortcut("1")
        actual_action.triggered.connect(self.canvas.actual_size)
        toolbar.addAction(actual_action)

        reset_action = QAction("Reset W/L", self)
        reset_action.setShortcut("R")
        reset_action.triggered.connect(self._reset_wl)
        toolbar.addAction(reset_action)
        toolbar.addSeparator()

        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        toolbar.addAction(about_action)

        # Layout: series list (left) + canvas with slider (right)
        self.slice_slider = QSlider(Qt.Horizontal, self)
        self.slice_slider.setRange(0, 0)
        self.slice_slider.valueChanged.connect(self._on_slider_changed)
        self.slice_label = QLabel("–/–", self)
        self.slice_label.setObjectName("sliceLabel")

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(8, 4, 8, 6)
        slider_row.addWidget(self.slice_slider, 1)
        slider_row.addWidget(self.slice_label)

        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.canvas, 1)
        right_layout.addLayout(slider_row)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.series_list)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 900])
        self.setCentralWidget(splitter)

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready")

    # -- scanning ------------------------------------------------------------

    def _start_scan(self, root: str):
        self._media_root = root
        self.canvas.empty_text = f"Scanning media…\n\n{root}"
        self.canvas.set_image(None)
        self.series_list.clear()
        self.statusBar().showMessage(f"Scanning {root} …")
        self._pool.start(_ScanTask(self._bridge, root))

    def _on_scan_done(self, result: ScanResult):
        self._scan = result
        self._series = list(result.series)
        self._populate_series_list()

        if not self._series:
            message = result.errors[0] if result.errors else "No DICOM images found."
            self.canvas.empty_text = (
                f"{message}\n\nUse  Open Folder…  to select a folder that contains "
                "DICOM images or a DICOMDIR."
            )
            self.canvas.set_image(None)
            self.statusBar().showMessage(message)
            return

        patients = ", ".join(result.patient_labels()[:3])
        self.statusBar().showMessage(
            f"{len(self._series)} series · {result.total_images} images · "
            f"{patients} · source: {result.source}"
        )
        self._select_series(0)

    def _populate_series_list(self):
        self.series_list.blockSignals(True)
        self.series_list.clear()
        last_group = None
        for idx, series in enumerate(self._series):
            group = (series.patient_name, series.patient_id, series.study_uid)
            if group != last_group:
                last_group = group
                title = series.patient_name or "Unknown patient"
                if series.patient_id:
                    title += f"  [{series.patient_id}]"
                sub = series.study_description or series.study_date or "Study"
                header = QListWidgetItem(f"{title}\n{sub}")
                header.setFlags(Qt.NoItemFlags)
                header.setForeground(QColor("#7f9bbd"))
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                self.series_list.addItem(header)
            item = QListWidgetItem("  " + series.display_label())
            item.setData(Qt.UserRole, idx)
            item.setToolTip(
                f"Series {series.series_number} · {series.modality}\n"
                f"{series.description}\n{series.image_count} image(s)"
            )
            self.series_list.addItem(item)
        self.series_list.blockSignals(False)

    # -- series / slice handling ----------------------------------------------

    def _on_series_item_changed(self, current: Optional[QListWidgetItem], _previous):
        if current is None:
            return
        idx = current.data(Qt.UserRole)
        if idx is None:
            return
        self._select_series(int(idx), from_list=True)

    def _select_series(self, index: int, from_list: bool = False):
        if not (0 <= index < len(self._series)):
            return
        self._series_index = index
        series = self._series[index]

        # Build per-slice keys; expand single-file cine (multi-frame) series.
        if series.image_count == 1:
            frames = peek_frame_count(series.instances[0].path)
            if frames > 1:
                self._slice_keys = [(series.instances[0].path, f) for f in range(frames)]
            else:
                self._slice_keys = [(series.instances[0].path, 0)]
        else:
            self._slice_keys = [(inst.path, 0) for inst in series.instances]

        self._slice_index = 0
        self.slice_slider.blockSignals(True)
        self.slice_slider.setRange(0, max(0, len(self._slice_keys) - 1))
        self.slice_slider.setValue(0)
        self.slice_slider.blockSignals(False)

        if not from_list:
            self._sync_list_selection(index)

        # Restore remembered W/L for the series (if any)
        self._current_wl = self._wl_by_series.get(series.series_uid, (0.0, 0.0))
        self._show_slice(0, keep_view=False)

    def _sync_list_selection(self, series_index: int):
        for row in range(self.series_list.count()):
            item = self.series_list.item(row)
            if item.data(Qt.UserRole) == series_index:
                self.series_list.blockSignals(True)
                self.series_list.setCurrentItem(item)
                self.series_list.blockSignals(False)
                return

    def _step_slice(self, delta: int):
        if not self._slice_keys:
            return
        new_index = max(0, min(len(self._slice_keys) - 1, self._slice_index + delta))
        if new_index != self._slice_index:
            self._show_slice(new_index)

    def _on_slider_changed(self, value: int):
        if 0 <= value < len(self._slice_keys) and value != self._slice_index:
            self._show_slice(value)

    def _show_slice(self, index: int, keep_view: bool = True):
        if not (0 <= index < len(self._slice_keys)):
            return
        self._slice_index = index
        key = self._slice_keys[index]
        data = self._cache_get(key)
        if data is None:
            data = load_slice(key[0], key[1])
            self._cache_put(key, data)

        if not data.error and (self._current_wl[1] or 0) <= 0:
            self._current_wl = (data.default_center, data.default_width)
        if self._series_index >= 0 and not data.error:
            self._wl_by_series[self._series[self._series_index].series_uid] = self._current_wl

        self._render_current(keep_view=keep_view)
        self._update_slider_label()
        self._prefetch_neighbors(index)

    def _render_current(self, keep_view: bool = True):
        key = self._slice_keys[self._slice_index] if self._slice_keys else None
        data = self._cache.get(key) if key else None
        if data is None:
            return
        if data.error:
            self.canvas.empty_text = data.error
            self.canvas.set_image(None)
        else:
            center, width = self._current_wl
            image = slice_to_qimage(data, center, width)
            self.canvas.set_image(image, keep_view=keep_view)
        self._refresh_overlay()

    def _update_slider_label(self):
        total = len(self._slice_keys)
        self.slice_label.setText(f"{self._slice_index + 1}/{total}" if total else "–/–")
        self.slice_slider.blockSignals(True)
        self.slice_slider.setValue(self._slice_index)
        self.slice_slider.blockSignals(False)

    # -- window/level ----------------------------------------------------------

    def _adjust_wl(self, dx: int, dy: int):
        if not self._slice_keys:
            return
        key = self._slice_keys[self._slice_index]
        data = self._cache.get(key)
        if data is None or data.error or data.is_color:
            return
        center, width = self._current_wl
        span = max(abs(width), 1.0)
        width = max(1e-3, width + dx * span * 0.01)
        center = center + dy * span * 0.01
        self._current_wl = (center, width)
        if self._series_index >= 0:
            self._wl_by_series[self._series[self._series_index].series_uid] = self._current_wl
        self._render_current()

    def _reset_wl(self):
        if not self._slice_keys:
            return
        data = self._cache.get(self._slice_keys[self._slice_index])
        if data is None or data.error:
            return
        self._current_wl = (data.default_center, data.default_width)
        if self._series_index >= 0:
            self._wl_by_series[self._series[self._series_index].series_uid] = self._current_wl
        self._render_current()

    # -- cache / prefetch --------------------------------------------------------

    def _cache_get(self, key: Tuple[str, int]) -> Optional[SliceData]:
        data = self._cache.get(key)
        if data is not None:
            self._cache.move_to_end(key)
        return data

    def _cache_put(self, key: Tuple[str, int], data: SliceData):
        self._cache[key] = data
        self._cache.move_to_end(key)
        while len(self._cache) > _SLICE_CACHE_MAX:
            self._cache.popitem(last=False)

    def _prefetch_neighbors(self, index: int):
        for offset in range(1, _PREFETCH_RADIUS + 1):
            for neighbor in (index + offset, index - offset):
                if not (0 <= neighbor < len(self._slice_keys)):
                    continue
                key = self._slice_keys[neighbor]
                if key in self._cache or key in self._pending_loads:
                    continue
                self._pending_loads.add(key)
                self._pool.start(_SliceLoadTask(self._bridge, key[0], key[1]))

    def _on_slice_loaded(self, path: str, frame: int, data: SliceData):
        key = (path, frame)
        self._pending_loads.discard(key)
        if key not in self._cache:
            self._cache_put(key, data)
        # If the user scrolled onto this slice while it was loading, render it.
        if self._slice_keys and self._slice_keys[self._slice_index] == key:
            self._render_current()

    # -- overlay / misc ------------------------------------------------------------

    def _refresh_overlay(self):
        if self._series_index < 0 or not self._slice_keys:
            self.canvas.overlay_lines = {"tl": [], "tr": [], "bl": [], "br": []}
            self.canvas.update()
            return
        series = self._series[self._series_index]
        data = self._cache.get(self._slice_keys[self._slice_index])
        center, width = self._current_wl
        self.canvas.overlay_lines = {
            "tl": [
                series.patient_name or "Unknown patient",
                f"ID: {series.patient_id}" if series.patient_id else "",
                series.study_description or series.study_date or "",
            ],
            "tr": [f"Im: {self._slice_index + 1}/{len(self._slice_keys)}"],
            "bl": [
                f"Se {series.series_number}: {series.description}".strip(),
                f"{data.cols}×{data.rows}" if data and not data.error else "",
            ],
            "br": (
                ["RGB", f"Zoom: {self.canvas.zoom * 100.0:.0f}%"]
                if data is not None and data.is_color
                else [
                    f"W: {width:.0f}  L: {center:.0f}",
                    f"Zoom: {self.canvas.zoom * 100.0:.0f}%",
                ]
            ),
        }
        self.canvas.update()

    def _set_tool(self, tool: str):
        self.canvas.active_tool = tool

    def _open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Open DICOM folder", self._media_root or "", QFileDialog.ShowDirsOnly
        )
        if folder:
            self._start_scan(folder)

    def _show_about(self):
        QMessageBox.information(
            self,
            f"About {VIEWER_DISPLAY_NAME}",
            f"{VIEWER_DISPLAY_NAME} {VIEWER_VERSION}\n\n"
            "Portable DICOM viewer for AI-PACS patient media.\n"
            "Basic viewing only: series list, scroll, zoom, pan, window/level.\n\n"
            "Wheel: scroll slices · Ctrl+wheel: zoom · Left-drag: active tool\n"
            "Middle-drag: pan · Right-drag: zoom · Double-click: fit\n"
            "Keys: ←/→ or ↑/↓ slices · F fit · 1 actual size · R reset W/L",
        )

    # -- keyboard --------------------------------------------------------------

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        key = event.key()
        if key in (Qt.Key_Down, Qt.Key_Right):
            self._step_slice(1)
        elif key in (Qt.Key_Up, Qt.Key_Left):
            self._step_slice(-1)
        elif key == Qt.Key_PageDown:
            self._step_slice(10)
        elif key == Qt.Key_PageUp:
            self._step_slice(-10)
        elif key == Qt.Key_Home:
            self._show_slice(0)
        elif key == Qt.Key_End:
            self._show_slice(len(self._slice_keys) - 1)
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="AIPacsLiteViewer", add_help=True)
    parser.add_argument(
        "--import-folder", dest="import_folder", default=None,
        help="Folder containing DICOM images / DICOMDIR (media root).",
    )
    parser.add_argument(
        "folder", nargs="?", default=None,
        help="Positional alternative to --import-folder.",
    )
    args, _unknown = parser.parse_known_args(argv)
    return args


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(VIEWER_DISPLAY_NAME)
    app.setApplicationVersion(VIEWER_VERSION)
    app.setOrganizationName("AI-PACS")

    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    media_root = discover_media_root(args.import_folder or args.folder, exe_dir=exe_dir)

    window = LiteViewerWindow(media_root)
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
