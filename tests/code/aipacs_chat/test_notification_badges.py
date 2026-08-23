"""Pop-ups for new work, and badges that say how much is waiting.

THE FIRST PAGE IS NOT NEWS. Opening the console must not raise a banner for
every conversation already in the list — that is the failure mode a naive
"announce anything I have not seen" detector has, and it announces sixty
things at once on a busy morning.

ONE ARRIVAL, ONE BANNER. The server's own feed and the client's safety-net
detector both announce new conversations. They share a seen-set so an arrival
the server spoke for is never announced twice.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modules.aipacs_chat.services.models import ConversationRow, Counts  # noqa: E402
from modules.aipacs_chat.ui.chat_widget import AiPacsChatWidget  # noqa: E402
from modules.aipacs_chat.ui.notifications import (  # noqa: E402
    KIND_LABELS,
    LocalEvent,
    NotificationStack,
)


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Repo(QObject):
    """Only what the widget connects to. Mirrors the real signature."""

    stateChanged = Signal(str)
    rowsReplaced = Signal(object)
    countsChanged = Signal(object)
    errorRaised = Signal(str)
    authRequired = Signal(str)
    threadReplaced = Signal(int, object)
    messagesAppended = Signal(int, object)
    messagesRevised = Signal(int, object)
    presenceChanged = Signal(int, bool, bool)
    receiptsChanged = Signal(int, object, object)
    caseStatusChanged = Signal(int, str, str)
    caseDetailLoaded = Signal(object)
    caseDetailFailed = Signal(int, str)
    savedRepliesLoaded = Signal(object)
    pricingLoaded = Signal(object)
    statusesLoaded = Signal(object)
    eventsArrived = Signal(object)
    fileDownloaded = Signal(int, object)
    writeSucceeded = Signal(str, object)
    writeFailed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.event_cursor = 0
        self.open_case = None

    def start(self): pass
    def stop(self): pass
    def setVisible(self, visible): pass
    def setNotificationsEnabled(self, enabled): pass
    def openCase(self, case_id): self.open_case = case_id
    def setFilters(self, filters): pass
    def retryAfterSignIn(self): pass
    def setComposerHasText(self, has_text): pass
    def loadCaseDetail(self, case_id): pass


def _row(case_id, **overrides):
    fields = {
        "id": case_id,
        "label": f"Patient {case_id}",
        "ref": str(9400000 + case_id),
        "unread": 0,
        "online": False,
        "ago": "1m",
        "preview": "I uploaded the MRI study.",
        "sender": "patient",
        "status": "new",
        "tone": "fresh",
    }
    fields.update(overrides)
    return ConversationRow.parse(fields)


class _Event:
    """A server feed entry, only as much of one as the banner reads."""

    def __init__(self, case, kind="message", title="Maria", should_alert=True):
        self.key = f"e{case}"
        self.kind = kind
        self.case = case
        self.title = title
        self.who = ""
        self.body = "hello"
        self.url = "https://ai-pacs.com/consult-form/forms-panel/chat/1"
        self.should_alert = should_alert


def _widget(qapp):
    repo = _Repo()
    widget = AiPacsChatWidget(repository=repo)
    qapp.processEvents()
    return widget, repo


def _banner_count(widget):
    return widget._notifications.visible_count()


# ── new-request pop-ups ──────────────────────────────────────────────────────


def test_the_first_page_of_conversations_raises_no_banners(qapp):
    widget, repo = _widget(qapp)

    repo.rowsReplaced.emit(tuple(_row(n) for n in range(1, 8)))
    qapp.processEvents()

    assert _banner_count(widget) == 0, "opening the console announced work that was already there"

    widget.cleanup()


def test_a_conversation_that_appears_later_pops_up(qapp):
    widget, repo = _widget(qapp)

    repo.rowsReplaced.emit((_row(1), _row(2)))
    qapp.processEvents()
    repo.rowsReplaced.emit((_row(3), _row(1), _row(2)))
    qapp.processEvents()

    assert _banner_count(widget) == 1

    widget.cleanup()


def test_the_same_conversation_is_not_announced_twice(qapp):
    widget, repo = _widget(qapp)

    repo.rowsReplaced.emit((_row(1),))
    qapp.processEvents()
    repo.rowsReplaced.emit((_row(2), _row(1)))
    qapp.processEvents()
    widget._notifications.clear()
    repo.rowsReplaced.emit((_row(2), _row(1)))
    qapp.processEvents()

    assert _banner_count(widget) == 0

    widget.cleanup()


def test_a_case_the_server_already_announced_is_not_announced_again(qapp):
    """The feed spoke for it, so the client's safety net must stay quiet."""
    widget, repo = _widget(qapp)

    repo.rowsReplaced.emit((_row(1),))
    qapp.processEvents()

    repo.eventsArrived.emit((_Event(case=2, kind="request", title="Ali"),))
    qapp.processEvents()
    server_banners = _banner_count(widget)
    assert server_banners == 1

    # Now the row for that same case shows up in the list.
    repo.rowsReplaced.emit((_row(2), _row(1)))
    qapp.processEvents()

    assert _banner_count(widget) == server_banners, "one arrival, two banners"

    widget.cleanup()


