"""Explicit approved synthetic humans for legacy transport integration tests."""
import json
import urllib.request
import pytest

from modules.ai_imaging.eagle_eye_remote.contracts import MODULES
from modules.ai_imaging.eagle_eye_remote.user_access import AccessStore, UserAuthority
from modules.network.socket_token_manager import get_socket_token_manager


@pytest.fixture
def human_access(tmp_path, monkeypatch):
    class Provider:
        def login(self,username,password):
            if (username,password)!=('synthetic-user','synthetic-password'):raise ValueError('Synthetic login rejected')
            return 'synthetic-approved-upstream', {'subject':'synthetic-approved-person','username':'synthetic-user'}
        def verify(self, token):
            if token != 'synthetic-approved-upstream':
                raise ValueError('Synthetic identity rejected')
            return {'subject': 'synthetic-approved-person', 'username': 'synthetic-user'}
    authority = UserAuthority(AccessStore(tmp_path / 'human-access.sqlite3', 'synthetic-center'), {'pacs': Provider()})
    principal = authority.store.identify({'provider': 'pacs', **Provider().verify('synthetic-approved-upstream')})
    authority.store.grant(principal, dict(enabled=True, echomind=True, imaging=True, crm=True,
                                         secretary=True, modules=sorted(MODULES)), 'synthetic-console-admin')
    manager = get_socket_token_manager()
    manager.set_token('synthetic-approved-upstream')
    from modules.ai_imaging.eagle_eye_remote import user_session
    user_session.capture_login('synthetic-user','synthetic-password')
    from modules.ai_imaging.eagle_eye_remote import user_access
    monkeypatch.setattr(user_access, 'create_authority', lambda config: authority)
    try:
        yield authority
    finally:
        manager.clear_token()


def session_headers(url, device_token):
    request = urllib.request.Request(url + '/v1/auth/session',
        data=json.dumps({'username':'synthetic-user','password':'synthetic-password'}).encode(),
        headers={'Authorization': 'Bearer ' + device_token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=3) as response:
        session = json.load(response)['user_session']
    return {'Authorization': 'Bearer ' + device_token, 'X-Eagle-User-Session': session}
