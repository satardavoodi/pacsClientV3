"""Responsive numbered slide cards for the instructor dock."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QListView, QListWidget, QListWidgetItem, QStyledItemDelegate, QStyle


class _CardDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.Antialiasing)
        card = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.State_Selected)
        painter.setBrush(QColor('#1f4a67' if selected else '#142637'))
        painter.setPen(QColor('#72b9eb' if option.state & QStyle.State_HasFocus else '#30485e'))
        painter.drawRoundedRect(card, 6, 6)
        badge = card.adjusted(10, 0, 0, 0)
        badge.setTop(card.center().y() - 16)
        badge.setSize(QSize(32, 32))
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon):
            icon.paint(painter, badge)
        painter.setFont(option.font)
        painter.setPen(QColor('#f3f8ff' if selected else '#d7e2ee'))
        text_rect = card.adjusted(52, 8, -10, -8)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                         str(index.data(Qt.DisplayRole) or ''))
        painter.restore()


class SlideSelector(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ListMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setMovement(QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setIconSize(QSize(32, 32))
        self.setItemDelegate(_CardDelegate(self))
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideNone)
        self.model().rowsInserted.connect(self._layout_cards)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_cards()

    def _layout_cards(self, *args):
        # Reserve scrollbar space even before it appears to avoid column churn.
        available = max(1, self.width() - 2 * self.frameWidth()
                        - self.verticalScrollBar().sizeHint().width() - 8)
        columns = 2 if available >= 600 else 1
        width = available // columns
        size = QSize(width, 88)
        if self.gridSize() != size:
            self.setGridSize(size)
        for index in range(self.count()):
            item = self.item(index)
            hint = QSize(max(1, width - 10), 84)
            if item.sizeHint() != hint:
                item.setSizeHint(hint)

    def add_slide(self, number, title):
        badge = QPixmap(32, 32)
        badge.fill(Qt.transparent)
        painter = QPainter(badge)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor('#245777'))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, 32, 32, 7, 7)
        font = QFont()
        font.setPixelSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor('#f3f8ff'))
        painter.drawText(badge.rect(), Qt.AlignCenter, str(number))
        painter.end()
        item = QListWidgetItem(QIcon(badge), str(title))
        item.setToolTip(f'{number}. {title}')
        self.addItem(item)
