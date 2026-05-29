"""Regression guard: RightPanelWidget.THUMBNAIL_BOX_HEIGHT must match the
real ThumbnailManager card height.

Background - 2026-05-29 round-2 home-thumbnail-overlap
======================================================
After the home thumbnail card was made taller (190x190 -> 190x215) so the
server-description and image-count labels could coexist, the user
reported the cards STILL overlapped vertically on the Home page (but not
in the Patient Viewer thumbnail panel, which uses the same card).

Root cause: RightPanelWidget._set_reserved_content_height pre-reserves
the content_widget's height with `count * THUMBNAIL_BOX_HEIGHT + spacing`
and locks min == max == that value. THUMBNAIL_BOX_HEIGHT was the OLD 190
literal — 25 px LESS than each card's real height. With 4 cards the
container was locked to 100 px short of what the cards needed; QGridLayout
compressed them and they visually overlapped.

The Patient Viewer doesn't pre-reserve content_widget height — its grid
content can grow freely, so the same 215-tall card lays out correctly
there with even tighter spacing (6 px).

Fix: bump THUMBNAIL_BOX_HEIGHT to 215 so the reserved height matches the
real card. This guard couples the two constants in source so they can't
drift apart again.
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


@pytest.fixture(scope="module")
def right_panel_src() -> str:
    return RIGHT_PANEL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def thumb_mgr_src() -> str:
    return THUMBNAIL_MANAGER.read_text(encoding="utf-8")


def _thumbnail_card_fixed_height(src: str) -> int:
    """Parse the create_thumbnail_widget card height from thumbnail_manager.py.

    Looks for `widget.setFixedSize(<w>, <h>)` immediately after the
    `def create_thumbnail_widget(` marker — the 'main container widget'
    in the create_thumbnail_widget function body.
    """
    idx = src.find("def create_thumbnail_widget(")
    assert idx >= 0, "create_thumbnail_widget definition missing"
    end = src.find("\n    def ", idx + 1)
    body = src[idx : end if end > 0 else len(src)]
    m = re.search(r"widget\.setFixedSize\(\s*\d+\s*,\s*(\d+)\s*\)", body)
    assert m is not None, (
        "Could not find widget.setFixedSize(W, H) inside "
        "create_thumbnail_widget. If the API moved, update this guard."
    )
    return int(m.group(1))


def test_thumbnail_box_height_constant_matches_card(
    right_panel_src: str, thumb_mgr_src: str
) -> None:
    """RightPanelWidget.THUMBNAIL_BOX_HEIGHT must == the real card height
    in ThumbnailManager.create_thumbnail_widget.

    If this fails the pre-reserved scroll height is wrong by N * (real -
    constant) pixels and the cards will visually overlap.
    """
    card_h = _thumbnail_card_fixed_height(thumb_mgr_src)
    m = re.search(
        r"^\s*THUMBNAIL_BOX_HEIGHT\s*=\s*(\d+)\s*$",
        right_panel_src,
        re.MULTILINE,
    )
    assert m is not None, (
        "RightPanelWidget.THUMBNAIL_BOX_HEIGHT constant missing. "
        "_set_reserved_content_height needs it to pre-allocate the "
        "content_widget height; without it the scroll area's vertical "
        "geometry is unstable while thumbnails stream in."
    )
    reserved = int(m.group(1))
    assert reserved == card_h, (
        f"RightPanelWidget.THUMBNAIL_BOX_HEIGHT ({reserved}) does NOT "
        f"match the real ThumbnailManager card height ({card_h}). The "
        f"home-page right panel uses this constant to lock the "
        f"content_widget to count * THUMBNAIL_BOX_HEIGHT + spacing. If "
        f"the constant is smaller than the real card height, cards will "
        f"VISUALLY OVERLAP each other on the Home page (but not in the "
        f"Patient Viewer, which doesn't pre-reserve). See 2026-05-29 "
        f"round-2 user-reported overlap regression."
    )


def test_thumbnail_box_height_has_warning_comment(right_panel_src: str) -> None:
    """The THUMBNAIL_BOX_HEIGHT declaration must be accompanied by a
    comment pointing at the source-of-truth in thumbnail_manager. Future
    agents shouldn't be able to change the constant without first reading
    why it has to track the card height."""
    # Look at the 12 lines preceding the THUMBNAIL_BOX_HEIGHT line so the
    # comment can sit just above it.
    lines = right_panel_src.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r"\s*THUMBNAIL_BOX_HEIGHT\s*=", ln):
            window = "\n".join(lines[max(0, i - 12) : i])
            assert "thumbnail_manager" in window.lower(), (
                "THUMBNAIL_BOX_HEIGHT must have a comment above it "
                "referencing thumbnail_manager.py as the source of truth. "
                "Otherwise the next person who edits the constant won't "
                "know it has to match the real card height. See 2026-05-29 "
                "round-2 overlap regression."
            )
            return
    pytest.fail("THUMBNAIL_BOX_HEIGHT line not found in right_panel_widget.py")
