"""Guard: the disk-ready resume watchdog must NOT livelock on a COMPLETE multi-study series
(patient 47084, series 202/203 — ViewportLoadResumedFromDisk attempt=243 despite MAX=6).

Two reinforcing fixes (source-pinned — both live deep inside change_series / the watchdog,
which need a full ViewerController + on-disk study to exercise functionally):

1. ``_vc_switch.py`` grow-fallback: the canonical metadata re-sync stays UNCONDITIONAL (keeps
   the 47855 stub repair) but ``force_reload`` now only fires when the viewport is genuinely
   BEHIND disk (``displayed < disk``). On a complete, fully-shown series the rebuild was pure
   churn that re-armed ``_awaiting_series_number`` every tick → the livelock. Flag
   ``AIPACS_GROW_FALLBACK_ONLY_WHEN_BEHIND`` (default on).
2. ``_vc_progressive.py`` settled-stop: a complete series stops when visibly full OR after the
   attempt cap is exhausted — guaranteeing termination even if get_count_of_slices() reads low
   mid-rebuild.
"""
import re
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


def _read(rel: str) -> str:
    return (_repo_root() / rel).read_text(encoding="utf-8")


_SWITCH = "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py"
_PROG = "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py"


def test_grow_fallback_force_reload_gated_on_behind():
    src = _read(_SWITCH)
    assert "AIPACS_GROW_FALLBACK_ONLY_WHEN_BEHIND" in src
    # the gate computes "behind" as true-disk > displayed and only then force-reloads
    blk = src[src.index("AIPACS_GROW_FALLBACK_ONLY_WHEN_BEHIND"):]
    blk = blk[: blk.index("self.logger.debug(")]
    assert re.search(r"_behind\s*=\s*_true_disk\s*>\s*int\(displayed_count", blk)
    assert re.search(r"if\s*\(not\s*_only_when_behind\)\s*or\s*_behind\s*:", blk)
    # and the force_reload assignment is now INSIDE that conditional, not unconditional
    i_cond = blk.index("if (not _only_when_behind) or _behind:")
    i_force = blk.index("force_reload = True")
    assert i_cond < i_force, "force_reload must be gated by the behind check"


def test_grow_fallback_resync_stays_unconditional():
    """The canonical re-sync (the 47855 stub repair) must NOT be gated on `behind` — only the
    rebuild is. Re-sync still runs whenever there are files on disk."""
    src = _read(_SWITCH)
    blk = src[src.index("AIPACS_GROW_FALLBACK_ONLY_WHEN_BEHIND") - 2000:
              src.index("AIPACS_GROW_FALLBACK_ONLY_WHEN_BEHIND")]
    assert "_refresh_and_sync_metadata(series_number, _fresh_disk)" in blk
    assert "if _fresh_disk > 0:" in blk


def test_settled_stop_terminates_on_exhaustion():
    src = _read(_PROG)
    blk = src[src.index("AIPACS_RESUME_STOP_WHEN_SETTLED"):]
    blk = blk[: blk.index("Progressive first-image start")]
    assert re.search(r"_exhausted\s*=\s*_attempts_now\s*>=\s*_DISK_READY_RESUME_MAX_ATTEMPTS", blk)
    assert re.search(r"_settled_visible\s*=\s*_vis_settled\s*>\s*0\s*and\s*_vis_settled\s*>=\s*count", blk)
    assert "if _settled_visible or _exhausted or _authority_settled:" in blk
    # and it still clears the stale awaiting flag when it stops
    stop = blk[blk.index("if _settled_visible or _exhausted or _authority_settled:"):]
    assert "vtk_w._awaiting_series_number = None" in stop


def test_kill_switch_present():
    assert re.search(
        r'os\.getenv\(\s*\n?\s*"AIPACS_GROW_FALLBACK_ONLY_WHEN_BEHIND"\s*,\s*"1"\s*\)',
        _read(_SWITCH),
    )


def test_s2b_state_authority_is_additional_stop_signal():
    """S2b: the state authority's is_settled is an ADDITIONAL settled-stop signal (the live
    _settled_visible / _exhausted checks are never removed — strictly more-likely-to-stop), and
    the feed runs when shadow OR authority is enabled. Default OFF (AIPACS_VIEWER_STATE_AUTHORITY)."""
    src = _read(_PROG)
    # flag defaults OFF (opt-in '1'); the resume reads the authority record only when enabled
    assert re.search(
        r'_STATE_AUTHORITY_ENABLED\s*=\s*\(\s*_os\.getenv\(\s*"AIPACS_VIEWER_STATE_AUTHORITY"\s*,\s*"0"\s*\)[\s\S]*?==\s*"1"',
        src,
    )
    assert "_auth_rec = self._feed_state_authority(" in src
    assert re.search(
        r"_authority_settled\s*=\s*bool\(\s*\n?\s*_STATE_AUTHORITY_ENABLED\s*and\s*_auth_rec is not None\s*and\s*_auth_rec\.is_settled",
        src,
    )
    # the feed runs for shadow OR authority (so the store is populated when the authority is on)
    feed = src[src.index("def _feed_state_authority"):]
    feed = feed[: feed.index("def _maybe_resume_awaiting_from_disk")]
    assert "if not (shadow_enabled() or _STATE_AUTHORITY_ENABLED):" in feed
    # the authority READ never replaces the live checks — they remain in the OR
    assert "if _settled_visible or _exhausted or _authority_settled:" in src
