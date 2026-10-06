"""Fail closed for unverifiable synthetic command results."""
from modules.EchoMind.secretary.workflow import WorkflowExecutor, WorkflowPlan, WorkflowStep, VerifySpec
from modules.EchoMind.secretary import AdapterRegistry, CommandBus, CommandPlan
import asyncio
from types import SimpleNamespace
import pytest


def test_async_workflow_yields_during_verification():
    async def scenario():
        ticks = []
        probes = []
        async def run(action, args):
            if action == "probe":
                probes.append(1)
                return {"ok": True, "data": {"patient_id": "synthetic" if ticks else ""}}
            return {"ok": True}
        async def heartbeat():
            await asyncio.sleep(0)
            ticks.append(1)
        task = asyncio.create_task(heartbeat())
        engine = WorkflowExecutor(run)
        result = await engine.run_async(WorkflowPlan("synthetic", [WorkflowStep("open", verify=
            VerifySpec("patient_open", "probe", expect={"patient_id": "synthetic"}, retries=3, delay_s=.01))]))
        await task
        assert result.ok and ticks and len(probes) >= 2
    asyncio.run(scenario())


def test_async_search_timeout_does_not_return_stale_rows():
    from modules.EchoMind.secretary.adapters.home_widget_adapter import HomeWidgetAdapter
    async def scenario():
        task = asyncio.get_running_loop().create_future()
        home = SimpleNamespace(_search_task=None, patient_search_widget=SimpleNamespace(set_search_data=lambda p: None))
        home.patient_list_function_identifier = lambda src: setattr(home, "_search_task", task)
        adapter = HomeWidgetAdapter(home)
        adapter._set_active_source = lambda s: None
        adapter._set_modalities = lambda s: None
        with pytest.raises(TimeoutError):
            await adapter.search_async("local", {}, timeout_s=.01)
        assert not task.cancelled()  # A reader must not cancel Home's shared task.
    asyncio.run(scenario())


def test_replaced_search_cannot_supply_another_requests_rows():
    from modules.EchoMind.secretary.adapters.home_widget_adapter import HomeWidgetAdapter
    async def scenario():
        first = asyncio.get_running_loop().create_future()
        home = SimpleNamespace(_search_task=first)
        adapter = HomeWidgetAdapter(home)
        adapter.start_search = lambda *a: first
        waiting = asyncio.create_task(adapter.search_async("local", {}, timeout_s=1))
        await asyncio.sleep(0)
        home._search_task = asyncio.get_running_loop().create_future()
        first.set_result(None)
        with pytest.raises(RuntimeError, match="replaced"):
            await waiting
    asyncio.run(scenario())


def test_error_probe_cannot_verify_success_payload():
    engine = WorkflowExecutor(lambda *a: {"ok": False, "data": {"count": 4}})
    assert not engine._verify(VerifySpec("thumbnails_loaded", "probe"), {})


def test_unknown_verifier_stops_workflow():
    calls = []
    engine = WorkflowExecutor(lambda *a: calls.append(a) or {"ok": True})
    result = engine.run(WorkflowPlan("synthetic", [WorkflowStep(
        "synthetic", verify=VerifySpec("unknown", "probe"))]))
    assert not result.ok
    assert not calls


def test_missing_success_does_not_advance():
    calls = []
    engine = WorkflowExecutor(lambda action, args: calls.append(action) or {})
    result = engine.run(WorkflowPlan("synthetic", [WorkflowStep("first"), WorkflowStep("second")]))
    assert not result.ok
    assert calls == ["first"]


def test_empty_state_retains_identity():
    class Adapter:
        def run(self, plan, state):
            state["synthetic"] = True
            return {"ok": True}
    registry = AdapterRegistry()
    registry.register("synthetic", Adapter(), {"synthetic": "run"})
    state = {}
    CommandBus(registry=registry, orchestrator=None).execute(CommandPlan(action="synthetic"), state)
    assert state == {"synthetic": True}


def test_policy_failure_cannot_execute_scoped_action(monkeypatch):
    from modules.EchoMind.secretary import permissions
    calls = []
    registry = AdapterRegistry()
    registry.register("synthetic", SimpleNamespace(run=lambda *a: calls.append(1)), {"get_active_tab": "run"})
    def broken(*a, **k):
        raise RuntimeError("Synthetic policy failure")
    monkeypatch.setattr(permissions, "decide", broken)
    result = registry.dispatch(CommandPlan(action="get_active_tab"), {"agent_mode": "assistant"})
    assert not result.ok and calls == []


