"""Two-phase confirmation: issued, not asserted.

    A confirmation is minted by the core, approved by a HUMAN on a surface the
    model cannot write to, and redeemed exactly once.   (security-model.md §3)

Phase 1 — plan.    The orchestrator stores the exact payload and returns a
                   ``plan_id`` and a human-readable summary. **No token.**
Phase 2 — approve. The human taps تأیید; the client calls ``/api/confirm`` with
                   the ``plan_id`` and *their own* session. The core checks the
                   plan belongs to that principal, is unexpired, and unused.
Phase 3 — execute. The plan is redeemed once. It is invalid if: expired ·
                   already used · a different principal · the payload changed by
                   one byte (payload_hash).

The payload-hash binding is the part that matters: it stops an approval for a
4,500,000-rial admission being spent on a 45,000,000-rial one.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .errors import ReceptionCoreError

DEFAULT_TTL_SECONDS = 300  # 5 minutes


class ConfirmationError(ReceptionCoreError):
    code = "CONFIRMATION_INVALID"


@dataclass
class Plan:
    plan_id: str
    user: str | None
    center: str | None
    intent: str
    steps: list[dict[str, Any]]
    payload_hash: str
    summary_fa: str
    effects: list[str] = field(default_factory=list)
    request_id: str = ""
    #: The mode this plan was composed in. Provenance, deliberately NOT part of
    #: `payload_hash`: the hash binds what will be EXECUTED, and widening it to
    #: cover metadata would make approvals fail for reasons that have nothing to
    #: do with the action approved.
    #:
    #: It exists because redemption used to lose it. `confirm()` called `_run`
    #: without a mode, so a completed write reported `mode: null` while every
    #: other response named one — the one turn where knowing which mode was in
    #: force matters most, because it is the only kind that changed something.
    mode: str | None = None
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    used: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "CONFIRMATION",
            "planId": self.plan_id,
            "requestId": self.request_id,
            "mode": self.mode,
            "intent": self.intent,
            "summaryFa": self.summary_fa,
            "effects": list(self.effects),
            "steps": [
                {"tool": step["tool"], "safety": step.get("safety"), "arguments": step.get("arguments", {})}
                for step in self.steps
            ],
            "expiresAt": int(self.expires_at),
        }


class ConfirmationStore:
    """In-process plan store. Plans live 5 minutes; a restart voids them (safe)."""

    def __init__(self, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self._plans: dict[str, Plan] = {}
        self._ttl = ttl
        self._lock = threading.Lock()

    def create(
        self,
        principal: Any,
        intent: str,
        steps: list[dict[str, Any]],
        summary_fa: str,
        effects: list[str] | None = None,
        request_id: str = "",
        mode: str | None = None,
    ) -> Plan:
        now = time.time()
        plan = Plan(
            plan_id=f"pln_{uuid.uuid4().hex[:16]}",
            user=getattr(principal, "user", None),
            center=getattr(principal, "center", None),
            intent=intent,
            steps=steps,
            payload_hash=payload_hash(steps),
            summary_fa=summary_fa,
            effects=list(effects or []),
            request_id=request_id,
            mode=mode,
            created_at=now,
            expires_at=now + self._ttl,
        )
        with self._lock:
            self._purge(now)
            self._plans[plan.plan_id] = plan
        return plan

    def redeem(self, plan_id: str, principal: Any) -> Plan:
        """Consume a plan. Every failure mode here is a refusal, never a warning."""
        now = time.time()
        with self._lock:
            plan = self._plans.get(str(plan_id))
            if plan is None:
                raise ConfirmationError("This confirmation is unknown or has already been used.")
            if plan.used:
                raise ConfirmationError("This confirmation has already been used.")
            if plan.expires_at < now:
                del self._plans[plan.plan_id]
                raise ConfirmationError("This confirmation has expired. Please repeat the command.")
            if plan.user != getattr(principal, "user", None) or plan.center != getattr(principal, "center", None):
                # Approval is personal. Another user's tap is not your approval.
                raise ConfirmationError("This confirmation belongs to a different user.")
            if plan.payload_hash != payload_hash(plan.steps):
                raise ConfirmationError("The planned payload changed after approval.")
            plan.used = True
            del self._plans[plan.plan_id]
        return plan

    def _purge(self, now: float) -> None:
        for key in [k for k, v in self._plans.items() if v.expires_at < now]:
            del self._plans[key]


def payload_hash(steps: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        [{"tool": s["tool"], "arguments": s.get("arguments", {})} for s in steps],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_STORE = ConfirmationStore()


def default_store() -> ConfirmationStore:
    return _STORE
