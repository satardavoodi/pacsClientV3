"""Unit tests for secure_store (keyring path + encrypted-file fallback)."""

import pytest

from modules.Identity import secure_store


class _FakeKeyring:
    def __init__(self):
        self.store = {}

    def set_password(self, service, account, blob):
        self.store[(service, account)] = blob

    def get_password(self, service, account):
        return self.store.get((service, account))

    def delete_password(self, service, account):
        self.store.pop((service, account), None)


def test_keyring_roundtrip(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(secure_store, "_keyring", lambda: fake)
    assert secure_store.save_secret("google", "sub1", {"refresh_token": "rt"}) is True
    assert secure_store.load_secret("google", "sub1") == {"refresh_token": "rt"}
    secure_store.delete_secret("google", "sub1")
    assert secure_store.load_secret("google", "sub1") is None


def test_fallback_roundtrip(monkeypatch, tmp_path):
    pytest.importorskip("cryptography")
    monkeypatch.setattr(secure_store, "_keyring", lambda: None)  # force fallback
    import modules.Identity.config as cfg

    monkeypatch.setattr(cfg, "identity_config_dir", lambda: tmp_path)
    assert secure_store.save_secret("google", "sub2", {"token": "x"}) is True
    assert secure_store.load_secret("google", "sub2") == {"token": "x"}
    secure_store.delete_secret("google", "sub2")
    assert secure_store.load_secret("google", "sub2") is None


def test_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(secure_store, "_keyring", lambda: None)
    import modules.Identity.config as cfg

    monkeypatch.setattr(cfg, "identity_config_dir", lambda: tmp_path)
    assert secure_store.load_secret("google", "nope") is None
