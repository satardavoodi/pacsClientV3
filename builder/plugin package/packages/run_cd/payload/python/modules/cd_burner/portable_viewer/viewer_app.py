"""AI-PACS Lite Viewer — main window and application entry.

A deliberately small, dependency-light 2D DICOM viewer for patient CD/DVD
media. v1.1: two-view layout by default, cross-pane reference lines and a
ruler tool — plus the basics (series list, stack scrolling, zoom, pan,
window/level). Nothing else (no MPR / AI / reporting), and it must stay
that way — this ships on read-only media.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import (
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QDrag,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
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
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

if __package__:  # package-relative (dev run inside AI-PACS repo)
    from .viewer_meta import VIEWER_DISPLAY_NAME, VIEWER_VERSION
    from .media_scan import (
        ScanResult,
        SeriesRecord,
        discover_media_root,
        load_media_info,
        scan_media,
    )
    from .render import (
        SliceData,
        load_slice,
        peek_frame_count,
        reference_line_segment,
        ruler_length_label,
        slice_to_qimage,
    )
    from .welcome import WelcomePage
else:  # standalone build / direct script execution
    from viewer_meta import VIEWER_DISPLAY_NAME, VIEWER_VERSION  # type: ignore
    from media_scan import (  # type: ignore
        ScanResult,
        SeriesRecord,
        discover_media_root,
        load_media_info,
        scan_media,
    )
    from render import (  # type: ignore
        SliceData,
        load_slice,
        peek_frame_count,
        reference_line_segment,
        ruler_length_label,
        slice_to_qimage,
    )
    from welcome import WelcomePage  # type: ignore

logger = logging.getLogger(__name__)

_SLICE_CACHE_MAX = 96          # decoded slices kept in memory (LRU, shared)
_PREFETCH_RADIUS = 2           # neighbour slices loaded in the background
_SERIES_MIME = "application/x-aipacs-series-index"  # drag payload: series index

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
# Series list (drag source)
# ---------------------------------------------------------------------------

def build_series_mime(series_index: int) -> QMimeData:
    """MIME payload carrying a series index (shared by drag + tests)."""
    mime = QMimeData()
    mime.setData(_SERIES_MIME, str(int(series_index)).encode("ascii"))
    return mime


class SeriesListWidget(QListWidget):
    """Series list with click/drag fully separated.

    Mouse-press never loads anything (that was the bug: the default
    selection-changed-on-press fired the load before a drag could start).
    Instead:

    * **Single click** (press + release on the same row, no movement) →
      emits ``seriesClicked`` → the window loads it into the ACTIVE pane.
    * **Drag** (button held + moved past the platform drag threshold) →
      a ``QDrag`` with a ghost-thumbnail preview; the import happens ONLY in
      a pane's ``dropEvent`` at the release position. No click-load fires,
      and panes the cursor merely passes over receive nothing.
    """

    seriesClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # We drive the drag ourselves so we control the threshold and the
        # click/drag split — Qt's own DragOnly machinery starts on press.
        self.setDragEnabled(False)
        self.setDragDropMode(QListWidget.NoDragDrop)
        self.setSelectionMode(QListWidget.SingleSelection)

        self.preview_provider: Callable[[int], Optional[QPixmap]] = lambda index: None

        self._press_pos: Optional[QPoint] = None
        self._press_index: Optional[int] = None
        self._dragging: bool = False

    def mimeTypes(self):  # noqa: N802 — Qt override
        return [_SERIES_MIME]

    # -- helpers --------------------------------------------------------------

    def _series_index_at(self, pos: QPoint) -> Optional[int]:
        item = self.itemAt(pos)
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        return None if index is None else int(index)

    def _exec_drag(self, drag: QDrag):  # test seam (exec is modal)
        drag.exec(Qt.CopyAction)

    def _text_chip(self, series_index: int) -> QPixmap:
        item = self.currentItem()
        text = item.text().strip() if item is not None else f"Series {series_index}"
        font = QFont(self.font())
        font.setBold(True)
        metrics = self.fontMetrics()
        width = min(260, max(120, metrics.horizontalAdvance(text) + 24))
        pixmap = QPixmap(width, 34)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QBrush(QColor(31, 41, 59, 235)))
        painter.setPen(QPen(QColor("#3b82f6"), 1))
        painter.drawRoundedRect(pixmap.rect().adjusted(0, 0, -1, -1), 7, 7)
        painter.setPen(QPen(QColor("#e8eef4")))
        painter.setFont(font)
        painter.drawText(pixmap.rect().adjusted(10, 0, -8, 0),
                         Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.end()
        return pixmap

    def _start_series_drag(self, series_index: int):
        drag = QDrag(self)
        drag.setMimeData(build_series_mime(series_index))
        pixmap: Optional[QPixmap] = None
        try:
            pixmap = self.preview_provider(series_index)
        except Exception:
            pixmap = None
        if pixmap is None or pixmap.isNull():
            pixmap = self._text_chip(series_index)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        self._exec_drag(drag)
        # Drag finished (dropped or cancelled) — the OS consumed the release,
        # so reset here; never emit a click for a drag.
        self._press_pos = None
        self._press_index = None
        self._dragging = False

    # -- mouse handling (click vs drag) ----------------------------------------

    def mousePressEvent(self, event):  # noqa: N802 — Qt override
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self._press_index = self._series_index_at(self._press_pos)
            self._dragging = False
        super().mousePressEvent(event)  # selection highlight only — no load

    def mouseMoveEvent(self, event):  # noqa: N802 — Qt override
        if (
            (event.buttons() & Qt.LeftButton)
            and self._press_pos is not None
            and self._press_index is not None
            and not self._dragging
        ):
            moved = (event.position().toPoint() - self._press_pos).manhattanLength()
            if moved >= QApplication.startDragDistance():
                self._dragging = True
                self._start_series_drag(self._press_index)
            return  # suppress base rubber-band / auto-scroll while pressed
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 — Qt override
        was_dragging = self._dragging
        press_index = self._press_index
        release_index = (
            self._series_index_at(event.position().toPoint())
            if self._press_pos is not None else None
        )
        self._press_pos = None
        self._press_index = None
        self._dragging = False
        super().mouseReleaseEvent(event)
        # A genuine click = no drag started AND released on the same row.
        if (
            event.button() == Qt.LeftButton
            and not was_dragging
            and press_index is not None
            and release_index == press_index
        ):
            self.seriesClicked.emit(press_index)


# ---------------------------------------------------------------------------
# Image canvas (one viewport pane)
# ---------------------------------------------------------------------------

class ImageCanvas(QWidget):
    """Paints one slice with zoom/pan, overlays, reference line and rulers.

    Interaction: wheel = scroll slices · Ctrl+wheel = zoom · left-drag =
    active tool (W/L, Pan, Zoom or Ruler) · middle-drag = pan ·
    right-drag = zoom · double-click = fit. Clicking activates the pane.
    """

    TOOL_WL = "wl"
    TOOL_PAN = "pan"
    TOOL_ZOOM = "zoom"
    TOOL_RULER = "ruler"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True)            # series drag-and-drop target
        self._drop_hover = False

        self._image: Optional[QImage] = None
        self._zoom: float = 1.0
        self._pan: QPointF = QPointF(0.0, 0.0)
        self._fit_pending = True

        self.active_tool: str = self.TOOL_WL
        self.is_active: bool = False           # active-pane highlight
        self.overlay_lines: Dict[str, List[str]] = {"tl": [], "tr": [], "bl": [], "br": []}
        self.empty_text: str = "—"
        self.reference_line: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
        self.rulers: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = []
        self._ruler_start: Optional[Tuple[float, float]] = None
        self._ruler_current: Optional[Tuple[float, float]] = None

        # Callbacks wired by the window
        self.on_scroll: Callable[[int], None] = lambda delta: None
        self.on_wl_drag: Callable[[int, int], None] = lambda dx, dy: None
        self.on_interaction_changed: Callable[[], None] = lambda: None
        self.on_activated: Callable[[], None] = lambda: None
        self.on_ruler_done: Callable[[Tuple[float, float], Tuple[float, float]], None] = (
            lambda p1, p2: None
        )
        self.on_series_dropped: Callable[[int], None] = lambda series_index: None

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

    # -- coordinate transforms ------------------------------------------------

    def _view_geometry(self) -> Optional[Tuple[float, float, float]]:
        """(scale, offset_x, offset_y): widget = image*scale + offset."""
        if self._image is None or self._image.width() == 0:
            return None
        if self._fit_pending:
            self._apply_fit()
        x = (self.width() - self._image.width() * self._zoom) / 2.0 + self._pan.x()
        y = (self.height() - self._image.height() * self._zoom) / 2.0 + self._pan.y()
        return self._zoom, x, y

    def image_to_widget(self, u: float, v: float) -> Optional[Tuple[float, float]]:
        geometry = self._view_geometry()
        if geometry is None:
            return None
        scale, ox, oy = geometry
        return u * scale + ox, v * scale + oy

    def widget_to_image(self, x: float, y: float) -> Optional[Tuple[float, float]]:
        geometry = self._view_geometry()
        if geometry is None:
            return None
        scale, ox, oy = geometry
        if scale <= 0:
            return None
        return (x - ox) / scale, (y - oy) / scale

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
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
            self._paint_border(painter)
            painter.end()
            return

        geometry = self._view_geometry()
        if geometry is None:
            painter.end()
            return
        scale, ox, oy = geometry

        painter.setRenderHint(QPainter.SmoothPixmapTransform, self._zoom < 4.0)
        painter.save()
        painter.translate(ox, oy)
        painter.scale(scale, scale)
        painter.drawImage(0, 0, self._image)
        painter.restore()

        self._paint_reference_line(painter)
        self._paint_rulers(painter)
        self._paint_overlay(painter)
        self._paint_border(painter)
        painter.end()

    def _paint_border(self, painter: QPainter):
        if self._drop_hover:
            # Highlight + hint while a series is dragged over this pane
            painter.setPen(QPen(QColor("#22d3ee"), 3))
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))
            painter.setPen(QPen(QColor("#22d3ee")))
            font = QFont(self.font())
            font.setPointSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                self.rect(), Qt.AlignBottom | Qt.AlignHCenter, "Drop series here  "
            )
            return
        color = QColor("#3b82f6") if self.is_active else QColor("#2a323c")
        painter.setPen(QPen(color, 2))
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def _paint_reference_line(self, painter: QPainter):
        if self.reference_line is None:
            return
        a = self.image_to_widget(*self.reference_line[0])
        b = self.image_to_widget(*self.reference_line[1])
        if a is None or b is None:
            return
        pen = QPen(QColor("#22d3ee"), 1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))

    def _paint_rulers(self, painter: QPainter):
        items = list(self.rulers)
        if self._ruler_start and self._ruler_current:
            items.append((self._ruler_start, self._ruler_current, ""))
        if not items:
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont(self.font())
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        for p1, p2, label in items:
            a = self.image_to_widget(*p1)
            b = self.image_to_widget(*p2)
            if a is None or b is None:
                continue
            painter.setPen(QPen(QColor("#facc15"), 2))
            painter.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
            for x, y in (a, b):
                painter.drawEllipse(QPointF(x, y), 3, 3)
            if label:
                mid_x = (a[0] + b[0]) / 2 + 8
                mid_y = (a[1] + b[1]) / 2 - 8
                painter.setPen(QPen(QColor(0, 0, 0, 200)))
                painter.drawText(int(mid_x) + 1, int(mid_y) + 1, label)
                painter.setPen(QPen(QColor("#fde047")))
                painter.drawText(int(mid_x), int(mid_y), label)

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
        self.on_activated()
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_by(1.15 if delta > 0 else 1.0 / 1.15)
        else:
            self.on_scroll(-1 if delta > 0 else 1)
        event.accept()

    def mouseDoubleClickEvent(self, event):  # noqa: N802 — Qt override
        self.fit()
        self.on_interaction_changed()

    def mousePressEvent(self, event):  # noqa: N802 — Qt override
        self.on_activated()
        self._drag_button = event.button()
        self._drag_last = event.position().toPoint()
        if (
            self._drag_button == Qt.LeftButton
            and self.active_tool == self.TOOL_RULER
            and self._image is not None
        ):
            point = self.widget_to_image(event.position().x(), event.position().y())
            if point is not None:
                self._ruler_start = point
                self._ruler_current = point
                self.update()
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 — Qt override
        if self._ruler_start and self._ruler_current and event.button() == Qt.LeftButton:
            start, end = self._ruler_start, self._ruler_current
            self._ruler_start = None
            self._ruler_current = None
            dx = abs(start[0] - end[0])
            dy = abs(start[1] - end[1])
            if dx > 2 or dy > 2:  # ignore accidental clicks
                self.on_ruler_done(start, end)
            self.update()
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

        if tool == self.TOOL_RULER and button == Qt.LeftButton:
            if self._ruler_start is not None:
                point = self.widget_to_image(event.position().x(), event.position().y())
                if point is not None:
                    self._ruler_current = point
                    self.update()
        elif tool == self.TOOL_PAN:
            self._fit_pending = False
            self._pan += QPointF(dx, dy)
            self.update()
        elif tool == self.TOOL_ZOOM:
            self.zoom_by(1.0 + (-dy) * 0.01)
        else:  # window/level
            self.on_wl_drag(dx, dy)
        self.on_interaction_changed()
        event.accept()

    # -- drag-and-drop (series → pane) ----------------------------------------

    def dragEnterEvent(self, event):  # noqa: N802 — Qt override
        if event.mimeData().hasFormat(_SERIES_MIME):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self._drop_hover = True
            self.update()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802 — Qt override
        if event.mimeData().hasFormat(_SERIES_MIME):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):  # noqa: N802 — Qt override
        self._drop_hover = False
        self.update()

    def dropEvent(self, event):  # noqa: N802 — Qt override
        self._drop_hover = False
        data = event.mimeData().data(_SERIES_MIME)
        if data.isEmpty():
            event.ignore()
            self.update()
            return
        try:
            series_index = int(bytes(data).decode("ascii"))
        except Exception:
            event.ignore()
            self.update()
            return
        event.setDropAction(Qt.CopyAction)
        event.accept()
        self.on_activated()
        self.on_series_dropped(series_index)
        self.update()


# ---------------------------------------------------------------------------
# Pane state
# ---------------------------------------------------------------------------

class PaneState:
    """Per-viewport series/slice/W-L/ruler state."""

    def __init__(self):
        self.series_index: int = -1
        self.slice_keys: List[Tuple[str, int]] = []
        self.slice_index: int = 0
        self.wl: Tuple[float, float] = (0.0, 0.0)
        self.rulers: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = []

    def clear(self):
        self.series_index = -1
        self.slice_keys = []
        self.slice_index = 0
        self.wl = (0.0, 0.0)
        self.rulers = []


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class LiteViewerWindow(QMainWindow):
    PANE_COUNT = 2  # default layout: 2-view

    def __init__(self, media_root: Optional[str] = None, show_welcome: bool = True):
        super().__init__()
        self.setWindowTitle(f"{VIEWER_DISPLAY_NAME} {VIEWER_VERSION}")
        self.resize(1240, 780)
        self._show_welcome = bool(show_welcome)

        self._bridge = _Bridge()
        self._bridge.scan_done.connect(self._on_scan_done)
        self._bridge.slice_loaded.connect(self._on_slice_loaded)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)

        self._media_root: Optional[str] = media_root
        self._scan: Optional[ScanResult] = None
        self._series: List[SeriesRecord] = []
        self._cache: "OrderedDict[Tuple[str, int], SliceData]" = OrderedDict()
        self._pending_loads: set = set()
        self._wl_by_series: Dict[str, Tuple[float, float]] = {}

        self.pane_states: List[PaneState] = [PaneState() for _ in range(self.PANE_COUNT)]
        self.canvases: List[ImageCanvas] = []
        self.active_pane: int = 0
        self._two_view: bool = True            # DEFAULT: 2-view layout
        self._reference_lines_on: bool = True  # required tool — on by default

        self._build_ui()
        self._set_active_pane(0)
        if media_root:
            self._start_scan(media_root)
        else:
            self.canvases[0].empty_text = (
                "No DICOM media detected.\n\nUse  Open Folder…  to select a "
                "folder that contains DICOM images or a DICOMDIR."
            )
            self.canvases[0].update()

    # -- legacy single-pane accessors (active pane) ----------------------------

    @property
    def canvas(self) -> ImageCanvas:
        return self.canvases[self.active_pane]

    @property
    def _slice_keys(self) -> List[Tuple[str, int]]:
        return self.pane_states[self.active_pane].slice_keys

    @property
    def _slice_index(self) -> int:
        return self.pane_states[self.active_pane].slice_index

    @property
    def _series_index(self) -> int:
        return self.pane_states[self.active_pane].series_index

    @property
    def _current_wl(self) -> Tuple[float, float]:
        return self.pane_states[self.active_pane].wl

    # -- UI construction -----------------------------------------------------

    def _build_ui(self):
        self.setStyleSheet(_DARK_QSS)

        # Central widgets FIRST — toolbar actions connect to them.
        self.series_list = SeriesListWidget(self)
        self.series_list.setMinimumWidth(220)
        self.series_list.setMaximumWidth(420)
        # Load on a genuine CLICK only (not on press/selection-change — that
        # was loading the series the moment a drag began). Drag is handled by
        # the list itself and imports only on a pane's drop.
        self.series_list.seriesClicked.connect(self._on_series_clicked)
        self.series_list.preview_provider = self._series_drag_pixmap

        for index in range(self.PANE_COUNT):
            canvas = ImageCanvas(self)
            canvas.on_scroll = (lambda delta, i=index: self._step_slice_pane(i, delta))
            canvas.on_wl_drag = (lambda dx, dy, i=index: self._adjust_wl_pane(i, dx, dy))
            canvas.on_interaction_changed = (lambda i=index: self._refresh_overlay_pane(i))
            canvas.on_activated = (lambda i=index: self._set_active_pane(i))
            canvas.on_ruler_done = (lambda p1, p2, i=index: self._add_ruler(i, p1, p2))
            canvas.on_series_dropped = (lambda series_index, i=index: self._on_series_dropped(i, series_index))
            canvas.empty_text = "Click or drag a series here"
            self.canvases.append(canvas)

        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(toolbar)

        open_action = QAction("Open Folder…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_folder_dialog)
        toolbar.addAction(open_action)
        toolbar.addSeparator()

        # Layout selection (default: 2 views)
        layout_group = QActionGroup(self)
        layout_group.setExclusive(True)
        self.one_view_action = QAction("1 View", self)
        self.one_view_action.setCheckable(True)
        self.two_view_action = QAction("2 Views", self)
        self.two_view_action.setCheckable(True)
        self.two_view_action.setChecked(True)
        for action, two in ((self.one_view_action, False), (self.two_view_action, True)):
            layout_group.addAction(action)
            toolbar.addAction(action)
            action.triggered.connect(lambda _=False, t=two: self._set_two_view(t))
        toolbar.addSeparator()

        # Tools: W/L · Pan · Zoom · Ruler (one active at a time)
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_actions = {}
        for key, label, tip in (
            (ImageCanvas.TOOL_WL, "W/L", "Left-drag adjusts window/level"),
            (ImageCanvas.TOOL_PAN, "Pan", "Left-drag pans the image"),
            (ImageCanvas.TOOL_ZOOM, "Zoom", "Left-drag zooms the image"),
            (ImageCanvas.TOOL_RULER, "Ruler", "Left-drag measures distance (mm when calibrated)"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setToolTip(tip)
            action.triggered.connect(lambda _=False, k=key: self._set_tool(k))
            self._tool_group.addAction(action)
            toolbar.addAction(action)
            self._tool_actions[key] = action
        self._tool_actions[ImageCanvas.TOOL_WL].setChecked(True)

        clear_action = QAction("Clear", self)
        clear_action.setToolTip("Remove measurements from the active view")
        clear_action.triggered.connect(self._clear_rulers)
        toolbar.addAction(clear_action)
        toolbar.addSeparator()

        self.ref_lines_action = QAction("Ref Lines", self)
        self.ref_lines_action.setCheckable(True)
        self.ref_lines_action.setChecked(True)
        self.ref_lines_action.setToolTip(
            "Show the other view's slice position as a dashed line (same frame of reference)"
        )
        self.ref_lines_action.toggled.connect(self._on_ref_lines_toggled)
        toolbar.addAction(self.ref_lines_action)
        toolbar.addSeparator()

        fit_action = QAction("Fit", self)
        fit_action.setShortcut("F")
        fit_action.triggered.connect(lambda: self.canvas.fit())
        toolbar.addAction(fit_action)

        actual_action = QAction("1:1", self)
        actual_action.setShortcut("1")
        actual_action.triggered.connect(lambda: self.canvas.actual_size())
        toolbar.addAction(actual_action)

        reset_action = QAction("Reset W/L", self)
        reset_action.setShortcut("R")
        reset_action.triggered.connect(self._reset_wl)
        toolbar.addAction(reset_action)
        toolbar.addSeparator()

        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        toolbar.addAction(about_action)

        # Layout: series list (left) + pane splitter with slider (right)
        self.pane_splitter = QSplitter(Qt.Horizontal, self)
        for canvas in self.canvases:
            self.pane_splitter.addWidget(canvas)
        self.pane_splitter.setChildrenCollapsible(False)

        self.slice_slider = QSlider(Qt.Horizontal, self)
        self.slice_slider.setRange(0, 0)
        self.slice_slider.valueChanged.connect(self._on_slider_changed)
        self.slice_label = QLabel("–/–", self)
        self.slice_label.setObjectName("sliceLabel")

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(8, 4, 8, 6)
        slider_row.addWidget(self.slice_slider, 1)
        slider_row.addWidget(self.slice_label)

        # Imaging-center banner (from AIPACS_MEDIA_INFO.json on the media)
        self.center_header = QLabel("", self)
        self.center_header.setAlignment(Qt.AlignCenter)
        self.center_header.setWordWrap(True)
        self.center_header.setStyleSheet(
            "background-color: #1d2735; color: #dbe7f5; font-size: 13px;"
            "font-weight: 600; padding: 6px 10px;"
            "border-bottom: 1px solid #2f5d9e;"
        )
        self.center_header.setVisible(False)

        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.center_header)
        right_layout.addWidget(self.pane_splitter, 1)
        right_layout.addLayout(slider_row)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.series_list)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 980])

        # Welcome page (branded landing) → viewer body, in a stack. The
        # media scan keeps running underneath the welcome page, so the
        # series are usually ready the moment the user clicks through.
        self.welcome_page = WelcomePage(self)
        self.welcome_page.proceed.connect(self._leave_welcome)
        self._toolbar = toolbar
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.welcome_page)   # index 0
        self.stack.addWidget(splitter)            # index 1
        self.setCentralWidget(self.stack)

        if self._show_welcome:
            self.stack.setCurrentIndex(0)
            self._toolbar.setVisible(False)
        else:
            self.stack.setCurrentIndex(1)

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready")

    def _leave_welcome(self):
        self._toolbar.setVisible(True)
        self.stack.setCurrentIndex(1)
        self.canvas.setFocus()

    # -- layout / active pane ---------------------------------------------------

    def _set_two_view(self, two: bool):
        self._two_view = two
        self.canvases[1].setVisible(two)
        if not two and self.active_pane == 1:
            self._set_active_pane(0)
        self._update_reference_lines()

    def _set_active_pane(self, index: int):
        if not (0 <= index < len(self.canvases)):
            return
        self.active_pane = index
        for n, canvas in enumerate(self.canvases):
            changed = canvas.is_active != (n == index)
            canvas.is_active = (n == index)
            if changed:
                canvas.update()
        self._sync_slider_to_active()
        self._sync_list_selection(self.pane_states[index].series_index)

    def _set_tool(self, tool: str):
        for canvas in self.canvases:
            canvas.active_tool = tool

    def _on_ref_lines_toggled(self, checked: bool):
        self._reference_lines_on = checked
        self._update_reference_lines()

    # -- scanning ------------------------------------------------------------

    def _apply_media_info(self, root: str):
        """Show the imaging-center banner when the media declares one."""
        try:
            center = (load_media_info(root) or {}).get("center") or {}
        except Exception:
            center = {}
        parts = []
        if center.get("name"):
            parts.append(str(center["name"]))
        if center.get("address"):
            parts.append(str(center["address"]))
        if center.get("phone"):
            parts.append(f"☎ {center['phone']}")
        if parts:
            self.center_header.setText("  ·  ".join(parts))
            self.center_header.setVisible(True)
            if center.get("name"):
                self.setWindowTitle(
                    f"{VIEWER_DISPLAY_NAME} {VIEWER_VERSION} — {center['name']}"
                )
        else:
            self.center_header.clear()
            self.center_header.setVisible(False)
            self.setWindowTitle(f"{VIEWER_DISPLAY_NAME} {VIEWER_VERSION}")
        self.welcome_page.set_center_identity(center)

    def _start_scan(self, root: str):
        self._media_root = root
        self._apply_media_info(root)
        self.canvases[0].empty_text = f"Scanning media…\n\n{root}"
        for state in self.pane_states:
            state.clear()
        for canvas in self.canvases:
            canvas.set_image(None)
            canvas.rulers = []
            canvas.reference_line = None
        self.series_list.clear()
        self.statusBar().showMessage(f"Scanning {root} …")
        self._pool.start(_ScanTask(self._bridge, root))

    def _on_scan_done(self, result: ScanResult):
        self._scan = result
        self._series = list(result.series)
        self._populate_series_list()

        if not self._series:
            message = result.errors[0] if result.errors else "No DICOM images found."
            self.canvases[0].empty_text = (
                f"{message}\n\nUse  Open Folder…  to select a folder that contains "
                "DICOM images or a DICOMDIR."
            )
            self.canvases[0].set_image(None)
            self.statusBar().showMessage(message)
            return

        patients = ", ".join(result.patient_labels()[:3])
        self.statusBar().showMessage(
            f"{len(self._series)} series · {result.total_images} images · "
            f"{patients} · source: {result.source}"
        )
        # Default 2-view: first series left, second (when present) right.
        self._select_series_for_pane(0, 0)
        if len(self._series) > 1 and self._two_view:
            self._select_series_for_pane(1, 1)
        self._set_active_pane(0)

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

    def _on_series_clicked(self, series_index: int):
        """A genuine single click → load into the ACTIVE pane."""
        if not (0 <= series_index < len(self._series)):
            return
        self._select_series_for_pane(self.active_pane, series_index, from_list=True)

    def _on_series_dropped(self, pane: int, series_index: int):
        """A series was dragged from the list and dropped onto `pane`."""
        if not (0 <= series_index < len(self._series)):
            return
        self._set_active_pane(pane)
        self._select_series_for_pane(pane, series_index)

    def _series_drag_pixmap(self, series_index: int) -> Optional[QPixmap]:
        """Ghost preview shown under the cursor while dragging a series:
        the series' first slice thumbnail plus a label band."""
        if not (0 <= series_index < len(self._series)):
            return None
        series = self._series[series_index]
        thumb: Optional[QPixmap] = None
        try:
            key = (series.instances[0].path, 0)
            data = self._cache_get(key) or load_slice(key[0], key[1])
            if not data.error:
                image = slice_to_qimage(data, data.default_center, data.default_width)
                thumb = QPixmap.fromImage(image).scaled(
                    132, 132, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
        except Exception:
            thumb = None

        label = series.display_label()
        width = 152
        thumb_h = thumb.height() if thumb is not None else 0
        height = thumb_h + 30 + (8 if thumb is not None else 0)
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QBrush(QColor(17, 24, 38, 235)))
        painter.setPen(QPen(QColor("#3b82f6"), 2))
        painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 9, 9)
        if thumb is not None:
            painter.drawPixmap((width - thumb.width()) // 2, 6, thumb)
        font = QFont(self.font())
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#dbe7f5")))
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(label, Qt.ElideRight, width - 16)
        painter.drawText(
            pixmap.rect().adjusted(8, height - 26, -8, -4),
            Qt.AlignVCenter | Qt.AlignHCenter,
            elided,
        )
        painter.end()
        return pixmap

    def _select_series(self, index: int, from_list: bool = False):
        """Legacy single-pane API: loads into the ACTIVE pane."""
        self._select_series_for_pane(self.active_pane, index, from_list=from_list)

    def _select_series_for_pane(self, pane: int, index: int, from_list: bool = False):
        if not (0 <= index < len(self._series)):
            return
        state = self.pane_states[pane]
        state.series_index = index
        state.rulers = []
        self.canvases[pane].rulers = []
        series = self._series[index]

        if series.image_count == 1:
            frames = peek_frame_count(series.instances[0].path)
            if frames > 1:
                state.slice_keys = [(series.instances[0].path, f) for f in range(frames)]
            else:
                state.slice_keys = [(series.instances[0].path, 0)]
        else:
            state.slice_keys = [(inst.path, 0) for inst in series.instances]

        state.slice_index = 0
        state.wl = self._wl_by_series.get(series.series_uid, (0.0, 0.0))

        if not from_list and pane == self.active_pane:
            self._sync_list_selection(index)

        self._show_slice_pane(pane, 0, keep_view=False)
        if pane == self.active_pane:
            self._sync_slider_to_active()

    def _sync_list_selection(self, series_index: int):
        if series_index < 0:
            return
        for row in range(self.series_list.count()):
            item = self.series_list.item(row)
            if item.data(Qt.UserRole) == series_index:
                self.series_list.blockSignals(True)
                self.series_list.setCurrentItem(item)
                self.series_list.blockSignals(False)
                return

    def _step_slice(self, delta: int):
        self._step_slice_pane(self.active_pane, delta)

    def _step_slice_pane(self, pane: int, delta: int):
        state = self.pane_states[pane]
        if not state.slice_keys:
            return
        new_index = max(0, min(len(state.slice_keys) - 1, state.slice_index + delta))
        if new_index != state.slice_index:
            self._show_slice_pane(pane, new_index)

    def _on_slider_changed(self, value: int):
        state = self.pane_states[self.active_pane]
        if 0 <= value < len(state.slice_keys) and value != state.slice_index:
            self._show_slice_pane(self.active_pane, value)

    def _show_slice(self, index: int, keep_view: bool = True):
        self._show_slice_pane(self.active_pane, index, keep_view=keep_view)

    def _show_slice_pane(self, pane: int, index: int, keep_view: bool = True):
        state = self.pane_states[pane]
        if not (0 <= index < len(state.slice_keys)):
            return
        state.slice_index = index
        # Measurements belong to a specific image — drop them on slice change.
        if state.rulers:
            state.rulers = []
            self.canvases[pane].rulers = []
        key = state.slice_keys[index]
        data = self._cache_get(key)
        if data is None:
            data = load_slice(key[0], key[1])
            self._cache_put(key, data)

        if not data.error and (state.wl[1] or 0) <= 0:
            state.wl = (data.default_center, data.default_width)
        if state.series_index >= 0 and not data.error:
            self._wl_by_series[self._series[state.series_index].series_uid] = state.wl

        self._render_pane(pane, keep_view=keep_view)
        if pane == self.active_pane:
            self._sync_slider_to_active()
        self._prefetch_neighbors(state, index)
        self._update_reference_lines()

    def _current_slice_data(self, pane: int) -> Optional[SliceData]:
        state = self.pane_states[pane]
        if not state.slice_keys:
            return None
        return self._cache.get(state.slice_keys[state.slice_index])

    def _render_pane(self, pane: int, keep_view: bool = True):
        state = self.pane_states[pane]
        canvas = self.canvases[pane]
        data = self._current_slice_data(pane)
        if data is None:
            return
        if data.error:
            canvas.empty_text = data.error
            canvas.set_image(None)
        else:
            center, width = state.wl
            canvas.set_image(slice_to_qimage(data, center, width), keep_view=keep_view)
        self._refresh_overlay_pane(pane)

    def _render_current(self, keep_view: bool = True):
        self._render_pane(self.active_pane, keep_view=keep_view)

    def _sync_slider_to_active(self):
        state = self.pane_states[self.active_pane]
        total = len(state.slice_keys)
        self.slice_label.setText(f"{state.slice_index + 1}/{total}" if total else "–/–")
        self.slice_slider.blockSignals(True)
        self.slice_slider.setRange(0, max(0, total - 1))
        self.slice_slider.setValue(state.slice_index)
        self.slice_slider.blockSignals(False)

    # -- window/level ----------------------------------------------------------

    def _adjust_wl(self, dx: int, dy: int):
        self._adjust_wl_pane(self.active_pane, dx, dy)

    def _adjust_wl_pane(self, pane: int, dx: int, dy: int):
        state = self.pane_states[pane]
        data = self._current_slice_data(pane)
        if data is None or data.error or data.is_color:
            return
        center, width = state.wl
        span = max(abs(width), 1.0)
        width = max(1e-3, width + dx * span * 0.01)
        center = center + dy * span * 0.01
        state.wl = (center, width)
        if state.series_index >= 0:
            self._wl_by_series[self._series[state.series_index].series_uid] = state.wl
        self._render_pane(pane)

    def _reset_wl(self):
        state = self.pane_states[self.active_pane]
        data = self._current_slice_data(self.active_pane)
        if data is None or data.error:
            return
        state.wl = (data.default_center, data.default_width)
        if state.series_index >= 0:
            self._wl_by_series[self._series[state.series_index].series_uid] = state.wl
        self._render_pane(self.active_pane)

    # -- rulers ------------------------------------------------------------------

    def _add_ruler(self, pane: int, p1: Tuple[float, float], p2: Tuple[float, float]):
        data = self._current_slice_data(pane)
        if data is None or data.error:
            return
        label = ruler_length_label(data, p1, p2)
        state = self.pane_states[pane]
        state.rulers.append((p1, p2, label))
        self.canvases[pane].rulers = list(state.rulers)
        self.canvases[pane].update()

    def _clear_rulers(self):
        state = self.pane_states[self.active_pane]
        state.rulers = []
        self.canvases[self.active_pane].rulers = []
        self.canvases[self.active_pane].update()

    # -- reference lines -----------------------------------------------------------

    def _update_reference_lines(self):
        show = self._reference_lines_on and self._two_view
        slices = [self._current_slice_data(0), self._current_slice_data(1)]
        for pane in range(self.PANE_COUNT):
            canvas = self.canvases[pane]
            line = None
            if show:
                target = slices[pane]
                other = slices[1 - pane]
                if target is not None and other is not None and not target.error and not other.error:
                    line = reference_line_segment(target, other)
            if canvas.reference_line != line:
                canvas.reference_line = line
                canvas.update()

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

    def _prefetch_neighbors(self, state: PaneState, index: int):
        for offset in range(1, _PREFETCH_RADIUS + 1):
            for neighbor in (index + offset, index - offset):
                if not (0 <= neighbor < len(state.slice_keys)):
                    continue
                key = state.slice_keys[neighbor]
                if key in self._cache or key in self._pending_loads:
                    continue
                self._pending_loads.add(key)
                self._pool.start(_SliceLoadTask(self._bridge, key[0], key[1]))

    def _on_slice_loaded(self, path: str, frame: int, data: SliceData):
        key = (path, frame)
        self._pending_loads.discard(key)
        if key not in self._cache:
            self._cache_put(key, data)
        for pane, state in enumerate(self.pane_states):
            if state.slice_keys and state.slice_keys[state.slice_index] == key:
                self._render_pane(pane)
                self._update_reference_lines()

    # -- overlay / misc ------------------------------------------------------------

    def _refresh_overlay(self):
        self._refresh_overlay_pane(self.active_pane)

    def _refresh_overlay_pane(self, pane: int):
        state = self.pane_states[pane]
        canvas = self.canvases[pane]
        if state.series_index < 0 or not state.slice_keys:
            canvas.overlay_lines = {"tl": [], "tr": [], "bl": [], "br": []}
            canvas.update()
            return
        series = self._series[state.series_index]
        data = self._cache.get(state.slice_keys[state.slice_index])
        center, width = state.wl
        canvas.overlay_lines = {
            "tl": [
                series.patient_name or "Unknown patient",
                f"ID: {series.patient_id}" if series.patient_id else "",
                series.study_description or series.study_date or "",
            ],
            "tr": [f"Im: {state.slice_index + 1}/{len(state.slice_keys)}"],
            "bl": [
                f"Se {series.series_number}: {series.description}".strip(),
                f"{data.cols}×{data.rows}" if data and not data.error else "",
            ],
            "br": (
                ["RGB", f"Zoom: {canvas.zoom * 100.0:.0f}%"]
                if data is not None and data.is_color
                else [
                    f"W: {width:.0f}  L: {center:.0f}",
                    f"Zoom: {canvas.zoom * 100.0:.0f}%",
                ]
            ),
        }
        canvas.update()

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
            "Tools: stack scrolling, reference lines, ruler, window/level, zoom, pan.\n\n"
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
        "--selftest", action="store_true",
        help="Verify the frozen bundle (imports, Qt platform, codecs) and exit.",
    )
    parser.add_argument(
        "--no-welcome", dest="no_welcome", action="store_true",
        help="Skip the branded welcome page and open the viewer directly.",
    )
    parser.add_argument(
        "folder", nargs="?", default=None,
        help="Positional alternative to --import-folder.",
    )
    args, _unknown = parser.parse_known_args(argv)
    return args


