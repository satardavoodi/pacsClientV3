"""Guard tests for command-routing v2 + compound workflows (both DEFAULT-ON 2026-06-28)."""
from __future__ import annotations

import pytest

from modules.EchoMind.secretary import config as cfg
from modules.EchoMind.secretary import parser_rules
from modules.EchoMind.secretary import prompt_context as pctx
from modules.EchoMind.secretary.brain import router as brain_router
from modules.EchoMind.secretary.brain import agent as brain_agent
from modules.EchoMind.secretary.brain import catalog_loader as catloader
from modules.EchoMind.secretary.brain.multistep import WORKFLOW_ACTION
from modules.EchoMind.secretary import orchestrator as orch_mod
from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator


def test_flag_default_on(monkeypatch):
    monkeypatch.delenv("AIPACS_SECRETARY_ROUTING_V2", raising=False)
    assert cfg.routing_v2_enabled() is True
    assert cfg.get_phase1_prompt_file() == cfg.PHASE1_PROMPT_FILE_V2


def test_flag_kill_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "0")
    assert cfg.routing_v2_enabled() is False
    assert cfg.get_phase1_prompt_file() == cfg.PHASE1_PROMPT_FILE


def test_v2_prompt_has_web_routing_and_no_substitution():
    text = cfg.PHASE1_PROMPT_FILE_V2.read_text(encoding="utf-8")
    assert "web_browser" in text
    assert "internet" in text.lower()
    assert "education" in text.lower()
    assert "do not substitute" in text.lower()


def test_router_prompt_switches_by_flag(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    assert "web_browser" in brain_router._load_phase1_prompt()
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "0")
    assert "web_browser" not in brain_router._load_phase1_prompt()


def test_phase2_prefix_included_when_on(monkeypatch):
    monkeypatch.setattr(brain_agent, "get_llm_backend", lambda: "gapgpt")
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    sp = brain_agent._phase2_system_prompt()
    assert "ROUTING-V2 OVERRIDE RULES" in sp
    assert "NO WRONG-DOMAIN SUBSTITUTION" in sp
    assert "Action Planner" in sp


def test_phase2_prefix_absent_when_off(monkeypatch):
    monkeypatch.setattr(brain_agent, "get_llm_backend", lambda: "gapgpt")
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "0")
    sp = brain_agent._phase2_system_prompt()
    assert "ROUTING-V2 OVERRIDE RULES" not in sp


