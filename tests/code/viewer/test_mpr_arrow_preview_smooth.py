"""Guard: smooth, FAST-like MPR arrow drawing (2026-06-28).

The two-click MPR arrow used to anchor the tail on click 1 and only draw on click
2 — no rubber-band, unlike the ruler (vtkDistanceWidget previews natively) and the
FAST viewer. This adds a LIVE preview leader that follows the cursor from the tail,
throttled to 2px display motion for smoothness, plus an IMMEDIATE final render so
the placed arrow appears the instant the 2nd click lands.

Purely additive — a transient overlay actor + render timing. NO geometry, reslice,
slice order, or measurement value changes (the placed arrow's world points are
unchanged). Flag ``AIPACS_MPR_ANNOTATION_SMOOTH`` (default ON; ``=0`` = byte-identical
legacy: no preview, batched final render).

Source-pins the wiring + a behavioral test of the preview throttle/lifecycle bound
to a fake viewer (no real VTK render window).
"""
import re
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


# ----------------------------------------------------------------------------
# Flag — default ON, kill switch preserved.
# ----------------------------------------------------------------------------
def test_flag_default_on():
    src = _src()
    assert 'os.environ.get("AIPACS_MPR_ANNOTATION_SMOOTH"' in src
    # default-on: absent env resolves truthy (NOT in the off-set)
    blk = src[src.find("def _annotation_smooth_enabled"):src.find("def _annotation_smooth_enabled") + 260]
    assert 'not in (' in blk and '"0", "false", "off"' in blk


# ----------------------------------------------------------------------------
# Wiring — move observer installed for preview, preview cleared on click 2 and on
# tool teardown, final render is immediate.
# ----------------------------------------------------------------------------
def test_move_observer_installed_for_preview():
    src = _src()
    fn = src.find("def _activate_arrow_on_view")
    assert fn != -1
    body = src[fn:fn + 1600]
    assert "if _MPR_ANNOTATION_SMOOTH:" in body
    assert 'AddObserver("MouseMoveEvent"' in body
    assert "self._arrow_move_observers[view_name]" in body


def test_second_click_clears_preview_then_draws():
    src = _src()
    fn = src.find("def _handle_arrow_click")
    assert fn != -1
    body = src[fn:fn + 2400]
    # the preview is removed BEFORE the final arrow is committed
    clear = body.find("_clear_arrow_preview(view_name)")
    create = body.find("_create_arrow_actor(view_name, tail, world)")
    assert clear != -1 and create != -1 and clear < create


def test_final_arrow_renders_immediately():
    src = _src()
    fn = src.find("def _create_arrow_actor")
    assert fn != -1
    body = src[fn:fn + 1200]
    assert "_render_immediately(view_name)" in body          # instant final paint
    assert "if _MPR_ANNOTATION_SMOOTH:" in body              # legacy keeps batched request


def test_teardown_removes_move_observers_and_preview():
    src = _src()
    fn = src.find("def _deactivate_arrow_placement")
    assert fn != -1
    body = src[fn:fn + 900]
    assert "self._arrow_move_observers" in body
    assert "self._clear_arrow_preview()" in body


def test_preview_is_throttled():
    src = _src()
    fn = src.find("def _handle_arrow_move")
    assert fn != -1
    body = src[fn:fn + 1500]
    # 2px display-move threshold (smoothness) before re-compositing
    assert re.search(r"abs\(x - last\[0\]\) < 2 and abs\(y - last\[1\]\) < 2", body)
    # geometry-irrelevant: a no-op unless the arrow tool is armed with a pending tail
    assert "self.current_tool != 'arrow'" in body
    assert "self._arrow_pending_tail.get(view_name)" in body


# ----------------------------------------------------------------------------
# Behavioral — preview create/update + the 2px throttle, against a fake viewer
# (no real VTK render window; the VTK helpers are stubbed).
# ----------------------------------------------------------------------------
def test_arrow_preview_behavioral():
    pytest.importorskip("vtk")
    try:
        from modules.mpr.zeta_mpr import mpr_measurement_tools as MT
    except Exception as exc:  # pragma: no cover - import env dependent
        pytest.skip(f"mpr_measurement_tools import unavailable: {exc}")
    if not getattr(MT, "_MPR_ANNOTATION_SMOOTH", False):
        pytest.skip("AIPACS_MPR_ANNOTATION_SMOOTH disabled in this env")

    class FakeRW:
        def __init__(self):
            self.renders = 0

        def Render(self):
            self.renders += 1

    class FakeRenderer:
        def __init__(self, rw):
            self._rw = rw
            self.added = []
            self.removed = []

        def GetRenderWindow(self):
            return self._rw

        def AddActor2D(self, a):
            self.added.append(a)

        def RemoveActor2D(self, a):
            self.removed.append(a)

    class FakeInteractor:
        def __init__(self):
            self.pos = (0, 0)

        def GetEventPosition(self):
            return self.pos

    class FakeWidget:
        def __init__(self, rw, inter):
            self._rw = rw
            self._inter = inter

        def GetRenderWindow(self):
            return _RWWithInteractor(self._rw, self._inter)

    class _RWWithInteractor:
        def __init__(self, rw, inter):
            self._rw = rw
            self._inter = inter

        def GetInteractor(self):
            return self._inter

    class FakeCoord:
        def __init__(self):
            self.value = None

        def SetValue(self, *v):
            self.value = v

    class FakeLeader:
        def __init__(self):
            self._p1 = FakeCoord()
            self._p2 = FakeCoord()

        def GetPositionCoordinate(self):
            return self._p1

        def GetPosition2Coordinate(self):
            return self._p2

    rw = FakeRW()
    rend = FakeRenderer(rw)
    inter = FakeInteractor()
    widget = FakeWidget(rw, inter)

    fake = types.SimpleNamespace(
        current_tool='arrow',
        _arrow_pending_tail={'axial': (1.0, 2.0, 3.0)},
        _arrow_preview_actor={},
        _arrow_preview_last_xy={},
        mpr_viewer=types.SimpleNamespace(viewers={'axial': {'widget': widget, 'renderer': rend}}),
    )
    fake._display_to_world = lambda r, x, y: (float(x), float(y), 0.0)
    fake._make_arrow_leader = lambda p1, p2: FakeLeader()

    move = MT.MPRMeasurementTools._handle_arrow_move.__get__(fake)

    # First move with a pending tail -> creates the preview, renders once.
    inter.pos = (100, 100)
    move('axial')
    assert 'axial' in fake._arrow_preview_actor
    assert len(rend.added) == 1
    assert rw.renders == 1

    # A sub-2px nudge is throttled -> no extra actor, no extra render.
    inter.pos = (101, 101)
    move('axial')
    assert len(rend.added) == 1
    assert rw.renders == 1

    # A real move -> updates the SAME preview actor (no new add), renders again.
    inter.pos = (140, 160)
    move('axial')
    assert len(rend.added) == 1          # reused, not re-created
    assert rw.renders == 2
    assert fake._arrow_preview_actor['axial']._p2.value == (140.0, 160.0, 0.0)

    # Clearing removes the actor and forgets the throttle position.
    clear = MT.MPRMeasurementTools._clear_arrow_preview.__get__(fake)
    clear('axial')
    assert 'axial' not in fake._arrow_preview_actor
    assert len(rend.removed) == 1

    # No pending tail -> the move handler is a no-op (geometry-irrelevant).
    fake._arrow_pending_tail = {}
    rw.renders = 0
    inter.pos = (200, 200)
    move('axial')
    assert rw.renders == 0
