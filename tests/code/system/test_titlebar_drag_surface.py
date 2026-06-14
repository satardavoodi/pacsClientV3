"""Regression guard: the frameless main window must stay draggable between
monitors (2026-06-14).

The window is frameless on Windows; it is moved by clicking the title-bar
*background* and the code arms a system move only when
``_is_titlebar_background_hit`` is True. That check used to require
``QApplication.widgetAt(cursor) is self.title_bar`` EXACTLY — but the title bar
is filled by child frames (``tab_area`` claims most of the width via stretch,
plus ``right_tab_area`` and the account pill), so there is almost no raw
``title_bar`` background left to grab. When the user-info pill gained a clickable
"Connected Accounts" popup, the last easily-grabbed spot became a button and the
whole window stopped being draggable.

Fix: the bare regions of the tab-strip frames (``tab_area`` / ``right_tab_area``)
are now also drag surfaces, while the account pill (``user_info_container``) is
intentionally NOT — it must stay clickable. Window buttons and the standard tab
bar remain excluded earlier in the function.

A behavioural test needs a shown top-level window + ``QApplication.widgetAt``;
this source guard pins the contract instead.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = (REPO / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py").read_text(encoding="utf-8")


def _hit_test_body():
    m = re.search(
        r"def _is_titlebar_background_hit\(self.*?\)\s*->\s*bool:(.*?)\n    def ",
        SRC, re.DOTALL,
    )
    assert m, "could not locate _is_titlebar_background_hit"
    return m.group(1)


def _drag_surfaces_list():
    """The actual `drag_surfaces = [...]` literal (excludes comments)."""
    m = re.search(r"drag_surfaces\s*=\s*\[(.*?)\]", _hit_test_body(), re.DOTALL)
    assert m, "could not locate the drag_surfaces list"
    return m.group(1)


def test_tab_strip_frames_are_drag_surfaces():
    surfaces = _drag_surfaces_list()
    assert "tab_area" in surfaces, "tab_area must be a drag surface (it claims the title-bar width)"
    assert "right_tab_area" in surfaces, "right_tab_area must be a drag surface"
    assert "title_bar" in surfaces, "the title_bar frame itself must remain a drag surface"


def test_account_pill_is_not_a_drag_surface():
    # The user/account pill is clickable (Connected Accounts popup); it must NOT
    # be in the drag-surface list or the click would be swallowed. (The body's
    # explanatory comment may mention it; only the list literal matters.)
    surfaces = _drag_surfaces_list()
    assert "user_info_container" not in surfaces and "user_container" not in surfaces, (
        "the account pill must NOT be a drag surface — it must stay clickable"
    )


def test_buttons_and_tabbar_still_excluded_before_drag():
    # The interactive exclusions must still run before the drag-surface decision.
    body = _hit_test_body()
    assert "_is_over_window_buttons" in body
    assert "_is_over_tabbar" in body
