"""Assist + Search server (2026-07-17): both go to Server 1; nothing else moves.

Scope evolved with owner decisions:
  * first move: Assist (/generate_assistant) → Server 1;
  * then (Search fix): Search (/search) → the SAME server as Assist, because it
    was broken on AI_BASE.
This guard pins that exact scope: moving anything else here — Chat, Report or
Transcript — is a regression the owner did not ask for.

Pure/offline: ``ai_chat_config`` imports headless (its PacsClient theme/icon
imports are wrapped in try/except).
"""
from __future__ import annotations

from pathlib import Path

from modules.EchoMind import ai_chat_config as c

SERVER_1 = "http://81.16.117.196:8082"   # A100 — Assist + Search server
SERVER_2 = "http://80.210.31.214:8085"   # AI_BASE — everything else stays here


def test_assist_and_search_are_on_server_1():
    assert c.ASSIST_BASE == SERVER_1
    assert c.URL_GEN_ASSISTANT == f"{SERVER_1}/generate_assistant"
    assert c.resolve_assist_endpoint() == f"{SERVER_1}/generate_assistant"
    # Search must use the SAME server + backend structure as Assist.
    assert c.URL_SEARCH == f"{SERVER_1}/search"
    assert c.resolve_search_endpoint() == f"{SERVER_1}/search"
    # Same host as Assist (the whole point of "same server as Assistant").
    assert c.URL_SEARCH.rsplit("/", 1)[0] == c.URL_GEN_ASSISTANT.rsplit("/", 1)[0]


def test_everything_else_stays_on_ai_base():
    # Chat, Report, Transcript, sessions/health MUST NOT move.
    assert c.AI_BASE == SERVER_2
    for url in (c.URL_CHAT, c.URL_GEN_REPORT, c.URL_GEN_TRANSCRIPT,
                c.URL_HEALTH, c.URL_STATUS, c.URL_SESSIONS, c.URL_SESSION_GET,
                c.URL_EXPORT_ALL):
        assert url.startswith(SERVER_2), f"{url} was moved off AI_BASE"
        assert SERVER_1 not in url


def test_openai_gapgpt_flow_is_untouched():
    # The ChatGPT tab / OpenAI backend uses GapGPT completions, unrelated to the
    # Assist move.
    assert c.GAPGPT_API_URL == "https://api.gapgpt.app/v1/chat/completions"


def test_central_point_exists_for_future_moves():
    """The doc asked for ONE place to change the Assist/Search address."""
    src = (Path(c.__file__)).read_text(encoding="utf-8", errors="replace")
    assert "ASSIST_BASE" in src
    assert "def resolve_assist_endpoint" in src
    assert "def resolve_search_endpoint" in src


def test_call_sites_still_log_the_endpoints():
    """A debug log must show the Assist/Search endpoint used (acceptance #5).

    F8 (2026-07-28): this used to be a bare `print(f"[ASSISTANT] POST {url}...")`
    that ALSO dumped the request payload and the full response body — i.e. the
    physician's dictation and the generated report — to stdout on every call.
    The endpoint logging that this acceptance criterion actually asks for is now
    done by `_dbg_request(tag, url, payload)`, which logs the endpoint, the
    payload KEYS and its SIZE at DEBUG on the `echomind.chat` logger, and never
    the content. The criterion is satisfied more precisely than before.
    """
    pages = Path(c.__file__).resolve().parent / "viewer_chat" / "ai_chat_pages.py"
    src = pages.read_text(encoding="utf-8", errors="replace")
    assert '_dbg_request("ASSISTANT", URL_GEN_ASSISTANT' in src
    assert '_dbg_request("SEARCH", URL_SEARCH' in src
    # ...and the helper really does put the endpoint in the log record.
    assert 'POST %s keys=%s payload_bytes=%d' in src


def test_assist_search_menu_is_styled_and_iconed():
    """The Assistant/Search chooser must be a themed, iconed control now."""
    pages = Path(c.__file__).resolve().parent / "viewer_chat" / "ai_chat_pages.py"
    src = pages.read_text(encoding="utf-8", errors="replace")
    assert "assistSearchMenu" in src            # object-name for the scoped QSS
    assert "_assist_menu_icon" in src            # icons added to the actions
    assert "border-radius" in src                # cleaner rounded surface
