"""
Dual View Widget — Zone-based bilateral breast comparison.

Shows Left and Right breast views (both CC or both MLO) side by side.
The user selects a ZONE (Interior / Middle / Posterior) and the OTHER two
zones are shadowed on BOTH viewers simultaneously, letting the radiologist
compare symmetric breast regions with high focus.

Zones divide the breast (nipple → chest wall) into 3 equal portions:
    - Interior (1/3 closest to nipple)
    - Middle (central 1/3)
    - Posterior (1/3 closest to chest wall)
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy, QButtonGroup,
)


# ─── Constants ───────────────────────────────────────────────────────────────

SHADOW_COLOR = QColor(0, 0, 0, 160)          # Dark shadow overlay
SHADOW_GRADIENT_WIDTH = 30                     # Gradient transition width in pixels
ZONE_BORDER_COLOR = QColor(60, 180, 255, 200) # Bright border at zone boundary

# Zone definitions (fraction of total breast width from nipple side)
ZONE_INTERIOR = 'interior'   # 0% – 33% from nipple
ZONE_MIDDLE = 'middle'       # 33% – 66%
ZONE_POSTERIOR = 'posterior'  # 66% – 100% (chest wall)


class DualViewOverlay(QWidget):
    """
    Transparent overlay that shadows the non-selected zones.

    Given the active zone and the nipple/chest-wall orientation,
    darkens the two inactive zones on the image.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

        # Direction: +1 = nipple is on LEFT, chest wall on RIGHT
        #           -1 = nipple is on RIGHT, chest wall on LEFT
        self._direction: int = 1

        # Active zone (the zone that stays BRIGHT)
        self._active_zone: Optional[str] = None

    def set_direction(self, direction: int):
        """Set the nipple-to-chestwall direction."""
        self._direction = direction

    def set_active_zone(self, zone: Optional[str]):
        """Set which zone should be BRIGHT (the rest gets shadowed)."""
        self._active_zone = zone
        self.update()

    def clear(self):
        """Remove all shadows."""
        self._active_zone = None
        self.update()

    def paintEvent(self, event):
        if not self._active_zone:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # Determine the zone boundaries (in pixels from left edge)
        # Zone fractions from nipple side
        if self._direction > 0:
            # Nipple on LEFT → Interior=left 1/3, Middle=mid 1/3, Posterior=right 1/3
            zone_starts = {
                ZONE_INTERIOR: 0,
                ZONE_MIDDLE: w / 3.0,
                ZONE_POSTERIOR: 2 * w / 3.0,
            }
        else:
            # Nipple on RIGHT → Interior=right 1/3, Middle=mid 1/3, Posterior=left 1/3
            zone_starts = {
                ZONE_INTERIOR: 2 * w / 3.0,
                ZONE_MIDDLE: w / 3.0,
                ZONE_POSTERIOR: 0,
            }

        zone_width = w / 3.0

        # Shadow the zones that are NOT active
        for zone_name in [ZONE_INTERIOR, ZONE_MIDDLE, ZONE_POSTERIOR]:
            if zone_name == self._active_zone:
                continue

            zx = zone_starts[zone_name]

            # Draw gradient edges for smooth transition
            grad_w = min(SHADOW_GRADIENT_WIDTH, zone_width * 0.3)

            # Left gradient (entering the shadow)
            if zx > 0:
                grad = QLinearGradient(zx, 0, zx + grad_w, 0)
                grad.setColorAt(0.0, QColor(0, 0, 0, 0))
                grad.setColorAt(1.0, SHADOW_COLOR)
                painter.fillRect(int(zx), 0, int(grad_w), h, QBrush(grad))
                # Solid shadow after gradient
                painter.fillRect(int(zx + grad_w), 0, int(zone_width - grad_w), h, SHADOW_COLOR)
            else:
                # First zone from edge — no left gradient needed
                # Right gradient (exiting the shadow)
                solid_w = zone_width - grad_w
                painter.fillRect(int(zx), 0, int(solid_w), h, SHADOW_COLOR)
                grad = QLinearGradient(zx + solid_w, 0, zx + zone_width, 0)
                grad.setColorAt(0.0, SHADOW_COLOR)
                grad.setColorAt(1.0, QColor(0, 0, 0, 0))
                painter.fillRect(int(zx + solid_w), 0, int(grad_w), h, QBrush(grad))

        # Draw zone boundary lines for the active zone
        active_start = zone_starts[self._active_zone]
        pen = QPen(ZONE_BORDER_COLOR, 2)
        painter.setPen(pen)
        painter.drawLine(int(active_start), 0, int(active_start), h)
        painter.drawLine(int(active_start + zone_width), 0, int(active_start + zone_width), h)

        painter.end()


