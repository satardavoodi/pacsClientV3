"""Off-GUI-thread work, and the two rules that keep it from killing the process.

═══ THE CRASH THIS PREVENTS ═══

A running ``QThread`` whose last Python reference is dropped is finalised by the
garbage collector while it is still running, and Qt answers that with

    QThread: Destroyed while thread is still running

which is a ``qFatal`` — ``abort()``, no traceback, no faulthandler entry. The
log simply stops. This codebase has paid for that twice already:

  * ``AIChatInteractorStyle._current_worker`` was the ONLY strong reference to a
    running Eagle Eye worker. A second run overwrote it; closing the tab dropped
    it. Either way the interpreter aborted mid-request (OPT-51, 2026-08-03).
  * EchoMind's ``ApiWorker`` was parented to a page on a ``WA_DeleteOnClose``
    window. Closing the window during a transcription deleted a running QThread
    (2026-07-12).

So, two rules, and they are not optional:

  RULE 1 — a running worker ALWAYS has a module-level strong reference.
           ``_LIVE_CHAT_WORKERS`` holds it until ``finished`` fires. Not an
           attribute on a widget, which dies with the widget.

  RULE 2 — teardown DETACHES; it never waits and never lets Qt delete it.
           Disconnect the result signals, ``setParent(None)``, move it to
           ``_ORPHANED_CHAT_WORKERS``, and let it finish into the void. Waiting
           on a socket read with a 15-second timeout freezes the close.

RULE 3, which has no crash attached but has a 3-20 second freeze attached: a
worker touches NO Qt object. It returns plain data; the GUI slot does the
widget work. The chat services are Qt-free precisely so this is easy to obey.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


# RULE 1. Module-level, so it outlives any widget that started the work.
_LIVE_CHAT_WORKERS: set = set()

# RULE 2. A worker that has been detached from a dying UI and is being allowed
# to finish on its own. A list rather than a set: identity is all that matters
# and a list cannot raise on an unhashable subclass.
_ORPHANED_CHAT_WORKERS: list = []


# Failure kinds the UI branches on. Strings rather than exception classes so the
# signal stays trivially queueable across threads.
KIND_AUTH = "auth"            # 401 — the token is dead; re-pair, do not retry
KIND_TRANSPORT = "transport"  # network / server — back off and try again
KIND_CONFIG = "config"        # not paired, or no base URL — a screen, not an error


class ChatWorker(QThread):
    """One blocking call, off the GUI thread.

    Deliberately not a thread pool: these are long-lived-ish network calls with
    their own cadence, and the rest of this codebase uses ``QThread`` + signals
    everywhere. One pattern is worth more than a marginally better one.
    """

    done = Signal(object)
    failed = Signal(str, str)  # (kind, message)

    def __init__(self, fn: Callable[..., Any], *args: Any, parent=None, **kwargs: Any) -> None:
        super().__init__(parent)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:  # pragma: no cover - exercised through start_chat_worker
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:
            self.failed.emit(classify(exc), str(exc))
            return
        self.done.emit(result)


def classify(exc: BaseException) -> str:
    """Which of the three failures this is.

    Imported lazily so this module can be read by a test that has not built a
    client — and so importing the Qt bridge never drags in ``requests``.
    """
    try:
        from modules.aipacs_chat.services.chat_client import (
            ChatAuthError,
            ChatNotConfiguredError,
        )
    except Exception:  # pragma: no cover - import-time only
        return KIND_TRANSPORT

    if isinstance(exc, ChatAuthError):
        return KIND_AUTH
    if isinstance(exc, ChatNotConfiguredError):
        return KIND_CONFIG
    return KIND_TRANSPORT


def start_chat_worker(
    fn: Callable[..., Any],
    *args: Any,
    on_done: Callable[[Any], None] | None = None,
    on_failed: Callable[[str, str], None] | None = None,
    parent=None,
    **kwargs: Any,
) -> ChatWorker:
    """Run ``fn`` off the GUI thread and deliver the result as a signal.

    The caller's slots are connected BEFORE the retirement handler, so the UI
    sees the result while the worker is still alive and registered. Retiring
    first would mean the object could be collected between the two.
    """
    worker = ChatWorker(fn, *args, parent=parent, **kwargs)

    if on_done is not None:
        worker.done.connect(on_done)
    if on_failed is not None:
        worker.failed.connect(on_failed)

    _LIVE_CHAT_WORKERS.add(worker)
    worker.finished.connect(lambda w=worker: retire_chat_worker(w))

    worker.start()
    return worker


def retire_chat_worker(worker: ChatWorker) -> None:
    """Drop the strong reference now that the thread has actually finished."""
    try:
        _LIVE_CHAT_WORKERS.discard(worker)
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        worker.deleteLater()
    except Exception:  # pragma: no cover
        pass


def detach_chat_worker(worker: ChatWorker) -> None:
    """RULE 2. Let a running worker finish alone, with nothing waiting on it.

    Called from the tab's cleanup and from any cancel path. In order:

      1. disconnect the result signals — the widgets they point at are going
         away, and a queued emit into a deleted receiver is a crash of its own;
      2. ``setParent(None)`` — Qt must not delete it along with the page;
      3. keep a Python reference so the garbage collector does not either;
      4. release that reference when the thread genuinely finishes.

    What this deliberately does NOT do is ``wait()``. A request against a
    15-second timeout would freeze the close for 15 seconds, and the operator
    would reasonably conclude the application had hung.
    """
    for signal_name in ("done", "failed", "finished"):
        try:
            getattr(worker, signal_name).disconnect()
        except Exception:
            # Never connected, or already disconnected. Both are fine.
            pass

    try:
        worker.setParent(None)
    except Exception:  # pragma: no cover
        pass

    _ORPHANED_CHAT_WORKERS.append(worker)

    try:
        worker.finished.connect(lambda w=worker: release_orphan_worker(w))
    except Exception:  # pragma: no cover
        release_orphan_worker(worker)

    _LIVE_CHAT_WORKERS.discard(worker)

    if not worker.isRunning():
        # It finished between the caller's check and now, so `finished` will
        # never fire again and nothing else would ever release it.
        release_orphan_worker(worker)


def release_orphan_worker(worker: ChatWorker) -> None:
    try:
        _ORPHANED_CHAT_WORKERS.remove(worker)
    except ValueError:
        pass
    except Exception:  # pragma: no cover
        pass
    try:
        worker.deleteLater()
    except Exception:  # pragma: no cover
        pass


def live_worker_count() -> int:
    """For tests and for the "is anything still in flight" check on close."""
    return len(_LIVE_CHAT_WORKERS)
