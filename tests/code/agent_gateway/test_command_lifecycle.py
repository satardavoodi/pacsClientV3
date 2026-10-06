"""Synthetic commands only; no application, database or clinical state."""
import threading
import json
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from modules.agent_gateway.gui_dispatch import make_gui_dispatcher
from modules.agent_gateway.mcp_bridge import McpBridge, PROTOCOL_VERSION


def test_expired_queued_command_never_executes():
    app = QApplication.instance() or QApplication([])
    calls = []

    class Bus:
        def execute(self, plan, state):
            calls.append(plan.action)
            return {"ok": True, "action": plan.action}

    dispatcher = make_gui_dispatcher(lambda: Bus())
    results = []
    thread = threading.Thread(target=lambda: results.append(
        dispatcher.run_command("synthetic", {}, "read_only", timeout=1)))
    thread.start()
    thread.join(3)
    assert not thread.is_alive()
    assert results[0]["error_code"] == "GUI_TIMEOUT"
    app.processEvents()
    assert calls == []


def test_unknown_protocol_is_not_advertised_as_supported():
    bridge = McpBridge(list_actions=lambda: [], execute=lambda *a, **k: {})
    response = bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "unsupported"}})
    assert response["result"]["protocolVersion"] == PROTOCOL_VERSION


def test_confirmation_must_be_boolean():
    calls = []
    bridge = McpBridge(list_actions=lambda: ["synthetic"],
                       execute=lambda *a, **k: calls.append(a) or {"ok": True})
    response = bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "synthetic", "arguments": {"confirmed": "false"}}})
    assert "error" in response
    assert calls == []


def test_idempotency_key_prevents_repeated_action_and_rejects_changed_target():
    from modules.agent_gateway.core import GatewayCore
    calls = []
    core = GatewayCore(run_command=lambda *a: calls.append(a) or {"ok": True},
        list_actions=lambda: ["synthetic"],
        device_store=SimpleNamespace(authenticate=lambda token: {"device_id": "synthetic-device", "mode": "full"}))
    headers = {"authorization": "Bearer synthetic", "idempotency-key": "synthetic-operation"}
    def request(target, request_id):
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": "synthetic", "arguments": {"target": target}}}).encode()
        return core.handle("POST", "/mcp", headers, body)
    assert request("one", 1).status == 200
    response = request("one", 2)
    assert len(calls) == 1
    assert json.loads(response.body)["id"] == 2
    assert request("two", 3).status == 409
    assert len(calls) == 1


def test_home_tool_advertises_and_enforces_typed_entities():
    calls = []
    bridge = McpBridge(list_actions=lambda: ["read_patients"],
                       execute=lambda *a, **k: calls.append(a) or {"ok": True})
    listed = bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    schema = listed["result"]["tools"][0]["inputSchema"]["properties"]["entities"]
    assert "limit" in schema.get("properties", {})
    rejected = bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "read_patients", "arguments": {"entities": {"limit": True}}}})
    assert "error" in rejected and not calls


def test_running_command_timeout_is_not_reported_as_cancelled():
    app = QApplication.instance() or QApplication([])
    released = threading.Event()
    results = []
    calls = []
    class Bus:
        def execute(self, plan, state):
            calls.append(plan.action)
            assert released.wait(3)
            return {"ok": True, "action": plan.action}
    dispatcher = make_gui_dispatcher(lambda: Bus())
    def request():
        results.append(dispatcher.run_command("synthetic", {}, "read_only", timeout=1))
        released.set()
    thread = threading.Thread(target=request)
    thread.start()
    import time
    deadline = time.monotonic() + 3
    while thread.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    thread.join(1)
    assert results[0]["error_code"] == "EXECUTION_IN_PROGRESS"
    assert results[0]["retryable"] is False and len(calls) == 1
