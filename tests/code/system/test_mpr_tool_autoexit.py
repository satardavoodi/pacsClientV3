"""Guards for MPR single-use tool auto-exit (2026-06-09).

MPR ruler/angle/arrow must behave like the 2D viewer: after ONE completed
measurement the tool auto-exits and the mouse returns to the MPR default
(stack / WL / zoom). Previously the persistent VTK widget stayed enabled, so
the tool got stuck, stacking stopped, extra measurements were drawn, and the
toolbar highlight diverged from the actual interaction state.

Pattern mirrored from modules/viewer/interactor_styles/ruler_interactorstyle.py
(place_point_event → auto_deactivate_tool).
"""
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_MEAS = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_measurement_tools.py")
_LAYOUT = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_layout.py")
_TOOLBAR = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
            / "patient_toolbar" / "toolbar_manager.py")


def _no_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _read(p: Path) -> str:
    return _no_comments(p.read_text(encoding="utf-8", errors="ignore"))


# ───────────────────────────── source guards ─────────────────────────────

def test_measurement_tools_have_autoexit_machinery():
    code = _read(_MEAS)
    assert "def _register_placement_autoexit" in code
    assert "def _fire_single_use_auto_exit" in code
    assert "def _do_single_use_auto_exit" in code
    assert "self.on_auto_exit" in code
    # ruler completes on 2 points, angle on 3, arrow fires after one draw
    assert "_register_placement_autoexit(distance_widget, view_name, 'ruler', 2)" in code
    assert "_register_placement_autoexit(angle_widget, view_name, 'angle', 3)" in code
    assert "self._fire_single_use_auto_exit(view_name, 'arrow')" in code


def test_layout_exposes_set_tool_auto_exit_callback():
    code = _read(_LAYOUT)
    assert "def set_tool_auto_exit_callback" in code
    assert "self.measurement_tools.on_auto_exit = callback" in code


def test_toolbar_registers_autoexit_for_all_single_use_tools():
    code = _read(_TOOLBAR)
    assert "def _mpr_single_use_tool_finished" in code
    assert "def _register_mpr_tool_auto_exit" in code
    # MPR mode stays active; only the measurement tool turns off.
    fn = code[code.index("def _mpr_single_use_tool_finished"):]
    fn = fn[:1200]
    assert "self.tool_selected = self.tool_access.MPR" in fn
    assert "self.handle_buttons_checked()" in fn
    # all three single-use MPR tools register the callback before activating
    assert code.count("self._register_mpr_tool_auto_exit(mpr_widget)") >= 3


# ─────────────────────────── behavioral guards ───────────────────────────

@pytest.fixture()
def meas_tools():
    pytest.importorskip("vtk")
    from modules.mpr.zeta_mpr.mpr_measurement_tools import MPRMeasurementTools

    class _StubViewer:
        viewers = {}

        def _request_render(self, *_a, **_k):
            pass

    return MPRMeasurementTools(_StubViewer())


def test_auto_exit_cleans_empty_views_keeps_completed_and_fires_callback(meas_tools):
    mt = meas_tools

    class _FakeWidget:
        def __init__(self):
            self.off = False

        def Off(self):
            self.off = True

    # Simulate ruler armed on all three views; user completes on 'axial'.
    axial_w, sag_w, cor_w = _FakeWidget(), _FakeWidget(), _FakeWidget()
    mt.active_tools['axial']['ruler'] = [axial_w]
    mt.active_tools['sagittal']['ruler'] = [sag_w]
    mt.active_tools['coronal']['ruler'] = [cor_w]
    mt.current_tool = 'ruler'

    fired = []
    mt.on_auto_exit = lambda: fired.append(True)

    mt._do_single_use_auto_exit('axial', 'ruler')

    # Completed view keeps its measurement; empty views are turned off + dropped.
    assert mt.active_tools['axial']['ruler'] == [axial_w]
    assert axial_w.off is False
    assert sag_w.off is True and cor_w.off is True
    assert mt.active_tools['sagittal']['ruler'] == []
    assert mt.active_tools['coronal']['ruler'] == []
    # Returned to default + toolbar notified exactly once.
    assert mt.current_tool is None
    assert fired == [True]


def test_placement_counting_fires_autoexit_at_threshold(meas_tools):
    mt = meas_tools
    calls = []
    mt._fire_single_use_auto_exit = lambda vn, tn: calls.append((vn, tn))

    class _FakeWidget:
        def __init__(self):
            self.observer = None

        def AddObserver(self, event, cb):
            self.observer = cb
            return 1

    w = _FakeWidget()
    mt._register_placement_autoexit(w, 'axial', 'ruler', 2)
    assert callable(w.observer)

    w.observer(None, None)            # first point — no exit yet
    assert calls == []
    w.observer(None, None)            # second point — completes → auto-exit
    assert calls == [('axial', 'ruler')]


def test_reentrancy_guard_blocks_double_fire(meas_tools):
    mt = meas_tools
    mt._auto_exit_in_progress = True   # simulate an in-flight exit
    fired = []
    mt.on_auto_exit = lambda: fired.append(True)
    mt._fire_single_use_auto_exit('axial', 'ruler')
    # Guard active → no second scheduling/callback.
    assert fired == []
