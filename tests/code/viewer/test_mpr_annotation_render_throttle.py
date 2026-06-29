"""Guard: MPR ruler/angle placement renders at frame cadence, not per move event
(smooth drawing, 48272 follow-up, 2026-06-28).

The vtkDistanceWidget (ruler) / vtkAngleWidget render on EVERY MouseMoveEvent during
the two-point placement. On a large reslice the flood of move events saturates the GUI
thread → choppy / laggy rubber-band. A high-priority MouseMoveEvent observer DROPS
(aborts) intermediate moves so the widget renders at ~the frame cadence
(AIPACS_MPR_ANNOTATION_THROTTLE_MS, default 16 ms). It aborts ONLY while a measurement
is being placed (`current_tool` ruler/angle); the 2nd/3rd click is never throttled.

Also removes two per-activation debug `print()`s.

Source-pins + a behavioral test of the throttle decision.
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
        _repo_root() / "modules" / "mpr" / "zeta_mpr" / "mpr_measurement_tools.py"
    ).read_text(encoding="utf-8")


def test_debug_prints_removed():
    src = _src()
    assert "print('self.mpr_viewer.viewers[view_name]:'" not in src
    assert 'print("self.mpr_viewer.viewers[view_name][\'widget\']:"' not in src


def test_throttle_installed_and_removed_at_the_right_sites():
    src = _src()
    assert 'os.environ.get("AIPACS_MPR_ANNOTATION_THROTTLE_MS"' in src
    # installed for BOTH ruler and angle placement
    assert src.count("self._install_placement_render_throttle(view_name, interactor)") == 2
    # removed on single-use auto-exit AND on manual deactivate
    assert src.count("self._remove_placement_render_throttles()") >= 2
    # the observer sits above the widget and aborts a dropped frame
    assert 'AddObserver("MouseMoveEvent", _on_move, 1.0)' in src
    assert "cmd.SetAbortFlag(1)" in src
    # only throttles an ACTIVE placement (never blocks normal interaction)
    assert "if self.current_tool not in ('ruler', 'angle'):" in src


def test_throttle_decision_behavioral():
    pytest.importorskip("vtk")
    try:
        from modules.mpr.zeta_mpr import mpr_measurement_tools as MT
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"mpr_measurement_tools import unavailable: {exc}")

    if MT._MPR_ANNOTATION_THROTTLE_MS <= 0:
        pytest.skip("throttle disabled via env in this environment")

    class FakeCmd:
        def __init__(self):
            self.aborted = 0

        def SetAbortFlag(self, v):
            self.aborted = v

    class FakeInteractor:
        def __init__(self):
            self._cbs, self._cmds, self._n = {}, {}, 0

        def AddObserver(self, event, cb, prio):
            self._n += 1
            self._cbs[self._n] = cb
            self._cmds[self._n] = FakeCmd()
            return self._n

        def GetCommand(self, tag):
            return self._cmds.get(tag)

        def RemoveObserver(self, tag):
            self._cbs.pop(tag, None)

    fake = types.SimpleNamespace(
        current_tool="ruler",
        _placement_throttle_observers={},
        _placement_throttle_last={},
    )
    install = MT.MPRMeasurementTools._install_placement_render_throttle.__get__(fake)
    interactor = FakeInteractor()
    install("axial", interactor)

    tag = fake._placement_throttle_observers["axial"][1]
    cb = interactor._cbs[tag]
    cmd = interactor._cmds[tag]

    # First move (last == 0.0) → far past budget → NOT aborted; records the time.
    cb(interactor, "MouseMoveEvent")
    assert cmd.aborted == 0

    # Immediate next move → within the budget → dropped (aborted).
    cb(interactor, "MouseMoveEvent")
    assert cmd.aborted == 1

    # When NOT placing a measurement, a move is never aborted (normal interaction).
    cmd.aborted = 0
    fake.current_tool = None
    cb(interactor, "MouseMoveEvent")
    assert cmd.aborted == 0

    # Removal detaches the observer and clears state.
    remove = MT.MPRMeasurementTools._remove_placement_render_throttles.__get__(fake)
    remove()
    assert fake._placement_throttle_observers == {}
    assert tag not in interactor._cbs
