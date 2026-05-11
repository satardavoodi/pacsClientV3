"""Source-contract tests for deferred Server Settings data loading.

This guards the startup optimization where ServerSettingsWidget construction
stays lightweight and initial data scans run only when the widget is shown.
"""

from pathlib import Path


_SERVER_SETTINGS_PATH = Path("PacsClient/pacs/workstation_ui/settings_ui/server_settings.py")


def _src() -> str:
    return _SERVER_SETTINGS_PATH.read_text(encoding="utf-8")


def test_server_settings_defers_initial_data_load_to_show_event() -> None:
    src = _src()
    assert "self._initial_data_loaded = False" in src
    assert "def showEvent(self, event):" in src
    assert "QTimer.singleShot(0, self._load_initial_data)" in src


def test_server_settings_constructor_no_longer_runs_heavy_data_load_calls() -> None:
    src = _src()
    assert "def _load_initial_data(self):" in src
    assert "self.load_servers()" in src
    assert "self._load_ai_service_urls()" in src
    assert "self._ext_load_and_display()" in src
    assert "self._cloud_load_and_display()" in src
