"""Centralized QSS builders for the web-browser module (2026-06-07).

Single source of truth for the browser's visual language so every button,
input, card, and panel shares one radius scale and one theme-token palette.

Rules:
- Pure string builders — NO Qt imports (headless tests import this file
  directly without QtWebEngine).
- Colors come from the live theme-token dict (``PacsClient.utils
  .theme_manager``); hex literals below are builder fallbacks only.
- Radius scale: panels 12 / groups & cards 10 / controls 8 / address pill 16.
"""

from __future__ import annotations

RADIUS_PANEL = 12
RADIUS_GROUP = 10
RADIUS_CONTROL = 8
RADIUS_PILL = 16


def _tok(t: dict, key: str, fallback: str) -> str:
    try:
        value = t.get(key)
    except AttributeError:
        value = None
    return value or fallback


def tool_button_qss(t: dict) -> str:
    """36x36 toolbar icon buttons (back/forward/reload/home/...)."""
    return f"""
        QPushButton {{
            background-color: {_tok(t, 'panel_alt_bg', '#1d2533')};
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: {RADIUS_CONTROL}px;
            color: {_tok(t, 'text_primary', '#f8fafc')};
        }}
        QPushButton:hover {{
            background-color: {_tok(t, 'menu_hover_bg', '#2a3a52')};
            border-color: {_tok(t, 'accent_hover', '#60a5fa')};
        }}
        QPushButton:pressed {{
            background-color: {_tok(t, 'accent_pressed', '#1d4ed8')};
            border-color: {_tok(t, 'accent_pressed', '#1d4ed8')};
        }}
        QPushButton:disabled {{
            background-color: {_tok(t, 'panel_bg', '#111927')};
            border-color: {_tok(t, 'border', '#33405a')};
            color: {_tok(t, 'text_muted', '#93a4b7')};
        }}
    """


