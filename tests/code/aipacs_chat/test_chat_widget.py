"""The tab shell: states, rows, theming, and a close that does not hang.

Offscreen Qt, no network — the widget is handed a fake repository, which is
exactly what the repository exists for.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modules.aipacs_chat.services.models import ConversationRow, Counts  # noqa: E402
from modules.aipacs_chat.ui.chat_widget import AiPacsChatWidget  # noqa: E402


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeRepository(QObject):
    """Every signal and slot the widget touches.

    A double that is missing a member the real object has does not fail
    honestly — it fails at connect() with an AttributeError, which reads like a
    widget bug. Mirror the real signature; there is an in-repo comment about a
    stale double doing exactly this and silently reddening eight tests.
    """

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
    # Added 2026-08-23 with the panel's own failure path. Same rule as the
    # notification feed above: the widget connects it, so the double carries it.
    caseDetailFailed = Signal(int, str)
    savedRepliesLoaded = Signal(object)
    pricingLoaded = Signal(object)
    statusesLoaded = Signal(object)

    writeSucceeded = Signal(str, object)
    writeFailed = Signal(str, str)

    # The notification feed. Added 2026-08-22 when the widget finally started
    # listening to it: a double missing a member the real object has fails at
    # connect() with an AttributeError, which reads like a widget bug.
    eventsArrived = Signal(object)

    # Attachments. Same rule as above: the widget connects this in
    # _connect_repository, so the double has to carry it.
    fileDownloaded = Signal(int, object)

    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False
        self.notifications_enabled = []
        self.visible_calls = []
        self.opened = []
        self.filters = []
        self.retried = 0
        self.event_cursor = 4242
        self.open_case = None
        self.sent = []
        self.prices = []
        self.statuses = []
        self.reactions = []
        self.edits = []
        self.removals = []
        self.pins = []
        self.emails = []
        self.detail_loads = []
        self.composer_text = []
        self.downloads = []
        self.sent_with_files = []
        self.pinned_cases = []
        self.rotations = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def setVisible(self, visible):
        self.visible_calls.append(bool(visible))

    def setNotificationsEnabled(self, enabled):
        self.notifications_enabled.append(bool(enabled))

    def openCase(self, case_id):
        self.opened.append(case_id)
        self.open_case = case_id

    def setFilters(self, filters):
        self.filters.append(filters)

    def retryAfterSignIn(self):
        self.retried += 1

    def setComposerHasText(self, has_text):
        self.composer_text.append(bool(has_text))

    def sendMessage(self, body):
        self.sent.append(body)

    def sendMessageWithFiles(self, body, paths, is_report=False):
        self.sent_with_files.append((body, list(paths or []), bool(is_report)))

    def sendPrice(self, tier):
        self.prices.append(tier)

    def setStatus(self, status, note=""):
        self.statuses.append(status)

    def react(self, message_id, value):
        self.reactions.append((message_id, value))

    def editMessage(self, message_id, body):
        self.edits.append((message_id, body))

    def removeMessage(self, message_id):
        self.removals.append(message_id)

    def pinMessage(self, message_id):
        self.pins.append(message_id)

    def pinCase(self, case_id):
        self.pinned_cases.append(case_id)

    def rotateLink(self):
        self.rotations += 1

    def emailMessage(self, message_id):
        self.emails.append(message_id)

    def loadCaseDetail(self, case_id):
        self.detail_loads.append(case_id)

    def downloadFile(self, file_id, file_name=""):
        self.downloads.append((file_id, file_name))


def _row(case_id=41, **overrides):
    fields = {
        "id": case_id,
        "label": "Maria Rossi",
        "ref": "9400123",
        "unread": 2,
        "online": True,
        "ago": "2m",
        "preview": "I uploaded the MRI study.",
        "sender": "patient",
        "status": "awaiting_images",
        "tone": "wait",
    }
    fields.update(overrides)
    return ConversationRow(**fields)


def _widget(qapp):
    repo = _FakeRepository()
    widget = AiPacsChatWidget(repository=repo)
    qapp.processEvents()
    return widget, repo


def test_the_tab_opens_on_the_loading_state_not_an_empty_list(qapp):
    """An empty list that actually means "cannot connect" gets trusted."""
    widget, _ = _widget(qapp)

    assert widget.stack.currentWidget() is widget.page_loading

    widget.cleanup()


def test_each_state_shows_its_own_page(qapp):
    widget, repo = _widget(qapp)

    for state, page in (
        ("notconfigured", widget.page_not_configured),
        ("signedout", widget.page_signed_out),
        ("error", widget.page_error),
        ("ready", widget.page_content),
        ("loading", widget.page_loading),
    ):
        repo.stateChanged.emit(state)
        qapp.processEvents()
        assert widget.stack.currentWidget() is page, state

    widget.cleanup()


def test_rows_reach_the_list_and_keep_their_identity(qapp):
    widget, repo = _widget(qapp)

    repo.rowsReplaced.emit((_row(41), _row(87, label="Jan Novak", ref="9400124")))
    qapp.processEvents()

    assert widget.conversation_list._model.rowCount() == 2
    assert widget.conversation_list.row_for_case(41).title == "Maria Rossi"
    assert widget.conversation_list.row_for_case(87).title == "Jan Novak"

    widget.cleanup()


def test_a_row_without_a_name_still_has_a_title(qapp):
    widget, repo = _widget(qapp)

    repo.rowsReplaced.emit((_row(41, label="", ref="9400123"),))
    qapp.processEvents()

    assert widget.conversation_list.row_for_case(41).title == "#9400123"

    widget.cleanup()


def test_the_selection_survives_a_refresh(qapp):
    """The list reorders as messages arrive; the open case must not slide away."""
    widget, repo = _widget(qapp)

    repo.rowsReplaced.emit((_row(41), _row(87)))
    qapp.processEvents()
    widget.conversation_list.select_case(87)
    assert widget.conversation_list.current_case_id() == 87

    # Same two conversations, reordered by a new message on 41.
    repo.rowsReplaced.emit((_row(87), _row(41)))
    qapp.processEvents()

    assert widget.conversation_list.current_case_id() == 87

    widget.cleanup()


def test_counts_are_spelled_out_rather_than_echoed(qapp):
    """`none` is the server's name for "not priced yet" — the 72% leak."""
    widget, repo = _widget(qapp)

    repo.countsChanged.emit(Counts(unread=3, online=2, stalled=1, none=4))
    qapp.processEvents()

    assert widget.chip_unread.text() == "Unread 3"
    assert widget.chip_unpriced.text() == "No price 4"

    widget.cleanup()


