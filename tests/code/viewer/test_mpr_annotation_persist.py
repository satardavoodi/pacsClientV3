"""Guard: MPR annotations persist — drawing a 2nd measurement keeps the 1st (2026-06-28).

Root cause: the single-use auto-exit (`_do_single_use_auto_exit`) removed EVERY
ruler/angle widget on the non-completed views — including PREVIOUSLY-COMPLETED
measurements. So measuring on a 2nd pane wiped the measurement on the 1st pane
("only the last annotation remains visible"). The MPR DOES store annotations in a
collection (`active_tools[view][tool]` lists); the destruction was the bug.

Fix: auto-exit removes ONLY the current activation's EMPTY placement widgets on the
other views (tracked per-view in `_placement_widgets`), never a finished
measurement. UNIFIED 2026-06-28: the `AIPACS_MPR_ANNOTATION_PERSIST` flag + its
destructive legacy branch were retired — this is the only path.

Source-pins + a behavioral cross-view test (no real VTK).
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


def test_persist_is_unconditional_no_flag():
    # Unified 2026-06-28: the AIPACS_MPR_ANNOTATION_PERSIST flag + its destructive
    # legacy branch were RETIRED — keeping multiple measurements visible is now the
    # only path (the bug can no longer be re-enabled).
    src = _src()
    assert "AIPACS_MPR_ANNOTATION_PERSIST" not in src
    assert "_MPR_ANNOTATION_PERSIST" not in src
    assert "Legacy (destructive)" not in src


def test_placement_widgets_tracked_on_activation():
    src = _src()
    assert "self._placement_widgets = {}" in src
    # both ruler and angle record THIS activation's placement widget
    ruler = src.find("def _activate_ruler_on_view")
    assert "self._placement_widgets[view_name] = distance_widget" in src[ruler:ruler + 2800]
    angle = src.find("def _activate_angle_on_view")
    assert "self._placement_widgets[view_name] = angle_widget" in src[angle:angle + 2800]


def test_auto_exit_removes_only_this_activation_empties():
    src = _src()
    fn = src.find("def _do_single_use_auto_exit")
    assert fn != -1
    body = src[fn:fn + 2200]
    # removes ONLY the tracked placement widget per other view — now unconditional
    assert "w = self._placement_widgets.get(vn)" in body
    assert "self._placement_widgets.clear()" in body
    # the destructive legacy branch + its flag are gone
    assert "Legacy (destructive)" not in body
    assert "_MPR_ANNOTATION_PERSIST" not in body


def test_cross_view_completed_measurement_survives_behavioral():
    """Draw ruler 1 on axial (completed), then ruler 2 on sagittal — ruler 1 must
    survive. Binds the real auto-exit to a fake self (no VTK)."""
    try:
        from modules.mpr.zeta_mpr import mpr_measurement_tools as MT
    except Exception as exc:  # pragma: no cover - import env dependent
        pytest.skip(f"mpr_measurement_tools import unavailable: {exc}")

    class FakeWidget:
        def __init__(self, name):
            self.name = name
            self.off_called = False

        def Off(self):
            self.off_called = True

    r1_done = FakeWidget("r1_done")   # ruler 1, completed on axial earlier
    r2_ax = FakeWidget("r2_ax")       # this activation's EMPTY placement on axial
    r2_sag = FakeWidget("r2_sag")     # this activation's widget on sagittal (being completed)
    r2_cor = FakeWidget("r2_cor")     # this activation's EMPTY placement on coronal

    active_tools = {
        'axial': {'ruler': [r1_done, r2_ax], 'angle': [], 'caption': [], 'arrow': []},
        'sagittal': {'ruler': [r2_sag], 'angle': [], 'caption': [], 'arrow': []},
        'coronal': {'ruler': [r2_cor], 'angle': [], 'caption': [], 'arrow': []},
    }

    fake = types.SimpleNamespace(
        _placement_widgets={'axial': r2_ax, 'sagittal': r2_sag, 'coronal': r2_cor},
        active_tools=active_tools,
        _placement_clicks={('sagittal', 'ruler'): 2},
        current_tool='ruler',
        on_auto_exit=None,
        _auto_exit_in_progress=True,
        mpr_viewer=types.SimpleNamespace(_render_immediately=lambda v: None),
    )
    fake._deactivate_arrow_placement = lambda: None
    fake.refresh_slice_visibility = lambda v=None: None
    fake._apply_annotation_visibility = lambda item, tt, vis: None

    MT.MPRMeasurementTools._do_single_use_auto_exit.__get__(fake)('sagittal', 'ruler')

    # The previously-completed measurement on axial SURVIVES, untouched.
    assert r1_done in active_tools['axial']['ruler']
    assert r1_done.off_called is False
    # This activation's EMPTY placement widgets on the other views are dropped.
    assert r2_ax not in active_tools['axial']['ruler'] and r2_ax.off_called is True
    assert r2_cor not in active_tools['coronal']['ruler'] and r2_cor.off_called is True
    # The just-completed measurement on the completed view is kept.
    assert active_tools['sagittal']['ruler'] == [r2_sag]
    assert r2_sag.off_called is False
    # Tracking dict cleared for the next activation.
    assert fake._placement_widgets == {}
