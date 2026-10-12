"""Synthetic licensing contracts; never read a live license or company key."""
from datetime import datetime, timedelta, timezone
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from modules.LicenseGenerator.renewal import RenewalLicenseManager
from modules.LicenseGenerator.signed_license import LicenseError, decode_token, key_id
from tools.licensing.issuer import Issuer


NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
HARDWARE = 'A' * 32


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from modules.LicenseGenerator import license_manager as legacy
    monkeypatch.setattr(legacy, '_compute_app_data_dir', lambda: tmp_path / 'legacy')
    monkeypatch.setattr(legacy.LicenseManager, 'get_hardware_id', lambda self, **kw: HARDWARE)
    monkeypatch.setattr(legacy.LicenseManager, '_current_candidate_ids',
                        lambda self: [(HARDWARE, 'synthetic')])
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    trusted = {key_id(public): public.hex()}
    manager = RenewalLicenseManager(directory=tmp_path / 'client', product='client',
                                   trusted_keys=trusted, clock=lambda: NOW)
    issuer = Issuer(private, tmp_path / 'issuer.sqlite', trusted_keys=trusted)
    return manager, issuer, trusted


def activate(manager, issuer, days=30, order='initial'):
    request = manager.generate_request()
    token = issuer.issue(request, days=days, order_id=order, now=NOW)
    assert manager.save_license(token)[0]
    return token


def test_remaining_days_are_preserved_and_replay_is_idempotent(setup):
    manager, issuer, _ = setup
    activate(manager, issuer)
    request = manager.generate_request()
    token = issuer.issue(request, days=360, order_id='renew-1', now=NOW)
    assert manager.preview(token)['days_remaining'] == 390
    assert manager.save_license(token)[0]
    assert manager.save_license(token)[0]
    assert manager.status()['days_remaining'] == 390
    assert issuer.issue(request, days=360, order_id='renew-1', now=NOW) == token


def test_expired_license_renews_from_issue_time(setup):
    manager, issuer, _ = setup
    activate(manager, issuer, 30)
    manager.clock = lambda: NOW + timedelta(days=35)
    request = manager.generate_request()
    later = NOW + timedelta(days=35)
    token = issuer.issue(request, days=360, order_id='expired', now=later)
    assert manager.preview(token)['days_remaining'] == 360


def test_delayed_application_does_not_reset_expiry(setup):
    manager, issuer, _ = setup
    activate(manager, issuer)
    token = issuer.issue(manager.generate_request(), days=360, order_id='delayed', now=NOW)
    manager.clock = lambda: NOW + timedelta(days=5)
    assert manager.save_license(token)[0]
    assert manager.status()['days_remaining'] == 385


def test_old_request_and_duplicate_order_cannot_issue_extra_credit(setup):
    manager, issuer, _ = setup
    old_request = manager.generate_request()
    token = issuer.issue(old_request, days=30, order_id='order-1', now=NOW)
    assert manager.save_license(token)[0]
    with pytest.raises(LicenseError):
        issuer.issue(old_request, days=30, order_id='order-2', now=NOW)
    with pytest.raises(LicenseError):
        issuer.issue(manager.generate_request(), days=30, order_id='order-1', now=NOW)


def test_tampered_token_foreign_product_and_machine_are_rejected(setup):
    manager, issuer, trusted = setup
    token = activate(manager, issuer)
    parts = token.split('.')
    parts[-1] = ('A' if parts[-1][0] != 'A' else 'B') + parts[-1][1:]
    assert not manager.save_license('.'.join(parts))[0]
    server = RenewalLicenseManager(directory=manager.directory / 'server', product='eagle-eye-server',
                                  trusted_keys=trusted, clock=lambda: NOW)
    assert not server.save_license(token)[0]
    with pytest.raises(LicenseError):
        decode_token(token, trusted, hardware_id='B' * 32, product='client')


