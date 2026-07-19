"""AgentGatewayService — lifecycle + control surface (Qt-side).

A single, app-scoped service object that the home panel installs at startup and
the Settings ▸ Agent tab drives. It owns:

* the GUI-thread command dispatcher (:mod:`gui_dispatch`),
* the transport-agnostic :class:`GatewayCore`,
* the active transport(s): the LAN HTTPS server and/or the outbound relay client,
* TLS identity (self-signed cert + pinning fingerprint),
* pairing-QR assembly and paired-device management for the UI.

Design rules honoured:
* **Default OFF / flag-gated** — ``install_service`` is cheap (no threads, no
  ports); nothing binds until :meth:`start` runs, and :meth:`start_if_enabled`
  only starts when :func:`feature_flags.agent_gateway_enabled` is true.
* **GUI never blocks** — all network I/O is on daemon threads; only the fast
  ``bus.execute`` runs on the GUI thread (marshalled, one turn at a time).
* **Clean teardown** — :meth:`stop` closes the server + joins threads; called
  from ``main.py``'s shutdown ``finally`` before the hard-exit failsafe.
* **No clinical-path coupling** — the service only reads ``get_bus()`` and calls
  the existing CommandBus; it never touches viewer/VTK/download internals.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_SERVICE: Optional["AgentGatewayService"] = None


def install_service(get_bus: Callable[[], Any]) -> "AgentGatewayService":
    """Create (once) the app-scoped gateway service. Does NOT start it."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = AgentGatewayService(get_bus)
    return _SERVICE


def get_service() -> Optional["AgentGatewayService"]:
    return _SERVICE


