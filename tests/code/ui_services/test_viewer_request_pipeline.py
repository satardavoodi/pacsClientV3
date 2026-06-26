"""S3a contract tests for the ensure_series_displayed chokepoint decision core
(``PacsClient/utils/viewer_request_pipeline.py``). Pure + unwired in S3a; these lock the
decision + request-scoping contract before any entry point routes through it (S3b).

Plan: docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md (S3).
"""
from PacsClient.utils.viewer_identity import SeriesRequest, ViewerHandle
from PacsClient.utils.series_display_state import DisplayAction
from PacsClient.utils.viewer_request_pipeline import (
    plan_series_display, LoadIntent, DisplayPlan,
)


def _req(series="U1", key="1000500", handle=None):
    return SeriesRequest.create(
        patient_id="P1", study_uid="S1", series_uid=series, display_key=key,
        viewer_handle=handle,
    )


def test_grow_in_place_when_behind_with_lazy():
    p = plan_series_display(_req(), viewer_visible_count=4, disk_count=10,
                            expected_count=10, has_lazy_loader=True)
    assert p.action == DisplayAction.GROW_IN_PLACE
    assert p.needs_work and not p.is_noop
    assert p.target_count == 10
    assert p.request.series_uid == "U1"


def test_refresh_rebuild_when_behind_no_lazy():
    p = plan_series_display(_req(), viewer_visible_count=4, disk_count=10,
                            expected_count=10, has_lazy_loader=False)
    assert p.action == DisplayAction.REFRESH_AND_REBUILD
    assert p.needs_work


def test_await_download_when_incomplete():
    p = plan_series_display(_req(), viewer_visible_count=8, disk_count=8, expected_count=20)
    assert p.action == DisplayAction.AWAIT_DOWNLOAD
    assert p.needs_work
    assert p.target_count == 20


def test_noop_when_full():
    p = plan_series_display(_req(), viewer_visible_count=10, disk_count=10, expected_count=10)
    assert p.action == DisplayAction.NOOP
    assert p.is_noop and not p.needs_work


def test_skip_downgrade_when_viewer_ahead():
    p = plan_series_display(_req(), viewer_visible_count=99, disk_count=8, expected_count=8)
    assert p.action == DisplayAction.SKIP_DOWNGRADE
    assert p.is_noop


def test_rebuild_when_requested():
    p = plan_series_display(_req(), viewer_visible_count=5, disk_count=10,
                            expected_count=10, rebuild_needed=True)
    assert p.action == DisplayAction.REBUILD
    assert p.needs_work


def test_identity_and_intent_carried():
    h = ViewerHandle.new(slot_hint=0)
    p = plan_series_display(_req(handle=h), viewer_visible_count=10, disk_count=10,
                            expected_count=10, intent="preview")
    assert p.request.viewer_handle == h
    assert p.intent == LoadIntent.PREVIEW


def test_supersedes_is_request_scoped():
    """The request-scoped cancellation signal that replaces the grid-index token race:
    a plan supersedes a prior one ONLY for the same viewport (ViewerHandle) + a different series."""
    h = ViewerHandle.new()
    pa = plan_series_display(_req(series="U1", handle=h), viewer_visible_count=1,
                             disk_count=1, expected_count=1)
    pb = plan_series_display(_req(series="U2", handle=h), viewer_visible_count=1,
                             disk_count=1, expected_count=1)
    assert pb.supersedes(pa)            # same viewport, different series → supersedes
    assert not pb.supersedes(pb)        # same series → not a supersession
    pc = plan_series_display(_req(series="U1", handle=ViewerHandle.new()),
                             viewer_visible_count=1, disk_count=1, expected_count=1)
    assert not pc.supersedes(pa)        # different viewport → never supersedes another
