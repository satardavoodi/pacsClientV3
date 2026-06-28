"""Guard: MPR annotations still target the MPR after an active-layout switch (2026-06-28).

Repro (patient 48117): a multi-cell layout with the MPR in one cell. The user clicks
another cell to make it active. The MPR-preserve active-viewport switch
(`_vc_layout.set_viewer_to_main_viewer`) keeps the MPR intact but moves
`selected_widget` to the clicked (FAST) cell while keeping `tool_selected == MPR`.
Pressing Ruler/Angle/Arrow then armed the now-active FAST cell, so clicking the MPR
window did nothing ("annotation doesn't work on the MPR window after switching the
active layout").

Fix: `ToolbarManager._annotation_target_widget()` — when MPR mode is active but the
active cell is NOT the MPR, it returns the open MPR HOST cell so the annotation
routes to the MPR. The annotation button handlers (ruler/angle/two-line-angle/
arrow/text) call it instead of using `selected_widget` directly. UNIFIED 2026-06-28:
the `AIPACS_ANNOTATION_ROUTE_TO_OPEN_MPR` flag was retired (confirmed live) — the
routing is unconditional.

Source-pins + a behavioral test of the resolver (bound to a fake, no Qt).
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


def test_resolver_exists_and_unconditional():
    src = _src()
    fn = src.find("def _annotation_target_widget(self):")
    assert fn != -1
    body = src[fn:fn + 2400]
    # Unified 2026-06-28: the AIPACS_ANNOTATION_ROUTE_TO_OPEN_MPR flag was retired —
    # routing annotations to the open MPR cell is now the only path.
    assert "AIPACS_ANNOTATION_ROUTE_TO_OPEN_MPR" not in body
    # only reroute while MPR mode is the active mode
    assert "self.tool_access.MPR in str(self.tool_selected)" in body
    # scans the viewport nodes for the open MPR host cell
    assert "getattr(w, '_zeta_mpr_widget', None) is not None" in body
    # active cell already the MPR → unchanged
    assert "if self.is_mpr_viewer(sw):" in body


def test_annotation_handlers_route_through_resolver():
    src = _src()
    # every annotation button handler must go through the resolver, not selected_widget
    assert "self.toggle_ruler(self._annotation_target_widget())" in src
    assert "self.toggle_angle(self._annotation_target_widget())" in src
    assert "self.toggle_two_line_angle(self._annotation_target_widget())" in src
    assert "self.toggle_arrow(self._annotation_target_widget())" in src
    assert "self.toggle_text(self._annotation_target_widget())" in src


def test_resolver_behavioral(monkeypatch):
    pytest.importorskip("PySide6")
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import (
            ToolbarManager,
        )
    except Exception as exc:  # pragma: no cover - heavy import env dependent
        pytest.skip(f"toolbar_manager import unavailable: {exc}")

    class Acc:
        MPR = "MPR"

    class Node:
        def __init__(self, w):
            self.vtk_widget = w

    fast_cell = types.SimpleNamespace()                       # no _zeta_mpr_widget
    mpr_host = types.SimpleNamespace(_zeta_mpr_widget=object())  # MPR host cell

    fake = types.SimpleNamespace(
        patient_widget=types.SimpleNamespace(
            selected_widget=fast_cell,
            lst_nodes_viewer=[Node(mpr_host), Node(fast_cell)],
        ),
        tool_selected="MPR,RULER",
        tool_access=Acc(),
    )
    fake.is_mpr_viewer = lambda w: getattr(w, "_zeta_mpr_widget", None) is not None
    resolve = ToolbarManager._annotation_target_widget.__get__(fake)

    # MPR mode active + active cell is the FAST cell → routes to the MPR host.
    assert resolve() is mpr_host

    # Active cell IS the MPR → returned unchanged (no rerouting needed).
    fake.patient_widget.selected_widget = mpr_host
    assert resolve() is mpr_host

    # NOT in MPR mode → the active (FAST) cell is annotated, not the MPR.
    fake.patient_widget.selected_widget = fast_cell
    fake.tool_selected = "RULER"
    assert resolve() is fast_cell
