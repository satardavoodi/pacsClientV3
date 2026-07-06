from __future__ import annotations

import ast
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]


SECRETARY_WIDGET = (
    REPO
    / "PacsClient"
    / "pacs"
    / "workstation_ui"
    / "home_ui"
    / "secretary_button_widget.py"
)
ORCHESTRATOR = REPO / "modules" / "EchoMind" / "secretary" / "orchestrator.py"
AGENT = REPO / "modules" / "EchoMind" / "secretary" / "brain" / "agent.py"
EXECUTOR = REPO / "modules" / "EchoMind" / "secretary" / "executor.py"
TEST_SERVER = REPO / "modules" / "EchoMind" / "secretary" / "test_server.py"
MCP_SERVER = REPO / "tools" / "testing" / "aipacs_control_mcp" / "server.py"
DOC = REPO / "docs" / "agent_control" / "secretary_mcp_unified_entrypoint.md"
CLINICAL_PIPELINE_DOC = (
    REPO / "docs" / "agent_control" / "clinical_agent_validation_pipeline.md"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _mcp_tool_names() -> set[str]:
    mod = ast.parse(_read(MCP_SERVER))
    names: set[str] = set()
    for node in mod.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "tool"
            ):
                names.add(node.name)
    return names


def test_voice_commands_enter_through_secretary_transcription_and_orchestrator():
    src = _read(SECRETARY_WIDGET)
    assert "self._stt_router.transcribe_files(" in src
    assert "self._secretary_orchestrator.handle(payload)" in src
    assert '"Phase 2: Sending transcript + module catalog to GPT."' in src


def test_secretary_llm_brain_uses_echomind_gapgpt_connection():
    orchestrator = _read(ORCHESTRATOR)
    agent = _read(AGENT)
    assert "from .brain.agent import AgentBrain" in orchestrator
    assert "self._brain = AgentBrain(" in orchestrator
    assert "from modules.EchoMind.llm_client import gapgpt_chat" in agent
    assert "gapgpt_chat(" in agent


def test_secretary_executor_routes_non_home_actions_to_shared_command_bus():
    src = _read(EXECUTOR)
    assert "def _try_command_bus(" in src
    assert "CommandPlan(" in src
    assert "bus.execute(cmd_plan, bus_state)" in src
    assert "agent_mode" in src


def test_mcp_server_is_transport_not_duplicate_secretary_brain():
    src = _read(MCP_SERVER)
    assert "FastMCP" in src
    assert "AipacsControlClient" in src
    assert "AgentBrain" not in src
    assert "SecretaryOrchestrator" not in src
    assert {"raw_command", "open_patient", "query_viewport_state"} <= _mcp_tool_names()


def test_in_app_test_server_dispatches_mcp_requests_to_same_command_bus():
    src = _read(TEST_SERVER)
    assert "external transport for the CommandBus" in src
    assert "plan = CommandPlan(action=action, entities=dict(entities))" in src
    assert 'mode = str(req.get("mode") or "qa").strip() or "qa"' in src
    assert 'result = bus.execute(plan, {"agent_mode": mode})' in src


def test_unified_entrypoint_doc_records_the_architecture_rule():
    src = _read(DOC)
    flat = _one_line(src)
    assert "Secretary EchoMind is the primary user-command entry point." in src
    assert "MCP server = external transport" in src
    assert "Do not build two independent agents" in src
    assert "There must be one agentic app-control structure" in src
    assert "intent -> EchoMind reasoning -> CommandPlan -> CommandBus -> adapter -> app" in src
    assert "They are not a second product agent." in flat
    assert "same CommandBus" in src


def test_clinical_runner_is_documented_as_validation_not_product_agent_path():
    src = _read(CLINICAL_PIPELINE_DOC)
    assert "This script is a validation harness, not a second product agent." in src
    assert "single EchoMind app-control spine" in src
    assert "It must not become a parallel command system." in src
    assert "must be promoted into a CommandBus action and adapter" in src