class DualViewPanel(QWidget):
    """
    A panel that holds a snapshot of one viewer and its zone overlay.
    """

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self._label = label

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Header label
        self._header = QLabel(label)
        self._header.setAlignment(Qt.AlignCenter)
        self._header.setStyleSheet(
            "color: #b0c4de; font-weight: bold; font-size: 13px; "
            "background: transparent; padding: 2px;"
        )
        layout.addWidget(self._header)

        # Container for the viewer snapshot + overlay
        self._container = QWidget()
        self._container.setStyleSheet("background: #000;")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._container, stretch=1)

        # Image label to show snapshot
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setScaledContents(True)
        self._image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._container_layout.addWidget(self._image_label)

        # Overlay (will be positioned on top of the viewer)
        self._overlay = DualViewOverlay(self._container)
        self._overlay.raise_()

        # Track state
        self._vtk_widget = None
        self._direction: int = 1

    def set_viewer_widget(self, vtk_widget):
        """Grab a screenshot of the viewer widget and display it."""
        self._vtk_widget = vtk_widget
        if vtk_widget is not None:
            try:
                pixmap = vtk_widget.grab()
                self._image_label.setPixmap(pixmap)
            except Exception:
                self._image_label.setText("(No image)")
            self._overlay.raise_()

    def set_direction(self, direction: int):
        """Set nipple direction."""
        self._direction = direction
        self._overlay.set_direction(direction)

    def set_active_zone(self, zone: Optional[str]):
        """Apply zone-based shadow."""
        self._overlay.set_active_zone(zone)

    def clear(self):
        """Remove shadow."""
        self._overlay.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep overlay covering the container
        self._overlay.setGeometry(self._container.geometry())


