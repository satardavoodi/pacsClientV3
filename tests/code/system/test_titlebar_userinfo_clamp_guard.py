"""Regression guard: TitleBar UserInfoContainer must stay bounded vertically.

Background — 2026-05-29 (Stage 9 follow-up)
============================================
The user_container in setup_user_info (PacsClient/pacs/workstation_ui/
mainwindow_ui.py) was constructed with setMinimumHeight(70) and
setMinimumWidth(170) but NO setMaximumHeight and NO setSizePolicy call.
Qt's default Preferred/Preferred policy let the pill grow vertically to
fill whatever space the title bar offered, rendering as a tall portrait
box (~170 x 120 in the live screenshot) that overflowed into the search
panel below.

Fix: clamp vertical growth with setMaximumHeight(74) and
setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed).
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
MAINWINDOW = REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py"


@pytest.fixture(scope="module")
def src() -> str:
    return MAINWINDOW.read_text(encoding="utf-8")


def _setup_user_info_body(src: str) -> str:
    idx = src.find("def setup_user_info(")
    assert idx >= 0, "setup_user_info removed?"
    end = src.find("    def ", idx + 1)
    return src[idx : end if end > 0 else len(src)]


def test_QSizePolicy_imported(src: str) -> None:
    import_start = src.find("from PySide6.QtWidgets import (")
    assert import_start >= 0
    import_end = src.find(")", import_start)
    import_block = src[import_start:import_end]
    assert "QSizePolicy" in import_block, (
        "QSizePolicy was removed from mainwindow_ui.py imports. "
        "It is needed for the user_container vertical clamp."
    )


def test_user_container_is_bounded(src: str) -> None:
    """The pill must not be free to grow without limit in EITHER axis.

    2026-08-02 (satar UI branch): the pill moved out of the flat title-bar
    QHBoxLayout into a dedicated right column (``title_bar_right``) and is now
    clamped on WIDTH (120-168) and stretches vertically inside that column.

    The original 2026-05-29 defect was unbounded vertical growth in a title bar
    that had no ceiling. That cannot recur: ``title_bar`` itself is clamped
    (``setMaximumHeight`` + Fixed vertical policy, pinned below), so the pill's
    vertical extent is bounded by its parent chain rather than by its own
    ``setMaximumHeight``. The invariant is preserved; the mechanism moved.
    """
    body = _setup_user_info_body(src)
    has_own_ceiling = "setMaximumHeight(" in body
    has_width_clamp = "setMaximumWidth(" in body and "setMinimumWidth(" in body
    assert has_own_ceiling or has_width_clamp, (
        "user_container lost every size clamp in setup_user_info. It must be "
        "bounded either by its own setMaximumHeight or by explicit width "
        "clamps inside the (clamped) title-bar right column."
    )


def test_user_container_vertical_growth_is_bounded_by_the_title_bar(src: str) -> None:
    """If the pill is vertically Expanding, its PARENT must supply the ceiling."""
    body = _setup_user_info_body(src)
    if "QSizePolicy.Expanding" not in body:
        pytest.skip("pill is not vertically expanding; its own clamp applies")
    title_body = _setup_title_bar_body(src)
    assert "self.title_bar.setMaximumHeight(" in title_body, (
        "the pill is vertically Expanding, so the title bar MUST cap the "
        "column it lives in — otherwise the 2026-05-29 tall-portrait-box "
        "overflow returns."
    )
    assert (
        "self.title_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)"
        in title_body
    )


def test_user_container_min_height_preserved(src: str) -> None:
    """A floor still anchors the pill so it looks consistent across themes.

    2026-08-02: lowered 70 -> 48 by the redesign (the pill is now a compact
    single-row chip, not a two-line block). The floor must still EXIST.
    """
    body = _setup_user_info_body(src)
    assert "setMinimumHeight(" in body, (
        "user_container lost its minimum-height floor entirely."
    )


def _setup_title_bar_body(src: str) -> str:
    idx = src.find("def setup_title_bar(")
    assert idx >= 0, "setup_title_bar removed?"
    end = src.find("    def ", idx + 1)
    return src[idx : end if end > 0 else len(src)]


def test_title_bar_has_max_height(src: str) -> None:
    """The title_bar QFrame must clamp its vertical growth.

    Post-audit live finding (2026-05-29): without a ceiling, the
    QVBoxLayout above let title_bar grow to ~180 px tall - rendering
    a big empty band between the AI-Pacs logo and the patient search
    panel.
    """
    body = _setup_title_bar_body(src)
    assert "self.title_bar.setMaximumHeight(" in body, (
        "title_bar lost its setMaximumHeight call. Without it the QFrame "
        "grows vertically to ~180 px, leaving an empty band between the "
        "AI-Pacs logo and the patient search area."
    )


def test_title_bar_uses_fixed_vertical_size_policy(src: str) -> None:
    body = _setup_title_bar_body(src)
    assert (
        "self.title_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)"
        in body
    ), (
        "title_bar lost its Fixed vertical size policy. Even with a max "
        "height the QVBoxLayout could still push it to its max; the Fixed "
        "policy plus 84-px floor + 94-px ceiling keeps it tightly bounded."
    )


def test_title_bar_min_height_preserved(src: str) -> None:
    body = _setup_title_bar_body(src)
    assert "self.title_bar.setMinimumHeight(84)" in body, (
        "title_bar lost setMinimumHeight(84). The Stage 9 follow-up added "
        "a ceiling on top; the 84 px floor remains the content sizing "
        "anchor (chip strip 70 + margins)."
    )
