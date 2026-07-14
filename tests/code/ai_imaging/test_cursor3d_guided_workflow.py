# -*- coding: utf-8 -*-
"""Guard: the 3D Cursor guided workflow (Eagle Eye / Mammography).

The old flow ran two dialogs ("viewer 1 / viewer 2") and asked for a pectoral line
on BOTH views — but the correlation only ever consumes the **MLO** pectoral angle
(`correlator._build_geometry` passes `pectoral_angle_deg` only when
`view.view_position == 'MLO'`), so the CC line was collected and discarded. The
guided flow asks for exactly what the math uses, in that order:

    1. nipple_mlo   (1 click)
    2. nipple_cc    (1 click)
    3. pectoral_mlo (2 clicks: superior → inferior)

These tests pin the ORDER, the click counts, the wrong-view rejection, Back/undo,
and the fallback-to-legacy when the views can't be identified. The state machine is
pure (no Qt/VTK), so it runs headless.
"""

import inspect
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.ai_imaging.ai_module_ui.cursor_3d.guided_workflow import (  # noqa: E402
    Cursor3DFlow,
    ViewSlot,
    guided_flow_enabled,
    plan_cursor3d_steps,
)


def _slots(first="MLO", second="CC", lat="R"):
    return [
        ViewSlot(viewer_index=0, laterality=lat, view_position=first),
        ViewSlot(viewer_index=1, laterality=lat, view_position=second),
    ]


# ---------------------------------------------------------------------------
# 1. The plan matches the calculation logic
# ---------------------------------------------------------------------------

def test_step_order_is_nipple_mlo_then_nipple_cc_then_pectoral_mlo():
    steps = plan_cursor3d_steps(_slots("MLO", "CC"))
    assert [s.key for s in steps] == ["nipple_mlo", "nipple_cc", "pectoral_mlo"]
    assert [s.clicks for s in steps] == [1, 1, 2]
    assert [s.kind for s in steps] == ["point", "point", "line"]


def test_no_cc_pectoral_step_is_requested():
    """The CC pectoral angle is never used by the correlator — do not ask for it."""
    steps = plan_cursor3d_steps(_slots("MLO", "CC"))
    assert not any(s.kind == "line" and s.view_position == "CC" for s in steps)
    line_steps = [s for s in steps if s.kind == "line"]
    assert len(line_steps) == 1 and line_steps[0].view_position == "MLO"


def test_steps_target_the_viewer_actually_showing_the_view():
    """Whichever viewer holds the MLO must be the one the MLO steps point at."""
    steps = plan_cursor3d_steps(_slots("CC", "MLO"))  # CC in viewer 0, MLO in viewer 1
    by_key = {s.key: s for s in steps}
    assert by_key["nipple_cc"].viewer_index == 0
    assert by_key["nipple_mlo"].viewer_index == 1
    assert by_key["pectoral_mlo"].viewer_index == 1
    # order is still MLO nipple first
    assert [s.key for s in steps][0] == "nipple_mlo"


def test_every_step_names_the_view_the_tool_and_the_reason():
    for s in plan_cursor3d_steps(_slots()):
        assert s.view_label and s.view_label != "View"
        assert s.tool, "each step must state which tool is active"
        assert s.instruction, "each step must say what to do"
        assert s.why, "each step must say what the value is used for"


@pytest.mark.parametrize("slots", [
    [],
    [ViewSlot(0, "R", "MLO")],                                   # only one view
    [ViewSlot(0, "R", "CC"), ViewSlot(1, "R", "CC")],            # two CCs
    [ViewSlot(0, "R", "MLO"), ViewSlot(1, "R", "")],             # unknown view
    [ViewSlot(0, "R", "MLO"), ViewSlot(1, "R", "XCCL")],         # not CC/MLO
])
def test_unidentifiable_views_fall_back_to_legacy(slots):
    """Never GUESS which view is which — a wrong nipple silently corrupts the math."""
    assert plan_cursor3d_steps(slots) is None


# ---------------------------------------------------------------------------
# 2. The flow state machine
# ---------------------------------------------------------------------------

def _flow():
    return Cursor3DFlow(steps=plan_cursor3d_steps(_slots("MLO", "CC")))


