#!/usr/bin/env python3
"""AI-PACS Agent Gateway — reference RELAY server (stdlib only).

Deploy this on a host both the workstation and the phone can reach (e.g. a small
VPS behind an HTTPS reverse proxy). It is a stateless-ish FORWARDER: the
workstation dials out and long-polls; the phone hits the public
``/client/<workstation_id>/...`` path; the relay pipes bytes between them. It
holds NO device tokens and validates NO application auth — device-token auth is
enforced end-to-end on the workstation, so a compromised relay cannot call
workstation functions.

This is a REFERENCE (correct + runnable, ~250 lines, no dependencies). For
production add: TLS (terminate at your reverse proxy), rate limiting, per-
workstation quotas, structured logging, and horizontal scaling via a shared
broker instead of in-process queues.

Protocol (see docs/for-future-agents/AGENT_MOBILE_PAIRING_PROTOCOL.md §8):

  Workstation (needs Authorization: Bearer <RELAY_TOKEN>):
    POST /agent/register            {"workstation_id": "..."}
    GET  /agent/poll?ws=<id>&wait=<s>   -> {"requests":[{rid,method,path,headers,body_b64}]}
    POST /agent/respond             {"rid","status","headers","body_b64"}

  Phone (public):
    ANY  /client/<workstation_id><path>   -> forwarded to the workstation

Run:  python relay_server.py --port 9000 --token "$(openssl rand -hex 24)"
Env:  AIPACS_RELAY_TOKEN, AIPACS_RELAY_PORT
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_MAX_BODY = 16 * 1024 * 1024
_CLIENT_TIMEOUT_S = 60.0  # how long a phone request waits for the workstation


class Channel:
    """One workstation channel: a queue of pending requests + response slots."""

    def __init__(self) -> None:
        self.lock = threading.Condition()
        self.pending: list[dict] = []             # requests awaiting the workstation
        self.responses: dict[str, dict] = {}      # rid -> response envelope
        self.last_seen = time.time()

    # phone side: enqueue a request, block until the workstation responds
    def submit(self, envelope: dict, timeout: float) -> dict | None:
        rid = envelope["rid"]
        with self.lock:
            self.pending.append(envelope)
            self.lock.notify_all()
            deadline = time.time() + timeout
            while rid not in self.responses:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self.lock.wait(timeout=remaining)
            return self.responses.pop(rid)

    # workstation side: long-poll for queued requests
    def poll(self, wait: float) -> list[dict]:
        with self.lock:
            self.last_seen = time.time()
            deadline = time.time() + wait
            while not self.pending:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self.lock.wait(timeout=remaining)
            batch = self.pending[:]
            self.pending.clear()
            return batch

    # workstation side: deliver a response
    def respond(self, envelope: dict) -> None:
        with self.lock:
            self.responses[envelope["rid"]] = envelope
            self.lock.notify_all()


class Relay:
    def __init__(self, token: str) -> None:
        self.token = token or ""
        self.channels: dict[str, Channel] = {}
        self.lock = threading.Lock()

    def channel(self, ws_id: str, create: bool = False) -> Channel | None:
        with self.lock:
            ch = self.channels.get(ws_id)
            if ch is None and create:
                ch = Channel()
                self.channels[ws_id] = ch
            return ch


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AIPacsAgentRelay/1.0"

    # ── helpers ───────────────────────────────────────────────────────
    def _body(self) -> bytes:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        n = max(0, min(n, _MAX_BODY))
        return self.rfile.read(n) if n else b""

    def _json(self, status: int, obj) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _raw(self, status: int, headers: dict, body: bytes) -> None:
        self.send_response(status)
        ct = headers.get("Content-Type", "application/json")
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body or b"")))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _authorized(self) -> bool:
        auth = str(self.headers.get("Authorization") or "")
        expected = self.server.relay.token  # type: ignore[attr-defined]
        if not expected:
            return True  # no token configured (dev only)
        return auth == f"Bearer {expected}"

    # ── routing ───────────────────────────────────────────────────────
    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method: str):
        relay: Relay = self.server.relay  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            # ── workstation endpoints (authenticated) ──
            if path == "/agent/register" and method == "POST":
                if not self._authorized():
                    return self._json(401, {"ok": False, "error": "unauthorized"})
                req = json.loads(self._body() or b"{}")
                ws = str(req.get("workstation_id") or "").strip()
                if not ws:
                    return self._json(400, {"ok": False, "error": "workstation_id required"})
                relay.channel(ws, create=True)
                return self._json(200, {"ok": True, "channel": ws})

            if path == "/agent/poll" and method == "GET":
                if not self._authorized():
                    return self._json(401, {"ok": False, "error": "unauthorized"})
                qs = parse_qs(parsed.query)
                ws = (qs.get("ws") or [""])[0]
                wait = float((qs.get("wait") or ["25"])[0])
                ch = relay.channel(ws, create=True)
                batch = ch.poll(min(50.0, max(1.0, wait)))
                return self._json(200, {"requests": batch})

            if path == "/agent/respond" and method == "POST":
                if not self._authorized():
                    return self._json(401, {"ok": False, "error": "unauthorized"})
                env = json.loads(self._body() or b"{}")
                ws = str(env.get("ws") or "")
                ch = relay.channel(ws) if ws else None
                # ws is optional in the envelope; fall back to scanning by rid
                if ch is None:
                    for c in list(relay.channels.values()):
                        c.respond(env)
                else:
                    ch.respond(env)
                return self._json(200, {"ok": True})

            # ── phone endpoint (public): /client/<ws_id><path> ──
            if path.startswith("/client/"):
                rest = path[len("/client/"):]
                ws, _, sub = rest.partition("/")
                ch = relay.channel(ws)
                if ch is None:
                    return self._json(502, {"ok": False, "error": "workstation not connected"})
                envelope = {
                    "rid": uuid.uuid4().hex,
                    "ws": ws,
                    "method": method,
                    "path": "/" + sub + (("?" + parsed.query) if parsed.query else ""),
                    "headers": {k: v for k, v in self.headers.items()},
                    "body_b64": base64.b64encode(self._body()).decode("ascii"),
                }
                resp = ch.submit(envelope, _CLIENT_TIMEOUT_S)
                if resp is None:
                    return self._json(504, {"ok": False, "error": "workstation timeout"})
                body = base64.b64decode(resp.get("body_b64") or "")
                return self._raw(int(resp.get("status") or 200), resp.get("headers") or {}, body)

            return self._json(404, {"ok": False, "error": "not found"})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "error": str(exc)})

    def log_message(self, fmt, *args):
        pass  # quiet by default


def main():
    ap = argparse.ArgumentParser(description="AI-PACS Agent Gateway reference relay")
    ap.add_argument("--port", type=int, default=int(os.environ.get("AIPACS_RELAY_PORT", "9000")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--token", default=os.environ.get("AIPACS_RELAY_TOKEN", ""))
    args = ap.parse_args()

    if not args.token:
        print("WARNING: no --token / AIPACS_RELAY_TOKEN set — workstation endpoints are UNAUTHENTICATED (dev only).")

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    httpd.relay = Relay(args.token)  # type: ignore[attr-defined]
    print(f"AI-PACS agent relay listening on {args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
