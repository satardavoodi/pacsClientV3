"""The two guards that keep the poll loop from killing or freezing the app.

1. THE TICK IS CHEAP. ConsultationPoller.poll_once once froze the UI for three
   to twenty seconds per poll, and the guard written for it asserts the caller
   returns in under 100 ms and that no network call ran on the main thread.
   Same guard, same reasons.

2. A RUNNING WORKER KEEPS A STRONG REFERENCE. Dropping the last one finalises a
   running QThread and Qt answers with qFatal — abort(), no traceback, the log
   just stops. See modules/aipacs_chat/qt/workers.py for the two times this
   codebase has already paid for it.
"""

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modules.aipacs_chat.qt import workers  # noqa: E402
from modules.aipacs_chat.qt.repository import ChatRepository  # noqa: E402
from modules.aipacs_chat.services.models import SyncResponse  # noqa: E402
from modules.aipacs_chat.services.sync_engine import SyncEngine  # noqa: E402


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


class _SlowClient:
    """A client whose sync blocks, and records which thread it ran on."""

    def __init__(self, delay=0.4):
        self.delay = delay
        self.threads = []
        self.calls = 0

    def sync(self, params):
        self.threads.append(threading.current_thread())
        self.calls += 1
        time.sleep(self.delay)
        return SyncResponse.parse(
            {"t": 1, "cursor": {"m": 0, "rev": 100, "ev": 0, "req": 1}, "rows": []}
        )


def test_the_poll_tick_returns_immediately_and_never_touches_the_network(qapp):
    client = _SlowClient(delay=0.4)
    repo = ChatRepository("drv", client=client)
    repo._started = True  # _tick() is a no-op on a stopped loop, by design

    started = time.time()
    repo._tick()
    elapsed = time.time() - started

    assert elapsed < 0.1, (
        f"the tick took {elapsed:.3f}s on the GUI thread — it must start a worker and return"
    )

    assert _wait_until(qapp, lambda: client.calls >= 1)

    main = threading.main_thread()
    assert all(t is not main for t in client.threads), (
        "a network call ran on the GUI thread; the workstation would freeze for the timeout"
    )

    repo.stop()
    _wait_until(qapp, lambda: workers.live_worker_count() == 0)


def test_a_running_worker_is_strongly_referenced(qapp):
    client = _SlowClient(delay=0.3)
    repo = ChatRepository("drv", client=client)
    repo._started = True

    repo._tick()

    assert workers.live_worker_count() >= 1, (
        "a running QThread with no module-level reference is a qFatal waiting to happen"
    )

    assert _wait_until(qapp, lambda: workers.live_worker_count() == 0, timeout_s=5.0)

    repo.stop()


def test_stopping_detaches_rather_than_waiting(qapp):
    """Closing the tab mid-request must not block on a 15-second timeout."""
    client = _SlowClient(delay=0.5)
    repo = ChatRepository("drv", client=client)
    repo._started = True
    repo._tick()

    started = time.time()
    repo.stop()
    elapsed = time.time() - started

    assert elapsed < 0.1, f"stop() blocked for {elapsed:.3f}s — it must detach, never wait"

    # The orphan still finishes, and releases itself when it does.
    assert _wait_until(qapp, lambda: not workers._ORPHANED_CHAT_WORKERS, timeout_s=5.0)


def test_only_one_request_is_ever_in_flight(qapp):
    """Two overlapping requests would both be built from one cursor."""
    client = _SlowClient(delay=0.4)
    repo = ChatRepository("drv", client=client)
    repo._started = True

    repo._tick()
    repo._tick()
    repo._tick()

    assert workers.live_worker_count() == 1

    assert _wait_until(qapp, lambda: client.calls >= 1)
    repo.stop()
    _wait_until(qapp, lambda: workers.live_worker_count() == 0)


# --- failure routing --------------------------------------------------------


class _FailingClient:
    def __init__(self, exc):
        self.exc = exc

    def sync(self, params):
        raise self.exc


