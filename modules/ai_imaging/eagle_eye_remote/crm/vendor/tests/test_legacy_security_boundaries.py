from __future__ import annotations

from http import HTTPStatus
from io import BytesIO
from types import SimpleNamespace

import pytest

from reception_crm.core.types import ToolResult
from reception_crm.mcp_server import call_tool, mcp_tools
from reception_crm.permissions import PermissionDecision
from reception_crm.voice_gateway import VoiceGatewayHandler, run_gateway
from reception_crm.write_executor import execute_operation


def test_mcp_does_not_advertise_executable_operations() -> None:
    names = {tool["name"] for tool in mcp_tools()}

    assert "execute_operation" not in names
    assert "appointments.schedule" not in names


def test_mcp_refuses_direct_core_write_calls() -> None:
    with pytest.raises(PermissionError, match="stdio MCP is read-only"):
        call_tool(
            "appointments.schedule",
            {
                "receptionId": "123",
                "persianDate": "1405/06/10",
                "timeSlot": "10:00",
                "room": "1",
            },
        )


def test_mcp_uses_server_owned_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_dispatch(call, registry, context):
        captured["context"] = context
        return ToolResult(ok=True, name=call.name, data={"ok": True})

    monkeypatch.setattr("reception_crm.mcp_server.dispatch", fake_dispatch)
    result = call_tool("daily-summary", {"date": "today"})

    assert result["ok"] is True
    principal = captured["context"].principal
    assert principal.user == "local_cli"
    assert principal.center
    assert principal.roles == ["agent_readonly"]
    assert principal.auth_method == "os_session"


def test_retired_legacy_executor_never_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    plan = SimpleNamespace(
        enabled=True,
        missing_required_inputs=[],
        safety="clinical_write",
        url="http://127.0.0.1:8080/api/appointment",
        method="POST",
        query={},
        body={"receptionId": "123"},
        as_dict=lambda: {"operation": "appointments.schedule", "enabled": True},
    )
    registry = SimpleNamespace(plan=lambda name, inputs: plan)
    allowed = PermissionDecision(
        allowed=True,
        reason="test policy",
        user="owner",
        center="TEST",
        roles=["owner"],
    )
    permissions = SimpleNamespace(check=lambda *args: allowed)
    monkeypatch.setenv("RECEPTION_ENABLE_WRITES", "true")

    result = execute_operation(
        "appointments.schedule",
        inputs={"receptionId": "123"},
        user="owner",
        center="TEST",
        confirmation="EXECUTE appointments.schedule",
        execute=True,
        registry=registry,
        permissions=permissions,
        data_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["checks"]["legacy_execution_path_active"] is False
    assert "api_response" not in result


@pytest.mark.parametrize(
    ("host_header", "expected"),
    [
        ("127.0.0.1:8765", True),
        ("localhost:8765", True),
        ("[::1]:8765", True),
        ("127.0.0.1.evil.example", False),
        ("evil.example", False),
    ],
)
def test_legacy_gateway_rejects_untrusted_host_headers(host_header: str, expected: bool) -> None:
    handler = SimpleNamespace(headers={"Host": host_header})

    assert VoiceGatewayHandler.has_trusted_host(handler) is expected


@pytest.mark.parametrize("path", ["/api/settings", "/api/settings/test"])
def test_legacy_gateway_settings_endpoints_are_gone(path: str) -> None:
    captured = {}
    handler = SimpleNamespace(
        path=path,
        has_trusted_host=lambda: True,
        respond_json=lambda body, status: captured.update(body=body, status=status),
    )

    VoiceGatewayHandler.do_POST(handler)

    assert captured["status"] == HTTPStatus.GONE
    assert captured["body"]["error"] == "legacy_settings_disabled"


def test_legacy_gateway_does_not_emit_wildcard_cors() -> None:
    headers = []
    handler = SimpleNamespace(
        send_response=lambda status: None,
        send_header=lambda name, value: headers.append((name, value)),
        end_headers=lambda: None,
        wfile=BytesIO(),
    )

    VoiceGatewayHandler.respond_json(handler, {"status": "ok"})

    assert not any(name.lower() == "access-control-allow-origin" for name, _ in headers)


def test_legacy_gateway_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECEPTION_ENABLE_LEGACY_GATEWAY", raising=False)

    with pytest.raises(RuntimeError, match="Legacy gateway is disabled"):
        run_gateway()


def test_legacy_gateway_cannot_bind_to_lan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECEPTION_ENABLE_LEGACY_GATEWAY", "true")

    with pytest.raises(ValueError, match="only to a loopback host"):
        run_gateway(host="0.0.0.0")
