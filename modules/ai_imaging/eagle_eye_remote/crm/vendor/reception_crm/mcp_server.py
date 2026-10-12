from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .agent_router import route_command
from .core.dispatcher import dispatch
from .core.registry import default_registry, requires_human_approval
from .core.types import DispatchContext, Principal, ToolCall
from .operations import load_operations
from .settings import resolve_center


PROTOCOL_VERSION = "2024-11-05"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

LEGACY_TOOLS = [
    {
        "name": "route_command",
        "description": "Route a Persian or English CRM command into an analytics skill or a safe dry-run write plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "user": {"type": "string"},
                "center": {"type": "string"},
                "inputs": {"type": "object"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_operations",
        "description": "List mapped CRM operations and their safety status.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "plan_operation",
        "description": "Build a dry-run plan for a mapped CRM operation without executing it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "inputs": {"type": "object"},
            },
            "required": ["name"],
        },
    },
]


def mcp_tools() -> list[dict[str, Any]]:
    tools = []
    for tool in default_registry().list():
        # Stdio MCP has no authenticated human session and therefore cannot
        # redeem a confirmation plan. Do not advertise executable operations;
        # the same boundary is enforced again in ``call_tool`` below.
        if tool.get("permission_action") == "execute" or tool.get("requires_confirmation"):
            continue
        tools.append(
            {
                "name": tool["name"],
                "description": str(tool.get("description") or ""),
                "inputSchema": tool.get("input_schema") or {"type": "object", "properties": {}},
            }
        )
    tools.extend(dict(entry) for entry in LEGACY_TOOLS)
    return tools


def run_stdio_server() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"},
            }
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "reception-crm-mcp", "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return result(request_id, {"tools": mcp_tools()})
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        payload = call_tool(str(tool_name or ""), arguments)
        return result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, ensure_ascii=False, indent=2),
                    }
                ]
            },
        )

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Unsupported method: {method}"},
    }


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    registry = load_operations()
    core_registry = default_registry()
    if name in core_registry.tools:
        # ``data_root`` is a path on THIS machine, not something an MCP client can
        # know or should be trusted to send. The schema requires it, so the server
        # injects it for every tool that declares it — the orchestrator does the
        # same thing in ``_with_server_arguments``. Injecting it only for the
        # report-template-* family left every analytics tool failing validation.
        definition = core_registry.get(name)
        if definition.permission_action == "execute" or requires_human_approval(definition):
            raise PermissionError(
                "Executable CRM operations require an authenticated HTTP session and "
                "human confirmation; stdio MCP is read-only."
            )
        properties = (definition.input_schema or {}).get("properties") or {}
        if "data_root" in properties and not arguments.get("data_root"):
            arguments = {**arguments, "data_root": os.getenv("RECEPTION_CRM_DATA_ROOT") or str(PROJECT_ROOT)}
        tool_result = dispatch(
            ToolCall(name, arguments),
            registry=core_registry,
            context=DispatchContext(
                principal=Principal(
                    user="local_cli",
                    center=resolve_center(),
                    roles=["agent_readonly"],
                    auth_method="os_session",
                ),
                client="mcp",
            ),
        )
        return {
            "ok": tool_result.ok,
            "data": tool_result.data,
            "error": tool_result.error,
        }
    if name == "route_command":
        return route_command(
            text=str(arguments.get("text", "")),
            user=arguments.get("user"),
            center=arguments.get("center"),
            inputs=arguments.get("inputs") or {},
            registry=registry,
        )
    if name == "list_operations":
        return {"operations": registry.list_operations()}
    if name == "plan_operation":
        plan = registry.plan(str(arguments["name"]), arguments.get("inputs") or {})
        return plan.as_dict()
    raise ValueError(f"Unknown tool: {name}")


def result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}
