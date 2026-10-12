"""Synthetic emergency SCM shutdown guards; no installed service operations."""
import subprocess
import threading
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor, await_private_receipt


def test_explicit_stop_does_not_wait_for_unknown_private_receipt(tmp_path):
    supervisor = Supervisor(tmp_path / 'unused.json', command=['synthetic'])
    stop = threading.Event()
    stop.set()
    events = []
    supervisor.start = lambda: None
    supervisor.stop = lambda report: events.append('stop')
    supervisor.close = lambda: events.append('close')
    def unknown():
        events.append('private-wait')
        raise TimeoutError('Synthetic private receipt remains unknown')
    supervisor.run(stop, lambda state: None, before_close=unknown)
    assert events == ['stop', 'close']


def test_stop_budget_survives_blocked_notification_and_keeps_old_generation(tmp_path):
    entered, release = threading.Event(), threading.Event()
    events = []
    class Input:
        def write(self, value):
            entered.set()
            assert release.wait(2)
            events.append('old-write')
        def flush(self):
            events.append('old-flush')
    process = SimpleNamespace(stdin=Input(), poll=lambda: None)
    def wait(timeout):
        events.append('bounded-wait')
        raise subprocess.TimeoutExpired('synthetic', timeout)
    process.wait = wait
    supervisor = Supervisor(tmp_path / 'unused.json', command=['synthetic'], stop_timeout=.01)
    supervisor.process = process
    try:
        supervisor.stop(lambda state: None)
        assert entered.is_set()
        assert 'bounded-wait' in events
        supervisor.process = SimpleNamespace(stdin=SimpleNamespace(write=lambda value: events.append('new-write')))
    finally:
        release.set()
        sender = getattr(supervisor, 'stop_sender', None)
        if sender is not None:
            sender.join(1)
    assert 'new-write' not in events


def test_resource_close_does_not_wait_on_busy_notification_stream(tmp_path):
    events = []
    supervisor = Supervisor(tmp_path / 'unused.json', command=['synthetic'])
    supervisor.owner = SimpleNamespace(close=lambda: events.append('job-close'))
    supervisor.stop_sender = SimpleNamespace(is_alive=lambda: True)
    supervisor.process = SimpleNamespace(
        poll=lambda: 0, wait=lambda timeout: None,
        stdin=SimpleNamespace(close=lambda: events.append('stdin-close')),
        stdout=SimpleNamespace(close=lambda: events.append('stdout-close')))
    supervisor.close()
    assert events == ['job-close', 'stdout-close']


def test_scm_stop_arriving_during_private_wait_releases_owned_close():
    stop = threading.Event()
    waits = []
    def wait(timeout):
        waits.append(timeout)
        stop.set()
        return False
    await_private_receipt(SimpleNamespace(wait=wait), stop, lambda message: pytest.fail('Unexpected warning'))
    assert waits == [1]


def test_resource_close_does_not_reacquire_active_reader_stream(tmp_path):
    supervisor = Supervisor(tmp_path / 'unused.json', command=['synthetic'])
    events = []
    supervisor.reader = SimpleNamespace(join=lambda timeout: events.append('reader-join'), is_alive=lambda: True)
    supervisor.process = SimpleNamespace(poll=lambda: 0, wait=lambda timeout: None,
        stdin=SimpleNamespace(close=lambda: events.append('stdin-close')),
        stdout=SimpleNamespace(close=lambda: pytest.fail('Active reader stream lock')))
    supervisor.close()
    assert events == ['reader-join', 'stdin-close']
