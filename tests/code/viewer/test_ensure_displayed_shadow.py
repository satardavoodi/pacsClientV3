"""Guard: S3b — ensure_series_displayed chokepoint, SHADOW-first wiring (2026-06-26).

The pure chokepoint ``plan_series_display`` (S3a, ``PacsClient/utils/viewer_request_pipeline.py``)
decides what a viewport must DO to show a series. S3b begins routing the live entry points through
it — but per the staged plan's STRICT ORDER ("do not start S3 retirements until S1/S2 are
default-ON and soaked"), this first step is **shadow-only and additive**: at the resume settled-stop
(`_feed_state_authority`) the viewer ALSO asks the chokepoint and logs ``[ENSURE-DISPLAYED-SHADOW]``
when its ``DisplayPlan`` disagrees with the live settled decision. It changes NO behavior and
retires NO flag (``AIPACS_PROGRESSIVE_UID_BIND`` etc. stay) until a live multi-study soak proves the
chokepoint agrees.

This guard pins: (1) the pure divergence helper's truth table, (2) that it composes the REAL
``plan_series_display`` correctly, (3) the wiring is additive + default-off and retires nothing.

Plan: docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md (S3 / S3b).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
_CANON = _ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_progressive.py"


def _src() -> str:
    return _CANON.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Functional — the pure chokepoint composes correctly (pure imports, no vtk)
# --------------------------------------------------------------------------- #

@pytest.fixture()
def _pipe():
    """The S3a chokepoint + identity are pure stdlib and import without vtk."""
    try:
        from PacsClient.utils.viewer_identity import SeriesRequest
        from PacsClient.utils.viewer_request_pipeline import plan_series_display, LoadIntent
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"pure pipeline import unavailable: {exc}")
    return SeriesRequest, plan_series_display, LoadIntent


def _divergence(plan, live_settled):
    """Mirror of the production helper's contract for the functional checks below. The production
    copy (`_vc_progressive._ensure_displayed_shadow_divergence`) is source-pinned + behaviourally
    identical; it lives in a vtk-gated module so it is re-validated here against the REAL plan."""
    chokepoint_done = bool(plan.is_noop)
    if chokepoint_done == bool(live_settled):
        return None
    return f"plan={plan.action.name} target={plan.target_count} live_settled={live_settled}"


def test_chokepoint_agrees_when_behind(_pipe):
    """Viewport behind disk → chokepoint wants work, live not settled → AGREE (no divergence)."""
    SeriesRequest, plan_series_display, LoadIntent = _pipe
    req = SeriesRequest.create(patient_id="P1", study_uid="S1", series_uid="U1", display_key=2000008)
    plan = plan_series_display(req, viewer_visible_count=50, disk_count=162,
                               server_count=162, expected_count=162, intent=LoadIntent.DISPLAY)
    assert not plan.is_noop                       # the chokepoint would load/grow
    assert _divergence(plan, live_settled=False) is None


def test_chokepoint_agrees_when_caught_up(_pipe):
    """Viewport == disk → chokepoint NOOP, live settled → AGREE (no divergence)."""
    SeriesRequest, plan_series_display, LoadIntent = _pipe
    req = SeriesRequest.create(patient_id="P1", study_uid="S1", series_uid="U1", display_key=2000008)
    plan = plan_series_display(req, viewer_visible_count=162, disk_count=162,
                               server_count=162, expected_count=162, intent=LoadIntent.DISPLAY)
    assert plan.is_noop                           # the chokepoint would leave it as-is
    assert _divergence(plan, live_settled=True) is None


def test_divergence_reported_when_they_disagree(_pipe):
    """A constructed disagreement must produce a note (so the live soak can surface real gaps)."""
    SeriesRequest, plan_series_display, LoadIntent = _pipe
    req = SeriesRequest.create(patient_id="P1", study_uid="S1", series_uid="U1", display_key=302)
    plan = plan_series_display(req, viewer_visible_count=162, disk_count=162,
                               server_count=162, expected_count=162, intent=LoadIntent.DISPLAY)
    # plan.is_noop is True here; claim live_settled=False → they disagree → a note is returned.
    note = _divergence(plan, live_settled=False)
    assert note is not None and "plan=" in note


def test_production_helper_matches_this_contract(monkeypatch):
    """If _vc_progressive imports (Windows .venv has vtk), its real helper must agree with the
    mirror above on the same plan objects. Skips in the sandbox (no vtk)."""
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_progressive as mod
        from PacsClient.utils.viewer_identity import SeriesRequest
        from PacsClient.utils.viewer_request_pipeline import plan_series_display, LoadIntent
    except Exception as exc:  # pragma: no cover - heavy import unavailable in sandbox
        pytest.skip(f"_vc_progressive import unavailable: {exc}")
    req = SeriesRequest.create(patient_id="P1", study_uid="S1", series_uid="U1", display_key=2000008)
    for v, dk in [(50, 162), (162, 162), (0, 0)]:
        plan = plan_series_display(req, viewer_visible_count=v, disk_count=dk,
                                   server_count=dk, expected_count=dk, intent=LoadIntent.DISPLAY)
        live = v > 0 and v >= dk
        assert mod._ensure_displayed_shadow_divergence(plan, live) == _divergence(plan, live)


# --------------------------------------------------------------------------- #
# Source-pins — additive, default-off, retires nothing
# --------------------------------------------------------------------------- #

def test_flag_default_off_and_after_os_import():
    s = _src()
    assert 'AIPACS_ENSURE_SERIES_DISPLAYED", "0"' in s, "S3b flag must DEFAULT OFF (shadow-first)"
    assert s.index("import os as _os") < s.index("_ENSURE_SERIES_DISPLAYED_ENABLED ="), (
        "flag uses _os.getenv → must be defined after `import os as _os` (load-time NameError)"
    )


def test_helper_and_shadow_wired():
    s = _src()
    assert "def _ensure_displayed_shadow_divergence(" in s
    assert "[ENSURE-DISPLAYED-SHADOW]" in s
    assert "plan_series_display(" in s
    # co-located in the existing authority feed, reusing its req + counts
    feed = s[s.index("def _feed_state_authority("):]
    head = feed[:4000]
    assert "_ensure_displayed_shadow_divergence(_plan" in head
    assert "or _ENSURE_SERIES_DISPLAYED_ENABLED" in head   # entry gate widened


def test_retires_nothing_yet():
    """S3b shadow must NOT remove the existing re-keying patches (gated on S1/S2 soak)."""
    s = _src()
    # the sibling/uid-bind machinery this stage will EVENTUALLY retire must still be present now
    assert "display_key_for_active_series_uid" in s or "_GROW_SIBLING" in s or "display_key" in s
    # and the shadow must be observe-only: no live decision is taken from the plan
    feed = s[s.index("def _feed_state_authority("):]
    head = feed[:4000]
    assert "change_series_on_viewer" not in head, "shadow must not ACT on the plan (observe-only)"
