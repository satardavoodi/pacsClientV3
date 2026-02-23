from __future__ import annotations

# NOTE:
# This module contains only shared constants/config used by the AI chat UI.

from html import escape

# Keep the same symbol as the old single-file module (even if unused)
safe = escape("<div>")

# Qt (same symbol as old file)
QWIDGETSIZE_MAX = 16777215

# ICON helper: keep behavior identical to the old module
try:
    from PacsClient.utils import ICON_PATH
except Exception:
    ICON_PATH = "."

# =============================
# API endpoints
# =============================
AI_BASE      = 'http://185.239.2.153:8002'  
URL_CHAT             = f"{AI_BASE}/chat"
URL_GEN_REPORT       = f"{AI_BASE}/generate_report"
URL_GEN_TRANSCRIPT   = f"{AI_BASE}/generate_transcript"
URL_HEALTH           = f"{AI_BASE}/health"
URL_STATUS           = f"{AI_BASE}/status"
URL_SESSIONS         = f"{AI_BASE}/sessions"
URL_SESSION_GET      = f"{AI_BASE}/session"      
URL_EXPORT_ALL       = f"{AI_BASE}/export_all"
URL_GEN_ASSISTANT    = f"{AI_BASE}/generate_assistant"
URL_SEARCH           = f"{AI_BASE}/search"


# =============================
# UI tokens
# =============================
CLR_BG = "#222"
CLR_BG_PANEL = "#1b1b1b"
CLR_TEXT = "#dddddd"
CLR_BORDER= "#444"
CLR_ACCENT = "#8a8a8a"
CLR_BUBBLE_USER = "#333"
CLR_BUBBLE_BOT = "#2b2b2b"

