"""Tests for GoogleIdentityProvider credential vending (refresh + capability client).

All Google libraries are mocked, so these run without google-auth/googleapiclient.
"""

import sys
import types

import pytest

from modules.Identity import secure_store
from modules.Identity.models import Capability, ExternalIdentity
from modules.Identity.providers.google import oauth_flow
from modules.Identity.providers.google.provider import GoogleIdentityProvider


def test_get_credentials_refreshes_and_persists(monkeypatch):
    prov = GoogleIdentityProvider()
    monkeypatch.setattr(secure_store, "load_secret", lambda p, s: {"refresh_token": "rt", "token": None})

    class FakeCreds:
        def __init__(self):
            self.valid = False
            self.refresh_token = "rt"
            self.refreshed = False

        def refresh(self, _request):
            self.refreshed = True
            self.valid = True

    fake = FakeCreds()
    monkeypatch.setattr(oauth_flow, "payload_to_credentials", lambda payload: fake)
    monkeypatch.setattr(oauth_flow, "credentials_to_payload", lambda creds: {"refresh_token": "rt", "token": "new"})

    saved = {}
    monkeypatch.setattr(
        secure_store, "save_secret",
        lambda p, s, payload: saved.__setitem__((p, s), payload) or True,
    )
    # Provide a stand-in for google.auth.transport.requests.Request.
    mod = types.ModuleType("google.auth.transport.requests")
    mod.Request = lambda: object()
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", mod)

    creds = prov.get_credentials(ExternalIdentity(provider="google", subject_id="123"))
    assert creds is fake
    assert fake.refreshed is True
    assert ("google", "123") in saved


def test_get_credentials_without_token_raises(monkeypatch):
    prov = GoogleIdentityProvider()
    monkeypatch.setattr(secure_store, "load_secret", lambda p, s: None)
    with pytest.raises(RuntimeError):
        prov.get_credentials(ExternalIdentity(provider="google", subject_id="x"))


def test_get_capability_client_builds_drive(monkeypatch):
    prov = GoogleIdentityProvider()
    monkeypatch.setattr(GoogleIdentityProvider, "get_credentials", lambda self, ident: object())

    built = {}
    discovery = types.ModuleType("googleapiclient.discovery")

    def _fake_build(*a, **k):
        # Test bug fixed 2026-06-04: the old one-liner used
        # `built.setdefault("args", (a, k)) or "DRIVE_SERVICE"` — setdefault
        # returns the (truthy) args tuple, so the sentinel was never returned
        # and the assertion below could never pass.
        built["args"] = (a, k)
        return "DRIVE_SERVICE"

    discovery.build = _fake_build
    monkeypatch.setitem(sys.modules, "googleapiclient", types.ModuleType("googleapiclient"))
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)

    svc = prov.get_capability_client(
        ExternalIdentity(provider="google", subject_id="x"), Capability.CLOUD_STORAGE
    )
    assert svc == "DRIVE_SERVICE"
    assert built["args"][0][0] == "drive" and built["args"][0][1] == "v3"


def test_drive_client_has_bounded_socket_timeout(monkeypatch):
    """Offline hardening (2026-06-07): the Drive HTTP client must carry a
    bounded per-socket timeout so a dead network fails fast in the worker
    instead of hanging; discovery must be static (no network fetch)."""
    pytest.importorskip("google_auth_httplib2")
    prov = GoogleIdentityProvider()
    monkeypatch.setattr(GoogleIdentityProvider, "get_credentials", lambda self, ident: object())

    built = {}
    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = lambda *a, **k: built.update(k) or "DRIVE_SERVICE"
    monkeypatch.setitem(sys.modules, "googleapiclient", types.ModuleType("googleapiclient"))
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)

    prov.get_capability_client(
        ExternalIdentity(provider="google", subject_id="x"), Capability.CLOUD_STORAGE
    )
    authed = built["http"]
    assert authed.http.timeout == GoogleIdentityProvider.DRIVE_HTTP_TIMEOUT_SEC
    assert built["static_discovery"] is True


def test_token_refresh_request_has_bounded_timeout(monkeypatch):
    """The OAuth refresh transport must inject a bounded timeout (google-auth
    default is 120 s — that froze the GUI for the full hang when on-thread)."""
    pytest.importorskip("google.auth.transport.requests")
    captured = {}

    from google.auth.transport.requests import Request

    def fake_call(self, *args, **kwargs):
        captured.update(kwargs)
        return "RESP"

    monkeypatch.setattr(Request, "__call__", fake_call)
    req = GoogleIdentityProvider._bounded_refresh_request()
    assert req("https://oauth2.googleapis.com/token") == "RESP"
    assert captured["timeout"] == GoogleIdentityProvider.TOKEN_REFRESH_TIMEOUT_SEC

    # An explicit caller-provided timeout must win.
    captured.clear()
    req("https://oauth2.googleapis.com/token", timeout=3)
    assert captured["timeout"] == 3
