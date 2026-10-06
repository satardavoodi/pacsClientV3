"""Synthetic guards for ordered-list opening and checkbox verification."""
from copy import deepcopy
import pytest
from modules.EchoMind.secretary.executor import SecretaryExecutor
from modules.EchoMind.secretary.validator import validate_plan
from modules.EchoMind.secretary.workflow import WorkflowExecutor, build_plan

ROWS = [dict(patient_id="synthetic-a", study_uid="1.2.3.1"), dict(patient_id="synthetic-b", study_uid="1.2.3.2")]

def plan(action="open_patient", **entities):
    return dict(action=action, entities=entities, confidence=0.9, reason="synthetic", needs_confirmation=True)

class Adapter:
    source = "local"
    def __init__(self):
        self.rows = deepcopy(ROWS)
        self.opened = []
    def is_available(self): return True
    def get_active_source(self): return self.source
    def search(self, **kwargs): pass
    def list_rows(self): return self.rows
    def open_patient(self, **kwargs): self.opened.append(kwargs)
    def select_top_n_rows(self, n): return min(n, len(self.rows))
    def get_checked_studies(self): return self.rows[:1]

def captured(ex, state):
    assert ex._list_patients(plan("list_patients"), state)["ok"]

@pytest.mark.parametrize("index", [1, 2, 10000])
def test_validator_accepts_ordinal(index):
    normalized, errors = validate_plan(plan(row_index=index))
    assert normalized and not errors

@pytest.mark.parametrize("index", [True, 0, -1, 10001, 1.5, "1"])
def test_validator_rejects_bad_ordinal(index):
    assert validate_plan(plan(row_index=index))[1]

@pytest.mark.parametrize("extra", [{"patient_code":"synthetic-a"}, {"resolved_patient":ROWS[0]}])
def test_validator_rejects_conflicting_selector(extra):
    assert validate_plan(plan(row_index=1, **extra))[1]

def test_ordinal_uses_captured_order_and_confirmation():
    a=Adapter(); ex=SecretaryExecutor(a); state={}; captured(ex,state)
    a.rows.reverse()
    assert ex._open_patient(plan(row_index=1), state, False)["error_code"] == "CONFIRM_REQUIRED"
    assert not a.opened
    assert ex._open_patient(plan(row_index=1), state, True)["ok"]
    assert a.opened[0]["study_uid"] == ROWS[0]["study_uid"]

@pytest.mark.parametrize("change", ["missing", "empty", "range", "source", "stale"])
def test_ordinal_rejects_unresolved_context(change):
    a=Adapter(); ex=SecretaryExecutor(a); state={}; captured(ex,state)
    index=1
    if change=="missing": state={}
    if change=="empty": state["last_list"]=[]
    if change=="range": index=3
    if change=="source": a.source="server"
    if change=="stale": a.rows=[]
    assert not ex._open_patient(plan(row_index=index), state, True)["ok"]
    assert not a.opened

def test_empty_selection_is_failure():
    a=Adapter(); a.rows=[]
    assert not SecretaryExecutor(a)._select_patient(plan("select_patient", limit=1), {})["ok"]

def test_checkbox_selection_does_not_require_thumbnails():
    calls=[]
    def run(action, entities):
        calls.append(action)
        assert action == "select_patient"
        return {"ok":True, "data":{"selected_count":1}}
    result=WorkflowExecutor(run, sleep=lambda _:None).run(build_plan("select", [{"action":"select_patient", "entities":{"limit":1}}]))
    assert result.ok
    assert calls == ["select_patient"]

@pytest.mark.parametrize("count", [0, None, True, -1])
def test_workflow_rejects_unconfirmed_selection(count):
    result=WorkflowExecutor(lambda *_: {"ok":True, "data":{"selected_count":count}}).run(
        build_plan("select", [{"action":"select_patient", "entities":{"limit":1}}]))
    assert not result.ok

@pytest.mark.parametrize("wrong_study", [False, True])
def test_list_then_open_verifies_exact_captured_study(wrong_study):
    a=Adapter(); ex=SecretaryExecutor(a); state={}
    def run(action, entities):
        if action=="get_active_tab":
            return {"ok":True, "data":{"patient_id":ROWS[0]["patient_id"],
                    "study_uid":"1.2.3.999" if wrong_study else ROWS[0]["study_uid"]}}
        return ex.execute(plan(action, **entities),state,confirmed=True)
    steps=[{"action":"list_patients", "entities":{}}, {"action":"open_patient", "entities":{"row_index":1}}]
    result=WorkflowExecutor(run,sleep=lambda _:None).run(build_plan("list and open",steps))
    assert result.ok is (not wrong_study)
    assert len(a.opened)==1

def test_failed_search_invalidates_old_ordinal_context():
    a=Adapter(); ex=SecretaryExecutor(a); state={}; captured(ex,state)
    def fail(**kwargs): raise RuntimeError("Synthetic failure")
    a.search=fail
    assert not ex._list_patients(plan("list_patients"),state)["ok"]
    assert not ex._open_patient(plan(row_index=1),state,True)["ok"]
    assert not a.opened


def test_single_ordinal_confirmation_round_trip():
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    a=Adapter(); ex=SecretaryExecutor(a); state={}; captured(ex,state)
    owner=SecretaryOrchestrator.__new__(SecretaryOrchestrator)
    owner.adapter=a; owner.executor=ex
    assert owner._run_plan(plan(row_index=1),state,False)["error_code"] == "CONFIRM_REQUIRED"
    pending=state["pending"]["plan"]
    assert not validate_plan(pending)[1]
    assert owner._run_plan(pending,state,True)["ok"]
    assert a.opened[0]["study_uid"] == ROWS[0]["study_uid"]
