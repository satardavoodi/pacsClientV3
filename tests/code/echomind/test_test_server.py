# -*- coding: utf-8 -*-
"""Unit tests for the env-gated Test Control Server (secretary/test_server.py).

Headless: offscreen QApplication, a fake bus, a QLocalSocket client driven by
processEvents. Verifies: env gate, ping, list_actions, bus dispatch round-trip,
write-adapter registration hook, and queued (one-per-turn) draining of bursts.
"""
from __future__ import annotations

import json
import os
import time
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtNetwork import QLocalSocket  # noqa: E402

from modules.EchoMind.secretary.command_envelope import CommandPlan, CommandResult  # noqa: E402
from modules.EchoMind.secretary.registry import AdapterRegistry  # noqa: E402
from modules.EchoMind.secretary.command_bus import CommandBus  # noqa: E402
from modules.EchoMind.secretary.test_server import maybe_start_test_server  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """An offscreen **QApplication**, not a bare QCoreApplication.

    2026-07-31 — this used to build a `QCoreApplication`. Nothing in THIS file
    needs a GUI app, so it looked harmless (and the module docstring above has
    always claimed "offscreen QApplication"). But the instance is process-wide
    and lives for the whole session: once it exists, every later
    `QApplication.instance()` returns a non-GUI application, and any test that
    then constructs a QWidget on it is undefined behaviour. Since
    `tests/code/echomind` sorts before `tests/gui`, a combined run —
    `pytest tests/code/echomind tests/gui` — created the bare core app here and
    then aborted the interpreter at exit with STATUS_STACK_BUFFER_OVERRUN
    (0xC0000409), AFTER every test had passed. A green run followed by a silent
    crash is the worst possible failure mode for a gate.

    `QApplication` IS a `QCoreApplication`, so the IPC tests below are
    unaffected; the difference is only that whoever comes next gets a usable
    application object.
    """
    app = QCoreApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _EchoAdapter:
    def echo(self, plan: CommandPlan, state: dict) -> CommandResult:
        return CommandResult(ok=True, action=plan.action, data=dict(plan.entities))


def _make_bus() -> CommandBus:
    reg = AdapterRegistry()
    reg.register("test", _EchoAdapter(), actions={"echo": "echo"})
    return CommandBus(registry=reg)


def _pump(qapp, ms: float = 50.0):
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents()


def _connect(qapp, name: str) -> QLocalSocket:
    sock = QLocalSocket()
    sock.connectToServer(name)
    deadline = time.monotonic() + 2.0
    while sock.state() != QLocalSocket.ConnectedState and time.monotonic() < deadline:
        qapp.processEvents()
    assert sock.state() == QLocalSocket.ConnectedState, sock.errorString()
    return sock


def _request(qapp, sock: QLocalSocket, payload: dict, timeout_s: float = 3.0) -> dict:
    sock.write(json.dumps(payload).encode() + b"\n")
    sock.flush()
    buf = b""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if sock.bytesAvailable():
            buf += bytes(sock.readAll().data())
            if b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                return json.loads(line)
    raise AssertionError("no reply within timeout")


def test_env_gate_off_returns_none(qapp, monkeypatch):
    monkeypatch.delenv("AIPACS_TEST_SERVER", raising=False)
    assert maybe_start_test_server(get_bus=_make_bus) is None


def test_ping_list_and_dispatch(qapp):
    name = f"AIPACS_TEST_UT_{uuid.uuid4().hex[:8]}"
    bus = _make_bus()
    server = maybe_start_test_server(get_bus=lambda: bus, server_name=name, force=True)
    assert server is not None
    try:
        sock = _connect(qapp, name)

        pong = _request(qapp, sock, {"id": 1, "action": "ping"})
        assert pong["ok"] is True and pong["data"] == "pong" and pong["id"] == 1

        acts = _request(qapp, sock, {"id": 2, "action": "list_actions"})
        assert acts["ok"] is True and "echo" in acts["data"]
        # write adapter registered by the server (test mode only)
        assert "change_series" in acts["data"]
        assert "query_viewport_state" in acts["data"]

        echo = _request(qapp, sock, {"id": 3, "action": "echo",
                                     "entities": {"x": 7, "s": "hi"}})
        assert echo["ok"] is True
        assert echo["data"] == {"x": 7, "s": "hi"}
        assert echo.get("elapsed_ms") is not None

        bad = _request(qapp, sock, {"id": 4, "action": "no_such_action"})
        assert bad["ok"] is False and bad["id"] == 4
    finally:
        server.close()


def test_burst_drains_one_per_turn(qapp):
    name = f"AIPACS_TEST_UT_{uuid.uuid4().hex[:8]}"
    bus = _make_bus()
    server = maybe_start_test_server(get_bus=lambda: bus, server_name=name, force=True)
    assert server is not None
    try:
        sock = _connect(qapp, name)
        n = 25
        blob = b"".join(
            json.dumps({"id": i, "action": "echo", "entities": {"i": i}}).encode() + b"\n"
            for i in range(n)
        )
        sock.write(blob)
        sock.flush()
        got: dict[int, dict] = {}
        buf = b""
        deadline = time.monotonic() + 5.0
        while len(got) < n and time.monotonic() < deadline:
            qapp.processEvents()
            if sock.bytesAvailable():
                buf += bytes(sock.readAll().data())
                while b"\n" in buf:
                    line, _, buf = buf.partition(b"\n")
                    msg = json.loads(line)
                    got[msg["id"]] = msg
        assert len(got) == n, f"only {len(got)}/{n} answered"
        assert all(got[i]["ok"] and got[i]["data"]["i"] == i for i in range(n))
    finally:
        server.close()


