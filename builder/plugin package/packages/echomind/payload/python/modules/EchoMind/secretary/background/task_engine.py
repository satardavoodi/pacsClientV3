"""BackgroundTaskEngine — Qt-free priority worker pool for agent tasks.

Performance / isolation contract (the reason this file exists):

* Tasks run on at most ``max_workers`` (default 2) daemon threads —
  they can NEVER block the UI thread, viewer rendering, downloads, or
  PACS sockets.
* Only LOW and MEDIUM priorities exist here. Clinical work (viewer
  interaction, reporting, PACS operations) is intentionally NOT
  expressible as an engine task — it stays on its existing paths.
* Cooperative cancellation (``task.request_cancel()``); a cancelled task
  observes ``task.is_cancelled()`` between steps and bails out.
* Listeners are invoked on the WORKER thread — Qt consumers must
  marshal (see ``status_badges.ModuleStatusBadges`` / ``ui_bridge``).
* The engine never raises into callers; task exceptions become FAILED
  results with the exception text.

States: queued → working → completed | warning | failed | cancelled.
"""
from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

PRIORITY_MEDIUM = 1   # consultation lookups etc.
PRIORITY_LOW = 2      # browser / education searches, long analysis


class TaskState:
    QUEUED = "queued"
    WORKING = "working"
    COMPLETED = "completed"
    WARNING = "warning"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    ok: bool
    message: str = ""
    data: Optional[dict] = None
    artifacts: list[str] = field(default_factory=list)
    warning: bool = False


@dataclass
class AgentTask:
    task_id: str
    name: str                      # human label ("Google search: …")
    module: str                    # "web_browser" | "education" | …
    fn: Callable[["AgentTask"], TaskResult]
    priority: int = PRIORITY_LOW
    state: str = TaskState.QUEUED
    result: Optional[TaskResult] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    _cancel_event: threading.Event = field(default_factory=threading.Event)

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()


# Listener signature: (task: AgentTask, state: str) — worker thread!
TaskListener = Callable[[AgentTask, str], None]


class BackgroundTaskEngine:
    """Small, bounded, cancellable background worker pool."""

    def __init__(self, max_workers: int = 2):
        self._queue: "queue.PriorityQueue" = queue.PriorityQueue()
        self._tasks: dict[str, AgentTask] = {}
        self._listeners: list[TaskListener] = []
        self._lock = threading.Lock()
        self._seq = itertools.count()
        self._shutdown = False
        self._workers: list[threading.Thread] = []
        self._max_workers = max(1, int(max_workers))

    # ── listeners ─────────────────────────────────────────────────────
    def add_listener(self, listener: TaskListener) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: TaskListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _emit(self, task: AgentTask, state: str) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(task, state)
            except Exception:
                logger.exception("task engine: listener raised (ignored)")

    # ── submit / cancel / inspect ─────────────────────────────────────
    def submit(self, name: str, module: str,
               fn: Callable[[AgentTask], TaskResult],
               priority: int = PRIORITY_LOW) -> str:
        if priority not in (PRIORITY_MEDIUM, PRIORITY_LOW):
            priority = PRIORITY_LOW  # clinical priorities don't exist here
        with self._lock:
            n = next(self._seq)
            task_id = f"agent-{int(time.time())}-{n}"
            task = AgentTask(task_id=task_id, name=name, module=module,
                             fn=fn, priority=priority)
            self._tasks[task_id] = task
        self._ensure_workers()
        self._queue.put((priority, n, task_id))
        logger.info("task engine: queued %s [%s] prio=%d name=%r",
                    task_id, module, priority, name)
        self._emit(task, TaskState.QUEUED)
        return task_id

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return False
        task.request_cancel()
        if task.state == TaskState.QUEUED:
            task.state = TaskState.CANCELLED
            task.finished_at = time.time()
            self._emit(task, TaskState.CANCELLED)
        return True

    def get(self, task_id: str) -> Optional[AgentTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> list[AgentTask]:
        with self._lock:
            tasks = sorted(self._tasks.values(),
                           key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    def wait(self, task_id: str, timeout: float = 30.0) -> Optional[AgentTask]:
        """Test helper — poll until the task leaves queued/working."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = self.get(task_id)
            if task is not None and task.state not in (
                    TaskState.QUEUED, TaskState.WORKING):
                return task
            time.sleep(0.02)
        return self.get(task_id)

    def shutdown(self) -> None:
        self._shutdown = True
        for _ in self._workers:
            self._queue.put((0, -1, None))  # wake workers

    # ── workers ───────────────────────────────────────────────────────
    def _ensure_workers(self) -> None:
        with self._lock:
            alive = [w for w in self._workers if w.is_alive()]
            self._workers = alive
            while len(self._workers) < self._max_workers:
                w = threading.Thread(
                    target=self._worker_loop,
                    name=f"AgentTaskWorker-{len(self._workers)}",
                    daemon=True,
                )
                self._workers.append(w)
                w.start()

    def _worker_loop(self) -> None:
        while not self._shutdown:
            try:
                _prio, _n, task_id = self._queue.get(timeout=5.0)
            except queue.Empty:
                continue
            if task_id is None:  # shutdown sentinel
                return
            task = self.get(task_id)
            if task is None or task.state == TaskState.CANCELLED:
                continue
            self._run_task(task)

    def _run_task(self, task: AgentTask) -> None:
        task.state = TaskState.WORKING
        task.started_at = time.time()
        self._emit(task, TaskState.WORKING)
        try:
            if task.is_cancelled():
                raise _Cancelled()
            result = task.fn(task)
            if not isinstance(result, TaskResult):
                result = TaskResult(ok=bool(result),
                                    message=str(result) if result else "")
        except _Cancelled:
            task.state = TaskState.CANCELLED
            task.result = TaskResult(ok=False, message="Cancelled")
            task.finished_at = time.time()
            self._emit(task, TaskState.CANCELLED)
            return
        except Exception as exc:
            logger.exception("task engine: task %s crashed", task.task_id)
            task.result = TaskResult(ok=False, message=f"Task failed: {exc}")
            task.state = TaskState.FAILED
            task.finished_at = time.time()
            self._emit(task, TaskState.FAILED)
            return
        task.result = result
        if task.is_cancelled():
            task.state = TaskState.CANCELLED
        elif result.ok and result.warning:
            task.state = TaskState.WARNING
        elif result.ok:
            task.state = TaskState.COMPLETED
        else:
            task.state = TaskState.FAILED
        task.finished_at = time.time()
        elapsed = (task.finished_at - (task.started_at or task.finished_at))
        logger.info("task engine: %s [%s] -> %s in %.1fs (%s)",
                    task.task_id, task.module, task.state, elapsed,
                    (result.message or "")[:120])
        self._emit(task, task.state)


class _Cancelled(Exception):
    pass


# ── process-wide singleton ───────────────────────────────────────────────
_engine: Optional[BackgroundTaskEngine] = None
_engine_lock = threading.Lock()


def get_task_engine() -> BackgroundTaskEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = BackgroundTaskEngine(max_workers=2)
        return _engine


__all__ = [
    "AgentTask", "BackgroundTaskEngine", "TaskResult", "TaskState",
    "PRIORITY_LOW", "PRIORITY_MEDIUM", "get_task_engine",
]
