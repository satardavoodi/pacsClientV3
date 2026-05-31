"""Unit tests for the registry + IdentityService using a fake provider + fake DB."""

import pytest

from modules.Identity import registry
from modules.Identity.identity_service import IdentityService
from modules.Identity.models import Capability, ExternalIdentity
from modules.Identity.providers.base import IdentityProvider


class FakeProvider(IdentityProvider):
    id = "fake"
    display_name = "Fake"
    capabilities = {Capability.PROFILE}

    def __init__(self):
        self.disconnected = []

    def is_available(self):
        return True, "ok"

    def connect(self, aipacs_user):
        return ExternalIdentity(
            provider="fake",
            subject_id="fx",
            handle="f@x",
            display_name="Fake User",
            capabilities=["profile"],
            aipacs_user=aipacs_user,
        )

    def disconnect(self, identity):
        self.disconnected.append(identity.subject_id)


@pytest.fixture
def fake_registry(monkeypatch):
    registry.reset_for_tests()
    fp = FakeProvider()
    registry.register_provider(fp)
    # Prevent auto-registration of the real Google provider during tests.
    monkeypatch.setattr(registry, "_initialized", True)
    return fp


@pytest.fixture
def fake_db(monkeypatch):
    store = {}
    from database import identity_db

    monkeypatch.setattr(
        identity_db, "upsert_identity",
        lambda ident: store.__setitem__((ident.aipacs_user, ident.provider, ident.subject_id), ident) or 1,
    )
    monkeypatch.setattr(identity_db, "get_identity", lambda u, p, s: store.get((u, p, s)))
    monkeypatch.setattr(identity_db, "list_identities", lambda u: [v for k, v in store.items() if k[0] == u])
    monkeypatch.setattr(
        identity_db, "delete_identity",
        lambda u, p, s: store.pop((u, p, s), None) is not None,
    )
    return store


def test_resolve_aipacs_user():
    assert IdentityService.resolve_aipacs_user(None) == "local"
    assert IdentityService.resolve_aipacs_user({"username": "u"}) == "u"
    assert IdentityService.resolve_aipacs_user({"full_name": "F"}) == "F"


def test_connect_list_disconnect(fake_registry, fake_db):
    svc = IdentityService("drv")
    ident = svc.connect("fake")
    assert ident.subject_id == "fx"
    assert ident.aipacs_user == "drv"
    assert len(svc.list_identities()) == 1

    infos = svc.list_provider_infos()
    assert any(i.id == "fake" and i.connected and i.connected_handle == "f@x" for i in infos)

    svc.disconnect("fake", "fx")
    assert len(svc.list_identities()) == 0
    assert "fx" in fake_registry.disconnected


def test_connect_unknown_provider(fake_registry, fake_db):
    svc = IdentityService("drv")
    with pytest.raises(ValueError):
        svc.connect("does-not-exist")
