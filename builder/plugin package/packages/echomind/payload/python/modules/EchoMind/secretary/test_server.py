"""AIPACS Test Control Server — external transport for the CommandBus.

Env-gated (``AIPACS_TEST_SERVER=1``), source-build-only. Exposes the existing
in-process CommandBus over a per-user ``QLocalServer`` (Windows named pipe) so
external agents (the ``aipacs-control`` MCP, pytest, a CLI) can invoke
application functions directly instead of driving the mouse.

Design (TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04 §4):

* **Protocol** — JSON-lines. Request: ``{"id": n, "action": str,
  "entities": {...}}``. Response: the serialized ``CommandResult`` plus the
  echoed ``id``. Built-ins handled by the server itself: ``ping``,
  ``list_actions``.
* **Pressure model / Qt safety** — the server lives on the Qt main thread
  (created in ``HomePanelWidget.__init__``). Incoming lines are queued and
  drained ONE PER EVENT-LOOP TURN via ``QTimer.singleShot(0, ...)`` — commands
  interleave with real paint/timer/input traffic exactly like posted input,
  can pile up faster than the app completes prior work (the requested
  impatient-user semantics), and never re-enter or block the loop wholesale.
* **Safety gates** — default OFF; refuses frozen builds (``sys.frozen``);
  per-user socket name; loud log banner. The test-only
  ``ViewerWriteCommandAdapter`` is registered onto the bus *here*, so all
  write-side surface exists only when the server is enabled. Clinical guards
  are unaffected: every command runs the same production functions.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import re
import sys
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

ENV_FLAG = "AIPACS_TEST_SERVER"


def default_server_name() -> str:
    # Explicit override wins (lets launcher and clients agree even when the
    # process env's USERNAME drifted, e.g. registry-restored env → SYSTEM).
    override = os.environ.get("AIPACS_TEST_SOCKET", "").strip()
    if override:
        return override
    user = re.sub(r"[^A-Za-z0-9_]", "_", getpass.getuser() or "user")
    return f"AIPACS_TEST_{user}"


def _result_to_wire(result: Any, req_id: Any) -> str:
    """Serialize a CommandResult (or anything) into one JSON line."""
    try:
        payload = result.model_dump() if hasattr(result, "model_dump") else result
    except Exception:
        payload = {"ok": False, "error_code": "SERIALIZE_FAILED", "message": str(result)}
    if not isinstance(payload, dict):
        payload = {"ok": True, "data": payload}
    payload["id"] = req_id
    return json.dumps(payload, default=str, ensure_ascii=False) + "\n"


class _Connection:
    """One client connection: line buffer + fair-share command queue."""

    def __init__(self, socket, owner: "TestControlServer") -> None:
        self.socket = socket
        self.owner = owner
        self._buf = b""
        self._pending: list[dict] = []
        self._drain_scheduled = False
        socket.readyRead.connect(self._on_ready_read)
        socket.disconnected.connect(self._on_disconnected)

    # ── socket plumbing (Qt main thread) ─────────────────────────────
    def _on_ready_read(self) -> None:
        try:
            self._buf += bytes(self.socket.readAll().data())
        except Exception:
            return
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line.decode("utf-8", "replace"))
            except Exception as exc:
                self._write({"id": None, "ok": False, "error_code": "BAD_JSON",
                             "message": str(exc)})
                continue
            self._pending.append(req)
        self._schedule_drain()

    def _on_disconnected(self) -> None:
        try:
            self.owner._connections.discard(self)
        except Exception:
            pass

    def _write(self, payload: dict) -> None:
        try:
            self.socket.write(json.dumps(payload, default=str).encode("utf-8") + b"\n")
            self.socket.flush()
        except Exception:
            pass

    # ── one command per event-loop turn ──────────────────────────────
    def _schedule_drain(self) -> None:
        if self._drain_scheduled or not self._pending:
            return
        self._drain_scheduled = True
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._drain_one)

    def _drain_one(self) -> None:
        self._drain_scheduled = False
        if not self._pending:
            return
        req = self._pending.pop(0)
        try:
            wire = self.owner._execute(req)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[TEST_SERVER] command failed")
            wire = _result_to_wire(
                {"ok": False, "action": str(req.get("action")),
                 "error_code": "SERVER_ERROR", "message": str(exc)},
                req.get("id"),
            )
        try:
            self.socket.write(wire.encode("utf-8"))
            self.socket.flush()
        except Exception:
            pass
        self._schedule_drain()


class TestControlServer:
    """QLocalServer wrapper dispatching JSON commands onto the CommandBus."""

    def __init__(self, get_bus: Callable[[], Any], server_name: str) -> None:
        from PySide6.QtNetwork import QLocalServer
        self._get_bus = get_bus
        self.server_name = server_name
        self._connections: set[_Connection] = set()
        # Remove a stale endpoint from a crashed previous run, then listen.
        QLocalServer.removeServer(server_name)
        self._server = QLocalServer()
        if not self._server.listen(server_name):
            raise RuntimeError(
                f"TestControlServer: listen('{server_name}') failed: "
                f"{self._server.errorString()}"
            )
        self._server.newConnection.connect(self._on_new_connection)

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            if sock is not None:
                self._connections.add(_Connection(sock, self))

    # ── dispatch ─────────────────────────────────────────────────────
    def _execute(self, req: dict) -> str:
        req_id = req.get("id")
        action = str(req.get("action") or "")
        entities = req.get("entities") or {}

        if action == "ping":
            return _result_to_wire({"ok": True, "action": "ping", "data": "pong"}, req_id)

        bus = self._get_bus()
        if bus is None:
            return _result_to_wire(
                {"ok": False, "action": action, "error_code": "NO_BUS",
                 "message": "command_bus not initialised yet"}, req_id)

        if action == "list_actions":
            return _result_to_wire(
                {"ok": True, "action": "list_actions", "data": list(bus.actions())},
                req_id)

        from .command_envelope import CommandPlan
        plan = CommandPlan(action=action, entities=dict(entities))
        result = bus.execute(plan)
        return _result_to_wire(result, req_id)

    def close(self) -> None:
        try:
            self._server.close()
        except Exception:
            pass


def maybe_start_test_server(
    get_bus: Callable[[], Any],
    get_active_patient_tab: Optional[Callable[[], Any]] = None,
    get_main_tab_widget: Optional[Callable[[], Any]] = None,
    server_name: Optional[str] = None,
    force: bool = False,
) -> Optional[TestControlServer]:
    """Start the test server when ``AIPACS_TEST_SERVER=1`` (else no-op).

    ``force=True`` bypasses the env gate (unit tests only). Also registers the
    test-only ``ViewerWriteCommandAdapter`` so write-side actions exist
    exclusively in test mode.
    """
    if not force and os.environ.get(ENV_FLAG, "").strip() != "1":
        return None
    if getattr(sys, "frozen", False):
        logger.warning("[TEST_SERVER] refused: frozen build")
        return None

    name = server_name or default_server_name()
    server = TestControlServer(get_bus=get_bus, server_name=name)

    # Test-mode-only write adapter (never in the production bus).
    try:
        bus = get_bus()
        if bus is not None and not bus.registry.has_action("change_series"):
            from .adapters.viewer_write_adapter import (
                TEST_WRITE_ACTIONS,
                ViewerWriteCommandAdapter,
            )
            bus.registry.register(
                "viewer_write",
                ViewerWriteCommandAdapter(
                    get_active_patient_tab=get_active_patient_tab,
                    get_main_tab_widget=get_main_tab_widget,
                ),
                actions=dict(TEST_WRITE_ACTIONS),
            )
            logger.info("[TEST_SERVER] ViewerWriteCommandAdapter registered (test mode)")
    except Exception:
        logger.exception("[TEST_SERVER] write-adapter registration failed (continuing)")

    banner = f"[TEST_SERVER] LISTENING on local socket '{name}' (env {ENV_FLAG}=1)"
    logger.warning(banner)
    print(banner)
    return server


__all__ = ["TestControlServer", "maybe_start_test_server", "default_server_name", "ENV_FLAG"]