def test_flow_progress_and_completion():
    f = _flow()
    assert f.total_steps == 3
    assert f.progress_text() == "Step 1 of 3"
    assert f.step_state(0) == "current" and f.step_state(2) == "pending"

    assert f.click(0, 100, 200)["status"] == "step_done"      # nipple MLO (viewer 0)
    assert f.progress_text() == "Step 2 of 3"
    assert f.step_state(0) == "done"

    assert f.click(1, 300, 400)["status"] == "step_done"      # nipple CC (viewer 1)
    assert f.clicks_remaining() == 2                          # pectoral line needs 2

    assert f.click(0, 10, 10)["status"] == "need_more_clicks"
    assert f.clicks_remaining() == 1
    assert f.click(0, 60, 90)["status"] == "flow_done"

    assert f.is_complete
    assert f.points_for("nipple_mlo") == [(100.0, 200.0)]
    assert f.points_for("nipple_cc") == [(300.0, 400.0)]
    assert f.points_for("pectoral_mlo") == [(10.0, 10.0), (60.0, 90.0)]


def test_click_on_the_wrong_viewer_is_rejected_not_recorded():
    f = _flow()
    evt = f.click(1, 50, 50)          # step 1 wants viewer 0 (MLO)
    assert evt["status"] == "wrong_view"
    assert evt["expected_view"] == "R-MLO"
    assert f.points_for("nipple_mlo") == []
    assert f.current_index == 0       # flow did not advance


def test_back_undoes_partial_line_then_previous_steps():
    f = _flow()
    f.click(0, 1, 1)                  # nipple MLO done
    f.click(1, 2, 2)                  # nipple CC done
    f.click(0, 3, 3)                  # first pectoral point (partial)

    undone = f.back()                 # drops the partial line clicks
    assert undone.key == "pectoral_mlo"
    assert f.points_for("pectoral_mlo") == []
    assert f.current_index == 2       # still on the pectoral step

    undone = f.back()                 # re-opens the CC nipple step
    assert undone.key == "nipple_cc"
    assert f.current_index == 1
    assert f.points_for("nipple_cc") == []

    undone = f.back()
    assert undone.key == "nipple_mlo"
    assert f.current_index == 0
    assert f.back() is None           # nothing left to undo


def test_clicks_after_completion_are_ignored():
    f = _flow()
    f.click(0, 1, 1); f.click(1, 2, 2); f.click(0, 3, 3); f.click(0, 4, 4)
    assert f.is_complete
    assert f.click(0, 9, 9)["status"] == "ignored"


# ---------------------------------------------------------------------------
# 3. Flag + wiring
# ---------------------------------------------------------------------------

def test_guided_flow_is_default_on(monkeypatch):
    monkeypatch.delenv("AIPACS_CURSOR3D_GUIDED", raising=False)
    assert guided_flow_enabled() is True


def test_kill_switch_restores_legacy_flow(monkeypatch):
    monkeypatch.setenv("AIPACS_CURSOR3D_GUIDED", "0")
    assert guided_flow_enabled() is False


def test_imaging_tab_uses_guided_flow_and_keeps_legacy_fallback():
    from modules.ai_imaging.ai_module_ui.service_tab.imaging_tab import ImagingToolsTab

    src = inspect.getsource(ImagingToolsTab._on_3d_cursor_clicked)
    assert "guided_flow_enabled" in src
    assert "Cursor3DGuidedPicker" in src
    assert "NipplePickerController" in src, "the legacy flow must remain as the fallback"

    done = inspect.getsource(ImagingToolsTab._on_guided_cursor3d_done)
    assert "pectoral_line1=pectoral_mlo" in done
    assert "pectoral_line2=None" in done, "the CC pectoral angle is not used by the correlator"


def test_correlator_only_consumes_the_mlo_pectoral_angle():
    """The premise of the redesign — pin it so a refactor can't silently break it."""
    from modules.ai_imaging.ai_module_ui.cursor_3d import correlator as corr

    src = inspect.getsource(corr.CursorCorrelator3D._build_geometry)
    assert "if view.view_position == 'MLO' else None" in src
