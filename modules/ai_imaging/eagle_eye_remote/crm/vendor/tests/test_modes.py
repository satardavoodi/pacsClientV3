"""Agent modes: the registry, the narrowing, and the ceiling.

The load-bearing property is that a mode only ever *removes*. If a mode could
add a tool, the permission model would have a second door.
"""

from __future__ import annotations

import pytest

from reception_crm.core import modes
from reception_crm.core.registry import default_registry


# --------------------------------------------------------------------------- #
# the registry is real
# --------------------------------------------------------------------------- #
def test_every_named_tool_actually_exists():
    """A renamed tool would leave a mode narrowing to nothing — an assistant
    that still answers but has quietly lost half its abilities."""
    registered = set(default_registry().tools)
    for mode in modes.all_modes():
        missing = [name for name in mode.tools if name not in registered]
        assert not missing, f"mode '{mode.id}' names tools that do not exist: {missing}"


def test_every_prefix_matches_at_least_one_tool():
    registered = list(default_registry().tools)
    for mode in modes.all_modes():
        for prefix in mode.prefixes:
            assert any(name.startswith(prefix) for name in registered), (
                f"mode '{mode.id}' has prefix '{prefix}' that matches nothing"
            )


def test_every_mode_has_a_prompt_file_on_disk():
    from reception_crm.llm.interpreter import PROMPT_DIR

    for mode in modes.all_modes():
        path = PROMPT_DIR / mode.prompt_file
        assert path.exists(), f"mode '{mode.id}' prompt is missing: {path}"
        assert path.read_text(encoding="utf-8").strip(), f"mode '{mode.id}' prompt is empty"


def test_the_default_mode_is_one_of_the_modes():
    assert modes.is_known(modes.DEFAULT_MODE)


def test_the_three_modes_the_product_promises_are_present():
    """Report, Analysis, Executive Command. The default product ships exactly
    these, on every customer's server, without configuration."""
    assert [m.id for m in modes.all_modes()] == ["report", "analysis", "executive"]


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def test_an_unknown_mode_falls_back_rather_than_failing():
    """An older or newer client naming a mode this server lacks should get an
    answer in the default mode, not a refusal. Safe because a mode only narrows."""
    assert modes.get("no-such-mode").id == modes.DEFAULT_MODE
    assert modes.get(None).id == modes.DEFAULT_MODE
    assert modes.get("").id == modes.DEFAULT_MODE
    assert modes.get("  ANALYSIS  ").id == "analysis"


def test_is_known_is_strict_where_get_is_forgiving():
    assert modes.is_known("analysis")
    assert not modes.is_known("no-such-mode")


# --------------------------------------------------------------------------- #
# the rename
# --------------------------------------------------------------------------- #
def test_the_retired_id_still_resolves_to_the_mode_that_replaced_it():
    """'order' was renamed to 'executive'. Conversations stored under the old id
    exist on the server and in every phone's mirror, and `get()` falls back to
    the DEFAULT mode for anything unknown — so without the alias each of those
    chats would have quietly reopened in Reporting mode: still there, still
    answering, and no longer able to do the thing it was opened to do."""
    assert modes.get("order").id == "executive"
    assert modes.get("action").id == "executive"
    assert modes.is_known("order")
    assert modes.canonical("  ORDER  ") == "executive"


def test_the_retired_id_is_resolved_but_never_advertised():
    """A client that learns 'order' from us today asks for it forever."""
    published = [m["id"] for m in (m.as_dict() for m in modes.all_modes())]
    assert "order" not in published and "action" not in published


def test_a_stored_conversation_migrates_to_the_new_id_rather_than_keeping_both():
    from reception_crm.core import conversations

    assert conversations._mode("order") == "executive"
    assert conversations._mode("executive") == "executive"


# --------------------------------------------------------------------------- #
# narrowing
# --------------------------------------------------------------------------- #
def _tools(*names):
    return [{"name": n} for n in names]


def test_a_mode_can_only_remove_tools_never_add_one():
    offered = _tools("report.search", "financial-analysis", "patients.search")
    for mode in modes.all_modes():
        narrowed = modes.tools_for(mode, offered)
        assert all(t in offered for t in narrowed), f"mode '{mode.id}' invented a tool"


