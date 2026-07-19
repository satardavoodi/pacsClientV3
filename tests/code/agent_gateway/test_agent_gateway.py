"""Functional tests for the Agent Gateway core (offscreen, no Qt/network).

Covers the pure/testable surface: pairing wire format + tokens, the device
store, the MCP JSON-RPC bridge, the transport-agnostic GatewayCore routing +
auth + single-use pairing, relay framing, TLS identity, config/flags. The Qt
service + HTTP/relay transports are thin wrappers over these and are exercised
live on the source build.
"""
from __future__ import annotations

import json
import os

import pytest

from modules.agent_gateway import pairing
from modules.agent_gateway.core import GatewayCore, GatewayResponse
from modules.agent_gateway.device_store import DeviceStore
from modules.agent_gateway.mcp_bridge import McpBridge
from modules.agent_gateway import relay_transport


# ── pairing ──────────────────────────────────────────────────────────────────
def test_pairing_uri_roundtrip():
    payload = pairing.build_pairing_payload(
        code="ABCD2345",
        transport="lan",
        endpoints=["https://192.168.1.5:8760", "https://10.0.0.9:8760"],
        tls_fingerprint="sha256:AA:BB:CC",
        mcp_path="/mcp",
        workstation_name="Clinic PC",
        ttl_seconds=300,
    )
    uri = pairing.encode_pairing_uri(payload)
    assert uri.startswith("aipacs-agent://pair?d=")
    back = pairing.decode_pairing_uri(uri)
    assert back["code"] == "ABCD2345"
    assert back["endpoints"] == payload["endpoints"]
    assert back["tls_fp"] == "sha256:AA:BB:CC"
    assert back["mcp"] == "/mcp"


def test_pairing_uri_rejects_foreign_scheme():
    with pytest.raises(ValueError):
        pairing.decode_pairing_uri("https://evil.example.com/pair?d=abc")


def test_pairing_payload_expiry():
    payload = pairing.build_pairing_payload(
        code="X", transport="lan", endpoints=[], ttl_seconds=100, now=1000.0
    )
    assert not pairing.payload_is_expired(payload, now=1050.0)
    assert pairing.payload_is_expired(payload, now=2000.0)


def test_token_hash_and_verify_constant_time():
    tok = pairing.new_device_token()
    h = pairing.hash_token(tok)
    assert len(h) == 64  # sha256 hex
    assert pairing.verify_token(tok, h)
    assert not pairing.verify_token(tok + "x", h)
    assert not pairing.verify_token("", h)


def test_pairing_codes_are_unambiguous_and_unique():
    codes = {pairing.new_pairing_code() for _ in range(200)}
    assert len(codes) > 190  # effectively unique
    for c in codes:
        assert all(ch not in "01OIL" for ch in c)  # no ambiguous glyphs


# ── device store ─────────────────────────────────────────────────────────────
def _store(tmp_path):
    return DeviceStore(path=tmp_path / "devices.json")


def test_device_store_lifecycle(tmp_path):
    ds = _store(tmp_path)
    tok = pairing.new_device_token()
    rec = ds.add_device("Vahid Pixel", tok, "full")
    assert rec["mode"] == "full"
    # raw/hashed token never leaks out of the public record
    assert "token_sha256" not in rec and "token" not in rec

    auth = ds.authenticate(tok)
    assert auth and auth["device_id"] == rec["device_id"]
    assert ds.authenticate("nope") is None

    assert ds.set_mode(rec["device_id"], "read_only")
    assert ds.list_devices()[0]["mode"] == "read_only"

    assert ds.revoke(rec["device_id"])
    assert ds.authenticate(tok) is None  # revoked can't authenticate

    assert ds.remove(rec["device_id"])
    assert ds.list_devices() == []


def test_device_store_persists_only_hash(tmp_path):
    ds = _store(tmp_path)
    tok = pairing.new_device_token()
    ds.add_device("d", tok, "assistant")
    raw = (tmp_path / "devices.json").read_text(encoding="utf-8")
    assert tok not in raw  # the bearer token is never written to disk
    assert pairing.hash_token(tok) in raw


