"""In-app notification banners for the chat console.

WHY NOT A DIALOG. A radiologist is reporting when a patient writes. A modal —
or anything that takes focus — interrupts a clinical task to announce a chat
message, which is worse than not announcing it at all. These banners are
overlay children of the content page: they never take focus, never block
input, and disappear on their own.

WHY NOT A TRAY ICON. The workstation has never had a `QSystemTrayIcon` (a
search of the repo finds zero), and adding one is an app-global surface
decision — an icon that outlives this tab, in a product whose notification
convention today is the account-pill badge. The banner plus the tab-title
count keeps the announcement inside the module that owns it. If the owner
wants desktop-level toasts later, that is one call added here, not a rewrite.

CLICKING OPENS BY ``case``, NEVER BY ``url``. ``ConsoleEvent.url`` is an
absolute WEB console address; following it would throw the operator out of the
workstation and into a browser session they are not signed in to. The model's
own docstring says so, and this is the code that would otherwise be tempted.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# How many banners can be on screen at once. Beyond this the oldest is
# retired: a stack of nine is a wall, not a notification.
MAX_VISIBLE = 3
DISMISS_MS = 9000
BANNER_WIDTH = 340

# What each kind is CALLED on the banner, so a new consultation request and a
# reply in a conversation already in hand are told apart at a glance. They
# demand different things of an operator — one is work arriving, the other is
# work continuing — and a banner that reads the same for both makes the
# operator open it to find out which.
KIND_LABELS = {
    "request": "New consultation request",
    "message": "New message",
    "status": "Status changed",
    "unsubmitted": "Form left unfinished",
}
KIND_TONES = {
    "request": "good",
    "message": "work",
    "status": "wait",
    "unsubmitted": "alert",
}


class LocalEvent:
    """An event the CLIENT noticed, shaped like one from the server.

    The server's feed is the source of truth for notifications, and this is not
    a second one — it is the safety net for the single case the feed can miss
    from where this client stands: a conversation that appears in the list
    having never been announced. A request that arrives while the console is
    closed, or on a server build whose feed predates the ``request`` kind,
    would otherwise land silently in a list nobody is looking at.

    Given the same shape as ``ConsoleEvent`` so the banner code has one type to
    understand, and de-duplicated by case in the widget so the operator never
    sees both this and the server's own announcement.
    """

    should_alert = True

    def __init__(self, kind: str, case: int, title: str, who: str = "", body: str = ""):
        self.key = f"local-{kind}-{int(case)}"
        self.kind = str(kind)
        self.case = int(case)
        self.title = str(title)
        self.who = str(who)
        self.body = str(body)
        self.url = ""


class _Banner(QFrame):
    """One card. Click the body to open the conversation; × to dismiss."""

    activated = Signal(int)
    dismissed = Signal(object)

    def __init__(self, event, parent=None):
        super().__init__(parent)
        self._case = int(getattr(event, "case", 0) or 0)
        self.setObjectName("ChatNotifyBanner")
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedWidth(BANNER_WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        # Never take focus from whatever the operator is typing into.
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 8, 10)
        lay.setSpacing(2)

        kind = str(getattr(event, "kind", "") or "")
        self.setProperty("chatNotifyKind", kind or "message")

        # A tone strip down the leading edge. The colour is the same one the
        # case's status chip uses, so "green means a new request" is learned
        # once and holds everywhere in the module.
        from .styles import tone_color

        self._tone = tone_color(KIND_TONES.get(kind, "work"))

        kind_row = QLabel(KIND_LABELS.get(kind, "New activity"), self)
        kind_row.setObjectName("ChatNotifyKind")
        kind_row.setStyleSheet(
            f"color:{self._tone}; font-size:10px; font-weight:700;"
            " letter-spacing:0.6px;"
        )
        lay.addWidget(kind_row)

        top = QHBoxLayout()
        top.setSpacing(6)
        title = QLabel(str(getattr(event, "title", "") or "New activity"), self)
        title.setObjectName("ChatNotifyTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)

        close = QPushButton("×", self)
        close.setObjectName("ChatNotifyClose")
        close.setFixedSize(20, 20)
        close.setFocusPolicy(Qt.NoFocus)
        close.setCursor(Qt.ArrowCursor)
        close.clicked.connect(self._dismiss)
        top.addWidget(close, 0, Qt.AlignTop)
        lay.addLayout(top)

        who = str(getattr(event, "who", "") or "")
        body = str(getattr(event, "body", "") or "")
        line = " — ".join(part for part in (who, body) if part)
        if line:
            body_label = QLabel(line, self)
            body_label.setObjectName("ChatNotifyBody")
            body_label.setWordWrap(True)
            lay.addWidget(body_label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DISMISS_MS)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton and self._case:
            self.activated.emit(self._case)
            self._dismiss()
            return
        super().mouseReleaseEvent(event)

    def _dismiss(self) -> None:
        try:
            self._timer.stop()
        except Exception:  # pragma: no cover - defensive
            pass
        self.dismissed.emit(self)


class NotificationStack(QObject):
    """Owns the banner overlay for one content page.

    Anchored top-right of ``host`` and repositioned on resize. Nothing here
    keeps a widget alive after its page dies: every banner is a child of the
    host, so the host's destruction takes them with it.
    """

    caseRequested = Signal(int)

    def __init__(self, host: QWidget):
        super().__init__(host)
        self._host = host
        self._banners: list[_Banner] = []
        host.installEventFilter(self)

    # ── public ────────────────────────────────────────────────────────────
    def show_events(self, events) -> None:
        """Raise a banner for each event that asks to interrupt.

        ``should_alert`` is the model's policy — ``message`` and ``request``
        interrupt; ``status`` and ``unsubmitted`` are feed entries and do not.
        Honour it rather than deciding again here.
        """
        for event in events or ():
            try:
                if not getattr(event, "should_alert", False):
                    continue
                self._add(event)
            except Exception as exc:  # pragma: no cover - never break the poll
                logger.debug("aipacs_chat: banner failed: %s", exc)

    def show_local(self, event) -> None:
        """Raise one banner for something the client noticed itself."""
        try:
            self._add(event)
        except Exception as exc:  # pragma: no cover - never break the poll
            logger.debug("aipacs_chat: local banner failed: %s", exc)

    def clear(self) -> None:
        for banner in list(self._banners):
            self._retire(banner)

    def visible_count(self) -> int:
        return len(self._banners)

    # ── internals ─────────────────────────────────────────────────────────
    def _add(self, event) -> None:
        banner = _Banner(event, self._host)
        banner.activated.connect(self.caseRequested)
        banner.dismissed.connect(self._retire)
        self._banners.append(banner)
        while len(self._banners) > MAX_VISIBLE:
            self._retire(self._banners[0])
        banner.show()
        banner.raise_()
        self._reposition()

    def _retire(self, banner) -> None:
        try:
            self._banners.remove(banner)
        except ValueError:
            return
        try:
            banner.setParent(None)
            banner.deleteLater()
        except Exception:  # pragma: no cover - defensive
            pass
        self._reposition()

    def _reposition(self) -> None:
        try:
            margin = 16
            y = margin
            width = self._host.width()
            for banner in self._banners:
                banner.adjustSize()
                banner.move(max(margin, width - BANNER_WIDTH - margin), y)
                banner.raise_()
                y += banner.height() + 8
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("aipacs_chat: banner reposition failed: %s", exc)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        if obj is self._host and event.type() in (QEvent.Resize, QEvent.Show):
            self._reposition()
        return False
