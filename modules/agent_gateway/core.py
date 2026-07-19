"""GatewayCore — transport-agnostic request brain.

Both transports (the LAN HTTPS server and the outbound relay client) frame every
incoming request as ``(method, path, headers, body)`` and hand it to
:meth:`GatewayCore.handle`, which returns a :class:`GatewayResponse`. The core
owns pairing-code issuance/redemption, bearer authentication against the
:class:`DeviceStore`, and MCP dispatch — so the two transports share ONE
security + routing implementation and neither can drift from the other.

Command execution is delegated to an injected ``run_command`` callable. The
service wires that to the Qt-GUI-thread dispatcher, which runs the real
``CommandBus`` (permission gate included). The core therefore contains no Qt and
no command logic of its own and is fully unit-testable off-screen.

Routes
------
* ``GET  /health``        → liveness + non-secret capability summary (no auth)
* ``POST /pair``          → redeem a pairing code → mint a device token
* ``POST <mcp_path>``     → JSON-RPC MCP endpoint (bearer required)
* ``GET  <mcp_path>``     → 405 (no server-initiated SSE stream in v1)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import pairing
from .config_store import normalize_device_mode
from .device_store import DeviceStore
from .docs_resources import DocsResourceProvider
from .mcp_bridge import McpBridge

logger = logging.getLogger(__name__)

# Device mode → CommandBus permission-gate ``agent_mode``.
#   full      → qa           (every action, no confirmation, still audited)
#   assistant → assistant    (reads free; server-write/destructive need confirm)
#   read_only → read_only    (reads only)
_MODE_TO_AGENT_MODE = {
    "full": "qa",
    "assistant": "assistant",
    "read_only": "read_only",
}


@dataclass
class GatewayResponse:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/json"
    headers: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def json(cls, obj: Any, status: int = 200) -> "GatewayResponse":
        return cls(
            status=status,
            body=json.dumps(obj, default=str, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

    @classmethod
    def text(cls, msg: str, status: int = 200) -> "GatewayResponse":
        return cls(status=status, body=msg.encode("utf-8"), content_type="text/plain")


class GatewayCore:
    def __init__(
        self,
        *,
        run_command: Callable[..., Dict[str, Any]],
        device_store: Optional[DeviceStore] = None,
        list_actions: Optional[Callable[[], List[str]]] = None,
        config: Optional[Dict[str, Any]] = None,
        docs_provider: Optional[DocsResourceProvider] = None,
        key_provider: Optional[Callable[[], Dict[str, str]]] = None,
    ) -> None:
        # ``key_provider()`` returns ``{"pubkey", "salt"}`` — the workstation's
        # X25519 public key + HKDF salt handed to a device at pairing so both
        # ends can derive the end-to-end keys. ``None`` = E2E disabled.
        self._key_provider = key_provider
        self._run_command = run_command
        self._devices = device_store or DeviceStore()
        self._list_actions = list_actions or (lambda: [])
        self._config = dict(config or {})
        self._docs = docs_provider or DocsResourceProvider(list_actions=self._list_actions)
        # Outstanding single-use pairing codes: code -> {"exp", "used"}.
        self._codes: Dict[str, Dict[str, Any]] = {}
        self._codes_lock = threading.RLock()

    # ── config helpers ────────────────────────────────────────────────
    @property
    def mcp_path(self) -> str:
        return str(self._config.get("mcp_path") or "/mcp")

    @property
    def default_device_mode(self) -> str:
        return normalize_device_mode(self._config.get("default_device_mode"))

    def update_config(self, config: Dict[str, Any]) -> None:
        self._config = dict(config or {})

    # ── pairing-code lifecycle (used by the Settings tab via the service) ─
    def issue_pairing_code(self, ttl_seconds: Optional[int] = None) -> str:
        ttl = int(ttl_seconds if ttl_seconds is not None
                  else self._config.get("pairing_ttl_seconds") or 300)
        code = pairing.new_pairing_code()
        with self._codes_lock:
            self._prune_codes_locked()
            self._codes[code] = {"exp": time.time() + max(30, ttl), "used": False}
        return code

    def _prune_codes_locked(self) -> None:
        now = time.time()
        dead = [c for c, m in self._codes.items()
                if m.get("used") or now > float(m.get("exp", 0))]
        for c in dead:
            self._codes.pop(c, None)

    def _redeem_code(self, code: str) -> bool:
        if not code:
            return False
        with self._codes_lock:
            meta = self._codes.get(code)
            if not meta:
                return False
            if meta.get("used") or time.time() > float(meta.get("exp", 0)):
                self._codes.pop(code, None)
                return False
            meta["used"] = True  # single use
            self._codes.pop(code, None)
            return True

    # ── device management passthrough (for the Settings tab) ──────────
    def devices(self) -> List[Dict[str, Any]]:
        return self._devices.list_devices()

    def set_device_mode(self, device_id: str, mode: str) -> bool:
        return self._devices.set_mode(device_id, mode)

    def revoke_device(self, device_id: str) -> bool:
        return self._devices.revoke(device_id)

    def remove_device(self, device_id: str) -> bool:
        return self._devices.remove(device_id)

    # ── request routing ───────────────────────────────────────────────
    def handle(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: bytes,
    ) -> GatewayResponse:
        method = (method or "GET").upper()
        # Strip any query string for routing.
        route = (path or "/").split("?", 1)[0].rstrip("/") or "/"
        h = {str(k).lower(): v for k, v in (headers or {}).items()}

        try:
            if route == "/health":
                return self._handle_health()
            if route == "/pair" and method == "POST":
                return self._handle_pair(body)
            if route == (self.mcp_path.rstrip("/") or "/mcp"):
                if method == "POST":
                    return self._handle_mcp(h, body)
                if method == "GET":
                    # Streamable-HTTP allows a server with no SSE stream to
                    # reject GET. v1 is request/response only.
                    return GatewayResponse.json(
                        {"ok": False, "error": "SSE stream not offered; use POST"},
                        status=405,
                    )
            return GatewayResponse.json({"ok": False, "error": "not found"}, status=404)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[AGENT_GATEWAY] request handling crashed")
            return GatewayResponse.json(
                {"ok": False, "error": f"internal error: {exc}"}, status=500
            )

    # ── routes ────────────────────────────────────────────────────────
    def _handle_health(self) -> GatewayResponse:
        try:
            n_actions = len(self._list_actions() or [])
        except Exception:
            n_actions = 0
        return GatewayResponse.json(
            {
                "ok": True,
                "server": "aipacs-agent-gateway",
                "version": "1.0.0",
                "mcp_path": self.mcp_path,
                "transport": str(self._config.get("transport") or "lan"),
                "tls": bool(self._config.get("tls_enabled", True)),
                "actions": n_actions,
                "paired_devices": len(self._devices.list_devices()),
            }
        )

    def _handle_pair(self, body: bytes) -> GatewayResponse:
        try:
            req = json.loads((body or b"{}").decode("utf-8") or "{}")
        except Exception:
            return GatewayResponse.json(
                {"ok": False, "error": "bad JSON"}, status=400
            )
        code = str(req.get("code") or "").strip().upper()
        device_name = str(req.get("device_name") or req.get("name") or "device").strip()
        device_pubkey = str(req.get("device_pubkey") or "").strip()
        if not self._redeem_code(code):
            return GatewayResponse.json(
                {"ok": False, "error": "invalid or expired pairing code"}, status=403
            )

        # End-to-end key material (optional — absent when E2E is off).
        key_material: Dict[str, str] = {}
        if self._key_provider is not None:
            try:
                key_material = self._key_provider() or {}
            except Exception:  # noqa: BLE001
                key_material = {}

        token = pairing.new_device_token()
        record = self._devices.add_device(
            device_name, token, self.default_device_mode,
            device_pubkey=device_pubkey,
            key_salt=str(key_material.get("salt") or ""),
        )
        logger.warning(
            "[AGENT_GATEWAY] device paired id=%s name=%r mode=%s e2e=%s",
            record.get("device_id"), record.get("name"), record.get("mode"),
            bool(device_pubkey and key_material.get("pubkey")),
        )
        out = {
            "ok": True,
            "device_id": record.get("device_id"),
            "device_token": token,  # returned exactly once
            "mode": record.get("mode"),
            "mcp_path": self.mcp_path,
            "server": {"name": "aipacs-agent-gateway", "version": "1.0.0"},
        }
        # Give the device what it needs to derive the shared keys.
        if key_material.get("pubkey"):
            out["workstation_pubkey"] = key_material["pubkey"]
            out["salt"] = key_material.get("salt", "")
        return GatewayResponse.json(out)

    def _handle_mcp(self, headers: Dict[str, str], body: bytes) -> GatewayResponse:
        device = self._authenticate(headers)
        if device is None:
            return GatewayResponse.json(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32001, "message": "unauthorized"}},
                status=401,
            )
        agent_mode = _MODE_TO_AGENT_MODE.get(
            normalize_device_mode(device.get("mode")), "read_only"
        )

        def _execute(action: str, entities: Dict[str, Any], *, confirmed: bool = False):
            return self._run_command(action, entities, agent_mode, confirmed)

        bridge = McpBridge(
            list_actions=self._list_actions,
            execute=_execute,
            docs_provider=self._docs,
        )

        try:
            message = json.loads((body or b"").decode("utf-8") or "null")
        except Exception:
            return GatewayResponse.json(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "parse error"}},
                status=400,
            )

        # JSON-RPC batch (list) or single object.
        if isinstance(message, list):
            responses = [r for r in (bridge.handle(m) for m in message) if r is not None]
            return GatewayResponse.json(responses)
        response = bridge.handle(message)
        if response is None:
            # A notification — 202 Accepted with no body, per streamable HTTP.
            return GatewayResponse(status=202, body=b"", content_type="application/json")
        return GatewayResponse.json(response)

    # ── auth ──────────────────────────────────────────────────────────
    def _authenticate(self, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
        auth = str(headers.get("authorization") or "")
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if not token:
            # Also accept an explicit device-token header for simple clients.
            token = str(headers.get("x-aipacs-device-token") or "").strip()
        if not token:
            return None
        return self._devices.authenticate(token)


__all__ = ["GatewayCore", "GatewayResponse"]
