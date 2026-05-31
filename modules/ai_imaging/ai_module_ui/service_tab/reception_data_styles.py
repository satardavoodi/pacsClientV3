"""
Reception Data Styles Module

This module provides centralized styling for the Reception Data Tab.
All colors, fonts, and CSS styles are defined here for consistency and maintainability.
"""

import re
from html import unescape

from PacsClient.utils.css_utils import get_roboto_font_family
from PacsClient.utils.scroll_style import get_scroll_area_style as get_shared_scroll_area_style

# Strippers so HTML markup never skews RTL/LTR detection. <style>/<script>
# block *contents* (all Latin CSS/JS — Qt's toHtml() emits a big <style> block)
# must be removed wholesale, not just their tags, then comments, then tags.
_STYLE_SCRIPT_RE = re.compile(r"<(?:style|script)\b[^>]*>.*?</(?:style|script)>",
                              re.IGNORECASE | re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]*>")
# Unicode blocks that denote Persian/Arabic (RTL) script.
_RTL_RANGES = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
)

# ═══════════════════════════════════════════════════════════════════════════════
# COLOR CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

COLORS = {
    # Primary accent — single unified steel-blue used for all icons, titles, active states
    "primary": "#4a9fd4",
    "primary_dark": "#3a8cbf",
    # secondary now equals primary (was purple; unified to avoid multi-hue clutter)
    "secondary": "#4a9fd4",
    "secondary_dark": "#3a8cbf",

    # Semantic status colors — used ONLY for state indicators (not decorative icons)
    "success": "#3fb950",
    "success_dark": "#2ea043",
    "success_bg": "#0d2318",
    "warning": "#d29922",
    "warning_dark": "#b37c00",
    "warning_bg": "#2d2100",
    "error": "#f85149",
    "error_dark": "#da3633",
    "error_bg": "#2d0f0f",
    # info = primary (was separate vivid blue; unified)
    "info": "#4a9fd4",
    "info_dark": "#3a8cbf",
    "info_bg": "#0d1f2d",

    # Background colors
    "bg_darkest": "#1a1a2e",
    "bg_dark": "#1e1e1e",
    "bg_medium": "#252a30",
    "bg_light": "#2b2b2b",
    "bg_lighter": "#2d2d2d",
    "bg_card": "#3a3a3a",

    # Border colors — unified neutral-dark tones (no more vivid blue borders)
    "border_dark": "#1f2937",
    "border_medium": "#374151",
    "border_light": "#4b5563",

    # Text colors
    "text_primary": "#ffffff",
    "text_secondary": "#aaaaaa",
    "text_muted": "#888888",
    "text_disabled": "#666666",

    # Gradient colors
    "gradient_start": "#4a9fd4",
    "gradient_end": "#3a8cbf",
    "gradient_success_start": "#3fb950",
    "gradient_success_end": "#2ea043",
}

# ═══════════════════════════════════════════════════════════════════════════════
# FONT CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

FONTS = {
    "primary": "'Tahoma', 'Segoe UI', sans-serif",
    "persian": "'IRANYekan', 'B Nazanin', 'Tahoma', sans-serif",
    "monospace": "'Consolas', 'Courier New', monospace",
    "roboto": get_roboto_font_family('regular'),
    "roboto_medium": get_roboto_font_family('medium'),
    "roboto_bold": get_roboto_font_family('bold'),
}

FONT_SIZES = {
    "xs": 10,
    "sm": 11,
    "md": 12,
    "lg": 13,
    "xl": 14,
    "xxl": 16,
    "title": 18,
    "header": 20,
}

# ═══════════════════════════════════════════════════════════════════════════════
# SPACING CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

SPACING = {
    "xs": 4,
    "sm": 6,
    "md": 8,
    "lg": 10,
    "xl": 12,
    "xxl": 15,
    "section": 20,
}

BORDER_RADIUS = {
    "sm": 4,
    "md": 6,
    "lg": 8,
    "xl": 10,
    "round": 50,
}

# ═══════════════════════════════════════════════════════════════════════════════
# STYLE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_main_background_style():
    """Get the main widget background style."""
    return f"""
        QWidget {{
            background-color: {COLORS['bg_dark']};
        }}
    """


