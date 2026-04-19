"""B4.3 lifecycle state-map tests for progressive display.

These tests validate the explicit state transitions introduced alongside
legacy guard sets. They intentionally use lightweight objects so they can run
fast and verify helper compatibility with bound-mixin style tests.
"""

from types import SimpleNamespace

from PacsClient.pacs.patient_tab.ui.patient_ui._vc_progressive import (
    _VCProgressiveMixin,
    _PROGRESSIVE_STATE_AWAITING,
    _PROGRESSIVE_STATE_COMPLETING,
    _PROGRESSIVE_STATE_DONE,
    _PROGRESSIVE_STATE_NO_VIEWER,
    _PROGRESSIVE_STATE_PROGRESSIVE,
    _cleanup_progressive_lifecycle_state,
    _clear_layer2b_complete_guard,
    _clear_progressive_done_guard,
    _clear_progressive_finalized,
    _clear_progressive_inflight,
    _clear_progressive_terminal_complete_guard,
    _clear_series_download_completed,
    _get_progressive_lifecycle_state,
    _is_layer2b_complete_guard_active,
    _is_progressive_done_guard_active,
    _is_progressive_finalized,
    _is_progressive_inflight,
    _is_progressive_start_task_inflight,
    _is_progressive_terminal_complete_guard_active,
    _is_series_download_completed,
    _mark_layer2b_complete_guard,
    _mark_progressive_done_guard,
    _mark_progressive_finalized,
    _mark_progressive_inflight,
    _mark_progressive_terminal_complete_guard,
    _mark_series_download_completed,
    _set_progressive_lifecycle_state,
    _should_restart_after_done,
)


def test_lifecycle_default_is_no_viewer():
    obj = SimpleNamespace()

    state = _get_progressive_lifecycle_state(obj, "101")

    assert state == _PROGRESSIVE_STATE_NO_VIEWER
    assert getattr(obj, "_progressive_lifecycle_state", None) == {}


def test_lifecycle_transition_can_reenter_from_done():
    obj = SimpleNamespace()

    _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_DONE,
        source="test",
        reason="seed_done",
    )
    old = _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_AWAITING,
        source="test",
        reason="new_download_session",
    )

    assert old == _PROGRESSIVE_STATE_DONE
    assert _get_progressive_lifecycle_state(obj, "101") == _PROGRESSIVE_STATE_AWAITING


def test_cleanup_sets_done_and_discards_legacy_guards():
    obj = SimpleNamespace(
        _progressive_series={"101": {"total": 10}},
        _progressive_display_done={"101", "202"},
        _layer2b_complete_guard={"101", "303"},
    )

    # Put state in PROGRESSIVE before cleanup
    _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_PROGRESSIVE,
        source="test",
        reason="before_cleanup",
    )

    _cleanup_progressive_lifecycle_state(obj, "101", source="unit_test")

    assert "101" not in obj._progressive_series
    assert "101" not in obj._progressive_display_done
    assert "101" not in obj._layer2b_complete_guard
    assert _get_progressive_lifecycle_state(obj, "101") == _PROGRESSIVE_STATE_DONE


def test_done_guard_helper_uses_progressive_state_without_raw_set():
    obj = SimpleNamespace()

    _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_PROGRESSIVE,
        source="test",
        reason="active_progressive_cycle",
    )

    assert _is_progressive_done_guard_active(obj, "101") is True


def test_done_guard_helper_allows_reentry_from_done_state():
    obj = SimpleNamespace()

    _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_DONE,
        source="test",
        reason="prior_cycle_complete",
    )

    assert _is_progressive_done_guard_active(obj, "101") is False


def test_inflight_helper_uses_awaiting_state_without_raw_set():
    obj = SimpleNamespace()

    _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_AWAITING,
        source="test",
        reason="queued_start",
    )

    assert _is_progressive_inflight(obj, "101") is True
    assert _is_progressive_start_task_inflight(obj, "101") is False


def test_mark_and_clear_legacy_compatibility_helpers_round_trip():
    obj = SimpleNamespace()

    _mark_progressive_done_guard(obj, "101")
    _mark_progressive_inflight(obj, "101")
    _mark_layer2b_complete_guard(obj, "101")
    _mark_series_download_completed(obj, "101")

    assert _is_progressive_done_guard_active(obj, "101") is True
    assert _is_progressive_inflight(obj, "101") is True
    assert _is_layer2b_complete_guard_active(obj, "101") is True
    assert _is_series_download_completed(obj, "101") is True

    _clear_progressive_done_guard(obj, "101")
    _clear_progressive_inflight(obj, "101")
    _clear_layer2b_complete_guard(obj, "101")
    _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_COMPLETING,
        source="test",
        reason="completion_phase",
    )
    assert _is_progressive_done_guard_active(obj, "101") is True

    _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_DONE,
        source="test",
        reason="cleanup_complete",
    )
    assert _is_progressive_done_guard_active(obj, "101") is False
    assert _is_progressive_inflight(obj, "101") is False
    assert _is_layer2b_complete_guard_active(obj, "101") is False


