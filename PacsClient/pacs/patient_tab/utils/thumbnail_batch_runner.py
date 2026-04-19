from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import QTimer


class ThumbnailBatchRunner:
    """Small reusable Qt batch scheduler for thumbnail sidebar work.

    Owns timer cadence, current index, and batch iteration so the panel can stay
    focused on per-item processing and layout hosting.
    """

    def __init__(self, parent, *, interval_ms: int, batch_size: int):
        self._timer = QTimer(parent)
        self._timer.timeout.connect(self._tick)
        self._interval_ms = int(interval_ms)
        self._batch_size = max(1, int(batch_size))
        self._items: list = []
        self._index = 0
        self._on_item: Callable[[int, object], None] | None = None
        self._on_progress: Callable[[int, int], None] | None = None
        self._on_finished: Callable[[int], None] | None = None
        self._on_error: Callable[[Exception], None] | None = None

    @property
    def timer(self) -> QTimer:
        return self._timer

    @property
    def current_index(self) -> int:
        return int(self._index)

    def start(
        self,
        items: Iterable,
        *,
        on_item: Callable[[int, object], None],
        on_progress: Callable[[int, int], None] | None = None,
        on_finished: Callable[[int], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self.stop()
        self._items = list(items or [])
        self._index = 0
        self._on_item = on_item
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._on_error = on_error

        total = len(self._items)
        if self._on_progress is not None:
            self._on_progress(0, total)
        if total <= 0:
            if self._on_finished is not None:
                self._on_finished(0)
            return
        self._timer.start(self._interval_ms)

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def _tick(self) -> None:
        total = len(self._items)
        if total <= 0 or self._on_item is None:
            self.stop()
            return

        start_idx = self._index
        end_idx = min(start_idx + self._batch_size, total)
        try:
            for idx in range(start_idx, end_idx):
                self._on_item(idx, self._items[idx])
        except Exception as exc:
            self.stop()
            if self._on_error is not None:
                self._on_error(exc)
            return

        self._index = end_idx
        if self._on_progress is not None:
            self._on_progress(self._index, total)

        if self._index >= total:
            self.stop()
            if self._on_finished is not None:
                self._on_finished(total)