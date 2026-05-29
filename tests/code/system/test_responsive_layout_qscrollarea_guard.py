"""Regression guard: responsive_layout.wrap_in_horizontal_scroll must NOT
call the bogus QAbstractScrollArea.setHorizontalScrollMode method.

Background - 2026-05-28 (Stage 9 audit)
========================================
Stage 1 of the live audit surfaced a recurring WARNING at every startup:

    [CustomTabManager] responsive scroll wrap unavailable
    ('PySide6.QtWidgets.QScrollArea' object has no attribute
    'setHorizontalScrollMode'); falling back to plain container

Root cause: PacsClient/utils/responsive_layout.py was calling
sa.setHorizontalScrollMode(QAbstractScrollArea.ScrollPerPixel) on a
QScrollArea. That method does NOT exist on QAbstractScrollArea - it
lives on QAbstractItemView. PySide6 raised AttributeError; the caller
in custom_tab_manager.py:119 caught it via try/except and fell back to
a NON-scrolling container, silently re-introducing the chip-strip
overlap defect on narrow monitors.

Fix: replaced with sa.horizontalScrollBar().setSingleStep(8).

This guard prevents accidental re-introduction during future refactors.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
RESPONSIVE_LAYOUT = REPO_ROOT / "PacsClient" / "utils" / "responsive_layout.py"


@pytest.fixture(scope="module")
def src() -> str:
    return RESPONSIVE_LAYOUT.read_text(encoding="utf-8")


def _code_lines_in_function(src: str, def_signature: str) -> list[str]:
    """Return only non-comment code lines inside the named function body."""
    idx = src.find(def_signature)
    assert idx >= 0, f"{def_signature!r} not found"
    end = src.find("\ndef ", idx + 1)
    body = src[idx : end if end > 0 else len(src)]
    out: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(line)
    return out


def test_no_setHorizontalScrollMode_on_QScrollArea(src: str) -> None:
    """The bogus call must not be re-introduced in code (comments OK)."""
    code_lines = _code_lines_in_function(src, "def wrap_in_horizontal_scroll(")
    offending = [ln for ln in code_lines if "setHorizontalScrollMode" in ln]
    assert not offending, (
        "wrap_in_horizontal_scroll reverted to setHorizontalScrollMode in code. "
        "That method does not exist on QScrollArea. PySide6 raises AttributeError, "
        "the caller swallows it, and chip-strip scroll silently disables. "
        f"Offending lines: {offending}"
    )


def test_QAbstractScrollArea_not_imported(src: str) -> None:
    """The class should not appear in the QtWidgets import block anymore."""
    import_start = src.find("from PySide6.QtWidgets import (")
    assert import_start >= 0, "QtWidgets import block reshaped - update guard"
    import_end = src.find(")", import_start)
    import_block = src[import_start:import_end]
    assert "QAbstractScrollArea" not in import_block, (
        "QAbstractScrollArea was re-added to the QtWidgets import block. "
        "It is not needed by any current helper; its presence usually means "
        "the setHorizontalScrollMode regression is about to be re-introduced."
    )


def test_horizontal_smoothness_uses_scrollbar_singleStep(src: str) -> None:
    """The proper Qt API for QScrollArea smoothness is the scrollbar's single step."""
    code_lines = _code_lines_in_function(src, "def wrap_in_horizontal_scroll(")
    body_text = "\n".join(code_lines)
    assert "horizontalScrollBar()" in body_text and "setSingleStep" in body_text, (
        "wrap_in_horizontal_scroll no longer calls "
        "sa.horizontalScrollBar().setSingleStep(...). If the smoothness is set "
        "via a different correct API, update this guard. The bogus call "
        "setHorizontalScrollMode must NOT be the replacement."
    )


def test_table_helper_still_uses_setHorizontalScrollMode_on_QTableView(src: str) -> None:
    """Sanity check: setHorizontalScrollMode IS valid on QTableView.

    set_table_column_policy at the bottom of the module calls
    setHorizontalScrollMode on a QTableView - that call IS correct
    (the method exists on QAbstractItemView, which QTableView inherits).
    This test exists so the 'no setHorizontalScrollMode' rule above
    is not over-applied to remove this valid usage too.
    """
    idx = src.find("def set_table_column_policy(")
    assert idx >= 0, "set_table_column_policy removed?"
    body = src[idx:]
    assert "setHorizontalScrollMode" in body and "QTableView" in body, (
        "set_table_column_policy lost its valid setHorizontalScrollMode call. "
        "The method is valid on QTableView; only the QScrollArea variant was "
        "the bug. Do not remove this one."
    )