class AgentGatewayService:
    def __init__(self, get_bus: Callable[[], Any]) -> None:
        self._get_bus = get_bus
        self._dispatcher = None
        self._core = None
        self._http = None
        self._relay = None       # long-poll relay (fallback transport)
        self._relay_ws = None    # persistent WebSocket rendezvous (preferred)
        self._running = False
        self._last_error = ""
        self._tls_fingerprint = ""
        self._bound_port = 0
        self._channel_keys: Optional[Dict[str, str]] = None
        # device_id -> SecureChannel (session state; see _channel_for)
        self._channels: Dict[str, Any] = {}
        self._channels_lock = threading.RLock()

    # ── end-to-end key material (P4) ──────────────────────────────────
    def _channel_key_path(self):
        from .config_store import gateway_data_dir

        return gateway_data_dir() / "channel_key.json"

    def _ensure_channel_keys(self) -> Dict[str, str]:
        """Load (or create once) this workstation's X25519 identity + HKDF salt.

        The PRIVATE key never leaves this machine and is never sent anywhere —
        that is what keeps the relay zero-knowledge. Public key + salt travel in
        the pairing QR / redeem response.
        """
        if self._channel_keys:
            return self._channel_keys
        import json

        from . import secure_channel as sc

        path = self._channel_key_path()
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("priv") and data.get("pub") and data.get("salt"):
                    self._channel_keys = data
                    return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AGENT_GATEWAY] channel key read failed: %s", exc)

        priv, pub = sc.generate_keypair()
        data = {"priv": sc.b64e(priv), "pub": sc.b64e(pub), "salt": sc.b64e(sc.new_salt())}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            try:
                import os
                import stat

                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AGENT_GATEWAY] channel key persist failed: %s", exc)
        self._channel_keys = data
        return data

    def _key_provider(self) -> Dict[str, str]:
        """Public key + salt handed to a device at pairing."""
        keys = self._ensure_channel_keys()
        return {"pubkey": keys.get("pub", ""), "salt": keys.get("salt", "")}

    def _channel_for(self, device_id: str):
        """The :class:`SecureChannel` for a paired device (or ``None``).

        **Cached per device — never rebuilt per request.** A channel carries the
        nonce counter and the replay high-water mark; recreating it would restart
        the counter at 1 and the peer would rightly reject the next frame as a
        replay. Cached channels are dropped on stop()/restart, which is correct:
        a fresh session gets a fresh nonce prefix.
        """
        if not device_id or self._core is None:
            return None
        with self._channels_lock:
            cached = self._channels.get(device_id)
            if cached is not None:
                return cached
        try:
            from . import secure_channel as sc
            from .device_store import DeviceStore

            material = DeviceStore().channel_material(device_id)
            if not material:
                return None
            keys = self._ensure_channel_keys()
            channel = sc.SecureChannel.for_role(
                "workstation",
                sc.b64d(keys["priv"]),
                sc.b64d(material["device_pubkey"]),
                sc.b64d(material["key_salt"]),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[AGENT_GATEWAY] channel build failed for %s: %s", device_id, exc)
            return None
        with self._channels_lock:
            return self._channels.setdefault(device_id, channel)

    def _forget_channel(self, device_id: str) -> None:
        with self._channels_lock:
            self._channels.pop(device_id, None)

    # ── lifecycle ─────────────────────────────────────────────────────
    def start_if_enabled(self) -> bool:
        from .feature_flags import agent_gateway_enabled

        if not agent_gateway_enabled():
            logger.info("[AGENT_GATEWAY] disabled; not starting")
            return False
        return self.start()

    def start(self) -> bool:
        if self._running:
            return True
        self._last_error = ""
        try:
            from .config_store import (
                load_settings, normalize_transport, get_port, TRANSPORT_RELAY,
            )
            from .core import GatewayCore
            from .device_store import DeviceStore
            from .docs_resources import DocsResourceProvider
            from .gui_dispatch import make_gui_dispatcher
            from . import net_utils

            settings = load_settings()
            transport = normalize_transport(settings.get("transport"))

            # GUI-thread command dispatcher (must be built on the GUI thread).
            self._dispatcher = make_gui_dispatcher(self._get_bus)

            def _run_command(action, entities, agent_mode, confirmed):
                return self._dispatcher.run_command(action, entities, agent_mode, confirmed)

            list_actions = self._make_list_actions()
            e2e = bool(settings.get("e2e_encryption", True))
            core = GatewayCore(
                run_command=_run_command,
                device_store=DeviceStore(),
                list_actions=list_actions,
                config=self._core_config(settings),
                docs_provider=DocsResourceProvider(list_actions=list_actions),
                key_provider=self._key_provider if e2e else None,
            )
            self._core = core

            # TLS identity (self-signed; fingerprint goes into the QR).
            ssl_context = None
            self._tls_fingerprint = ""
            if bool(settings.get("tls_enabled", True)):
                try:
                    from . import tls_identity

                    # Cover EVERY address a client might dial — including the
                    # pinned advertise_host and any VPN/tunnel address — or a
                    # strict TLS client rejects the cert for that address.
                    san = net_utils.all_lan_ipv4(settings.get("advertise_host"))
                    cert_path, key_path, fp = tls_identity.ensure_identity(san_hosts=san)
                    ssl_context = tls_identity.build_ssl_context(cert_path, key_path)
                    self._tls_fingerprint = fp
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[AGENT_GATEWAY] TLS setup failed, "
                                   "falling back to plaintext: %s", exc)
                    ssl_context = None

            # LAN transport (always available so pairing works locally even in
            # relay mode; the QR chooses which endpoints to advertise).
            from .http_gateway import GatewayHttpServer

            host = net_utils.resolve_bind_host(settings.get("bind_scope"))
            port = get_port(settings)
            self._http = GatewayHttpServer(core, host, port, ssl_context=ssl_context)
            self._http.start()
            self._bound_port = self._http.port

            # ── Outbound rendezvous (remote access) ─────────────────────────
            # Preferred: ONE persistent WebSocket to the AIPACS relay, so the
            # workstation is reachable from anywhere with no static IP and no
            # port forwarding. Falls back to the long-poll transport when the
            # WS URL isn't set or the optional client library is missing.
            ws_url = str(settings.get("relay_ws_url") or "").strip()
            ws_id = (str(settings.get("relay_workstation_id") or "").strip()
                     or str(settings.get("workstation_name") or "").strip()
                     or "workstation")
            started_ws = False
            if transport == TRANSPORT_RELAY and ws_url:
                from .relay_ws import WebSocketRelayClient

                self._relay_ws = WebSocketRelayClient(
                    core,
                    ws_url=ws_url,
                    workstation_id=ws_id,
                    auth_token=str(settings.get("relay_workstation_secret") or ""),
                    secure_channel_provider=(self._channel_for if e2e else None),
                )
                started_ws = self._relay_ws.start()
                if not started_ws:
                    self._relay_ws = None

            if (not started_ws and transport == TRANSPORT_RELAY
                    and str(settings.get("relay_base_url") or "").strip()):
                from .relay_transport import RelayClient

                self._relay = RelayClient(
                    core,
                    base_url=str(settings.get("relay_base_url") or ""),
                    workstation_id=ws_id,
                    auth_token=str(settings.get("relay_auth_token") or ""),
                    poll_timeout=int(settings.get("relay_poll_timeout_seconds") or 25),
                )
                self._relay.start()

            self._running = True
            logger.warning("[AGENT_GATEWAY] started (transport=%s, tls=%s, port=%s)",
                           transport, bool(ssl_context), self._bound_port)
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            logger.exception("[AGENT_GATEWAY] start failed")
            self.stop()
            return False

    def stop(self) -> None:
        for comp in (self._relay_ws, self._relay, self._http):
            try:
                if comp is not None:
                    comp.stop()
            except Exception:
                pass
        self._relay_ws = None
        self._relay = None
        self._http = None
        self._running = False
        with self._channels_lock:
            self._channels.clear()   # new session ⇒ fresh nonce prefixes
        logger.info("[AGENT_GATEWAY] stopped")

    def restart(self) -> bool:
        self.stop()
        return self.start_if_enabled()

    # ── config helpers ────────────────────────────────────────────────
    def _core_config(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        from .config_store import normalize_transport, normalize_device_mode, get_port

        return {
            "transport": normalize_transport(settings.get("transport")),
            "mcp_path": str(settings.get("mcp_path") or "/mcp"),
            "mcp_enabled": bool(settings.get("mcp_enabled", True)),
            "tls_enabled": bool(settings.get("tls_enabled", True)),
            "default_device_mode": normalize_device_mode(settings.get("default_device_mode")),
            "pairing_ttl_seconds": int(settings.get("pairing_ttl_seconds") or 300),
            "port": get_port(settings),
        }

    def _make_list_actions(self) -> Callable[[], List[str]]:
        def _list() -> List[str]:
            try:
                bus = self._get_bus()
                if bus is not None:
                    return list(bus.actions())
            except Exception:
                pass
            return []
        return _list

    # ── pairing (used by the Settings tab) ────────────────────────────
    def build_pairing(self) -> Dict[str, Any]:
        """Issue a fresh single-use code and assemble the QR payload + image.

        Returns ``{ok, uri, payload, code, endpoints, fingerprint, qr_png,
        error}``. ``qr_png`` is PNG bytes (or ``None`` if ``segno`` is missing —
        the tab then shows the URI as selectable text).
        """
        if not self._running or self._core is None:
            return {"ok": False, "error": "gateway is not running"}
        try:
            from . import pairing, net_utils, qr
            from .config_store import (
                load_settings, normalize_transport, TRANSPORT_RELAY,
            )

            settings = load_settings()
            transport = normalize_transport(settings.get("transport"))
            scheme = "https" if self._tls_fingerprint else "http"
            port = self._bound_port or 0

            endpoints: List[str] = []
            relay_desc = None
            ws_url = str(settings.get("relay_ws_url") or "").strip()
            if transport == TRANSPORT_RELAY and (ws_url or str(settings.get("relay_base_url") or "").strip()):
                base = str(settings.get("relay_base_url") or "").rstrip("/")
                ws_id = (str(settings.get("relay_workstation_id") or "").strip()
                         or str(settings.get("workstation_name") or "").strip()
                         or "workstation")
                if ws_url:
                    # Rendezvous mode: the phone dials the RELAY, not this PC.
                    # There is deliberately no address of ours in the payload.
                    endpoints = [base or ws_url]
                    relay_desc = {"ws_url": ws_url, "base_url": base, "id": ws_id}
                else:
                    endpoints = [f"{base}/client/{ws_id}"]
                    relay_desc = {"url": base, "id": ws_id}
            else:
                # advertise_host (when pinned) leads the list, so a phone that
                # reaches this box over a VPN/tunnel tries the RIGHT address
                # first instead of walking a dozen unreachable modality subnets.
                for ip in net_utils.all_lan_ipv4(settings.get("advertise_host")):
                    endpoints.append(f"{scheme}://{ip}:{port}")

            code = self._core.issue_pairing_code(settings.get("pairing_ttl_seconds"))
            e2e = bool(settings.get("e2e_encryption", True))
            keys = self._key_provider() if e2e else {}
            payload = pairing.build_pairing_payload(
                code=code,
                transport=transport,
                endpoints=endpoints,
                tls_fingerprint=self._tls_fingerprint,
                mcp_path=str(settings.get("mcp_path") or "/mcp"),
                workstation_name=str(settings.get("workstation_name") or ""),
                relay=relay_desc,
                ttl_seconds=int(settings.get("pairing_ttl_seconds") or 300),
                workstation_id=(str(settings.get("relay_workstation_id") or "").strip()),
                workstation_pubkey=str(keys.get("pubkey") or ""),
                key_salt=str(keys.get("salt") or ""),
            )
            uri = pairing.encode_pairing_uri(payload)
            return {
                "ok": True,
                "uri": uri,
                "payload": payload,
                "code": code,
                "endpoints": endpoints,
                "fingerprint": self._tls_fingerprint,
                "qr_png": qr.qr_png_bytes(uri),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("[AGENT_GATEWAY] build_pairing failed")
            return {"ok": False, "error": str(exc)}

    # ── device management passthrough ─────────────────────────────────
    def devices(self) -> List[Dict[str, Any]]:
        return self._core.devices() if self._core else []

    def set_device_mode(self, device_id: str, mode: str) -> bool:
        return bool(self._core and self._core.set_device_mode(device_id, mode))

    def revoke_device(self, device_id: str) -> bool:
        return bool(self._core and self._core.revoke_device(device_id))

    def remove_device(self, device_id: str) -> bool:
        return bool(self._core and self._core.remove_device(device_id))

    # ── status ────────────────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._running

    def status(self) -> Dict[str, Any]:
        from .feature_flags import gateway_config_summary

        summary = gateway_config_summary()
        summary.update(
            {
                "running": self._running,
                "bound_port": self._bound_port,
                "tls_fingerprint": self._tls_fingerprint,
                "paired_devices": len(self.devices()),
                "last_error": self._last_error,
            }
        )
        # Remote rendezvous state — what the operator needs to see to know the
        # workstation is reachable from outside.
        if self._relay_ws is not None:
            summary["relay_ws"] = self._relay_ws.status()
        elif self._relay is not None:
            summary["relay_ws"] = {"configured": True, "connected": False,
                                   "library": "long-poll fallback"}
        return summary


__all__ = ["AgentGatewayService", "install_service", "get_service"]
