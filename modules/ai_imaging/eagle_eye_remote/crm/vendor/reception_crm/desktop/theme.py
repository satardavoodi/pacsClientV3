"""Visual theme — one token set, two palettes, no OS colours anywhere.

The previous version was a single stylesheet of hardcoded light colours. That
worked only as long as Qt handed us a light default palette. On a Windows
machine set to dark mode it does not: widgets the stylesheet does not paint
explicitly (``QDialog``, ``QMessageBox``, tooltips, and every plain ``QLabel``
inside them) keep the system's dark background while our text stays near-black.
The result is dark-on-dark — unreadable, and only in some places, which is worse
than being uniformly wrong.

The fix has three parts, and all three are needed:

1. **Every colour is a token.** ``Palette`` holds them; ``LIGHT`` and ``DARK``
   are the two instances. Nothing in the UI writes a hex value.
2. **The palette is set explicitly.** ``apply()`` installs a fully specified
   ``QPalette`` on top of the Fusion style, so a widget with no stylesheet rule
   still lands on our colours rather than the desktop's.
3. **The stylesheet paints the containers too.** ``QDialog``, ``QMessageBox``
   and ``QToolTip`` now have their own rules, so nothing is left to chance.

Persian text is set in **IRANYekan**, bundled beside this module in ``fonts/``
and registered with Qt by :func:`load_fonts`. Segoe UI and Tahoma stay in the
stack behind it: both ship with Windows and shape Arabic script correctly, so a
build where the font files did not make it still renders readable Persian
instead of boxes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

LOG = logging.getLogger("reception_crm.desktop.theme")

#: The family name **as Qt reports it** after loading the TTFs — not the file
#: name, and not the name on the vendor's website. Qt matches on the family
#: recorded inside the font, and a stylesheet naming a family that does not
#: exist does not fail: it silently falls through to the next entry in the
#: stack, which looks exactly like "the font loaded fine".
FONT_FAMILY = "IRANYekanWeb"

#: The plain cut, not ``(fanum)``. The fanum files substitute Persian digits for
#: ASCII ones inside the font itself, which cannot be scoped — it would apply to
#: every number in the app, including ids, versions and the Latin screens.
_FONT_FILES = (
    "IRANYekanWebLight.ttf",
    "IRANYekanWebRegular.ttf",
    "IRANYekanWebBold.ttf",
)

FONT_STACK = f'"{FONT_FAMILY}", "Segoe UI", "Tahoma", sans-serif'

_fonts_loaded: bool | None = None


def load_fonts() -> bool:
    """Register the bundled IRANYekan cuts with Qt. Idempotent; never raises.

    Returns whether at least one cut loaded, so a caller can log it. Nothing
    depends on the answer: [FONT_STACK] falls through to Segoe UI on its own,
    and typography must never be a reason the app will not open.

    The result is cached because Qt keeps its own registry — calling
    ``addApplicationFont`` again on every theme switch would add duplicate
    entries for the same family.
    """
    global _fonts_loaded
    if _fonts_loaded is not None:
        return _fonts_loaded

    _fonts_loaded = False
    try:
        from PySide6.QtGui import QFontDatabase

        directory = Path(__file__).resolve().parent / "fonts"
        for name in _FONT_FILES:
            path = directory / name
            if not path.exists():
                LOG.warning("bundled font missing: %s", path)
                continue
            if QFontDatabase.addApplicationFont(str(path)) != -1:
                _fonts_loaded = True
            else:
                LOG.warning("Qt refused the font file: %s", path)
    except Exception as exc:  # noqa: BLE001 - styling never stops the app opening
        LOG.warning("could not register bundled fonts (%s)", type(exc).__name__)

    if not _fonts_loaded:
        LOG.warning("IRANYekan not loaded; falling back to %s", FONT_STACK)
    return _fonts_loaded


AUTO = "auto"
LIGHT_MODE = "light"
DARK_MODE = "dark"

MODE_LABELS = {
    AUTO: "خودکار (هماهنگ با ویندوز)",
    LIGHT_MODE: "روشن",
    DARK_MODE: "تیره",
}


# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Palette:
    """Every colour the UI can use, named by role rather than by hue.

    Roles are what keeps the two themes honest: ``ink`` is "the colour text on
    ``surface`` must be", so swapping the palette can never leave text and its
    background pointing at the same end of the scale.
    """

    name: str
    dark: bool

    # surfaces
    canvas: str          # window background, behind the cards
    surface: str         # cards, inputs, tables
    subtle: str          # table headers, disabled inputs, secondary fills
    line: str            # borders and separators

    # text
    ink: str             # primary text on `surface` / `canvas`
    ink_soft: str        # secondary text, still body-legible
    muted: str           # captions and hints
    faint: str           # technical footnotes, placeholder-weight text

    # brand
    brand: str           # primary buttons, focus rings, accents
    brand_strong: str    # hover state of the above
    brand_text: str      # brand-coloured text on `surface` (headings)
    on_brand: str        # text drawn on top of `brand`
    selection: str       # selected table row background

    # sidebar (its own scale — it is a dark slab in both themes)
    sidebar: str
    sidebar_hover: str
    sidebar_title: str
    sidebar_text: str
    sidebar_sub: str
    sidebar_border: str
    sidebar_border_hover: str

    # semantic
    ok: str
    warn: str
    bad: str
    info: str
    ok_bg: str
    warn_bg: str
    bad_bg: str
    info_bg: str
    ok_line: str
    warn_line: str
    bad_line: str
    info_line: str

    # help affordance
    help_bg: str
    help_line: str

    # disabled
    disabled_text: str
    disabled_bg: str


LIGHT = Palette(
    name="light",
    dark=False,
    canvas="#f1f5f9",
    surface="#ffffff",
    subtle="#f8fafc",
    line="#d9e1ea",
    ink="#0f172a",
    ink_soft="#334155",
    muted="#5b6878",
    faint="#78899c",
    brand="#0d6e6e",
    brand_strong="#0a5555",
    brand_text="#0a5555",
    on_brand="#ffffff",
    selection="#d6ecec",
    sidebar="#0b3b3b",
    sidebar_hover="#124a4a",
    sidebar_title="#ffffff",
    sidebar_text="#cfe6e6",
    sidebar_sub="#8cc2c2",
    sidebar_border="#2c6a6a",
    sidebar_border_hover="#4d9a9a",
    ok="#15803d",
    warn="#a4530a",
    bad="#b91c1c",
    info="#0369a1",
    ok_bg="#ecfdf5",
    warn_bg="#fffbeb",
    bad_bg="#fef2f2",
    info_bg="#f0f9ff",
    ok_line="#a7f3d0",
    warn_line="#fde68a",
    bad_line="#fecaca",
    info_line="#bae6fd",
    help_bg="#e8eff5",
    help_line="#cbd9e4",
    disabled_text="#7d8a99",
    disabled_bg="#f1f5f9",
)

# Not the light palette inverted: dark surfaces need desaturated, lightened
# accents or they vibrate, and the tinted callout backgrounds have to be dark
# enough that light text still clears 4.5:1 on top of them.
DARK = Palette(
    name="dark",
    dark=True,
    canvas="#0e1419",
    surface="#171f27",
    subtle="#1e2833",
    line="#2c3948",
    ink="#e8eef4",
    ink_soft="#c7d3de",
    muted="#a3b1c0",
    faint="#8494a5",
    brand="#2c9e9e",
    brand_strong="#37b9b9",
    brand_text="#6fd0d0",
    on_brand="#04201f",
    selection="#1d4444",
    sidebar="#0a2f2f",
    sidebar_hover="#11413f",
    sidebar_title="#ffffff",
    sidebar_text="#c3dede",
    sidebar_sub="#82b3b3",
    sidebar_border="#265c5c",
    sidebar_border_hover="#46908f",
    ok="#5bd68b",
    warn="#f0b64a",
    bad="#f28b8b",
    info="#5cc0f0",
    ok_bg="#10251b",
    warn_bg="#2a2110",
    bad_bg="#2b1618",
    info_bg="#0d2130",
    ok_line="#245c40",
    warn_line="#6a5317",
    bad_line="#743033",
    info_line="#1c4c68",
    help_bg="#1c2b38",
    help_line="#2f4356",
    disabled_text="#6b7a8a",
    disabled_bg="#141c24",
)

PALETTES = {LIGHT_MODE: LIGHT, DARK_MODE: DARK}


# --------------------------------------------------------------------------- #
# stylesheet
# --------------------------------------------------------------------------- #
def stylesheet(p: Palette) -> str:
    return f"""
