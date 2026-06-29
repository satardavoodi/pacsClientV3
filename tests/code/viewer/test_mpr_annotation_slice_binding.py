"""Guard: MPR annotations persist per slice and restore on scroll-back (48272, 2026-06-28).

Root cause of "draw a 2nd ruler → both disappear" + "scroll away and back → gone":
`refresh_slice_visibility` decided which slice an annotation belongs to by reading
the 2D widget geometry (`vtkDistanceRepresentation2D.GetPoint1WorldPosition()[look_axis]`),
whose through-plane component is NOT reliably the reslice-plane position. So
annotations ON the current slice were wrongly hidden.

Fix: capture the reslice coordinate AT CREATION (`current_position[look_axis]` when
the measurement completes) into `_annotation_slice_coord[id(widget)]`, and bind on
that stored value. Multiple measurements on one slice stay visible together, and
scrolling away + back restores them. (Arrows already stored their world point.)

Source-pins + a behavioral test of the slice-binding with the real methods.
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


def test_stored_slice_map_and_binding():
    src = _src()
    assert "self._annotation_slice_coord = {}" in src
    # _annotation_look_coord prefers the stored slice over the 2D-widget geometry
    fn = src.find("def _annotation_look_coord")
    body = src[fn:fn + 900]
    assert "stored = self._annotation_slice_coord.get(id(item))" in body
    assert "if stored is not None:" in body and "return float(stored)" in body


def test_slice_captured_at_completion_before_refresh():
    src = _src()
    fn = src.find("def _do_single_use_auto_exit")
    body = src[fn:fn + 4200]
    cap = body.find("self._annotation_slice_coord[id(items[-1])]")
    ref = body.find("self.refresh_slice_visibility(completed_view)")
    assert cap != -1 and ref != -1
    # the slice must be recorded BEFORE the refresh so the binding uses it
    assert cap < ref
    assert "current_position[_la]" in body


def test_stored_slice_cleaned_on_clear_and_delete():
    src = _src()
    assert "self._annotation_slice_coord.pop(id(widget), None)" in src


def test_slice_binding_keeps_multiple_then_restores_behavioral():
    pytest.importorskip("vtk")
    try:
        from modules.mpr.zeta_mpr import mpr_measurement_tools as MT
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"mpr_measurement_tools import unavailable: {exc}")

    class W:
        """Fake VTK distance widget (On/Off only)."""
        def __init__(self):
            self.on = None

        def On(self):
            self.on = True

        def Off(self):
            self.on = False

    r1, r2 = W(), W()  # two rulers drawn on the SAME slice (look-axis coord 50.0)

    class FakeViewer:
        def __init__(self):
            self.current_position = [0.0, 0.0, 50.0]
            self.spacing = [1.0, 1.0, 1.0]

        def _view_axes(self, vn):
            return (2,)   # axial look axis = 2 (z)

        def _request_render(self, vn):
            pass

    empty = {'ruler': [], 'angle': [], 'caption': [], 'arrow': []}
    fake = types.SimpleNamespace(
        _slice_bound_enabled=True,
        active_tools={
            'axial': {'ruler': [r1, r2], 'angle': [], 'caption': [], 'arrow': []},
            'sagittal': dict(empty),
            'coronal': dict(empty),
        },
        _annotation_visible_cache={},
        _annotation_slice_coord={id(r1): 50.0, id(r2): 50.0},
        mpr_viewer=FakeViewer(),
    )
    fake._annotation_look_coord = MT.MPRMeasurementTools._annotation_look_coord.__get__(fake)
    fake._apply_annotation_visibility = MT.MPRMeasurementTools._apply_annotation_visibility.__get__(fake)
    refresh = MT.MPRMeasurementTools.refresh_slice_visibility.__get__(fake)

    # On the slice both were drawn on → BOTH visible together (criterion 5).
    refresh('axial')
    assert r1.on is True and r2.on is True

    # Scroll away → both hidden (slice-bound).
    fake.mpr_viewer.current_position[2] = 60.0
    refresh('axial')
    assert r1.on is False and r2.on is False

    # Scroll BACK to the same slice → both restored (criterion 7).
    fake.mpr_viewer.current_position[2] = 50.0
    refresh('axial')
    assert r1.on is True and r2.on is True