def test_unknown_device_mode_defaults_to_full(tmp_path):
    ds = _store(tmp_path)
    rec = ds.add_device("d", pairing.new_device_token(), "bogus-mode")
    assert rec["mode"] == "full"


# ── MCP bridge ───────────────────────────────────────────────────────────────
class _FakeDocs:
    def list_resources(self):
        return [{"uri": "aipacs-agent://functions", "name": "fns"}]

    def read_resource(self, uri):
        if uri == "aipacs-agent://functions":
            return {"uri": uri, "mimeType": "application/json", "text": "{}"}
        return None


def _bridge(executed):
    def execute(action, entities, *, confirmed=False):
        executed.append((action, entities, confirmed))
        return {"ok": True, "action": action, "data": {"echo": entities}}

    return McpBridge(
        list_actions=lambda: ["list_patients", "download_patient"],
        execute=execute,
        docs_provider=_FakeDocs(),
    )


def test_mcp_initialize_advertises_server():
    resp = _bridge([]).handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    info = resp["result"]["serverInfo"]
    assert info["name"] == "aipacs-agent-gateway"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_tools_list_maps_actions():
    resp = _bridge([]).handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"list_patients", "download_patient"}
    for tool in resp["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"


def test_mcp_tools_call_executes_and_reports_error_flag():
    executed = []
    resp = _bridge(executed).handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_patients", "arguments": {"entities": {"q": "smith"}}},
        }
    )
    assert executed == [("list_patients", {"q": "smith"}, False)]
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["data"]["echo"] == {"q": "smith"}


def test_mcp_tools_call_flat_arguments_and_confirmed():
    executed = []
    _bridge(executed).handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "download_patient", "arguments": {"patient_id": "P1", "confirmed": True}},
        }
    )
    action, entities, confirmed = executed[-1]
    assert action == "download_patient"
    assert entities == {"patient_id": "P1"}  # 'confirmed' stripped from entities
    assert confirmed is True


def test_mcp_resources_list_and_read():
    b = _bridge([])
    lst = b.handle({"jsonrpc": "2.0", "id": 5, "method": "resources/list"})
    assert lst["result"]["resources"][0]["uri"] == "aipacs-agent://functions"
    rd = b.handle(
        {"jsonrpc": "2.0", "id": 6, "method": "resources/read",
         "params": {"uri": "aipacs-agent://functions"}}
    )
    assert rd["result"]["contents"][0]["mimeType"] == "application/json"


def test_mcp_unknown_method_errors_and_notification_is_silent():
    b = _bridge([])
    err = b.handle({"jsonrpc": "2.0", "id": 7, "method": "bogus"})
    assert err["error"]["code"] == -32601
    # a notification (no id) never gets a response body
    assert b.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


# ── GatewayCore routing + auth ───────────────────────────────────────────────
def _core(tmp_path, executed):
    def run_command(action, entities, mode, confirmed):
        executed.append((action, entities, mode, confirmed))
        return {"ok": True, "action": action, "data": {"mode": mode}}

    return GatewayCore(
        run_command=run_command,
        device_store=DeviceStore(path=tmp_path / "dev.json"),
        list_actions=lambda: ["list_patients", "download_patient"],
        config={"mcp_path": "/mcp", "default_device_mode": "full", "pairing_ttl_seconds": 300},
    )


def test_core_health_is_unauthenticated(tmp_path):
    r = _core(tmp_path, []).handle("GET", "/health", {}, b"")
    body = json.loads(r.body)
    assert r.status == 200 and body["ok"] and body["actions"] == 2


def test_core_pairing_is_single_use(tmp_path):
    core = _core(tmp_path, [])
    code = core.issue_pairing_code()
    r = core.handle("POST", "/pair", {}, json.dumps({"code": code, "device_name": "Pixel"}).encode())
    body = json.loads(r.body)
    assert r.status == 200 and body["ok"] and body["device_token"]
    # same code cannot be redeemed twice
    r2 = core.handle("POST", "/pair", {}, json.dumps({"code": code}).encode())
    assert r2.status == 403