def test_rule_parser_web_search_english_on(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    plan = parser_rules.parse_command_rule("search this word on the internet")
    assert plan is not None and plan["action"] == "web_search"
    assert plan["entities"]["query"].strip().lower() == "this word"


def test_rule_parser_web_search_persian_on(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    plan = parser_rules.parse_command_rule("constipation رو روی اینترنت برام سرچ کن")
    assert plan is not None and plan["action"] == "web_search"
    assert "constipation" in plan["entities"]["query"].lower()


def test_rule_parser_web_search_killswitch_is_legacy_none(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "0")
    assert parser_rules.parse_command_rule("search this word on the internet") is None
    assert parser_rules.parse_command_rule(
        "constipation رو روی اینترنت برام سرچ کن") is None


def test_rule_parser_patient_paths_unharmed(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    pl = parser_rules.parse_command_rule("show today's patients")
    assert pl is not None and pl["action"] == "list_patients"
    g = parser_rules.parse_command_rule("google rotator cuff tear")
    assert g is not None and g["action"] == "web_search"


class _FakeSession:
    instances: list = []

    def __init__(self, user_text: str = "", session_id=None):
        self.user_text = user_text
        self.entries: list = []
        _FakeSession.instances.append(self)

    def add(self, key, value):
        self.entries.append((key, value))

    def add_plan(self, p):
        self.add("plan", p)

    def add_result(self, r):
        self.add("result", r)

    def add_error(self, *a, **k):
        pass

    def add_repair(self, *a, **k):
        pass

    def close(self, result=None):
        self.add("close", result)


def _make_orch(monkeypatch):
    orch = SecretaryOrchestrator(home_widget=None, use_brain=False)
    monkeypatch.setattr(orch.adapter, "get_active_source", lambda: "local")
    monkeypatch.setattr(orch_mod.audit, "log_start", lambda **k: None)
    monkeypatch.setattr(orch_mod.audit, "log_end", lambda **k: None)
    monkeypatch.setattr(orch, "_get_memory_store_safe", lambda: None)
    return orch


_CMD = "constipation رو روی اینترنت سرچ کن"


def test_unknown_action_triggers_clarify_when_on(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    orch = _make_orch(monkeypatch)
    monkeypatch.setattr(orch, "_parse_plan", lambda cmd, memory_context="": {
        "action": "unknown", "entities": {}, "confidence": 0.3,
        "needs_confirmation": False, "reason": "internet search not supported here"})
    res = orch.handle({"text": _CMD, "session_id": "t1"})
    assert res["action"] == "needs_clarification"
    assert res["error_code"] == "NEEDS_CLARIFICATION"


def test_unknown_action_killswitch_no_clarify(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "0")
    orch = _make_orch(monkeypatch)
    monkeypatch.setattr(orch, "_parse_plan", lambda cmd, memory_context="": {
        "action": "unknown", "entities": {}, "confidence": 0.3,
        "needs_confirmation": False, "reason": "x"})
    res = orch.handle({"text": _CMD, "session_id": "t2"})
    assert res["error_code"] != "NEEDS_CLARIFICATION"


def test_route_trace_is_logged(monkeypatch):
    _FakeSession.instances.clear()
    monkeypatch.setattr(orch_mod, "SessionLog", _FakeSession)
    orch = _make_orch(monkeypatch)

    def fake_parse(cmd, memory_context=""):
        orch._last_route = {"modules": ["homepage"], "reason": "test routing"}
        return None

    monkeypatch.setattr(orch, "_parse_plan", fake_parse)
    orch.handle({"text": "zzz qqq", "session_id": "t3"})
    sess = _FakeSession.instances[-1]
    routes = [v for (k, v) in sess.entries if k == "route"]
    assert routes and routes[0]["modules"] == ["homepage"]


def test_single_shot_advertises_full_capabilities_when_on(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    ctx = pctx.build_prompt_context(language="en")
    assert "web_search" in ctx
    assert "browser_fill_field" in ctx
    assert "list_patients" in ctx


def test_single_shot_killswitch_only_patient(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "0")
    ctx = pctx.build_prompt_context(language="en")
    assert "web_search" not in ctx
    assert "list_patients" in ctx


def test_web_browser_doc_has_page_tools_when_on(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    doc = catloader.load_module_doc("web_browser")
    assert "web_search" in doc
    assert "browser_fill_field" in doc
    assert "browser_click" in doc


def test_web_browser_doc_killswitch_legacy(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "0")
    doc = catloader.load_module_doc("web_browser")
    assert "browser_fill_field" not in doc


def test_module_ids_exclude_v2_overlays():
    ids = catloader.list_available_module_ids()
    assert "web_browser" in ids
    assert "web_browser_v2" not in ids


def test_router_v2_prompt_has_topic_and_browser_rules():
    text = cfg.PHASE1_PROMPT_FILE_V2.read_text(encoding="utf-8")
    assert "MEDICAL TOPIC" in text
    assert "fill a field" in text.lower()


# ── Compound workflows (default-on) ──────────────────────────────────────────

def _two_step():
    return {"goal": "dl+open", "steps": [
        {"action": "download_patient", "entities": {"patient_code": "5"},
         "needs_confirmation": True},
        {"action": "open_patient", "entities": {"patient_code": "5"},
         "needs_confirmation": True}]}


def test_workflows_default_on_expands_multistep(monkeypatch):
    monkeypatch.delenv("AIPACS_SECRETARY_WORKFLOWS", raising=False)
    out = brain_agent._normalize_multistep(_two_step())
    assert out["action"] == WORKFLOW_ACTION
    assert len(out["steps"]) == 2


def test_workflows_kill_switch_collapses_to_first(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_WORKFLOWS", "0")
    out = brain_agent._normalize_multistep(_two_step())
    assert out["action"] == "download_patient"


def test_workflows_single_action_unaffected(monkeypatch):
    monkeypatch.delenv("AIPACS_SECRETARY_WORKFLOWS", raising=False)
    single = {"action": "open_patient", "entities": {"patient_code": "5"}}
    out = brain_agent._normalize_multistep(single)
    assert out["action"] == "open_patient"