def test_reporting_mode_hides_the_analytical_tools():
    """Report retrieves. `financial-analysis`, `trend-analysis` and the
    `integrity.*` checks all reason over what they read, which is the other
    mode's job — so they are not on this menu.

    `cashier-reconciliation` used to be here, on the argument that it was the
    only tool that read the cashier's day and that the prompt would govern the
    treatment. Both halves were weak. It computes variances and possible
    CAUSES, so a Report-mode answer built on it contained interpretation no
    matter what the prompt asked for; and it is no longer the only such tool,
    because `cashier-report` now reads the cashier's day from the reception
    software's own report. Asking a prompt to suppress what the data already is
    was the wrong lever — the menu is."""
    offered = _tools(
        "report.search", "report-current", "cashier-report", "cashier-reconciliation",
        "financial-analysis", "trend-analysis", "integrity.missing-reports",
    )
    names = [t["name"] for t in modes.tools_for(modes.REPORT, offered)]
    assert "report.search" in names and "report-current" in names
    assert "cashier-report" in names, "Report mode must be able to read the cashier's day"
    assert "cashier-reconciliation" not in names
    assert "financial-analysis" not in names
    assert "trend-analysis" not in names
    assert "integrity.missing-reports" not in names


def test_the_cashier_report_and_the_reconciliation_are_not_the_same_report():
    """They answer different questions, so they are separate tools with
    separate menus. «گزارش صندوق» is what the till took; «تطبیق صندوق» is
    whether that matches what the day should have produced."""
    offered = _tools("cashier-report", "cashier-reconciliation")

    report_names = [t["name"] for t in modes.tools_for(modes.REPORT, offered)]
    analysis_names = [t["name"] for t in modes.tools_for(modes.ANALYSIS, offered)]

    assert report_names == ["cashier-report"]
    assert set(analysis_names) == {"cashier-report", "cashier-reconciliation"}


def test_deleted_cashier_actor_details_are_available_in_analysis():
    """Registering the detail source is not enough: the analysis menu is the
    capability ceiling, so omission here makes deletion actors unreachable."""
    offered = _tools("cashier-report", "cashier-deleted-transactions")

    report_names = [t["name"] for t in modes.tools_for(modes.REPORT, offered)]
    analysis_names = [t["name"] for t in modes.tools_for(modes.ANALYSIS, offered)]

    assert report_names == ["cashier-report"]
    assert set(analysis_names) == {"cashier-report", "cashier-deleted-transactions"}


def test_physician_workload_has_a_source_in_both_modes():
    """It had none. Both modes answered "which physicians were busiest?" by
    asking which date range the user meant — which implies the answer exists
    once you say. It did not, and no prompt could have produced it."""
    offered = _tools("physician-performance", "daily-summary")
    for mode in (modes.REPORT, modes.ANALYSIS):
        names = [t["name"] for t in modes.tools_for(mode, offered)]
        assert "physician-performance" in names, f"{mode.id} cannot answer a workload question"


def test_analysis_mode_can_open_the_reports_it_is_asked_to_compare():
    """It could not, before the three-mode separation: Analysis was defined as
    counts, and «سی‌تی و ام‌آرآی این بیمار را مقایسه کن» could not be answered
    at all. Comparing documents is analysis; it needs the documents."""
    offered = _tools("report.get", "report.history", "financial-analysis", "daily-summary")
    names = [t["name"] for t in modes.tools_for(modes.ANALYSIS, offered)]
    assert "financial-analysis" in names and "daily-summary" in names
    assert "report.get" in names and "report.history" in names


def test_the_calendar_is_on_a_menu_and_not_only_the_waiting_queue():
    """Registering a tool is not the same as offering it.

    `appointments.day` and `appointments.availability` existed, were registered,
    and were named in `scenarios.py` -- and the benchmark's appointment
    questions still came back as clarification requests, because the scenario
    layer does not narrow the menu and the MENU is what the model is shown. A
    tool that is on no mode's list cannot be picked, however well it is
    described.

    `appointments.list` is the waiting QUEUE (who is here now). It is not a
    substitute: it cannot say what is booked for a day, and it cannot say what
    is still free."""
    offered = _tools("appointments.list", "appointments.day", "appointments.availability")
    for mode in (modes.REPORT, modes.ANALYSIS):
        names = [t["name"] for t in modes.tools_for(mode, offered)]
        assert "appointments.day" in names, f"{mode.id} cannot see the booking diary"
        assert "appointments.availability" in names, f"{mode.id} cannot see a free slot"


