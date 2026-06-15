"""GUI-thread guard for external-network operations (Google OAuth / Drive).

Why this exists: on 2026-06-07 the consultation poller ran a Google OAuth token
refresh + a Drive API round-trip on the Qt GUI thread; with slow connectivity the
main thread froze for 3–20 s per poll (MAIN_THREAD_STALL_TRACE evidence). The app
must never *depend* on reaching Google: if the internet is down these calls hang
until their socket timeout, so they are only ever allowed on worker threads.

``assert_off_gui_thread(op)`` raises ``RuntimeError`` immediately (instead of
letting the app freeze) when a guarded operation is entered on the GUI thread.

Escape hatches:
* ``AIPACS_ALLOW_MAINTHREAD_GOOGLE=1`` — emergency kill-switch (logs a warning).
* Under pytest the guard is inert unless ``AIPACS_FORCE_GUI_GUARD=1`` (tests run
  everything on the main thread by design).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def assert_off_gui_thread(operation: str) -> None:
    """Raise RuntimeError if called on the Qt GUI thread.

    No-op when Qt is absent, no QApplication exists (headless tools), under
    pytest (unless forced), or when the emergency override is set.
    """
    if os.environ.get("AIPACS_ALLOW_MAINTHREAD_GOOGLE") == "1":
        logger.warning("GUI-thread guard bypassed by AIPACS_ALLOW_MAINTHREAD_GOOGLE for %s", operation)
        return
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("AIPACS_FORCE_GUI_GUARD") != "1":
        return
    try:
        from PySide6.QtCore import QCoreApplication, QThread
    except Exception:  # Qt not available — nothing to protect
        return
    app = QCoreApplication.instance()
    if app is None:
        return
    if QThread.currentThread() is app.thread():
        msg = (
            f"BLOCKED: '{operation}' was attempted on the GUI thread. "
            "Google/OAuth/Drive network calls can stall for seconds (or hang while "
            "offline) and must run in a worker thread (QThread / _ScanThread). "
            "See consultation-poller stall 2026-06-07. "
            "Emergency override: AIPACS_ALLOW_MAINTHREAD_GOOGLE=1."
        )
        logger.error(msg)
        raise RuntimeError(msg)