QWidget {{
    font-family: {FONT_STACK};
    font-size: 14px;
    color: {p.ink};
}}

QMainWindow, #Content {{
    background: {p.canvas};
}}

/* Containers Qt would otherwise paint from the desktop palette. Without these
   a dark Windows theme shows our dark text on its own dark background. */
QDialog, QMessageBox {{
    background: {p.canvas};
    color: {p.ink};
}}
QMessageBox QLabel {{
    color: {p.ink};
}}
QToolTip {{
    background: {p.surface};
    color: {p.ink};
    border: 1px solid {p.line};
    border-radius: 6px;
    padding: 6px 9px;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QMenu {{
    background: {p.surface};
    color: {p.ink};
    border: 1px solid {p.line};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item:selected {{
    background: {p.selection};
    color: {p.ink};
}}

/* ---------- sidebar ---------- */
#Sidebar {{
    background: {p.sidebar};
    border: none;
}}
#BrandTitle {{
    color: {p.sidebar_title};
    font-size: 16px;
    font-weight: 700;
    padding: 0;
}}
#BrandSub {{
    color: {p.sidebar_sub};
    font-size: 11px;
    padding: 0;
}}
#Nav {{
    background: transparent;
    border: none;
    outline: none;
}}
#Nav::item {{
    color: {p.sidebar_text};
    padding: 11px 14px;
    margin: 2px 8px;
    border-radius: 8px;
}}
#Nav::item:selected {{
    background: {p.brand};
    color: {p.on_brand};
    font-weight: 600;
}}
#Nav::item:hover:!selected {{
    background: {p.sidebar_hover};
}}
QPushButton#SidebarAction {{
    background: transparent;
    color: {p.sidebar_text};
    border: 1px solid {p.sidebar_border};
    border-radius: 8px;
    margin: 6px 12px 0 12px;
    padding: 9px 12px;
    font-weight: 600;
}}
QPushButton#SidebarAction:hover {{
    background: {p.sidebar_hover};
    color: {p.sidebar_title};
    border-color: {p.sidebar_border_hover};
}}