def test_write_adapter_errors_without_tab(qapp):
    name = f"AIPACS_TEST_UT_{uuid.uuid4().hex[:8]}"
    bus = _make_bus()
    server = maybe_start_test_server(
        get_bus=lambda: bus, server_name=name, force=True,
        get_active_patient_tab=lambda: None, get_main_tab_widget=lambda: None,
    )
    assert server is not None
    try:
        sock = _connect(qapp, name)
        res = _request(qapp, sock, {"id": 1, "action": "change_series",
                                    "entities": {"series_number": 201}})
        assert res["ok"] is False and res["error_code"] == "NO_ACTIVE_TAB"
        res2 = _request(qapp, sock, {"id": 2, "action": "change_layout"})
        assert res2["ok"] is False and res2["error_code"] == "NOT_IMPLEMENTED"
    finally:
        server.close()


def test_aggregate_interceptor_missing_callback_never_dispatches_bus():
    import json
    from modules.EchoMind.secretary.test_server import TestControlServer
    server = object.__new__(TestControlServer)
    server._get_native_runtime = None
    server._get_bus = lambda: (_ for _ in ()).throw(AssertionError('Must not dispatch'))
    result = json.loads(server._execute({'id': 1, 'action': 'secretary_terminal_receipt',
                                        'entities': {'request_id': 'invalid'}}))
    assert result == {'id': 1, 'action': 'secretary_terminal_receipt', 'ok': False, 'error_code': 'NOT_FOUND'}


def test_aggregate_interceptor_callback_failure_is_sanitized():
    import json
    from modules.EchoMind.secretary.test_server import TestControlServer
    server = object.__new__(TestControlServer)
    server._get_native_runtime = lambda: (_ for _ in ()).throw(RuntimeError('SYNTHETIC_PRIVATE_VALUE'))
    result = json.loads(server._execute({'id': 2, 'action': 'secretary_terminal_receipt'}))
    assert result['error_code'] == 'NOT_FOUND'
    assert 'SYNTHETIC_PRIVATE_VALUE' not in str(result)


def test_lifecycle_inspection_uses_only_existing_attachment():
    import json
    from types import SimpleNamespace
    from modules.EchoMind.secretary.test_server import TestControlServer
    server = object.__new__(TestControlServer)
    server._get_bus = lambda: (_ for _ in ()).throw(AssertionError('No mutation'))
    server._get_native_lifecycle = lambda:SimpleNamespace(diagnostics=lambda:{
        'stage':'human_session','category':'authentication','closed':True})
    request={'action':'secretary_lifecycle','entities':{}}
    assert json.loads(server._execute(request))['data']['stage']=='human_session'
    assert json.loads(server._execute(dict(request,entities={'extra':True})))['error_code']=='NOT_FOUND'
    server._get_native_lifecycle=None
    assert json.loads(server._execute(request))['error_code']=='NOT_FOUND'


def test_runtime_binding_is_existing_owner_bound_and_read_only():
    import json
    import threading
    from types import SimpleNamespace
    from uuid import uuid4
    from modules.EchoMind.secretary.test_server import TestControlServer
    runtime_id, session_id = str(uuid4()), str(uuid4())
    runtime = SimpleNamespace(gui_thread_id=threading.get_ident(), closed=False,
        owner='synthetic-owner', owner_getter=lambda:'synthetic-owner',
        runtime_instance=runtime_id, widget=SimpleNamespace(_secretary_orchestrator=
        SimpleNamespace(_memory_store=SimpleNamespace(_conversation={'id':session_id}))))
    server = object.__new__(TestControlServer)
    server._get_bus = lambda: (_ for _ in ()).throw(AssertionError('No bus dispatch'))
    server._get_native_runtime = lambda:runtime
    request = {'action':'secretary_runtime_binding','entities':{}}
    result = json.loads(server._execute(request))
    assert result['data'] == {'runtime_instance':runtime_id,'current_session':session_id}
    for field, value in [('closed',True),('gui_thread_id',-1),('owner','different')]:
        original = getattr(runtime,field)
        setattr(runtime,field,value)
        assert json.loads(server._execute(request))['error_code']=='NOT_FOUND'
        setattr(runtime,field,original)
    assert json.loads(server._execute(dict(request,entities={'extra':True})))['error_code']=='NOT_FOUND'
    server._get_native_runtime = None
    assert json.loads(server._execute(request))['error_code']=='NOT_FOUND'


def test_terminal_diagnostic_interceptor_never_initializes_or_dispatches_bus():
    import json
    from types import SimpleNamespace
    from modules.EchoMind.secretary.test_server import TestControlServer
    server=object.__new__(TestControlServer)
    server._get_bus=lambda:(_ for _ in ()).throw(AssertionError('No bus'))
    server._get_native_runtime=None
    request={'id':1,'action':'secretary_terminal_diagnostic','entities':{}}
    assert json.loads(server._execute(request))['error_code']=='NOT_FOUND'
    calls=[]
    server._get_native_runtime=lambda:SimpleNamespace(test_terminal_diagnostic=lambda entities:
        calls.append(entities) or {'ok':True,'data':{'action':'unknown'}})
    assert json.loads(server._execute(request))['data']=={'action':'unknown'}
    assert calls==[{}]
