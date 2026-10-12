"""The scenario registry is checked against reality, not against itself.

`modes.py` is held to this rule already and it is the reason a renamed tool
fails the build rather than silently emptying a mode. A scenario registry has
the same failure mode and one more: it names REPORT ROUTES, and a route that
does not exist in the catalogue would be a plan to call something that is not
there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reception_crm import scenarios
from reception_crm.core import modes
from reception_crm.core.registry import default_registry

PKG = Path(__file__).resolve().parents[1] / "reception_crm"

CATALOG = json.loads((PKG / "reports_catalog.json").read_text(encoding="utf-8"))
CATALOG_PATHS = {r["path"] for r in CATALOG["reports"]}

API = json.loads((PKG / "api_catalog.json").read_text(encoding="utf-8"))
API_PATHS = {r["path"] for r in API["routes"]}

REGISTERED = {str(t.get("name")) for t in default_registry().list()}


# --------------------------------------------------------------------------- #
# grounding
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scenario", scenarios.all_scenarios(), ids=lambda s: s.id)
def test_every_named_tool_exists(scenario):
    missing = sorted(set(scenario.tools()) - REGISTERED)
    assert not missing, f"{scenario.id} names tools that are not registered: {missing}"


@pytest.mark.parametrize("scenario", scenarios.all_scenarios(), ids=lambda s: s.id)
def test_every_named_report_exists_in_the_catalog(scenario):
    missing = sorted(set(scenario.preferred_reports) - CATALOG_PATHS)
    assert not missing, f"{scenario.id} names routes not in the catalogue: {missing}"


@pytest.mark.parametrize("scenario", scenarios.all_scenarios(), ids=lambda s: s.id)
def test_every_named_api_exists(scenario):
    """A report is one kind of source; these are the other 627 routes.

    Checked against `api_catalog.json`, which was built from `D:\\api`'s own
    routers with the mounts resolved from `index.js`. Naming a path that does
    not exist would be planning to call something that is not there.
    """
    missing = sorted(set(scenario.preferred_apis) - API_PATHS)
    assert not missing, f"{scenario.id} names API paths not in the catalogue: {missing}"


@pytest.mark.parametrize("scenario", scenarios.all_scenarios(), ids=lambda s: s.id)
def test_planned_tools_wrap_something_real(scenario):
    """A planned tool must name a source that exists, or it is a wish.

    The exception is the conversation scenario, whose sources are on a CENTRAL
    backend that no local catalogue covers — those are marked `central:` and
    are exempt by that prefix rather than by being skipped silently.
    """
    for tool in scenario.planned_tools:
        assert tool.name and tool.purpose_fa, f"{scenario.id}: {tool.name} is undescribed"
        for source in tool.wraps:
            if source.startswith("central:"):
                continue
            assert source in API_PATHS or source in CATALOG_PATHS, (
                f"{scenario.id}: planned tool {tool.name} wraps unknown source {source}"
            )


def test_planned_tools_are_never_offered_as_real_ones():
    """`tools()` is what narrowing uses. A tool that does not exist must not be
    in it, or the model would be handed a name it can never call."""
    for scenario in scenarios.all_scenarios():
        planned = {t.name for t in scenario.planned_tools}
        assert not (planned & set(scenario.tools()))
        assert not (planned & REGISTERED), (
            f"{scenario.id} plans a tool that already exists — promote it instead"
        )


def test_the_booking_tool_is_marked_as_a_write():
    """Booking changes a record, and `writes` is what keeps that visible.

    Matched by exact name rather than by substring: an earlier version looked
    for "schedule" anywhere in the name and caught `get_department_schedule`,
    which only READS the room timetable. A guard that fails on a correct entry
    gets relaxed, and then it guards nothing.
    """
    by_name = {t.name: t for s in scenarios.all_scenarios() for t in s.planned_tools}
    assert "schedule_appointment" in by_name
    assert by_name["schedule_appointment"].writes is True
    assert by_name["get_department_schedule"].writes is False


def test_every_writing_planned_tool_is_in_a_mode_that_may_act():
    """A write planned for a read-only scenario could never be carried through.

    Better to catch the contradiction in the registry than to build the tool and
    discover Executive mode was never on the scenario's list.
    """
    for scenario in scenarios.all_scenarios():
        if any(t.writes for t in scenario.planned_tools):
            assert "executive" in scenario.modes, (
                f"{scenario.id} plans a write but does not support executive mode"
            )


def test_the_dead_route_is_not_recommended():
    """`/cashier/summary` is defined twice and the second shadows the first.

    The catalogue records it, so a mapping written from the path list alone
    would include a route that never runs.
    """
    for scenario in scenarios.all_scenarios():
        assert "/cashier/summary" not in scenario.preferred_reports


@pytest.mark.parametrize("scenario", scenarios.all_scenarios(), ids=lambda s: s.id)
def test_every_scenario_is_described(scenario):
    assert scenario.name_fa and scenario.description_fa and scenario.intent_fa
    assert scenario.id == scenario.id.lower()


@pytest.mark.parametrize("scenario", scenarios.all_scenarios(), ids=lambda s: s.id)
def test_related_scenarios_exist(scenario):
    for other in scenario.related:
        assert scenarios.is_known(other), f"{scenario.id} relates to unknown {other}"


@pytest.mark.parametrize("scenario", scenarios.all_scenarios(), ids=lambda s: s.id)
def test_modes_named_are_real_modes(scenario):
    for mode_id in scenario.modes:
        assert modes.is_known(mode_id), f"{scenario.id} names unknown mode {mode_id}"


# --------------------------------------------------------------------------- #
# the safety property: subtraction only
# --------------------------------------------------------------------------- #
def _tools(*names):
    return [{"name": n, "safety": "read"} for n in names]


def test_narrowing_can_only_remove():
    offered = _tools("daily-summary", "cashier-report", "report.get", "conversation.summary")
    narrowed = scenarios.tools_for(scenarios.FINANCIAL, offered)
    assert {t["name"] for t in narrowed} <= {t["name"] for t in offered}


def test_a_scenario_cannot_add_a_tool_the_mode_withheld():
    """The property the read-only guarantee rests on.

    `FINANCIAL` names `cashier-reconciliation`; if the mode did not offer it,
    no scenario may put it back. This filters the list it is given and never
    consults the registry, so the guarantee is structural rather than a rule
    somebody has to remember.
    """
    offered = _tools("daily-summary")
    narrowed = scenarios.tools_for(scenarios.FINANCIAL, offered)
    assert [t["name"] for t in narrowed] == ["daily-summary"]


def test_general_narrows_nothing():
    """The whole fallback argument in one assertion.

    A question routed to General must be answered exactly as it was before this
    module existed, or "misclassification is free" stops being true.
    """
    offered = _tools("daily-summary", "report.get", "conversation.summary")
    assert scenarios.tools_for(scenarios.GENERAL, offered) == offered


def test_narrowing_to_nothing_returns_the_mode_menu():
    """A scenario whose tools are all absent must not disable the agent.

    Same guard as `modes.tools_for`, and worth having twice: this layer is a
    routing hint, and a hint that can leave the model with no tools is a hint
    that can take the assistant down.
    """
    offered = _tools("report.get")
    assert scenarios.tools_for(scenarios.CONVERSATION, offered) == offered


def test_multi_scenario_merges_both_menus():
    offered = _tools("cashier-report", "physician-performance", "report.get")
    narrowed = scenarios.tools_for_many(["staff", "financial"], offered)
    names = {t["name"] for t in narrowed}
    assert "cashier-report" in names and "physician-performance" in names
    assert "report.get" not in names


def test_a_general_half_means_do_not_narrow():
    offered = _tools("cashier-report", "report.get")
    assert scenarios.tools_for_many(["financial", "general"], offered) == offered


def test_unknown_scenario_falls_back_to_general():
    assert scenarios.get("nope").id == "general"
    assert scenarios.get(None).id == "general"
    offered = _tools("report.get")
    assert scenarios.tools_for_many(["nope"], offered) == offered


# --------------------------------------------------------------------------- #
# the published shape
# --------------------------------------------------------------------------- #
def test_as_dict_withholds_the_server_side_fields():
    """A phone renders quick actions; it has no use for the database path.

    Also a privacy-shaped habit: publish the menu, not the architecture.
    """
    published = scenarios.FINANCIAL.as_dict()
    for withheld in ("preferredReports", "databasePath", "validationRules", "crossCheckRules"):
        assert withheld not in published
    assert published["id"] == "financial"
    assert published["quickActionsFa"]


def test_every_scenario_publishes_cleanly():
    for scenario in scenarios.all_scenarios():
        json.dumps(scenario.as_dict(), ensure_ascii=False)


def test_the_api_catalog_is_bundled_by_both_packaging_paths():
    """A new data file is the F8 trap, and F8 was shipped four times.

    `api_catalog.json` is DATA: nothing imports it, so PyInstaller will not
    follow anything to it, and setuptools ships only what `package-data` names.
    A build without it does not fail — it answers from the three endpoints wired
    in by name, which reads as a thin answer rather than as a missing file.

    Both paths are asserted because fixing one and not the other is the easy way
    to make this mistake twice; that is precisely what happened with the
    lexicon, where the installer was fixed and the wheel was not.
    """
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    spec = (root / "scripts" / "ReceptionCrmServer.spec").read_text(encoding="utf-8")
    assert "api_catalog.json" in pyproject, "the wheel must ship the API catalogue"
    assert "API_CATALOG" in spec, "the frozen build must ship the API catalogue"
    assert "refusing to build" in spec.lower()


def test_the_api_catalog_describes_the_whole_surface_not_just_reports():
    """The point of the file. If it ever shrinks back to the Reports router,
    the scenario layer has quietly lost the other 627 routes."""
    assert API["route_count"] > 600
    reports = [r for r in API["routes"] if r["path"].startswith("/api/Reports")]
    assert 50 < len(reports) < 80
    assert len(reports) < API["route_count"] / 5, (
        "reports should be a minority of the surface — that is the finding"
    )


def test_conversation_recommends_no_reception_report():
    """The chat is a different backend. A reception route here is an invention.

    `conversation.summary` existed on neither mode menu once, and the model
    answered a chat question from the reception day summary. Naming a reception
    report as a conversation source would rebuild that mistake as a design.
    """
    assert scenarios.CONVERSATION.preferred_reports == ()
