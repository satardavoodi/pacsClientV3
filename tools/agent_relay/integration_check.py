#!/usr/bin/env python3
"""End-to-end check of the REMOTE stack: relay + workstation + simulated phone.

Proves the whole outbound-rendezvous architecture without any network setup:

  phone ──ws──► AIPACS relay ◄──ws── workstation (outbound only)
        sealed X25519/ChaCha20-Poly1305 frames the relay cannot read

Run from the repo root:  python tools/agent_relay/integration_check.py
Requires: aiohttp, websocket-client, requests, cryptography
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import requests  # noqa: E402
import websocket  # noqa: E402
from aiohttp import web  # noqa: E402

from modules.agent_gateway import secure_channel as sc  # noqa: E402
from modules.agent_gateway.core import GatewayCore  # noqa: E402
from modules.agent_gateway.device_store import DeviceStore  # noqa: E402
from modules.agent_gateway.relay_ws import WebSocketRelayClient  # noqa: E402

ADMIN = "admin-secret-token"
_ok = lambda m: print(f"  [OK] {m}")  # noqa: E731


def _load_relay():
    p = os.path.join(REPO, "tools", "agent_relay", "aipacs_relay.py")
    spec = importlib.util.spec_from_file_location("aipacs_relay", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    tmp = tempfile.mkdtemp()
    relay_mod = _load_relay()
    port_holder = []

    def run_relay():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = relay_mod.build_app(os.path.join(tmp, "relay.sqlite3"), ADMIN)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", 0)
        loop.run_until_complete(site.start())
        port_holder.append(list(runner.addresses)[0][1])
        loop.run_forever()

    threading.Thread(target=run_relay, daemon=True).start()
    for _ in range(100):
        if port_holder:
            break
        time.sleep(0.05)
    port = port_holder[0]
    base = f"http://127.0.0.1:{port}"
    assert requests.get(base + "/health", timeout=5).json()["ok"]
    _ok(f"relay running on {base}")

    # P1 — provision the workstation identity (note: no IP is ever stored)
    reg = requests.post(
        base + "/api/workstations/register", json={"display_name": "Clinic PC"},
        headers={"Authorization": f"Bearer {ADMIN}"}, timeout=5).json()
    wsid, wssecret = reg["workstation_id"], reg["workstation_secret"]
    _ok(f"workstation registered: {wsid}")

    # Workstation side: E2E identity + GatewayCore + outbound WS
    ws_priv, ws_pub = sc.generate_keypair()
    salt = sc.new_salt()
    store = DeviceStore(path=os.path.join(tmp, "devices.json"))
    executed = []
    core = GatewayCore(
        run_command=lambda a, e, m, c: executed.append((a, m)) or
        {"ok": True, "action": a, "data": {"mode": m, "rss_mb": 493.0}},
        device_store=store,
        list_actions=lambda: ["list_patients", "open_patient", "snapshot_resources"],
        config={"mcp_path": "/mcp", "default_device_mode": "full"},
        key_provider=lambda: {"pubkey": sc.b64e(ws_pub), "salt": sc.b64e(salt)},
    )

    def channel_for(device_id):
        m = store.channel_material(device_id)
        if not m:
            return None
        return sc.SecureChannel.for_role(
            "workstation", ws_priv, sc.b64d(m["device_pubkey"]), sc.b64d(m["key_salt"]))

    client = WebSocketRelayClient(
        core, ws_url=f"ws://127.0.0.1:{port}/agent/ws",
        workstation_id=wsid, auth_token=wssecret,
        secure_channel_provider=channel_for)
    assert client.start(), "ws client did not start"
    for _ in range(100):
        if client.is_connected():
            break
        time.sleep(0.05)
    assert client.is_connected(), "workstation never connected"
    _ok("workstation holds an OUTBOUND WebSocket to the relay")
    assert requests.get(f"{base}/api/workstations/{wsid}/status", timeout=5).json()["online"]
    _ok("relay reports the workstation online (routed by id, not IP)")

    # Pairing token for the QR
    tok = requests.post(
        base + "/api/pair/token",
        json={"pubkey": sc.b64e(ws_pub), "salt": sc.b64e(salt)},
        headers={"Authorization": f"Bearer {wssecret}", "X-Workstation-Id": wsid},
        timeout=5).json()

    # PHONE — redeem at the relay
    dev_priv, dev_pub = sc.generate_keypair()
    red = requests.post(base + "/api/pair/redeem", json={
        "token": tok["token"], "device_name": "Pixel",
        "device_pubkey": sc.b64e(dev_pub)}, timeout=5).json()
    assert red["ok"], red
    _ok(f"phone paired with relay: {red['device_id']}")

    pws = websocket.create_connection(f"ws://127.0.0.1:{port}/device/ws", timeout=10)
    pws.send(json.dumps({"t": "hello", "device_id": red["device_id"], "auth": red["device_token"]}))
    assert json.loads(pws.recv())["workstation_online"] is True
    _ok("phone connected to relay; workstation reachable")

    def http_req(method, path, headers, body):
        return {"rid": "x", "method": method, "path": path, "headers": headers,
                "body_b64": base64.b64encode(body).decode()}

    def rpc(inner, rid, channel=None, device_id=None):
        frame = {"t": "msg", "rid": rid}
        if channel is not None:
            frame.update(channel.seal(json.dumps(inner).encode()).to_dict())
        else:
            frame["payload"] = inner
        if device_id:
            frame["device_id"] = device_id
        pws.send(json.dumps(frame))
        return json.loads(pws.recv())

    # Step 1: gateway-level /pair IN CLEAR (carries only a code + public key —
    # no clinical data — because the workstation cannot know our key yet).
    code = core.issue_pairing_code()
    r1 = rpc(http_req("POST", "/pair", {}, json.dumps(
        {"code": code, "device_name": "Pixel", "device_pubkey": sc.b64e(dev_pub)}).encode()), "r1")
    body1 = json.loads(base64.b64decode(r1["payload"]["body_b64"]).decode())
    assert body1["ok"] and body1.get("workstation_pubkey"), body1
    gw_dev_id, gw_token = body1["device_id"], body1["device_token"]
    _ok("gateway pairing completed THROUGH the relay tunnel")

    # Step 2: everything after this is sealed end-to-end.
    chan = sc.SecureChannel.for_role(
        "device", dev_priv, sc.b64d(body1["workstation_pubkey"]), sc.b64d(body1["salt"]))
    r2 = rpc(http_req("POST", "/mcp", {"Authorization": f"Bearer {gw_token}"},
                      json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()),
             "r2", channel=chan, device_id=gw_dev_id)
    assert "ct" in r2 and "payload" not in r2, "response was NOT encrypted"
    env = json.loads(chan.open(r2).decode())
    names = sorted(t["name"] for t in json.loads(
        base64.b64decode(env["body_b64"]).decode())["result"]["tools"])
    _ok(f"SEALED tools/list over the relay -> {names}")

    r3 = rpc(http_req("POST", "/mcp", {"Authorization": f"Bearer {gw_token}"},
                      json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": "snapshot_resources",
                                             "arguments": {"entities": {}}}}).encode()),
             "r3", channel=chan, device_id=gw_dev_id)
    env3 = json.loads(chan.open(r3).decode())
    inner = json.loads(json.loads(base64.b64decode(env3["body_b64"]).decode())
                       ["result"]["content"][0]["text"])
    assert inner["ok"] and inner["action"] == "snapshot_resources", inner
    _ok(f"SEALED tools/call executed on the workstation (mode={inner['data']['mode']})")
    assert executed and executed[-1][0] == "snapshot_resources"

    # The relay must never have seen plaintext.
    assert "ct" in r2 and "ct" in r3
    _ok("relay only ever forwarded opaque ciphertext")

    pws.close()
    client.stop()
    print("\nREMOTE_E2E_INTEGRATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
