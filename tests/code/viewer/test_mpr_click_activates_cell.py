"""Guard: clicking an MPR pane selects the MPR's host cell as the active viewport
(patient 48272, 2026-06-28).

Annotation tools are viewport-scoped — they target the active `selected_widget`. A
`StandardMPRViewer` is NOT a FAST `qt_fast_container`, so its VTK clicks did not run
`change_container_border`; after annotating another cell you could not re-select the
MPR by clicking it, so the ruler kept arming the other cell ("can't draw on MPR after
annotating the other layout"). Fix: the MPR's per-pane `eventFilter` (already installed
on every pane) now calls a host-set `_viewport_activate_cb` on `MouseButtonPress`, and
`ToolbarManager.toggle_zeta_mpr` wires that callback to
`patient_widget.change_container_border(host_id)` (flag `AIPACS_MPR_ACTIVATE_ON_CLICK`,
default-on; no-op when the MPR cell is already active).

Source-pins + a behavioral test of the eventFilter hook.
"""
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _layout_src() -> str:
    return (
        _repo_root() / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_layout.py"
    ).read_text(encoding="utf-8")


def _toolbar_src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "patient_toolbar" / "toolbar_manager.py"
    ).read_text(encoding="utf-8")


def test_mpr_eventfilter_calls_activate_callback_on_press():
    src = _layout_src()
    # setter present
    assert "def set_viewport_activate_callback(self, cb):" in src
    assert "self._viewport_activate_cb = cb" in src
    # the press branch invokes the host callback
    fn = src.find("def eventFilter")
    body = src[fn:fn + 3000]
    press = body.find("MouseButtonPress, event.Type.Wheel")
    cb = body.find("_viewport_activate_cb")
    assert press != -1 and cb != -1 and cb > press
    assert "if callable(_vac):" in body and "_vac()" in body


def test_toolbar_wires_activation_flag_gated():
    src = _toolbar_src()
    assert 'os.getenv("AIPACS_MPR_ACTIVATE_ON_CLICK"' in src
    assert "set_viewport_activate_callback(_activate_mpr_host)" in src
    # already-active guard (cheap no-op on crosshair clicks) + the real selection call
    assert 'getattr(_pw, "selected_widget", None) is _h' in src
    assert "_pw.change_container_border(_hid)" in src


def test_eventfilter_invokes_callback_behavioral():
    pytest.importorskip("PySide6")
    try:
        from modules.mpr.zeta_mpr.mpr_viewer._mpr_layout import _MprLayoutMixin
    except Exception as exc:  # pragma: no cover - heavy import env dependent
        pytest.skip(f"_mpr_layout import unavailable: {exc}")

    class _Base:
        # stands in for the next class in the real MRO (eventually QWidget)
        def eventFilter(self, obj, event):
            return False

    class T(_MprLayoutMixin, _Base):
        def __init__(self):
            self._vtk_widget_to_view = {}   # obj not mapped → view_name None
            self._viewport_activate_cb = None
            self.rotation_stopped = 0

        def stop_auto_rotation(self):
            self.rotation_stopped += 1

    class _Type:
        MouseButtonPress = "press"
        Wheel = "wheel"
        MouseButtonDblClick = "dbl"
        Resize = "resize"
        MouseButtonRelease = "rel"
        MouseMove = "move"

    class FakeEvent:
        Type = _Type

        def __init__(self, t):
            self._t = t

        def type(self):
            return self._t

        def button(self):
            return None

    t = T()
    hits = []
    t.set_viewport_activate_callback(lambda: hits.append(1))

    # A press fires the host activation callback.
    t.eventFilter(object(), FakeEvent(_Type.MouseButtonPress))
    assert hits == [1]

    # A wheel (stack scroll) does NOT activate the cell.
    t.eventFilter(object(), FakeEvent(_Type.Wheel))
    assert hits == [1]

    # No callback set → no error, no activation (flag-off / unwired = legacy).
    t2 = T()
    t2.eventFilter(object(), FakeEvent(_Type.MouseButtonPress))  # must not raise
