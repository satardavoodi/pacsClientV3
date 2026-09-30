"""Bounded SCM primitives exercised only against a synthetic service manager."""
import sys
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_remote import service_admin as admin


@pytest.fixture
def scm(monkeypatch):
    fake = SimpleNamespace(**{name: index + 1 for index, name in enumerate([
        'SC_MANAGER_CONNECT', 'SERVICE_QUERY_CONFIG', 'SERVICE_QUERY_STATUS',
        'SERVICE_STOP', 'SERVICE_START', 'DELETE', 'SERVICE_STOPPED',
        'SERVICE_RUNNING', 'SERVICE_STOP_PENDING', 'SERVICE_START_PENDING',
        'SERVICE_CONTROL_STOP'])})
    fake.calls = []
    fake.state = fake.SERVICE_RUNNING
    fake.command = 'owned-command'
    fake.account = 'NT AUTHORITY\\LocalService'
    fake.stuck = False
    fake.OpenSCManager = lambda *args: 'manager'
    fake.OpenService = lambda *args: 'service'
    fake.QueryServiceConfig = lambda handle: (0, 0, 0, fake.command, '', 0, [], fake.account, '')
    fake.QueryServiceStatus = lambda handle: (0, fake.state, 0, 0, 0, 0, 0)
    fake.CloseServiceHandle = lambda handle: fake.calls.append(('close', handle))
    def stop(*args):
        fake.calls.append(('stop',))
        fake.state = fake.SERVICE_STOP_PENDING if fake.stuck else fake.SERVICE_STOPPED
    def start(*args):
        fake.calls.append(('start',))
        fake.state = fake.SERVICE_START_PENDING if fake.stuck else fake.SERVICE_RUNNING
    fake.ControlService = stop
    fake.StartService = start
    fake.DeleteService = lambda handle: fake.calls.append(('delete',))
    monkeypatch.setitem(sys.modules, 'win32service', fake)
    monkeypatch.setattr(admin, 'service_command', lambda path: 'owned-command')
    return fake


@pytest.mark.parametrize('operation', ['stop_owned_service', 'start_owned_service', 'remove_owned_service'])
@pytest.mark.parametrize('mismatch', ['command', 'account'])
def test_unrelated_service_is_never_mutated(scm, operation, mismatch):
    setattr(scm, mismatch, 'unrelated')
    with pytest.raises(ValueError, match='ownership'):
        getattr(admin, operation)('synthetic')
    assert not any(c[0] in {'stop', 'start', 'delete'} for c in scm.calls)
    assert scm.calls[-2:] == [('close', 'service'), ('close', 'manager')]


def test_remove_stops_owned_service_before_deleting(scm):
    admin.remove_owned_service('synthetic')
    assert [c[0] for c in scm.calls] == ['stop', 'delete', 'close', 'close']


def test_stop_start_supports_recovery_without_reconfiguring(scm):
    assert admin.stop_owned_service('synthetic') is True
    assert admin.stop_owned_service('synthetic') is False
    assert admin.start_owned_service('synthetic') is True
    assert admin.start_owned_service('synthetic') is False
    assert [c[0] for c in scm.calls if c[0] != 'close'] == ['stop', 'start']


def test_timeout_never_deletes_or_kills_service(scm, monkeypatch):
    scm.stuck = True
    now = iter([0., 0., 2.])
    monkeypatch.setattr(admin.time, 'monotonic', lambda: next(now))
    monkeypatch.setattr(admin.time, 'sleep', lambda seconds: None)
    with pytest.raises(TimeoutError):
        admin.remove_owned_service('synthetic', timeout=1.)
    assert ('delete',) not in scm.calls
    assert scm.calls[-2:] == [('close', 'service'), ('close', 'manager')]


@pytest.mark.parametrize('timeout', [0, -1, float('inf'), float('nan'), 121])
def test_invalid_timeout_rejected_before_scm_access(scm, timeout):
    scm.OpenSCManager = lambda *args: pytest.fail('Invalid budget reached SCM')
    with pytest.raises(ValueError):
        admin.stop_owned_service('synthetic', timeout=timeout)


@pytest.mark.parametrize('operation', ['start_owned_service', 'remove_owned_service'])
def test_scm_command_failure_propagates_and_closes_handles(scm, operation):
    def failed(*args):
        raise OSError('Synthetic SCM failure')
    scm.state = scm.SERVICE_STOPPED
    scm.StartService = failed
    scm.DeleteService = failed
    with pytest.raises(OSError, match='Synthetic SCM failure'):
        getattr(admin, operation)('synthetic')
    assert scm.calls[-2:] == [('close', 'service'), ('close', 'manager')]


def test_missing_service_is_not_created(scm):
    def missing(*args):
        raise OSError('Synthetic missing service')
    scm.OpenService = missing
    with pytest.raises(OSError, match='missing service'):
        admin.remove_owned_service('synthetic')
    assert scm.calls == [('close', 'manager')]


def test_existing_stop_pending_is_waited_without_second_stop(scm):
    states = iter([scm.SERVICE_STOP_PENDING, scm.SERVICE_STOPPED])
    scm.QueryServiceStatus = lambda handle: (0, next(states), 0, 0, 0, 0, 0)
    admin.remove_owned_service('synthetic')
    assert [c[0] for c in scm.calls] == ['delete', 'close', 'close']
