# -*- coding: utf-8 -*-
"""Guard tests for the Secretary EchoMind multi-step workflow engine (2026-06-23).

Pins the sequencing + verification contract in ``workflow.py``:
- steps run in order; a later step only runs after the previous step VERIFIES;
- the run STOPS on the first failed step (subsequent steps never execute);
- context threads from one step to the next (open uses the patient the download
  step captured);
- async effects (download) are re-probed until verified (bounded retries);
- ``decompose`` recognises the documented compound commands and returns ``None``
  for single-action input (which falls through to the legacy path).

Pure stdlib — no Qt/VTK/bus. Runs in the offscreen verify lane.
"""
from __future__ import annotations

from modules.EchoMind.secretary.workflow import (
    VerifySpec,
    WorkflowExecutor,
    WorkflowPlan,
    WorkflowStep,
    decompose,
)

_NOSLEEP = lambda *_a, **_k: None


class FakeRunner:
    """Records (action, entities) calls; returns scripted results.

    A script value may be a single dict (returned every call) or a list used as
    a queue (one result per call) for polling probes.
    """

    def __init__(self, scripts):
        self.scripts = scripts
        self.calls = []

    def __call__(self, action, entities):
        self.calls.append((action, dict(entities or {})))
        v = self.scripts.get(action)
        if isinstance(v, list):
            return v.pop(0) if v else {"ok": True, "action": action}
        return v if v is not None else {"ok": True, "action": action}

    def actions(self):
        return [a for a, _ in self.calls]


# ── happy path: download → open, with verification + context threading ────────
def test_download_then_open_runs_both_and_threads_context():
    r = FakeRunner({
        "download_patient": {"ok": True, "data": {"patient_id": "47734"}},
        "check_download_status": {"ok": True, "data": {"status": "complete"}},
        "open_patient": {"ok": True, "data": {"patient_id": "47734"}},
        "get_active_tab": {"ok": True, "data": {"patient_id": "47734"}},
    })
    plan = decompose("download this patient and open it")
    assert plan is not None and len(plan.steps) == 2
    out = WorkflowExecutor(r, sleep=_NOSLEEP).run(plan)
    assert out.ok and out.failed_index is None
    assert r.actions().count("download_patient") == 1
    assert "open_patient" in r.actions()
    # open_patient must have received the patient_id captured from the download step
    open_call = [e for a, e in r.calls if a == "open_patient"][0]
    assert open_call.get("patient_code") == "47734"
    assert all(s.verified for s in out.steps)


# ── stop-on-failed-verify: download never completes → open never runs ──────────
def test_stops_when_download_not_verified():
    r = FakeRunner({
        "download_patient": {"ok": True, "data": {"patient_id": "47734"}},
        "check_download_status": {"ok": True, "data": {"status": "downloading"}},  # never complete
        "open_patient": {"ok": True, "data": {"patient_id": "47734"}},
    })
    plan = decompose("download this patient and open it")
    out = WorkflowExecutor(r, sleep=_NOSLEEP).run(plan)
    assert not out.ok and out.failed_index == 0
    assert "open_patient" not in r.actions()  # second step must NOT run


# ── stop-on-failed-step: download itself fails → stop immediately ──────────────
def test_stops_when_step_not_ok():
    r = FakeRunner({
        "download_patient": {"ok": False, "error_code": "NO_HOME_WIDGET"},
        "open_patient": {"ok": True},
    })
    plan = WorkflowPlan(goal="dl+open", steps=[
        WorkflowStep("download_patient", {}),
        WorkflowStep("open_patient", {"patient_code": "1"}),
    ])
    out = WorkflowExecutor(r, sleep=_NOSLEEP).run(plan)
    assert not out.ok and out.failed_index == 0
    assert out.steps[0].error_code == "NO_HOME_WIDGET"
    assert "open_patient" not in r.actions()


# ── async retry: download completes on the 3rd poll ────────────────────────────
def test_verify_retries_until_complete():
    r = FakeRunner({
        "download_patient": {"ok": True, "data": {"patient_id": "9"}},
        "check_download_status": [
            {"ok": True, "data": {"status": "downloading"}},
            {"ok": True, "data": {"status": "downloading"}},
            {"ok": True, "data": {"status": "complete"}},
        ],
    })
    plan = WorkflowPlan(goal="dl", steps=[
        WorkflowStep("download_patient", {},
                     verify=VerifySpec("download_complete", "check_download_status",
                                       retries=5, delay_s=0.0)),
    ])
    out = WorkflowExecutor(r, sleep=_NOSLEEP).run(plan)
    assert out.ok and out.steps[0].verified
    assert r.actions().count("check_download_status") == 3


# ── three-step compound: download → open → load first series ───────────────────
def test_decompose_three_step_load_series():
    plan = decompose("download this patient, open it, and load the first series")
    assert plan is not None
    tools = [s.tool for s in plan.steps]
    assert tools == ["download_patient", "open_patient", "get_thumbnails_data", "change_series"]
    cs = [s for s in plan.steps if s.tool == "change_series"][0]
    assert cs.args.get("series_index") == 0


def test_decompose_series_ordinal():
    plan = decompose("download and open and load the third series")
    cs = [s for s in plan.steps if s.tool == "change_series"][0]
    assert cs.args.get("series_index") == 2


# ── single-action input is NOT a workflow (legacy path handles it) ─────────────
def test_decompose_returns_none_for_single_action():
    assert decompose("show me today's MRI patient list") is None
    assert decompose("open this patient") is None
    assert decompose("") is None