def get_group_box_style(color_key="info", title_color=None, bg_color=None, border_color=None):
    """
    Get styled QGroupBox CSS.
    
    Args:
        color_key: One of 'success', 'warning', 'error', 'info', 'primary'
        title_color: Override title color
        bg_color: Override background color
        border_color: Override border color
    
    Returns:
        str: CSS stylesheet for QGroupBox
    """
    color_map = {
        "success": (COLORS["success"], COLORS["success_bg"]),
        "warning": (COLORS["warning"], COLORS["warning_bg"]),
        "error": (COLORS["error"], COLORS["error_bg"]),
        "info": (COLORS["info"], COLORS["info_bg"]),
        "primary": (COLORS["primary"], COLORS["bg_medium"]),
        "default": (COLORS["text_secondary"], COLORS["bg_light"]),
    }
    
    accent, bg = color_map.get(color_key, color_map["default"])
    title_clr = title_color or accent
    background = bg_color or bg
    border = border_color or accent
    
    return f"""
        QGroupBox {{
            background-color: {background};
            border: 2px solid {border};
            border-radius: {BORDER_RADIUS['md']}px;
            margin-top: {SPACING['md']}px;
            padding-top: {SPACING['xl']}px;
            font-family: {FONTS['primary']};
            font-size: {FONT_SIZES['xl']}px;
            font-weight: bold;
            color: {COLORS['text_primary']};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 3px 8px;
            color: {title_clr};
        }}
    """


def get_button_style(variant="primary", size="md"):
    """
    Get styled QPushButton CSS.
    
    Args:
        variant: One of 'primary', 'success', 'warning', 'error', 'info', 'secondary'
        size: One of 'sm', 'md', 'lg'
    
    Returns:
        str: CSS stylesheet for QPushButton
    """
    color_map = {
        "primary": (COLORS["primary"], COLORS["primary_dark"]),
        "secondary": (COLORS["secondary"], COLORS["secondary_dark"]),
        "success": (COLORS["success"], COLORS["success_dark"]),
        "warning": (COLORS["warning"], COLORS["warning_dark"]),
        "error": (COLORS["error"], COLORS["error_dark"]),
        "info": (COLORS["info"], COLORS["info_dark"]),
    }
    
    size_map = {
        "sm": (FONT_SIZES["sm"], "6px 12px"),
        "md": (FONT_SIZES["md"], "8px 16px"),
        "lg": (FONT_SIZES["lg"], "10px 20px"),
    }
    
    bg, hover_bg = color_map.get(variant, color_map["primary"])
    font_size, padding = size_map.get(size, size_map["md"])
    
    return f"""
        QPushButton {{
            background-color: {bg};
            color: {COLORS['text_primary']};
            border: none;
            border-radius: {BORDER_RADIUS['sm']}px;
            padding: {padding};
            font-family: {FONTS['primary']};
            font-size: {font_size}px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
        }}
        QPushButton:pressed {{
            background-color: {hover_bg}cc;
        }}
        QPushButton:disabled {{
            background-color: {COLORS['text_disabled']};
            color: {COLORS['text_muted']};
        }}
    """


