# -*- coding: utf-8 -*-
"""Guard: Sync Image (TARGET) survives an active-viewport change — viewport-click
driven, not active-layout dependent (2026-06-27).

Bug: with Sync Image active on Layout 1, clicking Sync Image on a NON-active
viewport (Layout 2) first ran ``set_viewer_to_main_viewer`` →
``check_and_deactivate_tools()`` (which turns sync OFF), and ``get_tool_activated_method``
has no TARGET branch so it was not re-applied. The in-flight FAST press then saw
``_sync_mode_active`` False and placed no point — so the user had to click Sync Image a
second time once Layout 2 was active.

Fix: ``set_viewer_to_main_viewer`` gains a SYNC-preserve branch (sibling of the existing
MPR-preserve): when the active tool is ``TARGET`` it just moves the active selection and
returns WITHOUT tearing sync down, so the same click lands the target on the clicked
viewport and syncs to the others. Kill switch:
``AIPACS_SYNC_PRESERVE_ON_VIEWPORT_CHANGE=0``.

Source-pin (``set_viewer_to_main_viewer`` is Qt/VTK-heavy and can't run offscreen).
``_vc_layout.py`` is NOT plugin-mirrored.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SRC = (
    REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_layout.py"
)


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated read of {p.name}; run on Windows / clean checkout")
    return b.decode("utf-8", "replace")


def _method_body(src: str, method_def: str) -> str:
    i = src.find(method_def)
    assert i != -1, f"{method_def} not found"
    nxt = src.find("\n    def ", i + len(method_def))
    return src[i: nxt if nxt != -1 else len(src)]


def test_sync_preserve_branch_present_and_flag_default_on():
    body = _method_body(_read(SRC), "def set_viewer_to_main_viewer(self")
    # Flag, default ON
    assert "AIPACS_SYNC_PRESERVE_ON_VIEWPORT_CHANGE" in body
    assert '"AIPACS_SYNC_PRESERVE_ON_VIEWPORT_CHANGE", "1"' in body
    # Detects the Sync Image tool by TARGET
    assert "tb.tool_access.TARGET" in body
    assert "_tool_is_sync" in body
    assert "_preserve_sync" in body


def test_sync_preserve_returns_before_teardown():
    """The sync-preserve early-return must precede check_and_deactivate_tools() so the
    click neither deactivates sync nor falls through to the generic teardown path."""
    body = _method_body(_read(SRC), "def set_viewer_to_main_viewer(self")
    i_branch = body.find("if _preserve_sync and _tool_is_sync:")
    i_teardown = body.find("tb.check_and_deactivate_tools()")
    assert i_branch != -1, "sync-preserve branch missing"
    assert i_teardown != -1, "check_and_deactivate_tools call missing"
    assert i_branch < i_teardown, "sync-preserve must come before the teardown call"
    # The branch body moves the selection and returns (no teardown).
    branch = body[i_branch:i_teardown]
    assert "self.selected_widget" in branch
    assert "return" in branch


def test_target_still_deactivates_in_check_and_deactivate_tools():
    """Regression: switching to ANOTHER tool must still tear sync down — the TARGET
    branch in check_and_deactivate_tools (toolbar_manager) is untouched."""
    tbm = (
        REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "patient_toolbar" / "toolbar_manager.py"
    )
    src = _read(tbm)
    assert "elif self.tool_selected == self.tool_access.TARGET:" in src
    assert "self.toggle_sync_point(False)" in src
