#!/usr/bin/env python3
"""AIPACS Agent Relay — identity registry + WebSocket rendezvous (P1 + P2).

Deploy this on the AIPACS cloud (any small host behind HTTPS). It is the
*rendezvous* that lets a phone reach a workstation that has **no static IP, no
port forwarding and no fixed location**.

How it works (see docs/plans/architecture/REMOTE_CONNECTIVITY_ARCHITECTURE_2026-07-17.md):

* The workstation opens ONE **outbound** WebSocket to ``/agent/ws`` and keeps it
  open. The relay addresses it by a stable ``workstation_id`` — **never by IP**.
  A changing IP is therefore invisible: it is just a reconnect.
* The phone opens a WebSocket to ``/device/ws`` and is routed to its paired
  workstation.
* The relay forwards frames. With E2E enabled those frames are **opaque
  ciphertext** — this server cannot read patient data, by construction.

DESIGN RULE — **conduit, not a store.** Messages are forwarded in flight and
never written to disk. Only identity/pairing rows are persisted. Keeping it a
pure conduit is deliberate: the moment a relay persists clinical traffic it
changes its privacy and regulatory position entirely.

Run
---
    pip install -r requirements.txt
    python aipacs_relay.py --port 9000 --admin-token "$(openssl rand -hex 24)"

Put it behind HTTPS (nginx/Caddy). Workstations then use
``wss://relay.aipacs.example/agent/ws``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import sqlite3
import time
from typing import Any, Dict, Optional

from aiohttp import WSMsgType, web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aipacs-relay")

PAIRING_TTL_S = 300          # single-use pairing token lifetime
DEVICE_REQUEST_TIMEOUT_S = 60


# ── storage: identity only, never messages ───────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS workstations (
    workstation_id TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL DEFAULT '',
    secret_hash    TEXT NOT NULL,
    pubkey         TEXT NOT NULL DEFAULT '',
    created        INTEGER NOT NULL,
    last_seen      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS devices (
    device_id      TEXT PRIMARY KEY,
    workstation_id TEXT NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    token_hash     TEXT NOT NULL,
    pubkey         TEXT NOT NULL DEFAULT '',
    mode           TEXT NOT NULL DEFAULT 'full',
    created        INTEGER NOT NULL,
    revoked        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pairing_tokens (
    token          TEXT PRIMARY KEY,
    workstation_id TEXT NOT NULL,
    pubkey         TEXT NOT NULL DEFAULT '',
    salt           TEXT NOT NULL DEFAULT '',
    expires_at     INTEGER NOT NULL,
    used_at        INTEGER NOT NULL DEFAULT 0
);
"""
# NOTE: there is deliberately NO ip/endpoint/port column anywhere. The relay
# never needs to know where a workstation is — only that it is connected.


def _hash(secret: str) -> str:
    import hashlib

    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


