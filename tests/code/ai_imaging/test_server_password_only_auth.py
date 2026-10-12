"""Password-only ordinary Eagle admission; no live accounts or provider traffic."""
import pytest
from tests.code.ai_imaging.test_user_access import access,approve
from tests.code.ai_imaging.test_user_access_http import service
from modules.ai_imaging.eagle_eye_remote.user_access import UserDenied

@pytest.mark.parametrize('provider',['pacs','reception'])
def test_caller_provider_token_rejected_before_authority_io(access,provider):
    authority,adapter=access;approve(authority)
    with pytest.raises(UserDenied) as ended:
        authority.login('ordinary',{'provider':provider,'upstream_token':'synthetic-upstream-token'})
    assert ended.value.status==401
    assert adapter.calls==0 and not authority.sessions


def test_password_admission_still_issues_internal_opaque_session(access):
    authority,adapter=access;approve(authority)
    value=authority.login('ordinary',{'username':'synthetic-user','password':'synthetic-password'})
    assert value['user_session'] and value['user_session']!='synthetic-upstream-token'
    assert authority.verify('ordinary',value['user_session'])['provider']=='pacs'



def test_http_provider_token_rejection_and_password_grants(service):
    call,authority,adapter,principal,grant,calls=service
    before=adapter.calls
    status,result=call('/v1/auth/session',{'provider':'pacs','upstream_token':'synthetic-upstream'},device='')
    assert status==401 and adapter.calls==before and not authority.sessions
    status,value=call('/v1/auth/session',{'username':'synthetic-user','password':'synthetic-password'},device='')
    assert status==200
    assert call('/v1/jobs',{'module':'brain'},session=value['user_session'],device='')[0]==403
