"""GW-1 — Agent Gateway fast bind (no reverse-DNS in server_bind).

Live evidence 2026-08-05 (pid 193888): stdlib ``HTTPServer.server_bind``
calls ``socket.getfqdn(host)`` on the bind address; with host "0.0.0.0"
that reverse-DNS lookup hung ~11.5 s INSIDE ``gethostbyaddr`` ON THE GUI
THREAD (F11 stall samples 20:35:45→20:35:56) because ``service.start()``
constructs the server synchronously during home-widget construction —
the bulk of the 18.5 s startup stall (STARTUP_STAGE home_widget ms=14203).

Pins:
  * flag parsing (default ON; 0/false/no/off disable),
  * the fast server binds WITHOUT ever calling socket.getfqdn,
  * the stdlib class DOES call it (reproduction of the avoided defect),
  * a real HTTP request still round-trips through GatewayHttpServer,
  * start() selects the server class from the flag (source pin),
  * the subclass overrides ONLY server_bind (minimal-change pin).
"""
from __future__ import annotations

import http.client
import inspect
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.agent_gateway import http_gateway as hg


class _StubResponse:
    status = 200
    body = b'{"ok":true}'
    content_type = "application/json"
    headers = {}


class _StubCore:
    def handle(self, method, path, headers, body):
        return _StubResponse()


# ── flag parsing ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("val,expected", [
    (None, True), ("", True), ("1", True), ("true", True), ("weird", True),
    ("0", False), ("false", False), ("no", False), ("off", False), (" 0 ", False),
    ("FALSE", False), ("Off", False),
])
def test_fast_bind_flag_parsing(monkeypatch, val, expected):
    if val is None:
        monkeypatch.delenv("AIPACS_GW_FAST_BIND", raising=False)
    else:
        monkeypatch.setenv("AIPACS_GW_FAST_BIND", val)
    assert hg._fast_bind_enabled() is expected


# ── the bind itself ──────────────────────────────────────────────────────
def test_fast_bind_never_calls_getfqdn(monkeypatch):
    calls = []

    def _spy(name=""):
        calls.append(name)
        return "spied.example"

    monkeypatch.setattr(socket, "getfqdn", _spy)
    httpd = hg._FastBindThreadingHTTPServer(("127.0.0.1", 0), hg._Handler)
    try:
        assert calls == [], "GW-1 fast bind must not resolve DNS"
        assert httpd.server_name == "127.0.0.1"
        assert httpd.server_port == httpd.server_address[1]
        assert httpd.server_port > 0
    finally:
        httpd.server_close()


def test_stdlib_server_does_call_getfqdn(monkeypatch):
    """Reproduction pin: the stdlib bind is what resolves DNS. If a future
    Python stops doing this, GW-1 becomes redundant — revisit then."""
    from http.server import ThreadingHTTPServer

    calls = []

    def _spy(name=""):
        calls.append(name)
        return "spied.example"

    monkeypatch.setattr(socket, "getfqdn", _spy)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), hg._Handler)
    try:
        assert calls == ["127.0.0.1"]
    finally:
        httpd.server_close()


# ── end-to-end: requests still served with the fast-bind class ───────────
def test_gateway_http_server_roundtrip_without_dns(monkeypatch):
    calls = []

    def _spy(name=""):
        calls.append(name)
        return "spied.example"

    monkeypatch.delenv("AIPACS_GW_FAST_BIND", raising=False)  # default ON
    monkeypatch.setattr(socket, "getfqdn", _spy)

    srv = hg.GatewayHttpServer(_StubCore(), "127.0.0.1", 0, ssl_context=None)
    srv.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        conn.request("GET", "/ping")
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        assert resp.status == 200
        assert data == b'{"ok":true}'
        assert calls == [], "default start() path must never touch DNS"
    finally:
        srv.stop()


# ── wiring / minimal-change pins ─────────────────────────────────────────
def test_start_selects_class_from_flag():
    src = inspect.getsource(hg.GatewayHttpServer.start)
    assert "_fast_bind_enabled()" in src
    assert "_FastBindThreadingHTTPServer" in src
    assert "else ThreadingHTTPServer" in src


def test_fast_bind_subclass_overrides_only_server_bind():
    own = {k for k in vars(hg._FastBindThreadingHTTPServer)
           if not k.startswith("__")}
    assert own == {"server_bind"}
