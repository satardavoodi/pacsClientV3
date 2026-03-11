"""Re-export from the canonical modules.EchoMind.ai_chat_config module.

All chat-config constants live in EchoMind/ai_chat_config.py (single source
of truth).  This shim keeps ``from .ai_chat_config import …`` working inside
the viewer_chat package.
"""
from modules.EchoMind.ai_chat_config import (          # noqa: F401
    safe,
    QWIDGETSIZE_MAX,
    ICON_PATH,
    # API endpoints
    AI_BASE,
    URL_CHAT,
    URL_GEN_REPORT,
    URL_GEN_TRANSCRIPT,
    URL_HEALTH,
    URL_STATUS,
    URL_SESSIONS,
    URL_SESSION_GET,
    URL_EXPORT_ALL,
    URL_GEN_ASSISTANT,
    URL_SEARCH,
    # GapGPT transport settings
    GAPGPT_API_URL,
    GAPGPT_DEFAULT_MODEL,
    GAPGPT_TIMEOUT,
    # UI colour tokens
    CLR_BG,
    CLR_BG_PANEL,
    CLR_TEXT,
    CLR_BORDER,
    CLR_ACCENT,
    CLR_BUBBLE_USER,
    CLR_BUBBLE_BOT,
)