class Registry:
    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._lock = asyncio.Lock()

    async def _run(self, fn, *a):
        async with self._lock:
            return await asyncio.get_running_loop().run_in_executor(None, fn, *a)

    # workstations
    def _create_ws(self, display_name: str, pubkey: str):
        wid = "ws_" + secrets.token_hex(8)
        secret = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO workstations(workstation_id,display_name,secret_hash,pubkey,created)"
            " VALUES(?,?,?,?,?)",
            (wid, display_name, _hash(secret), pubkey, int(time.time())),
        )
        self.db.commit()
        return {"workstation_id": wid, "workstation_secret": secret}

    def _auth_ws(self, wid: str, secret: str) -> bool:
        row = self.db.execute(
            "SELECT secret_hash FROM workstations WHERE workstation_id=?", (wid,)
        ).fetchone()
        return bool(row) and secrets.compare_digest(row["secret_hash"], _hash(secret))

    def _touch_ws(self, wid: str):
        self.db.execute(
            "UPDATE workstations SET last_seen=? WHERE workstation_id=?",
            (int(time.time()), wid),
        )
        self.db.commit()

    def _set_ws_pubkey(self, wid: str, pubkey: str):
        self.db.execute(
            "UPDATE workstations SET pubkey=? WHERE workstation_id=?", (pubkey, wid)
        )
        self.db.commit()

    # pairing
    def _new_pair_token(self, wid: str, pubkey: str, salt: str):
        tok = secrets.token_urlsafe(18)
        self.db.execute(
            "INSERT INTO pairing_tokens(token,workstation_id,pubkey,salt,expires_at)"
            " VALUES(?,?,?,?,?)",
            (tok, wid, pubkey, salt, int(time.time()) + PAIRING_TTL_S),
        )
        self.db.commit()
        return {"token": tok, "expires_in": PAIRING_TTL_S}

    def _redeem(self, token: str, name: str, device_pubkey: str):
        row = self.db.execute(
            "SELECT * FROM pairing_tokens WHERE token=?", (token,)
        ).fetchone()
        now = int(time.time())
        if not row or row["used_at"] or row["expires_at"] < now:
            return None
        self.db.execute("UPDATE pairing_tokens SET used_at=? WHERE token=?", (now, token))
        did = "dev_" + secrets.token_hex(8)
        dtok = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO devices(device_id,workstation_id,name,token_hash,pubkey,created)"
            " VALUES(?,?,?,?,?,?)",
            (did, row["workstation_id"], name, _hash(dtok), device_pubkey, now),
        )
        self.db.commit()
        return {
            "device_id": did,
            "device_token": dtok,
            "workstation_id": row["workstation_id"],
            "workstation_pubkey": row["pubkey"],
            "salt": row["salt"],
        }

    def _auth_device(self, did: str, token: str):
        row = self.db.execute(
            "SELECT * FROM devices WHERE device_id=? AND revoked=0", (did,)
        ).fetchone()
        if not row or not secrets.compare_digest(row["token_hash"], _hash(token)):
            return None
        return {"device_id": did, "workstation_id": row["workstation_id"],
                "mode": row["mode"], "name": row["name"]}

    def _revoke(self, wid: str, did: str) -> bool:
        cur = self.db.execute(
            "UPDATE devices SET revoked=1 WHERE device_id=? AND workstation_id=?",
            (did, wid),
        )
        self.db.commit()
        return cur.rowcount > 0

    def _list_devices(self, wid: str):
        rows = self.db.execute(
            "SELECT device_id,name,mode,created,revoked FROM devices WHERE workstation_id=?",
            (wid,),
        ).fetchall()
        return [dict(r) for r in rows]

    # async wrappers
    async def create_workstation(self, n, p): return await self._run(self._create_ws, n, p)
    async def auth_workstation(self, w, s):  return await self._run(self._auth_ws, w, s)
    async def touch(self, w):                return await self._run(self._touch_ws, w)
    async def set_pubkey(self, w, p):        return await self._run(self._set_ws_pubkey, w, p)
    async def new_pair_token(self, w, p, s): return await self._run(self._new_pair_token, w, p, s)
    async def redeem(self, t, n, p):         return await self._run(self._redeem, t, n, p)
    async def auth_device(self, d, t):       return await self._run(self._auth_device, d, t)
    async def revoke(self, w, d):            return await self._run(self._revoke, w, d)
    async def list_devices(self, w):         return await self._run(self._list_devices, w)


# ── live connection table (in memory only) ───────────────────────────────────
class Hub:
    def __init__(self) -> None:
        self.workstations: Dict[str, web.WebSocketResponse] = {}
        # rid -> device websocket, so a reply can find its way home
        self.pending: Dict[str, web.WebSocketResponse] = {}

    def online(self, wid: str) -> bool:
        ws = self.workstations.get(wid)
        return ws is not None and not ws.closed


# ── helpers ──────────────────────────────────────────────────────────────────
def _bearer(request: web.Request) -> str:
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _json(obj: Any, status: int = 200) -> web.Response:
    return web.json_response(obj, status=status)


