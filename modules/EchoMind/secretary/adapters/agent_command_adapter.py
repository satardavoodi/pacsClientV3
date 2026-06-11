"""AgentCommandAdapter — background agent workflows on the CommandBus.

2026-06-11: actions that run as BACKGROUND TASKS (task_engine) so the
user keeps reporting while the agent works. Each action returns
immediately with the task id; completion is signalled by the module
icon badge + an inbox notification.

* ``login_website``             — open a stored site and log in from the
                                  encrypted credential vault (verified).
* ``search_education_content``  — deep full-content education search
                                  (courses, slides, cases, PDFs, PPTX,
                                  optionally consultation notes).
* ``agent_task_status``         — list recent background tasks.
* ``cancel_agent_task``         — cancel a queued/running task.

(Plain ``web_search`` / ``open_url`` also run in the background — the
BrowserCommandAdapter routes them through the engine when one is wired.)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)

AGENT_ACTIONS: dict[str, str] = {
    "login_website":            "login_website",
    "search_education_content": "search_education_content",
    "agent_task_status":        "agent_task_status",
    "cancel_agent_task":        "cancel_agent_task",
}


def _err(action: str, code: str, msg: str) -> CommandResult:
    return CommandResult(ok=False, action=action, error_code=code, message=msg)


class AgentCommandAdapter:
    def __init__(
        self,
        browser_launcher: Optional[Callable[[dict], Any]] = None,
        engine_getter: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._browser_launcher = browser_launcher
        self._engine_getter = engine_getter or self._default_engine

    @staticmethod
    def _default_engine():
        from ..background import get_task_engine
        return get_task_engine()

    def _engine(self):
        try:
            return self._engine_getter()
        except Exception:
            logger.exception("agent adapter: engine unavailable")
            return None

    # ── login_website ─────────────────────────────────────────────────
    def login_website(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        site = str(ent.get("site") or ent.get("url") or
                   ent.get("label") or "").strip()
        if not site:
            return _err("login_website", "MISSING_SITE",
                        "login_website requires entities.site (the website "
                        "name or URL).")
        if self._browser_launcher is None:
            return _err("login_website", "MODULE_UNAVAILABLE",
                        "The Web Browser module is not available.")
        engine = self._engine()
        if engine is None:
            return _err("login_website", "ENGINE_UNAVAILABLE",
                        "Background agent engine is not available.")
        from ..background.agent_tasks import make_login_task
        from ..background.task_engine import PRIORITY_MEDIUM
        task_id = engine.submit(
            name=f"Log in to {site}",
            module="web_browser",
            fn=make_login_task(site, self._browser_launcher),
            priority=PRIORITY_MEDIUM,
        )
        logger.info("agent adapter: login_website queued task=%s site=%r",
                    task_id, site)
        return CommandResult(
            ok=True, action="login_website",
            message=(f"Logging in to {site} in the background — you'll get "
                     "a notification when it's done."),
            data={"task_id": task_id, "background": True},
        )

    # ── search_education_content ──────────────────────────────────────
    def search_education_content(self, plan: CommandPlan,
                                 state: dict) -> CommandResult:
        ent = plan.entities or {}
        query = str(ent.get("query") or ent.get("text") or "").strip()
        if not query:
            return _err("search_education_content", "MISSING_QUERY",
                        "search_education_content requires entities.query.")
        include_consults = bool(ent.get("include_consultations"))
        engine = self._engine()
        if engine is None:
            return _err("search_education_content", "ENGINE_UNAVAILABLE",
                        "Background agent engine is not available.")
        from ..background.agent_tasks import make_education_search_task
        from ..background.task_engine import PRIORITY_LOW
        task_id = engine.submit(
            name=f"Education search: {query}",
            module="education",
            fn=make_education_search_task(
                query, include_consultations=include_consults),
            priority=PRIORITY_LOW,
        )
        logger.info("agent adapter: education content search queued "
                    "task=%s query=%r consults=%s",
                    task_id, query, include_consults)
        return CommandResult(
            ok=True, action="search_education_content",
            message=(f"Searching all educational content for '{query}' in "
                     "the background — the Education icon will turn green "
                     "when results are ready."),
            data={"task_id": task_id, "background": True},
        )

    # ── agent_task_status ─────────────────────────────────────────────
    def agent_task_status(self, plan: CommandPlan,
                          state: dict) -> CommandResult:
        engine = self._engine()
        if engine is None:
            return _err("agent_task_status", "ENGINE_UNAVAILABLE",
                        "Background agent engine is not available.")
        tasks = engine.list_tasks(limit=10)
        rows = [{
            "task_id": t.task_id, "name": t.name, "module": t.module,
            "state": t.state,
            "message": (t.result.message if t.result else ""),
        } for t in tasks]
        active = sum(1 for t in tasks if t.state in ("queued", "working"))
        return CommandResult(
            ok=True, action="agent_task_status",
            message=f"{active} active task(s), {len(rows)} recent.",
            data={"tasks": rows},
        )

    # ── cancel_agent_task ─────────────────────────────────────────────
    def cancel_agent_task(self, plan: CommandPlan,
                          state: dict) -> CommandResult:
        ent = plan.entities or {}
        task_id = str(ent.get("task_id") or "").strip()
        engine = self._engine()
        if engine is None:
            return _err("cancel_agent_task", "ENGINE_UNAVAILABLE",
                        "Background agent engine is not available.")
        if not task_id:
            # No id given: cancel the newest active task.
            for t in engine.list_tasks(limit=10):
                if t.state in ("queued", "working"):
                    task_id = t.task_id
                    break
        if not task_id:
            return _err("cancel_agent_task", "NO_ACTIVE_TASK",
                        "There is no active background task to cancel.")
        ok = engine.cancel(task_id)
        return CommandResult(
            ok=ok, action="cancel_agent_task",
            message=(f"Cancellation requested for {task_id}." if ok
                     else f"Task {task_id} was not found."),
            data={"task_id": task_id},
            error_code=None if ok else "TASK_NOT_FOUND",
        )


__all__ = ["AgentCommandAdapter", "AGENT_ACTIONS"]
