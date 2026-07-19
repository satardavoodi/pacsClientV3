"""Minimal MCP server logic (JSON-RPC 2.0) — pure and transport-agnostic.

Implements the subset of the Model Context Protocol an AI client needs to drive
the workstation over Streamable HTTP:

    initialize · notifications/initialized · ping ·
    tools/list · tools/call · resources/list · resources/read

Every CommandBus action becomes an MCP **tool**; the operational docs +
function catalog become MCP **resources** (via :class:`DocsResourceProvider`).
The class holds NO transport and NO Qt — it takes injected callables:

* ``list_actions() -> list[str]``
* ``execute(action, arguments, *, confirmed) -> dict``  (a serialized
  ``CommandResult``; the caller runs it on the Qt GUI thread and applies the
  device's permission mode)

so it is fully unit-testable off-screen. We implement the JSON-RPC subset
directly rather than pulling in an ASGI MCP server, keeping the dependency
footprint at stdlib.

Spec references: MCP 2025-06-18 / 2026 streamable-HTTP; JSON-RPC 2.0.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Advertised protocol revision; clients negotiate against their own.
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "aipacs-agent-gateway"

# JSON-RPC error codes.
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603

# Short human descriptions for the well-known actions (best-effort; unmapped
# actions still get a generic description so every action is callable).
_ACTION_HINTS: Dict[str, str] = {
    "list_patients": "List/search patients on the workstation (read-only).",
    "select_patient": "Select a patient in the list (loads thumbnails).",
    "open_patient": "Open a patient's study in the viewer.",
    "download_patient": "Trigger download of a patient's study (server write).",
    "change_series": "Load/switch to a series in the active viewport.",
    "switch_tab": "Switch the active patient tab.",
    "query_viewport_state": "Read the current viewport state (read-only).",
    "get_viewport_context": "Read rich viewport context (read-only).",
    "capture_viewport": "Capture the current viewport image.",
    "activate_tool": "Activate a viewer tool (ruler, WL, ...).",
    "measure_distance": "Place a distance measurement.",
    "get_measurements": "List current measurements (read-only).",
    "open_mpr": "Open Standard (Zeta) MPR for the active study.",
    "list_downloads": "List active/queued downloads (read-only).",
    "check_download_status": "Check a download's status (read-only).",
    "close_patient_tab": "Close a patient tab (destructive).",
    "send_report_to_pacs": "Send a report to the PACS (server write).",
}


class McpBridge:
    def __init__(
        self,
        *,
        list_actions: Callable[[], List[str]],
        execute: Callable[..., Dict[str, Any]],
        docs_provider: Optional[Any] = None,
    ) -> None:
        self._list_actions = list_actions
        self._execute = execute
        self._docs = docs_provider

    # ── top-level JSON-RPC entry ──────────────────────────────────────
    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle one JSON-RPC request/notification.

        Returns a JSON-RPC response dict, or ``None`` for a notification
        (no ``id``) which per spec gets no response body.
        """
        if not isinstance(message, dict):
            return self._error(None, ERR_INVALID_REQUEST, "not a JSON-RPC object")

        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}
        is_notification = "id" not in message

        try:
            if method == "initialize":
                result = self._initialize(params)
            elif method in ("notifications/initialized", "initialized"):
                return None  # notification — no response
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self._tools()}
            elif method == "tools/call":
                result = self._tools_call(params)
            elif method == "resources/list":
                result = {"resources": self._resources()}
            elif method == "resources/read":
                result = self._resources_read(params)
            else:
                if is_notification:
                    return None
                return self._error(msg_id, ERR_METHOD_NOT_FOUND,
                                   f"unknown method {method!r}")
        except _McpError as exc:
            return self._error(msg_id, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("MCP handler crashed for method=%s", method)
            return self._error(msg_id, ERR_INTERNAL, f"internal error: {exc}")

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    # ── method impls ──────────────────────────────────────────────────
    def _initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        client_ver = str((params or {}).get("protocolVersion") or PROTOCOL_VERSION)
        return {
            "protocolVersion": client_ver or PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
            },
            "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
            "instructions": (
                "This server exposes the AI-PACS workstation. Call an action "
                "with tools/call (name=action, arguments=entities). Read "
                "resources/list for the live function catalog and operational "
                "docs before driving clinical workflows."
            ),
        }

    def _tools(self) -> List[Dict[str, Any]]:
        try:
            actions = sorted(self._list_actions() or [])
        except Exception:
            actions = []
        tools: List[Dict[str, Any]] = []
        for action in actions:
            tools.append(
                {
                    "name": action,
                    "description": _ACTION_HINTS.get(
                        action, f"Invoke the '{action}' workstation action."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "entities": {
                                "type": "object",
                                "description": "Action arguments (entities).",
                            },
                            "confirmed": {
                                "type": "boolean",
                                "description": (
                                    "Set true to confirm a server-write / "
                                    "destructive action when the device mode "
                                    "requires confirmation."
                                ),
                            },
                        },
                        "additionalProperties": True,
                    },
                }
            )
        return tools

    def _tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = str((params or {}).get("name") or "").strip()
        if not name:
            raise _McpError(ERR_INVALID_PARAMS, "tools/call requires 'name'")
        arguments = (params or {}).get("arguments") or {}
        if not isinstance(arguments, dict):
            raise _McpError(ERR_INVALID_PARAMS, "'arguments' must be an object")

        # Accept either {entities:{...}, confirmed:bool} or a flat args dict
        # (flat is treated as the entities themselves).
        if "entities" in arguments and isinstance(arguments.get("entities"), dict):
            entities = dict(arguments.get("entities") or {})
        else:
            entities = {k: v for k, v in arguments.items() if k != "confirmed"}
        confirmed = bool(arguments.get("confirmed"))

        result = self._execute(name, entities, confirmed=confirmed)
        if not isinstance(result, dict):
            result = {"ok": True, "action": name, "data": result}

        import json as _json

        is_error = not bool(result.get("ok", True))
        return {
            "content": [
                {"type": "text", "text": _json.dumps(result, default=str, ensure_ascii=False)}
            ],
            "isError": is_error,
        }

    def _resources(self) -> List[Dict[str, Any]]:
        if self._docs is None:
            return []
        try:
            return list(self._docs.list_resources() or [])
        except Exception:
            return []

    def _resources_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        uri = str((params or {}).get("uri") or "").strip()
        if not uri:
            raise _McpError(ERR_INVALID_PARAMS, "resources/read requires 'uri'")
        if self._docs is None:
            raise _McpError(ERR_INVALID_PARAMS, f"no resource provider for {uri!r}")
        content = self._docs.read_resource(uri)
        if content is None:
            raise _McpError(ERR_INVALID_PARAMS, f"unknown resource {uri!r}")
        return {"contents": [content]}

    # ── helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }


class _McpError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


__all__ = ["McpBridge", "PROTOCOL_VERSION", "SERVER_NAME"]
