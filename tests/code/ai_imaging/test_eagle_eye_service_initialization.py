"""Service readiness must include native DICOM dependency initialization."""
import builtins
import io
import threading

import pytest

from modules.ai_imaging.eagle_eye_remote import service_host as host, server


@pytest.mark.parametrize('import_fails', [False, True])
def test_dicom_runtime_initializes_on_main_thread_before_listener(monkeypatch, import_fails):
    imported = []
    original = builtins.__import__

    def checked_import(name, *args, **kwargs):
        if name == 'pydicom':
            assert threading.current_thread() is threading.main_thread()
            imported.append(name)
            if import_fails:
                raise ImportError('Synthetic native dependency failure')
        return original(name, *args, **kwargs)

    class ListenerReached(Exception):
        pass

    def create(config):
        assert imported, 'Listener opened before native dependencies initialized'
        assert 'numpy' in host.sys.modules
        raise ListenerReached()

    monkeypatch.setattr(builtins, '__import__', checked_import)
    monkeypatch.setattr(host.sys, 'stdin', io.StringIO('start\n'))
    monkeypatch.setattr(host, 'service_config', lambda path: {})
    monkeypatch.setattr(server, 'create_server', create)
    with pytest.raises(ImportError if import_fails else ListenerReached):
        host.serve_child('synthetic-config')
