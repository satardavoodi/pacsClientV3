# -*- coding: utf-8 -*-
"""Guard tests for the brain multi-step plan core (2026-06-23).

Pins the pure pieces that make the "brain emits a multi-step plan" feature
correct: the workflow plan builder (`build_plan`), the multi-step parser
(`brain/multistep.py`), and per-step validation (`validator.validate_steps`).
The orchestrator/brain wiring is exercised live (Qt-coupled); these cover the
deterministic logic offscreen.
"""
from __future__ import annotations

from modules.EchoMind.secretary.workflow import WorkflowPlan, build_plan
from modules.EchoMind.secretary.brain.multistep import (
    WORKFLOW_ACTION,
    extract_steps,
    is_multi,
    to_brain_plan,
    to_workflow_plan,
)
from modules.EchoMind.secretary.validator import validate_steps


# ── build_plan: attaches the right verify + capture per action ────────────────
def test_build_plan_attaches_verifies_and_capture():
    plan = build_plan("dl+open+load", [
        {"action": "download_patient", "entities": {"patient_code": "47734"}},
        {"action": "open_patient", "entities": {"patient_code": "47734"}},
        {"action": "change_series", "entities": {"series_index": 0, "viewport": 1}},
    ])
    assert isinstance(plan, WorkflowPlan) and len(plan.steps) == 3
    dl, op, cs = plan.steps
    assert dl.verify.kind == "download_complete"
    assert dl.capture.get("patient_id") == "patient_id"
    assert op.verify.kind == "patient_open"
    assert cs.verify.kind == "viewport_has_series"
    assert cs.verify.expect.get("viewport") == 1


# ── multistep parsing ─────────────────────────────────────────────────────────
def test_extract_and_is_multi():
    single = {"action": "open_patient", "entities": {}}
    multi = {"goal": "g", "steps": [{"action": "download_patient"}, {"action": "open_patient"}]}
    assert extract_steps(single) is None
    assert is_multi(single) is False
    assert is_multi(multi) is True
    assert len(extract_steps(multi)) == 2
    assert is_multi([{"action": "a"}, {"action": "b"}]) is True  # bare array form


def test_to_brain_plan_single_is_passed_through_unchanged():
    single = {"action": "open_patient", "entities": {"patient_code": "1"}, "needs_confirmation": True}
    assert to_brain_plan(single) is single  # identity — single path untouched


def test_to_brain_plan_multi_aggregates():
    obj = {"goal": "download and open", "steps": [
        {"action": "download_patient", "entities": {"patient_code": "5"}, "needs_confirmation": True, "confidence": 0.8},
        {"action": "open_patient", "entities": {"patient_code": "5"}, "needs_confirmation": True, "confidence": 0.9},
    ]}
    bp = to_brain_plan(obj)
    assert bp["action"] == WORKFLOW_ACTION
    assert bp["needs_confirmation"] is True
    assert bp["confidence"] == 0.8  # min across steps
    wp = to_workflow_plan(bp)
    assert [s.tool for s in wp.steps] == ["download_patient", "open_patient"]


# ── validate_steps: reuses validate_plan, normalizes shape ────────────────────
def test_validate_steps_ok_for_well_formed_steps():
    norm, errs = validate_steps([
        {"action": "download_patient", "entities": {"patient_code": "5"}},
        {"action": "open_patient", "entities": {"patient_code": "5"}},
    ])
    assert errs == []
    # side-effect steps are normalized to needs_confirmation=True
    assert all(s.get("needs_confirmation") is True for s in norm)


def test_validate_steps_flags_missing_action():
    _norm, errs = validate_steps([{"entities": {}}])
    assert errs  # a step with no action must produce a validation error
