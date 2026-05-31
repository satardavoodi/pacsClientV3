"""Unit tests for GoogleIdentityProvider with the OAuth flow + storage mocked."""

from modules.Identity import config as cfg
from modules.Identity import secure_store
from modules.Identity.providers.google import oauth_flow
from modules.Identity.providers.google.provider import GoogleIdentityProvider


def test_is_available_reports_reason_when_unconfigured(monkeypatch):
    monkeypatch.setattr(cfg, "google_client_configured", lambda: False)
    ok, reason = GoogleIdentityProvider().is_available()
    assert ok is False
    assert reason  # human-readable reason (libs missing OR config missing)


def test_connect_builds_identity_and_stores_token(monkeypatch):
    prov = GoogleIdentityProvider()
    # Bypass dependency/config gating for the unit test.
    monkeypatch.setattr(GoogleIdentityProvider, "is_available", lambda self: (True, "ok"))
    monkeypatch.setattr(cfg, "load_google_client_config", lambda: {"installed": {"client_id": "x"}})
    monkeypatch.setattr(oauth_flow, "run_installed_app_flow", lambda client_config, scopes=None: object())
    monkeypatch.setattr(
        oauth_flow, "fetch_userinfo",
        lambda creds: {
            "sub": "123", "email": "a@b.com", "name": "A B",
            "picture": "http://p", "email_verified": True,
        },
    )
    monkeypatch.setattr(oauth_flow, "credentials_to_payload", lambda creds: {"refresh_token": "rt"})

    saved = {}
    monkeypatch.setattr(
        secure_store, "save_secret",
        lambda provider, subject, payload: saved.__setitem__((provider, subject), payload) or True,
    )

    ident = prov.connect("drv")
    assert ident.subject_id == "123"
    assert ident.handle == "a@b.com"
    assert ident.display_name == "A B"
    assert "profile" in ident.capabilities and "cloud_storage" in ident.capabilities
    assert ident.aipacs_user == "drv"
    assert ident.extra.get("email_verified") is True
    assert ("google", "123") in saved


def test_connect_raises_when_unavailable(monkeypatch):
    prov = GoogleIdentityProvider()
    monkeypatch.setattr(GoogleIdentityProvider, "is_available", lambda self: (False, "no config"))
    try:
        prov.connect("drv")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "no config" in str(exc)
