"""Guards for slice-bound MPR annotations (2026-06-09).

A measurement drawn on one MPR reslice position must be visible ONLY there:
hidden when scrolling to other slices, restored (not lost) when scrolling back.
Mirrors the 2D viewer's per-slice widgets, adapted to MPR's CONTINUOUS reslice
(bind to the look-axis world coordinate; visible when the pane's current
through-plane position is within half a slice of it).
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture()
def tools():
    pytest.importorskip("vtk")
    from modules.mpr.zeta_mpr.mpr_measurement_tools import MPRMeasurementTools

    class _StubViewer:
        # axial look-axis = 2 (legacy), spacing along it = 2.0 → tol = 1.0
        _LEGACY = {'axial': (2, 0, 1), 'sagittal': (0, 1, 2), 'coronal': (1, 0, 2)}

        def __init__(self):
            self.current_position = [0.0, 0.0, 0.0]
            self.spacing = (1.0, 1.0, 2.0)
            self.viewers = {}
            self.renders = []

        def _view_axes(self, view_name):
            return self._LEGACY[view_name]

        def _request_render(self, vn):
            self.renders.append(vn)

    mt = MPRMeasurementTools(_StubViewer())
    mt._slice_bound_enabled = True   # force on regardless of env
    return mt


class _FakeRep:
    def __init__(self, world):
        self._w = world

    def GetPoint1WorldPosition(self, p):
        p[0], p[1], p[2] = self._w

    def GetCenterWorldPosition(self, p):
        p[0], p[1], p[2] = self._w

    def GetAnchorPosition(self, p):
        p[0], p[1], p[2] = self._w


class _FakeWidget:
    def __init__(self, world):
        self._rep = _FakeRep(world)
        self.on_calls = 0
        self.off_calls = 0
        self.visible = True   # VTK widgets begin On()

    def GetRepresentation(self):
        return self._rep

    def On(self):
        self.on_calls += 1
        self.visible = True

    def Off(self):
        self.off_calls += 1
        self.visible = False


class _FakeActor:
    def __init__(self):
        self.vis = 1

    def SetVisibility(self, v):
        self.vis = int(v)


def test_ruler_visible_only_on_its_slice(tools):
    mt = tools
    # ruler drawn on the axial plane at world z = 10.0
    w = _FakeWidget((5.0, 5.0, 10.0))
    mt.active_tools['axial']['ruler'] = [w]

    # on its slice → visible
    mt.mpr_viewer.current_position[2] = 10.0
    mt.refresh_slice_visibility('axial')
    assert w.visible is True

    # scroll one slice away (z=12, > tol 1.0) → hidden
    mt.mpr_viewer.current_position[2] = 12.0
    mt.refresh_slice_visibility('axial')
    assert w.visible is False
    assert w.off_calls >= 1

    # scroll back → restored (not lost)
    mt.mpr_viewer.current_position[2] = 10.0
    mt.refresh_slice_visibility('axial')
    assert w.visible is True


def test_refresh_is_change_only(tools):
    mt = tools
    w = _FakeWidget((0.0, 0.0, 4.0))
    mt.active_tools['axial']['ruler'] = [w]
    mt.mpr_viewer.current_position[2] = 4.0
    mt.refresh_slice_visibility('axial')
    on_after_first = w.on_calls
    # refreshing again at the SAME position must not re-toggle (cheap/no flicker)
    mt.refresh_slice_visibility('axial')
    mt.refresh_slice_visibility('axial')
    assert w.on_calls == on_after_first


def test_arrow_actor_visibility_bound_to_slice(tools):
    mt = tools
    actor = _FakeActor()
    mt.active_tools['axial']['arrow'] = [{'actor': actor, 'p1': (1.0, 1.0, 20.0), 'p2': (2.0, 2.0, 20.0)}]

    mt.mpr_viewer.current_position[2] = 20.0
    mt.refresh_slice_visibility('axial')
    assert actor.vis == 1

    mt.mpr_viewer.current_position[2] = 30.0
    mt.refresh_slice_visibility('axial')
    assert actor.vis == 0

    mt.mpr_viewer.current_position[2] = 20.0
    mt.refresh_slice_visibility('axial')
    assert actor.vis == 1


def test_two_rulers_on_different_slices_are_independent(tools):
    mt = tools
    w_lo = _FakeWidget((0.0, 0.0, 0.0))    # slice z=0
    w_hi = _FakeWidget((0.0, 0.0, 50.0))   # slice z=50
    mt.active_tools['axial']['ruler'] = [w_lo, w_hi]

    mt.mpr_viewer.current_position[2] = 0.0
    mt.refresh_slice_visibility('axial')
    assert w_lo.visible is True and w_hi.visible is False

    mt.mpr_viewer.current_position[2] = 50.0
    mt.refresh_slice_visibility('axial')
    assert w_lo.visible is False and w_hi.visible is True


def test_gate_off_leaves_annotations_untouched(tools):
    mt = tools
    mt._slice_bound_enabled = False
    w = _FakeWidget((0.0, 0.0, 10.0))
    mt.active_tools['axial']['ruler'] = [w]
    mt.mpr_viewer.current_position[2] = 999.0  # far away
    mt.refresh_slice_visibility('axial')
    # gate off → no toggling at all (legacy always-visible behaviour)
    assert w.off_calls == 0 and w.visible is True


def test_synchronize_oblique_views_calls_refresh():
    src = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
           / "_mpr_crosshair_state.py").read_text(encoding="utf-8", errors="ignore")
    start = src.index("def _synchronize_oblique_views")
    body = src[start:start + 1500]
    assert "refresh_slice_visibility()" in body
    assert "measurement_tools" in body


def test_completion_force_shows_new_measurement_and_paints(tools):
    """The SECOND-measurement fix: on completion the just-drawn measurement is
    force-shown (even if a tiny reslice drift would fail the tolerance) and the
    pane is painted immediately — so a 2nd/Nth ruler reliably appears. The
    earlier hidden measurement on another slice stays hidden."""
    mt = tools
    rendered = []
    mt.mpr_viewer._render_immediately = lambda vn: rendered.append(vn)
    mt.on_auto_exit = lambda: None

    m1 = _FakeWidget((0.0, 0.0, 0.0))    # earlier measurement on slice z=0
    m2 = _FakeWidget((0.0, 0.0, 50.0))   # just-completed measurement (last item)
    mt.active_tools['axial']['ruler'] = [m1, m2]
    # we are on slice ~51.5 — a small drift from m2's 50 that EXCEEDS tol(=1.0),
    # so the plain slice check would wrongly hide the just-drawn m2.
    mt.mpr_viewer.current_position[2] = 51.5
    mt._annotation_visible_cache[id(m1)] = False
    m1.visible = False

    mt._do_single_use_auto_exit('axial', 'ruler')

    assert m2.visible is True          # force-shown despite the drift
    assert m1.visible is False         # off-slice measurement stays hidden
    assert 'axial' in rendered         # pane painted immediately
    assert mt.current_tool is None
