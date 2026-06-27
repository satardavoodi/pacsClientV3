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
signal, and return False (stop). UNCONDITIONAL since the S3b cutover (2026-06-27) — the
``AIPACS_RESUME_STOP_WHEN_SETTLED`` flag + its legacy "loop" ``=0`` branch were removed,
so the livelock can no longer be re-enabled.

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


def test_settled_stop_is_unconditional_no_flag():
    src = _src()
    # S3b cutover 2026-06-27: the flag's env-read + its `=0` legacy (loop) branch were removed
    # (the docstring/comment may still NAME the retired flag for history). Settled-stop unconditional.
    assert 'getenv("AIPACS_RESUME_STOP_WHEN_SETTLED"' not in src
    assert "if _complete:" in src   # the unconditional settled-stop gate


def test_settled_stop_lives_in_the_resume_watchdog():
    src = _src()
    # The settled-stop must sit inside the disk-ready resume method, after disk-completeness.
    fn = src.find("def _maybe_resume_awaiting_from_disk")
    assert fn != -1
    complete = src.find("_complete = _disk_ready_complete(", fn)
    assert complete != -1
    stop = src.find("stopping resume loop", complete)
    assert stop != -1 and stop > complete


def test_settled_stop_clears_flag_and_returns_without_resuming():
    src = _src()
    fn = src.find("def _maybe_resume_awaiting_from_disk")
    start = src.find("_complete = _disk_ready_complete(", fn)
    end = src.find("Progressive first-image start", start)
    assert start != -1 and end != -1
    block = src[start:end]   # the whole settled-stop region (disk-complete gate → next section)
    # Gated on disk-complete AND the viewport already showing every on-disk slice.
    assert "get_count_of_slices()" in block
    assert re.search(r"_vis_settled\s*>=\s*count", block)
    # Clears the stale awaiting flag, emits the settled signal, and stops.
    assert "_awaiting_series_number = None" in block
    assert "ViewportLoadSucceeded" in block
    assert re.search(r"stopping resume loop[\s\S]{0,200}?\n\s+return False", block)
