"""LLM layer for the Reception CRM agent.

Ported from the AI-PACS workstation EchoMind LLM integration
(``modules/EchoMind/llm_client.py`` + ``ai_chat_config.py``), keeping the same
provider selection (company/GapGPT vs OpenAI), request configuration, error
taxonomy and logging conventions — but with **server-side** credentials and no
workstation/PySide dependencies.

The EchoMind reporting prompts are NOT reused: this package ships its own CRM
command-interpretation prompt (``prompts/crm_command_interpretation.md``).
"""

from .client import (
    BackendSession,
    LLMAPIError,
    LLMAuthError,
    LLMError,
    LLMNoKeyError,
    chat_completion,
    is_configured,
    test_connection,
)

__all__ = [
    "BackendSession",
    "LLMError",
    "LLMNoKeyError",
    "LLMAuthError",
    "LLMAPIError",
    "chat_completion",
    "is_configured",
    "test_connection",
]
