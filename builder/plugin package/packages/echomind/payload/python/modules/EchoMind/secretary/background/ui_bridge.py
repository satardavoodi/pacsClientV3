"""ui_bridge — safe worker-thread → Qt-main-thread call marshaling.

Agent tasks run on plain daemon threads (task_engine). Any step that
touches a widget (open the browser tab, read ``_is_loading``, grab a
screenshot) must execute on the Qt main thread. The standard safe
pattern is a queued signal emitted from the worker:

    ok, value = run_on_ui(lambda: widget.search_web("q"), timeout=10.0)

Rules enforced here:

* ``init_ui_bridge()`` MUST be called once from the main thread (the
  home-panel wiring site does this). Before that — or in Qt-less test
  runs — ``run_on_ui`` executes the callable inline.
* A bounded ``timeout`` so a hung UI can never deadlock a worker.
* Exceptions inside the callable are captured and returned, never
  propagated into the Qt event loop.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional, Tuple

logger = logging.getLogger(__name__)

_invoker = None          # _UiInvoker living on the main thread
_main_thread_id: Optional[int] = None


def init_ui_bridge() -> bool:
    """Create the queued-signal invoker. Call once, on the main thread."""
    global _invoker, _main_thread_id
    if _invoker is not None:
        return True
    try:
        from PySide6.QtCore import QObject, Signal

        class _UiInvoker(QObject):
            trigger = Signal(object)

            def __init__(self):
                super().__init__()
                # Auto connection: cross-thread emits become queued.
                self.trigger.connect(self._run)

            @staticmethod
            def _run(fn):
                try:
                    fn()
                except Exception:
                    logger.exception("ui_bridge: marshaled callable raised")

        _invoker = _UiInvoker()
        _main_thread_id = threading.get_ident()
        return True
    except Exception:
        logger.exception("ui_bridge: init failed (Qt unavailable?)")
        return False


def run_on_ui(fn: Callable[[], Any],
              timeout: float = 10.0) -> Tuple[bool, Any]:
    """Run *fn* on the Qt main thread; wait up to *timeout* seconds.

    Returns ``(ok, value)``. ``ok`` is False on timeout or when *fn*
    raised (value then holds the exception). Inline execution when the
    bridge isn't initialised (tests) or when already on the main thread.
    """
    if _invoker is None or threading.get_ident() == _main_thread_id:
        try:
            return True, fn()
        except Exception as exc:  # noqa: BLE001
            logger.exception("ui_bridge: inline callable raised")
            return False, exc

    done = threading.Event()
    box: dict[str, Any] = {}

    def _wrapper():
        try:
            box["value"] = fn()
            box["ok"] = True
        except Exception as exc:  # noqa: BLE001
            box["value"] = exc
            box["ok"] = False
        finally:
            done.set()

    try:
        _invoker.trigger.emit(_wrapper)
    except Exception as exc:  # noqa: BLE001
        return False, exc
    if not done.wait(timeout):
        logger.warning("ui_bridge: UI call timed out after %.1fs", timeout)
        return False, TimeoutError(f"UI call timed out ({timeout}s)")
    return bool(box.get("ok")), box.get("value")


def _reset_for_tests() -> None:
    global _invoker, _main_thread_id
    _invoker = None
    _main_thread_id = None


__all__ = ["init_ui_bridge", "run_on_ui"]
