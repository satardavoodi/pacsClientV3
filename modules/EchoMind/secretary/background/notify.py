"""notify — agent completion notifications into the account inbox.

Reuses the existing notifications pipeline (``database.notifications_db``
via ``modules.cloud_consultation.notifications.inbox``) that already
renders unread items in the top-right Account popup. Agent kinds are
plain strings — the inbox stores arbitrary kinds and we always pass an
explicit title, so no KIND_TITLES registration is required.

Worker-thread safe (the consultation poller already writes notifications
off-thread through the same DB layer). Always fail-silent: a missing or
locked notifications DB must never fail an agent task.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

KIND_AGENT_DONE = "agent_task_completed"
KIND_AGENT_WARN = "agent_task_warning"
KIND_AGENT_FAIL = "agent_task_failed"


def post_notification(title: str, body: str = "",
                      kind: str = KIND_AGENT_DONE) -> int:
    """Record a notification; returns its id or -1 on failure."""
    try:
        from modules.cloud_consultation.notifications import inbox
        nid = inbox.notify(kind, title=title, body=body)
        logger.info("agent notify: [%s] %s (id=%s)", kind, title, nid)
        return int(nid)
    except Exception:
        logger.warning("agent notify: notifications DB unavailable — "
                       "[%s] %s", kind, title, exc_info=True)
        return -1


def notify_task_finished(task, result) -> None:
    """Map a finished AgentTask to an inbox notification."""
    try:
        state = getattr(task, "state", "")
        name = getattr(task, "name", "Agent task")
        message = getattr(result, "message", "") if result else ""
        artifacts = list(getattr(result, "artifacts", []) or [])
        body = message
        if artifacts:
            body = (body + "\n" if body else "") + "Artifacts: " + \
                "; ".join(artifacts[:3])
        if state == "completed":
            post_notification(f"Done: {name}", body, KIND_AGENT_DONE)
        elif state == "warning":
            post_notification(f"Check: {name}", body, KIND_AGENT_WARN)
        elif state == "failed":
            post_notification(f"Failed: {name}", body, KIND_AGENT_FAIL)
        # queued/working/cancelled → no inbox entry
    except Exception:
        logger.exception("agent notify: notify_task_finished failed")


__all__ = ["post_notification", "notify_task_finished",
           "KIND_AGENT_DONE", "KIND_AGENT_WARN", "KIND_AGENT_FAIL"]
