"""Cloud-consultation feature flag: default OFF; env + config overrides."""

from modules.cloud_consultation import feature_flags


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("AIPACS_CLOUD_CONSULTATION", raising=False)
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: __import__("pathlib").Path("/nonexistent/x.json"))
    assert feature_flags.cloud_consultation_enabled() is False


def test_flag_env_on(monkeypatch):
    monkeypatch.setenv("AIPACS_CLOUD_CONSULTATION", "1")
    assert feature_flags.cloud_consultation_enabled() is True


def test_flag_env_off(monkeypatch):
    monkeypatch.setenv("AIPACS_CLOUD_CONSULTATION", "off")
    assert feature_flags.cloud_consultation_enabled() is False


def test_flag_config_file(monkeypatch, tmp_path):
    monkeypatch.delenv("AIPACS_CLOUD_CONSULTATION", raising=False)
    flag = tmp_path / "cloud_consultation.json"
    flag.write_text('{"enabled": true}', encoding="utf-8")
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: flag)
    assert feature_flags.cloud_consultation_enabled() is True
