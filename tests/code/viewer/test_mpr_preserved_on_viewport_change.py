"""Guard: a drag-drop / click onto ANOTHER viewport must not tear down MPR.

Scenario (1×2 layout): viewport 1 is in MPR mode, viewport 2 shows a series.
Dropping a new series onto viewport 2 changes the ACTIVE viewport (1 → 2). That
active-viewport change used to call `check_and_deactivate_tools()` while
`selected_widget` was still the MPR host (it is reassigned afterwards), so the
MPR guard saw an MPR-hosting selection and called `toggle_zeta_mpr()` — which
scans every node and closes whichever cell hosts MPR. Net effect: dropping on
viewport 2 exited viewport 1's MPR.

Fix (2026-06-21): `set_viewer_to_main_viewer` treats MPR as a PER-VIEWPORT mode
— on an active-viewport change it just moves the selection and leaves MPR (and
`tool_selected`) intact. Gated by `AIPACS_MPR_PRESERVE_ON_VIEWPORT_CHANGE`
(default on; `=0` restores the legacy teardown).

The method is exec'd from source against stubs so the test needs no live
QApplication / VTK / viewer stack (offscreen-safe).
"""
import os
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_LAYOUT = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
           / "_vc_layout.py")


class _DummyLogger:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


def _load_set_viewer_class():
    """Exec just `set_viewer_to_main_viewer` as a one-method class."""
    src = _LAYOUT.read_text(encoding="utf-8", errors="ignore")
    start = src.index("    def set_viewer_to_main_viewer(self, node_viewer")
    end = src.index("    def change_container_border(self, id_vtk_widget):", start)
    block = textwrap.dedent(src[start:end])
    ns = {"os": os, "logger": _DummyLogger(), "VTKWidget": object, "NodeViewer": object}
    exec("class _C:\n" + textwrap.indent(block, "    "), ns)  # noqa: S102
    return ns["_C"]


_Cls = _load_set_viewer_class()


class _ToolAccess:
    MPR = "MPR"
    RULER = "RULER"


class _FakeToolbar:
    def __init__(self, tool_selected, activated_method=None):
        self.tool_access = _ToolAccess()
        self.tool_selected = tool_selected
        self.deactivate_calls = 0
        self._activated_method = activated_method

    def get_tool_activated_method(self):
        return self._activated_method

    def check_and_deactivate_tools(self):
        self.deactivate_calls += 1


class _FakeNode:
    def __init__(self, widget, slider):
        self.vtk_widget = widget
        self.slider = slider


def _make_controller(tb, current_widget):
    inst = _Cls.__new__(_Cls)        # bypass __init__ (mixin has none here)
    inst.selected_widget = current_widget
    inst.slider = "old_slider"

    class _PW:
        pass

    pw = _PW()
    pw.toolbar_manager = tb
    inst.parent_widget = pw
    return inst


def test_mpr_active_viewport_change_does_not_deactivate(monkeypatch):
    monkeypatch.delenv("AIPACS_MPR_PRESERVE_ON_VIEWPORT_CHANGE", raising=False)
    mpr_host = object()        # viewport 1 (MPR)
    target = object()          # viewport 2 (drop target)
    tb = _FakeToolbar(tool_selected="MPR")
    ctrl = _make_controller(tb, mpr_host)

    ctrl.set_viewer_to_main_viewer(_FakeNode(target, "new_slider"))

    # MPR must NOT be torn down…
    assert tb.deactivate_calls == 0
    # …the active selection moves to the drop target…
    assert ctrl.selected_widget is target
    assert ctrl.slider == "new_slider"
    # …and the MPR mode flag is left intact.
    assert tb.tool_selected == "MPR"


def test_non_mpr_tool_still_deactivates_and_reapplies(monkeypatch):
    monkeypatch.delenv("AIPACS_MPR_PRESERVE_ON_VIEWPORT_CHANGE", raising=False)
    reapplied = []
    tb = _FakeToolbar(tool_selected="RULER", activated_method=lambda w: reapplied.append(w))
    old, target = object(), object()
    ctrl = _make_controller(tb, old)

    ctrl.set_viewer_to_main_viewer(_FakeNode(target, "s2"))

    # legacy/transient-tool behaviour unchanged: deactivate on old, re-apply on new
    assert tb.deactivate_calls == 1
    assert ctrl.selected_widget is target
    assert reapplied == [target]
    assert tb.tool_selected is None  # reset before re-apply


def test_same_widget_is_noop():
    tb = _FakeToolbar(tool_selected="MPR")
    w = object()
    ctrl = _make_controller(tb, w)
    assert ctrl.set_viewer_to_main_viewer(_FakeNode(w, "s")) is False
    assert tb.deactivate_calls == 0


def test_flag_off_restores_legacy_mpr_teardown(monkeypatch):
    monkeypatch.setenv("AIPACS_MPR_PRESERVE_ON_VIEWPORT_CHANGE", "0")
    tb = _FakeToolbar(tool_selected="MPR")
    mpr_host, target = object(), object()
    ctrl = _make_controller(tb, mpr_host)

    ctrl.set_viewer_to_main_viewer(_FakeNode(target, "s2"))

    # legacy path: the active-viewport change DOES run check_and_deactivate_tools
    assert tb.deactivate_calls == 1
    assert ctrl.selected_widget is target


# ── source pins (guard can't be silently removed) ────────────────────────────
def test_source_has_mpr_preserve_guard():
    src = _LAYOUT.read_text(encoding="utf-8", errors="ignore")
    seg = src[src.index("def set_viewer_to_main_viewer"):
              src.index("def change_container_border(self, id_vtk_widget):")]
    assert "AIPACS_MPR_PRESERVE_ON_VIEWPORT_CHANGE" in seg
    assert "tool_access.MPR" in seg
    # non-MPR path must still deactivate tools (transient-tool cleanup preserved)
    assert "check_and_deactivate_tools()" in seg
