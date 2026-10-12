"""Background execution for the desktop UI.

Every CRM call is a blocking network round-trip. Running them on the Qt event
loop would freeze the window, so all work goes through a thread pool and comes
back as a signal.
"""

from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ..core.dispatcher import dispatch
from ..core.types import DispatchContext, Principal, ToolCall
from ..settings import ConnectionProfile


class TaskSignals(QObject):
    finished = Signal(object)          # payload on success
    failed = Signal(str, str)          # (message, traceback)
    done = Signal()                    # always fires, success or failure


class Task(QRunnable):
    """Run one callable off the UI thread."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            self.signals.failed.emit(str(exc) or exc.__class__.__name__, traceback.format_exc())
        else:
            self.signals.finished.emit(result)
        finally:
            self.signals.done.emit()


class TaskRunner:
    """Thin wrapper so pages don't each manage a pool."""

    def __init__(self) -> None:
        self.pool = QThreadPool.globalInstance()

    def run(
        self,
        fn: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[str, str], None],
        on_done: Callable[[], None] | None = None,
    ) -> None:
        task = Task(fn)
        task.signals.finished.connect(on_success)
        task.signals.failed.connect(on_error)
        if on_done is not None:
            task.signals.done.connect(on_done)
        self.pool.start(task)


def apply_profile_env(profile: ConnectionProfile, password: str | None = None) -> None:
    """Export the active profile into the environment.

    The live report tools build their client with ``InoClient.from_env()``, so
    the UI's connection settings only take effect once they are in os.environ.
    """
    resolved = profile.resolved_password(password)
    os.environ["INO_HOST"] = profile.normalized_host
    os.environ["INO_CRM_PORT"] = str(profile.crm_port)
    os.environ["INO_DASHBOARD_PORT"] = str(profile.dashboard_port)
    os.environ["INO_PACS_PORT"] = str(profile.pacs_port)
    os.environ["INO_SOCKET_PORT"] = str(profile.socket_port)
    os.environ["RECEPTION_CRM_DATA_ROOT"] = profile.data_root
    if profile.username:
        os.environ["INO_USER"] = profile.username
    if resolved:
        os.environ["INO_PASS"] = resolved


def run_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    user: str,
    center: str,
    data_root: str | Path,
) -> Any:
    """Dispatch one registry tool and unwrap it.

    Goes through the same guard chain as the CLI and MCP server — the UI gets no
    private back door. Permission and validation failures raise, and the page
    shows the reason.
    """
    root = Path(data_root)
    payload = {key: value for key, value in arguments.items() if value not in (None, "")}
    payload.setdefault("data_root", str(root))

    result = dispatch(
        ToolCall(name, payload),
        context=DispatchContext(
            principal=Principal(user=user, center=center, roles=[]),
            client="desktop",
            data_root=root,
        ),
    )
    return result.unwrap()
