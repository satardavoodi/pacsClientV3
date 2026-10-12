"""Write tools — reachable from ``dispatch()``, but only through the gates.

Only ONE write is registered: ``appointments.schedule``. It is the lowest blast
radius and the easiest to reverse, which is exactly why it goes first
(docs/voice-pipeline.md §7).

A write executes only when ALL of these hold:

  1. the core issued a plan and a **human redeemed it** (orchestrator, via
     ``core/confirmation.py``) — the model cannot mint an approval;
  2. an **idempotency key** is present, so a retry cannot double-book;
  3. the role policy permits ``execute`` on this operation (``core/guards.py``,
     already run by ``dispatch()`` before this handler is reached);
  4. the operation is ``enabled: true`` in ``config/operations.json``;
  5. ``RECEPTION_ENABLE_WRITES=true`` in the environment.

4 and 5 are owner-controlled switches and are OFF today. 1–3 are the controls
that hold against an agent.

This module deliberately does NOT go through ``write_executor.execute_operation``:
that path re-checks a *caller-supplied* user string and the fixed ``EXECUTE <op>``
phrase — two guards the security model classes as forgeable. Here the identity
came from a session and the confirmation came from a human. The remaining owner
switches are re-checked below, and a blocked write **raises** rather than
returning a cheerful "not executed" payload: a refusal must never be mistakable
for a success.
"""

from __future__ import annotations

import os
from typing import Any

from ...audit import AuditLogger
from ...config import DEFAULT_DATA_ROOT
from ...ino_api import InoClient
from ...operations import load_operations
from ...write_executor import api_path_from_url
from ..errors import ReceptionCoreError
from ..registry import ToolRegistry
from ..types import ToolDefinition


class WriteBlockedError(ReceptionCoreError):
    code = "WRITE_BLOCKED"


def writes_enabled() -> bool:
    return os.getenv("RECEPTION_ENABLE_WRITES") == "true"


def register_write_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="appointments.schedule",
            kind="operation",
            handler=_schedule_appointment,
            description=(
                "Schedule an appointment for a reception that is waiting. Requires the reception id "
                "(use patients.search first), a Jalali date (YYYY/MM/DD), a time slot, and a room."
            ),
            safety="clinical_write",
            permission_action="execute",
            requires_confirmation=True,
            requires_idempotency=True,
            confirmation_summary_fa="ثبت نوبت برای پذیرش {receptionId} در تاریخ {persianDate} ساعت {timeSlot}",
            effects_fa=("یک نوبت جدید در CRM ثبت می‌شود.",),
            input_schema={
                "type": "object",
                "required": ["receptionId", "persianDate", "timeSlot", "room"],
                "properties": {
                    "receptionId": {"type": "string"},
                    "persianDate": {"type": "string"},
                    "timeSlot": {"type": "string"},
                    "room": {"type": "string"},
                    "roomName": {"type": "string"},
                    "startTime": {"type": "string"},
                    "endTime": {"type": "string"},
                    "scheduledAt": {"type": "string"},
                    "shift": {"type": "string"},
                    "shiftName": {"type": "string"},
                    "duration": {"type": "integer"},
                },
            },
        )
    )


def _schedule_appointment(args: dict[str, Any]) -> dict[str, Any]:
    return _execute("appointments.schedule", args)


def _execute(operation: str, args: dict[str, Any]) -> dict[str, Any]:
    registry = load_operations()
    plan = registry.plan(operation, args)

    if plan.missing_required_inputs:
        raise WriteBlockedError(f"Missing required inputs: {', '.join(plan.missing_required_inputs)}")
    if not plan.enabled:
        raise WriteBlockedError(
            f"{operation} is disabled in config/operations.json. Enabling it is a deliberate, "
            "owner-approved act."
        )
    if not writes_enabled():
        raise WriteBlockedError(
            "Writes are globally disabled. Set RECEPTION_ENABLE_WRITES=true on the Reception CRM machine."
        )

    client = InoClient.from_env()
    response = client.request(plan.method, api_path_from_url(plan.url), params=plan.query, body=plan.body)

    # A separate, explicit record of the CRM mutation itself. `redact()` hashes
    # PHI; secrets are stripped. This is in addition to the dispatch audit.
    AuditLogger(DEFAULT_DATA_ROOT).write(
        "crm_write",
        {
            "operation": operation,
            "method": plan.method,
            "endpoint": api_path_from_url(plan.url),
            "safety": plan.safety,
            "status": "executed",
            "inputs": args,
        },
    )
    return {"skill": operation, "executed": True, "api_response": response}
