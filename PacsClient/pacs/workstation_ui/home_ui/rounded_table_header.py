"""Paint smooth outer header corners without binary region clipping."""
import re
from PySide6.QtCore import QObject, QEvent, QRectF, QTimer, Qt
from PySide6.QtGui import QPainterPath, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget


class _CornerSurface(QWidget):
    def __init__(self, header, radius):
        super().__init__(header)
        self.radius = radius
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        header = self.parentWidget()
        table = header.parentWidget()
        match = re.search(r'QTableWidget\s*\{[^}]*background(?:-color)?\s*:\s*(#[0-9a-fA-F]{6})', table.styleSheet())
        color = QColor(match.group(1)) if match else table.palette().color(table.backgroundRole())
        rect = QRectF(self.rect())
        radius = min(self.radius, rect.height()/2, rect.width()/2)
        rounded = QPainterPath()
        rounded.setFillRule(Qt.FillRule.WindingFill)
        rounded.addRoundedRect(rect, radius, radius)
        rounded.addRect(QRectF(0, radius, rect.width(), rect.height()-radius))
        outer = QPainterPath()
        outer.addRect(rect)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(outer.subtracted(rounded), color)
        # Join the straight section borders through each curved corner instead
        # of leaving their cut ends visible as a notch.
        border = re.search(r'border-(?:right|bottom):\s*\d+px\s+solid\s+(#[0-9a-fA-F]{6})', table.styleSheet())
        painter.setPen(QPen(QColor(border.group(1) if border else '#4a5568'), 1))
        curve = QPainterPath()
        # Use circular arcs matching addRoundedRect; quadratic approximations
        # leave a differently curved dark sliver at this small radius.
        arc_radius = max(0, radius - .5)
        curve.arcMoveTo(QRectF(.5, .5, 2 * arc_radius, 2 * arc_radius), 180)
        curve.arcTo(QRectF(.5, .5, 2 * arc_radius, 2 * arc_radius), 180, -90)
        right_arc = QRectF(rect.width() - .5 - 2 * arc_radius, .5,
                           2 * arc_radius, 2 * arc_radius)
        curve.arcMoveTo(right_arc, 90)
        curve.arcTo(right_arc, 90, -90)
        painter.drawPath(curve)


class RoundedHeaderClip(QObject):
    def __init__(self, header, radius=8):
        super().__init__(header)
        self.header = header
        self.surface = _CornerSurface(header, radius)
        header.installEventFilter(self)
        self.update_clip()

    def update_clip(self):
        self.header.clearMask()
        self.surface.setGeometry(self.header.rect())
        self.surface.show()
        self.surface.raise_()
        self.surface.update()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.StyleChange):
            QTimer.singleShot(0, self.update_clip)
        return False
