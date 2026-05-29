"""Regression guards for the 2026-05-29 UI polish batch.

User-reported issues addressed:
1. Title bar maxHeight 94 was too tight - patient tabs were vertically clipped.
   Bumped to 110.
2. Right-panel thumbnail grid vertical spacing was 6 px - with the new 215 px
   thumbnail cards, rows overlapped. Bumped to 14 px. Right margin 14 -> 22 so
   the dotted thumb border isn't truncated near the scrollbar (round-3 later
   bumped 22 -> 30; the min-panel-width guard does the load-bearing work).
3. Patient list rows had vertical separator gridlines. User wants those gone
   from data rows. Disabled with setShowGrid(False). Header keeps its
   border-right via QHeaderView::section.

These are silent visual regressions if reverted - no exception thrown -
so structural guards are the only reliable defence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
MAINWINDOW = REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py"
RIGHT_PANEL = REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "right_panel_widget.py"
PATIENT_TABLE = REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "patient_table_widget.py"


@pytest.fixture(scope="module")
def mainwindow_src() -> str:
    return MAINWINDOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def right_panel_src() -> str:
    return RIGHT_PANEL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def patient_table_src() -> str:
    return PATIENT_TABLE.read_text(encoding="utf-8")


def test_title_bar_max_height_at_least_110(mainwindow_src: str) -> None:
    """Title bar must allow at least 110 px so patient tab content isn't clipped."""
    assert "self.title_bar.setMaximumHeight(110)" in mainwindow_src, (
        "Title bar maxHeight reverted to a tighter value. Patient tabs need "
        "the chip strip (70 px) + close button + name + ID label - 94 px was "
        "too tight. Bumped to 110 on 2026-05-29 after user reported tab "
        "clipping. See post-audit UI polish batch."
    )
    assert "self.title_bar.setMaximumHeight(94)" not in mainwindow_src, (
        "Title bar maxHeight reverted to 94 - patient tab content will clip."
    )


def test_thumbnail_grid_vertical_spacing_at_least_14(right_panel_src: str) -> None:
    """Right-panel grid vertical spacing must be at least 14 px - with the
    215 px tall thumbnail cards, 6 px was too tight and rows overlapped."""
    assert "setVerticalSpacing(14)" in right_panel_src or \
           "setVerticalSpacing(15)" in right_panel_src or \
           "setVerticalSpacing(16)" in right_panel_src, (
        "Right-panel content_grid vertical spacing reverted below 14 px. "
        "The 215 px thumbnail cards will overlap vertically. See 2026-05-29 "
        "user-reported regression."
    )
    assert "setVerticalSpacing(6)" not in right_panel_src, (
        "setVerticalSpacing(6) reintroduced - thumbnails will overlap again."
    )


def test_thumbnail_grid_right_margin_at_least_22(right_panel_src: str) -> None:
    """Right-panel grid right margin must be at least 22 px for visual
    breathing room. 2026-05-29 round-3 note: the right margin alone is NOT
    the load-bearing fix anymore - AlignLeft on a fixed-width card means
    the card sits at left_margin regardless of right margin. The
    setMinimumWidth bump (see test_right_panel_min_width_guard.py) is what
    guarantees the dotted border clears the scrollbar. We still require
    >= 22 here for visual breathing room at wider widths."""
    pattern = r"setContentsMargins\(\s*8\s*,\s*6\s*,\s*(\d+)\s*,\s*6\s*\)"
    m = re.search(pattern, right_panel_src)
    assert m is not None, (
        "Right-panel content_grid setContentsMargins(8, 6, N, 6) literal "
        "not found. The layout's right margin can't be verified."
    )
    right_margin = int(m.group(1))
    assert right_margin >= 22, (
        "Right-panel content_grid right margin is %d px - must be >= 22 px "
        "so dotted thumb borders have breathing room at wider widths." % right_margin
    )
    assert "setContentsMargins(8, 6, 14, 6)" not in right_panel_src, (
        "Right margin reverted to 14 px - dotted borders will clip again."
    )


def test_patient_table_grid_disabled(patient_table_src: str) -> None:
    """Patient list data rows must not show vertical separator gridlines.
    Header keeps its separators via the QHeaderView::section border-right rule."""
    assert "self.results_table.setShowGrid(False)" in patient_table_src, (
        "Patient table reverted to showing grid lines on data rows. User "
        "explicitly asked for vertical separators ONLY in the header, NOT "
        "between data cells. See 2026-05-29 UI polish batch."
    )
