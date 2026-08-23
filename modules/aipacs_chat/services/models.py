"""The wire shapes, as Python.

MIRRORS OF SERVER DTOs, NOT DEFINITIONS OF THEM. Every field here exists
because ``CaseMessage::toStaffArray()``, ``StaffConsoleController::listRows()``
or ``ConsoleEvents::shape()`` emits it. When one of those changes, this file
follows — it never leads.

WHAT IS DELIBERATELY NOT COMPUTED HERE:

  * ``editable``    the server decides who may edit a message and enforces it.
                    A client that re-derives the rule shows a button the
                    controller refuses.
  * ``tone``        the status→colour map lives in ``Support\\CaseStatus``. A
                    copy in Python is how the list paints amber while the
                    panel paints green for the same case.
  * ``ago``         rendered server-side and localised. Displayed as given and
                    never cached, because it is a string that goes stale.
  * delivery state  the server sends ``delivered`` or ``seen`` and there is no
                    ``sending`` — the composer owns that until a row exists.

Everything is frozen. A message that arrived in a sync response is a fact
about the past; mutating one in place is how a revised copy and an appended
copy of the same id end up disagreeing inside one model.

Parsing is TOLERANT ON THE WAY IN and strict on the way out: an unknown
message ``type`` renders as its body rather than raising, because the server
already carries two type constants (``payment_link``, ``report``) that nothing
writes yet, and the first client to meet one in the wild should not crash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)


# ── vocabularies ─────────────────────────────────────────────────────────────
# Listed for readability and for tests. NOT used to reject anything: the server
# is the authority on what a valid value is, and a client that refuses an
# unknown one is a client that breaks the day a status is added.

SENDER_PATIENT = "patient"
SENDER_STAFF = "staff"
SENDER_SYSTEM = "system"

MESSAGE_TYPES = (
    "text",
    "file",
    "link",
    "system",
    "price_offer",
    # Constants that exist server-side and that nothing currently writes.
    # Rendered defensively rather than assumed absent.
    "payment_link",
    "report",
)

EVENT_KINDS = ("message", "request", "status", "unsubmitted")


# ── helpers ──────────────────────────────────────────────────────────────────


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _bool(value: Any) -> bool:
    return bool(value)


def _ts(value: Any) -> datetime | None:
    """A unix-seconds timestamp as an aware datetime, or None.

    The envelope mixes both forms on purpose and both are honoured here:
    ``rows[].at``, ``read_at`` and ``events[].at`` are unix ints, while
    ``messages[].at`` is ISO-8601. Normalising at the boundary means no widget
    ever has to know which endpoint a value came from.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        # Python < 3.11 does not accept a trailing Z in fromisoformat.
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            logger.debug("aipacs_chat: unparsable timestamp %r", value)
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


# ── messages ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Reactions:
    """``reactionSummary()``: the patient's single thumb, and staff tallies.

    ``patient`` is 1, -1 or None — one patient, one opinion. The staff numbers
    are counts, because several operators can each leave one.
    """

    patient: int | None = None
    staff_up: int = 0
    staff_down: int = 0

    @classmethod
    def parse(cls, raw: Any) -> "Reactions":
        if not isinstance(raw, Mapping):
            return cls()
        return cls(
            patient=_opt_int(raw.get("patient")),
            staff_up=_int(raw.get("staff_up")),
            staff_down=_int(raw.get("staff_down")),
        )


