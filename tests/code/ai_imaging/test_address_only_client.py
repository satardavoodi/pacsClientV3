"""Ordinary Eagle APIs use human admission without mandatory device pairing."""
import ssl
from types import SimpleNamespace
import pytest
from modules.ai_imaging.eagle_eye_remote.client import Client
from modules.ai_imaging.eagle_eye_remote.administration import validate_connection

@pytest.mark.parametrize('url',['http://192.0.2.10:8002','https://eagle.example:8002'])
def test_address_only_transport(url,monkeypatch):
    monkeypatch.delenv('AIPACS_EAGLE_EYE_TOKEN',raising=False)
    c=Client(validate_connection({'url':url}))
    assert c.token==''
    seen=[]
    c.opener=SimpleNamespace(open=lambda req,**kw:seen.append(req) or object())
    c.open('/v1/capabilities')
    assert seen[0].get_header('Authorization') is None


def test_https_keeps_default_trust(monkeypatch):
    contexts=[]
    original=ssl.create_default_context
    def create(**kw):
        context=original(**kw);contexts.append(context);return context
    monkeypatch.setattr(ssl,'create_default_context',create)
    monkeypatch.delenv('AIPACS_EAGLE_EYE_TOKEN',raising=False)
    Client({'url':'https://eagle.example:8002'})
    assert contexts[0].check_hostname
    assert contexts[0].verify_mode==ssl.CERT_REQUIRED


def test_stale_optional_pairing_files_do_not_block_address_only(tmp_path,monkeypatch):
    monkeypatch.delenv('AIPACS_EAGLE_EYE_TOKEN',raising=False)
    c=Client({'url':'http://192.0.2.10:8002','token_file':str(tmp_path/'missing'),
        'client_certificate':str(tmp_path/'missing.crt'),'client_private_key':str(tmp_path/'missing.key')})
    assert c.token==''


def test_address_only_protected_request_uses_human_header(monkeypatch):
    import io
    from modules.ai_imaging.eagle_eye_remote import user_session
    monkeypatch.delenv('AIPACS_EAGLE_EYE_TOKEN',raising=False)
    c=Client({'url':'http://192.0.2.10:8002'})
    seen=[]
    c.opener=SimpleNamespace(open=lambda req,**kw:seen.append(req) or io.BytesIO(b'{}'))
    monkeypatch.setattr(user_session,'session',lambda _:('synthetic-human-session','synthetic-user',1))
    monkeypatch.setattr(user_session,'require_generation',lambda _:None)
    with c.open('/v1/echomind/process',{'text':'synthetic'}): pass
    assert seen[0].get_header('Authorization') is None
    assert seen[0].get_header('X-eagle-user-session')=='synthetic-human-session'


def test_address_only_does_not_bypass_human_admission(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import user_session
    from modules.ai_imaging.eagle_eye_remote.client import ServerHTTPError
    c=Client({'url':'http://192.0.2.10:8002'})
    def denied(_): raise ServerHTTPError(401,'Sign in required')
    monkeypatch.setattr(user_session,'session',denied)
    c.opener=SimpleNamespace(open=lambda *a,**k:pytest.fail('No protected request without human admission'))
    with pytest.raises(ServerHTTPError) as error:c.open('/v1/echomind/process',{})
    assert error.value.status==401


def test_existing_legacy_token_is_ignored_by_ordinary_client(tmp_path,monkeypatch):
    monkeypatch.delenv('AIPACS_EAGLE_EYE_TOKEN',raising=False)
    token=tmp_path/'legacy-token';token.write_text('synthetic-legacy-device-token-value')
    monkeypatch.setattr(ssl.SSLContext, 'load_cert_chain', lambda *a, **k: pytest.fail('Ordinary client must not load a device certificate'))
    c=Client({'url':'https://eagle.example:8002','token_file':str(token),
        'client_certificate':str(tmp_path/'legacy.crt'),'client_private_key':str(tmp_path/'legacy.key')})
    seen=[]
    c.opener=SimpleNamespace(open=lambda req,**kw:seen.append(req) or object())
    c.open('/v1/capabilities')
    assert seen[0].get_header('Authorization') is None
    assert seen[0].full_url == 'https://eagle.example:8002/v1/capabilities'
    assert c.token == ''
