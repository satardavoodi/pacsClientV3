"""One concept, several spellings — and the thirteen calls that proved it.

⚠️ Replaying the 194 tool calls the v3 benchmark actually made found THIRTEEN
that were already silently broken: accepted, ignored, and answered anyway.
`daily-summary` and `cashier-reconciliation` were sent `start_date`/`end_date`
and reported about TODAY. `reporting-queue` was sent `date` and reported about a
period nobody asked for. `patients.search` was sent `name`, matched nothing, and
did not say so — that one is why P1's patient lookup came back empty.

Not one of those was an unreasonable guess. `reception.search` says `dateFrom`,
the report tools said `date`, `reporting-queue` says `startDate`: the menu was
inconsistent, and anything reading it would guess.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reception_crm.core.aliases import normalise_arguments
from reception_crm.core.errors import ToolValidationError
from reception_crm.core.registry import default_registry
from reception_crm.core.validation import validate_input

BENCH = Path(__file__).resolve().parents[1] / "benchmark"


def schema_of(tool: str) -> dict:
    return default_registry().get(tool).input_schema or {}


# --------------------------------------------------------------- the renames

@pytest.mark.parametrize("tool,sent,expected", [
    ("daily-summary", {"start_date": "1405/06/02"}, "dateFrom"),
    ("daily-summary", {"end_date": "1405/06/02"}, "dateTo"),
    ("cashier-reconciliation", {"start_date": "1405/06/02"}, "dateFrom"),
    ("reception.search", {"start_date": "1405/06/02"}, "dateFrom"),
    ("patients.search", {"name": "x"}, "patientName"),
    ("trend-analysis", {"compare_to": "last-week"}, "compare"),
])
def test_a_sibling_tools_spelling_is_renamed_onto_the_declared_one(tool, sent, expected):
    out = normalise_arguments(schema_of(tool), sent)
    assert expected in out
    assert set(sent) & set(out) == set(), "the caller's spelling should be gone"


def test_the_callers_dict_is_never_mutated():
    """The original arguments are what the audit log records and what a
    confirmation shows a human. Renaming in place would make the two disagree."""
    sent = {"start_date": "1405/06/02"}
    normalise_arguments(schema_of("daily-summary"), sent)
    assert sent == {"start_date": "1405/06/02"}


def test_a_single_day_widens_to_both_ends_of_a_range():
    """«صف گزارش امروز» is a fair question to a tool that only speaks in ranges."""
    out = normalise_arguments(schema_of("reporting-queue"), {"date": "1405/06/02"})
    assert out == {"startDate": "1405/06/02", "endDate": "1405/06/02"}


def test_a_range_is_never_collapsed_into_a_day():
    """Widening one day into two ends keeps everything that was asked for.
    Narrowing a range to a day would throw part of it away."""
    schema = schema_of("daily-summary")
    out = normalise_arguments(schema, {"dateFrom": "1405/06/01", "dateTo": "1405/06/03"})
    assert out == {"dateFrom": "1405/06/01", "dateTo": "1405/06/03"}
    assert "date" not in out


def test_two_spellings_of_the_same_thing_are_refused_not_guessed():
    """Which one did they mean? Neither answer is safe, so neither is given."""
    with pytest.raises(ToolValidationError, match="mean the same thing"):
        normalise_arguments(schema_of("daily-summary"),
                            {"dateFrom": "1405/06/01", "start_date": "1405/05/01"})


def test_a_capability_the_tool_lacks_is_still_refused():
    """⚠️ THE LINE THIS MUST NOT CROSS. `cashier-report` cannot group by
    cashier. «کدوم صندوق‌دار» was sent to it with `groupBy`, and the right
    answer is that this tool cannot do that — not a silent report of the
    ungrouped total under a question about individuals."""
    schema = dict(schema_of("cashier-report"))
    # `data_root` is injected server-side, so it is supplied here to let the
    # required check pass and the UNKNOWN check be the thing under test.
    out = normalise_arguments(schema, {"groupBy": "cashier", "data_root": "/tmp"})
    assert out["groupBy"] == "cashier"
    with pytest.raises(ToolValidationError, match="groupBy"):
        validate_input(schema, out)


def test_a_tool_that_declares_both_names_keeps_them_apart():
    """`finance.metric` declares dateFrom AND startDate deliberately. A tool
    that distinguishes two names is not ours to merge."""
    schema = schema_of("finance.metric")
    properties = set(schema["properties"])
    assert {"dateFrom", "startDate"} <= properties
    out = normalise_arguments(schema, {"metric": "service_value", "startDate": "1405/06/01"})
    assert out["startDate"] == "1405/06/01"


# ------------------------------------------------- the corpus, replayed whole

def _captured_calls():
    for name in ("challenge_v3_results.json", "retest_v3_results.json",
                 "retest2_v3_results.json"):
        path = BENCH / name
        if not path.exists():
            continue
        run = json.loads(path.read_text(encoding="utf-8"))
        rows = list(run.get("core") or [])
        for section in ("variants", "conversations"):
            for item in run.get(section) or []:
                rows.extend(item.get("turns") or [])
        for row in rows:
            for source in row.get("sources") or []:
                if isinstance(source, dict) and isinstance(source.get("arguments"), dict):
                    yield str(source.get("tool") or ""), source["arguments"]


#: The two calls that SHOULD be refused, and why. Listed rather than excluded,
#: because a refusal nobody has written down looks like one nobody noticed.
EXPECTED_REFUSALS = {
    ("cashier-report", "groupBy"): "this tool cannot group; saying so is the answer",
    ("trend-analysis", "compare"): "the comparison period was not one of the three "
                                   "the tool supports — the enum is doing its job, "
                                   "where before the whole argument was dropped",
}


def test_every_call_the_agent_really_made_still_works():
    """The corpus is 194 real (tool, arguments) pairs the model chose against
    the real menu. Anything here that breaks is a schema that lies."""
    registry = default_registry()
    surprises = []
    for tool, args in _captured_calls():
        try:
            definition = registry.get(tool)
        except Exception:
            continue  # a renamed tool is a separate concern, covered elsewhere
        schema = dict(definition.input_schema or {})
        schema["required"] = [k for k in schema.get("required", []) if k != "data_root"]
        try:
            validate_input(schema, normalise_arguments(schema, args))
        except ToolValidationError as exc:
            key = next((k for k in EXPECTED_REFUSALS if k[0] == tool and k[1] in str(exc)),
                       None)
            if key is None:
                surprises.append(f"{tool}: {exc}  args={sorted(args)}")
    assert not surprises, "\n".join(surprises)