def test_completed_guard_can_clear_for_verified_new_partial_cycle():
    obj = SimpleNamespace(
        _progressive_series={},
        _series_download_completed=set(),
        _find_progressive_viewers=lambda sn: [],
    )

    _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_DONE,
        source="test",
        reason="prior_cycle_complete",
    )
    _mark_series_download_completed(obj, "101")
    _mark_progressive_terminal_complete_guard(obj, "101")

    assert _should_restart_after_done(obj, "101", downloaded=5, total=20) is True

    _clear_series_download_completed(obj, "101")
    _clear_progressive_terminal_complete_guard(obj, "101")

    assert _is_series_download_completed(obj, "101") is False
    assert _is_progressive_terminal_complete_guard_active(obj, "101") is False


def test_completed_guard_rejects_terminal_late_progress_after_done():
    obj = SimpleNamespace(
        _progressive_series={},
        _series_download_completed={"101"},
        _find_progressive_viewers=lambda sn: [],
    )
    _set_progressive_lifecycle_state(
        obj,
        "101",
        _PROGRESSIVE_STATE_DONE,
        source="test",
        reason="prior_cycle_complete",
    )

    assert _should_restart_after_done(obj, "101", downloaded=20, total=20) is False


def test_terminal_complete_guard_round_trip():
    obj = SimpleNamespace()

    assert _is_progressive_terminal_complete_guard_active(obj, "101") is False


def test_progressive_finalized_guard_round_trip():
    obj = SimpleNamespace()

    assert _is_progressive_finalized(obj, "101") is False

    _mark_progressive_finalized(obj, "101")

    assert _is_progressive_finalized(obj, "101") is True

    _clear_progressive_finalized(obj, "101")

    assert _is_progressive_finalized(obj, "101") is False


def test_finalize_progressive_series_is_one_shot():
    calls = {
        "refresh": [],
        "invalidate": [],
        "thumb": [],
        "dispatch": [],
    }

    class _FakeViewer:
        _progressive_mode = True
        _progressive_series_number = "101"
        id_vtk_widget = "vw-1"

        def __init__(self):
            self.image_viewer = SimpleNamespace(update_corners_actors=lambda: None)

        def exit_progressive_mode(self):
            self._progressive_mode = False

    vtk_w = _FakeViewer()
    node = SimpleNamespace(vtk_widget=vtk_w)
    obj = SimpleNamespace(
        logger=SimpleNamespace(debug=lambda *a, **k: None, info=lambda *a, **k: None, warning=lambda *a, **k: None),
        lst_nodes_viewer=[node],
        _progressive_series={"101": {"total": 10}},
        _progressive_display_done=set(),
        _layer2b_complete_guard=set(),
        _progressive_terminal_complete_guard=set(),
        _series_download_completed=set(),
        _refresh_and_sync_metadata=lambda sn, count: calls["refresh"].append((sn, count)),
        _invalidate_series_caches=lambda sn: calls["invalidate"].append(sn),
        _update_thumbnail_count=lambda sn, count: calls["thumb"].append((sn, count)),
        _dispatch_post_completion_cache_warm=lambda sn, viewers: calls["dispatch"].append((sn, len(viewers))),
    )

    first = _VCProgressiveMixin._finalize_progressive_series(
        obj,
        "101",
        final_count=10,
        viewers=[(vtk_w, node)],
        source="unit_test",
        dispatch_cache_warm=True,
    )
    second = _VCProgressiveMixin._finalize_progressive_series(
        obj,
        "101",
        final_count=10,
        viewers=[(vtk_w, node)],
        source="unit_test_duplicate",
        dispatch_cache_warm=True,
    )

    assert first is True
    assert second is False
    assert _is_progressive_finalized(obj, "101") is True
    assert _is_series_download_completed(obj, "101") is True
    assert _get_progressive_lifecycle_state(obj, "101") == _PROGRESSIVE_STATE_DONE
    assert calls["refresh"] == [("101", 10)]
    assert calls["invalidate"] == ["101"]
    assert calls["thumb"] == [("101", 10)]
    assert calls["dispatch"] == [("101", 1)]

    _mark_progressive_terminal_complete_guard(obj, "101")

    assert _is_progressive_terminal_complete_guard_active(obj, "101") is True

    _clear_progressive_terminal_complete_guard(obj, "101")

    assert _is_progressive_terminal_complete_guard_active(obj, "101") is False
