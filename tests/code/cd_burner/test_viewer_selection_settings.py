"""Viewer-mode settings: persistence, back-compat, and selection resolution."""

import json

import pytest

import PacsClient.pacs.workstation_ui.settings_ui.lightviewer_settings as lvs
from PacsClient.pacs.workstation_ui.settings_ui.lightviewer_settings import (
    VIEWER_MODE_CUSTOM,
    VIEWER_MODE_DEFAULT,
    LightViewerSettingsWidget,
)
from modules.cd_burner import viewer_locator


@pytest.fixture()
def config_root(tmp_path, monkeypatch):
    monkeypatch.setattr(lvs, "roaming_config_root", lambda: tmp_path)
    monkeypatch.delenv(viewer_locator.ENV_OVERRIDE, raising=False)
    return tmp_path


def _write_config(root, **payload):
    (root / "lightviewer_settings.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_normalize_mode_back_compat():
    norm = LightViewerSettingsWidget._normalize_mode
    assert norm(None, "") == VIEWER_MODE_DEFAULT
    assert norm(None, r"C:\x\viewer.exe") == VIEWER_MODE_CUSTOM
    assert norm("default", r"C:\x\viewer.exe") == VIEWER_MODE_DEFAULT
    assert norm("custom", "") == VIEWER_MODE_CUSTOM
    assert norm("garbage", "") == VIEWER_MODE_DEFAULT


def test_mode_default_when_no_config(config_root):
    assert LightViewerSettingsWidget.get_viewer_mode() == VIEWER_MODE_DEFAULT


def test_legacy_config_with_path_means_custom(config_root, tmp_path):
    exe = tmp_path / "OldViewer.exe"
    exe.write_bytes(b"MZ")
    _write_config(config_root, light_viewer_path=str(exe), disc_label="X")

    assert LightViewerSettingsWidget.get_viewer_mode() == VIEWER_MODE_CUSTOM
    selection = LightViewerSettingsWidget.get_viewer_selection()
    assert selection["mode"] == VIEWER_MODE_CUSTOM
    assert selection["kind"] == "custom"
    assert selection["path"] == str(exe)


def test_custom_mode_with_missing_path_resolves_none(config_root):
    _write_config(
        config_root,
        viewer_mode="custom",
        light_viewer_path=r"C:\does\not\exist.exe",
    )
    selection = LightViewerSettingsWidget.get_viewer_selection()
    assert selection["mode"] == VIEWER_MODE_CUSTOM
    assert selection["path"] is None
    assert selection["kind"] == "none"


def test_default_mode_resolves_bundled_viewer(config_root, tmp_path, monkeypatch):
    exe = tmp_path / "AIPacsLiteViewer.exe"
    exe.write_bytes(b"MZ lite")
    monkeypatch.setenv(viewer_locator.ENV_OVERRIDE, str(exe))
    _write_config(config_root, viewer_mode="default", light_viewer_path="")

    selection = LightViewerSettingsWidget.get_viewer_selection()
    assert selection["mode"] == VIEWER_MODE_DEFAULT
    assert selection["path"] == str(exe)
    assert selection["kind"] == "override"
    assert selection["display_name"] == "AI-PACS Lite Viewer"


def test_default_mode_without_build_resolves_none(config_root, monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_locator, "_module_root", lambda: tmp_path)
    _write_config(config_root, viewer_mode="default", light_viewer_path="")

    selection = LightViewerSettingsWidget.get_viewer_selection()
    assert selection["mode"] == VIEWER_MODE_DEFAULT
    assert selection["path"] is None
    assert selection["kind"] == "none"
