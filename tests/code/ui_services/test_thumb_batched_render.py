"""Guard: patient-open GUI-FREEZE fix — large right-panel thumbnail sets render incrementally.

Live evidence (PID 206088, 2026-06-27): opening a large multi-study patient froze the GUI thread for
~23s. The [MAIN_THREAD_STALL_TRACE] stack was:
    main.notify -> right_panel_widget.display_thumbnails_immediately
                -> thumbnail_manager.create_thumbnail_widget (QWidget()/addWidget loop)
i.e. ALL thumbnail widgets were built synchronously on the GUI thread. NOT the VTK volume build, and
NOT the S4b cache (which had 0 execution that run).

Fix (flag AIPACS_THUMB_BATCHED_RENDER default-on; `=0` = byte-identical legacy synchronous render):
`display_thumbnails_immediately` delegates a set larger than AIPACS_THUMB_IMMEDIATE_MAX (default 16)
to the EXISTING incremental renderer `display_thumbnails_progressively`, which paces widget creation
across event-loop turns so the UI stays responsive. Small sets keep the fast synchronous path.

Source-pin only (the render path needs PySide6 + the widget tree); the behaviour is validated live.
"""
from __future__ import annotations

from pathlib import Path

_SRC = (Path(__file__).resolve().parents[3]
        / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "right_panel_widget.py")


def _src() -> str:
    return _SRC.read_text(encoding="utf-8")


def test_flag_default_on_with_kill_switch():
    s = _src()
    # the flag DEFINITION line: default "1" + `!= "0"` = default-on with a `=0` kill switch
    assert ('_THUMB_BATCHED_RENDER_ENABLED = (os.getenv("AIPACS_THUMB_BATCHED_RENDER", "1") '
            'or "1").strip() != "0"') in s
    assert '"AIPACS_THUMB_IMMEDIATE_MAX", "16"' in s      # tunable threshold, sane default


def test_large_set_delegates_to_incremental_renderer():
    s = _src()
    body = s[s.index("def display_thumbnails_immediately("):]
    head = body[:1400]
    assert "_THUMB_BATCHED_RENDER_ENABLED" in head
    assert "len(thumbnails" in head and "_THUMB_IMMEDIATE_MAX" in head
    assert "return self.display_thumbnails_progressively(thumbnails, generation)" in head
    # the delegate must sit BEFORE the synchronous build path (the 0x8001010d guard precedes the loop)
    assert head.index("display_thumbnails_progressively") < head.index("0x8001010d")


def test_incremental_renderer_still_exists():
    """The fix REUSES the existing progressive renderer — it must still be present + paced by a timer."""
    s = _src()
    assert "def display_thumbnails_progressively(" in s
    prog = s[s.index("def display_thumbnails_progressively("):]
    assert "QTimer" in prog[:2000]            # it paces via a timer (does not build all synchronously)


def test_small_set_keeps_synchronous_path():
    """Small sets must NOT be forced through the timer path (no behaviour change / no slowdown)."""
    s = _src()
    body = s[s.index("def display_thumbnails_immediately("):]
    head = body[:1200]
    # the delegate is gated on the threshold, not unconditional
    assert "if _THUMB_BATCHED_RENDER_ENABLED and _too_many:" in head