@dataclass(frozen=True)
class ChatMessage:
    """One row of the transcript, exactly as ``toStaffArray()`` sends it."""

    id: int
    sender_type: str
    type: str
    body: str
    at: datetime | None
    sender: str | None = None
    meta: Mapping[str, Any] | None = None
    ai_action: str | None = None
    edited: bool = False
    removed: bool = False
    editable: bool = False
    reactions: Reactions = field(default_factory=Reactions)
    my_reaction: int | None = None
    is_automated: bool = False

    # --- convenience the UI would otherwise re-derive per paint -------------

    @property
    def is_mine_to_edit(self) -> bool:
        """Server-computed. Never re-derive from sender_type and is_automated.

        The controller enforces ``isEditableByStaff()`` and the console's Edit
        button reads the same flag, so both agree about who may press it. A
        third opinion in Python is a button that 403s.
        """
        return self.editable

    @property
    def is_outbound(self) -> bool:
        return self.sender_type == SENDER_STAFF

    @property
    def is_system(self) -> bool:
        return self.sender_type == SENDER_SYSTEM

    def meta_value(self, key: str, default: Any = None) -> Any:
        """One meta key, tolerantly.

        ``meta`` is None on a withdrawn message, and ``price_offer`` builds its
        dict with ``array_filter`` — so ``tier`` and ``url`` are ABSENT rather
        than null when unset. Both cases have to read as "not there".
        """
        if not isinstance(self.meta, Mapping):
            return default
        value = self.meta.get(key, default)
        return default if value is None else value

    @classmethod
    def parse(cls, raw: Any) -> "ChatMessage | None":
        if not isinstance(raw, Mapping):
            return None
        mid = _opt_int(raw.get("id"))
        if mid is None:
            # Without an id there is no cursor position and no identity. Drop
            # it rather than inventing one.
            logger.debug("aipacs_chat: message without an id discarded")
            return None

        meta = raw.get("meta")
        return cls(
            id=mid,
            sender_type=_str(raw.get("sender_type"), SENDER_SYSTEM),
            type=_str(raw.get("type"), "text"),
            body=_str(raw.get("body")),
            at=_ts(raw.get("at")),
            sender=_opt_str(raw.get("sender")),
            meta=dict(meta) if isinstance(meta, Mapping) else None,
            ai_action=_opt_str(raw.get("ai_action")),
            edited=_bool(raw.get("edited")),
            removed=_bool(raw.get("removed")),
            editable=_bool(raw.get("editable")),
            reactions=Reactions.parse(raw.get("reactions")),
            my_reaction=_opt_int(raw.get("my_reaction")),
            is_automated=_bool(raw.get("is_automated")),
        )

    @classmethod
    def parse_many(cls, raw: Any) -> tuple["ChatMessage", ...]:
        """A list of messages, sorted by id.

        SORTED HERE, DEFENSIVELY. ``CaseSync`` now orders by id explicitly, but
        the client must not depend on that: order is the difference between a
        transcript and a shuffle, and sorting a hundred rows costs nothing.
        """
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, Mapping)):
            return ()
        out = [m for m in (cls.parse(item) for item in raw) if m is not None]
        out.sort(key=lambda m: m.id)
        return tuple(out)


# ── the conversation list ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConversationRow:
    """``listRows()``. Note the key is ``tone``, not ``status_tone``.

    The thread sends ``status_tone`` and a row sends ``tone``. Both are
    correct and they are genuinely different keys; assuming one name for both
    renders half the list without a colour.
    """

    id: int
    # Who the conversation is with. Added server-side 2026-08-19 — the web
    # console never needed them here because its rows are rendered from the
    # full model and this payload only patches that DOM. A native client has no
    # such DOM, so without these it can only list case numbers.
    label: str = ""
    ref: str = ""
    unread: int = 0
    online: bool = False
    at: datetime | None = None
    ago: str | None = None
    preview: str = ""
    sender: str = ""
    status: str = ""
    tone: str = "work"
    pinned: bool = False

    @property
    def title(self) -> str:
        """What the row shows. Falls back so a row is never blank."""
        return self.label or (f"#{self.ref}" if self.ref else f"#{self.id}")

    @classmethod
    def parse(cls, raw: Any) -> "ConversationRow | None":
        if not isinstance(raw, Mapping):
            return None
        rid = _opt_int(raw.get("id"))
        if rid is None:
            return None
        return cls(
            id=rid,
            label=_str(raw.get("label")),
            ref=_str(raw.get("ref")),
            unread=_int(raw.get("unread")),
            online=_bool(raw.get("online")),
            at=_ts(raw.get("at")),
            ago=_opt_str(raw.get("ago")),
            preview=_str(raw.get("preview")),
            sender=_str(raw.get("sender")),
            status=_str(raw.get("status")),
            # 'work' is the server's own fallback for an unknown status: an
            # unfamiliar case should read as ordinary in-progress, not lose its
            # chip styling and look broken.
            tone=_str(raw.get("tone"), "work") or "work",
            pinned=_bool(raw.get("pinned")),
        )

    @classmethod
    def parse_many(cls, raw: Any) -> tuple["ConversationRow", ...]:
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, Mapping)):
            return ()
        return tuple(r for r in (cls.parse(item) for item in raw) if r is not None)


