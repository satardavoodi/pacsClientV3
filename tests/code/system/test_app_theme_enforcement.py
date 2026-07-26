"""Centralised OS light/dark-mode immunity (2026-07-24).

The app applied a global QSS that only targeted the built-in dialog classes
(QMessageBox/QInputDialog/QFileDialog/QToolTip). A CUSTOM dialog/popup with no
complete stylesheet fell back to the QApplication palette — which, with the
native Windows style and no fixed palette, FOLLOWED the OS light/dark theme and
became unreadable (the recurring "every new popup breaks" defect, e.g. the 3D
Cursor windows).

Fix: install Fusion (honours the palette, ignores the OS theme) + a fixed dark
palette derived from the active theme, at the app level. The QSS still overrides
both for styled widgets, so only the broken un-styled ones change.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_palette_is_dark_readable():
    _app()
    from PySide6.QtGui import QPalette
    from PacsClient.utils.theme_manager import build_application_palette

    pal = build_application_palette()
    wt = pal.color(QPalette.ColorRole.WindowText)
    win = pal.color(QPalette.ColorRole.Window)
    base = pal.color(QPalette.ColorRole.Base)
    # text must be light, backgrounds dark → readable regardless of OS mode
    assert wt.lightnessF() > 0.7, f"WindowText should be light, got {wt.name()}"
    assert win.lightnessF() < 0.4, f"Window should be dark, got {win.name()}"
    assert base.lightnessF() < 0.4, f"Base (inputs) should be dark, got {base.name()}"
    # sufficient contrast between text and background
    assert wt.lightnessF() - win.lightnessF() > 0.4


def test_apply_installs_fusion_and_palette():
    app = _app()
    from PySide6.QtGui import QPalette
    from PacsClient.utils.theme_manager import apply_global_app_theme

    apply_global_app_theme(app)
    assert app.style().objectName().lower() == "fusion"
    assert app.palette().color(QPalette.ColorRole.WindowText).lightnessF() > 0.7


def test_kill_switch_disables_enforcement(monkeypatch):
    monkeypatch.setenv("AIPACS_FORCE_APP_THEME", "0")
    import importlib
    import PacsClient.utils.theme_manager as tm
    importlib.reload(tm)
    assert tm._force_app_theme_enabled() is False
    app = _app()
    # with the kill switch on, apply is a no-op (does not force Fusion)
    before = app.style().objectName()
    tm.apply_global_app_theme(app)
    assert app.style().objectName() == before
    monkeypatch.delenv("AIPACS_FORCE_APP_THEME", raising=False)
    importlib.reload(tm)


def test_unstyled_dialog_inherits_dark_palette():
    """THE representative case (3D Cursor class): a custom QDialog with a QLabel
    and NO background stylesheet must render on a DARK background with LIGHT text
    after the global theme is enforced — not the OS light/dark palette."""
    app = _app()
    from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout
    from PySide6.QtGui import QPalette
    from PacsClient.utils.theme_manager import apply_global_app_theme

    apply_global_app_theme(app)

    dlg = QDialog()                    # no parent, no stylesheet — the escaping case
    lay = QVBoxLayout(dlg)
    lbl = QLabel("Select nipple points")
    lay.addWidget(lbl)
    dlg.ensurePolished()
    lbl.ensurePolished()

    win = dlg.palette().color(QPalette.ColorRole.Window)
    txt = lbl.palette().color(QPalette.ColorRole.WindowText)
    assert win.lightnessF() < 0.4, "dialog background must be dark, not OS-light"
    assert txt.lightnessF() > 0.7, "label text must be light on the dark dialog"


def test_apply_dialog_theme_helper_forces_palette():
    app = _app()
    from PySide6.QtWidgets import QWidget
    from PySide6.QtGui import QPalette
    from PacsClient.utils.theme_manager import apply_dialog_theme

    w = QWidget()
    apply_dialog_theme(w)
    assert w.palette().color(QPalette.ColorRole.WindowText).lightnessF() > 0.7
    apply_dialog_theme(None)  # must not raise


def test_main_wires_global_theme_into_apply():
    """main.py must call apply_global_app_theme inside _apply_application_theme so
    the palette is (re)applied at startup AND on every theme change."""
    import pathlib
    root = pathlib.Path(__file__).resolve()
    for anc in root.parents:
        if (anc / "main.py").is_file() and (anc / "PacsClient").is_dir():
            src = (anc / "main.py").read_text(encoding="utf-8", errors="ignore")
            break
    else:
        pytest.skip("main.py not found")
    assert "apply_global_app_theme(app" in src
    i_apply = src.find("def _apply_application_theme")
    i_call = src.find("apply_global_app_theme(app")
    i_qss = src.find("app.setStyleSheet(themed_stylesheet)")
    assert -1 < i_apply < i_call < i_qss, "must apply palette before the stylesheet"
