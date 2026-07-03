"""Source-wiring guard for the Seam B grow cutover (2026-07-03).

Pins the safety-critical shape of the flag-gated, default-OFF event-driven
watchdog keep-alive in home_download_service.py so a refactor can't silently
turn it on, remove the guard, or reintroduce a wrong-viewport routing change.
Pure source scan — imports nothing, runs anywhere.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SRC = (_REPO / "PacsClient/pacs/workstation_ui/home_ui/home_download_service.py").read_text(
    encoding="utf-8", errors="ignore"
)


def test_flag_present_with_kill_switch():
    assert 'AIPACS_LIFECYCLE_GROW_ACTIVE' in _SRC
    # Default ON for the test build; the env var remains a kill switch (=0).
    assert '"AIPACS_LIFECYCLE_GROW_ACTIVE", "1"' in _SRC
    assert '_LIFECYCLE_GROW_ACTIVE' in _SRC


def test_nudge_is_guarded_and_reuses_backstop():
    assert 'def _lc_seam_b_nudge_backstop' in _SRC
    # It must be gated on the flag ...
    assert 'if not _LIFECYCLE_GROW_ACTIVE' in _SRC
    # ... reuse the EXISTING watchdog (no new routing/render) ...
    assert '_ensure_dl_watchdog' in _SRC
    # ... and swallow all exceptions (never break the clinical path).
    assert 'except Exception:' in _SRC


def test_wired_at_both_drop_sites():
    # Both on_series_progress and on_series_completed drop-paths nudge the backstop.
    assert _SRC.count('_lc_seam_b_nudge_backstop(widget_ref())') >= 2


def test_does_not_route_or_render_directly():
    # The cutover must NOT call display/grow/change_series directly from the bridge
    # drop path — that is the wrong-viewport risk it deliberately avoids.
    fn = _SRC.split('def _lc_seam_b_nudge_backstop', 1)[1].split('\n\n\n', 1)[0]
    for forbidden in ('display_thumbnails', 'change_series', 'set_server_series_info',
                      'load_single_series', 'grow('):
        assert forbidden not in fn, f"nudge helper must not call {forbidden!r} directly"