def get_gradient_button_style(start_color=None, end_color=None, size="md"):
    """
    Get gradient styled QPushButton CSS.
    
    Args:
        start_color: Gradient start color
        end_color: Gradient end color
        size: One of 'sm', 'md', 'lg'
    
    Returns:
        str: CSS stylesheet for QPushButton with gradient
    """
    start = start_color or COLORS["gradient_success_start"]
    end = end_color or COLORS["gradient_success_end"]
    
    size_map = {
        "sm": (FONT_SIZES["sm"], "6px 12px", BORDER_RADIUS['sm']),
        "md": (FONT_SIZES["lg"], "10px 25px", BORDER_RADIUS['md']),
        "lg": (FONT_SIZES["xl"], "12px 30px", BORDER_RADIUS['lg']),
    }
    
    font_size, padding, radius = size_map.get(size, size_map["md"])
    
    return f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {start}, stop:1 {end});
            color: {COLORS['text_primary']};
            border: none;
            border-radius: {radius}px;
            padding: {padding};
            font-family: {FONTS['primary']};
            font-size: {font_size}px;
            font-weight: bold;
            min-width: 100px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {start}dd, stop:1 {end}dd);
        }}
        QPushButton:pressed {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {start}aa, stop:1 {end}aa);
        }}
        QPushButton:disabled {{
            background: {COLORS['text_disabled']};
            color: {COLORS['text_muted']};
        }}
    """


def get_label_style(color="primary", size="md", bold=False):
    """
    Get styled QLabel CSS.
    
    Args:
        color: One of 'primary', 'secondary', 'muted', 'success', 'warning', 'error', 'info'
        size: One of 'xs', 'sm', 'md', 'lg', 'xl', 'xxl', 'title', 'header'
        bold: Whether to make text bold
    
    Returns:
        str: CSS stylesheet for QLabel
    """
    color_map = {
        "primary": COLORS["text_primary"],
        "secondary": COLORS["text_secondary"],
        "muted": COLORS["text_muted"],
        "success": COLORS["success"],
        "warning": COLORS["warning"],
        "error": COLORS["error"],
        "info": COLORS["info"],
        "accent": COLORS["primary"],
    }
    
    text_color = color_map.get(color, COLORS["text_primary"])
    font_size = FONT_SIZES.get(size, FONT_SIZES["md"])
    font_weight = "bold" if bold else "normal"
    
    return f"""
        QLabel {{
            color: {text_color};
            font-family: {FONTS['primary']};
            font-size: {font_size}px;
            font-weight: {font_weight};
            background: transparent;
        }}
    """


def get_card_style(hover=True):
    """
    Get styled card widget CSS.
    
    Args:
        hover: Whether to include hover effect
    
    Returns:
        str: CSS stylesheet for card widget
    """
    hover_style = f"""
        QWidget:hover {{
            background-color: {COLORS['bg_card']};
            border-color: {COLORS['info']};
        }}
    """ if hover else ""
    
    return f"""
        QWidget {{
            background-color: {COLORS['bg_lighter']};
            border: 2px solid {COLORS['border_medium']};
            border-radius: {BORDER_RADIUS['sm']}px;
        }}
        {hover_style}
    """


def get_text_edit_style(rtl=False):
    """
    Get styled QTextEdit CSS.
    
    Args:
        rtl: Whether to set RTL direction
    
    Returns:
        str: CSS stylesheet for QTextEdit
    """
    direction = "rtl" if rtl else "ltr"
    font = FONTS['persian'] if rtl else FONTS['primary']
    
    return f"""
        QTextEdit {{
            background-color: {COLORS['text_primary']};
            color: #333333;
            border: none;
            padding: 25px;
            font-family: {font};
            font-size: {FONT_SIZES['xl']}px;
        }}
        QScrollBar:vertical {{
            border: 1px solid #4b5563;
            background: #1f2937;
            width: 12px;
            margin: 12px 0px 12px 0px;
            border-radius: 6px;
        }}
        QScrollBar::handle:vertical {{
            background: #374151;
            border-radius: 5px;
            min-height: 40px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: #4b5563;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 12px;
            width: 12px;
            background: transparent;
            border: none;
            subcontrol-origin: margin;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QScrollBar::up-arrow:vertical,
        QScrollBar::down-arrow:vertical {{
            width: 0px;
            height: 0px;
        }}
    """


def get_scroll_area_style():
    """Get styled QScrollArea CSS."""
    return get_shared_scroll_area_style()


def get_dialog_style():
    """Get styled QDialog CSS."""
    return f"""
        QDialog {{
            background-color: {COLORS['bg_darkest']};
        }}
    """


def get_header_gradient_style():
    """Get header with gradient background."""
    return f"""
        QWidget {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {COLORS['gradient_start']}, stop:1 {COLORS['gradient_end']});
            border: none;
        }}
    """


def get_toolbar_style():
    """Get toolbar style."""
    return f"""
        QWidget {{
            background-color: {COLORS['bg_medium']};
            border-bottom: 1px solid {COLORS['border_dark']};
        }}
    """


def get_footer_style():
    """Get footer style."""
    return f"""
        QWidget {{
            background-color: {COLORS['bg_medium']};
            border-top: 1px solid {COLORS['border_dark']};
        }}
    """


def get_progress_dialog_style():
    """Get styled QProgressDialog CSS."""
    return f"""
        QProgressDialog {{
            background-color: {COLORS['bg_light']};
            color: {COLORS['text_primary']};
            font-family: {FONTS['primary']};
        }}
        QProgressBar {{
            border: 2px solid {COLORS['border_medium']};
            border-radius: 5px;
            text-align: center;
            background-color: {COLORS['bg_dark']};
            color: {COLORS['text_primary']};
        }}
        QProgressBar::chunk {{
            background-color: {COLORS['info']};
            border-radius: 3px;
        }}
        QPushButton {{
            background-color: {COLORS['error']};
            color: {COLORS['text_primary']};
            border: none;
            border-radius: {BORDER_RADIUS['sm']}px;
            padding: 5px 15px;
            font-family: {FONTS['primary']};
        }}
    """


def get_status_badge_style(status="pending"):
    """
    Get status badge style.
    
    Args:
        status: One of 'completed', 'in_progress', 'pending'
    
    Returns:
        str: CSS stylesheet for status badge
    """
    status_colors = {
        "completed": COLORS["success"],
        "in_progress": COLORS["warning"],
        "pending": COLORS["error"],
    }
    
    bg_color = status_colors.get(status, COLORS["text_disabled"])
    
    return f"""
        QLabel {{
            background-color: {bg_color};
            color: {COLORS['text_primary']};
            font-family: {FONTS['primary']};
            font-size: {FONT_SIZES['sm']}px;
            font-weight: bold;
            border-radius: {BORDER_RADIUS['xl']}px;
            padding: 4px 12px;
        }}
    """


def get_toolbar_button_style(color):
    """
    Get toolbar button style.
    
    Args:
        color: Background color for the button
    
    Returns:
        str: CSS stylesheet for toolbar button
    """
    return f"""
        QPushButton {{
            background-color: {color};
            color: {COLORS['text_primary']};
            border: none;
            border-radius: {BORDER_RADIUS['sm']}px;
            padding: 6px 12px;
            font-family: {FONTS['primary']};
            font-size: {FONT_SIZES['sm']}px;
            font-weight: bold;
            min-width: 30px;
        }}
        QPushButton:hover {{
            background-color: {color}dd;
        }}
        QPushButton:pressed {{
            background-color: {color}aa;
        }}
    """


def get_image_viewer_style():
    """Get image viewer style."""
    return f"""
        QGraphicsView {{
            border: 2px solid {COLORS['border_medium']};
            border-radius: {BORDER_RADIUS['sm']}px;
            background-color: {COLORS['bg_dark']};
        }}
    """


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def is_rtl_content(text, sample_size=4000):
    """
    Check if text is predominantly RTL (Persian/Arabic).

    HTML reports are stripped of tags/entities first so that markup and
    attributes (which are Latin: ``<p style=...>``, ``font-family`` \u2026) do not
    skew the count toward LTR. The dominant script of the *visible* text then
    decides direction: a report that is, say, 85% Persian reads right-to-left
    even when it embeds English terms like "MRI" or "Disc Bulging".

    Args:
        text: Text or HTML to check.
        sample_size: Max number of *visible* characters to inspect (after tags
            are removed) \u2014 large enough to cover a full report.

    Returns:
        bool: True if Persian/Arabic letters outnumber Latin letters.
    """
    if not text:
        return False
    try:
        visible = _STYLE_SCRIPT_RE.sub(" ", text)
        visible = _HTML_COMMENT_RE.sub(" ", visible)
        visible = _HTML_TAG_RE.sub(" ", visible)
        visible = unescape(visible)
    except Exception:
        visible = text

    rtl_chars = 0
    ltr_chars = 0
    for char in visible[:sample_size]:
        o = ord(char)
        if any(lo <= o <= hi for lo, hi in _RTL_RANGES):
            rtl_chars += 1
        elif 'a' <= char.lower() <= 'z':
            ltr_chars += 1
    return rtl_chars > ltr_chars


def get_font_for_content(text):
    """
    Get appropriate font based on content.
    
    Args:
        text: Text content to analyze
    
    Returns:
        str: Font family CSS value
    """
    if is_rtl_content(text):
        return FONTS['persian']
    return FONTS['primary']