def test_the_referral_source_and_the_staff_log_are_retrievable():
    """«کدام پزشک بیشترین ارجاع را داشت؟» and «هر کاربر امروز چند اقدام ثبت
    کرد؟» are counted facts plus a sort -- retrieval, on the same reading that
    puts `physician-performance` on the Report menu."""
    offered = _tools("marketing.referrers", "staff.activity", "daily-summary")
    for mode in (modes.REPORT, modes.ANALYSIS):
        names = [t["name"] for t in modes.tools_for(mode, offered)]
        assert "marketing.referrers" in names and "staff.activity" in names


def test_the_reconciling_and_auditing_tools_stay_out_of_reporting_mode():
    """Same rule that keeps `integrity.*` and `cashier-reconciliation` off that
    menu: Report retrieves what exists, it does not go looking for what is
    wrong. `appointments.vs-receptions` produces a no-show rate and
    `audit.name-changes` reads who edited a name after the fact -- both are
    findings about the records, not the records."""
    offered = _tools("appointments.vs-receptions", "audit.name-changes", "appointments.day")

    report_names = [t["name"] for t in modes.tools_for(modes.REPORT, offered)]
    analysis_names = [t["name"] for t in modes.tools_for(modes.ANALYSIS, offered)]

    assert report_names == ["appointments.day"]
    assert "appointments.vs-receptions" in analysis_names
    assert "audit.name-changes" in analysis_names


def test_every_scenario_the_router_can_choose_has_a_tool_on_some_menu():
    """The gap this catches is the one that cost a whole benchmark family: the
    router could route to `appointment`, `marketing`, `staff` and `audit`, the
    scenario named its preferred tools, and no mode offered any of them. A
    scenario the router can reach whose tools nothing shows is a dead end that
    looks, from the outside, exactly like a model that will not answer."""
    from reception_crm import scenarios
    from reception_crm.core.registry import ToolRegistry, default_registry

    offered = [ToolRegistry.describe(t) for t in default_registry().tools.values()]
    reachable = set()
    for mode in modes.all_modes():
        reachable.update(t["name"] for t in modes.tools_for(mode, offered))

    for scenario in scenarios.all_scenarios():
        preferred = set(getattr(scenario, "preferred_tools", ()) or ())
        registered = {name for name in preferred if name in default_registry().tools}
        if not registered:
            continue
        assert registered & reachable, (
            f"scenario '{scenario.id}' prefers {sorted(registered)}, "
            "and not one of them is offered by any mode"
        )


def test_a_new_report_tool_joins_reporting_mode_without_a_code_change():
    """The prefix is what makes the registry extensible in the small: adding
    `report.compare` should not also require editing this mode."""
    offered = _tools("report.compare", "financial-analysis")
    names = [t["name"] for t in modes.tools_for(modes.REPORT, offered)]
    assert names == ["report.compare"]


def test_executive_mode_does_not_narrow_because_it_must_read_widely():
    offered = _tools("report.search", "financial-analysis", "patients.search")
    assert modes.tools_for(modes.EXECUTIVE, offered) == offered


def test_narrowing_to_nothing_degrades_to_the_full_list():
    """A deployment without the local database offers no `report.*` at all.
    Reporting mode should then behave as a general assistant, not a dead one."""
    offered = _tools("trend-analysis", "financial-analysis")
    assert modes.tools_for(modes.REPORT, offered) == offered


def test_the_degrade_path_still_refuses_to_hand_a_read_only_mode_a_write():
    """The bug this was written for: `tools_for` returns the FULL list when
    narrowing leaves nothing, so at a site whose report tools were missing,
    Reporting mode was offered every write the principal could call. The menus
    said nothing, and the leak test passed, because on a complete registry that
    branch is never taken."""
    offered = [
        {"name": "trend-analysis", "safety": "read"},
        {"name": "appointments.schedule", "safety": "write", "requires_confirmation": True},
    ]
    names = [t["name"] for t in modes.tools_for(modes.REPORT, offered)]
    assert names == ["trend-analysis"]
    assert [t["name"] for t in modes.tools_for(modes.ANALYSIS, offered)] == ["trend-analysis"]


