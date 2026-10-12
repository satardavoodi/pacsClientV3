import pytest
from modules.ai_imaging.eagle_eye_remote.reception_identity import ReceptionIdentity

def test_reception_roster_projects_only_identity(monkeypatch):
    adapter = ReceptionIdentity({'protocol':'ino-admin-user-v1','base_url':'http://127.0.0.1:8080'})
    monkeypatch.setattr(adapter, '_request', lambda *a, **k: [
        {'_id':'1234567890abcdef12345678','User':'synthetic','Password':'discard','Deactive':False},
        {'_id':'abcdef1234567890abcdef12','User':'disabled','Deactive':True}], raising=True)
    assert adapter.roster('synthetic-token') == [{'subject':'1234567890abcdef12345678','username':'synthetic','provider':'reception'}]


def test_import_requires_admin_before_roster(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import user_administration as admin
    calls = []
    class Adapter:
        def __init__(self, config): pass
        def _login(self, username, password, *, console):
            assert console is True
            calls.append('admin')
            raise PermissionError('denied')
        def roster(self, token):
            calls.append('roster')
    monkeypatch.setattr(admin, 'console_store', lambda session: (object(), {'user_access':{'providers':{'reception':{'protocol':'ino-admin-user-v1'}}}}))
    monkeypatch.setattr('modules.ai_imaging.eagle_eye_remote.reception_identity.ReceptionIdentity', Adapter)
    with pytest.raises(PermissionError): admin.import_reception('console','synthetic','synthetic')
    assert calls == ['admin']

def test_logs_are_opt_in_source_guard():
    from pathlib import Path
    source = Path('PacsClient/pacs/workstation_ui/settings_ui/user_settings.py').read_text(encoding='utf-8')
    assert 'self.audit.hide()' in source
    assert 'if self.show_logs.isChecked():' in source
    assert "Import Reception users" in source
