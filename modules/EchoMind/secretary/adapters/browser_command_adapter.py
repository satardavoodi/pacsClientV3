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
    # ── structured page read / inspect / interact (2026-06-27) ──────────
    # The MCP-like surface so the Secretary/agent can drive the page through
    # tools instead of synthetic mouse/keyboard. All names are browser_*
    # namespaced to guarantee no collision with other adapters' actions.
    "browser_navigate":      "navigate",        # open a page by URL (alias of open_url)
    "browser_go_back":       "browser_back",
    "browser_go_forward":    "browser_forward",
    "browser_reload":        "refresh_page",
    "browser_get_url":       "get_current_url",
    "browser_get_text":      "get_page_text",
    "browser_get_html":      "get_page_html",
    "browser_dom_summary":   "get_dom_summary",
    "browser_find_element":  "find_element",
    "browser_fill_field":    "fill_field",
    "browser_click":         "click_element",
    "browser_submit_form":   "submit_form",
    "browser_selected_text": "get_selected_text",
    "browser_extract_table": "extract_table",
    "browser_get_links":     "get_links",
    "browser_screenshot":    "take_screenshot",
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

    # ── structured page read / inspect / interact (2026-06-27) ───────────
    # Read actions are READ_ONLY; fill/click/submit are LOCAL_WRITE page
    # interactions. Each resolves the live widget through the launcher, calls
    # its controller method, and returns the page data in CommandResult.data.
    # The widget runs the actual JS off a bounded sync helper, so these never
    # hang the bus. A missing controller method degrades to a typed error
    # (older widget), never an exception.

    def navigate(self, plan: CommandPlan, state: dict) -> CommandResult:
        """browser_navigate — open a page by URL (alias of open_url)."""
        return self.open_url(plan, state)

    def _need_widget(self, action: str):
        """(widget, None) when available, else (None, MODULE_UNAVAILABLE)."""
        widget = self._widget()
        if widget is None:
            return None, _unavailable(action)
        return widget, None

    def _read(self, action: str, method: str, data_key: str,
              ok_msg: str) -> CommandResult:
        widget, err = self._need_widget(action)
        if err is not None:
            return err
        fn = getattr(widget, method, None)
        if not callable(fn):
            return _err(action, "ACTION_FAILED",
                        f"Browser does not support {method}.")
        try:
            value = fn()
        except Exception as exc:
            logger.exception("browser adapter: %s failed", action)
            return _err(action, "ACTION_FAILED", f"{action} failed: {exc}")
        return CommandResult(ok=True, action=action, message=ok_msg,
                             data={data_key: value})

    def get_current_url(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._read("browser_get_url", "get_current_url", "url",
                          "Current URL read.")

    def get_page_text(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget, err = self._need_widget("browser_get_text")
        if err is not None:
            return err
        try:
            text = widget.get_page_text()
            url = widget.get_current_url()
        except Exception as exc:
            logger.exception("browser adapter: get_page_text failed")
            return _err("browser_get_text", "ACTION_FAILED", str(exc))
        return CommandResult(
            ok=True, action="browser_get_text",
            message=f"Read {len(text)} characters of page text.",
            data={"text": text, "length": len(text), "url": url})

    def get_page_html(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget, err = self._need_widget("browser_get_html")
        if err is not None:
            return err
        try:
            html = widget.get_page_html()
            url = widget.get_current_url()
        except Exception as exc:
            logger.exception("browser adapter: get_page_html failed")
            return _err("browser_get_html", "ACTION_FAILED", str(exc))
        return CommandResult(
            ok=True, action="browser_get_html",
            message=f"Read {len(html)} characters of HTML.",
            data={"html": html, "length": len(html), "url": url})

    def get_dom_summary(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._read("browser_dom_summary", "get_dom_summary", "summary",
                          "Page structure summarized.")

    def get_selected_text(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._read("browser_selected_text", "get_selected_text",
                          "selected_text", "Selection read.")

    def get_links(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget, err = self._need_widget("browser_get_links")
        if err is not None:
            return err
        try:
            links = widget.get_links()
        except Exception as exc:
            logger.exception("browser adapter: get_links failed")
            return _err("browser_get_links", "ACTION_FAILED", str(exc))
        links = links if isinstance(links, list) else []
        return CommandResult(
            ok=True, action="browser_get_links",
            message=f"Found {len(links)} link(s).",
            data={"links": links, "count": len(links)})

    def extract_table(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget, err = self._need_widget("browser_extract_table")
        if err is not None:
            return err
        ent = plan.entities or {}
        selector = str(ent.get("selector") or "").strip() or None
        try:
            table = widget.extract_table(selector)
        except Exception as exc:
            logger.exception("browser adapter: extract_table failed")
            return _err("browser_extract_table", "ACTION_FAILED", str(exc))
        rows = table.get("rows", []) if isinstance(table, dict) else []
        found = bool(isinstance(table, dict) and table.get("found"))
        return CommandResult(
            ok=found, action="browser_extract_table",
            message=(f"Extracted {len(rows)} row(s)." if found
                     else "No matching table found."),
            data={"table": table})

    def find_element(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget, err = self._need_widget("browser_find_element")
        if err is not None:
            return err
        ent = plan.entities or {}
        selector = str(ent.get("selector") or "").strip()
        if not selector:
            return _err("browser_find_element", "MISSING_SELECTOR",
                        "find_element requires entities.selector (a CSS selector).")
        try:
            info = widget.find_element(selector)
        except Exception as exc:
            logger.exception("browser adapter: find_element failed")
            return _err("browser_find_element", "ACTION_FAILED", str(exc))
        found = bool(isinstance(info, dict) and info.get("found"))
        return CommandResult(
            ok=True, action="browser_find_element",
            message=("Element found." if found else "Element not found."),
            data={"selector": selector, "element": info})

    def fill_field(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget, err = self._need_widget("browser_fill_field")
        if err is not None:
            return err
        ent = plan.entities or {}
        selector = str(ent.get("selector") or "").strip()
        value = ent.get("value")
        value = "" if value is None else str(value)
        if not selector:
            return _err("browser_fill_field", "MISSING_SELECTOR",
                        "fill_field requires entities.selector and entities.value.")
        try:
            ok = bool(widget.fill_field(selector, value))
        except Exception as exc:
            logger.exception("browser adapter: fill_field failed")
            return _err("browser_fill_field", "ACTION_FAILED", str(exc))
        if not ok:
            return _err("browser_fill_field", "ACTION_FAILED",
                        f"Could not fill {selector!r} (element not found?).")
        return CommandResult(ok=True, action="browser_fill_field",
                             message=f"Filled {selector}.",
                             data={"selector": selector})

    def click_element(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget, err = self._need_widget("browser_click")
        if err is not None:
            return err
        ent = plan.entities or {}
        selector = str(ent.get("selector") or "").strip()
        if not selector:
            return _err("browser_click", "MISSING_SELECTOR",
                        "click_element requires entities.selector (a CSS selector).")
        try:
            ok = bool(widget.click_element(selector))
        except Exception as exc:
            logger.exception("browser adapter: click_element failed")
            return _err("browser_click", "ACTION_FAILED", str(exc))
        if not ok:
            return _err("browser_click", "ACTION_FAILED",
                        f"Could not click {selector!r} (element not found?).")
        return CommandResult(ok=True, action="browser_click",
                             message=f"Clicked {selector}.",
                             data={"selector": selector})

    def submit_form(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget, err = self._need_widget("browser_submit_form")
        if err is not None:
            return err
        ent = plan.entities or {}
        selector = str(ent.get("selector") or "").strip() or None
        try:
            ok = bool(widget.submit_form(selector))
        except Exception as exc:
            logger.exception("browser adapter: submit_form failed")
            return _err("browser_submit_form", "ACTION_FAILED", str(exc))
        if not ok:
            return _err("browser_submit_form", "ACTION_FAILED",
                        "No form to submit.")
        return CommandResult(ok=True, action="browser_submit_form",
                             message="Form submitted.", data={})

    def take_screenshot(self, plan: CommandPlan, state: dict) -> CommandResult:
        widget, err = self._need_widget("browser_screenshot")
        if err is not None:
            return err
        ent = plan.entities or {}
        path = str(ent.get("path") or "").strip() or None
        try:
            res = widget.take_screenshot(path)
        except Exception as exc:
            logger.exception("browser adapter: take_screenshot failed")
            return _err("browser_screenshot", "ACTION_FAILED", str(exc))
        if not (isinstance(res, dict) and res.get("ok")):
            return _err("browser_screenshot", "ACTION_FAILED",
                        "Screenshot could not be captured.")
        return CommandResult(ok=True, action="browser_screenshot",
                             message=f"Saved screenshot to {res.get('path')}.",
                             data={"path": res.get("path")})


__all__ = ["BrowserCommandAdapter", "BROWSER_ACTIONS", "normalize_url",
           "GOOGLE_SEARCH_URL"]
