"""Marshal a CommandBus call from a background thread onto the Qt GUI thread.

The HTTP server and the relay client both run on background threads (so network
I/O never blocks the GUI). But CommandBus adapters touch live Qt widgets and MUST
run on the GUI thread. :class:`GuiCommandDispatcher` bridges the two:

* It lives on the GUI thread (created there by the service).
* ``run_command(...)`` is called from a background thread; it enqueues a job,
  posts ``_drain`` to itself via ``QMetaObject.invokeMethod(..., QueuedConnection)``
  (the thread-safe way to hop threads in Qt), and blocks on a
  ``threading.Event`` with a timeout.
* ``_drain`` runs on the GUI thread, executes ``bus.execute`` (same production
  path + permission gate as the voice assistant and the test server), and sets
  the result.

This is the same "one command per event-loop turn, never block the loop
wholesale" pattern the Test Control Server uses (``test_server.py``), adapted for
a cross-thread caller. The background caller blocks (with a timeout); the GUI
thread never does.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 30.0


class _Job:
    __slots__ = ("action", "entities", "agent_mode", "confirmed", "event", "result")

    def __init__(self, action, entities, agent_mode, confirmed):
        self.action = action
        self.entities = entities
        self.agent_mode = agent_mode
        self.confirmed = confirmed
        self.event = threading.Event()
        self.result: Optional[Dict[str, Any]] = None


def _make_dispatcher_class():
    """Build the QObject subclass lazily so importing this module never needs Qt."""
    from PySide6.QtCore import QObject, Qt, QMetaObject, Slot

    class _GuiCommandDispatcher(QObject):
        def __init__(self, get_bus: Callable[[], Any], parent=None) -> None:
            super().__init__(parent)
            self._get_bus = get_bus
            self._queue: "deque[_Job]" = deque()
            self._lock = threading.Lock()

        # Called from ANY thread.
        def run_command(
            self,
            action: str,
            entities: Dict[str, Any],
            agent_mode: str,
            confirmed: bool = False,
            timeout: float = _DEFAULT_TIMEOUT_S,
        ) -> Dict[str, Any]:
            job = _Job(action, dict(entities or {}), agent_mode, bool(confirmed))

            # If we're already on the GUI thread, run inline (no deadlock).
            from PySide6.QtCore import QThread

            if QThread.currentThread() is self.thread():
                self._execute_job(job)
                return job.result or {"ok": False, "action": action,
                                      "error_code": "NO_RESULT"}

            with self._lock:
                self._queue.append(job)
            QMetaObject.invokeMethod(self, "_drain", Qt.QueuedConnection)

            if not job.event.wait(timeout=max(1.0, float(timeout))):
                return {
                    "ok": False,
                    "action": action,
                    "error_code": "GUI_TIMEOUT",
                    "message": f"command '{action}' timed out after {timeout}s",
                }
            return job.result or {"ok": False, "action": action,
                                  "error_code": "NO_RESULT"}

        @Slot()
        def _drain(self) -> None:
            # Runs on the GUI thread. Drain everything queued so far.
            while True:
                with self._lock:
                    if not self._queue:
                        return
                    job = self._queue.popleft()
                self._execute_job(job)

        def _execute_job(self, job: "_Job") -> None:
            try:
                job.result = self._invoke_bus(job)
            except Exception as exc:  # noqa: BLE001
                logger.exception("[AGENT_GATEWAY] command execution crashed")
                job.result = {
                    "ok": False,
                    "action": job.action,
                    "error_code": "EXECUTION_ERROR",
                    "message": str(exc),
                }
            finally:
                job.event.set()

        def _invoke_bus(self, job: "_Job") -> Dict[str, Any]:
            bus = None
            try:
                bus = self._get_bus()
            except Exception:
                bus = None
            if bus is None:
                return {
                    "ok": False,
                    "action": job.action,
                    "error_code": "NO_BUS",
                    "message": "command_bus not available",
                }
            from modules.EchoMind.secretary.command_envelope import CommandPlan

            plan = CommandPlan(action=job.action, entities=dict(job.entities or {}))
            result = bus.execute(
                plan, {"agent_mode": job.agent_mode, "confirmed": job.confirmed}
            )
            if hasattr(result, "model_dump"):
                return result.model_dump()
            if isinstance(result, dict):
                return result
            return {"ok": True, "action": job.action, "data": result}

    return _GuiCommandDispatcher


_DISPATCHER_CLS = None


def make_gui_dispatcher(get_bus: Callable[[], Any], parent=None):
    """Create a GUI-thread command dispatcher (must be called on the GUI thread)."""
    global _DISPATCHER_CLS
    if _DISPATCHER_CLS is None:
        _DISPATCHER_CLS = _make_dispatcher_class()
    return _DISPATCHER_CLS(get_bus, parent)


__all__ = ["make_gui_dispatcher"]
