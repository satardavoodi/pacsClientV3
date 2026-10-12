"""Synthetic socket and private-pipe transport diagnostic integration guards."""
import io
import json
import socket
import ssl
import threading
import time
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_remote.service_host import DIAGNOSTICS, Supervisor, diagnostic_command, transition_command
from modules.ai_imaging.eagle_eye_remote.transport_diagnostics import Counters
from tests.code.ai_imaging.test_ordinary_human_http import ordinary_service


def test_auth_and_capability_responses_are_counted(ordinary_service):
    call, authority, http = ordinary_service
    assert call('/v1/capabilities')[0] == 200
    status, reply = call('/v1/auth/session', {'username':'alpha','password':'synthetic-password'})
    assert status == 200
    assert call('/v1/auth/me', session=reply['user_session'])[0] == 200
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        counts = http.transport_diagnostics.snapshot()['counts']['response_completed']
        if counts['auth_me']:
            break
        time.sleep(.005)
    assert counts['auth_session'] == counts['auth_me'] == counts['public_capabilities'] == 1


def test_real_socket_invalid_preface_and_capacity_are_classified(ordinary_service):
    _, _, http = ordinary_service
    with socket.create_connection(http.server_address, timeout=2) as peer:
        peer.sendall(b'Z synthetic invalid preface')
        try:
            peer.recv(1)
        except ConnectionError:
            pass
    deadline = time.monotonic() + 2
    while not http.transport_diagnostics.snapshot()['counts']['invalid_preface']['other'] and time.monotonic() < deadline:
        time.sleep(.01)
    assert http.transport_diagnostics.snapshot()['counts']['invalid_preface']['other'] == 1
    for _ in range(64):
        assert http.connection_slots.acquire(False)
    try:
        with socket.create_connection(http.server_address, timeout=2) as peer:
            peer.sendall(b'GET /v1/capabilities HTTP/1.0\r\n\r\n')
            try:
                peer.recv(1)
            except ConnectionError:
                pass
        assert http.transport_diagnostics.snapshot()['counts']['connection_capacity_refused']['other'] == 1
    finally:
        for _ in range(64):
            http.connection_slots.release()


@pytest.mark.parametrize('change', [ {'protocol':True}, {'request_id':'private-secret'}, {'extra':'private-secret'}, {'operation':'stop_when_idle'} ])
def test_private_diagnostic_parser_rejects_extra_or_wrong_fields(change):
    body = dict(protocol=1,operation='transport_diagnostics',request_id='a'*32)
    body.update(change)
    with pytest.raises(ValueError):
        diagnostic_command(json.dumps(body), Counters())


def test_diagnostics_are_not_transition_commands():
    body = json.dumps(dict(protocol=1,operation='transport_diagnostics',request_id='a'*32))
    counters = Counters()
    result = diagnostic_command(body, counters)
    assert result['snapshot'] == counters.snapshot()
    with pytest.raises(ValueError):
        transition_command(body, None, threading.Event())


def test_private_reader_uses_separate_bounded_validated_queue():
    supervisor = Supervisor('unused', command=['synthetic'])
    good = dict(protocol=1,request_id='a'*32,snapshot=Counters().snapshot())
    bad = dict(good, extra='private-secret')
    frame = DIAGNOSTICS + json.dumps(good) + '\n'
    assert 512 < len(frame) <= 4096
    supervisor.process = SimpleNamespace(stdout=io.StringIO(
        DIAGNOSTICS + 'x'*5000 + '\n' + DIAGNOSTICS + json.dumps(bad)+'\n' + frame))
    supervisor._read_status()
    assert supervisor.diagnostics.get_nowait() == good
    assert supervisor.diagnostics.empty() and supervisor.transitions.empty()


def test_private_diagnostic_api_correlates_without_transition_or_stop():
    supervisor = Supervisor('unused', command=['synthetic'])
    snapshot = Counters().snapshot()
    class Pipe(io.StringIO):
        def flush(self):
            value = json.loads(self.getvalue().splitlines()[-1])
            assert set(value) == {'protocol','operation','request_id'}
            assert value['operation'] == 'transport_diagnostics'
            supervisor.diagnostics.put(dict(protocol=1,request_id='b'*32,snapshot=snapshot))
            supervisor.diagnostics.put(dict(protocol=1,request_id=value['request_id'],snapshot=snapshot))
    supervisor.process = SimpleNamespace(stdin=Pipe(),poll=lambda:None)
    supervisor.ready.set()
    assert supervisor.transport_diagnostics(timeout=.5) == snapshot
    assert not supervisor.certified_idle.is_set() and not supervisor.transition_requested.is_set()


def test_missing_diagnostic_reply_never_changes_lifecycle():
    supervisor = Supervisor('unused', command=['synthetic'])
    supervisor.process = SimpleNamespace(stdin=io.StringIO(),poll=lambda:None)
    supervisor.ready.set()
    with pytest.raises(TimeoutError):
        supervisor.transport_diagnostics(timeout=.02)
    assert not supervisor.certified_idle.is_set() and not supervisor.transition_requested.is_set()


@pytest.mark.parametrize('preface,error,reason', [
    (b'', None, 'peer_closed_before_preface'),
    (b'', TimeoutError, 'first_byte_timeout'),
    (b'', ConnectionResetError, 'first_byte_read_failed'),
    (b'\x16', None, 'tls_unavailable'),
])
def test_preface_failures_are_fixed_counters(preface, error, reason):
    from http.server import BaseHTTPRequestHandler
    from modules.ai_imaging.eagle_eye_remote.server import HumanHTTPServer
    http = HumanHTTPServer(('127.0.0.1',0), BaseHTTPRequestHandler)
    class Peer:
        def settimeout(self, timeout):
            pass
        def recv(self, *args):
            if error:
                raise error('Synthetic private transport failure')
            return preface
        def close(self):
            pass
    try:
        assert http.connection_slots.acquire(False)
        http.process_request_thread(Peer(), ('127.0.0.1',1))
        snapshot = http.transport_diagnostics.snapshot()
        assert snapshot['counts'][reason]['other'] == 1
        assert 'Synthetic private transport failure' not in json.dumps(snapshot)
    finally:
        http.server_close()
