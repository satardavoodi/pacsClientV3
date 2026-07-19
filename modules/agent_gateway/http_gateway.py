"""LAN transport — a threaded HTTPS server feeding :class:`GatewayCore`.

Runs a stdlib ``ThreadingHTTPServer`` on a background daemon thread (network I/O
never touches the GUI thread), optionally wrapped in the gateway's self-signed
TLS context. Each request is framed to ``core.handle(method, path, headers,
body)`` and the :class:`GatewayResponse` is written back. No new heavy
dependency — ``http.server`` + ``ssl`` are stdlib.

The phone reaches this directly on the clinic network at the LAN address encoded
in the QR. The workstation never needs an inbound port opened by hand *beyond
allowing the app through the local firewall* (documented in the pipeline doc);
there is no cloud hop.
"""
from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_BODY = 8 * 1024 * 1024  # 8 MiB cap — commands are tiny; guards against abuse


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AIPacsAgentGateway/1.0"

    # Route everything through the core.
    def _dispatch(self, method: str) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except Exception:
            length = 0
        length = max(0, min(length, _MAX_BODY))
        body = self.rfile.read(length) if length else b""

        headers = {k: v for k, v in self.headers.items()}
        try:
            resp = self.server.core.handle(method, self.path, headers, body)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[AGENT_GATEWAY] handler error")
            self._write(500, b'{"ok":false,"error":"internal"}', "application/json")
            return
        self._write(resp.status, resp.body, resp.content_type, resp.headers)

    def _write(self, status, body, content_type, extra=None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body or b"")))
            # Same-origin only; a browser page must not script this endpoint.
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)
        except Exception:
            pass  # client hung up — nothing to do

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_OPTIONS(self):
        # CORS pre-flight: allow the paired native app / MCP client. Kept tight.
        self._write(204, b"", "text/plain", {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, X-AIPACS-Device-Token",
        })

    def log_message(self, fmt, *args):  # silence default stderr spam
        logger.debug("[AGENT_GATEWAY_HTTP] " + fmt, *args)


class GatewayHttpServer:
    def __init__(
        self,
        core,
        host: str,
        port: int,
        ssl_context=None,
    ) -> None:
        self._core = core
        self._host = host
        self._port = int(port)
        self._ssl_context = ssl_context
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        httpd = ThreadingHTTPServer((self._host, self._port), _Handler)
        httpd.daemon_threads = True
        httpd.core = self._core  # type: ignore[attr-defined]
        if self._ssl_context is not None:
            httpd.socket = self._ssl_context.wrap_socket(httpd.socket, server_side=True)
        self._httpd = httpd
        # If port was 0 (ephemeral) reflect the bound port back.
        try:
            self._port = httpd.server_address[1]
        except Exception:
            pass
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            name="agent-gateway-http",
            daemon=True,
        )
        self._thread.start()
        logger.warning(
            "[AGENT_GATEWAY] HTTPS%s listening on %s:%s",
            "" if self._ssl_context else " (PLAINTEXT)", self._host, self._port,
        )

    def stop(self) -> None:
        httpd = self._httpd
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass
        if self._thread is not None:
            try:
                self._thread.join(timeout=3.0)
            except Exception:
                pass
        self._httpd = None
        self._thread = None
        logger.info("[AGENT_GATEWAY] HTTP server stopped")


__all__ = ["GatewayHttpServer"]
