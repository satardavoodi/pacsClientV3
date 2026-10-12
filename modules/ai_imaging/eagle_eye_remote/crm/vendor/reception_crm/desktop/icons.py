"""The app mark, and one stroke-drawn glyph per part of the app.

Everything here is SVG authored inline rather than a folder of PNGs, for three
reasons that matter to this project specifically:

* **Any DPI.** Clinic machines run at 100%, 125% and 150% scaling. A 16px PNG
  scaled to 20px is mush; a path is redrawn.
* **Any theme.** The stroke colour is substituted at render time, so the same
  glyph works on the dark sidebar and on a light card without a second asset.
* **Nothing to package.** No `datas` entry, no missing-file mode — a build
  cannot ship without its icons because they are source.

The glyphs are a single family: 24×24 box, 1.9 stroke, round caps and joins, no
fill except where a dot needs weight. Mixing an outline set with a filled one is
the fastest way to make an app look assembled from clip art.

``clear_cache()`` must be called when the theme changes — the rendered pixmaps
are tinted, so they are stale the moment the palette swaps.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

# --------------------------------------------------------------------------- #
# the app mark
# --------------------------------------------------------------------------- #
#: Brand constants for the logo. Deliberately NOT palette tokens: an app icon
#: must look identical in both themes and on a desktop that has neither.
LOGO_TEAL = "#0d6e6e"
LOGO_TEAL_DEEP = "#083f3f"
LOGO_WHITE = "#ffffff"

#: A report sheet with a spark — what the app does, not what a scanner does.
#: Two heavy lines rather than three light ones: at 16px a 3px gap closes up.
LOGO_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{LOGO_TEAL}"/>
      <stop offset="1" stop-color="{LOGO_TEAL_DEEP}"/>
    </linearGradient>
  </defs>
  <rect width="96" height="96" rx="22" fill="url(#tile)"/>
  <path d="M28 18 h26 l16 16 v44 a5 5 0 0 1 -5 5 H28 a5 5 0 0 1 -5 -5 V23 a5 5 0 0 1 5 -5 z"
        fill="{LOGO_WHITE}"/>
  <path d="M54 18 v16 h16" fill="none" stroke="{LOGO_TEAL}" stroke-width="4.5"
        stroke-linejoin="round" opacity="0.45"/>
  <path d="M33 47 h22 M33 60 h16" stroke="{LOGO_TEAL}" stroke-width="7" stroke-linecap="round"/>
  <path d="M67 52 l3.6 8.4 L79 64 l-8.4 3.6 L67 76 l-3.6 -8.4 L55 64 l8.4 -3.6 z"
        fill="{LOGO_WHITE}" stroke="{LOGO_TEAL_DEEP}" stroke-width="5" stroke-linejoin="round"/>
</svg>"""

#: The same mark without its tile, for placing on a coloured surface.
LOGO_GLYPH_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
  <path d="M28 18 h26 l16 16 v44 a5 5 0 0 1 -5 5 H28 a5 5 0 0 1 -5 -5 V23 a5 5 0 0 1 5 -5 z"
        fill="{LOGO_WHITE}"/>
  <path d="M54 18 v16 h16" fill="none" stroke="{LOGO_TEAL}" stroke-width="4.5"
        stroke-linejoin="round" opacity="0.45"/>
  <path d="M33 47 h22 M33 60 h16" stroke="{LOGO_TEAL}" stroke-width="7" stroke-linecap="round"/>
  <path d="M67 52 l3.6 8.4 L79 64 l-8.4 3.6 L67 76 l-3.6 -8.4 L55 64 l8.4 -3.6 z"
        fill="{LOGO_WHITE}" stroke="{LOGO_TEAL_DEEP}" stroke-width="5" stroke-linejoin="round"/>
