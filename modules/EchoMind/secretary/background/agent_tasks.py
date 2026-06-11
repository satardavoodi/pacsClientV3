"""agent_tasks — concrete background workflows for the Secretary agent.

Each factory returns a ``fn(task) -> TaskResult`` suitable for
``BackgroundTaskEngine.submit``. The pattern shared by every task:

    1. ONE short UI hop (open/activate the module tab, fire the action)
    2. wait + verify OFF the UI thread (page text / file scan)
    3. one retry when verification fails and retrying makes sense
    4. screenshot / JSON artifact for the user to review
    5. TaskResult → engine state → badge + notification

Launchers are the same activate-or-create callables the CommandBus
adapters use (``entities → widget | None``) — module-level control,
never synthetic clicks.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, Optional

from .task_engine import AgentTask, TaskResult
from .ui_bridge import run_on_ui
from . import verification as V

logger = logging.getLogger(__name__)

Launcher = Callable[[dict], object]


def _cancelled(task: AgentTask) -> Optional[TaskResult]:
    if task.is_cancelled():
        return TaskResult(ok=False, message="Cancelled by user")
    return None


# ── web search ───────────────────────────────────────────────────────────

def make_web_search_task(query: str, browser_launcher: Launcher,
                         max_attempts: int = 2):
    """Search Google, verify the results page actually shows the terms."""

    def _run(task: AgentTask) -> TaskResult:
        widget_box: dict = {}

        def _start():
            w = browser_launcher({})
            if w is None:
                return False
            widget_box["w"] = w
            return bool(w.search_web(query))

        last_ratio = 0.0
        for attempt in range(1, max_attempts + 1):
            c = _cancelled(task)
            if c:
                return c
            ok, started = run_on_ui(_start, timeout=15.0)
            if not ok or not started:
                if "w" not in widget_box:
                    return TaskResult(
                        ok=False,
                        message="Web Browser module is not available.")
                return TaskResult(ok=False, message="Search did not start.")
            widget = widget_box["w"]
            V.wait_page_loaded(widget, timeout=25.0)
            c = _cancelled(task)
            if c:
                return c
            text = V.get_page_text(widget, timeout=10.0)
            verified, ratio = V.verify_terms_in_text(text, query)
            last_ratio = max(last_ratio, ratio)
            if verified:
                shot = V.capture_screenshot(widget, f"google_{query}")
                return TaskResult(
                    ok=True,
                    message=(f"Google results for '{query}' loaded "
                             f"({ratio:.0%} of terms verified on page)."),
                    data={"query": query, "term_ratio": ratio,
                          "url": V.get_page_url(widget),
                          "attempt": attempt},
                    artifacts=[shot] if shot else [],
                )
            logger.info("web_search task: verify attempt %d ratio=%.2f",
                        attempt, ratio)
            time.sleep(1.0)
        shot = V.capture_screenshot(widget_box.get("w"), f"google_{query}") \
            if widget_box.get("w") is not None else ""
        return TaskResult(
            ok=True, warning=True,
            message=(f"Search for '{query}' was sent, but the results page "
                     f"could not be fully verified ({last_ratio:.0%} of "
                     "terms found). Open the browser to review."),
            data={"query": query, "term_ratio": last_ratio},
            artifacts=[shot] if shot else [],
        )

    return _run


# ── open url ─────────────────────────────────────────────────────────────

def make_open_url_task(url: str, browser_launcher: Launcher):
    """Open a URL and verify a page actually rendered there."""

    def _run(task: AgentTask) -> TaskResult:
        widget_box: dict = {}

        def _start():
            w = browser_launcher({})
            if w is None:
                return False
            widget_box["w"] = w
            return bool(w.load_url(url))

        ok, started = run_on_ui(_start, timeout=15.0)
        if not ok or not started:
            if "w" not in widget_box:
                return TaskResult(ok=False,
                                  message="Web Browser module is not available.")
            return TaskResult(ok=False, message=f"Could not open {url}.")
        widget = widget_box["w"]
        V.wait_page_loaded(widget, timeout=25.0)
        c = _cancelled(task)
        if c:
            return c
        text = V.get_page_text(widget, timeout=10.0)
        final_url = V.get_page_url(widget)
        loaded = len((text or "").strip()) > 40
        shot = V.capture_screenshot(widget, f"open_{url}")
        if loaded:
            return TaskResult(
                ok=True,
                message=f"Page loaded: {final_url or url}",
                data={"url": final_url or url, "text_chars": len(text)},
                artifacts=[shot] if shot else [],
            )
        return TaskResult(
            ok=True, warning=True,
            message=(f"Navigation to {url} finished but the page shows "
                     "little or no text — it may have failed to load."),
            data={"url": final_url or url, "text_chars": len(text)},
            artifacts=[shot] if shot else [],
        )

    return _run


# ── website login (credential vault) ─────────────────────────────────────

def make_login_task(site: str, browser_launcher: Launcher):
    """Open a stored site and auto-fill its login form from the vault.

    The password travels straight from the OS-keychain-backed vault into
    the page's form fields — it is never logged, never included in the
    TaskResult, never shown in a dialog.
    """

    def _run(task: AgentTask) -> TaskResult:
        try:
            from modules.web_browser.credential_vault import get_vault
            vault = get_vault()
            cred = vault.find_for_site(site)
        except Exception as exc:  # noqa: BLE001
            return TaskResult(ok=False,
                              message=f"Credential vault unavailable: {exc}")
        if cred is None:
            return TaskResult(
                ok=False,
                message=(f"No stored credentials match '{site}'. Add them "
                         "in the browser's Favorites panel first."))
        secret = vault.get_password(cred["id"])
        if not secret:
            return TaskResult(
                ok=False,
                message=f"Stored password for '{cred.get('label') or site}' "
                        "could not be decrypted.")

        widget_box: dict = {}

        def _open():
            w = browser_launcher({})
            if w is None:
                return False
            widget_box["w"] = w
            return bool(w.load_url(cred["url"]))

        ok, started = run_on_ui(_open, timeout=15.0)
        if not ok or not started:
            return TaskResult(ok=False,
                              message="Web Browser module is not available.")
        widget = widget_box["w"]
        V.wait_page_loaded(widget, timeout=25.0)
        c = _cancelled(task)
        if c:
            return c

        ok, _ = run_on_ui(
            lambda: widget.auto_fill_login(cred.get("username", ""), secret,
                                           submit=True),
            timeout=10.0)
        if not ok:
            return TaskResult(ok=False, message="Login form fill failed.")
        # Give the site time to authenticate + redirect.
        time.sleep(2.0)
        V.wait_page_loaded(widget, timeout=20.0)
        text = V.get_page_text(widget, timeout=10.0)
        low = (text or "").lower()
        failure_markers = ("incorrect password", "wrong password",
                           "invalid login", "login failed",
                           "invalid username", "try again",
                           "incorrect username")
        success_marker = (cred.get("success_text") or "").strip().lower()
        failed = any(m in low for m in failure_markers)
        succeeded = bool(success_marker) and success_marker in low
        shot = V.capture_screenshot(widget, f"login_{cred.get('label') or site}")
        try:
            vault.touch_last_used(cred["id"])
        except Exception:
            pass
        if failed:
            return TaskResult(
                ok=False,
                message=f"Login to {cred['url']} appears to have FAILED "
                        "(error text detected on page).",
                artifacts=[shot] if shot else [])
        if succeeded or not success_marker:
            return TaskResult(
                ok=True, warning=not succeeded,
                message=(f"Logged in to {cred['url']}." if succeeded else
                         f"Login submitted to {cred['url']} — no error "
                         "detected. Open the browser to confirm."),
                data={"url": cred["url"], "username": cred.get("username", "")},
                artifacts=[shot] if shot else [])
        return TaskResult(
            ok=True, warning=True,
            message=(f"Login submitted to {cred['url']} but the expected "
                     f"success text was not found. Please review."),
            artifacts=[shot] if shot else [])

    return _run


# ── education content search ─────────────────────────────────────────────

def make_education_search_task(query: str,
                               include_consultations: bool = False):
    """Deep search across courses, slides, cases, PDFs/e-books, PPTX."""

    def _run(task: AgentTask) -> TaskResult:
        from modules.education.content_search import search_education_content
        report = search_education_content(
            query,
            include_consultations=include_consultations,
            cancelled=task.is_cancelled,
        )
        c = _cancelled(task)
        if c:
            return c
        results = report.get("results", [])
        # Persist the result set so the Education module / user can review.
        out = V.artifacts_dir() / (
            f"education_search_{time.strftime('%Y%m%d_%H%M%S')}.json")
        try:
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            artifact = str(out)
        except Exception:
            artifact = ""
        skipped = report.get("skipped_extractors", [])
        msg = (f"Education search for '{query}': {len(results)} match(es) "
               f"across {report.get('sources_searched', 0)} source(s).")
        if skipped:
            msg += f" (Not searched: {', '.join(skipped)}.)"
        return TaskResult(
            ok=True,
            warning=bool(skipped) and not results,
            message=msg,
            data={"query": query, "count": len(results),
                  "results": results[:25], "skipped": skipped},
            artifacts=[artifact] if artifact else [],
        )

    return _run


__all__ = [
    "make_web_search_task", "make_open_url_task", "make_login_task",
    "make_education_search_task",
]
