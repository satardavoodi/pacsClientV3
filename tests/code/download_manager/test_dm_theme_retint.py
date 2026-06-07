"""Guards for the DM theme-retint NameError + deferred app restyle.

Other-PC crash log 2026-06-07:
- 10:53 pid 55728: CRITICAL excepthook — _dm_theming.py:21 _on_app_theme_changed
  raised ``NameError: name '_dm_retint_widget_tree' is not defined``. The
  Phase-2 split copied the PatientWidget pattern but never created the DM
  helper, so EVERY theme change with the Download Manager alive raised.
- 10:49 pid 26524: access violation inside the synchronous theme-click
  dispatch (themeChanged.emit → main.py _apply_application_theme →
  app.setStyleSheet global repolish). main.py now re-posts the app-wide
  restyle to a clean event-loop turn.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


THEME = {
    "window_bg": "#101820",
    "panel_bg": "#16212e",
    "card_bg": "#1c2a3a",
    "border": "#2a3b50",
    "accent": "#4d9dff",
    "text_primary": "#eef5ff",
    "text_secondary": "#9fb3c8",
}


def test_retint_helpers_exist_and_are_callable():
    from modules.download_manager.ui.widget import _dm_theming as t

    assert callable(t._dm_retint_widget_tree)
    assert callable(t._dm_retint_stylesheet)
    assert callable(t._dm_theme_color_map)


def test_retint_widget_tree_replaces_hardcoded_colors(qapp):
    from modules.download_manager.ui.widget._dm_theming import (
        _dm_retint_widget_tree,
    )

    root = QWidget()
    root.setStyleSheet("QWidget { background: #0f1419; color: #f7fafc; }")
    child = QLabel(root)
    child.setStyleSheet("QLabel { border: 1px solid #374151; color: #06b6d4; }")

    _dm_retint_widget_tree(root, THEME)

    assert "#101820" in root.styleSheet()          # window_bg applied
    assert "#eef5ff" in root.styleSheet()          # text_primary applied
    assert "#2a3b50" in child.styleSheet()         # border applied
    assert "#4d9dff" in child.styleSheet()         # accent applied


def test_retint_handles_none_root_and_empty_theme(qapp):
    from modules.download_manager.ui.widget._dm_theming import (
        _dm_retint_stylesheet,
        _dm_retint_widget_tree,
    )

    _dm_retint_widget_tree(None, THEME)  # must not raise
    w = QWidget()
    w.setStyleSheet("QWidget { background: #0f1419; }")
    _dm_retint_widget_tree(w, {})        # empty theme → identity, no raise
    assert "#0f1419" in w.styleSheet()
    assert _dm_retint_stylesheet("", THEME) == ""


def test_on_app_theme_changed_never_raises(qapp, monkeypatch):
    """The handler runs inside themeChanged.emit on the GUI thread — a raise
    becomes an excepthook CRITICAL (or worse). It must swallow and log."""
    from modules.download_manager.ui.widget._dm_theming import _DMThemingMixin

    class Host(_DMThemingMixin, QWidget):
        pass

    h = Host()
    # No _app_theme_manager attribute at all → theme=None path would raise
    # AttributeError pre-guard; the handler must absorb it.
    h._on_app_theme_changed(None)
    # Normal path with a real theme dict.
    h.setStyleSheet("QWidget { background: #0f1419; }")
    h._on_app_theme_changed(THEME)
    assert "#101820" in h.styleSheet()


def test_mainpy_defers_app_restyle_out_of_emit():
    src = (REPO_ROOT / "main.py").read_text(encoding="utf-8", errors="ignore")
    assert "themeChanged.connect(_apply_application_theme_deferred)" in src
    assert "themeChanged.connect(_apply_application_theme)" not in src
    assert "QTimer.singleShot(0, lambda: _apply_application_theme(theme))" in src


def test_dm_theming_source_defines_helper():
    src = (
        REPO_ROOT
        / "modules" / "download_manager" / "ui" / "widget" / "_dm_theming.py"
    ).read_text(encoding="utf-8")
    assert "def _dm_retint_widget_tree(" in src
    assert "def _dm_retint_stylesheet(" in src
