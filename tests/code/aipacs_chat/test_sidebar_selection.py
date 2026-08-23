"""Clicking a row in the sidebar, all the way to the data on screen.

THE CHAIN THIS COVERS, end to end:

    click -> caseActivated(id) -> openCase(id) -> ``case=<id>`` on the wire
          -> thread -> transcript, presence, receipts, status
          -> loadCaseDetail(id) -> the right-hand panel

Each link used to be tested in isolation, which is how the panel could be
empty in production while every test passed: the SERVER's case-detail endpoint
answers 500 for most conversations (verified live, 2026-08-23), and the client
had no answer for that beyond a four-word strip under the transcript.

So these also pin the behaviour that makes a click useful WITHOUT that
endpoint: the panel is drawn from the row the operator clicked before any
request goes out, and a failure degrades to identity-plus-error rather than to
a blank column.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QObject, QPoint, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from modules.aipacs_chat.services.models import ChatMessage, ConversationRow  # noqa: E402
from modules.aipacs_chat.ui.case_panel import CasePanel  # noqa: E402
from modules.aipacs_chat.ui.chat_widget import AiPacsChatWidget  # noqa: E402
from modules.aipacs_chat.ui.conversation_list import ConversationListView  # noqa: E402


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Repo(QObject):
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
        self.opened = []
        self.detail_loads = []

    def start(self): pass
    def stop(self): pass
    def setVisible(self, visible): pass
    def setNotificationsEnabled(self, enabled): pass
    def setFilters(self, filters): pass
    def retryAfterSignIn(self): pass
    def setComposerHasText(self, has_text): pass

    def openCase(self, case_id):
        self.opened.append(case_id)
        self.open_case = case_id

    def loadCaseDetail(self, case_id):
        self.detail_loads.append(case_id)


def _row(case_id, **overrides):
    fields = {
        "id": case_id,
        "label": f"Patient {case_id}",
        "ref": str(9400000 + case_id),
        "unread": 0,
        "online": False,
        "ago": "2m",
        "preview": "hello",
        "sender": "patient",
        "status": "awaiting_images",
        "tone": "wait",
    }
    fields.update(overrides)
    return ConversationRow.parse(fields)


def _message(mid, body="hello"):
    return ChatMessage.parse({
        "id": mid, "sender_type": "patient", "type": "text",
        "body": body, "at": "2026-08-22T10:00:00Z",
    })


def _detail(case_id, **overrides):
    detail = {
        "id": case_id,
        "display_label": f"Patient {case_id}",
        "reference": str(9400000 + case_id),
        "email": f"p{case_id}@example.com",
        "phone": "0912345678",
        "status": "awaiting_images",
        "status_tone": "wait",
        "stage": {"label": "Waiting for images"},
        "summaries": {"imaging": "1 file", "location": "Iran"},
        "files": [],
        "patient_online": True,
    }
    detail.update(overrides)
    return detail


def _widget(qapp):
    repo = _Repo()
    widget = AiPacsChatWidget(repository=repo)
    repo.stateChanged.emit("ready")
    qapp.processEvents()
    return widget, repo


def _panel_text(widget):
    return " ".join(
        label.text() for body in widget.case_panel._bodies.values()
        for label in body.findChildren(QLabel)
    )


# ── the click itself ─────────────────────────────────────────────────────────


def test_clicking_a_row_emits_its_case_id(qapp):
    view = ConversationListView()
    view.resize(320, 400)
    view.show()
    qapp.processEvents()
    view.set_rows([_row(41), _row(87)])
    qapp.processEvents()

    seen = []
    view.caseActivated.connect(seen.append)

    index = view._model.index_of_case(87)
    view.clicked.emit(index)

    assert seen == [87], "the sidebar row did not report the case it stands for"
    view.close()


def test_a_click_opens_that_case_and_asks_for_its_details(qapp):
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(41), _row(87)))
    qapp.processEvents()

    widget._on_case_activated(87)
    qapp.processEvents()

    assert repo.opened == [87], "the wrong case id reached the repository"
    assert repo.detail_loads == [87], "the panel's own request was never made"
    assert widget.thread_header.text() == "Patient 87"
    assert widget.conversation_list.current_case_id() == 87, "the row is not highlighted"

    widget.cleanup()


def test_the_selected_row_is_visibly_current(qapp):
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(41), _row(87)))
    qapp.processEvents()

    widget._on_case_activated(41)
    qapp.processEvents()

    index = widget.conversation_list.currentIndex()
    assert index.isValid()
    assert widget.conversation_list._model.row_at(index).id == 41

    widget.cleanup()


# ── what a click puts on screen ──────────────────────────────────────────────


def test_the_panel_is_populated_from_the_row_before_the_server_answers(qapp):
    """A click must never leave the right-hand column blank."""
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(87, label="Maria Rossi", ref="9400123"),))
    qapp.processEvents()

    widget._on_case_activated(87)
    qapp.processEvents()

    assert "Maria Rossi" in widget.case_panel.header.text()
    text = _panel_text(widget)
    assert "Maria Rossi" in text
    assert "9400123" in text

    widget.cleanup()


def test_the_full_detail_replaces_the_preliminary_one(qapp):
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(87),))
    qapp.processEvents()
    widget._on_case_activated(87)
    qapp.processEvents()

    repo.caseDetailLoaded.emit(_detail(87))
    qapp.processEvents()

    text = _panel_text(widget)
    assert "p87@example.com" in text
    assert "0912345678" in text
    assert "Loading" not in text, "the placeholder outlived the answer"

    widget.cleanup()


def test_the_thread_reaches_the_transcript(qapp):
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(87),))
    qapp.processEvents()
    widget._on_case_activated(87)

    repo.threadReplaced.emit(87, (_message(1, "first"), _message(2, "second")))
    repo.presenceChanged.emit(87, True, False)
    repo.caseStatusChanged.emit(87, "priced", "wait")
    qapp.processEvents()

    assert widget.transcript.message_count() == 2
    assert widget.presence_label.text() == "online"
    assert "priced" in widget.case_panel.status_chip.text()

    widget.cleanup()


# ── no stale data, ever ──────────────────────────────────────────────────────


def test_switching_patients_clears_the_previous_transcript_immediately(qapp):
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(41), _row(87)))
    qapp.processEvents()

    widget._on_case_activated(41)
    repo.threadReplaced.emit(41, (_message(1, "case 41 message"),))
    qapp.processEvents()
    assert widget.transcript.message_count() == 1

    widget._on_case_activated(87)
    qapp.processEvents()

    assert widget.transcript.message_count() == 0, (
        "the previous patient's words were still on screen while the next loaded"
    )

    widget.cleanup()


def test_a_late_answer_for_the_previous_patient_is_dropped(qapp):
    """Switching fast must not mix two patients' data."""
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(41), _row(87)))
    qapp.processEvents()

    widget._on_case_activated(41)
    widget._on_case_activated(87)          # before 41's answers came back
    qapp.processEvents()

    repo.threadReplaced.emit(41, (_message(1, "case 41 message"),))
    repo.caseDetailLoaded.emit(_detail(41, display_label="WRONG PATIENT"))
    repo.presenceChanged.emit(41, True, False)
    qapp.processEvents()

    assert widget.transcript.message_count() == 0
    assert "WRONG PATIENT" not in widget.case_panel.header.text()
    assert "WRONG PATIENT" not in _panel_text(widget)

    widget.cleanup()