@dataclass(frozen=True)
class Counts:
    """Badge numbers. UNFILTERED, unlike the rows they sit beside.

    A manager filtered to "From Crisp" must still be told a consultation
    arrived on the form, so the server deliberately does not apply the list
    filter to these. Do not "fix" that by filtering them here.
    """

    unread: int = 0
    online: int = 0
    stalled: int = 0
    none: int = 0  # "not priced yet"

    @classmethod
    def parse(cls, raw: Any) -> "Counts":
        if not isinstance(raw, Mapping):
            return cls()
        return cls(
            unread=_int(raw.get("unread")),
            online=_int(raw.get("online")),
            stalled=_int(raw.get("stalled")),
            none=_int(raw.get("none")),
        )


# ── notifications ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConsoleEvent:
    """One entry of the notification feed.

    ``key`` is prefixed by kind (``e<event_id>`` / ``u<case_id>``) so an event
    id and a case id can never collide in a seen-set. De-duplicate on it, never
    on ``case``.

    ``url`` is an absolute WEB CONSOLE address. The desktop client ignores it
    and opens the conversation in-app by ``case`` — noted here so nobody later
    "fixes" the module by following it into a browser.
    """

    key: str
    kind: str
    case: int
    ref: str = ""
    who: str = ""
    title: str = ""
    body: str = ""
    url: str = ""
    at: datetime | None = None

    @property
    def should_alert(self) -> bool:
        """Which kinds raise a banner.

        ``message`` and ``request`` — a patient wrote, or a consultation
        arrived. ``status`` is usually the operator's own click echoing back
        and ``unsubmitted`` is a standing condition rather than an event, so
        both are shown in the feed and neither interrupts.
        """
        return self.kind in ("message", "request")

    @classmethod
    def parse(cls, raw: Any) -> "ConsoleEvent | None":
        if not isinstance(raw, Mapping):
            return None
        key = _str(raw.get("key"))
        if not key:
            return None
        return cls(
            key=key,
            kind=_str(raw.get("kind")),
            case=_int(raw.get("case")),
            ref=_str(raw.get("ref")),
            who=_str(raw.get("who")),
            title=_str(raw.get("title")),
            body=_str(raw.get("body")),
            url=_str(raw.get("url")),
            at=_ts(raw.get("at")),
        )

    @classmethod
    def parse_many(cls, raw: Any) -> tuple["ConsoleEvent", ...]:
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, Mapping)):
            return ()
        return tuple(e for e in (cls.parse(item) for item in raw) if e is not None)


# ── the sync envelope ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SyncCursor:
    """The four numbers that make reconnects safe.

    m    highest message id already drawn
    rev  unix seconds; anything updated after this is stale on screen
    ev   highest console-event id already announced
    req  the client's own counter, echoed back untouched

    Handed back VERBATIM. The server clamps every one of them and stamps
    ``rev`` from the moment it built the response rather than from the newest
    row it contains — a row written during the request would otherwise fall in
    the gap and be missed forever.
    """

    m: int = 0
    rev: int = 0
    ev: int = 0
    req: int = 0

    @classmethod
    def parse(cls, raw: Any) -> "SyncCursor":
        if not isinstance(raw, Mapping):
            return cls()
        return cls(
            m=_int(raw.get("m")),
            rev=_int(raw.get("rev")),
            ev=_int(raw.get("ev")),
            req=_int(raw.get("req")),
        )

    def as_query(self) -> dict[str, int]:
        return {"m": self.m, "rev": self.rev, "ev": self.ev, "req": self.req}


