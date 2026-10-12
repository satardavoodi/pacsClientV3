"""Contrast is a property of the palette, so it can be checked without a screen.

This exists because of a real defect: the app set a stylesheet full of dark text
colours but never set a QPalette, so on a Windows machine in dark mode the
dialogs kept the system's dark background and the text became unreadable.

Two things guard against that returning:

* every text token is measured against the surface it is actually drawn on, in
  both themes, using the WCAG 2.1 relative-luminance formula;
* the stylesheet is checked for stray hex literals, since a hardcoded colour is
  exactly how one theme ends up with the other theme's text.

Thresholds follow WCAG AA: 4.5:1 for body text, 3:1 for large/bold text and for
UI boundaries such as borders.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from reception_crm.desktop import theme

THEMES = [theme.LIGHT, theme.DARK]
IDS = [p.name for p in THEMES]

BODY = 4.5
LARGE = 3.0


# --------------------------------------------------------------------------- #
# WCAG maths
# --------------------------------------------------------------------------- #
def _channel(value: float) -> float:
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    hex_colour = hex_colour.lstrip("#")
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)

def contrast(foreground: str, background: str) -> float:
    a, b = luminance(foreground), luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def test_the_maths_is_right():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contrast("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.01)


# --------------------------------------------------------------------------- #
# text on its real background
# --------------------------------------------------------------------------- #
def text_pairs(p: theme.Palette) -> list[tuple[str, str, str, float]]:
    """(description, foreground, background, minimum) for every text token."""
    return [
        # body text on the two main surfaces
        ("ink on surface", p.ink, p.surface, BODY),
        ("ink on canvas", p.ink, p.canvas, BODY),
        ("ink on subtle", p.ink, p.subtle, BODY),
        ("ink_soft on surface", p.ink_soft, p.surface, BODY),
        ("ink_soft on canvas", p.ink_soft, p.canvas, BODY),
        ("muted on surface", p.muted, p.surface, BODY),
        ("muted on canvas", p.muted, p.canvas, BODY),
        ("muted on subtle", p.muted, p.subtle, BODY),
        # small print — allowed the large-text threshold, no lower
        ("faint on surface", p.faint, p.surface, LARGE),
        ("faint on canvas", p.faint, p.canvas, LARGE),
        # brand
        ("brand_text on surface", p.brand_text, p.surface, BODY),
        ("brand_text on canvas", p.brand_text, p.canvas, BODY),
        ("on_brand on brand", p.on_brand, p.brand, LARGE),
        ("on_brand on brand_strong", p.on_brand, p.brand_strong, LARGE),
        ("ink on selection", p.ink, p.selection, BODY),
        # semantic text on its own tinted background (chips, callouts)
        ("ok on ok_bg", p.ok, p.ok_bg, BODY),
        ("warn on warn_bg", p.warn, p.warn_bg, BODY),
        ("bad on bad_bg", p.bad, p.bad_bg, BODY),
        ("info on info_bg", p.info, p.info_bg, BODY),
        # semantic text on plain surfaces (status-bar pills)
        ("ok on surface", p.ok, p.surface, BODY),
        ("warn on surface", p.warn, p.surface, BODY),
        ("bad on surface", p.bad, p.surface, BODY),
        ("info on surface", p.info, p.surface, BODY),
        # callout body text sits on the tint, not on the surface
        ("ink on info_bg", p.ink, p.info_bg, BODY),
        ("ink on warn_bg", p.ink, p.warn_bg, BODY),
        ("ink on bad_bg", p.ink, p.bad_bg, BODY),
        ("ink on ok_bg", p.ink, p.ok_bg, BODY),
        # sidebar has its own scale
        ("sidebar_title on sidebar", p.sidebar_title, p.sidebar, BODY),
        ("sidebar_text on sidebar", p.sidebar_text, p.sidebar, BODY),
        ("sidebar_sub on sidebar", p.sidebar_sub, p.sidebar, LARGE),
        ("sidebar_text on sidebar_hover", p.sidebar_text, p.sidebar_hover, BODY),
        # help affordance
        ("info on help_bg", p.info, p.help_bg, BODY),
        # disabled controls must stay readable, just clearly inactive
        ("disabled_text on disabled_bg", p.disabled_text, p.disabled_bg, LARGE),
    ]


@pytest.mark.parametrize("p", THEMES, ids=IDS)
def test_every_text_token_is_readable(p):
    failures = []
    for description, foreground, background, minimum in text_pairs(p):
        ratio = contrast(foreground, background)
        if ratio < minimum:
            failures.append(f"{description}: {ratio:.2f} < {minimum} ({foreground} on {background})")
    assert not failures, f"{p.name} theme contrast failures:\n" + "\n".join(failures)


@pytest.mark.parametrize("p", THEMES, ids=IDS)
def test_borders_are_visible_against_their_surface(p):
    """A border below 1.3:1 reads as no border at all."""
    pairs = [
        ("line on surface", p.line, p.surface),
        ("line on canvas", p.line, p.canvas),
        ("ok_line on ok_bg", p.ok_line, p.ok_bg),
        ("warn_line on warn_bg", p.warn_line, p.warn_bg),
        ("bad_line on bad_bg", p.bad_line, p.bad_bg),
        ("info_line on info_bg", p.info_line, p.info_bg),
    ]
    for description, border, background in pairs:
        assert contrast(border, background) >= 1.2, f"{p.name}: {description} is invisible"


@pytest.mark.parametrize("p", THEMES, ids=IDS)
def test_surfaces_are_distinguishable(p):
    """Cards must read as raised off the canvas."""
    assert contrast(p.surface, p.canvas) >= 1.05, f"{p.name}: cards vanish into the background"


def test_light_is_light_and_dark_is_dark():
    assert luminance(theme.LIGHT.canvas) > 0.5
    assert luminance(theme.DARK.canvas) < 0.1
    assert theme.DARK.dark is True and theme.LIGHT.dark is False


# --------------------------------------------------------------------------- #
# the stylesheet must not smuggle colours past the palette
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("p", THEMES, ids=IDS)
def test_stylesheet_contains_no_hardcoded_colours(p):
    """Every hex in the sheet has to have come from this palette."""
    known = {
        value.lower()
        for field in dataclasses.fields(p)
        if isinstance((value := getattr(p, field.name)), str) and value.startswith("#")
    }
    used = {match.lower() for match in re.findall(r"#[0-9a-fA-F]{6}\b", theme.stylesheet(p))}
    assert not (used - known), f"{p.name}: colours outside the palette: {sorted(used - known)}"


@pytest.mark.parametrize("p", THEMES, ids=IDS)
def test_report_css_contains_no_hardcoded_colours(p):
    known = {
        value.lower()
        for field in dataclasses.fields(p)
        if isinstance((value := getattr(p, field.name)), str) and value.startswith("#")
    }
    used = {match.lower() for match in re.findall(r"#[0-9a-fA-F]{6}\b", theme.report_css(p))}
    assert not (used - known), f"{p.name}: report colours outside the palette: {sorted(used - known)}"


@pytest.mark.parametrize("p", THEMES, ids=IDS)
def test_the_containers_that_broke_are_painted(p):
    """Regression guard for the dark-on-dark dialog bug.

    These are exactly the widgets that had no rule and so fell through to the
    desktop palette.
    """
    sheet = theme.stylesheet(p)
    for selector in ("QDialog", "QMessageBox", "QToolTip", "QMenu", "QCheckBox"):
        assert selector in sheet, f"{selector} has no explicit rule — it will inherit OS colours"


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def test_resolve_maps_modes_to_palettes():
    assert theme.resolve(theme.LIGHT_MODE) is theme.LIGHT
    assert theme.resolve(theme.DARK_MODE) is theme.DARK
    assert theme.resolve("nonsense") in (theme.LIGHT, theme.DARK)
    assert theme.resolve(theme.AUTO) in (theme.LIGHT, theme.DARK)


def test_every_mode_has_a_persian_label():
    for mode in (theme.AUTO, theme.LIGHT_MODE, theme.DARK_MODE):
        assert theme.MODE_LABELS[mode]
