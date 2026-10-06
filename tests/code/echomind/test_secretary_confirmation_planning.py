"""Confirmation resolves local pending state, never another provider call."""
from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator

def test_pending_confirmation_skips_worker_replanning():
    engine = object.__new__(SecretaryOrchestrator)
    engine._get_state = lambda sid: {'pending':{'type':'confirm_workflow'}}
    engine._parse_plan = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('No replan for confirmation'))
    assert engine.preplan({'session_id':'synthetic:act','text':'yes'}) is None

def test_expired_confirmation_fails_before_planning_or_gui_access():
    engine = object.__new__(SecretaryOrchestrator)
    engine._get_state = lambda sid: {}
    iterator = engine._handle_core_steps({'session_id':'synthetic:act','text':'yes','_confirmation_response':True}, None)
    try:
        next(iterator)
        assert False, 'Expired confirmation must not request execution'
    except StopIteration as result:
        assert result.value['error_code'] == 'CONFIRMATION_EXPIRED'
