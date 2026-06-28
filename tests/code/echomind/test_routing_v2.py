"""Guard tests for the command-routing v2 fix (web vs patient search).

Background: a correctly-transcribed "search this on the internet" voice command
executed a PATIENT-LIST search. Root cause + design:
  docs/reports/SECRETARY_ECHOMIND_COMMAND_ROUTING_REVIEW_2026-06-28.md
  docs/agent_control/command_routing_rules.md

Everything here is behind the AIPACS_SECRETARY_ROUTING_V2 flag (default OFF). These
tests pin BOTH states: flag-off must be byte-identical legacy behaviour; flag-on
must route internet searches to web_search and never silently fall back to a
patient action.

Offscreen-safe: pure Python, no Qt / VTK / network.
"""
from __future__ import annotations

import pytest

from modules.EchoMind.secretary import config as cfg
from modules.EchoMind.secretary import parser_rules
from modules.EchoMind.secretary.brain import router as brain_router
from modules.EchoMind.secretary.brain import agent as brain_agent
from modules.EchoMind.secretary import orchestrator as orch_mod
from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator


# ── config / prompt selection ────────────────────────────────────────────────

def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("AIPACS_SECRETARY_ROUTING_V2", raising=False)
    assert cfg.routing_v2_enabled() is False
    assert cfg.get_phase1_prompt_file() == cfg.PHASE1_PROMPT_FILE


def test_flag_on_selects_v2_prompt(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    assert cfg.routing_v2_enabled() is True
    assert cfg.PHASE1_PROMPT_FILE_V2.exists()
    assert cfg.get_phase1_prompt_file() == cfg.PHASE1_PROMPT_FILE_V2


def test_v2_prompt_has_web_routing_and_no_substitution():
    text = cfg.PHASE1_PROMPT_FILE_V2.read_text(encoding="utf-8")
    assert "web_browser" in text
    assert "internet" in text.lower()
    assert "education" in text.lower()
    # must explicitly forbid silently demoting to the patient list
    assert "do not substitute" in text.lower()


def test_router_prompt_switches_by_flag(monkeypatch):
    # ON → v2 (mentions web_browser); OFF → legacy (no web_browser row)
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    assert "web_browser" in brain_router._load_phase1_prompt()
    monkeypatch.delenv("AIPACS_SECRETARY_ROUTING_V2", raising=False)
    assert "web_browser" not in brain_router._load_phase1_prompt()


# ── Phase-2 planner prompt override ──────────────────────────────────────────

def test_phase2_prefix_included_when_on(monkeypatch):
    monkeypatch.setattr(brain_agent, "get_llm_backend", lambda: "gapgpt")
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    sp = brain_agent._phase2_system_prompt()
    assert "ROUTING-V2 OVERRIDE RULES" in sp
    assert "NO WRONG-DOMAIN SUBSTITUTION" in sp
    # the legacy body is still present (prefix is layered, not a replacement)
    assert "Action Planner" in sp


def test_phase2_prefix_absent_when_off(monkeypatch):
    monkeypatch.setattr(brain_agent, "get_llm_backend", lambda: "gapgpt")
    monkeypatch.delenv("AIPACS_SECRETARY_ROUTING_V2", raising=False)
    sp = brain_agent._phase2_system_prompt()
    assert "ROUTING-V2 OVERRIDE RULES" not in sp


# ── Deterministic rule parser (offline fallback) ─────────────────────────────

def test_rule_parser_web_search_english_on(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    plan = parser_rules.parse_command_rule("search this word on the internet")
    assert plan is not None and plan["action"] == "web_search"
    assert plan["entities"]["query"].strip().lower() == "this word"


def test_rule_parser_web_search_persian_on(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    # the exact live-logged failing command (2026-06-27)
    plan = parser_rules.parse_command_rule("constipation رو روی اینترنت برام سرچ کن")
    assert plan is not None and plan["action"] == "web_search"
    assert "constipation" in plan["entities"]["query"].lower()


def test_rule_parser_web_search_off_is_legacy_none(monkeypatch):
    # With the flag off these phrasings are unmapped by the rule parser (legacy).
    monkeypatch.delenv("AIPACS_SECRETARY_ROUTING_V2", raising=False)
    assert parser_rules.parse_command_rule("search this word on the internet") is None
    assert parser_rules.parse_command_rule(
        "constipation رو روی اینترنت برام سرچ کن") is None


def test_rule_parser_patient_paths_unharmed_with_v2_on(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    # patient list still routes to list_patients (no web object)
    pl = parser_rules.parse_command_rule("show today's patients")
    assert pl is not None and pl["action"] == "list_patients"
    # existing google fast-path still web_search
    g = parser_rules.parse_command_rule("google rotator cuff tear")
    assert g is not None and g["action"] == "web_search"


# ── Orchestrator: clarify-don't-guess + route trace ──────────────────────────

class _FakeSession:
    """Captures SessionLog.add(...) calls without touching disk."""
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
    # never write audit rows to a DB during the test
    monkeypatch.setattr(orch_mod.audit, "log_start", lambda **k: None)
    monkeypatch.setattr(orch_mod.audit, "log_end", lambda **k: None)
    return orch


def test_unknown_action_triggers_clarify_when_on(monkeypatch):
    monkeypatch.setenv("AIPACS_SECRETARY_ROUTING_V2", "1")
    orch = _make_orch(monkeypatch)
    monkeypatch.setattr(orch, "_parse_plan", lambda cmd, memory_context="": {
        "action": "unknown", "entities": {}, "confidence": 0.3,
        "needs_confirmation": False, "reason": "internet search not supported here"})
    res = orch.handle({"text": "search this on the internet", "session_id": "t1"})
    assert res["action"] == "needs_clarification"
    assert res["error_code"] == "NEEDS_CLARIFICATION"


def test_unknown_action_not_clarify_when_off(monkeypatch):
    monkeypatch.delenv("AIPACS_SECRETARY_ROUTING_V2", raising=False)
    orch = _make_orch(monkeypatch)
    monkeypatch.setattr(orch, "_parse_plan", lambda cmd, memory_context="": {
        "action": "unknown", "entities": {}, "confidence": 0.3,
        "needs_confirmation": False, "reason": "x"})
    res = orch.handle({"text": "search this on the internet", "session_id": "t2"})
    # legacy: "unknown" is not an allowed action → validation failure, NOT clarify
    assert res["error_code"] != "NEEDS_CLARIFICATION"


def test_route_trace_is_logged(monkeypatch):
    _FakeSession.instances.clear()
    monkeypatch.setattr(orch_mod, "SessionLog", _FakeSession)
    orch = _make_orch(monkeypatch)

    def fake_parse(cmd, memory_context=""):
        orch._last_route = {"modules": ["homepage"], "reason": "test routing"}
        return None  # unparsed; route trace must still be recorded

    monkeypatch.setattr(orch, "_parse_plan", fake_parse)
    orch.handle({"text": "whatever", "session_id": "t3"})
    sess = _FakeSession.instances[-1]
    routes = [v for (k, v) in sess.entries if k == "route"]
    assert routes and routes[0]["modules"] == ["homepage"]
