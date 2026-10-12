"""The write path: confirmation, idempotency, identity, audit.

Every test here is a way the system could hurt a patient or a bank balance, and
the expected outcome is that it refuses. All data is synthetic; no CRM call is
made (the fake write tool records its calls instead of hitting the network).
"""

from __future__ import annotations

import json

import pytest

from reception_crm.audit import redact
from reception_crm.core import identity
from reception_crm.core.confirmation import ConfirmationStore
from reception_crm.core.guards import phi_fields_present
from reception_crm.core.idempotency import IdempotencyConflictError, IdempotencyStore
from reception_crm.core.orchestrator import CommandRequest, ConfirmRequest, confirm, handle_command
from reception_crm.core.registry import ToolRegistry
from reception_crm.core.types import DispatchContext, Principal, ToolDefinition


CALLS: list[dict] = []


def _schedule(args):
    CALLS.append(dict(args))
    return {"skill": "appointments.schedule", "executed": True}


WRITE_TOOL = ToolDefinition(
    name="appointments.schedule",
    kind="operation",
    handler=_schedule,
    description="Schedule an appointment",
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
        },
    },
    audit=False,
)

GOOD_ARGS = {"receptionId": "8891", "persianDate": "1405/04/25", "timeSlot": "10:00-10:30", "room": "R1"}


@pytest.fixture(autouse=True)
def _reset():
    CALLS.clear()
    yield
    CALLS.clear()


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(WRITE_TOOL)
    return reg


@pytest.fixture()
def context(tmp_path) -> DispatchContext:
    return DispatchContext(
        principal=Principal(user="vahid", center="RAZI", roles=["owner"], auth_method="session"),
        client="test",
        data_root=tmp_path,
        audit=False,
    )


@pytest.fixture()
def store() -> ConfirmationStore:
    return ConfirmationStore()


def fake_llm(*payloads):
    calls = {"n": 0}

    def chat(messages, **kwargs):
        payload = payloads[min(calls["n"], len(payloads) - 1)]
        calls["n"] += 1
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return {"content": content, "usage": {}}

    return chat


def schedule_decision(**args) -> dict:
    return {
        "intent": "schedule_appointment",
        "requiresClarification": False,
        "requiresConfirmation": True,
        "confidence": 0.9,
        "toolCalls": [{"tool": "appointments.schedule", "arguments": {**GOOD_ARGS, **args}}],
    }


def plan_a_write(registry, context, store, monkeypatch, **args) -> dict:
    """Plan a write in the one mode that is allowed to hold one.

    The mode is named explicitly, and must be. It used to be left off, which
    meant these tests ran in the DEFAULT mode — and the default is Report,
    which is now read-only by enforcement. A write there is refused before it
    can reach the confirmation machinery this file exists to test.

    That is the correct behaviour, and naming the mode here is the correct fix.
    The tempting one — relaxing the read-only ceiling so these tests pass again
    — would have traded a real guarantee for a green suite.
    """
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    return handle_command(
        CommandRequest(text="نوبت ثبت کن", request_id="req_w", mode="executive"),
        context=context,
        registry=registry,
        chat=fake_llm(schedule_decision(**args)),
        confirmations=store,
    )


# --- phase 1: the plan ------------------------------------------------------


def test_command_alone_never_writes(registry, context, store, monkeypatch):
    result = plan_a_write(registry, context, store, monkeypatch)

    assert CALLS == []  # the handler was never reached
    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert result["userAction"]["type"] == "CONFIRMATION"
    assert "planId" in result["userAction"]
    # The human must read the real arguments, not prose the model wrote.
    assert "8891" in result["userAction"]["summaryFa"]
    assert "1405/04/25" in result["userAction"]["summaryFa"]


def test_plan_response_carries_no_token(registry, context, store, monkeypatch):
    """The model can see WHAT would happen; it cannot cause it."""
    result = plan_a_write(registry, context, store, monkeypatch)
    body = json.dumps(result, ensure_ascii=False).lower()

    assert "token" not in body
    assert "confirmationtoken" not in body


# --- phase 2: the human approves --------------------------------------------


def test_confirmed_write_executes_once(registry, context, store, monkeypatch):
    plan = plan_a_write(registry, context, store, monkeypatch)["userAction"]["planId"]

    result = confirm(
        ConfirmRequest(plan_id=plan, idempotency_key="idem-1"),
        context=context,
        registry=registry,
        chat=fake_llm("ثبت شد."),
        confirmations=store,
    )

    assert result["success"] is True
    assert len(CALLS) == 1
    assert CALLS[0]["receptionId"] == "8891"


