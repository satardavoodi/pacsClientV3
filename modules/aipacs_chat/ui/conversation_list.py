"""The conversation list: a model, a delegate, and a view.

MODEL/VIEW AND NOT A WIDGET PER ROW. Sixty conversations each built from a
handful of QLabels is sixty widget trees to lay out, style and repaint on every
poll — and this list repaints as often as every 800 ms while somebody is
talking. A delegate paints; it does not lay out.

WHAT THE DELEGATE DOES NOT DO IS DECIDE ANYTHING. ``tone`` arrives on the wire
and is looked up in one place; ``ago`` arrives rendered; ``preview`` arrives
truncated to 180 characters. The row draws what it was sent.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate

from .styles import RADIUS_SM, theme_tokens, tone_color

ROW_ROLE = Qt.UserRole + 1

ROW_HEIGHT = 66
PAD_X = 12
PAD_Y = 9
DOT = 8


class ConversationModel(QAbstractListModel):
    """Rows exactly as the server sent them.

    A RESET IS THE EXPENSIVE CASE, NOT THE DEFAULT. The server sends the whole
    filtered page on every sync — every 800 ms while somebody is talking — and
    ``beginResetModel`` tells the view that everything it knew is void. The
    view responds by dropping its scroll position, its selection and its hover,
    which is exactly the "list keeps jumping back to the top" the operator
    sees: not a scrolling bug, a reset five times a minute.

    So the ids are compared first. Same conversations in the same order — the
    overwhelmingly common case, since only a new message or a status change
    reorders them — means the rows are swapped in place and repainted, and the
    view never learns anything happened. A reset is kept for the case that
    genuinely is one: rows appearing, disappearing or changing order.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: tuple = ()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == ROW_ROLE:
            return row
        if role == Qt.DisplayRole:
            return row.preview
        if role == Qt.ToolTipRole:
            return f"{row.status} · {row.preview}"
        return None

    def replace(self, rows) -> bool:
        """Swap the page in. Returns True if the view was reset.

        The caller uses the answer to decide whether it has to put the scroll
        position back — after an in-place update there is nothing to restore,
        and setting the scrollbar anyway would fight a scroll in progress.
        """
        fresh = tuple(rows or ())
        if [r.id for r in self._rows] == [r.id for r in fresh]:
            self._rows = fresh
            if fresh:
                self.dataChanged.emit(self.index(0, 0), self.index(len(fresh) - 1, 0))
            return False

        self.beginResetModel()
        self._rows = fresh
        self.endResetModel()
        return True

    def row_at(self, index: QModelIndex):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        return self._rows[index.row()]

    def index_of_case(self, case_id: int) -> QModelIndex:
        for position, row in enumerate(self._rows):
            if row.id == case_id:
                return self.index(position, 0)
        return QModelIndex()


