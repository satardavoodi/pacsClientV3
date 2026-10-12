"""Every part of the app must have a glyph, and every glyph must actually draw.

An icon set fails quietly in two ways: a page gets added with no entry and
silently falls back to the help mark, or an SVG has a typo and renders as a
blank square that nobody notices until a customer sees it. Both are checked
here by rasterising each glyph and confirming ink reached the canvas.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QIcon

from reception_crm.desktop import icons, theme


def ink(pixmap) -> int:
    """How many pixels the renderer actually painted."""
    image = pixmap.toImage()
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 8
    )


# --------------------------------------------------------------------------- #
# the glyph family
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", sorted(icons.GLYPHS))
def test_every_glyph_renders_something(qapp, name):
    assert ink(icons.pixmap(name, "#000000", 32)) > 20, f"{name} renders blank"


@pytest.mark.parametrize("name", sorted(icons.GLYPHS))
def test_every_glyph_survives_sixteen_pixels(qapp, name):
    """The size a taskbar and a small list actually use."""
    assert ink(icons.pixmap(name, "#000000", 16)) > 8, f"{name} disappears at 16px"


@pytest.mark.parametrize("name", sorted(icons.GLYPHS))
def test_glyphs_stay_inside_their_box(qapp, name):
    """A path spilling past the 24x24 viewBox gets clipped on screen."""
    image = icons.pixmap(name, "#000000", 48).toImage()
    edges = [
        (x, y)
        for x in range(image.width())
        for y in (0, image.height() - 1)
        if image.pixelColor(x, y).alpha() > 8
    ] + [
        (x, y)
        for y in range(image.height())
        for x in (0, image.width() - 1)
        if image.pixelColor(x, y).alpha() > 8
    ]
    assert not edges, f"{name} touches the edge of its box at {edges[:3]}"


def test_the_colour_is_actually_applied(qapp):
    red = icons.pixmap("help", "#ff0000", 32).toImage()
    hits = [
        red.pixelColor(x, y)
        for x in range(32)
        for y in range(32)
        if red.pixelColor(x, y).alpha() > 200
    ]
    assert hits, "nothing opaque was drawn"
    assert all(c.red() > c.green() and c.red() > c.blue() for c in hits)


# --------------------------------------------------------------------------- #
# coverage of the app
# --------------------------------------------------------------------------- #
def test_every_sidebar_page_has_its_own_glyph():
    """A page with no entry silently falls back to the help mark."""
    for label, name in icons.NAV_GLYPHS.items():
        assert name in icons.GLYPHS, f"{label} points at a glyph that does not exist: {name}"


def test_no_two_sidebar_pages_share_a_glyph():
    used = list(icons.NAV_GLYPHS.values())
    assert len(used) == len(set(used)), "two pages would look identical in the sidebar"


def test_the_architecture_diagram_has_a_glyph_per_box():
    from reception_crm.desktop import wizard
    from reception_crm.desktop.help import ARCHITECTURE_STEPS

    assert len(wizard.FLOW_GLYPHS) >= len(ARCHITECTURE_STEPS)
    for name in wizard.FLOW_GLYPHS:
        assert name in icons.GLYPHS


def test_sidebar_labels_match_the_real_pages():
    """Guards the mapping against a page being renamed."""
    from reception_crm.desktop import app as desktop_app

    assert set(icons.NAV_GLYPHS) == set(desktop_app.PAGE_LABELS), (
        "icons.NAV_GLYPHS and the sidebar have drifted apart"
    )


# --------------------------------------------------------------------------- #
# the app mark
# --------------------------------------------------------------------------- #
def test_the_logo_renders_at_every_windows_size(qapp):
    for size in icons.ICO_SIZES:
        assert ink(icons.logo_pixmap(size)) > size, f"logo is blank at {size}px"


def test_the_logo_fills_its_tile(qapp):
    """A tile icon should reach its corners — a floating glyph looks shrunken."""
    image = icons.logo_pixmap(64).toImage()
    assert image.pixelColor(32, 2).alpha() > 200, "top edge is empty"
    assert image.pixelColor(2, 32).alpha() > 200, "left edge is empty"


def test_the_app_icon_offers_every_size(qapp):
    available = {size.width() for size in icons.app_icon().availableSizes()}
    for size in icons.ICO_SIZES:
        assert size in available, f"the window icon has no {size}px variant"


def test_the_app_icon_is_not_null(qapp):
    assert not icons.app_icon().isNull()


def test_the_logo_is_theme_independent(qapp):
    """An app icon must look the same whatever the app's theme is."""
    theme.apply(qapp, theme.LIGHT_MODE)
    light = icons.logo_pixmap(64).toImage()
    theme.apply(qapp, theme.DARK_MODE)
    dark = icons.logo_pixmap(64).toImage()
    assert light == dark


# --------------------------------------------------------------------------- #
# theming
# --------------------------------------------------------------------------- #
def test_nav_icons_carry_a_selected_variant(qapp):
    theme.apply(qapp, theme.LIGHT_MODE)
    nav = icons.nav_icon("dashboard", 20)
    normal = nav.pixmap(20, 20, QIcon.Normal, QIcon.Off).toImage()
    selected = nav.pixmap(20, 20, QIcon.Selected, QIcon.On).toImage()
    assert normal != selected, "the sidebar glyph does not change when selected"


def test_clearing_the_cache_repaints_in_the_new_palette(qapp):
    theme.apply(qapp, theme.LIGHT_MODE)
    before = icons.pixmap("dashboard", theme.active().brand, 20).toImage()
    theme.apply(qapp, theme.DARK_MODE)
    icons.clear_cache()
    after = icons.pixmap("dashboard", theme.active().brand, 20).toImage()
    assert before != after, "glyphs kept the old theme's colour"
