"""Guard: MPR annotation tools are VIEWPORT-SCOPED (patient 48272, 2026-06-28).

`ToolbarManager._annotation_target_widget()` must ALWAYS return the active
`selected_widget` — the cell the user last selected — so each layout/cell annotates
independently. An MPR open in one cell must NOT capture annotation tools meant for
another cell (reported: "Layout 2 can't use ruler/annotation while Layout 1 is in
MPR"). An earlier version rerouted annotations to the open MPR cell whenever MPR
mode was globally active; that broke the multi-layout case and was removed. To
annotate the MPR, its cell must be the active viewport.

Source-pins + a behavioral test (bound to a fake, no Qt).
"""
import types
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "patient_toolbar" / "toolbar_manager.py"
    ).read_text(encoding="utf-8")


def test_resolver_is_viewport_scoped():
    src = _src()
    fn = src.find("def _annotation_target_widget(self):")
    assert fn != -1
    body = src[fn:fn + 1400]
    # ALWAYS the active selected_widget — viewport-scoped.
    assert "return getattr(self.patient_widget, 'selected_widget', None)" in body
    # the old global MPR-rerouting (which broke Layout 2) is gone.
    assert "[MPR-ANNOT-ROUTE]" not in body
    assert "_zeta_mpr_widget" not in body
    assert "AIPACS_ANNOTATION_ROUTE_TO_OPEN_MPR" not in body


def test_annotation_handlers_route_through_resolver():
    src = _src()
    # every annotation button handler goes through the (viewport-scoped) resolver
    assert "self.toggle_ruler(self._annotation_target_widget())" in src
    assert "self.toggle_angle(self._annotation_target_widget())" in src
    assert "self.toggle_two_line_angle(self._annotation_target_widget())" in src
    assert "self.toggle_arrow(self._annotation_target_widget())" in src
    assert "self.toggle_text(self._annotation_target_widget())" in src


def test_resolver_returns_active_viewport_behavioral():
    pytest.importorskip("PySide6")
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import (
            ToolbarManager,
        )
    except Exception as exc:  # pragma: no cover - heavy import env dependent
        pytest.skip(f"toolbar_manager import unavailable: {exc}")

    class Node:
        def __init__(self, w):
            self.vtk_widget = w

    fast_cell = types.SimpleNamespace()                         # Layout 2 (FAST)
    mpr_host = types.SimpleNamespace(_zeta_mpr_widget=object())  # Layout 1 (MPR)

    fake = types.SimpleNamespace(
        patient_widget=types.SimpleNamespace(
            selected_widget=fast_cell,
            lst_nodes_viewer=[Node(mpr_host), Node(fast_cell)],
        ),
        tool_selected="MPR,RULER",   # MPR mode globally active (Layout 1)
    )
    resolve = ToolbarManager._annotation_target_widget.__get__(fake)

    # P2: active cell is Layout 2 (FAST) while Layout 1 is MPR → annotate Layout 2,
    # NOT the MPR. (The old code wrongly returned mpr_host here.)
    assert resolve() is fast_cell

    # Active cell IS the MPR → annotate the MPR.
    fake.patient_widget.selected_widget = mpr_host
    assert resolve() is mpr_host
