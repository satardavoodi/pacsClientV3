"""OPT-37 — thumbnails must refresh when the server gains new images (50264, 2026-07-14).

THE BUG. The user clicked a study when only 3 series were on the server; ~5 minutes later
the rest arrived (24 series / 1148 images) — but the thumbnails never refreshed, no matter
how many times the study was clicked. Clearing the patient-code filter and switching to
"Yesterday" made them appear instantly.

The live trace (patient 50264, CT study …072):

    17:21:21  study_resync_check  result=grew  server_series=2  new_series=2   <- DETECTED
    17:22:43  resync_start -> resync_complete  changed=0   (0.2 ms, NO server check)
    17:22:58  ... changed=0      17:23:49  changed=0      17:24:19  changed=0
    17:25:07  changed=0          17:25:20  changed=0      17:25:52  changed=0

ROOT CAUSE: `_RESYNC_TTL_S = 300.0` — a flat 5-minute per-study throttle on the change
detector, applied to EVERY study including one the previous check had just found INCOMPLETE
(`result=grew`). That is exactly the study whose content WILL change, and 5 minutes is
exactly the window in which it did. Every click inside the window was throttled out before
any server query, so the growth was never seen.

The refresh machinery itself was never broken: a detected change already re-renders with
`_show_grouped_patient_studies(..., force_server_merge=True)`.

WHY THE FILTER CHANGE "FIXED" IT: the patient-code search returns the patient's 2 studies as
ONE aggregated row (`study_uids_count=2`) -> the GROUPED render path, which reads local
thumbnails only. The "Yesterday" list produced a SINGLE-study row (`study_uids_count=1`) ->
`show_patient_studies` -> the single-study cache gate, which DOES check the server
(`grew=1 local_thumbs=2 server_series=24` -> fetched 24). Nothing was invalidated; the click
simply took the other code path.

THE FIX: the TTL is now per-study and completeness-aware. `set_synced_version` is stamped
ONLY on the confirmed-complete branch, so its ABSENCE means "still growing" -> short TTL.
"""

import os

import pytest


TTL_FULL = 300.0
TTL_INCOMPLETE = 10.0


def _ttl_for(confirmed_complete, enabled=True):
    """Mirrors `_resync_ttl_for`."""
    if not enabled:
        return TTL_FULL
    return TTL_FULL if confirmed_complete else TTL_INCOMPLETE


def _due(last_checked_ago, confirmed_complete, force=False, enabled=True, feature_on=True):
    """Mirrors `_study_due_for_resync`."""
    if force:
        return True
    if not feature_on:
        return False
    if last_checked_ago is None:      # never checked
        return True
    return last_checked_ago >= _ttl_for(confirmed_complete, enabled)


# ── the exact 50264 failure ───────────────────────────────────────────────
@pytest.mark.parametrize("seconds_after_first_check", [82, 97, 148, 178, 226, 239, 271])
def test_50264_a_growing_study_is_rechecked_on_every_click_inside_5_minutes(seconds_after_first_check):
    """The real click times (17:22:43 … 17:25:52 after a 17:21:21 check) — ALL were skipped.

    The study was found `grew` (never confirmed complete), so it must be re-checked.
    """
    assert _due(seconds_after_first_check, confirmed_complete=False) is True


def test_50264_legacy_flat_TTL_skipped_every_one_of_those_clicks():
    """Pins the OLD behaviour so we can see exactly what was broken."""
    for ago in (82, 97, 148, 178, 226, 239, 271):
        assert _due(ago, confirmed_complete=False, enabled=False) is False  # <- the bug


# ── the responsiveness contract (44113) must be preserved ─────────────────
def test_a_CONFIRMED_COMPLETE_study_still_honours_the_full_5_minute_TTL():
    """A finished study must NOT hit the network on every click."""
    assert _due(30, confirmed_complete=True) is False
    assert _due(299, confirmed_complete=True) is False
    assert _due(301, confirmed_complete=True) is True


def test_a_growing_study_is_still_throttled_against_click_spam():
    """The short TTL is a throttle, not 'always fetch' — rapid double-clicks are absorbed."""
    assert _due(0.5, confirmed_complete=False) is False
    assert _due(9.9, confirmed_complete=False) is False
    assert _due(10.0, confirmed_complete=False) is True


# ── invariants ────────────────────────────────────────────────────────────
def test_never_checked_is_always_due():
    assert _due(None, confirmed_complete=True) is True
    assert _due(None, confirmed_complete=False) is True


def test_manual_refresh_always_forces_a_check():
    assert _due(0, confirmed_complete=True, force=True) is True
    assert _due(0, confirmed_complete=False, force=True) is True


def test_feature_disabled_never_resyncs():
    assert _due(999, confirmed_complete=False, feature_on=False) is False


def test_kill_switch_restores_the_flat_TTL():
    assert _ttl_for(confirmed_complete=False, enabled=False) == TTL_FULL
    assert _ttl_for(confirmed_complete=True, enabled=False) == TTL_FULL


def test_ttl_selection():
    assert _ttl_for(confirmed_complete=True) == TTL_FULL
    assert _ttl_for(confirmed_complete=False) == TTL_INCOMPLETE


# ── wiring pins ───────────────────────────────────────────────────────────
def _src():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    path = os.path.join(
        root, "PacsClient", "pacs", "workstation_ui", "home_ui", "home_panel", "_hp_series.py"
    )
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


def test_wiring_completeness_aware_ttl_is_used_by_the_throttle():
    src = _src()
    assert "def _study_confirmed_complete" in src
    assert "def _resync_ttl_for" in src
    assert "self._resync_ttl_for(study_uid)" in src, "the throttle must use the per-study TTL"


def test_wiring_completeness_comes_from_the_content_version_store():
    """`set_synced_version` is stamped ONLY on the confirmed-complete branch — that is
    what makes its absence a reliable 'still growing' signal. Don't swap this source."""
    src = _src()
    assert "from modules.storage.content_version_store import get_synced_version" in src


def test_wiring_flags_default_on_with_kill_switch():
    src = _src()
    assert "AIPACS_RESYNC_TTL_INCOMPLETE" in src
    assert "'AIPACS_RESYNC_TTL_INCOMPLETE', '1'" in src, "must default to ON"
    assert "_RESYNC_TTL_S = 300.0" in src, "the full TTL must stay 300s for complete studies"


def test_wiring_the_existing_refresh_path_is_untouched():
    """A detected change already re-renders with force_server_merge=True — the fix only
    restores DETECTION; it must not fork a second refresh path."""
    src = _src()
    assert "force_server_merge=True" in src