def test_write_without_an_idempotency_key_is_refused(registry, context, store, monkeypatch):
    plan = plan_a_write(registry, context, store, monkeypatch)["userAction"]["planId"]

    result = confirm(
        ConfirmRequest(plan_id=plan, idempotency_key=None),
        context=context,
        registry=registry,
        chat=fake_llm("ok"),
        confirmations=store,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "VALIDATION"
    assert CALLS == []


def test_a_plan_can_be_redeemed_only_once(registry, context, store, monkeypatch):
    plan = plan_a_write(registry, context, store, monkeypatch)["userAction"]["planId"]
    args = dict(plan_id=plan, idempotency_key="idem-1")

    first = confirm(ConfirmRequest(**args), context, registry, fake_llm("ok"), store)
    second = confirm(ConfirmRequest(**args), context, registry, fake_llm("ok"), store)

    assert first["success"] is True
    assert second["success"] is False
    assert second["error"]["code"] == "CONFIRMATION_INVALID"
    assert len(CALLS) == 1


def test_another_users_tap_is_not_your_approval(registry, context, store, monkeypatch):
    plan = plan_a_write(registry, context, store, monkeypatch)["userAction"]["planId"]
    intruder = DispatchContext(
        principal=Principal(user="someone_else", center="RAZI", roles=["owner"]),
        data_root=context.data_root,
        audit=False,
    )

    result = confirm(ConfirmRequest(plan_id=plan, idempotency_key="idem-2"), intruder, registry, fake_llm("ok"), store)

    assert result["error"]["code"] == "CONFIRMATION_INVALID"
    assert CALLS == []


def test_expired_plan_is_refused(registry, context, monkeypatch):
    store = ConfirmationStore(ttl=-1)  # already expired on creation
    plan = plan_a_write(registry, context, store, monkeypatch)["userAction"]["planId"]

    result = confirm(ConfirmRequest(plan_id=plan, idempotency_key="idem-3"), context, registry, fake_llm("ok"), store)

    assert result["error"]["code"] == "CONFIRMATION_INVALID"
    assert CALLS == []


def test_unknown_plan_id_is_refused(registry, context, store):
    result = confirm(
        ConfirmRequest(plan_id="pln_invented_by_a_model", idempotency_key="idem-4"),
        context, registry, fake_llm("ok"), store,
    )

    assert result["error"]["code"] == "CONFIRMATION_INVALID"
    assert CALLS == []


# --- idempotency ------------------------------------------------------------


def test_retry_with_the_same_key_does_not_double_book(registry, context, store, monkeypatch):
    """The network dropped after the write left the phone. The app retries."""
    plan = plan_a_write(registry, context, store, monkeypatch)["userAction"]["planId"]
    first = confirm(ConfirmRequest(plan_id=plan, idempotency_key="idem-9"), context, registry, fake_llm("ok"), store)

    plan2 = plan_a_write(registry, context, store, monkeypatch)["userAction"]["planId"]
    replay = confirm(ConfirmRequest(plan_id=plan2, idempotency_key="idem-9"), context, registry, fake_llm("ok"), store)

    assert first["success"] is True
    assert replay["success"] is True
    assert replay.get("replayed") is True
    assert len(CALLS) == 1  # ONE appointment, not two


def test_same_key_different_payload_is_a_hard_error(tmp_path):
    store = IdempotencyStore(tmp_path)
    store.remember("k", "sha256:aaa", {"success": True})

    with pytest.raises(IdempotencyConflictError):
        store.lookup("k", "sha256:bbb")


# --- identity ---------------------------------------------------------------


def test_a_session_token_cannot_be_forged(monkeypatch):
    monkeypatch.setenv("RECEPTION_SESSION_SECRET", "test-secret")
    session = identity.issue(Principal(user="vahid", center="RAZI", roles=["owner"]))

    assert identity.resolve(session.token).user == "vahid"

    tampered = session.token.replace("vahid", "admin") if "vahid" in session.token else session.token[:-4] + "AAAA"
    with pytest.raises(identity.AuthError):
        identity.resolve(tampered)


def test_a_revoked_session_stops_working(monkeypatch):
    monkeypatch.setenv("RECEPTION_SESSION_SECRET", "test-secret")
    session = identity.issue(Principal(user="vahid", center="RAZI", roles=["owner"]))

    identity.revoke(session.token)

    with pytest.raises(identity.AuthError):
        identity.resolve(session.token)


def test_an_expired_session_is_typed_as_expired(monkeypatch):
    monkeypatch.setenv("RECEPTION_SESSION_SECRET", "test-secret")
    session = identity.issue(Principal(user="vahid", center="RAZI", roles=["owner"]), ttl=-1)

    with pytest.raises(identity.SessionExpiredError):
        identity.resolve(session.token)


# --- PHI --------------------------------------------------------------------


def test_audit_hashes_phi_and_keeps_the_shape():
    record = redact(
        {
            "tool": "patients.search",
            "arguments": {"nationalCode": "0012345678", "patientName": "مریم رضایی", "limit": 5},
            "password": "hunter2",
        }
    )

    assert record["password"] == "<redacted>"
    assert record["arguments"]["nationalCode"].startswith("phi:sha256:")
    assert record["arguments"]["patientName"].startswith("phi:sha256:")
    assert "0012345678" not in json.dumps(record, ensure_ascii=False)
    assert "مریم" not in json.dumps(record, ensure_ascii=False)
    assert record["arguments"]["limit"] == 5  # non-PHI is left readable


def test_phi_fields_present_names_the_fields_not_the_values():
    fields = phi_fields_present({"nationalCode": "0012345678", "date": "today"})

    assert fields == ["nationalCode"]
