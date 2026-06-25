"""Unit tests for the pure series-display decision authority
(PacsClient/utils/series_display_state.py) — the §7 unification foundation
(docs/reports/SERIES_DISPLAY_PIPELINE_UNIFIED_METHOD_EVALUATION_2026-06-24.md).

Pure stdlib — no Qt/VTK/pydicom — so it runs anywhere the repo imports.
"""
from PacsClient.utils.series_display_state import (
    DisplayAction,
    SeriesDisplayState,
    build_series_display_state,
    decide_display_action,
)


def _state(**kw):
    return build_series_display_state("203", **kw)


# ── target / expected consolidation ───────────────────────────────────────────

def test_expected_is_max_of_resolved_and_server():
    st = _state(expected_count=102, server_count=120, disk_count=120, viewer_visible_count=8)
    assert st.expected == 120  # server's higher count wins → immune to a low resolve


def test_target_never_trusts_a_single_low_source():
    # disk transiently low (3) but expected high (24) → target stays 24
    st = _state(expected_count=24, disk_count=3, viewer_visible_count=8)
    assert st.target == 24


# ── the closed action set ──────────────────────────────────────────────────────

def test_rebuild_on_backend_mismatch():
    st = _state(disk_count=120, viewer_visible_count=120, backend_mismatch=True)
    assert decide_display_action(st) is DisplayAction.REBUILD


def test_rebuild_on_explicit_rebuild_needed():
    st = _state(disk_count=120, viewer_visible_count=120, rebuild_needed=True)
    assert decide_display_action(st) is DisplayAction.REBUILD


def test_grow_in_place_when_disk_grew_and_lazy_loader_present():
    st = _state(expected_count=120, disk_count=120, viewer_visible_count=40, has_lazy_loader=True)
    assert decide_display_action(st) is DisplayAction.GROW_IN_PLACE


def test_refresh_and_rebuild_when_disk_grew_and_no_lazy_loader():
    # The 47793 / 47842 series-203 case: viewer shows a partial volume, disk is
    # full, no lazy loader on the preview volume → refresh canonical + rebuild.
    st = _state(expected_count=120, server_count=120, disk_count=120,
                canonical_metadata_count=8, viewer_visible_count=8, has_lazy_loader=False)
    assert decide_display_action(st) is DisplayAction.REFRESH_AND_REBUILD


def test_await_download_when_viewer_matches_disk_but_incomplete():
    # disk == viewer but below expected: keep current, don't rebuild to the same/fewer.
    st = _state(expected_count=24, disk_count=8, viewer_visible_count=8)
    assert decide_display_action(st) is DisplayAction.AWAIT_DOWNLOAD


def test_noop_when_viewer_shows_full_set():
    st = _state(expected_count=120, disk_count=120, viewer_visible_count=120)
    assert decide_display_action(st) is DisplayAction.NOOP


# ── the never-downgrade guard (the core structural fix) ────────────────────────

def test_skip_downgrade_when_viewer_ahead_of_low_disk_and_expected():
    # The catastrophic reset: viewer already shows 99, a stale source reports only
    # 8 on disk with no better expected → must NOT shrink to 8.
    st = _state(expected_count=0, disk_count=8, viewer_visible_count=99)
    assert decide_display_action(st) is DisplayAction.SKIP_DOWNGRADE


def test_transient_low_disk_does_not_downgrade_when_expected_is_high():
    # viewer=99, disk transiently 8, but expected/server says 120 → not a downgrade
    # (target=120); the series is simply still catching up → AWAIT, never shrink.
    st = _state(expected_count=120, disk_count=8, viewer_visible_count=99)
    assert decide_display_action(st) is DisplayAction.AWAIT_DOWNLOAD


def test_force_reload_overrides_downgrade_guard():
    # An explicit user re-drop is allowed to rebuild even if smaller.
    st = _state(expected_count=0, disk_count=8, viewer_visible_count=99, force_reload=True)
    assert decide_display_action(st) is not DisplayAction.SKIP_DOWNGRADE


def test_growing_viewer_is_not_a_downgrade():
    # viewer=99 < disk=120 → bring it UP (not a downgrade, not await).
    st = _state(expected_count=120, server_count=120, disk_count=120, viewer_visible_count=99,
                has_lazy_loader=False)
    assert decide_display_action(st) is DisplayAction.REFRESH_AND_REBUILD


# ── frozen / pure contract ─────────────────────────────────────────────────────

def test_state_is_frozen():
    st = _state(disk_count=10, viewer_visible_count=10)
    assert isinstance(st, SeriesDisplayState)
    try:
        st.has_lazy_loader = True  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised, "SeriesDisplayState must be immutable (frozen)"
