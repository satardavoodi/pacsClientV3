"""The concrete fresh driver never guesses post-release drain safety."""
import pytest


@pytest.mark.parametrize('marker_exists', [False, True])
def test_driver_requires_never_released_owned_closed_startup(tmp_path, monkeypatch, marker_exists):
    from tools.eagle_eye import fresh_install_driver as driver
    from modules.ai_imaging.eagle_eye_remote import startup_barrier as barrier
    marker = tmp_path / 'marker.json'
    if marker_exists:
        marker.write_text('{}')
    manifest = {key: key for key in barrier.BINDINGS}
    manifest.update(release_marker_path=str(marker), readiness_path=str(tmp_path/'ready.json'))
    record = {**manifest, 'scm_pid': 123, 'admission': {
        'state': 'quiesced', 'inflight': 0, 'completion_uncertain': False}}
    class Backend:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
        def inspect(self):
            return {'running': True, 'pid': 123, 'command': self.expected_command(candidate),
                    'account': 'NT AUTHORITY\\LocalService'}
        def verify_child(self, value, selected):
            assert value == record and selected == candidate
    monkeypatch.setattr(driver, 'WindowsFreshBackend', Backend)
    monkeypatch.setattr(barrier, 'protected_file', lambda *args, **kwargs: None)
    monkeypatch.setattr(barrier, 'read_record', lambda *args, **kwargs: record)
    candidate = {'root': str(tmp_path/'core')}
    backend = driver.create_backend({'shortcut': str(tmp_path/'server.lnk'),
        'config_path': str(tmp_path/'server.json')}, lambda *args: None)
    if marker_exists:
        backend.cooperative_removal = lambda selected: (_ for _ in ()).throw(RuntimeError('Unproven cooperative transport'))
        with pytest.raises(RuntimeError, match='Unproven cooperative'):
            backend.closed_for_removal(manifest, candidate)
    else:
        proof = backend.closed_for_removal(manifest, candidate)
        assert proof['fresh'] is True and proof['never_released'] is True
        assert proof['state'] == 'quiesced'
    with pytest.raises(RuntimeError, match='upgrade admission'):
        backend.admission()


@pytest.mark.parametrize('installed', [False, True])
def test_pre_start_rollback_requires_owned_stopped_service_and_process_absence(tmp_path, monkeypatch, installed):
    from tools.eagle_eye import fresh_install_driver as driver
    from modules.ai_imaging.eagle_eye_remote import startup_barrier as barrier
    class Backend:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
        def inspect(self):
            return {'installed': installed, 'stopped': True, 'pid': 0,
                'command': self.expected_command(candidate), 'account': 'NT AUTHORITY\\LocalService'}
    monkeypatch.setattr(driver, 'WindowsFreshBackend', Backend)
    monkeypatch.setattr(barrier, 'protected_file', lambda *args, **kwargs: None)
    candidate = {'root': str(tmp_path/'core')}
    backend = driver.create_backend({'shortcut': str(tmp_path/'server.lnk'),
        'config_path': str(tmp_path/'server.json')}, lambda *args: None)
    manifest = {'release_marker_path': str(tmp_path/'marker.json')}
    calls = []
    backend.verify_no_runtime = lambda selected: calls.append(selected)
    assert backend.closed_for_removal(manifest, candidate)['never_released'] is True
    assert calls == [candidate]
    backend.verify_no_runtime = lambda selected: (_ for _ in ()).throw(RuntimeError('orphan unknown'))
    with pytest.raises(RuntimeError, match='orphan unknown'):
        backend.closed_for_removal(manifest, candidate)