def test_a_401_stops_the_loop_and_asks_for_a_sign_in(qapp):
    """Retrying a revoked token 75 times a minute helps nobody."""
    from modules.aipacs_chat.services.chat_client import ChatAuthError

    repo = ChatRepository("drv", client=_FailingClient(ChatAuthError("expired")))
    asked = []
    repo.authRequired.connect(asked.append)

    repo._started = True
    repo._tick()

    assert _wait_until(qapp, lambda: bool(asked))
    assert repo.state == "signedout"
    assert not repo._timer.isActive(), "the loop must stop, not back off"

    repo.stop()


def test_a_transport_failure_keeps_the_loop_alive_and_does_not_move_the_cursor(qapp):
    from modules.aipacs_chat.services.chat_client import ChatTransportError

    repo = ChatRepository("drv", client=_FailingClient(ChatTransportError("refused")))
    errors = []
    repo.errorRaised.connect(errors.append)

    repo._started = True
    before = repo._engine.cursor

    repo._tick()

    assert _wait_until(qapp, lambda: bool(errors))
    assert repo.state != "signedout"
    assert repo._engine.cursor == before, "a failed request must lose nothing"

    repo.stop()


def test_an_unconfigured_workstation_is_a_state_not_an_error_strip(qapp):
    from modules.aipacs_chat.services.chat_client import ChatNotConfiguredError

    repo = ChatRepository("drv", client=_FailingClient(ChatNotConfiguredError("not paired")))

    repo._started = True
    repo._tick()

    assert _wait_until(qapp, lambda: repo.state == "notconfigured")
    assert not repo._timer.isActive()

    repo.stop()


# --- the signal contract ----------------------------------------------------


class _ScriptedClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def sync(self, params):
        return SyncResponse.parse(self.payloads.pop(0) if self.payloads else {})


def test_revisions_are_emitted_before_appends(qapp):
    """A patch must never land on a row that has not been drawn yet."""
    payload = {
        "t": 1,
        "cursor": {"m": 12, "rev": 100, "ev": 0, "req": 1},
        "cold": False,
        "thread": {
            "case": 41,
            "m": 12,
            "messages": [{"id": 12, "sender_type": "patient", "type": "text", "body": "new"}],
            "revised": [{"id": 5, "sender_type": "staff", "type": "text", "body": "fixed"}],
            "patient_online": True,
            "patient_typing": False,
            "status": "new",
            "status_tone": "fresh",
        },
        "rows": [],
        "counts": {},
        "events": [],
    }

    repo = ChatRepository("drv", client=_ScriptedClient([payload]))
    repo._engine.set_open_case(41)

    order = []
    repo.messagesRevised.connect(lambda case, msgs: order.append("revised"))
    repo.messagesAppended.connect(lambda case, msgs: order.append("appended"))

    repo._started = True
    repo._tick()

    assert _wait_until(qapp, lambda: len(order) == 2)
    assert order == ["revised", "appended"]

    repo.stop()


def test_presence_is_emitted_even_when_nothing_moved(qapp):
    """"Is the patient still here" is what an idle poll exists to answer."""
    payload = {
        "t": 1,
        "cursor": {"m": 0, "rev": 100, "ev": 0, "req": 1},
        "thread": {
            "case": 41, "m": 0, "messages": [], "revised": [],
            "patient_online": True, "patient_typing": True,
            "status": "new", "status_tone": "fresh",
        },
        "rows": [], "counts": {}, "events": [],
    }

    repo = ChatRepository("drv", client=_ScriptedClient([payload]))
    repo._engine.set_open_case(41)

    seen = []
    repo.presenceChanged.connect(lambda case, online, typing: seen.append((online, typing)))

    repo._started = True
    repo._tick()

    assert _wait_until(qapp, lambda: bool(seen))
    assert seen[0] == (True, True)

    repo.stop()


def test_the_event_cursor_is_exposed_for_persistence(qapp):
    repo = ChatRepository("drv", client=_ScriptedClient([]), ev_cursor=9040)

    assert repo.event_cursor == 9040
