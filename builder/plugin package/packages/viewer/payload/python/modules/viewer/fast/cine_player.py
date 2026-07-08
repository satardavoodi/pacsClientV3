"""Pure (Qt-free) cine playback state machine.

The viewer owns a QTimer and, on each tick, calls :meth:`CinePlayer.advance` to
get the next frame index to display; on manual navigation it calls
:meth:`CinePlayer.sync_index` so play resumes from where the user left off. Keeping
the state machine free of Qt makes the play/pause/loop/step/speed logic fully
unit-testable headless. The player never touches pixels or the GUI — it only
computes indices and the timer interval.
"""
from __future__ import annotations

from typing import Optional

try:  # normal package import
    from .cine_metadata import clamp_fps, DEFAULT_CINE_FPS
except ImportError:  # pragma: no cover - standalone/headless import (tests)
    from cine_metadata import clamp_fps, DEFAULT_CINE_FPS


class CinePlayer:
    def __init__(self, fps: Optional[float] = None, loop: bool = True):
        self._count: int = 0
        self._index: int = 0
        self._fps: float = clamp_fps(fps) or DEFAULT_CINE_FPS
        self._playing: bool = False
        self._loop: bool = bool(loop)

    # ── configuration ────────────────────────────────────────────────
    def set_count(self, count: int) -> None:
        """Set the number of frames. Clamps the current index into range and
        stops playback when there is nothing to play (<= 1 frame)."""
        try:
            n = int(count)
        except (TypeError, ValueError):
            n = 0
        self._count = max(0, n)
        if self._count <= 1:
            self._playing = False
        if self._count <= 0:
            self._index = 0
        else:
            self._index = max(0, min(self._index, self._count - 1))

    def sync_index(self, index: int) -> None:
        """Adopt an externally-driven current frame (manual scroll/slider), so a
        subsequent play continues from there. Does not change playing state."""
        try:
            i = int(index)
        except (TypeError, ValueError):
            return
        if self._count > 0:
            self._index = max(0, min(i, self._count - 1))
        else:
            self._index = max(0, i)

    def set_fps(self, fps: Optional[float]) -> None:
        f = clamp_fps(fps)
        if f is not None:
            self._fps = f

    def set_loop(self, loop: bool) -> None:
        self._loop = bool(loop)

    # ── playback control ─────────────────────────────────────────────
    def can_play(self) -> bool:
        return self._count > 1

    def play(self) -> bool:
        """Start playback if there is more than one frame. If already at the last
        frame in non-loop mode, restart from 0. Returns the resulting playing state."""
        if not self.can_play():
            self._playing = False
            return False
        if not self._loop and self._index >= self._count - 1:
            self._index = 0
        self._playing = True
        return True

    def pause(self) -> None:
        self._playing = False

    def stop(self) -> None:
        """Pause and rewind to the first frame."""
        self._playing = False
        self._index = 0

    def toggle(self) -> bool:
        if self._playing:
            self.pause()
        else:
            self.play()
        return self._playing

    # ── stepping ─────────────────────────────────────────────────────
    def advance(self) -> Optional[int]:
        """Timer tick: return the NEXT frame index to display and adopt it, or
        None when playback should not advance (paused / single frame). At the end
        it wraps to 0 when looping, else pauses on the last frame."""
        if not self._playing or self._count <= 1:
            return None
        nxt = self._index + 1
        if nxt >= self._count:
            if self._loop:
                nxt = 0
            else:
                self._playing = False
                return None
        self._index = nxt
        return nxt

    def step(self, delta: int = 1) -> Optional[int]:
        """Manual single-frame step (does not start playback). Returns the new
        index (wrapping when looping), or None when there is nothing to step."""
        if self._count <= 1:
            return None
        nxt = self._index + int(delta)
        if self._loop:
            nxt %= self._count
        else:
            nxt = max(0, min(nxt, self._count - 1))
        self._index = nxt
        return nxt

    # ── read-only state ──────────────────────────────────────────────
    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def loop(self) -> bool:
        return self._loop

    @property
    def index(self) -> int:
        return self._index

    @property
    def count(self) -> int:
        return self._count

    @property
    def interval_ms(self) -> int:
        """Timer interval for the current fps (>= 1 ms)."""
        return max(1, int(round(1000.0 / self._fps)))
