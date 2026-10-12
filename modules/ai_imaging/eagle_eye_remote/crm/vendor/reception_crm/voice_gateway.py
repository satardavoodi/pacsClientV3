from __future__ import annotations

import json
import os
from importlib import resources
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .agent_router import route_command
from .operations import load_operations
from .settings import load_settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent
UI_PATH = PROJECT_ROOT / "ui" / "voice-gateway.html"
LEGACY_GATEWAY_ENV = "RECEPTION_ENABLE_LEGACY_GATEWAY"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class VoiceGatewayHandler(BaseHTTPRequestHandler):
    server_version = "ReceptionVoiceGateway/0.1"

    def do_GET(self) -> None:
        if not self.has_trusted_host():
            self.respond_json({"error": "untrusted_host"}, HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/ui"}:
            self.respond_html(read_ui_html())
        elif parsed.path == "/api/health":
            registry = load_operations()
            self.respond_json(
                {
                    "status": "ok",
                    "service": "reception-voice-gateway",
                    "operation_count": len(registry.operations),
                    "write_policy": registry.defaults.get("write_mode", "dry_run_only"),
                }
            )
        elif parsed.path == "/api/operations":
            registry = load_operations()
            self.respond_json({"operations": registry.list_operations()})
        elif parsed.path == "/api/settings":
            self.respond_json(load_settings().public_dict())
        else:
            self.respond_json({"error": "not_found", "path": parsed.path}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self.has_trusted_host():
            self.respond_json({"error": "untrusted_host"}, HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        if parsed.path in {"/api/settings", "/api/settings/test"}:
            self.respond_json(
                {
                    "error": "legacy_settings_disabled",
                    "message": "Configure and test connections through the authenticated server API.",
                },
                HTTPStatus.GONE,
            )
            return

        if parsed.path != "/api/command":
            self.respond_json({"error": "not_found", "path": parsed.path}, HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self.read_json()
            result = route_command(
                text=str(payload.get("text", "")),
                user=payload.get("user"),
                center=payload.get("center"),
                inputs=payload.get("inputs") or {},
            )
            self.respond_json(result)
        except Exception as exc:  # Defensive boundary for UI/API callers.
            self.respond_json({"error": type(exc).__name__, "message": str(exc)}, HTTPStatus.BAD_REQUEST)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)

    def respond_json(self, body: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def has_trusted_host(self) -> bool:
        raw_host = self.headers.get("Host", "")
        if not raw_host:
            return False
        parsed = urlparse(f"//{raw_host}")
        return (parsed.hostname or "").lower() in LOOPBACK_HOSTS

    def respond_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = body.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_gateway(host: str = "127.0.0.1", port: int = 8765) -> None:
    if os.getenv(LEGACY_GATEWAY_ENV) != "true":
        raise RuntimeError(
            f"Legacy gateway is disabled. Set {LEGACY_GATEWAY_ENV}=true only for "
            "temporary local compatibility testing."
        )
    if host.lower() not in LOOPBACK_HOSTS:
        raise ValueError("Legacy gateway may bind only to a loopback host.")
    server = ThreadingHTTPServer((host, port), VoiceGatewayHandler)
    print(f"Reception CRM voice gateway running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


def read_ui_html() -> str:
    if UI_PATH.exists():
        return UI_PATH.read_text(encoding="utf-8")
    return resources.files("reception_crm.web").joinpath("voice-gateway.html").read_text(encoding="utf-8")
