"""Pydantic envelope round-trip + TypedDict compat (Phase 1 acceptance)."""
from __future__ import annotations

import pytest

from modules.EchoMind.secretary import (
    CommandPlan, CommandRequest, CommandResult,
)


# ── CommandRequest ──────────────────────────────────────────────────────
def test_command_request_default_construction():
    req = CommandRequest()
    assert req.text == ""
    assert req.language == "auto"
    assert req.source_scope == "active_tab"
    assert req.session_id is None


def test_command_request_typeddict_round_trip_preserves_extras():
    td = {
        "text": "open patient 43743",
        "language": "en",
        "session_id": "sess-1",
        "source_scope": "server",
        "stt_route": "native",
        "stt_fallback": True,
        # legacy extra not in our schema:
        "progress_cb": None,
    }
    req = CommandRequest.from_typeddict(td)
    assert req.text == "open patient 43743"
    assert req.source_scope == "server"
    out = req.to_typeddict()
    assert out["progress_cb"] is None, "extras should survive round-trip"


def test_command_request_string_shortcut():
    # the bus accepts a bare string; envelope direct construction
    # is the same thing.
    req = CommandRequest(text="hi")
    assert req.text == "hi"


# ── CommandPlan ─────────────────────────────────────────────────────────
def test_command_plan_minimal():
    plan = CommandPlan(action="open_patient")
    assert plan.action == "open_patient"
    assert plan.entities == {}
    assert plan.confidence == 1.0
    assert plan.needs_confirmation is False


def test_command_plan_from_legacy_action_plan():
    legacy = {
        "action": "open_patient",
        "entities": {"patient_id": "43743"},
        "confidence": 0.87,
        "needs_confirmation": False,
        "reason": "user typed it",
        "source_module": "patient_viewer",
    }
    plan = CommandPlan.from_typeddict(legacy)
    assert plan is not None
    assert plan.source_module == "patient_viewer"
    assert plan.entities["patient_id"] == "43743"


def test_command_plan_from_none_returns_none():
    assert CommandPlan.from_typeddict(None) is None


# ── CommandResult ───────────────────────────────────────────────────────
def test_command_result_required_fields():
    result = CommandResult(ok=True, action="list_patients")
    assert result.ok is True
    assert result.action == "list_patients"
    assert result.elapsed_ms is None  # filled in by CommandBus
    assert result.data is None


def test_command_result_serializes_for_json():
    result = CommandResult(
        ok=True, action="open_patient",
        data={"patient_id": "43743"},
        elapsed_ms=152.4,
    )
    out = result.to_typeddict()
    assert out["ok"] is True
    assert out["data"]["patient_id"] == "43743"
    assert out["elapsed_ms"] == pytest.approx(152.4)
