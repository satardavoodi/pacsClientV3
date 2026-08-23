"""QSS built from theme tokens. No hex literals anywhere else in this module.

``get_theme_manager().current_theme()`` returns the token dict and
``themeChanged`` fires when the operator picks a different theme. Every widget
here connects to it and restyles; nothing caches a colour.

THE ONE EXCEPTION IS TONE. ``fresh / wait / work / good / alert / done`` are
the SERVER's six status tones, and they map onto theme tokens rather than onto
fixed colours so a case chip still reads correctly in every theme. The map is
here, in one place; the decision about which tone a status has stays on the
server, where CaseStatus::TONE lives.
"""

from __future__ import annotations

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14


def theme_tokens() -> dict:
    """The active theme, or a usable fallback.

    Never raises: a styling helper that can fail takes the whole tab with it,
    and a slightly wrong colour is a much smaller problem than a blank pane.
    """
    try:
        from PacsClient.utils.theme_manager import get_theme_manager

        tokens = get_theme_manager().current_theme()
        if isinstance(tokens, dict) and tokens:
            return tokens
    except Exception:
        pass
    return _FALLBACK


_FALLBACK = {
    "window_bg": "#1e2229",
    "panel_bg": "#232830",
    "panel_alt_bg": "#282e37",
    "card_bg": "#2b323c",
    "border": "#39414d",
    "text_primary": "#e8ecf1",
    "text_secondary": "#aab4c0",
    "text_muted": "#7c8794",
    "accent": "#3b82f6",
    "accent_hover": "#2f6fd8",
    "accent_soft": "#1d3a63",
    "button_text": "#ffffff",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "info": "#38bdf8",
    "neutral": "#64748b",
    "status_online": "#22c55e",
    "status_offline": "#64748b",
}


def token(name: str, default: str = "#888888") -> str:
    return str(theme_tokens().get(name, default) or default)


# ── status tones ─────────────────────────────────────────────────────────────
# The six the server sends. Mapped to tokens, never to literals, so a chip
# tracks the operator's chosen theme.

_TONE_TOKENS = {
    "fresh": "info",
    "wait": "warning",
    "work": "accent",
    "good": "success",
    "alert": "danger",
    "done": "neutral",
}


def tone_color(tone: str) -> str:
    """The colour for a server tone.

    Falls back to the ``work`` token for anything unrecognised — the same
    fallback ``CaseStatus::tone()`` uses, so an unfamiliar status reads as
    ordinary in-progress rather than losing its styling and looking broken.
    """
    return token(_TONE_TOKENS.get(tone, "accent"))


# ── QSS builders ─────────────────────────────────────────────────────────────


def shell_qss(t: dict) -> str:
    return f"""
    QWidget#AiPacsChatShell {{
        background: {t.get('window_bg')};
        color: {t.get('text_primary')};
    }}
    QLabel#ChatStateTitle {{
        color: {t.get('text_primary')};
        font-size: 17px;
        font-weight: 600;
    }}
    QLabel#ChatStateBody {{
        color: {t.get('text_secondary')};
        font-size: 13px;
    }}
    QPushButton#ChatStateAction {{
        background: {t.get('accent')};
        color: {t.get('button_text')};
        border: none;
        border-radius: {RADIUS_SM}px;
        padding: 8px 18px;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton#ChatStateAction:hover {{ background: {t.get('accent_hover')}; }}
    """


def pane_qss(t: dict) -> str:
    return f"""
    QWidget#ChatListPane, QWidget#ChatThreadPane, QWidget#ChatCasePane {{
        background: {t.get('panel_bg')};
        border: 1px solid {t.get('border')};
        border-radius: {RADIUS_MD}px;
    }}
    QLabel#ChatPaneTitle {{
        color: {t.get('text_secondary')};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1px;
        padding: 10px 12px 4px 12px;
    }}
    QLineEdit#ChatSearch {{
        background: {t.get('panel_alt_bg')};
        color: {t.get('text_primary')};
        border: 1px solid {t.get('border')};
        border-radius: {RADIUS_SM}px;
        padding: 6px 10px;
        font-size: 13px;
    }}
    QLineEdit#ChatSearch:focus {{ border-color: {t.get('accent')}; }}
    QListView#ChatConversationList {{
        background: transparent;
        border: none;
        outline: none;
    }}
    """


