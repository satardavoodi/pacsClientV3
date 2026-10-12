"""Every response says the same things about itself.

The envelope was already a fixed shape, which is most of the work. Two facts
were missing from it, and both were missing in the way that is hardest to
notice — present somewhere, so nothing looked broken.

`mode` appeared on all five refusal paths and on none of the answers, so a
client could learn which mode was in force by being turned down but not by
being served. `serverVersion` appeared nowhere at all, so no reply could say
which build produced it, and every benchmark row that records a version records
the name of an installer someone copied over.

Both are additive: a client that does not know these keys is unaffected.
"""

from __future__ import annotations

import inspect

import reception_crm
from reception_crm.core import orchestrator


def test_the_base_envelope_carries_the_build():
    """On the base, so refusals identify the build too.

    A failure is exactly when someone asks "which version did that?", and a
    version present only on success is absent from every report worth filing.
    """
    envelope = orchestrator._envelope("req_1", 0.0)

    assert envelope["serverVersion"] == reception_crm.__version__


def test_a_refusal_carries_the_build():
    failure = orchestrator._failure("req_1", "VALIDATION", "…", 0.0)

    assert failure["serverVersion"] == reception_crm.__version__
    assert failure["success"] is False


def test_every_envelope_key_is_always_present():
    """The shape must not vary by outcome.

    A caller that has to test for the presence of a key before reading it will
    eventually stop testing, and then a missing key reads as a false value.
    """
    base = orchestrator._envelope("req_1", 0.0)
    failure = orchestrator._failure("req_1", "VALIDATION", "…", 0.0)

    assert set(base).issubset(set(failure))
    for key in ("requestId", "serverVersion", "success", "message", "result",
                "action", "requiresUserAction", "userAction", "error",
                "auditId", "latencyMs"):
        assert key in base, key


def test_the_answer_path_reports_its_mode():
    """Read out of the source: `_run` needs a live dispatch to exercise.

    What this pins is that the success envelope names the mode at all — the
    asymmetry it fixes was invisible precisely because every OTHER path already
    did.
    """
    source = inspect.getsource(orchestrator._run)
    assert '"mode": mode,' in source, (
        "the success envelope must report the mode, as every refusal path does"
    )


def test_a_plan_remembers_the_mode_it_was_composed_in():
    """Redemption used to lose it, on the only turn that changes anything.

    `confirm()` called `_run` with no mode, so a completed write reported
    `mode: null` while every refusal named one. The plan carries it now — and
    the mode that matters is the one the human saw and approved, not whichever
    mode the client happens to be in when it taps تأیید a minute later.
    """
    from reception_crm.core.confirmation import ConfirmationStore

    class _P:
        user = "dr"
        center = "RAZI"

    store = ConfirmationStore()
    plan = store.create(
        principal=_P(),
        intent="cancel",
        steps=[{"tool": "reception.cancel", "safety": "write", "arguments": {"receptionId": 1}}],
        summary_fa="…",
        mode="executive",
    )

    assert plan.mode == "executive"
    assert plan.as_dict()["mode"] == "executive"
    assert store.redeem(plan.plan_id, _P()).mode == "executive"


def test_the_mode_is_not_part_of_the_payload_hash():
    """The hash binds what will be EXECUTED.

    Widening it to metadata would make approvals fail for reasons that have
    nothing to do with the action approved — the opposite of what the binding
    is for, which is stopping an approval for one amount being spent on another.
    """
    from reception_crm.core.confirmation import payload_hash

    steps = [{"tool": "reception.cancel", "arguments": {"receptionId": 1}}]

    assert payload_hash(steps) == payload_hash([dict(steps[0], mode="executive")])


def test_the_documented_contract_mentions_both_keys():
    """A wire contract nobody wrote down is a wire contract nobody can rely on."""
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[1] / "docs" / "mobile-agent-http-api.md").read_text(
        encoding="utf-8"
    )
    assert "serverVersion" in doc
    assert "`mode`" in doc
