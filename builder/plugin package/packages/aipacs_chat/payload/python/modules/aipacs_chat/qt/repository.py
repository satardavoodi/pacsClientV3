"""ChatRepository — the only object the widgets import from outside ``ui/``.

It owns the sync engine, the REST client and the workers, and it turns answers
into signals. Widgets never see HTTP, never see a thread, and never hold a
dataclass they did not receive through a signal.

THE POLL TICK DOES NOTHING BUT START A WORKER. There is a test in this repo
that fails if a poller's tick takes more than 100 ms, and it exists because
``ConsultationPoller.poll_once`` once froze the UI for three to twenty seconds
per poll. The timer here fires, checks whether a request is already in flight,
starts a thread, and returns.

ONE REQUEST IN FLIGHT AT A TIME. Not for politeness — the cursor is a single
piece of state, and two overlapping requests would both be built from it and
both try to advance it. The engine's request-ordering guard catches the
symptom; refusing to overlap avoids the cause.

WHAT "VISIBLE" MEANS. The repository does not decide. The tab tells it, because
only the tab knows whether it is the current tab of an active, non-minimised
window — and ``visible`` is what makes the server write ``staff_last_read_at``,
which is the patient's second tick. See ``SyncEngine`` for why that matters.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from modules.aipacs_chat.services.models import Filters
from modules.aipacs_chat.services.sync_engine import SyncEngine

from .workers import (
    KIND_AUTH,
    KIND_CONFIG,
    ChatWorker,
    detach_chat_worker,
    start_chat_worker,
)

logger = logging.getLogger(__name__)

# UI states, mirrored by the shell's QStackedWidget.
STATE_NOT_CONFIGURED = "notconfigured"
STATE_SIGNED_OUT = "signedout"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_ERROR = "error"


def _now_ms() -> int:
    """Monotonic milliseconds.

    Monotonic and not wall-clock: every interval in the engine is a duration,
    and a wall clock that steps backwards over a DST change or an NTP
    correction would make "hidden for 15 minutes" briefly true.
    """
    from time import monotonic

    return int(monotonic() * 1000)


class ChatRepository(QObject):
    """Cursor state, scheduling and every call the console makes."""

    # How soon to look again when a UI-requested poll collided with one already
    # in flight. Short enough that a click feels immediate, long enough that it
    # is a retry rather than a spin.
    URGENT_RETRY_MS = 120

    # ── lifecycle / state ──────────────────────────────────────────────────
    stateChanged = Signal(str)
    authRequired = Signal(str)   # human message; the UI offers a sign-in
    errorRaised = Signal(str)    # transient, non-fatal — a strip, not a dialog

    # ── list ───────────────────────────────────────────────────────────────
    rowsReplaced = Signal(object)     # tuple[ConversationRow, ...]
    countsChanged = Signal(object)    # Counts

    # ── thread ─────────────────────────────────────────────────────────────
    threadReplaced = Signal(int, object)      # case_id, messages (cold answer)
    messagesAppended = Signal(int, object)    # case_id, messages
    messagesRevised = Signal(int, object)     # case_id, messages
    presenceChanged = Signal(int, bool, bool)  # case_id, online, typing
    receiptsChanged = Signal(int, object, object)  # case_id, read_at, seen_at
    caseStatusChanged = Signal(int, str, str)  # case_id, status, tone

    # ── side panel ─────────────────────────────────────────────────────────
    caseDetailLoaded = Signal(object)
    # CARRIES THE CASE ID. A failure has to be attributable: without the id the
    # widget cannot tell whether the fetch that just failed was for the
    # conversation still on screen or for one the operator has already left,
    # and it would write patient A's error into patient B's panel.
    caseDetailFailed = Signal(int, str)

    # ── catalogue (fetched once per session, not per poll) ─────────────────
    savedRepliesLoaded = Signal(object)
    pricingLoaded = Signal(object)
    statusesLoaded = Signal(object)

    # ── notifications ──────────────────────────────────────────────────────
    eventsArrived = Signal(object)    # tuple[ConsoleEvent, ...], already de-duped

    # ── attachments ────────────────────────────────────────────────────────
    fileDownloaded = Signal(int, object)   # file_id, absolute path as str

    # ── optimistic write feedback ──────────────────────────────────────────
    writeSucceeded = Signal(str, object)   # (kind, payload)
    writeFailed = Signal(str, str)         # (kind, message)

    def __init__(self, aipacs_user: str, *, parent=None, client=None,
                 ev_cursor: int = 0, notifications_enabled: bool = True) -> None:
        super().__init__(parent)

        self._aipacs_user = aipacs_user
        self._client = client            # injectable for tests
        self._client_failed = False

        self._engine = SyncEngine(
            now_ms=_now_ms(),
            ev_cursor=ev_cursor,
            notifications_enabled=notifications_enabled,
        )

        self._state = STATE_LOADING
        self._sync_worker: ChatWorker | None = None
        self._write_workers: list[ChatWorker] = []
        self._pricing: dict = {}
        self._catalogue_loaded = False
        # File ids whose download is in flight. A second click on the same
        # chip must not start a second request for the same bytes.
        self._downloading: set[int] = set()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

        self._started = False
        # "Somebody is waiting for this one." Set when the UI asks for a poll
        # rather than the clock — opening a case, changing a filter, finishing
        # a write. See _tick for why it cannot simply be a short delay.
        self._urgent = False

    # ── properties the shell reads ─────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    @property
    def event_cursor(self) -> int:
        """Persist this across restarts, with NO age limit. See SyncEngine."""
        return self._engine.event_cursor

    @property
    def open_case(self) -> int | None:
        return self._engine.open_case

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Begin polling. Idempotent.

        The first poll is scheduled rather than run inline: opening the tab
        should paint before it talks to the network, and 400 ms is the same
        first-poll delay the web console uses.
        """
        if self._started:
            return
        self._started = True
        self._set_state(STATE_LOADING)
        self._timer.start(SyncEngine.FIRST_POLL_MS)

    def stop(self) -> None:
        """Stop polling and let anything in flight finish alone.

        DETACH, NEVER WAIT — see workers.detach_chat_worker. Called from the
        tab's close path, which may be running under WA_DeleteOnClose.
        """
        self._started = False
        self._timer.stop()

        if self._sync_worker is not None:
            detach_chat_worker(self._sync_worker)
            self._sync_worker = None

        for worker in list(self._write_workers):
            detach_chat_worker(worker)
        self._write_workers.clear()

    # ── state the UI drives ────────────────────────────────────────────────

    @Slot(int)
    def openCase(self, case_id: int) -> None:
        """Switch conversation and resync it immediately.

        The engine resets the message cursor so the server answers cold, which
        is right: a conversation just opened has nothing on screen to patch.
        """
        # force=True: the widget has already blanked the transcript, so the
        # answer must be cold even when this is the conversation already open.
        self._engine.set_open_case(case_id or None, force=True)
        self._urgent = True
        self._reschedule(60)

    @Slot()
    def closeCase(self) -> None:
        self._engine.set_open_case(None)
        self._reschedule(60)

    @Slot(object)
    def setFilters(self, filters: Filters) -> None:
        self._engine.set_filters(filters)
        self._urgent = True
        self._reschedule(60)

    @Slot(bool)
    def setVisible(self, visible: bool) -> None:
        """The tab became (in)visible. Only the tab can know this."""
        delay = self._engine.set_visible(bool(visible), now_ms=_now_ms())
        if delay is None:
            # Hidden. Keep polling, more slowly — the engine's delay_ms decides
            # how much more slowly, and whether to stop entirely.
            self._reschedule()
        else:
            self._reschedule(delay)

    @Slot(bool)
    def setComposerHasText(self, has_text: bool) -> None:
        self._engine.note_composer(bool(has_text), now_ms=_now_ms())

    @Slot(bool)
    def setNotificationsEnabled(self, enabled: bool) -> None:
        self._engine.set_notifications_enabled(bool(enabled))

    # ── the poll loop ──────────────────────────────────────────────────────

    def _reschedule(self, delay_ms: int | None = None) -> None:
        """When to poll next.

        A CADENCE RECALCULATION MUST NOT CANCEL AN URGENT POLL. This is the
        bug that made clicking a patient look like it did nothing:

            openCase()          -> _reschedule(60)     timer armed for 60 ms
            setVisible(...)     -> _reschedule()       timer re-armed for 15 s

        Anything that recomputes the ordinary cadence — the tab becoming
        visible or hidden, a window activation, a write settling — landing in
        that 60 ms window silently replaced the click's poll with the idle one.
        The conversation then took up to three seconds (idle) or fifteen
        (backgrounded) to appear, which reads as a dead sidebar. Switching to
        the chat tab and immediately clicking a patient hits it every time,
        because the tab's own visibility push arrives on the same turn.

        So an IMPLICIT reschedule never pushes a sooner deadline out. It is
        self-correcting: the urgent poll runs, and the answer's own
        ``_reschedule()`` then settles onto the cadence that was being asked
        for. An EXPLICIT delay is still obeyed — a caller naming a number means
        it, including a longer one.
        """
        if not self._started:
            return

        explicit = delay_ms is not None
        if delay_ms is None:
            delay_ms = self._engine.delay_ms(now_ms=_now_ms())
        if delay_ms is None:
            # Hidden a long time with notifications off: the loop stops. It
            # restarts the moment the tab becomes visible again.
            self._timer.stop()
            return

        if not explicit and self._timer.isActive():
            pending = self._timer.remainingTime()
            if 0 <= pending < int(delay_ms):
                return

        self._timer.start(int(delay_ms))

    @Slot()
    def _tick(self) -> None:
        """Cheap by contract. Starts a thread; touches nothing else."""
        if not self._started:
            return

        if self._sync_worker is not None:
            # Still waiting on the previous answer. Come back rather than
            # stacking a second request on the same cursor.
            #
            # HOW LONG TO WAIT IS THE WHOLE POINT. Falling back to the engine's
            # cadence here is what made clicking a patient look like it did
            # nothing: the request in flight was built from the OLD cursor, so
            # it carries no `case=` for the conversation just opened, and the
            # poll that would actually fetch it got pushed out to the ordinary
            # interval — 3 seconds idle, 15 while the tab is in the background.
            # The operator had already decided the sidebar was broken.
            #
            # So a poll the UI asked for keeps its urgency across the
            # collision and comes back in a moment instead.
            self._reschedule(self.URGENT_RETRY_MS if self._urgent else None)
            return

        self._urgent = False
        params = self._engine.next_request(now_ms=_now_ms())

        self._sync_worker = start_chat_worker(
            self._run_sync,
            params,
            on_done=self._on_sync_done,
            on_failed=self._on_sync_failed,
            parent=None,
        )

    def _run_sync(self, params):
        """Runs OFF the GUI thread. Returns data; touches no Qt object."""
        return self._ensure_client().sync(params)

    @Slot(object)
    def _on_sync_done(self, response) -> None:
        self._sync_worker = None

        outcome = self._engine.apply(response, now_ms=_now_ms())

        if not outcome.applied:
            # Overtaken by a newer answer. Nothing may be touched — not the
            # rows, not the counts, not the presence dot.
            self._reschedule()
            return

        self._set_state(STATE_READY)

        # The first successful answer proves the client works; only then is it
        # worth spending a request on the catalogue.
        if not self._catalogue_loaded:
            self._catalogue_loaded = True
            self.loadCatalogue()

        if outcome.counts is not None:
            self.countsChanged.emit(outcome.counts)

        # Rows are always a full replacement: the server sends the whole
        # filtered page every time, so a "patch" would just be a diff the UI
        # would have to compute against data it already has.
        self.rowsReplaced.emit(outcome.rows)

        thread = outcome.thread
        if thread is not None:
            case_id = thread.case

            if outcome.cold:
                # Replace wholesale. Merging a cold answer is how a message
                # that was read goes unread again.
                self.threadReplaced.emit(case_id, thread.messages)
            else:
                # Revisions BEFORE appends — a patch must never land on a row
                # that has not been drawn yet.
                if thread.revised:
                    self.messagesRevised.emit(case_id, thread.revised)
                if thread.messages:
                    self.messagesAppended.emit(case_id, thread.messages)

            # Presence and receipts travel on EVERY answer, including empty
            # ones. "Is the patient still here" is the question an idle poll
            # exists to answer.
            self.presenceChanged.emit(case_id, thread.patient_online, thread.patient_typing)
            self.receiptsChanged.emit(case_id, thread.read_at, thread.seen_at)
            self.caseStatusChanged.emit(case_id, thread.status, thread.status_tone)

        if outcome.events:
            self.eventsArrived.emit(outcome.events)

        self._reschedule()

    @Slot(str, str)
    def _on_sync_failed(self, kind: str, message: str) -> None:
        self._sync_worker = None
        self._engine.record_failure()

        if kind == KIND_AUTH:
            # The token is gone. The client has already discarded it; stop
            # polling and ask for a sign-in rather than retrying a dead token
            # 75 times a minute.
            self._client = None
            self._client_failed = True
            self._set_state(STATE_SIGNED_OUT)
            self.authRequired.emit(message)
            self._timer.stop()
            return

        if kind == KIND_CONFIG:
            self._client = None
            self._client_failed = True
            self._set_state(STATE_NOT_CONFIGURED)
            self._timer.stop()
            return

        # Transport. The engine's backoff decides how long to wait, and the
        # cursor has not moved — every request is already a catch-up request.
        if self._state != STATE_READY:
            self._set_state(STATE_ERROR)
        self.errorRaised.emit(message)
        self._reschedule()

    def retryAfterSignIn(self) -> None:
        """The operator paired again. Rebuild the client and resume."""
        self._client = None
        self._client_failed = False
        self._set_state(STATE_LOADING)
        if not self._started:
            self.start()
        else:
            self._reschedule(60)

    # ── writes ─────────────────────────────────────────────────────────────

    def _write(self, kind: str, fn, *args, **kwargs) -> None:
        """Run one write off the GUI thread and report it by signal.

        Every write is fire-and-report: the composer owns the "sending" state
        until the server hands back a real row, because there is deliberately
        no `sending` state server-side.
        """
        worker = start_chat_worker(
            fn,
            *args,
            on_done=lambda payload, k=kind: self._on_write_done(k, payload),
            on_failed=lambda err_kind, message, k=kind: self._on_write_failed(
                k, err_kind, message
            ),
            **kwargs,
        )
        self._write_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._forget_write_worker(w))

    def _forget_write_worker(self, worker: ChatWorker) -> None:
        try:
            self._write_workers.remove(worker)
        except ValueError:
            pass

    def _on_write_done(self, kind: str, payload: Any) -> None:
        if kind == "file":
            # A download changes nothing server-side, so it is not activity:
            # stirring the cadence for it would pull every poll back to 800 ms
            # every time somebody opened a PDF.
            self._on_file_downloaded(payload)
            return
        self.writeSucceeded.emit(kind, payload)
        # A write is activity. Pull the cadence back so the operator sees the
        # consequence at 800 ms rather than at 3 seconds.
        self._engine.stir(now_ms=_now_ms())
        self._reschedule(60)

    def _on_write_failed(self, kind: str, err_kind: str, message: str) -> None:
        if err_kind == KIND_AUTH:
            self._client = None
            self._set_state(STATE_SIGNED_OUT)
            self.authRequired.emit(message)
        if kind == "file":
            # Release every id rather than the one that failed: the payload of
            # a failure is a message, not a file id, so there is nothing to
            # match on — and leaving an id stuck in the set would make that
            # chip permanently unclickable.
            self._downloading.clear()
        self.writeFailed.emit(kind, message)

    def _on_file_downloaded(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        try:
            file_id = int(payload.get("file_id"))
        except (TypeError, ValueError):
            return
        self._downloading.discard(file_id)
        self.fileDownloaded.emit(file_id, payload.get("path"))

    # The write surface. Thin on purpose — each one names the client call and
    # the kind the UI will branch on.

    @Slot(str)
    def sendMessage(self, body: str) -> None:
        case_id = self._engine.open_case
        if not case_id:
            return
        self._write("send", lambda: self._ensure_client().send(case_id, body))

    @Slot(str, object, bool)
    def sendMessageWithFiles(self, body: str, paths, is_report: bool = False) -> None:
        """One message carrying files. The text is their caption.

        THE FILES ARE READ ON THE WORKER. Twenty megabytes off a network drive
        is not something the GUI thread does, and the pre-flight that decides
        whether the selection is sendable at all reads their sizes — so it
        belongs on the same side of the thread boundary as the read.

        The selection is copied here, before the worker starts: the composer's
        tray is cleared the moment send is pressed, and a worker reading a list
        the UI is still mutating is a race with a patient on the other end.
        """
        case_id = self._engine.open_case
        if not case_id:
            return
        selection = [str(p) for p in (paths or [])]
        if not selection:
            self.sendMessage(body)
            return
        report = bool(is_report)

        def _send():
            from modules.aipacs_chat.services.attachments import inspect
            from modules.aipacs_chat.services.chat_client import ChatAttachmentError

            items, error = inspect(selection)
            if error:
                raise ChatAttachmentError(error)
            return self._ensure_client().send(
                case_id, body, attachments=items, is_report=report,
            )

        self._write("send", _send)

    @Slot(int, str)
    def editMessage(self, message_id: int, body: str) -> None:
        case_id = self._engine.open_case
        if not case_id:
            return
        self._write("edit", lambda: self._ensure_client().edit_message(case_id, message_id, body))

    @Slot(int)
    def removeMessage(self, message_id: int) -> None:
        case_id = self._engine.open_case
        if not case_id:
            return
        self._write("remove", lambda: self._ensure_client().remove_message(case_id, message_id))

    @Slot(int, object)
    def react(self, message_id: int, value: int | None) -> None:
        case_id = self._engine.open_case
        if not case_id:
            return
        self._write("react", lambda: self._ensure_client().react(case_id, message_id, value))

    @Slot(int)
    def pinMessage(self, message_id: int) -> None:
        """A pin never arrives on the poll — this response is the only word."""
        case_id = self._engine.open_case
        if not case_id:
            return
        self._write("pin_message", lambda: self._ensure_client().pin_message(case_id, message_id))

    @Slot(int)
    def pinCase(self, case_id: int) -> None:
        self._write("pin_case", lambda: self._ensure_client().pin_case(case_id))

    @Slot()
    def rotateLink(self) -> None:
        """Issue the patient a fresh access link.

        SHOWN ONCE, NEVER STORED. The response is the only time this client
        ever sees the link: it is a bearer credential for the patient's whole
        conversation, and keeping a copy in a widget, a log line or a settings
        file would turn a one-time secret into a permanent one.
        """
        case_id = self._engine.open_case
        if not case_id:
            return
        self._write("rotate_link", lambda: self._ensure_client().rotate_link(case_id))

    @Slot(str, str)
    def setStatus(self, status: str, note: str = "") -> None:
        case_id = self._engine.open_case
        if not case_id:
            return
        self._write("status", lambda: self._ensure_client().set_status(case_id, status, note=note))

    @Slot(str)
    def sendPrice(self, tier: str) -> None:
        """A tier, never a typed amount.

        The amount and the checkout link come from the server's config and are
        owner-confirmed as a pair. Sending an amount from here would mean the
        client had an opinion about pricing, which is exactly how a patient
        ends up offered €49 and charged €99.
        """
        case_id = self._engine.open_case
        if not case_id:
            return
        currency = str((self._pricing or {}).get("currency") or "EUR")
        self._write(
            "price",
            lambda: self._ensure_client().send_price(case_id, currency=currency, tier=tier),
        )

    @Slot(int, str)
    def downloadFile(self, file_id: int, file_name: str = "") -> None:
        """Fetch one attachment, or hand back the copy already on disk.

        THE CACHE CHECK RUNS ON THE WORKER, not here. It is a ``stat()``, and
        ``user_data`` is a network share in some installs — the GUI thread does
        no I/O, not even cheap I/O.

        The bytes land under ``user_data/aipacs_chat/files/case_<id>/`` through
        ``services.storage``, which is the only module allowed to turn a
        patient-supplied filename into a path.
        """
        case_id = self._engine.open_case
        if not case_id:
            return
        try:
            file_id = int(file_id)
        except (TypeError, ValueError):
            return
        if file_id in self._downloading:
            return
        self._downloading.add(file_id)
        name = str(file_name or "")

        def _fetch():
            from modules.aipacs_chat.services import storage

            cached = storage.cached_attachment(case_id, file_id, name)
            if cached is not None:
                return {"file_id": file_id, "path": str(cached), "cached": True}
            data = self._ensure_client().download_file(case_id, file_id)
            path = storage.write_attachment(case_id, file_id, name, data)
            return {"file_id": file_id, "path": str(path), "cached": False}

        self._write("file", _fetch)

    @Slot(int)
    def emailMessage(self, message_id: int) -> None:
        case_id = self._engine.open_case
        if not case_id:
            return
        self._write("email", lambda: self._ensure_client().email_message(case_id, message_id))

    @Slot(int)
    def loadCaseDetail(self, case_id: int) -> None:
        """Everything the side panel renders, for one case.

        A SEPARATE REQUEST FROM THE POLL, and therefore separately fallible.
        ``/chat/cases/{id}`` is the only source for identity, imaging, drive,
        location, provenance and the mail log — the sync answer carries none of
        it — so when this fails the panel has nothing, and the operator has to
        be told that rather than left looking at an empty column.

        The failure is reported with the case id attached and does NOT go
        through the generic write path: a detail fetch is a read, and routing
        it through ``writeFailed`` put "Could not case detail" in the typing
        strip, which is both ungrammatical and the wrong place to look.
        """
        case_id = int(case_id)

        def _failed(kind: str, message: str) -> None:
            if kind == KIND_AUTH:
                # Still worth acting on: a dead token means every request is
                # about to fail, not just this one.
                self._client = None
                self._set_state(STATE_SIGNED_OUT)
                self.authRequired.emit(message)
            self.caseDetailFailed.emit(case_id, message)

        start_chat_worker(
            lambda: self._ensure_client().case(case_id),
            on_done=self.caseDetailLoaded.emit,
            on_failed=_failed,
        )

    @Slot()
    def loadCatalogue(self) -> None:
        """Saved replies, pricing tiers and the status list.

        ONCE PER SESSION, not per poll: these change when the owner edits them,
        which is on the order of months, and putting them on the sync response
        would pay for them every 800 ms.

        Fetched in ONE worker rather than three — three threads racing to fill
        three combo boxes is three chances to touch a widget that is going away.
        """
        def _fetch():
            client = self._ensure_client()
            return {
                "replies": client.saved_replies(case_id=self._engine.open_case),
                "pricing": client.pricing(),
                "statuses": client.statuses(),
            }

        start_chat_worker(
            _fetch,
            on_done=self._on_catalogue,
            # A missing catalogue is a smaller problem than a broken console:
            # the composer simply has no shortcuts, and the operator can type.
            on_failed=lambda kind, message: logger.debug(
                "aipacs_chat: catalogue unavailable (%s): %s", kind, message
            ),
        )

    def _on_catalogue(self, payload) -> None:
        if not isinstance(payload, dict):
            return
        self._pricing = payload.get("pricing") or {}
        self.savedRepliesLoaded.emit(payload.get("replies") or [])
        self.pricingLoaded.emit(self._pricing)
        self.statusesLoaded.emit(payload.get("statuses") or [])

    # ── the client ─────────────────────────────────────────────────────────

    def _ensure_client(self):
        """Built once per repository, not once per request.

        Constructing one hits Windows Credential Manager and the identity
        database — cheap once, wasteful at 800 ms intervals. Runs on the WORKER
        thread, which is also where the Identity module's thread guard wants
        it.
        """
        if self._client is None:
            from modules.aipacs_chat.services.chat_client import ChatClient

            self._client = ChatClient.for_user(self._aipacs_user)
        return self._client

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self.stateChanged.emit(state)
