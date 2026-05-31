"""Unit tests for modules.Identity.models (hermetic; no Qt, no network)."""

import json

from modules.Identity.models import Capability, ExternalIdentity, ProviderInfo


def test_capability_values():
    assert Capability.PROFILE.value == "profile"
    assert Capability.CLOUD_STORAGE.value == "cloud_storage"
    assert Capability.MESSAGING.value == "messaging"


def test_identity_from_row_roundtrip():
    row = {
        "provider": "google",
        "subject_id": "sub123",
        "handle": "a@b.com",
        "display_name": "A B",
        "avatar_url": "http://x/p.png",
        "avatar_cache": "",
        "capabilities": json.dumps(["profile", "cloud_storage"]),
        "is_active_for": json.dumps([]),
        "extra": json.dumps({"email_verified": True}),
        "aipacs_user": "drv",
    }
    ident = ExternalIdentity.from_row(row)
    assert ident.subject_id == "sub123"
    assert ident.handle == "a@b.com"
    assert ident.capabilities == ["profile", "cloud_storage"]
    assert ident.extra == {"email_verified": True}
    assert ident.aipacs_user == "drv"
    assert ident.to_dict()["provider"] == "google"


def test_identity_from_row_handles_missing_and_bad_json():
    ident = ExternalIdentity.from_row({"provider": "google", "subject_id": "s"})
    assert ident.capabilities == []
    assert ident.extra == {}
    bad = ExternalIdentity.from_row(
        {"provider": "g", "subject_id": "s", "capabilities": "not-json", "extra": "{"}
    )
    assert bad.capabilities == []
    assert bad.extra == {}


def test_provider_info_defaults():
    info = ProviderInfo(id="google", display_name="Google", capabilities=["profile"], available=True)
    assert info.connected is False
    assert info.connected_handle == ""
