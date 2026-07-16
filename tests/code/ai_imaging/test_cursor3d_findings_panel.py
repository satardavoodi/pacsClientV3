"""
Guard — the 3D-Cursor findings corner panel (multiple-lesion UX).

Verifies the piece that is easy to get wrong: a row click must emit the finding's
GLOBAL index (its position in the controller's ordered list), and `set_selected`
must highlight by that same global index — so the panel stays correct even when
findings target more than one viewport.

Qt-offscreen. Skipped when PySide6 / an offscreen display is unavailable; the VTK
overlay rendering + the on-image placement need the live source build.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_qt = pytest.importorskip("PySide6.QtWidgets")


# Same package-stub bootstrap the other cursor_3d tests use, so the pure submodule
# imports without dragging in the GUI package __init__.
_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
for _name, _path in [
    ("modules", _ROOT / "modules"),
    ("modules.ai_imaging", _ROOT / "modules" / "ai_imaging"),
    ("modules.ai_imaging.ai_module_ui", _ROOT / "modules" / "ai_imaging" / "ai_module_ui"),
    ("modules.ai_imaging.ai_module_ui.cursor_3d",
     _ROOT / "modules" / "ai_imaging" / "ai_module_ui" / "cursor_3d"),
]:
    if _name not in sys.modules:
        _stub = types.ModuleType(_name)
        _stub.__path__ = [str(_path)]
        sys.modules[_name] = _stub

_fp = importlib.import_module("modules.ai_imaging.ai_module_ui.cursor_3d.findings_panel")


@pytest.fixture(scope="module")
def _app():
    app = _qt.QApplication.instance() or _qt.QApplication([])
    yield app


def test_row_click_emits_global_index(_app):
    panel = _fp.FindingsOverlayPanel()
    got = []
    panel.selected.connect(lambda i: got.append(i))

    # Two findings; global indices 0 and 1, numbers 1 and 2.
    panel.set_findings([(0, 1, 0.48, "R MLO->CC"), (1, 2, 0.46, "R MLO->CC")], selected=0)
    assert len(panel._rows) == 2

    # Simulate a click on the SECOND row → must emit its global index (1).
    panel._rows[1]._on = None
    panel._rows[1].clicked.emit(panel._rows[1]._index)
    assert got == [1]


def test_set_selected_highlights_by_global_index(_app):
    panel = _fp.FindingsOverlayPanel()
    panel.set_findings([(0, 1, 0.7, "L CC->MLO"), (1, 2, 0.5, "L CC->MLO")], selected=0)
    panel.set_selected(1)
    # The row whose stored index == 1 is the highlighted (selected) style.
    styles = {r._index: r.styleSheet() for r in panel._rows}
    assert styles[1] != styles[0]
    assert "rgba(30, 220, 255" in styles[1]   # the selected accent


def test_single_finding_titles_singular(_app):
    panel = _fp.FindingsOverlayPanel()
    panel.set_findings([(0, 1, 0.6, "R MLO->CC")], selected=0)
    assert "1 finding" in panel._title.text()
