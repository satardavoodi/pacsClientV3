"""The cursor, the cadence, and every rule that makes a poll loop trustworthy.

NO QT, NO HTTP, NO CLOCK OF ITS OWN. The engine is handed the time and handed
the parsed response; it decides what to ask for next, when to ask, and what of
an answer may be applied. That is what makes the rules below testable without
a QApplication or a network, which matters because each of them exists to stop
a specific failure that is invisible until it is not.

THE SIX FAILURES THIS EXISTS TO MAKE IMPOSSIBLE, in the web console's own
words, because the desktop client inherits every one of them:

    no duplicates       the same answer applied twice changes nothing
    no lost messages    a failed request leaves the cursor where it was
    right read state    presence and reading stay different facts
    right conversation  an answer names the case it is about
    one truth           every surface reads the same endpoint
    no runaway writes   polling five times faster is not writing five times
                        more

WHAT "VISIBLE" MEANS HERE, and why it is not ``document.hidden``.

Sending ``visible=1`` is not a formality: the server writes
``staff_last_read_at`` from it, and that timestamp is the patient's second
tick. Two ticks on a message nobody read is the most corrosive thing this
feature could do, so the flag has to mean *an operator is looking at this
conversation right now* — the app is active, the chat tab is the current tab,
and the window is not minimised. Anything less generous would under-report and
leave conversations unread; anything more would lie to a patient.

Note also that the server DEFAULTS ``visible`` to true when the parameter is
absent. A client that forgets to send it claims to have read everything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import (
    ChatMessage,
    ConsoleEvent,
    ConversationRow,
    Counts,
    Filters,
    SyncCursor,
    SyncResponse,
    Thread,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncOutcome:
    """What the UI should do with one answer.

    ``applied`` false means the answer was discarded and NOTHING should be
    touched — not the rows, not the counts, not the presence dot. A discarded
    answer is an answer about a moment that has passed.
    """

    applied: bool
    reason: str = ""
    cold: bool = False

    # Present only when applied.
    thread_case: int | None = None
    messages: tuple[ChatMessage, ...] = ()
    revised: tuple[ChatMessage, ...] = ()
    thread: Thread | None = None
    rows: tuple[ConversationRow, ...] = ()
    counts: Counts | None = None
    events: tuple[ConsoleEvent, ...] = ()

    @property
    def thread_applied(self) -> bool:
        return self.thread is not None


class SyncEngine:
    """Cursor state and poll scheduling for one operator console.

    Every millisecond constant below is read from the web console's
    ``console-script.blade.php`` rather than invented. Two clients on different
    cadences against one backend is two different answers to "is this patient
    online", and the operator sees both.
    """

    # --- cadence, in milliseconds -------------------------------------------
    ACTIVE_MS = 800          # something moved in the last ACTIVE_FOR_MS
    IDLE_MS = 3000           # visible, nothing moving
    HIDDEN_MS = 15000        # not in front of the operator
    WATCH_MS = 45000         # hidden a long time, notifications still wanted
    ACTIVE_FOR_MS = 30000    # how long "recently active" lasts
    HIDDEN_STOP_MS = 15 * 60 * 1000   # after this, hidden counts as dead
    FIRST_POLL_MS = 400      # after the console opens
    RESUME_MS = 60           # became visible again
    RESUME_DEAD_MS = 250     # became visible after being dead
    MAX_BACKOFF_MS = 30000
    TYPING_MS = 4000         # how long one keystroke claims "typing"

    # Consecutive failures tolerated before backing off at all. Two dropped
    # requests on a hotel wifi are not an outage, and slowing down at the
    # first one is how a live conversation stutters.
    MISS_GRACE = 2

    # Event keys remembered so a banner is never raised twice for the same
    # thing. The server sends at most 8 per poll and prefixes each key by kind,
    # so collisions are impossible and this only needs to outlast the feed's
    # own 30-minute lookback.
    SEEN_EVENT_KEYS = 300

    def __init__(
        self,
        *,
        now_ms: int = 0,
        ev_cursor: int = 0,
        notifications_enabled: bool = True,
    ) -> None:
        self._cursor = SyncCursor(m=0, rev=0, ev=max(0, int(ev_cursor)), req=0)

        self._req_seq = 0
        self._req_applied = 0

        self._misses = 0

        self._visible = True
        self._hidden_since_ms: int | None = None
        self._last_beat_ms = now_ms
        self._typing_until_ms = 0

        self._open_case: int | None = None
        self._filters = Filters()
        self._notifications_enabled = bool(notifications_enabled)

        self._seen_event_keys: list[str] = []
        self._seen_event_set: set[str] = set()

    # ── state the UI drives ────────────────────────────────────────────────

    @property
    def cursor(self) -> SyncCursor:
        return self._cursor

    @property
    def event_cursor(self) -> int:
        """Persist this across restarts, WITH NO AGE LIMIT.

        The web client keeps its event cursor in localStorage and throws it
        away after five minutes, so every page load was effectively a cold
        start and roughly half the notifications never fired. Worse, the
        server always returns the HEAD of the event log — including after the
        30-minute lookback and the 8-event trim — so anything dropped is never
        re-offered. A cursor thrown away is notifications lost, not delayed.
        """
        return self._cursor.ev

    @property
    def open_case(self) -> int | None:
        return self._open_case

    @property
    def misses(self) -> int:
        return self._misses

    def set_open_case(self, case_id: int | None, *, force: bool = False) -> None:
        """Switch conversation, and start the new one cold.

        ``force`` RE-OPENS THE CONVERSATION ALREADY OPEN. Clicking the selected
        row is not a no-op at the UI layer — the widget clears the transcript
        so the previous patient's words can never linger — and without a cursor
        reset the next poll would ask for "messages newer than the newest one
        already seen", get nothing, and leave the operator staring at a
        transcript that has been emptied and never refilled.

        m AND rev BOTH RESET. Message ids are global but the cursor's meaning
        is per-conversation: carrying case 41's high-water mark into case 87
        would ask the server for "messages newer than 812" in a thread whose
        newest message is 90, and the transcript would come back empty.

        Sending rev=0 makes the server answer ``cold: true``, which is exactly
        right — a conversation just opened has nothing on screen to patch. The
        web console gets this for free because selection is a URL and every
        switch is a page load; here it has to be said out loud.

        The EVENT cursor is deliberately untouched. Notifications are about
        the whole inbox and do not restart when the operator changes desk.
        """
        new_id = int(case_id) if case_id else None
        if new_id == self._open_case and not force:
            return
        self._open_case = new_id
        self._cursor = SyncCursor(m=0, rev=0, ev=self._cursor.ev, req=self._cursor.req)

    def set_filters(self, filters: Filters) -> None:
        """Change what the list shows.

        Rows are replaced wholesale on the next answer because the server
        applies filters to rows and to nothing else — counts and events stay
        unfiltered on purpose, so a manager watching one view is still told
        about a consultation arriving outside it.
        """
        self._filters = filters

    def set_visible(self, visible: bool, *, now_ms: int) -> int | None:
        """The window/tab became (in)visible. Returns the delay to reschedule.

        Going visible after being DEAD returns 250 ms rather than 60: the list
        is fifteen minutes stale and the operator is looking at it now. The web
        console goes further and reloads the page outright, which a desktop
        client must not do — there may be a half-typed reply in the composer —
        so the answer is a fast cold-ish resync instead.
        """
        visible = bool(visible)

        if not visible:
            if self._visible:
                self._hidden_since_ms = now_ms
            self._visible = False
            # Tabbing away ends typing. A "typing…" indicator left running
            # under a window nobody is in front of is a lie with a timer on it.
            self._typing_until_ms = 0
            return None

        was_dead = self.is_dead(now_ms=now_ms)
        self._visible = True
        self._hidden_since_ms = None
        self._typing_until_ms = 0
        self.stir(now_ms=now_ms)

        return self.RESUME_DEAD_MS if was_dead else self.RESUME_MS

    def note_composer(self, has_text: bool, *, now_ms: int) -> None:
        """The operator typed. Costs no request of its own.

        The typing flag rides the sync that was already scheduled, which is
        why it is a deadline rather than an event: each keystroke pushes it
        four seconds out, and an empty composer clears it immediately.
        """
        self._typing_until_ms = (now_ms + self.TYPING_MS) if has_text else 0
        if has_text:
            self.stir(now_ms=now_ms)

    def set_notifications_enabled(self, enabled: bool) -> None:
        self._notifications_enabled = bool(enabled)

    def stir(self, *, now_ms: int) -> None:
        """Something happened; poll fast for a while.

        Called on new messages, on the patient typing, on any event, on a
        non-zero unread count and on the operator touching the composer. The
        cadence follows the conversation rather than a clock, which is the
        whole reason one poll can be both cheaper at rest and five times
        fresher while somebody is talking.
        """
        self._last_beat_ms = now_ms

    # ── scheduling ─────────────────────────────────────────────────────────

    def is_dead(self, *, now_ms: int) -> bool:
        """Hidden long enough that the operator is somewhere else entirely."""
        if self._visible or self._hidden_since_ms is None:
            return False
        return (now_ms - self._hidden_since_ms) >= self.HIDDEN_STOP_MS

    def delay_ms(self, *, now_ms: int) -> int | None:
        """When to poll next. None means stop the loop.

        Order matters and is the web console's: backoff first (an outage
        outranks everything), then visibility, then activity.
        """
        if self._misses > self.MISS_GRACE:
            # 800·2^n, capped. misses 3 → 6.4s, 4 → 12.8s, 5+ → 25.6s.
            return min(self.MAX_BACKOFF_MS, self.ACTIVE_MS * (2 ** min(self._misses, 5)))

        if not self._visible:
            if self.is_dead(now_ms=now_ms):
                # Notifications ON: keep a slow watch, ~80 requests an hour
                # against ~450 while being read. OFF: stop entirely — nobody is
                # waiting for anything and the server is shared with WordPress.
                return self.WATCH_MS if self._notifications_enabled else None
            return self.HIDDEN_MS

        return (
            self.ACTIVE_MS
            if (now_ms - self._last_beat_ms) < self.ACTIVE_FOR_MS
            else self.IDLE_MS
        )

    def should_poll(self, *, now_ms: int) -> bool:
        return self.delay_ms(now_ms=now_ms) is not None

    # ── building a request ─────────────────────────────────────────────────

    def next_request(self, *, now_ms: int) -> list[tuple[str, str]]:
        """Query parameters for the next poll, and bump the request counter.

        EVERY VALUE GOES IN THE QUERY STRING. The server reads the cursor and
        the filters through ``$request->query()`` exclusively — a JSON body is
        ignored, and a client that sends one looks permanently cold: rev=0 on
        every poll, full state every time, no revision sweep, forever.
        """
        self._req_seq += 1

        params: list[tuple[str, str]] = [
            ("m", str(self._cursor.m)),
            ("rev", str(self._cursor.rev)),
            ("ev", str(self._cursor.ev)),
            ("req", str(self._req_seq)),
            # Explicit, always. The server defaults this to TRUE, so omitting
            # it while the window is in the background would write
            # staff_last_read_at and show the patient "read" for a screen
            # nobody looked at.
            ("visible", "1" if self._visible else "0"),
            ("typing", "1" if self._typing_until_ms > now_ms else "0"),
        ]

        if self._open_case:
            params.append(("case", str(self._open_case)))

        params.extend(self._filters.as_query_pairs())

        return params

    # ── applying an answer ─────────────────────────────────────────────────

    def record_failure(self) -> None:
        """A request did not come back.

        THE CURSOR DOES NOT MOVE. Every request is already a catch-up request,
        so a failure costs latency and nothing else — there is deliberately no
        separate reconnect path to get subtly wrong.
        """
        self._misses += 1

    def apply(self, payload: Mapping[str, Any] | SyncResponse, *, now_ms: int) -> SyncOutcome:
        """Fold one answer into the engine's state.

        Returns what the UI may act on. Read the two discards below before
        changing anything here: both are silent when they work and expensive
        when they are missing.
        """
        response = payload if isinstance(payload, SyncResponse) else SyncResponse.parse(payload)

        # A response is proof the server is reachable, even if it is stale.
        self._misses = 0

        seq = response.cursor.req

        # ── DISCARD 1: an answer that was overtaken ────────────────────────
        # Responses arrive out of order on a bad network. Applying an older one
        # after a newer one is how a message that was read goes unread again,
        # and how a conversation the operator has left paints over the one they
        # are in. `req` is echoed untouched precisely so this check is cheap.
        if seq and seq < self._req_applied:
            logger.debug("aipacs_chat: dropped sync answer req=%s (applied %s)", seq, self._req_applied)
            return SyncOutcome(applied=False, reason="stale-req")

        if seq:
            self._req_applied = seq

        # ── DISCARD 2: an answer about another conversation ────────────────
        # The operator clicked away while this was in flight. The list, the
        # counts and the notification feed in the same payload are still about
        # the whole inbox and are still good — only the thread is wrong.
        thread = response.thread
        if thread is not None and thread.case != self._open_case:
            logger.debug(
                "aipacs_chat: dropped thread for case %s (open: %s)", thread.case, self._open_case
            )
            thread = None

        # ── the cursor ─────────────────────────────────────────────────────
        # m and ev never go backwards; the server already guarantees that with
        # max(), and it is repeated here so a hand-built payload in a test
        # cannot rewind live state either. rev is taken as given: it is stamped
        # from the response build time, not from the newest row, so that a row
        # written mid-request does not fall into the gap.
        self._cursor = SyncCursor(
            m=max(self._cursor.m, response.cursor.m),
            rev=response.cursor.rev or self._cursor.rev,
            ev=max(self._cursor.ev, response.cursor.ev),
            req=seq,
        )

        # ── the notification feed ──────────────────────────────────────────
        fresh_events = self._unseen(response.events)

        # ── cadence ────────────────────────────────────────────────────────
        # Anything that moved pulls the loop back to 800 ms for the next 30
        # seconds. An unread count is included because a badge appearing means
        # a patient is writing somewhere, even if not here.
        moved = bool(
            (thread and (thread.messages or thread.revised or thread.patient_typing))
            or fresh_events
            or response.counts.unread
        )
        if moved:
            self.stir(now_ms=now_ms)

        return SyncOutcome(
            applied=True,
            reason="",
            # cold is about the THREAD's state, and it is the server's word for
            # "you hold nothing I can patch". Replace, do not merge.
            cold=response.cold,
            thread_case=thread.case if thread else None,
            messages=thread.messages if thread else (),
            revised=thread.revised if thread else (),
            thread=thread,
            rows=response.rows,
            counts=response.counts,
            events=fresh_events,
        )

    # ── event de-duplication ───────────────────────────────────────────────

    def _unseen(self, events: tuple[ConsoleEvent, ...]) -> tuple[ConsoleEvent, ...]:
        """Events not already announced.

        Keyed on ``event.key``, never on the case id: the server prefixes the
        key by kind (``e`` for a log row, ``u`` for the standing
        "never submitted" condition) exactly so an event id and a case id
        cannot collide in a set like this one.

        The ``unsubmitted`` kind is a standing condition rather than an event —
        it is re-sent on every poll while it holds, including on a cold start —
        so without this it would raise a banner every few seconds.
        """
        fresh: list[ConsoleEvent] = []

        for event in events:
            if event.key in self._seen_event_set:
                continue
            fresh.append(event)
            self._seen_event_set.add(event.key)
            self._seen_event_keys.append(event.key)

        overflow = len(self._seen_event_keys) - self.SEEN_EVENT_KEYS
        if overflow > 0:
            for key in self._seen_event_keys[:overflow]:
                self._seen_event_set.discard(key)
            del self._seen_event_keys[:overflow]

        return tuple(fresh)