class DualViewWidget(QWidget):
    """
    Main Dual View comparison widget.

    Shows left and right breast views side-by-side with zone-based
    shadowing for symmetric assessment.

    The user selects Interior / Middle / Posterior and the other zones
    are shadowed on BOTH viewers simultaneously.
    """

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dual View — Bilateral Symmetry Comparison")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setMinimumSize(900, 550)
        self.resize(1200, 650)

        self._left_panel: Optional[DualViewPanel] = None
        self._right_panel: Optional[DualViewPanel] = None
        self._active_zone: Optional[str] = None

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # ─── Header ───
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)

        title = QLabel("⬡ Dual View — Bilateral Symmetry")
        title.setStyleSheet("color: #60a5fa; font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        close_btn = QPushButton("✕ Close")
        close_btn.setStyleSheet(
            "QPushButton { color: #ef4444; border: 1px solid #374151; "
            "border-radius: 4px; padding: 4px 12px; background: #1f2937; }"
            "QPushButton:hover { background: #374151; }"
        )
        close_btn.clicked.connect(self._on_close)
        header_layout.addWidget(close_btn)

        main_layout.addWidget(header)

        # ─── Zone selection toolbar ───
        zone_bar = QWidget()
        zone_bar.setStyleSheet("background: #111827; border-radius: 6px;")
        zone_layout = QHBoxLayout(zone_bar)
        zone_layout.setContentsMargins(12, 6, 12, 6)
        zone_layout.setSpacing(8)

        zone_label = QLabel("ناحیه مقایسه:")
        zone_label.setStyleSheet("color: #9ca3af; font-size: 12px;")
        zone_layout.addWidget(zone_label)

        self._zone_btn_group = QButtonGroup(self)
        self._zone_btn_group.setExclusive(True)

        btn_style = (
            "QPushButton { color: #d1d5db; border: 1px solid #374151; "
            "border-radius: 4px; padding: 6px 16px; background: #1f2937; font-size: 12px; }"
            "QPushButton:hover { background: #374151; }"
            "QPushButton:checked { background: #1e40af; border-color: #3b82f6; color: #fff; }"
        )

        self._btn_interior = QPushButton("Interior (نیپل)")
        self._btn_interior.setCheckable(True)
        self._btn_interior.setStyleSheet(btn_style)
        self._zone_btn_group.addButton(self._btn_interior, 1)
        zone_layout.addWidget(self._btn_interior)

        self._btn_middle = QPushButton("Middle (میانی)")
        self._btn_middle.setCheckable(True)
        self._btn_middle.setStyleSheet(btn_style)
        self._zone_btn_group.addButton(self._btn_middle, 2)
        zone_layout.addWidget(self._btn_middle)

        self._btn_posterior = QPushButton("Posterior (دیواره)")
        self._btn_posterior.setCheckable(True)
        self._btn_posterior.setStyleSheet(btn_style)
        self._zone_btn_group.addButton(self._btn_posterior, 3)
        zone_layout.addWidget(self._btn_posterior)

        # Clear button
        sep = QLabel("|")
        sep.setStyleSheet("color: #374151;")
        zone_layout.addWidget(sep)

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setStyleSheet(
            "QPushButton { color: #9ca3af; border: 1px solid #374151; "
            "border-radius: 4px; padding: 6px 12px; background: #1f2937; font-size: 11px; }"
            "QPushButton:hover { background: #374151; }"
        )
        self._btn_clear.clicked.connect(self._on_clear)
        zone_layout.addWidget(self._btn_clear)

        zone_layout.addStretch()

        # Hint
        hint = QLabel("یک ناحیه انتخاب کنید — بقیه سایه می‌شوند")
        hint.setStyleSheet("color: #6b7280; font-size: 11px;")
        zone_layout.addWidget(hint)

        main_layout.addWidget(zone_bar)

        # Connect zone buttons
        self._btn_interior.clicked.connect(lambda: self._on_zone_selected(ZONE_INTERIOR))
        self._btn_middle.clicked.connect(lambda: self._on_zone_selected(ZONE_MIDDLE))
        self._btn_posterior.clicked.connect(lambda: self._on_zone_selected(ZONE_POSTERIOR))

        # ─── Viewer panels side by side ───
        self._viewers_container = QWidget()
        viewers_layout = QHBoxLayout(self._viewers_container)
        viewers_layout.setContentsMargins(0, 0, 0, 0)
        viewers_layout.setSpacing(4)

        self._left_panel = DualViewPanel("Left")
        self._right_panel = DualViewPanel("Right")

        viewers_layout.addWidget(self._left_panel, stretch=1)

        # Separator
        sep_line = QFrame()
        sep_line.setFrameShape(QFrame.VLine)
        sep_line.setStyleSheet("color: #374151;")
        viewers_layout.addWidget(sep_line)

        viewers_layout.addWidget(self._right_panel, stretch=1)

        main_layout.addWidget(self._viewers_container, stretch=1)

    def setup_views(
        self,
        left_widget,
        right_widget,
        left_direction: int = 1,
        right_direction: int = -1,
        left_label: str = "Left",
        right_label: str = "Right",
    ):
        """
        Configure the dual view with two viewer widgets.

        Args:
            left_widget: VTK widget for left breast.
            right_widget: VTK widget for right breast.
            left_direction: +1 if nipple is on left side of image, -1 if on right.
            right_direction: +1 if nipple is on left side, -1 if on right.
            left_label: Display label for left panel.
            right_label: Display label for right panel.
        """
        self._left_panel._header.setText(left_label)
        self._right_panel._header.setText(right_label)

        self._left_panel.set_viewer_widget(left_widget)
        self._right_panel.set_viewer_widget(right_widget)

        self._left_panel.set_direction(left_direction)
        self._right_panel.set_direction(right_direction)

    def _on_zone_selected(self, zone: str):
        """User selected a zone — shadow the other zones on both panels."""
        self._active_zone = zone
        self._left_panel.set_active_zone(zone)
        self._right_panel.set_active_zone(zone)

    def _on_clear(self):
        """Remove all shadows."""
        self._active_zone = None
        self._left_panel.clear()
        self._right_panel.clear()
        # Uncheck all zone buttons
        checked = self._zone_btn_group.checkedButton()
        if checked:
            self._zone_btn_group.setExclusive(False)
            checked.setChecked(False)
            self._zone_btn_group.setExclusive(True)

    def _on_close(self):
        """Close the dual view widget."""
        self._on_clear()
        self.closed.emit()
        self.hide()

    def closeEvent(self, event):
        self._on_close()
        super().closeEvent(event)