async def _require_ws_auth(request: web.Request):
    """Workstation REST auth: header ``X-Workstation-Id`` + bearer secret."""
    wid = request.headers.get("X-Workstation-Id", "").strip()
    secret = _bearer(request)
    if not wid or not secret:
        return None
    reg: Registry = request.app["registry"]
    return wid if await reg.auth_workstation(wid, secret) else None


# ── REST: identity & pairing ─────────────────────────────────────────────────
async def h_register(request: web.Request) -> web.Response:
    """Provision a workstation. Guarded by the relay admin token."""
    if not secrets.compare_digest(_bearer(request), request.app["admin_token"]):
        return _json({"ok": False, "error": "unauthorized"}, 401)
    body = await request.json()
    out = await request.app["registry"].create_workstation(
        str(body.get("display_name") or ""), str(body.get("pubkey") or "")
    )
    log.info("registered workstation %s", out["workstation_id"])
    return _json({"ok": True, **out})


async def h_pair_token(request: web.Request) -> web.Response:
    """Workstation asks for a short-lived, single-use pairing token for its QR."""
    wid = await _require_ws_auth(request)
    if not wid:
        return _json({"ok": False, "error": "unauthorized"}, 401)
    body = await request.json()
    pubkey, salt = str(body.get("pubkey") or ""), str(body.get("salt") or "")
    if pubkey:
        await request.app["registry"].set_pubkey(wid, pubkey)
    out = await request.app["registry"].new_pair_token(wid, pubkey, salt)
    return _json({"ok": True, "workstation_id": wid, **out})


async def h_pair_redeem(request: web.Request) -> web.Response:
    """Phone redeems the QR token -> device identity + the key material it needs."""
    body = await request.json()
    out = await request.app["registry"].redeem(
        str(body.get("token") or ""),
        str(body.get("device_name") or "device"),
        str(body.get("device_pubkey") or ""),
    )
    if not out:
        return _json({"ok": False, "error": "invalid or expired pairing token"}, 403)
    log.info("paired device %s -> %s", out["device_id"], out["workstation_id"])
    return _json({"ok": True, **out})


async def h_devices(request: web.Request) -> web.Response:
    wid = await _require_ws_auth(request)
    if not wid:
        return _json({"ok": False, "error": "unauthorized"}, 401)
    return _json({"ok": True, "devices": await request.app["registry"].list_devices(wid)})


async def h_revoke(request: web.Request) -> web.Response:
    wid = await _require_ws_auth(request)
    if not wid:
        return _json({"ok": False, "error": "unauthorized"}, 401)
    did = request.match_info["device_id"]
    ok = await request.app["registry"].revoke(wid, did)
    return _json({"ok": ok}, 200 if ok else 404)


async def h_status(request: web.Request) -> web.Response:
    wid = request.match_info["workstation_id"]
    return _json({"ok": True, "workstation_id": wid,
                  "online": request.app["hub"].online(wid)})


async def h_health(request: web.Request) -> web.Response:
    hub: Hub = request.app["hub"]
    return _json({"ok": True, "service": "aipacs-agent-relay", "version": "1.0.0",
                  "workstations_online": len(hub.workstations)})


# ── WebSocket: workstation side (outbound, long-lived) ───────────────────────
async def h_agent_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30.0, autoping=True)
    await ws.prepare(request)
    reg: Registry = request.app["registry"]
    hub: Hub = request.app["hub"]
    wid: Optional[str] = None
    try:
        raw = await ws.receive(timeout=15)
        hello = json.loads(raw.data)
        wid = str(hello.get("workstation_id") or "")
        if not await reg.auth_workstation(wid, str(hello.get("auth") or "")):
            await ws.send_json({"t": "error", "code": "unauthorized"})
            return ws

        old = hub.workstations.get(wid)
        if old is not None and not old.closed:
            await old.close()          # a workstation has exactly one live socket
        hub.workstations[wid] = ws
        await reg.touch(wid)
        await ws.send_json({"t": "ready", "workstation_id": wid})
        log.info("workstation %s connected", wid)

        async for msg in ws:
            if msg.type is not WSMsgType.TEXT:
                continue
            try:
                frame = json.loads(msg.data)
            except Exception:
                continue
            t = frame.get("t")
            if t == "ping":
                await ws.send_json({"t": "pong"})
                continue
            if t != "msg":
                continue
            # Route the reply back to whichever device asked.
            target = hub.pending.pop(str(frame.get("rid") or ""), None)
            if target is not None and not target.closed:
                await target.send_json(frame)
    except Exception as exc:  # noqa: BLE001
        log.debug("workstation ws ended: %s", exc)
    finally:
        if wid and hub.workstations.get(wid) is ws:
            hub.workstations.pop(wid, None)
            log.info("workstation %s disconnected", wid)
    return ws


