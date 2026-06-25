# -*- coding: utf-8 -*-
"""Guard tests for the P0 agent-control permission gate (2026-06-23).

Pins the safety contract added in ``permissions.py`` +
``registry.AdapterRegistry.dispatch`` (see
``docs/reports/AGENT_CONTROL_ARCHITECTURE_REVIEW_2026-06-23.md`` Appendix B):

- The gate is INERT for the legacy / unscoped caller (no ``agent_mode``) — every
  current caller (voice executor, Test Control Server, direct bus.execute) stays
  byte-identical, and ``plan.needs_confirmation`` is ignored exactly as before.
- Enforcement (deny / confirm) activates ONLY under an explicit restrictive mode.
- The ``AIPACS_AGENT_PERMISSIONS`` kill switch restores byte-identical legacy
  dispatch (no gate at all).
- Unknown action handling is unchanged.

Pure Python + pydantic only — no PySide6 / GUI. Runs in the offscreen verify lane.
"""
from __future__ import annotations

from modules.EchoMind.secretary import permissions as P
from modules.EchoMind.secretary import registry as registry_mod
from modules.EchoMind.secretary.command_envelope import CommandPlan
from modules.EchoMind.secretary.registry import AdapterRegistry


class _FakeAdapter:
    """Records calls so we can assert a denied / unconfirmed action never ran."""

    def __init__(self):
        self.calls: list[str] = []

    def read_thing(self, plan, state):
        self.calls.append("read_thing")
        return {"ok": True, "data": {"value": 1}}

    def send_to_server(self, plan, state):
        self.calls.append("send_to_server")
        return {"ok": True, "message": "sent"}

    def nuke(self, plan, state):
        self.calls.append("nuke")
        return {"ok": True, "message": "boom"}


def _registry():
    reg = AdapterRegistry()
    fake = _FakeAdapter()
    reg.register("fake", fake, actions={
        "get_active_tab":       "read_thing",     # READ_ONLY
        "send_report_to_pacs":  "send_to_server",  # SERVER_WRITE
        "close_patient_tab":    "nuke",           # DESTRUCTIVE
    })
    return reg, fake


# ── permissions.decide (pure policy) ──────────────────────────────────────────

def test_classify_known_and_unknown():
    assert P.classify("get_active_tab") == P.READ_ONLY
    assert P.classify("send_report_to_pacs") == P.SERVER_WRITE
    assert P.classify("close_patient_tab") == P.DESTRUCTIVE
    # known-but-unmapped action → conservative UI_NAV default
    assert P.classify("some_future_action") == P.UI_NAV


def test_unrestricted_is_permissive_and_ignores_needs_confirmation():
    # Legacy/unscoped: everything allowed, no confirmation — even destructive,
    # even when the plan asks for confirmation (the legacy path ignored it).
    for action in ("get_active_tab", "send_report_to_pacs", "close_patient_tab"):
        d = P.decide(action, mode=None, plan_needs_confirmation=True)
        assert d.allowed and not d.requires_confirmation


def test_read_only_mode_denies_writes():
    assert P.decide("get_active_tab", mode=P.READ_ONLY_MODE).allowed
    d = P.decide("send_report_to_pacs", mode=P.READ_ONLY_MODE)
    assert not d.allowed and d.error_code == "PERMISSION_DENIED"
    assert not P.decide("close_patient_tab", mode=P.READ_ONLY_MODE).allowed


def test_assistant_confirms_server_write_and_denies_destructive():
    d = P.decide("send_report_to_pacs", mode=P.ASSISTANT)
    assert d.allowed and d.requires_confirmation and d.error_code == "CONFIRM_REQUIRED"
    # confirmed clears it
    d = P.decide("send_report_to_pacs", mode=P.ASSISTANT, confirmed=True)
    assert d.allowed and not d.requires_confirmation
    # an assistant may not run a destructive action at all
    assert not P.decide("close_patient_tab", mode=P.ASSISTANT).allowed


def test_qa_mode_allows_destructive_without_confirmation():
    d = P.decide("close_patient_tab", mode=P.QA)
    assert d.allowed and not d.requires_confirmation
    # qa is automated (no human in the loop): a stray plan needs_confirmation
    # must NOT pause the harness.
    d = P.decide("send_report_to_pacs", mode=P.QA, plan_needs_confirmation=True)
    assert d.allowed and not d.requires_confirmation


def test_unknown_explicit_mode_fails_closed():
    assert P.normalize_mode("typo_mode") == P.READ_ONLY_MODE
    assert not P.decide("send_report_to_pacs", mode="typo_mode").allowed
    # empty / None stays the legacy/unscoped (permissive) case
    assert P.normalize_mode("") == P.UNRESTRICTED
    assert P.normalize_mode(None) == P.UNRESTRICTED


# ── registry.dispatch integration ─────────────────────────────────────────────

def test_dispatch_inert_without_mode(monkeypatch):
    monkeypatch.setattr(registry_mod, "_PERMISSIONS_ENABLED", True)
    reg, fake = _registry()
    # No agent_mode → server-write runs, even with needs_confirmation set.
    r = reg.dispatch(CommandPlan(action="send_report_to_pacs", needs_confirmation=True), {})
    assert r.ok and "send_to_server" in fake.calls


def test_dispatch_denied_under_read_only(monkeypatch):
    monkeypatch.setattr(registry_mod, "_PERMISSIONS_ENABLED", True)
    reg, fake = _registry()
    r = reg.dispatch(CommandPlan(action="send_report_to_pacs"), {"agent_mode": "read_only"})
    assert not r.ok and r.error_code == "PERMISSION_DENIED"
    assert "send_to_server" not in fake.calls  # method must NOT have run


def test_dispatch_confirm_required_under_assistant(monkeypatch):
    monkeypatch.setattr(registry_mod, "_PERMISSIONS_ENABLED", True)
    reg, fake = _registry()
    r = reg.dispatch(CommandPlan(action="send_report_to_pacs"), {"agent_mode": "assistant"})
    assert not r.ok and r.error_code == "CONFIRM_REQUIRED"
    assert "send_to_server" not in fake.calls
    # re-issued with confirmed=True → runs
    r = reg.dispatch(
        CommandPlan(action="send_report_to_pacs"),
        {"agent_mode": "assistant", "confirmed": True},
    )
    assert r.ok and "send_to_server" in fake.calls


def test_dispatch_flag_off_is_byte_identical_legacy(monkeypatch):
    monkeypatch.setattr(registry_mod, "_PERMISSIONS_ENABLED", False)
    reg, fake = _registry()
    # Gate off: even a destructive action under read_only mode runs (legacy).
    r = reg.dispatch(CommandPlan(action="close_patient_tab"), {"agent_mode": "read_only"})
    assert r.ok and "nuke" in fake.calls


def test_dispatch_unknown_action_unchanged(monkeypatch):
    monkeypatch.setattr(registry_mod, "_PERMISSIONS_ENABLED", True)
    reg, _ = _registry()
    r = reg.dispatch(CommandPlan(action="does_not_exist"), {"agent_mode": "read_only"})
    assert not r.ok and r.error_code == "UNKNOWN_ACTION"