/* ---------- cards ---------- */
QFrame#Card {{
    background: {p.surface};
    border: 1px solid {p.line};
    border-radius: 12px;
}}
#PageTitle {{
    font-size: 22px;
    font-weight: 700;
    color: {p.ink};
}}
#PageHint {{
    color: {p.muted};
    font-size: 13px;
}}
#KpiValue {{
    font-size: 26px;
    font-weight: 700;
    color: {p.brand_text};
}}
#KpiLabel {{
    color: {p.muted};
    font-size: 12px;
}}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit {{
    background: {p.surface};
    color: {p.ink};
    border: 1px solid {p.line};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {p.brand};
    selection-color: {p.on_brand};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {p.brand};
}}
QComboBox QAbstractItemView {{
    background: {p.surface};
    color: {p.ink};
    border: 1px solid {p.line};
    selection-background-color: {p.selection};
    selection-color: {p.ink};
}}

/* In RTL the spin buttons sit on the left, so the value needs room there or
   the arrows print on top of the digits. */
QSpinBox, QDoubleSpinBox {{
    padding-left: 24px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    width: 18px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top left;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom left;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {p.disabled_bg};
    color: {p.disabled_text};
}}
QCheckBox {{
    color: {p.ink};
    spacing: 7px;
}}
QCheckBox:disabled {{
    color: {p.disabled_text};
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {p.line};
    border-radius: 4px;
    background: {p.surface};
}}
QCheckBox::indicator:checked {{
    background: {p.brand};
    border-color: {p.brand};
}}

QPushButton {{
    background: {p.surface};
    color: {p.ink};
    border: 1px solid {p.line};
    border-radius: 8px;
    padding: 8px 16px;
}}
QPushButton:hover {{
    border-color: {p.brand};
}}
QPushButton:disabled {{
    color: {p.disabled_text};
    background: {p.disabled_bg};
}}
QPushButton#Primary {{
    background: {p.brand};
    color: {p.on_brand};
    border: 1px solid {p.brand};
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background: {p.brand_strong};
    border-color: {p.brand_strong};
}}
QPushButton#Primary:disabled {{
    background: {p.disabled_bg};
    color: {p.disabled_text};
    border-color: {p.line};
}}