def test_secretary_uses_assistant_policy_by_default(monkeypatch):
    from modules.EchoMind.secretary.executor import _assistant_bus_mode
    monkeypatch.delenv("AIPACS_AGENT_ASSISTANT_MODE", raising=False)
    assert _assistant_bus_mode() == "assistant"


def test_async_execution_waits_for_search_before_open_and_can_cancel():
    from modules.EchoMind.secretary.executor import SecretaryExecutor
    from modules.EchoMind.secretary.workflow import build_plan
    async def scenario(cancel):
        ready = asyncio.Event()
        opened = []
        rows = [{"patient_id": "synthetic", "study_uid": "1.2.3.4"}]
        async def search(**kwargs):
            await ready.wait()
        adapter = SimpleNamespace(is_available=lambda: True, get_active_source=lambda: "local",
            search=lambda **kw: pytest.fail("Blocking search"), search_async=search,
            list_rows=lambda: rows, open_patient=lambda **kw: opened.append(kw))
        executor = SecretaryExecutor(adapter)
        state = {}
        async def run(action, entities):
            return await executor.execute_async({"action": action, "entities": entities}, state, confirmed=True)
        plan = build_plan("synthetic", [{"action": "list_patients"},
            {"action": "open_patient", "entities": {"row_index": 1}}], verify=False)
        task = asyncio.create_task(WorkflowExecutor(run).run_async(plan))
        await asyncio.sleep(0)
        assert not opened
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            ready.set()
            await asyncio.sleep(0)
            assert not opened
        else:
            ready.set()
            result = await task
            assert result.ok and len(opened) == 1
            assert opened[0]["study_uid"] == "1.2.3.4"
    asyncio.run(scenario(False))
    asyncio.run(scenario(True))


def test_async_orchestrator_rejects_overlapping_session_and_releases_on_cancel():
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    from modules.EchoMind.secretary.workflow import ExecutionCall
    async def scenario():
        owner = SecretaryOrchestrator.__new__(SecretaryOrchestrator)
        ready = asyncio.Event()
        def steps(cmd):
            yield ExecutionCall(lambda: None, ready.wait)
            return {"ok": True}
        owner._handle_steps = steps
        first = asyncio.create_task(owner.handle_async({"session_id": "synthetic"}))
        await asyncio.sleep(0)
        second = await owner.handle_async({"session_id": "synthetic"})
        assert second["error_code"] == "EXECUTION_IN_PROGRESS"
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        ready.set()
        assert (await owner.handle_async({"session_id": "synthetic"}))["ok"]
    asyncio.run(scenario())


def test_async_orchestrator_preserves_real_confirmation_state_machine(monkeypatch):
    from modules.EchoMind.secretary import orchestrator as module
    from modules.EchoMind.secretary.executor import SecretaryExecutor
    class NullSession:
        def __init__(self, **kw): pass
        def __getattr__(self, name): return lambda *a, **kw: None
    monkeypatch.setattr(module, "SessionLog", NullSession)
    monkeypatch.setattr(module.audit, "log_start", lambda **kw: 1)
    monkeypatch.setattr(module.audit, "log_end", lambda **kw: None)
    owner = module.SecretaryOrchestrator.__new__(module.SecretaryOrchestrator)
    opened = []
    rows = [{"patient_id": "synthetic", "study_uid": "1.2.3.4"}]
    owner.adapter = SimpleNamespace(get_active_source=lambda: "local", is_available=lambda: True,
        list_rows=lambda: rows, open_patient=lambda **kw: opened.append(kw))
    owner.executor = SecretaryExecutor(owner.adapter)
    owner._sessions = {"synthetic": {"last_list": rows, "last_list_source": "local", "pending": None}}
    owner._last_modules = []
    owner._last_route = {}
    owner._get_memory_store_safe = lambda: None
    owner._parse_plan = lambda *a, **kw: {"action": "open_patient", "entities": {"row_index": 1},
        "confidence": 1.0, "reason": "synthetic", "needs_confirmation": True}
    async def scenario():
        command = {"text": "Synthetic command", "session_id": "synthetic"}
        first = await owner.handle_async(command)
        assert first["error_code"] == "CONFIRM_REQUIRED" and not opened
        final = await owner.handle_async(dict(command, text="yes"))
        assert final["ok"] and len(opened) == 1
        assert opened[0]["study_uid"] == "1.2.3.4"
    asyncio.run(scenario())