def run_selftest() -> int:
    """Verify the (frozen) bundle is complete: imports, Qt platform plugin,
    image pipeline, DICOM codecs. Exit code 0 = OK. Used by the build script
    as a release gate — a bundle that cannot pass this must never ship.
    """
    import numpy as np

    report: List[str] = []
    try:
        # Qt platform must initialize (proves qwindows/qoffscreen shipped)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication(["selftest"])
        report.append("qt: ok")

        # Render pipeline (module-level imports already resolved render/
        # media_scan/viewer_meta — reaching here proves they shipped)
        data = SliceData(
            array=np.linspace(0, 100, 64, dtype=np.float32).reshape(8, 8),
            is_color=False, invert=False,
            default_center=50.0, default_width=100.0, rows=8, cols=8,
        )
        image = slice_to_qimage(data, 50.0, 100.0)
        assert image.width() == 8 and image.height() == 8
        report.append("render: ok")

        # DICOM + codec availability
        import pydicom  # noqa: F401
        report.append(f"pydicom: {pydicom.__version__}")
        for codec in ("pylibjpeg", "openjpeg", "rle", "libjpeg"):
            try:
                __import__(codec)
                report.append(f"codec {codec}: ok")
            except Exception as exc:
                report.append(f"codec {codec}: MISSING ({exc})")

        print("SELFTEST OK — " + " | ".join(report))
        return 0
    except Exception as exc:  # pragma: no cover — failure path
        import traceback

        print("SELFTEST FAILED: " + " | ".join(report))
        traceback.print_exc()
        try:  # leave evidence even for windowed builds (no console)
            import tempfile

            (Path(tempfile.gettempdir()) / "aipacs_lite_selftest_failed.txt").write_text(
                f"{exc}\n\n{traceback.format_exc()}", encoding="utf-8"
            )
        except Exception:
            pass
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parse_args(argv)

    if args.selftest:
        return run_selftest()

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(VIEWER_DISPLAY_NAME)
    app.setApplicationVersion(VIEWER_VERSION)
    app.setOrganizationName("AI-PACS")

    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    media_root = discover_media_root(args.import_folder or args.folder, exe_dir=exe_dir)

    window = LiteViewerWindow(media_root, show_welcome=not args.no_welcome)
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
