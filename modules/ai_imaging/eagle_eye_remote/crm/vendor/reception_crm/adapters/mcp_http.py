"""MCP over HTTP — the network transport for external AI clients.

Same server, second door. Every request is handed to ``mcp_server.handle_request``
(the stdio implementation), so the two transports can never drift apart in what
they expose or how they behave. This module owns transport concerns only:

  * bearer-token auth        (a clinical tool list is not public)
  * bind scope               (loopback unless remote is explicitly enabled)
  * connected-client tracking
  * start/stop from the UI thread

Endpoints
---------
POST /mcp        JSON-RPC request  -> JSON-RPC response   (Streamable HTTP)
GET  /mcp        text/event-stream -> keep-alive SSE channel
GET  /mcp/health unauthenticated liveness probe (no tool data)

Security posture
----------------
Loopback + token by default. Binding to 0.0.0.0 without a token is rejected by
``ExternalMcpConnection.validate()`` before the server can be started — putting
clinical write-planning tools on a LAN with no auth is not a mistake we let the
user make by accident. This transport is plain HTTP: terminate TLS in front of
it before it leaves the machine.
"""

from __future__ import annotations

import json
import secrets as stdlib_secrets
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from ..mcp_server import PROTOCOL_VERSION, handle_request, mcp_tools

SERVER_NAME = "reception-crm-mcp-http"


class ClientRegistry:
    """Who is connected right now, and what did they ask for."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, dict[str, Any]] = {}

    def touch(self, client_id: str, *, address: str, info: dict[str, Any] | None, method: str) -> None:
        with self._lock:
            entry = self._clients.setdefault(
                client_id,
                {
                    "id": client_id,
                    "address": address,
                    "name": "unknown",
                    "version": "",
                    "connected_at": _now(),
                    "requests": 0,
                },
            )
            entry["last_seen"] = _now()
            entry["requests"] = int(entry["requests"]) + 1
            entry["last_method"] = method
            if info:
                entry["name"] = str(info.get("name") or entry["name"])
                entry["version"] = str(info.get("version") or entry["version"])

    def drop(self, client_id: str) -> None:
        with self._lock:
            self._clients.pop(client_id, None)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._clients.values(), key=lambda item: item["connected_at"])


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class McpHttpHandler(BaseHTTPRequestHandler):
    server_version = "ReceptionMcpHttp/0.1"

    # injected by the server factory
    token: str = ""
    require_auth: bool = True
    clients: ClientRegistry

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Default BaseHTTPRequestHandler logging writes request lines to stderr.
        # Request lines can carry tool arguments — keep them out of the console.
        return

    # ---- auth --------------------------------------------------------------
    def authorized(self) -> bool:
        if not self.require_auth:
            return True
        header = self.headers.get("Authorization") or ""
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        # Constant-time: do not let a caller time-slice the token out of us.
        return stdlib_secrets.compare_digest(header[len(prefix) :].strip(), self.token)

    def reject(self) -> None:
        body = json.dumps({"error": "unauthorized"}).encode("utf-8")
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Bearer realm="reception-crm-mcp"')
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- GET ---------------------------------------------------------------
    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/mcp/health":
            # Deliberately unauthenticated and deliberately empty: it proves the
            # port is alive without disclosing the tool surface.
            self.respond_json({"status": "ok", "service": SERVER_NAME, "protocol": PROTOCOL_VERSION})
            return

        if path == "/mcp/clients":
            if not self.authorized():
                self.reject()
                return
            self.respond_json({"clients": self.clients.list()})
            return

        if path == "/mcp":
            if not self.authorized():
                self.reject()
                return
            self.stream_sse()
            return

        self.respond_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)

    def stream_sse(self) -> None:
        client_id = self.headers.get("Mcp-Session-Id") or f"sse-{stdlib_secrets.token_hex(6)}"
        self.clients.touch(client_id, address=self.client_address[0], info=None, method="GET /mcp (sse)")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Mcp-Session-Id", client_id)
        self.end_headers()

        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                time.sleep(15)
                self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.clients.drop(client_id)

    # ---- POST --------------------------------------------------------------
    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/mcp":
            self.respond_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
            return
        if not self.authorized():
            self.reject()
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            request = json.loads(raw.decode("utf-8") or "{}")
        except Exception as exc:  # noqa: BLE001
            self.respond_json(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}},
                HTTPStatus.BAD_REQUEST,
            )
            return

        method = str(request.get("method") or "")
        client_id = self.headers.get("Mcp-Session-Id") or f"http-{self.client_address[0]}"
        info = ((request.get("params") or {}).get("clientInfo")) if method == "initialize" else None
        self.clients.touch(client_id, address=self.client_address[0], info=info, method=method)

        try:
            response = handle_request(request)
        except Exception as exc:  # noqa: BLE001 - a tool failure is a JSON-RPC error, not a 500
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"},
            }

        if response is None:
            # Notification (e.g. notifications/initialized): no body by spec.
            self.send_response(HTTPStatus.ACCEPTED)
            self.send_header("Mcp-Session-Id", client_id)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.respond_json(response, extra_headers={"Mcp-Session-Id": client_id})

    # ---- helpers -----------------------------------------------------------
    def respond_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


class McpHttpServer:
    """Start/stop wrapper so the desktop UI can own the server's lifetime."""

    def __init__(self, host: str, port: int, token: str = "", require_auth: bool = True) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.require_auth = require_auth
        self.clients = ClientRegistry()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        if self.require_auth and not self.token:
            raise ValueError("A bearer token is required when authentication is enabled.")

        registry = self.clients
        handler = type(
            "BoundMcpHttpHandler",
            (McpHttpHandler,),
            {"token": self.token, "require_auth": self.require_auth, "clients": registry},
        )
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="mcp-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self._thread = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "host": self.host,
            "port": self.port,
            "url": f"http://{self.host}:{self.port}/mcp",
            "auth": "bearer" if self.require_auth else "none",
            "tool_count": len(mcp_tools()),
            "clients": self.clients.list(),
        }


def new_token() -> str:
    return stdlib_secrets.token_urlsafe(32)


def run(host: str = "127.0.0.1", port: int = 8790, token: str = "", require_auth: bool = True) -> None:
    """Blocking runner for `python -m reception_crm.adapters.mcp_http`."""
    server = McpHttpServer(host, port, token=token, require_auth=require_auth)
    server.start()
    print(f"MCP HTTP server on http://{host}:{port}/mcp  (auth: {'bearer' if require_auth else 'none'})")
    print(f"Exposing {len(mcp_tools())} tools. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Run the Reception CRM MCP server over HTTP.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--token", default=os.getenv("RECEPTION_MCP_TOKEN", ""))
    parser.add_argument("--no-auth", action="store_true")
    args = parser.parse_args()

    run(args.host, args.port, token=args.token, require_auth=not args.no_auth)
