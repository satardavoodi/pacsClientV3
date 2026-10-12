"""Console-to-ordinary admission uses synthetic identities and no provider I/O."""
import pytest
from modules.ai_imaging.eagle_eye_remote import user_session
from modules.ai_imaging.eagle_eye_remote.client import ServerHTTPError
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def isolated_identity(monkeypatch):
    monkeypatch.setattr(user_session,'identity',lambda:((1,user_session._epoch),None))
    user_session.clear()
    yield
    user_session.clear()


def result(source='pacs',subject='synthetic-subject'):
    return {'session':'synthetic-console-session','user':{
        'auth_source':source,'provider':source,'subject':subject}}


@pytest.mark.parametrize('provider',['pacs','reception'])
def test_successful_console_context_uses_standard_exchange_and_exact_subject(provider):
    context=user_session.ConsoleLoginContext()
    operation=context.begin('synthetic-user','synthetic-password')
    assert context.accept(operation,result(provider),lambda value:True)
    calls=[]
    client=SimpleNamespace(url='https://synthetic.invalid',token='',_profile_key='synthetic',opener=None)
    def exchange(path,body):
        calls.append((path,body))
        return {'user_session':'synthetic-ordinary-session-0123456789','expires_in':60,
                'user':{'provider':provider,'subject':'synthetic-subject','principal':'server-derived-principal'}}
    client.json=exchange
    assert user_session.session(client)[1]=='server-derived-principal'
    assert calls[0][0]=='/v1/auth/session'
    assert set(calls[0][1])=={'username','password'}


@pytest.mark.parametrize('provider,subject',[('reception','synthetic-subject'),('pacs','different')])
def test_cross_authority_response_never_enters_cache(provider,subject):
    user_session.capture_login('synthetic-user','synthetic-password',expected_provider='pacs',expected_subject='synthetic-subject')
    client=SimpleNamespace(url='https://synthetic.invalid',token='',opener=None)
    client.json=lambda *args:{'user_session':'synthetic-ordinary-session-0123456789','expires_in':60,
        'user':{'provider':provider,'subject':subject,'principal':'server-derived'}}
    with pytest.raises(ServerHTTPError): user_session.session(client)
    assert not user_session._sessions


def test_stale_completion_and_local_superadmin_cannot_capture():
    context=user_session.ConsoleLoginContext()
    old=context.begin('synthetic-old','synthetic-password')
    current=context.begin('synthetic-current','synthetic-password')
    assert not context.accept(old,result(),lambda value:True)
    assert user_session._login_credentials is None
    assert context.accept(current,result('eagle-eye-console'),lambda value:True)
    assert user_session._login_credentials is None


def test_account_change_and_invalid_console_discard_credentials():
    context=user_session.ConsoleLoginContext()
    operation=context.begin('synthetic-user','synthetic-password')
    user_session.clear()
    assert not context.accept(operation,result(),lambda value:True)
    operation=context.begin('synthetic-user','synthetic-password')
    assert not context.accept(operation,result(),lambda value:False)
    assert user_session._login_credentials is None


def test_logout_revokes_only_the_matching_current_console():
    from modules.ai_imaging.eagle_eye_remote import admin_auth
    context=user_session.ConsoleLoginContext()
    old=context.begin('synthetic-user','synthetic-password')
    assert context.accept(old,result(),lambda value:True)
    current=context.begin('synthetic-user','synthetic-password')
    fresh=result();fresh['session']='synthetic-fresh-console'
    assert context.accept(current,fresh,lambda value:True)
    captured=user_session._login_credentials
    for foreign in (None,'synthetic-foreign','synthetic-console-session'):
        admin_auth.invalidate_session(foreign)
        assert user_session._login_credentials is captured
    admin_auth.invalidate_session('synthetic-fresh-console')
    assert user_session._login_credentials is None


def test_stale_capture_rejected_before_newer_context_is_cleared():
    old=user_session.identity()[0]
    user_session.clear()
    user_session.capture_login('synthetic-fresh','synthetic-password')
    fresh=user_session._login_credentials
    assert user_session.capture_login('synthetic-old','synthetic-password',expected_generation=old) is None
    assert user_session._login_credentials is fresh


def test_oversized_attempt_does_not_retain_credentials():
    context=user_session.ConsoleLoginContext()
    operation=context.begin('synthetic-user','x'*4097)
    assert context.pending is None
    assert not context.accept(operation,result(),lambda value:True)