# --------------------------------------------------------------------------- #
# the ceiling
# --------------------------------------------------------------------------- #
def test_exactly_one_mode_may_change_anything():
    """The separation the product is built on, in one assertion. Report and
    Analysis are read-only; Executive Command is the single mode that is not."""
    changers = [m.id for m in modes.all_modes() if not m.read_only]
    assert changers == ["executive"]

    for mode in (modes.REPORT, modes.ANALYSIS):
        assert mode.read_only is True
        assert mode.can_act is False, (
            f"'{mode.id}' is read_only, so can_act must be False too — leaving it "
            "True describes a mode that may carry through a write it can never hold"
        )


def test_executive_command_is_permitted_to_act():
    """Owner instruction, 2026-08-22, superseding the propose-only v1 decision.

    This opens the MODE. It enables no operation: every write still passes the
    role policy, the per-operation switch in operations.json, the server's
    write flag, and the human confirmation gate."""
    assert modes.EXECUTIVE.can_act is True
    assert modes.EXECUTIVE.read_only is False


def test_no_write_tool_is_ever_offered_in_a_read_only_mode():
    """Checked against the REAL registry, so a tool added later that changes
    state fails here rather than in a clinic."""
    from reception_crm.core.registry import ToolRegistry

    registry = default_registry()
    offered = [ToolRegistry.describe(t) for t in registry.tools.values()]
    writes = [t["name"] for t in offered if not modes.is_read_only_tool(t)]
    assert writes, "this test is meaningless if the registry has no write tools"

    for mode in modes.all_modes():
        if not mode.read_only:
            continue
        names = [t["name"] for t in modes.tools_for(mode, offered)]
        leaked = [w for w in writes if w in names]
        assert not leaked, f"mode '{mode.id}' offers a write tool: {leaked}"


def test_every_registry_tool_declares_what_it_does_to_the_system():
    """`is_read_only_tool` treats an unlabelled tool as read-only, because every
    genuine read tool omits both fields. That default is only safe while no
    state-changing tool is unlabelled — which is what this checks."""
    from reception_crm.core.registry import ToolRegistry, requires_human_approval

    for tool in default_registry().tools.values():
        described = ToolRegistry.describe(tool)
        if requires_human_approval(tool):
            assert not modes.is_read_only_tool(described), (
                f"'{tool.name}' needs a human tap but reads as read-only to the "
                "mode filter, so a read-only mode would offer it"
            )


def test_a_prefix_never_admits_a_tool_that_needs_a_human_tap():
    """`report-` was written to pick up new report readers. It would just as
    happily pick up a future `report-delete`, and nobody would notice."""
    offered = [
        {"name": "report-viewer", "requires_confirmation": False},
        {"name": "report-delete", "requires_confirmation": True},
    ]
    names = [t["name"] for t in modes.tools_for(modes.REPORT, offered)]
    assert names == ["report-viewer"]


def test_a_write_named_explicitly_is_still_admitted():
    """The prefix rule is a guard against carelessness, not a ban. A mode that
    genuinely needs a write says so by name."""
    acting = modes.AgentMode(
        id="acting", label_fa="x", description_fa="x", prompt_file="mode_report.md",
        tools=("appointments.schedule",),
    )
    offered = [{"name": "appointments.schedule", "requires_confirmation": True}]
    assert modes.tools_for(acting, offered) == offered


# --------------------------------------------------------------------------- #
# the wire shape the phone renders
# --------------------------------------------------------------------------- #
def test_the_published_shape_carries_what_a_client_needs_to_render():
    for mode in modes.all_modes():
        published = mode.as_dict()
        assert published["id"] and published["labelFa"] and published["descriptionFa"]
        assert isinstance(published["canAct"], bool)
        assert isinstance(published["examplesFa"], list)
        # Nothing server-internal leaks into the menu.
        assert "tools" not in published and "prompt_file" not in published


def test_the_chat_store_and_the_registry_agree_on_what_a_mode_is():
    """Two lists of modes is how a mode ends up offered by /api/modes and then
    rejected when the conversation is saved."""
    from reception_crm.core import conversations

    for mode in modes.all_modes():
        assert conversations._mode(mode.id) == mode.id
    with pytest.raises(conversations.InvalidMode):
        conversations._mode("not-a-mode")