/* ---------- data ---------- */
QTableWidget {{
    background: {p.surface};
    alternate-background-color: {p.subtle};
    color: {p.ink};
    border: 1px solid {p.line};
    border-radius: 10px;
    gridline-color: {p.line};
}}
QHeaderView::section {{
    background: {p.subtle};
    color: {p.muted};
    border: none;
    border-bottom: 1px solid {p.line};
    padding: 8px;
    font-weight: 600;
}}
QTableWidget::item {{
    padding: 6px;
}}
QTableWidget::item:selected {{
    background: {p.selection};
    color: {p.ink};
}}

QTextBrowser {{
    background: {p.surface};
    color: {p.ink};
    border: 1px solid {p.line};
    border-radius: 10px;
    padding: 10px;
}}

QTabWidget::pane {{
    border: 1px solid {p.line};
    border-radius: 10px;
    background: {p.surface};
}}
QTabBar::tab {{
    padding: 8px 16px;
    margin-right: 2px;
    border: 1px solid {p.line};
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    background: {p.subtle};
    color: {p.muted};
}}
QTabBar::tab:selected {{
    background: {p.surface};
    color: {p.ink};
    font-weight: 600;
}}

QStatusBar {{
    background: {p.surface};
    border-top: 1px solid {p.line};
    color: {p.muted};
}}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.line};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.faint};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---------- status pills (legacy status-bar text) ---------- */
#PillOk    {{ color: {p.ok};   font-weight: 600; }}
#PillWarn  {{ color: {p.warn}; font-weight: 600; }}
#PillBad   {{ color: {p.bad};  font-weight: 600; }}
#PillMuted {{ color: {p.muted}; }}

/* ---------- help affordances ---------- */
QToolButton#HelpButton {{
    background: {p.help_bg};
    color: {p.info};
    border: 1px solid {p.help_line};
    border-radius: 10px;
    font-size: 12px;
    font-weight: 700;
    padding: 0;
}}
QToolButton#HelpButton:hover {{
    background: {p.info};
    color: {p.on_brand};
    border-color: {p.info};
}}
QToolButton#HelpButton:focus {{
    border: 1px solid {p.brand};
}}

QFrame#HelpPopup {{
    background: {p.surface};
    border: 1px solid {p.line};
    border-radius: 12px;
}}
#HelpTitle {{
    font-size: 15px;
    font-weight: 700;
    color: {p.ink};
}}
#HelpHeading {{
    color: {p.brand_text};
    font-size: 12px;
    font-weight: 700;
}}
#HelpBody {{
    color: {p.ink_soft};
    font-size: 13px;
}}
#HelpTechnical {{
    color: {p.faint};
    font-size: 11px;
    font-family: Consolas, monospace;
}}
#BadgeRequired {{
    background: {p.bad_bg};
    color: {p.bad};
    border: 1px solid {p.bad_line};
    border-radius: 6px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 600;
}}
#BadgeOptional {{
    background: {p.subtle};
    color: {p.muted};
    border: 1px solid {p.line};
    border-radius: 6px;
    padding: 1px 7px;
    font-size: 11px;
}}
#RequiredStar {{
    color: {p.bad};
    font-weight: 700;
}}
#FieldLabel {{
    font-weight: 600;
    color: {p.ink};
}}
#FieldNote {{
    color: {p.muted};
    font-size: 12px;
}}
#SectionTitle {{
    font-size: 16px;
    font-weight: 700;
    color: {p.ink};
}}

/* ---------- status chips ---------- */
#ChipOk {{
    color: {p.ok};
    background: {p.ok_bg};
    border: 1px solid {p.ok_line};
    border-radius: 9px;
    padding: 3px 11px;
    font-weight: 600;
    font-size: 12px;
}}
#ChipWarn {{
    color: {p.warn};
    background: {p.warn_bg};
    border: 1px solid {p.warn_line};
    border-radius: 9px;
    padding: 3px 11px;
    font-weight: 600;
    font-size: 12px;
}}
#ChipBad {{
    color: {p.bad};
    background: {p.bad_bg};
    border: 1px solid {p.bad_line};
    border-radius: 9px;
    padding: 3px 11px;
    font-weight: 600;
    font-size: 12px;
}}
#ChipIdle {{
    color: {p.muted};
    background: {p.subtle};
    border: 1px solid {p.line};
    border-radius: 9px;
    padding: 3px 11px;
    font-size: 12px;
}}
#ChipBusy {{
    color: {p.info};
    background: {p.info_bg};
    border: 1px solid {p.info_line};
    border-radius: 9px;
    padding: 3px 11px;
    font-weight: 600;
    font-size: 12px;
}}

