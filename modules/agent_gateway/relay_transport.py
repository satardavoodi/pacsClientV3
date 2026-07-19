"""Relay transport — outbound tunnel so the phone works off-network.

The owner chose cloud-relay reachability. Rather than open an inbound port on the
clinic firewall (a security liability), the workstation **dials OUT** to a
rendezvous server you host and long-polls it for requests. The phone talks HTTPS
to the relay; the relay forwards each request down the workstation's channel; the
workstation runs it through the SAME :class:`GatewayCore` and posts the response
back. Auth is end-to-end: the *device* bearer token is validated by GatewayCore
on the workstation (the relay never sees a valid device — it is a dumb pipe), and
the *workstation* authenticates to the relay with its own ``relay_auth_token``.

Wire protocol (reference relay server: ``tools/agent_relay/relay_server.py`` +
``docs/for-future-agents/AGENT_MOBILE_PAIRING_PROTOCOL.md`` §8):

* ``POST <relay>/agent/register``  ``{workstation_id}``  → claim the channel
* ``GET  <relay>/agent/poll?ws=<id>&wait=<s>``           → pending requests batch
* ``POST <relay>/agent/respond``   ``{ws, rid, status, headers, body_b64}``

Uses ``requests`` (already a dependency). The framing is pure + unit-tested; the
poll loop runs on a daemon thread and never blocks the GUI. The relay path is
inert until ``relay_base_url`` is configured — LAN remains the tested default.
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ── pure framing helpers (unit-testable) ─────────────────────────────────────
def decode_relay_request(d: Dict[str, Any]) -> Tuple[str, str, str, Dict[str, str], bytes]:
    """(rid, method, path, headers, body) from a relay request envelope."""
    rid = str(d.get("rid") or "")
    method = str(d.get("method") or "GET").upper()
    path = str(d.get("path") or "/")
    headers = {str(k): str(v) for k, v in (d.get("headers") or {}).items()}
    body_b64 = d.get("body_b64") or ""
    try:
        body = base64.b64decode(body_b64) if body_b64 else b""
    except Exception:
        body = b""
    return rid, method, path, headers, body


def encode_relay_response(rid: str, status: int, headers: Dict[str, str], body: bytes) -> Dict[str, Any]:
    return {
        "rid": rid,
        "status": int(status),
        "headers": dict(headers or {}),
        "body_b64": base64.b64encode(body or b"").decode("ascii"),
    }


class RelayClient:
    def __init__(
        self,
        core,
        *,
        base_url: str,
        workstation_id: str,
        auth_token: str,
        poll_timeout: int = 25,
    ) -> None:
        self._core = core
        self._base = (base_url or "").rstrip("/")
        self._ws_id = workstation_id or "workstation"
        self._auth = auth_token or ""
        self._poll_timeout = max(5, int(poll_timeout or 25))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._registered = False

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self) -> None:
        if not self._base:
            logger.info("[AGENT_GATEWAY] relay not configured; transport idle")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="agent-gateway-relay", daemon=True
        )
        self._thread.start()
        logger.warning("[AGENT_GATEWAY] relay client dialing %s (ws=%s)",
                       self._base, self._ws_id)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            try:
                self._thread.join(timeout=3.0)
            except Exception:
                pass
        self._thread = None
        logger.info("[AGENT_GATEWAY] relay client stopped")

    # ── poll loop (daemon thread) ─────────────────────────────────────
    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                if not self._registered:
                    self._register()
                self._poll_once()
                backoff = 1.0  # healthy → reset backoff
            except Exception as exc:  # noqa: BLE001
                self._registered = False
                logger.debug("[AGENT_GATEWAY] relay loop error: %s", exc)
                # Bounded exponential backoff on relay/network trouble.
                self._stop.wait(timeout=min(30.0, backoff))
                backoff = min(30.0, backoff * 2)

    def _session(self):
        import requests

        s = requests.Session()
        if self._auth:
            s.headers["Authorization"] = f"Bearer {self._auth}"
        return s

    def _register(self) -> None:
        import requests

        with self._session() as s:
            r = s.post(
                f"{self._base}/agent/register",
                json={"workstation_id": self._ws_id},
                timeout=15,
            )
            r.raise_for_status()
        self._registered = True
        logger.info("[AGENT_GATEWAY] relay channel registered ws=%s", self._ws_id)

    def _poll_once(self) -> None:
        with self._session() as s:
            r = s.get(
                f"{self._base}/agent/poll",
                params={"ws": self._ws_id, "wait": self._poll_timeout},
                timeout=self._poll_timeout + 10,
            )
            r.raise_for_status()
            data = r.json() if r.content else {}
            requests_batch = data.get("requests") or []
            for req in requests_batch:
                if self._stop.is_set():
                    return
                resp = self.process_one(req)
                s.post(f"{self._base}/agent/respond", json=resp, timeout=15)

    # ── one request → core → response envelope (pure-ish, testable) ───
    def process_one(self, req_envelope: Dict[str, Any]) -> Dict[str, Any]:
        rid, method, path, headers, body = decode_relay_request(req_envelope)
        try:
            resp = self._core.handle(method, path, headers, body)
            return encode_relay_response(
                rid, resp.status,
                {"Content-Type": resp.content_type, **(resp.headers or {})},
                resp.body,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[AGENT_GATEWAY] relay request handling failed")
            import json

            return encode_relay_response(
                rid, 500, {"Content-Type": "application/json"},
                json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"),
            )


__all__ = ["RelayClient", "decode_relay_request", "encode_relay_response"]
