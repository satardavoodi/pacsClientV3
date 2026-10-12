"""GUI-owned card construction, bounded to one card per event-loop turn."""
from copy import deepcopy
import logging
import time
from PySide6.QtCore import QObject, QTimer, Slot, QEvent, Qt
from PySide6.QtWidgets import QLabel

logger = logging.getLogger(__name__)


class CardGridBuild(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.setInterval(1)
        self.timer.timeout.connect(self._next)
        self.generation = 0
        self.entries = []
        self.apply = None
        self.index = 0
        self.started = 0.0
        self.max_apply_ms = 0.0
        self.applied = 0
        self.overlay = None
        self.surface = None
        self.ready = None

    def cancel(self, outcome='cancelled'):
        self.timer.stop()
        if self.overlay is not None:
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None
        if self.surface is not None:
            self.surface.removeEventFilter(self)
            self.surface = None
        self.ready = None
        if self.entries:
            logger.info('[EDU-CARD-GRID] outcome=%s requested=%d applied=%d '
                        'elapsed_ms=%.1f max_apply_ms=%.1f', outcome,
                        len(self.entries), self.applied,
                        (time.perf_counter() - self.started) * 1000, self.max_apply_ms)
        self.generation += 1
        self.entries = []
        self.apply = None

    def start(self, entries, apply, *, surface=None, ready=None):
        self.cancel()
        self.entries = deepcopy(list(entries))
        self.apply = apply
        self.ready = ready
        if surface is not None and self.entries:
            self.surface = surface
            surface.installEventFilter(self)
            self.overlay = QLabel("Loading resources...", surface)
            self.overlay.setAlignment(Qt.AlignCenter)
            self.overlay.setStyleSheet("background: #0d1117; color: #a8b2c0; font-size: 12pt;")
            self.overlay.setGeometry(surface.rect())
            self.overlay.show()
            self.overlay.raise_()
        self.index = 0
        self.applied = 0
        self.max_apply_ms = 0.0
        self.started = time.perf_counter()
        if self.entries:
            self.timer.setInterval(1)
            self.timer.start()

    @Slot()
    def _next(self):
        generation = self.generation
        if self.index >= len(self.entries):
            elapsed = time.perf_counter() - self.started
            if self.overlay is not None and elapsed < 2.0:
                if elapsed < 0.15 or (self.ready is not None and not self.ready()):
                    self.timer.setInterval(16)
                    return
            waiting = self.ready is not None and not self.ready()
            self.cancel('cover_wait_expired' if waiting else 'completed')
            return
        index = self.index
        self.index += 1
        started = time.perf_counter()
        try:
            self.apply(index, self.entries[index])
        except Exception:
            self.cancel('failed')
            raise
        # A callback can synchronously replace the filter or close the page.
        if generation == self.generation:
            self.applied += 1
            self.max_apply_ms = max(self.max_apply_ms, (time.perf_counter() - started) * 1000)
            if self.index >= len(self.entries) and self.overlay is None:
                self.cancel('completed')

    def eventFilter(self, watched, event):
        if watched is self.surface and event.type() == QEvent.Resize and self.overlay is not None:
            self.overlay.setGeometry(watched.rect())
        return super().eventFilter(watched, event)