/* ---------- callouts ---------- */
QFrame#CalloutInfo {{ background: {p.info_bg}; border: 1px solid {p.info_line}; border-radius: 10px; }}
QFrame#CalloutWarn {{ background: {p.warn_bg}; border: 1px solid {p.warn_line}; border-radius: 10px; }}
QFrame#CalloutBad  {{ background: {p.bad_bg};  border: 1px solid {p.bad_line};  border-radius: 10px; }}
QFrame#CalloutOk   {{ background: {p.ok_bg};   border: 1px solid {p.ok_line};   border-radius: 10px; }}
#CalloutText {{ font-size: 13px; color: {p.ink}; }}
#CalloutIcon {{ font-weight: 700; color: {p.muted}; }}
QFrame#CalloutInfo #CalloutIcon {{ color: {p.info}; }}
QFrame#CalloutWarn #CalloutIcon {{ color: {p.warn}; }}
QFrame#CalloutBad  #CalloutIcon {{ color: {p.bad}; }}
QFrame#CalloutOk   #CalloutIcon {{ color: {p.ok}; }}
QToolButton#CalloutAction {{
    background: transparent;
    border: none;
    color: {p.brand_text};
    font-weight: 600;
    text-decoration: underline;
    padding: 0 4px;
}}

/* ---------- disclosure ---------- */
QToolButton#DisclosureToggle {{
    background: transparent;
    border: none;
    color: {p.brand_text};
    font-weight: 600;
    font-size: 13px;
    padding: 4px 0;
}}
QToolButton#DisclosureToggle:hover {{
    color: {p.brand_strong};
}}

/* ---------- prompt list ----------
   Its own name, not #Nav: the sidebar's palette is light-on-dark and would be
   invisible here, where the list sits on a card. */
QListWidget#PromptList {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#PromptList::item {{
    color: {p.ink};
    padding: 9px 12px;
    margin: 2px 0;
    border-radius: 8px;
}}
QListWidget#PromptList::item:selected {{
    background: {p.brand};
    color: {p.on_brand};
    font-weight: 600;
}}
QListWidget#PromptList::item:hover:!selected {{
    background: {p.subtle};
}}

QSplitter::handle {{
    background: transparent;
    width: 10px;
}}

/* ---------- setup wizard ---------- */
#WizardHeading {{
    font-size: 20px;
    font-weight: 700;
    color: {p.ink};
}}
#WizardLead {{
    color: {p.ink_soft};
    font-size: 13px;
}}
#StepDone {{
    color: {p.ok};
    background: {p.ok_bg};
    border: 1px solid {p.ok_line};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}}
#StepCurrent {{
    color: {p.on_brand};
    background: {p.brand};
    border: 1px solid {p.brand};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 700;
}}
#StepPending {{
    color: {p.muted};
    background: {p.subtle};
    border: 1px solid {p.line};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
}}
#StepArrow {{
    color: {p.faint};
    font-size: 13px;
}}
#FlowBox {{
    background: {p.surface};
    border: 1px solid {p.line};
    border-radius: 10px;
}}
#FlowTitle {{ font-weight: 700; color: {p.brand_text}; font-size: 13px; }}
#FlowRole  {{ color: {p.muted}; font-size: 11px; font-weight: 600; }}
#FlowNote  {{ color: {p.ink_soft}; font-size: 12px; }}
#FlowArrow {{ color: {p.brand}; font-size: 18px; font-weight: 700; }}

QProgressBar {{
    border: none;
    background: {p.line};
    height: 3px;
    border-radius: 2px;
}}
QProgressBar::chunk {{
    background: {p.brand};
    border-radius: 2px;
}}
"""


def report_css(p: Palette) -> str:
    """Styles for the HTML shown inside QTextBrowser.

    A rich-text document does not inherit the widget stylesheet, so the report
    body needs the tokens spelled out again or it renders black-on-dark.
    """
    return f"""
