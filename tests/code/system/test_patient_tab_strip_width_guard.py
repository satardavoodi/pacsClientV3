"""Regression guards for the patient-tab strip width + height (round 2 fix).

Background - 2026-05-29 (post-UI-polish second iteration)
==========================================================
After the first UI polish batch, user reported:
1. Tab strip was still squeezed to ~350 px (only 1 tab visible). The
   sibling addStretch() in title_layout absorbed all horizontal slack,
   leaving tab_area at its sizeHint.
2. PatientTabWidget (70 px tall) was visually clipped at the bottom
   because the chip strip max_height also = 70 px (zero buffer).

Fixes:
- mainwindow_ui.py setup_title_bar: replace addWidget(tab_area) + addStretch()
  with addWidget(tab_area, 1). tab_area now claims leftover horizontal
  space so multiple tabs fit before scrolling.
- custom_tab_manager.py setup_title_bar_tabs: bump
  wrap_in_horizontal_scroll(max_height=70) to max_height=80. 10 px buffer
  so 70 px patient tab content isn't clipped at the bottom.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
MAINWINDOW = REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py"
TAB_MANAGER = (
    REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "custom_tab_manager.py"
)


@pytest.fixture(scope="module")
def mainwindow_src() -> str:
    return MAINWINDOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tab_manager_src() -> str:
    return TAB_MANAGER.read_text(encoding="utf-8")


def test_tab_area_has_horizontal_stretch_factor(mainwindow_src: str) -> None:
    """tab_area must be added to title_layout with stretch factor >= 1
    so it claims the leftover horizontal space."""
    assert "title_layout.addWidget(self.tab_area, 1)" in mainwindow_src, (
        "tab_area lost its horizontal stretch factor. Without it the chip "
        "strip is squeezed to its sizeHint and only 1 patient tab is "
        "visible before horizontal scrolling kicks in. See 2026-05-29 "
        "user-reported regression."
    )
    # Specifically forbid the no-stretch form.
    assert "title_layout.addWidget(self.tab_area)\n" not in mainwindow_src, (
        "tab_area is being added without a stretch factor - the chip "
        "strip will be squeezed again."
    )


def test_no_absorbing_addStretch_between_tab_area_and_right_tab_area(
    mainwindow_src: str,
) -> None:
    """The standalone title_layout.addStretch() between tab_area and
    right_tab_area must be removed - it was absorbing the horizontal
    space that should go to the patient tab strip."""
    # Look in the setup_title_bar body specifically.
    idx = mainwindow_src.find("def setup_title_bar(")
    assert idx >= 0
    end = mainwindow_src.find("\n    def ", idx + 1)
    body = mainwindow_src[idx : end if end > 0 else len(mainwindow_src)]
    # The forbidden pattern is a bare addStretch() (no args, no factor).
    assert "title_layout.addStretch()" not in body, (
        "title_layout.addStretch() is back between tab_area and "
        "right_tab_area. It absorbs horizontal space that should make "
        "the chip strip wider. Use addWidget(self.tab_area, 1) instead."
    )


def test_chip_strip_max_height_at_least_80(tab_manager_src: str) -> None:
    """The wrap_in_horizontal_scroll max_height for the chip strip must
    be at least 80 px so the 70 px PatientTabWidget isn't clipped at the
    bottom."""
    assert "max_height=80," in tab_manager_src or \
           "max_height=84," in tab_manager_src or \
           "max_height=90," in tab_manager_src, (
        "Chip strip max_height reverted below 80 px. PatientTabWidget is "
        "fixed at 70 px - without a buffer the bottom edge clips visually. "
        "See 2026-05-29 user-reported regression."
    )
    assert "max_height=70," not in tab_manager_src, (
        "Chip strip max_height reverted to 70 px (matched PatientTabWidget "
        "exactly = zero buffer). Tab bottom edge will clip again."
    )


def test_no_trailing_addStretch_after_scroll_area() -> None:
    """No title_bar_layout.addStretch() should appear after the scroll area
    is added with stretch=1. A trailing addStretch with the same factor
    splits horizontal space 50/50 and pushes the tabs into the center."""
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[3]
        / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "custom_tab_manager.py"
    ).read_text(encoding="utf-8")
    # Look in setup_title_bar_tabs body specifically.
    idx = src.find("def setup_title_bar_tabs")
    assert idx >= 0
    end = src.find("\n    def ", idx + 1)
    body = src[idx : end if end > 0 else len(src)]
    # Any addStretch on the OUTER title_bar_layout is a smell. The inner
    # title_bar_tabs_layout.addStretch(1) inside the fallback is OK.
    bad = [
        ln for ln in body.splitlines()
        if "self.title_bar_layout.addStretch" in ln
    ]
    assert not bad, (
        "title_bar_layout.addStretch() reintroduced after the scroll area. "
        "It splits horizontal space with the scroll_area (also stretch=1) and "
        "pushes patient tabs to the centre. Tabs must left-align - see "
        "2026-05-29 user-reported alignment regression. Offending lines: "
        f"{bad}"
    )


def test_inner_chip_layout_has_trailing_addStretch() -> None:
    """The inner title_bar_tabs_layout MUST contain a trailing addStretch(1)
    so chips are left-packed inside the QScrollArea viewport.

    Round-3 removed the OUTER addStretch but ALSO had no INNER addStretch.
    With widgetResizable=True, the QScrollArea expands the container to the
    viewport width, and the QHBoxLayout has no expanding child or stretch
    so Qt distributed the leftover horizontal space evenly around the
    chips — they rendered CENTRED in the title bar instead of pinned left.

    Round-4 restores the INNER addStretch(1). QSpacerItem.sizeHint() is
    (0, 0) so it does NOT contribute to the layout's preferred width,
    therefore horizontal scrolling still works correctly when chip-strip
    natural width exceeds the viewport.

    _add_title_bar_tab_widget uses count()-1 as insert_index → new chips
    are inserted BEFORE this stretch, preserving left-to-right order.
    """
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[3]
        / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "custom_tab_manager.py"
    ).read_text(encoding="utf-8")
    idx = src.find("def setup_title_bar_tabs")
    assert idx >= 0
    end = src.find("\n    def ", idx + 1)
    body = src[idx : end if end > 0 else len(src)]
    assert "self.title_bar_tabs_layout.addStretch(1)" in body, (
        "title_bar_tabs_layout.addStretch(1) is missing from "
        "setup_title_bar_tabs. Without it, widgetResizable=True expands the "
        "chip container to the viewport width and the chips appear CENTRED "
        "instead of left-aligned. See 2026-05-29 round-4 user-reported "
        "alignment regression."
    )


def test_add_title_bar_tab_widget_inserts_before_stretch() -> None:
    """_add_title_bar_tab_widget must use count()-1 as insert_index so new
    chips are placed BEFORE the trailing addStretch.

    Without count()-1 (e.g. naive addWidget or count()), the stretch ends
    up between the chips, breaking the left-pack ordering.
    """
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[3]
        / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "custom_tab_manager.py"
    ).read_text(encoding="utf-8")
    idx = src.find("def _add_title_bar_tab_widget")
    assert idx >= 0
    end = src.find("\n    def ", idx + 1)
    body = src[idx : end if end > 0 else len(src)]
    assert "self.title_bar_tabs_layout.count() - 1" in body, (
        "_add_title_bar_tab_widget no longer inserts at count()-1. The "
        "trailing addStretch in title_bar_tabs_layout requires this offset "
        "so new chips are placed BEFORE the stretch (preserving left-pack "
        "order). See 2026-05-29 round-4 alignment regression."
    )