@dataclass(frozen=True)
class Thread:
    """The open conversation's slice of a sync answer.

    ``messages`` and ``revised`` are DISJOINT by construction on the server:
    new is ``id > cursor.m``, revised is ``id <= cursor.m AND updated_at >
    cursor.rev``. A message that is both appears only in ``messages``, or the
    UI would draw it and immediately patch it.

    Apply ``revised`` FIRST, then append ``messages`` — the order the web
    console uses, and the only order in which a patch cannot land on a row
    that is not there yet.
    """

    case: int
    m: int = 0
    messages: tuple[ChatMessage, ...] = ()
    revised: tuple[ChatMessage, ...] = ()
    patient_online: bool = False
    patient_typing: bool = False
    read_at: datetime | None = None
    seen_at: datetime | None = None
    status: str = ""
    status_tone: str = "work"

    @classmethod
    def parse(cls, raw: Any) -> "Thread | None":
        if not isinstance(raw, Mapping):
            return None
        case_id = _opt_int(raw.get("case"))
        if case_id is None:
            return None
        return cls(
            case=case_id,
            m=_int(raw.get("m")),
            messages=ChatMessage.parse_many(raw.get("messages")),
            revised=ChatMessage.parse_many(raw.get("revised")),
            patient_online=_bool(raw.get("patient_online")),
            patient_typing=_bool(raw.get("patient_typing")),
            read_at=_ts(raw.get("read_at")),
            seen_at=_ts(raw.get("seen_at")),
            status=_str(raw.get("status")),
            status_tone=_str(raw.get("status_tone"), "work") or "work",
        )


@dataclass(frozen=True)
class SyncResponse:
    """One round trip: the thread, the list, the counts and the feed.

    ``cold`` means the server decided the client holds nothing trustworthy —
    ``rev`` absent, older than 900 seconds, or more than 60 seconds in the
    future. REPLACE STATE WHOLESALE on a cold answer; merging one is how a
    read message goes unread again.
    """

    t: int = 0
    cursor: SyncCursor = field(default_factory=SyncCursor)
    cold: bool = False
    thread: Thread | None = None
    counts: Counts = field(default_factory=Counts)
    events: tuple[ConsoleEvent, ...] = ()
    rows: tuple[ConversationRow, ...] = ()

    @classmethod
    def parse(cls, raw: Any) -> "SyncResponse":
        if not isinstance(raw, Mapping):
            return cls()
        return cls(
            t=_int(raw.get("t")),
            cursor=SyncCursor.parse(raw.get("cursor")),
            cold=_bool(raw.get("cold")),
            thread=Thread.parse(raw.get("thread")),
            counts=Counts.parse(raw.get("counts")),
            events=ConsoleEvent.parse_many(raw.get("events")),
            rows=ConversationRow.parse_many(raw.get("rows")),
        )


# ── list filters ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Filters:
    """The compact filter model, mirroring ``Support\\CaseFilters``.

    ONE POPOVER, NOT A ROW OF BUTTONS. The server models these as facets that
    AND across groups and OR within one, because "unread AND online" is the
    most useful question an operator can ask and the old mutually-exclusive
    chips could not ask it.

    NOTE THE WIRE NAMES. Single-value groups post bare (``show``,
    ``presence``, ``price``); multi-value groups post bracketed (``attn[]``,
    ``source[]``, ``status[]``). Two entries cannot share a key, which is why
    the server's ``hiddenFields()`` returns pairs rather than a map — and why
    this builds a list of pairs too.
    """

    show: str = "open"          # open | all | closed
    attention: tuple[str, ...] = ()   # unread | stalled
    presence: str = "any"       # any | online | offline
    price: str = "any"          # any | none | priced
    sources: tuple[str, ...] = ()     # form | widget | crisp
    statuses: tuple[str, ...] = ()
    term: str = ""

    MAX_TERM = 120

    @property
    def active_count(self) -> int:
        """What the filter button's badge shows. Mirrors ``activeCount()``."""
        return (
            (0 if self.show == "open" else 1)
            + len(self.attention)
            + (0 if self.presence == "any" else 1)
            + (0 if self.price == "any" else 1)
            + len(self.sources)
            + len(self.statuses)
        )

    @property
    def is_default(self) -> bool:
        return self.active_count == 0 and not self.term

    def as_query_pairs(self) -> list[tuple[str, str]]:
        """Query parameters, as ordered pairs.

        Defaults are omitted entirely — the server supplies them, and sending
        ``show=open`` explicitly only makes the URL longer.
        """
        out: list[tuple[str, str]] = []
        if self.show != "open":
            out.append(("show", self.show))
        if self.presence != "any":
            out.append(("presence", self.presence))
        if self.price != "any":
            out.append(("price", self.price))
        for value in self.attention:
            out.append(("attn[]", value))
        for value in self.sources:
            out.append(("source[]", value))
        for value in self.statuses:
            out.append(("status[]", value))
        term = self.term.strip()[: self.MAX_TERM]
        if term:
            out.append(("q", term))
        return out
