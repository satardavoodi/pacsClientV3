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
    discovery.build = lambda *a, **k: built.setdefault("args", (a, k)) or "DRIVE_SERVICE"
    monkeypatch.setitem(sys.modules, "googleapiclient", types.ModuleType("googleapiclient"))
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)

    svc = prov.get_capability_client(
        ExternalIdentity(provider="google", subject_id="x"), Capability.CLOUD_STORAGE
    )
    assert svc == "DRIVE_SERVICE"
    assert built["args"][0][0] == "drive" and built["args"][0][1] == "v3"
