"""Installer consumes exact committed private control proof, never force fallback."""
import pytest


@pytest.mark.parametrize('pid,refuses', [(4, False), (0, False), (4321, True)])
def test_process_absence_ignores_only_reserved_kernel_pids(tmp_path, monkeypatch, pid, refuses):
    import psutil
    from tools.eagle_eye import fresh_install_driver as driver
    class Backend:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    class Process:
        def exe(self):
            raise psutil.AccessDenied(self.pid)
    process = Process(); process.pid = pid
    monkeypatch.setattr(driver, 'WindowsFreshBackend', Backend)
    monkeypatch.setattr(psutil, 'process_iter', lambda: [process])
    backend = driver.create_backend({'shortcut': str(tmp_path/'server.lnk'),
        'config_path': str(tmp_path/'server.json')}, lambda *args: None)
    if refuses:
        with pytest.raises(RuntimeError, match='absence could not'):
            backend.verify_no_runtime({'root': str(tmp_path/'core')})
    else:
        backend.verify_no_runtime({'root': str(tmp_path/'core')})


@pytest.mark.parametrize('outcome', ['committed', 'unknown', 'wrong_identity'])
def test_post_marker_removal_requires_correlated_commit_and_observed_stopped(tmp_path, monkeypatch, outcome):
    from tools.eagle_eye import fresh_install_driver as driver
    from modules.ai_imaging.eagle_eye_remote import service_control, startup_barrier
    candidate = {'root': str(tmp_path/'core')}
    calls = []
    class Backend:
        timeout = 1
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.completed = False
        def inspect(self):
            return {'installed': True, 'running': not self.completed, 'stopped': self.completed,
                'pid': 0 if self.completed else 123, 'command': self.expected_command(candidate),
                'account': 'NT AUTHORITY\\LocalService'}
        def stop(self):
            raise AssertionError('SCM stop fallback is forbidden')
    monkeypatch.setattr(driver, 'WindowsFreshBackend', Backend)
    monkeypatch.setattr(startup_barrier, 'protected_file', lambda *args, **kwargs: None)
    request = {'shortcut': str(tmp_path/'server.lnk'), 'config_path': str(tmp_path/'server.json')}
    backend = driver.create_backend(request, lambda *args: None)
    expected = {'scm_command': backend.expected_command(candidate)}
    def identity(*args, **kwargs):
        assert args[0] == request['config_path'] and args[1] == tmp_path/'core'
        assert kwargs['scm_pid'] == 123
        return expected
    monkeypatch.setattr(service_control, 'reviewed_identity', identity, raising=False)
    def stop(config, selected, deadline):
        calls.append('private_control')
        assert config == request['config_path'] and selected == expected
        if outcome == 'unknown':
            raise TimeoutError('Unknown private completion')
        backend.completed = True
        return {'result': 'committed', 'code': 'CERTIFIED_IDLE_EXIT',
            'identity': {} if outcome == 'wrong_identity' else expected,
            'closed': True, 'inflight': 0, 'completion_uncertain': False}
    monkeypatch.setattr(service_control, 'stop_when_idle', stop)
    backend.verify_no_runtime = lambda selected: calls.append('process_absence')
    marker = tmp_path/'marker.json'; marker.write_text('{}')
    if outcome == 'committed':
        proof = backend.closed_for_removal({'release_marker_path': str(marker)}, candidate)
        assert proof['cooperatively_stopped'] is True
        assert calls == ['private_control', 'process_absence']
    else:
        with pytest.raises((RuntimeError, TimeoutError)):
            backend.closed_for_removal({'release_marker_path': str(marker)}, candidate)
        assert calls == ['private_control']
