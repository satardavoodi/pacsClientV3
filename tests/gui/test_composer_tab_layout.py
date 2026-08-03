"""Guard: switching composer tabs must not move the action buttons (2026-07-28).

THE REPORTED BUG: selecting the **Correction** tab adds a "Select report…"
toolbar above the editor. That toolbar's 44 px were ADDED to the composer
instead of being taken out of the editor, so the composer grew and the action
row (+ / mic / Modalities / Turbo / send) was pushed past the bottom of the
window and became unreachable.

THE CAUSE: `UnifiedComposer.__init__` pinned the editor with
`self.box.setFixedHeight(140)`. `setFixedHeight` sets the minimum AND the
maximum, so `_sync_composer_heights_for_tab()`'s later `setMaximumHeight(96)`
was inert — a layout honours the minimum when min > max. The compensation the
code *intended* to perform had never actually worked.

THE FIX: the editor's height is owned by `_sync_composer_heights_for_tab()`,
which sets only the MAXIMUM per tab and leaves the minimum at a floor. A layout
clamps a child's size hint to its maximum, so the composer requests exactly
`base - toolbar` (constant total) while staying free to shrink toward the floor
when the parent has less to give.

These are real Qt widget tests on the offscreen platform — a source-pin could
not have caught this, because the old code *looked* correct.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

#: Tabs that show a toolbar above the editor, plus the plain one.
_TOOLBAR_TABS = ("transcribe", "correction", "normal_template")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def page(qapp):
    """A host that mimics the real page: history (stretch 1) + composer (0)."""
    from modules.EchoMind.viewer_chat.ai_chat_widgets import UnifiedComposer

    host = QWidget()
    history = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 10)
    lay.setSpacing(0)
    composer = UnifiedComposer()
    lay.addWidget(history, 1)
    lay.addWidget(composer, 0)
    host.resize(1100, 749)
    host.show()

    def settle(n: int = 4):
        for _ in range(n):
            qapp.processEvents()

    settle()
    yield host, history, composer, settle
    host.close()
    host.deleteLater()
    qapp.processEvents()


def _controls_bottom(host, composer) -> int:
    ctl = composer.controls
    return ctl.mapTo(host, ctl.rect().bottomLeft()).y()


# ── 1. the reported bug ─────────────────────────────────────────────────────

def test_composer_height_is_identical_across_toolbar_tabs(page):
    """The whole bug in one assertion."""
    host, _history, composer, settle = page
    heights = {}
    for tab in _TOOLBAR_TABS:
        composer.switch_tab(tab)
        settle()
        heights[tab] = composer.height()
    assert len(set(heights.values())) == 1, (
        f"composer changes height between tabs {heights} — the toolbar is being "
        "added to the composer instead of taken out of the editor"
    )


def test_the_toolbar_height_comes_out_of_the_editor(page):
    host, _history, composer, settle = page
    composer.switch_tab("transcribe")
    settle()
    plain_box = composer.box.height()

    composer.switch_tab("correction")
    settle()
    corr_box = composer.box.height()

    bar = composer.corr_bar.height()
    assert composer.corr_bar.isVisible()
    assert plain_box - corr_box == bar, (
        f"editor shrank by {plain_box - corr_box}px but the toolbar is {bar}px"
    )


def test_action_buttons_stay_inside_the_window_on_every_tab(page):
    host, _history, composer, settle = page
    for tab in _TOOLBAR_TABS + ("standard",):
        composer.switch_tab(tab)
        settle()
        bottom = _controls_bottom(host, composer)
        assert bottom <= host.height(), (
            f"[{tab}] action row bottom={bottom} is below the window "
            f"({host.height()}) — the buttons are clipped"
        )


def test_the_editor_is_never_pinned_with_setfixedheight():
    """The exact call that made the compensation inert.

    Comment lines are stripped before matching: `__init__` deliberately quotes
    the old `self.box.setFixedHeight(...)` line in a comment so the next reader
    knows why it must not come back.
    """
    import inspect

    from modules.EchoMind.viewer_chat import ai_chat_widgets

    src = inspect.getsource(ai_chat_widgets.UnifiedComposer.__init__)
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "self.box.setFixedHeight(" not in code, (
        "setFixedHeight sets minimum AND maximum, so the per-tab "
        "setMaximumHeight() can never shrink the editor"
    )


def test_the_editor_has_a_shrinkable_vertical_policy():
    """`Fixed` vertically would make the minimum/maximum inert again."""
    from PySide6.QtWidgets import QSizePolicy

    from modules.EchoMind.viewer_chat import ai_chat_widgets

    composer = ai_chat_widgets.UnifiedComposer()
    try:
        assert composer.box.sizePolicy().verticalPolicy() != QSizePolicy.Fixed
    finally:
        composer.deleteLater()


# ── 2. no ratchet: switching back and forth must be stable ──────────────────

def test_repeated_tab_switching_is_stable(page):
    """A height derived from the layout's own output oscillates. Ours must not."""
    host, _history, composer, settle = page
    seen: dict[str, set] = {}
    for i in range(24):
        tab = _TOOLBAR_TABS[i % len(_TOOLBAR_TABS)]
        composer.switch_tab(tab)
        settle()
        seen.setdefault(tab, set()).add((composer.height(), composer.box.height()))
    for tab, values in seen.items():
        assert len(values) == 1, f"[{tab}] height oscillates across switches: {values}"


