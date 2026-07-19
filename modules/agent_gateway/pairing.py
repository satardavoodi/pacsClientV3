"""Pairing primitives — pure stdlib, unit-testable off-screen.

The pairing flow (see ``docs/pipelines/agent-gateway.md`` and
``docs/for-future-agents/AGENT_MOBILE_PAIRING_PROTOCOL.md``):

1. The workstation shows a QR built by :func:`build_pairing_payload` /
   :func:`encode_pairing_uri`. It carries the reachable endpoints, a **single-use
   short-lived pairing code**, the TLS certificate fingerprint (for pinning),
   and the MCP path — everything the phone needs, so the user types nothing.
2. The phone scans it and POSTs the ``code`` (plus a device name) to ``/pair``.
3. The workstation validates the code (unused + unexpired), mints an opaque
   **device token** with :func:`new_device_token`, stores only its hash
   (:func:`hash_token`), and returns the token once. The phone stores it and
   sends ``Authorization: Bearer <token>`` on every later request.

This module is intentionally free of Qt / network / crypto-library imports so
the wire format and the token/hariding logic can be tested in the offscreen
lane. Randomness uses :mod:`secrets`; hashing uses :mod:`hashlib` (SHA-256).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

PAIRING_URI_SCHEME = "aipacs-agent"
PAIRING_PAYLOAD_TYPE = "aipacs-agent-pair"
PAYLOAD_VERSION = 1

# Pairing codes: short, human-glanceable, unambiguous alphabet (no 0/O/1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8


def new_pairing_code() -> str:
    """A single-use pairing code (also embedded in the QR)."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


def new_device_token() -> str:
    """An opaque, high-entropy bearer token handed to a paired device once."""
    return secrets.token_urlsafe(32)


def new_device_id() -> str:
    return "dev_" + secrets.token_hex(8)


def hash_token(token: str) -> str:
    """SHA-256 hex of a token. Only the hash is persisted; the raw token is
    shown to the device exactly once."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def verify_token(token: str, token_sha256: str) -> bool:
    """Constant-time compare of ``token`` against a stored hash."""
    if not token or not token_sha256:
        return False
    return hmac.compare_digest(hash_token(token), str(token_sha256))


def build_pairing_payload(
    *,
    code: str,
    transport: str,
    endpoints: List[str],
    tls_fingerprint: str = "",
    mcp_path: str = "/mcp",
    workstation_name: str = "",
    relay: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = 300,
    now: Optional[float] = None,
    workstation_id: str = "",
    workstation_pubkey: str = "",
    key_salt: str = "",
) -> Dict[str, Any]:
    """Assemble the (JSON-serializable) QR payload.

    ``endpoints`` are fully-qualified base URLs the phone may try, in order
    (e.g. ``["https://192.168.1.20:8760"]`` for LAN, or the relay entry URL for
    relay). ``tls_fingerprint`` is ``"sha256:AA:BB:.."`` for certificate pinning
    (empty when TLS is off). ``relay`` carries the rendezvous descriptor when
    ``transport == "relay"``.

    **v2 additions (end-to-end encryption, 2026-07-17).** When the workstation
    runs the E2E channel it also publishes:

    * ``wsid``   — the stable workstation id the relay routes by (never an IP);
    * ``ws_pub`` — its X25519 public key (base64url);
    * ``salt``   — the HKDF salt for this pairing.

    The phone replies with its own public key at redeem time, and both sides
    derive the shared keys. These keys are what make the relay a zero-knowledge
    conduit. The fields are OPTIONAL: a v1 client that ignores them still pairs
    over LAN exactly as before, so this is backwards compatible.
    """
    ts = time.time() if now is None else now
    payload: Dict[str, Any] = {
        "v": PAYLOAD_VERSION,
        "typ": PAIRING_PAYLOAD_TYPE,
        "code": code,
        "transport": (transport or "lan").strip().lower(),
        "endpoints": list(endpoints or []),
        "mcp": mcp_path or "/mcp",
        "name": workstation_name or "",
        "iat": int(ts),
        "exp": int(ts + max(30, int(ttl_seconds or 300))),
    }
    if tls_fingerprint:
        payload["tls_fp"] = tls_fingerprint
    if relay:
        payload["relay"] = dict(relay)
    if workstation_id:
        payload["wsid"] = workstation_id
    if workstation_pubkey:
        payload["ws_pub"] = workstation_pubkey
    if key_salt:
        payload["salt"] = key_salt
    return payload


def encode_pairing_uri(payload: Dict[str, Any]) -> str:
    """Compact single-string form for the QR: ``aipacs-agent://pair?d=<b64url>``.

    The whole payload is base64url-encoded JSON so any QR/deep-link scanner can
    round-trip it without worrying about reserved characters.
    """
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{PAIRING_URI_SCHEME}://pair?d={b64}"


def decode_pairing_uri(uri: str) -> Dict[str, Any]:
    """Inverse of :func:`encode_pairing_uri`. Raises ValueError on a bad URI."""
    parsed = urlparse(uri or "")
    if parsed.scheme != PAIRING_URI_SCHEME:
        raise ValueError(f"not an {PAIRING_URI_SCHEME} URI")
    qs = parse_qs(parsed.query)
    vals = qs.get("d") or []
    if not vals:
        raise ValueError("missing payload")
    b64 = vals[0]
    pad = "=" * (-len(b64) % 4)
    raw = base64.urlsafe_b64decode(b64 + pad)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("typ") != PAIRING_PAYLOAD_TYPE:
        raise ValueError("unexpected payload type")
    return data


def payload_is_expired(payload: Dict[str, Any], now: Optional[float] = None) -> bool:
    ts = time.time() if now is None else now
    try:
        return ts > float(payload.get("exp", 0))
    except Exception:
        return True


__all__ = [
    "PAIRING_URI_SCHEME",
    "PAIRING_PAYLOAD_TYPE",
    "PAYLOAD_VERSION",
    "new_pairing_code",
    "new_device_token",
    "new_device_id",
    "hash_token",
    "verify_token",
    "build_pairing_payload",
    "encode_pairing_uri",
    "decode_pairing_uri",
    "payload_is_expired",
]
