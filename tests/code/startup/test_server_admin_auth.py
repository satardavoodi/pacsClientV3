"""Synthetic identities only; never read production administrator storage."""
import pytest
from modules.ai_imaging.eagle_eye_remote import admin_auth as auth


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, 'protect', lambda raw, **kw: raw)
    monkeypatch.setattr(auth, 'unprotect', lambda raw: raw)
    auth._FAILURES.clear()
    auth._SESSIONS.clear()
    path = tmp_path / 'admin.bin'
    auth.provision(path, 'SyntheticOwner', 'Synthetic-only-passphrase')
    return path


def test_valid_identity_has_console_session_without_pacs_token(account):
    result = auth.authenticate('SyntheticOwner', 'Synthetic-only-passphrase', path=account)
    assert result['user']['role'] == 'superadmin'
    assert result['user']['auth_source'] == 'eagle-eye-console'
    assert auth.valid_session(result['session'])
    assert 'token' not in result
    assert b'Synthetic-only-passphrase' not in account.read_bytes()


@pytest.mark.parametrize('username', ['syntheticowner', 'SYNTHETICOWNER', 'SyNtHeTiCoWnEr'])
def test_console_username_is_case_insensitive_and_preserves_account(account, username):
    result = auth.authenticate(username, 'Synthetic-only-passphrase', path=account)
    assert result is not None
    assert result['user']['username'] == 'SyntheticOwner'
    assert auth.valid_session(result['session'])


def test_username_case_does_not_relax_password_or_accept_another_account(account):
    assert auth.authenticate('syntheticowner', 'synthetic-only-passphrase', path=account) is None
    auth._FAILURES.clear()
    assert auth.authenticate('OtherOwner', 'Synthetic-only-passphrase', path=account) is None


def test_wrong_password_missing_and_corrupt_store_fail_closed(account):
    assert auth.authenticate('SyntheticOwner', 'wrong', path=account) is None
    assert auth.authenticate('SyntheticOwner', 'anything', path=account.with_name('missing')) is None
    account.write_bytes(b'invalid')
    auth._FAILURES.clear()
    assert auth.authenticate('SyntheticOwner', 'anything', path=account) is None
    assert not auth.valid_session('invented')


def test_provisioning_cannot_replace_account(account):
    with pytest.raises(FileExistsError):
        auth.provision(account, 'OtherOwner', 'Other-synthetic-passphrase')


def test_client_role_cannot_resolve_admin_store(monkeypatch):
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE', 'standard')
    with pytest.raises(ValueError):
        auth.store_path()


@pytest.mark.parametrize('edition,environment', [('server', 'standard'), ('standard', 'server')])
def test_installed_edition_cannot_be_overridden_by_environment(monkeypatch, edition, environment):
    import aipacs_runtime
    from modules.ai_imaging.eagle_eye_remote import administration
    monkeypatch.setattr(aipacs_runtime, 'is_frozen', lambda: True)
    monkeypatch.setattr(administration, '_installed_settings_role', lambda: edition)
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE', environment)
    assert administration.settings_role() == edition


def test_failed_attempt_backoff_and_expired_session(account, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(auth.time, 'monotonic', lambda: clock[0])
    for _ in range(5):
        assert auth.authenticate('SyntheticOwner', 'wrong', path=account) is None
        clock[0] += 1.1
    assert auth.authenticate('SyntheticOwner', 'Synthetic-only-passphrase', path=account) is None
    clock[0] += 61
    result = auth.authenticate('SyntheticOwner', 'Synthetic-only-passphrase', path=account)
    assert auth.valid_session(result['session'])
    clock[0] += 8 * 3600 + 1
    assert not auth.valid_session(result['session'])


def test_console_session_can_be_revoked_before_reauthentication(account):
    result = auth.authenticate('SyntheticOwner','Synthetic-only-passphrase',path=account)
    assert auth.valid_session(result['session'])
    auth.invalidate_session(result['session'])
    assert not auth.valid_session(result['session'])