# ── WebSocket: device (phone) side ───────────────────────────────────────────
async def h_device_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30.0, autoping=True)
    await ws.prepare(request)
    reg: Registry = request.app["registry"]
    hub: Hub = request.app["hub"]
    try:
        raw = await ws.receive(timeout=15)
        hello = json.loads(raw.data)
        dev = await reg.auth_device(
            str(hello.get("device_id") or ""), str(hello.get("auth") or "")
        )
        if not dev:
            await ws.send_json({"t": "error", "code": "unauthorized"})
            return ws
        wid = dev["workstation_id"]
        await ws.send_json({"t": "ready", "workstation_id": wid,
                            "workstation_online": hub.online(wid)})

        async for msg in ws:
            if msg.type is not WSMsgType.TEXT:
                continue
            try:
                frame = json.loads(msg.data)
            except Exception:
                continue
            t = frame.get("t")
            if t == "ping":
                await ws.send_json({"t": "pong"})
                continue
            if t == "status":
                await ws.send_json({"t": "status", "workstation_online": hub.online(wid)})
                continue
            if t != "msg":
                continue

            target = hub.workstations.get(wid)
            if target is None or target.closed:
                # Honest failure beats silent queueing — and queueing clinical
                # traffic would turn this conduit into a store.
                await ws.send_json({"t": "error", "code": "workstation_offline",
                                    "rid": frame.get("rid")})
                continue
            rid = str(frame.get("rid") or secrets.token_hex(8))
            frame["rid"] = rid
            # Two DISTINCT id spaces: the relay's device id (routing/authz here)
            # and the workstation's own device id (which selects the end-to-end
            # channel over there). Never overwrite the client's `device_id` with
            # ours — the workstation would then fail to find the right key.
            frame["relay_device_id"] = dev["device_id"]
            hub.pending[rid] = ws
            await target.send_json(frame)
    except Exception as exc:  # noqa: BLE001
        log.debug("device ws ended: %s", exc)
    return ws


def build_app(db_path: str, admin_token: str) -> web.Application:
    app = web.Application()
    app["registry"] = Registry(db_path)
    app["hub"] = Hub()
    app["admin_token"] = admin_token
    app.add_routes([
        web.get("/health", h_health),
        web.post("/api/workstations/register", h_register),
        web.post("/api/pair/token", h_pair_token),
        web.post("/api/pair/redeem", h_pair_redeem),
        web.get("/api/devices", h_devices),
        web.post("/api/devices/{device_id}/revoke", h_revoke),
        web.get("/api/workstations/{workstation_id}/status", h_status),
        web.get("/agent/ws", h_agent_ws),
        web.get("/device/ws", h_device_ws),
    ])
    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="AIPACS Agent Relay")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=int(os.environ.get("AIPACS_RELAY_PORT", "9000")))
    ap.add_argument("--db", default=os.environ.get("AIPACS_RELAY_DB", "aipacs_relay.sqlite3"))
    ap.add_argument("--admin-token", default=os.environ.get("AIPACS_RELAY_ADMIN_TOKEN", ""))
    args = ap.parse_args()
    if not args.admin_token:
        raise SystemExit("--admin-token (or AIPACS_RELAY_ADMIN_TOKEN) is required")
    log.info("AIPACS relay listening on %s:%s (db=%s)", args.host, args.port, args.db)
    web.run_app(build_app(args.db, args.admin_token), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