def test_migration_retains_days_but_requires_company_verified_expiry(setup):
    manager, issuer, _ = setup
    from modules.LicenseGenerator.license_manager import SECRET_KEY
    expiry = (NOW + timedelta(days=30)).strftime('%Y%m%d')
    digest = hashlib.sha256(f'{HARDWARE}|{expiry}|{SECRET_KEY}'.encode()).hexdigest()[:24].upper()
    legacy = f'{expiry}-{digest}'
    # Synthetic old format; timestamp is fixed independently from the OS clock.
    manager.legacy.license_path = manager.license_path
    manager.directory.mkdir(parents=True)
    import json
    manager.license_path.write_text(json.dumps({'license_key': legacy}), encoding='utf-8')
    request = manager.generate_request()
    with pytest.raises(LicenseError, match='legacy'):
        issuer.issue(request, days=360, order_id='migration', now=NOW)
    from modules.LicenseGenerator.renewal import legacy_claim
    token = issuer.issue(request, days=360, order_id='migration', now=NOW,
                         approved_legacy_expiry=legacy_claim(legacy, HARDWARE)['expires_at'])
    assert manager.save_license(token)[0]
    assert manager.status()['days_remaining'] == 390
    assert not manager.save_license(legacy)[0]


def test_clock_rollback_and_corrupt_state_fail_closed(setup):
    manager, issuer, _ = setup
    activate(manager, issuer)
    manager.clock = lambda: NOW - timedelta(days=2)
    assert not manager.check_license()[0]
    manager.license_path.write_bytes(b'corrupt-state')
    assert not manager.check_license()[0]


def test_storage_failure_preserves_active_license(setup, monkeypatch):
    manager, issuer, _ = setup
    activate(manager, issuer)
    token = issuer.issue(manager.generate_request(), days=360, order_id='io-fail', now=NOW)
    monkeypatch.setattr(manager, '_write', lambda state: (_ for _ in ()).throw(OSError('synthetic')))
    assert not manager.save_license(token)[0]
    assert manager.status()['days_remaining'] == 30


@pytest.mark.parametrize('days', [0, -1, True, 36501, 1.5])
def test_invalid_credit_is_rejected(setup, days):
    manager, issuer, _ = setup
    with pytest.raises(LicenseError):
        issuer.issue(manager.generate_request(), days=days, order_id='bad', now=NOW)


def test_unknown_signer_and_missing_request_do_not_activate(setup):
    manager, issuer, trusted = setup
    token = issuer.issue(manager.generate_request(), days=30, order_id='first', now=NOW)
    other = RenewalLicenseManager(directory=manager.directory / 'other', product='client',
                                 trusted_keys=trusted, clock=lambda: NOW)
    assert not other.save_license(token)[0]
    with pytest.raises(LicenseError):
        decode_token(token, {}, hardware_id=HARDWARE, product='client')


def test_signed_state_cannot_be_replaced_by_unprotected_json(setup):
    manager, issuer, _ = setup
    token = activate(manager, issuer)
    import json
    manager.license_path.write_text(json.dumps({'version': 3, 'license_key': token,
        'signed_revision': 1, 'last_seen': '2026-10-07T12:00:00Z'}), encoding='utf-8')
    assert not manager.check_license()[0]


def test_status_and_save_fail_closed_when_store_is_unwritable(setup, monkeypatch):
    manager, issuer, _ = setup
    token = activate(manager, issuer)
    from contextlib import contextmanager
    @contextmanager
    def unavailable():
        raise OSError('Synthetic storage denial')
        yield
    monkeypatch.setattr(manager, '_exclusive', unavailable)
    assert not manager.check_license()[0]
    assert not manager.save_license(token)[0]


def test_two_requests_from_same_base_cannot_receive_two_credits(setup):
    manager, issuer, _ = setup
    activate(manager, issuer)
    first = manager.generate_request()
    from modules.LicenseGenerator.signed_license import decode_request, encode_request
    second = decode_request(first)
    second['request_id'] = 'b' * 32
    issuer.issue(first, days=360, order_id='first-renewal', now=NOW)
    with pytest.raises(LicenseError, match='newer issued'):
        issuer.issue(encode_request(second), days=360, order_id='second-renewal', now=NOW)


def test_company_product_confirmation_must_match_customer_request(setup):
    manager, issuer, _ = setup
    request = manager.generate_request()
    assert issuer.inspect_request(request, expected_product='client')['initial']
    with pytest.raises(LicenseError, match='purchased company product'):
        issuer.inspect_request(request, expected_product='eagle-eye-server')
