"""Guard: an AWAITING viewport (series dragged before its download finished) starts
the progressive display on the FIRST on-disk image instead of waiting for the full
series (2026-06-24, mehr poor network — the core "see the first usable image as
early as possible" goal).

Live symptom this fixes: 6/10 images downloaded, viewport still blank (spinner
"Downloading 6 of 10"), because the disk-ready resume required _disk_ready_complete
(count >= expected) before loading. The fix starts the display on count>=1 (once per
awaiting episode); the in-place on_series_images_progress grow expands the stack as
the rest arrive. The complete-resume path (secondary-study completion backfill) is
unchanged.

Source-pin (the resume needs a live viewer + download to exercise); no PySide6.
"""
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
    assert "AIPACS_PROGRESSIVE_AWAIT_FIRST_IMAGE" in src
    assert "_PROGRESSIVE_AWAIT_FIRST_IMAGE" in src


def test_progressive_start_gate_conditions():
    src = _src()
    idx = src.find("_prog_start = (")
    assert idx != -1, "progressive first-image start gate missing"
    block = src[idx: idx + 400]
    assert "_PROGRESSIVE_AWAIT_FIRST_IMAGE" in block
    assert "not _complete" in block          # only when NOT yet complete
    assert "count >= 1" in block             # at least one image on disk
    assert "_progressive_await_started" in block  # once per episode


def test_complete_resume_path_preserved():
    """The full-series resume (secondary-study completion) must remain — the change
    only ADDS the partial-start path."""
    src = _src()
    assert "_disk_ready_complete(count, expected, prev)" in src
    assert "ViewportLoadResumedFromDisk" in src
    assert "ViewportProgressiveFirstImage" in src


def test_started_flag_reset_per_episode():
    src = _src()
    # Reset alongside the other per-episode awaiting state.
    idx = src.find("_disk_ready_resume_key = key_str")
    assert idx != -1
    block = src[idx: idx + 700]
    assert "_progressive_await_started = False" in block
