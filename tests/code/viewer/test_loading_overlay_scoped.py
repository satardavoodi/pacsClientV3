"""Guard: the AiPacsLoadingOverlay is scoped to the app + anchor viewport, so a
top-level always-on-top loading overlay never floats above OTHER applications
(e.g. Chrome) and is dropped on a patient-tab switch (2026-06-24, Issue 1).

Background: the overlay is intentionally a top-level Qt.Tool + WindowStaysOnTopHint
window — the only reliable way to paint above native VTK/OpenGL viewports. Left
unscoped it also floated above other apps and lingered after a tab switch. The fix
keeps the always-on-top window (VTK compatibility) but:
  * hides it on QApplication.applicationStateChanged != ApplicationActive
    (another app is in front),
  * hides it when the anchor viewport receives QEvent.Hide (tab switch / dispose),
  * restores it when focus + anchor return and loading is still intended,
  * stops re-showing once hide_overlay() has run (_intended_visible=False).

Pure source-pin (constructing the real overlay needs a QApplication + the branded
pixmap; this is robust and needs no PySide6).
"""
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _overlay_src() -> str:
    return (
        _repo_root() / "PacsClient" / "components" / "loading_overlay.py"
    ).read_text(encoding="utf-8")


def test_scoping_flag_and_app_state_hook_present():
    src = _overlay_src()
    assert "AIPACS_OVERLAY_SCOPED" in src
    assert "_intended_visible" in src
    # Hooked to application focus changes (not intra-app window changes).
    assert "applicationStateChanged" in src
    assert "def _on_app_state_changed" in src


def test_hides_when_app_not_active():
    src = _overlay_src()
    idx = src.find("def _on_app_state_changed")
    assert idx != -1
    body = src[idx: idx + 700]
    # Hide when the application is no longer the active app.
    assert "Qt.ApplicationActive" in body
    assert "self.hide()" in body


def test_anchor_hide_drops_overlay_on_tab_switch():
    src = _overlay_src()
    idx = src.find("def eventFilter")
    assert idx != -1
    body = src[idx: idx + 900]
    assert "QEvent.Hide" in body
    assert "obj is self._anchor" in body


def test_hide_overlay_clears_intended_visible():
    src = _overlay_src()
    idx = src.find("def hide_overlay")
    assert idx != -1
    body = src[idx: idx + 800]
    assert "_intended_visible = False" in body


def test_vtk_overlay_capability_preserved():
    """The always-on-top top-level flags stay (so the overlay still paints above an
    in-app VTK viewport when AI-PACS is focused) — the fix scopes WHEN it shows, it
    does not downgrade the window type."""
    src = _overlay_src()
    assert "Qt.Tool" in src
    assert "Qt.WindowStaysOnTopHint" in src
