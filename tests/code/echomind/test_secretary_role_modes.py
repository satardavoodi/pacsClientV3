from datetime import datetime, timezone
import pytest
from modules.ai_imaging.eagle_eye_remote.secretary.service import Request


def test_server_accepts_explicit_modes_and_rejects_unknown():
    base = dict(protocol=1, request_id="11111111-1111-4111-8111-111111111111", phase="plan", text="Synthetic question", language="en", client_time=datetime.now(timezone.utc).isoformat())
    for mode in ("act", "ask", "guide"):
        assert Request(**base, interaction_mode=mode).interaction_mode == mode
    with pytest.raises(ValueError): Request(**base, interaction_mode="automatic-delete")


def test_question_mode_never_reaches_execution():
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    instance = object.__new__(SecretaryOrchestrator)
    instance._get_memory_store_safe = lambda: None
    work = instance._handle_steps({"text":"Synthetic question", "interaction_mode":"ask", "_preplanned":{"_mode":"ask", "_mode_reply":"Synthetic answer"}})
    with pytest.raises(StopIteration) as finished:
        next(work)
    assert finished.value.value["message"] == "Synthetic answer"
    assert finished.value.value["action"] == "mode_reply"
    rejected = instance._handle_steps({"text":"Synthetic question", "interaction_mode":"guide", "_preplanned":{"action":"request_storage_cleanup", "entities":{"category":"patients", "strategy":"all"}}})
    with pytest.raises(StopIteration) as denied:
        next(rejected)
    assert denied.value.value["error_code"] == "MODE_RESPONSE_REQUIRED"
