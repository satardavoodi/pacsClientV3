from __future__ import annotations

try:
    from EchoMind.ai_chat_pages import OneChatPage, ModePickerPage, ChatGPTPage
except Exception:
    from .ai_chat_pages import OneChatPage, ModePickerPage, ChatGPTPage

__all__ = ["OneChatPage", "ModePickerPage", "ChatGPTPage"]
