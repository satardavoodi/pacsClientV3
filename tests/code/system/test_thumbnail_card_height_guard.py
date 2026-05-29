"""Regression guard: thumbnail card height stays tall enough for both labels.

Background - 2026-05-29 (post-audit live finding)
==================================================
The right-panel thumbnail cards built by ThumbnailManager.create_thumbnail_widget
were sized 190 x 190 px. When BOTH a server description label and an
image-count label were present, total content height was 211 px (28 margins
+ 18 header + 120 image + 16 desc + 20 count + 9 spacing). The 21 px overflow
caused one label to disappear visually.

User-reported symptom: first click on patient shows description (e.g.
"Series 101"). After re-clicking and data is cached, description disappears
- only blue image count remains.

Fix (2026-05-29): widget + progress_border + glass_overlay heights bumped
from 190 to 215 px so both labels coexist.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
THUMBNAIL_MANAGER = (
    REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "utils" / "thumbnail_manager.py"
)


@pytest.fixture(scope="module")
def src() -> str:
    return THUMBNAIL_MANAGER.read_text(encoding="utf-8")


def test_widget_height_at_least_215(src: str) -> None:
    """Outer thumbnail QWidget must be at least 215 px tall."""
    assert "widget.setFixedSize(190, 215)" in src, (
        "Thumbnail outer widget reverted from 215 px. Both server description "
        "label and image-count label need at least 215 px to coexist."
    )
    assert "widget.setFixedSize(190, 190)" not in src, (
        "Thumbnail outer widget reverted to 190x190 - the description label "
        "will be clipped when both labels are present."
    )


def test_progress_border_matches_widget_height(src: str) -> None:
    """progress_border must mirror the outer widget height."""
    assert "progress_border.setFixedSize(190, 215)" in src, (
        "progress_border height does not mirror widget (215 px)."
    )


def test_glass_overlay_matches_widget_height(src: str) -> None:
    """glass_overlay must mirror the outer widget height."""
    assert "glass_overlay.setGeometry(0, 0, 190, 215)" in src, (
        "glass_overlay does not mirror widget height."
    )


def test_progress_text_is_y_centered_on_new_height(src: str) -> None:
    """The progress text label must be centered on the 215 px height."""
    assert "(215 - label_height) // 2" in src, (
        "Progress text overlay y-position not updated to the 215 px height."
    )


def test_description_label_still_created(src: str) -> None:
    """The card must still create desc_label."""
    assert "desc_label = QLabel(desc)" in src, (
        "desc_label was removed from create_thumbnail_widget. The user "
        "wants BOTH server description and image count visible."
    )


def test_image_count_label_still_created(src: str) -> None:
    """The card must still create count_label."""
    assert "count_label = QLabel(" in src, (
        "count_label was removed from create_thumbnail_widget."
    )