def test_core_bad_pairing_code_rejected(tmp_path):
    r = _core(tmp_path, []).handle("POST", "/pair", {}, json.dumps({"code": "ZZZZZZZZ"}).encode())
    assert r.status == 403


def test_core_mcp_requires_bearer(tmp_path):
    core = _core(tmp_path, [])
    r = core.handle("POST", "/mcp", {}, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode())
    assert r.status == 401


def test_core_authed_mcp_call_maps_full_mode_to_qa(tmp_path):
    executed = []
    core = _core(tmp_path, executed)
    code = core.issue_pairing_code()
    tok = json.loads(core.handle("POST", "/pair", {}, json.dumps({"code": code}).encode()).body)["device_token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    r = core.handle(
        "POST", "/mcp", hdr,
        json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": "list_patients", "arguments": {"entities": {"q": "a"}}}}).encode(),
    )
    assert r.status == 200
    # a "full" device maps to the permission-gate 'qa' agent_mode
    assert executed[-1][0] == "list_patients" and executed[-1][2] == "qa"


def test_core_read_only_device_maps_to_read_only_mode(tmp_path):
    executed = []
    core = GatewayCore(
        run_command=lambda a, e, m, c: executed.append((a, m)) or {"ok": True, "action": a},
        device_store=DeviceStore(path=tmp_path / "d.json"),
        list_actions=lambda: ["list_patients"],
        config={"mcp_path": "/mcp", "default_device_mode": "read_only"},
    )
    code = core.issue_pairing_code()
    tok = json.loads(core.handle("POST", "/pair", {}, json.dumps({"code": code}).encode()).body)["device_token"]
    core.handle("POST", "/mcp", {"Authorization": f"Bearer {tok}"},
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "list_patients", "arguments": {}}}).encode())
    assert executed[-1][1] == "read_only"


def test_core_get_mcp_rejected(tmp_path):
    assert _core(tmp_path, []).handle("GET", "/mcp", {}, b"").status == 405


def test_core_unknown_route_404(tmp_path):
    assert _core(tmp_path, []).handle("GET", "/nope", {}, b"").status == 404


# ── relay framing ────────────────────────────────────────────────────────────
def test_relay_frame_roundtrip():
    env = relay_transport.encode_relay_response("r1", 200, {"Content-Type": "application/json"}, b'{"ok":true}')
    rid, method, path, headers, body = relay_transport.decode_relay_request(
        {"rid": "r1", "method": "POST", "path": "/mcp",
         "headers": {"Authorization": "Bearer x"}, "body_b64": env["body_b64"]}
    )
    assert rid == "r1" and method == "POST" and path == "/mcp"
    assert headers["Authorization"] == "Bearer x"
    assert body == b'{"ok":true}'


def test_relay_process_one_uses_core(tmp_path):
    core = _core(tmp_path, [])
    rc = relay_transport.RelayClient(core, base_url="", workstation_id="w", auth_token="t")
    out = rc.process_one({"rid": "z", "method": "GET", "path": "/health", "headers": {}, "body_b64": ""})
    assert out["rid"] == "z" and out["status"] == 200


# ── TLS identity ─────────────────────────────────────────────────────────────
def test_tls_identity_generates_pinnable_cert(tmp_path):
    pytest.importorskip("cryptography")
    from modules.agent_gateway import tls_identity

    cert, key, fp = tls_identity.ensure_identity(san_hosts=["192.168.1.5"], data_dir=tmp_path, regenerate=True)
    assert fp.startswith("sha256:") and cert.exists() and key.exists()
    assert tls_identity.fingerprint_of(cert) == fp  # stable, re-readable
    # reuse (no regenerate) keeps the same fingerprint
    _c2, _k2, fp2 = tls_identity.ensure_identity(data_dir=tmp_path)
    assert fp2 == fp


