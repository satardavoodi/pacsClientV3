"""Trailing icon buttons on form fields are ROUNDED CHIPS, not sharp rails (2026-08-04).

User report (screenshot, red arrows): the blue icon buttons at the right of the
server picker, Patient ID, Patient Name, the date preset and both date fields
"have sharp corners and are slightly too large".

Root cause — the original "rail" design meant them to sit FLUSH against the
field's right edge (square left, rounded right, 1px separator). It never landed
flush: the button was `34 x (field_h - 4)` inside a shell of `field_h` with a 1px
border, so at the Home page's `field_h=36` it floated inside the shell and its
5px right corners never lined up with the shell's 6px ones. 5px on a 32px block
barely reads as a curve at all. Two authorities also disagreed about the width —
`setFixedSize` said 34px and the QSS `min-width`/`max-width` said 34px, and the
QSS one had to be kept in sync by hand.

All five arrowed controls are built by `_configure_icon_rail_button` +
`_icon_rail_btn_qss`, so both the defect and the fix live in exactly two places.
`AIPACS_FIELD_ICON_CHIP=0` restores the old rail byte-for-byte.
"""
from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


def _lfs():
    from PacsClient.utils import login_form_styles
    return login_form_styles


def _qss(chip: bool, monkeypatch) -> str:
    monkeypatch.setenv("AIPACS_FIELD_ICON_CHIP", "1" if chip else "0")
    return _lfs()._icon_rail_btn_qss(
        "QToolButton#X", border="#64748b", accent_soft="#1e3a5f", accent="#2563eb"
    )


# ── the flag ────────────────────────────────────────────────────────────────

def test_chip_defaults_on(monkeypatch):
    monkeypatch.delenv("AIPACS_FIELD_ICON_CHIP", raising=False)
    assert _lfs()._icon_chip_enabled() is True
    monkeypatch.setenv("AIPACS_FIELD_ICON_CHIP", "0")
    assert _lfs()._icon_chip_enabled() is False


# ── appearance ──────────────────────────────────────────────────────────────

def test_chip_corners_are_rounded_on_all_four_sides(monkeypatch):
    """THE REPORT: the corners must not be square."""
    qss = _qss(True, monkeypatch)
    radius = _lfs()._CHIP_RADIUS
    assert f"border-radius: {radius}px;" in qss
    # a per-corner radius is what made three corners square
    assert not re.search(r"border-radius:\s*\d+px\s+\d+px", qss), \
        "chip must use one uniform radius, not per-corner values"
    assert radius >= 5


def test_chip_drops_the_flush_rail_separator(monkeypatch):
    """A chip floats inside the field, so the attached-rail divider is wrong."""
    assert "border-left" not in _qss(True, monkeypatch)


def test_chip_qss_does_not_fight_setfixedsize(monkeypatch):
    """Geometry has ONE authority — _configure_icon_rail_button."""
    qss = _qss(True, monkeypatch)
    for prop in ("min-width", "max-width", "min-height", "max-height"):
        assert prop not in qss, f"{prop} in the QSS re-introduces a second authority"


def test_hover_and_pressed_still_light_up_and_decorative_stays_flat(monkeypatch):
    """The non-interactive Patient-Name icon must not look clickable."""
    qss = _qss(True, monkeypatch)
    assert ":hover" in qss and ":pressed" in qss
    assert '[decorative="true"]:hover' in qss


# ── size ────────────────────────────────────────────────────────────────────

def test_chip_is_smaller_than_the_old_rail_and_square():
    lfs = _lfs()
    for field_h in (36, 40):
        side = lfs._chip_side(field_h)
        assert side < lfs._ICON_RAIL_W, "the chip must be narrower than the old rail"
        assert side < field_h, "the chip must fit inside its field with room to spare"
        # square: the same value is used for width and height (see the button test)
        assert side == max(lfs._CHIP_MIN_SIDE, field_h - 12)
    assert lfs._chip_side(36) == 24
    assert lfs._chip_side(40) == 28


def test_chip_never_collapses_on_a_tiny_field():
    lfs = _lfs()
    assert lfs._chip_side(10) == lfs._CHIP_MIN_SIDE
    assert lfs._chip_side(0) == lfs._CHIP_MIN_SIDE