def icon_button_qss(t: dict) -> str:
    """Borderless inline icon buttons (list rows, panel headers)."""
    return f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            border-radius: {RADIUS_CONTROL}px;
            padding: 2px;
        }}
        QPushButton:hover {{
            background-color: {_tok(t, 'menu_hover_bg', '#2a3a52')};
        }}
        QPushButton:pressed {{
            background-color: {_tok(t, 'menu_active_bg', '#31486a')};
        }}
    """


def input_qss(t: dict) -> str:
    """Shared QLineEdit / QComboBox styling for dialogs and panels."""
    return f"""
        QLineEdit, QComboBox {{
            padding: 8px 10px;
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: {RADIUS_CONTROL}px;
            font-size: 13px;
            color: {_tok(t, 'text_primary', '#f8fafc')};
            background-color: {_tok(t, 'panel_deep_bg', '#0d1420')};
            selection-background-color: {_tok(t, 'accent', '#3b82f6')};
        }}
        QLineEdit:focus, QComboBox:focus {{
            border: 1px solid {_tok(t, 'accent', '#3b82f6')};
            background-color: {_tok(t, 'panel_bg', '#111927')};
        }}
        QLineEdit:disabled, QComboBox:disabled {{
            color: {_tok(t, 'text_muted', '#93a4b7')};
            background-color: {_tok(t, 'panel_bg', '#111927')};
        }}
    """


def dialog_button_qss(t: dict, primary: bool = False) -> str:
    """Dialog / panel push buttons. ``primary`` = accent-filled."""
    if primary:
        return f"""
            QPushButton {{
                background-color: {_tok(t, 'accent', '#3b82f6')};
                color: {_tok(t, 'button_text', '#ffffff')};
                border: none;
                border-radius: {RADIUS_CONTROL}px;
                padding: 9px 20px;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {_tok(t, 'accent_hover', '#60a5fa')}; }}
            QPushButton:pressed {{ background-color: {_tok(t, 'accent_pressed', '#1d4ed8')}; }}
            QPushButton:disabled {{
                background-color: {_tok(t, 'panel_alt_bg', '#1d2533')};
                color: {_tok(t, 'text_muted', '#93a4b7')};
            }}
        """
    return f"""
        QPushButton {{
            background-color: {_tok(t, 'panel_alt_bg', '#1d2533')};
            color: {_tok(t, 'text_primary', '#f8fafc')};
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: {RADIUS_CONTROL}px;
            padding: 9px 20px;
            font-weight: 600;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background-color: {_tok(t, 'menu_hover_bg', '#2a3a52')};
            border-color: {_tok(t, 'accent_hover', '#60a5fa')};
        }}
        QPushButton:pressed {{ background-color: {_tok(t, 'menu_active_bg', '#31486a')}; }}
        QPushButton:disabled {{
            color: {_tok(t, 'text_muted', '#93a4b7')};
            background-color: {_tok(t, 'panel_bg', '#111927')};
        }}
    """


def state_button_qss(t: dict, state: str) -> str:
    """Small fixed-size action buttons keyed by semantic state.

    ``state`` is one of ``warning`` (pause), ``danger`` (cancel),
    ``success`` (open).
    """
    base = _tok(t, state, {'warning': '#f59e0b', 'danger': '#ef4444',
                           'success': '#10b981'}.get(state, '#3b82f6'))
    hover = _tok(t, f'{state}_hover', base)
    return f"""
        QPushButton {{
            background-color: {base};
            border: none;
            border-radius: {RADIUS_CONTROL}px;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ background-color: {base}; }}
        QPushButton:disabled {{
            background-color: {_tok(t, 'panel_alt_bg', '#1d2533')};
        }}
    """


def progress_qss(t: dict, state: str = "accent", text: bool = True) -> str:
    """Progress bars. ``state``: accent | success | danger."""
    chunk = {
        "accent": _tok(t, 'accent', '#3b82f6'),
        "success": _tok(t, 'success', '#10b981'),
        "danger": _tok(t, 'danger', '#ef4444'),
    }.get(state, _tok(t, 'accent', '#3b82f6'))
    text_color = f"color: {_tok(t, 'text_primary', '#f8fafc')};" if text else ""
    return f"""
        QProgressBar {{
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: 4px;
            text-align: center;
            background-color: {_tok(t, 'panel_deep_bg', '#0d1420')};
            {text_color}
        }}
        QProgressBar::chunk {{
            background-color: {chunk};
            border-radius: 3px;
        }}
    """


def popup_panel_qss(t: dict, object_name: str) -> str:
    """Root style for popup panels (favorites/history), scoped by
    objectName so the border does NOT cascade onto every child widget."""
    return f"""
        QWidget#{object_name} {{
            background-color: {_tok(t, 'panel_bg', '#111927')};
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: {RADIUS_PANEL}px;
        }}
        QLabel {{ color: {_tok(t, 'text_primary', '#f8fafc')}; background: transparent; border: none; }}
        QListWidget {{
            background-color: {_tok(t, 'panel_deep_bg', '#0d1420')};
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: {RADIUS_CONTROL}px;
            color: {_tok(t, 'text_primary', '#f8fafc')};
        }}
        QListWidget::item:selected {{
            background-color: {_tok(t, 'menu_active_bg', '#31486a')};
        }}
        QListWidget::item:hover {{
            background-color: {_tok(t, 'menu_hover_bg', '#2a3a52')};
        }}
    """


def card_qss(t: dict) -> str:
    """Saved-item / download cards."""
    return f"""
        QFrame {{
            background-color: {_tok(t, 'card_bg', '#141d2c')};
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: {RADIUS_GROUP}px;
        }}
        QLabel {{
            color: {_tok(t, 'text_primary', '#f8fafc')};
            background: transparent;
            border: none;
        }}
    """


def shell_qss(t: dict) -> str:
    """Sub-panel 'shell' frames inside the sidebar."""
    return (
        f"QFrame {{ background-color: {_tok(t, 'panel_alt_bg', '#1d2533')};"
        f" border: 1px solid {_tok(t, 'border', '#33405a')};"
        f" border-radius: {RADIUS_GROUP}px; }}"
    )


def section_button_qss(t: dict) -> str:
    """Checkable section buttons in the saved-items sidebar."""
    return f"""
        QPushButton {{
            background-color: {_tok(t, 'panel_deep_bg', '#0d1420')};
            color: {_tok(t, 'text_primary', '#f8fafc')};
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: {RADIUS_CONTROL}px;
            padding: 10px 12px;
            text-align: left;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {_tok(t, 'menu_hover_bg', '#2a3a52')};
            border-color: {_tok(t, 'accent_hover', '#60a5fa')};
        }}
        QPushButton:checked {{
            background-color: {_tok(t, 'accent', '#3b82f6')};
            border-color: {_tok(t, 'accent_hover', '#60a5fa')};
            color: {_tok(t, 'button_text', '#ffffff')};
        }}
    """


def menu_qss(t: dict) -> str:
    """Right-click context menu (2026-06-27).

    The default QtWebEngine context menu inherits the app palette and on the
    dark theme renders dark-text-on-dark (unreadable). This explicitly pins
    BOTH background and foreground from the live theme tokens, so the menu is
    guaranteed high-contrast and readable in EVERY theme (dark and light) and
    consistent with the rest of the browser chrome. Tokens only — the hex
    literals are builder fallbacks for headless tests.
    """
    return f"""
        QMenu {{
            background-color: {_tok(t, 'panel_bg', '#111927')};
            color: {_tok(t, 'text_primary', '#f8fafc')};
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: {RADIUS_CONTROL}px;
            padding: 6px;
        }}
        QMenu::item {{
            background-color: transparent;
            color: {_tok(t, 'text_primary', '#f8fafc')};
            padding: 7px 24px 7px 14px;
            border-radius: {RADIUS_CONTROL - 2}px;
        }}
        QMenu::item:selected {{
            background-color: {_tok(t, 'menu_hover_bg', '#2a3a52')};
            color: {_tok(t, 'text_primary', '#f8fafc')};
        }}
        QMenu::item:disabled {{
            color: {_tok(t, 'text_muted', '#93a4b7')};
            background-color: transparent;
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {_tok(t, 'border', '#33405a')};
            margin: 5px 8px;
        }}
    """


def autofill_popup_qss(t: dict) -> str:
    """Floating credential-suggestion popup frame (2026-06-28).

    Anchored to the focused login field as a top-level window — it floats over
    the page and never reflows it. Tokens only; hex literals are headless
    fallbacks.
    """
    return f"""
        QFrame#BrowserAutofillPopup {{
            background-color: {_tok(t, 'panel_bg', '#111927')};
            border: 1px solid {_tok(t, 'border', '#33405a')};
            border-radius: {RADIUS_CONTROL}px;
        }}
    """


def autofill_popup_header_qss(t: dict) -> str:
    """The small 'Saved logins' caption above the suggestion rows."""
    return (
        f"color: {_tok(t, 'text_muted', '#93a4b7')}; font-size: 11px;"
        " font-weight: 600; padding: 2px 6px; background: transparent;"
        " border: none;"
    )


def autofill_row_qss(t: dict) -> str:
    """A single credential row button (username + masked password)."""
    return f"""
        QPushButton {{
            text-align: left;
            padding: 7px 10px;
            border: none;
            border-radius: {RADIUS_CONTROL - 2}px;
            color: {_tok(t, 'text_primary', '#f8fafc')};
            background-color: transparent;
            font-size: 12px;
        }}
        QPushButton:hover {{ background-color: {_tok(t, 'menu_hover_bg', '#2a3a52')}; }}
        QPushButton:pressed {{ background-color: {_tok(t, 'menu_active_bg', '#31486a')}; }}
    """