def test_a_late_failure_for_the_previous_patient_is_dropped(qapp):
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(41), _row(87)))
    qapp.processEvents()

    widget._on_case_activated(41)
    widget._on_case_activated(87)
    qapp.processEvents()

    repo.caseDetailFailed.emit(41, "Server Error")
    qapp.processEvents()

    assert "could not be loaded" not in _panel_text(widget), (
        "an error for a conversation the operator left was written over the open one"
    )

    widget.cleanup()


# ── the endpoint that is currently 500ing ────────────────────────────────────


def test_a_detail_failure_is_retried_once_then_reported_in_the_panel(qapp):
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(87, label="Maria Rossi"),))
    qapp.processEvents()
    widget._on_case_activated(87)
    qapp.processEvents()
    assert repo.detail_loads == [87]

    repo.caseDetailFailed.emit(87, "Server Error")
    qapp.processEvents()
    # First failure buys a retry, not an error message.
    assert "could not be loaded" not in _panel_text(widget)

    widget._retry_case_detail(87)
    assert repo.detail_loads == [87, 87], "the one retry never happened"

    repo.caseDetailFailed.emit(87, "Server Error")
    qapp.processEvents()

    text = _panel_text(widget)
    assert "could not be loaded" in text
    assert "Server Error" in text
    # Identity survives the failure — the row already told us who this is.
    assert "Maria Rossi" in widget.case_panel.header.text()

    widget.cleanup()


def test_the_panel_offers_a_way_to_ask_again(qapp):
    widget, repo = _widget(qapp)
    repo.rowsReplaced.emit((_row(87),))
    qapp.processEvents()
    widget._on_case_activated(87)
    widget._detail_retries = 5            # past the automatic retry
    repo.caseDetailFailed.emit(87, "Server Error")
    qapp.processEvents()

    buttons = [b for b in widget.case_panel._bodies["identity"].findChildren(QPushButton)
               if "again" in b.text().lower()]
    assert buttons, "a failed panel gave the operator nothing to do"

    before = len(repo.detail_loads)
    buttons[0].click()
    qapp.processEvents()
    assert len(repo.detail_loads) == before + 1

    widget.cleanup()


# ── re-clicking the conversation already open ────────────────────────────────


def test_reopening_the_same_case_asks_the_server_cold_again(qapp):
    """The widget blanks the transcript on every click, including this one.

    Without a cursor reset the next poll asks for messages newer than the
    newest already seen, gets none, and the transcript stays empty.
    """
    from modules.aipacs_chat.services.sync_engine import SyncEngine

    engine = SyncEngine(now_ms=0)
    engine.set_open_case(41)
    engine.apply_cursor = None  # not used; kept explicit for readers

    # Pretend a page of messages has been consumed.
    engine._cursor = engine._cursor.__class__(
        m=812, rev=999, ev=engine._cursor.ev, req=engine._cursor.req
    )

    engine.set_open_case(41)                    # a plain re-select: no change
    assert engine.cursor.m == 812

    engine.set_open_case(41, force=True)        # what openCase now does
    assert engine.cursor.m == 0
    assert engine.cursor.rev == 0
    assert engine.open_case == 41


def test_reopening_keeps_the_event_cursor(qapp):
    """Notifications are about the whole inbox, not the open conversation."""
    from modules.aipacs_chat.services.sync_engine import SyncEngine

    engine = SyncEngine(now_ms=0, ev_cursor=4242)
    engine.set_open_case(41)
    engine.set_open_case(41, force=True)

    assert engine.event_cursor == 4242
