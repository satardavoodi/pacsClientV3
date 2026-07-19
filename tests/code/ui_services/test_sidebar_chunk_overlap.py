"""Guard for the series-sidebar overlap-on-open fix (2026-07-19).

THE BUG
-------
The viewer's left series sidebar is a ``QGridLayout`` (one fixed-size 190×215
card per row). The single-study default render path ``_render_files_chunked``
appends a few cards per event-loop tick to avoid freezing the GUI. A
``QGridLayout`` only assigns a freshly ``addWidget``-ed card its cell geometry
on the NEXT layout pass — so with the container visible and painting enabled
between chunks, a just-added card could paint once at the (0,0) origin, stacked
on the cards already present, before the deferred layout moved it. That read as
"thumbnails overlap for <1s then snap into place".

THE FIX
-------
Bracket each chunk's adds in ``setUpdatesEnabled(False)`` … force the grid to
compute geometry (``layout.activate()``) … ``setUpdatesEnabled(True)``, so a
card is never painted before it is positioned.

The behavioural test below reproduces the exact mechanism on a bare
``QGridLayout`` (no patient widget needed): after ``addWidget`` with no layout
pass, the cards share the origin (overlap); after ``activate()`` they occupy
distinct, non-overlapping rows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QGridLayout, QWidget
from PySide6.QtCore import Qt


@pytest.fixture(scope="module")
def _app():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_sidebar_like_container():
    """A container + QGridLayout configured like the real series sidebar
    (`_pw_panels.py`): top-left aligned, small spacing, one card per row."""
    container = QWidget()
    grid = QGridLayout(container)
    grid.setContentsMargins(8, 6, 14, 6)
    grid.setHorizontalSpacing(6)
    grid.setVerticalSpacing(6)
    grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    container.resize(220, 900)
    return container, grid


def _add_cards(grid, n):
    cards = []
    for i in range(n):
        card = QWidget()
        card.setFixedSize(190, 215)   # the real card size
        grid.addWidget(card, i, 0, 1, 2)
        cards.append(card)
    return cards


def test_cards_overlap_before_layout_but_not_after_activate(_app):
    """Directly demonstrates the bug and the fix on a real QGridLayout."""
    container, grid = _make_sidebar_like_container()
    cards = _add_cards(grid, 6)

    # BEFORE any layout pass: geometry is unassigned, cards share the origin.
    positions_before = {(c.geometry().y()) for c in cards}
    assert len(positions_before) == 1, (
        "expected all freshly-added cards to share one (unpositioned) origin — "
        "this is the overlap the user sees"
    )

    # THE FIX: force the grid to compute geometry now.
    grid.activate()

    ys = [c.geometry().y() for c in cards]
    assert len(set(ys)) == len(cards), "every card must land on a distinct row"
    assert ys == sorted(ys), "cards must be ordered top-to-bottom"
    # No vertical overlap: each card starts at or below the previous card's end.
    for prev, nxt in zip(cards, cards[1:]):
        prev_bottom = prev.geometry().y() + prev.geometry().height()
        assert nxt.geometry().y() >= prev_bottom, "cards overlap vertically"


def test_activate_positions_incrementally_added_cards(_app):
    """Mirrors the chunked append: activate() after each chunk keeps every card
    positioned, so no intermediate state ever overlaps."""
    container, grid = _make_sidebar_like_container()
    all_cards = []
    for _chunk in range(4):                 # 4 chunks of 3 == 12 cards
        # (suppression would wrap these adds in the real code)
        chunk_cards = []
        for _ in range(3):
            card = QWidget()
            card.setFixedSize(190, 215)
            grid.addWidget(card, len(all_cards) + len(chunk_cards), 0, 1, 2)
            chunk_cards.append(card)
        all_cards.extend(chunk_cards)
        grid.activate()                     # the fix: position before next yield
        ys = [c.geometry().y() for c in all_cards]
        assert len(set(ys)) == len(all_cards), (
            "after activate() every card so far must be at a distinct position"
        )


# ---------------------------------------------------------------------------
# Source-pins: the fix is actually wired into the chunked render path
# ---------------------------------------------------------------------------


def _method_code(name: str) -> str:
    root = Path(__file__).resolve().parents[3]
    rel = "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py"
    src = (root / rel).read_text(encoding="utf-8", errors="ignore")
    body = src.split(f"def {name}", 1)[1].split("\n    def ", 1)[0]
    # strip docstring + comments so prose can't satisfy the assertions
    if '"""' in body:
        parts = body.split('"""')
        body = "".join(parts[2:]) if len(parts) >= 3 else body
    return "\n".join(l.split("#", 1)[0] for l in body.splitlines())


def test_chunked_render_brackets_adds_with_suppression_and_activate():
    code = _method_code("_render_files_chunked")
    assert "setUpdatesEnabled(False)" in code
    assert "setUpdatesEnabled(True)" in code
    assert "self.thumb_grid.activate()" in code
    # the suppression must be re-enabled in a finally so an exception mid-chunk
    # can never leave the sidebar frozen with painting disabled
    assert "finally:" in code
    # order: suppress -> add loop -> activate -> re-enable
    assert code.index("setUpdatesEnabled(False)") < code.index("_render_one_thumbnail_file")
    assert code.index("_render_one_thumbnail_file") < code.index("self.thumb_grid.activate()")
    assert code.index("self.thumb_grid.activate()") < code.rindex("setUpdatesEnabled(True)")


def test_kill_switch_present_and_default_on():
    code = _method_code("_render_files_chunked")
    assert "AIPACS_SIDEBAR_CHUNK_SUPPRESS" in code
    assert 'os.getenv("AIPACS_SIDEBAR_CHUNK_SUPPRESS", "1") != "0"' in code


def test_token_cancellation_still_guards_the_chunk_chain():
    """The stale-render cancellation must survive the change."""
    code = _method_code("_render_files_chunked")
    assert "_sidebar_build_token" in code
    assert "QTimer.singleShot(0" in code
