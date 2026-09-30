"""Responsive thumbnail rows with complete, wrapped authoring titles."""
from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QPalette, QTextLayout, QTextOption
from PySide6.QtWidgets import QListWidget, QListView, QStyledItemDelegate, QStyleOptionViewItem, QStyle


class _TitleDelegate(QStyledItemDelegate):
    def _layout(self, text, font, width):
        layout = QTextLayout(text, font)
        # Emphasize the stored ordering prefix while preserving accessible text.
        prefix, separator, _ = text.partition(". ")
        if self.parent().two_columns and separator and prefix.isdigit():
            number = QTextLayout.FormatRange()
            number.start = 0
            number.length = len(prefix) + 1
            number.format.setFontWeight(QFont.Bold)
            number_font = QFont(font)
            if font.pointSizeF() > 0:
                number_font.setPointSizeF(font.pointSizeF() * 1.5)
            else:
                number_font.setPixelSize(max(1, round(font.pixelSize() * 1.5)))
            number_font.setBold(True)
            number.format.setFont(number_font)
            layout.setFormats([number])
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        height = 0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(24, width))
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        return layout, height

    def sizeHint(self, option, index):
        prepared = QStyleOptionViewItem(option)
        self.initStyleOption(prepared, index)
        view = self.parent()
        width = view.cell_width()
        _, height = self._layout(prepared.text, prepared.font, width - 124)
        return QSize(width, max(80, int(height + 20)))

    def paint(self, painter, option, index):
        prepared = QStyleOptionViewItem(option)
        self.initStyleOption(prepared, index)
        prepared.decorationPosition = QStyleOptionViewItem.Left
        text = prepared.text
        prepared.text = ""
        prepared.textElideMode = Qt.ElideNone
        # Retain native selection, focus and thumbnail painting.
        self.parent().style().drawControl(QStyle.CE_ItemViewItem, prepared, painter, self.parent())
        area = option.rect.adjusted(112, 10, -12, -10)
        layout, height = self._layout(text, prepared.font, area.width())
        painter.save()
        painter.setClipRect(area)
        role = QPalette.HighlightedText if option.state & QStyle.State_Selected else QPalette.Text
        painter.setPen(prepared.palette.color(role))
        layout.draw(painter, QPointF(area.left(), area.top() + max(0, (area.height() - height) / 2)))
        painter.restore()


class AuthoringListWidget(QListWidget):
    def __init__(self, parent=None, *, two_columns=False):
        super().__init__(parent)
        self.two_columns = two_columns
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideNone)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setUniformItemSizes(False)
        self.setItemDelegate(_TitleDelegate(self))
        self._relayout = QTimer(self)
        self._relayout.setSingleShot(True)
        self._relayout.timeout.connect(self._update_grid)
        if two_columns:
            self.setViewMode(QListView.IconMode)
            self.setFlow(QListView.LeftToRight)
            self.setWrapping(True)
            self.setMovement(QListView.Static)
            self.setResizeMode(QListView.Adjust)
            self.setSpacing(4)
            self.model().rowsInserted.connect(lambda *_: self._relayout.start(0))
            self.model().rowsRemoved.connect(lambda *_: self._relayout.start(0))
            self.model().dataChanged.connect(lambda *_: self._relayout.start(0))

    def cell_width(self):
        if not self.two_columns:
            return self.viewport().width()
        columns = 2 if self.viewport().width() >= 700 else 1
        return max(100, (self.viewport().width() - 40) // columns)

    def _update_grid(self):
        if self.two_columns:
            option = QStyleOptionViewItem()
            height = max((self.itemDelegate().sizeHint(option, self.model().index(i, 0)).height()
                          for i in range(self.count())), default=80)
            self.setGridSize(QSize(self.cell_width() + 4, height + 8))
        self.doItemsLayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout.start(0)
