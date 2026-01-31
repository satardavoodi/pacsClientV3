"""
Reception Data Styles Module

This module provides centralized styling for the Reception Data Tab.
All colors, fonts, and CSS styles are defined here for consistency and maintainability.
"""

from PacsClient.utils.css_utils import get_roboto_font_family

# ═══════════════════════════════════════════════════════════════════════════════
# COLOR CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

COLORS = {
    # Primary colors
    "primary": "#667eea",
    "primary_dark": "#5a6fd6",
    "secondary": "#764ba2",
    "secondary_dark": "#6a4292",
    
    # Status colors
    "success": "#4caf50",
    "success_dark": "#388e3c",
    "success_bg": "#1e3a1e",
    "warning": "#ff9800",
    "warning_dark": "#f57c00",
    "warning_bg": "#3a2e1e",
    "error": "#f44336",
    "error_dark": "#d32f2f",
    "error_bg": "#3a1e1e",
    "info": "#2196f3",
    "info_dark": "#1976d2",
    "info_bg": "#1e2a3a",
    
    # Background colors
    "bg_darkest": "#1a1a2e",
    "bg_dark": "#1e1e1e",
    "bg_medium": "#16213e",
    "bg_light": "#2b2b2b",
    "bg_lighter": "#2d2d2d",
    "bg_card": "#3a3a3a",
    
    # Border colors
    "border_dark": "#0f3460",
    "border_medium": "#444444",
    "border_light": "#555555",
    
    # Text colors
    "text_primary": "#ffffff",
    "text_secondary": "#aaaaaa",
    "text_muted": "#888888",
    "text_disabled": "#666666",
    
    # Gradient colors
    "gradient_start": "#667eea",
    "gradient_end": "#764ba2",
    "gradient_success_start": "#11998e",
    "gradient_success_end": "#38ef7d",
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
            background-color: #f0f0f0;
            width: 12px;
            border-radius: 6px;
        }}
        QScrollBar::handle:vertical {{
            background-color: #c0c0c0;
            border-radius: 6px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: #a0a0a0;
        }}
    """


def get_scroll_area_style():
    """Get styled QScrollArea CSS."""
    return f"""
        QScrollArea {{
            border: 2px solid {COLORS['border_medium']};
            border-radius: {BORDER_RADIUS['sm']}px;
            background-color: {COLORS['bg_light']};
        }}
    """


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

def is_rtl_content(text, sample_size=500):
    """
    Check if text contains predominantly RTL characters.
    
    Args:
        text: Text to check
        sample_size: Number of characters to sample
    
    Returns:
        bool: True if text is predominantly RTL
    """
    rtl_chars = 0
    ltr_chars = 0
    for char in text[:sample_size]:
        if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F':  # Arabic/Persian
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
