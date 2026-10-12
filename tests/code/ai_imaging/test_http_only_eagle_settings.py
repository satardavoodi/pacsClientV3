"""Ordinary Eagle settings are HTTP-only; Agent pairing is separate."""
from modules.ai_imaging.eagle_eye_remote import administration, settings

def test_existing_profile_normalizes_without_touching_disk(tmp_path, monkeypatch):
    import json
    path=tmp_path/'profile.json'
    original={'url':'https://192.0.2.1:8002','token_file':'legacy','ca_file':'legacy','client_certificate':'legacy','client_private_key':'legacy','other':True}
    path.write_text(json.dumps(original))
    monkeypatch.setenv('AIPACS_EAGLE_EYE_CLIENT_CONFIG',str(path))
    value=settings.client_settings()
    assert value['url']=='http://192.0.2.1:8002'
    assert not set(value)&{'token_file','ca_file','client_certificate','client_private_key'}
    assert value['other'] is True
    assert json.loads(path.read_text())==original

def test_save_removes_legacy_transport_fields(tmp_path):
    import json
    path=tmp_path/'profile.json'
    path.write_text(json.dumps({'url':'https://192.0.2.1:8002','token_file':'legacy'}))
    before=administration.read_connection(path)
    saved=administration.save_connection(path,before['revision'],{'url':'http://192.0.2.1:8002'})
    assert saved['value']['url']=='http://192.0.2.1:8002'
    assert 'token_file' not in saved['value']
