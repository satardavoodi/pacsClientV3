"""The transcript: model, delegate, view.

MODEL/VIEW AGAIN, for the same reason as the conversation list — a long
consultation is hundreds of messages and this repaints as often as every
800 ms. A widget per bubble would be hundreds of layouts per poll.

THE RULES THIS VIEW OBEYS, none of which it decides for itself:

  * ORDER IS BY ID. The model keeps messages sorted by id and merges by id.
    Timestamps collide at one-second resolution.
  * REVISED BEFORE APPENDED. ``apply_revised`` patches rows in place;
    ``append`` adds new ones. The repository already emits them in that order.
  * ``editable`` IS THE SERVER'S ANSWER. The context menu offers Edit and
    Withdraw only when the server said so — re-deriving the rule from
    sender_type would show a menu item the controller refuses with a 403.
  * TICKS MEAN WHAT THE SERVER MEANS. One tick is delivered; two means an
    operator had the conversation in front of them after the message was
    written. There is no "sending" state on the wire — the composer owns that
    until a real row comes back.
  * COPY COPIES THE WHOLE MESSAGE, not the clamped text. A "Read more" that
    silently truncates what you paste into a report is worse than no clamp.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen, QTextOption
from PySide6.QtWidgets import QListView, QMenu, QPushButton, QStyledItemDelegate

from .styles import RADIUS_MD, theme_tokens

MESSAGE_ROLE = Qt.UserRole + 1
EXPANDED_ROLE = Qt.UserRole + 2
# The date band drawn above the first message of a day, or "" for every other
# row. Computed once when the transcript changes rather than per paint — the
# delegate has no way to see the row above it.
DAY_BREAK_ROLE = Qt.UserRole + 3

# Lines shown before a long message is clamped. Chosen so a normal reply is
# never clamped and a pasted report always is.
CLAMP_LINES = 12

BUBBLE_MAX_RATIO = 0.72
PAD = 13          # inside the bubble, all four sides
GAP = 10          # between one bubble and the next
META_H = 18       # the sender · time · ticks line
REACT_H = 18
# The attachment chip: one clickable row inside the bubble.
ATTACH_H = 36
# Extra leading on top of the font's own line spacing. A transcript is read in
# long paragraphs pasted out of reports, and Qt's default spacing sets them
# tighter than is comfortable at this size.
LEADING = 3
# The date band that separates one day from the next.
DAY_H = 30
# Minimum body size. The transcript inherits the application font, which is
# tuned for dense table views; a conversation is read, not scanned.
MIN_BODY_PT = 10.0
# How near the bottom still counts as "following the conversation". One line of
# slack, so a stray pixel of overscroll does not stop the view from following.
FOLLOW_SLACK = 28

# Message status, in the order a message passes through them.
STATUS_SENT = "sent"            # the server has it; the patient's client has not
STATUS_DELIVERED = "delivered"  # the patient's client fetched it
STATUS_SEEN = "seen"            # the patient had it on screen


def _is_dark(tokens: dict) -> bool:
    """Whether the active theme is a dark one.

    Asked rather than assumed, because every surface below is derived by
    lightening or darkening a token and the two directions are opposite in a
    light theme. Getting this wrong is how a "subtle" tint becomes black.
    """
    base = QColor(tokens.get("panel_bg", "#232830"))
    return base.lightness() < 128


def _day_label(day) -> str:
    """"Today", "Yesterday", or a written date.

    Named days for the two an operator thinks of by name, and an unambiguous
    written form for the rest — never a numeric ``08/09``, which half the world
    reads as September.
    """
    from datetime import date, timedelta

    today = date.today()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    if day.year == today.year:
        return day.strftime("%A, %d %B")
    return day.strftime("%d %B %Y")


def _shift(colour: str, amount: int, dark: bool) -> QColor:
    """A surface a step away from ``colour``, in whichever direction reads.

    ``amount`` is a percentage, the way Qt's own lighter()/darker() take it.
    On a dark theme a step AWAY from the background means lighter; on a light
    theme it means darker.
    """
    base = QColor(colour)
    return base.lighter(100 + amount) if dark else base.darker(100 + amount)


def _bubble_palette(tokens: dict) -> dict:
    """The four surfaces a transcript needs, derived once per theme.

    THE PATIENT'S BUBBLE WAS THE PROBLEM. It was painted in ``card_bg``, which
    is one step off ``panel_bg`` — a difference of a few points of lightness
    that reads as "no bubble at all" on a large monitor, and left a whole side
    of the conversation looking like loose text on the background.

    So the two sides are now separated on two axes at once, not one:

      * the PATIENT gets a raised neutral surface with a hairline border and a
        coloured spine on the leading edge — it reads as a card;
      * the OPERATOR gets a filled accent surface with no border — it reads as
        a block of colour.

    Even at a glance, without reading a word or noticing which side it is on,
    the two are different KINDS of shape. That is what makes a transcript
    scannable; alignment alone is not enough, because a long patient message
    and a long staff message both fill most of the width.
    """
    dark = _is_dark(tokens)
    panel = tokens.get("panel_bg", "#232830")
    accent_soft = tokens.get("accent_soft", "#1d3a63")

    inbound = _shift(panel, 34 if dark else 8, dark)
    outbound = QColor(accent_soft)
    if dark and outbound.lightness() < QColor(panel).lightness() + 12:
        # Some themes ship an accent_soft barely distinguishable from the
        # panel. Lift it rather than inheriting the same invisibility the
        # patient bubble had.
        outbound = outbound.lighter(130)

    return {
        "dark": dark,
        "inbound": inbound,
        "inbound_hover": _shift(inbound.name(), 12, dark),
        "inbound_border": _shift(inbound.name(), 26, dark),
        "outbound": outbound,
        "outbound_hover": _shift(outbound.name(), 12, dark),
        "removed": _shift(panel, 16 if dark else 5, dark),
    }


def human_size(value) -> str:
    """``file_size`` as something an operator reads, or "" if it is missing.

    The server sends bytes as an integer, but a message written before the
    column existed sends nothing at all — and "0 B" would be a lie about a file
    that downloads perfectly well.
    """
    try:
        size = int(value)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return ""


def attachment_of(message):
    """The file this message carries, or None.

    A WITHDRAWN file message keeps its row and loses its ``meta`` — the server
    nulls it on the tombstone. ``meta_value`` answers None for both "no meta"
    and "key absent", so a withdrawn attachment falls out here and paints as an
    ordinary removed bubble with nothing to click. Rendering a chip for it
    would offer a download the server answers with a 404.
    """
    if getattr(message, "type", "") != "file" or getattr(message, "removed", False):
        return None
    raw_id = message.meta_value("file_id")
    try:
        file_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    return {
        "file_id": file_id,
        "file_name": str(message.meta_value("file_name") or "attachment"),
        "size_text": human_size(message.meta_value("file_size")),
        "mime": str(message.meta_value("mime") or ""),
        "is_image": bool(message.meta_value("is_image")),
    }


class MessageModel(QAbstractListModel):
    """The transcript, keyed by message id."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._messages: list = []
        self._index_by_id: dict[int, int] = {}
        self._expanded: set[int] = set()
        self._day_breaks: dict[int, str] = {}
        self._read_at = None
        self._seen_at = None

    # --- reads ------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._messages)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._messages)):
            return None
        message = self._messages[index.row()]
        if role == MESSAGE_ROLE:
            return message
        if role == EXPANDED_ROLE:
            return message.id in self._expanded
        if role == DAY_BREAK_ROLE:
            return self._day_breaks.get(message.id, "")
        if role == Qt.DisplayRole:
            return message.body
        return None

    def message_at(self, index: QModelIndex):
        if not index.isValid() or not (0 <= index.row() < len(self._messages)):
            return None
        return self._messages[index.row()]

    @property
    def read_at(self):
        return self._read_at

    @property
    def seen_at(self):
        return self._seen_at

    def status_of(self, message) -> str:
        """Sent, delivered or seen — the three the server actually knows.

        ``read_at`` is when the patient's client last fetched this thread past
        a given point; ``seen_at`` is when they last had it in front of them.
        Both arrive on every sync and until now the second was being thrown
        away, which is why every outbound message had only two states to show.

        The comparison is ``>=``, the same way the server compares. A message
        with no timestamp cannot be placed on that line at all, so it stays at
        "sent" rather than being flattered upward.
        """
        at = getattr(message, "at", None)
        if at is None:
            return STATUS_SENT
        if self._seen_at is not None and self._seen_at >= at:
            return STATUS_SEEN
        if self._read_at is not None and self._read_at >= at:
            return STATUS_DELIVERED
        return STATUS_SENT

    # --- writes -----------------------------------------------------------

    def replace(self, messages) -> None:
        """A cold answer. Replace wholesale — never merge one."""
        self.beginResetModel()
        self._messages = sorted(messages or [], key=lambda m: m.id)
        self._reindex()
        self._expanded.clear()
        self.endResetModel()

    def append(self, messages) -> None:
        """New messages. Ids the model already holds are ignored, not doubled."""
        fresh = [m for m in (messages or []) if m.id not in self._index_by_id]
        if not fresh:
            return
        fresh.sort(key=lambda m: m.id)

        # Almost always a straight append — the cursor only ever hands over
        # messages newer than everything on screen. The sort below costs
        # nothing then, and covers the case where it does not hold.
        first = self.rowCount()
        self.beginInsertRows(QModelIndex(), first, first + len(fresh) - 1)
        self._messages.extend(fresh)
        self._messages.sort(key=lambda m: m.id)
        self._reindex()
        self.endInsertRows()

        # A sort can move earlier rows, so repaint everything rather than
        # trusting the inserted range.
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0))

    def apply_revised(self, messages) -> None:
        """Edited, withdrawn or reacted-to rows already on screen."""
        for message in messages or []:
            position = self._index_by_id.get(message.id)
            if position is None:
                continue
            self._messages[position] = message
            if message.removed:
                # Nothing left to expand.
                self._expanded.discard(message.id)
            model_index = self.index(position, 0)
            self.dataChanged.emit(model_index, model_index)

    def set_receipts(self, read_at, seen_at=None) -> None:
        """Two timestamps the whole tick column is re-derived from.

        Sent as values rather than per-message flags because the client already
        knows when each message was written — so two numbers update every row,
        including ones that arrived on an earlier poll.
        """
        if read_at == self._read_at and seen_at == self._seen_at:
            return
        self._read_at = read_at
        self._seen_at = seen_at
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0))

    def set_read_at(self, read_at) -> None:
        """Kept for callers that only have the one timestamp."""
        self.set_receipts(read_at, self._seen_at)

    def toggle_expanded(self, message_id: int) -> None:
        if message_id in self._expanded:
            self._expanded.discard(message_id)
        else:
            self._expanded.add(message_id)
        position = self._index_by_id.get(message_id)
        if position is not None:
            model_index = self.index(position, 0)
            self.dataChanged.emit(model_index, model_index)

    def _reindex(self) -> None:
        self._index_by_id = {m.id: i for i, m in enumerate(self._messages)}
        self._recompute_day_breaks()

    def _recompute_day_breaks(self) -> None:
        """Which messages open a new day.

        Done here, once per transcript change, because a delegate paints one
        row and cannot see the row above it — and asking the model for the
        previous message from inside paint() would be a lookup per repaint, at
        up to 800 ms intervals, for an answer that only changes when the
        transcript does.

        LOCAL DAYS, not UTC ones. The band says "Today" to the person reading
        it, so the boundary has to be their midnight.
        """
        self._day_breaks = {}
        previous = None
        for message in self._messages:
            at = getattr(message, "at", None)
            if at is None:
                continue
            day = at.astimezone().date()
            if day != previous:
                self._day_breaks[message.id] = _day_label(day)
                previous = day


