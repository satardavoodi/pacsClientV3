"""Secretary background agent layer (2026-06-11).

Turns the voice assistant into a background application agent:

* ``task_engine``   — Qt-free priority worker pool (LOW/MEDIUM only; the
                      clinical HIGH lane — viewer, reporting, PACS — never
                      enters this engine, by design).
* ``ui_bridge``     — safe worker→UI-thread marshaling (queued signal).
* ``verification``  — page-text extraction, screenshots, term checks,
                      pluggable OCR (pytesseract + bundled/PATH tesseract).
* ``agent_tasks``   — concrete workflows (web search verify, open-url
                      verify, website login, education content search).
* ``status_badges`` — module icon state dots (idle/working/done/warn/fail).
* ``notify``        — completion notifications into the account inbox.

Everything degrades gracefully: no engine → synchronous behavior unchanged;
no OCR → text extraction only; no notifications DB → log only.
"""
from .task_engine import (  # noqa: F401
    AgentTask,
    BackgroundTaskEngine,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
    TaskResult,
    TaskState,
    get_task_engine,
)

__all__ = [
    "AgentTask",
    "BackgroundTaskEngine",
    "PRIORITY_LOW",
    "PRIORITY_MEDIUM",
    "TaskResult",
    "TaskState",
    "get_task_engine",
]
