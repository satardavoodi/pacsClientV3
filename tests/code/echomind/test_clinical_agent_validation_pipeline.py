from __future__ import annotations

import ast
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "tools" / "testing" / "aipacs_control_mcp" / "clinical_agent_validation.py"
SMOOTH_DEMO = REPO / "tools" / "testing" / "aipacs_control_mcp" / "smooth_visible_agent_demo.py"
SCENARIO = (
    REPO / "tools" / "testing" / "aipacs_control_mcp"
    / "scenarios" / "clinical_agent_validation.default.json"
)
UI_PROBE = REPO / "tools" / "testing" / "aipacs_control_mcp" / "ui_probe.py"


def test_clinical_runner_has_required_workflow_methods():
    mod = ast.parse(RUNNER.read_text(encoding="utf-8"))
    cls = next(
        node for node in mod.body
        if isinstance(node, ast.ClassDef) and node.name == "ClinicalAgentValidation"
    )
    methods = {
        node.name for node in cls.body
        if isinstance(node, ast.FunctionDef)
    }
    assert {
        "run_patient_list",
        "run_modality_switch_and_search",
        "run_open_and_load",
        "run_stack_ocr_measurement",
        "coordinate_measurement",
        "choose_patient",
        "choose_series",
        "choose_slice_index",
        "decide_measurement_strategy",
        "commandbus_measurement",
        "write_markdown",
    } <= methods


def test_patient_selection_filters_mixed_modality_rows_before_calling_gpt():
    src = RUNNER.read_text(encoding="utf-8")
    assert "def _rows_with_modality(" in src
    assert "candidate_rows = _rows_with_modality(rows, target_modality)" in src
    assert "candidate_rows[: self.brain.max_rows]" in src
    assert "selected = next((row for row in candidate_rows" in src
    assert '"raw_count": len(rows)' in src


def test_runner_declares_external_gpt_brain_adapter():
    mod = ast.parse(RUNNER.read_text(encoding="utf-8"))
    classes = {
        node.name for node in mod.body
        if isinstance(node, ast.ClassDef)
    }
    assert "ExternalGPTBrain" in classes


def test_default_scenario_declares_clinical_modalities_brain_and_measurement_mode():
    cfg = json.loads(SCENARIO.read_text(encoding="utf-8"))
    assert cfg["initial_modality"] == "MRI"
    assert cfg["target_modality"] == "CT"
    assert cfg["modality_aliases"]["MRI"] == "MR"
    assert cfg["external_brain"]["enabled"] is True
    assert cfg["external_brain"]["required"] is True
    assert cfg["external_brain"]["allow_local_fallback"] is False
    assert cfg["external_brain"]["backend"] == "echomind_active_company_gapgpt"
    assert cfg["measurement"]["mode"] == "commandbus"


def test_ui_probe_persists_full_command_reply_for_code_validation():
    src = UI_PROBE.read_text(encoding="utf-8")
    assert '"reply": reply' in src
    assert '"message": reply.get("message")' in src
    assert "agent_artifacts" in src
    assert "shutil.copy2" in src


def test_smooth_visible_demo_focuses_once_not_per_command():
    src = SMOOTH_DEMO.read_text(encoding="utf-8")
    assert "def focus_once" in src
    assert "focus_once(maximize=False)" in src
    assert "SetForegroundWindow" in src
    assert "def send(" in src
    assert "--launch-app" in src
    assert "--stop-existing" in src
    assert "--monitor" in src
    send_body = src.split("def send(", 1)[1].split("def wait_for_series", 1)[0]
    assert "focus_once" not in send_body


def test_agent_artifacts_are_routed_to_echomind_user_data():
    runner_src = RUNNER.read_text(encoding="utf-8")
    demo_src = SMOOTH_DEMO.read_text(encoding="utf-8")
    for src in (runner_src, demo_src):
        assert "ECHOMIND_DIR" in src
        assert '"agent_runs"' in src
        assert "conversation.jsonl" in src
    assert '"clinical_validation"' in runner_src
    assert '"smooth_visible_demo"' in demo_src


def test_clinical_runner_routes_measurement_through_commandbus_tools():
    src = RUNNER.read_text(encoding="utf-8")
    assert '"get_viewport_context"' in src
    assert '"capture_viewport"' in src
    assert '"measure_distance"' in src
    assert '"get_measurements"' in src
    assert 'self.brain.decide("decide_measurement_points"' in src


def test_secretary_artifacts_dir_uses_echomind_agent_artifacts():
    path = REPO / "modules" / "EchoMind" / "secretary" / "background" / "verification.py"
    src = path.read_text(encoding="utf-8")
    assert "ECHOMIND_DIR" in src
    assert '"agent_artifacts"' in src
