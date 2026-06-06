"""Guards for the orchestrator→CommandBus bridge (2026-06-06).

Closes the central gap from docs/reports/SECRETARY_ECHOMIND_PIPELINE_REVIEW_2026-06-06.md:
the voice/text assistant was hard-capped at 9 home-panel actions while the
24-action CommandBus (modules / viewer / download control) was reachable only
from the test server. Contract pinned here:

  1. validator accepts the bus-bridged actions (and still rejects unknown +
     the destructive ``close_patient_tab``);
  2. SecretaryExecutor routes non-home actions to the bus and converts the
     CommandResult; home actions never touch the bus; env kill-switch works;
  3. the rule parser maps "open <module>" to ``open_module`` instead of the
     old open_patient misparse — while "open patient 123" is untouched;
  4. bus_factory's ``enable_viewer_write`` registers the safe subset only;
  5. the orchestrator auto-derives a bus getter from the home widget.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.EchoMind.secretary.executor import SecretaryExecutor  # noqa: E402
from modules.EchoMind.secretary.parser_rules import parse_command_rule  # noqa: E402
from modules.EchoMind.secretary.validator import (  # noqa: E402
    _BUS_ALLOWED_ACTIONS,
    validate_plan,
)


def _plan(action: str, entities: dict | None = None) -> dict:
    return {
        "action": action,
        "entities": entities or {},
        "confidence": 0.9,
        "needs_confirmation": False,
        "reason": "test",
    }


# ── 1. validator ──────────────────────────────────────────────────────────
def test_validator_accepts_bus_actions():
    for action in ("open_module", "toggle_eagle", "open_mpr", "change_series",
                   "list_downloads", "get_active_series", "switch_tab"):
        normalized, errors = validate_plan(_plan(action, {"module": "mpr"}))
        assert not errors, (action, [e.to_dict() for e in errors])
        assert normalized is not None


def test_validator_still_rejects_unknown_and_destructive():
    for action in ("close_patient_tab", "fly_to_moon", "delete_everything"):
        _, errors = validate_plan(_plan(action))
        assert errors, action
        assert action not in _BUS_ALLOWED_ACTIONS


def test_validator_home_actions_unchanged():
    # open_patient still requires confirmation + code (legacy strictness)
    _, errors = validate_plan(_plan("open_patient", {"patient_code": "123"}))
    assert any(e.field == "needs_confirmation" for e in errors)
    normalized, errors = validate_plan({
        "action": "open_patient",
        "entities": {"patient_code": "123"},
        "confidence": 0.9,
        "needs_confirmation": True,
        "reason": "test",
    })
    assert not errors and normalized is not None


# ── 2. executor bus routing ───────────────────────────────────────────────
class _FakeResult:
    def __init__(self, action):
        self.ok = True
        self.action = action
        self.message = "done"
        self.data = {"module": "mpr"}
        self.error_code = None


class _FakeRegistry:
    def __init__(self, actions):
        self._actions = set(actions)

    def has_action(self, name):
        return name in self._actions


class _FakeBus:
    def __init__(self, actions):
        self.registry = _FakeRegistry(actions)
        self.executed = []

    def execute(self, plan, state=None):
        self.executed.append(plan)
        return _FakeResult(plan.action)


class _UnavailableAdapter:
    def is_available(self):
        return False


def test_executor_routes_unknown_action_to_bus():
    bus = _FakeBus({"open_mpr", "toggle_eagle"})
    ex = SecretaryExecutor(_UnavailableAdapter(), command_bus_getter=lambda: bus)
    result = ex.execute(_plan("open_mpr"), state={})
    assert result["ok"] is True and result["action"] == "open_mpr"
    assert len(bus.executed) == 1 and bus.executed[0].action == "open_mpr"


def test_executor_falls_back_without_bus_or_action():
    ex = SecretaryExecutor(_UnavailableAdapter(), command_bus_getter=lambda: None)
    assert ex.execute(_plan("open_mpr"), state={})["error_code"] == "UNSUPPORTED_ACTION"
    bus = _FakeBus({"something_else"})
    ex2 = SecretaryExecutor(_UnavailableAdapter(), command_bus_getter=lambda: bus)
    assert ex2.execute(_plan("open_mpr"), state={})["error_code"] == "UNSUPPORTED_ACTION"
    assert not bus.executed


def test_executor_home_actions_never_touch_bus():
    bus = _FakeBus({"open_mpr", "list_patients"})  # even if bus claims it
    ex = SecretaryExecutor(_UnavailableAdapter(), command_bus_getter=lambda: bus)
    result = ex.execute(_plan("list_patients"), state={})
    # handled by the home executor (adapter unavailable → NO_HOME_WIDGET)
    assert result["error_code"] == "NO_HOME_WIDGET"
    assert not bus.executed


def test_executor_env_kill_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_BUS", "0")
    bus = _FakeBus({"open_mpr"})
    ex = SecretaryExecutor(_UnavailableAdapter(), command_bus_getter=lambda: bus)
    assert ex.execute(_plan("open_mpr"), state={})["error_code"] == "UNSUPPORTED_ACTION"
    assert not bus.executed


# ── 3. rule parser module names ───────────────────────────────────────────
def test_parser_open_module_names():
    cases = {
        "open echomind": "echomind",
        "open echo mind please": "echomind",
        "open eagle eye": "eagle_ai",
        "open eagleeye": "eagle_ai",
        "open mpr": "mpr",
        "open the report module": "printing",
        "open printing": "printing",
        "open education": "education",
    }
    for text, module in cases.items():
        plan = parse_command_rule(text)
        assert plan is not None, text
        assert plan["action"] == "open_module", (text, plan)
        assert plan["entities"].get("module") == module, (text, plan)
        assert plan["needs_confirmation"] is False


def test_parser_open_patient_untouched():
    plan = parse_command_rule("open patient id 12345")
    assert plan is not None and plan["action"] == "open_patient"
    assert plan["entities"].get("patient_code") == "12345"
    assert plan["needs_confirmation"] is True
    # bare open with no code and no module name → still open_patient (legacy)
    plan2 = parse_command_rule("open the patient with this id")
    assert plan2 is not None and plan2["action"] == "open_patient"


# ── 4. bus_factory viewer-write subset ────────────────────────────────────
def test_bus_factory_viewer_write_safe_subset():
    from modules.EchoMind.secretary.bus_factory import build_command_bus

    bus = build_command_bus(
        get_active_patient_tab=lambda: None,
        get_main_tab_widget=lambda: None,
        enable_viewer_write=True,
    )
    actions = set(bus.actions())
    for a in ("change_series", "query_viewport_state", "switch_tab",
              "get_series_info", "change_layout"):
        assert a in actions, a
    assert "close_patient_tab" not in actions  # destructive → test-server only

    bus_off = build_command_bus(
        get_active_patient_tab=lambda: None,
        get_main_tab_widget=lambda: None,
    )
    assert "change_series" not in set(bus_off.actions())


# ── 5. orchestrator auto-getter ───────────────────────────────────────────
def test_orchestrator_derives_bus_from_home_widget():
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator

    class _HW:  # minimal home-widget stand-in
        command_bus = _FakeBus({"open_mpr"})

    orch = SecretaryOrchestrator(home_widget=_HW())
    result = orch.executor.execute(_plan("open_mpr"), state={})
    assert result["ok"] is True and result["action"] == "open_mpr"


def test_parser_llm_allowed_actions_superset():
    from modules.EchoMind.secretary.parser_llm import _ALLOWED_ACTIONS

    assert {"list_patients", "open_patient", "download_patient",
            "open_module", "toggle_eagle", "change_series"} <= set(_ALLOWED_ACTIONS)


def test_run_plan_bus_results_do_not_poison_patient_context():
    """A successful open_module must NOT overwrite state['last_patient']."""
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator

    class _HW:
        command_bus = _FakeBus({"open_module"})

    orch = SecretaryOrchestrator(home_widget=_HW())
    state = {"pending": None, "last_patient": {"patient_id": "42"}, "last_list": []}
    result = orch._run_plan(_plan("open_module", {"module": "mpr"}), state, confirmed=False)
    assert result["ok"] is True
    assert state["last_patient"] == {"patient_id": "42"}  # untouched
    assert state["pending"] is None
    # module-context tracking (phase 2)
    assert state.get("last_module") == "mpr"


# ── phase 2: reporting workflow + slice scroll ────────────────────────────
def test_validator_accepts_phase2_actions():
    for action in ("start_report", "transcribe_voice", "generate_report",
                   "send_report_to_pacs", "scroll_slices"):
        normalized, errors = validate_plan(_plan(action))
        assert not errors, (action, [e.to_dict() for e in errors])
        assert normalized is not None


def test_send_to_pacs_requires_secretary_confirmation():
    """The executor must gate send_report_to_pacs behind a confirm turn even
    though the bus registers it — and execute it once confirmed."""
    bus = _FakeBus({"send_report_to_pacs"})
    ex = SecretaryExecutor(_UnavailableAdapter(), command_bus_getter=lambda: bus)
    first = ex.execute(_plan("send_report_to_pacs"), state={})
    assert first["error_code"] == "CONFIRM_REQUIRED"
    assert not bus.executed  # nothing ran yet
    second = ex.execute(_plan("send_report_to_pacs"), state={}, confirmed=True)
    assert second["ok"] is True
    assert len(bus.executed) == 1


def test_parser_reporting_fast_paths():
    cases = {
        "send this patient's report to pacs": "send_report_to_pacs",
        "send the final report to reception": "send_report_to_pacs",
        "transcribe this voice report": "transcribe_voice",
        "generate the report": "generate_report",
        "start a report for this patient": "start_report",
    }
    for text, action in cases.items():
        plan = parse_command_rule(text)
        assert plan is not None, text
        assert plan["action"] == action, (text, plan)
    # send is flagged for confirmation at the parser level too
    assert parse_command_rule("send report to pacs")["needs_confirmation"] is True


def test_parser_scroll_stack_fast_paths():
    cases = {
        "scroll through this series": "next",
        "stack this series": "next",
        "previous slice": "previous",
        "scroll back": "previous",
        "scroll to the last image": "last",
    }
    for text, direction in cases.items():
        plan = parse_command_rule(text)
        assert plan is not None, text
        assert plan["action"] == "scroll_slices", (text, plan)
        assert plan["entities"].get("direction") == direction, (text, plan)


def test_parser_open_report_module_still_wins_over_reporting():
    # "open the report module" must stay a module open, not start_report
    plan = parse_command_rule("open the report module")
    assert plan is not None and plan["action"] == "open_module"
    assert plan["entities"].get("module") == "printing"


def test_bus_factory_registers_echomind_and_scroll():
    from modules.EchoMind.secretary.bus_factory import build_command_bus

    bus = build_command_bus(
        get_active_patient_tab=lambda: None,
        get_main_tab_widget=lambda: None,
        enable_viewer_write=True,
    )
    actions = set(bus.actions())
    for a in ("start_report", "transcribe_voice", "generate_report",
              "send_report_to_pacs", "scroll_slices"):
        assert a in actions, a


def test_echomind_adapter_typed_errors_without_tab():
    from modules.EchoMind.secretary.adapters.echomind_command_adapter import (
        EchoMindCommandAdapter,
    )
    from modules.EchoMind.secretary.command_envelope import CommandPlan

    adapter = EchoMindCommandAdapter(get_active_patient_tab=lambda: None)
    for method in ("start_report", "transcribe_voice",
                   "generate_report", "send_report_to_pacs"):
        result = getattr(adapter, method)(CommandPlan(action=method), {})
        assert result.ok is False and result.error_code == "NO_ACTIVE_TAB", method


def test_scroll_slices_clamps_and_uses_set_slice():
    from modules.EchoMind.secretary.adapters.viewer_write_adapter import (
        ViewerWriteCommandAdapter,
    )
    from modules.EchoMind.secretary.command_envelope import CommandPlan

    calls = []

    class _Slider:
        def value(self):
            return 8

    class _Vtk:
        slider = _Slider()

        def get_count_of_slices(self):
            return 10

        def set_slice(self, idx):
            calls.append(idx)

    class _Node:
        vtk_widget = _Vtk()

    class _Tab:
        lst_nodes_viewer = [_Node()]

    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: _Tab())
    r = adapter.scroll_slices(CommandPlan(action="scroll_slices",
                                          entities={"delta": 5}), {})
    assert r.ok is True and calls == [9]  # clamped to last index
    r2 = adapter.scroll_slices(CommandPlan(action="scroll_slices",
                                           entities={"direction": "first"}), {})
    assert r2.ok is True and calls[-1] == 0
