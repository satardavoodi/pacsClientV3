"""status_badges — module-icon state dots driven by the task engine.

A small colored dot is overlaid on the left-menu module buttons
(e.g. Web Browser, Education) and follows the agent task lifecycle:

    gray   = idle (no badge shown)
    blue   = working
    green  = completed successfully
    orange = finished with warnings (verify manually)
    red    = failed

Engine listeners fire on WORKER threads — this class re-emits through a
queued Qt signal so all widget work happens on the main thread. Clicking
the module button clears the badge back to idle (the user has "reviewed"
the result). Everything is fail-safe: a missing button or a styling
error can never break a task or the home panel.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtWidgets import QLabel
    _QT = True
except ImportError:  # pragma: no cover — CI without Qt
    QObject = object
    _QT = False

STATE_COLORS = {
    "queued":    "#3b82f6",   # blue — about to work
    "working":   "#3b82f6",   # blue
    "completed": "#22c55e",   # green
    "warning":   "#f59e0b",   # orange
    "failed":    "#ef4444",   # red
    "cancelled": None,        # clear
    "idle":      None,        # clear
}

_BADGE_SIZE = 10


class ModuleStatusBadges(QObject if _QT else object):
    """Maps engine task states to per-module button badges."""

    if _QT:
        _stateSig = Signal(str, str, str)  # module, state, tooltip

    def __init__(self, engine,
                 button_resolver: Callable[[str], Optional[object]]):
        if _QT:
            super().__init__()
            self._stateSig.connect(self._apply_on_ui)
        self._resolver = button_resolver
        self._badges: dict[str, QLabel] = {}
        self._wired_buttons: set[int] = set()
        engine.add_listener(self._on_task_event)

    # ── engine listener (WORKER thread) ───────────────────────────────
    def _on_task_event(self, task, state: str) -> None:
        if not _QT:
            return
        try:
            tooltip = f"Secretary agent — {task.name}: {state}"
            if task.result is not None and task.result.message:
                tooltip += f"\n{task.result.message}"
            self._stateSig.emit(task.module, state, tooltip)
        except Exception:
            logger.exception("status badges: listener failed")

    # ── UI thread ─────────────────────────────────────────────────────
    def _apply_on_ui(self, module: str, state: str, tooltip: str) -> None:
        try:
            button = self._resolver(module)
            if button is None:
                return
            color = STATE_COLORS.get(state)
            if color is None:
                self._clear_badge(module)
                return
            badge = self._badges.get(module)
            if badge is None or badge.parent() is not button:
                badge = QLabel(button)
                badge.setFixedSize(_BADGE_SIZE, _BADGE_SIZE)
                badge.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self._badges[module] = badge
            badge.setStyleSheet(
                f"background-color: {color}; border-radius: "
                f"{_BADGE_SIZE // 2}px; border: 1px solid rgba(0,0,0,90);")
            badge.move(max(0, button.width() - _BADGE_SIZE - 2), 2)
            badge.setToolTip(tooltip)
            badge.show()
            badge.raise_()
            # First time we touch this button: clear the badge when the
            # user clicks it (they are reviewing the result).
            if id(button) not in self._wired_buttons:
                self._wired_buttons.add(id(button))
                try:
                    button.clicked.connect(
                        lambda *_a, m=module: self._clear_badge(m))
                except Exception:
                    pass
        except Exception:
            logger.exception("status badges: apply failed")

    def _clear_badge(self, module: str) -> None:
        badge = self._badges.get(module)
        if badge is not None:
            try:
                badge.hide()
            except Exception:
                pass

    def current_states(self) -> dict[str, str]:
        """Diagnostic helper."""
        return {m: ("shown" if b.isVisible() else "hidden")
                for m, b in self._badges.items()}


__all__ = ["ModuleStatusBadges", "STATE_COLORS"]
