"""Synthetic-only upstream identity, approval, scope and usage contracts."""
import pytest
from modules.ai_imaging.eagle_eye_remote.user_access import AccessStore, UserAuthority, UserDenied


class Provider:
    def __init__(self):
        self.calls = 0
        self.revoked = False
        self.identity = {'subject':'synthetic-id','username':'synthetic-user'}

    def login(self, username, password):
        if username != 'synthetic-user' or password != 'synthetic-password':
            raise ValueError('Denied')
        return 'synthetic-upstream-token', self.identity

    def verify(self, token):
        self.calls += 1
        if self.revoked or token != 'synthetic-upstream-token':
            raise ValueError('Revoked')
        return dict(self.identity)


@pytest.fixture
def access(tmp_path):
    store = AccessStore(tmp_path/'access.sqlite3', 'synthetic-center')
    provider = Provider()
    return UserAuthority(store, {'pacs':provider}), provider


def approve(authority, **changes):
    principal = authority.store.identify({'provider':'pacs','subject':'synthetic-id','username':'synthetic-user'})
    grant = dict(enabled=True,echomind=True,imaging=True,crm=False,secretary=False,modules=['bone-age'])
    authority.store.grant(principal, {**grant,**changes}, 'synthetic-console-admin')
    return principal


def login(authority):
    return authority.login('synthetic-device', {'username':'synthetic-user','password':'synthetic-password'})


def test_valid_upstream_identity_is_not_automatic_permission(access):
    authority, provider = access
    with pytest.raises(UserDenied) as error:
        login(authority)
    assert error.value.status == 403
    assert provider.calls == 1
    assert authority.store.users()[0]['enabled'] == 0


def test_invalid_upstream_cannot_use_existing_grants(access):
    authority, provider = access
    approve(authority)
    provider.revoked = True
    with pytest.raises(UserDenied) as error:
        login(authority)
    assert error.value.status == 401
    assert not authority.sessions


def test_grants_and_upstream_rechecked_on_every_request(access):
    authority, provider = access
    approve(authority)
    session = login(authority)['user_session']
    user = authority.verify('synthetic-device', session)
    authority.require(user,'imaging','bone-age')
    with pytest.raises(UserDenied):
        authority.require(user,'imaging','brain')
    with pytest.raises(UserDenied):
        authority.require(user,'secretary')
    approve(authority, enabled=False)
    with pytest.raises(UserDenied) as error:
        authority.verify('synthetic-device',session)
    assert error.value.status == 403
    assert provider.calls == 3


def test_device_binding_revocation_logout_and_no_secret_persistence(access):
    authority, provider = access
    approve(authority)
    result = authority.login('synthetic-device',{'provider':'pacs','username':'synthetic-user','password':'synthetic-password'})
    session = result['user_session']
    with pytest.raises(UserDenied):
        authority.verify('other-device',session)
    provider.revoked = True
    with pytest.raises(UserDenied):
        authority.verify('synthetic-device',session)
    assert not authority.sessions
    provider.revoked = False
    session = login(authority)['user_session']
    authority.logout('synthetic-device',session)
    with pytest.raises(UserDenied):
        authority.verify('synthetic-device',session)
    contents = authority.store.path.read_bytes()
    assert b'synthetic-password' not in contents
    assert b'synthetic-upstream-token' not in contents
    assert session.encode() not in contents


@pytest.mark.parametrize('body', [
    {'provider':'local','username':'synthetic-user','password':'synthetic-password'},
    {'provider':'pacs','username':'synthetic-user'},
    {'provider':'pacs','username':'synthetic-user','password':'synthetic-password','subject':'spoofed'},
    {'provider':'pacs','upstream_token':'synthetic-upstream-token','username':'synthetic-user'},
])
def test_username_only_local_admin_and_untrusted_claims_rejected(access,body):
    authority,_ = access
    with pytest.raises(UserDenied):
        authority.login('synthetic-device',body)


def test_identity_source_and_store_center_are_independent(access):
    authority,_ = access
    original = approve(authority)
    other = authority.store.identify({'provider':'reception','subject':'synthetic-id','username':'synthetic-user'})
    assert original != other
    assert not authority.store.user(other)['enabled']
    with pytest.raises(ValueError):
        AccessStore(authority.store.path, 'other-center')


def test_retries_do_not_double_count_and_status_advances(access):
    authority,_ = access
    principal = approve(authority)
    for state in ('queued','retrieving','succeeded','accepted'):
        authority.store.event(principal,'synthetic-device','imaging.bone-age',state,'synthetic-request')
    counts = [x for x in authority.store.audit(principal)['counts'] if x['operation']=='imaging.bone-age']
    assert counts == [{'operation':'imaging.bone-age','outcome':'succeeded','requests':1}]


def test_reception_only_authority_does_not_require_pacs(tmp_path):
    provider = Provider()
    authority = UserAuthority(AccessStore(tmp_path/'reception.sqlite3','synthetic-center'), {'reception':provider})
    principal = authority.store.identify({'provider':'reception',**provider.identity})
    authority.store.grant(principal,dict(enabled=True,echomind=True,imaging=False,crm=True,secretary=False,modules=[]),'synthetic-admin')
    result = authority.login('synthetic-device',{'username':'synthetic-user','password':'synthetic-password'})
    assert authority.verify('synthetic-device',result['user_session'])['provider']=='reception'


