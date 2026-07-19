"""AI-PACS Agent Gateway — mobile / AI-client connectivity for the workstation.

The gateway lets an external agent client (the Android AI-PACS agent app, or any
MCP-capable AI client) pair with and drive this Windows workstation. It is a
**second transport** onto the SAME EchoMind ``CommandBus`` the in-app voice
assistant and the Test Control Server already use — it does NOT fork the command
registry, the adapters, or the permission gate.

Design at a glance
------------------
* **Reachability** — ``transport = "lan"`` (phone ⇄ PC on the same network,
  the PC never needs an inbound port opened by hand) or ``transport = "relay"``
  (the PC dials OUT to a rendezvous server you host, so the phone works
  off-network). Both feed the same :class:`~modules.agent_gateway.core.GatewayCore`.
* **Pairing** — the Agent settings tab shows a QR code carrying the connection
  endpoints, a single-use short-lived pairing code, and the server's TLS
  certificate fingerprint. The phone scans it, exchanges the code for a
  long-lived **device token** (bearer), and pins the certificate. No manual
  typing of IPs / tokens.
* **Security** — self-signed TLS (cert-pinned via the QR fingerprint) + bearer
  device tokens on every request. Feature is **default-OFF**; the server binds
  only when the user enables it in Settings. Device tokens live in the roaming
  user profile (hashed), never in the shipped config template.
* **MCP** — an MCP endpoint (Streamable-HTTP style JSON-RPC over POST) exposes
  every CommandBus action as an MCP *tool* and the operational agent docs as
  MCP *resources*, so an AI client learns which functions exist and how to call
  them without those documents living inside the Settings UI.

Everything here is import-light: importing this package pulls in stdlib +
``modules.agent_gateway`` pure helpers only. Qt / ``cryptography`` / ``segno`` /
``requests`` are imported lazily inside the components that need them, so a
disabled gateway has zero startup cost and the pure logic stays unit-testable
off-screen.

Flag: ``AIPACS_AGENT_GATEWAY`` (env) or ``config/agent_gateway/agent_gateway.json``
(``"enabled"``). See :mod:`modules.agent_gateway.feature_flags`.
"""
from __future__ import annotations

from .feature_flags import agent_gateway_enabled, gateway_config_summary

__all__ = ["agent_gateway_enabled", "gateway_config_summary"]
