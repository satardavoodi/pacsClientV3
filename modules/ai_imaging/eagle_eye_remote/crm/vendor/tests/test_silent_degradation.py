"""Degrading is allowed. Degrading in silence is not.

This package has already paid for one silent fallback: a frozen build shipped
without `lexicon.json`, the `FileNotFoundError` was swallowed, and the server
told people that «ultrasound» is not a modality in this database — for four
releases, with every test green.

These three had the same shape and were found by a review rather than by an
incident. Each keeps its fallback, because failing hard would be worse in a
clinic; what each gained is a way to find out it happened.
"""

from __future__ import annotations

import json
import logging


from reception_crm import config as config_module
from reception_crm import operations as operations_module
from reception_crm.core import orchestrator
from reception_crm.core.types import ToolDefinition
from reception_crm.llm.interpreter import ProposedCall


# --------------------------------------------------------------------------- #
# which centre the agent talks to
# --------------------------------------------------------------------------- #
def test_unreadable_settings_are_reported_before_the_endpoint_falls_back(monkeypatch, caplog):
    """A malformed settings file must not quietly redirect the agent.

    `load_settings()` builds a profile from the environment when there is no
    settings file, so it only raises when a file EXISTS and cannot be read.
    The fallback then resolves the base URL from the environment, where the
    default host is a literal belonging to one particular clinic — so the
    swallowed version turned "your saved profile is corrupt" into "you are now
    querying somebody else's CRM", with no trace at all.
    """
    def explode():
        raise json.JSONDecodeError("Expecting value", "{", 0)

    monkeypatch.setattr(config_module, "_active_profile_or_warn", config_module._active_profile_or_warn)
    import reception_crm.settings as settings_module

    monkeypatch.setattr(settings_module, "load_settings", lambda *a, **k: explode())

    with caplog.at_level(logging.ERROR, logger="reception_crm.config"):
        profile = config_module._active_profile_or_warn()

    assert profile is None, "the fallback is deliberately kept"
    assert caplog.records, "but it must not be silent"
    message = caplog.records[0].getMessage()
    assert "connection settings" in message
    assert "DIFFERENT" in message, "the log must say what the fallback risks"


def test_unreadable_settings_are_reported_before_write_targets_fall_back(monkeypatch, caplog, tmp_path):
    """Same fault, on the path that carries writes.

    Operations are the write actions. If the saved profile cannot be read, the
    registry keeps whatever base URLs `operations.json` names, and a booking or
    a cancellation goes there. That must be findable afterwards.
    """
    registry_file = tmp_path / "operations.json"
    registry_file.write_text(
        json.dumps({"base_urls": {"crm": "http://example.invalid"}, "operations": []}),
        encoding="utf-8",
    )

    import reception_crm.settings as settings_module

    def explode(*args, **kwargs):
        raise TypeError("ConnectionProfile got an unexpected keyword argument 'newField'")

    monkeypatch.setattr(settings_module, "load_settings", explode)

    with caplog.at_level(logging.ERROR, logger="reception_crm.operations"):
        registry = operations_module.load_operations(str(registry_file))

    assert registry is not None, "the fallback is deliberately kept"
    assert caplog.records, "but it must not be silent"
    assert "DIFFERENT centre" in caplog.records[0].getMessage()


# --------------------------------------------------------------------------- #
# what the human approves
# --------------------------------------------------------------------------- #
def _definition(**kwargs) -> ToolDefinition:
    base = dict(
        name="reception.cancel",
        kind="action",
        description="لغو پذیرش",
        handler=lambda args: {},
    )
    base.update(kwargs)
    return ToolDefinition(**base)


def test_a_confirmation_with_an_unfilled_slot_shows_the_arguments(caplog):
    """An em-dash is not an acceptable answer to "what am I approving?".

    Every template slot used to be pre-filled with «—» so that `.format()`
    could not raise. It could not — and that was the defect, not the
    protection. A call naming the wrong argument rendered as «لغو پذیرش —»,
    and a human was asked to tap تأیید on it: a sentence that still looked
    like a confirmation while it had stopped naming what would happen.
    """
    definition = _definition(confirmation_summary_fa="لغو پذیرش {receptionId}")
    call = ProposedCall(tool="reception.cancel", arguments={"wrongKey": 55448})

    with caplog.at_level(logging.WARNING, logger="reception_crm.core.orchestrator"):
        summary = orchestrator._summary_fa([call], [definition])

    assert "55448" in summary, "the subject of the action must survive the failure"
    assert "wrongKey" in summary
    assert "—" not in summary, "a placeholder must not stand in for the subject"
    assert caplog.records, "and the template failure must be findable"


def test_a_fully_supplied_template_still_reads_as_a_sentence():
    """The common path must not be disturbed by the fix to the uncommon one."""
    definition = _definition(
        confirmation_summary_fa="ثبت نوبت برای پذیرش {receptionId} در تاریخ {persianDate}"
    )
    call = ProposedCall(
        tool="reception.cancel",
        arguments={"receptionId": 8891, "persianDate": "1405/04/25"},
    )

    summary = orchestrator._summary_fa([call], [definition])

    assert summary == "ثبت نوبت برای پذیرش 8891 در تاریخ 1405/04/25"


def test_a_tool_with_no_template_still_names_its_subject():
    definition = _definition(confirmation_summary_fa="")
    call = ProposedCall(tool="reception.cancel", arguments={"receptionId": 8891})

    summary = orchestrator._summary_fa([call], [definition])

    assert "لغو پذیرش" in summary
    assert "8891" in summary


def test_a_tool_with_no_arguments_reads_as_a_plain_sentence():
    definition = _definition(confirmation_summary_fa="")
    call = ProposedCall(tool="reception.cancel", arguments={})

    assert orchestrator._summary_fa([call], [definition]) == "لغو پذیرش"
