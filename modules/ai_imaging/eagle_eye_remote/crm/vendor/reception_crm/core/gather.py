"""The gathering loop: plan, fetch, decide whether that was enough, fetch more.

Shape, and why it is this shape
-------------------------------
The obvious design is ReAct: one tool per model round, the model deciding each
next step from the last result. It is the wrong design HERE, and the reason is
measured rather than aesthetic.

Every reception report answers in 7-835 ms; all but one in under 200 ms. Every
LLM round costs 4-18 SECONDS. Fetching four sources is roughly one fiftieth the
price of one extra round-trip to the model. A strict one-tool-per-round loop
would spend half a minute deciding what a broad plan fetches in one second, and
the clinician would wait for it.

So a round fetches a SET, and the bound is on rounds, not on sources:

    interpret  →  fetch set   →  assess  →  fetch set  →  ...  →  answer
      (LLM)        (~1 s)        (LLM)       (~1 s)              (LLM)

Report mode normally stops after the first fetch: retrieval questions have one
right source and a second round would cost eight seconds to confirm it. Analysis
is allowed more, because "آیا ناسازگاری هست؟" genuinely cannot be answered from
one report.

What the loop must never become
-------------------------------
A route to action. Every call in every round is re-checked against the mode's
ceiling and the principal's permissions -- not just the ones the first LLM call
proposed. Checking round one and trusting the rest would mean the safety
boundary held only until the model asked a second time, which is precisely when
an agent loop is most likely to reach for something new.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from . import modes as mode_registry
from .dispatcher import dispatch
from .registry import ToolNotFoundError, ToolRegistry, requires_human_approval
from .types import DispatchContext, ToolCall, ToolDefinition

LOG = logging.getLogger("reception_crm.core.gather")

#: Fetched payloads live for one turn by default, and only briefly beyond it.
#:
#: The figures move: across one two-minute evaluation run the patient debt went
#: 993,470,000 -> 1,011,130,000 and the unsettled count 31 -> 32. A cashier
#: report served from a ten-minute-old cache would be a confident, precise,
#: stale answer -- the worst kind. Sixty seconds covers the follow-up question
#: somebody types straight away and nothing else.
CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class Budget:
    """What one answer is allowed to spend.

    `rounds` counts FETCH rounds, so 1 means "the interpreter's plan, then
    answer" -- today's behaviour exactly.
    """

    rounds: int = 1
    sources: int = 4
    seconds: float = 45.0

    @classmethod
    def for_mode(cls, mode: Any) -> "Budget":
        mode_id = getattr(mode, "id", str(mode or ""))
        if mode_id == mode_registry.ANALYSIS.id:
            # Analysis is the mode whose questions need corroboration. Three
            # rounds is two chances to notice something is missing.
            return cls(rounds=3, sources=8, seconds=75.0)
        if mode_id == mode_registry.EXECUTIVE.id:
            # Executive gathers context before acting, but its writes go through
            # the confirmation gate, never through this loop.
            return cls(rounds=2, sources=6, seconds=60.0)
        return cls(rounds=1, sources=4, seconds=45.0)


@dataclass
class Fetched:
    """One tool result, with enough provenance to cite it in an answer."""

    tool: str
    arguments: dict[str, Any]
    ok: bool
    data: Any = None
    error: dict[str, Any] | None = None
    audit_id: str | None = None
    cached: bool = False
    session_cached: bool = False
    snapshot_at: str | None = None
    ms: int = 0
    why: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            **({"sessionSnapshotAt": self.snapshot_at} if self.session_cached and self.snapshot_at else {}),
        }


@dataclass
class Refused:
    """A call the loop would not make, and the reason.

    Recorded rather than dropped: a plan silently missing a step looks like a
    plan that never wanted it, and the answer then reads as complete.
    """

    tool: str
    reason: str


@dataclass
class Gathering:
    fetched: list[Fetched] = field(default_factory=list)
    refused: list[Refused] = field(default_factory=list)
    rounds: int = 0
    stopped_because: str = ""

    @property
    def ok_results(self) -> list[Fetched]:
        return [f for f in self.fetched if f.ok]

    def as_evidence(self) -> list[dict[str, Any]]:
        return [f.as_dict() for f in self.fetched]


class WorkingMemory:
    """Per-session cache of what has already been fetched.

    Keyed by tool AND arguments, because `daily-summary` for today and for
    yesterday are different answers to the same tool, and serving one for the
    other is the kind of error nobody catches by reading the reply.
    """

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self._entries: dict[tuple[str, str], tuple[float, Any, str, str | None]] = {}
        self._ttl = ttl_seconds

    @staticmethod
    def key(tool: str, arguments: dict[str, Any]) -> tuple[str, str]:
        # Server-injected arguments are excluded: `data_root` is a path on this
        # machine, identical for every call, and including it would only make
        # the key longer. Sorted so argument order cannot produce a miss.
        clean = {k: v for k, v in (arguments or {}).items() if k != "data_root"}
        return tool, json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str)

    def get(self, tool: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
        hit, data, _origin, _snapshot_at = self.get_entry(tool, arguments)
        return hit, data

    def get_entry(
        self, tool: str, arguments: dict[str, Any]
    ) -> tuple[bool, Any, str, str | None]:
        entry = self._entries.get(self.key(tool, arguments))
        if entry is None:
            return False, None, "", None
        stored_at, data, origin, snapshot_at = entry
        if (time.time() - stored_at) > self._ttl:
            return False, None, "", None
        return True, data, origin, snapshot_at

    def put(
        self,
        tool: str,
        arguments: dict[str, Any],
        data: Any,
        *,
        origin: str = "turn",
        snapshot_at: str | None = None,
    ) -> None:
        self._entries[self.key(tool, arguments)] = (
            time.time(), data, origin, snapshot_at
        )

    def __len__(self) -> int:
        return len(self._entries)


def admit(
    tool: str,
    registry: ToolRegistry,
    mode: Any,
    allowed_names: set[str],
) -> tuple[ToolDefinition | None, str]:
    """May this tool be called, in this mode, at all?

    Runs on EVERY round. The first round's calls were already checked by the
    orchestrator; these are the ones a model asked for after seeing data, which
    is exactly when it is most likely to reach past the boundary.

    Returns the definition, or None and a reason.
    """
    try:
        definition = registry.get(tool)
    except ToolNotFoundError:
        return None, "no such tool"

    if tool not in allowed_names:
        # The menu is per-principal and per-mode. A tool absent from it is
        # either not permitted to this user or not part of this mode's work.
        return None, "not offered in this mode"

    if getattr(mode, "read_only", False):
        described = {
            "name": definition.name,
            "safety": definition.safety,
            "requires_confirmation": definition.requires_confirmation,
        }
        if not mode_registry.is_read_only_tool(described):
            return None, "changes state; this mode is read-only"

    if requires_human_approval(definition) and not getattr(mode, "can_act", True):
        return None, "needs approval; this mode cannot act"

    if requires_human_approval(definition):
        # A write inside a gathering loop would bypass the confirmation gate,
        # which is the one control standing between a model and a patient
        # record. The loop reads; writes go the long way round.
        return None, "writes are never gathered; they go through confirmation"

    return definition, ""


def run_round(
    calls: list[tuple[str, dict[str, Any], str]],
    *,
    registry: ToolRegistry,
    context: DispatchContext,
    mode: Any,
    allowed_names: set[str],
    memory: WorkingMemory,
    request_id: str,
    with_server_arguments,
    remaining_sources: int,
) -> tuple[list[Fetched], list[Refused]]:
    """Execute one round of (tool, arguments, why) triples."""
    fetched: list[Fetched] = []
    refused: list[Refused] = []

    for tool, arguments, why in calls:
        if len(fetched) >= remaining_sources:
            refused.append(Refused(tool, "source budget reached"))
            continue

        definition, reason = admit(tool, registry, mode, allowed_names)
        if definition is None:
            LOG.info("gather refused %s: %s", tool, reason)
            refused.append(Refused(tool, reason))
            continue

        hit, cached, origin, snapshot_at = memory.get_entry(tool, arguments)
        if hit:
            fetched.append(
                Fetched(
                    tool, dict(arguments), True, cached, cached=True,
                    session_cached=origin == "session", snapshot_at=snapshot_at,
                    why=why,
                )
            )
            continue

        started = time.perf_counter()
        outcome = dispatch(
            ToolCall(
                definition.name,
                with_server_arguments(definition, arguments, context),
                request_id=request_id,
            ),
            registry=registry,
            context=context,
        )
        ms = int((time.perf_counter() - started) * 1000)

        if outcome.ok:
            memory.put(tool, arguments, outcome.data)
        fetched.append(
            Fetched(
                tool=definition.name,
                arguments=dict(arguments),
                ok=outcome.ok,
                data=outcome.data,
                error=outcome.error,
                audit_id=outcome.audit_id,
                ms=ms,
                why=why,
            )
        )

    return fetched, refused


def normalise_requests(raw: Any, limit: int = 6) -> list[tuple[str, dict[str, Any], str]]:
    """Turn whatever the model returned into (tool, arguments, why) triples.

    Defensive because this is model output: a malformed entry costs one source,
    while raising costs the whole answer -- and the answer is usually already
    possible from what round one fetched.
    """
    out: list[tuple[str, dict[str, Any], str]] = []
    if not isinstance(raw, list):
        return out
    for entry in raw[:limit]:
        if not isinstance(entry, dict):
            continue
        tool = str(entry.get("tool") or "").strip()
        if not tool:
            continue
        arguments = entry.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        out.append((tool, arguments, str(entry.get("why") or "")[:200]))
    return out
