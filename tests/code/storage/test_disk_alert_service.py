"""Disk space alert suppression preference (2026-07-29)."""
import importlib
import json

import pytest

das = importlib.import_module("modules.storage.disk_alert_service")


@pytest.fixture()
def prefs(tmp_path, monkeypatch):
    p = tmp_path / "config" / "disk_alert_prefs.json"
    monkeypatch.setattr(das, "_prefs_path", lambda: p, raising=True)
    return p


def test_not_suppressed_by_default(prefs):
    assert das.is_disk_space_alert_suppressed() is False
    assert das.disk_space_alert_enabled() is True


def test_set_suppressed_persists(prefs):
    assert das.set_disk_space_alert_suppressed(True) is True
    assert prefs.exists()
    raw = json.loads(prefs.read_text(encoding="utf-8"))
    assert raw["suppress_disk_space_alert"] is True
    assert das.is_disk_space_alert_suppressed() is True
    assert das.disk_space_alert_enabled() is False


def test_env_kill_switch_overrides(prefs, monkeypatch):
    monkeypatch.setenv("AIPACS_DISK_SPACE_ALERT", "0")
    assert das.disk_space_alert_enabled() is False


def test_dont_show_again_label_is_wired():
    src = (das.__file__)
    from pathlib import Path

    body = Path(src).read_text(encoding="utf-8")
    assert "Don't show again" in body
    assert "set_disk_space_alert_suppressed" in body
