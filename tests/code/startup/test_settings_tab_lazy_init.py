"""Source-contract tests for lazy Settings tab initialization.

This locks the startup optimization contract:
1. No deferred bulk setup method that initializes all heavy tabs at once.
2. Tab bootstrap is visibility-driven (showEvent), not startup-timer driven.
3. Core tabs are registered in _tab_creators for on-demand construction.
"""

from pathlib import Path


_SETTINGS_PATH = Path("PacsClient/pacs/workstation_ui/settings_ui/settings_ui.py")
_AIPACS_UI_PATH = Path("PacsClient/pacs/workstation_ui/AIPacs_ui.py")


def _src() -> str:
    return _SETTINGS_PATH.read_text(encoding="utf-8")


def _aipacs_src() -> str:
    return _AIPACS_UI_PATH.read_text(encoding="utf-8")


def test_settings_bootstrap_is_visibility_driven_not_startup_timer() -> None:
    src = _src()
    assert "def showEvent(self, event):" in src
    assert "self._ensure_tab_initialized(self.currentIndex())" in src
    assert "QTimer.singleShot(0, self._init_initial_tab)" not in src
    assert "def _deferred_setup_tabs" not in src


def test_core_tabs_are_registered_for_lazy_creation() -> None:
    src = _src()
    for name in [
        "Server Settings",
        "Tools Settings",
        "Viewer Configuration",
        "Image Filter",
        "Installation & Updates",
    ]:
        assert name in src, f"Missing lazy tab registration for {name}"


def test_current_changed_routes_to_ensure_initialized() -> None:
    src = _src()
    assert "self.currentChanged.connect(self._on_tab_changed)" in src
    assert "def _ensure_tab_initialized(self, idx):" in src
    assert "self._ensure_tab_initialized(idx)" in src


def test_viewer_config_ready_signal_exists_for_safe_external_wiring() -> None:
    src = _src()
    assert "viewerConfigReady = Signal(object)" in src
    assert "self.viewerConfigReady.emit(self.viewer_config)" in src


def test_aipacs_uses_viewer_config_ready_signal_instead_of_direct_access() -> None:
    src = _aipacs_src()
    assert "self.settings_widget.viewerConfigReady.connect(" in src
    assert "self._wire_modality_grid_config_signal" in src
    assert "self.settings_widget.viewer_config.configChanged.connect(" not in src