</svg>"""

#: Sizes Windows actually asks for: Explorer tiles, taskbar, Alt-Tab, tray.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


# --------------------------------------------------------------------------- #
# the glyph family
# --------------------------------------------------------------------------- #
#: name -> inner SVG. ``{s}`` is replaced with the stroke colour.
GLYPHS: dict[str, str] = {
    # -- navigation ---------------------------------------------------------- #
    "dashboard": """
        <rect x="3.4" y="3.4" width="7.6" height="7.6" rx="2.2"/>
        <rect x="13" y="3.4" width="7.6" height="4.6" rx="2"/>
        <rect x="3.4" y="13" width="7.6" height="7.6" rx="2.2"/>
        <rect x="13" y="10" width="7.6" height="10.6" rx="2.2"/>""",
    "reports": """
        <rect x="3.4" y="3.4" width="17.2" height="17.2" rx="3.4"/>
        <path d="M8 16.6v-4.2M12 16.6v-7.2M16 16.6v-2.6"/>""",
    "conversations": """
        <path d="M20.5 10.7c0 4-3.8 7.1-8.5 7.1-1.1 0-2.1-.2-3-.5l-4.8 2 1.2-3.5a6.6 6.6 0 0 1-1.9-5.1c0-4 3.8-7.1 8.5-7.1s8.5 3.1 8.5 7.1z"/>
        <path d="M7.8 9.2h8.4M7.8 12.5h5.8"/>""",
    "queue": """
        <path d="M4 6.8h11M4 12h8M4 17.2h5"/>
        <path d="M14.6 16.6l2.1 2.1 4.1-4.6"/>""",
    "templates": """
        <path d="M9 3.4h6.2l4.4 4.4v9.8a2.2 2.2 0 0 1-2.2 2.2H9a2.2 2.2 0 0 1-2.2-2.2V5.6A2.2 2.2 0 0 1 9 3.4z"/>
        <path d="M15 3.6V8h4.4"/>
        <path d="M4.6 7.6A2.2 2.2 0 0 0 3.4 9.6v8.6a3.4 3.4 0 0 0 3.4 3.4h7.4"/>""",
    "console": """
        <rect x="3" y="4.2" width="18" height="15.6" rx="3.2"/>
        <path d="M7.4 9.6l3 2.6-3 2.6M13.2 15h4.2"/>""",
    "connections": """
        <path d="M10.2 13.6a4.2 4.2 0 0 0 6 .4l2.4-2.4a4.2 4.2 0 0 0-5.9-6l-1.4 1.4"/>
        <path d="M13.8 10.4a4.2 4.2 0 0 0-6-.4l-2.4 2.4a4.2 4.2 0 0 0 5.9 6l1.4-1.4"/>""",
    "prompts": """
        <path d="M21 11.4c0 3.9-3.8 7-8.5 7-1 0-2-.1-2.9-.4L4 20.4l1.5-3.7A6.6 6.6 0 0 1 4 11.4c0-3.9 3.8-7 8.5-7s8.5 3.1 8.5 7z"/>
        <path d="M12.5 8.2l1.1 2.6 2.6 1.1-2.6 1.1-1.1 2.6-1.1-2.6-2.6-1.1 2.6-1.1z"/>""",
    "help": """
        <circle cx="12" cy="12" r="8.6"/>
        <path d="M9.5 9.4a2.6 2.6 0 0 1 5 .9c0 1.8-2.5 2.2-2.5 3.8"/>
        <circle cx="12" cy="17.2" r="1" fill="{s}" stroke="none"/>""",
    # -- the architecture / connection areas --------------------------------- #
    "reception": """
        <path d="M4.2 20.6V6.4a1.8 1.8 0 0 1 1.3-1.7l7-2.1A1.3 1.3 0 0 1 14.2 3.8v16.8"/>
        <path d="M14.2 9.6h4.4a1.7 1.7 0 0 1 1.7 1.7v9.3"/>
        <path d="M2.4 20.6h19.2"/>
        <path d="M7.6 8.4h2.6M7.6 12.4h2.6M7.6 16.4h2.6"/>""",
    "desktop_ai": """
        <path d="M5.2 5.4h13.6a1.6 1.6 0 0 1 1.6 1.6v7.6H3.6V7a1.6 1.6 0 0 1 1.6-1.6z"/>
        <path d="M2.2 17.4h19.6l-1.2 1.6a1.7 1.7 0 0 1-1.4.6H4.8a1.7 1.7 0 0 1-1.4-.6z"/>
        <path d="M12 7.8l1.1 2.6 2.6 1.1-2.6 1.1-1.1 2.6-1.1-2.6-2.6-1.1 2.6-1.1z"/>""",
    "mobile": """
        <rect x="6.6" y="2.6" width="10.8" height="18.8" rx="2.8"/>
        <path d="M10.4 5.6h3.2"/>
        <circle cx="12" cy="17.8" r="1.1" fill="{s}" stroke="none"/>""",
    "ai": """
        <path d="M11.2 3.4l1.9 4.7 4.7 1.9-4.7 1.9-1.9 4.7-1.9-4.7-4.7-1.9 4.7-1.9z"/>
        <path d="M18 14.6l.9 2.2 2.2.9-2.2.9-.9 2.2-.9-2.2-2.2-.9 2.2-.9z"/>""",
    "app": """
        <rect x="3" y="4.2" width="18" height="12.8" rx="2.6"/>
        <path d="M8.6 20.8h6.8M12 17v3.8"/>""",
    # -- small status marks --------------------------------------------------- #
    "check": '<path d="M4.6 12.6l4.6 4.6L19.4 6.8"/>',
    "warning": """
        <path d="M12 3.8l9 15.6H3z"/>
        <path d="M12 9.6v4.4"/>
        <circle cx="12" cy="16.6" r="1" fill="{s}" stroke="none"/>""",
    "wand": """
        <path d="M4.6 19.4L15 9"/>
        <path d="M17.4 3.4l1 2.4 2.4 1-2.4 1-1 2.4-1-2.4-2.4-1 2.4-1z"/>
        <path d="M6.4 4.2l.7 1.7 1.7.7-1.7.7-.7 1.7-.7-1.7-1.7-.7 1.7-.7z"/>""",
}

#: Which glyph belongs to which sidebar page, by the page's Persian label.
NAV_GLYPHS: dict[str, str] = {
    "داشبورد": "dashboard",
    "گزارش‌های مدیریتی": "reports",
    "گفت‌وگوها و داده‌ها": "conversations",
    "صف گزارش‌دهی": "queue",
    "قالب‌های گزارش": "templates",
    "کنسول فرمان": "console",
    "اتصال‌ها": "connections",
    "دستورهای هوش مصنوعی": "prompts",
    "راهنما": "help",
}


def glyph_svg(name: str, colour: str, width: float = 1.9) -> str:
    """One glyph as a complete SVG document in the given colour."""
    inner = GLYPHS.get(name, GLYPHS["help"]).replace("{s}", colour)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{colour}" stroke-width="{width}" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{inner}</svg>"
    )


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render_svg(svg: str, size: int) -> QPixmap:
    """Rasterise an SVG at exactly ``size`` px, transparent behind."""
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QPixmap.fromImage(image)


@lru_cache(maxsize=512)
def _pixmap(name: str, colour: str, size: int, width: float) -> QPixmap:
    return render_svg(glyph_svg(name, colour, width), size)


def pixmap(name: str, colour: str, size: int = 20, width: float = 1.9) -> QPixmap:
    return _pixmap(name, colour, size, width)


def icon(name: str, colour: str, size: int = 20, width: float = 1.9) -> QIcon:
    return QIcon(pixmap(name, colour, size, width))


def nav_icon(name: str, size: int = 19) -> QIcon:
    """A sidebar glyph that changes colour when its row is selected.

    Qt asks for the Selected pixmap when a list row is current, so both states
    are supplied rather than tinting the whole row after the fact.
    """
    palette = theme.active()
    result = QIcon()
    result.addPixmap(pixmap(name, palette.sidebar_text, size), QIcon.Normal, QIcon.Off)
    result.addPixmap(pixmap(name, palette.on_brand, size), QIcon.Selected, QIcon.On)
    result.addPixmap(pixmap(name, palette.on_brand, size), QIcon.Active, QIcon.On)
    return result


def themed_icon(name: str, role: str = "brand", size: int = 20) -> QIcon:
    """A glyph in a palette colour, for use on cards and tabs."""
    palette = theme.active()
    colour = getattr(palette, role, palette.brand)
    return icon(name, colour, size)


def clear_cache() -> None:
    """Drop the tinted pixmaps. Call this whenever the palette changes."""
    _pixmap.cache_clear()


# --------------------------------------------------------------------------- #
# the logo
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=32)
def logo_pixmap(size: int = 32, tile: bool = True) -> QPixmap:
    return render_svg(LOGO_SVG if tile else LOGO_GLYPH_SVG, size)


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """The window/taskbar icon, carrying every size Windows may ask for.

    Built from the vector at each size rather than downscaling one bitmap: at
    16px a scaled 256px render loses the two lines that make the mark readable.
    """
    result = QIcon()
    for size in ICO_SIZES:
        result.addPixmap(logo_pixmap(size))
    return result