def composer_qss(t: dict) -> str:
    return f"""
    QLabel#ChatThreadHeader {{
        color: {t.get('text_primary')};
        font-size: 15px;
        font-weight: 600;
        padding: 2px 0 6px 2px;
    }}
    QLabel#ChatTyping {{
        color: {t.get('text_muted')};
        font-size: 11px;
        font-style: italic;
        min-height: 14px;
    }}
    QListView#ChatTranscript {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QPlainTextEdit#ChatComposerEdit {{
        background: {t.get('panel_alt_bg')};
        color: {t.get('text_primary')};
        border: 1px solid {t.get('border')};
        border-radius: {RADIUS_SM}px;
        padding: 6px 8px;
        font-size: 13px;
    }}
    QPlainTextEdit#ChatComposerEdit:focus {{ border-color: {t.get('accent')}; }}
    QPushButton#ChatSendButton {{
        background: {t.get('accent')};
        color: {t.get('button_text')};
        border: none;
        border-radius: {RADIUS_SM}px;
        padding: 8px 20px;
        font-weight: 600;
    }}
    QPushButton#ChatSendButton:hover {{ background: {t.get('accent_hover')}; }}
    QPushButton#ChatSendButton:disabled {{
        background: {t.get('panel_alt_bg')};
        color: {t.get('text_muted')};
    }}
    QComboBox#ChatSavedReplies, QComboBox#ChatPricing, QComboBox#ChatStatuses {{
        background: {t.get('panel_alt_bg')};
        color: {t.get('text_secondary')};
        border: 1px solid {t.get('border')};
        border-radius: {RADIUS_SM}px;
        padding: 4px 8px;
        font-size: 12px;
    }}
    """


def counts_chip_qss(t: dict) -> str:
    # The chips are QPushButtons now (count AND filter toggle), so the checked
    # state has to read as "this filter is on" at a glance — accent fill, not
    # just a border shade, because an operator scanning the list must be able
    # to tell instantly why rows are missing.
    return f"""
    QPushButton[chatChip="true"] {{
        background: {t.get('panel_alt_bg')};
        color: {t.get('text_secondary')};
        border: 1px solid {t.get('border')};
        border-radius: {RADIUS_SM}px;
        padding: 3px 8px;
        font-size: 11px;
        text-align: center;
    }}
    QPushButton[chatChip="true"]:hover {{
        border-color: {t.get('accent')};
        color: {t.get('text_primary')};
    }}
    QPushButton[chatChip="true"][chatAlert="true"] {{
        background: {t.get('danger')};
        border-color: {t.get('danger')};
        color: {t.get('button_text', '#ffffff')};
        font-weight: 700;
    }}
    QPushButton[chatChip="true"][chatAlert="true"]:hover {{
        border-color: {t.get('text_primary')};
        color: {t.get('button_text', '#ffffff')};
    }}
    /* Checked LAST so an active filter still reads as active even while the
       same chip is carrying a badge — the two states can coexist and the
       filter is the one the operator needs to see. */
    QPushButton[chatChip="true"]:checked {{
        background: {t.get('accent')};
        border-color: {t.get('accent')};
        color: {t.get('on_accent', '#ffffff')};
        font-weight: 700;
    }}
    QLabel[chatChip="true"] {{
        background: {t.get('panel_alt_bg')};
        color: {t.get('text_secondary')};
        border: 1px solid {t.get('border')};
        border-radius: {RADIUS_SM}px;
        padding: 3px 8px;
        font-size: 11px;
    }}
    """
