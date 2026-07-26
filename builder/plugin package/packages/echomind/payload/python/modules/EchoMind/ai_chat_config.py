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
AI_BASE      = 'http://80.210.31.214:8085'

# ── Assist / Search server (2026-07-17) ──────────────────────────────────────
# The "Assist" capability (POST /generate_assistant) AND its related "Search"
# (POST /search) were moved off AI_BASE to a dedicated server. Search uses the
# SAME server + backend structure as Assist (owner request 2026-07-17 — Search
# was previously pointed at AI_BASE and did not work). This is the ONE central
# place to change that address — edit ASSIST_BASE and nothing else.
# Scope is deliberately Assist+Search ONLY: Chat (/chat), Report
# (/generate_report), Transcript (voice_transcription + STT settings) and the
# OpenAI/ChatGPT flow are unchanged and still use AI_BASE / their own paths.
ASSIST_BASE  = 'http://81.16.117.196:8082'


def resolve_assist_endpoint() -> str:
    """The Assist endpoint (central resolver, so a future move is one edit)."""
    return f"{ASSIST_BASE.rstrip('/')}/generate_assistant"


def resolve_search_endpoint() -> str:
    """The Search endpoint — SAME server as Assist (central resolver)."""
    return f"{ASSIST_BASE.rstrip('/')}/search"


URL_CHAT             = f"{AI_BASE}/chat"
URL_GEN_REPORT       = f"{AI_BASE}/generate_report"
URL_GEN_TRANSCRIPT   = f"{AI_BASE}/generate_transcript"
URL_HEALTH           = f"{AI_BASE}/health"
URL_STATUS           = f"{AI_BASE}/status"
URL_SESSIONS         = f"{AI_BASE}/sessions"
URL_SESSION_GET      = f"{AI_BASE}/session"
URL_EXPORT_ALL       = f"{AI_BASE}/export_all"
URL_GEN_ASSISTANT    = resolve_assist_endpoint()   # → ASSIST_BASE, not AI_BASE
URL_SEARCH           = resolve_search_endpoint()   # → ASSIST_BASE (same as Assist)


# =============================
# GapGPT LLM connection
# =============================
# These are shared transport-level settings used by EchoMind/llm_client.py.
#
# GAPGPT_API_URL   — the GapGPT completion endpoint (shared by all consumers)
# GAPGPT_TIMEOUT   — default HTTP timeout for llm_client.gapgpt_chat()
# GAPGPT_DEFAULT_MODEL — used ONLY as the llm_client.py default-parameter
#                        fallback (for reporting module callers that don't
#                        specify a model).  The Secretary module has its own
#                        model setting in EchoMind/secretary/config.py.
GAPGPT_API_URL       = "https://api.gapgpt.app/v1/chat/completions"
GAPGPT_DEFAULT_MODEL = "gpt-5.2"    # llm_client.py fallback only
GAPGPT_TIMEOUT       = 60           # seconds


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

# ── V2 design-system alignment (2026-06-05, readability fix) ────────────────
# The legacy flat near-black palette above (#222 / #1b1b1b / #2b2b2b panels,
# #dddddd text, GRAY accent #8a8a8a) gave the EchoMind chat poor contrast and
# indistinct active/selected states — the "Generating…" bubble, transcription
# and translated-output bubbles, composer, send-button states and the
# reception dialog all derive from these seven tokens. When the EchoMind
# module is on the V2 design (the build default), re-point them at the live
# AI-PACS theme: readable bright text, real accent for active states, and the
# design system's panel surfaces. Pinning V1 (env AIPACS_UI_VARIANT=v1 or the
# per-module override) — or any error here — keeps the legacy palette
# byte-identically. Never raises.
try:
    from PacsClient.utils.ui_variant import get_ui_variant as _get_ui_variant
    if _get_ui_variant("echomind") == "v2":
        from PacsClient.utils.theme_manager import get_theme_manager as _get_tm
        _t = _get_tm().current_theme()
        CLR_BG = _t.get("panel_bg", "#111927")            # chat background
        CLR_BG_PANEL = _t.get("card_bg", "#16202e")       # composer/panels
        CLR_TEXT = _t.get("text_primary", "#f8fafc")      # readable body text
        CLR_BORDER = _t.get("border", "#2d3748")
        CLR_ACCENT = _t.get("accent", "#3182ce")          # real accent, not gray
        CLR_BUBBLE_USER = _t.get("accent_soft", "#21314a")  # soft accent bubble
        CLR_BUBBLE_BOT = _t.get("panel_alt_bg", "#1a202c")  # AI/status bubble
        del _t, _get_tm
    del _get_ui_variant
except Exception:
    pass  # theme not ready / headless context → legacy palette stays