def test_banners_stay_off_when_the_operator_turned_them_off(qapp):
    widget, repo = _widget(qapp)
    widget.set_notifications_enabled(False)

    repo.rowsReplaced.emit((_row(1),))
    qapp.processEvents()
    repo.rowsReplaced.emit((_row(2), _row(1)))
    qapp.processEvents()

    assert _banner_count(widget) == 0

    widget.set_notifications_enabled(True)
    widget.cleanup()


def test_a_banner_names_the_kind_of_thing_that_happened(qapp):
    """A new request and a reply demand different things of an operator."""
    from PySide6.QtWidgets import QLabel, QWidget

    host = QWidget()
    host.resize(600, 400)
    stack = NotificationStack(host)

    stack.show_local(LocalEvent(kind="request", case=7, title="Ali"))
    stack.show_events([_Event(case=8, kind="message", title="Maria")])

    texts = [label.text() for label in host.findChildren(QLabel)]
    assert KIND_LABELS["request"] in texts
    assert KIND_LABELS["message"] in texts


def test_a_feed_entry_that_does_not_ask_to_interrupt_does_not(qapp):
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    stack = NotificationStack(host)
    stack.show_events([_Event(case=9, kind="status", should_alert=False)])

    assert stack.visible_count() == 0


# ── badges ───────────────────────────────────────────────────────────────────


def test_the_unread_chip_becomes_a_badge_when_work_is_waiting(qapp):
    widget, repo = _widget(qapp)

    repo.countsChanged.emit(Counts(unread=0, online=2, stalled=0, none=0))
    qapp.processEvents()
    assert not widget.chip_unread.property("chatAlert")

    repo.countsChanged.emit(Counts(unread=4, online=2, stalled=0, none=0))
    qapp.processEvents()
    assert widget.chip_unread.property("chatAlert") is True
    assert "4" in widget.chip_unread.text()

    repo.countsChanged.emit(Counts(unread=0, online=2, stalled=0, none=0))
    qapp.processEvents()
    assert widget.chip_unread.property("chatAlert") is False

    widget.cleanup()


def test_an_empty_queue_never_wears_a_badge(qapp):
    widget, repo = _widget(qapp)

    repo.countsChanged.emit(Counts(unread=0, online=0, stalled=0, none=0))
    qapp.processEvents()

    for chip in (widget.chip_unread, widget.chip_unpriced, widget.chip_stalled):
        assert not chip.property("chatAlert")

    widget.cleanup()


def test_the_unpriced_and_stalled_queues_get_their_own_badges(qapp):
    widget, repo = _widget(qapp)

    repo.countsChanged.emit(Counts(unread=0, online=0, stalled=3, none=9))
    qapp.processEvents()

    assert widget.chip_stalled.property("chatAlert") is True
    assert widget.chip_unpriced.property("chatAlert") is True
    assert widget.chip_unread.property("chatAlert") is False

    widget.cleanup()
