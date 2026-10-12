"""Compiled workers must use owned executable dispatch on both freeze backends."""
import json
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture(params=['pyinstaller', 'nuitka'])
def compiled(monkeypatch, request):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.delattr(sys, '__nuitka__', raising=False)
    monkeypatch.setattr(sys, 'frozen' if request.param == 'pyinstaller' else '__nuitka__', True, raising=False)
    from aipacs_runtime import is_frozen
    assert is_frozen()


def test_model_worker_uses_compiled_entry(compiled, monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_remote import server, process_owner
    calls = []
    class Owner:
        def assign(self, process): pass
        def close(self): pass
    class Process:
        import io
        stdout = io.BytesIO(b'Synthetic worker output')
        returncode = 0
        def poll(self): return 0
        def wait(self, timeout): return 0
    monkeypatch.setattr(process_owner, 'ProcessJob', Owner)
    monkeypatch.setattr(server.subprocess, 'Popen', lambda command, **kw: calls.append(command) or Process())
    (tmp_path/'worker-result.json').write_text(json.dumps({'synthetic': True}))
    import threading
    assert server.run_worker(tmp_path, threading.Event()) == {'synthetic': True}
    assert calls == [[sys.executable, '--eagle-eye-worker', str(tmp_path)]]


def test_crm_worker_uses_compiled_entry(compiled, monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_remote.crm import hosting
    calls = []
    class Captured(RuntimeError): pass
    class Owner:
        def close(self): pass
    def capture(command, **kwargs):
        calls.append(command)
        raise Captured('Synthetic launch boundary')
    (tmp_path/'server.json').write_text('{}')
    (tmp_path/'roles.json').write_text('{}')
    monkeypatch.setattr(hosting, 'ProcessJob', Owner)
    monkeypatch.setattr(hosting.subprocess, 'Popen', capture)
    crm = hosting.CRM({'config_dir':str(tmp_path)},SimpleNamespace(directory=tmp_path),{})
    with pytest.raises(Captured): crm._start()
    assert calls == [[sys.executable, '--eagle-eye-crm-worker', 'stdin']]


def test_server_cannot_host_models_from_compiled_client_edition(compiled, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import server, release_package
    import aipacs_runtime
    monkeypatch.setattr(release_package, 'runtime_identity', lambda: {'qualified': True})
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile', lambda: {'distribution_edition':'standard'})
    with pytest.raises(ValueError, match='server edition'):
        server.create_server({})