def test_configure_makes_a_square_button_and_shrinks_an_oversized_icon(monkeypatch):
    from PySide6.QtWidgets import QApplication, QToolButton
    QApplication.instance() or QApplication([])
    lfs = _lfs()
    monkeypatch.setenv("AIPACS_FIELD_ICON_CHIP", "1")

    btn = QToolButton()
    # the calendar field asks for an 18px glyph — too big for a 24px chip
    lfs._configure_icon_rail_button(
        btn, icon_name="fa5s.calendar-alt", tooltip="t", field_h=36, icon_size=18)
    assert btn.width() == btn.height() == 24
    assert btn.iconSize().width() <= 24 - 8, "glyph must keep breathing room"

    btn2 = QToolButton()
    lfs._configure_icon_rail_button(
        btn2, icon_name="fa5s.chevron-down", tooltip="t", field_h=40, icon_size=16)
    assert btn2.width() == btn2.height() == 28
    assert btn2.iconSize().width() == 16, "an already-small glyph must not be shrunk"


def test_right_inset_is_zero_on_the_legacy_path(monkeypatch):
    lfs = _lfs()
    monkeypatch.setenv("AIPACS_FIELD_ICON_CHIP", "1")
    assert lfs.icon_rail_right_margin(36) == lfs._CHIP_INSET > 0
    monkeypatch.setenv("AIPACS_FIELD_ICON_CHIP", "0")
    assert lfs.icon_rail_right_margin(36) == 0


# ── the kill switch really restores the old look ────────────────────────────

def test_kill_switch_restores_the_original_rail(monkeypatch):
    lfs = _lfs()
    qss = _qss(False, monkeypatch)
    assert "border-radius: 0 5px 5px 0;" in qss
    assert "border-left: 1px solid" in qss
    assert f"min-width: {lfs._ICON_RAIL_W}px;" in qss

    from PySide6.QtWidgets import QApplication, QToolButton
    QApplication.instance() or QApplication([])
    btn = QToolButton()
    lfs._configure_icon_rail_button(
        btn, icon_name="fa5s.chevron-down", tooltip="t", field_h=36, icon_size=16)
    assert (btn.width(), btn.height()) == (lfs._ICON_RAIL_W, 32)


def test_shell_qss_keeps_its_own_legacy_radius(monkeypatch):
    """The pre-theme shell used 6px where the themed QSS used 5px; the kill
    switch must reproduce BOTH, not flatten them to one value."""
    lfs = _lfs()
    monkeypatch.setenv("AIPACS_FIELD_ICON_CHIP", "0")
    shell = lfs._icon_rail_btn_qss(
        "QToolButton#X", border="#64748b", accent_soft="#1e3a5f",
        accent="#2563eb", legacy_radius=6)
    assert "border-radius: 0 6px 6px 0;" in shell


# ── every field type actually gets the inset ────────────────────────────────

@pytest.mark.parametrize("cls_name", ["LoginComboField", "LoginLineField", "LoginDateField"])
def test_every_field_insets_its_trailing_chip(cls_name, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    lfs = _lfs()
    monkeypatch.setenv("AIPACS_FIELD_ICON_CHIP", "1")

    kwargs = {"field_h": 36}
    if cls_name == "LoginLineField":
        kwargs["trailing_icon"] = "fa5s.sliders-h"
    w = getattr(lfs, cls_name)(**kwargs)
    margins = w.layout().contentsMargins()
    assert margins.right() == lfs._CHIP_INSET, f"{cls_name} does not inset its chip"
    assert (margins.left(), margins.top(), margins.bottom()) == (0, 0, 0), \
        "only the RIGHT margin may change — the text must not move"


def test_all_five_arrowed_controls_share_one_builder():
    """If a field ever hand-rolls its own trailing button, this fix stops
    covering it — the whole point is that there is one place to change."""
    from pathlib import Path
    src = Path(_lfs().__file__).read_text(encoding="utf-8", errors="replace")
    # chevron (combo), action (line), calendar (date) all go through the helper
    for obj_name in ("LoginFieldChevron", "LoginFieldAction", "LoginFieldCalendar"):
        assert f'setObjectName("{obj_name}")' in src
    assert src.count("_configure_icon_rail_button(") >= 6