class ConversationDelegate(QStyledItemDelegate):
    """One row: presence dot, label, time, preview, unread badge, tone bar."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tokens = theme_tokens()

    def set_theme(self, tokens: dict) -> None:
        self._tokens = tokens or theme_tokens()

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        row = index.data(ROW_ROLE)
        if row is None:
            return

        t = self._tokens
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect.adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            bg = QColor(t.get("accent_soft", "#1d3a63"))
        elif hovered:
            bg = QColor(t.get("panel_alt_bg", "#282e37"))
        else:
            bg = QColor(t.get("card_bg", "#2b323c"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, RADIUS_SM, RADIUS_SM)

        # The status tone, as a 3px spine down the left edge. A full-row tint
        # would fight the selection colour; a spine is legible against both.
        tone = QColor(tone_color(getattr(row, "tone", "work")))
        painter.setBrush(tone)
        painter.drawRoundedRect(QRect(rect.left(), rect.top() + 6, 3, rect.height() - 12), 2, 2)

        x = rect.left() + PAD_X
        right = rect.right() - PAD_X

        # Presence. The server computes "online" from a 45-second window; the
        # client just draws it.
        dot_y = rect.top() + PAD_Y + 4
        painter.setBrush(QColor(
            t.get("status_online", "#22c55e") if row.online else t.get("status_offline", "#64748b")
        ))
        painter.drawEllipse(QRect(x, dot_y, DOT, DOT))
        x += DOT + 7

        # Unread badge, drawn first so the title can be clipped to fit it.
        unread_left = right
        if row.unread:
            label = "9+" if row.unread > 9 else str(row.unread)
            badge_font = QFont(option.font)
            badge_font.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.5))
            badge_font.setBold(True)
            metrics = QFontMetrics(badge_font)
            width = max(18, metrics.horizontalAdvance(label) + 10)
            badge = QRect(right - width, rect.top() + PAD_Y, width, 16)
            painter.setBrush(QColor(t.get("danger", "#ef4444")))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge, 8, 8)
            painter.setPen(QPen(QColor("#ffffff")))
            painter.setFont(badge_font)
            painter.drawText(badge, Qt.AlignCenter, label)
            unread_left = badge.left() - 8

        # "ago" — rendered by the server, localised, and deliberately not
        # recomputed here. It is display text, not a timestamp.
        time_left = unread_left
        if row.ago:
            small = QFont(option.font)
            small.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.5))
            painter.setFont(small)
            painter.setPen(QPen(QColor(t.get("text_muted", "#7c8794"))))
            metrics = QFontMetrics(small)
            width = metrics.horizontalAdvance(row.ago)
            painter.drawText(
                QRect(unread_left - width, rect.top() + PAD_Y, width, 16),
                Qt.AlignRight | Qt.AlignVCenter,
                row.ago,
            )
            time_left = unread_left - width - 8

        # Title line.
        title_font = QFont(option.font)
        title_font.setBold(bool(row.unread))
        painter.setFont(title_font)
        painter.setPen(QPen(QColor(t.get("text_primary", "#e8ecf1"))))
        title_rect = QRect(x, rect.top() + PAD_Y, max(20, time_left - x), 17)
        title = _elide(painter, row.title, title_rect.width())
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title)

        # Preview. Prefixed with "You:" for a staff message so an operator can
        # see at a glance whether the ball is in their court.
        preview_font = QFont(option.font)
        preview_font.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.0))
        painter.setFont(preview_font)
        painter.setPen(QPen(QColor(t.get("text_secondary", "#aab4c0"))))
        preview_rect = QRect(x, rect.top() + PAD_Y + 20, right - x, 16)
        prefix = "You: " if row.sender == "staff" else ""
        preview = _elide(painter, prefix + _one_line(row.preview), preview_rect.width())
        painter.drawText(preview_rect, Qt.AlignLeft | Qt.AlignVCenter, preview)

        # Status, in the tone colour, plus a pin marker.
        status_font = QFont(option.font)
        status_font.setPointSizeF(max(7.0, option.font.pointSizeF() - 2.0))
        painter.setFont(status_font)
        painter.setPen(QPen(tone))
        status_rect = QRect(x, rect.top() + PAD_Y + 37, right - x, 14)
        status_text = _humanise(row.status)
        if row.pinned:
            status_text = "PINNED · " + status_text
        painter.drawText(status_rect, Qt.AlignLeft | Qt.AlignVCenter, status_text.upper())

        painter.restore()


class ConversationListView(QListView):
    """Selection emits a case id, which is all the repository needs."""

    caseActivated = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatConversationList")
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.setSpacing(1)

        self._model = ConversationModel(self)
        self._delegate = ConversationDelegate(self)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)

        self.clicked.connect(self._on_clicked)

    def set_rows(self, rows) -> None:
        """Replace the page, keeping the operator's place in it.

        THREE THINGS SURVIVE A POLL, and each is lost in a different way:

        * the SELECTION, because rows reorder as messages arrive and the open
          conversation must not slide out from under the reader;
        * the SCROLL POSITION, because a reset sends the view back to row zero
          and an operator reading the bottom of a sixty-row list is thrown to
          the top every few seconds;
        * the operator's ACTIVE SCROLL. The scrollbar is only touched when the
          model actually reset. Writing to it on every poll would stutter
          against a drag or a kinetic flick that is still in progress.
        """
        bar = self.verticalScrollBar()
        offset = bar.value()
        current = self.current_case_id()

        was_reset = self._model.replace(rows)

        if current is not None:
            index = self._model.index_of_case(current)
            if index.isValid():
                # No scrollTo: setCurrentIndex alone does not move the view,
                # and asking it to reveal the row would undo the restore below.
                self.setCurrentIndex(index)

        if was_reset and offset:
            bar.setValue(min(offset, bar.maximum()))

    def current_case_id(self) -> int | None:
        row = self._model.row_at(self.currentIndex())
        return None if row is None else row.id

    def select_case(self, case_id: int) -> None:
        index = self._model.index_of_case(case_id)
        if index.isValid():
            self.setCurrentIndex(index)

    def row_for_case(self, case_id: int):
        """The row for a case id, or None.

        By ID and not by "whatever is selected": a conversation can be opened
        without being clicked — from a notification, or a deep link — and
        reading the selection then gives the previous conversation, or nothing.
        """
        return self._model.row_at(self._model.index_of_case(case_id))

    def set_theme(self, tokens: dict) -> None:
        self._delegate.set_theme(tokens)
        self.viewport().update()

    def _on_clicked(self, index) -> None:
        row = self._model.row_at(index)
        if row is not None:
            self.caseActivated.emit(row.id)


# ── text helpers ─────────────────────────────────────────────────────────────


def _one_line(text: str) -> str:
    """Newlines in a single-line preview render as boxes on Windows."""
    return " ".join((text or "").split())


def _humanise(status: str) -> str:
    return (status or "").replace("_", " ")


def _elide(painter: QPainter, text: str, width: int) -> str:
    metrics = QFontMetrics(painter.font())
    return metrics.elidedText(text or "", Qt.ElideRight, max(10, width))