def test_returning_to_the_first_tab_restores_the_original_height(page):
    host, _history, composer, settle = page
    composer.switch_tab("transcribe")
    settle()
    before = (composer.height(), composer.box.height())
    for tab in ("correction", "normal_template", "standard", "correction"):
        composer.switch_tab(tab)
        settle()
    composer.switch_tab("transcribe")
    settle()
    assert (composer.height(), composer.box.height()) == before


# ── 3. the layout adapts to the available space ─────────────────────────────

@pytest.mark.parametrize("window_h", [749, 640, 560, 480, 420, 360, 300])
def test_buttons_survive_a_shrinking_window(page, window_h):
    host, _history, composer, settle = page
    host.resize(1100, window_h)
    composer.switch_tab("correction")
    settle()
    bottom = _controls_bottom(host, composer)
    assert bottom <= window_h, (
        f"at {window_h}px the action row bottom={bottom} is outside the window"
    )


def test_the_editor_absorbs_the_squeeze_not_the_buttons(page):
    """When the parent genuinely denies space, the editor gives it up."""
    host, history, composer, settle = page
    composer.switch_tab("correction")
    settle()
    roomy_box = composer.box.height()
    controls_h = composer.controls.height()

    history.setMinimumHeight(560)          # starve the composer
    host.resize(1100, 700)
    settle(6)

    assert composer.box.height() < roomy_box, "the editor did not give up space"
    assert composer.box.height() >= composer._composer_box_min_h, (
        "the editor shrank below its usable floor"
    )
    assert composer.controls.height() >= composer.controls.minimumHeight(), (
        "the controls row was squeezed instead of the editor"
    )
    assert controls_h >= composer.controls.height()


def test_the_editor_recovers_when_space_returns(page):
    host, history, composer, settle = page
    composer.switch_tab("correction")
    settle()
    original = composer.box.height()

    history.setMinimumHeight(560)
    host.resize(1100, 700)
    settle(6)
    assert composer.box.height() < original

    history.setMinimumHeight(0)
    host.resize(1100, 749)
    settle(8)
    assert composer.box.height() == original, "the editor did not recover"


# ── 4. the editor stays usable ──────────────────────────────────────────────

def test_editor_never_collapses_to_nothing(page):
    host, history, composer, settle = page
    history.setMinimumHeight(700)
    host.resize(1100, 720)
    for tab in _TOOLBAR_TABS:
        composer.switch_tab(tab)
        settle(6)
        assert composer.box.height() >= composer._composer_box_min_h
        assert composer.box.isVisible()


def test_only_the_active_tabs_toolbar_is_visible(page):
    host, _history, composer, settle = page
    for tab, nt, corr in (
        ("transcribe", False, False),
        ("correction", False, True),
        ("normal_template", True, False),
    ):
        composer.switch_tab(tab)
        settle()
        assert composer.nt_bar.isVisible() is nt, f"[{tab}] nt_bar visibility"
        assert composer.corr_bar.isVisible() is corr, f"[{tab}] corr_bar visibility"
