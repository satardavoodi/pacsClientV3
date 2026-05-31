"""Unit tests for the Identity feature flag (default OFF; env + config overrides)."""

from modules.Identity import feature_flags


def test_flag_default_off(monkeypatch, tmp_path):
    monkeypatch.delenv("AIPACS_IDENTITY_MODULE", raising=False)
    import modules.Identity.config as cfg

    # Point the flag-file path at a non-existent temp file so no stray config affects us.
    monkeypatch.setattr(cfg, "identity_flag_file_path", lambda: tmp_path / "identity.json")
    assert feature_flags.identity_module_enabled() is False


def test_flag_env_on(monkeypatch):
    monkeypatch.setenv("AIPACS_IDENTITY_MODULE", "1")
    assert feature_flags.identity_module_enabled() is True
    monkeypatch.setenv("AIPACS_IDENTITY_MODULE", "true")
    assert feature_flags.identity_module_enabled() is True


def test_flag_env_off(monkeypatch):
    monkeypatch.setenv("AIPACS_IDENTITY_MODULE", "off")
    assert feature_flags.identity_module_enabled() is False
    monkeypatch.setenv("AIPACS_IDENTITY_MODULE", "0")
    assert feature_flags.identity_module_enabled() is False


def test_flag_config_file(monkeypatch, tmp_path):
    monkeypatch.delenv("AIPACS_IDENTITY_MODULE", raising=False)
    import modules.Identity.config as cfg

    flag = tmp_path / "identity.json"
    flag.write_text('{"enabled": true}', encoding="utf-8")
    monkeypatch.setattr(cfg, "identity_flag_file_path", lambda: flag)
    assert feature_flags.identity_module_enabled() is True


def test_flag_disabled_creates_no_directories(monkeypatch):
    """A disabled flag check must never call the dir-creating identity_config_dir()."""
    monkeypatch.delenv("AIPACS_IDENTITY_MODULE", raising=False)
    import modules.Identity.config as cfg

    def _boom(*_a, **_k):
        raise AssertionError("identity_config_dir() must not be called when disabled")

    monkeypatch.setattr(cfg, "identity_config_dir", _boom)
    # Uses the non-creating path resolver internally; returns False with no mkdir.
    assert feature_flags.identity_module_enabled() is False
