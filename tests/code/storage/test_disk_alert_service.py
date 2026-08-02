"""Disk space alert suppression preference (2026-07-29)."""
import importlib
import json

import pytest

das = importlib.import_module("modules.storage.disk_alert_service")


@pytest.fixture()
def prefs(tmp_path, monkeypatch):
    p = tmp_path / "config" / "disk_alert_prefs.json"
    monkeypatch.setattr(das, "_prefs_path", lambda: p, raising=True)
    # The flag is cached process-wide (check_now runs from a repeating GUI-thread
    # timer and must not stat+read+parse the file on every tick). Each test gets
    # its own tmp prefs file, so the cache has to be dropped between tests —
    # otherwise the suite passes only in one particular order.
    das.invalidate_disk_alert_prefs_cache()
    yield p
    das.invalidate_disk_alert_prefs_cache()


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


def test_the_prefs_flag_is_not_re_read_on_every_check(prefs, monkeypatch):
    """check_now() runs from a repeating GUI-thread QTimer; the persisted flag
    must be cached, not stat+read+json-parsed on every tick."""
    reads = []
    real = das._read_suppressed_from_disk
    monkeypatch.setattr(
        das, "_read_suppressed_from_disk", lambda: (reads.append(1), real())[1]
    )
    for _ in range(5):
        das.is_disk_space_alert_suppressed()
    assert len(reads) == 1, f"prefs file read {len(reads)} times, expected 1"


def test_writing_the_flag_refreshes_the_cache(prefs):
    assert das.is_disk_space_alert_suppressed() is False
    das.set_disk_space_alert_suppressed(True)
    assert das.is_disk_space_alert_suppressed() is True


def test_dont_show_again_label_is_wired():
    src = (das.__file__)
    from pathlib import Path

    body = Path(src).read_text(encoding="utf-8")
    assert "Don't show again" in body
    assert "set_disk_space_alert_suppressed" in body
