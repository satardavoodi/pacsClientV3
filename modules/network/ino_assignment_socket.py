# -*- coding: utf-8 -*-
"""Socket transport for INO internal assignment (PACS socket :50052).

The documented PACS-client alternative to the REST assign path
(ASSIGN_CLIENT_GUIDE_FA §4): a framed-JSON request over the SAME imaging socket
AI-PACS already uses. Framing = ``[4-byte big-endian length] + [UTF-8 JSON]``.

Used as a fallback when the PACS HTTP service (:8000) isn't reachable but the
socket is. We reuse the app's existing socket token (no re-Login). Pure stdlib —
imports nothing from the consultation / Drive / payment / Identity stack, so the
isolation guard still holds.
"""

from __future__ import annotations

import json
import logging
import socket
import struct
from typing import Any, Dict, Optional

logger = logging.getLogger("ino_assignment")

_MAX_FRAME = 64 * 1024 * 1024  # 64 MiB safety cap on a response frame


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(65536, n - len(buf)))
        if not chunk:
            raise ConnectionError("socket closed mid-frame")
        buf.extend(chunk)
    return bytes(buf)


def _send_framed(sock: socket.socket, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack(">I", len(body)) + body)
    hdr = _recv_exact(sock, 4)
    n = struct.unpack(">I", hdr)[0]
    if n <= 0 or n > _MAX_FRAME:
        raise ValueError(f"bad response frame length: {n}")
    data = _recv_exact(sock, n)
    return json.loads(data.decode("utf-8"))


def _resolve_socket_target() -> Optional[tuple]:
    """(host, port) of the imaging socket, or None if unresolved."""
    try:
        from modules.network.socket_config import get_socket_config

        cfg = get_socket_config()
        host = cfg.get_socket_host()
        port = int(cfg.get_socket_port())
        if host and port:
            return (host, port)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[ino-assignment] socket target resolve failed: %s", exc)
    return None


def assign_via_socket(token: str, params: Dict[str, Any], timeout: int = 8) -> Dict[str, Any]:
    """Send an ``AssignStudy`` request over the PACS socket.

    ``params`` = ``{patient_id, assign_type, assignee_id, assignee_name,
    assignee_source, study_uid}``. Returns the same result shape as the REST
    client's ``assign`` (``ok`` / ``modified_count`` / ``message`` / ``raw``).
    Never raises.
    """
    target = _resolve_socket_target()
    if not target:
        return {"ok": False, "status": 0, "message": "socket server not configured"}
    if not token:
        return {"ok": False, "status": 401, "message": "no active session token", "auth_error": True}
    try:
        with socket.create_connection(target, timeout=timeout) as s:
            s.settimeout(timeout)
            resp = _send_framed(s, {"endpoint": "AssignStudy", "token": token, "params": params})
    except Exception as exc:
        return {"ok": False, "status": 0, "message": f"socket assign failed: {exc}"}
    data = resp.get("data") if isinstance(resp, dict) else {}
    data = data if isinstance(data, dict) else {}
    ok = bool(data.get("success") or (isinstance(resp, dict) and resp.get("status") == "success"))
    out: Dict[str, Any] = {"ok": ok, "status": 200 if ok else 0, "raw": resp,
                           "modified_count": data.get("modified_count")}
    if not ok:
        out["message"] = str((resp or {}).get("message") or data.get("message") or "socket assign rejected")
    return out