# ── config / flags ───────────────────────────────────────────────────────────
def test_config_defaults_shape():
    from modules.agent_gateway import config_store as cs

    d = cs._defaults()
    assert d["enabled"] is False
    assert d["transport"] == "lan"
    assert d["default_device_mode"] == "full"
    assert d["relay_auth_token"] == ""  # never a baked-in secret


def test_feature_flag_env_override(monkeypatch):
    from modules.agent_gateway import feature_flags as ff

    monkeypatch.setenv("AIPACS_AGENT_GATEWAY", "1")
    assert ff.agent_gateway_enabled() is True
    monkeypatch.setenv("AIPACS_AGENT_GATEWAY", "0")
    assert ff.agent_gateway_enabled() is False


# ── address discovery / advertise ordering (multi-homed + VPN) ───────────────
def test_pinned_advertise_host_is_first_endpoint():
    """A pinned address must lead — the phone tries endpoints in order, and on a
    multi-homed PACS box the reachable one (e.g. the VPN tunnel) would otherwise
    sit behind a dozen unreachable modality subnets."""
    from modules.agent_gateway import net_utils

    ips = net_utils.all_lan_ipv4("192.168.24.41")
    assert ips[0] == "192.168.24.41"
    assert len(ips) == len(set(ips)), "no duplicates"


def test_advertise_host_may_be_a_hostname():
    from modules.agent_gateway import net_utils

    assert net_utils.all_lan_ipv4("agent.example.com")[0] == "agent.example.com"


def test_auto_mode_still_returns_addresses():
    from modules.agent_gateway import net_utils

    ips = net_utils.all_lan_ipv4()
    assert ips and all(isinstance(i, str) for i in ips)
    # loopback / link-local must never be advertised
    assert not any(i.startswith("127.") or i.startswith("169.254.") for i in ips)


def test_detected_ipv4_excludes_loopback_and_linklocal():
    from modules.agent_gateway import net_utils

    for ip in net_utils.detected_ipv4():
        assert not ip.startswith("127.")
        assert not ip.startswith("169.254.")


def test_usable_ipv4_filter():
    from modules.agent_gateway.net_utils import _is_usable_ipv4

    assert _is_usable_ipv4("192.168.24.41")
    assert not _is_usable_ipv4("127.0.0.1")
    assert not _is_usable_ipv4("169.254.3.133")  # APIPA
    assert not _is_usable_ipv4("0.0.0.0")
    assert not _is_usable_ipv4("")


def test_cert_regenerated_when_san_missing(tmp_path):
    """A cert that predates a new tunnel address must NOT be silently reused."""
    pytest.importorskip("cryptography")
    from modules.agent_gateway import tls_identity

    cert, _key, fp1 = tls_identity.ensure_identity(
        san_hosts=["192.168.1.131"], data_dir=tmp_path, regenerate=True
    )
    assert "192.168.1.131" in tls_identity.cert_san_values(cert)
    # same SANs -> reuse (stable fingerprint)
    _c, _k, fp_same = tls_identity.ensure_identity(
        san_hosts=["192.168.1.131"], data_dir=tmp_path
    )
    assert fp_same == fp1
    # a NEW address appears -> must regenerate and now cover it
    cert2, _k2, fp2 = tls_identity.ensure_identity(
        san_hosts=["192.168.1.131", "192.168.24.41"], data_dir=tmp_path
    )
    assert fp2 != fp1
    assert "192.168.24.41" in tls_identity.cert_san_values(cert2)


def test_normalize_helpers():
    from modules.agent_gateway import config_store as cs

    assert cs.normalize_transport("RELAY") == "relay"
    assert cs.normalize_transport("garbage") == "lan"
    assert cs.normalize_device_mode("Assistant") == "assistant"
    assert cs.normalize_device_mode("") == "full"
    assert cs.get_port({"port": 70000}) == cs.DEFAULT_PORT
