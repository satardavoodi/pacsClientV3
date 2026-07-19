"""Persistent outbound WebSocket relay client (P3) — reach the workstation anywhere.

THE CORE IDEA (see ``docs/plans/architecture/REMOTE_CONNECTIVITY_ARCHITECTURE_2026-07-17.md``):
the workstation never becomes reachable. It holds ONE **outbound** WSS connection
to the AIPACS relay and keeps it open. The relay addresses it by a stable
``workstation_id`` — never by IP:port — so a changing IP, a new Wi-Fi, a sleep/wake
or a move to mobile tethering is just a reconnect. Nothing to reconfigure, no
inbound port, works behind NAT/CGNAT/hospital firewalls because outbound 443 is
essentially always allowed.

Properties that matter:

* **Never blocks the GUI thread.** The socket lives on a daemon thread; each
  request is dispatched on a small worker pool so heartbeats keep flowing even
  while a command is executing on the Qt thread.
* **Reconnects forever** with exponential backoff + jitter (jitter matters: a
  clinic with many workstations must not stampede the relay after an outage).
* **End-to-end encrypted** when a :class:`SecureChannel` is supplied — the relay
  sees ``{rid, nonce, ct}`` and cannot read patient data.
* **Soft dependency.** Uses ``websocket-client`` if importable; if it is missing
  the gateway simply keeps using the long-poll :mod:`relay_transport`, so a build
  without the package still works.

The inner request/response envelope is deliberately identical to the long-poll
transport (``decode_relay_request`` / ``encode_relay_response``), so both
transports feed the SAME :class:`GatewayCore` and can never drift apart.
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from .relay_transport import decode_relay_request, encode_relay_response

logger = logging.getLogger(__name__)

# Frame types on the wire (kept tiny and explicit).
T_HELLO = "hello"
T_READY = "ready"
T_MSG = "msg"
T_PING = "ping"
T_PONG = "pong"
T_ERROR = "error"

_MAX_BACKOFF_S = 60.0
_PING_INTERVAL_S = 30
_PING_TIMEOUT_S = 10
_DISPATCH_WORKERS = 4


def websocket_available() -> bool:
    """True when the optional ``websocket-client`` package is importable."""
    try:
        import websocket  # noqa: F401

        return True
    except Exception:
        return False


class WebSocketRelayClient:
    """Outbound WSS client that pumps relay frames into :class:`GatewayCore`."""

    def __init__(
        self,
        core,
        *,
        ws_url: str,
        workstation_id: str,
        auth_token: str,
        secure_channel_provider: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """
        ``secure_channel_provider(device_id)`` returns a :class:`SecureChannel`
        for that device (or ``None`` to pass frames in clear — LAN/dev only).
        """
        self._core = core
        self._url = (ws_url or "").strip()
        self._ws_id = workstation_id or "workstation"
        self._auth = auth_token or ""
        self._channel_for = secure_channel_provider or (lambda _dev: None)

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws = None
        self._pool: Optional[ThreadPoolExecutor] = None
        self._connected = threading.Event()
        self._last_error = ""
        self._connect_count = 0
        # device_id -> SecureChannel. Cached HERE as well as in the service so a
        # provider that naively returns a fresh channel each call cannot break
        # the protocol: a channel holds the nonce counter + replay high-water
        # mark, and restarting it mid-session makes the peer reject frame #2.
        self._channels: dict = {}
        self._channels_lock = threading.RLock()

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self) -> bool:
        if not self._url:
            logger.info("[AGENT_GATEWAY] relay ws: no URL configured; idle")
            return False
        if not websocket_available():
            logger.warning(
                "[AGENT_GATEWAY] relay ws: 'websocket-client' not installed — "
                "falling back to the long-poll relay transport"
            )
            return False
        self._stop.clear()
        self._pool = ThreadPoolExecutor(
            max_workers=_DISPATCH_WORKERS, thread_name_prefix="agw-relay"
        )
        self._thread = threading.Thread(
            target=self._run_forever, name="agent-gateway-relay-ws", daemon=True
        )
        self._thread.start()
        logger.warning(
            "[AGENT_GATEWAY] relay ws: dialing %s (workstation_id=%s)",
            self._url, self._ws_id,
        )
        return True

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        if self._thread is not None:
            try:
                self._thread.join(timeout=3.0)
            except Exception:
                pass
        if self._pool is not None:
            try:
                self._pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:  # py<3.9
                self._pool.shutdown(wait=False)
            except Exception:
                pass
        self._thread = None
        self._pool = None
        self._connected.clear()
        logger.info("[AGENT_GATEWAY] relay ws stopped")

    # ── status ────────────────────────────────────────────────────────
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def status(self) -> dict:
        return {
            "configured": bool(self._url),
            "connected": self.is_connected(),
            "workstation_id": self._ws_id,
            "connect_count": self._connect_count,
            "last_error": self._last_error,
            "library": "websocket-client" if websocket_available() else None,
        }

    # ── connect loop (daemon thread) ──────────────────────────────────
    def _run_forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._connect_once()
                # A clean return means the socket closed; reconnect promptly.
                backoff = 1.0
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                logger.debug("[AGENT_GATEWAY] relay ws error: %s", exc)
            finally:
                self._connected.clear()
            if self._stop.is_set():
                break
            # Exponential backoff with FULL JITTER — many workstations must not
            # reconnect in lockstep after a relay outage.
            delay = min(_MAX_BACKOFF_S, backoff) * (0.5 + random.random() * 0.5)
            self._stop.wait(timeout=delay)
            backoff = min(_MAX_BACKOFF_S, max(1.0, backoff * 2))

    def _connect_once(self) -> None:
        import websocket  # local import: optional dependency

        headers = [f"Authorization: Bearer {self._auth}"] if self._auth else None
        ws = websocket.create_connection(
            self._url,
            header=headers,
            timeout=_PING_TIMEOUT_S,
            enable_multithread=True,
        )
        self._ws = ws
        try:
            ws.send(json.dumps({
                "t": T_HELLO, "role": "workstation",
                "workstation_id": self._ws_id, "auth": self._auth, "v": 1,
            }))
            ws.settimeout(_PING_INTERVAL_S + _PING_TIMEOUT_S)
            self._connect_count += 1
            self._connected.set()
            self._last_error = ""
            logger.warning("[AGENT_GATEWAY] relay ws CONNECTED (%s)", self._ws_id)

            last_ping = time.time()
            while not self._stop.is_set():
                try:
                    raw = ws.recv()
                except Exception as exc:  # timeout or socket error
                    # Heartbeat: prove the path is alive, else drop and redial.
                    if time.time() - last_ping > _PING_INTERVAL_S:
                        try:
                            ws.send(json.dumps({"t": T_PING}))
                            last_ping = time.time()
                            continue
                        except Exception:
                            raise
                    raise exc
                if not raw:
                    break
                self._on_frame(ws, raw)
        finally:
            try:
                ws.close()
            except Exception:
                pass
            self._ws = None
            self._connected.clear()

    # ── frame handling ───────────────────────────────────────────────
    def _on_frame(self, ws, raw) -> None:
        try:
            msg = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        except Exception:
            return
        kind = str(msg.get("t") or "")

        if kind == T_PING:
            self._safe_send(ws, {"t": T_PONG})
            return
        if kind in (T_PONG, T_READY):
            return
        if kind == T_ERROR:
            self._last_error = str(msg.get("code") or msg.get("message") or "error")
            logger.warning("[AGENT_GATEWAY] relay ws error frame: %s", self._last_error)
            return
        if kind != T_MSG:
            return

        # Dispatch off the receive loop so a slow command can't stall heartbeats.
        pool = self._pool
        if pool is None:
            return
        try:
            pool.submit(self._handle_msg, ws, msg)
        except Exception:
            self._handle_msg(ws, msg)

    def _handle_msg(self, ws, msg: dict) -> None:
        rid = str(msg.get("rid") or "")
        device_id = str(msg.get("device_id") or "")
        channel = self._channel(device_id)

        try:
            payload = self._unwrap(msg, channel)
            method, path, headers, body = (
                payload.get("method", "GET"), payload.get("path", "/"),
                payload.get("headers") or {}, payload.get("body", b""),
            )
            resp = self._core.handle(method, path, headers, body)
            out = encode_relay_response(
                rid, resp.status,
                {"Content-Type": resp.content_type, **(resp.headers or {})},
                resp.body,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[AGENT_GATEWAY] relay ws request failed")
            out = encode_relay_response(
                rid, 500, {"Content-Type": "application/json"},
                json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"),
            )
        # Seal and send ATOMICALLY. Several requests may be in flight on the
        # worker pool; the peer enforces strictly increasing nonce counters, so
        # the counter order must match the order bytes hit the socket. One
        # WebSocket + TCP preserves that order once we serialise here.
        if channel is not None:
            with channel.lock:
                self._safe_send(ws, self._wrap(rid, device_id, out, channel))
        else:
            self._safe_send(ws, self._wrap(rid, device_id, out, channel))

    def _channel(self, device_id: str):
        """Cached :class:`SecureChannel` for ``device_id`` (``None`` = clear)."""
        if not device_id:
            return None
        with self._channels_lock:
            hit = self._channels.get(device_id)
            if hit is not None:
                return hit
        try:
            built = self._channel_for(device_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[AGENT_GATEWAY] channel provider failed: %s", exc)
            return None
        if built is None:
            return None
        with self._channels_lock:
            return self._channels.setdefault(device_id, built)

    @staticmethod
    def _unwrap(msg: dict, channel) -> dict:
        """Return ``{method, path, headers, body}`` from a (possibly sealed) frame."""
        if channel is not None and msg.get("ct"):
            from .secure_channel import SealedFrame

            plain = channel.open(SealedFrame.from_dict(msg))
            inner = json.loads(plain.decode("utf-8"))
        else:
            inner = msg.get("payload") or msg
        _rid, method, path, headers, body = decode_relay_request(inner)
        return {"method": method, "path": path, "headers": headers, "body": body}

    @staticmethod
    def _wrap(rid: str, device_id: str, envelope: dict, channel) -> dict:
        """Seal the response when a channel exists; otherwise send it in clear."""
        if channel is not None:
            sealed = channel.seal(json.dumps(envelope).encode("utf-8"))
            out = {"t": T_MSG, "rid": rid, **sealed.to_dict()}
        else:
            out = {"t": T_MSG, "rid": rid, "payload": envelope}
        if device_id:
            out["device_id"] = device_id
        return out

    @staticmethod
    def _safe_send(ws, obj: dict) -> None:
        try:
            ws.send(json.dumps(obj))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[AGENT_GATEWAY] relay ws send failed: %s", exc)


__all__ = ["WebSocketRelayClient", "websocket_available"]
