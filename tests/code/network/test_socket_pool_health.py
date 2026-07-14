"""FIX-1 guards — stale pooled socket must never be handed out, and a request
that failed BEFORE the server answered must reconnect and retry exactly once.

Field evidence (2026-07-13, laptop, remote server over the public internet):
every socket failure in the session was ``Invalid response length header`` —
never a timeout. That message is what EOF on a half-open socket produces:
``is_connected()`` is a FLAG, so the pool handed out a connection the server had
already closed, ``send_request`` skipped its reconnect branch, and the read hit
EOF. The user saw ``Search returned None`` / ``Update failed - no response from
server``, and it did not self-heal after the network came back because the pool
kept the poisoned connections.

These tests are pure — no real socket, no Qt.
"""
import socket as _socket_mod
import sys
import types

import pytest

# The module imports Qt-free helpers only, but it does pull socket_config /
# token manager; those are import-light. Import lazily so a collection failure is
# obvious.
from modules.network import socket_client as sc


class _FakeSock:
    """Minimal stand-in for a TCP socket."""

    def __init__(self, *, readable=False, peek=b'', raise_on_select=False):
        self._readable = readable
        self._peek = peek
        self._raise_on_select = raise_on_select
        self.closed = False
        self.sent = []

    def settimeout(self, _t):
        pass

    def recv(self, n, flags=0):
        return self._peek[:n]

    def close(self):
        self.closed = True

    def shutdown(self, _how):
        pass


def _client_with(sock, *, connected=True, healthy=True, last_used=None, monkeypatch=None):
    c = sc.PatientListSocketClient.__new__(sc.PatientListSocketClient)
    c.host, c.port, c.timeout = "1.2.3.4", 50052, 5.0
    c.socket = sock
    c.connected = connected
    c.healthy = healthy
    c.lock = __import__("threading").RLock()
    c.last_used_mono = last_used if last_used is not None else sc.time.monotonic()
    c._last_error_zero_byte = False
    return c


# ── is_socket_alive ─────────────────────────────────────────────────────────

def test_idle_but_open_socket_is_alive(monkeypatch):
    sock = _FakeSock(readable=False)
    c = _client_with(sock)
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([], [], []))
    assert c.is_socket_alive() is True


def test_peer_closed_socket_is_dead_eof(monkeypatch):
    """Readable + zero bytes = EOF = the peer closed it. This is THE bug."""
    sock = _FakeSock(readable=True, peek=b'')
    c = _client_with(sock)
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([sock], [], []))
    assert c.is_socket_alive() is False


def test_socket_with_leftover_bytes_is_unusable(monkeypatch):
    """Readable WITH bytes before we sent anything = stream desync."""
    sock = _FakeSock(readable=True, peek=b'\x00\x00\x01')
    c = _client_with(sock)
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([sock], [], []))
    assert c.is_socket_alive() is False


def test_is_socket_alive_never_raises(monkeypatch):
    sock = _FakeSock()
    c = _client_with(sock)

    def _boom(*_a, **_k):
        raise OSError("bad fd")

    monkeypatch.setattr("select.select", _boom)
    assert c.is_socket_alive() is False  # fail-safe, no exception


def test_disconnected_client_is_not_alive():
    c = _client_with(None, connected=False)
    assert c.is_socket_alive() is False


# ── is_reusable ─────────────────────────────────────────────────────────────

def test_unhealthy_client_is_not_reusable():
    """A client whose last request FAILED must never serve another one."""
    c = _client_with(_FakeSock(), healthy=False)
    assert c.is_reusable(30.0) is False


def test_idle_past_window_is_not_reusable(monkeypatch):
    """A public-internet path silently drops idle connections — recycle first."""
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([], [], []))
    c = _client_with(_FakeSock(), last_used=sc.time.monotonic() - 120.0)
    assert c.is_reusable(30.0) is False
    # ...but a fresh one is fine.
    c2 = _client_with(_FakeSock(), last_used=sc.time.monotonic())
    assert c2.is_reusable(30.0) is True


def test_idle_window_disabled_still_probes(monkeypatch):
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([], [], []))
    c = _client_with(_FakeSock(), last_used=sc.time.monotonic() - 9999.0)
    assert c.is_reusable(0.0) is True  # idle recycling off -> probe decides


# ── the pool ────────────────────────────────────────────────────────────────

