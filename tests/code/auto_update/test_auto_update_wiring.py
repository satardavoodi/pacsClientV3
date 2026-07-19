"""Wiring + policy guards for the auto-update system (OPT-38).

- main.py starts the service (flag-gated, guarded, after window.show()).
- Flag defaults: dev = silent, frozen = on, env kill/force switches work.
- summarize_available_updates passes the new feed keys through.
- Layer purity: manifest/client/apply never import Qt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── source pins ────────────────────────────────────────────────────────────

def test_main_py_wires_auto_update_service():
    source = (REPO_ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    assert "AutoUpdateService" in source, "startup update check wiring removed from main.py"
    assert "updateAvailable.connect" in source
    assert "show_update_notification" in source
    # wiring is guarded — a broken updater must never break startup
    start = source.index("AutoUpdateService")
    guard_region = source[max(0, start - 600): start]
    assert "try:" in guard_region


def test_layer_purity_no_qt_below_the_service():
    for name in ("manifest.py", "client.py", "apply.py"):
        source = (REPO_ROOT / "modules" / "auto_update" / name).read_text(
            encoding="utf-8", errors="replace"
        )
        assert "PySide6" not in source, f"{name} must stay Qt-free (worker/tool layer)"
        assert "QtWidgets" not in source


def test_settings_ui_routes_core_update_through_delta():
    source = (
        REPO_ROOT
        / "PacsClient" / "pacs" / "workstation_ui" / "settings_ui"
        / "installation_module_settings.py"
    ).read_text(encoding="utf-8", errors="replace")
    assert "begin_update_flow" in source
    assert "auto_check_on_startup" in source
    assert "launch_core_update_installer" in source, "installer fallback must remain"


def test_build_release_publishes_delta_and_version_marker():
    source = (REPO_ROOT / "builder" / "build_release.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "generate_core_delta" in source
    assert "stamp_stage_version" in source
    assert "AIPACS_UPDATE_DELTA_PUBLISH" in source
    # delta generation must be guarded so it can never fail the release build
    idx = source.index("generate_core_delta")
    assert "except Exception" in source[idx: idx + 800]


# ── service flag policy ────────────────────────────────────────────────────

def test_check_disabled_by_default_in_dev(monkeypatch):
    pytest.importorskip("PySide6")
    from modules.auto_update import service

    monkeypatch.delenv("AIPACS_AUTO_UPDATE_CHECK", raising=False)
    assert service.auto_update_check_enabled() is False  # dev runs stay quiet


def test_check_env_force_and_kill(monkeypatch):
    pytest.importorskip("PySide6")
    from modules.auto_update import service

    monkeypatch.setenv("AIPACS_AUTO_UPDATE_CHECK", "1")
    assert service.auto_update_check_enabled() is True
    monkeypatch.setenv("AIPACS_AUTO_UPDATE_CHECK", "0")
    assert service.auto_update_check_enabled() is False


def test_check_enabled_for_frozen_honors_config(monkeypatch):
    pytest.importorskip("PySide6")
    import aipacs_runtime
    from modules.auto_update import service

    monkeypatch.delenv("AIPACS_AUTO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(aipacs_runtime, "is_frozen", lambda: True)
    monkeypatch.setattr(
        aipacs_runtime, "load_update_sources", lambda: {"auto_check_on_startup": True}
    )
    assert service.auto_update_check_enabled() is True
    monkeypatch.setattr(
        aipacs_runtime, "load_update_sources", lambda: {"auto_check_on_startup": False}
    )
    assert service.auto_update_check_enabled() is False


def test_startup_delay_floor(monkeypatch):
    pytest.importorskip("PySide6")
    from modules.auto_update import service

    monkeypatch.setenv("AIPACS_UPDATE_CHECK_DELAY_S", "0")
    assert service.startup_check_delay_s() >= 1.0
    monkeypatch.setenv("AIPACS_UPDATE_CHECK_DELAY_S", "45")
    assert service.startup_check_delay_s() == 45.0


# ── feed passthrough (additive keys) ───────────────────────────────────────

def test_summarize_passes_delta_keys_through(tmp_path):
    from aipacs_runtime import summarize_available_updates

    feed = {
        "app_name": "AIPacs",
        "channel": "stable",
        "core": {
            "module_id": "core_app",
            "release_version": "99.0.0",
            "artifact_type": "installer",
            "artifact_path": "core/x.exe",
            "sha256": "a" * 64,
            "size": 12345,
            "required": True,
            "min_version": "3.0.0",
            "release_notes": "hello",
            "release_notes_path": "core/notes-99.0.0.md",
            "delta": {
                "manifest_path": "core/manifest-99.0.0.json",
                "manifest_sha256": "b" * 64,
                "files_base": "files/",
                "compression": "gzip",
            },
        },
        "components": [],
    }
    (tmp_path / "update_feed.json").write_text(json.dumps(feed), encoding="utf-8")
    summary = summarize_available_updates(str(tmp_path))
    core = summary["core"]
    assert core["status"] == "update_available"
    assert core["delta"]["manifest_path"] == "core/manifest-99.0.0.json"
    assert core["required"] is True
    assert core["size"] == 12345
    assert core["min_version"] == "3.0.0"
    assert core["release_notes"] == "hello"
    assert core["release_notes_path"] == "core/notes-99.0.0.md"


def test_summarize_tolerates_legacy_feed_without_delta(tmp_path):
    from aipacs_runtime import summarize_available_updates

    feed = {
        "app_name": "AIPacs",
        "core": {
            "module_id": "core_app",
            "release_version": "99.0.0",
            "artifact_type": "installer",
            "artifact_path": "core/x.exe",
            "sha256": "a" * 64,
        },
        "components": [],
    }
    (tmp_path / "update_feed.json").write_text(json.dumps(feed), encoding="utf-8")
    core = summarize_available_updates(str(tmp_path))["core"]
    assert core["delta"] is None
    assert core["required"] is False
    assert core["size"] == 0
