"""What the agent is doing right now, for the phone to show while it waits.

Why this exists
---------------
An Analysis answer takes 8-28 seconds. For all of that the phone shows a
spinner, and a spinner says only "something is happening" -- it cannot
distinguish a server thinking hard from a server that has died. Users conclude
the second one and tap again, which starts a whole new answer.

Why polling rather than streaming
---------------------------------
The command endpoint is a plain request/response POST, and the phone already
knows the conversation id. A progress READ keyed by that id needs no change to
the command contract, no long-lived socket through the clinic's router, and no
partial-response handling on either side. Streaming would be a better fit for a
much longer job; for a half-minute one it is a lot of new failure modes to buy
the same information.

What it is not
--------------
Not a queue, not a log, not durable. It is the CURRENT step, in memory, for a
couple of minutes. If the server restarts mid-answer the phone loses progress
and still gets its result or its error from the POST it is already waiting on --
the progress channel is decoration, and decoration must never be load-bearing.

Nothing in here may fail a command. Every entry point swallows.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

LOG = logging.getLogger("reception_crm.core.progress")

#: How long a step stays readable after it was published. Long enough for a
#: phone that missed a poll, short enough that a crashed answer's last step
#: does not sit there looking live.
TTL_SECONDS = 180.0

#: Hard ceiling on tracked conversations. One entry is a few hundred bytes, so
#: this is not about memory -- it is about a leak never becoming unbounded on a
#: machine that is also running a PACS server.
MAX_TRACKED = 200


@dataclass
class Step:
    """One published step. `done` marks the answer as finished, not the step."""

    message_fa: str
    index: int = 0
    total: int = 0
    sources: list[str] = field(default_factory=list)
    done: bool = False
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "messageFa": self.message_fa,
            "step": self.index,
            "totalSteps": self.total,
            "sources": list(self.sources),
            "done": self.done,
            "ageSeconds": round(time.time() - self.at, 1),
        }


class _Board:
    """Current step per (owner, conversation). Last write wins."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._steps: dict[tuple[str, str, str], Step] = {}

    @staticmethod
    def _key(principal: Any, conversation_id: str) -> tuple[str, str, str] | None:
        conversation_id = str(conversation_id or "")
        if not conversation_id:
            return None
        # Scoped by principal as well as conversation. An id is not a
        # capability anywhere else in this system and it is not one here: the
        # step text names tools and periods, which is a small leak but a leak.
        return (
            str(getattr(principal, "center", "") or ""),
            str(getattr(principal, "user", "") or ""),
            conversation_id,
        )

    def publish(self, principal: Any, conversation_id: str, step: Step) -> None:
        key = self._key(principal, conversation_id)
        if key is None:
            return
        with self._lock:
            # Prune AFTER inserting, not before. Pruning first trimmed to the
            # cap and then added one more, so the board settled at MAX_TRACKED+1
            # -- bounded, but not the number it claims, and a cap that is off by
            # one is a cap somebody will later trust to be exact.
            self._steps[key] = step
            self._prune_locked()

    def read(self, principal: Any, conversation_id: str) -> dict[str, Any] | None:
        key = self._key(principal, conversation_id)
        if key is None:
            return None
        with self._lock:
            step = self._steps.get(key)
            if step is None or (time.time() - step.at) > TTL_SECONDS:
                return None
            return step.as_dict()

    def clear(self, principal: Any, conversation_id: str) -> None:
        key = self._key(principal, conversation_id)
        if key is None:
            return
        with self._lock:
            self._steps.pop(key, None)

    def _prune_locked(self) -> None:
        now = time.time()
        stale = [k for k, s in self._steps.items() if (now - s.at) > TTL_SECONDS]
        for k in stale:
            self._steps.pop(k, None)
        if len(self._steps) > MAX_TRACKED:
            # Oldest first. A board this full means something is publishing and
            # never finishing, and dropping the oldest keeps the newest useful.
            for k, _ in sorted(self._steps.items(), key=lambda kv: kv[1].at)[: len(self._steps) - MAX_TRACKED]:
                self._steps.pop(k, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._steps)


