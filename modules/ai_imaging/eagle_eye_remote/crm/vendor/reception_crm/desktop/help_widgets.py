"""Reusable UI pieces that carry the explanations from ``help.py``.

Four things live here:

``HelpButton``   the «؟» next to a field. Hover shows one line; click opens the
                 full explanation in a popup that closes when you click away.
``StatusChip``   a coloured dot plus a word, so connection state is readable at
                 a glance without parsing a sentence.
``Callout``      an inline note — information, caution, or success.
``Disclosure``   a collapsible block used for «تنظیمات پیشرفته» and «جزئیات فنی».

All of them are plain ``QWidget`` subclasses styled through object names in
``theme.py``; none of them own state or talk to the network.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .help import Help


# --------------------------------------------------------------------------- #
# help popup
# --------------------------------------------------------------------------- #
class HelpPopup(QFrame):
    """Frameless panel with the full explanation. Closes on click-outside."""

    def __init__(self, topic: Help, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Popup)
        self.setObjectName("HelpPopup")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMaximumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)

        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        title = QLabel(topic.title)
        title.setObjectName("HelpTitle")
        title.setWordWrap(True)
        header_row.addWidget(title, 1)
        if topic.requirement_label:
            badge = QLabel(topic.requirement_label)
            badge.setObjectName("BadgeRequired" if topic.required else "BadgeOptional")
            header_row.addWidget(badge, 0, Qt.AlignTop)
        layout.addWidget(header)

        for heading, text in topic.rows():
            label = QLabel(heading)
            label.setObjectName("HelpHeading")
            body = QLabel(text)
            body.setObjectName("HelpBody")
            body.setWordWrap(True)
            layout.addWidget(label)
            layout.addWidget(body)

        if topic.warning:
            layout.addWidget(Callout(topic.warning, "warn"))

        if topic.steps:
            label = QLabel("مراحل")
            label.setObjectName("HelpHeading")
            layout.addWidget(label)
            for index, step in enumerate(topic.steps, start=1):
                step_label = QLabel(f"{index}. {step}")
                step_label.setObjectName("HelpBody")
                step_label.setWordWrap(True)
                layout.addWidget(step_label)

        if topic.technical:
            technical = QLabel(f"نام فنی: {topic.technical}")
            technical.setObjectName("HelpTechnical")
            technical.setLayoutDirection(Qt.LeftToRight)
            technical.setAlignment(Qt.AlignRight)
            layout.addWidget(technical)

    def show_near(self, anchor: QWidget) -> None:
        """Open below the anchor, nudged back on screen if it would clip."""
        self.adjustSize()
        point = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        screen = anchor.screen() or self.screen()
        if screen:
            available = screen.availableGeometry()
            x = min(max(point.x(), available.left() + 8), available.right() - self.width() - 8)
            y = point.y()
            if y + self.height() > available.bottom():
                y = max(available.top() + 8, anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 6)
            point = QPoint(x, y)
        self.move(point)
        self.show()


class HelpButton(QToolButton):
    """The «؟» affordance. One line on hover, the whole story on click."""

    def __init__(self, topic: Help, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.topic = topic
        self.setObjectName("HelpButton")
        self.setText("؟")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFocusPolicy(Qt.TabFocus)
        self.setFixedSize(19, 19)
        self.setAccessibleName(f"راهنمای {topic.title}")
        self.setToolTip(self._tooltip())
        self.clicked.connect(self.open_popup)
        self._popup: HelpPopup | None = None

    def _tooltip(self) -> str:
        lines = [f"<b>{self.topic.title}</b>", self.topic.summary()]
        if self.topic.requirement_label:
            lines.append(f"<i>{self.topic.requirement_label}</i>")
        lines.append(f"<span style='color:{theme.active().faint}'>برای توضیح کامل کلیک کنید</span>")
        return "<div dir='rtl' style='max-width:280px'>" + "<br>".join(lines) + "</div>"

    def open_popup(self) -> None:
        self._popup = HelpPopup(self.topic, self)
        self._popup.show_near(self)


def labeled(text: str, topic: Help | None) -> QWidget:
    """A form label with its help button attached.

    Returned instead of a bare string so ``QFormLayout`` keeps the «؟» glued to
    the label rather than letting it drift into the field column.
    """
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(5)
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    row.addWidget(label)
    if topic is not None:
        row.addWidget(HelpButton(topic))
        if topic.required:
            star = QLabel("*")
            star.setObjectName("RequiredStar")
            star.setToolTip("این مقدار الزامی است")
            row.addWidget(star)
    row.addStretch(1)
    host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return host


def described(widget: QWidget, text: str) -> QWidget:
    """Stack a one-line description under a control.

    Used for checkboxes, where the label lives on the control itself and there
    is no label column to hang an explanation from.
    """
    host = QWidget()
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(2)
    column.addWidget(widget)
    note = QLabel(text)
    note.setObjectName("FieldNote")
    note.setWordWrap(True)
    # A wrapped QLabel reports its unwrapped width as the size hint, so inside a
    # form it gets one line of space and clips the rest. Asking for a minimum
    # height that follows the width is what makes the second line appear.
    note.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    note.setMinimumHeight(note.fontMetrics().height())
    column.addWidget(note)
    host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return host


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
class StatusChip(QLabel):
    """Connection state as a coloured word.

    States are named after what the user sees, not after HTTP semantics:

        ok          متصل
        warn        نیازمند تنظیم / نیازمند ورود
        bad         خطا در اتصال
        idle        تنظیم نشده
        off         غیرفعال
        busy        در حال بررسی
    """

    LABELS = {
        "ok": "متصل",
        "warn": "نیازمند تکمیل",
        "bad": "خطا در اتصال",
        "idle": "تنظیم نشده",
        "off": "غیرفعال",
        "busy": "در حال بررسی…",
    }
    OBJECT_NAMES = {
        "ok": "ChipOk",
        "warn": "ChipWarn",
        "bad": "ChipBad",
        "idle": "ChipIdle",
        "off": "ChipIdle",
        "busy": "ChipBusy",
    }
    DOTS = {"ok": "●", "warn": "●", "bad": "●", "idle": "○", "off": "○", "busy": "◐"}

    def __init__(self, state: str = "idle", text: str = "") -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.set_state(state, text)

    def set_state(self, state: str, text: str = "") -> None:
        state = state if state in self.LABELS else "idle"
        self._state = state
        self.setText(f"{self.DOTS[state]}  {text or self.LABELS[state]}")
        self.setObjectName(self.OBJECT_NAMES[state])
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    @property
    def state(self) -> str:
        return self._state


# --------------------------------------------------------------------------- #
# callout + disclosure
# --------------------------------------------------------------------------- #
class Callout(QFrame):
    """An inline note. ``tone`` is one of info / warn / bad / ok."""

    OBJECT_NAMES = {"info": "CalloutInfo", "warn": "CalloutWarn", "bad": "CalloutBad", "ok": "CalloutOk"}
    ICONS = {"info": "i", "warn": "!", "bad": "!", "ok": "✓"}

    def __init__(self, text: str, tone: str = "info", action: tuple[str, Callable[[], None]] | None = None) -> None:
        super().__init__()
        tone = tone if tone in self.OBJECT_NAMES else "info"
        self.setObjectName(self.OBJECT_NAMES[tone])
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(9)

        icon = QLabel(self.ICONS[tone])
        icon.setObjectName("CalloutIcon")
        icon.setFixedWidth(16)
        icon.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        row.addWidget(icon)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setObjectName("CalloutText")
        row.addWidget(self.label, 1)

        if action:
            button = QToolButton()
            button.setText(action[0])
            button.setObjectName("CalloutAction")
            button.setCursor(QCursor(Qt.PointingHandCursor))
            button.clicked.connect(action[1])
            row.addWidget(button, 0, Qt.AlignTop)

    def set_text(self, text: str) -> None:
        self.label.setText(text)


class Disclosure(QWidget):
    """A titled block that starts collapsed.

    Advanced settings and technical error details both use it, which is what
    keeps the ordinary path free of things most users never need to touch.
    """

    def __init__(self, title: str, body: QWidget, note: str = "", expanded: bool = False) -> None:
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        self.toggle = QToolButton()
        self.toggle.setObjectName("DisclosureToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setCursor(QCursor(Qt.PointingHandCursor))
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._title = title
        self.toggle.clicked.connect(self._sync)
        column.addWidget(self.toggle, 0, Qt.AlignRight)

        if note:
            hint = QLabel(note)
            hint.setObjectName("FieldNote")
            hint.setWordWrap(True)
            column.addWidget(hint)
            self._note = hint
        else:
            self._note = None

        self.body = body
        column.addWidget(body)
        self._sync()

    def _sync(self) -> None:
        expanded = self.toggle.isChecked()
        self.toggle.setText(("▾  " if expanded else "▸  ") + self._title)
        self.body.setVisible(expanded)
        if self._note is not None:
            self._note.setVisible(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(expanded)
        self._sync()


def section_header(topic: Help, extra: QWidget | None = None) -> QWidget:
    """Title + one-line purpose + help button, used at the top of each area."""
    host = QWidget()
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(3)

    top = QWidget()
    row = QHBoxLayout(top)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(7)
    title = QLabel(topic.title)
    title.setObjectName("SectionTitle")
    row.addWidget(title)
    row.addWidget(HelpButton(topic))
    row.addStretch(1)
    if extra is not None:
        row.addWidget(extra)
    column.addWidget(top)

    if topic.what:
        hint = QLabel(topic.what)
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        column.addWidget(hint)
    return host
