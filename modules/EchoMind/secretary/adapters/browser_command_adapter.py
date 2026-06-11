"""BrowserCommandAdapter — voice-command access to the Web Browser module.

2026-06-11: lets the Secretary/EchoMind voice assistant drive the in-app
Web Browser through module-level calls (NEVER synthetic mouse clicks):

* ``open_browser``     — open/activate the Web Browser tab
* ``web_search``       — search a text query on Google (the default and
                         only search engine for voice commands)
* ``open_url``         — navigate to a specific http(s) URL
* ``browser_back``     — history back
* ``browser_forward``  — history forward
* ``refresh_page``     — reload (or stop+reload) the current page

The adapter is constructed with a single ``open_browser`` launcher —
``callable(entities: dict) -> WebBrowserWidget | None`` — supplied by the
home panel (``HomePanelWidget._launcher_web_browser``). The launcher is
idempotent (activate-or-create singleton tab), so every action first
resolves the live widget through it and then calls the widget's
controller-level API (``search_web`` / ``load_url`` / ``navigate_back`` /
``navigate_forward`` / ``reload_page``).

When the Web Browser module is not installed/enabled the launcher returns
``None`` and every action degrades to a typed, recoverable
``MODULE_UNAVAILABLE`` envelope with a clear user-facing message — never a
silent failure, never an exception.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional
from urllib.parse import quote_plus

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)

# Default (and only) voice-command search engine — per product requirement.
GOOGLE_SEARCH_URL = "https://www.google.com/search?q={query}"

# action_id → handler method name (mirrors ECHOMIND_ACTIONS convention)
BROWSER_ACTIONS: dict[str, str] = {
    "open_browser":    "open_browser",
    "web_search":      "web_search",
    "open_url":        "open_url",
    "browser_back":    "browser_back",
    "browser_forward": "browser_forward",
    "refresh_page":    "refresh_page",
}

_URL_OK_RE = re.compile(r"^https?://", re.I)


def _err(action: str, code: str, msg: str) -> CommandResult:
    return CommandResult(ok=False, action=action, error_code=code, message=msg)


def _unavailable(action: str) -> CommandResult:
    return _err(
        action, "MODULE_UNAVAILABLE",
        "The Web Browser module is not available on this workstation "
        "(not installed, disabled, or it failed to open).",
    )


def normalize_url(raw: str) -> str:
    """Best-effort normalization of a spoken/typed URL to https://…

    Returns '' when the input cannot be a safe web URL. Only http/https
    are ever produced (no file://, javascript:, etc.).
    """
    url = (raw or "").strip()
    if not url or " " in url:
        return ""
    low = url.lower()
    if low.startswith(("javascript:", "file:", "data:", "about:", "chrome:")):
        return ""
    if _URL_OK_RE.match(url):
        return url
    if "." in url:  # bare domain like "example.com" / "www.example.com"
        return "https://" + url
    return ""


class BrowserCommandAdapter:
    """Web Browser commands bound to the home panel's singleton browser tab."""

    def __init__(
        self,
        open_browser_launcher: Optional[Callable[[dict], Any]] = None,
        engine_getter: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._launch = open_browser_launcher or (lambda _entities: None)
        # Optional background task engine (2026-06-11). When wired,
        # web_search / open_url run as verified BACKGROUND tasks: the
        # browser still opens immediately (first UI hop inside the task),
        # but load-wait + page-text verification + screenshot happen on a
        # worker thread, and completion is reported via badge +
        # notification. Without an engine the original synchronous
        # behavior is unchanged (tests, legacy callers).
        self._engine_getter = engine_getter

    def _engine(self):
        if self._engine_getter is None:
            return None
        try:
            return self._engine_getter()
        except Exception:
            logger.exception("browser adapter: engine getter raised")
            return None

    # ── helpers ──────────────────────────────────────────────────────
    def _widget(self, entities: Optional[dict] = None):
        """Open/activate the browser tab and return the live widget (or None)."""
        try:
            return self._launch(dict(entities or {}))
        except Exception:
            logger.exception("browser adapter: launcher raised")
            return None

    # ── action: open_browser ─────────────────────────────────────────
    def open_browser(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget = self._widget(plan.entities)
        if widget is None:
            return _unavailable("open_browser")
        logger.info("browser adapter: open_browser ok")
        return CommandResult(
            ok=True, action="open_browser",
            message="Web Browser opened.",
            data={"widget_class": type(widget).__name__},
        )

    # ── action: web_search ───────────────────────────────────────────
    def web_search(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        query = str(ent.get("query") or ent.get("text") or "").strip()
        if not query:
            return _err("web_search", "MISSING_QUERY",
                        "web_search requires entities.query (the text to search).")
        # Background path (verified, non-blocking) when an engine is wired.
        engine = self._engine()
        if engine is not None:
            from ..background.agent_tasks import make_web_search_task
            task_id = engine.submit(
                name=f"Google search: {query}",
                module="web_browser",
                fn=make_web_search_task(query, self._launch),
            )
            logger.info("browser adapter: web_search queued task=%s "
                        "query=%r", task_id, query)
            return CommandResult(
                ok=True, action="web_search",
                message=(f"Searching Google for '{query}' — running in the "
                         "background, you can keep working."),
                data={"query": query, "engine": "google",
                      "task_id": task_id, "background": True},
            )
        widget = self._widget(plan.entities)
        if widget is None:
            return _unavailable("web_search")
        try:
            if hasattr(widget, "search_web"):
                ok = bool(widget.search_web(query))
            else:  # very old widget — fall back to a direct Google URL load
                ok = bool(widget.load_url(
                    GOOGLE_SEARCH_URL.format(query=quote_plus(query))))
        except Exception as exc:
            logger.exception("browser adapter: web_search failed")
            return _err("web_search", "ACTION_FAILED", f"Web search failed: {exc}")
        logger.info("browser adapter: web_search ok=%s query=%r", ok, query)
        if not ok:
            return _err("web_search", "ACTION_FAILED", "Web search failed.")
        return CommandResult(
            ok=True, action="web_search",
            message=f"Searching Google for '{query}'.",
            data={"query": query, "engine": "google"},
        )

    # ── action: open_url ─────────────────────────────────────────────
    def open_url(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        raw = str(ent.get("url") or "").strip()
        url = normalize_url(raw)
        if not url:
            return _err("open_url", "INVALID_URL",
                        f"'{raw}' is not a valid web address.")
        # Background path (verified, non-blocking) when an engine is wired.
        engine = self._engine()
        if engine is not None:
            from ..background.agent_tasks import make_open_url_task
            task_id = engine.submit(
                name=f"Open {url}",
                module="web_browser",
                fn=make_open_url_task(url, self._launch),
            )
            logger.info("browser adapter: open_url queued task=%s url=%r",
                        task_id, url)
            return CommandResult(
                ok=True, action="open_url",
                message=f"Opening {url} — running in the background.",
                data={"url": url, "task_id": task_id, "background": True},
            )
        widget = self._widget(plan.entities)
        if widget is None:
            return _unavailable("open_url")
        try:
            ok = bool(widget.load_url(url))
        except Exception as exc:
            logger.exception("browser adapter: open_url failed")
            return _err("open_url", "ACTION_FAILED", f"Could not open URL: {exc}")
        logger.info("browser adapter: open_url ok=%s url=%r", ok, url)
        if not ok:
            return _err("open_url", "ACTION_FAILED", "Could not open the URL.")
        return CommandResult(
            ok=True, action="open_url",
            message=f"Opening {url}.", data={"url": url},
        )

    # ── navigation actions ───────────────────────────────────────────
    def browser_back(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._nav("browser_back", "navigate_back", "Went back one page.")

    def browser_forward(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._nav("browser_forward", "navigate_forward",
                         "Went forward one page.")

    def refresh_page(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._nav("refresh_page", "reload_page", "Page refreshed.")

    def _nav(self, action: str, method: str, ok_msg: str) -> CommandResult:
        widget = self._widget()
        if widget is None:
            return _unavailable(action)
        fn = getattr(widget, method, None)
        if not callable(fn):
            return _err(action, "ACTION_FAILED",
                        f"Browser does not support {method}.")
        try:
            fn()
        except Exception as exc:
            logger.exception("browser adapter: %s failed", action)
            return _err(action, "ACTION_FAILED", f"{action} failed: {exc}")
        logger.info("browser adapter: %s ok", action)
        return CommandResult(ok=True, action=action, message=ok_msg)


__all__ = ["BrowserCommandAdapter", "BROWSER_ACTIONS", "normalize_url",
           "GOOGLE_SEARCH_URL"]
