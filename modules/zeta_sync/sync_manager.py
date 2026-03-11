from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple, Callable

from .sync_context import SyncContext
from .sync_types import SyncMode

logger = logging.getLogger(__name__)


class SyncManager:
    """
    Central coordinator for synchronization between viewers.

    This class is intentionally decoupled from viewer implementations.
    Integrations should provide adapter callbacks to:
      - emit source cursor/slice updates
      - apply cursor/slice updates to a target viewer
    """

    def __init__(self):
        self._contexts: Dict[str, SyncContext] = {}
        self._mode: SyncMode = SyncMode.DISABLED
        self._is_updating = False
        self._active_point: Optional[Tuple[float, float, float]] = None

        # Adapter callbacks (set by integrations)
        self._apply_cursor: Optional[Callable[[str, Tuple[float, float, float]], None]] = None
        self._map_cursor: Optional[
            Callable[[str, str, Tuple[float, float, float]], Optional[Tuple[float, float, float]]]
        ] = None
        self._apply_slice: Optional[Callable[[str, int], None]] = None

    def set_mode(self, mode: SyncMode) -> None:
        self._mode = mode
        logger.debug("Sync mode set to %s", mode.value)

    def get_mode(self) -> SyncMode:
        return self._mode

    def register_viewer(self, context: SyncContext) -> None:
        self._contexts[context.viewer_id] = context
        logger.debug("Registered sync context: %s", context)

    def clear_viewers(self) -> None:
        self._contexts.clear()
        logger.debug("Cleared all sync contexts")

    def unregister_viewer(self, viewer_id: str) -> None:
        if viewer_id in self._contexts:
            del self._contexts[viewer_id]
            logger.debug("Unregistered sync context: %s", viewer_id)

    def set_apply_cursor_callback(
        self,
        callback: Callable[[str, Tuple[float, float, float]], None]
    ) -> None:
        self._apply_cursor = callback

    def set_map_cursor_callback(
        self,
        callback: Callable[[str, str, Tuple[float, float, float]], Optional[Tuple[float, float, float]]]
    ) -> None:
        self._map_cursor = callback

    def set_apply_slice_callback(
        self,
        callback: Callable[[str, int], None]
    ) -> None:
        self._apply_slice = callback

    def set_active_point(self, world_pos: Tuple[float, float, float]) -> None:
        self._active_point = world_pos

    def get_active_point(self) -> Optional[Tuple[float, float, float]]:
        return self._active_point

    def notify_cursor_moved(
        self,
        source_viewer_id: str,
        world_pos: Tuple[float, float, float]
    ) -> None:
        if self._mode in (SyncMode.DISABLED, SyncMode.SLICE):
            return
        if self._is_updating:
            return

        self._is_updating = True
        try:
            if self._apply_cursor is None:
                return

            for viewer_id in self._contexts.keys():
                if viewer_id == source_viewer_id:
                    continue
                mapped_world = world_pos
                if self._map_cursor is not None:
                    mapped_world = self._map_cursor(source_viewer_id, viewer_id, world_pos)
                if mapped_world is None:
                    continue
                self._apply_cursor(viewer_id, mapped_world)
        finally:
            self._is_updating = False

    def notify_slice_changed(self, source_viewer_id: str, slice_index: int) -> None:
        if self._mode in (SyncMode.DISABLED, SyncMode.CURSOR):
            return
        if self._is_updating:
            return

        self._is_updating = True
        try:
            if self._apply_slice is None:
                return

            for viewer_id in self._contexts.keys():
                if viewer_id == source_viewer_id:
                    continue
                self._apply_slice(viewer_id, slice_index)
        finally:
            self._is_updating = False
