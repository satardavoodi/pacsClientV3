"""Guard: the disk-ready resume watchdog STOPS once the viewport already shows
the full on-disk set, instead of re-firing forever (2026-06-24, fresh-run
47801/47836 series 6 = 145+ live resume attempts, only 1 ViewportLoadSucceeded
across 153 ViewportLoadRequested).

Root cause: the resume rebuilds via change_series_on_viewer, which does NOT clear
``_awaiting_series_number`` — only _apply_progressive_to_target_viewer emits
ViewportLoadSucceeded + clears it. So a viewport that reached the full slice count
kept a stale awaiting flag, and `_maybe_resume_awaiting_from_disk` re-fired every
tick (CPU churn + main-thread stalls). Fix: when the series is disk-complete AND
``get_count_of_slices() >= disk_count``, clear the stale flag, emit the settled
signal, and return False (stop). Default on; ``AIPACS_RESUME_STOP_WHEN_SETTLED=0``
restores the legacy loop.

Source-pin (the watchdog needs a live viewer + the lifecycle timer to exercise).
"""
import re
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_progressive.py"
    ).read_text(encoding="utf-8")


def test_flag_present_default_on():
    src = _src()
    assert "AIPACS_RESUME_STOP_WHEN_SETTLED" in src
    m = re.search(
        r'getenv\(\s*"AIPACS_RESUME_STOP_WHEN_SETTLED"\s*,\s*"1"\s*\)[\s\S]*?!=\s*"0"',
        src,
    )
    assert m is not None, "resume settled-stop must default ON (disable on '0')"


def test_settled_stop_lives_in_the_resume_watchdog():
    src = _src()
    # The guard must sit inside the disk-ready resume method.
    fn = src.find("def _maybe_resume_awaiting_from_disk")
    assert fn != -1
    flag = src.find("AIPACS_RESUME_STOP_WHEN_SETTLED")
    assert flag != -1 and flag > fn
    # ... and after _complete is computed (it gates on disk completeness).
    complete = src.find("_complete = _disk_ready_complete(", fn)
    assert complete != -1 and flag > complete


def test_settled_stop_clears_flag_and_returns_without_resuming():
    src = _src()
    idx = src.find("AIPACS_RESUME_STOP_WHEN_SETTLED")
    assert idx != -1
    block = src[idx: idx + 1300]
    # Gated on disk-complete AND the viewport already showing every on-disk slice.
    assert "_complete" in block
    assert "get_count_of_slices()" in block
    assert re.search(r"_vis_settled\s*>=\s*count", block)
    # Clears the stale awaiting flag, emits the settled signal, and stops.
    assert "_awaiting_series_number = None" in block
    assert "ViewportLoadSucceeded" in block
    assert re.search(r"stopping resume loop[\s\S]{0,200}?\n\s+return False", block)