board = _Board()


# --------------------------------------------------------------------------- #
# What the user reads
# --------------------------------------------------------------------------- #
#: A tool's name in Persian. The phone shows this, so it must be the name a
#: receptionist uses -- not the tool id, which is an implementation detail they
#: never chose to learn.
TOOL_FA: dict[str, str] = {
    "cashier-report": "گزارش صندوق",
    "cashier-reconciliation": "تطبیق صندوق",
    "daily-summary": "خلاصهٔ روز",
    "patient-list": "فهرست بیماران",
    "financial-analysis": "گزارش مالی",
    "physician-performance": "حجم کاری پزشکان",
    "risk-analysis": "موارد پرریسک",
    "trend-analysis": "مقایسهٔ دوره‌ها",
    "reporting-queue": "صف گزارش‌نویسی",
    "report.search": "جست‌وجوی گزارش‌ها",
    "report.get": "گزارش بیمار",
    "report.history": "سابقهٔ بیمار",
    "report.archive-stats": "آمار آرشیو",
    "patients.search": "جست‌وجوی بیمار",
    "appointments.list": "نوبت‌ها",
}


def tool_fa(tool: str) -> str:
    return TOOL_FA.get(tool, tool)


class Reporter:
    """A publisher bound to one command. Every method is best-effort.

    Constructed even when there is nowhere to publish (no conversation), so
    call sites do not have to branch. A Reporter with no conversation is a
    working object that does nothing, which is cheaper to read than a `None`
    check at every step.
    """

    def __init__(self, principal: Any = None, conversation_id: str = "", total: int = 0) -> None:
        self.principal = principal
        self.conversation_id = str(conversation_id or "")
        #: An estimate of how many steps this command will take, or 0 for "not
        #: known". Zero is the normal case: the gathering loop fetches a number
        #: of sources the question decides, so the count is not knowable when
        #: the command starts.
        self.total = total
        self.index = 0
        self.sources: list[str] = []

    @property
    def active(self) -> bool:
        return bool(self.conversation_id and self.principal is not None)

    def _publishable_total(self) -> int:
        """The estimate, or 0 once it has been passed.

        An estimate that has been exceeded is not an estimate. A live run
        published «مرحله ۶ از ۴» — arithmetic nonsense on a screen a
        receptionist reads, and worse than saying nothing, because a step count
        is exactly the kind of number people assume nobody would print wrong.
        Dropping to "unknown" costs a counter and keeps the caption honest.
        """
        if self.total and self.index > self.total:
            self.total = 0
        return self.total

    def step(self, message_fa: str, *, advance: bool = True) -> None:
        if not self.active:
            return
        try:
            if advance:
                self.index += 1
            board.publish(
                self.principal,
                self.conversation_id,
                Step(message_fa=message_fa, index=self.index, total=self._publishable_total(),
                     sources=list(self.sources)),
            )
        except Exception as exc:  # noqa: BLE001 - decoration is never load-bearing
            LOG.debug("could not publish progress (%s)", type(exc).__name__)

    def fetched(self, tool: str) -> None:
        import os
        if os.environ.get('CRM_EAGLE_CONFIG'):
            from modules.ai_imaging.eagle_eye_remote.response_language import current_reply_language
            if current_reply_language() == 'en':
                label = tool.replace('.', ' ').replace('-', ' ')
                self.sources.append(label)
                self.step(f'Reading {label}...')
                return
        self.sources.append(tool_fa(tool))
        self.step(f"خواندن {tool_fa(tool)}…")

    def finish(self) -> None:
        """Mark the answer complete, so a poll in flight stops rather than
        showing the last step until it expires."""
        if not self.active:
            return
        try:
            board.publish(
                self.principal,
                self.conversation_id,
                Step(message_fa="", index=self.index, total=self._publishable_total(),
                     sources=list(self.sources), done=True),
            )
        except Exception as exc:  # noqa: BLE001
            LOG.debug("could not publish completion (%s)", type(exc).__name__)
