"""Inspection must enforce the same command/account boundary as SCM mutations."""
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('account,owned', [
    ('NT AUTHORITY\\LocalService', True),
    ('nt authority\\localservice', True),
    ('LocalSystem', False),
    ('EXAMPLE\\operator', False),
])
def test_service_inspection_requires_local_service_account(monkeypatch, tmp_path, account, owned):
    from modules.ai_imaging.eagle_eye_remote import service_admin as admin

    closed = []
    fake = SimpleNamespace(
        SC_MANAGER_CONNECT=1, SERVICE_QUERY_CONFIG=2, SERVICE_QUERY_STATUS=4,
        SERVICE_RUNNING=5, SERVICE_AUTO_START=6,
        OpenSCManager=lambda *args: 'manager',
        OpenService=lambda *args: 'service',
        QueryServiceConfig=lambda handle: (0, 6, 0, 'exact command', None, 0, None, account),
        QueryServiceStatus=lambda handle: (0, 5),
        CloseServiceHandle=lambda handle: closed.append(handle),
    )
    monkeypatch.setitem(sys.modules, 'win32service', fake)
    monkeypatch.setitem(sys.modules, 'pywintypes', SimpleNamespace(error=OSError))
    monkeypatch.setattr(admin, 'service_command', lambda path: 'exact command')
    state = admin.inspect_service(tmp_path / 'synthetic-server.json')
    assert state == {'installed': True, 'owned': owned, 'running': True, 'automatic': True}
    assert closed == ['service', 'manager']
