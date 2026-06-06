"""Guard tests for the unified viewport capture router (CaptureActiveViewport).

Covers the routing contract introduced for the MPR screenshot fix:
  - Plain 2D viewing  -> capture_active_viewport returns None (caller must run
    its legacy Advanced/FAST capture path unchanged — no regression).
  - Visible Zeta/Curve MPR replacing a viewport -> the MPR widget is resolved.
  - Hidden / torn-down MPR widgets are never resolved.

Pure-logic tests: no QApplication, no VTK (FAST-safe module contract).
"""
import sys
from pathlib import Path

# repo root (tests/code/viewer/ -> 3 levels up)
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.viewer.viewport_capture import (  # noqa: E402
    capture_active_viewport,
    resolve_active_mpr_widget,
)


class _Dummy:
    """Stand-in widget: visibility-only duck type."""

    def __init__(self, visible=True):
        self._visible = visible

    def isVisible(self):
        return self._visible


class _Node:
    def __init__(self, vtk_widget):
        self.vtk_widget = vtk_widget


class _PatientWidget:
    def __init__(self, nodes=(), study_uid="1.2.3", selected_widget=None):
        self.lst_nodes_viewer = list(nodes)
        self.study_uid = study_uid
        self.selected_widget = selected_widget


def test_no_mpr_returns_none_so_legacy_2d_path_runs():
    selected = _Dummy()
    pw = _PatientWidget(nodes=[_Node(selected)], selected_widget=selected)
    assert resolve_active_mpr_widget(selected, pw) is None
    # The router must hand plain 2D viewing back to the caller untouched.
    assert capture_active_viewport(pw, selected) is None


def test_visible_zeta_mpr_on_selected_widget_is_resolved():
    selected = _Dummy()
    mpr = _Dummy(visible=True)
    selected._zeta_mpr_widget = mpr
    assert resolve_active_mpr_widget(selected) is mpr


def test_hidden_mpr_widget_is_not_resolved():
    selected = _Dummy()
    selected._zeta_mpr_widget = _Dummy(visible=False)
    assert resolve_active_mpr_widget(selected) is None


def test_curve_mpr_attr_is_resolved():
    selected = _Dummy()
    mpr = _Dummy(visible=True)
    selected._curve_mpr_widget = mpr
    assert resolve_active_mpr_widget(selected) is mpr


def test_mpr_on_inner_vtk_widget_is_resolved():
    inner = _Dummy()
    mpr = _Dummy(visible=True)
    inner._zeta_mpr_widget = mpr
    selected = _Dummy()
    selected.vtk_widget = inner
    assert resolve_active_mpr_widget(selected) is mpr


def test_selection_that_is_the_mpr_widget_itself_is_resolved():
    mpr = _Dummy(visible=True)
    mpr._original_widget = _Dummy()
    assert resolve_active_mpr_widget(mpr) is mpr


def test_grid_scan_fallback_finds_mpr_on_other_node():
    selected = _Dummy()  # selection still points at a plain 2D widget
    other = _Dummy()
    mpr = _Dummy(visible=True)
    other._zeta_mpr_widget = mpr
    pw = _PatientWidget(nodes=[_Node(selected), _Node(other)], selected_widget=selected)
    assert resolve_active_mpr_widget(selected, pw) is mpr


def test_none_selection_with_no_nodes_is_safe():
    pw = _PatientWidget(nodes=[], selected_widget=None)
    assert resolve_active_mpr_widget(None, pw) is None
    assert capture_active_viewport(pw, None) is None
