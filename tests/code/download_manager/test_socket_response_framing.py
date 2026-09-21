"""Synthetic wire-level guards: no PACS, credentials, clinical files or database."""

import json
import socket
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from modules.download_manager.network import socket_client as sc


def frame(value):
    body = json.dumps(value, ensure_ascii=False).encode('utf-8')
    return len(body).to_bytes(4, 'big') + body


BROADCAST = {'type': 'broadcast', 'event_type': 'synthetic_update'}
REPLY = {'status': 'success', 'data': {'value': 'Synthetic \u00e9', 'dicom_data': 'AP8='}}


class WireSocket:
    def __init__(self, wire=b'', fragment=None):
        self.wire = bytearray(wire)
        self.fragment = fragment
        self.sent = bytearray()
        self.closed = False
        self.reads = 0
        self.timeouts = []

    def recv(self, size):
        self.reads += 1
        count = min(size, self.fragment or size, len(self.wire))
        chunk = bytes(self.wire[:count])
        del self.wire[:count]
        return chunk

    def sendall(self, data):
        self.sent.extend(data)

    def close(self):
        self.closed = True

    def shutdown(self, _how):
        pass

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def setsockopt(self, *_args):
        pass

    def connect(self, _address):
        pass


def client_for(sock, *, timeout=1):
    token = MagicMock()
    token.has_token.return_value = False
    client = sc.SocketDicomClient(token_manager=token, health_monitor=MagicMock(), timeout=timeout)
    client.socket = sock
    client.connected = True
    return client


@pytest.mark.parametrize('broadcasts', [0, 1, 9, 10, 11, 75])
@pytest.mark.parametrize('fragment', [None, 1, 2, 3])
def test_broadcast_bursts_and_fragmented_headers_preserve_the_actual_reply(broadcasts, fragment):
    sock = WireSocket(frame(BROADCAST) * broadcasts + frame(REPLY), fragment)
    client = client_for(sock, timeout=10)
    assert client._send_request_once('GetSeriesImages', {}) == REPLY
    assert not sock.wire
    assert client.connected and not sock.closed
    assert not client.lock.locked() if hasattr(client.lock, 'locked') else True


def test_two_requests_on_one_socket_do_not_consume_each_others_replies():
    other = {'status': 'success', 'data': {'value': 'second'}}
    sock = WireSocket(frame(BROADCAST) * 12 + frame(REPLY) + frame(other), 3)
    client = client_for(sock)
    assert client._send_request_once('GetSeriesImages', {'batch_index': 0}) == REPLY
    assert client._send_request_once('GetSeriesImages', {'batch_index': 1}) == other


def test_broadcast_only_stream_expires_by_elapsed_budget_and_discards_socket(monkeypatch):
    clock = SimpleNamespace(value=0.0)
    monkeypatch.setattr(sc, 'time', SimpleNamespace(monotonic=lambda: clock.value))

    class Flood(WireSocket):
        generated = 0

        def recv(self, size):
            if not self.wire:
                self.wire.extend(frame(BROADCAST))
                self.generated += 1
                clock.value += .25
            return super().recv(size)

    sock = Flood()
    client = client_for(sock)
    assert client._send_request_once('GetSeriesImages', {}) is None
    assert sock.generated <= 4, 'notification count must not replace the elapsed-time budget'
    assert sock.closed and not client.connected and client.socket is None


@pytest.mark.parametrize('broadcast_first', [False, True])
def test_large_real_response_body_keeps_existing_transfer_timeout(monkeypatch, broadcast_first):
    clock = SimpleNamespace(value=0.0)
    monkeypatch.setattr(sc, 'time', SimpleNamespace(monotonic=lambda: clock.value))

    class SlowBody(WireSocket):
        def recv(self, size):
            value = super().recv(size)
            if size != 4:
                clock.value += .1
            return value

    # The total real payload transfer may exceed the header/broadcast wait
    # budget. Do not introduce a new whole-batch wall-clock limit.
    sock = SlowBody((frame(BROADCAST) if broadcast_first else b'') + frame(REPLY), 8)
    client = client_for(sock, timeout=.9)
    assert client._send_request_once('GetSeriesImages', {}) == REPLY
    assert clock.value > client.timeout


