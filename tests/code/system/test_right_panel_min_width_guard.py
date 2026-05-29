"""Regression guards: RightPanelWidget min width must leave clear gap
between the thumbnail card right edge and the AlwaysOn vertical scrollbar.

Background - 2026-05-29 round-3 dotted-border-clip
==================================================
User reported (after rounds 1+2 of the home-thumbnail panel fix) that
the right edge of the thumbnail card's dotted border was still
visually clipped at the scrollbar.

Geometry:
    card_left_edge       = left_margin (8)
    card_right_edge      = left_margin + card_width(190) = 198
    scrollbar_left_edge  = panel_width - scrollbar_width(12)
    visible_gap          = scrollbar_left_edge - card_right_edge
                         = panel_width - 210

With AlignLeft on a fixed-width card, the grid's right margin does NOT
change card_right_edge — the card always sits at x=left_margin
regardless of how much right padding the drawing area has. The right
margin matters only if alignment is Center / Right OR the child has
Expanding policy.

The only way to guarantee visible clearance is to bump the panel's
minimum width so panel_width >= 210 + minimum_gap.

Fix: setMinimumWidth(232) → guarantees ≥22 px gap at the floor. The
generous grid right margin (30) is kept for breathing room at wider
widths but is not the load-bearing change.

Guards:
1. min_width >= 232 so at the floor gap is at least 22 px.
2. The setMinimumWidth call comment references the geometry math
   so the next agent who tries to lower it knows the constraint.
3. card width still = 190 in thumbnail_manager (otherwise the 232
   math is wrong) — surfaced by parsing both files.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
RIGHT_PANEL = (
    REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
    / "right_panel_widget.py"
)
THUMBNAIL_MANAGER = (
    REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "utils"
    / "thumbnail_manager.py"
)


# Geometry constants the guards depend on.
# Keep in sync with the comments in right_panel_widget.py.
_GRID_LEFT_MARGIN = 8
_SCROLLBAR_WIDTH = 12
_MIN_VISIBLE_GAP = 22


@pytest.fixture(scope="module")
def right_panel_src() -> str:
    return RIGHT_PANEL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def thumb_mgr_src() -> str:
    return THUMBNAIL_MANAGER.read_text(encoding="utf-8")


def _thumbnail_card_width(src: str) -> int:
    """Parse the create_thumbnail_widget card WIDTH from thumbnail_manager.py."""
    idx = src.find("def create_thumbnail_widget(")
    assert idx >= 0, "create_thumbnail_widget definition missing"
    end = src.find("\n    def ", idx + 1)
    body = src[idx : end if end > 0 else len(src)]
    m = re.search(r"widget\.setFixedSize\(\s*(\d+)\s*,\s*\d+\s*\)", body)
    assert m is not None, (
        "Could not find widget.setFixedSize(W, H) inside "
        "create_thumbnail_widget."
    )
    return int(m.group(1))


def _right_panel_min_width(src: str) -> int:
    """Parse the setMinimumWidth literal applied to RightPanelWidget."""
    # Match `self.setMinimumWidth(N)` — not `self.scroll_area.setMinimumWidth`
    # or anything else nested. The self. one applies to the RightPanelWidget.
    matches = re.findall(
        r"^\s*self\.setMinimumWidth\(\s*(\d+)\s*\)",
        src,
        flags=re.MULTILINE,
    )
    assert matches, "self.setMinimumWidth(N) not found in right_panel_widget.py"
    # If multiple, take the first (the construction-time floor).
    return int(matches[0])


def test_min_width_leaves_visible_gap_for_card_and_scrollbar(
    right_panel_src: str, thumb_mgr_src: str
) -> None:
    """At the minimum panel width the card's right edge must clear the
    AlwaysOn vertical scrollbar by at least _MIN_VISIBLE_GAP px,
    otherwise the dotted border visually clips into the scrollbar."""
    card_w = _thumbnail_card_width(thumb_mgr_src)
    min_w = _right_panel_min_width(right_panel_src)
    required = _GRID_LEFT_MARGIN + card_w + _MIN_VISIBLE_GAP + _SCROLLBAR_WIDTH
    assert min_w >= required, (
        f"RightPanelWidget.setMinimumWidth({min_w}) is too small. "
        f"With a {card_w} px card aligned LEFT (sits at x={_GRID_LEFT_MARGIN}) "
        f"and a {_SCROLLBAR_WIDTH} px AlwaysOn vertical scrollbar, the gap "
        f"between card right edge and scrollbar left edge is "
        f"(min_w - {_GRID_LEFT_MARGIN + card_w + _SCROLLBAR_WIDTH}) px. "
        f"For the dotted border to clear the scrollbar by at least "
        f"{_MIN_VISIBLE_GAP} px, min_w must be >= {required}. See "
        f"2026-05-29 round-3 user-reported dotted-border-clip regression."
    )


def test_min_width_comment_documents_the_constraint(right_panel_src: str) -> None:
    """The setMinimumWidth call must be accompanied by a comment
    explaining why it is what it is, so the next agent who wants to
    lower it can see the constraint."""
    lines = right_panel_src.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r"\s*self\.setMinimumWidth\s*\(", ln):
            window = "\n".join(lines[max(0, i - 12) : i])
            assert ("scrollbar" in window.lower()
                    and ("190" in window or "card" in window.lower())), (
                "self.setMinimumWidth must have a comment above it "
                "explaining the geometry constraint (card width + "
                "scrollbar + visible gap). Without it the next person "
                "to edit will not understand why the floor cannot be "
                "lowered. See 2026-05-29 round-3 regression."
            )
            return
    pytest.fail("self.setMinimumWidth line not found in right_panel_widget.py")
