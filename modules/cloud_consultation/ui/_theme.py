"""Dark palette for the consultation UI, pulled from the app theme with fallbacks.

Keeps the widgets visually consistent with the AI-PACS workstation (navy + blue) and
auto-follows the active theme tokens where available.
"""

from __future__ import annotations


def _theme_tokens() -> dict:
    try:
        from PacsClient.utils.theme_manager import get_theme_manager

        return get_theme_manager().current_theme() or {}
    except Exception:
        return {}


def palette() -> dict:
    t = _theme_tokens()

    def g(key, fallback):
        return t.get(key) or fallback

    return {
        "bg": g("window_bg", "#0b1220"),
        "surface": g("panel_bg", "#111c30"),
        "surface2": g("menu_bg", "#0c1626"),
        "border": g("border", "rgba(148,163,184,0.18)"),
        "accent": g("accent", "#3b82f6"),
        "accent_soft": g("accent_soft", "#16243c"),
        "text": g("text_primary", "#e6edf6"),
        "text_muted": g("text_secondary", "#93a4bd"),
        "button_text": g("button_text", "#ffffff"),
        "success": "#34d399",
        "warning": "#fbbf24",
        "danger": "#f87171",
    }
