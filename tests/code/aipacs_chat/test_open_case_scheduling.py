"""Opening a case must actually reach the wire, promptly.

THE BUG THIS PINS DOWN (found live, 2026-08-23). Clicking a patient armed the
poll timer for 60 ms; anything that recomputed the ordinary cadence in that
window — the tab's own visibility push, a window activation, a write settling —
re-armed the same timer for the idle interval and the click's poll never ran.
The request carrying ``case=<id>`` was therefore deferred by up to 3 seconds
while visible and 15 while backgrounded, and the sidebar looked dead.

Switching to the chat tab and immediately clicking hits it every time, because
the visibility push and the click arrive on the same turn.
"""

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from modules.aipacs_chat.qt import workers  # noqa: E402
from modules.aipacs_chat.qt.repository import ChatRepository  # noqa: E402
from modules.aipacs_chat.services.models import SyncResponse  # noqa: E402


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _wait_until(app, predicate, timeout_s=5.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


class _RecordingClient:
    """Records the query parameters of every sync it is asked to run."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def sync(self, params):
        pairs = dict(params)
        with self.lock:
            self.calls.append(pairs)
        case = pairs.get("case")
        payload = {
            "t": 1,
            "cursor": {"m": 0, "rev": 100, "ev": 0, "req": int(pairs.get("req", 1))},
            "rows": [],
            # The server answers cold exactly when the client sends rev=0, and
            # the repository branches on it — a cold answer replaces the
            # transcript, a warm one appends to it. A double that always says
            # "warm" makes the two indistinguishable here.
            "cold": pairs.get("rev") == "0",
        }
        if case:
            payload["thread"] = {
                "case": int(case), "m": 5,
                "messages": [{
                    "id": 5, "sender_type": "patient", "type": "text",
                    "body": "hello", "at": "2026-08-22T10:00:00Z",
                }],
                "patient_online": True, "patient_typing": False,
                "status": "awaiting_images", "status_tone": "wait",
            }
        return SyncResponse.parse(payload)

    def cases_asked_for(self):
        with self.lock:
            return [c.get("case") for c in self.calls]


def _repo(client):
    repo = ChatRepository("drv", client=client)
    repo._started = True
    return repo


# ── the scheduling rule ──────────────────────────────────────────────────────


def test_a_cadence_recalculation_does_not_cancel_an_urgent_poll(qapp):
    repo = _repo(_RecordingClient())

    repo.openCase(41)                       # arms the timer for 60 ms
    armed = repo._timer.remainingTime()
    assert 0 <= armed <= 60

    repo.setVisible(False)                  # recomputes the cadence: 15 s
    still = repo._timer.remainingTime()

    assert still <= 60, (
        "the click's poll was pushed out to the idle cadence and the "
        "conversation would not load for seconds"
    )
    repo.stop()


def test_an_explicit_delay_is_still_obeyed(qapp):
    """The guard must not make the repository ignore a caller that means it."""
    repo = _repo(_RecordingClient())

    repo.openCase(41)
    repo._reschedule(5000)

    assert repo._timer.remainingTime() > 60
    repo.stop()


def test_going_visible_still_schedules_promptly(qapp):
    repo = _repo(_RecordingClient())
    repo.setVisible(False)
    repo.setVisible(True)

    assert repo._timer.isActive()
    assert repo._timer.remainingTime() <= 1000
    repo.stop()


# ── the whole click, on a real repository ────────────────────────────────────


def test_opening_a_case_puts_that_case_on_the_wire(qapp):
    client = _RecordingClient()
    repo = _repo(client)

    repo.openCase(41)
    assert _wait_until(qapp, lambda: 41 in [
        int(c) for c in client.cases_asked_for() if c
    ]), "no request ever carried case=41"

    repo.stop()
    _wait_until(qapp, lambda: workers.live_worker_count() == 0)


def test_a_click_racing_a_visibility_push_still_loads_the_conversation(qapp):
    """The exact production sequence: switch to the tab, click a patient."""
    client = _RecordingClient()
    repo = _repo(client)

    threads = []
    repo.threadReplaced.connect(lambda cid, msgs: threads.append((cid, len(msgs))))

    repo.openCase(87)
    repo.setVisible(True)       # the tab announcing itself, same turn
    repo.setVisible(False)      # and again, as focus settles

    assert _wait_until(qapp, lambda: bool(threads)), (
        "the transcript never arrived for the case that was clicked"
    )
    assert threads[0] == (87, 1)

    repo.stop()
    _wait_until(qapp, lambda: workers.live_worker_count() == 0)


def test_switching_cases_asks_for_the_new_one_cold(qapp):
    client = _RecordingClient()
    repo = _repo(client)

    repo.openCase(41)
    assert _wait_until(qapp, lambda: any(
        c.get("case") == "41" for c in client.calls))

    repo.openCase(87)
    assert _wait_until(qapp, lambda: any(
        c.get("case") == "87" for c in client.calls))

    call = [c for c in client.calls if c.get("case") == "87"][0]
    assert call["m"] == "0", "case 87 was asked for from case 41's high-water mark"
    assert call["rev"] == "0"

    repo.stop()
    _wait_until(qapp, lambda: workers.live_worker_count() == 0)


def test_reopening_the_open_case_asks_again_rather_than_doing_nothing(qapp):
    """The widget blanks the transcript on every click, so every click must refill it."""
    client = _RecordingClient()
    repo = _repo(client)

    repo.openCase(41)
    assert _wait_until(qapp, lambda: sum(
        1 for c in client.calls if c.get("case") == "41") >= 1)

    repo.openCase(41)
    assert _wait_until(qapp, lambda: sum(
        1 for c in client.calls if c.get("case") == "41") >= 2), (
        "re-clicking the open conversation left the transcript emptied and never refilled"
    )

    repo.stop()
    _wait_until(qapp, lambda: workers.live_worker_count() == 0)