def test_header_wait_after_broadcast_uses_remaining_budget_then_restores_timeout(monkeypatch):
    clock = SimpleNamespace(value=0.0)
    monkeypatch.setattr(sc, 'time', SimpleNamespace(monotonic=lambda: clock.value))

    class DelayedNotice(WireSocket):
        def recv(self, size):
            value = super().recv(size)
            if self.reads == 2:
                clock.value = .75
            return value

    sock = DelayedNotice(frame(BROADCAST) + frame(REPLY))
    client = client_for(sock)
    assert client._send_request_once('GetSeriesImages', {}) == REPLY
    assert sock.timeouts == [.25, 1]


def test_real_socketpair_preserves_framed_reply_and_request():
    left, right = socket.socketpair()
    left.settimeout(2)
    right.settimeout(2)
    client = client_for(left, timeout=2)
    try:
        # Loopback-only synthetic exchange; a small payload fits the socket
        # buffer so no server/thread/process needs to be left running.
        right.sendall(frame(BROADCAST) * 15 + frame(REPLY))
        assert client._send_request_once('GetSeriesImages', {'batch_index': 2}) == REPLY
        length = int.from_bytes(right.recv(4), 'big')
        body = bytearray()
        while len(body) < length:
            body.extend(right.recv(length - len(body)))
        request = json.loads(body)
        assert request == {'endpoint': 'GetSeriesImages', 'params': {'batch_index': 2}}
    finally:
        client.disconnect()
        right.close()


@pytest.mark.parametrize('wire', [b'\0\0', b'\0\0\0\0', frame([]), b'\0\0\0\1\xff', b'\0\0\0\1{'])
def test_incomplete_or_invalid_frame_cannot_leave_a_reusable_stream(wire):
    sock = WireSocket(wire)
    client = client_for(sock)
    assert client._send_request_once('GetSeriesImages', {}) is None
    assert sock.closed and client.socket is None and not client.connected


def test_cancellation_between_broadcasts_does_not_wait_for_another_header():
    class CancelAfterBroadcast(WireSocket):
        def recv(self, size):
            result = super().recv(size)
            if not self.wire:
                client.request_cancel()
            return result

    sock = CancelAfterBroadcast(frame(BROADCAST))
    client = client_for(sock)
    reply = client._send_request_once('GetSeriesImages', {})
    assert reply['status'] == 'cancelled'
    assert sock.reads == 2, 'cancel must be checked before waiting for another header'
    assert sock.closed and not client.connected


def test_server_error_is_returned_unchanged_without_retry(monkeypatch):
    rejection = {'status': 'error', 'message': 'forbidden'}
    sock = WireSocket(frame(BROADCAST) * 11 + frame(rejection))
    client = client_for(sock)
    def unexpected_retry(*_args):
        raise AssertionError('a valid server error must not be retried')
    monkeypatch.setattr(client, '_sleep_with_cancel', unexpected_retry)
    assert client.send_request('GetSeriesImages', {}) == rejection
    assert not sock.closed


def test_disconnected_request_can_connect_without_recursive_lock_deadlock(monkeypatch):
    sock = WireSocket(frame(REPLY))
    client = client_for(sock)
    client.connected = False
    client.socket = None
    monkeypatch.setattr(sc.socket, 'socket', lambda *_a, **_k: sock)
    replies = []
    worker = threading.Thread(target=lambda: replies.append(client._send_request_once('GetSeriesImages', {})))
    worker.start()
    worker.join(1)
    stuck = worker.is_alive()
    if stuck:
        # Pre-fix Lock can be released by this test thread to let the inner
        # connect finish. Never leave a blocked thread behind after red proof.
        client.lock.release()
        worker.join(1)
    assert not worker.is_alive()
    assert not stuck, 'request lock deadlocked its own connect() call'
    assert replies == [REPLY]
