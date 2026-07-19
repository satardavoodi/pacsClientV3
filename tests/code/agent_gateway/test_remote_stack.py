"""Tests for the REMOTE stack: E2E secure channel, WS relay framing, pairing v2.

Covers the architecture in
``docs/plans/architecture/REMOTE_CONNECTIVITY_ARCHITECTURE_2026-07-17.md``:
outbound rendezvous + zero-knowledge relay. Offscreen; no network, no Qt.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("cryptography")

from modules.agent_gateway import secure_channel as sc  # noqa: E402
from modules.agent_gateway.core import GatewayCore  # noqa: E402
from modules.agent_gateway.device_store import DeviceStore  # noqa: E402
from modules.agent_gateway.relay_ws import WebSocketRelayClient  # noqa: E402


def _pair_channels():
    ws_priv, ws_pub = sc.generate_keypair()
    dev_priv, dev_pub = sc.generate_keypair()
    salt = sc.new_salt()
    ws = sc.SecureChannel.for_role("workstation", ws_priv, dev_pub, salt)
    dev = sc.SecureChannel.for_role("device", dev_priv, ws_pub, salt)
    return ws, dev


# ── secure channel ───────────────────────────────────────────────────────────
def test_bidirectional_roundtrip():
    ws, dev = _pair_channels()
    assert dev.open(ws.seal(b"ping")) == b"ping"
    assert ws.open(dev.seal(b"pong")) == b"pong"


def test_replay_is_rejected():
    ws, dev = _pair_channels()
    frame = ws.seal(b"x")
    assert dev.open(frame) == b"x"
    with pytest.raises(sc.SecureChannelError):
        dev.open(frame)


def test_tampered_ciphertext_is_rejected():
    ws, dev = _pair_channels()
    bad = ws.seal(b"secret").to_dict()
    bad["ct"] = sc.b64e(sc.b64d(bad["ct"])[:-1] + b"\x00")
    with pytest.raises(sc.SecureChannelError):
        dev.open(bad)


def test_wrong_peer_key_cannot_decrypt():
    ws, _dev = _pair_channels()
    other_priv, _ = sc.generate_keypair()
    _, ws_pub = sc.generate_keypair()
    stranger = sc.SecureChannel.for_role("device", other_priv, ws_pub, sc.new_salt())
    with pytest.raises(sc.SecureChannelError):
        stranger.open(ws.seal(b"x"))


def test_nonces_never_repeat():
    ws, _ = _pair_channels()
    assert len({ws.seal(b"x").nonce for _ in range(300)}) == 300


def test_directions_use_independent_keys():
    """A frame must not be replayable back at its own sender."""
    ws, dev = _pair_channels()
    frame = ws.seal(b"x")
    dev.open(frame)
    fresh_ws, _ = _pair_channels()
    with pytest.raises(sc.SecureChannelError):
        fresh_ws.open(frame)


def test_channel_must_be_reused_not_rebuilt():
    """REGRESSION: rebuilding a channel restarts the counter at 1, so the peer
    rejects the second frame as a replay. Caught by the live integration run."""
    ws_priv, ws_pub = sc.generate_keypair()
    dev_priv, dev_pub = sc.generate_keypair()
    salt = sc.new_salt()
    dev = sc.SecureChannel.for_role("device", dev_priv, ws_pub, salt)

    def rebuilt():  # the WRONG pattern
        return sc.SecureChannel.for_role("workstation", ws_priv, dev_pub, salt)

    dev.open(rebuilt().seal(b"one"))
    with pytest.raises(sc.SecureChannelError):
        dev.open(rebuilt().seal(b"two"))

    # the RIGHT pattern: one long-lived channel
    dev2 = sc.SecureChannel.for_role("device", dev_priv, ws_pub, salt)
    persistent = sc.SecureChannel.for_role("workstation", ws_priv, dev_pub, salt)
    assert dev2.open(persistent.seal(b"one")) == b"one"
    assert dev2.open(persistent.seal(b"two")) == b"two"


def test_failed_open_does_not_advance_counter():
    """A forged frame must not be able to wedge the channel."""
    ws, dev = _pair_channels()
    good = ws.seal(b"real")
    forged = dict(good.to_dict())
    forged["ct"] = sc.b64e(sc.b64d(forged["ct"])[:-1] + b"\x01")
    with pytest.raises(sc.SecureChannelError):
        dev.open(forged)
    assert dev.open(good) == b"real"      # the genuine frame still works


def test_channel_exposes_lock_for_atomic_seal_send():
    ws, _ = _pair_channels()
    with ws.lock:
        assert ws.seal(b"x") is not None


# ── relay WS framing ─────────────────────────────────────────────────────────
class _StubCore:
    def handle(self, method, path, headers, body):
        from modules.agent_gateway.core import GatewayResponse

        return GatewayResponse.json({"ok": True, "path": path, "method": method})


def _client(provider=None):
    return WebSocketRelayClient(
        _StubCore(), ws_url="ws://example/agent/ws",
        workstation_id="ws_1", auth_token="t",
        secure_channel_provider=provider,
    )


def test_wrap_unwrap_clear_text():
    c = _client()
    inner = {"rid": "r1", "method": "GET", "path": "/health",
             "headers": {}, "body_b64": ""}
    got = c._unwrap({"payload": inner}, None)
    assert got["method"] == "GET" and got["path"] == "/health"
    out = c._wrap("r1", "", {"status": 200}, None)
    assert out["t"] == "msg" and "payload" in out and "ct" not in out


def test_wrap_unwrap_sealed():
    ws, dev = _pair_channels()
    c = _client()
    inner = {"rid": "r2", "method": "POST", "path": "/mcp",
             "headers": {"Authorization": "Bearer x"}, "body_b64": ""}
    frame = dev.seal(json.dumps(inner).encode())
    got = c._unwrap({"ct": frame.ct, "nonce": frame.nonce}, ws)
    assert got["path"] == "/mcp" and got["headers"]["Authorization"] == "Bearer x"

    sealed_out = c._wrap("r2", "dev_1", {"status": 200}, ws)
    assert "ct" in sealed_out and "payload" not in sealed_out
    assert json.loads(dev.open(sealed_out).decode())["status"] == 200


def test_transport_caches_channel_per_device():
    """The transport must not rebuild the channel per request even if the
    provider naively returns a new one each time."""
    calls = []

    def provider(device_id):
        calls.append(device_id)
        return _pair_channels()[0]

    c = _client(provider)
    first = c._channel("dev_A")
    second = c._channel("dev_A")
    assert first is second, "channel must be cached"
    assert calls == ["dev_A"], "provider must be consulted once per device"
    c._channel("dev_B")
    assert calls == ["dev_A", "dev_B"]


def test_no_device_id_means_clear_channel():
    assert _client(lambda d: _pair_channels()[0])._channel("") is None


# ── pairing v2 + core E2E handshake ──────────────────────────────────────────
def test_pairing_payload_carries_e2e_material():
    from modules.agent_gateway import pairing

    p = pairing.build_pairing_payload(
        code="AAAA1111", transport="relay", endpoints=["https://relay.example"],
        workstation_id="ws_9", workstation_pubkey="PUBKEY", key_salt="SALT",
    )
    assert p["wsid"] == "ws_9" and p["ws_pub"] == "PUBKEY" and p["salt"] == "SALT"
    back = pairing.decode_pairing_uri(pairing.encode_pairing_uri(p))
    assert back["ws_pub"] == "PUBKEY"


def test_pairing_payload_v1_compatible_without_e2e():
    from modules.agent_gateway import pairing

    p = pairing.build_pairing_payload(code="A", transport="lan", endpoints=[])
    for absent in ("wsid", "ws_pub", "salt"):
        assert absent not in p


def test_core_pair_returns_and_stores_e2e_material(tmp_path):
    store = DeviceStore(path=tmp_path / "d.json")
    core = GatewayCore(
        run_command=lambda a, e, m, c: {"ok": True, "action": a},
        device_store=store,
        list_actions=lambda: ["list_patients"],
        config={"mcp_path": "/mcp", "default_device_mode": "full"},
        key_provider=lambda: {"pubkey": "WSPUB", "salt": "SALT"},
    )
    code = core.issue_pairing_code()
    resp = core.handle("POST", "/pair", {}, json.dumps(
        {"code": code, "device_name": "Pixel", "device_pubkey": "DEVPUB"}).encode())
    body = json.loads(resp.body)
    assert body["ok"] and body["workstation_pubkey"] == "WSPUB" and body["salt"] == "SALT"

    material = store.channel_material(body["device_id"])
    assert material == {"device_pubkey": "DEVPUB", "key_salt": "SALT"}


def test_core_pair_without_key_provider_is_plain(tmp_path):
    """E2E off ⇒ no key material leaks into the response (v1 behaviour)."""
    core = GatewayCore(
        run_command=lambda a, e, m, c: {"ok": True, "action": a},
        device_store=DeviceStore(path=tmp_path / "d.json"),
        list_actions=lambda: [],
        config={"mcp_path": "/mcp", "default_device_mode": "full"},
    )
    code = core.issue_pairing_code()
    body = json.loads(core.handle("POST", "/pair", {}, json.dumps({"code": code}).encode()).body)
    assert body["ok"] and "workstation_pubkey" not in body


def test_channel_material_absent_for_unknown_or_revoked(tmp_path):
    store = DeviceStore(path=tmp_path / "d.json")
    rec = store.add_device("d", "tok", "full", device_pubkey="P", key_salt="S")
    assert store.channel_material(rec["device_id"]) is not None
    store.revoke(rec["device_id"])
    assert store.channel_material(rec["device_id"]) is None
    assert store.channel_material("nope") is None
