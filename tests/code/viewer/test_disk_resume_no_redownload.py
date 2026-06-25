"""Guard: the disk-ready RESUME must not re-download data already on disk
(2026-06-24, mehr patient 14965 mammography).

Root cause that this pins: `_maybe_resume_awaiting_from_disk` fires ONLY after the
series files are confirmed complete on disk, then loads them by calling
`change_series_on_viewer(...)`. It used to pass `force_reload=True`, which (a)
invalidates the full-series / ZetaBoost disk cache (`clear_disk=True`) and (b) on
any load miss re-triggers a full network RE-DOWNLOAD of the data it just confirmed
on disk. On a slow link (mehr) that spun the viewport for minutes re-fetching tens
of MB it already had, and the watchdog repeated it every retry.

The fix flips that one call to `force_reload=False` (default), gated by the kill
switch `AIPACS_DISK_RESUME_NO_REDOWNLOAD=0` (restores the legacy force_reload).
Correct-cell targeting is preserved by `vtk_widget` + `flag_change_selected_widget`,
which are independent of force_reload.

Source-pin (the resume path needs a live viewer + download to exercise); no PySide6.
"""
import re
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _resume_source() -> str:
    return (
        _repo_root()
        / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_progressive.py"
    ).read_text(encoding="utf-8")


def test_resume_uses_flag_gated_force_reload_not_hardcoded_true():
    src = _resume_source()
    # The fix flag + its env var must be present.
    assert "AIPACS_DISK_RESUME_NO_REDOWNLOAD" in src
    assert "_resume_force_reload" in src
    # The resume's change_series call must pass the flag variable, NOT a literal True.
    m = re.search(
        r"_resume_force_reload\s*=\s*\(\s*\n?\s*_os2\.getenv\(\s*[\"']AIPACS_DISK_RESUME_NO_REDOWNLOAD[\"']",
        src,
    )
    assert m is not None, "disk-resume force_reload must be derived from the kill-switch env"
    # And the change_series_on_viewer call inside the resume must use the variable.
    assert "force_reload=_resume_force_reload" in src


def test_no_hardcoded_force_reload_true_in_disk_resume_call():
    """The specific resume call must not have reverted to force_reload=True.

    Scope the check to the ViewportLoadResumedFromDisk block so unrelated
    force_reload=True call sites (the legitimate manual-drag path) are ignored.
    """
    src = _resume_source()
    idx = src.find("ViewportLoadResumedFromDisk")
    assert idx != -1
    # Inspect a window after the resume marker that covers the change_series call
    # (the explanatory comment is long, so the call sits well past the marker).
    window = src[idx: idx + 2800]
    assert "force_reload=_resume_force_reload" in window
    # The legacy call form is `force_reload=True,` (a call argument with a trailing
    # comma). The explanatory comment mentions the words "force_reload=True" but
    # never as a call argument, so the comma form pins a real revert without false
    # positives on the prose.
    assert "force_reload=True," not in window, (
        "disk-ready resume reverted to a hardcoded force_reload=True — this re-downloads "
        "data already on disk on a slow link"
    )