def test_password_exchange_verifies_identity_without_persisting_password(access):
    authority,provider = access
    approve(authority)
    value = authority.login('synthetic-device',{'provider':'pacs','username':'synthetic-user','password':'synthetic-password'})
    assert provider.calls == 1
    assert authority.verify('synthetic-device',value['user_session'])['username']=='synthetic-user'
    assert b'synthetic-password' not in authority.store.path.read_bytes()
    assert 'synthetic-password' not in repr(authority.sessions)


def test_expired_session_fails_before_upstream_io(access,monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import user_access
    authority,provider = access
    clock=[100.0]
    monkeypatch.setattr(user_access.time,'monotonic',lambda:clock[0])
    approve(authority);session=login(authority)['user_session'];calls=provider.calls
    clock[0]+=3601
    with pytest.raises(UserDenied) as caught: authority.verify('synthetic-device',session)
    assert caught.value.status==401 and provider.calls==calls


def test_unconfigured_provider_and_login_rate_limit_fail_closed(access):
    authority,provider=access
    provider.available=False
    with pytest.raises(UserDenied) as caught: login(authority)
    assert caught.value.status==503 and provider.calls==0
    provider.available=True
    for _ in range(10):
        with pytest.raises(UserDenied):login(authority)
    with pytest.raises(UserDenied) as caught:login(authority)
    # The unavailable password attempt also consumes one admission-rate slot.
    assert caught.value.status==429 and provider.calls==9


@pytest.mark.parametrize('subject,username',[(True,'synthetic-user'),(' ','synthetic-user'),('synthetic-id',' '),('synthetic-id','injected\nname')])
def test_invalid_stable_subject_or_username_is_rejected(subject,username):
    from modules.ai_imaging.eagle_eye_remote.user_access import stable_identity
    with pytest.raises(UserDenied): stable_identity('pacs',{'subject':subject,'username':username})


def test_authority_outage_denies_request_without_reclassifying_identity(access,monkeypatch):
    import requests
    authority,provider=access
    approve(authority);session=login(authority)['user_session']
    verify=provider.verify
    def unavailable(token):raise requests.ConnectionError('synthetic-private-network-detail')
    monkeypatch.setattr(provider,'verify',unavailable)
    with pytest.raises(UserDenied) as caught:authority.verify('synthetic-device',session)
    assert caught.value.status==503
    assert 'private' not in str(caught.value)
    monkeypatch.setattr(provider,'verify',verify)
    assert authority.verify('synthetic-device',session)['enabled']


def test_password_identity_resolution_is_server_owned_pacs_then_reception(tmp_path):
    calls=[]
    class Ordered(Provider):
        def __init__(self, name, reject=False):
            super().__init__(); self.name=name; self.reject=reject
        def login(self, username, password):
            calls.append(self.name)
            if self.reject: raise ValueError('Rejected')
            return super().login(username,password)
    authority=UserAuthority(AccessStore(tmp_path/'ordered.sqlite3','synthetic-center'),
        {'reception':Ordered('reception'),'pacs':Ordered('pacs',True)})
    principal=authority.store.identify(dict(provider='reception',subject='synthetic-id',username='synthetic-user'))
    authority.store.grant(principal,dict(enabled=True,echomind=True,imaging=False,crm=False,secretary=False,modules=[]),'admin')
    result=authority.login('device',dict(username='synthetic-user',password='synthetic-password'))
    assert calls==['pacs','reception']
    assert result['user']['provider']=='reception'


def test_local_denial_never_tries_second_identity_provider(tmp_path):
    authority=UserAuthority(AccessStore(tmp_path/'denied.sqlite3','synthetic-center'),
        {'pacs':Provider(),'reception':Provider()})
    with pytest.raises(UserDenied) as error:
        authority.login('device',dict(username='synthetic-user',password='synthetic-password'))
    assert error.value.status==403
    assert authority.providers['reception'].calls==0


def test_pacs_outage_does_not_become_credential_rejection(tmp_path):
    import requests
    class Offline(Provider):
        def login(self,*args): raise requests.ConnectionError('synthetic outage')
    authority=UserAuthority(AccessStore(tmp_path/'outage.sqlite3','synthetic-center'),
        {'pacs':Offline(),'reception':Provider()})
    with pytest.raises(UserDenied) as error:
        authority.login('device',dict(username='synthetic-user',password='synthetic-password'))
    assert error.value.status==503
    assert authority.providers['reception'].calls==0


def test_reception_only_password_resolution_does_not_require_pacs(tmp_path):
    authority=UserAuthority(AccessStore(tmp_path/'reception-only.sqlite3','synthetic-center'),{'reception':Provider()})
    principal=authority.store.identify(dict(provider='reception',subject='synthetic-id',username='synthetic-user'))
    authority.store.grant(principal,dict(enabled=True,echomind=True,imaging=False,crm=False,secretary=False,modules=[]),'admin')
    assert authority.login('device',dict(username='synthetic-user',password='synthetic-password'))['user']['provider']=='reception'


def test_client_password_provider_hint_cannot_skip_pacs(access):
    authority,provider=access
    approve(authority)
    result=authority.login('device',dict(provider='reception',username='synthetic-user',password='synthetic-password'))
    assert result['user']['provider']=='pacs'


def test_temporary_structured_upstream_failure_keeps_session(access):
    authority,provider=access
    approve(authority)
    session=login(authority)['user_session']
    def unavailable(token): raise UserDenied(503,'UPSTREAM_IDENTITY_UNAVAILABLE')
    provider.verify=unavailable
    with pytest.raises(UserDenied) as error: authority.verify('synthetic-device',session)
    assert error.value.status==503
    assert authority.sessions
