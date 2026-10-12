"""An input a tool does not know is REFUSED, and a date range is honoured.

⚠️ WHY THIS FILE EXISTS. The report tools took `date` and `days`. The model sent
`start_date`/`end_date` — the shape its sibling `reception.search` uses — and
those keys were dropped in silence, `date` fell back to "today", and the report
answered confidently about a day nobody had asked about. Three benchmark
questions came back with real figures from the wrong day, and the only reason it
was ever noticed is that the agent read the period in the payload and said the
two did not match.

Two changes, and both are needed. Accepting `dateFrom`/`dateTo` fixes the case
the model actually hit. Refusing everything undeclared fixes the case nobody has
hit yet — because a caller cannot correct a mistake it is never told about.
"""

from __future__ import annotations

import pytest

from reception_crm.core.errors import ToolValidationError
from reception_crm.core.registry import default_registry
from reception_crm.core.tools import reports
from reception_crm.core.validation import validate_input

SCHEMA = {
    "type": "object",
    "required": ["data_root"],
    "properties": {
        "date": {"type": "string"},
        "days": {"type": "integer"},
        "dateFrom": {"type": "string"},
        "dateTo": {"type": "string"},
        "data_root": {"type": "string"},
    },
}


# ------------------------------------------------------- refusing the unknown

def test_an_undeclared_input_is_refused():
    with pytest.raises(ToolValidationError) as exc:
        validate_input(SCHEMA, {"data_root": "/tmp", "start_date": "1405/06/02"})
    assert "start_date" in str(exc.value)


def test_the_refusal_names_what_the_tool_does_accept():
    """A refusal the caller cannot act on is only a slower failure."""
    with pytest.raises(ToolValidationError) as exc:
        validate_input(SCHEMA, {"data_root": "/tmp", "start_date": "1405/06/02"})
    message = str(exc.value)
    for accepted in ("date", "days", "dateFrom", "dateTo"):
        assert accepted in message


def test_every_undeclared_input_is_named_not_just_the_first():
    with pytest.raises(ToolValidationError) as exc:
        validate_input(SCHEMA, {"data_root": "/tmp",
                                "start_date": "x", "end_date": "y", "modality": "MRI"})
    message = str(exc.value)
    assert "start_date" in message and "end_date" in message and "modality" in message


def test_a_declared_input_still_passes():
    validate_input(SCHEMA, {"data_root": "/tmp", "dateFrom": "1405/06/01",
                            "dateTo": "1405/06/03"})


def test_a_schema_with_no_properties_declares_nothing_and_refuses_nothing():
    """Silence about what is accepted is not a contract. A tool that publishes
    no properties cannot be held to a list it never wrote."""
    validate_input({"type": "object"}, {"anything": 1})


def test_every_registered_read_tool_declares_its_own_arguments():
    """The refusal above only helps where the schema is complete. A tool whose
    handler reads an argument it never declared would now REFUSE that argument —
    so the declaration is the contract, and it has to be true."""
    for name, definition in default_registry().tools.items():
        schema = definition.input_schema or {}
        if not schema.get("properties"):
            continue
        for required in schema.get("required", []):
            assert required in schema["properties"], (
                f"{name} requires {required} but does not declare it"
            )


# ------------------------------------------------------------- the date range

def test_a_date_range_is_honoured_rather_than_ignored():
    period = reports._period({"dateFrom": "1405/06/01", "dateTo": "1405/06/03"})
    assert period.start_jalali == "1405/06/01"
    assert period.end_jalali == "1405/06/03"
    assert period.assumed is False


def test_one_end_of_a_range_is_a_single_day_not_an_open_one():
    """An unbounded report over a clinical archive is never what was meant."""
    period = reports._period({"dateTo": "1405/06/02"})
    assert period.start_jalali == period.end_jalali == "1405/06/02"


def test_a_reversed_range_is_read_in_the_order_that_makes_sense():
    period = reports._period({"dateFrom": "1405/06/03", "dateTo": "1405/06/01"})
    assert period.start_jalali == "1405/06/01"
    assert period.end_jalali == "1405/06/03"


def test_the_single_day_form_still_works():
    period = reports._period({"date": "1405/06/02"})
    assert period.start_jalali == period.end_jalali == "1405/06/02"


def test_a_period_nobody_asked_for_is_still_marked_assumed():
    """The whole failure was a day nobody named being reported as fact. The
    `assumed` flag is what lets the answer say so, and a range must not lose
    it for the no-arguments case."""
    assert reports._period({}).assumed is True


def test_the_range_reaches_the_report_tools_schema():
    for name in ("daily-summary", "cashier-report", "financial-analysis",
                 "cashier-reconciliation", "risk-analysis"):
        properties = default_registry().get(name).input_schema["properties"]
        assert "dateFrom" in properties and "dateTo" in properties, name