def test_pool_discards_dead_connection_and_creates_fresh(monkeypatch):
    dead = _client_with(_FakeSock(readable=True, peek=b''))  # EOF
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([r[0]], [], []))

    pool = sc.SocketConnectionPool("1.2.3.4", 50052, pool_size=5)
    pool.connections.append(dead)

    made = {}

    class _Fresh:
        def __init__(self, host, port):
            made['yes'] = True

    monkeypatch.setattr(sc, "PatientListSocketClient", _Fresh)
    got = pool.get_connection()

    assert made.get('yes') is True, "a dead pooled connection must not be reused"
    assert dead.socket is None or dead.connected is False
    assert pool.connections == []


def test_pool_reuses_a_live_connection(monkeypatch):
    live = _client_with(_FakeSock(readable=False))
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([], [], []))
    pool = sc.SocketConnectionPool("1.2.3.4", 50052, pool_size=5)
    pool.connections.append(live)
    assert pool.get_connection() is live


def test_pool_refuses_to_repool_a_failed_client():
    """Re-pooling a poisoned connection is what made one network blip keep
    failing long after the network recovered."""
    pool = sc.SocketConnectionPool("1.2.3.4", 50052, pool_size=5)
    bad = _client_with(_FakeSock(), healthy=False)
    pool.return_connection(bad)
    assert pool.connections == [], "an unhealthy client must never go back in the pool"

    good = _client_with(_FakeSock(), healthy=True)
    pool.return_connection(good)
    assert pool.connections == [good]


def test_pool_refuses_to_repool_a_disconnected_client():
    pool = sc.SocketConnectionPool("1.2.3.4", 50052, pool_size=5)
    gone = _client_with(None, connected=False)
    pool.return_connection(gone)
    assert pool.connections == []


# ── send_request retry classification ───────────────────────────────────────

def test_zero_byte_failure_reconnects_and_retries_once(monkeypatch):
    """The stale-socket case: the server never answered, so the request cannot
    have been applied — reconnect and resend exactly once."""
    c = _client_with(_FakeSock(readable=False))
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([], [], []))
    monkeypatch.delenv("AIPACS_SOCKET_RECONNECT_RETRY", raising=False)

    calls = []

    def _once(endpoint, params):
        calls.append(endpoint)
        if len(calls) == 1:
            c._last_error_zero_byte = True   # EOF before any response byte
            return None
        return {"status": "success"}

    c._send_request_once = _once
    c.disconnect = lambda: None

    out = c.send_request("GetPatientList", {})
    assert out == {"status": "success"}
    assert calls == ["GetPatientList", "GetPatientList"], "exactly one retry"


def test_mid_response_failure_is_NOT_retried(monkeypatch):
    """The server had begun answering — a blind resend could double-apply a
    write. Never retry that."""
    c = _client_with(_FakeSock(readable=False))
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([], [], []))
    monkeypatch.delenv("AIPACS_SOCKET_RECONNECT_RETRY", raising=False)

    calls = []

    def _once(endpoint, params):
        calls.append(endpoint)
        c._last_error_zero_byte = False      # response had started
        return None

    c._send_request_once = _once
    c.disconnect = lambda: None

    assert c.send_request("UpdateReportStatus", {}) is None
    assert calls == ["UpdateReportStatus"], "a mid-response failure must not be resent"


def test_kill_switch_restores_single_attempt(monkeypatch):
    c = _client_with(_FakeSock(readable=False))
    monkeypatch.setenv("AIPACS_SOCKET_RECONNECT_RETRY", "0")

    calls = []

    def _once(endpoint, params):
        calls.append(endpoint)
        c._last_error_zero_byte = True
        return None

    c._send_request_once = _once
    assert c.send_request("GetPatientList", {}) is None
    assert calls == ["GetPatientList"], "kill switch must give the legacy single attempt"


def test_pool_idle_seconds_env(monkeypatch):
    monkeypatch.delenv("AIPACS_SOCKET_POOL_IDLE_S", raising=False)
    assert sc._pool_max_idle_seconds() == sc._DEFAULT_POOL_MAX_IDLE_S
    monkeypatch.setenv("AIPACS_SOCKET_POOL_IDLE_S", "5")
    assert sc._pool_max_idle_seconds() == 5.0
    monkeypatch.setenv("AIPACS_SOCKET_POOL_IDLE_S", "not-a-number")
    assert sc._pool_max_idle_seconds() == sc._DEFAULT_POOL_MAX_IDLE_S