def test_clicking_a_conversation_opens_it_on_the_repository(qapp):
    widget, repo = _widget(qapp)

    repo.rowsReplaced.emit((_row(41),))
    qapp.processEvents()
    widget._on_case_activated(41)

    assert repo.opened == [41]
    assert "Maria" in widget.thread_header.text()

    widget.cleanup()


def test_a_transient_error_does_not_blank_a_usable_console(qapp):
    """Keep what the operator was reading; the loop retries behind it."""
    widget, repo = _widget(qapp)

    repo.stateChanged.emit("ready")
    qapp.processEvents()
    repo.errorRaised.emit("connection reset")
    qapp.processEvents()

    assert widget.stack.currentWidget() is widget.page_content

    widget.cleanup()


def test_search_is_debounced_and_reaches_the_filters(qapp):
    widget, repo = _widget(qapp)

    widget.search_box.setText("rossi")
    qapp.processEvents()
    assert repo.filters == [], "a query per keystroke LIKE-scans every message body"

    widget._apply_search()
    assert repo.filters[-1].term == "rossi"

    widget.cleanup()


def test_visibility_is_false_for_a_tab_that_is_not_on_screen(qapp):
    """visible drives staff_last_read_at, which is the patient's second tick."""
    widget, repo = _widget(qapp)

    widget._push_visibility()

    assert repo.visible_calls, "the widget must report visibility, never leave it to default"
    assert repo.visible_calls[-1] is False

    widget.cleanup()


def test_closing_stops_the_loop_and_persists_the_event_cursor(qapp):
    widget, repo = _widget(qapp)

    widget.cleanup()

    assert repo.stopped is True
    assert repo.visible_calls[-1] is False

    # Idempotent — the tab manager and closeEvent can both call it.
    widget.cleanup()
    assert repo.stopped is True


def test_retry_asks_the_repository_to_rebuild_its_client(qapp):
    widget, repo = _widget(qapp)

    widget.page_signed_out.action_button.click()
    qapp.processEvents()

    assert repo.retried == 1

    widget.cleanup()


def test_a_theme_change_does_not_raise(qapp):
    widget, _ = _widget(qapp)

    widget._on_theme_changed({"window_bg": "#101010", "text_primary": "#ffffff"})
    qapp.processEvents()

    widget.cleanup()


def test_clicking_an_attachment_asks_the_repository_and_opens_nothing_yet(qapp):
    """The chip starts a download; the file opens when the bytes have landed.

    Opening from the click would mean opening a path that does not exist yet.
    """
    widget, repo = _widget(qapp)

    widget.transcript.attachmentRequested.emit(501, "referral.pdf")
    qapp.processEvents()

    assert repo.downloads == [(501, "referral.pdf")]

    widget.cleanup()


def test_a_download_with_no_path_is_not_opened(qapp):
    """A failure arrives as a null path. Handing that to the shell opens the
    user's home folder, which looks like the application lost the file."""
    widget, repo = _widget(qapp)

    repo.fileDownloaded.emit(501, None)
    qapp.processEvents()

    assert widget.typing_label.text() == ""

    widget.cleanup()
