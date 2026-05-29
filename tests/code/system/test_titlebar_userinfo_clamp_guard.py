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


def test_user_container_has_max_height(src: str) -> None:
    body = _setup_user_info_body(src)
    assert "setMaximumHeight(" in body, (
        "user_container in setup_user_info lost its setMaximumHeight call. "
        "Without it the pill grows vertically to fill the title bar, "
        "rendering as a tall portrait box that overflows into the search "
        "panel below."
    )


def test_user_container_uses_fixed_vertical_size_policy(src: str) -> None:
    body = _setup_user_info_body(src)
    assert (
        "QSizePolicy.Preferred, QSizePolicy.Fixed" in body
        or "QSizePolicy.Fixed" in body
    ), (
        "user_container lost its Fixed vertical size policy. Without it the "
        "QHBoxLayout in the title bar lets the pill stretch vertically."
    )


def test_user_container_min_height_preserved(src: str) -> None:
    body = _setup_user_info_body(src)
    assert "setMinimumHeight(70)" in body, (
        "user_container lost setMinimumHeight(70). The 70 px floor anchors "
        "the pill so it looks consistent across themes."
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