<style>
  body {{
    font-family: {FONT_STACK};
    font-size: 14px;
    color: {p.ink};
    line-height: 1.9;
  }}
  p, li, td, th {{ color: {p.ink}; }}
  h1, h2, h3, h4 {{ color: {p.brand_text}; }}
  a {{ color: {p.info}; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid {p.line}; padding: 6px 10px; text-align: right; }}
  th {{ background: {p.subtle}; color: {p.muted}; }}
  code, pre {{
    font-family: Consolas, monospace;
    background: {p.subtle};
    color: {p.ink_soft};
  }}
  hr {{ border: none; border-top: 1px solid {p.line}; }}
</style>
"""


# --------------------------------------------------------------------------- #
# active theme
# --------------------------------------------------------------------------- #
_active: Palette = LIGHT


def active() -> Palette:
    """The palette currently installed. Use this instead of hardcoding a hex."""
    return _active


def detect_mode() -> str:
    """What the desktop is set to, falling back to light when Qt can't say."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        hints = QGuiApplication.styleHints()
        scheme = getattr(hints, "colorScheme", None)
        if scheme is not None and scheme() == Qt.ColorScheme.Dark:
            return DARK_MODE
    except Exception:  # noqa: BLE001 - an unreadable desktop setting is not fatal
        pass
    return LIGHT_MODE


def resolve(mode: str) -> Palette:
    if mode == AUTO or mode not in PALETTES:
        mode = detect_mode()
    return PALETTES[mode]


def build_qpalette(p: Palette):
    """A fully specified QPalette.

    Every role is set, including the disabled group. Anything left unset would
    fall back to the desktop's own colours, which is the bug this replaces.
    """
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    pairs = [
        (QPalette.Window, p.canvas),
        (QPalette.WindowText, p.ink),
        (QPalette.Base, p.surface),
        (QPalette.AlternateBase, p.subtle),
        (QPalette.Text, p.ink),
        (QPalette.PlaceholderText, p.faint),
        (QPalette.Button, p.surface),
        (QPalette.ButtonText, p.ink),
        (QPalette.BrightText, p.bad),
        (QPalette.ToolTipBase, p.surface),
        (QPalette.ToolTipText, p.ink),
        (QPalette.Highlight, p.brand),
        (QPalette.HighlightedText, p.on_brand),
        (QPalette.Link, p.info),
        (QPalette.LinkVisited, p.brand_text),
        (QPalette.Light, p.surface),
        (QPalette.Midlight, p.subtle),
        (QPalette.Mid, p.line),
        (QPalette.Dark, p.faint),
        (QPalette.Shadow, p.line),
    ]
    for role, value in pairs:
        palette.setColor(role, QColor(value))

    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.HighlightedText):
        palette.setColor(QPalette.Disabled, role, QColor(p.disabled_text))
    palette.setColor(QPalette.Disabled, QPalette.Base, QColor(p.disabled_bg))
    palette.setColor(QPalette.Disabled, QPalette.Button, QColor(p.disabled_bg))
    return palette


def apply(app, mode: str = AUTO) -> Palette:
    """Install a theme on the application. Safe to call again to switch."""
    global _active, STYLESHEET, REPORT_CSS

    # Before the stylesheet, which names the family: a stylesheet applied first
    # would resolve the name against a database that does not have it yet, and
    # Qt does not re-resolve a family that failed to match.
    load_fonts()

    p = resolve(mode)
    _active = p
    STYLESHEET = stylesheet(p)
    REPORT_CSS = report_css(p)

    # Fusion ignores the Windows native theming that would otherwise repaint
    # controls with system colours regardless of our palette.
    try:
        app.setStyle("Fusion")
    except Exception:  # noqa: BLE001 - styling must never stop the app opening
        pass
    app.setPalette(build_qpalette(p))
    app.setStyleSheet(STYLESHEET)
    return p


# Module-level values for code that reads them once at import time. ``apply()``
# rebinds both, so anything rendered after startup uses the live theme.
STYLESHEET = stylesheet(LIGHT)
REPORT_CSS = report_css(LIGHT)
