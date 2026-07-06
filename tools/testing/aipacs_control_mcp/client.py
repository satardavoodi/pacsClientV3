# -*- coding: utf-8 -*-
"""AipacsControlClient — talks to the in-app Test Control Server.

Synchronous QLocalSocket client (PySide6 is in the app venv). One JSON line
per request, one per response; ``id`` correlates. Each client owns one
persistent connection; ``send`` is blocking with a timeout.

CLI usage (from the app venv):
    python client.py ping
    python client.py list_actions
    python client.py open_patient '{"patient_id": "44704"}'
    python client.py change_series '{"series_number": 201, "viewport": 0}'
"""
from __future__ import annotations

import getpass
import json
import re
import sys
import time
from typing import Any, Optional


def default_server_name() -> str:
    import os
    override = os.environ.get("AIPACS_TEST_SOCKET", "").strip()
    if override:
        return override
    user = re.sub(r"[^A-Za-z0-9_]", "_", getpass.getuser() or "user")
    return f"AIPACS_TEST_{user}"


def _ensure_qt_app():
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication(sys.argv[:1])


class AipacsControlClient:
    def __init__(self, server_name: Optional[str] = None, connect_timeout_ms: int = 3000):
        from PySide6.QtNetwork import QLocalSocket
        _ensure_qt_app()
        self.server_name = server_name or default_server_name()
        self._sock = QLocalSocket()
        self._buf = b""
        self._next_id = 1
        self._sock.connectToServer(self.server_name)
        if not self._sock.waitForConnected(connect_timeout_ms):
            raise ConnectionError(
                f"cannot reach AI-PACS test server '{self.server_name}' "
                f"({self._sock.errorString()}). Is the app running with "
                f"AIPACS_TEST_SERVER=1 ?"
            )

    # ── core ─────────────────────────────────────────────────────────
    def send(self, action: str, entities: Optional[dict] = None,
             timeout_ms: int = 30000, mode: str = "") -> dict:
        req_id = self._next_id
        self._next_id += 1
        req = {"id": req_id, "action": action, "entities": entities or {}}
        if mode:
            req["mode"] = mode
        line = json.dumps(req, default=str).encode("utf-8") + b"\n"
        self._sock.write(line)
        self._sock.flush()
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            # Drain anything already buffered first.
            while b"\n" in self._buf:
                raw, self._buf = self._buf.split(b"\n", 1)
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except Exception:
                    continue
                if msg.get("id") == req_id:
                    return msg
                # response to an older/parallel request — ignore
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no response to '{action}' within {timeout_ms} ms")
            if self._sock.waitForReadyRead(int(min(remaining * 1000, 250)) or 1):
                self._buf += bytes(self._sock.readAll().data())

    def fire(self, action: str, entities: Optional[dict] = None,
             mode: str = "") -> int:
        """Fire-and-forget (burst mode): write the request, don't wait."""
        req_id = self._next_id
        self._next_id += 1
        req = {"id": req_id, "action": action, "entities": entities or {}}
        if mode:
            req["mode"] = mode
        line = json.dumps(req, default=str).encode("utf-8") + b"\n"
        self._sock.write(line)
        self._sock.flush()
        return req_id

    def drain(self, expect_ids: list[int], timeout_ms: int = 30000) -> dict[int, dict]:
        """Collect responses for previously fired requests."""
        got: dict[int, dict] = {}
        deadline = time.monotonic() + timeout_ms / 1000.0
        want = set(expect_ids)
        while want and time.monotonic() < deadline:
            while b"\n" in self._buf:
                raw, self._buf = self._buf.split(b"\n", 1)
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except Exception:
                    continue
                mid = msg.get("id")
                if mid in want:
                    got[mid] = msg
                    want.discard(mid)
            if want and self._sock.waitForReadyRead(100):
                self._buf += bytes(self._sock.readAll().data())
        return got

    def close(self) -> None:
        try:
            self._sock.disconnectFromServer()
        except Exception:
            pass


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    entities = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    client = AipacsControlClient()
    try:
        result = client.send(action, entities)
    finally:
        client.close()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