class MessageDelegate(QStyledItemDelegate):
    """One bubble."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tokens = theme_tokens()
        self._read_more_rects: dict[int, QRect] = {}
        self._attachment_rects: dict[int, QRect] = {}
        self._hover_id: int | None = None
        # THE authoritative width. See _content_width.
        self._viewport_width = 0
        self._palette = _bubble_palette(self._tokens)

    def set_theme(self, tokens: dict) -> None:
        self._tokens = tokens or theme_tokens()
        self._palette = _bubble_palette(self._tokens)

    def set_viewport_width(self, width: int) -> None:
        self._viewport_width = max(0, int(width))

    def set_hovered(self, message_id: int | None) -> None:
        self._hover_id = message_id

    # --- geometry ---------------------------------------------------------

    def _content_width(self, option) -> int:
        """The width both sizeHint AND paint must agree on.

        THIS IS THE SCROLLBAR BUG. ``option.rect`` is the item's assigned
        rectangle, and QListView does not fill it in the same way for the two
        calls: paint gets the laid-out row, sizeHint is asked BEFORE the row
        has one. Measuring against a narrow (or zero) width wraps the body into
        far more lines than will ever be drawn, so every row is reserved several
        times the height it paints into.

        The visible result is exactly what it looks like: bubbles with large
        empty gaps under them, a scrollbar whose range is a multiple of the
        real content, and a thumb that therefore jumps a screenful at a time
        and cannot settle anywhere in the middle.

        The view pushes its real viewport width in here on every resize, and
        both calls read that one number. ``option.rect`` is only a fallback for
        a delegate used outside a view — a test measuring a bubble directly.
        """
        if self._viewport_width > 0:
            return self._viewport_width
        return max(0, option.rect.width())

    def _bubble_width(self, option) -> int:
        return max(160, int(self._content_width(option) * BUBBLE_MAX_RATIO))

    @staticmethod
    def _body_font(option) -> QFont:
        """The body font, floored at a size a paragraph can be read at."""
        font = QFont(option.font)
        if font.pointSizeF() > 0 and font.pointSizeF() < MIN_BODY_PT:
            font.setPointSizeF(MIN_BODY_PT)
        return font

    @classmethod
    def _line_height(cls, option) -> int:
        return QFontMetrics(cls._body_font(option)).lineSpacing() + LEADING

    def _layout(self, option, message, expanded: bool):
        """Wrapped lines, and whether the message was clamped.

        Returns (lines, clamped, text_width).
        """
        metrics = QFontMetrics(self._body_font(option))
        width = self._bubble_width(option) - 2 * PAD

        lines: list[str] = []
        for paragraph in (message.body or "").split("\n"):
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for word in paragraph.split(" "):
                candidate = word if not current else current + " " + word
                if metrics.horizontalAdvance(candidate) <= width:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                # A single word longer than the bubble — break it by character
                # rather than letting it overflow the layout. Visitor-supplied
                # strings (a referrer, a share URL) do this routinely.
                while metrics.horizontalAdvance(word) > width and len(word) > 1:
                    cut = 1
                    while cut < len(word) and metrics.horizontalAdvance(word[:cut + 1]) <= width:
                        cut += 1
                    lines.append(word[:cut])
                    word = word[cut:]
                current = word
            lines.append(current)

        clamped = not expanded and len(lines) > CLAMP_LINES
        if clamped:
            lines = lines[:CLAMP_LINES]
        return lines, clamped, width

    def _bubble_height(self, option, message, lines, clamped, expanded) -> int:
        """ONE formula, called by both sizeHint and paint.

        They used to compute this separately with the same arithmetic written
        twice. Two copies of a formula drift, and when this one drifts the
        symptom is a scrollbar that does not match the content — so there is
        now one copy and both callers use it.
        """
        height = PAD * 2 + max(1, len(lines)) * self._line_height(option)
        if self._is_inbound_named(message):
            height += META_H
        if clamped or (expanded and len(lines) > CLAMP_LINES):
            height += META_H
        if attachment_of(message) is not None:
            height += ATTACH_H
        if self._has_reactions(message):
            height += REACT_H
        return height + META_H

    @staticmethod
    def _is_inbound_named(message) -> bool:
        """Whether a name is drawn above an inbound message's body.

        Only when the server sent one. A patient conversation has a single
        patient in it, so the name is redundant there — but a mirrored Crisp
        thread or a multi-operator case is not, and an unattributed line in
        those is genuinely ambiguous.
        """
        return bool(
            getattr(message, "sender", None)
            and not message.is_outbound
            and not message.is_system
        )

    def sizeHint(self, option, index) -> QSize:
        message = index.data(MESSAGE_ROLE)
        if message is None:
            return QSize(self._content_width(option), 0)

        width = self._content_width(option)
        if message.is_system:
            return QSize(width, self._line_height(option) + GAP + 8)

        expanded = bool(index.data(EXPANDED_ROLE))
        lines, clamped, _ = self._layout(option, message, expanded)
        height = self._bubble_height(option, message, lines, clamped, expanded)
        if index.data(DAY_BREAK_ROLE):
            height += DAY_H
        return QSize(width, height + GAP)

    @staticmethod
    def _has_reactions(message) -> bool:
        reactions = message.reactions
        return bool(reactions.patient or reactions.staff_up or reactions.staff_down)

    def read_more_rect(self, message_id: int) -> QRect | None:
        return self._read_more_rects.get(message_id)

    def attachment_rect(self, message_id: int) -> QRect | None:
        return self._attachment_rects.get(message_id)

    # --- painting ---------------------------------------------------------

    def paint(self, painter: QPainter, option, index) -> None:
        message = index.data(MESSAGE_ROLE)
        if message is None:
            return

        t = self._tokens
        # Cleared before anything can return early, so a row that stops being
        # an attachment (a withdrawn file) leaves no clickable ghost behind.
        self._attachment_rects.pop(message.id, None)
        expanded = bool(index.data(EXPANDED_ROLE))
        lines, clamped, text_width = self._layout(option, message, expanded)
        body_font = self._body_font(option)
        metrics = QFontMetrics(body_font)
        line_h = self._line_height(option)
        p = self._palette

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        outbound = message.is_outbound
        system = message.is_system
        hovered = self._hover_id == message.id

        # The day band, above everything else in the row it belongs to.
        top = option.rect.top()
        day = index.data(DAY_BREAK_ROLE)
        if day and not system:
            self._paint_day_band(painter, option, QRect(option.rect.left(), top,
                                                        option.rect.width(), DAY_H), str(day))
            top += DAY_H

        if system:
            # A system line is bookkeeping, not speech: centred, no bubble.
            painter.setPen(QPen(QColor(t.get("text_muted", "#7c8794"))))
            small = QFont(body_font)
            small.setPointSizeF(max(8.0, body_font.pointSizeF() - 1.0))
            painter.setFont(small)
            text = " ".join((message.body or "").split())
            if day:
                text = f"{day}  ·  {text}" if text else str(day)
            painter.drawText(option.rect, Qt.AlignCenter, text)
            painter.restore()
            return

        bubble_w = self._bubble_width(option)
        bubble_h = self._bubble_height(option, message, lines, clamped, expanded)
        attachment = attachment_of(message)

        left = option.rect.right() - bubble_w - 10 if outbound else option.rect.left() + 10
        bubble = QRect(left, top, bubble_w, bubble_h)

        # --- the surface ---------------------------------------------------
        # Two DIFFERENT treatments, not two shades of one. See _bubble_palette.
        if message.removed:
            bg = QColor(p["removed"])
            border = None
        elif outbound:
            bg = QColor(p["outbound_hover"] if hovered else p["outbound"])
            border = None
        else:
            bg = QColor(p["inbound_hover"] if hovered else p["inbound"])
            border = QColor(p["inbound_border"])

        painter.setPen(QPen(border, 1) if border is not None else Qt.NoPen)
        painter.setBrush(bg)
        # Half-pixel inset so a 1px border lands on the pixel grid instead of
        # straddling it and rendering as a blurred two-pixel smear.
        painter.drawRoundedRect(
            QRect(bubble).adjusted(0, 0, -1, -1) if border is not None else bubble,
            RADIUS_MD, RADIUS_MD,
        )
        painter.setPen(Qt.NoPen)

        # The leading-edge spine. Inbound gets it on the left, and it carries
        # the one piece of colour that says "this came from outside".
        if not outbound and not message.removed:
            painter.setBrush(QColor(t.get("info", "#38bdf8")))
            painter.drawRoundedRect(
                QRect(bubble.left() + 1, bubble.top() + 10, 3, bubble.height() - 20), 2, 2
            )

        # An automated message is still a staff message, but nobody typed it —
        # a border says so without a badge stealing a line.
        if message.is_automated:
            painter.setBrush(QColor(t.get("warning", "#f59e0b")))
            painter.drawRoundedRect(
                QRect(bubble.right() - 4, bubble.top() + 10, 3, bubble.height() - 20), 2, 2
            )

        y = bubble.top() + PAD

        # --- who is speaking, on an inbound message that names them ---------
        if self._is_inbound_named(message):
            name_font = QFont(body_font)
            name_font.setPointSizeF(max(8.0, body_font.pointSizeF() - 1.0))
            name_font.setBold(True)
            painter.setFont(name_font)
            painter.setPen(QPen(QColor(t.get("info", "#38bdf8"))))
            painter.drawText(
                QRect(bubble.left() + PAD, y, text_width, META_H),
                Qt.AlignLeft | Qt.AlignVCenter,
                QFontMetrics(name_font).elidedText(
                    str(message.sender), Qt.ElideRight, text_width
                ),
            )
            y += META_H

        text_color = t.get("text_muted", "#7c8794") if message.removed else t.get("text_primary", "#e8ecf1")
        painter.setFont(QFont(body_font))
        if message.removed:
            italic = QFont(body_font)
            italic.setItalic(True)
            painter.setFont(italic)
        painter.setPen(QPen(QColor(text_color)))

        for line in lines:
            painter.drawText(
                QRect(bubble.left() + PAD, y, text_width, line_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                line,
            )
            y += line_h

        # Read more / Show less.
        self._read_more_rects.pop(message.id, None)
        if clamped or (expanded and len(lines) > CLAMP_LINES):
            link_font = QFont(option.font)
            link_font.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.0))
            link_font.setUnderline(True)
            painter.setFont(link_font)
            painter.setPen(QPen(QColor(t.get("accent", "#3b82f6"))))
            label = "Show less" if expanded else "Read more"
            link_rect = QRect(bubble.left() + PAD, y, text_width, META_H)
            painter.drawText(link_rect, Qt.AlignLeft | Qt.AlignVCenter, label)
            hit = QRect(link_rect)
            hit.setWidth(QFontMetrics(link_font).horizontalAdvance(label) + 8)
            self._read_more_rects[message.id] = hit
            y += META_H

        # Attachment chip. One clickable row: icon, name, size. The bytes are
        # NOT fetched to draw it — the chip is drawn from meta alone, and the
        # download only starts when the operator clicks. A transcript that
        # pulled every attachment on paint would download a consultation's
        # worth of imaging to scroll past it.
        if attachment is not None:
            chip = QRect(bubble.left() + PAD, y + 2, text_width, ATTACH_H - 6)
            painter.setPen(QPen(QColor(t.get("border", "#3a424e")), 1))
            painter.setBrush(QColor(t.get("panel_alt_bg", "#282e37")))
            painter.drawRoundedRect(chip, 6, 6)

            icon_font = QFont(option.font)
            painter.setFont(icon_font)
            painter.setPen(QPen(QColor(t.get("accent", "#3b82f6"))))
            icon_rect = QRect(chip.left() + 8, chip.top(), 20, chip.height())
            painter.drawText(
                icon_rect, Qt.AlignLeft | Qt.AlignVCenter,
                "🖼" if attachment["is_image"] else "📎",
            )

            name_font = QFont(option.font)
            name_font.setPointSizeF(max(7.5, option.font.pointSizeF() - 0.5))
            painter.setFont(name_font)
            painter.setPen(QPen(QColor(t.get("text_primary", "#e8ecf1"))))
            name_rect = QRect(
                icon_rect.right() + 6, chip.top(),
                chip.right() - icon_rect.right() - 14, chip.height(),
            )
            label = QFontMetrics(name_font).elidedText(
                attachment["file_name"], Qt.ElideMiddle, name_rect.width() - 60,
            )
            painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, label)

            if attachment["size_text"]:
                size_font = QFont(option.font)
                size_font.setPointSizeF(max(7.0, option.font.pointSizeF() - 2.0))
                painter.setFont(size_font)
                painter.setPen(QPen(QColor(t.get("text_muted", "#7c8794"))))
                painter.drawText(
                    name_rect, Qt.AlignRight | Qt.AlignVCenter, attachment["size_text"],
                )

            self._attachment_rects[message.id] = QRect(chip)
            y += ATTACH_H

        # Reactions.
        if self._has_reactions(message):
            react_font = QFont(option.font)
            react_font.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.0))
            painter.setFont(react_font)
            painter.setPen(QPen(QColor(t.get("text_secondary", "#aab4c0"))))
            parts = []
            if message.reactions.patient == 1:
                parts.append("Patient liked")
            elif message.reactions.patient == -1:
                parts.append("Patient disliked")
            if message.reactions.staff_up:
                parts.append(f"+{message.reactions.staff_up}")
            if message.reactions.staff_down:
                parts.append(f"-{message.reactions.staff_down}")
            painter.drawText(
                QRect(bubble.left() + PAD, y, text_width, REACT_H),
                Qt.AlignLeft | Qt.AlignVCenter,
                "  ".join(parts),
            )
            y += REACT_H

        # Meta line: sender, time, edited marker, ticks.
        meta_font = QFont(body_font)
        meta_font.setPointSizeF(max(8.0, body_font.pointSizeF() - 1.5))
        painter.setFont(meta_font)
        # A shade above text_muted. The timestamp has to be READABLE without
        # competing with the message — muted-on-a-tinted-bubble was neither.
        painter.setPen(QPen(QColor(t.get("text_secondary", "#aab4c0"))))

        bits = []
        if message.sender and outbound:
            bits.append(message.sender)
        if message.at:
            bits.append(message.at.astimezone().strftime("%H:%M"))
        if message.edited and not message.removed:
            bits.append("edited")
        meta = " · ".join(bits)

        meta_rect = QRect(bubble.left() + PAD, y, text_width, META_H)
        painter.drawText(meta_rect, Qt.AlignLeft | Qt.AlignVCenter, meta)

        if outbound and not message.removed:
            model = index.model()
            status = (
                model.status_of(message)
                if hasattr(model, "status_of")
                else STATUS_SENT
            )
            self._paint_ticks(painter, meta_rect, status)

        painter.restore()

    # --- the pieces paint() draws ----------------------------------------

    def _paint_day_band(self, painter: QPainter, option, rect: QRect, label: str) -> None:
        """A centred date, with a rule running out to each side.

        A transcript that runs over days needs somewhere for the eye to stop.
        The rule is what makes it a band rather than another short message —
        without it, a centred date reads as one more system line.
        """
        t = self._tokens
        font = QFont(self._body_font(option))
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1.5))
        font.setBold(True)
        metrics = QFontMetrics(font)
        text_w = metrics.horizontalAdvance(label) + 22

        centre = rect.center().y()
        pill = QRect(rect.center().x() - text_w // 2, centre - 10, text_w, 20)

        painter.setPen(QPen(QColor(t.get("border", "#39414d")), 1))
        painter.drawLine(rect.left() + 16, centre, pill.left() - 10, centre)
        painter.drawLine(pill.right() + 10, centre, rect.right() - 16, centre)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._palette["inbound"]))
        painter.drawRoundedRect(pill, 10, 10)

        painter.setFont(font)
        painter.setPen(QPen(QColor(t.get("text_secondary", "#aab4c0"))))
        painter.drawText(pill, Qt.AlignCenter, label)

    def _paint_ticks(self, painter: QPainter, meta_rect: QRect, status: str) -> None:
        """Sent, delivered or seen — DRAWN, not typed.

        The old version wrote "✓" and "✓✓" as text. Two problems, both visible
        in the product: the glyph is not in every font, so on a machine without
        it Qt substitutes and the marks change shape between rows; and two of
        them side by side are two separate glyphs with the font's own spacing
        between, which is why they read as a smudge rather than as a pair.

        Drawn as strokes they are one shape, at a size and overlap this code
        chooses, aligned to the meta line's own centre:

            sent       one tick,  muted    — the server has it
            delivered  two ticks, muted    — the patient's client fetched it
            seen       two ticks, accent   — the patient had it on screen
        """
        t = self._tokens
        seen = status == STATUS_SEEN
        colour = QColor(t.get("info", "#38bdf8")) if seen else QColor(
            t.get("text_secondary", "#aab4c0")
        )
        if not seen:
            # Slightly recessive while it is still only machine news.
            colour.setAlpha(190)

        pen = QPen(colour, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        double = status in (STATUS_DELIVERED, STATUS_SEEN)
        width = 15 if double else 10
        right = meta_rect.right()
        cy = meta_rect.center().y() + 1

        def _tick(x: int) -> None:
            # A check is two strokes: down-right, then up-right.
            painter.drawPolyline([
                QPoint(x, cy + 1),
                QPoint(x + 3, cy + 4),
                QPoint(x + 9, cy - 4),
            ])

        _tick(right - width)
        if double:
            # Overlapped by 5px, which is what makes a pair read as one mark.
            _tick(right - width + 5)


class ChatView(QListView):
    """The transcript, plus the operator actions that act on one message."""

    readMoreToggled = Signal(int)
    editRequested = Signal(int)
    removeRequested = Signal(int)
    reactRequested = Signal(int, object)
    pinRequested = Signal(int)
    emailRequested = Signal(int)
    attachmentRequested = Signal(int, str)   # file_id, file_name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatTranscript")
        self.setSelectionMode(QListView.NoSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.setWordWrap(True)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

        # Pixel scrolling with a small single step. QListView's default step is
        # one ITEM, and with bubbles of wildly different heights that is what
        # makes a wheel notch jump a paragraph at a time.
        self.verticalScrollBar().setSingleStep(24)

        self._model = MessageModel(self)
        self._delegate = MessageDelegate(self)
        self.setModel(self._model)
        self.setItemDelegate(self._delegate)
        self._delegate.set_viewport_width(self.viewport().width())

        self._pending_new = 0
        self._jump = QPushButton("", self.viewport())
        self._jump.setObjectName("ChatJumpToLatest")
        self._jump.setCursor(Qt.PointingHandCursor)
        self._jump.setVisible(False)
        self._jump.clicked.connect(self._on_jump_clicked)

        self.customContextMenuRequested.connect(self._show_menu)
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)

    # --- data -------------------------------------------------------------

    def replace(self, messages) -> None:
        self._model.replace(messages)
        self._pending_new = 0
        self._update_jump()
        self.scroll_to_end()

    def append(self, messages) -> None:
        at_end = self._is_at_end()
        before = self._model.rowCount()
        self._model.append(messages)
        added = self._model.rowCount() - before

        # Only follow the conversation if the operator was already at the
        # bottom. Yanking the view down while they are reading history is the
        # single most annoying thing a chat client can do — so instead the
        # arrival is OFFERED, as a count they can click, and the scroll
        # position they chose is left exactly where it is.
        if at_end:
            self._pending_new = 0
            self.scroll_to_end()
        elif added > 0:
            self._pending_new += added
        self._update_jump()

    def apply_revised(self, messages) -> None:
        self._model.apply_revised(messages)

    def set_read_at(self, read_at) -> None:
        self._model.set_read_at(read_at)

    def set_receipts(self, read_at, seen_at=None) -> None:
        self._model.set_receipts(read_at, seen_at)

    def set_theme(self, tokens: dict) -> None:
        self._delegate.set_theme(tokens)
        t = tokens or theme_tokens()
        self._jump.setStyleSheet(f"""
        QPushButton#ChatJumpToLatest {{
            background: {t.get('accent', '#3b82f6')};
            color: {t.get('button_text', '#ffffff')};
            border: none;
            border-radius: 13px;
            padding: 5px 14px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#ChatJumpToLatest:hover {{ background: {t.get('accent_hover', '#2f6fd8')}; }}
        """)
        self.viewport().update()

    def message_count(self) -> int:
        return self._model.rowCount()

    # --- layout -----------------------------------------------------------

    def resizeEvent(self, event) -> None:
        """Tell the delegate how wide the transcript actually is.

        THE ONE CALL THAT MAKES THE SCROLLBAR HONEST. Without it the delegate
        measures rows against a width it guessed and lays out a document
        several times taller than the one it paints. Everything about the
        scrolling follows from these two numbers agreeing.
        """
        super().resizeEvent(event)
        width = self.viewport().width()
        if width != self._delegate._viewport_width:
            self._delegate.set_viewport_width(width)
            # Every row's height depends on the width, so every row has to be
            # re-measured — not just repainted.
            self.scheduleDelayedItemsLayout()
        self._place_jump()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._delegate.set_viewport_width(self.viewport().width())
        self._place_jump()

    # --- following the conversation ---------------------------------------

    def _on_scrolled(self, _value: int) -> None:
        if self._is_at_end() and self._pending_new:
            # They caught up by hand. Nothing left to offer.
            self._pending_new = 0
        self._update_jump()

    def _on_jump_clicked(self) -> None:
        self._pending_new = 0
        self.scroll_to_end()
        self._update_jump()

    def _update_jump(self) -> None:
        count = self._pending_new
        if not count or self._is_at_end():
            self._jump.setVisible(False)
            return
        self._jump.setText(
            "1 new message  ↓" if count == 1 else f"{count} new messages  ↓"
        )
        self._jump.adjustSize()
        self._place_jump()
        self._jump.setVisible(True)
        self._jump.raise_()

    def _place_jump(self) -> None:
        if not hasattr(self, "_jump"):
            return
        area = self.viewport().rect()
        size = self._jump.sizeHint()
        self._jump.setGeometry(
            area.center().x() - size.width() // 2,
            area.bottom() - size.height() - 10,
            size.width(), size.height(),
        )

    def scroll_to_end(self) -> None:
        if self._model.rowCount():
            self.scrollToBottom()

    def _is_at_end(self) -> bool:
        """Near enough the bottom to count as following the conversation.

        A line of slack rather than four pixels: a transcript that has just
        grown by one bubble leaves the reader a few pixels short of the maximum
        through no action of their own, and treating that as "they scrolled
        away" makes the view stop following for no reason they can see.
        """
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - FOLLOW_SLACK

    # --- interaction ------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:
        """Track which bubble the pointer is over, and repaint only on change.

        Repainting the viewport on every mouse move would be a full delegate
        pass per pixel; repainting only when the hovered id changes is one pass
        per bubble crossed.
        """
        message = self._model.message_at(self.indexAt(event.pos()))
        hovered = None if message is None else message.id
        if hovered != self._delegate._hover_id:
            self._delegate.set_hovered(hovered)
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._delegate._hover_id is not None:
            self._delegate.set_hovered(None)
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        index = self.indexAt(event.pos())
        message = self._model.message_at(index)
        if message is not None:
            chip = self._delegate.attachment_rect(message.id)
            if chip is not None and chip.contains(event.pos()):
                attachment = attachment_of(message)
                if attachment is not None:
                    self.attachmentRequested.emit(
                        attachment["file_id"], attachment["file_name"],
                    )
                return
            hit = self._delegate.read_more_rect(message.id)
            if hit is not None and hit.contains(event.pos()):
                self._model.toggle_expanded(message.id)
                self.readMoreToggled.emit(message.id)
                # The row's height changed; ask the view to re-measure.
                self._delegate.sizeHintChanged.emit(index)
                return
        super().mousePressEvent(event)

    def _show_menu(self, position: QPoint) -> None:
        index = self.indexAt(position)
        message = self._model.message_at(index)
        if message is None:
            return

        menu = QMenu(self)

        copy_action = menu.addAction("Copy message")

        attachment = attachment_of(message)
        open_file = None
        if attachment is not None:
            open_file = menu.addAction("Open attachment")

        menu.addSeparator()

        like = menu.addAction("Like")
        dislike = menu.addAction("Dislike")
        clear = menu.addAction("Clear my reaction")
        for action in (like, dislike, clear):
            # A withdrawn message has nothing left to have an opinion about —
            # the server refuses it with a 403.
            action.setEnabled(not message.removed)

        menu.addSeparator()
        pin = menu.addAction("Pin / unpin this message")
        email = menu.addAction("Email this message to the patient")
        email.setEnabled(not message.is_system and not message.removed)

        edit = remove = None
        if message.editable:
            # ONLY when the server said so. Deriving this from sender_type
            # would offer Edit on an automated message and get a 403.
            menu.addSeparator()
            edit = menu.addAction("Edit…")
            remove = menu.addAction("Withdraw")

        chosen = menu.exec(self.viewport().mapToGlobal(position))
        if chosen is None:
            return

        if chosen is copy_action:
            # THE WHOLE BODY, never the clamped text.
            QGuiApplication.clipboard().setText(message.body or "")
        elif open_file is not None and chosen is open_file:
            self.attachmentRequested.emit(attachment["file_id"], attachment["file_name"])
        elif chosen is like:
            self.reactRequested.emit(message.id, 1)
        elif chosen is dislike:
            self.reactRequested.emit(message.id, -1)
        elif chosen is clear:
            self.reactRequested.emit(message.id, None)
        elif chosen is pin:
            self.pinRequested.emit(message.id)
        elif chosen is email:
            self.emailRequested.emit(message.id)
        elif edit is not None and chosen is edit:
            self.editRequested.emit(message.id)
        elif remove is not None and chosen is remove:
            self.removeRequested.emit(message.id)

    def message_by_id(self, message_id: int):
        for row in range(self._model.rowCount()):
            message = self._model.message_at(self._model.index(row, 0))
            if message is not None and message.id == message_id:
                return message
        return None
