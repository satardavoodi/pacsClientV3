"""UI-4 — the empty footer bar at the bottom of the main page (2026-08-10).

Reported: "there is a bar at the lower part of the main page, please remove it".

Measured on the live 1920x1032 window before the fix, the bar was the
`footerContainter` strip drawing:
  * a full-width 1 px separator at y=1002 (the `border-top` applied by
    apply_theme), and
  * the borders of its own permanently-empty child frames at y=1007-1008
    (x 72-684 and 1291-1296) plus the 20 px `sizeGrip` square at x 1890-1909,
which together read as a stray bar / scrollbar under the patient list and cost
~30 px of vertical space for nothing.

Safe to hide, and these tests pin exactly why:
  * `label_15` and `activityLabel` are set to "" here and written NOWHERE else
    in the codebase — the footer can never show content;
  * `sizeGrip` is a bare QFrame, not a QSizeGrip (there is no QSizeGrip in the
    project at all) and nothing references it, so it never resized the
    frameless main window;
  * the widgets stay alive and in the layout because apply_theme() still styles
    `footerContainter` / `activityLabel` — hiding, not deleting, keeps that
    working and keeps the change reversible.

Restore switch: AIPACS_MAIN_FOOTER=1.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

UI_SRC = (REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui"
          / "AIPacs_ui.py").read_text(encoding="utf-8")

# Scan only the APPLICATION source trees. A repo-wide rglob walks .venv and the
# Nuitka build output (tens of thousands of files) and takes minutes.
_SOURCE_ROOTS = ("PacsClient", "modules")
_SKIP_DIR_PARTS = {".venv", "__pycache__", "build", "dist", "node_modules"}


def _app_sources():
    """Every first-party .py file, excluding vendored / generated trees."""
    for root in _SOURCE_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if _SKIP_DIR_PARTS & set(path.parts):
                continue
            yield path
    main_py = REPO_ROOT / "main.py"
    if main_py.is_file():
        yield main_py


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _strip_comments(text: str) -> str:
    """Drop ``#`` comment tails so a pin matches CODE, not prose about the code.

    Learned the hard way twice on this codebase: an explanatory comment that
    names the very symbol a pin searches for will satisfy the pin (or, here,
    break it) without any code changing.
    """
    out = []
    for line in text.splitlines():
        hit = line.find("#")
        out.append(line if hit == -1 else line[:hit])
    return "\n".join(out)


def _uses_qsizegrip(text: str) -> bool:
    """Real usage: an instantiation or an import — not a mention in prose."""
    code = _strip_comments(text)
    return bool(re.search(r"\bQSizeGrip\s*\(", code)
                or re.search(r"import[^\n]*\bQSizeGrip\b", code))


# ---------------------------------------------------------------------------
# The suppression itself.
# ---------------------------------------------------------------------------
def test_footer_is_suppressed_by_default():
    add = UI_SRC.find("self.verticalLayout_10.addWidget(self.footerContainter)")
    assert add != -1, "footer must still be built + added (apply_theme styles it)"
    block = UI_SRC[add:add + 1800]
    assert "self.footerContainter.setVisible(False)" in block
    assert 'os.getenv("AIPACS_MAIN_FOOTER", "0")' in block, (
        "the suppression must be behind a restore switch, default off")


def test_footer_widgets_are_not_deleted():
    """apply_theme() still touches them — deleting would raise AttributeError."""
    assert "self.footerContainter.setStyleSheet(" in UI_SRC
    assert "self.activityLabel.setStyleSheet(" in UI_SRC
    assert "self.footerContainter = QWidget(" in UI_SRC


# ---------------------------------------------------------------------------
# Why it is safe — the footer could never show anything.
# ---------------------------------------------------------------------------
def test_footer_labels_are_never_written_anywhere():
    """If some code set text on them, hiding the footer would hide real info."""
    hits = []
    for path in _app_sources():
        text = _read(path)
        for name in ("activityLabel", "label_15"):
            for m in re.finditer(rf"\b{name}\.setText\s*\(", text):
                hits.append(f"{path.name}:{text[:m.start()].count(chr(10)) + 1}")
    assert hits == [], (
        "a footer label is written to — the footer is NOT dead UI: " + ", ".join(hits))


def test_sizegrip_is_a_plain_frame_and_unused():
    """It is not a QSizeGrip, so hiding it removes no resize affordance."""
    assert "self.sizeGrip = QFrame(" in UI_SRC
    assert not _uses_qsizegrip(UI_SRC)

    # ...and nothing anywhere else in the app refers to it.
    refs = []
    for path in _app_sources():
        if path.name == "AIPacs_ui.py":
            continue
        if "sizeGrip" in _strip_comments(_read(path)):
            refs.append(path.name)
    assert refs == [], f"sizeGrip is referenced elsewhere: {refs}"


def test_no_qsizegrip_anywhere_in_the_project():
    """Pins the claim the fix rests on: the window is not resized by a grip."""
    found = [p.name for p in _app_sources() if _uses_qsizegrip(_read(p))]
    assert found == [], f"a QSizeGrip exists after all — re-check UI-4: {found}"


# ---------------------------------------------------------------------------
# Behavioural — build the real shell offscreen and look at the footer.
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_footer_hidden_on_the_real_shell(monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("WINDIR", r"C:\Windows")
    from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

    app = QApplication.instance() or QApplication([])
    try:
        from PacsClient.pacs.workstation_ui.AIPacs_ui import ControlPanelWindow
    except Exception as exc:                      # pragma: no cover - env dependent
        pytest.skip(f"control panel shell unavailable: {exc}")

    class _Shell(QMainWindow):
        def __init__(self):
            super().__init__()
            self.tab_widget = QTabWidget()
            self.host_window = None

    monkeypatch.delenv("AIPACS_MAIN_FOOTER", raising=False)
    mw = _Shell()
    try:
        ui = ControlPanelWindow(MainWindow=mw)
        ui.setupUi()
    except Exception as exc:                      # pragma: no cover - env dependent
        pytest.skip(f"shell build unavailable in this env: {exc}")
    mw.resize(1920, 1032)
    mw.show()
    app.processEvents()

    assert ui.footerContainter.isVisible() is False, "the footer bar is still shown"
    assert ui.footerContainter.height() == 0
    # still parented into the layout so apply_theme() keeps working
    assert ui.verticalLayout_10.indexOf(ui.footerContainter) >= 0
    assert (ui.label_15.text(), ui.activityLabel.text()) == ("", "")

    # a theme re-apply must not resurrect it
    ui.apply_theme()
    app.processEvents()
    assert ui.footerContainter.isVisible() is False

    # the reclaimed strip goes to the page body
    assert ui.mainBodyContent.height() == mw.height()
